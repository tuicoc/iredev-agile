"""
agenda.py - AgendaAgent

AgendaAgent reads the reviewed Product Vision and produces an elicitation
agenda. Every item owns one evidence job — one perspective answering from
inside one scene to settle one downstream decision.

Execution: two sequential extract_structured passes.
- Pass 1 (DRAFT): vision → items skeleton (vision_refs, perspective,
  context, decision_target, seed_question, merge_anchor, notes). The LLM
  focuses on which vision IDs to attach, which role lives the scene most
  directly, what fork the dialogue should move.
- Pass 2 (COVERAGE): given Pass 1 items (with Python-assigned IT-NNN
  IDs), produce coverage_points and close_when per item. The LLM focuses
  exclusively on writing today's lived facts that pass the TODAY GATE.

Python responsibilities:
- assigns IT-NNN ids deterministically;
- generates the per-id audit table from items + vision (no LLM drift);
- merges Pass 2 coverage entries back into the items by id;
- assembles the final Agenda + AgendaRuntime.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseAgent

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Final Agenda schema
# ─────────────────────────────────────────────────────────────────────────────

class AgendaItem(BaseModel):
    id: str = Field(default="", description="Stable id IT-NNN; Python assigns.")
    vision_refs: List[str] = Field(default_factory=list, description="IDs from the reviewed Product Vision (assumptions, concerns, or scope) this item clarifies.")
    perspective: str = Field(description="Canonical role name from vision.roles who can answer from lived use or direct impact.")
    context: str = Field(description="A concrete operating moment in the role's life today.")
    decision_target: str = Field(description="One short phrase naming the downstream design fork the evidence should move.")
    seed_question: str = Field(description="One open invitation into the scene the role already inhabits.")
    coverage_points: List[str] = Field(default_factory=list, description="2-5 stakeholder-livable facts from today's life.")
    close_when: str = Field(description="Short stop condition summarizing when coverage_points are met.")
    merge_anchor: str = Field(default="", description="One concrete sentence — filled only when vision_refs has more than one entry; empty when exactly one.")
    notes: str = Field(default="", description="Optional reviewer-facing note for this item.")


class Agenda(BaseModel):
    notes: str = Field(description="Reviewer-facing audit notes. Python generates the per-id audit table; LLM commentary appends below.")
    items: List[AgendaItem] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Runtime shapes (consumed by InterviewerAgent / EndUserAgent)
# ─────────────────────────────────────────────────────────────────────────────

class AgendaRuntimeItem(BaseModel):
    id: str
    vision_refs: List[str] = Field(default_factory=list)
    perspective: str
    context: str
    decision_target: str = ""
    seed_question: str
    close_when: str
    coverage_points: List[str] = Field(default_factory=list)
    merge_anchor: str = ""
    notes: str = ""

    status: Literal["pending", "answered", "partial", "skipped"] = "pending"
    question: Optional[str] = None
    answer: Optional[str] = None
    talk: List[Dict[str, Any]] = Field(default_factory=list)
    rule: Optional[str] = None
    signals: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    assumption_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    coverage: List[Dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_item(cls, item: AgendaItem) -> "AgendaRuntimeItem":
        return cls(**item.model_dump())


class AgendaRuntime(BaseModel):
    items: List[AgendaRuntimeItem]
    current_index: int = 0
    elicitation_complete: bool = False

    @classmethod
    def from_agenda(cls, agenda: Agenda) -> "AgendaRuntime":
        return cls(items=[AgendaRuntimeItem.from_item(item) for item in agenda.items])

    @classmethod
    def from_agenda_artifact(cls, artifact: Dict[str, Any]) -> "AgendaRuntime":
        items_raw = artifact.get("items") or []
        if not items_raw:
            return cls(items=[])
        first = items_raw[0]
        if "talk" in first:
            return cls(**artifact)
        return cls(
            items=[
                AgendaRuntimeItem(
                    id=raw.get("id", ""),
                    vision_refs=list(raw.get("vision_refs") or []),
                    perspective=raw.get("perspective", ""),
                    context=raw.get("context", ""),
                    decision_target=raw.get("decision_target", ""),
                    seed_question=raw.get("seed_question", ""),
                    close_when=raw.get("close_when", ""),
                    coverage_points=list(raw.get("coverage_points") or []),
                    merge_anchor=raw.get("merge_anchor", ""),
                    notes=raw.get("notes", ""),
                )
                for raw in items_raw
            ]
        )

    def current_item(self) -> Optional[AgendaRuntimeItem]:
        if self.current_index < len(self.items):
            return self.items[self.current_index]
        return None

    def advance(self) -> None:
        self.current_index += 1
        while self.current_index < len(self.items):
            if self.items[self.current_index].status == "pending":
                break
            self.current_index += 1
        if self.current_index >= len(self.items):
            self.elicitation_complete = True


# ─────────────────────────────────────────────────────────────────────────────
# Per-pass shapes
# ─────────────────────────────────────────────────────────────────────────────

class DraftItem(BaseModel):
    vision_refs: List[str] = Field(default_factory=list, description="IDs from the vision this item clarifies.")
    perspective: str = Field(description="Canonical role name from vision.roles.")
    context: str = Field(description="A concrete operating moment in the role's life today.")
    decision_target: str = Field(description="One short phrase naming the first-release design fork the evidence should move.")
    seed_question: str = Field(description="One open invitation into today's scene.")
    merge_anchor: str = Field(default="", description="Filled only when vision_refs has more than one entry.")
    notes: str = Field(default="", description="Optional reviewer-facing note.")


class DraftPass(BaseModel):
    notes: str = Field(default="", description="Reviewer-facing commentary about coverage and merge decisions made during the draft.")
    items: List[DraftItem] = Field(default_factory=list)


class ItemCoverage(BaseModel):
    item_id: str = Field(description="The IT-NNN id assigned to the draft item this coverage entry corresponds to.")
    coverage_points: List[str] = Field(default_factory=list, description="2-5 stakeholder-livable facts from today's life that pass the TODAY GATE.")
    close_when: str = Field(description="Short stop condition summarizing when the coverage_points are met.")


class CoveragePass(BaseModel):
    coverages: List[ItemCoverage] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1 prompt — DRAFT (skeleton items)
# ─────────────────────────────────────────────────────────────────────────────

_DRAFT_BODY = """\
PASS 1 OF 2 — DRAFT THE AGENDA ITEMS (SKELETON)

