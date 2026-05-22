"""
analyst.py - AnalystAgent (Tech Lead + AC Specialist)

Two backlog-lane phases:

  Estimation
      Input:  user_story_draft + compact reviewed Product Vision.
      LLM Pass 1 (single call):  feasibility, INVEST (6 bool),
          dependencies, risks, split proposals — across every story.
      LLM Pass 2 (single call): complexity / effort / uncertainty
          (1-5 each) + reasoning — one entry per story.
      Python: derives invest_flags from the six bools, sums and
          snaps to Fibonacci, flags needs_split/split_warning,
          assembles analyst_estimation.

  Refinement
      Input:  product_backlog_approved + compact Product Vision.
      LLM Pass 3 (single call): Given-When-Then ACs + status — one
          entry per PBI.
      Python: assigns AC ids, assembles validated_product_backlog.

Schema descriptions teach WHAT each field is. Prompt blocks teach HOW
to reason. No domain, role name, or product category is hardcoded.
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
_FIBONACCI_SET = set(_FIBONACCI)
_SPLIT_THRESHOLD = 8

# Status severity for combining sprint's planning.status with Pass 3 AC status.
# Higher severity wins; Pass 3 can only DOWNGRADE further, never upgrade.
_STATUS_SEVERITY = {
    "ready": 0,
    "needs_refinement": 1,
    "oversized": 2,
    "invest_failed": 3,
}


def _combine_status(planning_status: str, ac_status: str) -> str:
    """Return the more severe of the two status values."""
    p = _STATUS_SEVERITY.get(planning_status, 0)
    a = _STATUS_SEVERITY.get(ac_status, 0)
    return planning_status if p >= a else ac_status

T = TypeVar("T")


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "429" in text or "rate_limit" in text or "rate limit" in text


def _snap_fibonacci(c: int, e: int, u: int) -> int:
    """Deterministic mapping from sum to Fibonacci. Python's job, not the LLM's."""
    total = max(3, min(15, int(c) + int(e) + int(u)))
    if total <= 4:
        return 1
    if total <= 6:
        return 2
    if total <= 8:
        return 3
    if total <= 10:
        return 5
    if total <= 12:
        return 8
    if total <= 14:
        return 13
    return 21


# ─────────────────────────────────────────────────────────────────────────────
# Prompt blocks — taught vocabulary lives here, not in schema descriptions.
# Cross-domain placeholders only (<actor>, <object>, <surface>).
# ─────────────────────────────────────────────────────────────────────────────

_FOUNDATIONS = """\
FOUNDATIONS

You are reading user stories whose obligations are already named in
requirement_trace. Your job is to surface the engineering shape of
each story — feasibility, INVEST, dependency, risk, estimate, and
acceptance criteria — so the team can plan a sprint without
discovering hidden cost mid-flight.

THE OBLIGATION CARRIES SIX AXES OF EVIDENCE

  stakeholder             - audience that LIVES the outcome.
  trigger_event           - event class that activates the obligation.
  operating_condition     - when the obligation is active.
  product_object          - product-owned object acted on.
  observable_outcome      - what the audience observes when it holds.
  participation_structure - who participates / decides / is affected.

These six are richer than the bare statement. They are the primary
evidence for INVEST judgments and AC clauses.

CONFIDENCE

  confirmed - obligation directly grounded in stated evidence.
  inferred  - upstream synthesis from friction; product shape is
              Distiller's translation, not stakeholder-stated.

A confidence='inferred' trace warrants more uncertainty during
estimation and clearer reviewer notes during AC writing.

DOMAIN NEUTRALITY

Use the vocabulary of the trace in front of you. No imported domain
examples, fixed role names, or product categories.
"""


_REASONING_MOVES = """\
REASONING MOVES

INVEST AS SIX INDEPENDENT JUDGMENTS

Not one box. Six separate questions, each with its own evidence:

  independent - can the story deliver value alone, or does it
                require another story to ship first? Multi-actor
                participation_structure often forces non-independence.

  negotiable  - does the team have implementation freedom? An
                'inferred' obligation is often MORE negotiable, not
                less — the direction is set, the shape is open.

  valuable    - does rationale + observable_outcome name a real
                audience benefit? Empty observable_outcome is a red
                flag.

  estimable   - can the team produce a Fibonacci estimate? Inferred
                + thin trace_refs + missing operating_condition
                often mean NOT estimable.

  small       - would it fit one sprint (≤8 points)? Many triggers,
                broad AC, multi-actor flows usually fail 'small'.

  testable    - can a product-observable AC be written? Empty
                product_object is a red flag — no anchor.

