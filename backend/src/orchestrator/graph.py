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
    ├─► analyst_estimation_turn → supervisor         (Sprint Zero step 9c)
    ├─► review_product_backlog_turn → supervisor     (Sprint Zero step 10 — HITL)
    ├─► analyst_turn → supervisor                    (Backlog Refinement step 1)
    ├─► review_validated_product_backlog_turn → supervisor  (Backlog Refinement step 2 — HITL)
    └─► END

Sprint Zero backlog creation flow (steps 9a → 9c → 9b):
  sprint_agent_turn (9a: create_user_stories → user_story_draft)
    → analyst_estimation_turn (9c: estimate_and_validate_stories → analyst_estimation)
        [if has_pending_splits AND split_round < MAX]
        → sprint_agent_turn (split loop: apply split_proposals → updated user_story_draft)
        → analyst_estimation_turn (re-estimate sub-stories)
        [repeat until no splits or split_round = MAX]
    → sprint_agent_turn (9b: build_product_backlog → product_backlog)

sprint_agent_turn routing (after_sprint_agent conditional edge):
  • user_story_draft absent               → process_stories()  (Step 9a)
  • analyst_estimation present
    AND has_pending_splits=True
    AND split_round < MAX                 → process_splits()   (split loop)
  • user_story_draft present
    AND analyst_estimation present
    AND (has_pending_splits=False OR
         split_round >= MAX)              → process_backlog()  (Step 9b)

HITL review order:
  1. review_product_vision_turn      — human reviews/edits the ProductVision
  2. review_elicitation_agenda_turn  — human reviews/edits the ElicitationAgenda
  3. review_interview_record_turn    — human reads raw Q&A (approve-only, no reject)
  4. review_requirement_list_turn    — human reviews the synthesised Requirement List
     • Reject here re-runs synthesis only; interview_record is NOT touched.
  5. review_product_backlog_turn     — PO reviews the assembled product_backlog
     • Reject removes product_backlog, user_story_draft, AND analyst_estimation
       so all three steps (9a → 9c → 9b) re-run with PO feedback.
  On vision rejection: only product_vision is removed from artifacts;
    product_vision_feedback is injected; VisionaryAgent re-runs (visionary_turn).
  On agenda rejection: elicitation_agenda_artifact and aspect_map_artifact
    are removed; AgendaAgent rebuilds both passes using reviewed_product_vision
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
from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt

from .state import WorkflowState
from .supervisor import supervisor_node, supervisor_router

logger = logging.getLogger(__name__)

_INTERVIEW_SAFETY_MAX_TURNS = 3
_MAX_SPLIT_ROUND            = 2   # mirrors sprint.py constant


# ─────────────────────────────────────────────────────────────────────────────
# UI Summaries
# ─────────────────────────────────────────────────────────────────────────────

