"""
analyst.py - AnalystAgent (Technical Lead / AC Specialist)

AnalystAgent owns two backlog-lane phases:

1. analyst_estimation_turn
   Input: user_story_draft plus compact reviewed Product Vision.
   Output: analyst_estimation.

2. analyst_turn
   Input: product_backlog_approved plus compact reviewed Product Vision.
   Output: validated_product_backlog.

The LLM decides feasibility, INVEST, dependencies, risk, estimates, split
proposals, and acceptance criteria. Python copies trace data, carries fields
forward, normalizes Fibonacci drift, and assembles artifacts.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseAgent

logger = logging.getLogger(__name__)

_FIBONACCI = {1, 2, 3, 5, 8, 13, 21}
_SPLIT_THRESHOLD = 8


# ---------------------------------------------------------------------------
# Pass prompts: how the agent works
# ---------------------------------------------------------------------------

_PASS1_ADDENDUM = """\
TASK: PASS 1 - FEASIBILITY, INVEST, DEPENDENCIES, RISKS, SPLIT PRESSURE

Review each story before estimation.

Inputs:
- USER STORY: title, description, domain, and split metadata.
- REQUIREMENT TRACE: source evidence copied from the approved Requirement List.
- PRODUCT VISION CONTEXT: read-only orientation for flow, role, quality concern,
  and scope vocabulary.

Flow:
1. Check feasibility from story plus requirement trace. Mark infeasible only
   when implementation cannot reasonably begin without missing or conflicting
   information.
2. Evaluate INVEST explicitly: independent, negotiable, valuable, estimable,
   small, testable.
3. Record hard dependencies using source_story_id values from the current draft.
4. Identify technical risks supported by requirement trace or Product Vision
   context.
5. Propose split slices when the story combines several actions, roles,
   conditions, acceptance criteria, or cross-flow concerns.

Rules:
- Do not create new requirements.
- Do not use the original project description.
- Product Vision can explain context but cannot add scope.
- invest_flags lists only failed INVEST criteria.
- Split proposals are suggestions for SprintAgent; do not create child stories.
"""

_PASS2_ADDENDUM = """\
TASK: PASS 2 - FIBONACCI ESTIMATION

Assign effort estimates to every story.

Inputs:
- USER STORY and REQUIREMENT TRACE.
- PASS 1 ASSESSMENT.
- PRODUCT VISION CONTEXT.

Flow:
1. Score Complexity from structural difficulty and interacting parts.
2. Score Effort from implementation surface.
3. Score Uncertainty from ambiguity, threshold gaps, dependency risk, and
   external unknowns.
4. Map the sum to Fibonacci:
   3-4 -> 1, 5-6 -> 2, 7-8 -> 3, 9-10 -> 5,
   11-12 -> 8, 13-14 -> 13, 15 -> 21.
5. If story_points exceeds 8, set needs_split=true.
6. If story_points equals 8, set split_warning when the story is near the
   threshold but still deliverable.

Rules:
- Story points are assigned only here.
- Do not change story wording.
- Do not add domain facts absent from trace/context.
"""

_PASS3_ADDENDUM = """\
TASK: PASS 3 - ACCEPTANCE CRITERIA GENERATION

Write Given-When-Then acceptance criteria for approved PBIs.

Inputs:
- PRODUCT BACKLOG ITEM: story, estimation, planning status, and INVEST flags.
- REQUIREMENT TRACE: original statement, rationale, acceptance criteria,
  priority, source, entity, step, aspect, and threshold flag.
- PRODUCT VISION CONTEXT: read-only flow and scope context.

Flow:
1. Start from requirement_trace.acceptance_criteria and formalize them into
   Given-When-Then triples.
2. Use requirement_trace.statement, entity, step, aspect, and rationale to add
   coverage for happy path, edge cases, and error cases.
3. Use the user story only to confirm actor, capability, and benefit coverage.
4. For non-functional PBIs, use measurable thresholds only when they are present
   in requirement evidence. If a threshold is required but absent, keep the PBI
   needs_refinement and explain the gap in thought.
5. For split children, scope AC to that child story while keeping the original
   requirement trace visible.

Rules:
- Write 2-5 criteria per PBI when evidence supports them.
- Include at least one happy_path criterion.
- Add edge_case and error_case criteria when the requirement evidence supports
  boundary or failure behavior.
- Each then clause has one verifiable assertion.
- Do not use vague words such as easy, clean, intuitive, user-friendly,
  beautiful, simple, appropriate, fast, quickly, seamlessly, properly,
  correctly without a threshold, reasonable, adequate, or sufficient.
