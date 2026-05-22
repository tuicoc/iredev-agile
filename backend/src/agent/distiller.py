"""
distiller.py - DistillerAgent

Map-reduce synthesis turning interview evidence into a structured
RequirementList. Pass 2 is split so the LLM never juggles preserve-
vs-merge pressure in the same call:

  Pass 1 (EXTRACT)        — SIGNAL-DRIVEN. One call per interview
                            record, run in parallel. Each call sees ONE
                            record plus the compact Product Vision and
                            produces an Extraction: requirements (with
                            the six Implementation Parity axes filled),
                            within-record gaps and conflicts, and a
                            signal_walk that assigns every signal one
                            of three verdicts (requirement_seed /
                            supporting_evidence / non_product). Items
                            emerge from clustering signals by product
                            object + trigger + audience + outcome.

  Pass 2A (CLUSTER)       — DECISION ONLY. One call sees every per-
                            record Extraction (each item assigned a
                            temporary T-NNN id by Python) plus the
                            compact Product Vision. It emits
                            merge_groups: clusters of 2+ Pass 1 items
                            that satisfy the same-build test, each
                            cluster carrying a unified consolidated
                            Requirement and a rationale. Items not
                            referenced by any group pass through
                            unchanged via Python.

  Pass 2B (ADJUDICATE)    — VISION + GAPS + CONFLICTS. One call sees
                            the same per-record Extractions and vision.
                            It walks vision.concerns / vision.assumptions
                            for narrowing-verb constraints that no
                            Pass 1 item already covers, then adjudicates
                            gaps and conflicts across records. It does
                            not decide merges or rewrite Pass 1 items.

Pass 2A and Pass 2B are independent; Python fires them in parallel.

Vision scope (OOS) items are preserved by Python as pure 1:1 data
movement. Every vision.scope entry becomes one out_of_scope
Requirement in the final artifact, regardless of whether the LLM
referenced the vision id elsewhere. The LLM is forbidden from emitting
out_of_scope items; any it emits are filtered out before Python
appends the vision-scope set.

Schema descriptions say WHAT a field holds. Prompt bodies teach HOW to
reason — definitions, dichotomies, cross-domain placeholders. No
domain, topic, role name, or product category is hardcoded.

Python's role: data movement and format guards. Assigning T-NNN temp
ids before Pass 2, applying merge_groups by replacing referenced
members with the consolidated form and unioning every member's
trace_refs into it (anti-drop invariant), passing through items not
in any group, concatenating vision_constraint_items, normalising
trace_ref format, dropping LLM-emitted OOS items, appending vision-
scope items 1:1, renumbering ids, persisting the artifact. Python
never decides which items are duplicates, never writes consolidated
statements, never adjudicates gaps or conflicts.
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, TypeVar

from pydantic import BaseModel, Field, field_validator

from .base import BaseAgent

logger = logging.getLogger(__name__)


RequirementType = Literal["functional", "non_functional", "system", "out_of_scope"]

SignalVerdict = Literal[
    "requirement_seed",
    "supporting_evidence",
    "non_product",
]

# Deterministic id-format guards. Source unit ids live inside an EL-NNN
# record at a specific sub-id; vision ids match canonical prefixes;
# vision paths are stable strings. Anything else is rejected so the
# "no bare item ids" rule holds at the schema boundary.
_SOURCE_UNIT_RE = re.compile(r"^EL-\d{3}-(?:S\d{2,}|T\d{2,}|ASM\d{2,}|RULE)$")
_VISION_ID_RE = re.compile(r"^(?:ASM|ROLE|CONCERN|OOS)-\d{2,}$")

T = TypeVar("T")


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Cross-provider sniff: 429 status or canonical 'rate limit' phrasing."""
    text = str(exc).lower()
    return "429" in text or "rate_limit" in text or "rate limit" in text


# ─────────────────────────────────────────────────────────────────────────────
# Final artifact pieces
# ─────────────────────────────────────────────────────────────────────────────

class Requirement(BaseModel):
    id: str = Field(default="", description="Leave empty. Python renumbers per type after the final pass.")
    type: RequirementType = Field(description=(
        "functional: product-owned behavior or content surface with a stakeholder-observable outcome. "
        "non_functional: independently reviewable property a behavior must hold (clarity, accuracy, ...). "
        "system: product-wide guarantee with no stakeholder trigger. "
        "out_of_scope: a responsibility the product explicitly excludes."
    ))
    stakeholder: Optional[str] = Field(default=None, description=(
        "Audience axis — the role that LIVES the observable_outcome, not the role that supplied the evidence. "
        "These often differ: a record whose perspective is one role frequently produces requirements whose "
        "audience is a different role (an observer-role record can speak about an outcome a user-role audience "
        "experiences). Set stakeholder to the role from vision.roles whose runtime experience changes when "
        "this obligation holds. Use 'product-wide' for system items or NFRs whose outcome applies uniformly "
        "across audiences. Leave null only for out_of_scope items, which exclude a responsibility and "
        "therefore have no audience."
    ))
    statement: str = Field(description=(
        "One complete declarative product-obligation. Subject is 'The product', 'The system', or a "
        "product-owned noun. No human-subject sentences, no bare imperative."
    ))
    rationale: str = Field(description="One short evidence-grounded sentence.")
    trace_refs: List[str] = Field(default_factory=list, description=(
        "Source-unit ids (EL-NNN-SNN/TNN/COVNN/ASMNN/RULE), vision ids (ASM-NN, ROLE-NN, CONCERN-NN, OOS-NN), "
        "or stable paths (ProductVision.scope). No bare item ids."
    ))
    acceptance_criteria: List[str] = Field(default_factory=list, description=(
        "Smallest non-duplicative set of product-observable checks. Empty for out_of_scope."
    ))
    status: Literal["confirmed", "excluded"] = Field(description=(
        "confirmed for implementable items; excluded only for out_of_scope boundaries."
    ))
    confidence: Literal["confirmed", "inferred"] = Field(description=(
        "confirmed: obligation directly grounded in stated evidence — input intent named it, "
        "a stakeholder signal explicitly described it, or a vision assumption was verified by "
        "interview. inferred: your synthesis from context — symptom→cause translation, "
        "product-side translation of role process, or a boundary that follows logically from "
        "multiple signals without being directly stated. Inference is legitimate work when "
        "evidence supports it; do not avoid inferring just to label everything confirmed."
    ))

    # ── Implementation Parity axes ──────────────────────────────────────────
    # The synthesize pass merges two candidates only when ALL six align (and
    # for NFRs, the same quality property — taught in prompt). Fill these
    # precisely; the synthesize pass keys merge decisions off the JSON.

    trigger_event: str = Field(default="", description=(
        "Event class that activates the obligation: a stakeholder action, a state change, a cadence, "
        "or 'always-on' for invariants. Empty for out_of_scope."
    ))
    product_object: str = Field(default="", description=(
        "Product-owned object the obligation operates on: a content surface, information, state, "
        "decision aid, boundary, interaction. Empty for out_of_scope."
    ))
    observable_outcome: str = Field(default="", description=(
        "What the audience observes when the obligation holds. Empty for out_of_scope."
    ))
    operating_condition: str = Field(default="", description=(
        "When the obligation is active. Empty for always-on or when no condition narrows it."
    ))
    participation_structure: str = Field(default="", description=(
        "Who participates / decides / is affected when more than one party is involved "
        "(single-actor, multi-actor, contested, delegated, authority-mediated, ...). "
        "Empty for single-actor obligations."
    ))

    @field_validator("trace_refs", mode="after")
    @classmethod
    def _validate_trace_ref_format(cls, refs: List[str]) -> List[str]:
        """Drop malformed or bare trace_ref entries; preserve valid ones.

        Pure format normalization. Source unit ids must point inside an
        EL-NNN record at a specific sub-id; vision ids must match the
        canonical prefixes; vision paths start with "ProductVision.".
        Empty strings, bare EL-NNN entries, and duplicates are silently
        dropped. The validator never rejects a Requirement.
        """
        kept: List[str] = []
        seen: set = set()
        for raw in refs or []:
            value = str(raw or "").strip()
            if not value or value in seen:
                continue
            if (
                _SOURCE_UNIT_RE.match(value)
                or _VISION_ID_RE.match(value)
                or value.startswith("ProductVision.")
            ):
                kept.append(value)
                seen.add(value)
        return kept


