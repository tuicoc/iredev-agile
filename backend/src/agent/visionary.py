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
            "Short verb-led action for this entity, expressed in the domain's "
            "natural vocabulary. The flow pass walks the LIFECYCLE DIMENSIONS "
            "block in the persona and emits one step per anchored moment, "
            "using the verb the domain's practitioners actually use for that "
            "moment when one exists. Prefer the domain's verb over a generic "
            "create / update / delete / read label whenever the domain has a "
            "more precise one. Do not invent a synonym to look domain-specific "
            "when the generic verb genuinely is the domain's own."
        )
    )
    detail: str = Field(
        description=(
            "Plain-language explanation that says BOTH (a) the lived domain "
            "moment this step represents and (b) the performer responsible for "
            "performing it.\n"
            "\n"
            "The lived domain moment may be either a state change on the entity "
            "(transition, mutation, termination, in the LIFECYCLE DIMENSIONS "
            "vocabulary), or a distinct operating activity the performer "
            "carries out on or with the entity that does not change its stored "
            "state (genesis, enrichment, consumption, cross-reference). Both "
            "kinds are first-class steps. Name the moment as it is actually "
            "experienced in domain practice, not as a generic database "
            "operation. When this step participates in a cross-reference, the "
            "detail must make the other entity visible so the next pass can "
            "read it as the trigger of a link.\n"
            "\n"
            "The performer is a load-bearing anchor: downstream passes read it "
            "to decide whether a stakeholder role exists, who owns a duty, and "
            "where a quality concern is felt.\n"
            "\n"
            "Use exactly one of the following performer forms:\n"
            "- a concrete human-role label (e.g. 'the user logs...', 'the "
            "reviewer approves...', 'the operator releases...'). Use this when "
            "a person performs the action;\n"
            "- 'the system' when no human performs the action and the step is "
            "automated generation, scheduled computation, derivation, or "
            "rendering of state the product owns. This signals that the step "
            "is entity behavior, not a human duty;\n"
            "- 'an external party' followed by the named external actor (e.g. "
            "'the payment provider notifies...', 'the regulator publishes...') "
            "when an outside system or organization performs the action.\n"
            "\n"
            "Do not omit the performer. Do not use placeholders like 'the "
            "appropriate actor', 'the application', or passive voice that "
            "hides the performer. If the project signal does not say who "
            "performs the step, choose the most defensible performer for the "
            "domain and stand behind it; the audit pass will verify."
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
            "Reviewer-facing anchor for why this entity is present. Must cite "
            "exactly one anchor of these three kinds and only these three:\n"
            "- an exact phrase or noun the project signal uses (quote the "
            "phrase);\n"
            "- a mechanic that a kept step's detail logically requires, where "
            "you name the specific step (e.g. 'Update Mood Entry implies the "
            "record persists across sessions');\n"
            "- a specific, named practice for this product's actual domain, "
            "distinctive enough to describe in plain language (e.g. "
            "'mood-tracking practice records entries against a timestamp so "
            "patterns can be computed over a window').\n"
            "\n"
            "Generic genre claims are NOT anchors and must not appear here. "
            "The following phrasings are forbidden in this field: 'apps of "
            "this kind tend to have one', 'often a feature in [domain] apps', "
            "'common feature in [genre]', 'users typically expect this', "
            "'industry standard', 'best practice', or any equivalent appeal "
            "to genre membership without a specific hook. If the only "
            "justification you can write reduces to genre membership, the "
            "entity should not have been added."
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
            "Step name on the source entity whose execution either (a) causes a "
            "state change on the target entity, or (b) requires records "
            "belonging to the target entity to be juxtaposed, correlated, "
            "aggregated, or referenced for the step to function as the domain "
            "expects. Type (b) corresponds to the Cross-reference dimension in "
            "the persona and is legitimate only when link.detail can quote the "
            "signal phrase, an entity purpose, or the step wording that demands "
            "the cross-reference."
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
            "Plain-language explanation of the dependency and why it matters in "
            "the domain process. For a state-change link (type a) the detail "
            "names the state on the target the trigger affects. For a "
            "cross-reference link (type b) the detail MUST quote the concrete "
            "phrase that makes the cross-reference necessary — a signal phrase, "
            "an entity purpose, or the source step's own wording — so that the "
            "anchor is auditable. Bare thematic kinship ('they belong to the "
            "same product', 'shared user', 'similar topic') does not earn a "
            "link of either type."
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
            "Atomic stakeholder responsibility, permission, limit, or "
            "dependency.\n"
            "\n"
            "Atomic means the rule names exactly ONE operational "
            "alternative, not a menu of alternatives wrapped under 'or'. "
            "When the underlying lived duty exposes two or more "
            "alternatives the practitioner chooses between, each "
            "alternative carries its OWN trigger condition, its own "
            "failure mode if used in the wrong moment, and its own "
            "interview surface. Merging alternatives under a single "
            "'A or B' rule destroys that surface: a downstream agenda "
            "item built on the merged rule needs only one drill turn to "
            "confirm 'both are acceptable', and the trigger-condition "
            "question — the real interview content — is never asked.\n"
            "\n"
            "Split discipline: when a candidate rule reads in the shape "
            "'the role does X or Y' between operational alternatives, "
            "emit it as TWO duties of the shape 'the role does X when "
            "<trigger condition for X>' and 'the role does Y when "
            "<trigger condition for Y>'. The two duties anchor to the "
            "same entity step; the audit notes name them as a deliberate "
            "split from one signal-level capability. The split is "
            "warranted only when the alternatives actually expose "
            "different trigger conditions in the domain; if both are "
            "interchangeable at all times, keep one duty and say so in "
            "the audit notes.\n"
            "\n"
            "Phrasing is descriptive of the stakeholder's responsibility "
            "or permission. Do not pre-bake the product-side verb here "
            "('the app must support X' is interview output, not duty "
            "input). The interview phase converts a settled stakeholder "
            "statement into the product-subject rule; the duty exists "
            "only to give the interviewer a sharp surface to probe."
        )
    )
    risk: str = Field(
        description=(
            "Concrete stakeholder-facing failure scenario when this duty "
            "is AMBIGUOUS or WRONG — not when it is absent. State the "
            "role, the condition under which the ambiguity bites, and "
            "the lived failure outcome.\n"
            "\n"
            "Two failure modes are NOT equivalent here:\n"
            "- Duty-absent failure: 'if the duty did not exist at all, "
            "  the role could not achieve their goal'. This is "
            "  uninteresting at the interview stage because everyone "
            "  already agrees the capability should exist; a downstream "
            "  interviewer has nothing to drill into.\n"
            "- Duty-ambiguous failure: 'the duty exists but its trigger, "
            "  scope, exception, threshold, or boundary is undefined, "
            "  and the role reaches a moment the rule does not handle'. "
            "  This is the interview-driving form — it names the "
            "  specific lived breakdown the dialogue must clarify.\n"
            "Always write risk in the duty-ambiguous form. If you can "
            "only state a duty-absent scenario for this duty, the duty "
            "is too generic to drive an interview; sharpen the rule or "
            "drop the duty.\n"
            "\n"
            "Required structure (three pieces visible): WHO experiences "
            "the failure (the role), WHEN the ambiguity bites (the "
            "operating condition that the current rule does not bound), "
            "and WHAT actually breaks in lived practice (the specific "
            "outcome — task abandoned, wrong path chosen, downstream "
            "data unreliable, retry forced, decision delayed). A "
            "single-clause statement that names only the broad domain "
            "consequence ('insight lost', 'engagement drops', "
            "'experience suffers') is too thin and must be rewritten."
        )
    )
    aspect: Literal[
        "operational_rule", "boundary_nfr", "integration", "permission"
    ] = Field(
        description=(
            "Semantic kind of constraint this duty exposes, judged by what would "
            "disappear from the product if the rule were removed.\n"
            "- operational_rule: shapes how a step is performed, ordered, "
            "conditioned, retried, paused, cancelled, or recovered. Removing it "
            "changes the flow itself, not who reaches it. A role's baseline "
            "ability to act on its own managed artifact is an operational_rule, "
            "not a permission, when no other actor or context can reach that "
            "same artifact.\n"
            "- boundary_nfr: a measurable operating limit such as capacity, "
            "latency, freshness, retention, or accuracy that this duty enforces. "
            "Removing it changes tolerance, not flow.\n"
            "- integration: declares an external system, organization, or data "
            "source this step depends on or hands off to. Removing it changes "
            "what the step can or must communicate with.\n"
            "- permission: separates who MAY act from who MAY NOT act on the "
            "same artifact at the same moment. A permission duty requires a "
            "concrete second locus of action - another role, a delegate, an "
            "external party, an owner-vs-non-owner split, a status that revokes "
            "access - that has the technical ability to reach the artifact but "
            "should be denied. If removing the rule leaves no actor able to act "
            "improperly because no such second locus exists, the duty is not a "
            "permission."
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
        description=(
            "Short human-readable softgoal theme for review. Name the "
            "specific lived moment the quality is about, or the "
            "observable that would expose its failure — not the "
            "emotional label the moment would wear. A theme that "
            "consists only of emotional descriptors ('quick', "
            "'responsive', 'intuitive', 'smooth', 'engaging', "
            "'satisfying') leaks into downstream agenda items: the "
            "agenda re-uses the descriptor in scene and probe, the "
            "interviewer accepts a closure rule worded with the same "
            "descriptor, and the quality-probe interview short-circuits "
            "without ever extracting an observable boundary. Choose "
            "words that name a moment, a surface, or the observable "
            "absence/comparator that would tell the role the quality "
            "failed."
        )
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
            "One sentence explaining why this quality plausibly matters "
            "at the named lived moment.\n"
            "\n"
            "Required structure: the sentence must name both (a) the "
            "lived moment where the role feels the quality — which "
            "step, while the role is doing what surrounding activity, "
            "and (b) the observable breakdown that would tell the role "
            "the quality failed — an absence, a delay long enough to "
            "shift attention, a re-check the role performs because they "
            "do not trust the first reading, a step abandoned before "
            "completion, a wrong choice forced by missing feedback. "
            "Without BOTH pieces the rationale is decoration, not "
            "anchoring.\n"
            "\n"
            "Three patterns are forbidden as the ONLY content:\n"
            "- emotional-descriptor-only rationales (the sentence's "
            "  load-bearing words are 'quick', 'responsive', 'fast', "
            "  'intuitive', 'smooth', 'snappy' and nothing else);\n"
            "- generic engagement claims that name no specific lived "
            "  moment ('user satisfaction', 'continued engagement', "
            "  'consistent use', 'good experience');\n"
            "- tautological broadening that restates that the slot is "
            "  big without naming the distinguishing moment ('matters "
            "  across the product', 'applies broadly', 'every step "
            "  needs this').\n"
            "When the sentence reduces to any of these, the concern "
            "fails the anchor test and must split into anchored "
            "concerns or drop. The TAUTOLOGY CHECK in Pass 6 applies "
            "to this field, not only to the audit-block collapse "
            "line.\n"
            "\n"
            "Do not include thresholds, technologies, vendors, or "
            "acceptance criteria — those belong to dialogue and "
            "synthesis, not to the vision-stage softgoal."
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
Extract the managed product-flow entities supported or operationally entailed
by the project signal, with an explicit performer label on every step so that
downstream passes can read it as a hard anchor instead of guessing.

Read the INVENTION DISCIPLINE block in the agent persona before producing this
pass. The anchor-before-slot rule, the system-action rule, and the preservation
rule all apply here.

Method:
1. Read the signal literally first.

2. Identify candidate entities: the managed objects through which the named
   capabilities reach the practitioner. Each candidate entity carries a
   lifecycle that may span any of the LIFECYCLE DIMENSIONS in the persona,
   not only state change. Some products lean on transition-heavy entities;
   others lean on entities whose value lives in enrichment and consumption
   moments; many flows are mixed. Identify a candidate by whether the product
   persists and operates on it, not by whether it has a named state machine.

3. Run the actor boundary test on every candidate:
   - If the candidate answers "who participates, performs, receives, owns,
     approves, benefits, or is affected", it is a role candidate, not an
     entity.
   - If the product manages information about an actor, name the managed
     record or process (e.g. an account, profile, assignment, participation,
     or approval record) when that record has its own lifecycle; otherwise
     keep the actor only as a role candidate for Pass 3.
   - Being the subject of another entity is not enough to become an entity.

4. For each kept entity, run three inference scans and surface every candidate
   they produce. Reject candidates only after running them through the actor
   boundary test (step 3) and the anchor test (step 5) below.

   Scan 4a - Operational entailment. Ask whether the entity's lifecycle is
   incoherent without another managed object being allocated, made available,
   occupied, consumed, transferred, blocked, reconciled, or released. These
   candidates are required for the flow to function.

   Scan 4b - Domain affinity. Ask what state-bearing companions a practitioner
   of this domain would expect to find alongside this entity in real use:
   context tags, triggers, causes, reminders, targets, streaks, sources,
   attachments, references, or other managed companions that the kept entity
   meaningfully ties to. These candidates are not required for the flow to
   compile, but they shape how requirements get discovered. Surface them; the
   anchor test decides whether to keep.

   Scan 4c - Lifecycle dimensions. Walk the LIFECYCLE DIMENSIONS block in
   the persona once for the kept entity. For each dimension in turn, ask:
   does the signal phrase, this entity's purpose, another kept step's
   mechanic, or a named domain practice anchor a step under this dimension
   for this entity? Emit one step per anchored moment, using the verb the
   domain itself uses for that moment. When the same dimension produces
   more than one operationally distinct moment for the practitioner — for
   example one enrichment that attaches context and another that attaches
   a note — emit one step per moment, not a merged one. Leave a dimension
   empty when no anchor exists. The audit notes must record which
   dimensions were considered and which were dropped for which reason, so
   the reviewer can see that the scan actually ran instead of pattern-
   matching to create / update / delete / read.

5. ANCHOR TEST for every candidate, including entities named verbatim in the
   signal. Each entity's signal field must point to exactly one anchor of one
   of these three kinds:
   a. an exact phrase or noun from the project signal (quote it);
   b. a mechanic implied by a kept step's detail (name the step);
   c. a specific, named practice for this product's actual domain,
      distinctive enough to describe in plain language.
   Generic genre claims — "apps of this kind", "often a feature in [domain]
   apps", "users typically expect", "common feature in [genre]" — are NOT
   anchors. If the only justification reduces to genre membership, reject
   the candidate and record it in the reject log (see notes format below).

6. PERFORMER LABEL on every step. The step.detail field MUST name the
   performer in one of three forms and only these three:
   - a human-role label ("the user", "the reviewer", "the operator", etc.) —
     a human performs the action;
   - "the system" — no human performs the action; this is automated
     generation, scheduled computation, derivation, or rendering of state
     the product owns;
   - "an external party" followed by the named external actor — an outside
     system or organization performs the action.
   Placeholders like "the appropriate actor", "the application", or passive
   voice that hides the performer are forbidden. The performer label is what
   Pass 3 reads to decide whether a role exists; Pass 4 reads to decide who
   owns a duty; Pass 6 reads to decide where a concern is felt. Omitting it
   forces downstream passes to guess and is a leading cause of invented
   roles.

7. PRESERVATION DISCIPLINE. Adding a new entity does not entitle you to
   silently drop steps from existing entities. Each step exists or doesn't
   exist on its own anchor in the signal or in the entity's lifecycle, not
   on whether a newly added entity now covers similar ground. If a user
   creates an entity, they typically can also review it; if they write a
   reflection, they typically can also read it back. Do not delegate
   Review / View / Read steps out of one entity into another. If you do
   remove a step from a kept entity, the reject log must name the step
   and which anchor failed.

8. Drop attributes, UI labels, measurements, transient events, generic data,
   implementation components, and environment/context nouns.

9. Each accepted entity must have at least one meaningful step in domain
   practice — a moment under any of the LIFECYCLE DIMENSIONS where the
   entity is genuinely operated on, not necessarily a state change — and
   every step must carry a performer label per rule 6.

10. If a dependency may matter later but is not necessary for the named
    flow, mention it in notes instead of creating an entity.

Notes must contain a compact audit with these sections. Each section may be
empty when no candidates of that kind exist, but the sections themselves must
be present so the reviewer can see what was considered:
- KEPT entities — for each, the anchor type from rule 5
  (signal-phrase | step-mechanic | named-domain-practice) and the anchor
  itself.
- REJECTED candidates (entity-level) — for each, the candidate name and
  the reason: failed actor boundary, failed anchor test (template claim
  only), attribute / UI label, etc.
- DROPPED steps — for each, the entity, the step name, and which anchor
  failed. Empty unless preservation discipline (rule 7) caused a removal.
- ACTOR-LIKE candidates — for each, the actor name moved to roles for
  Pass 3 to consider.
- LIFECYCLE COVERAGE — for each kept entity, the dimensions from the
  persona's LIFECYCLE DIMENSIONS block that this entity was decided to
  exercise (with the anchor for each exercised dimension) and the
  dimensions decided empty (with the reason each empty one is empty).
  This section is the reviewer-visible result of Scan 4c; an entity
  whose final step list looks like create / update / delete / read must
  show here which dimensions were considered and why none of the richer
  ones earned an anchor.
"""

_PASS1_AUDIT = """\
PASS 1 REVIEW - FLOW CONSISTENCY AUDIT

Goal:
Return the corrected FlowPass using the same schema. Do not add a new artifact
shape. This is a consistency review of the draft flow, not a new product design.

Read the INVENTION DISCIPLINE block in the agent persona before producing this
pass. Apply the same anchor, system-action, and preservation rules to the
audit decisions.

Project signal:
{signal}

Draft flow:
{flow}

Audit method:
1. Re-run the actor boundary test:
   - concepts that answer who participates, receives, owns, approves, benefits,
     or is affected must not be entities;
   - if actor information is managed, keep only the managed record/process
     when it has its own lifecycle;
   - otherwise move the actor candidate to notes for the role pass.

2. Re-run the operational object test:
   - if an existing entity step depends on something being allocated, made
     available, occupied, consumed, transferred, blocked, reconciled, or
     released, and the domain gives that object a natural role, include the
     minimum operational entity;
   - if that object is only a policy, measurement, attribute, or vague
     context, reject or defer it in notes.

3. Re-run the orphan concept test:
   - if notes, entity purposes, or step details rely on an object as
     allocated, available, occupied, consumed, transferred, blocked,
     reconciled, or released, that object must either be present as an
     entity or explicitly rejected in notes with a reason.

4. ANCHOR AUDIT on every entity's signal field. The signal must cite one
   of: an exact phrase from the project signal, a mechanic implied by a
   kept step (named), or a specific named domain practice. Phrases such
   as "often a feature in [genre] apps", "apps of this kind tend to have
   one", "common in [domain]", "users typically expect", "industry
   standard" are template claims, not anchors. For each entity whose
   signal reads like a template claim:
   a. If a real anchor exists for the entity, rewrite the signal to cite
      it (signal-phrase | step-mechanic | named-domain-practice) and
      record the rewrite in notes.
   b. If no real anchor exists, REMOVE the entity from the flow and
      record the removal in notes with the failed anchor.

5. PERFORMER LABEL AUDIT on every step. Step.detail must name the
   performer in one of three forms: a human role label, "the system",
   or "an external party" naming the actor. For each step whose detail
   is missing the performer or uses placeholders ("the appropriate
   actor", "the application", passive voice), rewrite the detail to
   include the most defensible performer:
   - default to "the user" (or the named user-side role) when the
     project signal plainly puts the action in user hands;
   - default to "the system" when the step is generation, computation,
     derivation, or rendering that no human visibly performs;
   - default to "an external party" only when the project signal names
     the external actor.
   Record performer rewrites in notes so the role pass can see the
   anchor explicitly.

6. STEP PRESERVATION AUDIT. Compare the draft flow against the project
   signal and against ordinary lifecycle expectations for each entity:
   - if the user creates an entity, they typically can also review it;
   - if the user writes a reflection, they typically can also read it
     back;
   - if the system generates an output, the user typically can view and
     filter that output.
   When a plausibly-implied step is missing — for example a Review,
   View, Read, Filter, or Browse step on an entity whose creation is
   already in the flow — restore it with the correct performer label.
   The draft may have trimmed these steps when adding a new entity;
   undo the trim. Record restorations in notes.

7. STEP RICHNESS AUDIT. For each kept entity, check whether its step
   list reduces in effect to a four-verb create / update / delete /
   read list, or to a 1:1 synonym mapping over those four moments. If
   it does, run the LIFECYCLE DIMENSIONS scan from Pass 1 step 4c
   again for this entity with two specific checks:
   a. Verb selection. For each existing CRUD-shaped step, ask
      whether the domain's own named practice uses a more precise
      verb for this moment than the draft chose. When it does,
      rewrite step.name to the domain's verb and update step.detail
      to match; record the rewrite in notes as a STEP RICHNESS
      RECOVERY (kind=verb-rename).
   b. Missing dimensions. Walk Enrichment, Consumption sub-moments,
      and Cross-reference in turn. For each, ask whether the signal
      phrase, the entity's purpose phrase, or another kept step's
      mechanic anchors a step under that dimension for this entity.
      When it does, add the step with a concrete performer label and
      record the addition in notes as a STEP RICHNESS RECOVERY
      (kind=missing-dimension), naming the dimension and the anchor.
   When this audit leaves an entity with steps that still reduce to
   the four-verb list, the audit notes must defend that result by
   naming the dimensions considered and why each empty dimension is
   honestly empty for this entity (for example, the domain treats
   the entity as a bare row with no enrichment moment, or the
   product has no place where the practitioner returns to the
   entity beyond reading it). Silent collapse to the four-verb list
   is the failure mode this audit exists to prevent; a passing
   entity either carries richer steps or carries an explicit defense
   of its CRUD shape.

8. Keep the flow compact. Do not add actors, screens, broad
   organizations, implementation components, generic data, qualities,
   or scope boundaries as entities.

9. Preserve good draft entities and steps unless the audit shows a
   classification error, an anchor failure (rule 4), or a missing
   performer the draft cannot defend.

Notes must summarize the audit decisions in the same compact format as
Pass 1 (KEPT, REJECTED, DROPPED, ACTOR-LIKE, LIFECYCLE COVERAGE) and
additionally include:
- ANCHOR REWRITES — entities whose signal field was rewritten under
  rule 4, with the old phrasing and the new anchor type.
- ENTITIES REMOVED FOR FAILED ANCHOR — under rule 4b.
- PERFORMER REWRITES — steps whose detail was changed under rule 5,
  with old detail and new performer.
- STEPS RESTORED — steps added back under rule 6, with the entity and
  the anchor that justifies restoration.
- STEP RICHNESS RECOVERIES — entries added or rewritten under rule 7,
  one line per recovery in the form
    <entity> <step> kind=<verb-rename | missing-dimension>
    dimension=<Genesis | Enrichment | Transition | Mutation |
    Consumption | Termination | Cross-reference>
    anchor=<the concrete signal phrase, purpose phrase, or step
    mechanic that justifies the recovery>.
  When an entity exits the audit with a step list that still reduces
  to create / update / delete / read, add a CRUD-DEFENSE line for it
  naming each LIFECYCLE DIMENSION that was considered empty and the
  reason it is honestly empty for this entity. The absence of such a
  defense for a CRUD-shaped entity is itself an audit failure.
"""

_PASS2 = """\
PASS 2 - LINKS

Goal:
Explain cross-entity dependencies in the reviewed flow. Two kinds of
dependency are legitimate here, corresponding to the link.trigger
schema description:

  Type (a) - state-change link. A step on the source entity causes a
  state change on the target entity (allocation, availability,
  occupancy, release, transfer, blocking, reconciliation, transition).

  Type (b) - cross-reference link. A step on the source entity cannot
  function as the domain expects without records belonging to the
  target entity being juxtaposed, correlated, aggregated, or
  referenced. This is the Cross-reference dimension in the persona;
  the source step is typically a Consumption-dimension step (review,
  compare, summarize, look for a pattern) whose purpose phrase or
  detail explicitly involves the target entity.

Read-only flow:
{flow}

Method:
1. Consider only entities already present in the flow.

2. Add a type (a) link when a step on one entity changes another
   entity's valid behavior, state, or timing.

3. Add a type (b) link when a step on the source cannot perform its
   domain function without target records. A type (b) link is
   legitimate only when link.detail can quote the concrete anchor
   that demands the cross-reference: the signal phrase, the source
   entity's purpose, or the source step's own wording. A step is a
   strong type (b) candidate when its name or detail uses words like
   compare, correlate, juxtapose, look for a pattern across,
   summarize alongside, align with — and the target entity is what is
   being looked at alongside.

4. Shared actors or shared subject matter are NOT enough on their
   own. "Both entities belong to the same product", "the same user
   touches both", "they sit in the same area of the app", or "the
   theme of the product spans both" do not earn either type of link.
   When that is the only justification available, omit the link and
   say so in notes.

5. When a primary entity uses an operational entity from the same
   flow, add type (a) links for allocation, availability, occupation,
   release, transfer, blocking, or reconciliation moments that are
   represented by existing steps.

6. Omit uncertain dependencies and explain the omission in notes.
   "Not explicit" is not enough when the reviewed flow already
   contains an operational entity whose lifecycle is changed by
   another entity, AND it is not enough when a source step's name or
   detail names a target entity to be cross-referenced.
"""

_PASS3 = """\
PASS 3 - ROLES

Goal:
Identify human and organizational stakeholders that shape requirements for
this product. The performer labels in the reviewed flow are the primary
license for any role you emit.

Read the INVENTION DISCIPLINE block in the agent persona before producing
this pass. The system-action rule and the internal-build-team rule are
load-bearing here: this pass is the most frequent site of role invention,
and the discipline applies regardless of how the pass-specific instructions
below are read.

Read-only flow:
{flow}

Read-only links:
{links}

Method:
1. Walk every entity step and read the performer label in step.detail.
   Build an internal table in your reasoning of:
     step -> performer label.
   The set of distinct human and external-party performer labels in this
   table is the primary anchor set for the role roster.

2. PERFORMER-LABEL LICENSE. A role appears in the roster only when one of
   the following anchors is present:
   a. a human performer label ("the user", "the reviewer", "the operator",
      etc.) appears in at least one step.detail — emit a role whose name
      matches that label and whose kind reflects what the role actually
      does (see rule 5);
   b. an external party performer label appears in at least one step.detail
      AND the external actor meaningfully shapes requirements (not merely
      a passive downstream consumer) — emit a partner role;
   c. the project signal names a human or organizational stakeholder
      outside the step performers (an audience that benefits from outputs,
      an authority that mandates behavior) AND you can name the specific
      step, signal phrase, or duty where their interest is felt — emit an
      inferred role with that anchor recorded.
   No other route creates a role. If you find yourself reaching for a role
   without one of these three anchors, you are inventing.

3. SYSTEM-PERFORMED STEPS DO NOT CREATE ROLES. When a step's performer is
   "the system", that step is entity behavior, not a missing duty owner.
   Do not invent a Data Analyst, Algorithm Owner, Maintainer, Developer,
   DevOps, Administrator, Trend Owner, or similar role to "own" the
   system-performed step. The product's build team is not a stakeholder
   of the product in the schema's sense; they are the team building it.
   The human role that consumes or triggers the system behavior (typically
   the user) is the affected role, and the system step itself anchors no
   new role.

4. INTERNAL BUILD TEAM BAN. The following role names and their close
   variants are forbidden UNLESS the project signal explicitly names the
   role as a stakeholder of the product itself (e.g. an admin-facing
   product whose user IS an administrator):
     Developer, Data Analyst, Algorithm Owner, Maintainer, Engineer,
     DevOps, Support, Operations, Administrator, System Owner.
   When a quality category seems to need one of these roles to make
   sense (maintainability is the typical case), the answer is to drop
   the category in Pass 6, not to invent the role here.

5. EXTERNAL ACTORS already classified out of the flow. If a person,
   organization, or audience noun was rejected from the entity flow
   because it is an actor rather than a managed object, reconsider it
   here as a role candidate when its experience, request, outcome,
   permission, or governance authority shapes requirements.

6. Choose kind by the role's relationship to the product work:
   - operator: performs recurring product work; most of the role's
     anchor steps have this role as the performer label;
   - partner: acts on the product but it is not their central job, or
     receives outputs while being materially affected by the flow;
   - authority: decides or approves; reserve this kind for a role the
     project signal or a named domain practice plainly puts in a
     decision or approval position. Do not use authority as a catch-all
     for "owner of system behavior" or "responsible for the algorithm".

7. Keep only roles that can meaningfully shape requirement discovery.

Sizing guardrail:
- The role roster cannot exceed the count of distinct human and
  external-party performer labels in the flow, plus AT MOST one or two
  inferred stakeholder roles anchored under rule 2c. If your roster is
  larger than the performer-label set, you are inventing.
- A role and an entity may share a name only when the product also
  manages that actor's separate record as a domain object.
- Do not drop a beneficiary or service recipient merely because they
  are not an operator. If their experience, permissions, data, wait,
  status, request, or outcome shapes requirements, model them as a
  partner role.

Notes must include a per-role audit line in this form:
  ROLE <name>: anchor=<performer-label | signal-phrase | named-domain-
  practice>; evidence=<the step where the performer label appears, or
  the signal phrase, or the named domain practice>; kind=<operator |
  partner | authority>.
And a per-rejection audit line for any role candidate you considered
and dropped:
  REJECTED <candidate>: reason=<system-performed-step-only | internal-
  build-team | unanchored-template | other>.
If the only candidates the flow's system-performed steps would
generate are internal build team roles, the notes must say so
explicitly and confirm the roster has no such role.
"""

_PASS4 = """\
PASS 4 - DUTIES

Goal:
Turn the reviewed role roster into duties that can drive interview agenda items.

Read the INVENTION DISCIPLINE block in the agent persona before producing this
pass. In particular: a schema slot is not a license to fill, system action is
not unowned duty, and internal build team is not a stakeholder. Duties exist
to surface interview questions about human responsibility, not to assign
ownership to every step the system performs.

Read-only flow:
{flow}

Read-only links:
{links}

Read-only roles:
{roles}

Method for each role:
1. SYSTEM-PERFORMED STEP RULE. Before walking the flow, mark every step
   whose performer label is "the system". Such steps do not automatically
   generate a duty. They generate a duty for a human role only when there
   is a real interview question to ask the human about it — typically
   when:
   - the human role triggers, configures, or consumes the system behavior
     at this step, or
   - the human role has a tolerance, expectation, or recovery story for
     the system behavior that can be tested as a duty.
   When neither applies, the system step is entity behavior captured in
   the entity itself; do NOT emit a duty for it under any role. In
   particular, do not pin system behavior on an authority role to make
   the ownership question go away.

2. Walk the flow and decide where the role creates work, makes a decision,
   enforces a limit, protects an access rule, or depends on another system.
   The performer label in step.detail is the primary anchor: when the
   performer label matches the role, that step is a strong duty candidate.

3. Build a coverage matrix in notes: role x primary entity x meaningful
   action. Use it to prevent missing duties for entities where the role's
   performer label clearly appears. Use it equally to prevent duties for
   entities where the role's performer label never appears.

4. Cover every primary capability entity before adding duties for inferred
   operational entities. When multiple primary entities share an inferred
   operational resource, duties must not collapse into only the shared
   resource.

5. For each primary entity, emit at least one concrete duty for each role
   that can create, change, cancel, enter, leave, approve, or depend on
   that entity.

6. Emit additional duties for inferred operational entities only when they
   expose a distinct responsibility such as allocation, availability,
   occupancy, release, or reconciliation.

7. Emit a duty when it gives an interviewer something concrete to verify.
   A duty may be a permission or responsibility whose exact rule is still
   open.

8. Do not compress separate lifecycle actions into one duty when the
   condition, permission, owner, or risk differs.

9. Anchor each duty to one entity and one step where it becomes
   interviewable. If an idea spans entities, choose the clearest touchpoint
   and use refs.

10. Do not add duties for template-only operations or policy details.
    Mention uncertain domain assumptions in notes only.

11. risk must state an interview-useful failure scenario: the role
    affected, the condition that makes the duty matter, and the failure
    outcome if the rule is wrong, missing, or ambiguous. Avoid generic
    risk labels.

12. Aspect classification routine. Before writing aspect for a duty, run
    the removal test in this order and stop at the first match:
    a. Remove the rule mentally from the product. Describe what would
       actually go wrong, who would feel it, and at which step.
    b. If a flow step would no longer be performable, sequenced correctly,
       conditioned correctly, retried, paused, cancelled, or recovered as
       the domain expects -> operational_rule. This includes the baseline
       "the role can do its own work" rules in products where the role is
       alone with its artifact, because removing them collapses the flow
       itself, not a guard around it.
    c. If a measurable operating limit (capacity, latency, freshness,
       retention, accuracy) would disappear -> boundary_nfr.
    d. If a connection to an external system, party, or data source would
       disappear -> integration.
    e. If the rule is the only thing keeping a specific other actor or
       other context from reaching the same artifact, and that other actor
       or context actually exists in the reviewed roster or flow, with the
       technical ability to act -> permission. Name that other locus in
       notes. If you cannot name it from the reviewed vision, the rule is
       not a permission; revisit (b) through (d).
    Surface phrasing such as "the user must be able to...", "only X may...",
    or "X has permission to..." does not select the aspect. The removal
    test does. Two duties phrased the same way can land on different
    aspects in different products, and the audit notes must record which
    test arm fired for any duty whose aspect is not obvious.

13. priority is a reviewer-facing importance estimate.

14. entity_refs and flow_step_refs are optional trace anchors.

15. Do not use duties to store NFR softgoals.

16. Notes must include:
    - the coverage matrix from step 3;
    - a short audit line for each duty whose aspect was a judgement
      call, naming which arm of step 12 fired and (for permission) which
      second locus from the reviewed vision justified the choice;
    - when all duties in this pass land on the same aspect, one or two
      sentences explaining why each other arm of step 12 was rejected by
      name, as a sanity check against pattern-matching;
    - a per-system-step audit line for each step whose performer is
      "the system", saying either "no duty emitted (entity behavior)"
      or naming the human role and the trigger / consume / tolerance
      reason that justified emitting a duty about it.
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

Read the INVENTION DISCIPLINE block in the agent persona before producing this
pass. The schema-slot rule, the internal-build-team rule, and the tautology
rule apply directly: every NFR category is here because SOME product needs it,
not because this product needs all of them, and the audit block's collapse
reason is the most frequent place where tautology slips through.

Read-only flow:
{flow}

Read-only links:
{links}

Read-only roles and duties:
{roles}

Method:
1. Scan only for quality concerns anchored to an existing entity, step, link,
   role, or duty in the reviewed vision.

2. ROLE EXISTENCE TEST. The role named in affected_roles MUST already exist
   in the reviewed roster from Pass 3. Do not invent roles such as
   "Developer", "Administrator", "Support", "Operations", "Data Analyst",
   "Algorithm Owner", "Maintainer", or "DevOps" to justify a category.
   When you find yourself wanting to attach a concern to a role that is
   not in the roster, the correct move is to drop the concern, not to
   reach back and add the role.

3. CATEGORY SCOPE TEST. Some categories tempt invention of internal-team
   roles because the lived-use side has no obvious owner for them:
   - maintainability typically applies to whoever modifies the product
     after release. If no human role in the roster does that work
     (i.e. the team itself is not modeled as a stakeholder of the
     product), drop maintainability and note the omission;
   - similarly drop compatibility, certain reliability sub-themes, and
     any other category whose anchor lives entirely on the product's
     development or operations side rather than its lived-use side,
     when no roster role inhabits that side.
   Dropping a category because no roster role inhabits it is not
   coverage loss — it is the schema honestly returning empty for slots
   this product does not need.

4. Fill category, theme, attached_to, affected_roles, and rationale.

5. SURFACE GRANULARITY. Choose attached_to at the granularity where the
   role's lived experience or tolerable failure for this quality is
   actually distinct.
   a. A quality "surface" is a (entity, step) where the role's
      expectation, operating condition, or breakdown story for this
      concern is distinct from elsewhere. Two steps that share the same
      patience budget, the same breakdown story, and the same recovery
      expectation are one surface; two steps that differ on any of
      those are two surfaces.
   b. Attach to specific steps when the quality is experienced during
      an action — patience while typing, trust while reading history,
      ease of navigation, error feedback during input. List every step
      that is a distinct surface; collapse steps only when their lived
      experience is genuinely the same.
   c. Attach to an entity (not a step) only when the quality is a
      property of the managed data itself rather than of any action on
      it — confidentiality of stored records, integrity over time,
      retention obligations. In that case the concern is felt regardless
      of which step is running.
   d. Do not default to "all steps of an entity" or "all entities".
      Broad attachment is a shortcut that hides where the interview
      should actually probe.

6. TAUTOLOGY CHECK on collapse reasoning. After drafting a concern's
   audit block, read the collapse field and reject it if it matches any
   of these patterns:
   - "all X involve Y" / "all steps involve [the user / the entity / the
     experience]";
   - "affects [user satisfaction / experience / engagement] uniformly";
   - "the whole [app / product / experience / flow] matters";
   - "applies broadly" / "applies across the product";
   - "shares the same need" without naming the specific need;
   - "users care about this everywhere";
   - "this is a general concern";
   - any restatement that the slot is broad without naming the specific
     distinguishing patience budget, breakdown story, or recovery
     expectation that justifies treating the surfaces as one.
   A valid collapse names the specific shared property: e.g.
   "all three log-entry surfaces share the same sub-second patience
   budget and the same recovery story — discard the half-typed entry
   and retry — distinct from review surfaces where patience is longer".
   When the collapse cannot be written without tautology, the concern
   must split into distinct anchored concerns (one per truly distinct
   surface) or drop.
   The category quality_in_use is the most frequent tautology trap:
   "engagement" or "satisfaction" applied to every entity is almost
   always tautological. If you reach for quality_in_use, name the
   specific lived moment the concern is about (logging an entry,
   reviewing past entries, writing a reflection) and attach only to
   that moment. If you cannot, drop the concern.

7. Use ids in CONCERN-NN format when consistent.

Guardrails:
- A concern is a softgoal, not a requirement. Do not write thresholds,
  SLAs, numeric targets, retention periods, technologies, vendors,
  architecture, encryption standards, or acceptance criteria.
- Do not emit a concern for every category by default.
- If you cannot anchor a concern to existing artifacts, drop it.
- Notes must contain a per-concern audit block, one block per concern,
  in this shape:
    CONCERN-NN: surfaces=<entity-level | list of (entity, step)>;
    reason=<why these surfaces and not others are the places where the
    role's lived experience for this quality differs>;
    collapse=<if multiple steps share one surface, the shared patience
    budget, breakdown story, or recovery expectation that justifies the
    collapse — concrete and distinguishing, not tautological per
    rule 6 — else "n/a">.
  A single trailing summary line does not satisfy this requirement;
  each concern needs its own block.
- Notes must also include a DROPPED-CATEGORIES line listing the
  catalog categories you considered and rejected under rule 3 (role
  existence) or rule 6 (tautology), with the reason for each.
- If a concern attaches to more than three steps, its audit block must
  explicitly defend that the lived experience is uniform across all of
  them WITHOUT using tautology phrasings from rule 6. If the defense
  names two or more different patience budgets, breakdown stories, or
  recovery expectations, the concern must be split or narrowed before
  emitting — do not write the broad attachment and then describe the
  split only in prose.
- Broad unjustified attachment will be downgraded to a single
  representative surface by downstream agenda construction.
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
            include_thinking=True,
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
            include_thinking=True,
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
            include_thinking=True,
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
            include_thinking=True,
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
            include_thinking=True,
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
            include_thinking=True,
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
            include_thinking=True,
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