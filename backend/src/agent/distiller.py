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
            "Atomic requirement statement. For functional and non-functional "
            "requirements, the grammatical subject is the PRODUCT, not the "
            "user: the user is the source of evidence; the product is the "
            "bearer of the obligation.\n"
            "\n"
            "Default form: 'The app must <verb> ...', 'The system must "
            "require / allow / present / display / warn / enforce / block ...'. "
            "User-subject statements ('Users must provide X', 'The user must "
            "agree to Y', 'Users must be aware of Z') are almost always "
            "interview wordings that need normalization to system-subject "
            "before they become requirements. Examples of correct "
            "normalization:\n"
            "  'Users must provide a valid email'    -> 'The app must require a\n"
            "                                          valid email at account\n"
            "                                          creation'\n"
            "  'Users must agree to terms'           -> 'The app must present\n"
            "                                          the terms and block account\n"
            "                                          creation until accepted'\n"
            "  'Users must be aware delete is        -> 'The app must warn the\n"
            "   permanent'                            user that delete is\n"
            "                                          permanent before\n"
            "                                          confirming'\n"
            "  'Users must be able to filter X'      -> 'The app must allow\n"
            "                                          filtering of X'\n"
            "\n"
            "Narrow exceptions where the user is the correct subject: a "
            "workflow obligation outside the app (an external auditor sign-off "
            "the system only records) or a legal acceptance whose force is "
            "external. In ordinary product feature elicitation these are rare; "
            "default to system subject.\n"
            "\n"
            "For out_of_scope items, state the excluded capability as a "
            "product boundary."
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
            "Objective checks that would verify the requirement. Each criterion "
            "describes observable PRODUCT behaviour, not user action. Correct "
            "form: 'the app rejects sign-up when email is missing', 'a warning "
            "dialog appears before delete is confirmed', 'the entry list filters "
            "down when a date range is selected'. Avoid criteria written as user "
            "duties ('the user enters an email', 'the user agrees to terms') — "
            "those describe the test setup, not the system behaviour being "
            "verified.\n"
            "\n"
            "For NFR criteria, the check must be testable: a comparator with a "
            "named anchor, an observable absence, an operating condition, a "
            "named precedent, or a number with a unit. A numeric criterion is "
            "permitted when the dialogue captured a stakeholder routine that "
            "anchors the number (the time the stakeholder has at the product "
            "moment, the activity surrounding it, the attention budget the "
            "situation gives); in that case requires_threshold stays true and "
            "the rationale quotes the anchoring phrase. A numeric criterion is "
            "forbidden when the only evidence is an emotional descriptor "
            "('instantly', 'immediately') with no operational routine — in "
            "that case set requires_threshold and write the best observable "
            "criterion the evidence supports.\n"
            "\n"
            "Must be non-empty for functional and non-functional requirements; "
            "keep empty only for out_of_scope items. If evidence cannot support "
            "criteria, surface that as a gap instead of leaving the list empty."
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
- statement: one atomic rule with the PRODUCT as the subject ("The app
  must ...", "The system must ..."). User-subject statements ("Users must
  ...") need normalization per SUBJECT FRAMING DISCIPLINE; the only
  exceptions are external workflow obligations or legal acceptance acts
  whose force is external, and the rationale must name the reason.
- entity, step, aspect: fill only when the source evidence supports them.
- category, concern_theme: fill for NFRs that operationalize concern items.
- entity_refs, flow_step_refs: preserve additional anchors when the source
  concern or interview item names them.
- requires_threshold: true for any NFR whose elicited evidence was only an
  emotional descriptor ("instantly", "immediately", "responsive", "fast",
  "smooth", "snappy", "promptly") — even when you wrote the strongest
  observable phrasing from the signals. The gap accompanies it. Also true
  when you derived a proposed number from a stakeholder routine under the
  OPERATIONAL-CONTEXT NUMBERS rule, so the reviewer can confirm or adjust
  the proposed threshold; in that case the rationale must quote the
  anchoring routine phrase.
- rationale: cite the actual source evidence, including the stakeholder's
  lived experience for normalised statements; do not write a generic
  benefit.
- acceptance_criteria: objective verification checks of observable PRODUCT
  behaviour ("the app rejects sign-up when email is missing", "a warning
  dialog appears before delete is confirmed"), not user actions ("the user
  enters an email"). Empty only for out_of_scope.
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

The persona's SUBJECT FRAMING DISCIPLINE and NFR EVIDENCE STRENGTH apply to
every requirement you emit. The interview captured what users want, expect,
and find painful; every requirement statement you emit names the PRODUCT as
the subject of the obligation.

Rules:
1. Read the full interview item: signals, dialogue/talk, settled rule, risk,
   kind, aspect, entity, step, and role. The settled rule is a closure summary,
   not a one-to-one requirement container.

2. Use signals as the preferred atomic evidence source. Use dialogue/talk to
   recover important stakeholder-stated facts that are missing from signals.
   Use the settled rule to confirm closure and wording, not to compress facts.

3. One interview record may produce zero, one, or many requirements. If the
   signals, rule, or dialogue contain multiple independent conditions, limits,
   permissions, dependencies, exceptions, or distinct behaviours, split them
   into multiple atomic requirement statements. Do not compress an AND-chain
   into one requirement.

4. SUBJECT NORMALIZATION (apply to every functional requirement before
   emitting). The interview rule is often phrased in user-obligation form
   because the stakeholder spoke from their own experience. Rewrite the
   subject to the PRODUCT before writing the statement. Use the persona's
   normalization patterns:
     - "Users must provide X"          -> "The app must require X at <step>"
     - "Users must agree to Y"         -> "The app must present Y and require
                                          acceptance before <step>"
     - "Users must be aware that Z"    -> "The app must warn the user that Z
                                          before <step>"
     - "Users must be able to W"       -> "The app must allow / support W"
     - "Users must define / select V"  -> "The app must let the user define /
                                          select V on <entity>"
   Narrow exceptions stay user-subject (external workflow obligations the
   app only records, or legal-act acceptances whose force is external). When
   you keep the user as subject, the rationale must name why.

5. Keep ids sequential as FR-NNN or NFR-NNN; do not use suffixes.
   Multiple requirements may share the same EL source id when they came from
   the same interview record.

6. When evidence is still incomplete, do not create a requirement. Note the
   gap.

7. For conflict agenda items:
   - if the interview clarified precedence, scope split, or escalation, emit
     the clarified atomic requirement(s) with system-subject statement;
   - if the stakeholder defensibly settled on flexibility itself as the rule
     (accepted ambiguity), emit a system-subject requirement that names the
     supported alternatives ("The app must support both <X> and <Y>"). This
     is NOT an unresolved conflict; it is a settled flexibility rule;
   - if the ambiguity remains unresolved, preserve the evidence for Pass 3
     by writing a precise gap note rather than inventing a rule.

8. For concern agenda items, operationalize the softgoal into a non-functional
   requirement only when the dialogue provides enough evidence:
   - use type=non_functional and id=NFR-NNN;
   - preserve concern_category in category and concern_theme in concern_theme;
   - preserve entity, step, aspect, and source from the interview item;
   - include the item entity in entity_refs and the item step in flow_step_refs
     when present;
   - the statement is system-subject ("The app must respond to mood logging
     before the user shifts attention away from the entry screen"), not
     "Users must experience instant response";
   - NFR EVIDENCE STRENGTH: emotional descriptors alone are NOT defensible
     quality boundaries. "Instantly", "immediately", "quickly", "responsive",
     "fast", "smooth", "snappy", "promptly" are placeholders for a boundary
     that was not elicited. When the only evidence is an emotional descriptor:
       (a) write the statement using the strongest observable phrasing the
           signals support — an observable absence ("no spinner appears"), a
           comparative anchor ("comparable to native typing"), an operating
           condition ("before the user shifts attention away"), or a named
           precedent;
       (b) set requires_threshold=true;
       (c) write the missing-evidence gap describing what observable anchor
           or measurement is still needed;
       (d) DO NOT fabricate a number when no operational routine was
           captured in the dialogue. "Less than 1 second", "under 200 ms",
           "within 100 ms" are inventions when nothing in the signals
           anchors them;
   - OPERATIONAL-CONTEXT NUMBERS: when the dialogue DOES capture the
     stakeholder's routine around the product moment — the time they
     have at that moment, the duration of the activity surrounding the
     moment, the attention budget the situation gives — derive a numeric
     threshold from that routine in the same units the routine implies
     (seconds when the routine is measured in seconds; minutes when in
     minutes). Set requires_threshold=true so the reviewer confirms the
     proposed number; in the rationale quote the stakeholder phrase that
     anchored the inference so the number is auditable rather than
     hidden;
   - when the stakeholder gave a concrete threshold, magnitude, frequency,
     or observable condition, write it into the statement and acceptance
     criteria;
   - when the stakeholder gave only a defensible qualitative boundary that
     IS observable, write the strongest qualitative NFR and set
     requires_threshold=true.

9. Use item risk only as trace context. If the interview answer resolves or
   bounds the risk, mention that in rationale. If the risk remains
   unresolved, write a gap instead of inventing a requirement.

10. Do not copy quality thresholds or quality concerns into unrelated
    functional requirements. A functional requirement may mention quality
    only when the stakeholder's functional rule itself depends on that
    quality behaviour.

11. Acceptance criteria describe observable PRODUCT behaviour, not user
    actions. Correct: "the app rejects sign-up when email is missing",
    "a warning dialog appears before delete is confirmed", "the entry list
    filters when a date range is selected". Wrong: "the user enters an
    email", "the user agrees to the terms" — those are test setup, not the
    system behaviour being verified.

12. Acceptance criteria must verify exactly the atomic statement being
    written. Do not use one broad criterion to cover multiple split
    requirements. NFR criteria must be testable per NFR EVIDENCE STRENGTH:
    name an observable, a comparator, an operating condition, or a number
    with a unit — never invent one.

Use reviewed Product Vision only to preserve role, entity, step, and aspect
context. Do not use it to invent statements not supported by interview
evidence.
"""

_PASS2 = """\
PASS 2 - BASELINE AND SCOPE

Task:
Add only the baseline requirements and scope boundaries that remain necessary
after Pass 1. Baseline work covers two complementary surfaces:
  (i)  domain baseline — operations on the reviewed-vision entities that are
       structurally implied by the product concept but not surfaced through
       interview evidence;
  (ii) platform baseline — obligations the product inherits from being an
       interactive software product of its shape (web, mobile, desktop, or
       hybrid) that stakeholders rarely articulate in domain interviews
       because they are assumed.

Inputs:
- Product Vision flow, roles, and scope.
- Pass 1 requirement items.

PLATFORM BASELINE CATEGORIES
A real interactive product carries obligations that any modern software of
its shape inherits from its platform, independent of the specific domain
the product serves. The interview almost never surfaces these obligations
explicitly because stakeholders assume them; Pass 2 is where they enter the
list. Walk the categories below in order for the product concept. Emit a
baseline requirement under a category only when

  (a) the product concept in the project signal and the reviewed vision
      plainly make this category necessary for THIS product (a personal-
      data product needs an identity story; a single-shot offline
      calculator widget typically does not),

  (b) the interview-grounded items from Pass 1 did not already cover the
      same obligation, and

  (c) you can phrase the requirement as a stand-alone system-subject
      obligation that fits the project signal — not a domain-specific rule
      that should have come from interview.

Categories (a scaffolding for thought, not a checklist to emit verbatim):

- Identity and access. How a person becomes known to the product and is
  recognized on return; how their session is established, preserved, and
  ended; how access is recovered when credentials are lost. Skip when the
  product is plainly anonymous or single-device-only with no persisted
  identity.

- Account stewardship. How the person's record persists, can be amended,
  and can be removed at their own request; what survives or vanishes when
  the account ends. Skip when no person-level record exists.

- Data protection. What the product must keep private even from itself in
  transport and at rest, and what it must record about access to sensitive
  material. Phrase as an obligation, not a technology: "the app must keep
  X confidential between sessions" rather than naming a specific cipher.
  Skip when the product handles nothing sensitive or identifying.

- Error and feedback. How the product confirms an action that succeeded,
  partially succeeded, or failed; how it surfaces validation problems
  before work is committed; how it makes the current state of long-running
  work visible. Almost every interactive product needs at least one
  requirement here.

- Reach and accommodation. The minimum shapes the product must work on
  (web, mobile, desktop, or a combination implied by the signal); the
  input modes it must accept (keyboard, touch, assistive tools); the
  language or locale variants the audience implies. Skip categories the
  signal explicitly excludes.

- Availability and resilience. What the product must do when connectivity
  is interrupted, when work in progress would be lost on a crash, or when
  a dependency the product needs is unreachable. Skip when the product is
  fully local and stateless.

- Legal and accountability. What the product must show, ask, or record to
  meet the duties its audience and jurisdiction usually demand (terms or
  privacy disclosure on first use, data export on request, age gating
  where the audience needs it). Skip when no such duty fits the product.

A category that does NOT apply must be skipped, not padded. Pass 2 notes
must list which categories were considered and which were dropped, with
the reason each empty category is empty for this product.

Rules for baseline items:
1. Emit a baseline requirement only when the product concept and reviewed
   vision make the software obligation plainly necessary — for the domain
   baseline (i) or for one of the PLATFORM BASELINE CATEGORIES above.
2. Do not restate an interview requirement already covered in Pass 1.
3. Stay at application-concept level, not implementation detail. Phrase
   platform-baseline statements as obligations, not as choices of
   technology, library, vendor, protocol, or cipher.
4. Baseline statements are system-subject ("The app must allow creation,
   update, and deletion of user profiles", "The app must support logging,
   updating, viewing, and deleting the entries the product manages"),
   never user-subject. Per SUBJECT FRAMING DISCIPLINE: the user is the
   source of need; the product is the bearer of the obligation.
5. Use ids BL-NNN in source and FR/NFR ids in id.
6. origin=baseline, status=confirmed.
7. Do not convert Product Vision NFR concerns directly into requirements
   unless the interview evidence or the product baseline already supports a
   testable system-side statement. Concerns are primarily operationalized in
   Pass 1.
8. Anchor every platform-baseline requirement to the PLATFORM BASELINE
   CATEGORY it answers. Notes must show the category each item came from
   so the reviewer can audit which categories were exercised and which
   were honestly dropped.

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

This pass is the last chance to catch SUBJECT FRAMING and NFR EVIDENCE
STRENGTH leaks from Pass 1. Audit every candidate before emitting.

Conflict standard:
- Report a conflict only when two items still cannot both hold in overlapping
  scope, or when the dialogue explicitly left a collision unresolved.
- Do not report ordinary trade-offs or already-clarified precedence as
  conflicts.
- Do not require a decision maker role to exist. The issue may remain
  unresolved because no governing rule was supplied.
- An accepted-flexibility outcome from the interview is NOT an unresolved
  conflict; it is a settled rule that the product must support multiple
  options.

Quality standard:
1. One atomic statement per requirement.
2. SUBJECT NORMALIZATION AUDIT. Every functional and non-functional
   requirement is system-subject by default ("The app must ...", "The system
   must ...", "The product must ..."). Reject any statement that begins with
   a user-obligation phrasing — "Users must ...", "The user must ...",
   "Users have to ...", "Users are required to ...", "Users must be aware
   that ...", "Users must be able to ..." — and rewrite it per the
   normalization patterns from Pass 1. Narrow exceptions stay user-subject
   only when the rationale names the external workflow or legal-act anchor
   that justifies it.
3. NFR EVIDENCE STRENGTH AUDIT. For every non_functional item, check that
   the statement and acceptance criteria contain at least one of: a number
   with a unit, a named comparator, an observable absence, an operating
   condition, or a named precedent. If they contain only emotional
   descriptors ("instantly", "immediately", "responsive", "fast", "smooth",
   "snappy", "promptly"), rewrite the statement using the strongest
   observable phrasing the source signals support, set
   requires_threshold=true, and add a gap naming what observable anchor
   or measurement is missing.
   - Numeric proposal IS allowed when the dialogue captured a stakeholder
     routine that anchors the number (see Pass 1 OPERATIONAL-CONTEXT
     NUMBERS): the time the stakeholder has at the product moment, the
     activity duration surrounding it, the attention budget the situation
     gives. In that case the number is stakeholder-grounded, and the
     rationale must quote the routine phrase that anchored it; requires
     _threshold stays true so the reviewer confirms.
   - Numeric proposal is NOT allowed when only an emotional descriptor
     was elicited and no operational routine was captured. Software-
     performance vocabulary the stakeholder did not say ("milliseconds",
     "P99 latency") is invention; reject it on audit.
4. Acceptance criteria exist for every non-scope item, describe observable
   PRODUCT behaviour, and verify the atomic statement. If an item lacks
   objective acceptance criteria grounded in its own statement and evidence,
   remove it or convert the missing evidence into a gap; do not leave an
   empty list and do not invent criteria from the system-side.
5. Scope items stay excluded and keep no acceptance criteria.
6. Preserve traceability in source and rationale. When you rewrite a
   user-subject statement to system-subject under rule 2, the rationale
   must cite the stakeholder's lived experience as the source of the
   obligation (e.g. "Stakeholder reported that the app prompts for email
   and password at sign-up (EL-001); the prerequisite is the app's
   responsibility, not the user's.").
7. gaps should mention important missing evidence that did not become a
   requirement, including any NFR that ended up requires_threshold=true
   because only an emotional descriptor was elicited.
8. Keep FR and NFR concerns separated unless the interview explicitly ties
   them together in one rule.
"""


_PASS3_CONFLICT_ADHERENCE = """\
CONFLICT FEEDBACK ADHERENCE
You are re-running this pass because a prior version surfaced conflicts
that a human reviewer has now resolved in the feedback above. The
reviewer's resolution is a DIRECTIVE for this re-run, not one option
among several.

ALREADY-SURFACED CONFLICTS (each was open in the previous version of
this list and has been addressed by the reviewer above):
{prior_conflicts}

Rules:
1. Treat the reviewer's resolution as the governing rule for the scope
   of each addressed conflict. Rewrite the affected requirements so
   each side of the conflict either fits the resolution or is removed.
   When the resolution says one side wins, drop or narrow the other
   side and record the change.
2. Do NOT re-emit a conflict the reviewer has already resolved.
   "Conflicts" must NOT contain a CF entry whose scope matches an
   already-addressed conflict above; doing so contradicts the
   directive and forces another round of human review for no reason.
3. When the reviewer's resolution is "ambiguity remains acceptable" or
   "the product should support both", encode that as a single system-
   subject requirement that names the supported alternatives ("The
   app must support both X and Y under conditions Z"). That is a
   settled flexibility rule, NOT an unresolved conflict.
4. Other tensions that the reviewer did NOT name may still surface as
   conflicts in this pass. Only the already-addressed conflicts above
   are forbidden to re-emit.
5. Notes MUST include a CONFLICT RESOLUTION ADHERENCE block, one line
   per already-surfaced conflict, in the form
     CF<scope or id> resolution=<short paraphrase of the reviewer's
     directive> result=<rewritten | merged | dropped | flexibility-
     encoded> ids=<the requirement ids that changed under this
     resolution>.
   A missing or contradicted line is an audit failure.
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

        pass3_only = bool(state.get("_distiller_pass3_only"))
        carryover_items = state.get("_pass3_carryover_items") or []
        carryover_conflicts = state.get("_pass3_carryover_conflicts") or []

        pass1_notes = ""
        pass2_notes = ""
        try:
            if pass3_only and carryover_items:
                logger.info(
                    "[DistillerAgent] Pass 3-only re-run on %d carryover item(s) "
                    "with %d resolved conflict(s).",
                    len(carryover_items),
                    len(carryover_conflicts),
                )
                all_items = carryover_items
                pass1_notes = (
                    "Skipped on this re-run. Pass 1 candidates carried over "
                    "from the previous synthesis are unchanged."
                )
                pass2_notes = (
                    "Skipped on this re-run. Pass 2 candidates carried over "
                    "from the previous synthesis are unchanged."
                )
            else:
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
                pass1_notes = pass1.notes
                pass2_notes = pass2.notes

            pass3_system = self.profile.prompt + "\n\n" + _PASS3
            if pass3_only and carryover_conflicts:
                pass3_system += "\n\n" + _PASS3_CONFLICT_ADHERENCE.format(
                    prior_conflicts=json.dumps(
                        carryover_conflicts, indent=2, ensure_ascii=False
                    )
                )
            pass3_system += "\n\n" + _FIELD_GUIDE + feedback_block

            pass3: FinalPass = self.extract_structured(
                schema=FinalPass,
                system_prompt=pass3_system,
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
                f"{pass1_notes.strip()}\n\n"
                "PASS 2 - BASELINE AND SCOPE\n"
                f"{pass2_notes.strip()}\n\n"
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
            "_distiller_pass3_only": False,
            "_pass3_carryover_items": [],
            "_pass3_carryover_conflicts": [],
        }