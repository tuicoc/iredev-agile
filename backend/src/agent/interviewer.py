"""
interviewer.py - InterviewerAgent

InterviewerAgent executes the reviewed agenda one item at a time. The model
decides the next conversational move; Python only records the chosen action,
updates runtime data, and writes the interview artifact.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .agenda import AgendaRuntime, AgendaRuntimeItem, TRAP_DRILL_STYLE
from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


class ELRecord(BaseModel):
    id: str = Field(description="Stable interview record id in EL-NNN format.")
    item: str = Field(description="Agenda item id that produced this record.")
    entity: str = Field(description="Entity discussed in this exchange.")
    step: str = Field(description="Entity step discussed in this exchange.")
    aspect: str = Field(description="Agenda aspect discussed in this exchange.")
    trap: str = Field(description="Interview trap used for this exchange.")
    kind: str = Field(description="Agenda item kind: need, conflict, or concern.")
    role: str = Field(description="Stakeholder role interviewed.")
    close: str = Field(description="Completion rule the interviewer was trying to settle.")
    source: str = Field(description="Agenda source id behind this interview record.")
    risk: Optional[str] = Field(
        default=None,
        description=(
            "Failure or tension scenario the interview item was designed to resolve "
            "or bound."
        ),
    )
    concern_ref: Optional[str] = Field(
        default=None,
        description="NFR concern id when this record came from a concern agenda item.",
    )
    concern_category: Optional[str] = Field(
        default=None,
        description="NFR concern category when this record came from a concern agenda item.",
    )
    concern_theme: Optional[str] = Field(
        default=None,
        description="NFR concern theme when this record came from a concern agenda item.",
    )
    rule: Optional[str] = Field(
        default=None,
        description=(
            "Final closure statement captured from the stakeholder when one was "
            "settled. The grammatical subject is the PRODUCT, not the user: the "
            "stakeholder describes their experience; this field records what the "
            "app must therefore do.\n"
            "\n"
            "- For need / conflict items, write it as 'The app must <verb> ...', "
            "'The system must require ...', 'The product must allow ...', or an "
            "equivalent system-subject form. Avoid 'Users must provide / agree / "
            "be aware / have / receive ...' — those are user obligations and "
            "almost always represent a system obligation in disguise.\n"
            "- For concern items, the rule names what observable quality the "
            "product must hold: a threshold with units, a named comparator, an "
            "observable absence ('no spinner visible'), an operating condition "
            "('before the user shifts attention'), or a named precedent. "
            "Emotional descriptors alone ('instantly', 'immediately', "
            "'responsive', 'fast', 'smooth') are not acceptable as the rule.\n"
            "- Narrow exception: a workflow obligation that exists outside the "
            "app (an external auditor sign-off the system only records) or a "
            "legal acceptance whose force is external. In ordinary product "
            "feature elicitation, default to system subject.\n"
            "- This field is a closure summary, not a container for every "
            "independent fact from the dialogue. Atomic facts go into signals."
        )
    )
    align: Optional[Literal["exact", "narrower", "broader", "misaligned"]] = Field(
        default=None,
        description="How well the final answer matched the close rule."
    )
    talk: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Question and answer turns captured for this agenda item."
    )
    signals: List[str] = Field(
        default_factory=list,
        description=(
            "Atomic evidence units captured from the stakeholder's reply. Each "
            "item should carry ONE independent fact the stakeholder stated: a "
            "condition, limit, exception, permission, dependency, threshold, "
            "precedence, observed failure, or observable quality boundary.\n"
            "\n"
            "Signals are the main raw material Distiller uses to split one "
            "interview record into multiple atomic requirements. Keep them "
            "atomic — do not join independent facts with 'and'.\n"
            "\n"
            "Signals may preserve the stakeholder's own phrasing of their "
            "experience (their lived statement is what it is), but each signal "
            "must be readable as evidence that justifies a PRODUCT-side rule. "
            "Avoid signals that read only as user-side duty ('users must "
            "provide X', 'users have to agree to Y') with no system-side "
            "consequence; rewrite to expose what the app does or fails to do "
            "('the app rejects sign-up when email is missing', 'the app must "
            "present terms before account creation'). A signal that gives "
            "Distiller no system-side hook is wasted evidence."
        )
    )
    question: Optional[str] = Field(
        default=None,
        description="Last interviewer message delivered on this item."
    )
    answer: Optional[str] = Field(
        default=None,
        description="Rendered answer block used for human review."
    )
    status: Optional[Literal["answered", "skipped"]] = Field(
        default=None,
        description="Final interview status for this agenda item."
    )


_REACT_ADDENDUM = """\
TURN CONTROL
- Always inspect TURN STATUS first.
- If "Pending answer: yes", call record_answer.
- If "Pending answer: no" and agenda remains open, call ask_question.
- Call conclude ONLY when the task explicitly says: "AGENDA STATUS: COMPLETE".
- If the task shows a CURRENT ITEM or says "AGENDA STATUS: OPEN", conclude is forbidden.
- One tool call per turn.
- The agenda is a queue of items. Closing one item does not complete the
  interview. After an item closes, the next turn must work on the next CURRENT
  ITEM until the task itself says AGENDA STATUS: COMPLETE.
