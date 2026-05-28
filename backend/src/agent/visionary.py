"""
visionary.py - VisionaryAgent

VisionaryAgent reads a project intent and produces a lean Product Vision.
Downstream agents (Agenda, Interviewer, EndUser, Distiller) consume the
roles, assumptions, concerns, and scope.

Execution: three sequential extract_structured passes governed by
``vision_mode`` in WorkflowState.

- Pass 1 — STATED + IMPLIED READ (always runs): input → description,
  intent_summary, target_outcome, known_signals, roles, notes. Roles
  emitted here are tagged ``lens=stated`` or ``lens=implied``. Generic
  product knowledge that names roles the input is silent on is
  reserved for Pass 3. The minimum-stakeholder guarantee — a primary
  user reached from the actor + action + object the input names when
  the intent is silent on the user label — fires in every vision
  mode and is tagged ``lens=implied`` (read from the input, not
  supplied by generic knowledge).

- Pass 2 — STATED + IMPLIED FORKS (always runs): given Pass 1 output,
  produce assumptions (design forks), concerns (quality dimensions),
  scope (boundaries). All items tagged ``lens=stated`` or
  ``lens=implied``.

- Pass 3 — INFERRED EXPANSION (only when ``vision_mode == "coverage"``):
  given Pass 1 + Pass 2 output, expand roles / assumptions /
  concerns / scope with items tagged ``lens=inferred`` — what generic
  product knowledge says a product of this shape typically owes.
  Allowed to chain its inferences on the Pass 1 + 2 output.

Python responsibilities:
- assigns IDs deterministically (ROLE-NN, ASM-NN, CONCERN-NN, OOS-NN)
  exactly once, AFTER Pass 3 (when it runs), so emission order
  reflects the assembled artifact;
- concatenates Pass 1 / Pass 2 / Pass 3 outputs into the final
  ProductVision and merges per-pass notes into one reviewer audit;
- filters cross-pass lens leakage (Pass 1/2 items tagged inferred
  are dropped; Pass 3 items tagged stated/implied are dropped) so
  the contract holds without requiring perfect LLM discipline.

Schema descriptions say *what* a field holds. Prompt bodies teach
*how* to reason — domain-neutral.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import BaseModel, Field

from .base import BaseAgent

logger = logging.getLogger(__name__)


SourceLens = Literal["stated", "implied", "inferred"]


# ─────────────────────────────────────────────────────────────────────────────
# Lean Product Vision schema (unchanged — downstream consumers read these)
# ─────────────────────────────────────────────────────────────────────────────

class Role(BaseModel):
    id: str = Field(default="", description="Leave empty; Python assigns ROLE-NN in emission order.")
    name: str = Field(description="Singular noun the role uses for itself, no market/geography/vertical qualifiers.")
    need: str = Field(description="One sentence on what this role expects at runtime — what they do, notice, or are shaped by.")
    lens: SourceLens = Field(description="How this role was reached. stated: input directly names the label. implied: input names a runtime activity that requires this role without naming the label, OR the actor+action+object forces the role. inferred: input is silent on both and generic product knowledge supplies the role (Pass 3 only).")
    anchor: str = Field(description="One sentence justifying the lens. For stated/implied: cite the input phrase or claim. For inferred: name the specific generic principle (product-pattern, product-shape inference, typical role-decomposition).")


class Assumption(BaseModel):
    id: str = Field(default="", description="Leave empty; Python assigns ASM-NN in emission order.")
    statement: str = Field(description="One uncertainty about a design decision the first release cannot avoid making. State it as a FORK — preferring option A over alternative B, naming a sub-group's distinct need, or stating which side of a boundary the product takes.")
    axis: str = Field(description="One short noun phrase naming the design dimension this fork moves along — the kind of question the fork answers, not the topic it concerns. Drawn from the input's own vocabulary; agent-named, not from any external catalog.")
    why_it_matters: str = Field(description="One sentence on the downstream decision this fork could move: a requirement, quality boundary, scope edge, conflict, or first-release choice.")
    lens: SourceLens = Field(description="stated / implied (Pass 2) or inferred (Pass 3) — same source-trail meaning as for roles.")
    anchor: str = Field(description="One sentence justifying the lens. For stated/implied: cite the input phrase or named claim. For inferred: name the specific generic principle that surfaces the fork.")


class Concern(BaseModel):
    id: str = Field(default="", description="Leave empty; Python assigns CONCERN-NN in emission order.")
    theme: str = Field(description="One keyword for a user-perceptible quality: clarity, timeliness, recoverability, accessibility, effort, consistency, confidence, trust.")
    affected_roles: List[str] = Field(default_factory=list, description="Canonical role names from this vision that would notice when this quality slips.")
    rationale: str = Field(description="One sentence on why this quality is worth raising as an elicitation topic.")
    lens: SourceLens = Field(description="stated / implied (Pass 2) or inferred (Pass 3) — same source-trail meaning as for assumptions.")
    anchor: str = Field(description="One sentence justifying the lens.")


class Boundary(BaseModel):
    id: str = Field(default="", description="Leave empty; Python assigns OOS-NN in emission order.")
    item: str = Field(description="One product responsibility the project intent excludes or wants kept outside the first release.")
    reason: str = Field(description="One sentence on why the boundary should stay visible to downstream agents.")
    lens: SourceLens = Field(description="stated / implied (Pass 2) or inferred (Pass 3) — same source-trail meaning as for assumptions.")
    anchor: str = Field(description="One sentence justifying the lens.")


class ProductVision(BaseModel):
    description: str = Field(description="Reader-facing overview of the requested product in two or three sentences.")
    intent_summary: str = Field(description="One sentence on what the project intent is asking for.")
    target_outcome: str = Field(description="One sentence on the outcome the product should help create for its users or affected roles.")
    notes: str = Field(description="Reviewer-facing audit paragraph combining per-pass notes plus the generation mode used.")
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
    notes: str = Field(description="Reviewer-facing reading observations — what was read directly vs what reading leaned on, any sparsity/density notes, any candidate deferred to Pass 3 with the structural reason.")
    known_signals: List[str] = Field(default_factory=list)
    roles: List[Role] = Field(default_factory=list, description="Roles tagged lens=stated or lens=implied only. lens=inferred items must not appear in this pass — Pass 3 handles those.")


class ForksPass(BaseModel):
    notes: str = Field(description="Reviewer-facing forks commentary — which forks the input surfaced directly, which were implied by the input's own claims, and what was left aside as out-of-pass (inferred items belong in Pass 3).")
    assumptions: List[Assumption] = Field(default_factory=list, description="Assumptions tagged lens=stated or lens=implied only.")
    concerns: List[Concern] = Field(default_factory=list, description="Concerns tagged lens=stated or lens=implied only.")
    scope: List[Boundary] = Field(default_factory=list, description="Boundaries tagged lens=stated or lens=implied only.")


class InferredPass(BaseModel):
    notes: str = Field(description="Reviewer-facing commentary on which generic patterns earned a place, which were considered and declined (and why), and any inferred-vs-implied judgment call.")
    roles: List[Role] = Field(default_factory=list, description="NEW roles tagged lens=inferred only. Do not re-emit Pass 1 roles.")
    assumptions: List[Assumption] = Field(default_factory=list, description="NEW assumptions tagged lens=inferred only. Do not re-emit Pass 2 assumptions.")
    concerns: List[Concern] = Field(default_factory=list, description="NEW concerns tagged lens=inferred only. Do not re-emit Pass 2 concerns.")
    scope: List[Boundary] = Field(default_factory=list, description="NEW boundaries tagged lens=inferred only. Do not re-emit Pass 2 boundaries.")


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1 prompt — STATED + IMPLIED READ
# ─────────────────────────────────────────────────────────────────────────────

_READ_BODY = """\
PASS 1 OF 3 — READ THE INPUT, BUILD THE ROLE LIST

