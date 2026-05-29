"""
sprint.py — SprintAgent (Product Owner)

Two backlog-lane steps, each a single LLM pass. No refinement loop:

  Step 9a — create_user_stories (shaping):
      Input:  requirement_list_approved + compact reviewed Product Vision.
      One pass composes the backlog story set from the approved
      requirements. The PO is free to reshape: one requirement → one
      story, fold near-duplicate requirements into one story (carrying
      every source id), split a bundled requirement into several stories,
      rewrite for clarity, add a story the set implies, or drop a
      requirement that should not become its own story. Every change is
      reported so the human signs off at the backlog gate.
      Output: user_story_draft.

  Step 9b — build_product_backlog (prioritise + assemble):
      Input:  analyst_estimation (the authoritative post-reshape, sized,
              INVEST-assessed story set) + compact Product Vision.
      One pass reasons a WSJF score (business value, time criticality,
      risk reduction) per story. Python computes WSJF = (BV+TC+RR)/points,
      ranks, applies dependency-aware reorder, assigns PBI ids, and
      assembles the product_backlog.

Numbers and judgments come from the agent's reasoning; Python only moves
data, computes the transparent WSJF division + sort, and assigns ids.
Prompts state the task and the guarantees the output must meet — never a
procedure. Schema descriptions say WHAT a field holds. Each pass emits a
`reasoning` field first so the model thinks before it decides. No domain,
role name, or product category is hardcoded.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

from .base import BaseAgent

logger = logging.getLogger(__name__)

_FIBONACCI = (1, 2, 3, 5, 8, 13, 21)
T = TypeVar("T")


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "429" in text or "rate_limit" in text or "rate limit" in text


# ─────────────────────────────────────────────────────────────────────────────
# Prompt blocks — task + guarantees, never procedure.
# ─────────────────────────────────────────────────────────────────────────────

_FOUNDATIONS = """\
FOUNDATIONS

You turn an approved requirement list into the backlog a team will build
from. A user story names one obligation in the team's language — who it
serves, the capability, and the benefit — in the form
'As a <role>, I can <capability>, so that <benefit>.'

The requirement list was approved as an inventory of obligations, not as
a backlog: it can hold near-duplicates that one story would satisfy, a
single entry that bundles two deliverables, or wording too raw to build
from. Shaping it into clean stories is your work, and the backlog is
judged on INVEST — each story independent, negotiable, valuable,
estimable, small, and testable.

A story card is a promise you understand the obligation well enough to
write a test for it, so name a capability concrete enough to admit one — a
state, an action with a result, or an output someone could confirm in the
product — not just an assurance that something works. The detailed checks
and dependencies are pinned down later; the card only has to be clear
enough to make them writable.

A long backlog earns its length from the range of distinct obligations
in it, never from the same obligation restated. Quantity comes from
coverage, not repetition.

DOMAIN NEUTRALITY. Use the vocabulary of the requirements in front of
you. Do not import role names, product categories, or domain examples
from outside this run.
"""

_PASS_SHAPE = """\
THIS PASS — SHAPE THE APPROVED REQUIREMENTS INTO A CLEAN BACKLOG

Compose the story set a team could pick up. The approved list is mostly
already at story grain, so carrying one requirement through as one story
is the default and the common case. The other moves are exceptions you
reach for only when the evidence demands them:

  - MERGE only when two requirements are the SAME single obligation said
    twice — one capability the team ships and accepts with one acceptance
    check. Requirements in the same workflow or feature area that name
    different capabilities (create vs track vs reorder vs record) are
    different stories; folding them buries distinct work. When in doubt,
    keep them separate. List every source id a merge covers.
  - SPLIT a requirement that bundles more than one capability into
    separate stories. This raises the count, which is healthy.
  - REWRITE raw wording into a clear story sentence (still one obligation).
  - ADD a story the approved set clearly implies but never stated.
  - DROP a requirement that should not become a story (e.g. a genuine
    duplicate, or out of first-release scope), with a reason.

The story count should land close to the number of approved
requirements — a little lower where you fold true duplicates, a little
higher where you split bundles. A large drop is a signal you have
over-merged distinct obligations; re-examine before emitting.

