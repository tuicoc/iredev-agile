"""
visionary.py - VisionaryAgent

VisionaryAgent reads a project intent and produces a lean Product Vision.
Downstream agents (Agenda, Interviewer, EndUser, Distiller) consume the
roles, assumptions, concerns, and scope.

Execution: two sequential extract_structured passes.
- Pass 1 (READ): input → description, intent_summary, target_outcome,
  known_signals, roles, notes. The LLM spends its entire attention on the
  input-reading + role-inventory task here.
- Pass 2 (FORKS): given Pass 1 output (especially roles), produce
  assumptions (forks), concerns, scope. The LLM spends its entire attention
  on the design-decision task here.

Python responsibilities:
- assigns IDs deterministically (ROLE-NN, ASM-NN, CONCERN-NN, OOS-NN);
- assembles the two pass outputs into the final ProductVision artifact;
- merges the two pass `notes` into one reviewer audit paragraph.

Schema descriptions say *what* a field holds. Prompt bodies teach *how*
to reason — 4 core principles, active scans, self-tests — domain-neutral.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseAgent

logger = logging.getLogger(__name__)


<<<<<<< Updated upstream
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

=======
SourceLens = Literal["stated", "implied", "inferred"]


# ─────────────────────────────────────────────────────────────────────────────
# Lean Product Vision schema
# ─────────────────────────────────────────────────────────────────────────────
>>>>>>> Stashed changes

class Role(BaseModel):
    id: str = Field(default="", description="Leave empty; Python assigns ROLE-NN in emission order.")
    name: str = Field(description="Singular noun the role uses for itself, no market/geography/vertical qualifiers.")
    need: str = Field(description="One sentence on what this role expects at runtime — what they do, notice, or are shaped by.")
    lens: SourceLens = Field(description="How this role was reached. stated: input directly names the label. implied: input names a runtime activity that requires this role without naming the label. inferred: input is silent on both; generic product knowledge supplies the role.")
    anchor: str = Field(description="One sentence justifying the lens. For stated/implied: cite the input phrase or claim. For inferred: name the specific generic product knowledge that supplies the role.")


class Assumption(BaseModel):
    id: str = Field(default="", description="Leave empty; Python assigns ASM-NN in emission order.")
    statement: str = Field(description="One uncertainty about a design decision the first release cannot avoid making. State it as a FORK — preferring option A over alternative B, naming a sub-group's distinct need, or stating which side of a boundary the product takes.")
    why_it_matters: str = Field(description="One sentence on the downstream decision this fork could move: a requirement, quality boundary, scope edge, conflict, or first-release choice.")
    lens: SourceLens = Field(description="stated / implied / inferred — same meaning as for roles.")
    anchor: str = Field(description="One sentence justifying the lens. For stated/implied: cite the input phrase or named claim. For inferred: name the specific generic product knowledge that surfaces the fork.")


class Concern(BaseModel):
    id: str = Field(default="", description="Leave empty; Python assigns CONCERN-NN in emission order.")
    theme: str = Field(description="One keyword for a user-perceptible quality: clarity, timeliness, recoverability, accessibility, effort, consistency, confidence, trust.")
    affected_roles: List[str] = Field(default_factory=list, description="Canonical role names from this vision that would notice when this quality slips.")
    rationale: str = Field(description="One sentence on why this quality is worth raising as an elicitation topic.")
    lens: SourceLens = Field(description="stated / implied / inferred — same meaning as for assumptions.")
    anchor: str = Field(description="One sentence justifying the lens.")


class Boundary(BaseModel):
<<<<<<< Updated upstream
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
=======
    id: str = Field(default="", description="Leave empty; Python assigns OOS-NN in emission order.")
    item: str = Field(description="One product responsibility the project intent excludes or wants kept outside the first release.")
    reason: str = Field(description="One sentence on why the boundary should stay visible to downstream agents.")
    lens: SourceLens = Field(description="stated / implied / inferred — same meaning as for assumptions.")
    anchor: str = Field(description="One sentence justifying the lens.")
>>>>>>> Stashed changes


class ProductVision(BaseModel):
    description: str = Field(description="Reader-facing overview of the requested product in two or three sentences.")
    intent_summary: str = Field(description="One sentence on what the project intent is asking for.")
    target_outcome: str = Field(description="One sentence on the outcome the product should help create for its users or affected roles.")
    notes: str = Field(description="Reviewer-facing audit paragraph combining Pass 1 reading observations with Pass 2 forks commentary.")
    known_signals: List[str] = Field(default_factory=list, description="Independent concrete facts about the world or work that the input named. One per entry; combine paraphrases.")
    roles: List[Role] = Field(default_factory=list)
    assumptions: List[Assumption] = Field(default_factory=list)
    concerns: List[Concern] = Field(default_factory=list)
    scope: List[Boundary] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Per-pass shapes
# ─────────────────────────────────────────────────────────────────────────────

class ReadingPass(BaseModel):
    description: str = Field(description="Reader-facing overview of the requested product in two or three sentences.")
    intent_summary: str = Field(description="One sentence on what the project intent is asking for.")
    target_outcome: str = Field(description="One sentence on the outcome the product should help create.")
    notes: str = Field(description="Reviewer-facing reading observations — what was read directly, what the inventory walk surfaced, any sparsity/density notes.")
    known_signals: List[str] = Field(default_factory=list)
    inventory_candidates: List[str] = Field(default_factory=list, description="Quoted noun-phrase candidates from the input that name a person/group/job-title that does something or experiences something at the product's runtime. Materialize the inventory walk by listing every such phrase BEFORE consolidating to `roles`. Each entry is one short quoted phrase from the input. Empty list is only acceptable for truly one-line inputs that name no role.")
    roles: List[Role] = Field(default_factory=list)


<<<<<<< Updated upstream
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
=======
class ForksPass(BaseModel):
    notes: str = Field(description="Reviewer-facing forks commentary — lens distribution, which forks earned a place, anything notable.")
    assumptions: List[Assumption] = Field(default_factory=list)
    concerns: List[Concern] = Field(default_factory=list)
    scope: List[Boundary] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1 prompt — READ + ROLES
# ─────────────────────────────────────────────────────────────────────────────

_READ_BODY = """\
PASS 1 OF 2 — READ THE INPUT AND BUILD THE ROLE LIST