Read the project intent and emit description, intent_summary,
target_outcome, known_signals, roles, notes. Pass 2 handles the
design forks (assumptions / concerns / scope) on top of what you
produce here. Pass 3 (Coverage mode only) later expands with items
generic product knowledge supplies that the input is silent on.


THE PRODUCT DOES NOT EXIST YET. Every fact you cite about a role's
runtime behavior must come from TODAY's life — what people already
try, notice, fall back on, decide. A wish about what the product
should make true belongs in target_outcome / description /
intent_summary, not in known_signals. A signal is a concrete fact
about the world or work as it stands; combine paraphrases of the
same fact; one-line inputs may legitimately produce a short or
empty known_signals list — that is honest.


STATED VS IMPLIED — THIS PASS ONLY. A role is **stated** when the
input itself names the label. A role is **implied** when the input
does not name the label but names a runtime activity that cannot
happen without someone in that role, or names an actor + action +
object that forces the role to exist. A role that only generic
product knowledge supplies — the input neither names nor forces it
— is **inferred** and belongs in Pass 3; hold it. Each emitted role
carries `lens` (stated or implied here) and a specific `anchor`:
stated anchors cite the input phrase; implied anchors cite the
activity, claim, or actor+action+object that forces the role.
Vague glue ("industry practice", "common pattern", "products like
this usually have <X>") is not an anchor — its presence means the
candidate belongs in Pass 3, not this one.


WHAT COUNTS AS A ROLE. Someone whose runtime behavior changes
because the product is in front of them — they use it, watch it,
are touched by what it does or shows. Anyone whose stake is purely
upstream of runtime (sponsors, funders, governance bodies, people
who motivated the work but never touch the product when it runs)
is not a role; mention them in `notes` or as motivation in
target_outcome. The minimum-stakeholder guarantee fires in every
vision mode: if the input is a one-line intent that never labels
the primary user, that user is still reachable from the actor +
action + object the intent itself names — emit them with
lens=implied, anchor citing that actor+action+object phrasing.
This is reading what the input forces, not what generic knowledge
supplies.


KEEP DISTINCT BY DEFAULT. When the input names two labels
separately, treat them as sacred until proven otherwise. Two
labels collapse into one role only when their runtime stake
genuinely coincides — the same activity at the product's moment
of use AND the same friction or concern they bring to it. If
activity matches but pain differs, or pain matches but activity
differs, keep them as distinct roles. The same topic word in the
input does not force a merge; people in different positions
around one topic (someone upstream of a moment, someone during it,
someone reviewing afterward, someone advising, someone setting
the rule the others work within) carry runtime evidence the
others cannot substitute. When the input names a label AND uses
an umbrella term that could plausibly cover it, the directly
named label is the stake the input cares about — the umbrella
term goes into notes, not into the role list. Record any merge
you approve in `notes` so the reviewer can verify which labels
collapsed and why activity + pain both matched.


IN-GROUP EXPANSION. If the input flags a sub-population whose
experience differs from the generic role — explicitly or by
surrounding language ("X who have been through Y", "we don't
want to flatten everyone into one audience") — emit the in-group
as its own role distinct from the generic. Walk every flagged
in-group; do not pick one and skip the rest.


WRITING ROLES. `name`: singular noun the actor would use for
themselves, stripped of market / geography / vertical /
demographic qualifiers unless needed to disambiguate against
another role. `need`: one sentence on what they expect at the
product's runtime — what they do, notice, or are shaped by. Not
duties, not policies. `lens`: stated or implied only this pass.
`anchor`: specific sentence as described above. `id`: leave
empty; Python assigns ROLE-NN.


WRITING notes. One reviewer-facing paragraph: what the input
named directly vs what reading leaned on; any synonym merges you
approved (which labels collapsed, under what chosen name, and
why activity + pain both matched); any labels you considered
merging and kept distinct because activity or pain differed; any
in-group splits and the input phrase that flags the distinct
stake; candidates filtered as upstream-only stakeholders; anything
notable about the input's sparsity or density; and any candidate
your reading surfaced whose stake the input neither states nor
forces — flag it as a Pass 3 candidate with the specific
structural reason that surfaces it, so Coverage mode can pick it
up cleanly.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2 prompt — STATED + IMPLIED FORKS
# ─────────────────────────────────────────────────────────────────────────────

_FORKS_BODY = """\
PASS 2 OF 3 — DESIGN FORKS THE INPUT SURFACES

Pass 1 has read the input and built the role list. Take that as
ground truth. Your job is to produce assumptions (design forks),
concerns (quality dimensions), and scope (boundaries) — plus a
notes commentary — strictly from what the input states or what
its claims force. Generic product knowledge that the input
neither names nor forces is reserved for Pass 3 (Coverage mode).


PASS 1 OUTPUT (ground truth — consume, do not modify)
{reading}


THE PRODUCT DOES NOT EXIST YET. Forks are decisions the first
release must make before shipping. They are not hypotheses about
how users will react to the finished product — dialogue cannot
settle those. Each assumption / concern / boundary carries `lens`
(stated or implied here) and a specific `anchor`. Inferred items
— those generic product knowledge supplies — belong in Pass 3;
do not mix them in here.


ASSUMPTIONS ARE THE STRATEGIC-DECISION MENU. Each assumption is
a real fork the team must answer before the first release: the
reviewer reads them in HITL and chooses a direction. They are
NOT a 1:1 driver for interview questions — the agenda picks
lived moments that surface evidence on multiple forks at once.
Optimize each assumption for "is this a strategic decision worth
the reviewer's attention", not for "will this become one
interview prompt".


FORK VS EFFECTIVENESS CLAIM VS SCOPE VS SETTLED SUBSTANCE.

A fork has a LOSING alternative you can name in one phrase —
option A over alternative B, one sub-group's distinct need vs
another's, one side of a boundary the product takes. Use whatever
phrasing reads naturally as long as the losing alternative is
visible.

An effectiveness claim ("users will use it", "the product will
reduce X", "X is more engaging than Y") names no losing
alternative dialogue could settle — drop or rewrite as a fork the
team can decide before shipping. A statement of what the software
will NOT do is a scope boundary, emit as scope. A settled
positive substance the input has already decided (a stated form
factor, a stated audience focus, with no losing alternative
dialogue could surface) is not a fork either — fold into
description / intent_summary; do not fabricate an ASM for it.

Two lenses for how a fork surfaced in this pass: STATED — input
names the uncertainty directly; anchor cites the input line.
IMPLIED — input does not name the uncertainty, but its own
claims would not hold together without a decision here; anchor
cites the input claim that forces the decision. Anti-bundle: one
assumption holds one fork. Connectives ("and", "or") that join
two distinct forks → split. `id`: leave empty (Python assigns
ASM-NN).


DIRECTION-LEVEL FORKS. A single project intent can be satisfied
by several distinct overall directions — different kinds of
product that all meet target_outcome but land at fundamentally
different first-release builds. When the input itself surfaces
direction-level uncertainty (it mentions multiple possible
audiences, multiple possible authorities, multiple distinct
outcomes pulling in different first-release shapes, multiple
sponsoring bodies, etc.), emit the direction-level fork as an
assumption. Do not silently lock to one direction the input is
ambivalent about. Direction-level uncertainty the input is
silent on belongs in Pass 3, not here.


AXIS DISCIPLINE — MANY INDEPENDENT AXES, AGENT-NAMED. The `axis`
field names the design DIMENSION the fork moves along — the kind
of question the fork is answering, not the topic it concerns.
Name each axis yourself in a short noun phrase drawn from the
input's own vocabulary; do not import names from an external
catalog. The set of assumptions you emit should span many
INDEPENDENT axes: each fork opens a distinct design question
whose answer would move a distinct downstream decision. The set
is rich when it offers the reviewer a wide menu of strategic
choices, not when it offers many sibling phrasings of one choice.

After drafting, read each pair: two forks may share a topic word
but sit on different axes when they answer different design
questions about that topic; two forks may name different topics
but share an axis when they answer the same design question from
different angles. The axis label captures the *kind* of decision
that moves, not the topic the decision concerns. When two forks
share an axis name AND answer the same underlying design
question, collapse them into one fork framed at the root — sub-
answers belong as interview evidence, not separate assumptions.
When two forks share a topic word but answer different design
questions, sharpen the axis names so the distinction is visible
on the artifact and keep both. Let the count of axes — and
therefore the count of assumptions — emerge from how many
independent design questions the input genuinely surfaces; do
not target a number.


STAKE PLACEMENT — EVERY NAMED STAKE HAS A HOME. Every
stakeholder the input names (by label, by activity, by stated
relationship to the product) must land somewhere visible: either
as an assumption the dialogue can move (a fork over how, or
whether, to accommodate the stake), or as a structural note in
`notes` explaining why no first-release decision flexes around
that stake (governance, sponsorship, observation, authority
source the product speaks under). Both are correct outcomes —
choose by whether a design fork genuinely exists. When the input
gestures at a stake as something the product might or might not
accommodate, a fork usually fits; when the input gestures at a
party the product operates next to but does not change behavior
for, a structural note usually fits. A stake that has neither
home is missing from the artifact.


CONCERNS — USER-PERCEPTIBLE QUALITY. A concern names a quality
the role NOTICES at the product's runtime when it slips —
clarity, timeliness, recoverability, accessibility, effort,
consistency, confidence, trust, and so on (the list is open;
use the friction vocabulary the input itself raises). The test:
when this quality slips at runtime, what does the role notice
specifically? If the answer is a runtime perception the role
can describe, it is a concern. If the answer is a design
relationship between roles or a design decision the team makes,
the candidate is an assumption or a scope item, not a concern.
Merge before emit: same theme touching multiple roles → one
concern with the union of `affected_roles`. Do not invent
numeric thresholds, technologies, vendors, standards, or
policies — concerns are elicitation topics, not measurable
targets. Lens + anchor follow the same rules as for assumptions
— stated / implied only in this pass; inferred concerns belong
in Pass 3. `id`: leave empty (Python assigns CONCERN-NN).


SCOPE — RESPONSIBILITIES THE SOFTWARE WILL NOT TAKE ON. A scope
item (OOS) describes a responsibility the product will not (or
cannot) handle within its first release — what is left to other
tools, other authorities, other processes, or to the user
themselves. Walk the input for phrases that describe what the
software is NOT meant to do or responsibilities the product
should leave to something else (a non-exhaustive trigger pattern:
"not replace", "alongside", "without doing", "outside the first
release", "we'd leave X to Y", "not aim to", "is not the venue
for", "out of scope"). For each candidate ask what it is doing:
a system-scope LIMIT (the software won't handle, leaves to
others, doesn't take responsibility for) → scope; an open
design FORK whose evidence dialogue could move → assumption; a
settled positive substance the input already decided (with no
losing alternative dialogue could surface) → fold into
description / intent_summary, do not fabricate an ASM for it.
Inferred boundaries (a generic principle says the product should
leave a responsibility to another authority, even if the input
did not state it) belong in Pass 3. Empty list is correct only
when the input has no boundary phrase the active scan would
catch; skipping a clearly stated system-scope boundary is a
defect. `id`: leave empty (Python assigns OOS-NN).


WRITING notes. One reviewer-facing paragraph: stated-vs-implied
distribution and the reasoning behind it; direction-level forks
you considered and how each was routed (assumption / dropped
because it collapses to another / deferred to Pass 3 because the
input is silent), with why; boundary trigger phrases you acted
on or declined, with reasoning; any fork / concern / boundary
you considered emitting as inferred-from-generic-knowledge and
deferred to Pass 3, with the specific structural principle that
would surface it there.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pass 3 prompt — INFERRED EXPANSION FROM GENERIC PRODUCT KNOWLEDGE
# ─────────────────────────────────────────────────────────────────────────────

_INFERRED_BODY = """\
PASS 3 OF 3 — INFERRED EXPANSION FROM STRUCTURAL READING

This pass runs only when the session is in Coverage mode. Pass 1
and Pass 2 have produced the input-anchored ground truth: roles,
assumptions, concerns, scope — all tagged stated or implied. Your
job: expand the ground truth with items the input neither names
nor forces, but that the product's structural shape (read out of
Pass 1 + Pass 2) typically owes. Every item you emit here is
tagged `lens=inferred`.


PASS 1 OUTPUT (ground truth)
{reading}

PASS 2 OUTPUT (ground truth)
{forks}


THE PRODUCT DOES NOT EXIST YET. Inferred items still describe
the first release's owed decisions / parties / qualities /
boundaries — they are not predictions about how users will react
to a finished product. Every fork still names a losing
alternative; every concern still names a runtime perception
that slips; every boundary still names a responsibility limit.


ANCHOR DISCIPLINE — INFERRED MUST BE SPECIFIC. Each inferred
item's anchor names the SPECIFIC structural reason this product
shape needs it. A specific structural reason — "the product
sits alongside an authoritative source it does not own, so
someone must own the alignment workflow when the source changes"
— earns the item its place. Vague glue — "industry practice",
"common pattern", "products like this usually have <X>", "best
practices" — is not an anchor; if you cannot state the
structural reason in one sentence tied to what Pass 1 + Pass 2
actually built, the item is not honestly inferred and you drop
it. The vague-glue test is the quality guard for this pass.


DO NOT RE-EMIT PASS 1 / PASS 2 ITEMS. Read their output as
ground truth; surface only NEW items. Do not contradict them
either — generic structural reasoning supplements input, it does
not override it. Where the input contradicts a generic pattern,
the input wins; skip that pattern.


HOW TO READ THE STRUCTURAL SHAPE. Hold the product Pass 1 +
Pass 2 described in your head: what kind of thing it is, who
acts on it, what flows through it, what it sits next to, what
changes around it over time, how it could go wrong, how it
stays current, how it recovers when something breaks, how it
hands off to other parties, how it knows who it is talking to.
Each of those is a question your reading can answer specifically
for this product. A NEW ROLE earns its place when the
structural shape genuinely places a party at runtime that
Pass 1's role list does not cover. A NEW FORK earns its place
when the shape genuinely makes the team face a design decision
Pass 1 + Pass 2 did not raise. A NEW CONCERN earns its place
when the shape genuinely puts a role in a runtime moment where
a quality could slip in a way the role would notice. A NEW
BOUNDARY earns its place when the shape genuinely places a
responsibility with another authority or party the product
should not take on.

The work is structural reasoning grounded in *this* input's
shape, not template matching against a fixed list of party
types or fork types. Two products with very different topics
may face different decisions because their shapes are different;
two products with the same topic may face different decisions
for the same reason. Walk the shape until your candidate set
stabilises before trimming; under-emission leaves the downstream
agenda without perspectives, forks, qualities, or boundaries
the team will encounter regardless. The default leans toward
EMITTING when a specific structural reason is namable; the
vague-glue test is the trim. Anti-bundle still applies — one
assumption holds one fork; split connectives that hide two
decisions.


AXIS DISCIPLINE ACROSS PASS 2 + PASS 3. The same axis
discipline from Pass 2 holds across the combined set. Pass 2
filled `axis` on every stated/implied assumption; read those as
the design dimensions already claimed. Before emitting an
inferred assumption, read its candidate axis against every
existing assumption (Pass 2 and earlier in Pass 3): if it shares
an axis name AND answers the same underlying design question,
do not emit — the existing fork's evidence will already settle
it. If it shares a topic word but opens a different design
question (a sub-population's accommodation pattern the existing
fork did not commit to, for example), emit it with an axis name
that surfaces the distinct question. A near-orthogonal fork the
team will later face anyway is worth emitting; a sibling
phrasing of an existing fork is not.


CONCERNS AND BOUNDARIES — same dichotomies as Pass 2. A concern
is what the role notices at runtime when a quality slips; merge
same theme across multiple roles into one concern with the union
of `affected_roles`. A boundary names a responsibility the
product will not own, surfaced when the shape places that
responsibility with another authority, system, or party. Each
inferred concern / boundary carries the specific structural
reason in its anchor; vague glue drops it.


CHAINING IS ALLOWED. An inferred item may build on Pass 1 +
Pass 2 + earlier Pass 3 items — an inferred role's runtime
activity may motivate an inferred concern, an inferred boundary
may motivate an inferred fork about how the product surfaces
what it does not own. Anchor the chain by naming the specific
structural reason the upstream item produces the downstream one.

`id`: leave empty. Python continues numbering after Pass 1 / 2.


WRITING notes. One reviewer-facing paragraph: the structural
reading you formed from Pass 1 + Pass 2 in the input's own
vocabulary; which inferred forks / roles / concerns / boundaries
the reading earned a place for, with the specific structural
reason behind each; candidates you considered and declined and
why (input contradicts them, Pass 2 already covers them, the
axis already exists, the anchor would have had to be vague);
any inferred-vs-implied judgment call (an item you could
plausibly have tagged implied in Pass 2 but chose to tag
inferred here, or vice versa); any chaining, with the principle
that justifies it.
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

    @staticmethod
    def _resolve_mode(state: Dict[str, Any]) -> str:
        raw = (state.get("vision_mode") or "fidelity").strip().lower()
        if raw not in ("fidelity", "coverage"):
            logger.warning(
                "[VisionaryAgent] Unknown vision_mode=%r; falling back to 'fidelity'.",
                raw,
            )
            return "fidelity"
        return raw

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

    def _pass3(
        self,
        signal: str,
        reading: ReadingPass,
        forks: ForksPass,
        feedback: Optional[str],
    ) -> InferredPass:
        body = _INFERRED_BODY.format(
            reading=json.dumps(reading.model_dump(), indent=2, ensure_ascii=False),
            forks=json.dumps(forks.model_dump(), indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
            schema=InferredPass,
            system_prompt=self._system(body),
            user_prompt=self._user_prompt(signal, feedback),
            include_memory=False,
        )

    # ── Lens contract enforcement ───────────────────────────────────────────

    @staticmethod
    def _filter_lens_items(
        items: List[Any],
        allowed: Set[str],
        pass_label: str,
        kind: str,
    ) -> List[Any]:
        """Drop items whose lens is outside the allowed set; log warning per drop."""
        kept: List[Any] = []
        for item in items or []:
            lens = getattr(item, "lens", None)
            if lens not in allowed:
                label = (
                    getattr(item, "name", None)
                    or getattr(item, "statement", None)
                    or getattr(item, "theme", None)
                    or getattr(item, "item", None)
                    or "?"
                )
                logger.warning(
                    "[VisionaryAgent] %s emitted %s lens=%r outside allowed {%s} "
                    "— dropping: %s",
                    pass_label, kind, lens, "/".join(sorted(allowed)), label,
                )
                continue
            kept.append(item)
        return kept

    def _enforce_lens_pass1(self, reading: ReadingPass) -> None:
        reading.roles = self._filter_lens_items(
            reading.roles, {"stated", "implied"}, "Pass 1", "role"
        )

    def _enforce_lens_pass2(self, forks: ForksPass) -> None:
        forks.assumptions = self._filter_lens_items(
            forks.assumptions, {"stated", "implied"}, "Pass 2", "assumption"
        )
        forks.concerns = self._filter_lens_items(
            forks.concerns, {"stated", "implied"}, "Pass 2", "concern"
        )
        forks.scope = self._filter_lens_items(
            forks.scope, {"stated", "implied"}, "Pass 2", "boundary"
        )

    def _enforce_lens_pass3(self, inferred: InferredPass) -> None:
        inferred.roles = self._filter_lens_items(
            inferred.roles, {"inferred"}, "Pass 3", "role"
        )
        inferred.assumptions = self._filter_lens_items(
            inferred.assumptions, {"inferred"}, "Pass 3", "assumption"
        )
        inferred.concerns = self._filter_lens_items(
            inferred.concerns, {"inferred"}, "Pass 3", "concern"
        )
        inferred.scope = self._filter_lens_items(
            inferred.scope, {"inferred"}, "Pass 3", "boundary"
        )

    # ── Assembly ────────────────────────────────────────────────────────────

    @staticmethod
    def _assemble(
        reading: ReadingPass,
        forks: ForksPass,
        inferred: Optional[InferredPass],
        mode: str,
    ) -> ProductVision:
        roles = list(reading.roles or [])
        assumptions = list(forks.assumptions or [])
        concerns = list(forks.concerns or [])
        scope = list(forks.scope or [])

        if inferred is not None:
            roles.extend(inferred.roles or [])
            assumptions.extend(inferred.assumptions or [])
            concerns.extend(inferred.concerns or [])
            scope.extend(inferred.scope or [])

        notes_parts = [
            "PASS 1 — READING",
            (reading.notes or "").strip(),
            "",
            "PASS 2 — FORKS",
            (forks.notes or "").strip(),
        ]
        if inferred is not None:
            notes_parts.extend([
                "",
                "PASS 3 — INFERRED EXPANSION",
                (inferred.notes or "").strip(),
            ])
        notes_parts.extend(["", f"Generation mode: {mode}"])

        return ProductVision(
            description=(reading.description or "").strip(),
            intent_summary=(reading.intent_summary or "").strip(),
            target_outcome=(reading.target_outcome or "").strip(),
            notes="\n".join(notes_parts),
            known_signals=list(reading.known_signals or []),
            roles=roles,
            assumptions=assumptions,
            concerns=concerns,
            scope=scope,
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

    # ── Entry point ────────────────────────────────────────────────────────

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        signal = (state.get("project_description") or "").strip()
        if not signal:
            logger.warning("[VisionaryAgent] project_description is missing.")
            return {}

        feedback = (state.get("product_vision_feedback") or "").strip() or None
        mode = self._resolve_mode(state)

        logger.info(
            "[VisionaryAgent] Building Product Vision — mode=%s, 3 passes (Pass 3 %s).",
            mode,
            "active" if mode == "coverage" else "skipped",
        )

        try:
            reading = self._pass1(signal, feedback)
            self._enforce_lens_pass1(reading)

            forks = self._pass2(signal, reading, feedback)
            self._enforce_lens_pass2(forks)

            inferred: Optional[InferredPass] = None
            if mode == "coverage":
                inferred = self._pass3(signal, reading, forks, feedback)
                self._enforce_lens_pass3(inferred)

            vision = self._assemble(reading, forks, inferred, mode)
            self._assign_ids(vision)
        except Exception as exc:
            logger.error("[VisionaryAgent] Pipeline failed: %s", exc, exc_info=True)
            return {}

        vision_dict = vision.model_dump()
        artifacts = dict(state.get("artifacts") or {})
        artifacts["product_vision"] = {
            **vision_dict,
            "created_at": datetime.now().isoformat(),
            "status": "pending_review",
            "vision_mode": mode,
        }

        updates: Dict[str, Any] = {
            "product_vision": vision_dict,
            "artifacts": artifacts,
        }
        if feedback:
            updates["product_vision_feedback"] = None

        lens_counts: Dict[str, int] = {"stated": 0, "implied": 0, "inferred": 0}
        for assumption in vision.assumptions:
            lens_counts[assumption.lens] = lens_counts.get(assumption.lens, 0) + 1

        logger.info(
            "[VisionaryAgent] Product Vision ready (mode=%s) — %d roles, "
            "%d assumptions (stated=%d, implied=%d, inferred=%d), %d concerns, "
            "%d scope.",
            mode,
            len(vision.roles),
            len(vision.assumptions),
            lens_counts["stated"],
            lens_counts["implied"],
            lens_counts["inferred"],
            len(vision.concerns),
            len(vision.scope),
        )
        return updates