class Conflict(BaseModel):
    id: str = Field(default="", description="Leave empty; Python renumbers to CF-NN.")
    kind: Literal["clash", "unclear"] = Field(description=(
        "clash for incompatible obligations; unclear for unresolved evidence."
    ))
    left: str = Field(description="Requirement id, source unit id, or vision id on one side.")
    right: str = Field(description="Requirement id, source unit id, or vision id on the other side.")
    scope: str = Field(description="Shared operating context where the conflict applies.")
    issue: str = Field(description="Why the sides cannot both hold, or what remains ambiguous.")
    paths: List[str] = Field(default_factory=list, description="Reviewer choices that could resolve the conflict.")
    refs: List[str] = Field(default_factory=list, description="Evidence references supporting the conflict.")


class SignalWalkEntry(BaseModel):
    """One signal's verdict — Pass 1 OUTPUT-required discipline.

    Signals are the richest evidence source in an interview record (often
    5-15 per record). Each signal owes a verdict so no signal is silently
    lost. The walk drives extraction: requirement_seed signals become
    items (alone or clustered), supporting_evidence signals enrich those
    items' trace_refs, non_product signals are observation only.
    """
    signal_id: str = Field(description=(
        "The signal id in the input record (EL-NNN-SNN)."
    ))
    verdict: SignalVerdict = Field(description=(
        "requirement_seed: this signal carries a distinct product-owned decision and became "
        "(or co-founded) an item in items[]. "
        "supporting_evidence: this signal supports another signal's product decision (same "
        "product object, trigger, audience, outcome cluster). "
        "non_product: real context (process, role behavior, observation) with no product duty."
    ))
    reason: str = Field(description=(
        "One short sentence: which cluster/item the signal seeded or supports, or why non_product."
    ))


class Extraction(BaseModel):
    """Pass 1 output for a single interview record."""
    notes: str = Field(description="Brief reviewer-facing extraction note. No section header echo.")
    items: List[Requirement] = Field(default_factory=list, description=(
        "Requirements grounded in this record's evidence. Do NOT emit out_of_scope items — "
        "Python preserves vision scope 1:1 deterministically."
    ))
    gaps: List[str] = Field(default_factory=list, description=(
        "Within-record gaps. Each begins with the source-id and names the missing product decision."
    ))
    conflicts: List[Conflict] = Field(default_factory=list, description="Within-record conflicts.")
    signal_walk: List[SignalWalkEntry] = Field(default_factory=list, description=(
        "One entry per signal in the input record. Required — every signal owes a verdict. "
        "The walk is the discipline that prevents silent under-extraction."
    ))


class MergeGroup(BaseModel):
    """One same-build cluster — Pass 2A OUTPUT.

    A group identifies two or more Pass 1 items that describe the same
    product obligation (one feature/surface/flow satisfies all of them)
    and supplies the unified obligation that replaces them. Pass 1
    items NOT referenced by any group pass through unchanged via
    Python; the cluster pass owns only the duplicates.
    """
    member_temp_ids: List[str] = Field(description=(
        "Temporary ids (T-NNN) of the Pass 1 items this group consolidates. "
        "Two or more required — a group of one is a pass-through (do not emit)."
    ))
    consolidated: Requirement = Field(description=(
        "The unified obligation that satisfies every member. Subject is "
        "product-side; smallest reviewable AC set; six Implementation Parity "
        "axes filled with the most specific value across members. "
        "confidence is confirmed only if EVERY member was confirmed."
    ))
    rationale: str = Field(description=(
        "One short sentence naming the single build (one surface + one code "
        "path or content flow + one end-to-end test) that satisfies every "
        "member word-for-word."
    ))


class MergeDecisions(BaseModel):
    """Pass 2A output — merge groups only.

    The cluster pass owns ONE concern: identify same-build duplicates
    among Pass 1 items and emit the unified obligation for each cluster.
    Pass 1 items not referenced by any group are pass-through; Python
    keeps them untouched. The LLM never writes pass-through items here.
    """
    notes: str = Field(description=(
        "Brief reviewer-facing note about clustering decisions. No section "
        "header echo (Python frames the section)."
    ))
    merge_groups: List[MergeGroup] = Field(default_factory=list, description=(
        "Only groups of 2+ Pass 1 items that satisfy the same-build test. "
        "Pass 1 items not listed in any group pass through unchanged via Python."
    ))


class VisionAndAdjudication(BaseModel):
    """Pass 2B output — vision constraint walk + gap/conflict adjudication.

    The adjudication pass owns ONE concern: walk the Product Vision for
    explicit constraints (narrowing verbs) that no Pass 1 item already
    covers, and adjudicate gaps + conflicts across records. It does NOT
    decide merges (Pass 2A owns that) and does NOT rewrite Pass 1 items.
    """
    notes: str = Field(description=(
        "Brief reviewer-facing note about vision constraints added and "
        "adjudication. No section header echo."
    ))
    vision_constraint_items: List[Requirement] = Field(default_factory=list, description=(
        "NEW non_functional or system items derived from explicit vision constraints "
        "(narrowing verbs in vision.concerns / vision.assumptions) that no Pass 1 item "
        "already covers. Do NOT emit out_of_scope items (Python preserves vision.scope 1:1)."
    ))
    final_gaps: List[str] = Field(default_factory=list, description=(
        "Gaps adjudicated across all per-record extractions. Format: '<source-id>: <missing "
        "product decision>'. Merge two gaps when the same answer would close both."
    ))
    final_conflicts: List[Conflict] = Field(default_factory=list, description=(
        "True cross-record conflicts only — two obligations that cannot both hold in the "
        "same operating context."
    ))


class RequirementList(BaseModel):
    notes: str = Field(description="Reviewer-facing synthesis note.")
    items: List[Requirement] = Field(description="Final requirements ready for human review.")
    conflicts: List[Conflict] = Field(default_factory=list, description="Unresolved conflicts.")
    gaps: List[str] = Field(default_factory=list, description="Readable missing decisions.")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt blocks
#
# Layout follows VisionaryAgent: every pass uses _FOUNDATIONS +
# _REASONING_MOVES + one pass-specific block. Concepts live in the shared
# blocks; pass blocks are narrative, not numbered procedure. Examples use
# generic placeholders (<role>, <surface>, <object>) — no domain, topic,
# role name, or category is hardcoded.
# ─────────────────────────────────────────────────────────────────────────────

