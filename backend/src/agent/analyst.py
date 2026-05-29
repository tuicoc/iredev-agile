"""
analyst.py — AnalystAgent (Technical Lead + Acceptance-Criteria author)

Two responsibilities, each a single LLM pass. No Python scoring formula,
no hint→action routing, no refinement loop:

  ESTIMATION (Sprint Zero, step 9c): user_story_draft → analyst_estimation.
    One pass reads every story and reasons, story by story: feasibility,
    the six INVEST qualities, dependencies, technical risk, and a size
    the agent states DIRECTLY as a Fibonacci story-point number (no
    complexity/effort/uncertainty formula). When a story misses an INVEST
    quality the agent has full authority over the wording to fix it —
    rewrite the sentence, split it into child stories it sizes itself, or
    write the finer story an obligation implies — so that every story it
    returns clears all six INVEST qualities and serves exactly one
    stakeholder. Each story and each split child reports the INVEST read of
    the form as it is left, and Python gates ready on all six passing: a
    reshape is no longer an automatic pass. A story no honest reshape can
    save is left for human review (status=needs_human_input). The returned
    analyst_estimation.stories is the authoritative post-reshape set.

  ACCEPTANCE CRITERIA (Backlog Refinement, step 1): product_backlog_approved
    → validated_product_backlog. One pass writes Given-When-Then criteria
    per PBI from the obligation's trace evidence.

Numbers and judgments come from the agent's reasoning. Python only moves
data, assigns ids, snaps an off-grid point to the nearest Fibonacci as a
format guard, and persists artifacts. Prompts state the task and the
guarantees the output must meet — never a procedure. Schema descriptions
say WHAT a field holds. Each pass emits a `reasoning` field first so the
model thinks before it decides (observable in logs). No domain, topic,
role name, or product category is hardcoded.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Literal, Optional, TypeVar, Union

from pydantic import BaseModel, Field, field_validator

from .base import BaseAgent

logger = logging.getLogger(__name__)

_FIBONACCI = (1, 2, 3, 5, 8, 13, 21)
T = TypeVar("T")


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "429" in text or "rate_limit" in text or "rate limit" in text


def _nearest_fibonacci(value: Any) -> int:
    """Format guard only: snap an off-grid emitted point to the nearest
    Fibonacci value. This normalises a number the agent already reasoned —
    it never computes the estimate itself."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 3
    if v in _FIBONACCI:
        return v
    return min(_FIBONACCI, key=lambda f: abs(f - v))


# ─────────────────────────────────────────────────────────────────────────────
# Prompt blocks — task + guarantees, never procedure. Cross-domain
# placeholders only (<actor>, <object>, <surface>).
# ─────────────────────────────────────────────────────────────────────────────

_FOUNDATIONS = """\
FOUNDATIONS

You read user stories whose obligations are already named in their
requirement_trace. Each trace carries six axes of evidence: the
stakeholder who lives the outcome, the trigger that activates it, the
operating condition, the product object acted on, the observable
outcome, and the participation structure. These are richer than the
one-line title and are your primary evidence for every judgment.

A trace marked confidence=inferred was synthesised upstream from
friction rather than stated outright; carry more estimation uncertainty
on it and say so in your reasoning.

INVEST IS THE BAR EVERY STORY MUST CLEAR — and it is the bar on what you
RETURN, not just what you read: every story you leave standing, and every
child you split out, clears all six. A story is ready only when it is
independent (a self-contained unit of value for ONE stakeholder — an
ordinary ordering dependency recorded in blocked_by is fine, only tight
coupling breaks this), negotiable (the sentence states the capability and
its outcome and leaves the HOW open — exact fields, values, states, and
screen mechanics live in the acceptance criteria, not the story sentence),
valuable (its outcome is a real benefit to that audience), estimable (the team can
size it), small (it fits inside one sprint), and testable (you understand
the obligation well enough that you could write a test for it). These are
qualities to weigh per story, not boxes to tick — and when a story misses
one, the usual cure is to split it finer, not to flag it or fold it away.

ONE STORY, ONE STAKEHOLDER. Each story serves the single stakeholder the
obligation matters to most — the one whose outcome the system most depends
on. When an obligation is lived by several, give it to that primary
stakeholder, or split so each owns an independently valuable slice; never
address two audiences with one "A or B" story, which is neither
independent nor cleanly testable.

TESTABLE STARTS IN THE CARD, LANDS IN THE CRITERIA. The story sentence
carries an implicit promise: you understand the obligation well enough that
you could write a test for it. So the capability it names must be concrete
enough to admit a check — a state, an action with a result, or an output
someone could confirm by inspecting the product. A sentence whose only
payoff is that something works well, with nothing a test could point at,
breaks that promise; name the checkable behaviour instead. The acceptance
criteria are where that check is actually written — they complete the
story, they do not decorate it. If you cannot write a concrete criterion,
the obligation is not yet understood well enough: leave testable false
rather than writing one that only restates a vague card.

DOMAIN NEUTRALITY. Use the vocabulary of the trace in front of you. Do
not import role names, product categories, or domain examples from
outside this run.
"""

