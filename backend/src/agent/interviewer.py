"""
interviewer.py - InterviewerAgent

InterviewerAgent runs the reviewed agenda one item at a time. The model chooses
conversational moves through tools; Python records the chosen action, updates
runtime data, and writes the interview_record artifact.

Design split
------------
Tool descriptions name what each tool does and its signature — they exist so
the model can pick the right tool. They do not teach how to think.
The ReAct addendum prompt teaches the thinking: turn control, question craft,
and closure judgment.
Persona text holds the agent's stable stance only.
Python only normalizes inputs, advances runtime, and writes the artifact.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .agenda import AgendaRuntime
from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


CoverageStatus = Literal["covered", "gap", "skipped"]
AssumptionStance = Literal["supports", "weakens", "qualifies", "unclear"]


# ─────────────────────────────────────────────────────────────────────────────
# Artifact pieces
# ─────────────────────────────────────────────────────────────────────────────

class CoverageEntry(BaseModel):
    point: str = Field(description="Agenda coverage point being judged.")
    status: CoverageStatus = Field(description="covered when stakeholder evidence settled the point. gap when probed but not settled. skipped when prior evidence or item scope makes more probing unnecessary.")
    evidence: str = Field(description="Brief evidence text: stakeholder fact for covered; failed probe reason for gap; prior-evidence or scope reason for skipped. Required for every entry.")


class AssumptionEvidenceEntry(BaseModel):
    vision_ref: str = Field(description="Vision id (assumption, concern, or scope) this evidence speaks to. Must come from the current item's vision_refs.")
    stance: AssumptionStance = Field(description="How the evidence affects the referenced vision element: supports (aligns), weakens (contradicts), qualifies (true only under a condition/subset/boundary), unclear (role could not settle it).")
    evidence: str = Field(description="Brief stakeholder fact from the dialogue. Do not invent; cite what the role actually said.")
    implication: str = Field(description="What this evidence may change downstream: requirement, quality expectation, boundary, conflict, gap, or first-release note.")


class ELRecord(BaseModel):
    id: str = Field(description="Stable interview record id in EL-NNN format.")
    item: str = Field(description="Agenda item id (IT-NNN) that produced this record.")
    vision_refs: List[str] = Field(default_factory=list, description="Vision ids (assumption / concern / scope) this exchange was meant to clarify.")
    perspective: str = Field(description="Product role perspective interviewed.")
    context: str = Field(description="Operating context shown to the stakeholder for this item.")
    decision_target: Optional[str] = Field(default=None, description="What this exchange was meant to clarify downstream.")
    close_when: str = Field(description="Stop condition used by the interviewer for this item.")
    coverage_points: List[str] = Field(default_factory=list, description="Agenda evidence points owned by this item.")
    coverage: List[CoverageEntry] = Field(default_factory=list, description="Per-point coverage judgment.")
    signals: List[str] = Field(default_factory=list, description="Atomic stakeholder-stated facts as they were said. One independent fact per entry. Not paraphrases of each other, not synthesis across speakers.")
    assumption_evidence: List[AssumptionEvidenceEntry] = Field(default_factory=list, description="Evidence about each assumption the answer touched.")
    gaps: List[str] = Field(default_factory=list, description="Coverage points probed but unresolved. One entry = one concrete missing element.")
    rule: Optional[str] = Field(default=None, description="Closure summary captured when the item settled. Empty when closing on gaps only.")
    talk: List[Dict[str, Any]] = Field(default_factory=list, description="Question/answer turns captured for this item.")
    status: Literal["answered", "partial", "skipped"] = Field(description="Final interview status for this agenda item.")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt addendum — taught thinking
# ─────────────────────────────────────────────────────────────────────────────

_REACT_ADDENDUM = """\
TURN CONTROL
- Inspect TURN STATUS first.
- If Pending answer: yes → call record_answer.
- If Pending answer: no and AGENDA STATUS: OPEN → call ask_question.
- If AGENDA STATUS: COMPLETE → call conclude.
- One tool call per turn. Closing one item does not complete the interview;
  the supervisor advances you to the next item automatically.

