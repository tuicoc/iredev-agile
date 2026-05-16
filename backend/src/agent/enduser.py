"""
enduser.py - EndUserAgent

EndUserAgent simulates the stakeholder role selected by the current agenda item.
It receives role context, scene context, current question, and prior statements
from the same role. It never sees interviewer-private trap fields.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


class EndUserAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="enduser")
        agent_cfg = (
            self._raw_config.get("iredev", {})
            .get("agents", {})
            .get("enduser", {})
        )
        custom = agent_cfg.get("custom_params", {})
        self._persona: str = custom.get("persona", "business stakeholder")
        raw_hidden: Any = custom.get("implicit_requirements", [])
        self._hidden: List[str] = raw_hidden if isinstance(raw_hidden, list) else []

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="search_knowledge",
            description=(
                "Retrieve limited background context when the current stakeholder role "
                "or product scene would otherwise be answered too vaguely. Use at most "
                "once in a turn, then call respond.\n"
                'Input: {"query": str}'
            ),
            func=self._tool_search_knowledge,
        ))
        self.register_tool(Tool(
            name="respond",
            description=(
                "Return the stakeholder's in-character answer to the current "
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
    def _role_context(cls, state: Dict[str, Any], role_name: str) -> str:
        for role in (cls._vision(state).get("roles") or []):
            if role.get("name", "").strip().lower() != role_name.strip().lower():
                continue
            lines = ["YOUR ROLE:"]
            lines.append(f"  Name: {role.get('name', '')}")
            lines.append(f"  Kind: {role.get('kind', '')}")
            duties = role.get("duties") or []
            if duties:
                lines.append("  Duties:")
                for duty in duties:
                    lines.append(f"    - {duty.get('rule', '')}")
            return "\n".join(lines)
        return ""

    @classmethod
    def _scene_context(cls, state: Dict[str, Any]) -> str:
        item = cls._runtime_item(state)
        if item is None:
            return ""
        flow = cls._vision(state).get("flow") or {}
        detail = ""
        for entity in flow.get("entities") or []:
            if entity.get("name") != getattr(item, "entity", ""):
                continue
            for step in entity.get("steps") or []:
                if step.get("name") == getattr(item, "step", ""):
                    detail = step.get("detail", "")
                    break
        lines = ["YOUR SCENE:"]
        lines.append(f"  Agenda kind: {getattr(item, 'kind', '')}")
        lines.append(f"  Aspect: {getattr(item, 'aspect', '')}")
        lines.append(f"  Entity: {getattr(item, 'entity', '')}")
        lines.append(f"  Step: {getattr(item, 'step', '')}")
        if getattr(item, "kind", "") == "concern":
            lines.append(f"  Concern category: {getattr(item, 'concern_category', '') or '(not provided)'}")
            lines.append(f"  Concern theme: {getattr(item, 'concern_theme', '') or '(not provided)'}")
        if detail:
            lines.append(f"  Flow detail: {detail}")
        scene = getattr(item, "scene", "")
        if scene:
            lines.append(f"  Situation: {scene}")
        return "\n".join(lines)

    @classmethod
    def _role_memory(cls, state: Dict[str, Any], role_name: str) -> str:
        raw = state.get("elicitation_agenda")
        if not raw or not role_name:
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
            if item.role != role_name:
                continue
            if item.rule:
                rules.append(item.rule)
            elif item.answer:
                answers.append(item.answer)
        if not rules and not answers:
            return ""
        lines: List[str] = []
        if rules:
            lines.append("YOUR SETTLED RULES:")
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
            return "No interviewer message is available yet. Wait for one."

        role = (state.get("current_stakeholder_role") or "").strip() or self._persona
        item = self._runtime_item(state)
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
        for block in (
            self._role_context(state, role),
            self._scene_context(state),
            self._role_memory(state, role),
            self._hidden_block(),
        ):
            if block:
                parts.extend(["", block])
        parts.extend([
            "",
            "PROJECT SIGNAL:",
            f"  {state.get('project_description', '(not provided)')}",
            "",
            "INTERVIEWER MESSAGE:",
            f"  {question}",
            "",
            "If the message conflicts with your scene or role, say so plainly after one sentence of experience. Do not turn that disagreement into a paragraph of rebuttal.",
            "If the interviewer asks the same closure question for the third time and your honest answer is still that the app should support flexibility or multiple options, say so once, clearly, and stop softening.",
            "Do not invent a precise number unless the question asks for an acceptable limit and this role would know it from practice, policy, or repeated experience. Prefer an observable anchor (absence, comparator, operating condition, precedent) over a fabricated number.",
            "You may call search_knowledge once if necessary. Then call respond.",
        ])
        return "\n".join(parts)

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return self.react(
            state=state,
            task=self._build_task(state),
            tool_choice="required",
            include_memory=False,
        )