_FOUNDATIONS = """\
FOUNDATIONS

A requirement is one product obligation: something the product must
do, must hold as a property, must guarantee as an invariant, or must
explicitly not take on. Stakeholder words about what they do, want,
or need are EVIDENCE for requirements, not requirements themselves —
your job is to translate that evidence into product-side obligations.

FOUR TYPES (you emit three; Python handles the fourth)

- functional: product behavior or content surface with a
  stakeholder-observable outcome.
- non_functional: independently reviewable property a behavior must
  hold (clarity, accuracy, accessibility, ...).
- system: product-wide guarantee with no stakeholder trigger.
- out_of_scope: handled by Python from vision.scope. DO NOT emit.

SUBJECT RULE

Statement subject is product-side: "The product", "The system", or a
product-owned noun (artifact, surface, content, component). Verb is
product-owned (provide / expose / preserve / constrain / display /
communicate / validate / record / prevent / recover / synchronize /
...). Not a social verb the product cannot perform (gain, earn,
attract, win, build trust).

If the natural phrasing puts a role as subject ("<role> needs to
..."), rewrite product-side. If no product object emerges, the
candidate is observation — drop, emit gap.

ACCEPTANCE CRITERIA — REVIEWABLE OR DROPPED

Each AC is inspectable. Three valid shapes:
- product state — "The product displays <X>", "Each <object>
  includes <Y>"
- product capability accessed by role — "<role> can access <X>",
  "<role> can switch between <Y> and <Z>"
- product invariant — "<rule> holds across <conditions>"

NOT valid: user cognition / behavior — "<role> reports <feeling>",
"<role> understands <thing>", "<role> finds <X> easy". The product
cannot enforce what users think or feel. Move to observable_outcome
or drop.

Self-test per AC: "Could the team test this by inspecting the
product, without interviewing a user?" If no → reshape or drop.

ATOMICITY

One statement = one obligation. Connectives ("and", "or", "plus")
between two distinct verbs or two distinct objects mark a bundle —
split.

ONE NFR = ONE QUALITY PROPERTY. Quality dimensions (open list,
cross-domain): accuracy, reliability, clarity, brevity, consistency,
accessibility, timeliness, trustworthiness, completeness, privacy,
recoverability, ... A statement with TWO+ dimensions ("clear and
concise", "accurate and reliable") is a bundle — split. Themes like
"good <X>" or "high-quality <Y>" erase dimensions a reviewer must
judge — split.

CONFIDENCE — be honest about which side you are on

The core test: did the stakeholder/input name the PROBLEM, or did
they name the SOLUTION?

- confirmed — the stakeholder or input named the product-side
  obligation in words you essentially preserve. A signal directly
  says "the product should <X>" or "we need <X>" where X is
  product-owned; or a vision assumption was verified by interview
  ("yes that's true"), and the product-side obligation follows
  word-for-word from the verified assumption.

- inferred — the stakeholder named friction, struggle, workaround,
  or wish; YOU named the product-side solution. The trace cites
  problem signals, but the statement's solution-shape is your
  synthesis. Also inferred: connecting multiple signals into a
  unified product decision none of them phrased individually;
  translating a role-side process into a product-side obligation
  the stakeholder did not articulate.

Default test before marking confirmed: read aloud ONE signal cited
in trace_refs. Does that single signal name the product-side
obligation in the statement (not just the problem behind it)?
If yes → confirmed. If you had to SYNTHESIZE across signals or
TRANSLATE from friction to solution → inferred.

Solution-proposer work yields LOTS of inferred items. A record
with 8 struggle signals and 4 emitted requirements typically
yields 1-2 confirmed (where stakeholders explicitly named the
product feature) and 2-3 inferred (where you translated friction
into solutions). If every item in your output is marked confirmed,
you are either over-claiming or you missed the solution-proposing
work the evidence asked for.

TRACE DISCIPLINE

Trace_refs are source-unit precision: EL-NNN-SNN (signal), EL-NNN-TNN
(talk), EL-NNN-ASMNN (assumption evidence), EL-NNN-RULE. Vision ids
(ASM-NN, ROLE-NN, CONCERN-NN) and stable paths (ProductVision.scope)
strengthen the trace. Bare item ids (EL-NNN alone) not valid. No
trace = invention.

DOMAIN NEUTRALITY

Use the vocabulary of the evidence in front of you. No imported
domain examples, fixed role names, product categories, or policy
templates from outside this run.
"""


_REASONING_MOVES = """\
REASONING MOVES

SOLUTION PROPOSER STANCE

You are not classifying signals. You are PROPOSING the product
obligations the team should build to satisfy what the evidence
revealed. When the stakeholder names a friction without naming the
product solution, the solution-side translation is YOUR work —
propose it, mark confidence=inferred, trace to the friction signals.

Under-proposing is a failure mode. A record with 8 signals about
struggles should yield 3-5 product obligations, not 1. Solution-shy
extraction leaves the team with no list to build.

SYMPTOM → CAUSE

Role-experience signals ("<role> tries X", "<role> avoids Y",
"<role> asks others when uncertain") describe product obligations
indirectly. Translate: role-looks-for-X → product-displays-X. A
candidate that preserves the workaround is wrong.

PROCESS → PRODUCT TRANSLATE

A stakeholder process (review, assessment, trust formation,
endorsement, discussion) becomes a product requirement ONLY when
evidence names a product-owned object the process depends on:
information, state, content, rule, feedback, record, constraint,
interaction. If no product-owned object emerges, the process is
observation.

The product cannot enforce social verbs. "Product gains trust",
"product earns endorsement" are not obligations. Find the
product-owned object the role uses to participate:
- expose evidence the role uses to judge — provenance, citations,
  source labels, transparency markers
- display signals from outside the product — badges, attestations
- present what other roles said — testimonials, case studies

If none supported, drop and emit gap.

The statement-verb test applies to NFRs too. "The product should
gain X / earn Y / attract Z" is misframed, regardless of type —
rewrite product-side or drop.

PRESERVATION vs BASELINE (vision dichotomy)

Interview evidence is authority for product behavior. Vision is
authority for explicit constraints (narrowing verbs) and excluded
responsibilities.

- preservation candidate — verb narrows or excludes. Allowed.
- baseline candidate — verb names positive product action
  ("provide", "ensure", "maintain", "support", "enable") the
  interview did not confirm. Drop. Filling a gap with vision
  content is invention.

GAP / CONFLICT

A gap is probed, unsettled, necessary. Format: "<source-id>:
<missing product decision>". Two gaps naming the same concept (same
answer would close both) → merge into one.

A conflict is two obligations that cannot both hold in the SAME
operating context. Condition differences absorbed into AC ≠
conflict. Mixed evidence on a theme (one role enthusiastic, another
sceptical) = ambivalence, not conflict.

IMPLEMENTATION PARITY (for the synthesize pass)

Two candidates describe the same obligation only when ALL align:
trigger_event, product_object, observable_outcome, stakeholder,
operating_condition, participation_structure (and for NFRs the same
quality property). Fill these axes precisely on every requirement.
"""


