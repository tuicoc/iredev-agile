"""
sprint.py - SprintAgent (Product Owner)

Two backlog-lane steps:

  Step 9a — create_user_stories
      Input:  requirement_list_approved + compact reviewed Product Vision.
      LLM:   Pass 1 (single call) emits one {source_requirement_id, title,
             description, thought} entry per requirement.
      Python: attaches trace, ids, type, domain; assembles user_story_draft.

  Step 9b — build_product_backlog
      Input:  user_story_draft + analyst_estimation + compact Product Vision.
      LLM:   Pass 2 (single call) emits {business_value, time_criticality,
             risk_reduction, thought} per story.
      Python: WSJF = (BV+TC+RR)/sp, dependency-aware rerank, PBI ids,
             planning status, format/fibonacci warnings.

Step 9c (process_splits) is Python-only: applies AnalystAgent's split
proposals to the draft (≤2 rounds).

Schema descriptions teach WHAT each field is. Prompt blocks teach HOW to
reason. No domain, role name, or product category is hardcoded.
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

_FIBONACCI = {1, 2, 3, 5, 8, 13, 21}
_MAX_SPLIT_ROUND = 2

T = TypeVar("T")


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "429" in text or "rate_limit" in text or "rate limit" in text


# ─────────────────────────────────────────────────────────────────────────────
# Prompt blocks — taught vocabulary lives here, not in schema descriptions.
# Cross-domain placeholders only (<actor>, <object>, <surface>).
# ─────────────────────────────────────────────────────────────────────────────

_FOUNDATIONS = """\
FOUNDATIONS

A backlog story makes one product obligation pickable. The obligation
is already named in the requirement_trace; your job is to reshape it
as one card a team can claim and ship.

THE OBLIGATION CARRIES SIX AXES OF EVIDENCE

  stakeholder             - audience that LIVES the outcome.
  trigger_event           - event class that activates the obligation.
  operating_condition     - when the obligation is active.
  product_object          - product-owned object acted on.
  observable_outcome      - what the audience observes when it holds.
  participation_structure - who participates / decides / is affected.

These six are richer than the bare statement. Lean on them when
writing the story. Do NOT invent thresholds, technologies, vendors,
or rules absent from the trace.

CONFIDENCE

  confirmed - obligation directly grounded in stated evidence.
  inferred  - upstream synthesis from friction; direction is set,
              exact shape may not be stakeholder-confirmed.

Inference is honest work upstream — do not re-judge it. Reflect it
in your `thought` so a reviewer can spot-check the leap.

DOMAIN NEUTRALITY

Use the vocabulary of the trace in front of you. No imported domain
examples, fixed role names, or product categories.
"""


_REASONING_MOVES = """\
REASONING MOVES

ACTOR

The actor is the audience that LIVES the outcome.

  - functional / non_functional: use stakeholder.
  - system: when stakeholder is 'product-wide' or null, the product
    itself is the actor.

CAPABILITY

Anchor the capability in trigger_event + operating_condition so the
recognisable moment is visible. Do not abstract away the situation;
do not over-narrow either.

BENEFIT

Source order: rationale → observable_outcome → first acceptance
criterion. Pick the wording that names the audience benefit most
clearly.

MULTI-ACTOR CUE

When participation_structure is multi-actor / contested / delegated /
authority-mediated, surface the collaboration in the capability so a
reviewer sees both sides. Single-actor obligations stay single-actor.

INFERRED HANDLING

If trace.confidence is 'inferred', write the story as the evidence
supports, then in `thought` name the leap from friction to product
solution so a reviewer can validate before commit.

WSJF AT A GLANCE (consumed in Pass 2)

WSJF prioritises by Cost of Delay over Job Size:

  WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints

You emit only the three numerators (1-10 each) per story. Python
applies the formula and orders by it, honouring dependencies
(blocker before blocked).

WHAT YOU DO NOT DO

  - Invent capabilities, thresholds, technologies, vendors, or rules.
  - Estimate story points, assess INVEST, or propose splits — those
    belong to AnalystAgent.
  - Pull from the original project description; the requirement
    trace is your scope.
  - Compute the WSJF formula or assign ranks — Python does.
"""


_PASS_STORY = """\
PASS 1 — REQUIREMENT TRACES → USER STORIES

You see every approved requirement trace plus the compact Product
Vision. Emit one card per trace, in any order; Python re-sorts.

MENTAL MODEL (per trace)

1. Read the trace. Who LIVES the outcome? What event activates it?
   Under what condition? On what product-owned object? With what
   observable effect?