_PASS_ASSESS = """\
THIS PASS — SIZE, ASSESS, AND RESHAPE EACH STORY TO INVEST

Reason as the engineer who will build each story: whether it is feasible
to start, whether it clears each INVEST quality, what it depends on, what
technical risk it carries, and how large it is.

State the size directly as a story-point estimate on the Fibonacci scale
(1, 2, 3, 5, 8, 13, 21) — the number your reasoning lands on, reflecting
structural complexity, implementation surface, and the uncertainty an
inferred trace leaves open. A story you would not dare size is not
estimable.

You have full authority over the wording of the set so that every story
clears INVEST: rewrite a sentence from its trace evidence, split a story
into as many child stories as the obligation needs, or write the finer or
supporting story an obligation plainly implies. Use whatever of these the
story needs — splitting is the usual fix, since most INVEST gaps come from
a story still carrying more than one capability. The one thing you may not
do is lose or merge away a distinct obligation; prefer more, finer stories
over fewer coarse ones.

The six INVEST qualities you report describe each story AS YOU LEAVE IT —
after any rewrite — and every story you return, parent or split child,
must have all six true. A reshape is not a free pass: if your own rewrite
or split still cannot make all six honestly true, do not report a pass —
that is exactly the story to leave for human review.

A story that simply needs another story shipped first is NOT an
independence failure — that is an ordinary dependency, so record it in
blocked_by and still treat the story as independent and ready. Reserve
needs_human_input for the rare story no honest split or rewrite can save:
its evidence is missing or contradictory, or the call genuinely belongs
to a human.

For each story (and each split child), also write a small set of
Given-When-Then acceptance criteria — the story's confirmation, written
from the same trace while you hold it. Being able to write a concrete one
IS the test of testability: if you can, the story is testable; if you
cannot, it is not yet, and testable stays false. Source the Given from the
operating condition, the When from the trigger, and the Then from the
observable outcome on the product object; an invariant has no trigger, so
leave its When empty. Keep it lean: one or two criteria covering the happy
path, plus an edge or error case only when the trace evidence clearly
supports it. Each criterion is checkable by inspecting the product, never
by asking a user what they think or feel.

NEGOTIABLE IS A REWRITE TARGET, NOT A RUBBER STAMP. A story whose sentence
pins the implementation — enumerated fields, fixed values or states, a
particular screen — is not negotiable even when every other quality passes:
it reads as a frozen spec and leaves the team nothing to shape. The cure is
in your hands and costs nothing: state the capability and its outcome in the
sentence, and carry the concrete specifics in the acceptance criteria, where
a checkable detail belongs. Whenever your own sentence pins the HOW, mark
negotiable false and rewrite it to capability grain.

You guarantee: every story you return clears all six INVEST qualities and
serves exactly one stakeholder, carries a Fibonacci estimate and at least
one product-observable acceptance criterion — or is honestly left for
human review; the INVEST read you report is the read of the story as you
leave it; dependencies reference real story ids; a reshape leaves the
backlog cleaner and never buries two obligations under one heading.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Feedback re-run block (only attached when reviewer feedback is present)
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
points it names; it does not loosen the Fibonacci-direct sizing,
the six INVEST honesty, or the in-pass reshape contract.
"""


