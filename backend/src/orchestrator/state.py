"""
state.py

WorkflowState — single source of truth flowing through the LangGraph graph.

Artifact chain (v10 — Lean Assumption-Centered Elicitation)
────────────────────────────────────────
Phase 1 (sprint_zero_planning):
  product_vision                 ← produced by VisionaryAgent (intent/outcome + roles + known_signals + curated assumptions + concerns + scope)
  reviewed_product_vision        ← HITL approval
  elicitation_agenda_artifact    ← produced by AgendaAgent (assumption-centered items: perspective + scene + decision_target + seed_question + coverage_points), approved by HITL
  interview_record               ← produced by InterviewerAgent (conclude), approved by HITL
  requirement_list               ← produced by DistillerAgent (map + vision preservation + final merge & audit)
  requirement_list_approved      ← HITL approval
  user_story_draft               ← produced by SprintAgent Pass 1
  analyst_estimation             ← produced by AnalystAgent (feasibility + INVEST + estimation)
  product_backlog                ← produced by SprintAgent Pass 2 (WSJF + assembly)
  product_backlog_approved       ← HITL approval

Phase 2 (backlog_refinement):
  validated_product_backlog      ← produced by AnalystAgent Pass 3 (AC generation)
  analyst_review_done            ← HITL approval

Elicitation state (v9)
──────────────────────
  elicitation_agenda  → AgendaRuntime dict (assumption-centered agenda)
  item_turn_count     → per-item question counter (reset on advance)
  current_question / enduser_answer → handshake between Interviewer and EndUser
  current_stakeholder_role → strict perspective key for EndUserAgent
  conversation        → per-item dialogue buffer (flushed on advance)

Agenda-driven flow (InterviewerAgent v10)
─────────────────────────────────────────
  Each agenda item is assumption-backed, concern-led:
    concern_ref      → single CONCERN-NN that opens the lived gate
    assumption_refs  → 1+ ASM-NN forks the evidence should move into features
    scope_refs       → 0+ OOS-NN boundary edges touched in this scene
  AgendaRuntimeItem also exposes a derived `vision_refs` (concern_ref +
  assumption_refs + scope_refs combined) so downstream consumers
  (InterviewerAgent, EndUserAgent, DistillerAgent) can keep using one
  flat list of vision ids for lookups.

  InterviewerAgent reads the current agenda item (vision_refs flat list,
  perspective, context, decision_target, seed_question, close_when,
  coverage_points). EndUserAgent receives only perspective + scene context
  + current question. System gates enforce only safety limits; interview
  strategy lives in the ReAct addendum prompt and tool descriptions.

Vision mode (VisionaryAgent)
────────────────────────────
  vision_mode = "fidelity" runs Pass 1 (STATED+IMPLIED reading) and
  Pass 2 (STATED+IMPLIED forks). Output reflects what the project
  intent says or strictly implies. The minimum-stakeholder guarantee
  (infer a primary user from actor+action+object when the intent is
  silent) lives inside Pass 1 and applies in every mode.

  vision_mode = "coverage" additionally runs Pass 3 (INFERRED) which
  expands the vision with what generic product knowledge says products
  of this shape typically owe — additional roles, forks, concerns,
  scope edges — and is allowed to chain its inferences on the output
  of Pass 1+2.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypedDict


class SystemPhase(str, Enum):
    SPRINT_ZERO_PLANNING = "sprint_zero_planning"
    BACKLOG_REFINEMENT   = "backlog_refinement"
    SPRINT_EXECUTION     = "sprint_execution"
    SPRINT_REVIEW        = "sprint_review"


class ProcessPhase(str, Enum):
    ELICITATION   = "elicitation"
    ANALYSIS      = "analysis"
    SPECIFICATION = "specification"
    VALIDATION    = "validation"


class ConversationTurn(TypedDict):
    role:      str
    content:   str
    timestamp: str


class WorkflowState(TypedDict, total=False):

    # ── Session ────────────────────────────────────────────────────────────
    session_id:          str
    project_description: str

    # ── Phase management ───────────────────────────────────────────────────
    system_phase: str

    # ── Vision generation mode ─────────────────────────────────────────────
    # "fidelity"  → run only stated+implied passes (Pass 1 + Pass 2)
    # "coverage"  → also run Pass 3 (INFERRED expansion from generic
    #               product knowledge — surfaces additional roles, forks,
    #               concerns, scope edges the project intent did not name)
    # Default is "fidelity"; chosen at session start (CLI / UI).
    vision_mode: Literal["fidelity", "coverage"]

    # Per-chat runtime model overrides. Same shape as agent_config.yaml's
    # profiled llm block, normally {"default": {...}, "interview": {...}}.
    # The graph uses this to pick/cache agent instances for the chat.
    llm_overrides: Dict[str, Any]

    # ── Artifact store ─────────────────────────────────────────────────────
    artifacts:    Dict[str, Any]
    artifact_ids: Dict[str, str]

    # ── Supervisor routing ─────────────────────────────────────────────────
    next_node: str

    # ── Interview sub-state ────────────────────────────────────────────────
    conversation:       List[ConversationTurn]
    turn_count:         int
    max_turns:          int
    interview_complete: bool

    # ── Agenda-driven elicitation (InterviewerAgent v5) ───────────────────
    # Serialised ProductVision dict produced by VisionaryAgent.
    # Persisted here so LangGraph checkpoints it between turns.
    product_vision: Dict[str, Any]

    # Serialised AgendaRuntime dict:
    #   { items: [...], current_index: int, elicitation_complete: bool }
    # Each item (AgendaRuntimeItem): { id, concern_ref, assumption_refs,
    #   scope_refs, vision_refs (derived flat list), perspective, context,
    #   decision_target, seed_question, close_when, coverage_points, notes,
    #   status, question, answer, talk, rule, signals, assumption_evidence,
    #   gaps, coverage }
    elicitation_agenda: Dict[str, Any]

    # Handshake keys between InterviewerAgent and EndUserAgent.
    # InterviewerAgent writes current_question via ask_question tool.
    # EndUserAgent reads current_question, writes enduser_answer via respond tool.
    # InterviewerAgent reads enduser_answer via record_answer tool.
    current_question: str
    enduser_answer:   str

    # The role being interviewed in the current turn.
    current_stakeholder_role: str

    # Final summary written by the conclude tool.
    # Format: one block per answered item — "Q: ...\nA: ..."
    elicitation_notes: str

    # ── Agenda-driven elicitation turn controls (InterviewerAgent v5) ──────
    # item_turn_count: 1-indexed turn counter within the current agenda item.
    item_turn_count: int

    # ── Sprint / Analyst collaboration intermediate artifacts ──────────────
    # user_story_draft: produced by SprintAgent step 9a (shaping the approved
    # requirements into an INVEST-clean backlog story set).
    user_story_draft: Dict[str, Any]

    # analyst_estimation: produced by AnalystAgent step 9c (Fibonacci sizing +
    # INVEST assessment + in-pass reshaping). Its `stories` list is the
    # authoritative post-reshape set consumed by SprintAgent step 9b.
    analyst_estimation: Dict[str, Any]

    # ── Sprint Zero HITL ───────────────────────────────────────────────────
    review_feedback:              Optional[str]
    product_vision_feedback:      Optional[str]
    elicitation_agenda_feedback:  Optional[str]
    requirement_list_feedback:    Optional[str]
    user_story_draft_feedback:    Optional[str]
    product_backlog_feedback:     Optional[str]

    # ── Phase 2: Backlog Refinement ────────────────────────────────────────
    analyst_feedback: Optional[str]

    # ── ReAct / synthesis gate flags ───────────────────────────────────────
    _last_react_thought:        str
    _react_strategy:            str
    readiness_approved:         bool

    # Set by _tool_conclude; tells process() to run _synthesise_srs() on the
    # very next invocation (no EndUser turn in between).
    _needs_srs_synthesis:       bool

    # Set by record_answer tool; tells after_interviewer to retry
    # interviewer_turn instead of routing to enduser_turn.
    _agenda_needs_question:     bool
    _agenda_needs_followup: bool

    # Set by record_answer when the LLM disagreed with the heuristic
    # auto-skip route and tried to close an item without enough
    # covered_by_prior coverage. Suppresses the next process() retry so
    # interviewer_turn falls through to ask_question instead of looping.
    _disabled_prior_skip: bool

    # ── UI signalling (transient) ──────────────────────────────────────────
    _workflow_started_message: bool

    # ── Error accumulation ─────────────────────────────────────────────────
    errors: List[str]