- If a tool observation says an item remains open, ask a follow-up on that same
  item. Do not conclude.

SUBJECT FRAMING (apply on every record_answer and every ask_question)
The persona's SUBJECT FRAMING DISCIPLINE governs all your wording. In short:
the user is the SOURCE of evidence; the product is the SUBJECT of every rule
and every question.
- When you record a rule, the subject is the product: "The app must
  require ...", "The system must allow ...", "The product must present ...".
  Do NOT record rules as user obligations ("Users must provide ...", "The
  user must agree to ...", "Users must be aware that ..."); those are the
  user's experience phrased the wrong way round and they will mislead
  Distiller into writing user-duty requirements.
- When you ask a question, frame it around what the PRODUCT must do for
  the user, not what the user must do. "What does the app need to enforce
  when X happens?", "What does the app need to show you at X?", "What
  does the app fail to do today at X?" — not "What must you do when X?".
- Three temptation patterns the stakeholder will hand you in user-subject
  form; you record them in product-subject form:
    user says "to sign up I have to enter my email and password"
      => rule "The app must require email and password at sign-up"
    user says "I have to agree to terms first"
      => rule "The app must present the terms and require acceptance
              before account creation"
    user says "I need to know that delete is permanent"
      => rule "The app must warn the user that delete is permanent
              before confirming"

WHEN CALLING record_answer
1. Read the pending stakeholder answer and the full local dialogue.
2. Classify align:
   - exact: answer settles close and directly addresses the gap plus risk.
   - narrower: answer settles close for a narrower condition that still
     addresses the gap plus risk.
   - broader: answer addresses the topic but leaves the decisive rule incomplete.
   - misaligned: answer does not address the agenda item.
3. done=true only when the close rule is now explicit enough that Distiller can
   use it without guessing and the risk is resolved, bounded, or explicitly
   left as accepted ambiguity per ACCEPT-AMBIGUITY CLOSE below.
4. Alignment and done must be internally consistent:
   - exact or narrower -> done may be true only if rule is concrete and
     system-subject.
   - broader or misaligned -> done must be false and rule must be empty.
5. rule is the shortest settled closure statement, written with the PRODUCT
   as the subject (see SUBJECT FRAMING). It is not the only source for
   Distiller and should not hide multiple independent facts in one blob.
   Leave it empty when done=false.
6. signals capture only concrete stakeholder evidence stated in this exchange.
   signals carry the independent facts Distiller will split.
   Split independent conditions, limits, permissions, dependencies, exceptions,
   thresholds, quality boundaries, and precedence facts into separate signal
   strings. Do not merge them with "and" when they could become separate
   requirements or acceptance criteria. Each signal should be readable as
   evidence justifying a system-side rule (see SUBJECT FRAMING).
7. done=true is invalid when rule is empty. If the answer has useful evidence
   but no settled rule or quality statement, use done=false and ask a follow-up.
8. Apply PROBE-FIRST RHYTHM and DRILL-BEFORE-CLOSE from the persona.
   For kind=need and kind=concern, the first stakeholder answer on this
   item is a reaction to the probe (a foil), not yet a settled rule.
   Default done=false on the first stakeholder turn for these kinds;
   close only when ACCEPT-AMBIGUITY CLOSE has explicitly fired in
   that first reaction, or when at least one follow-up drill has
   already happened. Outside those two cases, prefer recording
   signals with done=false and asking a follow-up.
9. For kind=concern, done=true is invalid when rule contains ONLY an
   emotional descriptor with no observable anchor. Apply QUALITY
   BOUNDARY DISCIPLINE before closing: if the load-bearing words in
   rule reduce to feeling vocabulary ("quickly", "responsive",
   "fast", "instantly", "immediately", "smooth", "snappy",
   "intuitive") and no observable absence, comparator, operating
   condition, or named precedent appears, set done=false, record
   the descriptor as a signal (it is evidence about the user's
   experience), and ask the grounded follow-up that turns the
   descriptor into an observable anchor.

ACCEPT-AMBIGUITY CLOSE (for kind=need and kind=conflict)
A need or conflict item is not always closed by a specific number, scale, or
precedence. Sometimes the defensible answer is that FLEXIBILITY itself is the
rule. When the stakeholder explicitly and consistently states across turns
that they cannot specify exact terms because variation in user experience or
absence of role authority is the reason, that statement IS the close.
- Signs flexibility is the close, not a stall:
  * the stakeholder names the alternatives that must coexist
    (predefined AND open-ended, structured AND free-form, etc.);
  * the stakeholder explains WHY a single answer would be wrong;
  * the stakeholder repeats the same refusal with consistent reasoning
    across two or more turns.
- Action: close with rule="The app must support [both X and Y / multiple
  options / flexibility in Z]" and signals carrying the named alternatives
  the stakeholder defended. align=narrower is usually correct here.