2. Compose the sentence:
     "As <actor>, I can <capability anchored in trigger + condition>,
      so that <benefit from rationale / outcome / AC>."

3. Title: a short noun phrase naming the obligation, not the
   audience. Reviewable at a glance.

4. Thought: one short sentence on how you mapped trace to story.
   If trace.confidence is 'inferred', name the inference here.

WHAT YOU EMIT (one entry per trace)

  source_requirement_id - the requirement id this story is for
  title                 - short backlog-card title
  description           - the user story sentence
  thought               - mapping note

Python attaches every other field (trace, story_id, type, domain).
Do NOT echo trace fields in your output.
"""


_PASS_WSJF = """\
PASS 2 — WSJF SCORING

You see every story plus its analyst estimation (points, INVEST
flags, dependencies, risks) and the compact Product Vision. Score
each story on three dimensions. Each score reflects EVIDENCE
strength, not a guess.

USE THE FULL 1-10 RANGE

If your draft has 5+ stories and they cluster within a 2-point
band on any dimension, you are not differentiating evidence. Re-
read the band, find one strongest member and one weakest, and
spread the band. Ties are allowed only between stories the team
would build interchangeably.

────────────────────────────────────────────────────────────────
BUSINESS VALUE (1-10)  — stakeholder outcome strength
────────────────────────────────────────────────────────────────

Anchor to: trace priority, rationale, observable_outcome, vision's
target_outcome, and audience reach (1 role vs many).

  9-10  Story directly delivers the vision.target_outcome OR
        addresses the audience's primary need named in vision.roles.
        Outcome is named with specifics in trace.rationale and
        trace.observable_outcome. Audience is broad (≥2 roles) or
        critical (a vision-stated primary role).

  7-8   Stakeholder benefit is clearly stated in trace.rationale
        with one named beneficiary role. observable_outcome is
        explicit. Audience is the primary role of one vision
        concern or assumption.

  5-6   Incremental benefit. Outcome is named but moderately
        scoped; audience is one role with secondary stake;
        priority='medium' in trace.

  3-4   Marginal improvement. Outcome implied rather than stated;
        audience narrow or peripheral; priority='low'.

  1-2   Weakly evidenced; rationale generic; observable_outcome
        vague or empty.

────────────────────────────────────────────────────────────────
TIME CRITICALITY (1-10)  — consequence of delay
────────────────────────────────────────────────────────────────

Anchor to: trace.operating_condition (narrow window = more
critical), dependency chains (a blocker is more time-critical),
vision.concerns that block adoption, and severity of the friction.

  9-10  Story is a blocker for ≥2 other stories OR addresses a
        vision concern explicitly blocking safe adoption OR has a
        narrow operating_condition (event-driven, time-bound).
        Delaying it strands the team.

  7-8   Blocker for ≥1 other story OR addresses an active vision
        concern (clarity / trust / accessibility) that the
        audience names as ongoing friction.

  5-6   Useful soon but not strictly blocking. operating_condition
        is "always-on" but the audience cited the friction in
        evidence.

  3-4   Nice-to-have timing. Friction is mild, audience can work
        around it.

  1-2   Timing doesn't matter; story would land equally well next
        sprint or next quarter.

────────────────────────────────────────────────────────────────
RISK REDUCTION (1-10)  — uncertainty bought down
────────────────────────────────────────────────────────────────

Anchor to: analyst risks list, threshold gaps, stories this one
unblocks, and confidence (inferred shape buys MORE clarity once
delivered than a fully-stated equivalent).

  9-10  Story unblocks ≥2 other stories OR addresses a high/critical
        risk in analyst.risks OR resolves a vision-stated open
        question. Direction is set; building it forces the open
        choices to surface.

  7-8   Unblocks 1 other story OR addresses a single named
        analyst risk OR confidence='inferred' on a vision-anchored
        obligation (delivery reveals real shape).

  5-6   Clarifies moderate uncertainty (one threshold gap or one
        cross-flow assumption).

  3-4   Small clarification; uncertainty mostly cosmetic.

  1-2   Story doesn't reduce uncertainty; the obligation is well-
        understood and the build is mechanical.

────────────────────────────────────────────────────────────────
CONFIDENCE-AWARE SCORING

For a story whose trace.confidence is 'inferred':
  - Lower BusinessValue by 1 vs a similarly-scoped confirmed sibling
    (the audience benefit is your synthesis, not stakeholder-stated).
  - Raise RiskReduction by 1-2 (delivery surfaces the real shape).
  - Name the inference in `thought`.

