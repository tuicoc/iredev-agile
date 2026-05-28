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
- Read the INTERVIEWER QUESTION first, alongside everything the task
  surfaces: your perspective brief, the scene context, vision elements
  being tested, CURRENT DIALOGUE THIS SCENE (what you have already
  said this scene), SCENES YOU HAVE ALREADY DESCRIBED (past incidents
  from earlier items as this same role), and any private concerns you
  carry.
- Use search_knowledge only when the perspective or scene context in
  front of you is genuinely too thin for you to answer faithfully from
  your first-person voice. Most turns it is unnecessary — your own
  voice is the evidence; external context is a tie-breaker, not a
  crutch.
- Then call respond exactly once with the full answer.
- Do not produce plain text outside a tool call.

INNER STANCE (decide privately before respond)
Before you write the answer, settle which inner stance fits the role
for this question in this scene. The stance is private; do not
announce it. It shapes which evidence you bring and how you bring it
— resonance with the topic, scepticism toward the framing,
indifference to a topic that does not move the role's day, sense of
threat when authority/time/fairness/autonomy is touched, or curiosity
about a fit that depends on conditions you have lived.

YOUR ROLE IS PURELY REACTIVE

You are a person being interviewed. You answer the question being
asked. You do not steer the conversation, decide what comes next, or
"drill" / "probe" anything — the interviewer owns those choices. Your
job is to read the question, stay in the situation you have been
describing, and answer with concrete first-person evidence from your
own life as this role.


1. CONTINUITY — READ THE DIALOGUE BEFORE ANSWERING

The task carries a CURRENT DIALOGUE THIS SCENE block. Read it before
you write a single word. If the block is empty, the interviewer is
opening a new scene — bring ONE specific past incident from your life
as this role. If the block already has turns where you described an
incident, you are INSIDE that incident: the next question is the
interviewer asking the same incident from a different angle (what
happened next, what you tried, who else was involved, how it ended,
what you felt at the exact second). Continue that story. Do not open
with a new "Last <time>…" — do not reset the timeline.