ARTIFACT_SUMMARIES: Dict[str, str] = {

    # Sent by interviewer_turn_fn on the very first turn — no artifact yet.
    "workflow_started": (
        "## Requirements Interview Started\n\n"
        "The AI Interviewer has begun a structured requirements discovery session "
        "with the virtual stakeholder.\n\n"
        "**What's happening:** The interviewer will ask a series of targeted questions "
        "to surface business facts, normal paths, exceptions, quality signals, "
        "and scope boundaries for your project.\n\n"
        "You can follow the conversation in real time below. "
        "When the interview is complete, you will be asked to review and approve the "
        "extracted requirements before the process continues."
    ),

    # Sent inside review_elicitation_agenda_turn interrupt — alongside the artifact.
    "elicitation_agenda": (
        "## Elicitation Agenda Ready for Review\n\n"
        "AgendaAgent has built an **Elicitation Agenda** from the approved "
        "Product Vision using structured mapping passes.\n\n"
        "**What's inside:**\n"
        "- **Aspect Map** — duty-to-agenda entries plus possible conflict hooks\n"
        "- **Conflict hooks** — places where precedence, scope split, or escalation needs dialogue\n"
        "- **Concern items** — quality probes derived from reviewed NFR concerns\n"
        "- **Agenda items** — one scene/probe/gap/close bundle per entry, sorted by flow order\n\n"
        "**Your action:** Review the agenda below. "
        "If duty coverage, conflict hooks, and item quality look correct, click **Accept** "
        "to start the interview. If entries are missing or items are too generic, "
        "click **Request Changes** — all passes will be rebuilt with your feedback."
    ),

    # Sent inside review_product_vision_turn interrupt — alongside the artifact.
    "product_vision": (
        "## Product Vision Ready for Review\n\n"
        "VisionaryAgent has analysed your project description and produced a "
        "**Product Vision** — the entity flow spine that drives all downstream "
        "agenda building, elicitation, and requirement synthesis.\n\n"
        "**What's inside:**\n"
        "- **Flow** — domain entities with lifecycle steps and active links between them\n"
        "- **Roles** — stakeholders with reviewable duties anchored to concrete flow moments\n"
        "- **NFR concerns** — quality softgoals to operationalize during interview\n"
        "- **Scope** — explicitly excluded capabilities, each with a reason\n\n"
        "**Your action:** Review the vision below. "
        "If the flow, stakeholder duties, NFR concerns, and scope boundaries accurately represent your project, "
        "click **Accept** to proceed to the elicitation agenda. "
        "If entities are missing, duties are wrong, NFR concerns are off, or scope boundaries are incorrect, "
        "click **Request Changes** — the vision will be regenerated with your feedback."
    ),

    # Sent inside review_interview_record_turn interrupt — alongside the artifact.
    "interview_record": (
        "## Requirements Interview Complete\n\n"
        "The AI Interviewer has finished the discovery session and compiled the "
        "stakeholder dialogue into an **Interview Record**.\n\n"
        "**What's inside:**\n"
        "- All agenda items that were discussed\n"
        "- The full question/answer dialogue captured for each item\n"
        "- The stakeholder role and close rule for each item\n\n"
        "**Your action:** Review the requirements below. "
        "If everything looks correct, click **Accept** to proceed to the Requirement List. "
        "This gate is view-only; requirement-level feedback belongs at the next review."
    ),

    # Sent inside review_requirement_list_turn interrupt — alongside the artifact.
    "requirement_list": (
        "## Requirement List Ready for Review\n\n"
        "DistillerAgent has synthesised all elicitation answers into a structured "
        "**Requirement List** — the authoritative specification used to build the "
        "Product Backlog.\n\n"
        "**What's inside:**\n"
        "- Functional Requirements (FR) — grounded in interview evidence or clear product baselines\n"
        "- Non-Functional Requirements (NFR) — explicit quality boundaries only\n"
        "- Out-of-Scope items (OOS) — reviewed Product Vision scope boundaries\n"
        "- Traceability: entity, step, aspect, and source per requirement\n"
        "- Acceptance criteria (≥1 per FR/NFR)\n"
        "- Conflicts (if any) — semantic contradictions requiring reviewer resolution\n\n"
        "**Note:** No CON type — constraints were removed (design_decisions no longer exist in ProductVision).\n\n"
        "**Your action:** Review the requirement list below. "
        "If conflicts are present, provide resolutions in your feedback — synthesis will re-run. "
        "Once conflict-free, click **Accept** to hand it to the Sprint Agent. "
        "Click **Request Changes** for gaps, misclassifications, or quality issues."
    ),

    # Sent inside review_product_backlog_turn interrupt — alongside the artifact.
    "product_backlog": (
        "## Initial Product Backlog Ready\n\n"
        "The Sprint Agent (Product Owner) and Analyst Agent (Technical Lead) have "
        "collaborated to build the initial **Product Backlog**.\n\n"
        "**What's inside:**\n"
        "- Each item written as: *As a \\<role\\>, I can \\<capability\\>, so that \\<benefit\\>*\n"
        "- Fibonacci story point estimates from the Analyst (Technical Lead)\n"
        "- WSJF priority scores with dependency-aware ranking\n"
        "- INVEST quality flags per story\n"
        "- Dependency map (blocked_by / blocks)\n\n"
        "**Your action:** Review the backlog below. "
        "Click **Accept** to hand it to the Analyst for Acceptance Criteria generation. "
        "Click **Request Changes** to send it back for revision — describe what "
        "story points, priorities, or story descriptions need adjustment. "
        "A rejection will trigger a full rebuild: stories → estimation → assembly."
    ),

    # Sent inside review_validated_product_backlog_turn interrupt — alongside the artifact.
    "validated_product_backlog": (
        "## Validated Product Backlog Ready\n\n"
        "The Analyst Agent has written Acceptance Criteria for every PBI:\n\n"
        "**What was done:**\n"
        "- **Acceptance Criteria** — 2–5 Given-When-Then criteria written per story, "
        "derived from original elicitation evidence and the user story capability clause\n"
        "- **Status** — every story with AC is now marked `ready`\n\n"
        "**Note:** INVEST validation and story point estimation were completed during "
        "backlog creation and are preserved unchanged.\n\n"
        "**Your action:** Review the validated backlog below. "
        "Click **Accept** to mark all `ready` stories available for Sprint planning. "
        "Click **Request Changes** to send the backlog back for AC re-generation — "
        "describe any AC quality issues or missing coverage."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Lazy agent singletons
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _default_store() -> InMemoryStore:
    return InMemoryStore()


@lru_cache(maxsize=1)
def _get_interviewer():
    from ..agent.interviewer import InterviewerAgent
    return InterviewerAgent()


@lru_cache(maxsize=1)
def _get_agenda():
    from ..agent.agenda import AgendaAgent
    return AgendaAgent()


@lru_cache(maxsize=1)
def _get_enduser():
    from ..agent.enduser import EndUserAgent
    return EndUserAgent()


@lru_cache(maxsize=1)
def _get_sprint_agent():
    from ..agent.sprint import SprintAgent
    return SprintAgent()


@lru_cache(maxsize=1)
def _get_analyst():
    from ..agent.analyst import AnalystAgent
    return AnalystAgent()


@lru_cache(maxsize=1)
def _get_visionary():
    from ..agent.visionary import VisionaryAgent
    return VisionaryAgent()

@lru_cache(maxsize=1)
def _get_distiller():
    from ..agent.distiller import DistillerAgent
    return DistillerAgent()
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
    updates = _get_visionary().process(state)
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

    updates = _get_interviewer().process(state)

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

    Dispatches to build_aspect_map or build_agenda_items based on state:
      build_aspect_map (Pass A/B/C):    produces aspect_map_artifact.
      build_agenda_items (Pass D):      produces elicitation_agenda_artifact
                                        and state["elicitation_agenda"].

    Routes unconditionally to supervisor after each pass. Supervisor re-fires
    agenda_turn until elicitation_agenda_artifact is present, then routes to
    review_elicitation_agenda_turn (HITL step 4).
    Also called after HITL rejection when elicitation_agenda_feedback is present.
    """
    updates = _get_agenda().process(state)
    artifacts_out = updates.get("artifacts") or {}
    logger.debug(
        "agenda_turn updates: %s | aspect_map=%s | agenda_artifact=%s | runtime=%s",
        list(updates.keys()),
        "present" if artifacts_out.get("aspect_map_artifact") else "MISSING",
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
    updates = _get_distiller().process(state)
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
        "_force_probe_next": False,
        "_agenda_needs_question": True,
        "_agenda_needs_followup": False,
        "item_turn_count": 0,
        "probe_presented": False,
    }


def enduser_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Run EndUserAgent, retrying if the agent exits without calling 'respond'.

    Resolves current_stakeholder_role from the agenda runtime before each attempt.

    AgendaRuntimeItem v5 carries a single `role` string per item — there is no
    multi-stakeholder cursor.  Role resolution priority:
      1. state["current_stakeholder_role"] — written by record_answer on advance.
      2. item.role — read directly from the current AgendaRuntimeItem.
      3. "" — fallback; EndUserAgent will use its config persona.

    EndUserAgent.respond sets should_return=True inside its own ReAct loop only.
    The edge from enduser_turn always returns to interviewer_turn — the enduser
    can never terminate the interview.
    """
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
                    resolved_role = getattr(item, "role", "") or ""
            except Exception as exc:
                logger.warning("enduser_turn_fn: failed to resolve stakeholder from agenda: %s", exc)

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

        updates = _get_enduser().process(augmented_state)
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
    Route to the correct SprintAgent method based on current state.

    Routing logic:
      1. user_story_draft absent → process_stories() (Step 9a: create stories)
      2. analyst_estimation present AND has_pending_splits=True
         AND split_round < MAX → process_splits() (split loop)
      3. user_story_draft present AND analyst_estimation present
         AND (no pending splits OR split_round >= MAX) → process_backlog() (Step 9b)
    """
    agent      = _get_sprint_agent()
    artifacts  = state.get("artifacts") or {}
    split_round = state.get("split_round", 0)

    has_draft      = "user_story_draft"   in artifacts
    has_estimation = "analyst_estimation" in artifacts

    if not has_draft:
        logger.info("sprint_agent_turn: no user_story_draft → process_stories() (Step 9a).")
        updates = agent.process_stories(state)

    elif has_estimation:
        estimation         = artifacts.get("analyst_estimation") or {}
        has_pending_splits = estimation.get("has_pending_splits", False)

        if has_pending_splits and split_round < _MAX_SPLIT_ROUND:
            logger.info(
                "sprint_agent_turn: has_pending_splits=True, split_round=%d → process_splits().",
                split_round,
            )
            updates = agent.process_splits(state)
        else:
            if has_pending_splits and split_round >= _MAX_SPLIT_ROUND:
                logger.warning(
                    "sprint_agent_turn: split_round=%d reached MAX (%d). "
                    "Proceeding to assembly with oversized stories.",
                    split_round, _MAX_SPLIT_ROUND,
                )
            logger.info("sprint_agent_turn: estimation ready → process_backlog() (Step 9b).")
            updates = agent.process_backlog(state)

    else:
        # user_story_draft present but analyst_estimation not yet available.
        # Supervisor should have routed to analyst_estimation_turn instead.
        logger.warning(
            "sprint_agent_turn: user_story_draft present but analyst_estimation absent. "
            "Supervisor routing may be inconsistent. Returning empty update."
        )
        updates = {}

    logger.debug("sprint_agent_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


def analyst_estimation_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """
    Run AnalystAgent.process_estimation() — Phase 1 technical estimation.

    Called for Step 9c (estimate_and_validate_stories) and also during
    split loop re-estimation when SprintAgent has applied split proposals.
    """
    updates = _get_analyst().process_estimation(state)
    logger.debug("analyst_estimation_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


def analyst_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Run AnalystAgent.process() — Phase 2 AC generation."""
    updates = _get_analyst().process(state)
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
      approved=False → remove aspect_map_artifact + elicitation_agenda_artifact,
                       inject elicitation_agenda_feedback; flow returns to
                       agenda_turn so all passes are rebuilt using
                       reviewed_product_vision + feedback.
    """
    artifacts  = dict(state.get("artifacts") or {})
    agenda     = artifacts.get("elicitation_agenda_artifact", {})
    aspect_map = artifacts.get("aspect_map_artifact", {})

    interrupt_value = {
        "review_type":    "elicitation_agenda",
        "artifact_data":  agenda,
        "review_payload": _build_elicitation_agenda_review_payload(agenda, aspect_map),
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

    # On rejection: remove both artifacts so AgendaAgent rebuilds all passes.
    artifacts.pop("elicitation_agenda_artifact", None)
    artifacts.pop("aspect_map_artifact", None)
    logger.info("[ReviewElicitationAgenda] REJECTED. Feedback: %s", feedback or "(none)")
    agenda_feedback = feedback or "The reviewer did not provide specific feedback."
    return {
        "artifacts":                  artifacts,
        "elicitation_agenda_feedback": agenda_feedback,
        # Reset live state keys so AgendaAgent rebuilds all passes cleanly.
        "elicitation_agenda":         None,
        "aspect_map":                 None,
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
      approved=False → remove product_backlog, user_story_draft, AND
                       analyst_estimation so all three steps (9a → 9c → 9b)
                       re-run with PO feedback injected.
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

    # On rejection: remove product_backlog AND the two intermediate artifacts
    # so all three steps (9a → 9c → 9b) re-run from scratch with feedback.
    artifacts.pop("product_backlog",     None)
    artifacts.pop("user_story_draft",    None)
    artifacts.pop("analyst_estimation",  None)
    logger.info("[ReviewProductBacklog] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":               artifacts,
        "product_backlog_feedback": feedback or "The reviewer did not provide specific feedback.",
        "split_round":             0,   # reset split counter for fresh cycle
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
      approved=False → remove validated_product_backlog, inject analyst_feedback;
                       flow returns to generate_acceptance_criteria (AC re-written only,
                       INVEST and estimation are NOT repeated).
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

    artifacts.pop("validated_product_backlog", None)
    logger.info("[AnalystReview] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":       artifacts,
        "analyst_feedback": feedback or "The reviewer did not provide specific feedback.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Review payload builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_product_vision_review_payload(vision: Dict[str, Any]) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing product_vision."""
    flow  = vision.get("flow") or {}
    roles = vision.get("roles") or []
    scope = vision.get("scope") or []
    concerns = vision.get("nfr_concerns") or []

    return {
        "description": vision.get("description", ""),
        "flow": {
            "entities": [
                {
                    "name": entity.get("name"),
                    "kind": entity.get("kind"),
                    "related_to": entity.get("related_to"),
                    "purpose": entity.get("purpose"),
                    "steps": entity.get("steps", []),
                    "order": entity.get("order"),
                    "signal": entity.get("signal"),
                }
                for entity in (flow.get("entities") or [])
            ],
            "links":    flow.get("links", []),
        },
        "roles": [
            {
                "name": role.get("name"),
                "kind": role.get("kind"),
                "duties": [
                    {
                        "id":       duty.get("id"),
                        "rule":     duty.get("rule"),
                        "risk":     duty.get("risk"),
                        "aspect":   duty.get("aspect"),
                        "entity":   duty.get("entity"),
                        "step":     duty.get("step"),
                        "entity_refs": duty.get("entity_refs", []),
                        "flow_step_refs": duty.get("flow_step_refs", []),
                        "priority": duty.get("priority"),
                    }
                    for duty in (role.get("duties") or [])
                ],
            }
            for role in roles
        ],
        "nfr_concerns": [
            {
                "id": concern.get("id"),
                "category": concern.get("category"),
                "theme": concern.get("theme"),
                "attached_to": concern.get("attached_to", []),
                "affected_roles": concern.get("affected_roles", []),
                "rationale": concern.get("rationale"),
            }
            for concern in concerns
        ],
        "scope": [
            {
                "id":     item.get("id"),
                "item":   item.get("item"),
                "reason": item.get("reason"),
            }
            for item in scope
        ],
    }


def _build_elicitation_agenda_review_payload(
    agenda: Dict[str, Any],
    aspect_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing elicitation_agenda_artifact.

    Shows:
      • aspect map entries for ordinary needs and possible conflicts
      • agenda items with context, probe, gap, and close rule
    """
    source_map = aspect_map or {}

    am_entries = [
        {
            "id":     e.get("id"),
            "entity": e.get("entity"),
            "step":   e.get("step"),
            "role":   e.get("role"),
            "aspect": e.get("aspect"),
            "source": e.get("source"),
            "kind":   e.get("kind"),
            "peer":   e.get("peer"),
            "note":   e.get("note"),
            "risk":   e.get("risk"),
            "concern_ref": e.get("concern_ref"),
            "concern_category": e.get("concern_category"),
            "concern_theme": e.get("concern_theme"),
        }
        for e in (source_map.get("entries") or [])
    ]

    items = []
    for item in agenda.get("items") or []:
        items.append({
            "id":       item.get("id"),
            "entity":   item.get("entity"),
            "step":     item.get("step"),
            "role":     item.get("role"),
            "aspect":   item.get("aspect"),
            "trap":     item.get("trap"),
            "kind":     item.get("kind"),
            "baseline": item.get("baseline"),
            "scene":    item.get("scene"),
            "risk":     item.get("risk"),
            "probe":    item.get("probe"),
            "gap":      item.get("gap"),
            "close":    item.get("close"),
            "source":   item.get("source"),
            "peer":     item.get("peer"),
            "concern_ref": item.get("concern_ref"),
            "concern_category": item.get("concern_category"),
            "concern_theme": item.get("concern_theme"),
        })

    return {
        "session_id":     agenda.get("session_id", ""),
        "created_at":     agenda.get("created_at", ""),
        "summary":        agenda.get("summary", {}),
        "map_summary":    source_map.get("summary", {}),
        "aspect_entries": am_entries,
        "total_items":    len(items),
        "items":          items,
        "flow":           agenda.get("flow", ""),
    }


def _build_requirement_list_review_payload(
    req_list: Dict[str, Any],
    requirements: list,
) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing requirement_list."""
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
            "category":            r.get("category"),
            "concern_theme":       r.get("concern_theme"),
            "requires_threshold":  r.get("requires_threshold", False),
            "entity_refs":         r.get("entity_refs", []),
            "flow_step_refs":      r.get("flow_step_refs", []),
            "acceptance_criteria": r.get("acceptance_criteria", []),
        })

    return {
        "session_id":        req_list.get("session_id", ""),
        "synthesised_at":    req_list.get("synthesised_at", ""),
        "total_requirements": len(requirements),
        "by_type":           by_type,
        "items":             req_summaries,
        "has_conflicts":     bool(req_list.get("conflicts") or []),
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

    Schema matches InterviewerAgent conclude output.
    """
    item_summaries = []
    for item in elicitation_items:
        # Truncate long answers for display but keep enough context
        answer = item.get("answer", "") or ""
        answer_preview = answer[:200] + "…" if len(answer) > 200 else answer

        item_summaries.append({
            "id":          item.get("id"),
            "item":        item.get("item"),
            "entity":      item.get("entity"),
            "step":        item.get("step"),
            "aspect":      item.get("aspect"),
            "trap":        item.get("trap"),
            "kind":        item.get("kind"),
            "close":       item.get("close"),
            "source":      item.get("source"),
            "risk":        item.get("risk"),
            "concern_ref": item.get("concern_ref"),
            "concern_category": item.get("concern_category"),
            "concern_theme": item.get("concern_theme"),
            "stakeholder": item.get("role"),
            "question":    item.get("question", "(not recorded)"),
            "answer":      answer_preview,
            "turn_count":  len(item.get("talk") or []),
            "status":      item.get("status"),
        })

    return {
        "project_description": record.get("project_description", ""),
        # interview_record from _tool_conclude does not carry completeness_score,
        # gaps_identified, total_turns, or notes — omit to avoid misleading None values.
        "total_items":         len(elicitation_items),
        "elicitation_items":   item_summaries,
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

        story_summaries.append({
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
                "entity": trace.get("entity"),
                "step": trace.get("step"),
                "aspect": trace.get("aspect"),
                "priority": trace.get("priority"),
                "source": trace.get("source"),
                "origin": trace.get("origin"),
                "statement": trace.get("statement"),
                "rationale": trace.get("rationale"),
                "acceptance_criteria": trace.get("acceptance_criteria", []),
            },
            "story_points":  est.get("story_points"),
            "priority_rank": pri.get("priority_rank"),
            "wsjf_score":    pri.get("wsjf_score"),
            "invest_flags":  qual.get("invest_flags", []),
            "status":        plan.get("status"),
            "blocked_by":    deps.get("blocked_by", []),
            "blocks":        deps.get("blocks", []),
        })

    return {
        "total_stories":   len(items),
        "methodology":     backlog.get("methodology", {}),
        "quality_warnings": backlog.get("quality_warnings", {}),
        "notes":           backlog.get("pass_notes", ""),
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
                "entity": trace.get("entity"),
                "step": trace.get("step"),
                "aspect": trace.get("aspect"),
                "priority": trace.get("priority"),
                "source": trace.get("source"),
                "origin": trace.get("origin"),
                "statement": trace.get("statement"),
                "rationale": trace.get("rationale"),
                "acceptance_criteria": trace.get("acceptance_criteria", []),
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
    g.add_edge("analyst_estimation_turn",                "supervisor")
    g.add_edge("review_product_backlog_turn",            "supervisor")
    g.add_edge("analyst_turn",                           "supervisor")
    g.add_edge("review_validated_product_backlog_turn",  "supervisor")

    compile_kwargs: Dict[str, Any] = {"store": store}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)
