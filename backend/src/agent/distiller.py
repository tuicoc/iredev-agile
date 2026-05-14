"""
distiller.py - DistillerAgent

DistillerAgent turns reviewed interview evidence plus the reviewed Product
Vision into a Requirement List.

Python only passes structured data between extraction calls and stores the final
artifact. Requirement judgment, baseline addition, and conflict judgment stay
inside structured prompts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseAgent

logger = logging.getLogger(__name__)


class Requirement(BaseModel):
    id: str = Field(
        description="Requirement id. Use FR-NNN, NFR-NNN, or OOS-NNN."
    )
    type: Literal["functional", "non_functional", "out_of_scope"] = Field(
        description="Requirement class."
    )
    stakeholder: str = Field(
        description=(
            "Primary role that owns the requirement. Use Project Team for baseline "
            "or scope-boundary items that do not belong to one stakeholder."
        )
    )
    statement: str = Field(
        description=(
            "Atomic requirement statement. For out_of_scope items, state the excluded "
            "capability as a product boundary."
        )
    )
    entity: Optional[str] = Field(
        default=None,
        description="Entity this requirement touches, or null when not applicable."
    )
    step: Optional[str] = Field(
        default=None,
        description="Entity step this requirement touches, or null when not applicable."
    )
    aspect: Optional[str] = Field(
        default=None,
        description="Agenda aspect behind the requirement, or null for baseline/scope items."
    )
    category: Optional[str] = Field(
        default=None,
        description=(
            "NFR category when this is a non-functional requirement traced from a "
            "quality concern; otherwise null."
        ),
    )
    concern_theme: Optional[str] = Field(
        default=None,
        description=(
            "NFR concern theme when this requirement operationalizes a Product Vision "
            "concern; otherwise null."
        ),
    )
    entity_refs: List[str] = Field(
        default_factory=list,
        description="Additional entity trace anchors, mainly for NFR concern items."
    )
    flow_step_refs: List[str] = Field(
        default_factory=list,
        description="Additional flow-step trace anchors, mainly for NFR concern items."
    )
    requires_threshold: bool = Field(
        default=False,
        description=(
            "True when the requirement is a qualitative NFR that still needs a human "
            "reviewer to confirm a measurable threshold."
        ),
    )
    rationale: str = Field(
        description="Source-grounded explanation of why this requirement exists."
    )
    acceptance_criteria: List[str] = Field(
        default_factory=list,
        description=(
            "Objective checks that would verify the requirement. Must be non-empty "
            "for functional and non-functional requirements; keep empty only for "
            "out_of_scope items."
        )
    )
    priority: Literal["high", "medium", "low"] = Field(
        description="Reviewer-friendly delivery importance."
    )
    source: str = Field(
        description="Trace id such as EL-NNN, BL-NNN, or OOS-NN."
    )
    origin: Literal["interview", "baseline", "vision"] = Field(
        description="Where this requirement came from."
    )
    status: Literal["confirmed", "excluded"] = Field(
        description="confirmed for implementable items; excluded for out_of_scope boundaries."
    )


class Conflict(BaseModel):
    id: str = Field(description="Conflict id in CF-NN format.")
    kind: Literal["clash", "unclear"] = Field(
        description=(
            "clash when two requirements cannot both hold in the same scope; "
            "unclear when dialogue exposes a collision but the governing rule is still missing."
        )
    )
    left: str = Field(description="Requirement id on one side of the conflict.")
    right: str = Field(description="Requirement id on the other side of the conflict.")
    scope: str = Field(
        description="Shared entity, step, condition, or actor scope where the conflict appears."
    )
    issue: str = Field(
        description="Why the two requirements remain incompatible or unresolved."
    )
    paths: List[str] = Field(
        description="Concrete reviewer choices that could resolve the conflict."
    )
    refs: List[str] = Field(
        description="Interview or agenda trace ids that support this conflict."
    )


class RequirementList(BaseModel):
    notes: str = Field(
        description="Reviewer-facing synthesis note covering all passes."
    )
    items: List[Requirement] = Field(
        description="Final requirement items ready for human review."
    )
    conflicts: List[Conflict] = Field(
        default_factory=list,
        description="Only unresolved conflicts that still require human judgment."
    )
    gaps: List[str] = Field(
        default_factory=list,
        description="Coverage notes that should remain visible but do not block review."
    )


class Draft(BaseModel):
    notes: str
    items: List[Requirement]


class FinalPass(BaseModel):
    notes: str
    items: List[Requirement]
    conflicts: List[Conflict] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)


_FIELD_GUIDE = """\
FIELD GUIDE
- id: FR-NNN, NFR-NNN, or OOS-NNN.
- type: functional, non_functional, out_of_scope.
- stakeholder: concrete role or Project Team.
- statement: one atomic rule or excluded capability.
- entity, step, aspect: fill only when the source evidence supports them.
- category, concern_theme: fill for NFRs that operationalize concern items.
- entity_refs, flow_step_refs: preserve additional anchors when the source
  concern or interview item names them.