ACCEPTANCE CRITERIA — PRODUCT-OBSERVABLE OR DROPPED

Three valid shapes:

  state      - "Given <cond>, When <trigger>, Then the product
                displays / records / exposes <X> on <surface>."
  capability - "Given <cond>, When <role> attempts <action>, Then
                <role> can <product-side capability>."
  invariant  - "Given <conditions>, When <any changes>, Then
                <invariant holds>."

NOT valid — user-cognition Then-clauses:
  ✗ "Then <role> understands ..."
  ✗ "Then <role> feels confident ..."
  ✗ "Then <role> recognises ..."

If the obligation only has user-cognition outcomes available, the
team cannot test it; keep the PBI needs_refinement with a gap note.

LANGUAGE DISCIPLINE FOR AC

Each Then carries ONE verifiable assertion. Avoid adjectives that
imply a hidden threshold without naming one ("easy", "clean",
"intuitive", "simple", "appropriate", "fast", "seamless"). If the
requirement needs that quality, name the threshold (count, duration,
presence/absence) or keep the PBI needs_refinement.

FIBONACCI ESTIMATION (consumed in Pass 2)

You emit three concept scores per story (1-5 each):

  complexity   - structural difficulty.
  effort       - implementation surface.
  uncertainty  - ambiguity left to resolve.

Python sums and snaps to Fibonacci. Do NOT emit story_points or
split_warning — Python applies the deterministic mapping.

SPLIT PRESSURE (Pass 1)

A story bundles when it has distinct triggers, audiences, product
objects, or outcomes. Propose split slices when this holds; you
PROPOSE — SprintAgent materialises children. Do not write child
stories yourself.

WHAT YOU DO NOT DO

  - Invent requirements, thresholds, technologies, or rules absent
    from trace evidence.
  - Use the original project description; requirement_trace is your
    evidence.
  - Change story wording (SprintAgent owns titles and descriptions).
  - Compute story_points, derive invest_flags, or assign AC ids —
    Python does.
"""


_PASS_FEASIBILITY = """\
PASS 1 — FEASIBILITY, INVEST, DEPENDENCIES, RISKS, SPLIT PRESSURE

You see every user story plus compact Product Vision context. For
each story, emit ONE assessment.

MENTAL MODEL

1. FEASIBILITY first. "Can implementation reasonably begin?" Mark
   infeasible only when required information is missing or
   contradictory and the gap blocks any safe start. A story with
   uncertain detail is still feasible if the team can probe during
   sprint 0.

2. INVEST as six bools — answer each independently, evidence-anchored.
   Reasoning for any 'false' answer goes in invest_notes.

3. DEPENDENCIES — `blocked_by` is the set of source_story_id values
   that must ship first for this story to deliver value. `blocks` is
   the reverse direction. Cross-flow concerns from vision or stated
   participation_structure usually surface these.

4. RISKS — technical risks the team should know before planning.
   Anchor each to trace_refs or Product Vision concerns, not to
   imagination. Categories: performance, security, integration,
   data, unknown.

5. SPLIT PROPOSALS — when a story bundles, propose slices. A
   horizontal split (one slice per participant role) often follows
   participation_structure='multi-actor'. A vertical split (one
   slice per operating_condition) often follows AC pointing at
   distinct conditions. Propose, do not materialise.

WHAT YOU EMIT (per story)

  source_story_id,
  is_feasible, feasibility_notes,
  independent, negotiable, valuable, estimable, small, testable,
  invest_notes,
  blocked_by, blocks,
  split_proposals, risks,
  thought

Python derives invest_flags from the six bools — do NOT emit a
duplicate flag list.
"""


_PASS_ESTIMATION = """\
PASS 2 — COMPLEXITY / EFFORT / UNCERTAINTY (EVERY STORY)

You see every user story plus its Pass-1 assessment plus compact
Product Vision context. Emit one estimation entry per story; Python
applies the Fibonacci snap.

COMPLEXITY (1-5)

Structural difficulty. How many parts interact? Does
participation_structure introduce coordination cost (multi-actor,
contested, delegated)? Does product_object exist already or need
new shape?

  - 5: team has to invent new structure.
  - 1: clear add to an existing surface.

EFFORT (1-5)

Implementation surface. Number of files, screens, content items,
integration points. observable_outcome requiring multiple
presentation surfaces raises this.

  - 5: many things to build.
  - 1: one small thing.

UNCERTAINTY (1-5)

Ambiguity left to resolve during implementation.

  - Inferred confidence raises uncertainty (product shape was
    Distiller-translated).
  - Empty operating_condition or trigger_event raises uncertainty.
  - Threshold gaps from Pass 1 raise uncertainty.
  - Hard dependencies on other stories raise uncertainty.