This pass extracts: description, intent_summary, target_outcome,
known_signals, roles, notes. It does NOT produce assumptions,
concerns, or scope — Pass 2 handles those once the role list is
fixed.

CORE PRINCIPLES (apply throughout)

P1. THE PRODUCT DOES NOT EXIST YET. Every fact you cite about a
role's behavior must come from TODAY's life. A stakeholder today
can say what they tried / noticed / decided about today; they
cannot describe their reaction to the unbuilt product.

P2. INVENTORY BEFORE CONSOLIDATE. For roles, the default is to
keep every named label separate. Merge only when the input itself
says two labels do the same thing.

P3. HONEST SOURCE TRAIL. Each role carries a `lens` enum (stated /
implied / inferred) and an `anchor` sentence specific enough that
a reviewer can verify it against the input.


READING THE INPUT

Walk the input phrase by phrase. For each phrase, decide:
- Concrete fact about the world or the work as it is TODAY →
  `known_signals`. Each entry independent; one could be false
  without the others also being false. Combine paraphrases.
- A wish about what the product should make true once shipped →
  fold into `target_outcome` / `description` / `intent_summary`.

A wish is not a signal. Sparse input that has only a one-line
intent may legitimately produce an empty or very short
known_signals list — that is honest.


ROLE INVENTORY — ACTIVE SCAN (THE CRITICAL STEP)

Step 1 (catalogue every name — WRITE THEM DOWN, do not just
think them):
Read the input and collect EVERY noun phrase that names a
person, group, or job-title that does something or experiences
something at the product's runtime. Emit them into the
`inventory_candidates` field as quoted phrases from the input.
This step is OUTPUT-required, not mental: writing the candidates
down forces the inventory walk to actually happen instead of
being skipped under pressure from the umbrella-merge temptation.
Do this BEFORE you reach for any umbrella term.

Step 2 (perspective filter):
For each candidate, ask: "if we remove the product, does this
person's runtime behavior change?"
If no → they are a stakeholder for context (sponsor, funder,
governance, problem-observer, person who motivated the work).
Mention them in `notes` or in `target_outcome` motivation —
never in `roles`.