This pass produces the structural skeleton of each item: which
vision IDs it clarifies, which canonical role answers, what scene
in their life today, what fork the dialogue moves, what seed
question opens the moment, and (when refs > 1) what shared
first-release decision warrants the merge.

This pass does NOT produce `coverage_points` or `close_when`.
Pass 2 will fill those once IDs are assigned.

CORE PRINCIPLES

P1. THE PRODUCT DOES NOT EXIST YET. Scenes must be moments the
role has already lived TODAY. Forks must be first-release
decisions the dialogue could move.

P2. VISION IS GROUND TRUTH. Use only IDs and role names that
appear in the vision below.

P3. ONE EVIDENCE JOB PER ITEM. One role in one concrete scene
answering once would settle one downstream decision.


REVIEWED PRODUCT VISION (ground truth — IDs and role names are
the cross-reference vocabulary)
{vision}


vision_refs — POINTERS INTO THE VISION

The ID(s) this item clarifies. Any mix of assumption / concern /
scope IDs is valid.
- One id may map to one OR several items — depends on how many
  roles have distinct stake (see ITEM MULTIPLICITY).
- Several ids may share one item — fill `merge_anchor` when so.
- Assumptions, concerns, AND scope items earn items:
  * an assumption with an uncertain fork → item;
  * a concern with an unclear acceptable boundary → item;
  * a scope id whose boundary edge could surprise the role at
    runtime → item.
Do not default to assumption-only.


ITEM MULTIPLICITY — ONE VISION ELEMENT, MULTIPLE ITEMS

Default is NOT 1:1 (one vision_ref → one item). Default is:

  Emit one item per ROLE WITH DISTINCT STAKE in the vision element.

A role has distinct stake when answering the element from THAT
role's lived position would produce different evidence (different
moment, different concern, different boundary) than from another
role. Cross-domain patterns:

