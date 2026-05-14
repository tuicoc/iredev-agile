"""
visionary.py - VisionaryAgent

VisionaryAgent turns a project signal into the reviewed Product Vision that
anchors the rest of the discovery flow.

Design split
------------
Schema descriptions define what every field means.
Prompt text defines how to reason into those fields.
Persona text defines the agent's stable stance only.

The pipeline remains structured-output only:
  Pass 1 - entity flow extraction
  Pass 2 - entity links
  Pass 3 - stakeholder roster
  Pass 4 - stakeholder duties
  Pass 5 - scope boundaries
  Pass 6 - NFR concerns
  Pass 7 - reader-facing product description
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .base import BaseAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pass 1 - flow
# ---------------------------------------------------------------------------

class Step(BaseModel):
    name: str = Field(
        description=(
            "Short verb-led lifecycle action for this entity."
        )
    )
    detail: str = Field(
        description=(
            "Plain-language explanation of the state change and normal actor."
        )
    )


class Entity(BaseModel):
    name: str = Field(
        description=(
            "Persistent managed domain object in the product flow."
        )
    )
    kind: Optional[Literal["primary", "related"]] = Field(
        default=None,
        description=(
            "primary = independent managed object; related = managed object whose "
            "lifecycle depends on a primary entity."
        ),
    )
    purpose: str = Field(
        description=(
            "Single sentence explaining why this entity matters in the product's "
            "real-world process."
        )
    )
    steps: List[Step] = Field(
        min_length=1,
        description=(
            "Ordered lifecycle actions that change this entity's product state."
        )
    )
    order: int = Field(
        description=(
            "Relative order of this entity in the end-to-end product flow. "
            "Use 1 for the earliest meaningful entity, then increase."
        )
    )
    related_to: Optional[str] = Field(
        default=None,
        description=(
            "Primary entity name when kind=related; otherwise null."
        ),
    )
    signal: str = Field(
        description=(
            "Reviewer-facing support for why this entity is present."
        )
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_flow_steps_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "steps" not in data and "flow_steps" in data:
            data = dict(data)
            data["steps"] = data.pop("flow_steps")
        return data

    @model_validator(mode="after")
    def _require_managed_lifecycle(self) -> "Entity":
        if not self.steps:
            raise ValueError(
                f"Entity '{self.name}' has no lifecycle steps. "
                "Drop it, classify it as a role, or model it as an attribute/reference "
                "of another entity."
            )

        if self.kind == "related" and not self.related_to:
            raise ValueError(
                f"Related entity '{self.name}' must name the primary entity it depends on, "
                "or be reclassified as primary if it has an independent lifecycle."
            )

        if self.kind != "related" and self.related_to:
            raise ValueError(
                f"Entity '{self.name}' has related_to set but is not kind='related'. "
                "Either set kind='related' or clear related_to."
            )

        return self

class FlowPass(BaseModel):
    notes: str = Field(
        description=(
            "Audit note for entity decisions."
        )
    )
    entities: List[Entity] = Field(
        description=(
            "Managed domain objects that structure the product flow."
        )
    )


# ---------------------------------------------------------------------------
# Pass 2 - links
# ---------------------------------------------------------------------------

class Link(BaseModel):
    source: str = Field(
        description="Entity name that initiates this dependency."
    )
    target: str = Field(
        description="Entity name affected by the source entity."
    )
    trigger: str = Field(
        description=(
            "Step name on the source entity whose occurrence changes what happens "
            "to the target entity."
        )
    )
    steps: List[str] = Field(
        description=(
            "Target entity steps affected by the trigger. Use only step names that "
            "already exist in the target entity."
        )
    )
    detail: str = Field(
        description=(
            "Plain-language explanation of the dependency and why it matters in the "
            "domain process."
        )
    )


class LinkPass(BaseModel):
    notes: str = Field(
        description=(
            "Reviewer-facing audit note describing which entity pairs were checked "
            "and why a dependency was accepted or rejected."
        )
    )
    links: List[Link] = Field(
        default_factory=list,
        description=(
            "Meaningful dependencies between entities. Leave empty when the reviewed "
            "flow does not justify a cross-entity dependency."
        )
    )


# ---------------------------------------------------------------------------
# Pass 3 - roles
# ---------------------------------------------------------------------------

class RoleSeed(BaseModel):
    name: str = Field(
        description=(
            "Stakeholder role that may shape product requirements. Use a concrete "
            "role label, not a vague audience segment."
        )
    )
    kind: Literal["operator", "partner", "authority"] = Field(
        description=(
            "Role kind. operator = performs recurring product work; partner = acts "
            "on the product but it is not their central job; authority = decides or "
            "approves when that role is truly grounded by the product signal or the "
            "domain understanding."
        )
    )


class RolePass(BaseModel):
    notes: str = Field(
        description=(
            "Reviewer-facing audit note explaining why each role belongs in the "
            "roster, which candidates were excluded, and whether inference was needed."
        )
    )
    roles: List[RoleSeed] = Field(
        description=(
            "Stakeholder roles relevant to requirements discovery. A role may be "
            "explicit in the input or inferred from the app concept plus general "
            "domain knowledge when the signal is sparse."
        )
    )


# ---------------------------------------------------------------------------
# Pass 4 - duties
# ---------------------------------------------------------------------------

class Duty(BaseModel):
    id: str = Field(
        description="Stable duty id in MD-NN format for downstream trace links."
    )
    rule: str = Field(
        description=(
            "Atomic stakeholder responsibility, permission, limit, or dependency."
        )
    )
    risk: str = Field(
        description=(
            "Concrete stakeholder-facing failure scenario if this duty is wrong, "
            "missing, or ambiguous. State the role, condition, and failure outcome."
        )
    )
    aspect: Literal[
        "operational_rule", "boundary_nfr", "integration", "permission"
    ] = Field(
        description=(
            "Aspect exposed by this duty. operational_rule = flow or exception rule; "
            "boundary_nfr = measurable quality boundary; integration = external system "
            "or data dependency; permission = who may or may not act."
        )
    )
    entity: str = Field(
        description="Entity name where this duty is easiest to interview."
    )
    step: str = Field(
        description="Step name where this duty is easiest to test."
    )
    entity_refs: List[str] = Field(
        default_factory=list,
        description=(
            "Optional explicit entity anchors for this duty. Use existing entity names."
        ),
    )
    flow_step_refs: List[str] = Field(
        default_factory=list,
        description=(
            "Optional explicit step anchors for this duty. Use existing step names."
        ),
    )
    priority: Literal["high", "medium", "low"] = Field(
        description=(
            "Reviewer-friendly importance signal. high blocks or materially distorts "
            "the product flow; medium degrades it; low refines it."
        )
    )


class Role(BaseModel):
    name: str = Field(
        description="Stakeholder role name carried from the roster pass."
    )
    kind: Literal["operator", "partner", "authority"] = Field(
        description="Role kind carried from the roster pass."
    )
    duties: List[Duty] = Field(
        description=(
            "Interview-worthy duties for this role, each anchored to one entity step."
        )
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_layer_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "kind" not in data and "layer" in data:
            layer = str(data.get("layer") or "").lower()
            mapped = {
                "operator": "operator",
                "beneficiary": "partner",
                "external": "partner",
                "governance": "authority",
                "authority": "authority",
                "partner": "partner",
            }.get(layer)
            if mapped:
                data = dict(data)
                data["kind"] = mapped
        return data


class Boundary(BaseModel):
    id: str = Field(
        description="Stable scope id in OOS-NN format."
    )
    item: str = Field(
        description=(
            "Capability boundary stated as one excluded product responsibility."
        )
    )
    reason: str = Field(
        description=(
            "Why that capability is outside the current product scope."
        )
    )


class DutyPass(BaseModel):
    notes: str = Field(
        description=(
            "Audit note explaining how duties were derived for each role."
        )
    )
    roles: List[Role] = Field(
        description="Final stakeholder roster with interview-worthy duties."
    )


class ScopePass(BaseModel):
    notes: str = Field(
        description="Audit note explaining why each scope boundary belongs here."
    )
    scope: List[Boundary] = Field(
        default_factory=list,
        description="Explicit product exclusions that should stay visible downstream."
    )


# ---------------------------------------------------------------------------
# Pass 7 - reader description
# ---------------------------------------------------------------------------

class SummaryPass(BaseModel):
    description: str = Field(
        description=(
            "Concise reviewer-facing description of the product assembled after the "
            "flow, roles, duties, scope, and NFR concerns are known. Downstream agents "
            "should not need this field to make decisions."
        )
    )


# ---------------------------------------------------------------------------
# Pass 6 - NFR concerns
# ---------------------------------------------------------------------------

NFRCategory = Literal[
    "performance_efficiency",
    "security",
    "reliability",
    "interaction_capability",
    "maintainability",
    "compatibility",
    "safety_freedom_from_risk",
    "flexibility",
    "quality_in_use",
]


class NFRConcern(BaseModel):
    id: Optional[str] = Field(
        default=None,
        description="Optional stable concern id in CONCERN-NN format.",
    )
    category: NFRCategory = Field(
        description=(
            "Quality category for this softgoal concern. This is not a requirement "
            "type or a measurable target."
        )
    )
    theme: str = Field(
        description="Short human-readable softgoal theme for review."
    )
    attached_to: List[str] = Field(
        default_factory=list,
        description=(
            "Existing entity names or step names where this concern is anchored."
        ),
    )
    affected_roles: List[str] = Field(
        default_factory=list,
        description="Existing role names that would feel this quality concern."
    )
    rationale: str = Field(
        description=(
            "One sentence explaining why this quality plausibly matters here. "
            "Do not include thresholds, technologies, vendors, or acceptance criteria."
        )
    )


class NFRPass(BaseModel):
    notes: str = Field(
        description=(
            "Reviewer-facing audit note explaining which quality concerns were kept "
            "or omitted and how each kept concern is anchored."
        )
    )
    concerns: List[NFRConcern] = Field(
        default_factory=list,
        description=(
            "Concept-level NFR softgoals. These are interview topics, not final "
            "non-functional requirements."
        )
    )


# ---------------------------------------------------------------------------
# Final artifact
# ---------------------------------------------------------------------------

class Flow(BaseModel):
    entities: List[Entity]
    links: List[Link]


class ProductVision(BaseModel):
    description: str = Field(
        description=(
            "Reader-facing overview of the system. It summarizes the completed vision "
            "artifact but is not the reasoning source for downstream agents."
        )
    )
    notes: str = Field(
        description=(
            "Combined reviewer-facing audit note from the structured passes."
        )
    )
    flow: Flow = Field(
        description=(
            "Entity flow that downstream agenda building must use as its product map."
        )
    )
    roles: List[Role] = Field(
        description=(
            "Reviewed stakeholder roster with duties that can be converted into agenda "
            "items without inventing missing context."
        )
    )
    nfr_concerns: List[NFRConcern] = Field(
        default_factory=list,
        description=(
            "Quality softgoals to operationalize later through stakeholder dialogue."
        ),
    )
    scope: List[Boundary] = Field(
        description="Product boundaries to keep visible during synthesis."
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SIGNAL = "Project signal:\n{signal}"
_FEEDBACK = (
    "\n\nReviewer feedback to address before regenerating any field:\n{feedback}"
)

_PASS1 = """\
PASS 1 - FLOW

