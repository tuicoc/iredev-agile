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


SourceLens = Literal["stated", "implied", "inferred"]


# ─────────────────────────────────────────────────────────────────────────────
# Lean Product Vision schema
# ─────────────────────────────────────────────────────────────────────────────

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
    id: str = Field(default="", description="Leave empty; Python assigns OOS-NN in emission order.")
    item: str = Field(description="One product responsibility the project intent excludes or wants kept outside the first release.")
    reason: str = Field(description="One sentence on why the boundary should stay visible to downstream agents.")
    lens: SourceLens = Field(description="stated / implied / inferred — same meaning as for assumptions.")
    anchor: str = Field(description="One sentence justifying the lens.")


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
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2 prompt — FORKS, CONCERNS, SCOPE
# ─────────────────────────────────────────────────────────────────────────────

_FORKS_BODY = """\
PASS 2 OF 2 — DESIGN FORKS THE FIRST RELEASE OWES

Pass 1 has already extracted the input reading and the role list
below. You receive that as ground truth. Your job: produce
assumptions (design forks), concerns (quality dimensions), scope
(boundaries) — and a notes commentary.

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
            schema=ForksPass,
            system_prompt=self._system(body),
            user_prompt=self._user_prompt(signal, feedback),
            include_memory=False,
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