- A concern with `affected_roles=[<role A>, <role B>, <role C>]`
  spawns up to 3 items (one per role), unless their lived evidence
  fully overlaps in moment / object / outcome. Default: emit per
  role.

- An assumption about an experienced phenomenon usually splits into
  a user-side item AND an observer/intermediary-side item (the
  TWO-ITEM rule applies here).

- A scope boundary (OOS) affects roles working at the boundary
  edge differently — a user perceives the boundary, a doer
  enforces or aligns with it. Emit per side.

When in doubt whether two roles share the same evidence: emit two
items. A reviewer can fold a duplicate later; a reviewer cannot
recover a role whose perspective was never probed.


ROLE COVERAGE GUARANTEE — every stated/implied role MUST appear

vision.roles is the inventory of who matters. EACH role with
lens=stated or lens=implied must appear as `perspective` in ≥1
item. Silent omission is a defect.

If you cannot place a role, explain why in `notes` using this
shape:

  "ROLE-NN <name> not used as perspective because <specific reason
  — e.g. fully represented by ROLE-MM's evidence in IT-NNN sharing
  the same product object, trigger, and outcome>."

Generic acceptable reasons: full evidence overlap with another
emitted item, or the role's stake is captured through a different
role's lived view (rare — usually distinct roles have distinct
stake).

Roles with lens=inferred (from generic product knowledge, not
named in the input) may be skipped without a note.


perspective — MOST CONTEXT-FITTING ROLE

Use only role names that appear in `vision.roles`. Never invent.

When the item's context describes a moment one specific role in
the vision lives more directly than any other, perspective MUST
be that role — even if a broader role nominally fits. Choosing
the broader role when the vision separated out a narrower one
erases the distinction.

Self-test: "Among the roles in vision.roles, which one lives
this exact moment most directly?" Use that role.

USER OVER OBSERVER (a stronger form of the same rule)

