"""
agenda.py - AgendaAgent

AgendaAgent reads the reviewed Product Vision and produces a
**lived-scenes** elicitation agenda. Each item names one concrete
moment in one role's life today where multiple frictions converge.
The interview opens with a critical-incident invitation and drills
each friction to a specific past incident, workaround, or explicit
gap.

Each item carries:
- perspective (role name from vision.roles);
- scene (triggering moment + working activity);
- frictions_to_probe (the points the interviewer will drill);
- critical_incident_prompt (the opening invitation);
- close_when (stop condition).

Vision IDs do NOT travel with items. The vision is read as the
strategic-decision menu the reviewer answers in HITL; the agenda
is the lived-experience menu the stakeholder answers in interview.
Python audit matches vision-entry text against scene+frictions
text informationally so reviewers can see likely coverage —
matches are never required.

Execution: two sequential extract_structured passes.
- Pass 1 (DRAFT): vision → scene items.
- Pass 2 (CLOSE-WHEN): produce one close_when sentence per item.

Python responsibilities:
- assigns IT-NNN ids deterministically;
- merges Pass 2 close_when entries back by id;
- writes the informational coverage audit (role exact match,
  assumption / concern / scope text overlap);
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
# Final Agenda schema (assumption-backed, concern-led)
# ─────────────────────────────────────────────────────────────────────────────

class AgendaItem(BaseModel):
    id: str = Field(default="", description="Stable id IT-NNN; Python assigns.")
    perspective: str = Field(description="Canonical role name from vision.roles.")
    scene: str = Field(description="One concrete moment in the role's life today: triggering event + the activity they are doing when it happens.")
    frictions_to_probe: List[str] = Field(default_factory=list, description="Concrete past moments the interviewer will drill inside this scene — points where the role's behavior was shaped by what was present or absent, drillable to a specific past incident.")
    critical_incident_prompt: str = Field(description="One opening invitation asking the role to recount a specific past incident in this scene.")
    close_when: str = Field(description="Stop condition: when each friction has been drilled to a specific past incident or explicit gap.")
    notes: str = Field(default="", description="Optional reviewer-facing note for this item.")


class Agenda(BaseModel):
    notes: str = Field(description="Reviewer-facing audit notes. Python generates the vision-coverage audit; LLM commentary appends below.")
    items: List[AgendaItem] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Runtime shapes (consumed by InterviewerAgent / EndUserAgent / DistillerAgent)
# ─────────────────────────────────────────────────────────────────────────────

class AgendaRuntimeItem(BaseModel):
    """Runtime view of an agenda item.

    Wraps the LLM-authored fields with the runtime state the
    interviewer + enduser loop produces (signals, talk turns,
    assumption_evidence, gaps, coverage). Downstream agents read
    ``perspective`` / ``scene`` / ``frictions_to_probe`` /
    ``critical_incident_prompt`` for context. ``vision_refs`` is a
    legacy slot kept empty; assumption_evidence is recorded by id
    against the vision artifact directly.
    """
    id: str
    perspective: str
    scene: str
    frictions_to_probe: List[str] = Field(default_factory=list)
    critical_incident_prompt: str
    close_when: str
    notes: str = ""
    vision_refs: List[str] = Field(default_factory=list)

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
        is_runtime = "talk" in items_raw[0]
        items: List[AgendaRuntimeItem] = []
        for raw in items_raw:
            # Tolerate both new (scene / critical_incident_prompt /
            # frictions_to_probe) and legacy (context / seed_question /
            # coverage_points) artifact shapes; the new shape is the
            # canonical one going forward.
            kwargs: Dict[str, Any] = {
                "id": raw.get("id", ""),
                "perspective": raw.get("perspective", ""),
                "scene": raw.get("scene") or raw.get("context") or "",
                "frictions_to_probe": list(
                    raw.get("frictions_to_probe") or raw.get("coverage_points") or []
                ),
                "critical_incident_prompt": (
                    raw.get("critical_incident_prompt")
                    or raw.get("seed_question")
                    or ""
                ),
                "close_when": raw.get("close_when", ""),
                "notes": raw.get("notes", ""),
                "vision_refs": list(raw.get("vision_refs") or []),
            }
            if is_runtime:
                for key in (
                    "status", "question", "answer", "talk", "rule",
                    "signals", "gaps", "assumption_evidence", "coverage",
                ):
                    if key in raw and raw[key] is not None:
                        kwargs[key] = raw[key]
            items.append(AgendaRuntimeItem(**kwargs))
        return cls(
            items=items,
            current_index=artifact.get("current_index", 0) if is_runtime else 0,
            elicitation_complete=(
                artifact.get("elicitation_complete", False) if is_runtime else False
            ),
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
    perspective: str = Field(description="Canonical role name from vision.roles.")
    scene: str = Field(description="One concrete moment in the role's life today: triggering event + the activity they are doing when it happens.")
    frictions_to_probe: List[str] = Field(default_factory=list, description="Friction points the interviewer should drill inside this scene.")
    critical_incident_prompt: str = Field(description="One opening invitation asking the role to recount a specific past incident in this scene.")
    notes: str = Field(default="", description="Optional reviewer-facing note.")


class DraftPass(BaseModel):
    notes: str = Field(default="", description="Reviewer-facing commentary about scene selection, lived moments considered, and any stakes left out.")
    items: List[DraftItem] = Field(default_factory=list)


class ItemCoverage(BaseModel):
    item_id: str = Field(description="The IT-NNN id of the drafted item this entry corresponds to.")
    close_when: str = Field(description="Stop condition: when each friction has been drilled to a specific past incident or explicit gap.")


class CoveragePass(BaseModel):
    coverages: List[ItemCoverage] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1 prompt — DRAFT (assumption-backed, concern-led skeleton)
# ─────────────────────────────────────────────────────────────────────────────

_DRAFT_BODY = """\
PASS 1 OF 2 — DRAFT THE AGENDA AS LIVED SCENES

