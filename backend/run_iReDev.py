"""
run_iReDev.py - Unified runner for full flow or debug starting/ending at any artifact.

Usage (full workflow):
    python run_iReDev.py
    python run_iReDev.py --max-turns 15
    python run_iReDev.py --project path/to/brief.txt
    python run_iReDev.py --db my_checkpoints.db --reset-db

Usage (debug from a specific artifact):
    python run_iReDev.py --start-at requirement_list
    python run_iReDev.py --start-at validated_product_backlog_approved --auto-approve

Usage (stop after a specific artifact is produced):
    python run_iReDev.py --end-at product_backlog
    python run_iReDev.py --start-at requirement_list --end-at product_backlog

Usage (debug from one artifact to another):
    python run_iReDev.py --start-at interview_record --end-at requirement_list_approved
"""

import argparse
import json
import logging
import os
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Debug manifest: for every target artifact, the artifacts that must be
# pre-loaded so the supervisor will select that step.
# Each entry: (state_key, file_prefix, is_sentinel)
# Sentinel artifacts are optional (missing file -> {}), non-sentinel are required.
# ---------------------------------------------------------------------------
def _manifest_for_product_vision():
    return []

def _manifest_for_reviewed_product_vision():
    return [("product_vision", "product_vision", False)]

def _manifest_for_elicitation_agenda_artifact():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
    ]

def _manifest_for_reviewed_elicitation_agenda():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
    ]

def _manifest_for_interview_record():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
    ]

def _manifest_for_reviewed_interview_record():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
    ]

def _manifest_for_requirement_list():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
    ]

def _manifest_for_requirement_list_approved():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
        ("requirement_list", "requirement_list", False),
    ]

def _manifest_for_product_backlog():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
        ("requirement_list", "requirement_list", False),
        ("requirement_list_approved", "requirement_list_approved", True),
    ]

def _manifest_for_product_backlog_approved():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
        ("requirement_list", "requirement_list", False),
        ("requirement_list_approved", "requirement_list_approved", True),
        ("product_backlog", "product_backlog", False),
    ]

def _manifest_for_validated_product_backlog():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
        ("requirement_list", "requirement_list", False),
        ("requirement_list_approved", "requirement_list_approved", True),
        ("product_backlog", "product_backlog", False),
        ("product_backlog_approved", "product_backlog_approved", True),
    ]

def _manifest_for_validated_product_backlog_approved():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
        ("requirement_list", "requirement_list", False),
        ("requirement_list_approved", "requirement_list_approved", True),
        ("product_backlog", "product_backlog", False),
        ("product_backlog_approved", "product_backlog_approved", True),
        ("validated_product_backlog", "validated_product_backlog", False),
    ]

DEBUG_MANIFESTS: Dict[str, callable] = {
    "product_vision":                    _manifest_for_product_vision,
    "reviewed_product_vision":           _manifest_for_reviewed_product_vision,
    "elicitation_agenda_artifact":       _manifest_for_elicitation_agenda_artifact,
    "reviewed_elicitation_agenda":       _manifest_for_reviewed_elicitation_agenda,
    "interview_record":                  _manifest_for_interview_record,
    "reviewed_interview_record":         _manifest_for_reviewed_interview_record,
    "requirement_list":                  _manifest_for_requirement_list,
    "requirement_list_approved":         _manifest_for_requirement_list_approved,
    "product_backlog":                   _manifest_for_product_backlog,
    "product_backlog_approved":          _manifest_for_product_backlog_approved,
    "validated_product_backlog":         _manifest_for_validated_product_backlog,
    "validated_product_backlog_approved": _manifest_for_validated_product_backlog_approved,
}

SEP = "=" * 70

