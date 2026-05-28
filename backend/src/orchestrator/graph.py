"""
graph.py – LangGraph orchestration.

Graph topology
──────────────
  supervisor
    ├─► visionary_turn → supervisor                  (Sprint Zero step 1)
    ├─► agenda_turn → supervisor                     (Sprint Zero step 3)
    ├─► interviewer_turn ◄──► enduser_turn           (Sprint Zero step 5)
    │       └─► supervisor  (interview_complete OR safety cap)
    ├─► distiller_turn → supervisor                  (Sprint Zero step 7)
    ├─► review_product_vision_turn → supervisor      (Sprint Zero step 2 — HITL)
    ├─► review_elicitation_agenda_turn → supervisor  (Sprint Zero step 4 — HITL)
    ├─► review_interview_record_turn → supervisor    (Sprint Zero step 6 — HITL, approve-only)
    ├─► review_requirement_list_turn → supervisor    (Sprint Zero step 8 — HITL)
    ├─► sprint_agent_turn → supervisor               (Sprint Zero steps 9a and 9b)
    ├─► review_user_story_draft_turn → supervisor    (Sprint Zero step 9a' — HITL)
    ├─► analyst_estimation_turn → supervisor         (Sprint Zero step 9c)
    ├─► review_product_backlog_turn → supervisor     (Sprint Zero step 10 — HITL)
    ├─► analyst_turn → supervisor                    (Backlog Refinement step 1)
    ├─► review_validated_product_backlog_turn → supervisor  (Backlog Refinement step 2 — HITL)
    └─► END

Sprint Zero backlog creation flow (linear, steps 9a → 9a' → 9c → 9b):
  sprint_agent_turn (9a: shape approved requirements → user_story_draft)
    → review_user_story_draft_turn (9a': HITL gate → user_story_draft_approved)
    → analyst_estimation_turn (9c: size + INVEST-assess + reshape → analyst_estimation)
    → sprint_agent_turn (9b: prioritise + assemble → product_backlog)

Reshaping (split / rewrite / merge / add / drop) and INVEST fixing happen
inside the single 9a and 9c passes, so there is no refinement loop and no
split_round.

sprint_agent_turn routing:
  • user_story_draft absent                                 → process_stories()  (Step 9a)
  • user_story_draft_approved + analyst_estimation present  → process_backlog()  (Step 9b)

HITL review order:
  1. review_product_vision_turn      — human reviews/edits the ProductVision
  2. review_elicitation_agenda_turn  — human reviews/edits the ElicitationAgenda
  3. review_interview_record_turn    — human reads raw Q&A (approve-only, no reject)
  4. review_requirement_list_turn    — human reviews the synthesised Requirement List
     • Reject here re-runs synthesis only; interview_record is NOT touched.
  5. review_user_story_draft_turn    — PO reviews the shaped user_story_draft
     • Reject removes ONLY user_story_draft, injects user_story_draft_feedback;
       SprintAgent re-runs step 9a (shaping) with the feedback.
  6. review_product_backlog_turn     — PO reviews the assembled product_backlog
     • Reject removes product_backlog, analyst_estimation, user_story_draft,
       AND user_story_draft_approved so all four steps (9a → 9a' → 9c → 9b)
       re-run with PO feedback.
  On vision rejection: only product_vision is removed from artifacts;
    product_vision_feedback is injected; VisionaryAgent re-runs (visionary_turn).
  On agenda rejection: elicitation_agenda_artifact
    is removed; AgendaAgent rebuilds using reviewed_product_vision
    + elicitation_agenda_feedback.

Review node design (HITL pattern)
──────────────────────────────────
All review nodes follow the same pattern:
  1. Build interrupt payload (artifact_data + review_payload + ui_summary).
  2. Call interrupt() — graph pauses; ws_handler emits an artifact card.
  3. Resume with {"approved": True|False, "feedback": "..."}.
  4. On approval  → write sentinel artifact, advance flow.
  5. On rejection → remove source artifact, inject feedback, restart step.
  Exception: review_interview_record_turn is approve-only (no rejection path).

UI Summaries (ARTIFACT_SUMMARIES)
──────────────────────────────────
Pre-written markdown summaries keyed by review_type.  ws_handler picks up
the right summary from the interrupt payload's "ui_summary" field and sends
it to the frontend alongside the artifact card.  Each summary explains:
  • What the artifact is
  • What the user needs to do (Accept / Request Changes)
"""

from __future__ import annotations

import json
import shutil
import logging
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt

from ..config.intake_hint import VISIONARY_CONTRACT
from .state import WorkflowState
from .supervisor import supervisor_node, supervisor_router

logger = logging.getLogger(__name__)

_INTERVIEW_SAFETY_MAX_TURNS = 3


# ─────────────────────────────────────────────────────────────────────────────
# UI Summaries
# ─────────────────────────────────────────────────────────────────────────────