The agenda directs an interview whose downstream output is a
catalog of product capabilities. Your job: pick the SCENES in
roles' lives today that are rich enough to surface that catalog
when a stakeholder is invited to recount a specific past incident
in the scene.

Each item names ONE scene — a concrete moment in ONE role's life
where multiple frictions converge. The interviewer will open with
a critical-incident invitation and drill each friction until a
specific past incident, workaround, or explicit gap is on record.


REVIEWED PRODUCT VISION (ground truth — read for context; do not
echo vision IDs into items)
{vision}


THE PRODUCT DOES NOT EXIST YET. Every scene must be a moment the
role has already lived. Anything that references the proposed
product is not a scene — it is design conversation, which the
interview does not run. Frictions are concrete past moments where
the role's behavior was shaped by what was present or absent in
their life as it is today.


VISION IS GROUND TRUTH, NOT A 1:1 DRIVER. Use only role names
that appear in vision.roles. Vision.assumptions, vision.concerns,
and vision.scope are the strategic forks, quality dimensions, and
boundaries the team is debating — read them so your scenes pick
moments that LIKELY surface evidence on them. Do NOT iterate
assumptions × roles to manufacture items, and do NOT attach
vision IDs to items; scenes touch the vision through lived
content, not through declared references. A scene drafted only
to "cover" a vision id becomes a hypothetical conversation the
interviewer cannot drill — skip it.


WHAT A SCENE HOLDS. A useful scene reads as: when <triggering
moment> happens, <role> is in the middle of <working activity>
and runs into <a few frictions>. The triggering moment is what
makes the role start the activity; the activity is what they
are doing when frictions hit; the frictions are the concrete
points the interviewer will drill. A scene without frictions is
observation — drop. A scene whose frictions all collapse to one
root friction is too narrow — re-frame to include the
surrounding moment so the drill yields more than one capability.


DISTINCTNESS — SCENES EARN THEIR PLACE BY DIFFERING. Two scenes
are paraphrases of one moment when, if drilled, they would
surface the same lived evidence: the role tries the same thing,
falls back to the same workaround, notices the same absence,
faces the same consequence. Two scenes are genuinely distinct
when the drill on each would surface evidence the other would
not. The dimensions on which two scenes can differ are not fixed
in advance — read each pair you draft and ask: drilled, what
would each one show that the other would not? The dimension
that emerges from that comparison is the dimension that
justifies keeping both. If your answer is "essentially the same
evidence in different words", collapse. When you keep a near-
pair distinct, you may name the dimension in `notes` if it would
help the reviewer see the reasoning — but the dimension itself
is yours to identify; there is no fixed axis list to walk.

