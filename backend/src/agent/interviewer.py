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
        description="Final business rule captured from the stakeholder when one was settled."
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
            "Atomic evidence units stated by the stakeholder. Each item should carry "
            "one independent condition, limit, exception, permission, dependency, "
            "threshold, precedence, failure, or quality boundary."
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
   left as accepted ambiguity.
4. Alignment and done must be internally consistent:
   - exact or narrower -> done may be true only if rule is concrete.
   - broader or misaligned -> done must be false and rule must be empty.
5. rule is the shortest settled closure statement for need/conflict items, or
   the settled quality statement for concern items. It is not the only source
   for Distiller and should not hide multiple independent facts in one blob.
   Leave it empty when done=false.
6. signals capture only concrete stakeholder evidence stated in this exchange.
   signals carry the independent facts Distiller will split.
   Split independent conditions, limits, permissions, dependencies, exceptions,
   thresholds, quality boundaries, and precedence facts into separate signal
   strings. Do not merge them with "and" when they could become separate
   requirements or acceptance criteria.
7. done=true is invalid when rule is empty. If the answer has useful evidence
   but no settled rule or quality statement, use done=false and ask a follow-up.

WHEN kind=need
- First ground the stakeholder in the named entity step.
- Then present the probe as a factual statement.
- Then drill until the missing rule, limit, dependency, or permission becomes explicit.

WHEN kind=conflict
- Do not assume a decision maker exists.
- Ask what happens when the two pressures occur together.
- Clarify whether the answer is:
  - a precedence rule,
  - a condition split,
  - an escalation path,
  - or an unresolved ambiguity.
- done=true only when one of those becomes explicit enough to remove the ambiguity.

WHEN kind=concern
- Work in quality-probing mode, not rule-clarification mode.
- Ground the stakeholder in the named entity step and concern theme.
- Ask for lived examples, operating conditions, tolerable failure, comparative
  anchors, and who is affected when the quality fails.
- done=true only when the answer states either:
  - a concrete threshold or magnitude,
  - a comparative anchor with conditions,
  - or the strongest qualitative boundary the stakeholder can defend.
- rule is the settled quality statement. It may be qualitative when no defensible
  number was provided.
- done=true is invalid if rule is empty; ask a follow-up instead.
- Do not invent a numeric threshold for the stakeholder.
- If the stakeholder gives only examples of frustration or failure, record the
  evidence with done=false, then ask for the operating condition, tolerable
  failure, comparative anchor, or qualitative boundary that would let Distiller
  write a reviewable NFR.

WHEN CALLING ask_question
- message is either:
  - a grounded question, or
  - the prepared probe stated as a fact.
- mirror briefly reflects the latest stakeholder concern when one exists.
- probe=true only when you are presenting the prepared probe itself.
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
                "    exact/narrower mean the item may close only if rule is non-empty and addresses the current gap plus risk/tension.\n"
                "    broader/misaligned mean the item remains open and rule must be empty.\n"
                "  done (bool, required): true only when the close rule is fully settled.\n"
                "    Mandatory pairing: broader/misaligned => done=false.\n"
                "    exact/narrower => done=true only if rule is explicit, non-empty, and addresses the current gap plus risk/tension.\n"
                "    If useful evidence exists but no settled rule/quality statement can be written, use done=false.\n"
                "  why (str, required): concise reason for the align decision.\n"
                "  rule (str): settled business rule in IF/THEN or MUST form for need/conflict items.\n"
                "    For kind=concern, this must be the settled quality statement: threshold, comparative anchor, operating condition, or qualitative boundary.\n"
                "    Keep rule as a closure summary; do not use it to compress every independent condition from the dialogue.\n"
                "    Mandatory pairing: broader/misaligned => rule=''.\n"
                "    Leave empty whenever done=false.\n"
                "  signals (list[str], required): atomic evidence units from the stakeholder's reply.\n"
                "    Include each independent condition, business limit, exception, permission, dependency, threshold, precedence fact, or quality boundary as its own string.\n"
                "    These signals are the main source Distiller uses to split one interview record into multiple atomic requirements.\n"
                "\nConcern items:\n"
                "  Do not close on examples/frustrations alone. Close only when rule contains a quality boundary Distiller can reuse. "
                "If missing, record signals with done=false so the next turn asks a follow-up.\n"
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
                "  mirror (str, required): one short sentence echoing the latest concern from this same stakeholder; "
                "use an empty string when no prior answer exists for this item.\n"
                "  probe (bool, required): true only when message is the prepared factual probe.\n"
                "\nFor kind=concern, ask for lived examples first if needed, then follow up for the risk-driving condition, tolerable failure, comparative anchor, or qualitative boundary. "
                "Do not ask the stakeholder to invent a precise number if their role cannot defend one.\n"
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
