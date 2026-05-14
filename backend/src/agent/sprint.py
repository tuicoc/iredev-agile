"""
sprint.py - SprintAgent (Product Owner)

SprintAgent owns two backlog-lane steps:

1. create_user_stories
   Input: requirement_list_approved.items plus compact reviewed Product Vision.
   Output: user_story_draft.

2. build_product_backlog
   Input: user_story_draft plus analyst_estimation.
   Output: product_backlog.

The LLM decides story wording and WSJF component scores. Python copies trace
data, formats prompt inputs, applies split proposals, computes formulas, maps
ids, and assembles artifacts.
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
_MAX_SPLIT_ROUND = 2


# ---------------------------------------------------------------------------
# Pass prompts: how the agent works
# ---------------------------------------------------------------------------

_PASS1_ADDENDUM = """\
TASK: PASS 1 - USER STORY DRAFT

Convert each approved requirement into one compact user story.

Inputs:
- REQUIREMENT TRACES: the only source of backlog scope.
- PRODUCT VISION CONTEXT: read-only orientation for role, entity, step,
  quality concern, and scope vocabulary.
- REVIEWER FEEDBACK: changes requested on a previous backlog, if present.

Flow:
1. Read each requirement trace fully before writing the story.
2. Use requirement_trace.stakeholder as the actor.
3. Rephrase requirement_trace.statement into a capability the actor can own.
4. Derive the benefit from requirement_trace.rationale first, then from
   requirement_trace.acceptance_criteria if the rationale has no clear outcome.
5. Use Product Vision only to keep entity, step, and role wording aligned.
6. For initial stories, source_story_id equals requirement_trace.requirement_id.
7. Write exactly one story for every trace in the input.

Rules:
- Do not create stories from Product Vision alone.
- Do not use the original project description.
- Do not estimate story points.
- Do not assess INVEST.
- Do not propose splits.
- Do not add technologies, UI layouts, vendors, thresholds, or rules absent
  from requirement evidence.
"""

_PASS2_ADDENDUM = """\
TASK: PASS 2 - WSJF PRIORITISATION

Assign BusinessValue, TimeCriticality, and RiskReduction for each story.

Inputs:
- USER STORIES: backlog cards created in Pass 1 or split cards created from
  AnalystAgent proposals.
- ANALYST ESTIMATION: the only source of story points, INVEST flags, risks,
  and dependency evidence.
- REQUIREMENT TRACE: source evidence for priority and stakeholder outcome.
- PRODUCT VISION CONTEXT: read-only orientation for flow and scope impact.

Flow:
1. Anchor BusinessValue and TimeCriticality to requirement priority, rationale,
   and acceptance criteria.
2. Use RiskReduction for uncertainty, hard dependencies, quality concerns,
   threshold gaps, and cross-flow impact visible in evidence.
3. Keep scores consistent for stories in the same domain.
4. Lower score confidence when the source evidence is sparse or a threshold
   still needs human confirmation.
5. Assign unique priority ranks from 1 upward.

Rules:
- Do not change story points.
- Do not reassess INVEST.
- Do not hide hard dependencies inside score rationale; Python will repair
  ranking order from AnalystAgent dependency fields.