Goal:
Extract the managed product-flow entities supported or operationally entailed by
the project signal.

Method:
1. Read the signal literally first.
2. Keep the named capability records whose state the product creates, changes,
   completes, cancels, removes, or revisits.
3. Run the actor boundary test on every candidate:
   - If the candidate answers "who participates, performs, receives, owns,
     approves, benefits, or is affected", it is a role candidate, not an entity.
   - If the product manages information about an actor, name the managed record
     or process, not the person. For example, prefer an account/profile/assignment/
     participation/approval/management record when that record has its own
     lifecycle; otherwise keep the actor only as a role.
   - Being the subject of another entity is not enough to become an entity.
4. For each kept entity and step, ask whether its lifecycle is incoherent without
   another managed object from the same domain being allocated, made available,
   occupied, consumed, transferred, blocked, reconciled, or released.
5. Add that operational entity only when both anchors are present:
   - at least one existing entity or step needs it to explain the product flow;
   - the product domain gives the object a natural name or role.
6. Name inferred entities from the user's domain wording when the domain meaning
   clearly supports it. Otherwise use neutral wording. Do not reuse a fixed
   label from a template.
7. Drop attributes, UI labels, measurements, transient events, generic data,
   implementation components, and environment/context nouns.
8. Each accepted entity must have at least one meaningful state-changing step.
9. If a dependency may matter later but is not necessary for the named flow,
   mention it in notes instead of creating an entity.