_FEEDBACK_BODY = """\
REVIEWER FEEDBACK — YOU MUST ADDRESS EVERY POINT BELOW:
{feedback}

Apply each point at the assessment slot it names:
  story_points (Fibonacci) · invest.* booleans · feasibility ·
  blocked_by / blocks · risks · reshape (rewrite or split
  children) · acceptance_criteria · needs_human_input · notes.

When a point challenges a size: re-reason the size from the
feedback's framing and state it directly — do not snap the
previous number with a small bump. When a point asks for a
split: emit sized child stories and let the parent fall away;
do not keep the parent with a smaller size. When a point asks
to mark a story needs_human_input: do not "save" it with a
reshape just to keep INVEST clean.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Schemas — WHAT each field holds. `reasoning` is declared first so the
# model reasons before it decides.
# ─────────────────────────────────────────────────────────────────────────────

class _Risk(BaseModel):
    category: Literal["performance", "security", "integration", "data", "unknown"] = Field(
        description="Risk category."
    )
    description: str = Field(description="What the risk is, anchored to the trace or a vision concern.")
    level: Literal["low", "medium", "high", "critical"] = Field(description="Severity.")
    mitigation: str = Field(description="One line on how to reduce it.")


class _AcEmit(BaseModel):
    given: str = Field(description="Operating condition lifted from trace.operating_condition.")
    when: str = Field(default="", description=(
        "Trigger lifted from trace.trigger_event. Empty for an invariant."
    ))
    then: str = Field(description=(
        "Product-observable outcome on trace.product_object: a product state, a "
        "capability a role can access, or an invariant. No user-cognition outcomes."
    ))
    type: Literal["happy_path", "edge_case", "error_case"] = Field(description="AC category.")


class _ChildStory(BaseModel):
    """One child the analyst writes when it splits a story to clear INVEST.
    A child is a new, independently shippable story; it must itself clear
    all six INVEST qualities, which it reports as it leaves them."""
    title: str = Field(description="Short noun-phrase title for the child obligation.")
    description: str = Field(description=(
        "User-story sentence for the child — 'As a <role>, I can <capability>, "
        "so that <benefit>.' One stakeholder only — the one this slice matters "
        "to most, never a compound 'A or B' audience. <capability> is a concrete "
        "product behaviour you could write a test for (something you can see, do, "
        "or inspect), not only an assurance that something works. Delivers value "
        "on its own."
    ))
    story_points: int = Field(description=(
        "Fibonacci size for this child (1, 2, 3, 5, 8, 13, 21), stated from "
        "your reasoning about it."
    ))
    independent: bool = Field(description="Self-contained unit of value (an ordering dependency in blocked_by is fine).")
    negotiable: bool = Field(description=(
        "True only when the sentence states the capability and its outcome and "
        "leaves the HOW open. False when it pins the implementation — enumerated "
        "fields, specific values or states, a fixed UI — which belongs in the "
        "acceptance criteria, not the story sentence. Read your own wording as a "
        "sceptical reviewer would before marking it true."
    ))
    valuable: bool = Field(description="Outcome is a real benefit to its one audience.")
    estimable: bool = Field(description="The team can size it.")
    small: bool = Field(description="Fits inside one sprint.")
    testable: bool = Field(description=(
        "You understand the obligation well enough to write a test for it: the "
        "capability the description names is concrete enough to confirm by "
        "inspecting the product. False when you could not write that check."
    ))
    invest_notes: str = Field(default="", description=(
        "Reasoning for any INVEST quality still false (empty when all six pass)."
    ))
    acceptance_criteria: List[_AcEmit] = Field(default_factory=list, description=(
        "1-2 Given-When-Then criteria for this child (happy path; add an edge/error "
        "only when the trace clearly supports it)."
    ))
    thought: str = Field(description="One line: why this child is independently shippable.")


class _Reshape(BaseModel):
    """Present only when a story must change to clear INVEST."""
    kind: Literal["rewrite", "split"] = Field(description=(
        "rewrite when one clearer sentence fixes it; split when it must become "
        "two or more child stories — including any finer or supporting story the "
        "obligation implies."
    ))
    rewritten_description: str = Field(default="", description=(
        "For kind=rewrite: the clearer story sentence sourced from the trace, "
        "serving one stakeholder. Empty for split."
    ))
    children: List[_ChildStory] = Field(default_factory=list, description=(
        "For kind=split: two or more child stories that together cover the "
        "original obligation without losing any of it, each sized, each serving "
        "one stakeholder and clearing all six INVEST. Empty for rewrite."
    ))
    reason: str = Field(description="Which INVEST quality this reshape restores, and how.")


class _StoryAssessment(BaseModel):
    source_story_id: str = Field(description="The story being assessed (matches the input id).")
    story_points: int = Field(description=(
        "Fibonacci size (1, 2, 3, 5, 8, 13, 21) stated directly from your "
        "reasoning — not a sub-score for a formula. For a split story this is "
        "the original's size before splitting (children carry their own)."
    ))
    independent: bool = Field(description=(
        "Is a self-contained unit of value. An ordinary ordering dependency "
        "(recorded in blocked_by) does NOT make it false; mark false only when "
        "it is so coupled to another story that neither can be delivered "
        "separately."
    ))
    negotiable: bool = Field(description=(
        "True only when the sentence states the capability and its outcome and "
        "leaves the HOW open. False when it pins the implementation — enumerated "
        "fields, specific values or states, a fixed UI — which belongs in the "
        "acceptance criteria, not the story sentence. Read your own wording as a "
        "sceptical reviewer would before marking it true."
    ))
    valuable: bool = Field(description="Outcome is a real benefit to its audience.")
    estimable: bool = Field(description="The team can size it.")
    small: bool = Field(description="Fits inside one sprint.")
    testable: bool = Field(description=(
        "You understand the obligation well enough to write a test for it: the "
        "capability the description names is concrete enough to confirm by "
        "inspecting the product. False when you could not write that check."
    ))
    invest_notes: str = Field(description=(
        "Reasoning for any INVEST quality still false after your reshape "
        "(empty when all six pass)."
    ))
    is_feasible: bool = Field(description=(
        "False only when required information is missing or contradictory and "
        "the gap blocks any safe start; uncertain detail alone is still feasible."
    ))
    feasibility_notes: str = Field(description="Feasibility rationale.")
    blocked_by: List[str] = Field(default_factory=list, description=(
        "source_story_id values that must ship first for this story to deliver value."
    ))
    blocks: List[str] = Field(default_factory=list, description="source_story_id values this story unblocks.")
    risks: List[_Risk] = Field(default_factory=list, description="Technical risks, if any.")
    reshape: Optional[_Reshape] = Field(default=None, description=(
        "Present only when the story misses an INVEST quality and you are "
        "fixing it. Omit when the story is already clean, or when no honest "
        "reshape helps (then leave the failing INVEST bools false so it "
        "surfaces for human review)."
    ))
    acceptance_criteria: List[_AcEmit] = Field(default_factory=list, description=(
        "1-2 Given-When-Then criteria for this story (happy path; add an edge/error "
        "only when the trace clearly supports it). Empty only when the story is "
        "split (children carry their own) or genuinely untestable."
    ))
    thought: str = Field(description="One-sentence summary of the assessment.")


class _AssessmentList(BaseModel):
    reasoning: str = Field(description=(
        "Your thinking before you assess — write this first, as a working "
        "scratchpad. Read the set as a whole: where the dependencies run, "
        "which stories are oversized or bundle more than one obligation and "
        "must split, which are vague or untestable and must be rewritten, and "
        "roughly how large each is. Reasoning this through first is what makes "
        "the per-story sizes and reshapes below sound."
    ))
    assessments: List[_StoryAssessment] = Field(description="One assessment per input story.")
    notes: str = Field(description="Reviewer-facing summary of the assessment.")


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
            self._rate_limit_base_delay = max(0.0, float(custom.get("rate_limit_base_delay", 5.0) or 5.0))
        except (TypeError, ValueError):
            self._rate_limit_base_delay = 5.0

    def _register_tools(self) -> None:
        """AnalystAgent uses structured extraction only."""

    # ── LangGraph entrypoints ────────────────────────────────────────────────

    def process_estimation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        feedback = (state.get("product_backlog_feedback") or "").strip()
        if "analyst_estimation" in artifacts and not feedback:
            logger.warning("[AnalystAgent] analyst_estimation already exists.")
            return {}
        return self._run_estimation(state)

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        if "validated_product_backlog" in artifacts and not (state.get("analyst_feedback") or "").strip():
            logger.warning("[AnalystAgent] validated_product_backlog already exists.")
            return {}
        return self._run_ac_generation(state)

    # ── Estimation phase (step 9c) ───────────────────────────────────────────

    def _run_estimation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        # 9c reads the PO-approved draft (9a' sentinel); fall back to the
        # raw draft only when running outside the gated flow (e.g.
        # --start-at debug paths that seed the unsentinelled artifact).
        draft = (
            artifacts.get("user_story_draft_approved")
            or artifacts.get("user_story_draft")
            or {}
        )
        stories = draft.get("stories") or []
        feedback = (state.get("product_backlog_feedback") or "").strip()
        if not stories:
            return {"errors": ["AnalystAgent: user_story_draft_approved has no stories."]}

        product_vision = self._compact_product_vision(state)
        feedback_block = self._feedback_block(feedback, "assessment, sizing, and reshaping")

        try:
            result = self._pass_assess(stories, product_vision, feedback_block)
        except Exception as exc:
            logger.error("[AnalystAgent] Estimation pass failed: %s", exc, exc_info=True)
            return {"errors": [f"AnalystAgent estimation error: {exc}"]}

        if (result.reasoning or "").strip():
            logger.info("[AnalystAgent] Estimation reasoning:\n%s", result.reasoning.strip())

        return self._assemble_estimation_artifact(
            stories=stories, result=result, state=state, feedback=feedback,
        )

    def _pass_assess(
        self,
        stories: List[Dict[str, Any]],
        product_vision: Dict[str, Any],
        feedback_block: str,
    ) -> _AssessmentList:
        return self._with_rate_limit_retry(
            label="assessment & estimation",
            fn=lambda: self.extract_structured(
                schema=_AssessmentList,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _PASS_ASSESS
                    + feedback_block
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(product_vision)}\n\n"
                    f"USER STORIES ({len(stories)} items):\n"
                    f"{self._format_story_block(stories)}\n\n"
                    "Assess every story: size it directly in Fibonacci points, "
                    "judge each INVEST quality, map dependencies by source_story_id, "
                    "and reshape (rewrite or split) any story that misses an INVEST "
                    "quality. Leave a story unreshaped only when no honest fix helps."
                ),
                include_memory=False,
            ),
        )

    def _assemble_estimation_artifact(
        self,
        stories: List[Dict[str, Any]],
        result: _AssessmentList,
        state: Dict[str, Any],
        feedback: str = "",
    ) -> Dict[str, Any]:
        by_id = {a.source_story_id: a for a in result.assessments}

        assembled: List[Dict[str, Any]] = []
        total_points = 0
        reshape_report: List[str] = []
        human_input: List[str] = []

        for story in stories:
            sid = self._story_id(story)
            fa = by_id.get(sid)
            base = self._carry_fields(story)

            if fa is None:
                # No assessment returned — pass through, flag for human.
                entry = {**base, "story_points": 3,
                         "invest": self._invest_block([], "no assessment returned"),
                         "feasibility": {"is_feasible": True, "feasibility_notes": ""},
                         "dependencies": {"blocked_by": [], "blocks": []},
                         "risks": [], "status": "needs_human_input",
                         "estimation_reasoning": "", "reshape_op": "none", "thought": ""}
                assembled.append(entry)
                total_points += 3
                human_input.append(sid)
                continue

            reshape = fa.reshape
            if reshape and reshape.kind == "split" and len(reshape.children) >= 2:
                # Replace the parent with its children. Each child reports its own
                # six-INVEST read and is gated on it — a child that cannot clear all
                # six surfaces for review, never stamped ready by default.
                reshape_report.append(
                    f"SPLIT {sid} → {len(reshape.children)} children ({reshape.reason})"
                )
                for idx, child in enumerate(reshape.children):
                    sp = _nearest_fibonacci(child.story_points)
                    child_id = f"{sid}.{idx + 1}"
                    child_flags = self._invest_flags(child)
                    child_ready = not child_flags and fa.is_feasible
                    if not child_ready:
                        human_input.append(child_id)
                    assembled.append({
                        **base,
                        "source_story_id": child_id,
                        "parent_story_id": sid,
                        "title": child.title.strip() or base["title"],
                        "description": child.description.strip(),
                        "story_points": sp,
                        "invest": self._invest_block(
                            child_flags, child.invest_notes or f"split child of {sid}", child
                        ),
                        "feasibility": {"is_feasible": fa.is_feasible,
                                        "feasibility_notes": fa.feasibility_notes},
                        "dependencies": {"blocked_by": list(fa.blocked_by), "blocks": list(fa.blocks)},
                        "risks": [r.model_dump() for r in fa.risks],
                        "status": "ready" if child_ready else "needs_human_input",
                        "estimation_reasoning": child.thought.strip(),
                        "reshape_op": "split_child",
                        "acceptance_criteria": [ac.model_dump() for ac in child.acceptance_criteria],
                        "thought": fa.thought,
                    })
                    total_points += sp
                continue

            # Rewrite or no-reshape: one entry, with the analyst's INVEST read.
            description = base["description"]
            reshape_op = "none"
            if reshape and reshape.kind == "rewrite" and reshape.rewritten_description.strip():
                description = reshape.rewritten_description.strip()
                reshape_op = "rewrite"
                reshape_report.append(f"REWRITE {sid} ({reshape.reason})")

            # The bools describe the story as the analyst leaves it (post-rewrite),
            # so the gate is the read itself — not the mere presence of a reshape.
            flags = self._invest_flags(fa)
            invest_pass = not flags
            status = "ready" if (invest_pass and fa.is_feasible) else "needs_human_input"
            if status == "needs_human_input":
                human_input.append(sid)
            sp = _nearest_fibonacci(fa.story_points)

            assembled.append({
                **base,
                "description": description,
                "story_points": sp,
                "invest": self._invest_block(flags, fa.invest_notes, fa),
                "feasibility": {"is_feasible": fa.is_feasible, "feasibility_notes": fa.feasibility_notes},
                "dependencies": {"blocked_by": list(fa.blocked_by), "blocks": list(fa.blocks)},
                "risks": [r.model_dump() for r in fa.risks],
                "status": status,
                "estimation_reasoning": fa.thought,
                "reshape_op": reshape_op,
                "acceptance_criteria": [ac.model_dump() for ac in fa.acceptance_criteria],
                "thought": fa.thought,
            })
            total_points += sp

        for s in assembled:
            inv = s["invest"]
            flags = inv.get("invest_flags") or []
            logger.info(
                "[AnalystAgent]   [%s] sp=%s invest=%s status=%s  %s",
                s["source_story_id"], s["story_points"],
                "PASS" if not flags else f"FAIL[{','.join(flags)}]",
                s["status"], (s.get("title") or "")[:60],
            )

        report_block = (
            "\n\nRESHAPES APPLIED\n  " + "\n  ".join(reshape_report)
            if reshape_report else ""
        )
        human_block = (
            "\n\nNEEDS HUMAN INPUT (no honest reshape):\n  " + ", ".join(human_input)
            if human_input else ""
        )
        analyst_estimation = {
            "id": str(uuid.uuid4()),
            "session_id": state.get("session_id", ""),
            "source_artifacts": ["user_story_draft_approved", "reviewed_product_vision"],
            "estimated_at": datetime.now().isoformat(),
            "stories": assembled,
            "total_story_points": total_points,
            "estimation_stats": {
                "total_stories": len(assembled),
                "reshaped": len(reshape_report),
                "needs_human_input": len(human_input),
                "invest_failures": sum(1 for s in assembled if not s["invest"]["invest_pass"]),
            },
            "notes": f"ASSESSMENT\n  {(result.notes or '').strip() or '(none)'}{report_block}{human_block}",
            **({"rebuild_feedback": feedback} if feedback else {}),
        }
        artifacts = dict(state.get("artifacts") or {})
        artifacts["analyst_estimation"] = analyst_estimation
        return {"artifacts": artifacts}

    # ── AC phase (Phase 2) — deterministic assembly, NO LLM call ─────────────
    #
    # The acceptance criteria were written by the Analyst in step 9c (they live
    # on each story in analyst_estimation). Phase 2 only attaches them to the
    # approved PBIs, assigns AC ids, and sets each PBI's final status — pure
    # data movement, so it is fast and never hangs. The validated_product_backlog
    # stays a distinct artifact (post-Analyst) to compare against the
    # product_backlog (post-Sprint), which carries no AC.

    def _run_ac_generation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        backlog = artifacts.get("product_backlog_approved") or artifacts.get("product_backlog") or {}
        items = backlog.get("items") or []
        if not items:
            return {"errors": ["AnalystAgent: product_backlog has no items."]}

        estimation = artifacts.get("analyst_estimation") or {}
        ac_by_story = {
            self._story_id(s): (s.get("acceptance_criteria") or [])
            for s in (estimation.get("stories") or [])
        }

        final_items: List[Dict[str, Any]] = []
        total_ac = 0
        ready_count = 0
        seq = 1
        for item in items:
            story_id = item.get("source_story_id") or ""
            ac_list: List[Dict[str, Any]] = []
            for ac in ac_by_story.get(story_id, []):
                ac_list.append({
                    "id": f"AC-{seq:03d}",
                    "given": ac.get("given", ""), "when": ac.get("when", ""),
                    "then": ac.get("then", ""), "type": ac.get("type", "happy_path"),
                })
                seq += 1
            total_ac += len(ac_list)

            planning_status = (item.get("planning") or {}).get("status", "needs_refinement")
            ac_status = "ready" if ac_list else "needs_refinement"
            final_status = self._final_status(planning_status, ac_status)
            if final_status == "ready":
                ready_count += 1
            final_items.append({
                **item,
                "quality": {**(item.get("quality") or {}), "acceptance_criteria": ac_list},
                "planning": {**(item.get("planning") or {}), "status": final_status},
            })

        for item in final_items:
            qual = item.get("quality") or {}
            flags = qual.get("invest_flags") or []
            logger.info(
                "[AnalystAgent]   [%s] sp=%s invest=%s ac=%d status=%s  %s",
                item.get("id", "?"), (item.get("estimation") or {}).get("story_points", "?"),
                "PASS" if not flags else f"FAIL[{','.join(flags)}]",
                len(qual.get("acceptance_criteria") or []),
                (item.get("planning") or {}).get("status", "?"),
                (item.get("title") or "")[:60],
            )

        no_ac = [i.get("id") for i in final_items if not (i.get("quality") or {}).get("acceptance_criteria")]
        validated = {
            **backlog,
            "items": final_items,
            "status": "validated",
            "total_items": len(final_items),
            "ready_count": ready_count,
            "refinement_stats": {"total_pbis": len(final_items), "ready_count": ready_count, "total_ac": total_ac},
            "refinement_summary": (
                "ACCEPTANCE CRITERIA (carried from Analyst step 9c; no separate LLM pass)\n"
                f"  {total_ac} AC across {len(final_items)} PBIs; {ready_count} ready."
                + (f"\n  PBIs with no AC: {', '.join(no_ac)}" if no_ac else "")
            ),
            "validated_at": datetime.now().isoformat(),
        }
        artifacts = dict(artifacts)
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

    # ── Helpers (data movement only) ───────────────────────────────────────────

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _story_id(item: Dict[str, Any]) -> str:
        return item.get("source_story_id") or item.get("id") or ""

    @staticmethod
    def _final_status(planning_status: str, ac_status: str) -> str:
        """Precedence (no severity table): human-input > needs_refinement > ready.
        AC quality can only hold a story back, never upgrade past the gate."""
        if planning_status == "needs_human_input":
            return "needs_human_input"
        if ac_status == "needs_refinement" or planning_status == "needs_refinement":
            return "needs_refinement"
        return "ready"

    @staticmethod
    def _invest_flags(fa: Union[_StoryAssessment, _ChildStory]) -> List[str]:
        pairs = (
            ("independent", fa.independent), ("negotiable", fa.negotiable),
            ("valuable", fa.valuable), ("estimable", fa.estimable),
            ("small", fa.small), ("testable", fa.testable),
        )
        return [name for name, ok in pairs if not ok]

    @staticmethod
    def _invest_block(flags: List[str], notes: str,
                      fa: Optional[Union[_StoryAssessment, _ChildStory]] = None) -> Dict[str, Any]:
        criteria = {
            "independent": fa.independent if fa else True,
            "negotiable": fa.negotiable if fa else True,
            "valuable": fa.valuable if fa else True,
            "estimable": fa.estimable if fa else True,
            "small": fa.small if fa else True,
            "testable": fa.testable if fa else True,
        }
        return {
            "invest_pass": len(flags) == 0,
            "invest_flags": flags,
            "invest_notes": notes,
            "criteria": criteria,
        }

    @classmethod
    def _carry_fields(cls, story: Dict[str, Any]) -> Dict[str, Any]:
        """The story fields carried forward into analyst_estimation (the
        authoritative post-reshape set consumed by SprintAgent step 9b)."""
        return {
            "source_story_id": cls._story_id(story),
            "source_requirement_ids": story.get("source_requirement_ids")
            or ([story.get("source_requirement_id")] if story.get("source_requirement_id") else []),
            "type": story.get("type", "functional"),
            "domain": story.get("domain", ""),
            "title": story.get("title", ""),
            "description": story.get("description", ""),
            "requirement_trace": story.get("requirement_trace") or {},
        }

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

    @classmethod
    def _format_story_block(cls, stories: List[Dict[str, Any]]) -> str:
        return "\n".join(cls._json({
            "source_story_id": cls._story_id(s),
            "type": s.get("type"), "title": s.get("title"),
            "description": s.get("description"),
            "requirement_trace": s.get("requirement_trace") or {},
        }) for s in stories)

    @staticmethod
    def _feedback_block(feedback: str, context: str) -> str:
        if not feedback:
            return ""
        return (
            "\n\n" + _FEEDBACK_PREAMBLE
            + "\n\n" + _FEEDBACK_BODY.format(feedback=feedback)
            + f"\nThis applies during {context}.\n"
        )