- requires_threshold: true only for qualitative NFRs that lack a defensible
  measurable threshold in the evidence.
- rationale: cite the actual source evidence, not a generic benefit.
- acceptance_criteria: objective verification checks, empty only for out_of_scope.
- priority: delivery importance, not confidence.
- source: trace id from interview, baseline, or scope. Multiple atomic
  requirements may share the same interview source id.
- origin: interview, baseline, or vision.
- status: confirmed or excluded.
"""

_PASS1 = """\
PASS 1 - INTERVIEW REQUIREMENTS

Task:
Read the reviewed interview items and emit requirement candidates only when the
dialogue or the settled rule gives enough evidence to do so without guessing.

Rules:
1. Read the full interview item: signals, dialogue/talk, settled rule, risk,
   kind, aspect, entity, step, and role. The settled rule is a closure summary,
   not a one-to-one requirement container.
2. Use signals as the preferred atomic evidence source. Use dialogue/talk to
   recover important stakeholder-stated facts that are missing from signals.
   Use the settled rule to confirm closure and wording, not to compress facts.
3. One interview record may produce zero, one, or many requirements. If the
   signals, rule, or dialogue contain multiple independent conditions, business
   limits, permissions, dependencies, exceptions, actor obligations, or distinct
   behaviors, split them into multiple atomic requirement statements. Do not
   compress an AND-chain into one requirement.
4. Keep ids sequential as FR-NNN or NFR-NNN; do not use suffixes.
   Multiple requirements may share the same EL source id when they came from
   the same interview record.
5. When evidence is still incomplete, do not create a requirement. Note the gap.
6. For conflict agenda items:
   - if the interview clarified precedence, scope split, or escalation, emit the
     clarified atomic requirement(s);
   - if the ambiguity remains unresolved, preserve the evidence for Pass 3 by
     writing a precise gap note rather than inventing a rule.
7. For concern agenda items, operationalize the softgoal into a non-functional
   requirement only when the dialogue provides enough evidence:
   - use type=non_functional and id=NFR-NNN;
   - preserve concern_category in category and concern_theme in concern_theme;
   - preserve entity, step, aspect, and source from the interview item;
   - include the item entity in entity_refs and the item step in flow_step_refs
     when present;
   - use the settled rule field as the quality statement when present;
   - if the stakeholder gave a threshold, magnitude, frequency, or condition,
     write it into the statement and acceptance criteria;
   - if the stakeholder gave only a defensible qualitative boundary, write the
     strongest qualitative NFR and set requires_threshold=true;
   - do not invent a number, SLA, technology, or test criterion that was not in
     the interview evidence.
8. Use item risk only as trace context. If the interview answer resolves or
   bounds the risk, mention that in rationale. If the risk remains unresolved,
   write a gap instead of inventing a requirement.
9. Do not copy quality thresholds or quality concerns into unrelated functional
   requirements. A functional requirement may mention quality only when the
   stakeholder's functional rule itself depends on that quality behavior.
10. Acceptance criteria must verify exactly the atomic statement being written.
    Do not use one broad criterion to cover multiple split requirements.

Use reviewed Product Vision only to preserve role, entity, step, and aspect
context. Do not use it to invent statements not supported by interview evidence.
"""

_PASS2 = """\
PASS 2 - BASELINE AND SCOPE

Task:
Add only the baseline requirements and scope boundaries that remain necessary
after Pass 1.

Inputs:
- Product Vision flow, roles, and scope.
- Pass 1 requirement items.

Rules for baseline items:
1. Emit a baseline requirement only when the product concept and reviewed vision
   make the software obligation plainly necessary.
2. Do not restate an interview requirement already covered in Pass 1.
3. Stay at application-concept level, not implementation detail.
4. Use ids BL-NNN in source and FR/NFR ids in id.
5. origin=baseline, status=confirmed.
6. Do not convert Product Vision NFR concerns directly into requirements unless
   the interview evidence or the product baseline already supports a testable
   statement. Concerns are primarily operationalized in Pass 1.

Rules for scope items:
1. Convert each reviewed scope boundary into an out_of_scope requirement.
2. Use the boundary wording and reason from Product Vision.
3. Use OOS-NNN in id, source=<vision scope id>, origin=vision, status=excluded.
4. acceptance_criteria must be [].
"""

_PASS3 = """\
PASS 3 - FINAL LIST AND CONFLICTS

Task:
Review all requirement candidates from Pass 1 and Pass 2, remove duplicates,
keep the clean final list, and identify only unresolved conflicts.

Conflict standard:
- Report a conflict only when two items still cannot both hold in overlapping
  scope, or when the dialogue explicitly left a collision unresolved.
- Do not report ordinary trade-offs or already-clarified precedence as conflicts.
- Do not require a decision maker role to exist. The issue may remain unresolved
  because no governing rule was supplied.

