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
                "Return the stakeholder's in-character answer to the current interviewer "
                "message. The answer should be concrete, scene-based, and 2-4 sentences. "
                "Correct wrong or incomplete interviewer assumptions from the stakeholder's "
                "operational reality, but do not provide product design advice or invented "
                "numeric thresholds.\n"
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
        text = message.strip() or "I need the interviewer to restate that more concretely."
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
        parts = [
            f"PERSONA: {role}",
            "Answer entirely from this stakeholder's perspective.",
            "You do not see interview strategy; treat the interviewer message as an ordinary but possibly flawed question.",
            "If the message is too simple, wrong, or missing a condition that affects your work, correct it directly.",
        ]
        if kind == "concern":
            parts.append(
                "This is a quality-concern item: answer with lived experience, operating conditions, tolerable failure, and comparative anchors only when you can defend them from this role."
            )
        elif kind:
            parts.append(
                "This is a rule-clarification item: answer with business rules, exceptions, permissions, dependencies, or precedence when the question touches them."
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
            "If the message conflicts with your scene or role, say so and explain why.",
            "Do not invent a precise number unless the question asks for an acceptable limit and this role would know it from practice, policy, or repeated experience.",
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