def section(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")

def wrap(text: str, indent: int = 4) -> str:
    return textwrap.fill(
        str(text), width=80,
        initial_indent=" " * indent,
        subsequent_indent=" " * indent,
    )

# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="iReDev unified runner - full flow or debug from/to any artifact",
    )
    p.add_argument(
        "--start-at",
        type=str,
        default=None,
        choices=list(DEBUG_MANIFESTS.keys()),
        help="Debug mode: start at the step that produces this artifact.",
    )
    p.add_argument(
        "--end-at",
        type=str,
        default=None,
        choices=list(DEBUG_MANIFESTS.keys()),
        help="Stop the workflow immediately after this artifact is produced.",
    )
    p.add_argument(
        "--max-turns",
        type=int,
        default=20,
        help="Safety-net max interview turns (default: 20).",
    )
    p.add_argument(
        "--project",
        type=argparse.FileType("r", encoding="utf-8"),
        default=None,
        help="Path to project description file.",
    )
    p.add_argument(
        "--db",
        type=str,
        default="checkpoints.db",
        help="Path to SQLite checkpoint DB (default: checkpoints.db).",
    )
    p.add_argument(
        "--reset-db",
        action="store_true",
        help="Delete checkpoint DB before running.",
    )
    p.add_argument(
        "--auto-approve",
        action="store_true",
        help="Automatically approve all HITL gates without prompting.",
    )
    p.add_argument(
        "--mode",
        type=str,
        default="fidelity",
        choices=["fidelity", "coverage"],
        help=(
            "Vision generation mode (default: fidelity). "
            "'fidelity' runs only stated+implied passes (Pass 1 + Pass 2). "
            "'coverage' also runs Pass 3 (INFERRED expansion from generic "
            "product knowledge — adds roles, forks, concerns, scope edges "
            "the project intent did not name)."
        ),
    )
    p.add_argument(
        "--artifact-dir",
        type=str,
        default=None,
        help="Directory containing artifact JSON files (default: auto-detect ./artifacts/artifact/).",
    )
    p.add_argument(
        "--session",
        type=str,
        default="demo_session_1",
        help="Session ID used in artifact file names (default: demo_session_1).",
    )
    return p.parse_args()

# ---------------------------------------------------------------------------
# Artifact loading helpers
# ---------------------------------------------------------------------------
def resolve_artifact_dir(artifact_dir_arg: Optional[str]) -> Path:
    if artifact_dir_arg:
        p = Path(artifact_dir_arg).expanduser().resolve()
        if not p.is_dir():
            print(f"[ERROR] --artifact-dir does not exist: {p}")
            sys.exit(1)
        return p
    here = Path(__file__).resolve().parent
    for candidate in [here] + list(here.parents):
        guess = candidate / "artifacts" / "artifact"
        if guess.is_dir():
            return guess
    print("[ERROR] Could not find artifacts/artifact/ directory. Use --artifact-dir.")
    sys.exit(1)

def load_artifact(
    artifact_dir: Path,
    file_prefix: str,
    session: str,
    is_sentinel: bool,
) -> Optional[Dict[str, Any]]:
    path = artifact_dir / f"{file_prefix}_{session}.json"
    if not path.exists():
        if is_sentinel:
            print(f"  Sentinel missing, using empty dict: {path.name}")
            return {}
        print(f"  Required artifact not found: {path}")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        chars = len(json.dumps(data, ensure_ascii=False))
        tag = "  [sentinel]" if is_sentinel else ""
        print(f"  Loaded {path.name:<55} (~{chars:>7,} chars){tag}")
        return data
    except json.JSONDecodeError as exc:
        print(f"  JSON error in {path.name}: {exc}")
        sys.exit(1)

def build_artifacts(
    target: str,
    session: str,
    artifact_dir: Path,
) -> Dict[str, Any]:
    manifest_fn = DEBUG_MANIFESTS[target]
    manifest = manifest_fn()
    artifacts: Dict[str, Any] = {}
    missing_required: List[str] = []

    print(f"\nArtifact directory: {artifact_dir}")
    print(f"Loading {len(manifest)} prerequisite(s) to start at '{target}':\n")

    for state_key, file_prefix, is_sentinel in manifest:
        data = load_artifact(artifact_dir, file_prefix, session, is_sentinel)
        if data is None:
            missing_required.append(f"{file_prefix}_{session}.json")
        else:
            artifacts[state_key] = data

    if missing_required:
        print(f"\n[ERROR] Missing {len(missing_required)} required artifact(s):")
        for f in missing_required:
            print(f"   • {f}")
        sys.exit(1)

    print(f"\nLoaded {len(artifacts)} artifact(s) into initial state.")
    return artifacts

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_LENS_ICON = {"stated": "✓", "implied": "~", "inferred": "?"}
_STATUS_ICON = {
    "ready": "✓", "needs_refinement": "~", "needs_split": "↔",
    "needs_spike": "◉", "invest_failed": "✗", "oversized": "!",
    "needs_human_input": "H",
}
_CONF_ICON = {"confirmed": "✓", "inferred": "~"}


