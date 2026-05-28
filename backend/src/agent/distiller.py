"""
distiller.py - DistillerAgent

Map-reduce synthesis turning interview evidence into a structured
RequirementList. Pass 2 is split so the LLM never juggles preserve-
vs-merge pressure in the same call:

  Pass 1 (EXTRACT)        — TALK-DRIVEN, BATCHED BY PERSPECTIVE.
                            Records sharing one role go in one LLM
                            call. Pass 1 owns ONE concern: read the
                            records like a structured observation of
                            the role's life around the product and
                            propose every product obligation the
                            evidence supports — every friction,
                            workaround, wish, or revealed need that
                            points at a product-side mechanism is a
                            candidate. Duplicates and near-siblings
                            are EXPECTED here; Pass 2A folds them.
                            Each item's trace_refs cite source units
                            (turn ids, assumption-evidence ids, rule
                            ids, vision ids) so every proposal is
                            auditable. Perspective groups run in
                            parallel.

  Pass 2A (CLUSTER)       — DECISION ONLY. Owns ALL deduplication
                            (within-perspective AND cross-perspective).
                            Walks the items Pass 1 emitted across
                            every perspective and identifies clusters
                            satisfied by ONE shippable piece of
                            product work. When a cluster mixes
                            confirmed and inferred members, the
                            confirmed item is the spine (EXTRACTION
                            OVER INFERENCE). Items not in any group
                            pass through unchanged via Python.

  Pass 2B (ADJUDICATE)    — VISION + GAPS + CONFLICTS. Runs AFTER
                            Pass 2A so it sees the POST-MERGE item set
                            (each item carrying a T-NNN for a pass-
                            through or M-NNN for a consolidated form),
                            plus all gaps and conflicts collected
                            across perspectives, plus a cluster summary
                            showing which member_temp_ids Pass 2A
                            merged. This sequencing prevents two
                            failure modes parallel execution allowed:
                            conflicts emitted on items Pass 2A already
                            consolidated (dangling refs after merge),
                            and vision_constraint_items duplicating
                            a consolidated capability.

Pass 2A and Pass 2B run sequentially; Pass 1 perspective batches run
in parallel because each batch is independent of the others.

Vision scope (OOS) items are preserved by Python as pure 1:1 data
movement. Every vision.scope entry becomes one out_of_scope
Requirement in the final artifact, regardless of whether the LLM
referenced the vision id elsewhere. The LLM is forbidden from emitting
out_of_scope items; any it emits are filtered out before Python
appends the vision-scope set.

Schema descriptions say WHAT a field holds. Prompt bodies state each
pass's purpose and the guarantees its output must meet — definitions
and dichotomies, never step-by-step procedure. No domain, topic, role
name, or product category is hardcoded.

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

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Tuple, TypeVar

from pydantic import BaseModel, Field, field_validator

from .base import BaseAgent

logger = logging.getLogger(__name__)


RequirementType = Literal["functional", "non_functional", "system", "out_of_scope"]

# Deterministic id-format guards. Source unit ids live inside an EL-NNN
# record at a specific sub-id; vision ids match canonical prefixes;
# vision paths are stable strings. Anything else is rejected so the
# "no bare item ids" rule holds at the schema boundary.
_SOURCE_UNIT_RE = re.compile(r"^EL-\d{3}-(?:T\d{2,}|ASM\d{2,}|RULE)$")
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
    id: str = Field(default="", description="Leave empty; ids are assigned automatically.")
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
        "Source-unit ids and vision ids that anchor this obligation in evidence. Valid forms: "
        "EL-NNN-TNN (talk turn), EL-NNN-ASMNN (assumption evidence), EL-NNN-RULE (closure "
        "summary), ASM-NN / ROLE-NN / CONCERN-NN / OOS-NN (vision ids), or stable paths "
        "starting with 'ProductVision.'. No bare item ids (EL-NNN alone is invalid)."
    ))
    acceptance_criteria: List[str] = Field(default_factory=list, description=(
        "Smallest non-duplicative set of product-observable checks. Each AC tests ONE aspect of this "
        "obligation's mechanism. When the obligation surfaced across stakeholders or operating conditions, "
        "ACs may be written as context-conditional branches ('When <role/condition>, the product …'). "
        "Empty for out_of_scope items."
    ))
    status: Literal["confirmed", "excluded"] = Field(description=(
        "confirmed for implementable items; excluded only for out_of_scope boundaries."
    ))
    confidence: Literal["confirmed", "inferred"] = Field(description=(
        "confirmed: obligation directly grounded in stated evidence — input intent named it, "
        "a stakeholder utterance in the talk explicitly described it, or a vision assumption "
        "was verified by interview. inferred: your synthesis from context — symptom→cause "
        "translation, product-side translation of role process, or a boundary that follows "
        "logically from multiple turns of talk without being directly stated. Inference is "
        "legitimate work when evidence supports it; do not avoid inferring just to label "
        "everything confirmed."
    ))

    # ── Implementation Parity axes ──────────────────────────────────────────
    # These axes describe an obligation precisely enough that the cluster pass
    # can judge which items one build would satisfy. Their meaning lives in the
    # field descriptions below; the cluster pass reads the values — it is not
    # handed a rule for combining them.

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
    id: str = Field(default="", description="Leave empty; ids are assigned automatically.")
    kind: Literal["clash", "unclear"] = Field(description=(
        "clash for incompatible obligations; unclear for unresolved evidence."
    ))
    left: str = Field(description="Requirement id, source unit id, or vision id on one side.")
    right: str = Field(description="Requirement id, source unit id, or vision id on the other side.")
    scope: str = Field(description="Shared operating context where the conflict applies.")
    issue: str = Field(description="Why the sides cannot both hold, or what remains ambiguous.")
    paths: List[str] = Field(default_factory=list, description="Reviewer choices that could resolve the conflict.")
    refs: List[str] = Field(default_factory=list, description="Evidence references supporting the conflict.")


class PerspectiveExtraction(BaseModel):
    """The product obligations one role's interview evidence implies.

    Bundles every interview record sharing one perspective (role). The
    obligations are proposed broadly — overlapping candidates are
    expected and not a defect; consolidating duplicates is not this
    step's job. Trace_refs cite specific source units (turn ids
    EL-NNN-TNN, assumption-evidence ids EL-NNN-ASMNN, rule ids
    EL-NNN-RULE, and vision ids) so every item is auditable.
    """
    perspective: str = Field(description=(
        "The shared role name across every record in this batch."
    ))
    reasoning: str = Field(description=(
        "Your thinking before you list the obligations — write this first, as a "
        "working scratchpad, not polished prose. Reason out from the evidence the "
        "distinct things this product must owe, and shape each so it stands on its "
        "own: one independent, valuable, testable obligation a team could size and "
        "ship by itself. Carving cleanly here is what makes the items below easy "
        "to compare and fold later."
    ))
    notes: str = Field(default="", description=(
        "Brief reviewer-facing commentary about what the evidence in "
        "this perspective surfaced — recurring observations, frictions, "
        "workarounds, wishes, and any inference the items propose."
    ))
    items: List[Requirement] = Field(default_factory=list, description=(
        "Product obligations this perspective's evidence implies, each "
        "grounded in its trace_refs. Propose broadly — overlapping "
        "candidates are fine and expected, so do not consolidate "
        "duplicates here. Do not emit out_of_scope items."
    ))
    gaps: List[str] = Field(default_factory=list, description=(
        "Within-perspective gaps — design questions the talk raised but "
        "did not settle. Format: '<source-id>: <missing product decision>'."
    ))
    conflicts: List[Conflict] = Field(default_factory=list, description=(
        "Within-perspective conflicts only — true clashes the records in "
        "this batch surface against each other."
    ))


class MergeGroup(BaseModel):
    """One cluster of items that describe the same product obligation.

    Two or more items that one build (one feature / surface / flow)
    would satisfy, together with the unified obligation that replaces
    them. Items not referenced by any group are left unchanged — only
    the duplicates belong here.
    """
    member_temp_ids: List[str] = Field(description=(
        "Temporary ids (T-NNN) of the items this group consolidates. "
        "Two or more required — a single-item group is not a cluster, do not emit it. "
        "Items not listed in any group are left unchanged."
    ))
    consolidated: Requirement = Field(description=(
        "The base-capability obligation satisfied by ONE build that covers every member. "
        "Subject is product-side. The acceptance_criteria carry the smallest reviewable check set "
        "for this capability; when members differ by perspective or operating condition, ACs may "
        "be written as context-conditional branches so each member's distinct context stays "
        "visible. Its descriptive fields (trigger, product object, observable outcome, condition, "
        "participation, stakeholder) hold the broadest value accurate to every member, with the "
        "specifics carried in the ACs. Confidence is confirmed only if EVERY member was confirmed; "
        "inferred otherwise."
    ))
    rationale: str = Field(description=(
        "One short sentence naming the single concrete build (one surface + one code path or content "
        "flow + one end-to-end test, possibly parameterised by perspective / condition) that "
        "satisfies every member."
    ))


class MergeDecisions(BaseModel):
    """The clusters of same-build duplicates found among the obligations.

    Each cluster names the duplicate items and the unified obligation
    that replaces them. Items in no cluster are left unchanged and are
    never restated here.
    """
    reasoning: str = Field(description=(
        "Your thinking before you choose the groups — write this first, as a "
        "working scratchpad. Reason over the obligations and work out which ones "
        "describe the same underlying build (the same shippable thing) even when "
        "their wording, the role they name, or their framing differ, and which "
        "only look alike but are really separate builds. Naming the equivalences "
        "here first is what lets the groups below be complete."
    ))
    merge_groups: List[MergeGroup] = Field(default_factory=list, description=(
        "Capability clusters: groups of 2+ items that one build would satisfy (ONE build covers "
        "all members). Items not listed in any group are left unchanged; only the consolidation "
        "belongs here."
    ))
    notes: str = Field(description=(
        "Brief reviewer-facing note about the clustering decisions made — which capability "
        "clusters were identified and why. No section header echo."
    ))


class VisionAndAdjudication(BaseModel):
    """Vision-limit obligations plus the adjudicated gaps and conflicts.

    Covers exactly three things: obligations that come only from the
    vision's explicit limits (narrowing verbs) that no current item
    already carries, the adjudicated gaps, and the surviving true
    conflicts. Does not decide merges and does not rewrite existing items.
    """
    notes: str = Field(description=(
        "Brief reviewer-facing note about vision constraints added and "
        "adjudication. No section header echo."
    ))
    vision_constraint_items: List[Requirement] = Field(default_factory=list, description=(
        "NEW non_functional or system items derived from explicit vision constraints "
        "(narrowing verbs in vision.concerns / vision.assumptions) that no current item "
        "already covers. Do not emit out_of_scope items."
    ))
    final_gaps: List[str] = Field(default_factory=list, description=(
        "Gaps adjudicated across all the evidence. Format: '<source-id>: <missing "
        "product decision>'. Merge two gaps when the same answer would close both."
    ))
    final_conflicts: List[Conflict] = Field(default_factory=list, description=(
        "True conflicts only — two obligations that cannot both hold in the "
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
# Layout: every pass uses the shared _FOUNDATIONS block plus one pass-
# specific block. _FOUNDATIONS states what a requirement is, the build-
# don't-transcribe mindset, and the guarantees every requirement must meet;
# each pass block states that pass's purpose and what its output must ensure.
# Both are narrative — definitions and dichotomies, never numbered procedure.
# No domain, topic, role name, or category is hardcoded.
# ─────────────────────────────────────────────────────────────────────────────

_FOUNDATIONS = """\
FOUNDATIONS