Write notes that explain kept entities, inferred operational entities, rejected
actors/attributes, actor-related records if any, and deferred assumptions.

Notes must include a compact concept audit with these decisions:
- kept workflow records,
- kept operational entities and their anchors,
- actor-like candidates moved to roles,
- actor-related records kept or rejected,
- attributes/context/scope candidates rejected or deferred.
"""

_PASS1_AUDIT = """\
PASS 1 REVIEW - FLOW CONSISTENCY AUDIT

Goal:
Return the corrected FlowPass using the same schema. Do not add a new artifact
shape. This is a consistency review of the draft flow, not a new product design.

Project signal:
{signal}

Draft flow:
{flow}

Audit method:
1. Re-run the actor boundary test:
   - concepts that answer who participates, receives, owns, approves, benefits,
     or is affected must not be entities;
   - if actor information is managed, keep only the managed record/process when
     it has its own lifecycle;
   - otherwise move the actor candidate to notes for the role pass.
2. Re-run the operational object test:
   - if an existing entity step depends on something being allocated, made
     available, occupied, consumed, transferred, blocked, reconciled, or released,
     and the domain gives that object a natural role, include the minimum
     operational entity;
   - if that object is only a policy, measurement, attribute, or vague context,
     reject or defer it in notes.
3. Re-run the orphan concept test:
   - if notes, entity purposes, or step details rely on an object as allocated,
     available, occupied, consumed, transferred, blocked, reconciled, or released,
     that object must either be present as an entity or explicitly rejected in
     notes with a reason.