These moves alter an approved set, so none may be silent: a fold lists
its source ids, an add names what implied it, a drop carries its reason.
The human reviews every change at the backlog gate.

You guarantee: every story reads as one sprint-small, INVEST-clean
obligation phrased as a concrete capability you could write a test for;
the set covers every approved obligation that should ship, with reductions
coming only from folding genuine duplicates, never from bundling distinct
capabilities together.
"""

_PASS_WSJF = """\
THIS PASS — PRIORITISE THE BACKLOG BY VALUE AND URGENCY

Score every story so the team can sequence the work. For each, reason
out three things on a 1–10 scale: its business value (how strongly its
outcome serves the stakeholders), its time criticality (how much the
value decays if it is delayed), and its risk or opportunity reduction
(how much uncertainty shipping it removes). These feed a WSJF ranking
against the size already set, so weigh stories against each other, not in
isolation. A story whose trace was inferred upstream deserves slightly
more caution in value and a note saying why.

You guarantee: every story is scored on all three dimensions with a
one-line rationale, and the scores reflect genuine relative value across
the set rather than a flat or default spread.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Feedback re-run blocks (only attached when reviewer feedback is present)
# ─────────────────────────────────────────────────────────────────────────────

_FEEDBACK_PREAMBLE = """\
FEEDBACK RE-RUN — REVIEWER REJECTED THE PREVIOUS OUTPUT.

Treat each feedback point below as a non-negotiable instruction
that overrides your default reasoning when the two conflict — if
a point tells you to keep / drop / rewrite / split / merge / re-
tag a specific element, comply exactly even when your own
judgment would have chosen differently. The "MUST address every
point" contract is absolute: a point left untouched is a failed
run, not a judgment call.

For any aspect the feedback is silent on, produce output the same
way you normally would — feedback narrows your choices on the
points it names; it does not loosen any INVEST guarantee, source-
id discipline, or WSJF honesty the pass already owes.
"""


_FEEDBACK_BODY_SHAPE = """\
REVIEWER FEEDBACK — YOU MUST ADDRESS EVERY POINT BELOW:
{feedback}

Apply each point at the shape slot it names:
  reshape_op (carry / merge / split / rewrite / add) · title ·
  description · source_requirement_ids · dropped reasons · notes.

When a point asks to merge two stories: union their source_
requirement_ids and report the fold. When a point asks to split a
bundle: emit the children with disjoint source_requirement_ids.
When a point asks to drop a story: record the drop with the
reviewer's stated reason; do not silently re-route the requirement
into another story to keep the count up.
"""


_FEEDBACK_BODY_WSJF = """\
REVIEWER FEEDBACK — YOU MUST ADDRESS EVERY POINT BELOW:
{feedback}

Apply each point at the prioritisation slot it names:
  business_value · time_criticality · risk_reduction · per-story
  rationale.

The dependency-aware reorder and the WSJF formula are Python's
job — do not anticipate the final rank in your scoring. If
feedback asks for a particular story to rise: justify the rise
through honest BV / TC / RR reasoning; do not inflate one
dimension purely to game the rank.
"""


_FEEDBACK_BODY_BY_CONTEXT: Dict[str, str] = {
    "story shaping": _FEEDBACK_BODY_SHAPE,
    "WSJF scoring":  _FEEDBACK_BODY_WSJF,
}


# ─────────────────────────────────────────────────────────────────────────────
# Schemas — WHAT each field holds. `reasoning` is declared first.
# ─────────────────────────────────────────────────────────────────────────────

class _StoryShape(BaseModel):
    source_requirement_ids: List[str] = Field(default_factory=list, description=(
        "Approved requirement ids this story covers: one for a straight carry, "
        "several when folding duplicates, the same parent repeated across the "
        "split children that divide it, empty for a newly added story."
    ))
    reshape_op: Literal["carry", "merge", "split", "rewrite", "add"] = Field(description=(
        "How this story relates to the approved set: carry (1:1), merge (folds "
        "several), split (one of several children of one requirement), rewrite "
        "(reworded 1:1), add (implied, no single source)."
    ))
    title: str = Field(description="Short backlog-card title — a noun phrase naming the obligation.")
    description: str = Field(description=(
        "The story sentence: 'As a <role>, I can <capability>, so that <benefit>.' "
        "<capability> is a concrete product behaviour you could write a test for "
        "(something you can see, do, or inspect), not just an assurance it works."
    ))
    thought: str = Field(description="One line: why this shaping is right; name any inference made.")