- Hard cap: if you have asked the same closure question three times and
  received the same flexibility answer with consistent reasoning, do not
  ask a fourth time. Close on flexibility. Asking the same question a
  fourth time is looping, not drilling.

WHEN kind=need
- First ground the stakeholder in the named entity step.
- Then present the probe as a factual statement framed around the PRODUCT
  (per SUBJECT FRAMING), not around the user's duties.
- Drill until the missing PRODUCT rule, limit, dependency, or permission
  becomes explicit, OR until the stakeholder defensibly settles on
  flexibility per ACCEPT-AMBIGUITY CLOSE.

WHEN kind=conflict
A conflict item exposes a collision between two reviewed duties or
concern pressures. Your job here is NOT to drive the resolution. Driving
resolution from a single stakeholder biases the outcome toward whichever
side that stakeholder represents; the global resolution requires every
affected stakeholder's stance side-by-side, which only the human
reviewer sees at the distiller HITL gate. Capture this stakeholder's
side only, then close.

Capture three things from THIS stakeholder alone:
  (a) HOW the collision lands in their lived role — when they feel
      it at the named entity step, what the experience looks like,
      what frustration or uncertainty it creates;
  (b) WHICH SIDE they personally lean toward and why, in their own
      role's terms — their lean is evidence of one party's stance,
      not a global verdict;
  (c) any concrete preference they would want the product to offer
      from their side (a default they would accept, a signal they
      would want to see, an exit they would want to keep open) —
      still expressed as their stance, not the product's commitment.