Quality standard:
1. One atomic statement per requirement.
2. Acceptance criteria exist for every non-scope item. If an item lacks
   objective acceptance criteria grounded in its own statement and evidence,
   remove it or convert the missing evidence into a gap; do not leave an empty
   list.
3. Scope items stay excluded and keep no acceptance criteria.
4. Preserve traceability in source and rationale.
5. gaps should mention important missing evidence that did not become a requirement.
6. Keep FR and NFR concerns separated unless the interview explicitly ties them
   together in one rule.
"""


class DistillerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="distiller")

    def _register_tools(self) -> None:
        """Distiller uses structured extraction only."""

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        should_run = (
            state.get("_needs_srs_synthesis")
            or (
                "reviewed_interview_record" in artifacts
                and "requirement_list" not in artifacts
            )
        )
        if not should_run:
            return {}
        return self._synthesise(state)

    def _synthesise(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = dict(state.get("artifacts") or {})
        vision = artifacts.get("reviewed_product_vision") or state.get("product_vision") or {}
        interview = artifacts.get("interview_record") or {}
        items = interview.get("items") or []
        feedback = (state.get("requirement_list_feedback") or "").strip()
        feedback_block = (
            f"\n\nReviewer feedback to address:\n{feedback}" if feedback else ""
        )

        try:
            pass1: Draft = self.extract_structured(
                schema=Draft,
                system_prompt=(
                    self.profile.prompt + "\n\n" + _PASS1 + "\n\n"
                    + _FIELD_GUIDE + feedback_block
                ),
                user_prompt=(
                    f"PROJECT SIGNAL:\n{state.get('project_description', '')}\n\n"
                    f"PRODUCT VISION:\n{json.dumps(vision, indent=2, ensure_ascii=False)}\n\n"
                    f"INTERVIEW ITEMS:\n{json.dumps(items, indent=2, ensure_ascii=False)}\n\n"
                    "Emit interview-grounded requirement items."
                ),
                include_memory=False,
            )

            pass2: Draft = self.extract_structured(
                schema=Draft,
                system_prompt=(
                    self.profile.prompt + "\n\n" + _PASS2 + "\n\n"
                    + _FIELD_GUIDE + feedback_block
                ),
                user_prompt=(
                    f"PROJECT SIGNAL:\n{state.get('project_description', '')}\n\n"
                    f"PRODUCT VISION:\n{json.dumps(vision, indent=2, ensure_ascii=False)}\n\n"
                    f"PASS 1 ITEMS:\n{json.dumps([item.model_dump() for item in pass1.items], indent=2, ensure_ascii=False)}\n\n"
                    "Emit baseline and scope items only."
                ),
                include_memory=False,
            )

            all_items = [item.model_dump() for item in (pass1.items + pass2.items)]
            pass3: FinalPass = self.extract_structured(
                schema=FinalPass,
                system_prompt=(
                    self.profile.prompt + "\n\n" + _PASS3 + "\n\n"
                    + _FIELD_GUIDE + feedback_block
                ),
                user_prompt=(
                    f"PROJECT SIGNAL:\n{state.get('project_description', '')}\n\n"
                    f"PRODUCT VISION:\n{json.dumps(vision, indent=2, ensure_ascii=False)}\n\n"
                    f"INTERVIEW ITEMS:\n{json.dumps(items, indent=2, ensure_ascii=False)}\n\n"
                    f"CANDIDATE REQUIREMENTS:\n{json.dumps(all_items, indent=2, ensure_ascii=False)}\n\n"
                    "Return the final requirement list and only unresolved conflicts."
                ),
                include_memory=False,
            )
        except Exception as exc:
            logger.error("[DistillerAgent] Synthesis failed: %s", exc, exc_info=True)
            return {
                "_needs_srs_synthesis": False,
                "interview_complete": True,
                "errors": (state.get("errors") or []) + [f"Synthesis failed: {exc}"],
            }

        final = RequirementList(
            notes=(
                "PASS 1 - INTERVIEW REQUIREMENTS\n"
                f"{pass1.notes.strip()}\n\n"
                "PASS 2 - BASELINE AND SCOPE\n"
                f"{pass2.notes.strip()}\n\n"
                "PASS 3 - FINAL LIST AND CONFLICTS\n"
                f"{pass3.notes.strip()}"
            ),
            items=pass3.items,
            conflicts=pass3.conflicts,
            gaps=pass3.gaps,
        )

        artifacts["requirement_list"] = {
            "session_id": state.get("session_id", ""),
            "project_description": state.get("project_description", ""),
            "synthesised_at": datetime.now().isoformat(),
            **final.model_dump(),
            "status": "pending_conflicts" if final.conflicts else "pending_review",
        }

        return {
            "artifacts": artifacts,
            "interview_complete": True,
            "_needs_srs_synthesis": False,
            "requirement_list_feedback": None,
        }