A requirement is one product obligation — something the product must
do, must hold as a property, must guarantee as an invariant, or must
explicitly refuse to take on. The interview is evidence about a
person's life around the product: what they do, want, avoid, work
around, or struggle with. Evidence is not itself a requirement; your
work is to decide what the product must therefore be obligated to do.
The schema names the requirement types; the product's out_of_scope
boundaries are added separately, so you never emit them.


BUILD THE LIST, DON'T TRANSCRIBE IT. You are composing the requirement
list a team could build this product from — not minuting what was
said. Most of what a working product owes is never spoken aloud:
people describe the friction they feel, not the mechanisms, states,
recoveries, and guarantees a product needs to remove it. Reason
outward from the lived evidence to the full set of obligations the
described product must carry for that life to actually work — the
happy path and the states around it, the failure someone fears and
the product's answer to it, the task done by hand and the product
doing it instead. Inferring an obligation the evidence implies but no
one named is the heart of this work, not a liberty taken sparingly.
The only discipline on inference: it must trace to evidence in front
of you and name a mechanism the product can actually own. Where you
cannot ground an obligation, that absence is a gap to surface — never
a requirement to invent.


EVIDENCE LEADS, VISION BOUNDS. The interview is the authority for what
the product does; infer positive obligations from it freely. The
vision is the authority for the product's limits — what it must
respect and what it must leave to others. From the vision take
constraints and exclusions, not new capabilities the interview never
implied.