_PASS_EXTRACT = """\
PASS 1 OF 2 — EXTRACT FROM ONE INTERVIEW RECORD (SIGNAL-DRIVEN)

You see ONE interview record plus the compact Product Vision. You
are a software solution proposer reading lived evidence and emitting
the product obligations the team should build.

INPUT FIELDS

The record carries:
- perspective — which role's view
- context — the scene
- vision_refs — vision elements this item probed
- decision_target — what fork the dialogue was meant to move
- signals — atomic stakeholder facts, each EL-NNN-SNN (primary
  evidence — typically 5-15 per record)
- talk — Q&A turns, each EL-NNN-TNN (richer context)
- assumption_evidence — stance + implication on vision assumptions,
  each EL-NNN-ASMNN (key for confirmed vs inferred)
- rule — closure summary if present (EL-NNN-RULE)

MENTAL MODEL

1. READ HOLISTICALLY. What is this role saying about their life?
   What pain, workaround, wish, or boundary did they name?

2. WALK EVERY SIGNAL. For each signal:
   (a) Does it name or imply a distinct product-owned decision?
       → requirement_seed. Translate to product side, propose
       obligation.
   (b) Does it support another signal's product decision (same
       product object + trigger + audience + outcome)?
       → supporting_evidence.
   (c) Is it process / role behavior / context only?
       → non_product.
   Every signal gets one verdict. No silent skips.

3. CLUSTER SEEDS into items. Signals converging on the SAME
   product object + trigger + audience + outcome form ONE cluster
   = ONE requirement. Keep clusters NARROW; when uncertain, split.

   Typical rhythm:
     10-15 signals → 5-8 items
     5-10 signals → 3-6 items
     <5 signals → 2-4 items

   1-2 items from a signal-rich record = over-collapsed. Re-split.

4. PROPOSE SOLUTIONS. For each cluster:
   - Name the product-owned object the obligation acts on.
   - State the obligation with a product-side subject.
   - Write ACs in one of 3 reviewable shapes (state / capability /
     invariant).
   - If evidence names friction without naming the product
     solution, YOU propose the solution — that is solution-
     proposer's work. Mark confidence=inferred and trace to the
     friction signals.

5. ENRICH. Walk assumption_evidence, talk, rule:
   - assumption_evidence verifying a vision assumption → marks
     related item as confidence=confirmed; add the ASM id and
     the vision_ref id to trace_refs.
   - talk turn adding lived context → trace_refs union.
   - rule summarizing closure → trace_refs union if relevant.

6. MARK CONFIDENCE per item (see Foundations):
   - confirmed when evidence directly grounds it (input intent,
     explicit signal phrasing, verified vision assumption).
   - inferred when you synthesized symptom→cause or connected
     multiple signals into a product-side conclusion.

7. FILL THE SIX IMPLEMENTATION PARITY AXES precisely.

8. TRACE — union ALL contributing source-unit ids on each item.

SIGNAL_WALK — OUTPUT REQUIRED

Every signal in the input record owes one entry in signal_walk.
The reason field names the cluster it seeded or supports (e.g.
"co-founded <X> cluster" / "supports cluster from EL-NNN-S03" /
"role process with no product object").

WITHIN-RECORD GAPS

If an assumption_evidence entry probed a decision (stance=unclear
or weakens) that no signal cluster settled at AC precision, emit
in gaps[] as "<source-id>: <missing product decision>".

DO NOT EMIT out_of_scope ITEMS. Python preserves vision.scope 1:1.

NOTES

Brief substantive observation about this record's extraction.
Don't echo a section header (Python frames the section).
"""


_PASS_CLUSTER = """\
PASS 2A OF 3 — CLUSTER SAME-BUILD DUPLICATES (DECISION ONLY)

You see every per-record Extraction (each item already carries a
temporary id T-NNN) plus the compact Product Vision. Your ONE job:

  Decide which Pass 1 items describe the same product obligation
  (same build) and emit one MergeGroup per such cluster.

You do NOT emit pass-through items. Items not referenced in any
merge_group are kept verbatim by Python; touching them is wasted
work and risks accidental drift.

You do NOT walk the vision for new constraints, you do NOT
adjudicate gaps, you do NOT adjudicate conflicts — a separate pass
owns those concerns.

DUPLICATE HANDLING — REASON LIKE A PRODUCT ENGINEER

Different records often surface the same product decision from
different perspectives. Decide whether two items cluster by running
two intuition tests in order, not by matching fields in a checklist.

TEST 1 — SAME-BUILD TEST (the primary merge question)

Imagine the team builds ONE feature, component, route, content
surface, or data flow to satisfy item A. Picture the actual
implementation: the screen the role sees, the code path that
serves it, the persisted state, the API or content artifact
behind it.

Does that SAME build also satisfy item B?
  - same surface where the role finds it
  - same code path or content flow producing the effect
  - same end-to-end test would verify both

If YES on all three → A and B are the same obligation. Cluster.

If the team would build TWO different things, OR the items live on
TWO different surfaces, OR you would need TWO end-to-end tests to
cover both → distinct, do NOT cluster.

TEST 2 — SPECIAL-CASE TEST (a frequent sibling of merge)

Is one item a specific scenario, condition, audience-narrowing,
or sub-case of the other? Patterns:
  - "X for <general audience>" + "X for <narrower sub-group>"
  - "X in <general context>" + "X in <specific situation>"
  - "X across <conditions>" + "X under <one condition>"

When this holds, the narrower item is not its own requirement;
its evidence becomes an acceptance criterion or operating
condition on the broader item. Cluster them and fold the
narrower's statement into the consolidated ACs.

SURFACE-MATCH RECOGNITION — DESCRIPTORS DRIFT, SURFACE PERSISTS

When two items describe the same product surface (content,
component, decision aid, interaction, invariant) using synonymous
or relatable-variant descriptors, the surface match wins — they
are same-build. Pass 1 picked one phrasing for the same product
object out of many available ones; treating each phrasing as a
distinct obligation creates near-siblings on the list.

Signs the surface is the same:
  - product_object axis denotes the same artifact after stripping
    decorative adjectives — synonyms or near-synonyms of the
    object word are not evidence of distinct surfaces
  - the obligation lives in ONE deliverable artifact the team
    would build once
  - the acceptance_criteria across both items inspect the same
    artifact, even if worded with different descriptors

Cross-quality cluster: when two NFRs name overlapping quality
descriptors of the SAME product object (e.g. one says <q1>+<q2>
of <object>, the other says <q3>+<q4> of <object>, and the
descriptor sets overlap or are listed as synonyms in the
foundational quality list), they constrain one property of one
artifact. Cluster under the broadest quality term covered.

Cross-perspective cluster: a Pass 1 item written from one record's
perspective and another from a different perspective can describe
the SAME build if the product_object and observable_outcome match.
Perspective is the evidence's lens, not the obligation's audience —
the stakeholder axis on the obligation may differ from the record's
perspective, and two records' perspectives may converge on one
audience.

Surface-match does NOT override the contradiction guard: if two
items' acceptance_criteria genuinely contradict, they are not the
same build even when the descriptors align.

WHEN NEITHER TEST FIRES — DO NOT CLUSTER

Same topic does NOT mean same obligation. Items sharing a theme
but landing on different product objects, surfaces, or flows are
distinct obligations. Different audiences whose surfaces or flows
differ are distinct even when the topic word is identical.

Different requirement TYPE (functional vs non_functional) is
never a duplicate; the build is in different layers.

HOW TO WRITE THE CONSOLIDATED FORM for a cluster

  member_temp_ids: list every Pass 1 temp id in the cluster (2+).

  consolidated.statement: pick the most precise wording across the
    cluster; rewrite if needed to capture the union of evidence
    without drifting from any member's intent.

  consolidated.acceptance_criteria: union the ACs across members;
    remove exact duplicates; keep the smallest reviewable set.
    Special-case members contribute their statements as ACs or
    operating conditions on the parent. If two ACs contradict each
    other, the cluster is NOT actually one obligation — split it
    back: emit two narrower groups, or do not cluster at all.

  consolidated.rationale: one evidence-grounded sentence covering
    the cluster.

  consolidated.confidence: confirmed only if EVERY member was
    confirmed; inferred otherwise.

  consolidated.6 axes (trigger_event, product_object,
    observable_outcome, operating_condition,
    participation_structure, stakeholder): choose the most specific
    value across members for each axis; do not let a vague
    descriptor erase a specific one.

  consolidated.trace_refs: list the member ids you consider load-
    bearing for this obligation; Python additionally unions every
    member's trace_refs into this field after the call, so the
    final consolidated item carries every member's evidence.

  rationale: one sentence naming the single build (one surface +
    one code path or content flow + one end-to-end test) that
    satisfies every member word-for-word.

MEMBERSHIP COMPLETENESS — ANTI-LEAK RULE

Python applies the member_temp_ids list verbatim. It does NOT
infer membership from semantic overlap, shared trace_refs, or
similar statements. A Pass 1 item is in the cluster only if its
T-NNN appears in member_temp_ids — otherwise it passes through
beside your consolidated form as a separate item, regardless of
how thoroughly its evidence is already absorbed.

Before finalizing each MergeGroup, run the anti-leak scan:

  1. Read your consolidated.statement and consolidated.rationale.
  2. For every product-side claim, condition, or audience-narrowing
     in those sentences, identify the Pass 1 item whose evidence
     you used.
  3. Every such item's T-NNN must appear in member_temp_ids.

Common leak shapes that produce duplicate items in the final list:

  - You absorbed a sub-case's evidence into the broader consolidated
    statement (folded it as an AC or operating condition), but
    forgot to list the sub-case's T-NNN as a member. The sub-case
    item then passes through with its own statement — the reviewer
    sees the broad obligation AND the sub-case as siblings, both
    citing overlapping signals.

  - You cited a Pass 1 item's trace_refs (e.g. one of its signal
    ids) inside the consolidated trace_refs without listing the
    item itself as a member. The signal appears twice in the final
    list, once inside the consolidated form and once inside the
    leaked item's preserved entry.

If you would NOT include a Pass 1 item as a member, do NOT cite
its statement, ACs, or signal ids inside the consolidated form.
The two decisions move together — either fully cluster the item
or fully leave it pass-through.

DEFAULT IS DO-NOT-CLUSTER — THE COST IS ASYMMETRIC

A false cluster hides a distinct obligation inside another item:
its statement is gone, only its trace_refs remain visible to a
reviewer. Recovery requires re-reading every per-record extraction.
A false non-cluster leaves two near-siblings visible side by side
and a reviewer folds them in one click.

This asymmetry sets the bar. Emit a MergeGroup only when you can
name ONE concrete build that satisfies every member word-for-word:

  - one surface where the role finds it,
  - one code path or content flow producing the effect,
  - one end-to-end test that would verify all members.

If you have to hand-wave on any of the three, do not cluster.
"Same theme" / "same vocabulary" / "same audience" / "same quality
property name" are NOT cluster evidence — only same build is.

EVIDENCE OF AGGRESSIVE CLUSTERING — STOP AND RE-SPLIT

Two soft signals that you collapsed too much:

  1. Your merge_groups list, after Python applies pass-through,
     would leave fewer than half the Pass 1 items visible.
     Aggressive clustering at this scale almost always paired
     items on topic, not on build.
  2. A consolidated item's member_temp_ids span >3 different
     EL-NNN records and you cannot, in one sentence, name the
     single build that satisfies every member statement.

When either signal fires, re-read that cluster and split it back.
The reviewer would rather see five near-siblings than four items
with one obligation hidden inside.

NOTES

Brief substantive note on clustering decisions made. No section
header echo (Python frames the section).
"""