A role inhabits multiple distinct moments around the product —
different points in time, different counterparts they engage
with, different things they are trying to reach or avoid,
different positions the same activity puts them in. Multi-scene
per role is the natural outcome; a role with only one scene
needs a reason (the role genuinely lives one recurring moment
relevant to this product, or every other moment they would live
is already covered by another role's scene). State the reason
in `notes` so the reviewer can verify.

Walk every role in vision.roles (including the inferred ones)
and consider their plausible moments before settling. A role
with zero scenes leaves a vision-named stake unprobed; zero
scenes is acceptable only when the reason is specific in `notes`
(state which structural responsibility the role holds that does
not surface as a lived moment around the product, or which
existing scene already covers the role's runtime experience).
Let the count of scenes emerge from how many genuinely distinct
moments the roles actually inhabit; do not target a number, do
not artificially constrain to one-per-role either.


BREADTH ACROSS THE VISION. After drafting the set, scan it as a
whole: do the scenes collectively touch a wide set of vision
elements (roles, assumptions, concerns, scope), or do they
cluster on one or two leaving others silent? If they cluster,
the agenda has gone vertical — many scenes drilling one corner
of the design space — and re-balance by replacing or splitting
toward elements the current draft does not yet touch. Coverage
stays anchored to the vision — do not invent axes the vision
does not raise. The vision (after its own coverage walks) is the
breadth menu; the agenda serves that breadth.


ASSUMPTIONS ARE FORKS WORTH A SCENE. An assumption is a first-
release decision the team must make. When the role lives a moment
where that decision already bites today — they choose, work
around it, or fall back on something — that moment earns a scene,
so the interview gathers evidence that informs the fork instead
of leaving it for the reviewer to decide blind. Reserve the
notes-only "strategic-HITL" routing for forks no lived moment can
reach; do not send a fork there just because no scene drafted yet
happens to touch it.


FRICTION DIVERSITY ACROSS SCENES. A role's life around the
product surfaces friction in genuinely different kinds of moment
— what they try and what breaks, what they cannot see or know,
what costs them effort or risk, what depends on other people,
what shifts when constraints change, what they fall back on
when the path they would prefer is unavailable. Read your full
set of frictions across all scenes and ask: are they sampling
that breadth, or are they many costumes of one pain-pattern? If
one pain-pattern dominates, the dialogue will keep returning the
same kind of evidence and the requirement list will get one
capability stated many ways. Re-balance by reshaping some scenes
so their frictions honestly produce a different kind of pain
the role's life can produce.


USER OVER OBSERVER — perspective rule. When the lived frictions
are user-perceptible (confusion, mistrust, surprise, recovery,
effort, delay, error), the user is the perspective for that
scene. An observer or authority can witness the phenomenon, but
their evidence about it is third-person — downstream synthesis
cannot turn "the observer reports the user is confused" into
product-side acceptance criteria. When both the user and an
observer/authority have stake in the same theme, draft two
distinct scenes (one per perspective); the observer's scene is
about their own activity (their decision, their workflow), not
their report on the user.


WRITING FIELDS

`perspective`: the role name from vision.roles whose life
contains this scene. One name, no invention.

`scene`: one short paragraph — triggering moment + working
activity + enough texture that a reader can picture the role
in it. Read aloud and ask: has the role lived this moment
today, before any product was built? If not, rewrite.

`frictions_to_probe`: the friction points the interviewer will
drill inside this scene. Each one names a concrete past moment
where the role's behavior was shaped by what was present or
absent — what got in their way, what they fell back on, what
they could not settle. Read each and ask: could the role
recount this as a specific past incident? If the wording reads
as a design wish ("they need X", "they would like Y") rather
than a lived moment, rewrite or drop.

`critical_incident_prompt`: one opening invitation asking the
role to recount a SPECIFIC PAST INCIDENT in this scene. Past
tense, concrete, open. Self-test: could the role answer this
without ever having seen the product we are proposing? If no,
rewrite. Avoid yes/no framing, design framing ("would you
use…"), hypothetical framing ("imagine if…"), aggregate framing
("how often do users…").

`notes`: reviewer-facing commentary. Use it to record any roles
you considered and ruled out (no scene rich enough), any vision
forks you read as strategic-HITL-only (the dialogue cannot
settle them by reporting today), any tension between two scenes
you considered merging or splitting, and any dimension name you
would give a near-pair you kept distinct.

`close_when` and `id` are not written here — Pass 2 produces
close_when; Python assigns IT-NNN.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2 prompt — COVERAGE
# ─────────────────────────────────────────────────────────────────────────────

_COVERAGE_BODY = """\
PASS 2 OF 2 — WRITE THE STOP CONDITION FOR EACH DRAFTED ITEM

The agenda items below have been drafted with IDs assigned. For
each item, produce one `close_when` sentence — the interviewer's
stop condition. Touch no other field.

A close_when names when the interviewer has heard enough on this
scene. Under critical-incident drilling, "enough" means every
friction in `frictions_to_probe` has either been drilled to a
specific past incident (with the role's workaround or response
on record) OR has been explicitly logged as a gap (the role
declined, could not recall, or no longer encounters that
friction).

A strong close_when reads in one short sentence, uses past-tense
framing, and ties stop to the frictions list — the reader can
see, from the sentence alone, which evidence ends the drill. A
weak close_when names a count, a checklist tick, or a vague
sufficiency criterion ("when enough has been heard", "when N
points are collected") — the reader cannot tell from the
sentence when to stop. Rewrite weak ones. Do not lift a phrasing
from another item; let each close_when fit the frictions of its
own scene.


REVIEWED PRODUCT VISION (read for context; do not echo)
{vision}


DRAFTED ITEMS
{items}


OUTPUT FORMAT

Produce `coverages` — one entry per drafted item, identified by
`item_id`. Cover every item; do not skip any.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Feedback re-run (only attached when reviewer feedback is present)
# ─────────────────────────────────────────────────────────────────────────────

_FEEDBACK_PREAMBLE = """\
FEEDBACK RE-RUN — REVIEWER REJECTED THE PREVIOUS OUTPUT.

The user message includes the reviewer feedback verbatim. Treat
each feedback point as a non-negotiable instruction that overrides
your default reasoning when the two conflict — if a point tells
you to keep / drop / rewrite / split / merge / re-tag a specific
element, comply exactly even when your own judgment would have
chosen differently. The "MUST address every point" contract is
absolute: a point left untouched is a failed run, not a judgment
call.

For any aspect the feedback is silent on, produce output the same
way you normally would — feedback narrows your choices on the
points it names; it does not loosen any other guarantee the pass
already owes.
"""


_FEEDBACK_USER_BODY = """\

REVIEWER FEEDBACK — YOU MUST ADDRESS EVERY POINT BELOW:
{feedback}

Apply each point at the right slot of the agenda item it names:
  perspective · scene · frictions_to_probe ·
  critical_incident_prompt · close_when · notes.

When a point asks to drop an item, do not redistribute its scene
or frictions to a different item just to keep role-coverage
numbers — honor the drop and let the audit reflect it. When a
point asks to add or split items, regenerate them through the
same role-coverage and friction-saturation discipline this pass
already owes; do not shortcut.
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
            text += _FEEDBACK_USER_BODY.format(feedback=feedback)
        return text

    def _system(self, body: str, feedback_mode: bool = False) -> str:
        preamble = f"{_FEEDBACK_PREAMBLE}\n\n" if feedback_mode else ""
        return f"{preamble}{self.profile.prompt}\n\n{body}"

    def _pass1(self, vision: Dict[str, Any], feedback: Optional[str]) -> DraftPass:
        body = _DRAFT_BODY.format(
            vision=json.dumps(vision, indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
            schema=DraftPass,
            system_prompt=self._system(body, feedback_mode=bool(feedback)),
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
                "perspective": item.perspective,
                "scene": item.scene,
                "frictions_to_probe": item.frictions_to_probe,
                "critical_incident_prompt": item.critical_incident_prompt,
            }
            for item in drafted_items
        ]
        body = _COVERAGE_BODY.format(
            vision=json.dumps(vision, indent=2, ensure_ascii=False),
            items=json.dumps(items_summary, indent=2, ensure_ascii=False),
        )
        return self.extract_structured(
            schema=CoveragePass,
            system_prompt=self._system(body, feedback_mode=bool(feedback)),
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
            item.close_when = (entry.close_when or "").strip()

    @staticmethod
    def _generate_audit_notes(
        items: List[AgendaItem],
        vision: Dict[str, Any],
        llm_commentary: str,
    ) -> str:
        """Walk vision entries and emit informational coverage notes.

        Under the lived-scenes design no item carries typed refs.
        Coverage is derived by matching vision-entry text against the
        scene + frictions text of each item — informational only,
        never a gate. Roles are matched by canonical name (already
        deterministic).
        """

        def collect(key: str) -> List[Dict[str, Any]]:
            return [
                entry
                for entry in (vision.get(key) or [])
                if str(entry.get("id") or "").strip()
            ]

        roles = collect("roles")
        assumptions = collect("assumptions")
        concerns = collect("concerns")
        scope = collect("scope")

        def _tokenize(text: str) -> set:
            return {
                token
                for token in (text or "").lower().split()
                if len(token) > 3
            }

        def _scan(entry_text: str, item: AgendaItem) -> bool:
            """True if entry text shares any meaningful token with item text."""
            item_blob = " ".join(
                filter(None, [item.scene, " ".join(item.frictions_to_probe or [])])
            )
            entry_tokens = _tokenize(entry_text)
            item_tokens = _tokenize(item_blob)
            return bool(entry_tokens & item_tokens)

        def _matches_for(entry: Dict[str, Any]) -> List[str]:
            entry_text = " ".join(
                str(entry.get(key) or "")
                for key in ("statement", "theme", "item", "rationale", "why_it_matters")
            )
            return [item.id for item in items if _scan(entry_text, item)]

        # Roles match by canonical name (exact, not substring).
        items_by_perspective: Dict[str, List[str]] = {}
        for item in items:
            persp = (item.perspective or "").strip().lower()
            if persp:
                items_by_perspective.setdefault(persp, []).append(item.id)

        lines: List[str] = []

        lines.append("ROLE COVERAGE (exact perspective match)")
        if roles:
            for role in roles:
                rid = str(role.get("id") or "").strip() or "ROLE"
                name = (role.get("name") or "(unnamed)").strip()
                lens = (role.get("lens") or "").strip()
                using = items_by_perspective.get(name.lower(), [])
                lens_tag = f" [{lens}]" if lens else ""
                if using:
                    lines.append(
                        f"  {rid} {name}{lens_tag} → perspective in {', '.join(using)}"
                    )
                else:
                    lines.append(
                        f"  {rid} {name}{lens_tag} → not selected by any scene "
                        "(structural role or vision missing a fork this role lives)"
                    )
        else:
            lines.append("  (no roles in vision)")

        lines.append("")
        lines.append("ASSUMPTION LIKELY-TOUCH (informational; HITL when empty)")
        if assumptions:
            for a in assumptions:
                aid = str(a.get("id") or "").strip()
                lens = (a.get("lens") or "").strip()
                lens_tag = f" [{lens}]" if lens else ""
                touching = _matches_for(a)
                if touching:
                    lines.append(f"  {aid}{lens_tag} → likely surfaced in {', '.join(touching)}")
                else:
                    lines.append(
                        f"  {aid}{lens_tag} → no scene text overlap "
                        "(reviewer decides: strategic-HITL fork, or vision needs a scene)"
                    )
        else:
            lines.append("  (no assumptions in vision)")

        lines.append("")
        lines.append("CONCERN LIKELY-TOUCH (informational)")
        if concerns:
            for c in concerns:
                cid = str(c.get("id") or "").strip()
                lens = (c.get("lens") or "").strip()
                lens_tag = f" [{lens}]" if lens else ""
                touching = _matches_for(c)
                if touching:
                    lines.append(f"  {cid}{lens_tag} → likely surfaced in {', '.join(touching)}")
                else:
                    lines.append(
                        f"  {cid}{lens_tag} → no scene text overlap"
                    )
        else:
            lines.append("  (no concerns in vision)")

        lines.append("")
        lines.append("SCOPE LIKELY-TOUCH (informational)")
        if scope:
            for s in scope:
                sid = str(s.get("id") or "").strip()
                touching = _matches_for(s)
                if touching:
                    lines.append(f"  {sid} → likely surfaced in {', '.join(touching)}")
                else:
                    lines.append(
                        f"  {sid} → no scene text overlap (HITL decides if a boundary scene is missing)"
                    )
        else:
            lines.append("  (no scope in vision)")

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

        # Convert draft items to final AgendaItem shape (close_when blank,
        # filled in Pass 2).
        items: List[AgendaItem] = [
            AgendaItem(
                perspective=d.perspective,
                scene=d.scene,
                frictions_to_probe=list(d.frictions_to_probe or []),
                critical_incident_prompt=d.critical_incident_prompt,
                notes=d.notes or "",
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

        logger.info(
            "[AgendaAgent] Agenda ready — %d scene(s); coverage shown in audit block.",
            len(items),
        )
        return updates