WHAT YOU EMIT (one entry per story)

  source_story_id, complexity, effort, uncertainty, reasoning

Python applies the deterministic Fibonacci snap:

    3-4  → 1     11-12 → 8
    5-6  → 2     13-14 → 13
    7-8  → 3     15    → 21
    9-10 → 5

Do NOT emit story_points, needs_split, or split_warning — Python
derives all three from your three scores.
"""


_PASS_AC = """\
PASS 3 — ACCEPTANCE CRITERIA (EVERY PBI)

You see every PBI plus compact Product Vision context. Write Given-
When-Then ACs that inspect the PRODUCT, one entry per PBI.

SIX-AXIS SEEDING (use the requirement_trace first)

  operating_condition  → Given clause. Lift the trace value
                         verbatim when present (e.g.
                         "post-integrity process", "assignment
                         start", "group project context"). DO NOT
                         default everything to "the product is
                         running" — that erases the
                         operating_condition signal.

  trigger_event        → When clause. Lift the trace value (e.g.
                         "student accesses guidance", "lecturer
                         requests examples"). Empty trigger_event
                         means the obligation is an INVARIANT —
                         see INVARIANT SHAPE below; never write
                         "When always-on" or "When the product is
                         running" — those are not events.

  product_object       → noun the Then asserts about.
  observable_outcome   → Then clause (product-observable).
  participation_structure → multi-actor / contested / delegated
                            warrants at least one AC exercising the
                            collaboration.

INVARIANT SHAPE (when trigger_event is empty)

  - given: state the conditions under which the invariant must hold
           (e.g. "the product has loaded content").
  - when:  leave empty OR write a synthesis event the trace
           supports (e.g. "When content is published", "When the
           formal policy updates"). Do not write "always-on".
  - then:  state the invariant the product preserves.

requirement_trace.acceptance_criteria from Distiller are already in
one of the three reviewable shapes; formalise them as GWT — do not
paraphrase away their shape.

────────────────────────────────────────────────────────────────
PRODUCT-OBSERVABLE OR DROPPED — anti-cognition rule
────────────────────────────────────────────────────────────────

Then must inspect the PRODUCT. The team must be able to verify it
without interviewing a user. Forbidden Then-shapes (cross-domain):

  ✗ "Then <role> understands ..."
  ✗ "Then <role> feels confident ..."
  ✗ "Then <role> trusts ..."
  ✗ "Then <role> recognises ..."
  ✗ "Then <role> finds <X> easy ..."
  ✗ "Then feedback from <role> confirms <X>"
  ✗ "Then <role> can <do-something-outside-the-product>"

If trace evidence only supports a cognition outcome, write the
qualitative product-side AC ("Then the product presents <X> in
plain language") AND set ac_status=needs_refinement with the gap
named in `thought`. Do not paper over with cognition phrasing.

NON-FUNCTIONAL ACs

Use measurable thresholds only when they appear in trace evidence.
If the NFR needs a threshold but trace has none, write the
qualitative AC and set ac_status=needs_refinement with a thought
naming the missing threshold.

SYSTEM ACs

System PBIs assert product-wide invariants. Write the AC around the
invariant under INVARIANT SHAPE above. No stakeholder-specific
workflow.

SPLIT CHILDREN

Scope the AC to the child's narrow obligation. Keep the parent
requirement_trace visible for context.

OUTPUT SHAPE

2-5 ACs per PBI. Always include at least one happy_path. Add at
least one edge_case OR error_case when trace evidence supports
boundary or failure behavior (e.g. operating_condition implies a
non-default state, or analyst.risks names a failure mode). A PBI
with only happy_path ACs and no plausible boundary is acceptable
only when trace has no boundary signal — say so in `thought`.

AC STATUS — your judgment of AC QUALITY ONLY

  - ready              - ACs cover the obligation cleanly using
                         product-observable Then-clauses; six axes
                         lifted from trace; no missing threshold.
  - needs_refinement   - a gap remains (missing threshold, only-
                         user-cognition evidence available,
                         contradictory trace, ACs paper over
                         operating_condition with "always-on").

You judge AC quality. Python combines your status with the PBI's
existing planning.status (from sprint) by severity-max — meaning a
PBI already flagged needs_refinement / invest_failed / oversized
stays at least that bad regardless of what you emit. You can only
DOWNGRADE further (ready → needs_refinement) based on AC evidence,
never UPGRADE.

CONFIDENCE AWARENESS

When requirement_trace.confidence is 'inferred', write ACs from
the product-side translation, but in `thought` name the inference
so a reviewer can spot-check before commit.

WHAT YOU EMIT (one entry per PBI)

  pbi_id,
  acceptance_criteria: [{given, when, then, type}, ...],
  status,
  thought

Python assigns AC ids (AC-001, AC-002, ...). Do NOT emit ids.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Schemas — describe WHAT a field is. HOW to reason lives in prompts above.
# ─────────────────────────────────────────────────────────────────────────────

class _SplitProposal(BaseModel):
    title: str = Field(description="Proposed split-child title.")
    capability: str = Field(description="Proposed split-child capability clause.")
    reasoning: str = Field(description="Why this split is useful.")


class _TechnicalRisk(BaseModel):
    category: Literal["performance", "security", "integration", "data", "unknown"] = Field(
        description="Risk category."
    )
    description: str = Field(description="Risk description.")
    level: Literal["low", "medium", "high", "critical"] = Field(description="Risk level.")
    mitigation: str = Field(description="Mitigation note.")


class _StoryFeasibility(BaseModel):
    """LLM output for Pass 1 — one entry per story."""
    source_story_id: str = Field(description="The story being assessed.")
    is_feasible: bool = Field(description=(
        "False only when required information is missing or contradictory "
        "and the gap blocks any safe start; uncertain detail does not make "
        "a story infeasible."
    ))
    feasibility_notes: str = Field(description="Feasibility rationale.")
    independent: bool = Field(description="INVEST 'I' — can deliver value alone.")
    negotiable: bool = Field(description="INVEST 'N' — implementation choices left open.")
    valuable: bool = Field(description="INVEST 'V' — rationale+outcome name a real benefit.")
    estimable: bool = Field(description="INVEST 'E' — team can produce a Fibonacci estimate.")
    small: bool = Field(description="INVEST 'S' — would fit one sprint (≤8 points).")
    testable: bool = Field(description="INVEST 'T' — product-observable AC can be written.")
    invest_notes: str = Field(description="Reasoning for any false INVEST bool.")
    blocked_by: List[str] = Field(default_factory=list, description=(
        "source_story_id values that must ship first for this story to "
        "deliver value."
    ))
    blocks: List[str] = Field(default_factory=list, description=(
        "source_story_id values this story unblocks."
    ))
    split_proposals: List[_SplitProposal] = Field(default_factory=list, description=(
        "Proposed split slices; SprintAgent materialises children later."
    ))
    risks: List[_TechnicalRisk] = Field(default_factory=list, description=(
        "Technical risks anchored to trace_refs or vision concerns."
    ))
    thought: str = Field(description="One-sentence summary of the assessment.")


class _FeasibilityList(BaseModel):
    assessments: List[_StoryFeasibility] = Field(description="One assessment per story.")
    pass_notes: str = Field(description="Reviewer-facing Pass 1 summary.")


class _EstimationEmit(BaseModel):
    """LLM output for Pass 2 — one entry per story."""
    source_story_id: str = Field(description="The story being estimated.")
    complexity: int = Field(ge=1, le=5, description="Structural difficulty, 1-5.")
    effort: int = Field(ge=1, le=5, description="Implementation surface, 1-5.")
    uncertainty: int = Field(ge=1, le=5, description="Ambiguity left to resolve, 1-5.")
    reasoning: str = Field(description="One-sentence estimation rationale.")


class _EstimationList(BaseModel):
    estimations: List[_EstimationEmit] = Field(description="One entry per story.")
    pass_notes: str = Field(description="Reviewer-facing Pass 2 summary.")


class _AcEmit(BaseModel):
    given: str = Field(description=(
        "Operating condition lifted from trace.operating_condition. Avoid "
        "the placeholder 'the product is running' — lift the trace value "
        "when present so the AC reflects the obligation's real context."
    ))
    when: str = Field(default="", description=(
        "Trigger lifted from trace.trigger_event. Leave empty for "
        "invariants (no event activates them); never write 'always-on' "
        "or 'the product is running' as a When clause."
    ))
    then: str = Field(description=(
        "Product-observable outcome on trace.product_object. Three valid "
        "shapes only: product state, product capability accessed by a role, "
        "or product invariant. User-cognition Then-clauses are forbidden."
    ))
    type: Literal["happy_path", "edge_case", "error_case"] = Field(
        description="AC category."
    )


class _PbiAcEmit(BaseModel):
    """LLM output for Pass 3 — one entry per PBI."""
    pbi_id: str = Field(description="The PBI receiving these ACs.")
    acceptance_criteria: List[_AcEmit] = Field(description=(
        "2-5 ACs; at least one happy_path. edge_case / error_case when "
        "trace evidence supports boundary or failure behavior."
    ))
    status: Literal["ready", "needs_refinement"] = Field(description=(
        "ready when ACs cover the obligation cleanly; needs_refinement when "
        "a gap remains (missing threshold, only-user-cognition evidence, "
        "contradictory trace)."
    ))
    thought: str = Field(description=(
        "AC generation note; name the inference for confidence='inferred' traces."
    ))


class _AcGenerationList(BaseModel):
    pbis: List[_PbiAcEmit] = Field(description="One entry per PBI.")
    pass_notes: str = Field(description="Reviewer-facing Pass 3 summary.")


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class AnalystAgent(BaseAgent):
    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="analyst")
        custom = (
            self._raw_config.get("iredev", {})
            .get("agents", {})
            .get("analyst", {})
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
        """AnalystAgent uses structured extraction only."""

    def process_estimation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        if "analyst_estimation" in artifacts and not (state.get("split_round", 0) > 0):
            logger.warning("[AnalystAgent] analyst_estimation already exists.")
            return {}
        return self._run_estimation(state)

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        if "validated_product_backlog" in artifacts:
            logger.warning("[AnalystAgent] validated_product_backlog already exists.")
            return {}
        return self._run_ac_generation(state)

    # ── Estimation phase ─────────────────────────────────────────────────────

    def _run_estimation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        draft = artifacts.get("user_story_draft") or {}
        stories = draft.get("stories") or []
        feedback = (state.get("product_backlog_feedback") or "").strip()
        split_round = state.get("split_round", 0)
        if not stories:
            return {"errors": ["AnalystAgent: user_story_draft has no stories."]}

        product_vision = self._compact_product_vision(state)
        feedback_block = self._feedback_block(feedback, "feasibility and estimation")

        try:
            feasibility = self._pass_feasibility(stories, product_vision, feedback_block)
        except Exception as exc:
            logger.error("[AnalystAgent] Pass 1 failed: %s", exc, exc_info=True)
            return {"errors": [f"AnalystAgent Pass 1 error: {exc}"]}

        fa_by_id = {a.source_story_id: a for a in feasibility.assessments}

        try:
            estimation = self._pass_estimation(stories, fa_by_id, product_vision, feedback)
        except Exception as exc:
            logger.error("[AnalystAgent] Pass 2 failed: %s", exc, exc_info=True)
            return {"errors": [f"AnalystAgent Pass 2 error: {exc}"]}

        estimation_by_id = {e.source_story_id: e for e in estimation.estimations}
        missing = [self._story_id(s) for s in stories if self._story_id(s) not in estimation_by_id]

        return self._assemble_estimation_artifact(
            stories=stories,
            feasibility=feasibility,
            estimation_by_id=estimation_by_id,
            pass2_notes=estimation.pass_notes,
            missing=missing,
            state=state,
            feedback=feedback,
            split_round=split_round,
        )

    def _pass_feasibility(
        self,
        stories: List[Dict[str, Any]],
        product_vision: Dict[str, Any],
        feedback_block: str,
    ) -> _FeasibilityList:
        return self._with_rate_limit_retry(
            label="feasibility & INVEST",
            fn=lambda: self.extract_structured(
                schema=_FeasibilityList,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _REASONING_MOVES
                    + "\n\n" + _PASS_FEASIBILITY
                    + feedback_block
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(product_vision)}\n\n"
                    f"USER STORIES ({len(stories)} items):\n"
                    f"{self._format_story_block(stories)}\n\n"
                    "Assess every story. Use current source_story_id values "
                    "for blocked_by/blocks."
                ),
                include_memory=False,
            ),
        )

    def _pass_estimation(
        self,
        stories: List[Dict[str, Any]],
        fa_by_id: Dict[str, _StoryFeasibility],
        product_vision: Dict[str, Any],
        feedback: str = "",
    ) -> _EstimationList:
        return self._with_rate_limit_retry(
            label="estimation",
            fn=lambda: self.extract_structured(
                schema=_EstimationList,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _REASONING_MOVES
                    + "\n\n" + _PASS_ESTIMATION
                    + self._feedback_block(feedback, "estimation")
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(product_vision)}\n\n"
                    f"USER STORIES WITH PASS 1 ASSESSMENT ({len(stories)} items):\n"
                    f"{self._format_stories_with_feasibility(stories, fa_by_id)}\n\n"
                    "Emit one entry per story. complexity (1-5), effort (1-5), "
                    "uncertainty (1-5), and one-sentence reasoning. Python "
                    "derives story_points."
                ),
                include_memory=False,
            ),
        )

    def _assemble_estimation_artifact(
        self,
        stories: List[Dict[str, Any]],
        feasibility: _FeasibilityList,
        estimation_by_id: Dict[str, _EstimationEmit],
        pass2_notes: str,
        missing: List[str],
        state: Dict[str, Any],
        feedback: str = "",
        split_round: int = 0,
    ) -> Dict[str, Any]:
        fa_by_id = {a.source_story_id: a for a in feasibility.assessments}

        assembled: List[Dict[str, Any]] = []
        total_points = 0
        split_count = 0

        for story in stories:
            story_id = self._story_id(story)
            fa = fa_by_id.get(story_id)
            emit = estimation_by_id.get(story_id)

            if emit is not None:
                sp = _snap_fibonacci(emit.complexity, emit.effort, emit.uncertainty)
                complexity, effort, uncertainty = emit.complexity, emit.effort, emit.uncertainty
                reasoning = emit.reasoning
            else:
                complexity, effort, uncertainty, sp, reasoning = 2, 2, 2, 3, ""

            needs_split = sp > _SPLIT_THRESHOLD
            split_warning = (
                f"sp={sp} at split threshold; review whether one slice is deliverable."
                if sp == _SPLIT_THRESHOLD else ""
            )

            # Six independent bools → flags. Python derives, never asks the LLM.
            invest_pairs = (
                ("independent", fa.independent if fa else True),
                ("negotiable", fa.negotiable if fa else True),
                ("valuable", fa.valuable if fa else True),
                ("estimable", fa.estimable if fa else True),
                ("small", fa.small if fa else True),
                ("testable", fa.testable if fa else True),
            )
            invest_flags = [name for name, ok in invest_pairs if not ok]

            # An LLM-claimed 'small=true' must be overridden when the snap says split.
            if needs_split and "small" not in invest_flags:
                invest_flags.append("small")

            has_proposals = bool(fa and fa.split_proposals)
            actionable_split = needs_split and has_proposals
            if actionable_split:
                split_count += 1

            assembled.append({
                "source_story_id": story_id,
                "source_requirement_id": story.get("source_requirement_id")
                or (story.get("requirement_trace") or {}).get("requirement_id")
                or story_id,
                "type": story.get("type", "functional"),
                "domain": story.get("domain", ""),
                "title": story.get("title", ""),
                "description": story.get("description", ""),
                "requirement_trace": story.get("requirement_trace") or {},
                "split": story.get("split") or {},
                "feasibility": {
                    "is_feasible": fa.is_feasible if fa else True,
                    "feasibility_notes": fa.feasibility_notes if fa else "",
                },
                "invest": {
                    "invest_pass": len(invest_flags) == 0,
                    "invest_flags": invest_flags,
                    "invest_notes": fa.invest_notes if fa else "",
                    "criteria": {
                        "independent": fa.independent if fa else True,
                        "negotiable": fa.negotiable if fa else True,
                        "valuable": fa.valuable if fa else True,
                        "estimable": fa.estimable if fa else True,
                        "small": False if "small" in invest_flags else (fa.small if fa else True),
                        "testable": fa.testable if fa else True,
                    },
                },
                "dependencies": {
                    "blocked_by": list(fa.blocked_by) if fa else [],
                    "blocks": list(fa.blocks) if fa else [],
                },
                "split_proposals": [p.model_dump() for p in (fa.split_proposals if fa else [])],
                "needs_split": actionable_split,
                "risks": [r.model_dump() for r in (fa.risks if fa else [])],
                "estimation": {
                    "complexity": complexity,
                    "effort": effort,
                    "uncertainty": uncertainty,
                    "story_points": sp,
                    "reasoning": reasoning,
                    "split_warning": split_warning,
                },
            })
            total_points += sp

        pass1_note = (feasibility.pass_notes or "").strip()
        pass2_note = (pass2_notes or "").strip()
        missing_block = (
            "\n\nMISSING ESTIMATIONS (story ids with no Pass 2 entry):\n  "
            + ", ".join(missing)
        ) if missing else ""
        pass_notes = (
            "PASS 1 — FEASIBILITY / INVEST / DEPS / RISKS / SPLITS\n"
            f"  {pass1_note or '(no Pass 1 notes)'}\n\n"
            "PASS 2 — COMPLEXITY / EFFORT / UNCERTAINTY\n"
            f"  {pass2_note or '(no Pass 2 notes)'}"
            + missing_block
        )

        analyst_estimation = {
            "id": str(uuid.uuid4()),
            "session_id": state.get("session_id", ""),
            "source_artifacts": ["user_story_draft", "reviewed_product_vision"],
            "estimated_at": datetime.now().isoformat(),
            "split_round": split_round,
            "stories": assembled,
            "has_pending_splits": split_count > 0,
            "total_story_points": total_points,
            "estimation_stats": {
                "total_stories": len(assembled),
                "stories_needing_split": split_count,
                "invest_failures": sum(1 for s in assembled if not s["invest"]["invest_pass"]),
            },
            "pass_notes": pass_notes,
            **({"rebuild_feedback": feedback} if feedback else {}),
        }
        artifacts = dict(state.get("artifacts") or {})
        artifacts["analyst_estimation"] = analyst_estimation
        return {"artifacts": artifacts, "split_round": split_round}

    # ── AC phase ─────────────────────────────────────────────────────────────

    def _run_ac_generation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        backlog = artifacts.get("product_backlog_approved") or artifacts.get("product_backlog") or {}
        items = backlog.get("items") or []
        feedback = (state.get("analyst_feedback") or "").strip()
        if not items:
            return {"errors": ["AnalystAgent: product_backlog has no items."]}

        product_vision = self._compact_product_vision(state)

        try:
            ac_result = self._pass_ac(items, product_vision, feedback)
        except Exception as exc:
            logger.error("[AnalystAgent] Pass 3 failed: %s", exc, exc_info=True)
            return {"errors": [f"AnalystAgent Pass 3 error: {exc}"]}

        ac_by_pbi = {p.pbi_id: p for p in ac_result.pbis}
        missing = [item.get("id", "") for item in items if item.get("id", "") not in ac_by_pbi]

        return self._assemble_validated_backlog(
            ac_by_pbi=ac_by_pbi,
            pass3_notes=ac_result.pass_notes,
            missing=missing,
            source_pb=backlog,
            state=state,
            feedback=feedback,
        )

    def _pass_ac(
        self,
        items: List[Dict[str, Any]],
        product_vision: Dict[str, Any],
        feedback: str = "",
    ) -> _AcGenerationList:
        return self._with_rate_limit_retry(
            label="AC generation",
            fn=lambda: self.extract_structured(
                schema=_AcGenerationList,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _REASONING_MOVES
                    + "\n\n" + _PASS_AC
                    + self._feedback_block(feedback, "acceptance criteria generation")
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(product_vision)}\n\n"
                    f"PRODUCT BACKLOG ITEMS ({len(items)} PBIs):\n"
                    f"{self._format_pbi_block(items)}\n\n"
                    "Emit one entry per PBI: pbi_id, acceptance_criteria "
                    "(given/when/then/type), status, thought. Python assigns AC ids."
                ),
                include_memory=False,
            ),
        )

    def _assemble_validated_backlog(
        self,
        ac_by_pbi: Dict[str, _PbiAcEmit],
        pass3_notes: str,
        missing: List[str],
        source_pb: Dict[str, Any],
        state: Dict[str, Any],
        feedback: str = "",
    ) -> Dict[str, Any]:
        final_items: List[Dict[str, Any]] = []
        total_ac = 0
        ready_count = 0
        upgrade_blocked: List[str] = []
        global_seq = 1

        for item in source_pb.get("items") or []:
            pbi_id = item.get("id", "")
            emit = ac_by_pbi.get(pbi_id)
            ac_list: List[Dict[str, Any]] = []
            if emit is not None:
                for ac in emit.acceptance_criteria:
                    ac_list.append({
                        "id": f"AC-{global_seq:03d}",
                        "given": ac.given,
                        "when": ac.when,
                        "then": ac.then,
                        "type": ac.type,
                    })
                    global_seq += 1
            total_ac += len(ac_list)

            # Pass 3 emits AC-quality status; combine with sprint's planning.status
            # via severity-max so Pass 3 can only downgrade, never upgrade.
            sprint_status = (item.get("planning") or {}).get("status", "needs_refinement")
            ac_status = emit.status if emit is not None else "needs_refinement"
            final_status = _combine_status(sprint_status, ac_status)
            if (
                ac_status == "ready"
                and sprint_status != "ready"
                and final_status != "ready"
            ):
                upgrade_blocked.append(f"{pbi_id} (sprint={sprint_status})")

            if final_status == "ready":
                ready_count += 1
            final_items.append({
                **item,
                "quality": {
                    **(item.get("quality") or {}),
                    "acceptance_criteria": ac_list,
                },
                "planning": {
                    **(item.get("planning") or {}),
                    "status": final_status,
                },
                "analysis": {
                    **(item.get("analysis") or {}),
                    "ac_generation_note": emit.thought if emit is not None else "",
                    "ac_status_emitted": ac_status,
                    "ac_status_sprint": sprint_status,
                },
            })

        missing_block = (
            "\n\nMISSING AC (PBI ids with no Pass 3 entry):\n  "
            + ", ".join(missing)
        ) if missing else ""
        upgrade_block = (
            "\n\nUPGRADES BLOCKED (Pass 3 emitted ready but sprint flagged worse):\n  "
            + ", ".join(upgrade_blocked)
        ) if upgrade_blocked else ""
        pass3_note = (pass3_notes or "").strip()
        refinement_summary = (
            "PASS 3 — AC GENERATION\n"
            f"  {pass3_note or '(no Pass 3 notes)'}"
            + upgrade_block
            + missing_block
        )

        validated = {
            **source_pb,
            "items": final_items,
            "status": "validated",
            "total_items": len(final_items),
            "ready_count": ready_count,
            "refinement_stats": {
                "total_pbis": len(final_items),
                "ready_count": ready_count,
                "total_ac": total_ac,
            },
            "refinement_summary": refinement_summary,
            "validated_at": datetime.now().isoformat(),
            **({"rebuild_feedback": feedback} if feedback else {}),
        }
        artifacts = dict(state.get("artifacts") or {})
        artifacts["validated_product_backlog"] = validated
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
                    "[AnalystAgent] %s rate-limited; retrying in %.1fs (attempt %d/%d).",
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
    def _story_id(item: Dict[str, Any]) -> str:
        return item.get("source_story_id") or item.get("source_req_id") or item.get("id") or ""

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

    @classmethod
    def _story_block_dict(cls, story: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "source_story_id": cls._story_id(story),
            "source_requirement_id": story.get("source_requirement_id"),
            "type": story.get("type"),
            "domain": story.get("domain"),
            "title": story.get("title"),
            "description": story.get("description"),
            "split": story.get("split") or {},
            "requirement_trace": story.get("requirement_trace") or {},
        }

    @classmethod
    def _format_story_block(cls, stories: List[Dict[str, Any]]) -> str:
        return "\n".join(cls._json(cls._story_block_dict(s)) for s in stories)

    @classmethod
    def _format_stories_with_feasibility(
        cls,
        stories: List[Dict[str, Any]],
        fa_by_id: Dict[str, _StoryFeasibility],
    ) -> str:
        """Stories + their Pass-1 assessment, one JSON block per story."""
        lines: List[str] = []
        for story in stories:
            story_id = cls._story_id(story)
            fa = fa_by_id.get(story_id)
            feas_block: Dict[str, Any] = {}
            if fa is not None:
                feas_block = {
                    "is_feasible": fa.is_feasible,
                    "invest": {
                        "independent": fa.independent,
                        "negotiable": fa.negotiable,
                        "valuable": fa.valuable,
                        "estimable": fa.estimable,
                        "small": fa.small,
                        "testable": fa.testable,
                    },
                    "blocked_by": fa.blocked_by,
                    "blocks": fa.blocks,
                    "split_proposals": [p.model_dump() for p in fa.split_proposals],
                    "risks": [r.model_dump() for r in fa.risks],
                }
            block = {**cls._story_block_dict(story), "pass1_assessment": feas_block}
            lines.append(cls._json(block))
        return "\n".join(lines)

    @classmethod
    def _format_pbi_block(cls, items: List[Dict[str, Any]]) -> str:
        return "\n".join(cls._json(cls._pbi_block_for_ac(item)) for item in items)

    @classmethod
    def _pbi_block_for_ac(cls, item: Dict[str, Any]) -> Dict[str, Any]:
        planning = item.get("planning") or {}
        return {
            "pbi_id": item.get("id"),
            "source_story_id": item.get("source_story_id"),
            "source_requirement_id": item.get("source_requirement_id"),
            "type": item.get("type"),
            "domain": item.get("domain"),
            "title": item.get("title"),
            "description": item.get("description"),
            "split": item.get("split") or {},
            "requirement_trace": item.get("requirement_trace") or {},
            "estimation": item.get("estimation") or {},
            # Show sprint's status so the LLM knows the upgrade-ceiling. Python
            # combines via severity-max, but seeing it helps the LLM frame
            # its `thought` honestly when sprint already flagged the PBI.
            "sprint_planning_status": planning.get("status"),
            "quality": {
                "invest_pass": (item.get("quality") or {}).get("invest_pass"),
                "invest_flags": (item.get("quality") or {}).get("invest_flags") or [],
            },
            "analysis": item.get("analysis") or {},
        }

    @staticmethod
    def _feedback_block(feedback: str, context: str) -> str:
        if not feedback:
            return ""
        return (
            "\n\nREVIEWER FEEDBACK — previous output was rejected:\n"
            f"{feedback}\n"
            f"Address this during {context}.\n"
        )