_PASS_ADJUDICATE = """\
PASS 2B OF 3 — VISION CONSTRAINTS + GAP/CONFLICT ADJUDICATION

You see every per-record Extraction (each item already carries a
temporary id T-NNN) plus the compact Product Vision. Your ONE job:

  (a) Walk vision.concerns and vision.assumptions for explicit
      constraints (narrowing verbs) that no Pass 1 item already
      covers — emit them as vision_constraint_items.
  (b) Adjudicate gaps across records.
  (c) Adjudicate conflicts across records.

You do NOT decide which Pass 1 items merge — a separate pass owns
that concern. You do NOT rewrite Pass 1 items. You do NOT emit
out_of_scope items (Python preserves vision.scope 1:1).

VISION CONSTRAINT WALK

For each entry in vision.concerns and vision.assumptions:
- Is the verb narrowing / bounding ("must be", "shall preserve",
  "must remain consistent with", "shall not contradict", ...)?
  → constraint candidate.
- Is the verb positive product action ("provide", "ensure",
  "enable") that the interview did not confirm anywhere?
  → baseline; drop (vision is not a source for unconfirmed
  behavior).

VISION ID IS A TRACE MARKER

Each per-record item's trace_refs already lists the vision elements
its obligation derives from. A vision id (ASM-NN, ROLE-NN,
CONCERN-NN) appearing in any per-record item's trace_refs is that
item's claim "this obligation authors this vision element into the
requirement list". The constraint is already represented through
that item — Python keeps it.

For each constraint candidate, do the trace-marker scan FIRST:

- The vision id appears in at least one per-record item's
  trace_refs → the constraint is already authored. Skip. Emitting
  a new vision_constraint_item duplicates the constraint and shows
  up as a near-sibling in the reviewer's list.
- The vision id appears in NO per-record item's trace_refs → run
  the statement-level scan: does any per-record item's statement
  or AC carry the narrowing-verb constraint without naming the
  vision id? If yes → still skip (the obligation lives there). If
  no → emit as a new vision_constraint_item. Choose type:
  non_functional for a reviewable property, system for a
  product-wide invariant.

Two failure modes the trace marker scan prevents:
- "Clarity" or "trust" constraints already carried by per-record
  items that traced the CONCERN id — without the marker scan, you
  will rephrase them slightly and emit a duplicate.
- A vision assumption verified by interview evidence (the
  per-record item already lists the ASM id) — without the marker
  scan, you will treat it as new and emit a duplicate.

Mark confidence on vision_constraint_items:
- confirmed when the vision statement directly states the
  constraint with a narrowing verb.
- inferred when the constraint is your synthesis from vision
  intent (rarer; prefer confirmed when verb is explicit).

GAP ADJUDICATION

Collect all gaps from all per-record extractions. Two gaps name
the same concept when the same answer would close both — merge
into one with the most precise wording. Drop a gap when a per-
record item already names the audience's own answer at AC
precision. Format: "<source-id>: <missing product decision>".

CONFLICT ADJUDICATION

A conflict is two per-record items that cannot both hold in the
SAME operating context. Condition differences absorbed into AC ≠
conflict. Ambivalence (mixed positive/negative signals on same
theme) ≠ conflict — that becomes a gap or an AC.

NOTES

Brief: which vision constraints you added and why; gap
adjudication summary. No section header echo.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class DistillerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="distiller")
        custom = (
            self._raw_config.get("iredev", {})
            .get("agents", {})
            .get("distiller", {})
            .get("custom_params", {})
        )
        raw_parallel = custom.get("max_parallel", 3) or 3
        try:
            self._max_parallel = max(1, int(raw_parallel))
        except (TypeError, ValueError):
            self._max_parallel = 3
        try:
            self._rate_limit_retries = max(0, int(custom.get("rate_limit_retries", 3) or 3))
        except (TypeError, ValueError):
            self._rate_limit_retries = 3
        try:
            self._rate_limit_base_delay = max(0.0, float(custom.get("rate_limit_base_delay", 5.0) or 5.0))
        except (TypeError, ValueError):
            self._rate_limit_base_delay = 5.0

    def _register_tools(self) -> None:
        """Distiller uses structured extraction only."""

    # ── Infra resilience ─────────────────────────────────────────────────────

    def _with_rate_limit_retry(self, label: str, fn: Callable[[], T]) -> T:
        """Retry on rate-limit errors with exponential backoff.

        Orchestration resilience, not product logic — a 429 would otherwise
        drop an entire interview record from synthesis.
        """
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
                    "[DistillerAgent] %s rate-limited; retrying in %.1fs (attempt %d/%d).",
                    label, delay, attempt + 1, attempts,
                )
                time.sleep(delay)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"{label}: retry loop exited without result")

    # ── Data shaping ─────────────────────────────────────────────────────────

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _compact_vision(vision: Dict[str, Any]) -> Dict[str, Any]:
        """Lean view of the Product Vision for prompt grounding."""
        def pick(raw: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
            return {key: raw.get(key) for key in keys if raw.get(key) not in (None, "", [])}

        return {
            "description": vision.get("description", ""),
            "intent_summary": vision.get("intent_summary", ""),
            "target_outcome": vision.get("target_outcome", ""),
            "notes": vision.get("notes", ""),
            "known_signals": list(vision.get("known_signals") or []),
            "roles": [
                pick(item, ["id", "name", "need", "lens", "anchor"])
                for item in (vision.get("roles") or [])
            ],
            "assumptions": [
                pick(item, ["id", "statement", "why_it_matters", "lens", "anchor"])
                for item in (vision.get("assumptions") or [])
            ],
            "concerns": [
                pick(item, ["id", "theme", "affected_roles", "rationale", "lens", "anchor"])
                for item in (vision.get("concerns") or [])
            ],
            "scope": [
                pick(item, ["id", "item", "reason", "lens", "anchor"])
                for item in (vision.get("scope") or [])
            ],
        }

    @staticmethod
    def _slim_interview_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """Slim one interview record to just what the distiller needs.

        Fields kept (9): id, perspective, context, vision_refs,
        decision_target, signals, talk, assumption_evidence, rule.

        Fields dropped (6): item (agenda id), status, close_when,
        coverage_points, coverage, interviewer_gaps — these are meta /
        interviewer-only / redundant with the signals + assumption_evidence
        the distiller already needs. Less context = less overload.
        """
        item_id = item.get("id") or item.get("item") or "EL"
        signals = [
            {"id": f"{item_id}-S{index:02d}", "text": text}
            for index, text in enumerate(item.get("signals") or [], 1)
            if str(text or "").strip()
        ]
        talk = []
        for index, turn in enumerate(item.get("talk") or [], 1):
            question = (turn.get("question") or "").strip()
            answer = (turn.get("answer") or "").strip()
            if question or answer:
                talk.append({
                    "id": f"{item_id}-T{index:02d}",
                    "question": question,
                    "answer": answer,
                })

        rule = (item.get("rule") or "").strip()
        assumption_evidence = [
            {
                "id": f"{item_id}-ASM{index:02d}",
                "vision_ref": entry.get("vision_ref") or entry.get("assumption_ref"),
                "stance": entry.get("stance"),
                "evidence": entry.get("evidence"),
                "implication": entry.get("implication"),
            }
            for index, entry in enumerate(item.get("assumption_evidence") or [], 1)
            if isinstance(entry, dict) and str(entry.get("vision_ref") or entry.get("assumption_ref") or "").strip()
        ]
        return {
            "id": item_id,
            "perspective": item.get("perspective"),
            "context": item.get("context"),
            "vision_refs": item.get("vision_refs") or item.get("assumption_refs") or [],
            "decision_target": item.get("decision_target"),
            "signals": signals,
            "talk": talk,
            "assumption_evidence": assumption_evidence,
            "rule": {"id": f"{item_id}-RULE", "text": rule} if rule else None,
        }

    @staticmethod
    def _build_known_id_set(
        compact_vision: Dict[str, Any],
        slim_records: List[Dict[str, Any]],
    ) -> set:
        """Union of source-unit ids exposed this run plus every vision id."""
        known: set = set()
        for record in slim_records:
            for signal in record.get("signals") or []:
                if isinstance(signal, dict) and signal.get("id"):
                    known.add(signal["id"])
            for turn in record.get("talk") or []:
                if isinstance(turn, dict) and turn.get("id"):
                    known.add(turn["id"])
            for entry in record.get("assumption_evidence") or []:
                if isinstance(entry, dict) and entry.get("id"):
                    known.add(entry["id"])
            rule = record.get("rule")
            if isinstance(rule, dict) and rule.get("id"):
                known.add(rule["id"])
        for key in ("roles", "assumptions", "concerns", "scope"):
            for entry in compact_vision.get(key) or []:
                if isinstance(entry, dict) and entry.get("id"):
                    known.add(entry["id"])
        return known

    @staticmethod
    def _filter_trace_refs(items: List[Requirement], known: set) -> int:
        """Drop trace_refs whose id is not exposed this run.

        Format is already enforced by the Requirement validator; this is the
        existence check that needs runtime data. Item is never rejected.
        """
        dropped = 0
        for item in items:
            kept = [
                ref for ref in item.trace_refs
                if ref in known or ref.startswith("ProductVision.")
            ]
            dropped += len(item.trace_refs) - len(kept)
            item.trace_refs = kept
        return dropped

    @staticmethod
    def _ensure_vision_oos_preserved(
        items: List[Requirement],
        raw_vision: Dict[str, Any],
    ) -> int:
        """Append one out_of_scope Requirement per vision.scope entry, 1:1.

        Pure data movement. No merge, no judgment, no skip-if-referenced.
        Every vision.scope entry becomes its own out_of_scope item in the
        final artifact regardless of whether the LLM cited the vision id
        elsewhere. Vision exclusions are categorically distinct from
        positive obligations or system invariants — they need to be
        visible as their own items.

        Returns the number of items appended.
        """
        scope = raw_vision.get("scope") or []
        if not scope:
            return 0

        appended = 0
        for entry in scope:
            if not isinstance(entry, dict):
                continue
            scope_id = str(entry.get("id") or "").strip()
            statement = str(entry.get("item") or "").strip()
            if not scope_id or not statement:
                continue
            rationale = str(entry.get("reason") or "").strip() or "Vision-declared scope boundary."
            items.append(Requirement(
                type="out_of_scope",
                stakeholder=None,
                statement=statement,
                rationale=rationale,
                trace_refs=[scope_id, "ProductVision.scope"],
                acceptance_criteria=[],
                status="excluded",
                confidence="confirmed",
            ))
            appended += 1
        return appended

    @staticmethod
    def _drop_llm_emitted_oos(items: List[Requirement]) -> int:
        """Drop any out_of_scope items the LLM emitted.

        Pass 2 is instructed not to emit out_of_scope; vision scope is
        Python's responsibility. Defensive cleanup: if the LLM emitted
        any out_of_scope items anyway, drop them before Python appends
        the vision-scope set so the final list never duplicates.

        Returns the number of items dropped. The mutation is in-place.
        """
        dropped = 0
        kept: List[Requirement] = []
        for item in items:
            if item.type == "out_of_scope" or item.status == "excluded":
                dropped += 1
                continue
            kept.append(item)
        items[:] = kept
        return dropped

    @staticmethod
    def _renumber_requirements(items: List[Requirement]) -> List[Requirement]:
        counters = {"functional": 0, "non_functional": 0, "system": 0, "out_of_scope": 0}
        prefixes = {"functional": "FR", "non_functional": "NFR", "system": "SYS", "out_of_scope": "OOS"}
        for item in items:
            if item.status == "excluded":
                item.type = "out_of_scope"
            elif item.type == "out_of_scope":
                item.status = "excluded"
            else:
                item.status = "confirmed"
            counters[item.type] += 1
            item.id = f"{prefixes[item.type]}-{counters[item.type]:03d}"
        return items

    @staticmethod
    def _renumber_conflicts(conflicts: List[Conflict]) -> List[Conflict]:
        for index, conflict in enumerate(conflicts, 1):
            conflict.id = f"CF-{index:02d}"
        return conflicts

    @staticmethod
    def _assign_temp_ids(
        extraction_results: List[Tuple[str, Extraction]],
    ) -> List[Tuple[str, Requirement]]:
        """Assign T-NNN temp ids to every Pass 1 item, in Pass 1 order.

        Mutates each Requirement.id so the value carries through when the
        extraction is dumped for Pass 2A's user prompt. Returns the list
        of (temp_id, item) pairs in original order so Python can apply
        merge groups deterministically while preserving reading order.
        """
        ordered: List[Tuple[str, Requirement]] = []
        counter = 1
        for _record_id, extraction in extraction_results:
            for item in extraction.items or []:
                tid = f"T-{counter:03d}"
                counter += 1
                item.id = tid
                ordered.append((tid, item))
        return ordered

    @staticmethod
    def _apply_merge_groups(
        pass1_items_in_order: List[Tuple[str, Requirement]],
        merge_groups: List[MergeGroup],
    ) -> Tuple[List[Requirement], List[str], int]:
        """Apply Pass 2A merge decisions deterministically.

        Pure data movement — Python never decides which items merge, only
        applies the LLM's decisions:
          - Items not referenced by any group pass through in Pass 1 order.
          - Each valid group (>=2 known members) is emitted as one
            consolidated Requirement at the position of its first member;
            later members are elided.
          - Every member's trace_refs are unioned into the consolidated
            form so no Pass 1 evidence is lost (anti-drop invariant).
          - Unknown temp ids from the LLM are dropped; an id claimed by
            two groups stays with the first.

        Returns (final_items, unknown_temp_ids, applied_group_count).
        """
        pass1_by_id: Dict[str, Requirement] = dict(pass1_items_in_order)
        claimed: Dict[str, int] = {}
        valid_members_per_group: Dict[int, List[str]] = {}
        unknown_temp_ids: List[str] = []

        for idx, group in enumerate(merge_groups):
            members: List[str] = []
            for tid in group.member_temp_ids or []:
                if tid not in pass1_by_id:
                    unknown_temp_ids.append(tid)
                    continue
                if tid in claimed:
                    continue
                members.append(tid)
            if len(members) >= 2:
                for tid in members:
                    claimed[tid] = idx
                valid_members_per_group[idx] = members

        emitted: set = set()
        final: List[Requirement] = []
        for tid, item in pass1_items_in_order:
            if tid in claimed:
                gidx = claimed[tid]
                if gidx in emitted:
                    continue
                consolidated = merge_groups[gidx].consolidated
                seen_refs = set(consolidated.trace_refs)
                unioned = list(consolidated.trace_refs)
                for mid in valid_members_per_group[gidx]:
                    for ref in pass1_by_id[mid].trace_refs:
                        if ref not in seen_refs:
                            unioned.append(ref)
                            seen_refs.add(ref)
                consolidated.trace_refs = unioned
                consolidated.id = ""
                final.append(consolidated)
                emitted.add(gidx)
            else:
                item.id = ""
                final.append(item)

        return final, unknown_temp_ids, len(valid_members_per_group)

    # ── LLM passes ───────────────────────────────────────────────────────────

    def _extract_per_item(
        self,
        slim_record: Dict[str, Any],
        compact_vision: Dict[str, Any],
        feedback_block: str,
    ) -> Extraction:
        record_id = slim_record.get("id", "EL?")
        return self._with_rate_limit_retry(
            label=f"per-record extract {record_id}",
            fn=lambda: self.extract_structured(
                schema=Extraction,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _REASONING_MOVES
                    + "\n\n" + _PASS_EXTRACT
                    + feedback_block
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(compact_vision)}\n\n"
                    f"INTERVIEW RECORD:\n{self._json(slim_record)}\n\n"
                    "Return an Extraction. Fill signal_walk with one entry per signal in the input "
                    "record; fill the six Implementation Parity axes on every Requirement; do NOT "
                    "emit out_of_scope items (Python preserves vision scope 1:1)."
                ),
                include_memory=False,
            ),
        )

    def _cluster(
        self,
        compact_vision: Dict[str, Any],
        record_extractions: List[Dict[str, Any]],
        feedback_block: str,
    ) -> MergeDecisions:
        """Pass 2A — emit merge groups only."""
        return self._with_rate_limit_retry(
            label="cluster",
            fn=lambda: self.extract_structured(
                schema=MergeDecisions,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _REASONING_MOVES
                    + "\n\n" + _PASS_CLUSTER
                    + feedback_block
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(compact_vision)}\n\n"
                    f"PER-RECORD EXTRACTIONS:\n{self._json(record_extractions)}\n\n"
                    "Each item carries a temporary id (T-NNN) in its id field. Return "
                    "MergeDecisions: merge_groups only, each grouping 2+ items that "
                    "satisfy the same-build test. Items not referenced by any group are "
                    "pass-through — do NOT emit them. For each group, list member_temp_ids "
                    "and write the consolidated Requirement (statement, six axes, ACs "
                    "unioned, confidence per the all-confirmed rule). Do NOT emit "
                    "out_of_scope items."
                ),
                include_memory=False,
            ),
        )

    def _adjudicate(
        self,
        compact_vision: Dict[str, Any],
        record_extractions: List[Dict[str, Any]],
        feedback_block: str,
    ) -> VisionAndAdjudication:
        """Pass 2B — vision constraint walk + gap/conflict adjudication."""
        return self._with_rate_limit_retry(
            label="adjudicate",
            fn=lambda: self.extract_structured(
                schema=VisionAndAdjudication,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _REASONING_MOVES
                    + "\n\n" + _PASS_ADJUDICATE
                    + feedback_block
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(compact_vision)}\n\n"
                    f"PER-RECORD EXTRACTIONS:\n{self._json(record_extractions)}\n\n"
                    "Each item carries a temporary id (T-NNN) in its id field — use it "
                    "when scanning for already-covered constraints. Return "
                    "VisionAndAdjudication: vision_constraint_items (new vision-derived "
                    "only, do not echo per-record items here), final_gaps (adjudicated, "
                    "format '<source-id>: <missing product decision>'), final_conflicts "
                    "(true cross-record clashes only), notes. Do NOT emit out_of_scope "
                    "items or decide merges."
                ),
                include_memory=False,
            ),
        )

    # ── Top-level pipeline ───────────────────────────────────────────────────

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
        raw_vision = artifacts.get("reviewed_product_vision") or state.get("product_vision") or {}
        interview = artifacts.get("reviewed_interview_record") or artifacts.get("interview_record") or {}
        items = interview.get("items") or []
        feedback = (state.get("requirement_list_feedback") or "").strip()
        feedback_block = f"\n\nReviewer feedback to address:\n{feedback}" if feedback else ""

        compact_vision = self._compact_vision(raw_vision)

        # ── Pass 1: per-record extraction in parallel ─────────────────
        slim_records = [self._slim_interview_item(item) for item in items]
        slim_by_id: Dict[str, Dict[str, Any]] = {
            str(slim.get("id") or ""): slim for slim in slim_records
        }
        extraction_results: List[Tuple[str, Extraction]] = []
        map_failures: List[str] = []

        if slim_records:
            with ThreadPoolExecutor(max_workers=self._max_parallel) as executor:
                future_to_id = {
                    executor.submit(
                        self._extract_per_item, slim, compact_vision, feedback_block
                    ): slim.get("id", "EL?")
                    for slim in slim_records
                }
                for future in as_completed(future_to_id):
                    record_id = future_to_id[future]
                    try:
                        extraction_results.append((record_id, future.result()))
                    except Exception as exc:
                        logger.warning(
                            "[DistillerAgent] Pass 1 extraction failed for %s: %s",
                            record_id, exc,
                        )
                        map_failures.append(f"{record_id}: {exc}")

        # Assign T-NNN temp ids in Pass 1 order — this mutates each
        # Requirement.id so the value carries through the model_dump
        # below, letting Pass 2A reference items by id and letting
        # Python apply merge groups deterministically.
        pass1_items_in_order = self._assign_temp_ids(extraction_results)
        pass1_item_count = len(pass1_items_in_order)

        # Bundle per-record extractions for Pass 2A + Pass 2B (same input
        # for both passes — they consume it for different concerns).
        record_extractions: List[Dict[str, Any]] = []
        for record_id, extraction in extraction_results:
            slim = slim_by_id.get(str(record_id) or "") or {}
            record_extractions.append({
                "record_id": record_id,
                "perspective": slim.get("perspective"),
                "vision_refs": slim.get("vision_refs") or [],
                "context": slim.get("context"),
                "extraction": extraction.model_dump(),
            })

        # ── Pass 2A (cluster) + Pass 2B (adjudicate) in parallel ───────
        # They consume the same Pass 1 bundle but have independent
        # concerns: Pass 2A decides merges, Pass 2B walks the vision and
        # adjudicates gaps/conflicts. Running in parallel halves the
        # serial latency without changing the rate-limit budget.
        cluster_result: Optional[MergeDecisions] = None
        adjudicate_result: Optional[VisionAndAdjudication] = None
        pass2_failures: List[str] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            cluster_future = executor.submit(
                self._cluster, compact_vision, record_extractions, feedback_block
            )
            adjudicate_future = executor.submit(
                self._adjudicate, compact_vision, record_extractions, feedback_block
            )
            try:
                cluster_result = cluster_future.result()
            except Exception as exc:
                logger.error(
                    "[DistillerAgent] Pass 2A (cluster) failed: %s", exc, exc_info=True,
                )
                pass2_failures.append(f"Pass 2A (cluster): {exc}")
            try:
                adjudicate_result = adjudicate_future.result()
            except Exception as exc:
                logger.error(
                    "[DistillerAgent] Pass 2B (adjudicate) failed: %s", exc, exc_info=True,
                )
                pass2_failures.append(f"Pass 2B (adjudicate): {exc}")

        if cluster_result is None and adjudicate_result is None:
            return {
                "_needs_srs_synthesis": False,
                "interview_complete": True,
                "errors": (state.get("errors") or []) + pass2_failures,
            }

        # ── Apply merge groups deterministically (Python data movement) ─
        # Pass-through items not in any group are preserved in Pass 1
        # order. Consolidated forms replace their first member's slot.
        # Member trace_refs are unioned into the consolidated form so no
        # Pass 1 evidence is lost regardless of what the LLM emitted.
        merge_groups = (cluster_result.merge_groups if cluster_result else []) or []
        merged_items, unknown_temp_ids, applied_groups = self._apply_merge_groups(
            pass1_items_in_order, merge_groups,
        )
        if unknown_temp_ids:
            logger.info(
                "[DistillerAgent] Pass 2A referenced %d unknown temp id(s): %s",
                len(unknown_temp_ids), ", ".join(unknown_temp_ids[:8]),
            )

        vision_constraint_items: List[Requirement] = list(
            adjudicate_result.vision_constraint_items if adjudicate_result else []
        )
        final_items: List[Requirement] = merged_items + vision_constraint_items
        final_gaps = list(adjudicate_result.final_gaps if adjudicate_result else [])
        final_conflicts = list(adjudicate_result.final_conflicts if adjudicate_result else [])

        known_ids = self._build_known_id_set(compact_vision, slim_records)
        dropped_refs = self._filter_trace_refs(final_items, known_ids)
        if dropped_refs:
            logger.info(
                "[DistillerAgent] Dropped %d trace_ref entries with unknown ids.",
                dropped_refs,
            )

        # Drop any LLM-emitted out_of_scope items BEFORE appending the
        # vision-scope set, so OOS items in the final list come solely
        # from vision.scope (pure 1:1 data movement).
        llm_oos_dropped = self._drop_llm_emitted_oos(final_items)
        if llm_oos_dropped:
            logger.info(
                "[DistillerAgent] Dropped %d LLM-emitted out_of_scope item(s); "
                "vision scope is handled by Python.",
                llm_oos_dropped,
            )

        vision_oos_added = self._ensure_vision_oos_preserved(final_items, raw_vision)
        if vision_oos_added:
            logger.info(
                "[DistillerAgent] Preserved %d vision scope item(s) as out_of_scope.",
                vision_oos_added,
            )

        final_items = self._renumber_requirements(final_items)
        final_conflicts = self._renumber_conflicts(final_conflicts)

        # ── Assemble reviewer notes ──────────────────────────────────
        per_record_notes = "\n".join(
            f"  [{record_id}]: {(extraction.notes or '').strip()}"
            for record_id, extraction in extraction_results
            if extraction.notes
        )
        cluster_note = (
            (cluster_result.notes or "").strip() if cluster_result else ""
        ) or "(no cluster note)"
        adjudicate_note = (
            (adjudicate_result.notes or "").strip() if adjudicate_result else ""
        ) or "(no adjudicate note)"
        cluster_stats = (
            f"  - Pass 1 items: {pass1_item_count}; merge groups applied: "
            f"{applied_groups}; items folded: "
            f"{pass1_item_count - (len(merged_items))}"
        )
        failure_block = (
            "\n\nPASS 1 FAILURES\n  " + "\n  ".join(map_failures)
            if map_failures else ""
        )
        pass2_failure_block = (
            "\n\nPASS 2 FAILURES\n  " + "\n  ".join(pass2_failures)
            if pass2_failures else ""
        )
        vision_oos_block = (
            f"\n\nVISION OOS PRESERVATION (Python, deterministic)\n"
            f"  - Preserved {vision_oos_added} vision scope item(s) as out_of_scope."
            if vision_oos_added else ""
        )

        final = RequirementList(
            notes=(
                "PASS 1 — PER-RECORD EXTRACTION\n"
                f"{per_record_notes or '  (no per-record notes)'}\n\n"
                "PASS 2A — CLUSTER\n"
                f"  {cluster_note}\n"
                f"{cluster_stats}\n\n"
                "PASS 2B — VISION + ADJUDICATE\n"
                f"  {adjudicate_note}"
                f"{failure_block}"
                f"{pass2_failure_block}"
                f"{vision_oos_block}"
            ),
            items=final_items,
            conflicts=final_conflicts,
            gaps=final_gaps,
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