4. Keep the flow compact. Do not add actors, screens, broad organizations,
   implementation components, generic data, qualities, or scope boundaries as
   entities.
5. Preserve good draft entities and steps unless the audit shows a classification
   error. Return a complete FlowPass.

Notes must summarize the audit decisions using the same compact concept audit
categories from PASS 1.
"""

_PASS2 = """\
PASS 2 - LINKS

Goal:
Explain cross-entity dependencies in the reviewed flow.

Read-only flow:
{flow}

Method:
1. Consider only entities already present in the flow.
2. Add a link when a step on one entity changes another entity's valid behavior,
   state, or timing.
3. Shared actors or shared subject matter are not enough.
4. When a primary entity uses an operational entity from the same flow, add links
   for allocation, availability, occupation, release, transfer, blocking, or
   reconciliation moments that are represented by existing steps.
5. Omit uncertain dependencies and explain the omission in notes. "Not explicit"
   is not enough when the reviewed flow already contains an operational entity
   whose lifecycle is changed by another entity.
"""

_PASS3 = """\
PASS 3 - ROLES

Goal:
Identify stakeholders that can shape requirements for this product.

Read-only flow:
{flow}

Read-only links:
{links}

Method:
1. Prefer roles explicitly named in the signal.
2. Add inferred roles when the product flow clearly requires a human or
   organization to create, operate, decide, approve, receive, or maintain part
   of the domain process.
3. Use the flow as the anchor. For each entity step ask:
   - who performs this step,
   - who is acted upon or affected by it,
   - who benefits when it succeeds,
   - who governs, audits, maintains, or can block it.
4. Use general domain understanding to name those roles precisely enough for
   review, but do not force a "decision maker" just to make conflict handling
   possible.
