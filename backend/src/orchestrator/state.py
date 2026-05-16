"""
state.py

WorkflowState — single source of truth flowing through the LangGraph graph.

Artifact chain (v7 — Entity Flow Spine)
────────────────────────────────────────
Phase 1 (sprint_zero_planning):
  product_vision                 ← produced by VisionaryAgent (flow + roles + NFR concerns + scope)
  reviewed_product_vision        ← HITL approval
  aspect_map_artifact            ← produced by AgendaAgent Pass A/B/C (duty/concern/conflict mapping)
  elicitation_agenda_artifact    ← produced by AgendaAgent Pass D, approved by HITL
  interview_record               ← produced by InterviewerAgent (conclude), approved by HITL
  requirement_list               ← produced by DistillerAgent (3-pass synthesis)
  requirement_list_approved      ← HITL approval
  user_story_draft               ← produced by SprintAgent Pass 1
  analyst_estimation             ← produced by AnalystAgent (feasibility + INVEST + estimation)
  product_backlog                ← produced by SprintAgent Pass 2 (WSJF + assembly)
  product_backlog_approved       ← HITL approval

Phase 2 (backlog_refinement):
  validated_product_backlog      ← produced by AnalystAgent Pass 3 (AC generation)
  analyst_review_done            ← HITL approval

Elicitation state (v7)
──────────────────────
  elicitation_agenda  → AgendaRuntime dict (Pass D of AgendaAgent)
  aspect_map          → AspectMap dict (Pass A/B/C of AgendaAgent)
  item_turn_count     → per-item turn counter (reset on advance)
  probe_presented     → gate flag for mandatory probe before item close
  current_question / enduser_answer → handshake between Interviewer and EndUser
  current_stakeholder_role → persona key for EndUserAgent
  conversation        → per-item dialogue buffer (flushed on advance)

Agenda-driven flow (InterviewerAgent v6)
────────────────────────────────────────
  InterviewerAgent reads current agenda item (entity, step, role, scene,
  baseline, risk, probe, gap, close, aspect, trap, kind).
  kind=concern runs quality probing; need/conflict run rule clarification.
  EndUserAgent receives only role + scene + entity + step grounding.
  System gates (turn budget, probe gate) are enforced in code; all interview
  strategy lives in the LLM prompts.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


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
    # Each item (AgendaRuntimeItem): { id, entity, step, role, aspect, trap, kind,
    #   baseline, scene, risk, probe, gap, close,
    #   status, question, answer, talk, rule, align, signals }
    elicitation_agenda: Dict[str, Any]

    # Serialised AspectMap dict produced by AgendaAgent Pass A/B/C.
    # Contains entries for duty needs, NFR concerns, and conflict hooks.
    aspect_map: Dict[str, Any]

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

    # probe_presented: True once ask_question is called with probe_injected=True.
    probe_presented: bool

    # ── Sprint / Analyst collaboration intermediate artifacts ──────────────
    # user_story_draft: produced by SprintAgent Pass 1.
    user_story_draft: Dict[str, Any]

    # analyst_estimation: produced by AnalystAgent (feasibility + INVEST + estimation).
    analyst_estimation: Dict[str, Any]

    # split_round: tracks how many split cycles have occurred between
    # SprintAgent and AnalystAgent. Hard limit = 2 to prevent infinite loops.
    split_round: int

    # ── Sprint Zero HITL ───────────────────────────────────────────────────
    review_feedback:              Optional[str]
    product_vision_feedback:      Optional[str]
    elicitation_agenda_feedback:  Optional[str]
    requirement_list_feedback:    Optional[str]
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

    # Distiller conflict-resolution short-circuit. When the requirement_list
    # HITL gate returns conflict-resolution feedback, the reviewer's choice
    # is the governing rule for Pass 3 only — Pass 1 and Pass 2 candidates
    # are valid and do not need re-running. The handler sets the flag and
    # carries the previous Pass 1+2 items and the surfaced conflicts in
    # the carryover fields below; distiller.process() reads them, runs only
    # Pass 3 with the CONFLICT FEEDBACK ADHERENCE addendum, and clears the
    # fields when synthesis completes.
    _distiller_pass3_only:          bool
    _pass3_carryover_items:         List[Dict[str, Any]]
    _pass3_carryover_conflicts:     List[Dict[str, Any]]

    # Set by record_answer tool; tells after_interviewer to retry
    # interviewer_turn instead of routing to enduser_turn.
    _agenda_needs_question:     bool
    _agenda_needs_followup: bool
    _force_probe_next: bool

    # ── UI signalling (transient) ──────────────────────────────────────────
    _workflow_started_message: bool

    # ── Error accumulation ─────────────────────────────────────────────────
    errors: List[str]