def display_product_vision(vision: dict) -> None:
    section("ARTIFACT: product_vision")
    roles = vision.get("roles") or []
    assumptions = vision.get("assumptions") or []
    concerns = vision.get("concerns") or []
    scope = vision.get("scope") or []
    known_signals = vision.get("known_signals") or []
    lens_counts: Dict[str, int] = {}
    for asm in assumptions:
        l = asm.get("lens", "?")
        lens_counts[l] = lens_counts.get(l, 0) + 1
    lens_str = ", ".join(f"{l}={n}" for l, n in sorted(lens_counts.items()))
    print(f"  Description   : {vision.get('description', '?')}")
    print(f"  Signals       : {len(known_signals)}")
    print(f"  Roles         : {len(roles)}")
    print(f"  Assumptions   : {len(assumptions)}  ({lens_str})")
    print(f"  Concerns      : {len(concerns)}")
    print(f"  Scope / OOS   : {len(scope)}")


def _flatten_item_refs(it: dict) -> list:
    flat: list = []
    cref = (it.get("concern_ref") or "").strip()
    if cref:
        flat.append(cref)
    flat.extend(it.get("assumption_refs") or [])
    flat.extend(it.get("scope_refs") or [])
    # Fall back to legacy flat field if present (covers older artifacts loaded
    # via --start-at).
    if not flat:
        flat = list(it.get("vision_refs") or [])
    return flat


def display_elicitation_agenda(agenda: dict) -> None:
    section("ARTIFACT: elicitation_agenda_artifact")
    items = agenda.get("items") or []
    all_refs: set = set()
    for it in items:
        all_refs.update(_flatten_item_refs(it))
    print(f"  Items         : {len(items)}  |  vision refs covered: {len(all_refs)}")
    for it in items:
        cref = (it.get("concern_ref") or "").strip() or "?"
        asms = ", ".join(it.get("assumption_refs") or []) or "(none)"
        scope_list = it.get("scope_refs") or []
        scope_part = f"  scope=[{', '.join(scope_list)}]" if scope_list else ""
        cps = len(it.get("coverage_points") or [])
        print(
            f"    [{it.get('id','?')}] {it.get('perspective','?'):<30}"
            f"  concern={cref}  asm=[{asms}]{scope_part}  coverage_points={cps}"
        )


def display_requirement_list(rl: dict) -> None:
    section("ARTIFACT: requirement_list")
    reqs = rl.get("items") or []
    conflicts = rl.get("conflicts") or []
    gaps = rl.get("gaps") or []
    by_type: Dict[str, int] = {}
    by_conf: Dict[str, int] = {}
    for r in reqs:
        by_type[r.get("type", "?")] = by_type.get(r.get("type", "?"), 0) + 1
        by_conf[r.get("confidence", "?")] = by_conf.get(r.get("confidence", "?"), 0) + 1
    type_str = "  ".join(f"{t}={n}" for t, n in sorted(by_type.items()))
    conf_str = "  ".join(f"{c}={n}" for c, n in sorted(by_conf.items()))
    print(f"  Total         : {len(reqs)}  |  conflicts: {len(conflicts)}  |  gaps: {len(gaps)}")
    print(f"  By type       : {type_str}")
    print(f"  Confidence    : {conf_str}")
    if conflicts:
        print(f"\n  Conflicts:")
        for conflict in conflicts:
            display_conflict(conflict, indent=4)


def display_conflict(conflict: dict, indent: int = 2) -> None:
    pad = " " * indent
    conflict_id = conflict.get("id", "?")
    left = conflict.get("left", "?")
    right = conflict.get("right", "?")
    kind = conflict.get("kind", "?")
    scope = conflict.get("scope", "(scope not specified)")
    issue = conflict.get("issue", "(no issue text)")
    print(f"{pad}• [{conflict_id}] {kind}: {left} ↔ {right}")
    print(wrap(f"Scope: {scope}", indent=indent + 2))
    print(wrap(f"Issue: {issue}", indent=indent + 2))
    paths = conflict.get("paths") or []
    if paths:
        print(f"{pad}  Resolution options:")
        for path in paths:
            print(wrap(f"- {path}", indent=indent + 4))
    refs = conflict.get("refs") or []
    if refs:
        print(f"{pad}  Refs: {', '.join(refs)}")