Close criteria for conflict items (done=true) — any of the following
is sufficient:
  - align in {exact, narrower} AND (a), (b), and (c) above are
    visible in signals (one or more of (b) and (c) may be "no lean"
    or "no preference" when the stakeholder honestly has none);
  - ACCEPT-AMBIGUITY CLOSE applies (the stakeholder explicitly
    settles on flexibility itself, with the alternatives named);
  - the stakeholder explicitly states the collision is not theirs
    to resolve ("that is a product decision", "I would defer to
    someone else", "this is not my call") — record that statement
    in signals and close.

The rule on a closed conflict item names the CURRENT stakeholder's
stance, never a globally enforced product rule. Acceptable rule
shapes for conflict items:
  - "The current stakeholder leans toward weighting <X> when <X>
    and <Y> collide, and would accept the product surfacing both
    rather than choosing for them."
  - "The current stakeholder defers the precedence decision to a
    product-level rule and wants the conflict surfaced rather than
    hidden."
  - "The current stakeholder cannot specify a single rule because
    the collision varies by context, and would accept either side
    so long as <named condition> holds."
The distiller picks these stakeholder stances up as evidence and
emits the unresolved tension as a Conflict object for human review.

Do NOT:
  - re-ask the same closure question after the stakeholder has
    already given their personal lean; their lean IS their close
    on this item.
  - push for a precedence rule, a condition split, or an escalation
    path that this single stakeholder would not naturally own. When
    the closure would require negotiating with another role, the
    collision belongs to HITL, not to this turn.
  - conflate the stakeholder's personal lean (evidence) with the
    product's global verdict (not your output). The first closes
    this item; the second is decided later.
  - keep drilling once item_turn_count is at 3 or more and the
    stakeholder's stance has not shifted. Capture what you have and
    close on stance; the conflict will be raised to HITL by the
    distiller.

WHEN kind=concern (apply QUALITY BOUNDARY DISCIPLINE)
- Work in quality-probing mode, not rule-clarification mode.
- Ground the stakeholder in the named entity step and concern theme.
- Ask for lived examples, operating conditions, tolerable failure,
  observable absences, comparative anchors, named precedents, and who is
  affected when the quality fails.
- Emotional descriptors are NOT qualitative boundaries. "Instantly",
  "immediately", "quickly", "responsive", "fast", "smooth", "snappy",
  "promptly" describe how the user feels but give Distiller nothing to
  test. Treat these as the START of a probe, never the end.
- When the stakeholder uses an emotional descriptor, ask one grounded
  follow-up: "When you say 'instantly', what would you actually notice if
  it were not instant — a spinner appearing, a perceptible wait, a moment
  where you start looking elsewhere?". Do NOT close on the descriptor
  alone.
- done=true only when the rule contains one of:
  * a concrete threshold or magnitude with a unit,
  * a comparative anchor with a named comparator ("faster than typing the
    next word"),
  * an observable absence ("no spinner appears"),
  * an operating condition that bounds the failure ("before the user
    shifts attention away"),
  * a named precedent the stakeholder genuinely knows.
- rule is the settled quality statement, written system-subject ("The
  app must respond before the user shifts attention away from the entry
  screen"), not "Users must experience instant response".
- done=true is invalid if rule is empty. done=true is also invalid if
  rule contains only an emotional descriptor without an observable
  anchor; ask the grounded follow-up first.
- Do not invent a numeric threshold for the stakeholder.
- If the stakeholder gives only examples of frustration or failure,
  record the evidence with done=false, then ask for the observable
  anchor (absence / comparator / operating condition / precedent) that
  would let Distiller write a reviewable NFR.

WHEN CALLING ask_question
- message is either:
  - a grounded question framed around the product, or
  - the prepared probe stated as a fact.
- Frame around the product, not the user (see SUBJECT FRAMING). Prefer
  "what does the app need to ..." or "what does the app fail to do at ..."
  over "what must you do when ...".
- mirror briefly reflects the latest stakeholder concern when one exists.
- probe=true only when you are presenting the prepared probe itself.
- Before asking, check: have I asked this same closure question two or
  more times already? If yes and the stakeholder's answer has not moved,
  consider ACCEPT-AMBIGUITY CLOSE or QUALITY BOUNDARY follow-up instead
  of repeating.
"""


class InterviewerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="interviewer")

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="record_answer",
            description=(
                "Record the pending stakeholder reply for the current agenda item.\n\n"
                "Use this tool only when TURN STATUS says Pending answer: yes. "
                "This tool records evidence for the CURRENT ITEM only; it does not "
                "complete the whole agenda.\n\n"
                "Arguments:\n"
                "  align (str, required): exact | narrower | broader | misaligned.\n"
                "    exact/narrower mean the item may close only if rule is non-empty, system-subject, and addresses the current gap plus risk/tension.\n"
                "    broader/misaligned mean the item remains open and rule must be empty.\n"
                "  done (bool, required): true only when the close rule is fully settled.\n"
                "    Mandatory pairing: broader/misaligned => done=false.\n"
                "    exact/narrower => done=true only if rule is explicit, non-empty, system-subject, and addresses the current gap plus risk/tension.\n"
                "    If useful evidence exists but no settled rule/quality statement can be written, use done=false.\n"
                "    Accepted ambiguity is a valid close for need/conflict items when the stakeholder defensibly settled on flexibility itself as the rule (see ACCEPT-AMBIGUITY CLOSE).\n"
                "    PROBE-FIRST / DRILL-BEFORE-CLOSE: for kind=need and kind=concern, done=true on the first stakeholder turn of an item is invalid unless ACCEPT-AMBIGUITY CLOSE has explicitly fired in that first reaction. The first answer is evidence about the probe (a foil); turn it into a closure rule with a follow-up. For kind=conflict, the stakeholder's first-turn lean is a valid close — record it.\n"
                "    QUALITY BOUNDARY DISCIPLINE: for kind=concern, done=true is invalid when rule reduces to emotional descriptors only ('quickly', 'responsive', 'fast', 'instantly', 'immediately', 'smooth', 'snappy', 'intuitive') with no observable anchor (absence, comparator, operating condition, named precedent). Set done=false and ask the grounded follow-up that turns the descriptor into an observable anchor.\n"
                "  why (str, required): concise reason for the align decision.\n"
                "  rule (str): settled closure statement written with the PRODUCT as the subject.\n"
                "    Correct: 'The app must require email and password at sign-up.', 'The system must present the terms before account creation.', 'The product must support both predefined and open-ended descriptors when logging stress.'.\n"
                "    Incorrect: 'Users must provide email and password.', 'The user must agree to the terms.', 'Users must be aware that delete is permanent.' — these are user obligations and almost always wrong as written (see SUBJECT FRAMING).\n"
                "    For kind=concern, the rule must contain an observable quality anchor: a threshold with units, a named comparator, an observable absence ('no spinner visible'), an operating condition ('before the user shifts attention'), or a named precedent. Emotional descriptors alone ('instantly', 'immediately', 'responsive', 'fast', 'smooth') are NOT acceptable.\n"
                "    Keep rule as a closure summary; do not use it to compress every independent condition from the dialogue.\n"
                "    Mandatory pairing: broader/misaligned => rule=''.\n"
                "    Leave empty whenever done=false.\n"
                "  signals (list[str], required): atomic evidence units from the stakeholder's reply.\n"
                "    Include each independent condition, limit, exception, permission, dependency, threshold, precedence fact, or quality boundary as its own string.\n"
                "    These signals are the main source Distiller uses to split one interview record into multiple atomic requirements.\n"
                "    Each signal should be readable as evidence justifying a system-side rule; if a signal reads only as a user duty, rewrite it to expose what the app does or fails to do.\n"
                "\nConcern items:\n"
                "  Do not close on examples or frustrations alone. Do not close on emotional descriptors alone. Close only when rule contains an observable quality anchor Distiller can reuse. "
                "If missing, record signals with done=false so the next turn asks a grounded follow-up about the observable anchor (absence / comparator / operating condition / precedent).\n"
                'Input: {"align": str, "done": bool, "why": str, "rule": str, "signals": list}'
            ),
            func=self._tool_record_answer,
        ))
        self.register_tool(Tool(
            name="ask_question",
            description=(
                "Deliver exactly one interviewer message to the current stakeholder.\n\n"
                "Use this tool when there is no pending answer, or after record_answer "
                "keeps the current item open. Ask only about the CURRENT ITEM shown in "
                "the task. Do not skip ahead.\n\n"
                "Arguments:\n"
                "  message (str, required): either a grounded question or the prepared probe stated as fact.\n"
                "    Frame around the PRODUCT, not the user: 'What does the app need to enforce at X?', 'What does the app need to show you at X?', 'What does the app fail to do today at X?'. Avoid 'What must you do at X?' — that elicits user obligations, not product rules (see SUBJECT FRAMING).\n"
                "  mirror (str, required): one short sentence echoing the latest concern from this same stakeholder; "
                "use an empty string when no prior answer exists for this item.\n"
                "  probe (bool, required): true only when message is the prepared factual probe.\n"
                "\nFor kind=concern, ask for lived examples first if needed, then follow up for an observable quality anchor: the absence the user would notice, a comparative anchor, an operating condition that bounds failure, or a named precedent. "
                "Emotional descriptors ('instantly', 'immediately', 'responsive') are the START of a probe, never an acceptable close — when the stakeholder uses one, ask one grounded follow-up that turns it into an observable condition.\n"
                "Do not ask the stakeholder to invent a precise number if their role cannot defend one.\n"
                "If you have asked the same closure question two or more times and the stakeholder keeps giving the same flexibility answer with consistent reasoning, do not ask a fourth time. Either close on flexibility per ACCEPT-AMBIGUITY CLOSE, or move on with done=false and a clear gap.\n"
                'Input: {"message": str, "mirror": str, "probe": bool}'
            ),
            func=self._tool_ask_question,
        ))
        self.register_tool(Tool(
            name="conclude",
            description=(
                "Write the interview_record artifact for the whole agenda.\n\n"
                "Hard precondition: call this tool only when the task explicitly states "
                "'AGENDA STATUS: COMPLETE' and no CURRENT ITEM is shown. Never call it "
                "because a single item was answered. Never call it while the task states "
                "'AGENDA STATUS: OPEN'. The tool will reject the call if any agenda item "
                "is still pending.\n"
                "Input: {}"
            ),
            func=self._tool_conclude,
        ))

    def _tool_record_answer(
        self,
        align: str = "",
        done: bool = False,
        why: str = "",
        rule: str = "",
        signals: Optional[List[str]] = None,
        state: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> ToolResult:
        state = state or {}
        answer = (state.get("enduser_answer") or "").strip()
        if not answer:
            return ToolResult(
                observation=(
                    "[record_answer] Pending answer is empty. Call ask_question instead."
                ),
                should_return=False,
            )

        runtime = self._load_runtime(state)
        if runtime is None:
            return ToolResult(
                observation="[record_answer] Agenda runtime is missing.",
                is_error=True,
                should_return=True,
            )

        item = runtime.current_item()
        if item is None:
            return ToolResult(
                observation="[record_answer] Agenda already complete.",
                should_return=True,
            )

        item.answer = answer
        item.talk.append({
            "question": item.question or "",
            "answer": answer,
            "recorded_at": datetime.now().isoformat(),
        })
        normalized_align = align.strip().lower() or "misaligned"
        if normalized_align not in {"exact", "narrower", "broader", "misaligned"}:
            normalized_align = "misaligned"

        settled_rule = rule.strip()
        can_close = (
            bool(done)
            and normalized_align in {"exact", "narrower"}
            and bool(settled_rule)
        )

        item.align = normalized_align  # type: ignore[assignment]
        item.rule = settled_rule or None
        item.signals = list(item.signals) + [
            signal for signal in (signals or []) if signal and signal not in item.signals
        ]

        if not can_close:
            reason = "the item remains open for another question."
            if done and normalized_align in {"exact", "narrower"} and not settled_rule:
                reason = (
                    "the model tried to close it without a settled rule or quality "
                    "statement, so the item remains open for a follow-up."
                )
            elif done and normalized_align in {"broader", "misaligned"}:
                reason = (
                    "the answer was broader or misaligned, so the item remains open "
                    "for a follow-up."
                )
            return ToolResult(
                observation=(
                    f"Answer recorded for {item.id}; {reason}"
                ),
                state_updates={
                    "elicitation_agenda": runtime.model_dump(),
                    "enduser_answer": "",
                    "current_question": "",
                    "_agenda_needs_question": True,
                },
                should_return=True,
            )

        item.status = "answered"
        runtime.advance()
        next_item = runtime.current_item()

        return ToolResult(
            observation=f"Answer recorded and item {item.id} closed.",
            state_updates={
                "elicitation_agenda": runtime.model_dump(),
                "enduser_answer": "",
                "current_question": "",
                "current_stakeholder_role": next_item.role if next_item else "",
                "item_turn_count": 0,
                "probe_presented": False,
                "conversation": [],
                "_agenda_needs_question": True,
            },
            should_return=True,
        )

    def _tool_ask_question(
        self,
        message: str = "",
        mirror: str = "",
        probe: bool = False,
        state: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> ToolResult:
        state = state or {}
        runtime = self._load_runtime(state)
        delivered = f"{mirror.strip()} {message.strip()}".strip() if mirror else message.strip()

        conversation = list(state.get("conversation") or [])
        conversation.append({
            "role": "interviewer",
            "content": delivered,
            "timestamp": datetime.now().isoformat(),
        })

        item_turn_count = (state.get("item_turn_count") or 0) + 1
        if runtime is not None:
            item = runtime.current_item()
            if item is not None:
                item.question = delivered

        updates: Dict[str, Any] = {
            "current_question": delivered,
            "conversation": conversation,
            "item_turn_count": item_turn_count,
            "probe_presented": bool(state.get("probe_presented")) or probe,
            "_agenda_needs_question": False,
        }
        if runtime is not None:
            updates["elicitation_agenda"] = runtime.model_dump()

        return ToolResult(
            observation=f"Question delivered: {delivered}",
            state_updates=updates,
            should_return=True,
        )

    def _tool_conclude(
        self,
        state: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> ToolResult:
        state = state or {}
        runtime = self._load_runtime(state)
        lines: List[str] = []
        records: List[Dict[str, Any]] = []

        if runtime is not None:
            current = runtime.current_item()
            if current is not None and not runtime.elicitation_complete:
                return ToolResult(
                    observation=(
                        "[conclude] Agenda is still open. Conclude is forbidden while "
                        f"current item {current.id} is pending. Ask the next question "
                        "or record the pending answer instead."
                    ),
                    should_return=False,
                )

            for index, item in enumerate(runtime.items, 1):
                talk = list(item.talk or [])
                answer_text = "\n".join(
                    f"Q: {turn.get('question') or '(not recorded)'}\n"
                    f"A: {turn.get('answer') or '(no answer provided)'}"
                    for turn in talk
                )
                record = ELRecord(
                    id=f"EL-{index:03d}",
                    item=item.id,
                    entity=item.entity,
                    step=item.step,
                    aspect=item.aspect,
                    trap=item.trap,
                    kind=item.kind,
                    role=item.role,
                    close=item.close,
                    source=item.source,
                    risk=item.risk,
                    concern_ref=item.concern_ref,
                    concern_category=item.concern_category,
                    concern_theme=item.concern_theme,
                    rule=item.rule,
                    align=item.align,
                    talk=talk,
                    signals=list(item.signals or []),
                    question=item.question,
                    answer=answer_text or None,
                    status="answered" if talk else "skipped",
                ).model_dump()
                records.append(record)
                if answer_text:
                    lines.append(
                        f"[{item.id}] {item.kind}/{item.aspect} | "
                        f"{item.entity}.{item.step} | {item.role}\n{answer_text}"
                    )

        notes = "\n\n".join(lines) or "(no answers recorded)"
        interview_record = {
            "session_id": state.get("session_id", ""),
            "project_description": state.get("project_description", ""),
            "created_at": datetime.now().isoformat(),
            "items": records,
            "notes": notes,
            "status": "pending_review",
        }

        artifacts = dict(state.get("artifacts") or {})
        artifacts["interview_record"] = interview_record

        return ToolResult(
            observation="Interview complete. interview_record artifact written.",
            state_updates={
                "elicitation_notes": notes,
                "artifacts": artifacts,
                "_needs_srs_synthesis": True,
            },
            should_return=True,
        )

    @staticmethod
    def _load_runtime(state: Optional[Dict[str, Any]]) -> Optional[AgendaRuntime]:
        state = state or {}
        artifacts = state.get("artifacts") or {}
        raw = (
            state.get("elicitation_agenda")
            or artifacts.get("reviewed_elicitation_agenda")
            or artifacts.get("elicitation_agenda_artifact")
        )
        if raw is None:
            return None
        if isinstance(raw, AgendaRuntime):
            return raw
        try:
            return AgendaRuntime.from_agenda_artifact(raw)
        except Exception as exc:
            logger.warning("[InterviewerAgent] Could not load agenda runtime: %s", exc)
            return None

    @staticmethod
    def _role_detail(vision: Dict[str, Any], role_name: str) -> str:
        for role in (vision.get("roles") or []):
            if role.get("name", "").strip().lower() != role_name.strip().lower():
                continue
            lines = [f"  Role kind: {role.get('kind', '')}"]
            duties = role.get("duties") or []
            if duties:
                lines.append("  Duties:")
                for duty in duties:
                    lines.append(f"    - {duty.get('rule', '')}")
            return "\n".join(lines)
        return ""

    @staticmethod
    def _role_memory(
        runtime: AgendaRuntime,
        role_name: str,
        current_id: str,
    ) -> str:
        rules: List[str] = []
        answers: List[str] = []
        for item in runtime.items:
            if item.id == current_id:
                break
            if item.role != role_name:
                continue
            if item.rule:
                rules.append(item.rule)
            elif item.answer:
                answers.append(item.answer)
        lines: List[str] = []
        if rules:
            lines.append("  Settled rules:")
            lines.extend(f"    - {rule}" for rule in rules[-4:])
        if answers:
            lines.append("  Prior answers:")
            lines.extend(f"    - {answer}" for answer in answers[-4:])
        return "\n".join(lines)

    def _build_task(self, state: Dict[str, Any]) -> str:
        runtime = self._load_runtime(state)
        vision = (
            (state.get("artifacts") or {}).get("reviewed_product_vision")
            or state.get("product_vision")
            or {}
        )

        if runtime is None:
            return "Agenda runtime is unavailable. Call ask_question only if a grounded next step is possible."
        if runtime.elicitation_complete:
            return "AGENDA STATUS: COMPLETE\nAll agenda items are complete. Call conclude."

        item = runtime.current_item()
        if item is None:
            return "AGENDA STATUS: COMPLETE\nAgenda is complete. Call conclude."

        answered = sum(1 for agenda_item in runtime.items if agenda_item.status == "answered")
        total = len(runtime.items)
        role_detail = self._role_detail(vision, item.role)
        role_memory = self._role_memory(runtime, item.role, item.id)
        drill = TRAP_DRILL_STYLE.get(item.trap, "")
        pending = bool((state.get("enduser_answer") or "").strip())

        sections = [
            "AGENDA STATUS: OPEN",
            "Conclude is forbidden while this status is OPEN. Work only on the current item.",
            "",
            f"AGENDA: {answered}/{total} items closed.",
            "",
            "CURRENT ITEM:",
            f"  id: {item.id}",
            f"  kind: {item.kind}",
            f"  entity: {item.entity}",
            f"  step: {item.step}",
            f"  role: {item.role}",
            f"  aspect: {item.aspect}",
            f"  trap: {item.trap}",
            "",
            "STAKEHOLDER CONTEXT:",
        ]
        sections.append(role_detail or "  (no extra role detail)")
        if role_memory:
            sections.extend(["", "SESSION MEMORY:", role_memory])

        sections.extend([
            "",
            "SCENE:",
            f"  {item.scene}",
            "",
            "PRIVATE INTERVIEWER CONTEXT:",
            f"  baseline: {item.baseline}",
            f"  risk/tension: {item.risk or '(not provided)'}",
            f"  probe: {item.probe}",
            f"  gap: {item.gap}",
            f"  close: {item.close}",
        ])
        if item.peer:
            sections.append(f"  peer duty: {item.peer}")
        if item.kind == "concern":
            sections.extend([
                "",
                "NFR CONCERN CONTEXT:",
                f"  concern_ref: {item.concern_ref or item.source}",
                f"  category: {item.concern_category or '(not provided)'}",
                f"  theme: {item.concern_theme or '(not provided)'}",
                "  mode: quality probing; settle quality evidence, not a business rule.",
            ])
        if drill:
            sections.extend(["", "DRILL STYLE:", f"  {drill}"])

        sections.extend([
            "",
            "TURN STATUS:",
            f"  Turn count: {state.get('item_turn_count', 0)}",
            f"  Probe presented: {'yes' if state.get('probe_presented') else 'no'}",
            f"  Pending answer: {'yes' if pending else 'no'}",
        ])

        conversation = state.get("conversation") or []
        if conversation:
            sections.extend(["", "CURRENT DIALOGUE:"])
            for turn in conversation[-6:]:
                sections.append(
                    f"  [{str(turn.get('role', '')).upper()}] {turn.get('content', '')}"
                )
        if pending:
            sections.extend([
                "",
                "PENDING ANSWER:",
                f"  {state.get('enduser_answer', '')}",
            ])

        return "\n".join(sections)

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.react(
            state=state,
            task=self._build_task(state),
            tool_choice="required",
            profile_addendum=_REACT_ADDENDUM,
            include_memory=False,
        )