QUESTION CRAFT (apply before ask_question)
You are talking to a simulated person who lives the situation. They are not a
designer, an analyst, or a reviewer. They cannot decide product scope; they
can tell you what they experience.

How to pick what to ask:
- Look at the current item's coverage_points and vision_refs. Pick the one
  open point whose settling would most change a downstream requirement, gap,
  conflict, boundary, or first-release note.
- If the prior answer was thin or moved off the point, ask the next question
  that pulls back to the point you still need.
- If a point was probed and the role could not answer, that is a gap — do not
  keep probing the same way; either pivot to an adjacent point or close on
  gap with a reason.
- If the seed question assumes the stakeholder has already used a product that
  the project description only proposes, translate it into the current problem
  moment, comparable workaround, decision boundary, or minimum useful behavior.
  Do not pretend usage history exists.

How to phrase the question:
- One open question. Not yes/no, not either/or, not multi-part. No design or
  feature-confirmation framing ("would you like…", "what features should…").
- Open with the question itself. No thanks, recap, or praise.
- The simulated person owns lived experience, not strategy. Ask about
  situation, current workaround, consequence, boundary, exception, quality
  expectation, or minimum useful behavior.

Probing angles available to you (choose what the moment needs; you do not
have to label or record which one you picked):
- specify — drill into a vague detail (when, who, how often, with what,
  inside which moment).
- negate — when does the rule NOT apply, or should it be blocked?
- stretch — boundary pressure: peak, simultaneity, absence, load, failure of
  the normal path, unusual timing.
- conflict — contrast a tension with prior dialogue, the Product Vision, or
  another role's evidence. Name both sides neutrally.
- why-deeper — causality, underlying reason, policy, or risk behind a stated
  behavior.
- critical-incident — ask for one concrete moment when the current situation
  went badly, urgently, ambiguously, or with meaningful consequence.
- ladder — ask why the named friction matters, then what the stakeholder does
  next when it is not resolved.
- boundary — ask what the product or resource should not decide, replace,
  own, expose, or guarantee from this stakeholder's view.

SIGNAL-DRIVEN PROBING (apply before choosing the next question)
A surfaced signal is a concrete fact the stakeholder just named for the first
time — a specific misconception, a specific workaround, a specific moment of
failure, a specific role attribute, a specific consequence. Surface is not
depth: the stakeholder named it, but the lived detail behind it (when, with
whom, what happens next, what they tried, what they wish were different) is
still implicit.

The temptation is to mark the coverage_point as covered and pivot to the next
point. Don't, unless the lived detail behind the surfaced signal would not
change any downstream requirement, gap, conflict, boundary, or release choice.

Self-test before the next question: "Did the last answer name a concrete
signal whose lived detail is still implicit, and would that detail change a
downstream decision?" If yes, the next question drills into THAT signal —
`specify` for the situation behind it, `critical-incident` for a real moment,
`ladder` for why it matters and what happens next, `why-deeper` for the cause,
`negate` for when it does not apply, `stretch` for boundary conditions, or
`boundary` for ownership limits — before pivoting to a different
coverage_point. Pivoting too early turns surface signals into shallow evidence
the Distiller cannot lift into a requirement.

CLOSURE JUDGMENT (apply before record_answer.done = true)
Your goal is lived evidence that supports, weakens, qualifies, or leaves each
relevant assumption unclear — not assumption confirmation, and not the
minimum number of turns.

VERDICT REQUIRED FOR EACH COVERAGE_POINT

Every coverage_point in the current item must receive ONE of three verdicts
in the coverage array before done=true:

- covered  — the stakeholder's answer directly addressed the point. Quote or
  summarize in CoverageEntry.evidence.
- gap      — you ASKED a question targeting this point AND the stakeholder
  could not settle it. Name the failed probe in CoverageEntry.evidence.