CONSISTENCY

Stories sharing the same vision_ref or trace_refs should score
consistently — higher-evidence siblings outrank lower-evidence
ones, and a blocker should not score lower than what it blocks
on TimeCriticality.

WHAT YOU EMIT (one entry per story)

  source_story_id   - the story you are scoring
  business_value    - 1-10
  time_criticality  - 1-10
  risk_reduction    - 1-10
  thought           - one sentence naming WHICH band you chose and
                      WHY (cite the trace field or vision element)

Python computes WSJF = (BV + TC + RR) / StoryPoints, sorts by it,
then honours `blocked_by` so a blocker outranks what it blocks. Do
NOT compute the formula or emit a rank.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Schemas — describe WHAT a field is. HOW to reason lives in prompts above.
# ─────────────────────────────────────────────────────────────────────────────

class _StoryEmit(BaseModel):
    """LLM output for Pass 1 — one entry per requirement trace."""
    source_requirement_id: str = Field(description=(
        "Id of the requirement this story is for; must match a trace in the input."
    ))
    title: str = Field(description=(
        "Short backlog-card title. A noun phrase naming the obligation, "
        "not the audience."
    ))
    description: str = Field(description=(
        "User-story sentence shaped 'As <actor>, I can <capability "
        "anchored in trigger+condition>, so that <benefit>.' Actor is "
        "the audience that LIVES the outcome; for system items where "
        "stakeholder is product-wide, the product itself is the actor."
    ))
    thought: str = Field(description=(
        "One short sentence on how trace was mapped to story. When "
        "trace.confidence is 'inferred', name the leap so the reviewer "
        "can spot-check."
    ))


class _StoryList(BaseModel):
    stories: List[_StoryEmit] = Field(description="One entry per requirement trace.")
    pass_notes: str = Field(description="Reviewer-facing Pass 1 summary.")


class _WsjfEmit(BaseModel):
    source_story_id: str = Field(description="The story being scored.")
    business_value: int = Field(ge=1, le=10, description=(
        "Stakeholder outcome strength on a 1-10 scale."
    ))
    time_criticality: int = Field(ge=1, le=10, description=(
        "Consequence of delay on a 1-10 scale."
    ))
    risk_reduction: int = Field(ge=1, le=10, description=(
        "Uncertainty bought down on a 1-10 scale."
    ))
    thought: str = Field(description="One sentence scoring rationale.")