Formula:
WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints
Round to two decimals.
"""


# ---------------------------------------------------------------------------
# Schemas: what the artifacts contain
# ---------------------------------------------------------------------------

class RequirementTrace(BaseModel):
    requirement_id: str = Field(description="Original requirement identifier.")
    requirement_type: Literal["functional", "non_functional"] = Field(
        description="Original requirement type."
    )
    stakeholder: str = Field(description="Role that owns the requirement.")
    statement: str = Field(description="Original requirement statement.")
    entity: Optional[str] = Field(default=None, description="Referenced entity.")
    step: Optional[str] = Field(default=None, description="Referenced entity step.")
    aspect: Optional[str] = Field(default=None, description="Requirement aspect.")
    category: Optional[str] = Field(default=None, description="NFR category.")
    concern_theme: Optional[str] = Field(default=None, description="NFR concern theme.")
    entity_refs: List[str] = Field(default_factory=list, description="Additional entity anchors.")
    flow_step_refs: List[str] = Field(default_factory=list, description="Additional step anchors.")
    requires_threshold: bool = Field(
        default=False,
        description="Whether a measurable threshold still needs confirmation.",
    )
    rationale: str = Field(description="Original requirement rationale.")
    acceptance_criteria: List[str] = Field(
        default_factory=list,
        description="Original requirement acceptance criteria.",
    )
    priority: Literal["high", "medium", "low"] = Field(description="Requirement priority.")
    source: str = Field(description="Trace source id.")
    origin: Literal["interview", "baseline", "vision"] = Field(
        description="Requirement origin."
    )
    status: str = Field(default="confirmed", description="Requirement status.")


class SplitTrace(BaseModel):
    parent_story_id: Optional[str] = Field(default=None, description="Parent story id.")
    suffix: Optional[str] = Field(default=None, description="Split suffix.")
    reasoning: Optional[str] = Field(default=None, description="Split proposal rationale.")


class UserStoryItem(BaseModel):
    source_story_id: str = Field(description="Story identifier in the backlog lane.")
    source_requirement_id: str = Field(description="Original requirement identifier.")
    type: Literal["functional", "non_functional"] = Field(description="Backlog item type.")
    domain: str = Field(description="Backlog domain label.")
    title: str = Field(description="Short backlog card title.")
    description: str = Field(description="User story sentence.")
    requirement_trace: RequirementTrace = Field(description="Copied source requirement trace.")
    is_split_child: bool = Field(default=False, description="Whether this story is a split child.")
    split: SplitTrace = Field(default_factory=SplitTrace, description="Split metadata.")
    thought: str = Field(description="Brief mapping note.")


class UserStoryList(BaseModel):
    stories: List[UserStoryItem] = Field(description="Draft user stories.")
    pass_notes: str = Field(description="Reviewer-facing pass summary.")


class PrioritizedStoryItem(BaseModel):
    source_story_id: str = Field(description="Story identifier being scored.")
    business_value: int = Field(ge=1, le=10, description="Business value score.")
    time_criticality: int = Field(ge=1, le=10, description="Time criticality score.")
    risk_reduction: int = Field(ge=1, le=10, description="Risk reduction score.")
    wsjf_score: float = Field(description="Weighted Shortest Job First score.")
    priority_rank: int = Field(description="Initial priority rank.")
    thought: str = Field(description="Brief scoring rationale.")


class PrioritizedBacklog(BaseModel):
    stories: List[PrioritizedStoryItem] = Field(description="Prioritized stories.")
    pass_notes: str = Field(description="Reviewer-facing prioritization summary.")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class SprintAgent(BaseAgent):
    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="sprint_agent")

    def _register_tools(self) -> None:
        """SprintAgent uses structured extraction only."""

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {}

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
            split_round,
            split_round + 1,
            len(new_stories),
        )
        return {"artifacts": updated_artifacts, "split_round": split_round + 1}

    def process_backlog(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        feedback = (state.get("product_backlog_feedback") or "").strip()
        if "product_backlog" in artifacts and not feedback:
            logger.warning("[SprintAgent] product_backlog already exists.")
            return {}
        return self._build_product_backlog(state)

    # ------------------------------------------------------------------
    # Step 9a
    # ------------------------------------------------------------------

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
            )
            != "out_of_scope"
        ]
        if not traces:
            return {"errors": ["SprintAgent: no active approved requirements found."]}

        product_vision = self._compact_product_vision(state)

        try:
            story_list = self._pass1_create_stories(traces, product_vision, feedback)
        except Exception as exc:
            logger.error("[SprintAgent] Story creation failed: %s", exc, exc_info=True)
            return {"errors": [f"SprintAgent story creation error: {exc}"]}

        trace_by_id = {t["requirement_id"]: t for t in traces}
        serialised_stories: List[Dict[str, Any]] = []
        for story in story_list.stories:
            story_dict = story.model_dump()
            source_requirement_id = (
                story_dict.get("source_requirement_id")
                or story_dict.get("source_story_id")
                or story_dict.get("requirement_trace", {}).get("requirement_id")
            )
            trace = trace_by_id.get(source_requirement_id) or story_dict.get("requirement_trace") or {}
            story_dict["source_requirement_id"] = trace.get("requirement_id", source_requirement_id)
            story_dict["source_story_id"] = story_dict.get("source_story_id") or story_dict["source_requirement_id"]
            story_dict["type"] = trace.get("requirement_type", story_dict.get("type", "functional"))
            story_dict["domain"] = story_dict.get("domain") or self._domain_from_trace(trace)
            story_dict["requirement_trace"] = trace
            story_dict["is_split_child"] = False
            story_dict["split"] = {"parent_story_id": None, "suffix": None, "reasoning": None}
            serialised_stories.append(story_dict)

        artifacts["user_story_draft"] = {
            "id": str(uuid.uuid4()),
            "session_id": state.get("session_id", ""),
            "source_artifacts": ["requirement_list_approved", "reviewed_product_vision"],
            "created_at": datetime.now().isoformat(),
            "stories": serialised_stories,
            "total_stories": len(serialised_stories),
            "pass_notes": story_list.pass_notes,
            **({"rebuild_feedback": feedback} if feedback else {}),
        }
        return {"artifacts": artifacts, "split_round": 0}

    def _pass1_create_stories(
        self,
        requirement_traces: List[Dict[str, Any]],
        product_vision: Dict[str, Any],
        feedback: str = "",
    ) -> UserStoryList:
        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS1_ADDENDUM
            + self._feedback_block(feedback, "user story creation")
        )
        user_prompt = (
            "PRODUCT VISION CONTEXT:\n"
            f"{json.dumps(product_vision, indent=2, ensure_ascii=False)}\n\n"
            f"REQUIREMENT TRACES ({len(requirement_traces)} items):\n"
            f"{self._format_requirement_traces(requirement_traces)}\n\n"
            "Return one draft user story per requirement trace."
        )
        return self.extract_structured(
            schema=UserStoryList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            include_memory=False,
        )

    # ------------------------------------------------------------------
    # Step 9b
    # ------------------------------------------------------------------

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
            prioritized = self._pass2_wsjf(stories, est_stories, product_vision, feedback)
            return self._pass3_assembly(
                prioritized=prioritized,
                stories=stories,
                est_stories=est_stories,
                state=state,
                feedback=feedback,
                split_round=split_round,
            )
        except Exception as exc:
            logger.error("[SprintAgent] Backlog assembly failed: %s", exc, exc_info=True)
            return {"errors": [f"SprintAgent assembly error: {exc}"]}

    def _pass2_wsjf(
        self,
        stories: List[Dict[str, Any]],
        est_stories: List[Dict[str, Any]],
        product_vision: Dict[str, Any],
        feedback: str = "",
    ) -> PrioritizedBacklog:
        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS2_ADDENDUM
            + self._feedback_block(feedback, "WSJF prioritisation")
        )
        est_lookup = {self._story_id(s): s for s in est_stories}
        user_prompt = (
            "PRODUCT VISION CONTEXT:\n"
            f"{json.dumps(product_vision, indent=2, ensure_ascii=False)}\n\n"
            f"STORIES WITH ANALYST ESTIMATION ({len(stories)} items):\n"
            f"{self._format_stories_with_estimation(stories, est_lookup)}\n\n"
            "Assign scores and unique initial priority ranks for every story."
        )
        return self.extract_structured(
            schema=PrioritizedBacklog,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            include_memory=False,
        )

    def _pass3_assembly(
        self,
        prioritized: PrioritizedBacklog,
        stories: List[Dict[str, Any]],
        est_stories: List[Dict[str, Any]],
        state: Dict[str, Any],
        feedback: str = "",
        split_round: int = 0,
    ) -> Dict[str, Any]:
        story_lookup = {self._story_id(s): s for s in stories}
        est_lookup = {self._story_id(s): s for s in est_stories}
        wsjf_lookup = {p.source_story_id: p for p in prioritized.stories}

        adjusted_ranks = {
            p.source_story_id: float(p.priority_rank)
            for p in prioritized.stories
        }
        for est in est_stories:
            story_id = self._story_id(est)
            for blocker_id in (est.get("dependencies") or {}).get("blocked_by") or []:
                if story_id not in adjusted_ranks or blocker_id not in adjusted_ranks:
                    continue
                if adjusted_ranks[story_id] < adjusted_ranks[blocker_id]:
                    adjusted_ranks[blocker_id] = adjusted_ranks[story_id] - 0.5

        ordered_ids = sorted(adjusted_ranks.keys(), key=lambda k: adjusted_ranks[k])
        rank_reassign = {story_id: i + 1 for i, story_id in enumerate(ordered_ids)}

        items: List[Dict[str, Any]] = []
        format_warnings: List[str] = []
        fib_warnings: List[str] = []
        invest_warnings: List[str] = []
        oversized: List[str] = []
        seq = 1
        parent_seq: Dict[str, int] = {}

        for story_id in ordered_ids:
            story = story_lookup.get(story_id)
            est = est_lookup.get(story_id)
            wsjf = wsjf_lookup.get(story_id)
            if not story or not est or not wsjf:
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

            est_data = est.get("estimation") or {}
            sp = est_data.get("story_points", 3)
            if sp not in _FIBONACCI:
                snapped = min(_FIBONACCI, key=lambda f: abs(f - sp))
                fib_warnings.append(f"{pbi_id} [{story_id}]: story_points {sp} -> {snapped}.")
                sp = snapped

            bv = wsjf.business_value
            tc = wsjf.time_criticality
            rr = wsjf.risk_reduction
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
            tags = self._tags_for_story(story)

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
                    "priority_rank": rank_reassign.get(story_id, len(items) + 1),
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
                    "tags": tags,
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
                },
            })

        story_to_pbi = {item["source_story_id"]: item["id"] for item in items}
        for item in items:
            item["dependencies"] = {
                "blocked_by": [
                    story_to_pbi.get(story_id, story_id)
                    for story_id in item.pop("_raw_blocked_by", [])
                ],
                "blocks": [
                    story_to_pbi.get(story_id, story_id)
                    for story_id in item.pop("_raw_blocks", [])
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
            "pass_notes": prioritized.pass_notes,
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
        raw_origin = requirement.get("origin") or requirement.get("sourcestream") or "interview"
        origin_map = {
            "interview": "interview",
            "tension": "interview",
            "baseline": "baseline",
            "vision": "vision",
            "productvision": "vision",
            "product_vision": "vision",
        }
        origin = origin_map.get(str(raw_origin).lower().replace("-", "_"), "interview")
        return {
            "requirement_id": requirement.get("id") or requirement.get("req_id") or "",
            "requirement_type": req_type,
            "stakeholder": requirement.get("stakeholder") or requirement.get("role") or "",
            "statement": requirement.get("statement") or requirement.get("description") or "",
            "entity": requirement.get("entity") or requirement.get("entityref"),
            "step": requirement.get("step") or requirement.get("stepref"),
            "aspect": requirement.get("aspect"),
            "category": requirement.get("category"),
            "concern_theme": requirement.get("concern_theme"),
            "entity_refs": requirement.get("entity_refs") or [],
            "flow_step_refs": requirement.get("flow_step_refs") or [],
            "requires_threshold": bool(requirement.get("requires_threshold", False)),
            "rationale": requirement.get("rationale") or "",
            "acceptance_criteria": requirement.get("acceptance_criteria")
            or requirement.get("acceptancecriteria")
            or [],
            "priority": priority,
            "source": requirement.get("source") or requirement.get("sourceelicitationid") or "",
            "origin": origin,
            "status": requirement.get("status") or "confirmed",
        }

    @staticmethod
    def _normalise_requirement_type(value: Any) -> str:
        text = str(value or "").lower().replace("-", "_")
        if text in {"nonfunctional", "non_functional"}:
            return "non_functional"
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
            "flow": vision.get("flow") or vision.get("entity_flow") or {},
            "roles": vision.get("roles") or vision.get("stakeholders") or [],
            "nfr_concerns": vision.get("nfr_concerns") or [],
            "scope": vision.get("scope") or vision.get("out_of_scope") or [],
        }

    @staticmethod
    def _domain_from_trace(trace: Dict[str, Any]) -> str:
        return (
            trace.get("entity")
            or trace.get("category")
            or trace.get("aspect")
            or "General"
        )

    @classmethod
    def _format_requirement_traces(cls, traces: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for trace in traces:
            lines.append(
                json.dumps(
                    {
                        **trace,
                        "suggested_domain": cls._domain_from_trace(trace),
                    },
                    ensure_ascii=False,
                )
            )
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
            lines.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(lines)

    @staticmethod
    def _valid_story_format(description: str) -> bool:
        lower = description.lower()
        return (
            (lower.startswith("as a ") or lower.startswith("as an "))
            and ", i can " in lower
            and ", so that " in lower
        )

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
        trace = story.get("requirement_trace") or {}
        aspect = (trace.get("aspect") or "").strip()
        if aspect:
            tags.append(aspect.lower().replace(" ", "_"))
        return tags

    @staticmethod
    def _feedback_block(feedback: str, context: str) -> str:
        if not feedback:
            return ""
        return (
            "\n\nREVIEWER FEEDBACK - previous backlog was rejected:\n"
            f"{feedback}\n"
            f"Address this feedback during {context}.\n"
        )