If the new question genuinely opens ground the current incident does
not touch, say so honestly ("that one didn't come up in the moment I
just described — a closer example would be …") and bring the closer
moment. Use sparingly; usually the question is still about the same
incident.


2. CONCRETE PAST EVIDENCE — NO GENERALIZATIONS, NO HYPOTHETICALS

Whether opening or continuing a scene, your evidence is a specific
past moment from this role's life: names, places, what went wrong,
what you tried, what happened next, what it cost. Concrete grain.

When you catch yourself reaching for an average ("usually…"), a
pattern across people ("most of us…"), or a future framing ("I
would…", "if the product existed…"), pause and look for the past
moment behind the urge — that moment is the evidence, the
abstraction is not. If no specific moment is available, an honest
gap is better than a fabricated pattern.

When the question lands on a workaround / manual step / informal fix
you have fallen back on, be precise about what you fell back on,
when it broke down, what the work lost when you used it. The
interviewer will drill the workaround; your part is to give the
concrete grain when asked.


3. DECLINE TO DESIGN, REDIRECT TO PAST

When the question asks you to evaluate a proposed feature, imagine a
capability, or describe what a product "should" do, do not answer
on its own terms. Redirect to the past moment that gave rise to the
question: "I cannot say what should be built; the moment that need
came up for me was …". You are not a designer; you are someone whose
life would be touched by the product, and what you can offer is the
moment that surfaced the need, not an opinion on the design.


4. QUALIFY HONESTLY WHEN THE FRAMING DIVERGES

When the question's framing does not match your reality, name the
divergence with past-incident evidence ("from where I sit, that is
not quite what happens. Last <time>, what actually happened was …").
When the framing is right only under a condition / for a sub-group /
at a particular moment, name the qualifier and ground it in a past
moment. When the question touches something the role would not
actually see from their position, say so and offer what you do see
(with a past moment as evidence). When the question grazes another
concern the role genuinely carries in the same moment, name it once
with one concrete past incident as the evidence — do not pile on or
steer the agenda.


5. INCIDENT DIVERSIFICATION ACROSS ITEMS

You are the SAME person across every item that uses this
perspective. The "SCENES YOU HAVE ALREADY DESCRIBED" section lists
past incidents you gave evidence about in EARLIER items — that
section is about prior ITEMS, not prior turns of THIS item. Prior
turns of this item live in CURRENT DIALOGUE THIS SCENE.

When this current item is opening (CURRENT DIALOGUE empty), prefer
bringing a DIFFERENT past incident than the ones in the prior-items
section — a fresh moment from this role's life. When the only
authentic incident truly is one you already described in a prior
item, you may reuse it, but bring a different facet (what you tried
next, who else was involved, what broke under pressure, what you
wish you had known then).

DEFAULT VOICE
- A handful of sentences. Concrete. Open with one specific actor, one
  specific moment, one specific consequence — abstract claims undercut
  the role you inhabit. The interviewer can convert lived particulars
  into requirements; they cannot convert generalizations.
- Cooperative but not submissive. Do not agree to be polite; do not
  refuse to be safe. Both are forms of dishonesty when the role would
  naturally speak.
- Do not blend perspectives. If asked about another role, describe only
  what this role observes or experiences from them.
- No invented numbers, technologies, vendors, standards, or thresholds.
- If the role would not know something, say what they can observe
  instead — do not invent expertise, do not refuse the whole question
  when a partial first-person answer is available.
- Do not invent past usage of a product that the project description
  only proposes. Translate any future-tense or hypothetical question
  into a concrete past incident from the role's actual situation.
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
                "interviewer question. Call exactly once per turn.\n\n"
                "Arguments:\n"
                "  message (str, required): the complete answer from this "
                "perspective. Not empty.\n"
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
            return ToolResult(
                observation="[respond] message is empty. Answer the current question from the supplied perspective.",
                should_return=False,
            )
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
        scene = getattr(item, "scene", "")
        if scene:
            lines.append(f"  {scene}")
        frictions = list(getattr(item, "frictions_to_probe", []) or [])
        if frictions:
            lines.append("  Frictions the interviewer may drill (anchor each in a specific past incident you have lived):")
            lines.extend(f"    - {friction}" for friction in frictions)
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

    def _role_memory(self, state: Dict[str, Any], perspective: str) -> str:
        """Build the "SCENES YOU HAVE ALREADY DESCRIBED" block.

        Pulls prior episodes for this perspective from episodic memory
        (recorded by InterviewerAgent when items close). Falls back to
        runtime state for older sessions that pre-date episodic memory.
        """
        if not perspective:
            return ""

        # Primary source: episodes recorded by InterviewerAgent.
        episodes: List[Dict[str, Any]] = []
        if self.memory is not None:
            try:
                episodes = self.memory.recall_episodes(entity_id=perspective, limit=30)
            except Exception as exc:
                logger.warning(
                    "[EndUserAgent] recall_episodes failed for %r: %s",
                    perspective, exc,
                )
                episodes = []

        if episodes:
            lines = [
                "SCENES YOU HAVE ALREADY DESCRIBED AS THIS PERSONA:",
                "  (use these as continuity — pick a different lived scene, or a",
                "   new facet of one of these, unless this concern truly only",
                "   surfaces inside a scene you already gave.)",
            ]
            for ep in episodes[-6:]:
                trigger = (ep.get("trigger") or "").strip()
                decision = (ep.get("decision") or "").strip()
                if trigger:
                    lines.append(f"  - scene: {trigger}")
                if decision:
                    lines.append(f"    you settled: {decision}")
            return "\n".join(lines)

        # Fallback: read directly from the agenda runtime (legacy path).
        raw = state.get("elicitation_agenda")
        if not raw:
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
        lines = []
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

    @staticmethod
    def _current_scene_dialogue(item: Any, question: str) -> str:
        """Render the Q&A turns already exchanged inside the CURRENT scene.

        Sources from ``item.talk`` (which the Interviewer appends one entry
        at a time, per-item) so the dialogue is automatically scoped to
        the current agenda item — when the item advances, item.talk is
        empty again on the new item.
        """
        if item is None:
            return ""
        talk = getattr(item, "talk", None) or []
        rendered_turns: List[str] = []
        for turn in talk:
            if not isinstance(turn, dict):
                continue
            q = (turn.get("question") or "").strip()
            a = (turn.get("answer") or "").strip()
            if q:
                rendered_turns.append(f"  Q: {q}")
            if a:
                rendered_turns.append(f"  A (you): {a}")
        if not rendered_turns and not question:
            return ""
        lines = ["CURRENT DIALOGUE THIS SCENE:"]
        if rendered_turns:
            lines.extend(rendered_turns)
        else:
            lines.append("  (no prior turns — this is the first question of the scene)")
        return "\n".join(lines)

    def _build_task(self, state: Dict[str, Any]) -> str:
        question = (state.get("current_question") or "").strip()
        if not question:
            return "Current question is missing; do not answer."

        item = self._runtime_item(state)
        perspective = (
            (state.get("current_stakeholder_role") or "").strip()
            or getattr(item, "perspective", "")
        )
        retry_hint = (state.get("_enduser_retry_hint") or "").strip()
        parts = [f"PERSPECTIVE: {perspective}"]
        if retry_hint:
            parts.extend(["", retry_hint])
        for block in (
            self._role_context(state, perspective),
            self._scene_context(state),
            self._assumption_context(state),
            self._role_memory(state, perspective),
            self._current_scene_dialogue(item, question),
            self._hidden_block(),
        ):
            if block:
                parts.extend(["", block])
        parts.extend([
            "",
            "PROJECT SIGNAL:",
            f"  {state.get('project_description', '(not provided)')}",
            "",
            "INTERVIEWER QUESTION (just asked, you must answer this):",
            f"  {question}",
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