def display_product_backlog(artifact: dict) -> None:
    section("ARTIFACT: product_backlog")
    items = artifact.get("items") or []
    qw = artifact.get("quality_warnings") or {}
    total_warn = sum(len(v) for v in qw.values() if isinstance(v, list))
    print(f"  Total items   : {artifact.get('total_items', len(items))}  |  sp: {artifact.get('total_story_points', '?')}")
    print(f"  Ready={artifact.get('ready_count',0)}  refine={artifact.get('needs_refinement_count',0)}  "
          f"split={artifact.get('needs_split_count',0)}  spike={artifact.get('needs_spike_count',0)}  "
          f"invest_fail={artifact.get('invest_failed_count',0)}  oversized={artifact.get('oversized_count',0)}")
    if total_warn:
        print(f"  Warnings      : {total_warn}")


def display_validated_product_backlog(artifact: dict) -> None:
    section("ARTIFACT: validated_product_backlog")
    items = artifact.get("items") or []
    stats = artifact.get("refinement_stats") or {}
    print(f"  Total PBIs    : {stats.get('total_pbis', len(items))}")
    print(f"  Ready PBIs    : {stats.get('ready_count', artifact.get('ready_count', '?'))}")
    print(f"  Total AC      : {stats.get('total_ac', '?')}")

# ---------------------------------------------------------------------------
# HITL interactive / auto-approve handler
# ---------------------------------------------------------------------------
def collect_review_decision(updates: tuple, auto_approve: bool) -> Dict[str, Any]:
    conflict_payload: Optional[Dict[str, Any]] = None
    for interrupt_obj in updates:
        payload = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj
        if not isinstance(payload, dict):
            continue
        review_type = payload.get("review_type", "unknown")
        print(f"\n{'─'*70}")
        print(f"  HITL GATE - {review_type.upper().replace('_', ' ')}")
        print(f"{'─'*70}")

        artifact_data = payload.get("artifact_data") or {}
        if review_type == "requirement_list":
            reqs = artifact_data.get("items") or []
            conflicts = payload.get("conflict_data") or artifact_data.get("conflicts") or []
            by_type: Dict[str, int] = {}
            for r in reqs:
                by_type[r.get("type", "?")] = by_type.get(r.get("type", "?"), 0) + 1
            print(f"\n  {len(reqs)} requirements (FR={by_type.get('functional',0)} ... )")
            if conflicts:
                conflict_payload = payload
                print(f"\n  {len(conflicts)} conflict(s) block approval:")
                for conflict in conflicts:
                    display_conflict(conflict, indent=4)
        elif review_type == "elicitation_agenda":
            items_list = artifact_data.get("items") or []
            # Collect all vision refs covered across items (concern + assumptions + scope)
            all_refs: set = set()
            for it in items_list:
                all_refs.update(_flatten_item_refs(it))
            print(
                f"\n  {len(items_list)} agenda item(s)  "
                f"covering {len(all_refs)} vision ref(s): {', '.join(sorted(all_refs)) or '(none)'}"
            )
            for it in items_list:
                cref = (it.get("concern_ref") or "").strip() or "?"
                asms = ", ".join(it.get("assumption_refs") or []) or "(none)"
                scope_list = it.get("scope_refs") or []
                scope_part = f" scope=[{', '.join(scope_list)}]" if scope_list else ""
                print(
                    f"    [{it.get('id','?')}] concern={cref} asm=[{asms}]{scope_part}"
                    f"  →  {it.get('perspective','?')}"
                    f"  |  {it.get('decision_target','')}"
                )
        elif review_type == "product_backlog":
            items = artifact_data.get("items") or []
            print(f"\n  {len(items)} user stories")
        elif review_type == "validated_product_backlog":
            items = artifact_data.get("items") or []
            print(f"\n  {len(items)} validated PBIs")
        # other types can be added similarly

    if conflict_payload is not None:
        conflicts = (
            conflict_payload.get("conflict_data")
            or (conflict_payload.get("artifact_data") or {}).get("conflicts")
            or []
        )
        print(f"\n{'─'*70}  CONFLICT RESOLUTION REQUIRED")
        print(
            "  Requirement List approval is disabled until these conflicts are resolved."
        )
        if auto_approve:
            print("  [auto-approve] Skipped: conflict gate requires resolution feedback.")
            return {
                "approved": False,
                "feedback": "No specific conflict resolution provided in auto-approve mode.",
            }

        print("\n  Provide resolution feedback for the conflict(s) above.")
        print("  Mention the conflict id and the decision to apply. Blank line to finish:")
        lines = []
        while True:
            line = input("  > ")
            if not line:
                break
            lines.append(line)
        feedback = " ".join(lines).strip()
        if not feedback:
            feedback = (
                "No specific conflict resolution provided. Re-run synthesis and keep "
                f"{len(conflicts)} conflict(s) visible for reviewer resolution."
            )
        return {"approved": False, "feedback": feedback}

    if auto_approve:
        print("\n  [auto-approve] Approved")
        return {"approved": True, "feedback": None}

    print(f"\n{'─'*70}  REVIEW DECISION")
    while True:
        choice = input("\n  Approve? [y/n]: ").strip().lower()
        if choice in ("y", "n"):
            break
        print("  Please enter y or n.")

    if choice == "y":
        notes = input("  Optional notes (Enter to skip): ").strip()
        return {"approved": True, "feedback": notes or None}
    else:
        print("\n  Provide feedback (blank line to finish):")
        lines = []
        while True:
            line = input("  > ")
            if not line:
                break
            lines.append(line)
        feedback = " ".join(lines).strip() or "No specific feedback provided."
        return {"approved": False, "feedback": feedback}