PRODUCT-SIDE AND BUILDABLE. A requirement speaks as the product or a
product-owned artifact and uses a verb the product can perform —
something a team can write code or content for and a reviewer can
later check on the product itself. When the natural phrasing makes a
person the subject, or names something only humans do — feeling,
trusting, deciding outside the product — find the product-owned object
the obligation really turns on and state it from the product's side.


ATOMIC — SPRINT-READY. Downstream the team sizes, estimates, and
accepts these one at a time, so each must stand as a single piece of
work: independent enough to ship alone, valuable enough that shipping
it means something, small enough to fit a sprint, and checkable as one
obligation. An item hiding two obligations reads as one ticket but
behaves as two — it cannot be sized or accepted cleanly. This is the
why behind every judgment of grain, not a checklist: when one
shippable build that one end-to-end check verifies would cover a
candidate, it is one item; when it would force two distinct builds or
two independent checks, it is two. Everything else — a different
surface, condition, audience, or example — is weighed inside that
one-build-one-check judgment, never a reflex to split or fold.


DISTINCT — NO ASPECT TWICE. A long list earns its length from the
range of distinct obligations in it, never from restating one
mechanism in different words. Breadth means covering the many
different things the evidence implies the product owes; it does not
mean saying one obligation from several angles. Two items one build
would satisfy and one check would verify are one obligation said
twice.


ACCEPTANCE CRITERIA THE TEAM CAN CHECK. Each criterion is something a
reviewer could confirm by inspecting the product, not by asking a user
how they feel. Each verifies one aspect of its parent's single
obligation; a criterion that introduces a separate object, workflow,
or independently checkable constraint is a different obligation hiding
in the wrong item — let it become its own.


CONFIDENCE — PROBLEM OR SOLUTION. Mark an obligation confirmed when a
turn of talk, or a vision assumption the interview verified, already
states it in product terms; mark it inferred when you synthesised the
product-side obligation yourself from friction, workaround, wish, or a
chain of turns that never named it. Both are honest work and a good
list is a healthy mix of the two; judge each item on its own, never
toward a ratio.


GROUNDED IN CITED EVIDENCE. Every requirement cites the source units
that support it; the schema documents the valid id forms. An obligation
with no genuine evidence behind it is invention.


THE EVIDENCE'S OWN VOCABULARY. Name things as the evidence in front of
you names them. Do not import role names, product categories, domain
examples, or policy templates from outside this run.
"""


_PASS_EXTRACT = """\
THIS PASS — OBLIGATIONS FROM ONE PERSPECTIVE'S EVIDENCE

You see every interview record from one role, plus the compact Product
Vision. Your purpose is to build, from this evidence, the broadest
honest set of distinct product obligations the described life implies,
and to hold nothing back for fear of overlap. A later pass folds true
duplicates and another settles gaps and conflicts; here, the only loss
that cannot be recovered is a real obligation never proposed, so reason
expansively.

Treat the records as a window into how this role actually lives around
the product: every friction, workaround, wish, surprise, fear, and
unmet need is a place the product could owe an obligation. One record
usually implies several distinct mechanisms — such as a surface to act
on, a state to track, a rule to enforce, a recovery when something
fails, a signal that makes status visible, something worth recording,
or a property the result must hold. Follow each one the evidence
implies. Let the evidence's real density decide how many obligations
you draw; a thin record yields few and a rich one many. Never aim at a
number, and never thin the list because it is growing.

Think the carve-up through in the reasoning field first, then list the
obligations. You ensure each is distinct from the others, is grounded
in the specific evidence it cites, carries honest confidence, and is
stated so a team could build and check it. You do not fold near-
duplicates here — that is the next pass — and you do not emit
out_of_scope items. Where the evidence raised a decision it never
settled, surface it as a gap rather than guessing the answer.
"""


_PASS_CLUSTER = """\
THIS PASS — FOLD TRUE DUPLICATES INTO ONE OBLIGATION

