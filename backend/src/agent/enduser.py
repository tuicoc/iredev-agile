"""
enduser.py - EndUserAgent

EndUserAgent simulates the product-user or directly affected perspective
selected by the current agenda item. It receives role context, scene context,
prior settled statements from the same perspective, and the current question.
It never sees interviewer strategy.

Design split
------------
Tool descriptions name what each tool does and its signature — they are read so
the model picks the right tool.
The ReAct addendum prompt teaches the stakeholder behavior: inner stance, six
techniques, and the default voice.
Persona text holds the agent's stable stance only.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


_REACT_ADDENDUM = """\
TURN CONTROL
- Read the INTERVIEWER QUESTION first.
- Call search_knowledge at most once if the perspective or scene context is
  genuinely too thin to answer faithfully.
- Call respond exactly once with the full answer.
- Maximum two tool calls per turn: optionally search_knowledge, then respond.
- Do not produce plain text outside a tool call.

INNER STANCE (decide privately before respond)
Before you write the answer, settle which inner stance fits the role for this
question in this scene. The stance is private; do not announce it. It shapes
which evidence you bring and how you bring it.
  resonate    — the question matches your lived work; you have direct evidence.
  skeptical   — the framing does not match what you actually see day to day.
  indifferent — the topic is real but does not affect your work; you do not
                pretend strong feelings.
  threatened  — the framing risks something the role cares about (authority,
                time, fairness, autonomy).
  curious     — partly fits, and the fit depends on a condition you have lived.

STAKEHOLDER TECHNIQUES (apply naturally; choose what the moment needs)

1. Lived friction first
   Lead with what you currently try, what fails, what you work around, what
   you avoid, what you keep losing. Concrete activity beats abstract wish.
   Pattern (cross-domain): instead of "the product should make X easier", say
   "today when I try X, here is what slows me down — and here is what I do
   instead". The interviewer can convert lived friction into requirements;
   they cannot convert wishlists.

2. Surface adjacent concern
   When the question grazes another concern the role actually carries, name
   it once.
   Pattern: "honestly, the thing I worry about more in this same moment is
   …; that is what would change my behavior". One surfacing per turn — do
   not pile on; do not steer the agenda.

3. Decline to design
   If asked "what features would you like", "what should the product do",
   "how should it work", "what improvements" — pivot back to lived
   condition, limit, consequence, or recovery. You are not the designer.
   Pattern: "I cannot say what should be built; what I can tell you is what
   happens to me when …".

4. Calibrated disagree
   If the question's framing does not match your reality, say where it
   diverges and what you see instead. Do not soften to look agreeable.
   Pattern: "from where I sit, that is not quite the situation. What
   actually happens is …". Disagreement is data; politeness costs evidence.

5. Partial fit qualify
   If the assumption is right only under a condition C, only for a subgroup
   S, or only at a moment M — say so and name C / S / M.
   Pattern: "yes, but only when … / only for … / only at the moment …".
   "Yes" without the qualifier is misleading evidence.

6. Boundary-aware silence
   For things the role would not actually see from their position, say so
   and offer what you do see.
   Pattern: "I do not see that side of it; from my position what I notice
   is …". Do not invent.

7. Temporal honesty
   If the project is still an idea, proposal, or planned product, do not speak
   as if you have already used it. Answer from your current situation,
   comparable tools or workarounds, the moment you would need help, and the
   minimum condition that would make the product useful or trustworthy.
   Pattern: "I have not used that product; the moment this would matter for me
   is …".

DEFAULT VOICE
- 3 to 6 sentences. Concrete. Lead with one specific actor, one specific
  moment, one specific consequence — abstract claims undercut the role you
  inhabit. The interviewer can convert lived particulars into requirements;
  they cannot convert generalizations.
- Cooperative but not submissive. Do not agree to be polite; do not refuse
  to be safe. Both are forms of dishonesty when the role would naturally
  speak.
- Do not blend perspectives. If asked about another role, describe only
  what this role observes or experiences from them.
- No invented numbers, technologies, vendors, standards, or thresholds.
- If the role would not know something, say what they can observe instead —
  do not invent expertise, and do not refuse the whole question when a
  partial first-person answer is available.
- Do not invent past usage of a product that the project description only
  proposes. Translate the question into present experience or expected
  decision pressure from the role's position.