class _Dropped(BaseModel):
    requirement_ids: List[str] = Field(description="Approved requirement ids not turned into a story.")
    reason: str = Field(description="Why these should not become backlog stories.")


class _StoryShapeList(BaseModel):
    reasoning: str = Field(description=(
        "Your thinking before you list the stories — write this first, as a "
        "working scratchpad. Read the approved set whole: which requirements "
        "are near-duplicates one story should cover, which bundle more than one "
        "deliverable and must split, which are too raw and need rewriting, what "
        "the set implies that no entry states, and what should not ship as a "
        "story. Reasoning this through first is what makes the shaping below "
        "clean rather than a flat 1:1 transcription."
    ))
    stories: List[_StoryShape] = Field(description="The shaped backlog story set.")
    dropped: List[_Dropped] = Field(default_factory=list, description="Requirements deliberately not storied.")
    notes: str = Field(description="Reviewer-facing summary of the shaping decisions.")


class _WsjfEmit(BaseModel):
    source_story_id: str = Field(description="The story being scored.")
    business_value: int = Field(ge=1, le=10, description="Stakeholder outcome strength, 1–10.")
    time_criticality: int = Field(ge=1, le=10, description="Consequence of delay, 1–10.")
    risk_reduction: int = Field(ge=1, le=10, description="Uncertainty bought down, 1–10.")
    thought: str = Field(description="One-sentence scoring rationale.")