You see every obligation the previous pass produced across all
perspectives — each with a temporary id and a lookup giving its
perspective and source records — plus the compact Product Vision. That
pass was told to reason broadly and ignore overlap, so near-duplicates
within a perspective and across perspectives are expected. Your purpose
is to make the list non-redundant: where several items would all be
satisfied by one shippable build that one end-to-end check verifies,
replace them with the single obligation that covers them.

Think the clustering through first in the reasoning field, then emit
only the merge groups; any item you do not name in a group is kept
unchanged, so you never restate pass-through items.
The judgment is semantic, not lexical: two items are the same
obligation when one shippable build would satisfy both — even if their
wording, the role they name, or their framing share nothing, and even
when they differ by a surface, audience, or condition that one
parameterised build still covers. They stay distinct only when the
builds genuinely differ, however alike the words look. What matters is
the build underneath the words, and no obligation should survive this
pass stated twice. When a cluster mixes confirmed and inferred members, the
confirmed member's phrasing is the spine of the consolidated
obligation. The consolidated form must still read as one buildable,
checkable obligation; if pulling members together would bury two real
obligations under one heading, they were never duplicates — leave them
separate.

The two mistakes cost the same. Burying two obligations as one hides
work the team must size; leaving the same obligation in twice inflates
the backlog and distorts sizing and priority just as badly. So when one
build genuinely covers several items, folding them is the correct call,
not a risky one — never leave a true repeat standing for safety's sake.
You ensure the folded list loses no distinct obligation and keeps none
stated twice. You do not walk the vision, settle gaps, or settle
conflicts — those are the next pass.
"""


_PASS_ADJUDICATE = """\
THIS PASS — VISION LIMITS, GAPS, AND CONFLICTS

You see the obligations after duplicates have been folded — each with
a temporary id, the merged ones carrying the union of their members'
evidence — plus every gap and conflict the earlier pass collected, a
summary of what was merged, and the compact Product Vision. Your
purpose is exactly three things: add obligations that come only from
the vision's limits, settle the gaps, and settle the conflicts.

From the vision, add an obligation only where it genuinely narrows or
excludes something no current item already carries — a limit the
product must respect. A positive capability the interview never
implied is invention, not a vision constraint, so leave it out. The
prompt hands you the vision ids no current item references, so the
candidates to weigh are few.

For the gaps, deliver the reader one clean list: fold gaps the same
answer would close into the best-worded one, and drop any a current
obligation already settles. For the conflicts, keep only true clashes
— two obligations that cannot both hold in the same situation. A
difference in condition that an obligation's own criteria absorb is
not a clash, and two items that were just merged are not in conflict.

You ensure you neither re-merge nor rewrite obligations and never emit
out_of_scope items; merging is done, and the vision's scope is
preserved separately.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Feedback re-run blocks (only attached when reviewer feedback is present)
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
points it names; it does not loosen any other guarantee the pass
already owes (anti-drop on trace_refs, lens/confidence honesty,
one-build-one-check grain, no out_of_scope emission).
"""


_FEEDBACK_BODY = """\
REVIEWER FEEDBACK — YOU MUST ADDRESS EVERY POINT BELOW:
{feedback}

Apply each point at the requirement-level field it names:
  type · subject · obligation · confidence · trace_refs ·
  Implementation Parity axes · notes.

When a point names a specific requirement (by id, by phrasing, or
by the obligation it carries): make the change on that requirement
and only that requirement. When a point names a category (FR / NFR
/ SYS / a vision_ref / a perspective), apply the change to every
item in scope, then say so in notes.

Do NOT widen an inferred item to confirmed just to satisfy a
phrasing request, and do NOT drop trace_refs to make a rewrite
"cleaner" — the anti-drop invariant still holds.
"""


_FEEDBACK_CONFLICT_CLAUSE = """\
CONFLICT RESOLUTION UNDER FEEDBACK — HARD RULE.

In this pass you decide which conflicts surface as final_conflicts,
which dissolve under merge, and which vision_constraint_items earn
a slot. Whenever the reviewer feedback above addresses a conflict
you are about to adjudicate — directly (naming the conflicting
items / vision_ref) or by direction (telling you which side the
product should take, what to drop, what must remain) — you MUST
resolve in the direction the feedback prescribes. The reviewer's
instruction is the authoritative tiebreaker; do not "average" it
against the on-paper evidence balance and do not re-flag it as a
fresh final_conflict for the reviewer to re-decide.