# ---------------------------------------------------------------------------
# State initialisation
# ---------------------------------------------------------------------------
def build_initial_state(args, preloaded_artifacts=None):
    from src.config.intake_hint import INTAKE_HINT, VISIONARY_CONTRACT
    input_guidance = INTAKE_HINT
    visionary_contract = VISIONARY_CONTRACT
    if args.project:
        project_desc = args.project.read()
        args.project.close()
    else:
        project_desc = (
            "We need a course-registration system for university students. "
            "Students should be able to browse available courses, register for "
            "up to 5 courses per semester, view their schedule, and receive "
            "notifications about enrollment deadlines."
        )

    state: Dict[str, Any] = {}

    if preloaded_artifacts:
        interview_record = preloaded_artifacts.get("interview_record") or {}
        pd_from_record = interview_record.get("project_description")
        if pd_from_record:
            project_desc = pd_from_record
        artifacts = preloaded_artifacts

        # Seed the agent’s own state fields so it doesn’t re‑run bootstrap steps
        if "product_vision" in artifacts:
            state["product_vision"] = artifacts["product_vision"]
        raw_agenda = (
            artifacts.get("reviewed_elicitation_agenda")
            or artifacts.get("elicitation_agenda_artifact")
        )
        if raw_agenda:
            try:
                from src.agent.agenda import AgendaRuntime
                state["elicitation_agenda"] = (
                    AgendaRuntime.from_agenda_artifact(raw_agenda).model_dump()
                )
            except Exception as exc:
                print(f"[WARNING] Could not normalise elicitation agenda: {exc}")
                state["elicitation_agenda"] = raw_agenda

        needs_srs = (args.start_at == "requirement_list")
        interview_complete = True if needs_srs else False
    else:
        artifacts = {}
        needs_srs = False
        interview_complete = False

    state.update({
        "session_id":          args.session,
        "project_description": project_desc,
        "input_guidance":      input_guidance,
        "visionary_contract":  visionary_contract,
        "vision_mode":         args.mode,
        "system_phase":        "sprint_zero_planning",
        "artifacts":           artifacts,
        "conversation":        [],
        "turn_count":          0,
        "max_turns":           args.max_turns,
        "interview_complete":  interview_complete,
        "requirements_draft":  [],
        "backlog_draft":       [],
        "errors":              [],
        "_needs_srs_synthesis": needs_srs,
    })
    return state