class _WsjfList(BaseModel):
    scores: List[_WsjfEmit] = Field(description="One score entry per story.")
    pass_notes: str = Field(description="Reviewer-facing scoring summary.")


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
            self._rate_limit_base_delay = max(
                0.0, float(custom.get("rate_limit_base_delay", 5.0) or 5.0)
            )
        except (TypeError, ValueError):
            self._rate_limit_base_delay = 5.0

    def _register_tools(self) -> None:
        """SprintAgent uses structured extraction only."""

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    # ── LangGraph entrypoints ────────────────────────────────────────────────

    def process_stories(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        feedback = (state.get("product_backlog_feedback") or "").strip()
        if "user_story_draft" in artifacts and not feedback:
            logger.warning("[SprintAgent] user_story_draft already exists.")
            return {}
        return self._create_user_stories(state)

    def process_splits(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        estimation = artifacts.get("analyst_estimation") or {}
        split_round = state.get("split_round", 0)

        if split_round >= _MAX_SPLIT_ROUND:
            return {"split_round": split_round}

        draft = artifacts.get("user_story_draft") or {}
        draft_lookup = {self._story_id(s): s for s in (draft.get("stories") or [])}

        new_stories: List[Dict[str, Any]] = []
        replaced_ids: List[str] = []

        for story_est in estimation.get("stories") or []:
            if not story_est.get("needs_split"):
                continue

            parent_id = self._story_id(story_est)
            parent_story = draft_lookup.get(parent_id, {})
            split_props = story_est.get("split_proposals") or []
            if not parent_story or not split_props:
                continue

            replaced_ids.append(parent_id)
            trace = dict(parent_story.get("requirement_trace") or {})
            source_requirement_id = (
                parent_story.get("source_requirement_id")
                or trace.get("requirement_id")
                or parent_id
            )

            for idx, proposal in enumerate(split_props):
                suffix = chr(ord("a") + idx)
                child_id = f"{parent_id}{suffix}"
                reasoning = proposal.get("reasoning", "")
                child_story = {
                    "source_story_id": child_id,
                    "source_requirement_id": source_requirement_id,
                    "type": parent_story.get("type", "functional"),
                    "domain": parent_story.get("domain", ""),
                    "title": proposal.get("title") or f"{parent_story.get('title', '')} {suffix}",
                    "description": (
                        f"As a {self._extract_role(parent_story.get('description', ''))}, "
                        f"I can {proposal.get('capability', '')}, "
                        f"so that {self._extract_benefit(parent_story.get('description', ''))}."
                    ),
                    "requirement_trace": trace,
                    "is_split_child": True,
                    "split": {
                        "parent_story_id": parent_id,
                        "suffix": suffix,
                        "reasoning": reasoning,
                    },
                    "thought": f"Split child of {parent_id}: {reasoning}",
                }
                new_stories.append(child_story)

        if not new_stories:
            return {"split_round": _MAX_SPLIT_ROUND}

        existing_stories = [
            s for s in (draft.get("stories") or [])
            if self._story_id(s) not in set(replaced_ids)
        ]
        updated_draft = {
            **draft,
            "stories": existing_stories + new_stories,
            "total_stories": len(existing_stories) + len(new_stories),
            "split_round": split_round + 1,
        }

        updated_artifacts = {**artifacts, "user_story_draft": updated_draft}
        updated_artifacts.pop("analyst_estimation", None)

        logger.info(
            "[SprintAgent] Split round %d -> %d created %d child stories.",
            split_round, split_round + 1, len(new_stories),
        )
        return {"artifacts": updated_artifacts, "split_round": split_round + 1}

    def process_backlog(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        feedback = (state.get("product_backlog_feedback") or "").strip()
        if "product_backlog" in artifacts and not feedback:
            logger.warning("[SprintAgent] product_backlog already exists.")
            return {}
        return self._build_product_backlog(state)

    # ── Step 9a — story creation (parallel per requirement) ──────────────────

    def _create_user_stories(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = dict(state.get("artifacts") or {})
        feedback = (state.get("product_backlog_feedback") or "").strip()
        req_list = artifacts.get("requirement_list_approved") or artifacts.get("requirement_list") or {}

        all_requirements = self._extract_all_requirements(req_list)
        traces = [
            self._normalise_requirement_trace(r)
            for r in all_requirements
            if r.get("status", "confirmed") != "excluded"
            and self._normalise_requirement_type(
                r.get("type") or r.get("req_type") or ""
            ) != "out_of_scope"
        ]
        if not traces:
            return {"errors": ["SprintAgent: no active approved requirements found."]}

        product_vision = self._compact_product_vision(state)

        try:
            emitted = self._pass_stories(traces, product_vision, feedback)
        except Exception as exc:
            logger.error("[SprintAgent] Pass 1 failed: %s", exc, exc_info=True)
            return {"errors": [f"SprintAgent Pass 1 error: {exc}"]}

        trace_by_id = {t["requirement_id"]: t for t in traces}
        emitted_by_id = {s.source_requirement_id: s for s in emitted.stories}

        results: List[Dict[str, Any]] = []
        missing: List[str] = []

        # Iterate traces in input order so the draft preserves it.
        for trace in traces:
            req_id = trace["requirement_id"]
            emit = emitted_by_id.get(req_id)
            if emit is None:
                missing.append(req_id)
                continue
            results.append({
                "source_story_id": req_id,
                "source_requirement_id": req_id,
                "type": trace.get("requirement_type", "functional"),
                "domain": self._domain_from_trace(trace),
                "title": emit.title.strip(),
                "description": emit.description.strip(),
                "requirement_trace": trace,
                "is_split_child": False,
                "split": {"parent_story_id": None, "suffix": None, "reasoning": None},
                "thought": emit.thought.strip(),
            })

        if not results:
            return {"errors": [f"SprintAgent: Pass 1 returned no stories (missing={missing})."]}

        notes = emitted.pass_notes.strip() or "(no Pass 1 notes)"
        miss_block = (
            "\n\nMISSING STORIES (no emit for these requirement ids):\n  "
            + ", ".join(missing)
        ) if missing else ""

        artifacts["user_story_draft"] = {
            "id": str(uuid.uuid4()),
            "session_id": state.get("session_id", ""),
            "source_artifacts": ["requirement_list_approved", "reviewed_product_vision"],
            "created_at": datetime.now().isoformat(),
            "stories": results,
            "total_stories": len(results),
            "pass_notes": "PASS 1 — STORY CREATION\n  " + notes + miss_block,
            **({"rebuild_feedback": feedback} if feedback else {}),
        }
        return {"artifacts": artifacts, "split_round": 0}

    def _pass_stories(
        self,
        traces: List[Dict[str, Any]],
        product_vision: Dict[str, Any],
        feedback: str = "",
    ) -> _StoryList:
        return self._with_rate_limit_retry(
            label="story creation",
            fn=lambda: self.extract_structured(
                schema=_StoryList,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _REASONING_MOVES
                    + "\n\n" + _PASS_STORY
                    + self._feedback_block(feedback, "user story creation")
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(product_vision)}\n\n"
                    f"REQUIREMENT TRACES ({len(traces)} items):\n"
                    f"{self._format_traces(traces)}\n\n"
                    "Return one story entry per trace. Emit only "
                    "source_requirement_id, title, description, thought; "
                    "Python attaches the rest."
                ),
                include_memory=False,
            ),
        )

    # ── Step 9b — backlog assembly (single Pass 2 WSJF call) ─────────────────

    def _build_product_backlog(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        feedback = (state.get("product_backlog_feedback") or "").strip()
        split_round = state.get("split_round", 0)

        draft = artifacts.get("user_story_draft") or {}
        estimation = artifacts.get("analyst_estimation") or {}
        stories = draft.get("stories") or []
        est_stories = estimation.get("stories") or []
        if not stories:
            return {"errors": ["SprintAgent: user_story_draft is empty."]}
        if not est_stories:
            return {"errors": ["SprintAgent: analyst_estimation is empty."]}

        product_vision = self._compact_product_vision(state)

        try:
            wsjf = self._pass_wsjf(stories, est_stories, product_vision, feedback)
        except Exception as exc:
            logger.error("[SprintAgent] WSJF pass failed: %s", exc, exc_info=True)
            return {"errors": [f"SprintAgent WSJF error: {exc}"]}

        return self._assemble_backlog(
            wsjf=wsjf,
            stories=stories,
            est_stories=est_stories,
            state=state,
            feedback=feedback,
            split_round=split_round,
        )

    def _pass_wsjf(
        self,
        stories: List[Dict[str, Any]],
        est_stories: List[Dict[str, Any]],
        product_vision: Dict[str, Any],
        feedback: str = "",
    ) -> _WsjfList:
        est_lookup = {self._story_id(s): s for s in est_stories}
        return self._with_rate_limit_retry(
            label="WSJF scoring",
            fn=lambda: self.extract_structured(
                schema=_WsjfList,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _REASONING_MOVES
                    + "\n\n" + _PASS_WSJF
                    + self._feedback_block(feedback, "WSJF scoring")
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(product_vision)}\n\n"
                    f"STORIES WITH ANALYST ESTIMATION ({len(stories)} items):\n"
                    f"{self._format_stories_with_estimation(stories, est_lookup)}\n\n"
                    "Score every story. Emit only source_story_id and the three "
                    "dimension scores plus thought; Python computes WSJF and ranks."
                ),
                include_memory=False,
            ),
        )

    def _assemble_backlog(
        self,
        wsjf: _WsjfList,
        stories: List[Dict[str, Any]],
        est_stories: List[Dict[str, Any]],
        state: Dict[str, Any],
        feedback: str = "",
        split_round: int = 0,
    ) -> Dict[str, Any]:
        story_lookup = {self._story_id(s): s for s in stories}
        est_lookup = {self._story_id(s): s for s in est_stories}
        wsjf_lookup = {entry.source_story_id: entry for entry in wsjf.scores}

        # Snap any drift in analyst story_points to Fibonacci defensively.
        fib_warnings: List[str] = []
        sp_by_story: Dict[str, int] = {}
        for est in est_stories:
            story_id = self._story_id(est)
            est_data = est.get("estimation") or {}
            sp = est_data.get("story_points", 3)
            if sp not in _FIBONACCI:
                snapped = min(_FIBONACCI, key=lambda f: abs(f - sp))
                fib_warnings.append(f"{story_id}: story_points {sp} → {snapped}.")
                sp = snapped
            sp_by_story[story_id] = sp

        # Initial rank: order by WSJF descending; preserve story order as tiebreak.
        story_order = {self._story_id(s): i for i, s in enumerate(stories)}
        scored_ids = [sid for sid in story_order if sid in wsjf_lookup and sid in est_lookup]
        scored_ids.sort(
            key=lambda sid: (
                -self._wsjf_value(wsjf_lookup[sid], sp_by_story.get(sid, 1)),
                story_order[sid],
            )
        )
        initial_rank = {sid: i + 1 for i, sid in enumerate(scored_ids)}

        # Dependency-aware adjustment: a blocker must rank ≤ what it blocks.
        adjusted = {sid: float(rank) for sid, rank in initial_rank.items()}
        for est in est_stories:
            story_id = self._story_id(est)
            for blocker_id in (est.get("dependencies") or {}).get("blocked_by") or []:
                if story_id not in adjusted or blocker_id not in adjusted:
                    continue
                if adjusted[story_id] < adjusted[blocker_id]:
                    adjusted[blocker_id] = adjusted[story_id] - 0.5

        ordered_ids = sorted(adjusted.keys(), key=lambda k: adjusted[k])
        final_rank = {sid: i + 1 for i, sid in enumerate(ordered_ids)}

        items: List[Dict[str, Any]] = []
        format_warnings: List[str] = []
        invest_warnings: List[str] = []
        oversized: List[str] = []
        seq = 1
        parent_seq: Dict[str, int] = {}

        for story_id in ordered_ids:
            story = story_lookup.get(story_id)
            est = est_lookup.get(story_id)
            score = wsjf_lookup.get(story_id)
            if not story or not est or not score:
                continue

            split_meta = story.get("split") or {}
            is_split_child = bool(story.get("is_split_child"))
            parent_story_id = split_meta.get("parent_story_id") or story.get("source_parent_story_id")
            suffix = split_meta.get("suffix") or story.get("split_suffix") or ""
            if is_split_child:
                if parent_story_id not in parent_seq:
                    parent_seq[parent_story_id or story_id] = seq
                    seq += 1
                pbi_id = f"PBI-{parent_seq[parent_story_id or story_id]:03d}{suffix}"
            else:
                pbi_id = f"PBI-{seq:03d}"
                parent_seq[story_id] = seq
                seq += 1

            sp = sp_by_story.get(story_id, 3)
            bv, tc, rr = score.business_value, score.time_criticality, score.risk_reduction
            wsjf_score = round((bv + tc + rr) / sp, 2)

            invest = est.get("invest") or {}
            invest_flags = invest.get("invest_flags") or []
            invest_pass = bool(invest.get("invest_pass", not invest_flags))
            if invest_flags:
                invest_warnings.append(f"{pbi_id} [{story_id}]: invest_flags={invest_flags}.")

            is_oversized = bool(est.get("needs_split")) and split_round >= _MAX_SPLIT_ROUND
            if is_oversized:
                oversized.append(story_id)

            status = self._planning_status(is_oversized, invest_pass, invest_flags)
            desc = (story.get("description") or "").strip()
            if not self._valid_story_format(desc):
                format_warnings.append(f"{pbi_id} [{story_id}]: invalid user story format.")
                if status == "ready":
                    status = "needs_refinement"

            trace = story.get("requirement_trace") or {}
            source_requirement_id = (
                story.get("source_requirement_id")
                or trace.get("requirement_id")
                or story_id
            )
            est_data = est.get("estimation") or {}

            items.append({
                "id": pbi_id,
                "source_story_id": story_id,
                "source_requirement_id": source_requirement_id,
                "type": story.get("type", trace.get("requirement_type", "functional")),
                "domain": story.get("domain", ""),
                "title": story.get("title", ""),
                "description": desc,
                "requirement_trace": trace,
                "split": split_meta,
                "estimation": {
                    "story_points": sp,
                    "complexity": est_data.get("complexity", 2),
                    "effort": est_data.get("effort", 2),
                    "uncertainty": est_data.get("uncertainty", 2),
                },
                "prioritization": {
                    "priority_rank": final_rank.get(story_id, len(items) + 1),
                    "wsjf_score": wsjf_score,
                    "business_value": bv,
                    "time_criticality": tc,
                    "risk_reduction": rr,
                },
                "_raw_blocked_by": (est.get("dependencies") or {}).get("blocked_by") or [],
                "_raw_blocks": (est.get("dependencies") or {}).get("blocks") or [],
                "planning": {
                    "status": status,
                    "target_sprint": None,
                    "tags": self._tags_for_story(story),
                },
                "quality": {
                    "invest_pass": invest_pass,
                    "invest_flags": invest_flags,
                    "acceptance_criteria": [],
                },
                "analysis": {
                    "is_feasible": (est.get("feasibility") or {}).get("is_feasible", True),
                    "feasibility_notes": (est.get("feasibility") or {}).get("feasibility_notes", ""),
                    "invest_notes": invest.get("invest_notes", ""),
                    "risks": est.get("risks") or [],
                    "estimation_reasoning": est_data.get("reasoning", ""),
                    "split_warning": est_data.get("split_warning", ""),
                    "wsjf_thought": score.thought,
                },
            })

        # Translate raw story-id dependencies to PBI-ids for the persisted artifact.
        story_to_pbi = {item["source_story_id"]: item["id"] for item in items}
        for item in items:
            item["dependencies"] = {
                "blocked_by": [
                    story_to_pbi.get(sid, sid) for sid in item.pop("_raw_blocked_by", [])
                ],
                "blocks": [
                    story_to_pbi.get(sid, sid) for sid in item.pop("_raw_blocks", [])
                ],
            }

        total_points = sum(i["estimation"]["story_points"] for i in items)
        ready_count = sum(1 for i in items if i["planning"]["status"] == "ready")
        refine_count = sum(1 for i in items if i["planning"]["status"] == "needs_refinement")
        failed_count = sum(1 for i in items if i["planning"]["status"] == "invest_failed")
        over_count = sum(1 for i in items if i["planning"]["status"] == "oversized")

        artifacts = dict(state.get("artifacts") or {})
        product_backlog = {
            "id": str(uuid.uuid4()),
            "session_id": state.get("session_id", ""),
            "source_artifacts": [
                "requirement_list_approved",
                "reviewed_product_vision",
                "user_story_draft",
                "analyst_estimation",
            ],
            "status": "draft",
            "total_items": len(items),
            "total_story_points": total_points,
            "ready_count": ready_count,
            "needs_refinement_count": refine_count,
            "invest_failed_count": failed_count,
            "oversized_count": over_count,
            "split_round": split_round,
            "items": items,
            "methodology": {
                "story_format": "As a <role>, I can <capability>, so that <benefit>.",
                "estimation": "Fibonacci story points from AnalystAgent.",
                "prioritization": "WSJF scores with dependency-aware ordering.",
                "quality_gate": "INVEST status from AnalystAgent.",
            },
            "pass_notes": wsjf.pass_notes,
            "quality_warnings": {
                "invest": invest_warnings,
                "format": format_warnings,
                "fibonacci": fib_warnings,
                "oversized": [
                    f"{story_id}: exceeded split threshold after {_MAX_SPLIT_ROUND} rounds."
                    for story_id in oversized
                ],
            },
            "created_at": datetime.now().isoformat(),
            **({"rebuild_feedback": feedback} if feedback else {}),
        }
        artifacts["product_backlog"] = product_backlog
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

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _wsjf_value(score: _WsjfEmit, sp: int) -> float:
        denominator = sp if sp > 0 else 1
        return (score.business_value + score.time_criticality + score.risk_reduction) / denominator

    @staticmethod
    def _story_id(item: Dict[str, Any]) -> str:
        return (
            item.get("source_story_id")
            or item.get("source_req_id")
            or item.get("id")
            or ""
        )

    @staticmethod
    def _extract_role(description: str) -> str:
        lower = description.lower()
        if lower.startswith("as an "):
            return description[6:].split(",", 1)[0].strip()
        if lower.startswith("as a "):
            return description[5:].split(",", 1)[0].strip()
        return "User"

    @staticmethod
    def _extract_benefit(description: str) -> str:
        marker = ", so that "
        idx = description.lower().find(marker)
        if idx == -1:
            return "achieve the intended outcome"
        return description[idx + len(marker):].rstrip(".")

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
    def _normalise_requirement_trace(requirement: Dict[str, Any]) -> Dict[str, Any]:
        req_type = SprintAgent._normalise_requirement_type(
            requirement.get("type") or requirement.get("req_type") or "functional"
        )
        if req_type == "out_of_scope":
            req_type = "functional"
        priority = requirement.get("priority") or "medium"
        if priority not in {"high", "medium", "low"}:
            priority = "medium"
        confidence = requirement.get("confidence")
        if confidence not in {"confirmed", "inferred"}:
            confidence = "confirmed"
        return {
            "requirement_id": requirement.get("id") or requirement.get("req_id") or "",
            "requirement_type": req_type,
            "stakeholder": requirement.get("stakeholder") or requirement.get("role") or "",
            "statement": requirement.get("statement") or requirement.get("description") or "",
            "rationale": requirement.get("rationale") or "",
            "acceptance_criteria": requirement.get("acceptance_criteria")
            or requirement.get("acceptancecriteria")
            or [],
            "trace_refs": list(requirement.get("trace_refs") or []),
            "priority": priority,
            "status": requirement.get("status") or "confirmed",
            "threshold_needed": bool(
                requirement.get("threshold_needed")
                or requirement.get("requires_threshold", False)
            ),
            "confidence": confidence,
            "trigger_event": requirement.get("trigger_event") or "",
            "product_object": requirement.get("product_object") or "",
            "observable_outcome": requirement.get("observable_outcome") or "",
            "operating_condition": requirement.get("operating_condition") or "",
            "participation_structure": requirement.get("participation_structure") or "",
        }

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

    @staticmethod
    def _compact_product_vision(state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        vision = (
            artifacts.get("reviewed_product_vision")
            or artifacts.get("product_vision")
            or state.get("product_vision")
            or {}
        )
        return {
            "intent_summary": vision.get("intent_summary", ""),
            "target_outcome": vision.get("target_outcome", ""),
            "known_signals": list(vision.get("known_signals") or []),
            "roles": vision.get("roles") or vision.get("stakeholders") or [],
            "assumptions": vision.get("assumptions") or [],
            "concerns": vision.get("concerns") or [],
            "scope": vision.get("scope") or vision.get("out_of_scope") or [],
        }

    @staticmethod
    def _domain_from_trace(trace: Dict[str, Any]) -> str:
        return (
            (trace.get("stakeholder") or "").strip()
            or (trace.get("requirement_type") or "").strip()
            or "General"
        )

    @classmethod
    def _format_traces(cls, traces: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for trace in traces:
            block = {
                **trace,
                "suggested_domain": cls._domain_from_trace(trace),
            }
            lines.append(cls._json(block))
        return "\n".join(lines)

    @classmethod
    def _format_stories_with_estimation(
        cls,
        stories: List[Dict[str, Any]],
        est_lookup: Dict[str, Dict[str, Any]],
    ) -> str:
        lines: List[str] = []
        for story in stories:
            story_id = cls._story_id(story)
            est = est_lookup.get(story_id, {})
            trace = story.get("requirement_trace") or {}
            block = {
                "source_story_id": story_id,
                "source_requirement_id": story.get("source_requirement_id"),
                "type": story.get("type"),
                "domain": story.get("domain"),
                "title": story.get("title"),
                "description": story.get("description"),
                "requirement_trace": trace,
                "analyst_estimation": {
                    "story_points": (est.get("estimation") or {}).get("story_points"),
                    "complexity": (est.get("estimation") or {}).get("complexity"),
                    "effort": (est.get("estimation") or {}).get("effort"),
                    "uncertainty": (est.get("estimation") or {}).get("uncertainty"),
                    "invest_flags": (est.get("invest") or {}).get("invest_flags") or [],
                    "blocked_by": (est.get("dependencies") or {}).get("blocked_by") or [],
                    "risks": est.get("risks") or [],
                },
            }
            lines.append(cls._json(block))
        return "\n".join(lines)

    @staticmethod
    def _valid_story_format(description: str) -> bool:
        """Accept user-shape and system/NFR-shape.

        User-shape:    "As <actor>, I can <X>, so that <Y>."
        System-shape:  "As <actor>, the product/system must|shall <X>, so that <Y>."

        Actor article is optional ("As a student" / "As teaching staff" both ok).
        """
        lower = description.lower().strip()
        if not lower.startswith("as "):
            return False
        if ", so that " not in lower:
            return False
        user_clause = ", i can "
        system_clauses = (
            ", the product must ",
            ", the product shall ",
            ", the system must ",
            ", the system shall ",
        )
        return user_clause in lower or any(c in lower for c in system_clauses)

    @staticmethod
    def _planning_status(
        is_oversized: bool,
        invest_pass: bool,
        invest_flags: List[str],
    ) -> Literal["ready", "needs_refinement", "invest_failed", "oversized"]:
        if is_oversized:
            return "oversized"
        if len(invest_flags) >= 3:
            return "invest_failed"
        if not invest_pass:
            return "needs_refinement"
        return "ready"

    @staticmethod
    def _tags_for_story(story: Dict[str, Any]) -> List[str]:
        tags: List[str] = []
        domain = (story.get("domain") or "").strip()
        if domain:
            tags.append(domain.lower().replace(" ", "_"))
        story_type = story.get("type")
        if story_type == "non_functional":
            tags.append("non_functional")
        elif story_type == "system":
            tags.append("system")
        return tags

    @staticmethod
    def _feedback_block(feedback: str, context: str) -> str:
        if not feedback:
            return ""
        return (
            "\n\nREVIEWER FEEDBACK — previous output was rejected:\n"
            f"{feedback}\n"
            f"Address this during {context}.\n"
        )