Your own adjudication only governs conflicts the feedback is
silent on. For every conflict the feedback DID resolve, record the
resolved direction in notes so the audit makes the deference
visible.
"""


def _build_feedback_block(feedback: str, include_conflict_clause: bool = False) -> str:
    """Assemble the feedback insertion appended to the system prompt.

    Returns an empty string when no feedback is present, so passes that
    are not re-runs see no extra body. When ``include_conflict_clause``
    is True, appends the Pass 2B-only adjudication directive.
    """
    if not feedback:
        return ""
    parts = [_FEEDBACK_PREAMBLE, _FEEDBACK_BODY.format(feedback=feedback)]
    if include_conflict_clause:
        parts.append(_FEEDBACK_CONFLICT_CLAUSE)
    return "\n\n" + "\n\n".join(parts)


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

    async def _a_with_rate_limit_retry(
        self, label: str, async_fn: Callable[[], Awaitable[T]],
    ) -> T:
        """Async counterpart of ``_with_rate_limit_retry``.

        Uses ``asyncio.sleep`` so the back-off does not block the event
        loop while other Pass 1 perspective batches are still in flight.
        """
        attempts = self._rate_limit_retries + 1
        last_exc: Optional[BaseException] = None
        for attempt in range(attempts):
            try:
                return await async_fn()
            except Exception as exc:
                last_exc = exc
                if not _is_rate_limit_error(exc) or attempt + 1 >= attempts:
                    raise
                delay = self._rate_limit_base_delay * (3 ** attempt)
                logger.warning(
                    "[DistillerAgent] %s rate-limited; retrying in %.1fs (attempt %d/%d).",
                    label, delay, attempt + 1, attempts,
                )
                await asyncio.sleep(delay)
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

        Kept: id, perspective, scene, frictions_to_probe, talk (raw Q/A
        turns), assumption_evidence (stance + evidence only), rule.

        Talk is the primary evidence. Pass 1 re-extracts atomic facts
        directly from dialogue. The interviewer's per-turn signal
        atomization is no longer fed — distiller's stronger model in
        batch mode does the extraction more reliably from talk than
        from an interviewer's lossy pre-extraction.

        Dropped: status, close_when, coverage, signals (entirely
        removed from pipeline), assumption_evidence's implication field
        — meta or interviewer-side guesses that bias synthesis.
        """
        item_id = item.get("id") or item.get("item") or "EL"
        rule = (item.get("rule") or "").strip()
        assumption_evidence = [
            {
                "id": f"{item_id}-ASM{index:02d}",
                "vision_ref": entry.get("vision_ref") or entry.get("assumption_ref"),
                "stance": entry.get("stance"),
                "evidence": entry.get("evidence"),
            }
            for index, entry in enumerate(item.get("assumption_evidence") or [], 1)
            if isinstance(entry, dict) and str(entry.get("vision_ref") or entry.get("assumption_ref") or "").strip()
        ]
        # Raw Q/A turns from the interview. Pass 1 reads these as primary
        # evidence; the explicit `id` field gives the LLM a ready-made
        # trace_ref it can cite directly (EL-NNN-TNN) without having to
        # construct the id by hand.
        talk_turns = [
            {
                "id": f"{item_id}-T{index:02d}",
                "turn": index,
                "question": (entry.get("question") or "").strip(),
                "answer": (entry.get("answer") or "").strip(),
            }
            for index, entry in enumerate(item.get("talk") or [], 1)
            if isinstance(entry, dict)
            and (entry.get("question") or "").strip()
            and (entry.get("answer") or "").strip()
        ]
        return {
            "id": item_id,
            "perspective": item.get("perspective"),
            "scene": item.get("scene") or item.get("context"),
            "frictions_to_probe": item.get("frictions_to_probe") or item.get("coverage_points") or [],
            "talk": talk_turns,
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
        perspective_results: List[Tuple[str, "PerspectiveExtraction"]],
    ) -> List[Tuple[str, Requirement]]:
        """Assign T-NNN temp ids to every Pass 1 item, in Pass 1 order.

        Mutates each Requirement.id so the value carries through when the
        extraction is dumped for Pass 2A's user prompt. Returns the list
        of (temp_id, item) pairs in original order so Python can apply
        merge groups deterministically while preserving reading order.
        """
        ordered: List[Tuple[str, Requirement]] = []
        counter = 1
        for _perspective, extraction in perspective_results:
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
                # Keep a stable post-merge id so Pass 2B can reference
                # the consolidated form. Final FR/NFR/SYS numbering
                # happens later in _renumber_requirements.
                consolidated.id = ""
                final.append(consolidated)
                emitted.add(gidx)
            else:
                # Pass-through items keep their T-NNN so Pass 2B can
                # cite them; final numbering reassigns later.
                final.append(item)

        return final, unknown_temp_ids, len(valid_members_per_group)

    @staticmethod
    def _assign_post_merge_ids(items: List[Requirement]) -> None:
        """Assign post-merge temp ids in place.

        Pass-through items keep their T-NNN (already set in Pass 1).
        Consolidated items (id was cleared in _apply_merge_groups) get
        M-NNN so Pass 2B can reference both kinds cleanly. Final
        FR/NFR/SYS numbering happens later in _renumber_requirements.
        """
        merged_counter = 1
        for item in items:
            if not (item.id or "").strip():
                item.id = f"M-{merged_counter:03d}"
                merged_counter += 1

    # ── LLM passes ───────────────────────────────────────────────────────────

    @staticmethod
    def _touched_vision_stances(
        slim_records: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, str]]]:
        """Aggregate assumption_evidence stances across the batch.

        Pure shape-reorganization of data the interviewer already emitted —
        no semantic judgment. Returns vision_ref → list of
        {record, stance, evidence_id} so Pass 1 sees which vision ids
        the dialogue has explicit stance on (used to mark confidence
        accurately).
        """
        stances: Dict[str, List[Dict[str, str]]] = {}
        for record in slim_records:
            rid = str(record.get("id") or "")
            for entry in record.get("assumption_evidence") or []:
                if not isinstance(entry, dict):
                    continue
                vref = str(entry.get("vision_ref") or "").strip()
                stance = str(entry.get("stance") or "").strip()
                if not vref or not stance:
                    continue
                stances.setdefault(vref, []).append({
                    "record": rid,
                    "stance": stance,
                    "evidence_id": str(entry.get("id") or ""),
                })
        return stances

    async def _aextract_per_perspective(
        self,
        perspective: str,
        slim_records: List[Dict[str, Any]],
        compact_vision: Dict[str, Any],
        feedback_block: str,
    ) -> PerspectiveExtraction:
        """Pass 1 batch — assemble requirements across one perspective's records.

        Async so perspective batches can be driven concurrently with
        ``asyncio.gather``. The model sees every record of one role as
        one corpus of lived evidence and emits items directly on the
        PerspectiveExtraction — trace_refs cite specific turn ids so a
        single item may draw evidence from one record or several.
        Cross-perspective consolidation remains Pass 2A's concern.
        """
        record_ids = [str(r.get("id") or "EL?") for r in slim_records]
        label = f"per-perspective extract {perspective} ({len(slim_records)} records)"
        # Compact batch payload — the model sees every record in one
        # call and assembles items across them. record_ids are listed
        # for context (so the model can cite specific turn ids cleanly)
        # but no longer a per-record emission contract.
        batch_payload = {
            "perspective": perspective,
            "record_ids": record_ids,
            "records": slim_records,
        }
        # Touched-stances map: reorganized view of assumption_evidence
        # already emitted by the interviewer. Pure aggregation; no
        # semantic judgment. Helps Pass 1 mark confidence accurately —
        # when a vision_ref has stance=supports here, items derived
        # from that ASM can legitimately be confidence=confirmed.
        touched_stances = self._touched_vision_stances(slim_records)

        async def _call() -> PerspectiveExtraction:
            return await self.aextract_structured(
                schema=PerspectiveExtraction,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _PASS_EXTRACT
                    + feedback_block
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(compact_vision)}\n\n"
                    f"TOUCHED VISION STANCES (vision_ref → the stances the "
                    f"dialogue recorded for it):\n{self._json(touched_stances)}\n\n"
                    f"PERSPECTIVE BATCH:\n{self._json(batch_payload)}\n\n"
                    "Return a PerspectiveExtraction whose perspective equals the "
                    "batch perspective. Build the broadest set of distinct "
                    "product obligations this evidence implies, each grounded in "
                    "the source units it cites (turn ids EL-NNN-TNN, assumption-"
                    "evidence ids EL-NNN-ASMNN, rule ids EL-NNN-RULE, vision ids). "
                    "Do not fold near-duplicates and do not emit out_of_scope "
                    "items."
                ),
                include_memory=False,
            )

        return await self._a_with_rate_limit_retry(label, _call)

    async def _arun_pass1(
        self,
        perspective_groups: Dict[str, List[Dict[str, Any]]],
        compact_vision: Dict[str, Any],
        feedback_block: str,
    ) -> List[Tuple[str, Any]]:
        """Drive every Pass 1 perspective batch concurrently.

        A semaphore caps in-flight calls at ``self._max_parallel`` so the
        provider's per-second / concurrent-request budget still binds.
        Returns ``(perspective, result_or_exception)`` tuples in input
        order; the caller maps each batch back to its expected record_ids.
        Exceptions are returned rather than raised so a single failing
        perspective does not abort the rest of the synthesis run.
        """
        semaphore = asyncio.Semaphore(self._max_parallel)

        async def _bounded(
            persp: str, records: List[Dict[str, Any]],
        ) -> PerspectiveExtraction:
            async with semaphore:
                return await self._aextract_per_perspective(
                    persp, records, compact_vision, feedback_block,
                )

        persps = list(perspective_groups.keys())
        coros = [_bounded(persp, perspective_groups[persp]) for persp in persps]
        results = await asyncio.gather(*coros, return_exceptions=True)
        return list(zip(persps, results))

    @staticmethod
    def _temp_id_context(
        perspective_extractions: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, str]]:
        """Map T-NNN → {perspective, source_records}.

        Pure lookup over the perspective_extractions Python has already
        built. Pass 2A uses this to write context-conditional ACs when
        clustering members from different perspectives. Source records
        are derived from each item's trace_refs (EL-NNN prefixes) so the
        cluster pass can still see which records contributed evidence,
        without forcing a 1:1 record-to-item shape upstream.
        """
        ctx: Dict[str, Dict[str, str]] = {}
        for entry in perspective_extractions:
            persp = str(entry.get("perspective") or "")
            for item in entry.get("items") or []:
                if not isinstance(item, dict):
                    continue
                tid = str(item.get("id") or "")
                if not tid:
                    continue
                source_records: List[str] = []
                seen: set = set()
                for ref in item.get("trace_refs") or []:
                    text = str(ref or "")
                    # EL-NNN-* → source record prefix
                    if text.startswith("EL-") and len(text) >= 6:
                        rid = text.split("-", 2)
                        if len(rid) >= 2:
                            record = f"{rid[0]}-{rid[1]}"
                            if record not in seen:
                                seen.add(record)
                                source_records.append(record)
                ctx[tid] = {
                    "perspective": persp,
                    "source_records": ", ".join(source_records) or "(no record ids)",
                }
        return ctx

    def _cluster(
        self,
        compact_vision: Dict[str, Any],
        perspective_extractions: List[Dict[str, Any]],
        feedback_block: str,
    ) -> MergeDecisions:
        """Pass 2A — emit merge groups only."""
        temp_id_ctx = self._temp_id_context(perspective_extractions)
        return self._with_rate_limit_retry(
            label="cluster",
            fn=lambda: self.extract_structured(
                schema=MergeDecisions,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _PASS_CLUSTER
                    + feedback_block
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(compact_vision)}\n\n"
                    f"TEMP_ID CONTEXT (T-NNN → perspective / source_records for "
                    f"the members you cluster):\n{self._json(temp_id_ctx)}\n\n"
                    f"PER-PERSPECTIVE EXTRACTIONS:\n{self._json(perspective_extractions)}\n\n"
                    "The earlier pass built obligations broadly without merging, "
                    "so duplicates within and across perspectives are expected. "
                    "Fold each cluster whose members one shippable build would "
                    "satisfy into a single consolidated obligation, and leave "
                    "every other item to pass through. When a cluster mixes "
                    "confirmed and inferred members, keep the confirmed member's "
                    "phrasing as the spine. Do not emit out_of_scope items."
                ),
                include_memory=False,
            ),
        )

    @staticmethod
    def _untouched_vision_ids(
        compact_vision: Dict[str, Any],
        post_merge_items: List[Dict[str, Any]],
    ) -> Dict[str, List[str]]:
        """Compute vision IDs that no post-merge item references in trace_refs.

        Pure set difference between the vision's id inventory and the
        union of trace_refs across every post-merge item (consolidated
        forms already carry the union of every member's trace_refs).
        Out_of_scope ids are excluded from the result (Python preserves
        them 1:1 elsewhere). Pass 2B uses this to focus adjudication on
        real gaps rather than re-scanning the full vision.
        """
        by_kind: Dict[str, List[str]] = {
            "assumptions": [],
            "concerns": [],
            "scope": [],
        }
        for key in by_kind.keys():
            for entry in compact_vision.get(key) or []:
                if isinstance(entry, dict) and entry.get("id"):
                    by_kind[key].append(str(entry["id"]))

        touched: set = set()
        for item in post_merge_items:
            if not isinstance(item, dict):
                continue
            for ref in item.get("trace_refs") or []:
                touched.add(str(ref).strip())

        untouched: Dict[str, List[str]] = {}
        for kind, ids in by_kind.items():
            missing = [vid for vid in ids if vid not in touched]
            if missing:
                untouched[kind] = missing
        return untouched

    def _adjudicate(
        self,
        compact_vision: Dict[str, Any],
        post_merge_items: List[Dict[str, Any]],
        all_gaps: List[str],
        all_conflicts: List[Dict[str, Any]],
        cluster_summary: List[Dict[str, Any]],
        feedback_block: str,
    ) -> VisionAndAdjudication:
        """Pass 2B — vision constraint walk + gap/conflict adjudication.

        Runs AFTER Pass 2A so it sees the post-merge item set (each item
        carrying a T-NNN for a pass-through or M-NNN for a consolidated
        form). This prevents Pass 2B from emitting conflicts on items
        Pass 2A already merged, or vision_constraint_items duplicating
        a consolidated capability.
        """
        untouched = self._untouched_vision_ids(compact_vision, post_merge_items)
        return self._with_rate_limit_retry(
            label="adjudicate",
            fn=lambda: self.extract_structured(
                schema=VisionAndAdjudication,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + _PASS_ADJUDICATE
                    + feedback_block
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(compact_vision)}\n\n"
                    f"UNTOUCHED VISION IDS (no post-merge item references "
                    f"these in trace_refs — focus your vision constraint walk "
                    f"here):\n{self._json(untouched)}\n\n"
                    f"CLUSTER SUMMARY (Pass 2A merge decisions; consolidated "
                    f"items now carry M-NNN ids and union the trace_refs of "
                    f"every member — do NOT emit vision_constraint_items or "
                    f"conflicts that duplicate a consolidated "
                    f"capability):\n{self._json(cluster_summary)}\n\n"
                    f"POST-MERGE ITEMS (every Pass 1 item, with consolidated "
                    f"forms replacing merged members; ids are T-NNN for pass-"
                    f"through items, M-NNN for consolidated):"
                    f"\n{self._json(post_merge_items)}\n\n"
                    f"ALL GAPS COLLECTED ACROSS PERSPECTIVES (deduplicate and "
                    f"drop any whose missing decision is already settled at AC "
                    f"precision by a post-merge item):\n{self._json(all_gaps)}\n\n"
                    f"ALL CONFLICTS COLLECTED ACROSS PERSPECTIVES (filter to "
                    f"true clashes that remain after merge; condition-difference "
                    f"absorbed into AC is not a conflict):"
                    f"\n{self._json(all_conflicts)}\n\n"
                    "Return VisionAndAdjudication: vision_constraint_items "
                    "(vision-derived only, never echoing a current item), "
                    "final_gaps, final_conflicts (true clashes only, referencing "
                    "the post-merge ids T-NNN / M-NNN), and notes. Do not emit "
                    "out_of_scope items or decide merges."
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
        # Pass 1 + Pass 2A get the standard re-run block. Pass 2B adjudicates
        # conflicts, so it gets an extra clause forcing feedback-prescribed
        # resolution direction over its own balance.
        feedback_block = _build_feedback_block(feedback)
        feedback_block_2b = _build_feedback_block(feedback, include_conflict_clause=True)

        compact_vision = self._compact_vision(raw_vision)

        # ── Pass 1: assembly batched by perspective ────────────────────
        # Records sharing one perspective go in one LLM call. The model
        # reads them as one corpus of lived evidence for that role and
        # emits requirements directly on PerspectiveExtraction.items;
        # trace_refs cite turn ids so a single item may draw evidence
        # from one record or several. Cross-perspective consolidation
        # remains Pass 2A's concern.
        slim_records = [self._slim_interview_item(item) for item in items]
        perspective_groups: Dict[str, List[Dict[str, Any]]] = {}
        for slim in slim_records:
            persp = (slim.get("perspective") or "").strip() or "(unknown)"
            perspective_groups.setdefault(persp, []).append(slim)

        perspective_results: List[Tuple[str, PerspectiveExtraction]] = []
        perspective_notes: List[str] = []
        map_failures: List[str] = []

        if perspective_groups:
            # Drive every perspective batch concurrently on an asyncio
            # event loop. Semaphore inside _arun_pass1 caps in-flight
            # calls at self._max_parallel so the provider's rate-limit
            # budget still binds. process() is called from synchronous
            # LangGraph nodes, so asyncio.run is safe here.
            persp_results = asyncio.run(
                self._arun_pass1(perspective_groups, compact_vision, feedback_block)
            )
            for persp, batch_or_exc in persp_results:
                record_count = len(perspective_groups[persp])
                if isinstance(batch_or_exc, BaseException):
                    logger.warning(
                        "[DistillerAgent] Pass 1 batch failed for perspective '%s' "
                        "(%d records): %s",
                        persp, record_count, batch_or_exc,
                    )
                    map_failures.append(
                        f"perspective '{persp}' ({record_count} records): {batch_or_exc}"
                    )
                    continue

                batch = batch_or_exc
                if (batch.reasoning or "").strip():
                    logger.info(
                        "[DistillerAgent] Pass 1 reasoning [%s]:\n%s",
                        persp, batch.reasoning.strip(),
                    )
                if (batch.notes or "").strip():
                    perspective_notes.append(
                        f"[{persp}] {batch.notes.strip()}"
                    )
                perspective_results.append((persp, batch))

        # Assign T-NNN temp ids in Pass 1 order — this mutates each
        # Requirement.id so the value carries through the model_dump
        # below, letting Pass 2A reference items by id and letting
        # Python apply merge groups deterministically.
        pass1_items_in_order = self._assign_temp_ids(perspective_results)
        pass1_item_count = len(pass1_items_in_order)

        # Bundle per-perspective extractions for Pass 2A + Pass 2B
        # (same input for both passes — they consume it for different
        # concerns). Each entry carries perspective, the assembled
        # items (with T-NNN ids), gaps, and conflicts.
        perspective_extractions: List[Dict[str, Any]] = []
        for persp, batch in perspective_results:
            perspective_extractions.append({
                "perspective": persp,
                "record_ids": [
                    str(r.get("id") or "")
                    for r in perspective_groups.get(persp, [])
                ],
                "notes": batch.notes,
                "items": [item.model_dump() for item in (batch.items or [])],
                "gaps": list(batch.gaps or []),
                "conflicts": [c.model_dump() for c in (batch.conflicts or [])],
            })

        # ── Pass 2A (cluster) — SEQUENTIAL, runs first ─────────────────
        # Pass 2B needs to see the post-merge item set, otherwise it
        # adjudicates conflicts and walks vision constraints against
        # raw Pass 1 items that Pass 2A is about to consolidate, which
        # produces dangling conflict refs and duplicate vision items.
        cluster_result: Optional[MergeDecisions] = None
        adjudicate_result: Optional[VisionAndAdjudication] = None
        pass2_failures: List[str] = []
        try:
            cluster_result = self._cluster(
                compact_vision, perspective_extractions, feedback_block
            )
            if cluster_result and (cluster_result.reasoning or "").strip():
                logger.info(
                    "[DistillerAgent] Pass 2A reasoning:\n%s",
                    cluster_result.reasoning.strip(),
                )
        except Exception as exc:
            logger.error(
                "[DistillerAgent] Pass 2A (cluster) failed: %s", exc, exc_info=True,
            )
            pass2_failures.append(f"Pass 2A (cluster): {exc}")

        # ── Apply merge groups deterministically (Python data movement) ─
        # Pass-through items not in any group are preserved in Pass 1
        # order. Consolidated forms replace their first member's slot.
        # Member trace_refs are unioned into the consolidated form so no
        # Pass 1 evidence is lost regardless of what the LLM emitted.
        # When Pass 2A failed, treat as no-merge and continue.
        merge_groups = (cluster_result.merge_groups if cluster_result else []) or []
        merged_items, unknown_temp_ids, applied_groups = self._apply_merge_groups(
            pass1_items_in_order, merge_groups,
        )
        if unknown_temp_ids:
            logger.info(
                "[DistillerAgent] Pass 2A referenced %d unknown temp id(s): %s",
                len(unknown_temp_ids), ", ".join(unknown_temp_ids[:8]),
            )

        # Assign post-merge ids (M-NNN for consolidated, T-NNN preserved
        # for pass-through) so Pass 2B can reference both kinds cleanly.
        self._assign_post_merge_ids(merged_items)

        # ── Build post-merge view for Pass 2B ──────────────────────────
        post_merge_items_view = [item.model_dump() for item in merged_items]
        all_gaps: List[str] = []
        all_conflicts: List[Dict[str, Any]] = []
        for entry in perspective_extractions:
            all_gaps.extend(entry.get("gaps") or [])
            all_conflicts.extend(entry.get("conflicts") or [])
        cluster_summary = [
            {
                "consolidated_id": item.id,
                "member_temp_ids": list(group.member_temp_ids or []),
                "statement": item.statement,
            }
            for item, group in zip(
                (
                    it for it in merged_items if (it.id or "").startswith("M-")
                ),
                merge_groups,
            )
        ]

        # ── Pass 2B (adjudicate) — SEQUENTIAL, sees post-merge view ────
        try:
            adjudicate_result = self._adjudicate(
                compact_vision,
                post_merge_items_view,
                all_gaps,
                all_conflicts,
                cluster_summary,
                feedback_block_2b,
            )
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

        # ── Per-requirement summary log ───────────────────────────────────────
        for item in final_items:
            icon = "✓" if item.confidence == "confirmed" else "~"
            logger.info(
                "[DistillerAgent]   %s [%s] (%s) %s",
                icon, item.id, item.type,
                (item.statement or "")[:100],
            )

        # ── Assemble reviewer notes ──────────────────────────────────
        perspective_notes_block = (
            "\n".join(f"  {line}" for line in perspective_notes)
            if perspective_notes else "  (no perspective notes)"
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
                "PASS 1 — PER-PERSPECTIVE ASSEMBLY\n"
                f"{perspective_notes_block}\n\n"
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