5. Keep only roles that can meaningfully shape requirement discovery.
6. Choose kind by relationship to the product work:
   operator, partner, or authority.

Guardrail:
- Do not invent a role from an industry template. Include an inferred role only
  when it is anchored to the reviewed flow or a clear product dependency.
- If a person, organization, team, or stakeholder-like noun was rejected from
  the entity flow because it is an actor rather than a managed object, consider
  it here as a role candidate when it performs, receives, governs, benefits from,
  maintains, or is affected by an entity step.
- Do not drop a beneficiary or service recipient merely because they are not an
  operator. If their experience, permissions, data, wait, status, request, or
  outcome shapes requirements, model them as a partner role.
- A role and an entity may share a name only when the product also manages that
  actor's separate record as a domain object. Otherwise keep the actor only as
  a role and refer to its involvement through duties.
"""

_PASS4 = """\
PASS 4 - DUTIES

Goal:
Turn the reviewed role roster into duties that can drive interview agenda items.

Read-only flow:
{flow}

Read-only links:
{links}

Read-only roles:
{roles}

Method for each role:
1. Walk the flow and decide where that role creates work, makes a decision,
   enforces a limit, protects an access rule, or depends on another system.
2. Build a coverage matrix in notes: role x primary entity x meaningful action.
   Use it to prevent missing duties before emitting the final list.
3. Cover every primary capability entity before adding duties for inferred
   operational entities. When multiple primary entities share an inferred
   operational resource, duties must not collapse into only the shared resource.
4. For each primary entity, emit at least one concrete duty for each role that
   can create, change, cancel, enter, leave, approve, or depend on that entity.
5. Emit additional duties for inferred operational entities only when they expose
   a distinct responsibility such as allocation, availability, occupancy, release,
   or reconciliation.
6. Emit a duty when it gives an interviewer something concrete to verify.
   A duty may be a permission or responsibility whose exact rule is still open.
7. Do not compress separate lifecycle actions into one duty when the condition,
   permission, owner, or risk differs.
8. Anchor each duty to one entity and one step where it becomes interviewable.
   If an idea spans entities, choose the clearest touchpoint and use refs.
9. Do not add duties for template-only operations or policy details. Mention
   uncertain domain assumptions in notes only.
10. risk must state an interview-useful failure scenario: the role affected, the
   condition that makes the duty matter, and the failure outcome if the rule is
   wrong, missing, or ambiguous. Avoid generic risk labels.
11. aspect is a semantic classification, not a feature label.
12. priority is a reviewer-facing importance estimate.
13. entity_refs and flow_step_refs are optional trace anchors.
14. Do not use duties to store NFR softgoals.
"""

_PASS5_SCOPE = """\
PASS 5 - SCOPE

Goal:
Capture explicit product boundaries that should stay visible downstream.

Project signal:
{signal}

Read-only flow:
{flow}

Read-only roles and duties:
{roles}

Method:
1. Add a boundary only when it is explicit in the signal or a clear omission
   that would otherwise mislead downstream agents.
2. Keep each boundary atomic.
3. Do not invent exclusions merely because they are common neighboring
   capabilities in the domain.
4. If a boundary comes from an omission, notes must explain why downstream agents
   are likely to assume it without the boundary.
"""

_PASS_SUMMARY = """\
PASS 7 - DESCRIPTION

Goal:
Write the one reader-facing product description after the structured vision is
complete. This description is for human review, not as a new reasoning source.

Read-only vision fields:
{vision}

Method:
- Summarize the product purpose, main flow, stakeholder picture, visible quality
  concerns, and explicit scope boundaries in one compact paragraph.
- Do not add facts that are absent from the completed fields.
"""

_PASS_NFR = """\
PASS 6 - NFR CONCERNS

Goal:
Name concept-level quality softgoals that should become interview topics later.
Do not write final non-functional requirements in this pass.

Read-only flow:
{flow}

Read-only links:
{links}

Read-only roles and duties:
{roles}

Method:
1. Scan only for quality concerns anchored to an existing entity, step, link,
   role, or duty.
2. Emit a concern only when a role in the reviewed roster would plausibly care
   about that quality.