ARTIFACT_SUMMARIES: Dict[str, str] = {

    # Opening text for the workflow when a no-artifact intro is needed.
    "workflow_started": VISIONARY_CONTRACT,

    # Sent inside review_elicitation_agenda_turn interrupt — alongside the artifact.
    "elicitation_agenda": (
        "## Elicitation Agenda Ready for Review\n\n"
        "Review the interview scenes, opening questions, and frictions to probe. "
        "Accept if the scenes are the right ones to elicit product evidence; "
        "request changes if a role, scene, or key friction is missing."
    ),

    # Sent inside review_product_vision_turn interrupt — alongside the artifact.
    "product_vision": (
        "## Product Vision Ready for Review\n\n"
        "Review the intent, target outcome, roles, assumptions, concerns, and scope. "
        "Accept if this is the right product framing; request changes if the direction, "
        "roles, or boundaries are off."
    ),

    # Sent inside review_interview_record_turn interrupt — alongside the artifact.
    "interview_record": (
        "## Requirements Interview Complete\n\n"
        "Review the closed interview scenes, coverage, and any gaps. "
        "Accept to continue to requirement synthesis. Requirement-level edits belong at the next gate."
    ),

    # Sent inside review_requirement_list_turn interrupt — alongside the artifact.
    "requirement_list": (
        "## Requirement List Ready for Review\n\n"
        "Review the buildable obligations, conflicts, gaps, and acceptance checks. "
        "Accept if the list is complete enough for backlog shaping; request changes for missing, duplicate, "
        "misclassified, or low-quality requirements."
    ),

    # Sent inside review_user_story_draft_turn interrupt — alongside the artifact.
    "user_story_draft": (
        "## User Story Draft Ready for Review\n\n"
        "Review the shaped stories before the Analyst sizes them — titles, descriptions, "
        "source requirements, reshape ops (carry / merge / split / rewrite / add), and "
        "dropped requirements with reasons. Accept if the shape is right for sizing; request "
        "changes for missing, duplicate, mis-shaped, or wrongly-dropped stories."
    ),

    # Sent inside review_product_backlog_turn interrupt — alongside the artifact.
    "product_backlog": (
        "## Initial Product Backlog Ready\n\n"
        "Review story titles, descriptions, estimates, readiness, priority order, INVEST status, "
        "and dependencies. Accept to add acceptance criteria; request changes for shaping, sizing, "
        "priority, or dependency issues."
    ),

    # Sent inside review_validated_product_backlog_turn interrupt — alongside the artifact.
    "validated_product_backlog": (
        "## Validated Product Backlog Ready\n\n"
        "Review each PBI's Given-When-Then acceptance criteria and readiness. "
        "Accept if criteria are clear and sufficient; request changes for missing coverage or weak checks."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Lazy agent singletons
# ─────────────────────────────────────────────────────────────────────────────

_store_override: Optional[BaseStore] = None
_inmemory_store_singleton: Optional[InMemoryStore] = None


def _normalise_llm_overrides(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}

    normalised: Dict[str, Dict[str, Any]] = {}
    allowed_fields = {
        "model",
        "temperature",
        "max_output_tokens",
        "max_input_tokens",
    }
    for profile_name in ("default", "interview"):
        profile = raw.get(profile_name)
        if not isinstance(profile, dict):
            continue
        cleaned = {
            key: value
            for key, value in profile.items()
            if key in allowed_fields and value not in (None, "")
        }
        if cleaned:
            normalised[profile_name] = cleaned
    return normalised


def _llm_cache_key(state: WorkflowState) -> str:
    overrides = _normalise_llm_overrides(state.get("llm_overrides"))
    return json.dumps(overrides, sort_keys=True, separators=(",", ":"))


def _agent_with_overrides(agent_cls, llm_cache_key: str):
    from ..agent.base import runtime_llm_overrides

    try:
        overrides = json.loads(llm_cache_key) if llm_cache_key else {}
    except json.JSONDecodeError:
        overrides = {}

    with runtime_llm_overrides(overrides):
        return agent_cls()


def configure_default_store(store: BaseStore) -> None:
    """Install a process-wide store used by _sync_artifacts_to_store +
    get_artifact_from_store. Server boot calls this with a PostgresStore so
    artifact reads/writes share the same persistent backend as the graph.
    """
    global _store_override
    _store_override = store


def _default_store() -> BaseStore:
    if _store_override is not None:
        return _store_override
    global _inmemory_store_singleton
    if _inmemory_store_singleton is None:
        _inmemory_store_singleton = InMemoryStore()
    return _inmemory_store_singleton


@lru_cache(maxsize=16)
def _get_interviewer(llm_cache_key: str):
    from ..agent.interviewer import InterviewerAgent
    return _agent_with_overrides(InterviewerAgent, llm_cache_key)


@lru_cache(maxsize=16)
def _get_agenda(llm_cache_key: str):
    from ..agent.agenda import AgendaAgent
    return _agent_with_overrides(AgendaAgent, llm_cache_key)


@lru_cache(maxsize=16)
def _get_enduser(llm_cache_key: str):
    from ..agent.enduser import EndUserAgent
    return _agent_with_overrides(EndUserAgent, llm_cache_key)


@lru_cache(maxsize=16)
def _get_sprint_agent(llm_cache_key: str):
    from ..agent.sprint import SprintAgent
    return _agent_with_overrides(SprintAgent, llm_cache_key)


@lru_cache(maxsize=16)
def _get_analyst(llm_cache_key: str):
    from ..agent.analyst import AnalystAgent
    return _agent_with_overrides(AnalystAgent, llm_cache_key)


@lru_cache(maxsize=16)
def _get_visionary(llm_cache_key: str):
    from ..agent.visionary import VisionaryAgent
    return _agent_with_overrides(VisionaryAgent, llm_cache_key)


@lru_cache(maxsize=16)
def _get_distiller(llm_cache_key: str):
    from ..agent.distiller import DistillerAgent
    return _agent_with_overrides(DistillerAgent, llm_cache_key)
# ─────────────────────────────────────────────────────────────────────────────
# Node functions
# ─────────────────────────────────────────────────────────────────────────────

def supervisor_node_fn(state: WorkflowState) -> Dict[str, Any]:
    return supervisor_node(state)


def visionary_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Run VisionaryAgent — Sprint Zero step 1 (extract_product_vision).

    Produces artifacts["product_vision"] and routes unconditionally to
    supervisor, which then fires review_product_vision_turn (HITL step 2).
    Also called after HITL rejection when product_vision_feedback is present.
    """
    updates = _get_visionary(_llm_cache_key(state)).process(state)
    logger.debug(
        "visionary_turn updates: %s | vision=%s",
        list(updates.keys()),
        "present" if updates.get("product_vision") else "MISSING",
    )
    _sync_artifacts_to_store(state, updates)
    return updates


def interviewer_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    old_agenda = state.get("elicitation_agenda") or {}
    old_index = old_agenda.get("current_index", -1)

    updates = _get_interviewer(_llm_cache_key(state)).process(state)

    logger.debug(
        "interviewer_turn updates: %s | vision=%s | agenda=%s | question=%r",
        list(updates.keys()),
        "present" if updates.get("product_vision") or state.get("product_vision") else "MISSING",
        "present" if updates.get("elicitation_agenda") or state.get("elicitation_agenda") else "MISSING",
        updates.get("current_question", ""),
    )

    new_agenda = updates.get("elicitation_agenda") or state.get("elicitation_agenda") or {}
    new_index = new_agenda.get("current_index", -1)

    if new_index != old_index and old_index != -1:
        updates.update(_agenda_boundary_reset_updates())
        logger.info(
            "interviewer_turn_fn: agenda advanced (%d → %d); per-item conversation and handshake reset applied.",
            old_index, new_index,
        )

    _sync_artifacts_to_store(state, updates)
    return updates


def agenda_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Run AgendaAgent — Sprint Zero step 3 (build_elicitation_agenda).

    Produces elicitation_agenda_artifact and state["elicitation_agenda"] from
    the reviewed assumption-centered Product Vision.
    """
    updates = _get_agenda(_llm_cache_key(state)).process(state)
    artifacts_out = updates.get("artifacts") or {}
    logger.debug(
        "agenda_turn updates: %s | agenda_artifact=%s | runtime=%s",
        list(updates.keys()),
        "present" if artifacts_out.get("elicitation_agenda_artifact") else "MISSING",
        "present" if updates.get("elicitation_agenda") else "MISSING",
    )
    _sync_artifacts_to_store(state, updates)
    return updates

def distiller_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Run DistillerAgent — Sprint Zero step 7 (synthesise_requirement_list).

    Produces artifacts["requirement_list"] and sets interview_complete=True.
    Always routes to supervisor afterwards.
    """
    updates = _get_distiller(_llm_cache_key(state)).process(state)
    logger.debug("distiller_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates

_ENDUSER_MAX_ATTEMPTS = 3


def _agenda_boundary_reset_updates() -> Dict[str, Any]:
    """Return deterministic handshake resets for a newly advanced agenda item."""
    return {
        "current_question": "",
        "enduser_answer": "",
        "conversation": [],
        "_agenda_needs_question": True,
        "_agenda_needs_followup": False,
        "item_turn_count": 0,
    }


def enduser_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Run EndUserAgent, retrying if the agent exits without calling 'respond'.

    Resolves current_stakeholder_role from the agenda runtime before each attempt.

    AgendaRuntimeItem carries a single `perspective` string per item — there is no
    multi-stakeholder cursor. Role resolution is strict:
      1. state["current_stakeholder_role"] — written by record_answer on advance.
      2. item.perspective — read directly from the current AgendaRuntimeItem.
      3. no fallback persona; missing perspective returns to interviewer.

    EndUserAgent.respond sets should_return=True inside its own ReAct loop only.
    The edge from enduser_turn always returns to interviewer_turn — the enduser
    can never terminate the interview.
    """
    if not (state.get("current_question") or "").strip():
        logger.warning("enduser_turn_fn: current_question missing; returning to interviewer.")
        return {
            "enduser_answer": "",
            "_agenda_needs_question": True,
        }

    # ── Resolve current stakeholder from agenda runtime ───────────────────────
    resolved_role = (state.get("current_stakeholder_role") or "").strip()
    if not resolved_role:
        artifacts = state.get("artifacts") or {}
        raw_agenda = (
            state.get("elicitation_agenda")
            or artifacts.get("reviewed_elicitation_agenda")
            or artifacts.get("elicitation_agenda_artifact")
        )
        if raw_agenda:
            try:
                from ..agent.agenda import AgendaRuntime
                runtime = (
                    AgendaRuntime.from_agenda_artifact(raw_agenda)
                    if isinstance(raw_agenda, dict)
                    else raw_agenda
                )
                item    = runtime.current_item()
                if item:
                    resolved_role = getattr(item, "perspective", "") or ""
            except Exception as exc:
                logger.warning("enduser_turn_fn: failed to resolve stakeholder from agenda: %s", exc)

    if not resolved_role:
        logger.warning("enduser_turn_fn: perspective missing; refusing fallback persona.")
        return {
            "current_question": "",
            "enduser_answer": "",
            "_agenda_needs_question": True,
            "errors": (state.get("errors") or []) + [
                "EndUser turn skipped because current agenda perspective is missing."
            ],
        }

    for attempt in range(1, _ENDUSER_MAX_ATTEMPTS + 1):
        augmented_state = dict(state)
        # Always inject the resolved role so EndUserAgent._build_task can read it
        augmented_state["current_stakeholder_role"] = resolved_role
        if attempt > 1:
            augmented_state["_enduser_retry_hint"] = (
                f"[Attempt {attempt}/{_ENDUSER_MAX_ATTEMPTS}] "
                "You MUST call the 'respond' tool right now. "
                "Do not generate plain text — use the tool."
            )

        updates = _get_enduser(_llm_cache_key(state)).process(augmented_state)
        logger.debug(
            "enduser_turn attempt %d/%d — role=%r — updates: %s",
            attempt, _ENDUSER_MAX_ATTEMPTS, resolved_role, list(updates.keys()),
        )

        new_conversation = updates.get("conversation")
        if (
            isinstance(new_conversation, list)
            and new_conversation
            and new_conversation[-1].get("role") == "enduser"
        ):
            logger.debug(
                "enduser_turn attempt %d/%d: fresh enduser response accepted.",
                attempt, _ENDUSER_MAX_ATTEMPTS,
            )
            return updates

        logger.warning(
            "enduser_turn attempt %d/%d: no fresh enduser response in updates. Retrying...",
            attempt,
            _ENDUSER_MAX_ATTEMPTS,
        )

    logger.error(
        "enduser_turn: EndUserAgent failed to call 'respond' after %d attempts.",
        _ENDUSER_MAX_ATTEMPTS,
    )
    return {}


def sprint_agent_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """
    Route to the correct SprintAgent method based on current state (linear,
    no refinement loop):
      1. user_story_draft absent → process_stories()  (Step 9a: shaping)
      2. user_story_draft_approved + analyst_estimation present →
         process_backlog()  (Step 9b: prioritise + assemble)

    Reshaping (split / rewrite / merge / add / drop) and INVEST fixing now
    happen inside the single 9a and 9c passes, so there is no sprint↔analyst
    cycle and no split_round. The user_story_draft_approved sentinel is
    written by the 9a' HITL gate (review_user_story_draft_turn).
    """
    agent      = _get_sprint_agent(_llm_cache_key(state))
    artifacts  = state.get("artifacts") or {}

    has_draft      = "user_story_draft"          in artifacts
    has_approved   = "user_story_draft_approved" in artifacts
    has_estimation = "analyst_estimation"        in artifacts

    if not has_draft:
        logger.info("sprint_agent_turn: no user_story_draft → process_stories() (Step 9a).")
        updates = agent.process_stories(state)
    elif has_approved and has_estimation:
        logger.info(
            "sprint_agent_turn: approved draft + estimation present → "
            "process_backlog() (Step 9b)."
        )
        updates = agent.process_backlog(state)
    else:
        # Supervisor should have routed to review_user_story_draft_turn
        # (9a') or analyst_estimation_turn (9c) instead of here.
        logger.warning(
            "sprint_agent_turn: user_story_draft present but the 9b prereqs "
            "(user_story_draft_approved + analyst_estimation) are not both set "
            "(has_approved=%s, has_estimation=%s). Returning empty update.",
            has_approved, has_estimation,
        )
        updates = {}

    logger.debug("sprint_agent_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


def analyst_estimation_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Run AnalystAgent.process_estimation() — Step 9c: size, INVEST-assess,
    and reshape stories in one pass → analyst_estimation."""
    updates = _get_analyst(_llm_cache_key(state)).process_estimation(state)
    logger.debug("analyst_estimation_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


def analyst_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Run AnalystAgent.process() — Phase 2: deterministically assemble
    validated_product_backlog by attaching the acceptance criteria the Analyst
    already wrote in step 9c. No LLM call."""
    updates = _get_analyst(_llm_cache_key(state)).process(state)
    logger.debug("analyst_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


# ─────────────────────────────────────────────────────────────────────────────
# HITL review nodes
# ─────────────────────────────────────────────────────────────────────────────

def review_product_vision_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — human reviews the product_vision artifact.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":    "product_vision",
        "artifact_data":  <full product_vision dict>,
        "review_payload": <structured review data>,
        "ui_summary":     ARTIFACT_SUMMARIES["product_vision"],
    }

    After resume:
      approved=True  → write reviewed_product_vision sentinel; flow →
                       review_interview_record_turn.
      approved=False → remove product_vision artifact, inject
                       product_vision_feedback; flow returns to
                       interviewer_turn so vision is re-extracted with
                       the reviewer's comments.
    """
    artifacts   = dict(state.get("artifacts") or {})
    vision      = artifacts.get("product_vision", {})

    interrupt_value = {
        "review_type":    "product_vision",
        "artifact_data":  vision,
        "review_payload": _build_product_vision_review_payload(vision),
        "ui_summary":     ARTIFACT_SUMMARIES["product_vision"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    if approved:
        artifacts["reviewed_product_vision"] = {
            **vision,
            "status":       "approved",
            "reviewed_at":  datetime.now().isoformat(),
            "review_notes": feedback or None,
        }
        _sync_artifacts_to_store(
            state, {"artifacts": {"reviewed_product_vision": artifacts["reviewed_product_vision"]}}
        )
        logger.info("[ReviewProductVision] APPROVED.")
        return {
            "artifacts":              artifacts,
            "product_vision_feedback": None,
        }

    artifacts.pop("product_vision", None)
    # Do NOT reset elicitation_agenda here — agenda is built AFTER vision is approved
    # (step 3), so it cannot exist yet at this rejection point.
    logger.info("[ReviewProductVision] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":               artifacts,
        "interview_complete":      False,
        "product_vision_feedback": feedback or "The reviewer did not provide specific feedback.",
    }


def review_elicitation_agenda_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — human reviews the elicitation_agenda_artifact.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":    "elicitation_agenda",
        "artifact_data":  <full elicitation_agenda_artifact dict>,
        "review_payload": <structured review data>,
        "ui_summary":     ARTIFACT_SUMMARIES["elicitation_agenda"],
    }

    After resume:
      approved=True  → write reviewed_elicitation_agenda sentinel;
                       flow → conduct_requirements_interview.
      approved=False → remove elicitation_agenda_artifact,
                       inject elicitation_agenda_feedback; flow returns to
                       agenda_turn so the agenda is rebuilt using
                       reviewed_product_vision + feedback.
    """
    artifacts  = dict(state.get("artifacts") or {})
    agenda     = artifacts.get("elicitation_agenda_artifact", {})

    interrupt_value = {
        "review_type":    "elicitation_agenda",
        "artifact_data":  agenda,
        "review_payload": _build_elicitation_agenda_review_payload(agenda),
        "ui_summary":     ARTIFACT_SUMMARIES["elicitation_agenda"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    if approved:
        artifacts["reviewed_elicitation_agenda"] = {
            **agenda,
            "status":       "approved",
            "reviewed_at":  datetime.now().isoformat(),
            "review_notes": feedback or None,
        }

        _sync_artifacts_to_store(
            state, {"artifacts": {"reviewed_elicitation_agenda": artifacts["reviewed_elicitation_agenda"]}}
        )

        logger.info("[ReviewElicitationAgenda] APPROVED.")
        return {
            "artifacts":                  artifacts,
            "elicitation_agenda_feedback": None,
        }

    # On rejection: remove the agenda artifact so AgendaAgent rebuilds.
    artifacts.pop("elicitation_agenda_artifact", None)
    logger.info("[ReviewElicitationAgenda] REJECTED. Feedback: %s", feedback or "(none)")
    agenda_feedback = feedback or "The reviewer did not provide specific feedback."
    return {
        "artifacts":                  artifacts,
        "elicitation_agenda_feedback": agenda_feedback,
        # Reset live state keys so AgendaAgent rebuilds all passes cleanly.
        "elicitation_agenda":         None,
    }


def review_requirement_list_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — human reviews the requirement_list artifact.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":    "requirement_list",
        "artifact_data":  <full requirement_list dict>,
        "review_payload": <structured review data>,
        "ui_summary":     ARTIFACT_SUMMARIES["requirement_list"],
    }

    After resume:
      Normal path (no conflicts):
        approved=True  → write requirement_list_approved sentinel;
                         flow → sprint_agent_turn (Step 9a: create_user_stories).
        approved=False → remove ONLY requirement_list artifact, inject
                         requirement_list_feedback; flow returns to
                         distiller_turn so synthesis re-runs with feedback.
                         interview_record and reviewed_interview_record are
                         NOT removed — only synthesis re-runs.

      Conflict gate (status = pending_hitl_conflict_review):
        Artifact has RequirementConflict entries. Reviewer provides resolutions.
        Always re-runs distiller with conflict resolution as feedback.
        Only moves forward when distiller re-runs and produces conflicts=[].
    """
    artifacts    = dict(state.get("artifacts") or {})
    req_list     = artifacts.get("requirement_list", {})
    requirements = req_list.get("items", [])
    conflicts    = req_list.get("conflicts", [])
    has_conflicts = bool(conflicts)

    interrupt_value = {
        "review_type":    "requirement_list",
        "artifact_data":  req_list,
        "review_payload": _build_requirement_list_review_payload(req_list, requirements),
        "ui_summary":     ARTIFACT_SUMMARIES["requirement_list"],
    }
    if has_conflicts:
        interrupt_value["mode"] = "conflict_resolution"
        interrupt_value["requires_resolution"] = True
        interrupt_value["conflict_data"] = conflicts
        interrupt_value["ui_summary"] = _build_requirement_conflict_summary(conflicts)
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    # Conflict gate: always re-run distiller with resolution feedback
    if has_conflicts:
        artifacts.pop("requirement_list", None)
        resolution_feedback = (
            f"CONFLICT RESOLUTION REQUIRED: The following conflicts were detected:\n"
            + "\n".join(
                f"  CF-{i+1}: {c.get('issue', '')} — "
                f"Reviewer resolution: {feedback or 'no specific resolution provided'}"
                for i, c in enumerate(conflicts)
            )
        )
        logger.info(
            "[ReviewRequirementList] CONFLICT GATE — %d conflict(s). "
            "Re-running distiller with resolution feedback.",
            len(conflicts),
        )
        return {
            "artifacts":                artifacts,
            "_needs_srs_synthesis":     True,
            "interview_complete":       False,
            "requirement_list_feedback": resolution_feedback,
        }

    if approved:
        artifacts["requirement_list_approved"] = {
            **req_list,
            "status":       "approved",
            "reviewed_at":  datetime.now().isoformat(),
            "review_notes": feedback or None,
        }
        logger.info(
            "[ReviewRequirementList] APPROVED — %d requirement(s).", len(requirements)
        )
        return {
            "artifacts":                artifacts,
            "requirement_list_feedback": None,
        }

    # Remove only the requirement_list — interview_record stays intact.
    artifacts.pop("requirement_list", None)
    logger.info("[ReviewRequirementList] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":                artifacts,
        "_needs_srs_synthesis":     True,
        "interview_complete":       False,
        "requirement_list_feedback": feedback or "The reviewer did not provide specific feedback.",
    }


def review_interview_record_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — human reviews the interview_record (view-only / approve-only).

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":    "interview_record",
        "artifact_data":  <full interview_record dict>,
        "review_payload": <structured review data>,
        "ui_summary":     ARTIFACT_SUMMARIES["interview_record"],
    }

    This gate is APPROVE-ONLY. There is no reject path.
    The interview_record cannot be sent back for re-interviewing here.
    If the reviewer has concerns about content quality, they should note them
    and provide feedback at the review_requirement_list gate instead, where
    synthesis can be re-run incorporating their comments.

    After resume:
      approved=True  → write reviewed_interview_record; flow → synthesise_requirement_list.
      approved=False → treated identically to approved=True (approve-only gate);
                       any feedback text is stored as review_notes on the artifact.
    """
    artifacts    = dict(state.get("artifacts") or {})
    record       = artifacts.get("interview_record", {})
    elicitation_items = record.get("items", [])

    interrupt_value = {
        "review_type":    "interview_record",
        "artifact_data":  record,
        "review_payload": _build_interview_review_payload(record, elicitation_items),
        "ui_summary":     ARTIFACT_SUMMARIES["interview_record"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    # Approve-only: ignore the approved flag, always proceed.
    feedback = (reviewer_response.get("feedback") or "").strip()

    reviewed_record = {
        **record,
        "status":       "approved",
        "reviewed_at":  datetime.now().isoformat(),
        "review_notes": feedback or None,
    }
    artifacts["reviewed_interview_record"] = reviewed_record
    logger.info(
        "[ReviewInterviewRecord] APPROVED (approve-only gate) — %d elicitation item(s).",
        len(elicitation_items),
    )
    return {
        "artifacts":       artifacts,
        "review_feedback": None,
    }


def review_user_story_draft_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — Product Owner reviews the user_story_draft BEFORE sizing.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":   "user_story_draft",
        "artifact_data": <full user_story_draft dict>,
        "review_payload": <structured review data>,
        "ui_summary":    ARTIFACT_SUMMARIES["user_story_draft"],
    }

    After resume:
      approved=True  → write user_story_draft_approved sentinel;
                       flow → analyst_estimation_turn (Step 9c).
      approved=False → remove ONLY user_story_draft, inject
                       user_story_draft_feedback; SprintAgent re-runs
                       step 9a with feedback. analyst_estimation is not
                       yet present at this point, so nothing else to clear.
    """
    artifacts = dict(state.get("artifacts") or {})
    draft     = artifacts.get("user_story_draft", {})

    interrupt_value = {
        "review_type":   "user_story_draft",
        "artifact_data": draft,
        "review_payload": _build_user_story_draft_review_payload(draft),
        "ui_summary":    ARTIFACT_SUMMARIES["user_story_draft"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    stories = draft.get("stories") or []

    if approved:
        artifacts["user_story_draft_approved"] = {
            **draft,
            "status":       "approved",
            "reviewed_at":  datetime.now().isoformat(),
            "review_notes": feedback or None,
        }
        logger.info(
            "[ReviewUserStoryDraft] APPROVED — %d shaped story(ies).", len(stories)
        )
        return {
            "artifacts":                 artifacts,
            "user_story_draft_feedback": None,
        }

    artifacts.pop("user_story_draft", None)
    logger.info("[ReviewUserStoryDraft] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":                 artifacts,
        "user_story_draft_feedback": feedback or "The reviewer did not provide specific feedback.",
    }


def review_product_backlog_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — Product Owner reviews the raw product_backlog.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":   "product_backlog",
        "artifact_data": <full product_backlog dict>,
        "review_payload": <structured review data>,
        "ui_summary":    ARTIFACT_SUMMARIES["product_backlog"],
    }

    After resume:
      approved=True  → write product_backlog_approved sentinel;
                       flow → analyst_turn (Phase 2: AC generation).
      approved=False → remove product_backlog, analyst_estimation,
                       user_story_draft, AND user_story_draft_approved so
                       all four steps (9a → 9a' → 9c → 9b) re-run with PO
                       feedback injected.
    """
    artifacts = dict(state.get("artifacts") or {})
    backlog   = artifacts.get("product_backlog", {})

    interrupt_value = {
        "review_type":   "product_backlog",
        "artifact_data": backlog,
        "review_payload": _build_product_backlog_review_payload(backlog),
        "ui_summary":    ARTIFACT_SUMMARIES["product_backlog"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    items = backlog.get("items") or []

    if approved:
        artifacts["product_backlog_approved"] = backlog
        logger.info(
            "[ReviewProductBacklog] APPROVED — %d user stories.", len(items)
        )
        return {
            "artifacts":               artifacts,
            "product_backlog_feedback": None,
        }

    # On rejection: clear product_backlog AND every upstream intermediate so
    # the full 9a → 9a' → 9c → 9b chain re-runs from scratch. The 9a' sentinel
    # must also be cleared so SprintAgent's shape pass actually re-runs
    # instead of falling through to 9b on stale approval.
    artifacts.pop("product_backlog",          None)
    artifacts.pop("analyst_estimation",       None)
    artifacts.pop("user_story_draft",         None)
    artifacts.pop("user_story_draft_approved", None)
    logger.info("[ReviewProductBacklog] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":                 artifacts,
        "product_backlog_feedback":  feedback or "The reviewer did not provide specific feedback.",
        "user_story_draft_feedback": None,
    }


def review_validated_product_backlog_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — Product Owner reviews the validated_product_backlog.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":   "validated_product_backlog",
        "artifact_data": <full validated_product_backlog dict>,
        "review_payload": <structured review data>,
        "ui_summary":    ARTIFACT_SUMMARIES["validated_product_backlog"],
    }

    After resume:
      approved=True  → write validated_product_backlog_approved sentinel; Sprint N can begin.
      approved=False → AC now live on the stories from step 9c, and Phase 2 is a
                       deterministic re-assembly, so to actually change AC we must
                       re-run the Analyst. Remove validated_product_backlog AND
                       analyst_estimation (+ the downstream product_backlog /
                       product_backlog_approved), inject the feedback as
                       product_backlog_feedback; the Analyst re-assesses + rewrites AC.
    """
    artifacts = dict(state.get("artifacts") or {})
    validated = artifacts.get("validated_product_backlog") or {}

    interrupt_value = {
        "review_type":   "validated_product_backlog",
        "artifact_data": validated,
        "review_payload": _build_validated_product_backlog_review_payload(validated),
        "ui_summary":    ARTIFACT_SUMMARIES["validated_product_backlog"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    if approved:
        artifacts["validated_product_backlog_approved"] = validated
        logger.info(
            "[AnalystReview] APPROVED — %d ready PBIs, %d total AC.",
            len([
                item["id"]
                for item in (validated.get("items") or [])
                if item.get("planning", {}).get("status") == "ready"
            ]),
            validated.get("refinement_stats", {}).get("total_ac", 0),
        )
        return {
            "artifacts":       artifacts,
            "analyst_feedback": None,
        }

    # AC are written by the Analyst in step 9c (they live on analyst_estimation),
    # and Phase 2 only re-assembles deterministically — so to change AC we re-run
    # the Analyst. Clear validated + estimation + the downstream backlog so the
    # 9c → 9b → review → Phase 2 chain re-runs with the feedback.
    for key in ("validated_product_backlog", "analyst_estimation",
                "product_backlog", "product_backlog_approved"):
        artifacts.pop(key, None)
    logger.info("[AnalystReview] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":                artifacts,
        "analyst_feedback":         None,
        "product_backlog_feedback": feedback or "The reviewer did not provide specific feedback.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Review payload builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_product_vision_review_payload(vision: Dict[str, Any]) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing product_vision.

    The product_vision schema is lean: description / intent_summary /
    target_outcome, known_signals, roles, assumptions, concerns, and scope
    boundaries. Every Role / Assumption / Concern / Boundary carries a
    `lens` (stated / implied / inferred) and a natural-language `anchor`.
    """
    roles = vision.get("roles") or []
    return {
        "description": vision.get("description", ""),
        "intent_summary": vision.get("intent_summary", ""),
        "target_outcome": vision.get("target_outcome", ""),
        "known_signals": list(vision.get("known_signals") or []),
        "roles": [
            {
                "id": role.get("id"),
                "name": role.get("name"),
                "need": role.get("need"),
                "lens": role.get("lens", ""),
                "anchor": role.get("anchor", ""),
            }
            for role in roles
        ],
        "assumptions": [
            {
                "id": item.get("id"),
                "statement": item.get("statement"),
                "why_it_matters": item.get("why_it_matters"),
                "lens": item.get("lens", ""),
                "anchor": item.get("anchor", ""),
            }
            for item in (vision.get("assumptions") or [])
        ],
        "concerns": [
            {
                "id": concern.get("id"),
                "theme": concern.get("theme"),
                "affected_roles": list(concern.get("affected_roles") or []),
                "rationale": concern.get("rationale"),
                "lens": concern.get("lens", ""),
                "anchor": concern.get("anchor", ""),
            }
            for concern in (vision.get("concerns") or [])
        ],
        "scope": [
            {
                "id": item.get("id"),
                "item": item.get("item"),
                "reason": item.get("reason"),
                "lens": item.get("lens", ""),
                "anchor": item.get("anchor", ""),
            }
            for item in (vision.get("scope") or [])
        ],
        "notes": vision.get("notes", ""),
    }


def _build_elicitation_agenda_review_payload(
    agenda: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing elicitation_agenda_artifact.

    Each item is assumption-backed, concern-led: concern_ref opens the
    lived gate, assumption_refs name the forks the evidence will move
    toward features, scope_refs (optional) are boundary edges the scene
    touches. The flat `vision_refs` is derived (concern_ref +
    assumption_refs + scope_refs) for backward-compatible display.
    """
    items = []
    for item in agenda.get("items") or []:
        concern_ref = (item.get("concern_ref") or "").strip()
        assumption_refs = list(item.get("assumption_refs") or [])
        scope_refs = list(item.get("scope_refs") or [])
        flat_refs = list(item.get("vision_refs") or [])
        if not flat_refs:
            flat_refs = ([concern_ref] if concern_ref else []) + assumption_refs + scope_refs
        items.append({
            "id": item.get("id"),
            "concern_ref": concern_ref,
            "assumption_refs": assumption_refs,
            "scope_refs": scope_refs,
            "vision_refs": flat_refs,
            "perspective": item.get("perspective"),
            "context": item.get("context"),
            "decision_target": item.get("decision_target", ""),
            "seed_question": item.get("seed_question"),
            "coverage_points": list(item.get("coverage_points") or []),
            "close_when": item.get("close_when"),
            "notes": item.get("notes"),
        })

    return {
        "session_id":  agenda.get("session_id", ""),
        "created_at":  agenda.get("created_at", ""),
        "total_items": len(items),
        "items":       items,
        "notes":       agenda.get("notes", ""),
    }


def _build_requirement_list_review_payload(
    req_list: Dict[str, Any],
    requirements: list,
) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing requirement_list.

    The Requirement schema is now lean: id, type, stakeholder, statement,
    rationale, trace_refs, acceptance_criteria, priority, status, and
    threshold_needed (NFR only). Display fields stay in sync.
    """
    by_type: Dict[str, int] = {}
    req_summaries = []
    for r in requirements:
        rtype = r.get("type", "unknown")
        by_type[rtype] = by_type.get(rtype, 0) + 1
        req_summaries.append({
            "id":                  r.get("id"),
            "type":                rtype,
            "priority":            r.get("priority"),
            "status":              r.get("status"),
            "stakeholder":         r.get("stakeholder"),
            "statement":           r.get("statement"),
            "rationale":           r.get("rationale", "(not provided)"),
            "trace_refs":          list(r.get("trace_refs") or []),
            "threshold_needed":    bool(r.get("threshold_needed", False)),
            "acceptance_criteria": list(r.get("acceptance_criteria") or []),
        })

    return {
        "session_id":        req_list.get("session_id", ""),
        "synthesised_at":    req_list.get("synthesised_at", ""),
        "total_requirements": len(requirements),
        "by_type":           by_type,
        "items":             req_summaries,
        "has_conflicts":     bool(req_list.get("conflicts") or []),
        "gap_count":         len(req_list.get("gaps") or []),
        "gaps":              req_list.get("gaps", []),
        "conflicts":         [
            {
                "id": c.get("id") or f"CF-{i + 1:02d}",
                "kind": c.get("kind"),
                "left": c.get("left"),
                "right": c.get("right"),
                "scope": c.get("scope"),
                "issue": c.get("issue"),
                "paths": c.get("paths", []),
                "refs": c.get("refs", []),
            }
            for i, c in enumerate(req_list.get("conflicts") or [])
        ],
    }


def _build_requirement_conflict_summary(conflicts: list) -> str:
    """Build the HITL summary shown when requirement conflicts block approval."""
    lines = [
        "## Requirement Conflicts Need Resolution",
        "",
        "DistillerAgent found contradictions or unresolved ambiguity in the Requirement List.",
        "This is a hard gate: the list cannot be approved until the conflicts are resolved.",
        "",
        "**Conflicts:**",
    ]
    for i, conflict in enumerate(conflicts, 1):
        conflict_id = conflict.get("id") or f"CF-{i:02d}"
        issue = conflict.get("issue", "(no issue text)")
        left = conflict.get("left", "?")
        right = conflict.get("right", "?")
        scope = conflict.get("scope", "(scope not specified)")
        lines.append(f"- **{conflict_id}** `{left}` vs `{right}` in {scope}: {issue}")
        paths = conflict.get("paths") or []
        if paths:
            lines.append(f"  Possible resolutions: {'; '.join(paths)}")
    lines.extend([
        "",
        "**Your action:** Provide the resolution decision in feedback. The Distiller will re-run with that decision and produce a conflict-free Requirement List for approval.",
    ])
    return "\n".join(lines)


def _build_interview_review_payload(
    record: Dict[str, Any],
    elicitation_items: list,
) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing interview_record.

    Schema matches the lean ELRecord shape: no focus_kind/focus_ref/covered_refs,
    no techniques, no coverage_note. Each agenda item carries vision_refs,
    perspective, scene, coverage, signals, assumption_evidence, gaps, and talk.
    """
    item_summaries = []
    for item in elicitation_items:
        talk = item.get("talk") or []
        last_answer = (talk[-1].get("answer") if talk else "") or ""
        answer_preview = last_answer[:200] + "…" if len(last_answer) > 200 else last_answer

        item_summaries.append({
            "id":               item.get("id"),
            "item":             item.get("item"),
            "vision_refs":     list(item.get("vision_refs") or item.get("assumption_refs") or []),
            "decision_target":  item.get("decision_target"),
            "context":          item.get("context"),
            "close_when":       item.get("close_when"),
            "coverage_points":  list(item.get("coverage_points") or []),
            "coverage":         list(item.get("coverage") or []),
            "stakeholder":      item.get("perspective"),
            "signals":          list(item.get("signals") or []),
            "assumption_evidence": list(item.get("assumption_evidence") or []),
            "gaps":             list(item.get("gaps") or []),
            "rule":             item.get("rule"),
            "answer_preview":   answer_preview,
            "turn_count":       len(talk),
            "status":           item.get("status"),
        })

    return {
        "project_description": record.get("project_description", ""),
        "total_items":         len(elicitation_items),
        "elicitation_items":   item_summaries,
    }


def _build_user_story_draft_review_payload(draft: Dict[str, Any]) -> Dict[str, Any]:
    """Build the structured payload shown to the PO when reviewing the user_story_draft.

    The draft is the SprintAgent's shape pass output — stories the PO signs off on
    BEFORE the Analyst sizes them. Shows per-story shaping decisions (reshape_op,
    source ids, title/description, thought) plus dropped requirements with reasons.
    """
    stories = draft.get("stories") or []

    story_summaries = []
    for story in stories:
        trace = story.get("requirement_trace") or {}
        story_summaries.append({
            "id":                     story.get("source_story_id") or story.get("id"),
            "source_requirement_ids": list(story.get("source_requirement_ids") or []),
            "reshape_op":             story.get("reshape_op", "carry"),
            "type":                   story.get("type"),
            "domain":                 story.get("domain"),
            "title":                  story.get("title"),
            "description":            story.get("description"),
            "thought":                story.get("thought", ""),
            "requirement_trace": {
                "requirement_id":         trace.get("requirement_id"),
                "requirement_type":       trace.get("requirement_type"),
                "stakeholder":            trace.get("stakeholder"),
                "statement":              trace.get("statement"),
                "rationale":              trace.get("rationale"),
                "trace_refs":             list(trace.get("trace_refs") or []),
                "merged_requirement_ids": list(trace.get("merged_requirement_ids") or []),
            },
        })

    return {
        "total_stories": len(stories),
        "stories":       story_summaries,
        "dropped":       list(draft.get("dropped") or []),
        # notes carries the shape report (merges / splits / rewrites / adds /
        # drops) the PO signs off on at this gate.
        "notes":         draft.get("notes", ""),
    }


def _build_product_backlog_review_payload(backlog: Dict[str, Any]) -> Dict[str, Any]:
    """Build the structured payload shown to the PO when reviewing the product_backlog.

    Reflects the consolidated PBI schema: estimation, prioritization, dependencies,
    planning, and quality blocks instead of flat top-level fields.
    """
    items = backlog.get("items") or []

    story_summaries = []
    for item in items:
        est   = item.get("estimation") or {}
        pri   = item.get("prioritization") or {}
        deps  = item.get("dependencies") or {}
        plan  = item.get("planning") or {}
        qual  = item.get("quality") or {}
        trace = item.get("requirement_trace") or {}

        analysis = item.get("analysis") or {}
        story_summaries.append({
            "id":            item.get("id"),
            "source_story_id": item.get("source_story_id"),
            # All approved requirement ids this PBI covers (≥1 after a merge).
            "source_requirement_ids": item.get("source_requirement_ids")
            or ([item.get("source_requirement_id")] if item.get("source_requirement_id") else []),
            "title":         item.get("title"),
            "type":          item.get("type"),
            "description":   item.get("description"),
            "requirement_trace": {
                "requirement_id": trace.get("requirement_id"),
                "requirement_type": trace.get("requirement_type"),
                "stakeholder": trace.get("stakeholder"),
                "trace_refs": list(trace.get("trace_refs") or []),
                "statement": trace.get("statement"),
                "rationale": trace.get("rationale"),
                "acceptance_criteria": list(trace.get("acceptance_criteria") or []),
                "merged_requirement_ids": list(trace.get("merged_requirement_ids") or []),
            },
            "story_points":  est.get("story_points"),
            "priority_rank": pri.get("priority_rank"),
            "wsjf_score":    pri.get("wsjf_score"),
            "invest_flags":  qual.get("invest_flags", []),
            "status":        plan.get("status"),
            "blocked_by":    deps.get("blocked_by", []),
            "blocks":        deps.get("blocks", []),
            # How this PBI was shaped from the approved set + why it is sized
            # this way, so the reviewer can sign off on changes to the
            # approved requirements.
            "reshape_op":            analysis.get("reshape_op", "none"),
            "estimation_reasoning":  analysis.get("estimation_reasoning", ""),
            "wsjf_thought":          analysis.get("wsjf_thought", ""),
        })

    return {
        "total_stories":   len(items),
        "methodology":     backlog.get("methodology", {}),
        "quality_warnings": backlog.get("quality_warnings", {}),
        # notes carries the shaping report (merges / splits / adds / drops)
        # the human signs off on at this gate.
        "notes":           backlog.get("notes", ""),
        "needs_human_input_count": backlog.get("needs_human_input_count", 0),
        "stories":         story_summaries,
    }


def _build_validated_product_backlog_review_payload(validated: Dict[str, Any]) -> Dict[str, Any]:
    """Build the structured payload shown to the PO when reviewing the validated_product_backlog.

    Reflects the consolidated PBI schema including the AC written by AnalystAgent.
    """
    items = validated.get("items") or []

    pbi_summaries = []
    for item in items:
        qual = item.get("quality") or {}
        est  = item.get("estimation") or {}
        plan = item.get("planning") or {}
        ac   = qual.get("acceptance_criteria") or []
        trace = item.get("requirement_trace") or {}

        pbi_summaries.append({
            "id":            item.get("id"),
            "source_story_id": item.get("source_story_id"),
            "source_requirement_id": item.get("source_requirement_id"),
            "title":         item.get("title"),
            "type":          item.get("type"),
            "description":   item.get("description"),
            "requirement_trace": {
                "requirement_id": trace.get("requirement_id"),
                "requirement_type": trace.get("requirement_type"),
                "stakeholder": trace.get("stakeholder"),
                "trace_refs": list(trace.get("trace_refs") or []),
                "threshold_needed": bool(trace.get("threshold_needed", False)),
                "priority": trace.get("priority"),
                "statement": trace.get("statement"),
                "rationale": trace.get("rationale"),
                "acceptance_criteria": list(trace.get("acceptance_criteria") or []),
            },
            "story_points":  est.get("story_points"),
            "priority_rank": (item.get("prioritization") or {}).get("priority_rank"),
            "status":        plan.get("status"),
            "invest_flags":  qual.get("invest_flags", []),
            "acceptance_criteria": [
                {
                    "id":    c.get("id"),
                    "type":  c.get("type"),
                    "given": c.get("given"),
                    "when":  c.get("when"),
                    "then":  c.get("then"),
                }
                for c in ac
            ],
        })

    return {
        "notes":              validated.get("notes", ""),
        "refinement_summary": validated.get("refinement_summary", ""),
        "refinement_stats":   validated.get("refinement_stats", {}),
        "pbis":               pbi_summaries,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Artifact persistence
# ─────────────────────────────────────────────────────────────────────────────

def _sync_artifacts_to_store(
    state:   WorkflowState,
    updates: Dict[str, Any],
) -> None:
    new_artifacts = updates.get("artifacts") or {}
    if not new_artifacts:
        return

    session_id   = state.get("session_id", "default")
    store        = _default_store()
    namespace    = ("artifacts", session_id)
    existing     = {
        item.key: item.value.get("content")
        for item in store.search(namespace)
    }

    base_dir     = Path("../artifacts")
    latest_dir   = base_dir / "artifact"
    versions_dir = base_dir / "versions"
    latest_dir.mkdir(parents=True, exist_ok=True)
    versions_dir.mkdir(parents=True, exist_ok=True)

    for name, content in new_artifacts.items():
        if name not in existing or existing[name] != content:
            store.put(namespace, name, {"content": content})
            file_name   = f"{name}_{session_id}.json"
            latest_path = latest_dir / file_name

            if latest_path.exists():
                ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
                version_path = versions_dir / f"{name}_{session_id}_v{ts}.json"
                shutil.move(str(latest_path), str(version_path))
                logger.info("File: versioned '%s'.", name)

            try:
                with open(latest_path, "w", encoding="utf-8") as f:
                    json.dump(content, f, ensure_ascii=False, indent=2)
                logger.info("File: saved artifact '%s' → %s", name, latest_path)
            except Exception as exc:
                logger.error("File: failed to save '%s': %s", name, exc)


def get_artifact_from_store(session_id: str, artifact_name: str) -> Optional[Any]:
    store = _default_store()
    item  = store.get(("artifacts", session_id), artifact_name)
    return item.value.get("content") if item else None


# ─────────────────────────────────────────────────────────────────────────────
# Conditional edge: after interviewer_turn
# ─────────────────────────────────────────────────────────────────────────────

def after_interviewer(state: WorkflowState) -> str:
    """Route after interviewer_turn completes.

    Bootstrap Phase:
      Turn 1 (vision produced, no reviewed_product_vision yet):
        product_vision in state, reviewed_product_vision NOT in artifacts
        → supervisor (for HITL review_product_vision_turn).
      Agenda is normally produced by agenda_turn. If interviewer_turn ever sees
      an unreviewed agenda artifact, route back to supervisor for the HITL gate.

    Synthesis Phase (Step 7):
      reviewed_interview_record exists → synthesis in progress or done
      → supervisor if done, else retry interviewer_turn.

    Elicitation Phase (Steps 3+):
      Question ready → enduser_turn.
      Answer needs processing → interviewer_turn (to call record_answer then ask_question).
    """
    artifacts = state.get("artifacts") or {}

    # 1. SYNTHESIS PHASE
    # if "reviewed_interview_record" in artifacts:
    #     if "requirement_list" in artifacts or state.get("interview_complete"):
    #         logger.info("after_interviewer: Synthesis complete → supervisor.")
    #         return "supervisor"
    #     else:
    #         logger.info("after_interviewer: Synthesis pending → interviewer_turn.")
    #         return "interviewer_turn"

    # 2. SAFETY GUARD — agenda artifact present but not yet HITL-reviewed.
    # (Normally agenda is built by agenda_turn, not interviewer_turn; this guard
    #  handles any edge case where state is inconsistent.)
    if (
        "elicitation_agenda_artifact" in artifacts
        and "reviewed_elicitation_agenda" not in artifacts
    ):
        logger.info(
            "after_interviewer: Agenda artifact present but not HITL-reviewed → supervisor."
        )
        return "supervisor"

    # 3. ELICITATION CONCLUDED DETECTOR
    # 'conclude' tool sets _needs_srs_synthesis=True when all agenda items are done.
    if state.get("_needs_srs_synthesis"):
        logger.info("after_interviewer: Elicitation concluded, record needs review → supervisor.")
        return "supervisor"

    # 4. SAFETY CAP
    turn_count = state.get("turn_count", 0)
    max_turns  = state.get("max_turns", _INTERVIEW_SAFETY_MAX_TURNS)
    if turn_count >= max_turns:
        logger.warning(
            "after_interviewer: safety cap reached (%d/%d) → supervisor.",
            turn_count, max_turns,
        )
        return "supervisor"

    # 5. ELICITATION LOOP — NEXT QUESTION NEEDED
    if state.get("_agenda_needs_question") or state.get("_agenda_needs_followup"):
        logger.debug(
            "after_interviewer: need question/followup "
            "(needs_question=%s, needs_followup=%s) → interviewer_turn.",
            bool(state.get("_agenda_needs_question")),
            bool(state.get("_agenda_needs_followup")),
        )
        return "interviewer_turn"

    # 6. ELICITATION LOOP — QUESTION READY
    if state.get("current_question"):
        logger.debug(
            "after_interviewer: question ready → enduser_turn (%d/%d turns).",
            turn_count, max_turns,
        )
        return "enduser_turn"

    # 7. FALLBACK
    logger.warning(
        "after_interviewer: no routing condition met "
        "(current_question=%r, needs_question=%s, needs_followup=%s) "
        "— forcing interviewer_turn for explicit next action.",
        state.get("current_question", ""),
        bool(state.get("_agenda_needs_question")),
        bool(state.get("_agenda_needs_followup")),
    )
    return "interviewer_turn"


# ─────────────────────────────────────────────────────────────────────────────
# Build graph
# ─────────────────────────────────────────────────────────────────────────────

def build_graph(store=None, checkpointer=None):
    """Compile the LangGraph workflow."""
    if store is None:
        store = _default_store()

    if checkpointer is None:
        logger.warning(
            "build_graph: no checkpointer. HITL review nodes use interrupt() "
            "which requires persistent storage in production."
        )
        checkpointer = InMemorySaver()

    g = StateGraph(WorkflowState)

    g.add_node("supervisor",                             supervisor_node_fn)
    g.add_node("visionary_turn",                         visionary_turn_fn)
    g.add_node("agenda_turn",                            agenda_turn_fn)
    g.add_node("distiller_turn",                         distiller_turn_fn)
    g.add_node("interviewer_turn",                       interviewer_turn_fn)
    g.add_node("enduser_turn",                           enduser_turn_fn)
    g.add_node("review_product_vision_turn",             review_product_vision_turn_fn)
    g.add_node("review_elicitation_agenda_turn",         review_elicitation_agenda_turn_fn)
    g.add_node("review_interview_record_turn",           review_interview_record_turn_fn)
    g.add_node("review_requirement_list_turn",           review_requirement_list_turn_fn)
    g.add_node("sprint_agent_turn",                      sprint_agent_turn_fn)
    g.add_node("review_user_story_draft_turn",           review_user_story_draft_turn_fn)
    g.add_node("analyst_estimation_turn",                analyst_estimation_turn_fn)
    g.add_node("review_product_backlog_turn",            review_product_backlog_turn_fn)
    g.add_node("analyst_turn",                           analyst_turn_fn)
    g.add_node("review_validated_product_backlog_turn",  review_validated_product_backlog_turn_fn)

    g.set_entry_point("supervisor")

    g.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "visionary_turn":                        "visionary_turn",
            "agenda_turn":                           "agenda_turn",
            "distiller_turn":                        "distiller_turn",
            "interviewer_turn":                      "interviewer_turn",
            "review_product_vision_turn":            "review_product_vision_turn",
            "review_elicitation_agenda_turn":        "review_elicitation_agenda_turn",
            "review_interview_record_turn":          "review_interview_record_turn",
            "review_requirement_list_turn":          "review_requirement_list_turn",
            "sprint_agent_turn":                     "sprint_agent_turn",
            "review_user_story_draft_turn":          "review_user_story_draft_turn",
            "analyst_estimation_turn":               "analyst_estimation_turn",
            "review_product_backlog_turn":           "review_product_backlog_turn",
            "analyst_turn":                          "analyst_turn",
            "review_validated_product_backlog_turn": "review_validated_product_backlog_turn",
            "__end__":                               END,
        },
    )
    g.add_conditional_edges(
        "interviewer_turn",
        after_interviewer,
        {
            "supervisor":       "supervisor",
            "enduser_turn":     "enduser_turn",
            "interviewer_turn": "interviewer_turn",
        },
    )

    g.add_edge("enduser_turn",                           "interviewer_turn")
    g.add_edge("visionary_turn",                         "supervisor")
    g.add_edge("agenda_turn",                            "supervisor")
    g.add_edge("distiller_turn",                         "supervisor")
    g.add_edge("review_product_vision_turn",             "supervisor")
    g.add_edge("review_elicitation_agenda_turn",         "supervisor")
    g.add_edge("review_interview_record_turn",           "supervisor")
    g.add_edge("review_requirement_list_turn",           "supervisor")
    g.add_edge("sprint_agent_turn",                      "supervisor")
    g.add_edge("review_user_story_draft_turn",           "supervisor")
    g.add_edge("analyst_estimation_turn",                "supervisor")
    g.add_edge("review_product_backlog_turn",            "supervisor")
    g.add_edge("analyst_turn",                           "supervisor")
    g.add_edge("review_validated_product_backlog_turn",  "supervisor")

    compile_kwargs: Dict[str, Any] = {"store": store}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)