- Do not invent thresholds, technologies, policies, or implementation designs.
"""


# ---------------------------------------------------------------------------
# Schemas: what the artifacts contain
# ---------------------------------------------------------------------------

class SplitProposal(BaseModel):
    title: str = Field(description="Proposed split story title.")
    capability: str = Field(description="Proposed split story capability.")
    reasoning: str = Field(description="Reason this split is useful.")


class TechnicalRisk(BaseModel):
    category: Literal["performance", "security", "integration", "data", "unknown"] = Field(
        description="Risk category."
    )
    description: str = Field(description="Risk description.")
    level: Literal["low", "medium", "high", "critical"] = Field(description="Risk level.")
    mitigation: str = Field(description="Risk mitigation note.")


class StoryFeasibilityAssessment(BaseModel):
    source_story_id: str = Field(description="Story identifier being assessed.")
    is_feasible: bool = Field(description="Whether implementation can reasonably begin.")
    feasibility_notes: str = Field(description="Feasibility note.")
    independent: bool = Field(description="INVEST independent result.")
    negotiable: bool = Field(description="INVEST negotiable result.")
    valuable: bool = Field(description="INVEST valuable result.")
    estimable: bool = Field(description="INVEST estimable result.")
    small: bool = Field(description="INVEST small result.")
    testable: bool = Field(description="INVEST testable result.")
    invest_flags: List[str] = Field(description="Failed INVEST criteria.")
    invest_notes: str = Field(description="INVEST assessment note.")
    blocked_by: List[str] = Field(default_factory=list, description="Blocking story ids.")
    blocks: List[str] = Field(default_factory=list, description="Blocked story ids.")
    split_proposals: List[SplitProposal] = Field(
        default_factory=list,
        description="Proposed splits.",
    )
    risks: List[TechnicalRisk] = Field(default_factory=list, description="Technical risks.")
    thought: str = Field(description="Brief assessment summary.")


class FeasibilityAssessmentList(BaseModel):
    assessments: List[StoryFeasibilityAssessment] = Field(description="Story assessments.")
    pass_notes: str = Field(description="Reviewer-facing assessment summary.")


class StoryEstimation(BaseModel):
    source_story_id: str = Field(description="Story identifier being estimated.")
    complexity: int = Field(ge=1, le=5, description="Complexity score.")
    effort: int = Field(ge=1, le=5, description="Effort score.")
    uncertainty: int = Field(ge=1, le=5, description="Uncertainty score.")
    story_points: int = Field(description="Fibonacci story point estimate.")
    needs_split: bool = Field(description="Whether the story exceeds split threshold.")
    split_warning: str = Field(default="", description="Split advisory note.")
    reasoning: str = Field(description="Estimation rationale.")


class EstimationList(BaseModel):
    estimations: List[StoryEstimation] = Field(description="Story estimates.")
    has_pending_splits: bool = Field(description="Whether any story needs a split.")
    pass_notes: str = Field(description="Reviewer-facing estimation summary.")


class AcceptanceCriterion(BaseModel):
    id: str = Field(description="Acceptance criterion id.")
    given: str = Field(description="Given condition.")
    when: str = Field(description="When event.")
    then: str = Field(description="Then outcome.")
    type: Literal["happy_path", "edge_case", "error_case"] = Field(
        description="Acceptance criterion type."
    )


class PbiWithAC(BaseModel):
    pbi_id: str = Field(description="PBI identifier.")
    source_story_id: str = Field(description="Story identifier.")
    acceptance_criteria: List[AcceptanceCriterion] = Field(
        description="Acceptance criteria for the PBI."
    )
    status: Literal["ready", "needs_refinement"] = Field(description="PBI refinement status.")
    thought: str = Field(description="Brief AC generation note.")


class AcGenerationList(BaseModel):
    pbis: List[PbiWithAC] = Field(description="PBIs with generated AC.")
    pass_notes: str = Field(description="Reviewer-facing AC generation summary.")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AnalystAgent(BaseAgent):
    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="analyst")

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

    # ------------------------------------------------------------------
    # Estimation phase
    # ------------------------------------------------------------------

    def _run_estimation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        draft = artifacts.get("user_story_draft") or {}
        stories = draft.get("stories") or []
        feedback = (state.get("product_backlog_feedback") or "").strip()
        split_round = state.get("split_round", 0)
        if not stories:
            return {"errors": ["AnalystAgent: user_story_draft has no stories."]}

        product_vision = self._compact_product_vision(state)

        try:
            feasibility = self._pass1_feasibility(stories, product_vision, feedback)
            estimation = self._pass2_estimation(stories, feasibility, product_vision, feedback)
            return self._assemble_estimation_artifact(
                stories=stories,
                feasibility=feasibility,
                estimation=estimation,
                state=state,
                feedback=feedback,
                split_round=split_round,
            )
        except Exception as exc:
            logger.error("[AnalystAgent] Estimation failed: %s", exc, exc_info=True)
            return {"errors": [f"AnalystAgent estimation error: {exc}"]}

    def _pass1_feasibility(
        self,
        stories: List[Dict[str, Any]],
        product_vision: Dict[str, Any],
        feedback: str = "",
    ) -> FeasibilityAssessmentList:
        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS1_ADDENDUM
            + self._feedback_block(feedback, "feasibility and INVEST assessment")
        )
        user_prompt = (
            "PRODUCT VISION CONTEXT:\n"
            f"{json.dumps(product_vision, indent=2, ensure_ascii=False)}\n\n"
            f"USER STORIES TO ASSESS ({len(stories)} stories):\n"
            f"{self._format_story_block(stories)}\n\n"
            "Assess every story and use current source_story_id values for dependencies."
        )
        return self.extract_structured(
            schema=FeasibilityAssessmentList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            include_memory=False,
        )

    def _pass2_estimation(
        self,
        stories: List[Dict[str, Any]],
        feasibility: FeasibilityAssessmentList,
        product_vision: Dict[str, Any],
        feedback: str = "",
    ) -> EstimationList:
        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS2_ADDENDUM
            + self._feedback_block(feedback, "Fibonacci estimation")
        )
        user_prompt = (
            "PRODUCT VISION CONTEXT:\n"
            f"{json.dumps(product_vision, indent=2, ensure_ascii=False)}\n\n"
            f"USER STORIES ({len(stories)} stories):\n"
            f"{self._format_story_block(stories)}\n\n"
            "PASS 1 ASSESSMENT:\n"
            f"{self._format_feasibility_block(feasibility)}\n\n"
            f"Pass 1 notes: {feasibility.pass_notes}\n\n"
            "Estimate every story in the same order."
        )
        return self.extract_structured(
            schema=EstimationList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            include_memory=False,
        )

    def _assemble_estimation_artifact(
        self,
        stories: List[Dict[str, Any]],
        feasibility: FeasibilityAssessmentList,
        estimation: EstimationList,
        state: Dict[str, Any],
        feedback: str = "",
        split_round: int = 0,
    ) -> Dict[str, Any]:
        fa_by_id = {a.source_story_id: a for a in feasibility.assessments}
        est_by_id = {e.source_story_id: e for e in estimation.estimations}

        assembled: List[Dict[str, Any]] = []
        total_points = 0
        split_count = 0

        for story in stories:
            story_id = self._story_id(story)
            fa = fa_by_id.get(story_id)
            est = est_by_id.get(story_id)

            sp = est.story_points if est else 3
            if sp not in _FIBONACCI:
                sp = min(_FIBONACCI, key=lambda f: abs(f - sp))

            invest_flags = list(fa.invest_flags if fa else [])
            needs_split = bool(est and est.needs_split) or sp > _SPLIT_THRESHOLD
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
                    "blocked_by": fa.blocked_by if fa else [],
                    "blocks": fa.blocks if fa else [],
                },
                "split_proposals": [
                    proposal.model_dump()
                    for proposal in (fa.split_proposals if fa else [])
                ],
                "needs_split": actionable_split,
                "risks": [risk.model_dump() for risk in (fa.risks if fa else [])],
                "estimation": {
                    "complexity": est.complexity if est else 2,
                    "effort": est.effort if est else 2,
                    "uncertainty": est.uncertainty if est else 2,
                    "story_points": sp,
                    "reasoning": est.reasoning if est else "",
                    "split_warning": est.split_warning if est else "",
                },
            })
            total_points += sp

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
            "pass_notes": estimation.pass_notes,
            **({"rebuild_feedback": feedback} if feedback else {}),
        }
        artifacts = dict(state.get("artifacts") or {})
        artifacts["analyst_estimation"] = analyst_estimation
        return {"artifacts": artifacts, "split_round": split_round}

    # ------------------------------------------------------------------
    # AC phase
    # ------------------------------------------------------------------

    def _run_ac_generation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        backlog = artifacts.get("product_backlog_approved") or artifacts.get("product_backlog") or {}
        items = backlog.get("items") or []
        feedback = (state.get("analyst_feedback") or "").strip()
        if not items:
            return {"errors": ["AnalystAgent: product_backlog has no items."]}

        product_vision = self._compact_product_vision(state)

        try:
            ac_result = self._pass3_ac_generation(items, product_vision, feedback)
            return self._assemble_validated_backlog(ac_result, backlog, state, feedback)
        except Exception as exc:
            logger.error("[AnalystAgent] AC generation failed: %s", exc, exc_info=True)
            return {"errors": [f"AnalystAgent AC generation error: {exc}"]}

    def _pass3_ac_generation(
        self,
        items: List[Dict[str, Any]],
        product_vision: Dict[str, Any],
        feedback: str = "",
    ) -> AcGenerationList:
        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS3_ADDENDUM
            + self._feedback_block(feedback, "acceptance criteria generation")
        )
        user_prompt = (
            "PRODUCT VISION CONTEXT:\n"
            f"{json.dumps(product_vision, indent=2, ensure_ascii=False)}\n\n"
            f"PRODUCT BACKLOG ITEMS ({len(items)} PBIs):\n"
            f"{self._format_pbi_block_for_ac(items)}\n\n"
            "Write acceptance criteria for every PBI in the same order."
        )
        return self.extract_structured(
            schema=AcGenerationList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            include_memory=False,
        )

    def _assemble_validated_backlog(
        self,
        ac_result: AcGenerationList,
        source_pb: Dict[str, Any],
        state: Dict[str, Any],
        feedback: str = "",
    ) -> Dict[str, Any]:
        ac_by_pbi = {p.pbi_id: p for p in ac_result.pbis}

        final_items: List[Dict[str, Any]] = []
        total_ac = 0
        ready_count = 0
        for item in source_pb.get("items") or []:
            pbi_id = item.get("id", "")
            ac_entry = ac_by_pbi.get(pbi_id)
            ac_list = [
                ac.model_dump()
                for ac in (ac_entry.acceptance_criteria if ac_entry else [])
            ]
            total_ac += len(ac_list)
            status = ac_entry.status if ac_entry else "needs_refinement"
            if status == "ready":
                ready_count += 1
            final_items.append({
                **item,
                "quality": {
                    **(item.get("quality") or {}),
                    "acceptance_criteria": ac_list,
                },
                "planning": {
                    **(item.get("planning") or {}),
                    "status": status,
                },
                "analysis": {
                    **(item.get("analysis") or {}),
                    "ac_generation_note": ac_entry.thought if ac_entry else "",
                },
            })

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
            "refinement_summary": ac_result.pass_notes,
            "validated_at": datetime.now().isoformat(),
            **({"rebuild_feedback": feedback} if feedback else {}),
        }
        artifacts = dict(state.get("artifacts") or {})
        artifacts["validated_product_backlog"] = validated
        return {"artifacts": artifacts}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
            "flow": vision.get("flow") or vision.get("entity_flow") or {},
            "roles": vision.get("roles") or vision.get("stakeholders") or [],
            "nfr_concerns": vision.get("nfr_concerns") or [],
            "scope": vision.get("scope") or vision.get("out_of_scope") or [],
        }

    @classmethod
    def _format_story_block(cls, stories: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for story in stories:
            block = {
                "source_story_id": cls._story_id(story),
                "source_requirement_id": story.get("source_requirement_id"),
                "type": story.get("type"),
                "domain": story.get("domain"),
                "title": story.get("title"),
                "description": story.get("description"),
                "split": story.get("split") or {},
                "requirement_trace": story.get("requirement_trace") or {},
            }
            lines.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(lines)

    @staticmethod
    def _format_feasibility_block(feasibility: FeasibilityAssessmentList) -> str:
        lines: List[str] = []
        for assessment in feasibility.assessments:
            block = {
                "source_story_id": assessment.source_story_id,
                "is_feasible": assessment.is_feasible,
                "invest_flags": assessment.invest_flags,
                "blocked_by": assessment.blocked_by,
                "blocks": assessment.blocks,
                "split_proposals": [p.model_dump() for p in assessment.split_proposals],
                "risks": [r.model_dump() for r in assessment.risks],
                "thought": assessment.thought,
            }
            lines.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(lines)

    @staticmethod
    def _format_pbi_block_for_ac(items: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for item in items:
            block = {
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
                "planning": item.get("planning") or {},
                "quality": {
                    "invest_pass": (item.get("quality") or {}).get("invest_pass"),
                    "invest_flags": (item.get("quality") or {}).get("invest_flags") or [],
                },
                "analysis": item.get("analysis") or {},
            }
            lines.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(lines)

    @staticmethod
    def _feedback_block(feedback: str, context: str) -> str:
        if not feedback:
            return ""
        return (
            "\n\nREVIEWER FEEDBACK - previous output was rejected:\n"
            f"{feedback}\n"
            f"Address this feedback during {context}.\n"
        )