3. Fill the category, theme, attached_to, affected_roles, and rationale fields.
4. Attach actor-facing concerns to the existing workflow entity or step where
   the actor-facing risk appears.
5. Use ids in CONCERN-NN format when you can do so consistently.

Guardrails:
- A concern is a softgoal, not a requirement. Do not write thresholds, SLAs,
  numeric targets, retention periods, technologies, vendors, architecture,
  encryption standards, or acceptance criteria.
- Do not emit a concern for every category by default.
- If you cannot anchor a concern to existing artifacts, drop it.
"""


class VisionaryAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="visionary")

    def _register_tools(self) -> None:
        """Visionary uses structured extraction only."""

    @staticmethod
    def _prompt(signal: str, feedback: Optional[str]) -> str:
        text = _SIGNAL.format(signal=signal)
        if feedback:
            text += _FEEDBACK.format(feedback=feedback)
        return text

    def _pass1(self, signal: str, feedback: Optional[str]) -> FlowPass:
        return self.extract_structured(
            schema=FlowPass,
            system_prompt=self.profile.prompt + "\n\n" + _PASS1,
            user_prompt=self._prompt(signal, feedback),
            include_memory=False,
        )

    def _pass1_audit(
        self,
        signal: str,
        draft_flow: FlowPass,
        feedback: Optional[str],
    ) -> FlowPass:
        system = self.profile.prompt + "\n\n" + _PASS1_AUDIT.format(
            signal=signal,
            flow=json.dumps(draft_flow.model_dump(), indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
            schema=FlowPass,
            system_prompt=system,
            user_prompt=self._prompt(signal, feedback),
            include_memory=False,
        )

    def _pass2(
        self,
        signal: str,
        flow: FlowPass,
        feedback: Optional[str],
    ) -> LinkPass:
        system = self.profile.prompt + "\n\n" + _PASS2.format(
            flow=json.dumps(flow.model_dump(), indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
            schema=LinkPass,
            system_prompt=system,
            user_prompt=self._prompt(signal, feedback),
            include_memory=False,
        )

    def _pass3(
        self,
        signal: str,
        flow: FlowPass,
        links: LinkPass,
        feedback: Optional[str],
    ) -> RolePass:
        system = self.profile.prompt + "\n\n" + _PASS3.format(
            flow=json.dumps(flow.model_dump(), indent=2, ensure_ascii=False),
            links=json.dumps(links.model_dump(), indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
            schema=RolePass,
            system_prompt=system,
            user_prompt=self._prompt(signal, feedback),
            include_memory=False,
        )

    def _pass4(
        self,
        signal: str,
        flow: FlowPass,
        links: LinkPass,
        roles: RolePass,
        feedback: Optional[str],
    ) -> DutyPass:
        system = self.profile.prompt + "\n\n" + _PASS4.format(
            flow=json.dumps(flow.model_dump(), indent=2, ensure_ascii=False),
            links=json.dumps(links.model_dump(), indent=2, ensure_ascii=False),
            roles=json.dumps(roles.model_dump(), indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
            schema=DutyPass,
            system_prompt=system,
            user_prompt=self._prompt(signal, feedback),
            include_memory=False,
        )

    def _pass5(
        self,
        signal: str,
        flow: FlowPass,
        duties: DutyPass,
        feedback: Optional[str],
    ) -> ScopePass:
        system = self.profile.prompt + "\n\n" + _PASS5_SCOPE.format(
            signal=signal,
            flow=json.dumps(flow.model_dump(), indent=2, ensure_ascii=False),
            roles=json.dumps(
                [r.model_dump() for r in duties.roles],
                indent=2,
                ensure_ascii=False,
            ),
        )
        return self.extract_structured(
            schema=ScopePass,
            system_prompt=system,
            user_prompt=self._prompt(signal, feedback),
            include_memory=False,
        )

    def _pass6(
        self,
        signal: str,
        flow: FlowPass,
        links: LinkPass,
        duties: DutyPass,
        feedback: Optional[str],
    ) -> NFRPass:
        system = self.profile.prompt + "\n\n" + _PASS_NFR.format(
            flow=json.dumps(flow.model_dump(), indent=2, ensure_ascii=False),
            links=json.dumps(links.model_dump(), indent=2, ensure_ascii=False),
            roles=json.dumps(
                [r.model_dump() for r in duties.roles],
                indent=2,
                ensure_ascii=False,
            ),
        )
        return self.extract_structured(
            schema=NFRPass,
            system_prompt=system,
            user_prompt=self._prompt(signal, feedback),
            include_memory=False,
        )

    def _pass7(
        self,
        signal: str,
        product: Dict[str, Any],
        feedback: Optional[str],
    ) -> SummaryPass:
        system = self.profile.prompt + "\n\n" + _PASS_SUMMARY.format(
            vision=json.dumps(product, indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
            schema=SummaryPass,
            system_prompt=system,
            user_prompt=self._prompt(signal, feedback),
            include_memory=False,
        )

    @staticmethod
    def _assemble(
        flow: FlowPass,
        links: LinkPass,
        roles: RolePass,
        duties: DutyPass,
        scope: ScopePass,
        nfr: NFRPass,
        summary: SummaryPass,
    ) -> ProductVision:
        notes = (
            "PASS 1 - FLOW\n"
            f"{flow.notes.strip()}\n\n"
            "PASS 2 - LINKS\n"
            f"{links.notes.strip()}\n\n"
            "PASS 3 - ROLES\n"
            f"{roles.notes.strip()}\n\n"
            "PASS 4 - DUTIES\n"
            f"{duties.notes.strip()}\n\n"
            "PASS 5 - SCOPE\n"
            f"{scope.notes.strip()}\n\n"
            "PASS 6 - NFR CONCERNS\n"
            f"{nfr.notes.strip()}"
        )
        return ProductVision(
            description=summary.description.strip(),
            notes=notes,
            flow=Flow(entities=flow.entities, links=links.links),
            roles=duties.roles,
            nfr_concerns=nfr.concerns,
            scope=scope.scope,
        )

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        signal = (state.get("project_description") or "").strip()
        if not signal:
            logger.warning("[VisionaryAgent] project_description is missing.")
            return {}

        feedback = (state.get("product_vision_feedback") or "").strip() or None
        logger.info("[VisionaryAgent] Building Product Vision.")

        try:
            flow = self._pass1(signal, feedback)
            flow = self._pass1_audit(signal, flow, feedback)
            links = self._pass2(signal, flow, feedback)
            role_seed = self._pass3(signal, flow, links, feedback)
            duties = self._pass4(signal, flow, links, role_seed, feedback)
            scope = self._pass5(signal, flow, duties, feedback)
            nfr = self._pass6(signal, flow, links, duties, feedback)
            draft = {
                "flow": {
                    "entities": [e.model_dump() for e in flow.entities],
                    "links": [l.model_dump() for l in links.links],
                },
                "roles": [r.model_dump() for r in duties.roles],
                "nfr_concerns": [c.model_dump() for c in nfr.concerns],
                "scope": [s.model_dump() for s in scope.scope],
            }
            summary = self._pass7(signal, draft, feedback)
            vision = self._assemble(
                flow, links, role_seed, duties, scope, nfr, summary
            )
        except Exception as exc:
            logger.error("[VisionaryAgent] Pipeline failed: %s", exc, exc_info=True)
            return {}

        vision_dict = vision.model_dump()
        artifacts = dict(state.get("artifacts") or {})
        artifacts["product_vision"] = {
            **vision_dict,
            "created_at": datetime.now().isoformat(),
            "status": "pending_review",
        }

        updates: Dict[str, Any] = {
            "product_vision": vision_dict,
            "artifacts": artifacts,
        }
        if feedback:
            updates["product_vision_feedback"] = None

        logger.info(
            "[VisionaryAgent] Product Vision ready - %d entities, %d roles, %d concerns, %d scope items.",
            len(vision.flow.entities),
            len(vision.roles),
            len(vision.nfr_concerns),
            len(vision.scope),
        )
        return updates