- skipped  — the point is genuinely duplicated by another covered point,
  represented by prior settled evidence, or out of scope for this item.
  Name the reason in CoverageEntry.evidence.

A coverage_point with NO verdict is an OMISSION — you did not address it.
"Skipped by default" because you did not ask is not allowed; that is silent
loss. Pursue the omitted point with one targeted follow-up, then assign the
correct verdict (covered if the answer addresses it, gap if it cannot be
settled).

Read the answer before judging coverage. Do not mark a point as skipped if
the answer actually covers it. Do not mark a point as gap if the question
did not target it — ask the targeted follow-up first.

EXPANSION OVER CHECKLIST — dialogue value comes from what is surfaced

The agenda's coverage_points are a FLOOR, not a ceiling. The value of
dialogue over reading a document is what the stakeholder surfaces beyond
the planned floor — a specific moment, a workaround, a quiet concern, a
boundary they noticed, a tension that did not appear in the agenda.

When the stakeholder names an unexpected lived detail outside the coverage
list, ask ONE follow-up exploring it before pivoting back to the next
planned coverage_point. A surfaced detail that becomes a signal is what
dialogue is for. Do not pivot away from new lived evidence just to tick the
next coverage_point.

done=true ONLY when ALL of these hold:
- Every coverage_point has a verdict (covered/gap/skipped) with evidence
  text — no omissions.
- Recent answers have stopped surfacing new unexpected signals worth
  exploring, OR the hard turn limit is reached.
- The current task's minimum evidence turns have been met.
- The recorded evidence is specific enough for Distiller to write at least
  one product-owned obligation, boundary, conflict, or explicit gap without
  inventing the missing object or acceptance condition.

done=false when:
- A coverage_point remains without a verdict (omission). Ask the targeted
  follow-up.
- A useful point is still unsettled and one non-redundant question would
  likely settle it. Ask that question.
- The last answer surfaced a new lived detail worth one follow-up. Pursue
  it.

If you reach the hard turn limit with uncovered points still without
verdict, mark them as explicit gaps with a clear "did not pursue due to
turn limit" reason — explicit gaps are reviewable; silent omissions are
not.

For each assumption touched by the answer, write one AssumptionEvidenceEntry
with stance + evidence + implication.