Step 3 (consolidation gate — DEFAULT IS KEEP SEPARATE):
Only merge two surviving candidates when EITHER:
  (a) the input itself says they do the same thing, OR
  (b) one is a strict instance of the other AND the input
      gives no signal that their runtime activity differs.
An umbrella term ("staff", "team", "users", "audience") that the
input uses alongside two specific labels does NOT meet (a) or (b)
— the umbrella is editorial, the specific labels mark different
runtime activities. Keep them as separate roles.

Step 4 (in-group expansion):
If the input flags an in-group whose experience differs from a
generic role ("<role> who have been through <X>", "<role> in
situation <Y>", "we don't want to flatten everyone into one
audience"), emit the in-group as its OWN role distinct from the
generic. Walk EVERY flagged in-group; do not pick one and skip
the rest.

Step 5 (sparse-input guarantee):
For a one-line intent, a primary user is still reachable from
the actor + action + object. Include it; lens = inferred; anchor
names how the product shape supplies the role.


WRITING ROLES

- `id`: leave empty. Python assigns ROLE-NN.
- `name`: singular noun the actor would use for themselves. Strip
  market / geography / vertical / demographic qualifiers unless
  needed for disambiguation against another role.
- `need`: one sentence on what they expect at runtime — what they
  do, notice, or are shaped by. Not duties, not policies.
- `lens`: stated (input names the label) / implied (input names
  the activity but not the label) / inferred (silent — generic
  product knowledge supplies it).
- `anchor`: for stated/implied, cite the input phrase exactly. For
  inferred, name the specific generic principle (e.g., "products
  of this shape always need a <X> party because <Y>"). Vague
  glue ("generic product knowledge", "industry practice")
  without naming the principle fails the trail.


WRITING notes (this pass)

One coherent paragraph for a reviewer:
- briefly describe what the input named directly vs what reading
  leaned on;
- mention the inventory walk decisions a reviewer should validate
  (in-groups split, umbrella terms declined, named labels kept
  separate, candidates filtered as stakeholders);
- surface anything notable about the input's sparsity or density.

Do NOT write assumptions, concerns, or scope here. Pass 2 will
generate those.
>>>>>>> Stashed changes
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2 prompt — FORKS, CONCERNS, SCOPE
# ─────────────────────────────────────────────────────────────────────────────

<<<<<<< Updated upstream
Read the INVENTION DISCIPLINE block in the agent persona before producing this
pass. Apply the same anchor, system-action, and preservation rules to the
audit decisions.

Project signal:
{signal}
=======
_FORKS_BODY = """\
PASS 2 OF 2 — DESIGN FORKS THE FIRST RELEASE OWES
>>>>>>> Stashed changes

Pass 1 has already extracted the input reading and the role list
below. You receive that as ground truth. Your job: produce
assumptions (design forks), concerns (quality dimensions), scope
(boundaries) — and a notes commentary.

<<<<<<< Updated upstream
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
=======
CORE PRINCIPLES (apply throughout)

P1. THE PRODUCT DOES NOT EXIST YET. Forks are decisions the
first release must make. They are NOT hypotheses about how users
will react to the finished product — dialogue cannot settle those.

P2. EVERY ASSUMPTION IS A FORK. State the LOSING alternative in
one phrase. Effectiveness hypotheses ("users will use X", "the
product will reduce Y", "X is more engaging than Y") that name no
losing alternative are not forks.

P3. HONEST SOURCE TRAIL. Each assumption / concern / boundary
carries a `lens` enum (stated / implied / inferred) and an
`anchor` sentence specific enough that a reviewer can verify.


PASS 1 OUTPUT (ground truth — DO NOT modify, only consume)
{reading}


MACRO FORK CHECK — DIRECTION VS SUB-FEATURE
(run this FIRST, before drafting assumptions)

A single project intent can often be satisfied by several
distinct overall DIRECTIONS — different kinds of product that all
meet the target_outcome but land at fundamentally different
first-release builds. Surface that direction-level uncertainty as
ASSUMPTIONS; do not silently lock to one direction and proceed.

Direction-level forks include (not exhaustive):
  * scope of the product (what it does vs leaves to others)
  * primary subject of the product (which audience it centers
    on when several are mentioned)
  * authority source (whose endorsement the product speaks
    under, when input names multiple possible authorities)
  * sponsoring body or partnership
  * strategic priority when input names several distinct
    outcomes that pull in different first-release directions
  * brand voice or institutional alignment

State each surfaced direction-level fork as an assumption using
the phrasing patterns in the ASSUMPTIONS section below — naming
the LOSING alternative so the reviewer can override at HITL with
feedback if needed.

DIRECTION SUFFICIENCY SELF-TEST (apply once before submitting):
"If a developer read ONLY the target_outcome, the roles, and the
assumptions, could they build TWO products that both satisfy
everything but are fundamentally different things?"
If yes — a direction-level fork is still hiding implicit.
Surface it as an assumption and re-emit.


ASSUMPTIONS — FORK SELF-TEST AND LENSES

Before emitting EACH assumption, run the FORK SELF-TEST:
  "What is the LOSING alternative if dialogue weakens this
   statement? Can I name it in one phrase?"
If you cannot name a losing alternative, the line is an
effectiveness claim or a restatement of input — drop or rewrite.

Required phrasing patterns (use whichever fits):
  - "<option A> is more useful than <option B> for <purpose>"
  - "<feature> belongs <here> rather than <there>"
  - "<X> works better as <shape A> than as <shape B>"
  - "<sub-group> needs <C>, distinct from what <other group>
    needs"
  - "The product should <decide D> rather than <leave it to the
    role / mirror the existing process>"

Forbidden (post-launch effectiveness — dialogue cannot settle
these):
  - "Users WILL use <feature>."
  - "Users WILL find <product> valuable / recommendable."
  - "<Product> WILL be effective at <outcome>."
  - "Users WILL feel <emotion> after using <product>."

Also forbidden (already-decided system-scope choices that belong
in SCOPE, not assumptions):
  - "The product will function alongside <X>, rather than replace
    it." → if input states this, the BOUNDARY is "product does
    not replace <X>" → emit as OOS.
  - "The product will not be <a type of authority/system>." →
    emit as OOS.
A statement of what the software will NOT do is not a dialogue
fork — it is a scope boundary. Do not duplicate it as an ASM.

Three lenses for how a fork surfaced:

- STATED: input names the uncertainty directly. Walk each
  `known_signal` as a claim and ask "what is the uncertainty
  INSIDE this claim?" Anchor cites the input line.

- IMPLIED: input does not name the uncertainty, but its own
  claims would not hold together without a decision here. Anchor
  cites the input claim that forces the decision.

- INFERRED: input silent at both layers above. Generic product
  knowledge says the first useful release owes a decision here.
  Anchor names the specific generic knowledge — for example, a
  product-pattern (a product producing output owes a way to
  recover from being wrong; a product orchestrating timing owes
  the affected roles a view into that timing; a product
  connecting two parties owes each a boundary on what crosses
  through; a product depending on an external source of truth
  owes a way to notice source changes; a product next to an
  authority owes a view of what it does not decide; a product
  relying on user cadence owes a handling of moments the user
  is absent; a product with multiple participants owes a
  handling of disagreement, silence, or handoff), a product-
  shape inference (the actor + action + object forces a basic
  structural choice), or a typical role-decomposition. If none
  fits, write your own specific principle — but it must be
  specific. Vague glue ("generic product knowledge", "industry
  practice") without naming the principle fails the trail.

Sparse input rhythm: a one-line input typically yields more
inferred than stated assumptions. Walk multiple bases (different
product-patterns, the product-shape, role-decomposition) — for
each, ask whether the product owes a fork there. Sparse inputs
usually produce 3-6 distinct inferred forks across different
bases. Do not stop at 1-2 generic ones.

Anti-bundle: one assumption holds one fork whose evidence would
move one downstream decision. Connectives ("and", "or") can
hide a bundle. Split when two distinct forks are present.

`id`: leave empty. Python assigns ASM-NN.


CONCERNS — USER-PERCEPTIBLE QUALITY

A concern names a quality whose acceptable boundary is not yet
clear, felt by the product user when it slips. Themes: clarity,
timeliness, recoverability, accessibility, effort, consistency,
confidence, trust.

Theme self-test: "When this quality slips at runtime, what does
the role NOTICE specifically?" If the answer is a runtime
perception, it is a concern. If the answer is a design
relationship between roles or between product and authority, the
candidate is an assumption or a scope item — not a concern.

Merge before emit: same theme keyword across different roles or
activities → one concern with the union of `affected_roles`.

A concern is an elicitation topic, not a measurable target. Do
not invent numeric thresholds, technologies, vendors, standards,
or policies.

Lens + anchor follow the same rules as for assumptions. For
inferred concerns, the anchor names why this quality dimension
is owed by this product shape.

`id`: leave empty. Python assigns CONCERN-NN.


SCOPE — SYSTEM-SCOPE BOUNDARIES (NOT "STATED DECISIONS")

A Boundary (OOS) is a RESPONSIBILITY the software will not (or
cannot) take on within its first release. The defining property
is system scope — the line between what the product handles vs
what is left to other tools, other authorities, other processes,
or to the user themselves.

OOS is NOT the same as "input stated a definitive choice". A
stated choice may belong in:
  - `scope` IF the choice is about a responsibility the software
    will not take on (e.g., the product will not credential, will
    not replace an external system, will not measure, will not
    enforce). The `item` describes what the SOFTWARE WILL NOT DO.
  - `description` / `intent_summary` IF the stated choice is
    already-decided substance about what the product positively
    IS (e.g., a stated form factor, a stated audience focus). This
    is not a fork dialogue can move; just record it where it
    belongs. Do not invent an ASM for it.

ASM-vs-OOS-vs-decided self-test (apply per stated/implied
candidate before emitting):
  "What is this statement actually doing?"
  1. Names a system-scope LIMIT (what the software won't handle,
     leaves to others, doesn't take responsibility for)
     → SCOPE / OOS.
  2. Names an open DESIGN FORK whose evidence dialogue could move
     → ASSUMPTION.
  3. Names a settled DESIGN CHOICE that dialogue cannot meaningfully
     move (because the input already decided it, and it isn't a
     responsibility limit) → fold into description / target_outcome
     / intent_summary, NOT into assumptions. A definitively settled
     choice with no losing alternative dialogue could surface is
     not a fork.

ACTIVE BOUNDARY SCAN:
Walk the input for phrases that describe what the software is
NOT meant to do, or responsibilities the product should leave to
something else. Non-exhaustive trigger phrases that often (not
always) signal an OOS candidate: "not replace", "alongside",
"without doing", "outside the first release", "we'd leave X to
Y", "not aim to", "we don't intend", "is not", "should not", "is
not the venue for", "at most might point at", "not a <type of
authority>", "out of scope". For each match, decide via the
self-test above whether it's a scope boundary (OOS) or already-
decided substance (description/notes).

INFERRED BOUNDARIES:
A boundary may also arise because a generic principle says the
product should leave a responsibility to another authority or
party, even if the input did not state it. Emit those with
lens=implied or lens=inferred and anchor the basis.

Empty list is correct only when the input has no boundary phrase,
no claim implies one, and no generic principle suggests
downstream agents would overreach. Skipping a clearly stated
system-scope boundary is a defect.

`id`: leave empty. Python assigns OOS-NN.


WRITING notes (this pass)

One coherent paragraph for a reviewer:
- briefly describe the lens distribution and the reasoning
  behind it (sparse-vs-rich rhythm honored);
- list direction-level forks you considered and how each was
  routed (assumption / open_question / dropped because it
  collapses into another), and why;
- note any boundary trigger phrases you acted on or declined to
  act on, with reasoning;
- surface any fork you considered and dropped (and why).
"""

>>>>>>> Stashed changes

# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class VisionaryAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="visionary")

    def _register_tools(self) -> None:
        """Visionary uses structured extraction only."""

    @staticmethod
    def _user_prompt(signal: str, feedback: Optional[str]) -> str:
        text = f"Project intent:\n{signal}"
        if feedback:
            text += (
                "\n\nReviewer feedback to address before regenerating any field:\n"
                f"{feedback}"
            )
        return text

    def _system(self, body: str) -> str:
        return f"{self.profile.prompt}\n\n{body}"

    def _pass1(self, signal: str, feedback: Optional[str]) -> ReadingPass:
        return self.extract_structured(
            schema=ReadingPass,
            system_prompt=self._system(_READ_BODY),
            user_prompt=self._user_prompt(signal, feedback),
            include_memory=False,
            include_thinking=True,
        )

    def _pass2(
        self,
        signal: str,
        reading: ReadingPass,
        feedback: Optional[str],
    ) -> ForksPass:
        body = _FORKS_BODY.format(
            reading=json.dumps(reading.model_dump(), indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
<<<<<<< Updated upstream
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
=======
            schema=ForksPass,
            system_prompt=self._system(body),
            user_prompt=self._user_prompt(signal, feedback),
>>>>>>> Stashed changes
            include_memory=False,
            include_thinking=True,
        )

    @staticmethod
    def _assign_ids(vision: ProductVision) -> None:
        for i, r in enumerate(vision.roles, 1):
            r.id = f"ROLE-{i:02d}"
        for i, a in enumerate(vision.assumptions, 1):
            a.id = f"ASM-{i:02d}"
        for i, c in enumerate(vision.concerns, 1):
            c.id = f"CONCERN-{i:02d}"
        for i, b in enumerate(vision.scope, 1):
            b.id = f"OOS-{i:02d}"

    @staticmethod
    def _check_inventory(reading: ReadingPass) -> List[str]:
        """Flag roles whose name has no traceable inventory candidate.

        Heuristic only — Python checks whether each role.name shares at
        least one significant word with one of the quoted candidates.
        Warnings are logged and appended to vision.notes; nothing is
        rejected. Empty candidate list returns no warnings (sparse
        one-liner case).
        """
        candidates = [c.strip() for c in (reading.inventory_candidates or []) if c.strip()]
        if not candidates:
            return []
        candidate_blob = " ".join(c.lower() for c in candidates)
        warnings: List[str] = []
        for role in reading.roles or []:
            name = (role.name or "").strip().lower()
            if not name:
                continue
            tokens = [t for t in name.split() if len(t) > 2]
            if not tokens:
                continue
            if not any(token in candidate_blob for token in tokens):
                warnings.append(
                    f"Role '{role.name}' has no inventory candidate trace — "
                    "either the inventory walk missed a phrase, or this role "
                    "was added without anchoring to an input phrase."
                )
        return warnings

    @staticmethod
    def _assemble(reading: ReadingPass, forks: ForksPass) -> ProductVision:
        combined_notes = (
            "PASS 1 — READING\n"
            f"{reading.notes.strip()}\n\n"
            "PASS 2 — FORKS\n"
            f"{forks.notes.strip()}"
        )
        return ProductVision(
            description=reading.description.strip(),
            intent_summary=reading.intent_summary.strip(),
            target_outcome=reading.target_outcome.strip(),
            notes=combined_notes,
            known_signals=list(reading.known_signals or []),
            roles=list(reading.roles or []),
            assumptions=list(forks.assumptions or []),
            concerns=list(forks.concerns or []),
            scope=list(forks.scope or []),
        )

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        signal = (state.get("project_description") or "").strip()
        if not signal:
            logger.warning("[VisionaryAgent] project_description is missing.")
            return {}

        feedback = (state.get("product_vision_feedback") or "").strip() or None
        logger.info("[VisionaryAgent] Building Product Vision (2 passes).")

        try:
            reading = self._pass1(signal, feedback)
            inventory_warnings = self._check_inventory(reading)
            forks = self._pass2(signal, reading, feedback)
            vision = self._assemble(reading, forks)
            self._assign_ids(vision)
        except Exception as exc:
            logger.error("[VisionaryAgent] Pipeline failed: %s", exc, exc_info=True)
            return {}

        if inventory_warnings:
            warning_block = "\n".join(f"  - {w}" for w in inventory_warnings)
            logger.warning(
                "[VisionaryAgent] Inventory check warnings:\n%s", warning_block
            )
            vision.notes = (
                f"{vision.notes}\n\n"
                f"INVENTORY WARNINGS (Python):\n{warning_block}"
            )

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

        lens_counts = {"stated": 0, "implied": 0, "inferred": 0}
        for assumption in vision.assumptions:
            lens_counts[assumption.lens] = lens_counts.get(assumption.lens, 0) + 1

        logger.info(
            "[VisionaryAgent] Product Vision ready — %d roles, %d assumptions "
            "(stated=%d, implied=%d, inferred=%d), %d concerns, %d scope.",
            len(vision.roles),
            len(vision.assumptions),
            lens_counts["stated"],
            lens_counts["implied"],
            lens_counts["inferred"],
            len(vision.concerns),
            len(vision.scope),
        )
        return updates