When the vision_ref names a USER-PERCEPTIBLE phenomenon — what a
user perceives, understands, finds clear or confusing, trusts or
mistrusts, expects, is surprised by, recovers from — perspective
MUST be the user who experiences the phenomenon, NOT an observer
who watches the user (an intermediary, a coach, an advisor, a
support contact, a teacher watching a learner, a manager hearing
complaints, anyone who reports on the user's experience).

The observer can witness the phenomenon but their evidence is
third-person about the user. Downstream synthesis cannot lift
"the observer reports that the user is confused" into product-
side acceptance criteria without inventing what the product
should display, expose, or preserve. The user can say "today
when I see X, here is what I think" — the observer can only say
"users often think X". First-person evidence translates; third-
person observation does not.

TWO-ITEM RULE (when both user and observer have stakes)

When a vision_ref names BOTH a user-perceptible phenomenon AND
an observer-owned decision related to it, emit TWO items:

  Item U: perspective = the user who experiences the phenomenon;
          decision_target = how the product changes what the user
          sees, understands, or can act on.

  Item O: perspective = the observer / intermediary;
          decision_target = what the observer themselves must do,
          check, escalate, or align with.

The two items have different audiences, different product
objects, and different scenes. Do not collapse them — collapsing
erases the user side, which is the harder side to evidence later.

Default test: read the vision_ref aloud and ask "does a user end
up seeing, doing, deciding, or feeling something different when
this is true?" If yes, the user-side item is required, regardless
of whether an observer-side item is also required. Emitting only
the observer-side item is the failure mode this rule prevents.

If NO canonical role can speak to a vision id from lived use or
direct impact, leave the id unassigned in your items list. Python
will mark it gap-named in the audit.


context — TODAY'S SCENE

A concrete operating moment in the role's life TODAY: current
problem, existing workaround, comparable tool, decision point that
triggers the need. Read your draft aloud and ask "has the role
already lived this moment?" If you assume product usage that does
not exist, rewrite.


decision_target — A FIRST-RELEASE DESIGN FORK

One short phrase naming a concrete first-release decision the
evidence is meant to move. A real decision_target names a fork a
developer could implement two different ways depending on what
the dialogue surfaces.

Self-test: "Could a reader of decision_target name two different
first-release builds that the dialogue's answer would steer
between?" If no, rewrite.

Hallmarks of a weak decision_target: a single quality keyword
alone ("<X> clarity"); a noun + "potential"; phrasings like
"support for <role>" / "understanding of <topic>"; meta-phrasings
like "informs requirements". Rewrite as "<A> vs <B>" over a
concrete first-release artifact (format, placement, handoff,
error boundary, cadence, scope edge).


seed_question — OPEN INVITATION INTO TODAY'S SCENE

Asks what the role does / notices / decides / wishes TODAY — not
what they would want from a hypothetical product.
Self-test: "Could the role answer this without ever having seen
the product we are proposing?" If no, rewrite.
Avoid yes/no, either/or, design framing, confirmation framing.


merge_anchor — ONLY WHEN vision_refs HAS MORE THAN ONE ENTRY

One concrete sentence with named perspective, scene, and shared
first-release decision:
  "One answer from <perspective> in <scene> would settle
   <evidence A> and <evidence B> because <shared first-release
   decision>."
The shared decision must be a concrete first-release choice, not
vague glue.
Both splits and merges need named anchors; do not split for
symmetry, do not merge for compression. 1:1 is the common case.


notes (this pass) — reviewer commentary only

Use the notes field for substantive commentary: which merges /
splits you made and why, any vision id you intentionally did not
attach and why, any role you considered as a perspective and
ruled out. Python will generate the per-id audit table separately
— do NOT duplicate it here.


WHAT YOU MUST NOT WRITE IN PASS 1

- coverage_points (Pass 2)
- close_when (Pass 2)
- IT-NNN ids (Python)
- audit format "<ID> → IT-XXX" (Python)
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2 prompt — COVERAGE
# ─────────────────────────────────────────────────────────────────────────────

_COVERAGE_BODY = """\
PASS 2 OF 2 — WRITE COVERAGE FOR EACH DRAFTED ITEM

The agenda items below have been drafted with IDs assigned. Your
single task: for EACH item, produce coverage_points (2-5
entries) and a close_when summary. You do not touch the other
fields.

CORE PRINCIPLES

P1. THE PRODUCT DOES NOT EXIST YET. Every coverage_point is a
fact the role can say TODAY — current problem, existing
workaround, comparable tool, decision they already face. If the
sentence references the proposed product (its name, its feature,
its tool), the role cannot truthfully say it today — rewrite.

P2. EACH COVERAGE_POINT IS ONE COMPLETE LIVED FACT. Open from the
role's verb mentally ("I tried …", "I noticed …", "I gave up
when …", "I wished …", "I decided …", "I got blocked by …", "I
worked around …"), then trim to a self-contained sentence with
concrete detail. Stub fragments that trail off ("I tried X
because…", "I noticed Y when…", "I usually do Z like…") are
incomplete — finish them.


REVIEWED PRODUCT VISION (for reference, do not modify)
{vision}


DRAFTED ITEMS — fill coverage for each by item_id
{items}


coverage_points — TODAY'S LIVED FACTS (per item, 2-5 entries)

The TODAY GATE applies to EVERY item — assumption-referenced,
concern-referenced, AND scope-referenced. For a scope item, the
coverage_points are still TODAY's friction with the current
state, NOT how the role imagines the proposed product will sit
beside the existing thing.

Verb-head self-test, applied per entry: "Could the role say this
sentence today, BEFORE the product is built?" If no, rewrite.

Completeness self-test: "Does the sentence end with concrete
detail, or does it trail off ('...because...', '...when...',
'...like...', '...such as...')?" If it trails off, finish it.

Common red flags — rewrite immediately:
- The sentence names the proposed product or one of its features.
- The sentence describes a reaction to using the proposed product.
- The sentence ends with a connective and no detail.
- The noun head is researcher jargon (criteria, instances,
  experiences of, preferences for, strategies for, understanding
  of, common X, comfort level, perceptions of, engagement levels,
  accounts of, use cases for).

For an item whose vision_refs include a scope/boundary id (OOS-),
remember the scene is the role bumping into TODAY's existing
state at the boundary — not comparing it to a future product. For
example, "I read the existing reference and got stuck at <X>" /
"I expected the existing material to cover <Y> but it didn't" /
"I asked <today's authority> about <boundary> and they said <Z>".

The smallest set whose settling moves the item's decision_target
— typically 3-5 entries. Do not pad.


close_when — STOP CONDITION

A short readable sentence summarizing when the coverage_points
above are met (what pattern across stakeholders signals enough
has been heard).


OUTPUT FORMAT

Produce `coverages` — a list with one entry per drafted item.
Each entry has `item_id` (the IT-NNN id of the drafted item) and
the `coverage_points` + `close_when` you wrote for it. Cover
EVERY drafted item; do not skip any.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class AgendaAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="agenda")

    def _register_tools(self) -> None:
        """Agenda uses structured extraction only."""

    @staticmethod
    def _vision(state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        return artifacts.get("reviewed_product_vision") or {}

    @staticmethod
    def _feedback(state: Dict[str, Any]) -> Optional[str]:
        feedback = (state.get("elicitation_agenda_feedback") or "").strip()
        return feedback or None

    @staticmethod
    def _user_prompt(feedback: Optional[str]) -> str:
        text = "Build the elicitation agenda following the system prompt instructions."
        if feedback:
            text += (
                "\n\nReviewer feedback to address before regenerating the artifact:\n"
                f"{feedback}"
            )
        return text

    def _system(self, body: str) -> str:
        return f"{self.profile.prompt}\n\n{body}"

    def _pass1(self, vision: Dict[str, Any], feedback: Optional[str]) -> DraftPass:
        body = _DRAFT_BODY.format(
            vision=json.dumps(vision, indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
            schema=DraftPass,
            system_prompt=self._system(body),
            user_prompt=self._user_prompt(feedback),
            include_memory=False,
        )

    def _pass2(
        self,
        vision: Dict[str, Any],
        drafted_items: List[AgendaItem],
        feedback: Optional[str],
    ) -> CoveragePass:
        items_summary = [
            {
                "item_id": item.id,
                "vision_refs": item.vision_refs,
                "perspective": item.perspective,
                "context": item.context,
                "decision_target": item.decision_target,
                "seed_question": item.seed_question,
                "merge_anchor": item.merge_anchor,
            }
            for item in drafted_items
        ]
        body = _COVERAGE_BODY.format(
            vision=json.dumps(vision, indent=2, ensure_ascii=False),
            items=json.dumps(items_summary, indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
            schema=CoveragePass,
            system_prompt=self._system(body),
            user_prompt=self._user_prompt(feedback),
            include_memory=False,
        )

    @staticmethod
    def _assign_item_ids(items: List[AgendaItem]) -> None:
        for index, item in enumerate(items, 1):
            item.id = f"IT-{index:03d}"

    @staticmethod
    def _merge_coverage(items: List[AgendaItem], coverages: List[ItemCoverage]) -> None:
        coverage_map: Dict[str, ItemCoverage] = {c.item_id: c for c in coverages}
        for item in items:
            entry = coverage_map.get(item.id)
            if entry is None:
                logger.warning(
                    "[AgendaAgent] No coverage entry produced for %s — leaving empty.",
                    item.id,
                )
                continue
            item.coverage_points = list(entry.coverage_points or [])
            item.close_when = (entry.close_when or "").strip()

    @staticmethod
    def _vision_role_names(vision: Dict[str, Any]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for role in (vision.get("roles") or []):
            rid = role.get("id") or ""
            name = role.get("name") or ""
            if rid or name:
                out.append({"id": rid, "name": name})
        return out

    @staticmethod
    def _generate_audit_notes(
        items: List[AgendaItem],
        vision: Dict[str, Any],
        llm_commentary: str,
    ) -> str:
        """Walk vision IDs and items[]; emit deterministic per-id audit lines."""

        def collect_ids(key: str) -> List[str]:
            return [
                str(entry.get("id") or "").strip()
                for entry in (vision.get(key) or [])
                if str(entry.get("id") or "").strip()
            ]

        assumption_ids = collect_ids("assumptions")
        concern_ids = collect_ids("concerns")
        scope_ids = collect_ids("scope")
        roles = AgendaAgent._vision_role_names(vision)

        # Build reverse maps
        items_by_ref: Dict[str, List[str]] = {}
        items_by_perspective: Dict[str, List[str]] = {}
        for item in items:
            for ref in item.vision_refs or []:
                items_by_ref.setdefault(ref, []).append(item.id)
            persp = (item.perspective or "").strip()
            if persp:
                items_by_perspective.setdefault(persp.lower(), []).append(item.id)

        def status_for_id(vid: str) -> str:
            covering = items_by_ref.get(vid) or []
            if not covering:
                return "gap-named: no item targets it"
            if len(covering) == 1:
                # Is this item multi-ref (i.e., this id is merged with others)?
                target_item = next((it for it in items if it.id == covering[0]), None)
                if target_item and len(target_item.vision_refs) > 1:
                    others = [r for r in target_item.vision_refs if r != vid]
                    other_str = ", ".join(others)
                    return f"{covering[0]} (merged with {other_str})"
                return covering[0]
            return ", ".join(covering)

        def status_for_role(role: Dict[str, str]) -> str:
            name = (role.get("name") or "").strip()
            using = items_by_perspective.get(name.lower(), [])
            if not using:
                return "gap-named: no item uses it as perspective"
            return f"used as perspective in {', '.join(using)}"

        lines: List[str] = []

        if assumption_ids:
            for aid in assumption_ids:
                lines.append(f"{aid} → {status_for_id(aid)}")
        else:
            lines.append("no assumptions in vision")

        if concern_ids:
            for cid in concern_ids:
                lines.append(f"{cid} → {status_for_id(cid)}")
        else:
            lines.append("no concerns in vision")

        if scope_ids:
            for sid in scope_ids:
                lines.append(f"{sid} → {status_for_id(sid)}")
        else:
            lines.append("no scope in vision")

        if roles:
            for role in roles:
                rid = role.get("id") or "ROLE"
                name = role.get("name") or "(unnamed)"
                lines.append(f"{rid} {name} → {status_for_role(role)}")
        else:
            lines.append("no roles in vision")

        audit_block = "\n".join(lines)
        commentary = (llm_commentary or "").strip()
        if commentary:
            return f"{audit_block}\n\n--- Reviewer commentary ---\n{commentary}"
        return audit_block

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        vision = self._vision(state)
        if not vision:
            logger.warning("[AgendaAgent] reviewed_product_vision is missing.")
            return {}

        feedback = self._feedback(state)
        logger.info("[AgendaAgent] Building agenda (2 passes).")

        try:
            draft = self._pass1(vision, feedback)
        except Exception as exc:
            logger.error("[AgendaAgent] Pass 1 (draft) failed: %s", exc, exc_info=True)
            return {}

        # Convert draft items to final AgendaItem shape (coverage_points + close_when blank)
        items: List[AgendaItem] = [
            AgendaItem(
                vision_refs=list(d.vision_refs or []),
                perspective=d.perspective,
                context=d.context,
                decision_target=d.decision_target,
                seed_question=d.seed_question,
                merge_anchor=d.merge_anchor or "",
                notes=d.notes or "",
                coverage_points=[],
                close_when="",
            )
            for d in (draft.items or [])
        ]
        self._assign_item_ids(items)

        try:
            coverage = self._pass2(vision, items, feedback)
        except Exception as exc:
            logger.error("[AgendaAgent] Pass 2 (coverage) failed: %s", exc, exc_info=True)
            return {}

        self._merge_coverage(items, coverage.coverages or [])

        audit_notes = self._generate_audit_notes(items, vision, draft.notes or "")
        agenda = Agenda(notes=audit_notes, items=items)
        runtime = AgendaRuntime.from_agenda(agenda)

        agenda_dict = agenda.model_dump()
        artifacts = dict(state.get("artifacts") or {})
        artifacts["elicitation_agenda_artifact"] = {
            "session_id": state.get("session_id", ""),
            "created_at": datetime.now().isoformat(),
            "status": "pending_review",
            **agenda_dict,
        }

        updates: Dict[str, Any] = {
            "elicitation_agenda": runtime.model_dump(),
            "artifacts": artifacts,
        }
        if feedback:
            updates["elicitation_agenda_feedback"] = None

        logger.info("[AgendaAgent] Agenda ready — %d items.", len(items))
        return updates