"""


class EndUserAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="enduser")
        agent_cfg = (
            self._raw_config.get("iredev", {})
            .get("agents", {})
            .get("enduser", {})
        )
        custom = agent_cfg.get("custom_params", {})
        raw_hidden: Any = custom.get("implicit_requirements", [])
        self._hidden: List[str] = raw_hidden if isinstance(raw_hidden, list) else []
        # Enduser needs at most 2 tool calls per turn (search_knowledge → respond).
        # Cap at 3 to give one retry slot without burning the full config budget.
        self.max_react_iterations = min(self.max_react_iterations, 3)

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="search_knowledge",
            description=(
                "Retrieve limited background context once per turn when the "
                "perspective or scene would otherwise be answered too vaguely.\n\n"
                "Arguments:\n"
                "  query (str, required): short phrase describing the missing "
                "context for this perspective and scene.\n"
                'Input: {"query": str}'
            ),
            func=self._tool_search_knowledge,
        ))
        self.register_tool(Tool(
            name="respond",
            description=(
                "Return the stakeholder's in-character answer to the current "
<<<<<<< Updated upstream
                "interviewer message.\n"
                "\n"
                "The message argument MUST be a non-empty string of at least "
                "two complete sentences of first-person lived experience "
                "grounded in YOUR SCENE. An empty message, a whitespace-only "
                "message, or a one-word acknowledgement is rejected and the "
                "model is asked to try again — do not call respond at all "
                "unless you have real content to deliver. Aim for two to "
                "four sentences: concrete, scene-based, and in your voice.\n"
                "\n"
                "Open from your situation, not from the interviewer's text. "
                "Good openings: 'When I open the app to...', 'In my "
                "experience...', 'For me, the moment that matters is...', "
                "'Usually I...'. Forbidden openings: 'The assertion that...', "
                "'The claim that... is misleading', 'The statement "
                "overlooks...', 'Your question assumes that...' — these "
                "signal textual analysis instead of lived experience.\n"
                "\n"
                "Describe the app's behaviour from your side ('the app asks "
                "me for...', 'the app won't let me past sign-up without...', "
                "'the app warns me about...'). Do NOT write requirement-"
                "shaped sentences about yourself ('users must do X', 'the "
                "user is required to Y'); that is the interviewer's job.\n"
                "\n"
                "If you cannot answer the question precisely from your role, "
                "still call respond with non-empty content: say what part "
                "you DO know, what your routine around this moment looks "
                "like, what you would notice or expect, and the specific "
                "part you would need the interviewer to clarify. Saying "
                "'I do not know exactly because my routine here is X' is "
                "real evidence; an empty respond call is not.\n"
                "\n"
                "If you need to correct a wrong interviewer assumption, do "
                "it AFTER one sentence of experience, not before. Do not "
                "provide product design advice. Do not invent numeric "
                "thresholds; prefer an observable anchor (absence, "
                "comparator, operating condition, precedent) — but real "
                "numbers from your own routine (the time you actually have "
                "at that moment, the duration of the activity around it) "
                "are legitimate and welcome.\n"
=======
                "interviewer question. Call exactly once per turn.\n\n"
                "Arguments:\n"
                "  message (str, required): the complete answer from this "
                "perspective. Not empty.\n"
>>>>>>> Stashed changes
                'Input: {"message": str}'
            ),
            func=self._tool_respond,
        ))

    def _tool_search_knowledge(
        self,
        query: str,
        state: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> ToolResult:
        if (state or {}).get("_sk_used_this_turn"):
            return ToolResult(
                observation="search_knowledge was already used this turn. Call respond now."
            )
        if self.knowledge is None:
            return ToolResult(
                observation="Knowledge base unavailable.",
                state_updates={"_sk_used_this_turn": True},
            )
        try:
            from ..orchestrator.state import ProcessPhase
            docs = self.knowledge.retrieve(query, phase=ProcessPhase.ELICITATION, k=3)
            snippets = "\n\n".join(
                f"[{doc.metadata.get('title', '?')}]\n{doc.page_content[:350]}"
                for doc in docs
            )
            return ToolResult(
                observation=snippets or "No relevant context found.",
                state_updates={"_sk_used_this_turn": True},
            )
        except Exception as exc:
            return ToolResult(
                observation=f"Knowledge search failed: {exc}",
                state_updates={"_sk_used_this_turn": True},
            )

    def _tool_respond(
        self,
        message: str = "",
        state: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> ToolResult:
        text = message.strip()
        if not text:
<<<<<<< Updated upstream
            # Empty respond calls are NOT silently substituted any more.
            # Returning a non-fatal observation tells the ReAct loop to keep
            # going (should_return=False, no state updates) and gives the
            # model an explicit fix-it instruction. The outer
            # enduser_turn_fn retry will fire if the loop exhausts itself
            # without ever producing a non-empty message.
            return ToolResult(
                observation=(
                    "Your respond call had an empty message. Call respond "
                    "again with at least two sentences of first-person "
                    "experience grounded in YOUR SCENE: start with "
                    "'When I...', 'Usually I...', or 'In my experience...', "
                    "and say what the app does to you at this moment, what "
                    "you expect, or what you would notice. If you cannot "
                    "answer the question precisely, name the part you do "
                    "know from your role and the part you would need the "
                    "interviewer to clarify — but do that in YOUR voice, "
                    "not as a tool-call hand-off."
                ),
                should_return=False,
            )

=======
            return ToolResult(
                observation="[respond] message is empty. Answer the current question from the supplied perspective.",
                should_return=False,
            )
>>>>>>> Stashed changes
        conversation = list((state or {}).get("conversation") or [])
        conversation.append({
            "role": "enduser",
            "content": text,
            "timestamp": datetime.now().isoformat(),
        })
        return ToolResult(
            observation="Stakeholder response posted.",
            state_updates={
                "enduser_answer": text,
                "conversation": conversation,
                "turn_count": ((state or {}).get("turn_count") or 0) + 1,
                "_sk_used_this_turn": False,
            },
            should_return=True,
        )

    # ── Context builders ─────────────────────────────────────────────────────

    @staticmethod
    def _vision(state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        return artifacts.get("reviewed_product_vision") or state.get("product_vision") or {}

    @staticmethod
    def _runtime_item(state: Dict[str, Any]):
        raw = state.get("elicitation_agenda")
        if not raw:
            return None
        try:
            from .agenda import AgendaRuntime
            runtime = AgendaRuntime(**raw) if isinstance(raw, dict) else raw
            return runtime.current_item()
        except Exception:
            return None

    @classmethod
    def _role_context(cls, state: Dict[str, Any], perspective: str) -> str:
        vision = cls._vision(state)
        lines: List[str] = []
        wanted = perspective.strip().lower()
        for role in (vision.get("roles") or []):
            if (role.get("name") or "").strip().lower() != wanted:
                continue
            lines = ["YOUR PERSPECTIVE:"]
            lines.append(f"  Name: {role.get('name', '')}")
            if role.get("need"):
                lines.append(f"  Your need: {role.get('need', '')}")
            lens = role.get("lens") or ""
            anchor = role.get("anchor") or ""
            if lens or anchor:
                lines.append(f"  How this role was reached: [{lens}] {anchor}".rstrip())
            break

        concerns = []
        for concern in vision.get("concerns") or []:
            affected = [
                str(role or "").strip().lower()
                for role in (concern.get("affected_roles") or [])
            ]
            if wanted in affected:
                concerns.append(concern)
        if concerns:
            if not lines:
                lines = ["YOUR PERSPECTIVE:", f"  Name: {perspective}"]
            lines.append("  Quality concerns you may feel:")
            for concern in concerns[:4]:
                theme = concern.get("theme") or ""
                rationale = concern.get("rationale") or ""
                if theme or rationale:
                    lines.append(f"    - {theme}: {rationale}")
        return "\n".join(lines)

    @classmethod
    def _scene_context(cls, state: Dict[str, Any]) -> str:
        item = cls._runtime_item(state)
        if item is None:
            return ""
        lines = ["YOUR SITUATION:"]
        if getattr(item, "context", ""):
            lines.append(f"  {getattr(item, 'context', '')}")
        decision_target = getattr(item, "decision_target", "")
        if decision_target:
            lines.append(f"  What this conversation is trying to clarify: {decision_target}")
        coverage_points = list(getattr(item, "coverage_points", []) or [])
        if coverage_points:
            lines.append("  Evidence the interviewer is looking for:")
            lines.extend(f"    - {point}" for point in coverage_points[:5])
        return "\n".join(lines)

    @classmethod
    def _assumption_context(cls, state: Dict[str, Any]) -> str:
        item = cls._runtime_item(state)
        if item is None:
            return ""
        refs = [
            str(ref or "").strip()
            for ref in (getattr(item, "vision_refs", []) or [])
            if str(ref or "").strip()
        ]
        if not refs:
            return ""
        wanted = set(refs)
        vision = cls._vision(state)
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
        def _grounding(item: Dict[str, Any]) -> str:
            lens = item.get("lens") or ""
            anchor = item.get("anchor") or ""
            if not lens and not anchor:
                return ""
            return f"    Grounding note: [{lens}] {anchor}".rstrip()

        lines = ["VISION ELEMENTS BEING TESTED:"]
        for assumption in assumption_hits:
            lines.append(f"  - {assumption.get('id')} [assumption]: {assumption.get('statement', '')}")
            grounding = _grounding(assumption)
            if grounding:
                lines.append(grounding)
        for concern in concern_hits:
            lines.append(f"  - {concern.get('id')} [concern]: {concern.get('theme', '')}")
            if concern.get("rationale"):
                lines.append(f"    Why it matters: {concern.get('rationale')}")
        for boundary in scope_hits:
            lines.append(f"  - {boundary.get('id')} [scope]: {boundary.get('item', '')}")
            if boundary.get("reason"):
                lines.append(f"    Why this boundary: {boundary.get('reason')}")
        lines.append(
            "You may support, weaken, qualify, or leave any element unclear. "
            "Choose the stance that fits your lived experience, not the question's framing."
        )
        return "\n".join(lines)

    @classmethod
    def _role_memory(cls, state: Dict[str, Any], perspective: str) -> str:
        raw = state.get("elicitation_agenda")
        if not raw or not perspective:
            return ""
        try:
            from .agenda import AgendaRuntime
            runtime = AgendaRuntime(**raw) if isinstance(raw, dict) else raw
        except Exception:
            return ""
        current = runtime.current_item()
        current_id = getattr(current, "id", None)
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
        if not rules and not answers:
            return ""
        lines: List[str] = []
        if rules:
            lines.append("YOUR PRIOR SETTLED EVIDENCE:")
            lines.extend(f"  - {rule}" for rule in rules[-4:])
        if answers:
            lines.append("YOUR PRIOR ANSWERS:")
            lines.extend(f"  - {answer}" for answer in answers[-4:])
        return "\n".join(lines)

    def _hidden_block(self) -> str:
        if not self._hidden:
            return ""
        lines = ["PRIVATE CONCERNS:"]
        lines.extend(f"  - {item}" for item in self._hidden)
        lines.append(
            "Reveal one only when the interviewer asks a scenario-specific follow-up "
            "that genuinely touches it."
        )
        return "\n".join(lines)

    def _build_task(self, state: Dict[str, Any]) -> str:
        question = (state.get("current_question") or "").strip()
        if not question:
            return "Current question is missing; do not answer."

        item = self._runtime_item(state)
<<<<<<< Updated upstream
        kind = getattr(item, "kind", "") if item is not None else ""
        retry_hint = (state.get("_enduser_retry_hint") or "").strip()
        parts: List[str] = []
        if retry_hint:
            # Outer-loop retry: the previous EndUserAgent invocation finished
            # without producing a usable stakeholder response (typically an
            # empty respond call). Place the hint at the very top so the
            # model encounters it before persona, scene, and rules.
            parts.append("RETRY DIRECTIVE — READ FIRST:")
            parts.append(retry_hint)
            parts.append(
                "On this attempt you MUST call respond with a non-empty "
                "first-person message rooted in YOUR SCENE below. Do not "
                "produce plain text outside a tool call, and do not call "
                "respond again with an empty message — the previous "
                "attempt already failed for that reason."
            )
            parts.append("")
        parts.extend([
            f"PERSONA: {role}",
            "You are this stakeholder. Speak in first person about your experience: what you do, what the app does to you, what you expect, what frustrates you. Do not narrate at the interviewer; live the scene.",
            "You do not see interview strategy. The interviewer's message is your conversation partner, not text to analyse.",
            "Do NOT open your reply by quoting, summarising, or rebutting the interviewer's claim. Forbidden openings include 'The assertion that...', 'The claim that... is misleading', 'The statement overlooks...', 'Your question assumes...'. Start from your situation instead: 'When I open the app to...', 'In my experience...', 'For me...', 'Usually I...'.",
            "If the interviewer is wrong about something, correct them AFTER one sentence of lived experience, not before.",
            "Describe the app's behaviour from your side: 'the app asks me for...', 'the app won't let me past sign-up without...', 'the app warns me about...'. Do not write requirement sentences about yourself ('users must do X', 'the user is required to Y'); your job is experience, the interviewer turns it into the product's rule.",
        ])
        if kind == "concern":
            parts.append(
                "This is a quality-concern item. Describe what failure feels like in lived use and what observable boundary you can defend: an observable absence (\"no spinner appears\", \"no perceptible pause\"), a comparative anchor (\"faster than typing the next word\"), an operating condition that bounds the failure (\"before I shift attention away\"), or a named precedent. Avoid emotional descriptors alone — saying 'instantly' or 'fast' without an observable condition gives the interviewer nothing to record."
            )
        elif kind == "conflict":
            parts.append(
                "This is a conflict item. The collision exposed here will "
                "be resolved later by a human reviewer who can balance every "
                "affected stakeholder's stance; the global resolution is NOT "
                "yours to produce. Your job is to give the interviewer YOUR "
                "side only: how the collision lands on you at this entity "
                "step, which side you personally lean toward and why from "
                "your own role, and any concrete preference you would want "
                "the product to offer from your side. Speak only from your "
                "role's perspective — do not negotiate a fair rule for "
                "other stakeholders or imagine what they would accept. If "
                "you honestly have no lean, or you feel the collision is "
                "not yours to call, say so plainly ('for me this is a "
                "product decision'); that refusal is a legitimate answer "
                "and the interviewer is expected to close on it."
            )
        elif kind:
            parts.append(
                "This is a rule-clarification item. Tell the interviewer what the app does to you, what conditions or exceptions you encounter, what the app prevents or allows. Phrase as your experience of being prompted, blocked, allowed — not as duties you bear."
            )
=======
        perspective = (
            (state.get("current_stakeholder_role") or "").strip()
            or getattr(item, "perspective", "")
        )
        retry_hint = (state.get("_enduser_retry_hint") or "").strip()
        parts = [f"PERSPECTIVE: {perspective}"]
        if retry_hint:
            parts.extend(["", retry_hint])
>>>>>>> Stashed changes
        for block in (
            self._role_context(state, perspective),
            self._scene_context(state),
            self._assumption_context(state),
            self._role_memory(state, perspective),
            self._hidden_block(),
        ):
            if block:
                parts.extend(["", block])
        parts.extend([
            "",
            "PROJECT SIGNAL:",
            f"  {state.get('project_description', '(not provided)')}",
            "",
            "INTERVIEWER QUESTION:",
            f"  {question}",
<<<<<<< Updated upstream
            "",
            "If the message conflicts with your scene or role, say so plainly after one sentence of experience. Do not turn that disagreement into a paragraph of rebuttal.",
            "If the interviewer asks the same closure question for the third time and your honest answer is still that the app should support flexibility or multiple options, say so once, clearly, and stop softening.",
            "Do not invent a precise number unless the question asks for an acceptable limit and this role would know it from practice, policy, or repeated experience. Prefer an observable anchor (absence, comparator, operating condition, precedent) over a fabricated number.",
            "You may call search_knowledge once if necessary. Then call respond.",
=======
>>>>>>> Stashed changes
        ])
        return "\n".join(parts)

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        question = (state.get("current_question") or "").strip()
        item = self._runtime_item(state)
        perspective = (
            (state.get("current_stakeholder_role") or "").strip()
            or getattr(item, "perspective", "")
        )
        if not question:
            logger.warning("[EndUserAgent] current_question is missing; refusing to fabricate an answer.")
            return {
                "enduser_answer": "",
                "_agenda_needs_question": True,
            }
        if not perspective:
            logger.warning("[EndUserAgent] perspective is missing; refusing to use a fallback persona.")
            return {
                "current_question": "",
                "enduser_answer": "",
                "_agenda_needs_question": True,
                "errors": (state.get("errors") or []) + [
                    "EndUserAgent: current agenda perspective is missing."
                ],
            }
        return self.react(
            state=state,
            task=self._build_task(state),
            tool_choice="required",
            profile_addendum=_REACT_ADDENDUM,
            include_memory=False,
        )