# ---------------------------------------------------------------------------
# Stream loop with interrupt and end-at support
# ---------------------------------------------------------------------------
def run_workflow(initial_state, config, args):
    from src.orchestrator import build_graph
    # printed_artifacts tracks every artifact that has been displayed so far.
    # Nodes often return the full artifacts dict (not just new entries), so
    # without this guard the same artifact would be printed on every subsequent
    # node update.
    printed_artifacts: set = set(initial_state.get("artifacts", {}).keys())
    final_artifacts = dict(initial_state.get("artifacts", {}))
    end_artifact = args.end_at

    # Display functions keyed by artifact name.
    _DISPLAY: Dict[str, Any] = {
        "product_vision":              display_product_vision,
        "elicitation_agenda_artifact": display_elicitation_agenda,
        "requirement_list":            display_requirement_list,
        "product_backlog":             display_product_backlog,
        "validated_product_backlog":   display_validated_product_backlog,
    }

    # If the end artifact is already present, stop immediately
    if end_artifact and end_artifact in final_artifacts:
        print(f"\nTarget end artifact '{end_artifact}' already in initial state. Nothing to do.")
        return final_artifacts

    with SqliteSaver.from_conn_string(args.db) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        stream_input = initial_state
        should_stop = False

        last_printed_turn = 0

        while not should_stop:
            interrupted = False
            for step_output in graph.stream(stream_input, config=config):
                for node_name, updates in step_output.items():
                    if node_name == "__interrupt__":
                        decision = collect_review_decision(updates, args.auto_approve)
                        stream_input = Command(resume=decision)
                        interrupted = True
                        break
                    else:
                        print(f"\n{'─'*70}\n  NODE: {node_name.upper()}\n{'─'*70}")

                        if isinstance(updates, dict):
                            conv = updates.get("conversation")
                            if conv and isinstance(conv, list):
                                # Conversation is intentionally flushed on agenda advance.
                                # Reset the print cursor when buffer shrinks to avoid
                                # skipping the first turns of a new agenda item.
                                if len(conv) < last_printed_turn:
                                    last_printed_turn = 0
                                new_turns = conv[last_printed_turn:]
                                for turn in new_turns:
                                    role = turn.get("role", "system")
                                    content = turn.get("content", "")
                                    print(f"\n  [{role.upper()}] {content}\n")
                                last_printed_turn = len(conv)

                            next_node = updates.get("next_node")
                            if next_node:
                                dest = "END" if next_node == "__end__" else next_node
                                print(f"\n  Routing to: {dest}")

                            new_arts = updates.get("artifacts") or {}
                            for name, content in new_arts.items():
                                if name in printed_artifacts:
                                    # Already displayed — skip to avoid duplicates.
                                    continue
                                printed_artifacts.add(name)
                                display_fn = _DISPLAY.get(name)
                                if display_fn:
                                    display_fn(content)
                                else:
                                    print(f"\n  Artifact produced: {name}")

                            errors = updates.get("errors")
                            if errors:
                                print(f"\n  Errors:")
                                for e in errors:
                                    print(f"    • {e}")

                            phase = updates.get("system_phase")
                            if phase:
                                print(f"\n  Phase: {phase}")

                            final_artifacts.update(new_arts)

                            # Check if end-at artifact just appeared
                            if end_artifact and end_artifact in final_artifacts:
                                print(f"\nTarget end artifact '{end_artifact}' produced. Stopping.")
                                should_stop = True
                                break  # break inner for-loop

                if interrupted or should_stop:
                    break  # break outer step_output loop

            # If the stream exhausted naturally (graph reached END) and we
            # were neither interrupted nor told to stop at a specific artifact,
            # break out of the while loop — otherwise we would re-enter
            # graph.stream() with the same input and replay/no-op forever,
            # spamming the checkpointer and the tracer on every cycle.
            if not interrupted:
                break

    return final_artifacts

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    if args.reset_db and os.path.exists(args.db):
        os.remove(args.db)

    if args.start_at:
        artifact_dir = resolve_artifact_dir(args.artifact_dir)
        preloaded = build_artifacts(args.start_at, args.session, artifact_dir)
        initial_state = build_initial_state(args, preloaded)
        section(f"DEBUG START - target artifact: {args.start_at}")
    else:
        initial_state = build_initial_state(args)
        section("iReDev - Full Sprint Zero + Refinement flow")
        print(f"  Input guidance: {initial_state.get('input_guidance', '')}")
        contract = initial_state.get("visionary_contract")
        if contract:
            section("Visionary support contract")
            print(contract)

    if args.end_at:
        print(f"  Will stop after: {args.end_at}")

    print(f"  Session      : {args.session}")
    print(f"  DB           : {args.db}")
    print(f"  Vision mode  : {args.mode}")
    print(f"  Auto-approve : {args.auto_approve}")

    config = {
        "configurable": {
            "thread_id": f"run_{uuid.uuid4().hex}",
            "recursion_limit": 100,
        }
    }

    final_artifacts = run_workflow(initial_state, config, args)

    section("Workflow complete")
    produced = [k for k in final_artifacts if k != "session_id"]
    print(f"  Final artifacts: {', '.join(produced) if produced else '(none)'}")

    errors = final_artifacts.get("errors") or []
    if errors:
        print(f"\n  Accumulated errors ({len(errors)}):")
        for e in errors:
            print(f"    • {e}")

if __name__ == "__main__":
    main()
