from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Type

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_RUNTIME_LLM_OVERRIDES: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "iredev_runtime_llm_overrides",
    default=None,
)


@contextmanager
def runtime_llm_overrides(overrides: Optional[Dict[str, Any]]) -> Iterator[None]:
    """Temporarily apply per-run LLM overrides while constructing agents."""
    token = _RUNTIME_LLM_OVERRIDES.set(overrides if isinstance(overrides, dict) else None)
    try:
        yield
    finally:
        _RUNTIME_LLM_OVERRIDES.reset(token)


# ─────────────────────────────────────────────────────────────────────────────
# Tool abstraction
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Value returned by every tool function.

    observation   – text the agent sees after the tool call
    state_updates – partial WorkflowState dict to merge after this step
    should_return – if True the ReAct loop exits immediately after this tool
    is_error      – if True the loop aborts with a fatal-error message
    """
    observation:   str
    state_updates: Dict[str, Any] = field(default_factory=dict)
    should_return: bool           = False
    is_error:      bool           = False


class Tool:
    """A named callable available to an agent inside the ReAct loop."""

    def __init__(self, name: str, description: str, func: Callable[..., ToolResult]):
        self.name        = name
        self.description = description
        self._func       = func

    def __call__(self, **kwargs: Any) -> ToolResult:
        try:
            return self._func(**kwargs)
        except Exception as exc:
            logger.exception("Tool '%s' raised: %s", self.name, exc)
            return ToolResult(
                observation=f"[Error in {self.name}]: {exc}",
                is_error=True,
                should_return=True,
            )

    def describe(self) -> str:
        return f"  {self.name}: {self.description}"


# ─────────────────────────────────────────────────────────────────────────────
# BaseAgent
# ─────────────────────────────────────────────────────────────────────────────

class BaseAgent(ABC):
    """Abstract base for all iReDev agents.

    Subclasses must implement:
      _register_tools() – populate self.tools with Tool instances
      process(state)     – top-level LangGraph node entry point

    Two public execution methods are available to subclasses:

    react()
        Run one full ReAct turn (bind_tools loop).  The model reasons over
        the task and decides which tool(s) to invoke.  Returns accumulated
        WorkflowState updates.

    extract_structured()
        Run a single deterministic LLM call (with_structured_output).  No
        tool routing, no loop — just one prompt → one validated Pydantic
        object.  Returns the parsed instance directly.
        Pass ``include_memory=False`` (default) for stateless extraction
        calls that do not need conversation history.
    """

    @staticmethod
    def _merge_llm_config(
        base: Optional[Dict[str, Any]],
        override: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Merge one LLM provider config over another without mutating either."""
        merged = dict(base or {})
        for key, value in (override or {}).items():
            if value is not None:
                merged[key] = value
        return merged

    @classmethod
    def _apply_runtime_llm_overrides(
        cls,
        raw_config: Dict[str, Any],
        llm_overrides: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Apply per-run model/profile overrides without mutating YAML config.

        The server UI sends overrides in the same profile shape as
        ``config/agent_config.yaml``:

            {"default": {"model": "..."}, "interview": {"model": "..."}}

        ``default`` continues to serve every agent unless routed elsewhere, and
        ``interview`` continues to serve interviewer/enduser through the
        existing ``llm.agents`` routing.
        """
        if not isinstance(llm_overrides, dict) or not llm_overrides:
            return raw_config

        patched = deepcopy(raw_config)
        llm_root = patched.setdefault("llm", {})
        if not isinstance(llm_root, dict):
            patched["llm"] = {}
            llm_root = patched["llm"]

        reserved = {"default", "profiles", "agents", "routing", "interview"}

        for profile_name in ("default", "interview"):
            override = llm_overrides.get(profile_name)
            if not isinstance(override, dict):
                continue
            current = llm_root.get(profile_name)
            if not isinstance(current, dict):
                current = (
                    {
                        key: value
                        for key, value in llm_root.items()
                        if key not in reserved
                    }
                    if profile_name == "default"
                    else {}
                )
            llm_root[profile_name] = cls._merge_llm_config(current, override)

        agents = llm_overrides.get("agents")
        if isinstance(agents, dict):
            current_agents = llm_root.get("agents")
            if not isinstance(current_agents, dict):
                current_agents = {}
            llm_root["agents"] = cls._merge_llm_config(current_agents, agents)

        return patched

    @classmethod
    def _resolve_llm_config(cls, raw_config: Dict[str, Any], name: str) -> Dict[str, Any]:
        """Return the provider config for one agent.

        Supported deployment shapes:

        1. Legacy single-model config:
           llm: { type, model, api_key, ... }

        2. Profiled config:
           llm:
             default: { type, model, api_key, ... }
             interview: { model, temperature, ... }
             agents:
               interviewer: interview
               enduser: interview

        Profiles inherit from ``llm.default`` when present, or from the legacy
        flat provider keys otherwise. Per-agent ``iredev.agents.<name>.llm`` can
        still override the resolved provider config.
        """
        llm_root = raw_config.get("llm") or {}
        if not isinstance(llm_root, dict):
            return {}

        reserved = {"default", "profiles", "agents", "routing", "interview"}
        default_cfg = llm_root.get("default")
        if isinstance(default_cfg, dict):
            base_cfg = dict(default_cfg)
        else:
            base_cfg = {
                key: value
                for key, value in llm_root.items()
                if key not in reserved
            }

        agent_section = raw_config.get("iredev", {}).get("agents", {}).get(name, {})
        profile_name = agent_section.get("llm_profile")
        direct_override: Optional[Dict[str, Any]] = None

        agent_routes = llm_root.get("agents") or {}
        if not profile_name and isinstance(agent_routes, dict):
            route = agent_routes.get(name)
            if isinstance(route, str):
                profile_name = route
            elif isinstance(route, dict):
                direct_override = route

        if not profile_name and not direct_override:
            if name in {"interviewer", "enduser"} and isinstance(llm_root.get("interview"), dict):
                profile_name = "interview"

        profile_cfg: Dict[str, Any] = {}
        if profile_name:
            profiles = llm_root.get("profiles") or {}
            if isinstance(profiles, dict) and isinstance(profiles.get(profile_name), dict):
                profile_cfg = profiles[profile_name]
            elif isinstance(llm_root.get(profile_name), dict):
                profile_cfg = llm_root[profile_name]
            else:
                logger.warning(
                    "Agent '%s': LLM profile '%s' not found; using default profile.",
                    name,
                    profile_name,
                )

        resolved = cls._merge_llm_config(base_cfg, profile_cfg)
        resolved = cls._merge_llm_config(resolved, direct_override)

        agent_llm_override = agent_section.get("llm")
        if isinstance(agent_llm_override, dict):
            resolved = cls._merge_llm_config(resolved, agent_llm_override)

        # Backward compatibility for mixed configs that keep provider type at
        # the top level while moving model settings into profiles.
        if not resolved.get("type") and llm_root.get("type"):
            resolved["type"] = llm_root.get("type")

        return resolved

    def __init__(self, name: str):
        self.name = name

        # ── Config ──────────────────────────────────────────────────────
        from ..config.config_manager import get_config
        raw_config       = self._apply_runtime_llm_overrides(
            get_config(),
            _RUNTIME_LLM_OVERRIDES.get(),
        )
        self._raw_config = raw_config

        agent_section = raw_config.get("iredev", {}).get("agents", {}).get(name, {})
        llm_cfg       = self._resolve_llm_config(raw_config, name)

        # ── LLM ─────────────────────────────────────────────────────────
        from .llm.factory import LLMFactory
        self.llm = LLMFactory.create_llm(llm_cfg)

        # ── Module 1: Profile ────────────────────────────────────────────
        from ..profile.profile_module import ProfileModule
        self.profile = ProfileModule(f"prompts/{name}_react.txt")

        # ── Module 2: Memory ─────────────────────────────────────────────
        from ..memory.memory_module import MemoryModule
        from ..memory.types import MemoryType
        memory_type = str(agent_section.get("memory_type", "short_term")).lower()
        self.memory = MemoryModule(memory_type=MemoryType(memory_type))

        # ── Module 3: Knowledge ──────────────────────────────────────────
        # Kept as a reference so subclasses can use it inside tool functions.
        self.knowledge = None
        try:
            from ..knowledge.knowledge_module import KnowledgeModule
            self.knowledge = KnowledgeModule.get_instance()
        except Exception as exc:
            logger.warning(
                "Agent '%s': knowledge module unavailable (%s). Skipping.", name, exc
            )

        # ── Module 4: Think (ReAct + structured extraction) ──────────────
        self.think: Optional[Any] = None
        try:
            from ..think.think_module import ThinkModule
            self.think = ThinkModule(llm=self.llm)
        except Exception as exc:
            logger.warning("Agent '%s': ThinkModule failed to init (%s).", name, exc)

        # ── Module 5: Action (ReAct config) ─────────────────────────────
        self.tools: Dict[str, Tool] = {}
        self.max_react_iterations: int = agent_section.get("max_react_iterations", 10)

        self._register_tools()
        logger.info("Agent '%s' ready | tools: %s", name, list(self.tools))

    # ── helpers ───────────────────────────────────────────────────────────

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    # ── ReAct entry point ─────────────────────────────────────────────────

    def react(
        self,
        state:            Dict[str, Any],
        task:             str,
        tool_choice:      Any = "auto",
        profile_addendum: str = "",
        include_memory:   bool = True,
    ) -> Dict[str, Any]:
        """Run one ReAct turn and return WorkflowState updates.

        Parameters
        ----------
        state:
            Current WorkflowState (read-only inside tool functions).
        task:
            Natural-language description of what to accomplish this turn.
        tool_choice:
            ``"auto"``, ``"required"``, or a specific tool dict.
        profile_addendum:
            Extra instructions appended to the base system prompt.
        include_memory:
            If ``True`` (default), prepend recent memory messages between the
            system prompt and the task.  Set to ``False`` for turns that do
            not need conversation history.
        """
        if self.think is None:
            logger.warning(
                "Agent '%s': ThinkModule unavailable — ReAct loop skipped.", self.name
            )
            return {}

        memory_messages: Optional[List[BaseMessage]] = None
        if include_memory:
            _memory_result = self.memory.take()
            # Guard against MemoryModule returning a (value, status) tuple
            # instead of a plain dict — AttributeError otherwise.
            if isinstance(_memory_result, tuple):
                _memory_result = _memory_result[0]
            if isinstance(_memory_result, dict):
                memory_messages = _memory_result.get("messages", [])

        final_profile = self.profile.prompt
        if profile_addendum:
            final_profile += f"\n\n{profile_addendum}"

        return self.think.run_react(
            task=task,
            tools_dict=self.tools,
            workflow_state=state,
            profile_prompt=final_profile,
            memory_messages=memory_messages,
            max_iterations=self.max_react_iterations,
            tool_choice=tool_choice,
        )

    # ── Structured extraction entry point ─────────────────────────────────

    def extract_structured(
        self,
        schema:          Type[BaseModel],
        system_prompt:   str,
        user_prompt:     str,
        include_memory:  bool = False,
    ) -> BaseModel:
        """Run a single structured-output LLM call and return a parsed object.

        This method bypasses the ReAct loop entirely.  It is the standard way
        to perform deterministic extraction tasks where the output schema is
        known in advance — no tool routing needed, no iterative reasoning.

        Parameters
        ----------
        schema:
            Pydantic ``BaseModel`` subclass defining the expected output shape.
        system_prompt:
            Extraction instructions for the LLM.
        user_prompt:
            The content to extract from (e.g. raw project description).
        include_memory:
            If ``True``, prepend recent memory messages to provide
            conversational context.  Defaults to ``False`` — most extraction
            calls are stateless and do not benefit from history.

        Returns
        -------
        BaseModel
            A validated instance of ``schema``.

        Raises
        ------
        RuntimeError
            If ThinkModule is unavailable.
        Exception
            Propagates any LLM or Pydantic validation error.
        """
        if self.think is None:
            raise RuntimeError(
                f"Agent '{self.name}': ThinkModule unavailable — "
                "cannot run extract_structured()."
            )

        memory_messages: Optional[List[BaseMessage]] = None
        if include_memory:
            _memory_result = self.memory.take()
            # Guard against MemoryModule returning a (value, status) tuple
            # instead of a plain dict — AttributeError otherwise.
            if isinstance(_memory_result, tuple):
                _memory_result = _memory_result[0]
            if isinstance(_memory_result, dict):
                memory_messages = _memory_result.get("messages", [])

        return self.think.run_structured(
            schema=schema,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            memory_messages=memory_messages,
        )

    # ── Async structured extraction entry point ───────────────────────────

    async def aextract_structured(
        self,
        schema:          Type[BaseModel],
        system_prompt:   str,
        user_prompt:     str,
        include_memory:  bool = False,
    ) -> BaseModel:
        """Async counterpart of ``extract_structured``.

        Use this from inside an ``asyncio`` driver (e.g. ``asyncio.gather``)
        to run several structured-output calls concurrently without spawning
        OS threads. The semantics are identical to ``extract_structured``;
        only the call mechanism (``ainvoke`` instead of ``invoke``) changes.
        """
        if self.think is None:
            raise RuntimeError(
                f"Agent '{self.name}': ThinkModule unavailable — "
                "cannot run aextract_structured()."
            )

        memory_messages: Optional[List[BaseMessage]] = None
        if include_memory:
            _memory_result = self.memory.take()
            if isinstance(_memory_result, tuple):
                _memory_result = _memory_result[0]
            if isinstance(_memory_result, dict):
                memory_messages = _memory_result.get("messages", [])

        return await self.think.arun_structured(
            schema=schema,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            memory_messages=memory_messages,
        )

    # ── abstract interface ────────────────────────────────────────────────

    @abstractmethod
    def _register_tools(self) -> None:
        """Populate self.tools. Called once at the end of __init__."""

    @abstractmethod
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph node entry point.

        Receives the current WorkflowState, returns a partial dict of
        state keys to update.
        """

    def clear_memory(self) -> None:
        """Reset the short-term conversation memory of this agent."""
        try:
            self.memory.refresh()
        except Exception as exc:
            logger.warning("Agent '%s': memory refresh failed: %s", self.name, exc)