class _WsjfList(BaseModel):
    reasoning: str = Field(description=(
        "Your thinking before you score — write this first. Weigh the stories "
        "against each other: which carry the most stakeholder value, which lose "
        "value fastest if delayed, which remove the most risk, and how "
        "dependencies shape what must come early."
    ))
    scores: List[_WsjfEmit] = Field(description="One score entry per story.")
    notes: str = Field(description="Reviewer-facing scoring summary.")


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class SprintAgent(BaseAgent):
    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="sprint_agent")
        custom = (
            self._raw_config.get("iredev", {})
            .get("agents", {})
            .get("sprint_agent", {})
            .get("custom_params", {})
        )
        try:
            self._rate_limit_retries = max(0, int(custom.get("rate_limit_retries", 3) or 3))
        except (TypeError, ValueError):
            self._rate_limit_retries = 3
        try:
            self._rate_limit_base_delay = max(0.0, float(custom.get("rate_limit_base_delay", 5.0) or 5.0))
        except (TypeError, ValueError):
            self._rate_limit_base_delay = 5.0

    def _register_tools(self) -> None:
        """SprintAgent uses structured extraction only."""

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    # ── LangGraph entrypoints ────────────────────────────────────────────────

    def process_stories(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        feedback = self._shape_feedback(state)
        if "user_story_draft" in artifacts and not feedback:
            logger.warning("[SprintAgent] user_story_draft already exists.")
            return {}
        return self._create_user_stories(state)

    @staticmethod
    def _shape_feedback(state: Dict[str, Any]) -> str:
        """Feedback that drives a 9a re-run.

        9a' (user_story_draft HITL) is the immediate gate, so its feedback
        wins. The step-10 backlog rejection cascade also re-runs 9a; in that
        path the gate cleared the 9a' channel and only product_backlog_feedback
        is present — fall back to it.
        """
        return (
            (state.get("user_story_draft_feedback") or "").strip()
            or (state.get("product_backlog_feedback") or "").strip()
        )

    def process_backlog(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        feedback = (state.get("product_backlog_feedback") or "").strip()
        if "product_backlog" in artifacts and not feedback:
            logger.warning("[SprintAgent] product_backlog already exists.")
            return {}
        return self._build_product_backlog(state)

    # ── Step 9a — shaping ─────────────────────────────────────────────────────

    def _create_user_stories(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = dict(state.get("artifacts") or {})
        feedback = self._shape_feedback(state)
        req_list = artifacts.get("requirement_list_approved") or artifacts.get("requirement_list") or {}

        all_requirements = self._extract_all_requirements(req_list)
        traces = [
            self._normalise_requirement_trace(r)
            for r in all_requirements
            if r.get("status", "confirmed") != "excluded"
            and self._normalise_requirement_type(r.get("type") or r.get("req_type") or "") != "out_of_scope"
        ]
        if not traces:
            return {"errors": ["SprintAgent: no active approved requirements found."]}

        trace_by_id = {t["requirement_id"]: t for t in traces}
        product_vision = self._compact_product_vision(state)

        try:
            emitted = self._pass_shape(traces, product_vision, feedback)
        except Exception as exc:
            logger.error("[SprintAgent] Shaping pass failed: %s", exc, exc_info=True)
            return {"errors": [f"SprintAgent shaping error: {exc}"]}

        if (emitted.reasoning or "").strip():
            logger.info("[SprintAgent] Shaping reasoning:\n%s", emitted.reasoning.strip())

        results: List[Dict[str, Any]] = []
        reshape_report: List[str] = []
        seq = 1
        for shape in emitted.stories:
            desc = (shape.description or "").strip()
            if not desc:
                continue
            src_ids = [rid for rid in shape.source_requirement_ids if rid in trace_by_id]
            primary = trace_by_id.get(src_ids[0]) if src_ids else {}
            story_id = f"ST-{seq:03d}"
            seq += 1
            if shape.reshape_op != "carry":
                reshape_report.append(
                    f"{shape.reshape_op.upper()} {story_id} ← "
                    f"{', '.join(src_ids) or '(none)'}: {shape.thought.strip()}"
                )
            results.append({
                "source_story_id": story_id,
                "source_requirement_ids": src_ids,
                "source_requirement_id": src_ids[0] if src_ids else story_id,
                "reshape_op": shape.reshape_op,
                "type": (primary or {}).get("requirement_type", "functional"),
                "domain": self._domain_from_trace(primary or {}),
                "title": shape.title.strip(),
                "description": desc,
                "requirement_trace": self._merge_traces(src_ids, trace_by_id),
                "thought": shape.thought.strip(),
            })

        if not results:
            return {"errors": ["SprintAgent: shaping returned no usable stories."]}

        dropped = [{"requirement_ids": d.requirement_ids, "reason": d.reason} for d in emitted.dropped]
        for d in dropped:
            reshape_report.append(f"DROP {', '.join(d['requirement_ids'])}: {d['reason']}")

        report_block = ("\n\nRESHAPES (human reviews at the backlog gate)\n  " + "\n  ".join(reshape_report)) if reshape_report else ""
        artifacts["user_story_draft"] = {
            "id": str(uuid.uuid4()),
            "session_id": state.get("session_id", ""),
            "source_artifacts": ["requirement_list_approved", "reviewed_product_vision"],
            "created_at": datetime.now().isoformat(),
            "stories": results,
            "total_stories": len(results),
            "dropped": dropped,
            "notes": f"STORY SHAPING\n  {(emitted.notes or '').strip() or '(none)'}{report_block}",
            **({"rebuild_feedback": feedback} if feedback else {}),
        }
        logger.info(
            "[SprintAgent] Shaped %d approved requirement(s) → %d story(ies); %d reshape(s), %d dropped.",
            len(traces), len(results), len(reshape_report) - len(dropped), len(dropped),
        )
        return {"artifacts": artifacts}

    def _pass_shape(
        self, traces: List[Dict[str, Any]], product_vision: Dict[str, Any], feedback: str = "",
    ) -> _StoryShapeList:
        return self._with_rate_limit_retry(
            label="story shaping",
            fn=lambda: self.extract_structured(
                schema=_StoryShapeList,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _PASS_SHAPE
                    + self._feedback_block(feedback, "story shaping")
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(product_vision)}\n\n"
                    f"APPROVED REQUIREMENTS ({len(traces)} items):\n"
                    f"{self._format_traces(traces)}\n\n"
                    "Shape these into a clean backlog. Reference approved "
                    "requirement ids in source_requirement_ids; report every "
                    "merge, split, rewrite, add, and drop."
                ),
                include_memory=False,
            ),
        )

    # ── Step 9b — prioritise + assemble ────────────────────────────────────────

    def _build_product_backlog(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        feedback = (state.get("product_backlog_feedback") or "").strip()
        estimation = artifacts.get("analyst_estimation") or {}
        # The analyst's post-reshape set is authoritative for stories at 9b.
        est_stories = estimation.get("stories") or []
        if not est_stories:
            return {"errors": ["SprintAgent: analyst_estimation is empty."]}

        product_vision = self._compact_product_vision(state)
        try:
            wsjf = self._pass_wsjf(est_stories, product_vision, feedback)
        except Exception as exc:
            logger.error("[SprintAgent] WSJF pass failed: %s", exc, exc_info=True)
            return {"errors": [f"SprintAgent WSJF error: {exc}"]}

        if (wsjf.reasoning or "").strip():
            logger.info("[SprintAgent] WSJF reasoning:\n%s", wsjf.reasoning.strip())

        return self._assemble_backlog(wsjf=wsjf, est_stories=est_stories, state=state, feedback=feedback)

    def _pass_wsjf(
        self, est_stories: List[Dict[str, Any]], product_vision: Dict[str, Any], feedback: str = "",
    ) -> _WsjfList:
        return self._with_rate_limit_retry(
            label="WSJF scoring",
            fn=lambda: self.extract_structured(
                schema=_WsjfList,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _PASS_WSJF
                    + self._feedback_block(feedback, "WSJF scoring")
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(product_vision)}\n\n"
                    f"STORIES WITH SIZE + ASSESSMENT ({len(est_stories)} items):\n"
                    f"{self._format_estimated_stories(est_stories)}\n\n"
                    "Score every story on business_value, time_criticality, and "
                    "risk_reduction (1–10) with a one-line rationale."
                ),
                include_memory=False,
            ),
        )

    def _assemble_backlog(
        self,
        wsjf: _WsjfList,
        est_stories: List[Dict[str, Any]],
        state: Dict[str, Any],
        feedback: str = "",
    ) -> Dict[str, Any]:
        est_lookup = {self._story_id(s): s for s in est_stories}
        wsjf_lookup = {e.source_story_id: e for e in wsjf.scores}
        story_order = {self._story_id(s): i for i, s in enumerate(est_stories)}

        # A story the analyst split no longer exists under its old id; its
        # children carry parent_story_id. Map parent id → child ids so a
        # dependency elsewhere that points at the split parent resolves to
        # its children instead of dangling.
        present_sids = set(est_lookup.keys())
        parent_to_children: Dict[str, List[str]] = {}
        for s in est_stories:
            parent = s.get("parent_story_id")
            if parent:
                parent_to_children.setdefault(parent, []).append(self._story_id(s))

        def _resolve_dep(ref: str) -> List[str]:
            """Story id → the story id(s) actually present (expand a split
            parent to its children; drop a dangling ref to a dropped story)."""
            if ref in present_sids:
                return [ref]
            return parent_to_children.get(ref, [])

        # Story points: snap any off-grid value as a format guard only.
        fib_warnings: List[str] = []
        sp_by_story: Dict[str, int] = {}
        for est in est_stories:
            sid = self._story_id(est)
            sp = est.get("story_points", 3)
            if sp not in _FIBONACCI:
                snapped = min(_FIBONACCI, key=lambda f: abs(f - sp))
                fib_warnings.append(f"{sid}: story_points {sp} → {snapped}.")
                sp = snapped
            sp_by_story[sid] = sp

        # Rank by WSJF (descending), preserving input order as tiebreak.
        scored_ids = [sid for sid in story_order if sid in wsjf_lookup]
        scored_ids.sort(key=lambda sid: (-self._wsjf_value(wsjf_lookup[sid], sp_by_story.get(sid, 1)), story_order[sid]))
        rank = {sid: float(i + 1) for i, sid in enumerate(scored_ids)}

        # Dependency-aware reorder: a blocker must rank ahead of what it blocks.
        for est in est_stories:
            sid = self._story_id(est)
            for raw_blocker in (est.get("dependencies") or {}).get("blocked_by") or []:
                for blocker in _resolve_dep(raw_blocker):
                    if sid in rank and blocker in rank and rank[sid] < rank[blocker]:
                        rank[blocker] = rank[sid] - 0.5
        ordered_ids = sorted(rank.keys(), key=lambda k: rank[k])
        final_rank = {sid: i + 1 for i, sid in enumerate(ordered_ids)}

        items: List[Dict[str, Any]] = []
        invest_warnings: List[str] = []
        seq = 1
        ac_seq = 1  # global AC numbering, mirrors AnalystAgent Phase 2 (AC-NNN)
        for sid in ordered_ids:
            est = est_lookup.get(sid)
            score = wsjf_lookup.get(sid)
            if not est or not score:
                continue
            sp = sp_by_story.get(sid, 3)
            bv, tc, rr = score.business_value, score.time_criticality, score.risk_reduction
            wsjf_score = round((bv + tc + rr) / (sp or 1), 2)

            invest = est.get("invest") or {}
            invest_flags = invest.get("invest_flags") or []
            invest_pass = bool(invest.get("invest_pass", not invest_flags))
            if invest_flags:
                invest_warnings.append(f"{sid}: invest_flags={invest_flags}.")
            status = est.get("status", "ready" if invest_pass else "needs_refinement")

            pbi_id = f"PBI-{seq:03d}"
            seq += 1
            trace = est.get("requirement_trace") or {}
            # Carry the acceptance criteria the Analyst already wrote in step 9c
            # onto the PBI (same AC-NNN shape Phase 2 uses), so the backlog the PO
            # reviews at step 10 — and any external INVEST judge — sees a complete,
            # testable, estimable story instead of an AC-less one. Phase 2
            # re-attaches/renumbers them idempotently for validated_product_backlog.
            ac_list: List[Dict[str, Any]] = []
            for ac in (est.get("acceptance_criteria") or []):
                ac_list.append({
                    "id": f"AC-{ac_seq:03d}",
                    "given": ac.get("given", ""),
                    "when": ac.get("when", ""),
                    "then": ac.get("then", ""),
                    "type": ac.get("type", "happy_path"),
                })
                ac_seq += 1
            items.append({
                "id": pbi_id,
                "source_story_id": sid,
                "source_requirement_ids": est.get("source_requirement_ids")
                or ([est.get("source_requirement_id")] if est.get("source_requirement_id") else []),
                "type": est.get("type", "functional"),
                "domain": est.get("domain", ""),
                "title": est.get("title", ""),
                "description": (est.get("description") or "").strip(),
                "requirement_trace": trace,
                "estimation": {"story_points": sp},
                "prioritization": {
                    "priority_rank": final_rank.get(sid, len(items) + 1),
                    "wsjf_score": wsjf_score,
                    "business_value": bv, "time_criticality": tc, "risk_reduction": rr,
                },
                "_raw_blocked_by": (est.get("dependencies") or {}).get("blocked_by") or [],
                "_raw_blocks": (est.get("dependencies") or {}).get("blocks") or [],
                "planning": {"status": status, "target_sprint": None, "tags": self._tags_for_story(est)},
                "quality": {
                    "invest_pass": invest_pass,
                    "invest_flags": invest_flags,
                    "acceptance_criteria": ac_list,
                },
                "analysis": {
                    "is_feasible": (est.get("feasibility") or {}).get("is_feasible", True),
                    "feasibility_notes": (est.get("feasibility") or {}).get("feasibility_notes", ""),
                    "invest_notes": invest.get("invest_notes", ""),
                    "risks": est.get("risks") or [],
                    "estimation_reasoning": est.get("estimation_reasoning", ""),
                    "reshape_op": est.get("reshape_op", "none"),
                    "wsjf_thought": score.thought,
                },
            })

        # Translate story-id dependencies to PBI-ids, expanding any split
        # parent to its children and dropping refs to dropped stories.
        story_to_pbi = {item["source_story_id"]: item["id"] for item in items}

        def _to_pbis(refs: List[str], self_id: str) -> List[str]:
            out: List[str] = []
            for raw in refs:
                for sid in _resolve_dep(raw):
                    pbi = story_to_pbi.get(sid)
                    if pbi and pbi != self_id and pbi not in out:
                        out.append(pbi)
            return out

        for item in items:
            item["dependencies"] = {
                "blocked_by": _to_pbis(item.pop("_raw_blocked_by", []), item["id"]),
                "blocks": _to_pbis(item.pop("_raw_blocks", []), item["id"]),
            }

        for item in items:
            pri = item.get("prioritization") or {}
            qual = item.get("quality") or {}
            flags = qual.get("invest_flags") or []
            logger.info(
                "[SprintAgent]   #%s [%s] sp=%s WSJF=%.2f invest=%s  %s",
                pri.get("priority_rank", "?"), item.get("id", "?"),
                item["estimation"]["story_points"], pri.get("wsjf_score", 0),
                "PASS" if not flags else f"FAIL[{','.join(flags)}]",
                (item.get("title") or "")[:60],
            )

        total_points = sum(i["estimation"]["story_points"] for i in items)
        total_ac = sum(len((i.get("quality") or {}).get("acceptance_criteria") or []) for i in items)
        ready_count = sum(1 for i in items if i["planning"]["status"] == "ready")
        human_count = sum(1 for i in items if i["planning"]["status"] == "needs_human_input")
        artifacts = dict(state.get("artifacts") or {})
        artifacts["product_backlog"] = {
            "id": str(uuid.uuid4()),
            "session_id": state.get("session_id", ""),
            "source_artifacts": [
                "requirement_list_approved", "reviewed_product_vision",
                "user_story_draft_approved", "analyst_estimation",
            ],
            "status": "draft",
            "total_items": len(items),
            "total_story_points": total_points,
            "total_ac": total_ac,
            "ready_count": ready_count,
            "needs_human_input_count": human_count,
            "items": items,
            "methodology": {
                "story_format": "As a <role>, I can <capability>, so that <benefit>.",
                "estimation": "Fibonacci story points reasoned by AnalystAgent.",
                "prioritization": "WSJF = (BV+TC+RR)/points with dependency-aware ordering.",
                "quality_gate": "INVEST assessed by AnalystAgent.",
            },
            "notes": (
                (state.get("artifacts") or {})
                .get("user_story_draft_approved", {})
                .get("notes", "")
                or (state.get("artifacts") or {})
                .get("user_story_draft", {})
                .get("notes", "")
            ),
            "pass_notes": f"WSJF SCORING\n  {(wsjf.notes or '').strip() or '(none)'}",
            "quality_warnings": {"invest": invest_warnings, "fibonacci": fib_warnings},
            "created_at": datetime.now().isoformat(),
            **({"rebuild_feedback": feedback} if feedback else {}),
        }
        return {"artifacts": artifacts}

    # ── Infra ────────────────────────────────────────────────────────────────

    def _with_rate_limit_retry(self, label: str, fn: Callable[[], T]) -> T:
        attempts = self._rate_limit_retries + 1
        last_exc: Optional[BaseException] = None
        for attempt in range(attempts):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if not _is_rate_limit_error(exc) or attempt + 1 >= attempts:
                    raise
                delay = self._rate_limit_base_delay * (3 ** attempt)
                logger.warning(
                    "[SprintAgent] %s rate-limited; retrying in %.1fs (attempt %d/%d).",
                    label, delay, attempt + 1, attempts,
                )
                time.sleep(delay)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"{label}: retry loop exited without result")

    # ── Helpers (data movement only) ───────────────────────────────────────────

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _wsjf_value(score: _WsjfEmit, sp: int) -> float:
        return (score.business_value + score.time_criticality + score.risk_reduction) / (sp if sp > 0 else 1)

    @staticmethod
    def _story_id(item: Dict[str, Any]) -> str:
        return item.get("source_story_id") or item.get("id") or ""

    @staticmethod
    def _extract_all_requirements(req_list: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not req_list:
            return []
        for key in ("items", "requirements", "requirement_items", "all_requirements"):
            if isinstance(req_list.get(key), list):
                return list(req_list[key])
        merged: List[Dict[str, Any]] = []
        for key in ("functional_requirements", "non_functional_requirements"):
            if isinstance(req_list.get(key), list):
                merged.extend(req_list[key])
        return merged

    @staticmethod
    def _normalise_requirement_type(value: Any) -> str:
        text = str(value or "").lower().replace("-", "_")
        if text in {"nonfunctional", "non_functional"}:
            return "non_functional"
        if text == "system":
            return "system"
        if text in {"outofscope", "out_of_scope"}:
            return "out_of_scope"
        return "functional"

    @classmethod
    def _normalise_requirement_trace(cls, requirement: Dict[str, Any]) -> Dict[str, Any]:
        req_type = cls._normalise_requirement_type(
            requirement.get("type") or requirement.get("req_type") or "functional"
        )
        if req_type == "out_of_scope":
            req_type = "functional"
        confidence = requirement.get("confidence")
        if confidence not in {"confirmed", "inferred"}:
            confidence = "confirmed"
        return {
            "requirement_id": requirement.get("id") or requirement.get("req_id") or "",
            "requirement_type": req_type,
            "stakeholder": requirement.get("stakeholder") or requirement.get("role") or "",
            "statement": requirement.get("statement") or requirement.get("description") or "",
            "rationale": requirement.get("rationale") or "",
            "acceptance_criteria": requirement.get("acceptance_criteria") or [],
            "trace_refs": list(requirement.get("trace_refs") or []),
            "confidence": confidence,
            "trigger_event": requirement.get("trigger_event") or "",
            "product_object": requirement.get("product_object") or "",
            "observable_outcome": requirement.get("observable_outcome") or "",
            "operating_condition": requirement.get("operating_condition") or "",
            "participation_structure": requirement.get("participation_structure") or "",
        }

    @classmethod
    def _merge_traces(cls, src_ids: List[str], trace_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Primary trace = the first source (richest single set of six axes for
        the analyst + AC pass); union trace_refs and record co-sources so a
        merged story keeps full audit trail."""
        if not src_ids:
            return {}
        primary = dict(trace_by_id.get(src_ids[0]) or {})
        if len(src_ids) > 1:
            refs = list(primary.get("trace_refs") or [])
            seen = set(refs)
            for rid in src_ids[1:]:
                for ref in (trace_by_id.get(rid) or {}).get("trace_refs") or []:
                    if ref not in seen:
                        refs.append(ref); seen.add(ref)
            primary["trace_refs"] = refs
            primary["merged_requirement_ids"] = src_ids
        return primary

    @staticmethod
    def _compact_product_vision(state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        vision = (
            artifacts.get("reviewed_product_vision")
            or artifacts.get("product_vision")
            or state.get("product_vision") or {}
        )
        return {
            "intent_summary": vision.get("intent_summary", ""),
            "target_outcome": vision.get("target_outcome", ""),
            "roles": vision.get("roles") or vision.get("stakeholders") or [],
            "concerns": vision.get("concerns") or [],
            "scope": vision.get("scope") or vision.get("out_of_scope") or [],
        }

    @staticmethod
    def _domain_from_trace(trace: Dict[str, Any]) -> str:
        return (trace.get("stakeholder") or "").strip() or (trace.get("requirement_type") or "").strip() or "General"

    @classmethod
    def _format_traces(cls, traces: List[Dict[str, Any]]) -> str:
        return "\n".join(cls._json(t) for t in traces)

    @classmethod
    def _format_estimated_stories(cls, est_stories: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for s in est_stories:
            lines.append(cls._json({
                "source_story_id": cls._story_id(s),
                "type": s.get("type"), "title": s.get("title"),
                "description": s.get("description"),
                "story_points": s.get("story_points"),
                "invest_flags": (s.get("invest") or {}).get("invest_flags") or [],
                "blocked_by": (s.get("dependencies") or {}).get("blocked_by") or [],
                "confidence": (s.get("requirement_trace") or {}).get("confidence", "confirmed"),
            }))
        return "\n".join(lines)

    @staticmethod
    def _tags_for_story(story: Dict[str, Any]) -> List[str]:
        tags: List[str] = []
        domain = (story.get("domain") or "").strip()
        if domain:
            tags.append(domain.lower().replace(" ", "_"))
        story_type = story.get("type")
        if story_type in ("non_functional", "system"):
            tags.append(story_type)
        return tags

    @staticmethod
    def _feedback_block(feedback: str, context: str) -> str:
        if not feedback:
            return ""
        body_template = _FEEDBACK_BODY_BY_CONTEXT.get(context) or _FEEDBACK_BODY_SHAPE
        return (
            "\n\n" + _FEEDBACK_PREAMBLE
            + "\n\n" + body_template.format(feedback=feedback)
        )