SIGNALS DISCIPLINE
- signals are atomic stakeholder-stated facts. One independent fact per entry.
- Do not paraphrase across speakers. Do not synthesize a fact combining two
  answers. Do not write "the user said X" wrappers. If a fact appears twice
  in dialogue, keep one entry.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class InterviewerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="interviewer")
        custom = (
            self._raw_config.get("iredev", {})
            .get("agents", {})
            .get("interviewer", {})
            .get("custom_params", {})
        )
        self._max_turns_per_item = int(custom.get("max_turns_per_item", 5) or 5)
        min_turns = int(custom.get("min_turns_per_assumption_item", 2) or 2)
        self._min_turns_per_assumption_item = max(1, min(min_turns, self._max_turns_per_item))

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="record_answer",
            description=(
                "Persist the stakeholder's reply for the current agenda item, "
                "judge coverage, and either keep the item open or close it.\n\n"
                "Use when TURN STATUS says Pending answer: yes.\n\n"
                "Arguments:\n"
                "  done (bool, required): close the item when meaningfully covered.\n"
                "  rule (str): closure summary; empty when closing on gaps only.\n"
                "  signals (list[str]): atomic stakeholder-stated facts.\n"
                "  assumption_evidence (list[dict]): each item is "
                "{vision_ref, stance, evidence, implication}; "
                "stance is supports | weakens | qualifies | unclear.\n"
                "  coverage (list[dict]): each item is {point, status, evidence}; "
                "status is covered | gap | skipped.\n"
                "  gaps (list[str]): probed-but-unresolved coverage_points.\n"
                'Input: {"done": bool, "rule": str, "signals": list, '
                '"assumption_evidence": list, "coverage": list, "gaps": list}'
            ),
            func=self._tool_record_answer,
        ))
        self.register_tool(Tool(
            name="ask_question",
            description=(
                "Deliver exactly one open question to the current stakeholder "
                "for the current agenda item.\n\n"
                "Use when TURN STATUS says Pending answer: no and "
                "AGENDA STATUS: OPEN.\n\n"
                "Arguments:\n"
                "  message (str, required): one open question.\n"
                'Input: {"message": str}'
            ),
            func=self._tool_ask_question,
        ))
        self.register_tool(Tool(
            name="conclude",
            description=(
                "Compile the interview_record artifact across the whole agenda.\n\n"
                "Hard precondition: call only when AGENDA STATUS: COMPLETE.\n"
                "Input: {}"
            ),
            func=self._tool_conclude,
        ))

    # ── Normalization helpers (no product logic) ─────────────────────────────

    @staticmethod
    def _normalize_coverage(
        raw_coverage: Optional[List[Any]],
    ) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        allowed = {"covered", "gap", "skipped"}
        for raw in raw_coverage or []:
            if not isinstance(raw, dict):
                continue
            point = str(raw.get("point") or "").strip()
            status = str(raw.get("status") or "").strip().lower()
            evidence = str(raw.get("evidence") or "").strip()
            if not point or status not in allowed or not evidence:
                continue
            normalized.append({
                "point": point,
                "status": status,
                "evidence": evidence,
            })
        return normalized

    @staticmethod
    def _merge_coverage(
        existing: Optional[List[Dict[str, Any]]],
        incoming: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        merged: Dict[str, Dict[str, str]] = {}
        for raw in existing or []:
            if not isinstance(raw, dict):
                continue
            point = str(raw.get("point") or "").strip()
            status = str(raw.get("status") or "").strip().lower()
            evidence = str(raw.get("evidence") or "").strip()
            if point and status:
                merged[point.lower()] = {
                    "point": point,
                    "status": status,
                    "evidence": evidence,
                }
        for entry in incoming:
            merged[entry["point"].lower()] = entry
        return list(merged.values())

    @staticmethod
    def _normalize_assumption_evidence(
        raw_entries: Optional[List[Any]],
        allowed_refs: Optional[List[str]],
    ) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        allowed_stances = {"supports", "weakens", "qualifies", "unclear"}
        allowed = {str(ref or "").strip() for ref in allowed_refs or [] if str(ref or "").strip()}
        for raw in raw_entries or []:
            if not isinstance(raw, dict):
                continue
            ref = str(raw.get("vision_ref") or raw.get("assumption_ref") or "").strip()
            stance = str(raw.get("stance") or "").strip().lower()
            evidence = str(raw.get("evidence") or "").strip()
            implication = str(raw.get("implication") or "").strip()
            if not ref or stance not in allowed_stances or not evidence or not implication:
                continue
            if allowed and ref not in allowed:
                continue
            normalized.append({
                "vision_ref": ref,
                "stance": stance,
                "evidence": evidence,
                "implication": implication,
            })
        return normalized

    @staticmethod
    def _merge_assumption_evidence(
        existing: Optional[List[Dict[str, Any]]],
        incoming: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        merged: List[Dict[str, str]] = []
        seen = set()
        for raw in list(existing or []) + incoming:
            if not isinstance(raw, dict):
                continue
            ref = str(raw.get("vision_ref") or raw.get("assumption_ref") or "").strip()
            stance = str(raw.get("stance") or "").strip().lower()
            evidence = str(raw.get("evidence") or "").strip()
            implication = str(raw.get("implication") or "").strip()
            key = (ref.lower(), stance, evidence.rstrip(".").lower(), implication.rstrip(".").lower())
            if not ref or not stance or not evidence or not implication or key in seen:
                continue
            seen.add(key)
            merged.append({
                "vision_ref": ref,
                "stance": stance,
                "evidence": evidence,
                "implication": implication,
            })
        return merged

    @staticmethod
    def _append_unique_text(existing: Optional[List[str]], incoming: List[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for text in list(existing or []) + list(incoming or []):
            value = str(text or "").strip()
            key = value.rstrip(".").lower()
            if not value or key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result

    @staticmethod
    def _coverage_complete(
        coverage_points: Optional[List[str]],
        coverage: Optional[List[Dict[str, Any]]],
    ) -> bool:
        points = [point.strip() for point in coverage_points or [] if point.strip()]
        if not points:
            return False
        settled = {
            str(entry.get("point") or "").strip().lower()
            for entry in coverage or []
            if (
                str(entry.get("status") or "").strip().lower() in {"covered", "gap", "skipped"}
                and str(entry.get("evidence") or "").strip()
            )
        }
        return all(point.lower() in settled for point in points)

    @staticmethod
    def _has_meaningful_coverage(
        coverage: Optional[List[Dict[str, Any]]],
    ) -> bool:
        return any(
            str(entry.get("status") or "").strip().lower() == "covered"
            and str(entry.get("evidence") or "").strip()
            for entry in coverage or []
        )

    def _min_turns_for_item(self, item: Any) -> int:
        return (
            self._min_turns_per_assumption_item
            if list(getattr(item, "vision_refs", []) or [])
            else 1
        )

    # ── Tools ────────────────────────────────────────────────────────────────

    def _tool_record_answer(
        self,
        done: bool = False,
        rule: str = "",
        signals: Optional[List[str]] = None,
        assumption_evidence: Optional[List[Any]] = None,
        coverage: Optional[List[Any]] = None,
        gaps: Optional[List[str]] = None,
        state: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> ToolResult:
        state = state or {}
        answer = (state.get("enduser_answer") or "").strip()
        if not answer:
            return ToolResult(
                observation="[record_answer] Pending answer is empty. Call ask_question instead.",
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
        item.signals = list(item.signals) + [
            signal for signal in (signals or []) if signal and signal not in item.signals
        ]
        normalized_assumption_evidence = self._normalize_assumption_evidence(
            assumption_evidence,
            getattr(item, "vision_refs", []),
        )
        item.assumption_evidence = self._merge_assumption_evidence(
            getattr(item, "assumption_evidence", []),
            normalized_assumption_evidence,
        )
        item.gaps = self._append_unique_text(list(item.gaps), list(gaps or []))
        normalized_coverage = self._normalize_coverage(coverage)
        item.coverage = self._merge_coverage(getattr(item, "coverage", []), normalized_coverage)
        settled_points = {
            str(entry.get("point") or "").strip().lower()
            for entry in item.coverage
            if str(entry.get("status") or "").strip().lower() in {"covered", "skipped"}
        }
        if settled_points:
            item.gaps = [
                gap for gap in list(item.gaps)
                if str(gap or "").strip().lower() not in settled_points
            ]
        for entry in normalized_coverage:
            if entry.get("status") == "gap":
                point = entry.get("point") or ""
                item.gaps = self._append_unique_text(list(item.gaps), [point])

        settled_rule = rule.strip()
        coverage_complete = self._coverage_complete(
            getattr(item, "coverage_points", []),
            getattr(item, "coverage", []),
        )
        requested_done = bool(
            (done and self._has_meaningful_coverage(getattr(item, "coverage", [])))
            or coverage_complete
        )
        turns_recorded = len(getattr(item, "talk", []) or [])
        min_turns = self._min_turns_for_item(item)
        min_turns_met = turns_recorded >= min_turns
        reached_limit = turns_recorded >= self._max_turns_per_item
        done = bool(requested_done and (min_turns_met or reached_limit))

        if not done and not reached_limit:
            depth_note = ""
            if requested_done and not min_turns_met:
                depth_note = (
                    f" Minimum evidence turns for this item are {min_turns}; "
                    f"{turns_recorded} recorded."
                )
            return ToolResult(
                observation=(
                    f"Answer recorded for {item.id}; the item remains open for another question."
                    f"{depth_note}"
                ),
                state_updates={
                    "elicitation_agenda": runtime.model_dump(),
                    "enduser_answer": "",
                    "current_question": "",
                    "_agenda_needs_question": True,
                },
                should_return=True,
            )

        item.rule = settled_rule or None
        item.status = "answered" if done else "partial"
        runtime.advance()
        next_item = runtime.current_item()

        status_text = "closed" if done else "marked partial at the item turn limit"
        return ToolResult(
            observation=f"Answer recorded and item {item.id} {status_text}.",
            state_updates={
                "elicitation_agenda": runtime.model_dump(),
                "enduser_answer": "",
                "current_question": "",
                "current_stakeholder_role": next_item.perspective if next_item else "",
                "item_turn_count": 0,
                "conversation": [],
                "_agenda_needs_question": True,
            },
            should_return=True,
        )

    def _tool_ask_question(
        self,
        message: str = "",
        state: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> ToolResult:
        state = state or {}
        # Orchestration guard: if a stakeholder answer is pending, the agent
        # must record it first; delivering a fresh question would silently
        # discard the prior turn's evidence.
        if (state.get("enduser_answer") or "").strip():
            return ToolResult(
                observation=(
                    "[ask_question] There is a pending stakeholder answer that has "
                    "not been recorded. Call record_answer first to persist signals, "
                    "assumption_evidence, and coverage; then ask the next question."
                ),
                should_return=False,
            )
        runtime = self._load_runtime(state)
        delivered = message.strip()
        if not delivered:
            return ToolResult(
                observation="[ask_question] message is empty. Ask exactly one open question for the current item.",
                should_return=False,
            )

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
                        "[conclude] Agenda is still open. Ask the next question "
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
                final_status: Literal["answered", "partial", "skipped"]
                if item.status in {"answered", "partial"}:
                    final_status = item.status
                else:
                    final_status = "skipped"
                record = ELRecord(
                    id=f"EL-{index:03d}",
                    item=item.id,
                    vision_refs=list(getattr(item, "vision_refs", []) or []),
                    perspective=item.perspective,
                    context=item.context,
                    decision_target=getattr(item, "decision_target", "") or None,
                    close_when=item.close_when,
                    coverage_points=list(getattr(item, "coverage_points", []) or []),
                    coverage=[
                        CoverageEntry(**entry)
                        for entry in (getattr(item, "coverage", []) or [])
                        if isinstance(entry, dict)
                    ],
                    signals=list(item.signals or []),
                    assumption_evidence=[
                        AssumptionEvidenceEntry(**entry)
                        for entry in (getattr(item, "assumption_evidence", []) or [])
                        if isinstance(entry, dict)
                    ],
                    gaps=list(item.gaps or []),
                    rule=item.rule,
                    talk=talk,
                    status=final_status,
                ).model_dump()
                records.append(record)
                if answer_text:
                    lines.append(
                        f"[{item.id}] {item.perspective}\n{answer_text}"
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

    # ── Runtime helpers ──────────────────────────────────────────────────────

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
    def _role_detail(vision: Dict[str, Any], perspective: str) -> str:
        lines: List[str] = []
        wanted = perspective.strip().lower()
        for role in (vision.get("roles") or []):
            if (role.get("name") or "").strip().lower() != wanted:
                continue
            if role.get("need"):
                lines.append(f"  Role need: {role.get('need', '')}")
            lens = role.get("lens") or ""
            anchor = role.get("anchor") or ""
            if lens or anchor:
                lines.append(f"  Role source: [{lens}] {anchor}".rstrip())
            break
        return "\n".join(lines)

    @staticmethod
    def _role_memory(runtime: AgendaRuntime, perspective: str, current_id: str) -> str:
        rules: List[str] = []
        answers: List[str] = []
        for item in runtime.items:
            if item.id == current_id:
                break
            if item.perspective != perspective:
                continue
            if item.rule:
                rules.append(item.rule)
            elif item.answer:
                answers.append(item.answer)
        lines: List[str] = []
        if rules:
            lines.append("  Settled evidence:")
            lines.extend(f"    - {rule}" for rule in rules[-4:])
        if answers:
            lines.append("  Prior answers:")
            lines.extend(f"    - {answer}" for answer in answers[-4:])
        return "\n".join(lines)

    @staticmethod
    def _vision_refs_detail(vision: Dict[str, Any], vision_refs: List[str]) -> str:
        if not vision_refs:
            return ""
        wanted = {ref.strip() for ref in vision_refs if ref and ref.strip()}
        if not wanted:
            return ""

        assumption_hits = [
            item for item in (vision.get("assumptions") or [])
            if item.get("id") in wanted
        ]
        concern_hits = [
            item for item in (vision.get("concerns") or [])
            if item.get("id") in wanted
        ]
        scope_hits = [
            item for item in (vision.get("scope") or [])
            if item.get("id") in wanted
        ]

        if not (assumption_hits or concern_hits or scope_hits):
            return ""

        def _source_line(item: Dict[str, Any]) -> str:
            lens = item.get("lens") or ""
            anchor = item.get("anchor") or ""
            if not lens and not anchor:
                return ""
            return f"    source: [{lens}] {anchor}".rstrip()

        lines = ["VISION ELEMENTS TO CLARIFY:"]
        for item in assumption_hits:
            lines.append(f"  - {item.get('id')} [assumption]: {item.get('statement', '')}")
            if item.get("why_it_matters"):
                lines.append(f"    why_it_matters: {item.get('why_it_matters')}")
            source_line = _source_line(item)
            if source_line:
                lines.append(source_line)
        for item in concern_hits:
            lines.append(f"  - {item.get('id')} [concern]: {item.get('theme', '')}")
            if item.get("rationale"):
                lines.append(f"    rationale: {item.get('rationale')}")
            source_line = _source_line(item)
            if source_line:
                lines.append(source_line)
        for item in scope_hits:
            lines.append(f"  - {item.get('id')} [scope]: {item.get('item', '')}")
            if item.get("reason"):
                lines.append(f"    reason: {item.get('reason')}")
            source_line = _source_line(item)
            if source_line:
                lines.append(source_line)
        return "\n".join(lines)

    def _build_task(self, state: Dict[str, Any]) -> str:
        runtime = self._load_runtime(state)
        vision = (
            (state.get("artifacts") or {}).get("reviewed_product_vision")
            or state.get("product_vision")
            or {}
        )

        if runtime is None:
            return "Agenda runtime is unavailable. Do not fabricate; await orchestration."
        if runtime.elicitation_complete:
            return "AGENDA STATUS: COMPLETE\nAll agenda items are complete. Call conclude."

        item = runtime.current_item()
        if item is None:
            return "AGENDA STATUS: COMPLETE\nAgenda is complete. Call conclude."

        answered = sum(1 for agenda_item in runtime.items if agenda_item.status in {"answered", "partial"})
        total = len(runtime.items)
        role_detail = self._role_detail(vision, item.perspective)
        role_memory = self._role_memory(runtime, item.perspective, item.id)
        assumption_detail = self._vision_refs_detail(
            vision,
            list(getattr(item, "vision_refs", []) or []),
        )
        pending = bool((state.get("enduser_answer") or "").strip())

        sections = [
            "AGENDA STATUS: OPEN",
            "Conclude is forbidden while this status is OPEN. Work only on the current item.",
            "",
            f"AGENDA: {answered}/{total} items closed or partial.",
            "",
            "CURRENT ITEM:",
            f"  id: {item.id}",
            f"  vision_refs: {', '.join(getattr(item, 'vision_refs', []) or []) or '(none)'}",
            f"  decision_target: {getattr(item, 'decision_target', '') or '(not provided)'}",
            f"  perspective: {item.perspective}",
            "",
            "PERSPECTIVE CONTEXT:",
            role_detail or "  (no extra role detail)",
        ]
        if assumption_detail:
            sections.extend(["", assumption_detail])
        if role_memory:
            sections.extend(["", "SESSION MEMORY:", role_memory])

        coverage_points = list(getattr(item, "coverage_points", []) or [])
        min_turns = self._min_turns_for_item(item)
        turns_recorded = len(getattr(item, "talk", []) or [])
        sections.extend([
            "",
            "FOCUS CONTEXT:",
            f"  {item.context}",
            "",
            "PRIVATE INTERVIEWER CONTEXT:",
            f"  seed_question: {item.seed_question}",
            f"  close_when: {item.close_when}",
            "  coverage_points:",
            *(
                [f"    - {point}" for point in coverage_points]
                if coverage_points
                else ["    - (not provided; use close_when as the fallback stop condition)"]
            ),
            f"  notes: {item.notes or '(not provided)'}",
            "",
            "TURN STATUS:",
            f"  Turn count for item: {state.get('item_turn_count', 0)}",
            f"  Recorded answer turns for item: {turns_recorded}",
            f"  Minimum evidence turns for this item: {min_turns}",
            f"  Minimum evidence turns met: {'yes' if turns_recorded >= min_turns else 'no'}",
            f"  Item turn limit: {self._max_turns_per_item}",
            f"  Pending answer: {'yes' if pending else 'no'}",
        ])

        conversation = state.get("conversation") or []
        if conversation:
            sections.extend(["", "CURRENT DIALOGUE:"])
            for turn in conversation[-8:]:
                sections.append(
                    f"  [{str(turn.get('role', '')).upper()}] {turn.get('content', '')}"
                )
        if pending:
            sections.extend(["", "PENDING ANSWER:", f"  {state.get('enduser_answer', '')}"])
        coverage = list(getattr(item, "coverage", []) or [])
        if coverage:
            sections.extend(["", "COVERAGE SO FAR:"])
            for entry in coverage:
                if not isinstance(entry, dict):
                    continue
                point = entry.get("point", "")
                status = entry.get("status", "")
                evidence = entry.get("evidence", "")
                suffix = f" — {evidence}" if evidence else ""
                sections.append(f"  - {status}: {point}{suffix}")
        assumption_evidence = list(getattr(item, "assumption_evidence", []) or [])
        if assumption_evidence:
            sections.extend(["", "ASSUMPTION EVIDENCE SO FAR:"])
            for entry in assumption_evidence:
                if not isinstance(entry, dict):
                    continue
                ref = entry.get("vision_ref") or entry.get("assumption_ref", "")
                stance = entry.get("stance", "")
                evidence = entry.get("evidence", "")
                implication = entry.get("implication", "")
                sections.append(f"  - {ref} {stance}: {evidence} -> {implication}")

        return "\n".join(sections)

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        # Orchestration decides which tool the LLM must call this turn. The
        # condition is deterministic; the reasoning (signals / coverage /
        # assumption_evidence / question wording) is still done by the LLM.
        #   pending answer + agenda open       → record_answer
        #   pending answer + agenda complete   → record_answer (persist first)
        #   no pending     + agenda complete   → conclude
        #   no pending     + agenda open       → ask_question
        runtime = self._load_runtime(state)
        pending = bool((state.get("enduser_answer") or "").strip())
        agenda_complete = bool(runtime is not None and runtime.elicitation_complete)

        def _force(tool_name: str) -> Dict[str, Any]:
            return {"type": "function", "function": {"name": tool_name}}

        if pending:
            tool_choice: Any = _force("record_answer")
        elif agenda_complete:
            tool_choice = _force("conclude")
        else:
            tool_choice = _force("ask_question")

        return self.react(
            state=state,
            task=self._build_task(state),
            tool_choice=tool_choice,
            profile_addendum=_REACT_ADDENDUM,
            include_memory=False,
        )
