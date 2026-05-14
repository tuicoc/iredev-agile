"""
agenda.py - AgendaAgent

AgendaAgent converts the reviewed Product Vision into an interview agenda.

Design split
------------
Schema descriptions define the agenda artifact contract.
Prompt text defines how to derive entries and interview items.
Python only moves, stores, and orders already-produced data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from .base import BaseAgent

logger = logging.getLogger(__name__)


TRAP_DRILL_STYLE: Dict[str, str] = {
    "straw_man": (
        "Ask what condition breaks the simplified process, which exception matters, "
        "and what exact rule should replace the simplification."
    ),
    "extreme_boundary": (
        "Ask for the threshold, what changes after that boundary, and how a user "
        "would know the boundary has been crossed."
    ),
    "eternal_island": (
        "Ask which external source or destination matters, what event triggers the "
        "exchange, and which direction information moves."
    ),
    "role_inversion": (
        "Ask who may act, who may not, what approval or escalation exists, and what "
        "happens when the wrong role acts."
    ),
    "priority_split": (
        "Ask when both pressures occur together, which rule wins, what condition "
        "separates them, and whether a person or a rule resolves the tie."
    ),
    "quality_probe": (
        "Ask for lived examples, the condition where quality failure matters, "
        "tolerable failure, and the strongest quality boundary the stakeholder "
        "can defend."
    ),
}


# ---------------------------------------------------------------------------
# Map artifact
# ---------------------------------------------------------------------------

class MapEntry(BaseModel):
    id: str = Field(
        description="Stable map id in AM-NN format."
    )
    entity: str = Field(
        description="Entity name taken from Product Vision flow."
    )
    step: str = Field(
        description="Step name inside the selected entity."
    )
    role: str = Field(
        description="Stakeholder role whose duty or conflict angle this entry represents."
    )
    aspect: Literal[
        "operational_rule", "boundary_nfr", "integration", "permission",
        "quality_concern"
    ] = Field(
        description="Duty aspect that explains what the later agenda item must surface."
    )
    source: str = Field(
        description="Duty id, concern id, or local source id that created this entry."
    )
    kind: Literal["need", "conflict", "concern"] = Field(
        description=(
            "need = normal elicitation target from one duty. conflict = agenda hook "
            "for a possible rule collision that must be clarified in dialogue. "
            "concern = NFR softgoal that must be operationalized through dialogue."
        )
    )
    peer: Optional[str] = Field(
        default=None,
        description=(
            "Opposing duty, concern, or source id involved in a possible conflict. "
            "Null for normal need and concern entries."
        )
    )
    note: str = Field(
        description="Reviewer-facing explanation of why this entry belongs in the agenda."
    )
    risk: Optional[str] = Field(
        default=None,
        description=(
            "Failure or tension scenario this entry should help clarify. For duty "
            "entries, carry the duty risk. For concern or conflict entries, state "
            "the quality or rule collision consequence without adding thresholds."
        ),
    )
    concern_ref: Optional[str] = Field(
        default=None,
        description="NFR concern id for concern entries, else null."
    )
    concern_category: Optional[str] = Field(
        default=None,
        description="NFR concern category for concern entries, else null."
    )
    concern_theme: Optional[str] = Field(
        default=None,
        description="NFR concern theme for concern entries, else null."
    )


class AspectMap(BaseModel):
    notes: str = Field(
        description=(
            "Reviewer-facing audit note covering need mapping and possible conflict "
            "hooks discovered from the reviewed vision."
        )
    )
    entries: List[MapEntry] = Field(
        default_factory=list,
        description="Agenda map entries that will each become one agenda item."
    )


# ---------------------------------------------------------------------------
# Agenda artifact
# ---------------------------------------------------------------------------

class AgendaItem(BaseModel):
    id: str = Field(
        description="Stable agenda item id in IT-NN format."
    )
    entry: str = Field(
        description="Map entry id that produced this agenda item."
    )
    entity: str = Field(
        description="Entity context the interviewer must keep visible."
    )
    step: str = Field(
        description="Entity step context the interviewer must keep visible."
    )
    role: str = Field(
        description="Stakeholder role to interview for this item."
    )
    aspect: Literal[
        "operational_rule", "boundary_nfr", "integration", "permission",
        "quality_concern"
    ] = Field(
        description="Topic aspect of the item."
    )
    trap: Literal[
        "straw_man",
        "extreme_boundary",
        "eternal_island",
        "role_inversion",
        "priority_split",
        "quality_probe",
    ] = Field(
        description=(
            "Interview pressure style. priority_split is reserved for conflict items; "
            "quality_probe is reserved for concern items; the other traps expose "
            "missing detail in one duty."
        )
    )
    kind: Literal["need", "conflict", "concern"] = Field(
        description="need item, possible conflict item, or NFR concern item."
    )
    baseline: str = Field(
        description=(
            "Starting business rule or duty the interviewer is trying to clarify. "
            "This is private interviewer context."
        )
    )
    scene: str = Field(
        description=(
            "Stakeholder-facing lived situation at this entity and step. It must be "
            "enough for EndUserAgent to answer without seeing interview strategy."
        )
    )
    risk: Optional[str] = Field(
        default=None,
        description=(
            "Private interviewer-facing failure or tension scenario that the dialogue "
            "must resolve or bound before this item is closed."
        ),
    )
    probe: str = Field(
        description=(
            "Deliberately incomplete factual claim that invites the stakeholder to "
            "correct, narrow, or enrich it."
        )
    )
    gap: str = Field(
        description="Short noun phrase naming what the probe intentionally leaves out."
    )
    close: str = Field(
        description=(
            "Completion rule for the interviewer. For need items, it names the business "
            "rule that must become explicit. For conflict items, it names the precedence, "
            "scope split, or escalation rule that must become explicit. For concern "
            "items, it names the quality evidence needed to bound the risk."
        )
    )
    source: str = Field(
        description="Duty, concern, or map entry id behind this agenda item."
    )
    peer: Optional[str] = Field(
        default=None,
        description="Opposing duty, concern, or source id for conflict items, else null."
    )
    concern_ref: Optional[str] = Field(
        default=None,
        description="NFR concern id for concern items, else null."
    )
    concern_category: Optional[str] = Field(
        default=None,
        description="NFR concern category for concern items, else null."
    )
    concern_theme: Optional[str] = Field(
        default=None,
        description="NFR concern theme for concern items, else null."
    )


class Agenda(BaseModel):
    notes: str = Field(
        description="Reviewer-facing audit note for agenda construction."
    )
    flow: str = Field(
        description="Compact reference to the Product Vision entities used for ordering."
    )
    items: List[AgendaItem] = Field(
        default_factory=list,
        description="Final interview agenda in execution order."
    )


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------

class AgendaRuntimeItem(BaseModel):
    id: str
    entity: str
    step: str
    role: str
    aspect: str
    trap: str
    kind: str
    baseline: str
    scene: str
    risk: Optional[str] = None
    probe: str
    gap: str
    close: str
    source: str
    peer: Optional[str] = None
    concern_ref: Optional[str] = None
    concern_category: Optional[str] = None
    concern_theme: Optional[str] = None

    status: Literal["pending", "answered", "skipped"] = "pending"
    question: Optional[str] = None
    answer: Optional[str] = None
    talk: List[Dict[str, str]] = Field(default_factory=list)
    rule: Optional[str] = None
    align: Optional[Literal["exact", "narrower", "broader", "misaligned"]] = None
    signals: List[str] = Field(default_factory=list)

    @classmethod
    def from_item(cls, item: AgendaItem) -> "AgendaRuntimeItem":
        return cls(
            id=item.id,
            entity=item.entity,
            step=item.step,
            role=item.role,
            aspect=item.aspect,
            trap=item.trap,
            kind=item.kind,
            baseline=item.baseline,
            scene=item.scene,
            risk=item.risk,
            probe=item.probe,
            gap=item.gap,
            close=item.close,
            source=item.source,
            peer=item.peer,
            concern_ref=item.concern_ref,
            concern_category=item.concern_category,
            concern_theme=item.concern_theme,
        )


class AgendaRuntime(BaseModel):
    items: List[AgendaRuntimeItem]
    current_index: int = 0
    elicitation_complete: bool = False

    @classmethod
    def from_agenda(cls, agenda: Agenda) -> "AgendaRuntime":
        return cls(items=[AgendaRuntimeItem.from_item(i) for i in agenda.items])

    @classmethod
    def from_agenda_artifact(cls, artifact: Dict[str, Any]) -> "AgendaRuntime":
        if "items" in artifact and artifact["items"]:
            first = artifact["items"][0]
            if "baseline" in first and "close" in first and "talk" in first:
                return cls(**artifact)
            if "baseline" in first and "close" in first:
                return cls(
                    items=[
                        AgendaRuntimeItem(
                            id=raw.get("id", ""),
                            entity=raw.get("entity", ""),
                            step=raw.get("step", ""),
                            role=raw.get("role", ""),
                            aspect=raw.get("aspect", "operational_rule"),
                            trap=raw.get("trap", "straw_man"),
                            kind=raw.get("kind", "need"),
                            baseline=raw.get("baseline", ""),
                            scene=raw.get("scene", ""),
                            risk=raw.get("risk"),
                            probe=raw.get("probe", ""),
                            gap=raw.get("gap", ""),
                            close=raw.get("close", ""),
                            source=raw.get("source", ""),
                            peer=raw.get("peer"),
                            concern_ref=raw.get("concern_ref"),
                            concern_category=raw.get("concern_category"),
                            concern_theme=raw.get("concern_theme"),
                        )
                        for raw in artifact.get("items") or []
                    ]
                )
        return cls(items=[])

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


# ---------------------------------------------------------------------------
# Structured pass schemas
# ---------------------------------------------------------------------------

class MapPass(BaseModel):
    notes: str
    entries: List[MapEntry]


class ConflictPass(BaseModel):
    notes: str
    entries: List[MapEntry]


class ConcernPass(BaseModel):
    notes: str
    entries: List[MapEntry]


class ItemPass(BaseModel):
    notes: str
    items: List[AgendaItem]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_MAP_PROMPT = """\
PASS A - DUTY MAP

Read-only Product Vision flow:
{flow}

Read-only Product Vision roles:
{roles}

Task:
Convert every review-worthy duty into one map entry that keeps:
- the role that owns the duty,
- the entity and step already chosen in Product Vision,
- the semantic aspect already chosen in Product Vision,
- the duty id as source.
- the duty risk as the entry risk.

Rules:
- Do not create new duties.
- Do not move a duty to a new entity or step.
- Each entry must be independently useful for agenda construction.
- risk must preserve the role, condition, and failure outcome from the duty when
  present; if the duty risk is vague, sharpen it only from the duty wording and
  reviewed flow, without adding a new business rule.
- notes must explain how coverage was achieved.
"""

_CONFLICT_PROMPT = """\
PASS C - TENSION AND CONFLICT HOOKS

Read-only links:
{links}

Read-only map entries:
{entries}

Read-only roles:
{roles}

Task:
Add conflict map entries only when reviewed duties or concern pressures may
collide and dialogue should clarify precedence, scoping, escalation, or quality
tradeoff boundaries.

Recognize a possible conflict when:
- two entries can apply to the same or linked product moment, and
- following both without clarification could create incompatible action, priority,
  ownership, permission, limit, timing, or quality pressure.

Important:
- This pass suspects conflict; it does not decide the final resolution.
- A missing authority role is not a reason to invent one.
- If no meaningful possible conflict exists, return entries=[].
- For each conflict angle, create one entry for the stakeholder who should be
  questioned from that angle.
- source stores the entry or duty/concern id for the local angle; peer stores
  the opposing source id.
- risk states what could go wrong if both pressures are followed without a
  clarified condition, precedence rule, escalation path, or accepted ambiguity.
"""

_CONCERN_PROMPT = """\
PASS B - NFR CONCERN MAP

Read-only Product Vision flow:
{flow}

Read-only Product Vision roles:
{roles}

Read-only Product Vision NFR concerns:
{concerns}

Task:
Convert each reviewed NFR concern into one concern map entry.

Rules:
- Do not create new concerns.
- Do not create new entities, steps, or roles.
- kind must be concern.
- aspect must be quality_concern.
- source and concern_ref must carry the concern id when present. If the concern
  has no id, use CONCERN-NN consistently from list order.
- role must be one of the concern's affected_roles. Choose the role most likely
  to describe lived quality impact.
- entity and step must come from the reviewed flow. If the concern attaches to
  an entity, choose that entity and the step where the quality is easiest to
  discuss. If it attaches to a step, choose the entity containing that step.
- note must explain how the entry is anchored.
- risk must state the stakeholder-facing failure or operating tension if the
  quality is not good enough. Do not include numbers, thresholds, technologies,
  or acceptance criteria.

Guardrails:
- A concern entry is an interview topic, not a final NFR. Do not write a
  threshold, SLA, technology, or acceptance criterion.
- If a concern cannot be anchored to an existing entity, step, and role, omit it
  and explain the omission in notes.
"""

_ITEM_PROMPT = """\
PASS D - AGENDA ITEMS

Read-only Product Vision flow:
{flow}

Read-only Product Vision roles:
{roles}

Read-only map entries:
{entries}

Task:
Create exactly one agenda item per map entry.

For need items:
- baseline restates the duty in business language.
- scene lets the stakeholder answer from lived work at the named entity step.
- risk carries the entry risk.
- probe is a factual claim that is intentionally incomplete.
- gap names the missing condition, threshold, dependency, or permission detail.
- close states what rule must become explicit to resolve or bound the risk
  before the interviewer may close.
- trap selection:
  operational_rule -> straw_man
  boundary_nfr -> extreme_boundary
  integration -> eternal_island
  permission -> role_inversion

For conflict items:
- use trap=priority_split.
- baseline states the local rule that is under pressure.
- scene describes the moment where two reviewed entries can collide.
- risk states the consequence of leaving the collision unresolved.
- probe presents a simplified priority assumption that should be corrected.
- gap names the missing precedence, scope split, or escalation rule.
- close states the exact clarification needed to remove ambiguity.

For concern items:
- use kind=concern, aspect=quality_concern, and trap=quality_probe.
- baseline restates the quality concern as a softgoal, not as a final
  requirement.
- scene lets the stakeholder answer from lived experience at the named entity
  step.
- risk carries the quality failure or operating tension to be bounded.
- probe is an intentionally incomplete quality claim that invites correction.
- gap names the missing operating condition, tolerable failure, comparative
  anchor, or quality boundary.
- close states what quality evidence must become explicit to resolve or bound
  the risk before the interviewer may close.
- carry concern_ref, concern_category, and concern_theme from the map entry.

For every item:
- The probe should deliberately omit or oversimplify the risk-driving condition,
  so a real stakeholder can correct it.
- The scene may include the lived situation and consequence, but must not expose
  trap language or private strategy.
"""

_MAP_USER = """\
Build the duty map from this reviewed Product Vision.
"""

_CONFLICT_USER = """\
Add only possible conflict hooks that justify agenda coverage.
"""

_CONCERN_USER = """\
Map reviewed NFR concerns into concern agenda entries.
"""

_ITEM_USER = """\
Create the executable agenda items.
"""

_FEEDBACK = (
    "\n\nReviewer feedback to address before regenerating the artifact:\n{feedback}"
)


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
    def _feedback(state: Dict[str, Any]) -> str:
        feedback = (state.get("elicitation_agenda_feedback") or "").strip()
        return _FEEDBACK.format(feedback=feedback) if feedback else ""

    @staticmethod
    def _sort(
        items: List[AgendaItem],
        entities: List[Dict[str, Any]],
    ) -> List[AgendaItem]:
        order: Dict[str, int] = {
            entity.get("name", ""): entity.get("order", 999)
            for entity in entities
        }
        steps: Dict[Tuple[str, str], int] = {}
        for entity in entities:
            entity_name = entity.get("name", "")
            for index, step in enumerate(entity.get("steps") or []):
                steps[(entity_name, step.get("name", ""))] = index
        return sorted(
            items,
            key=lambda item: (
                order.get(item.entity, 999),
                steps.get((item.entity, item.step), 999),
                item.role,
                item.id,
            ),
        )

    def build_aspect_map(self, state: Dict[str, Any]) -> Dict[str, Any]:
        vision = self._vision(state)
        if not vision:
            logger.warning("[AgendaAgent] reviewed_product_vision is missing.")
            return {}

        flow = vision.get("flow") or {}
        roles = vision.get("roles") or []
        concerns = vision.get("nfr_concerns") or []
        feedback = self._feedback(state)

        try:
            map_pass: MapPass = self.extract_structured(
                schema=MapPass,
                system_prompt=self.profile.prompt + "\n\n" + _MAP_PROMPT.format(
                    flow=json.dumps(flow, indent=2, ensure_ascii=False),
                    roles=json.dumps(roles, indent=2, ensure_ascii=False),
                ),
                user_prompt=_MAP_USER + feedback,
                include_memory=False,
            )
            if concerns:
                concern_pass: ConcernPass = self.extract_structured(
                    schema=ConcernPass,
                    system_prompt=self.profile.prompt + "\n\n" + _CONCERN_PROMPT.format(
                        flow=json.dumps(flow, indent=2, ensure_ascii=False),
                        roles=json.dumps(roles, indent=2, ensure_ascii=False),
                        concerns=json.dumps(concerns, indent=2, ensure_ascii=False),
                    ),
                    user_prompt=_CONCERN_USER + feedback,
                    include_memory=False,
                )
            else:
                concern_pass = ConcernPass(
                    notes="No reviewed NFR concerns were present in Product Vision.",
                    entries=[],
                )
            conflict_source_entries = map_pass.entries + concern_pass.entries
            conflict_pass: ConflictPass = self.extract_structured(
                schema=ConflictPass,
                system_prompt=self.profile.prompt + "\n\n" + _CONFLICT_PROMPT.format(
                    links=json.dumps((flow.get("links") or []), indent=2, ensure_ascii=False),
                    entries=json.dumps([e.model_dump() for e in conflict_source_entries], indent=2, ensure_ascii=False),
                    roles=json.dumps(roles, indent=2, ensure_ascii=False),
                ),
                user_prompt=_CONFLICT_USER + feedback,
                include_memory=False,
            )
        except Exception as exc:
            logger.error("[AgendaAgent] Map extraction failed: %s", exc, exc_info=True)
            return {}

        aspect_map = AspectMap(
            notes=(
                "PASS A - DUTY MAP\n"
                f"{map_pass.notes.strip()}\n\n"
                "PASS B - NFR CONCERN MAP\n"
                f"{concern_pass.notes.strip()}\n\n"
                "PASS C - TENSION AND CONFLICT HOOKS\n"
                f"{conflict_pass.notes.strip()}"
            ),
            entries=map_pass.entries + concern_pass.entries + conflict_pass.entries,
        )
        dump = aspect_map.model_dump()

        artifacts = dict(state.get("artifacts") or {})
        artifacts["aspect_map_artifact"] = {
            "session_id": state.get("session_id", ""),
            "created_at": datetime.now().isoformat(),
            "status": "pending_review",
            **dump,
            "summary": {
                "total": len(aspect_map.entries),
                "needs": sum(1 for e in aspect_map.entries if e.kind == "need"),
                "conflicts": sum(1 for e in aspect_map.entries if e.kind == "conflict"),
                "concerns": sum(1 for e in aspect_map.entries if e.kind == "concern"),
            },
        }
        return {"aspect_map": dump, "artifacts": artifacts}

    def build_agenda_items(self, state: Dict[str, Any]) -> Dict[str, Any]:
        vision = self._vision(state)
        artifacts = dict(state.get("artifacts") or {})
        aspect_map = artifacts.get("aspect_map_artifact") or {}
        if not vision or not aspect_map:
            logger.warning("[AgendaAgent] agenda inputs are incomplete.")
            return {}

        flow = vision.get("flow") or {}
        roles = vision.get("roles") or []
        entries = aspect_map.get("entries") or []
        feedback = self._feedback(state)

        try:
            item_pass: ItemPass = self.extract_structured(
                schema=ItemPass,
                system_prompt=self.profile.prompt + "\n\n" + _ITEM_PROMPT.format(
                    flow=json.dumps(flow, indent=2, ensure_ascii=False),
                    roles=json.dumps(roles, indent=2, ensure_ascii=False),
                    entries=json.dumps(entries, indent=2, ensure_ascii=False),
                ),
                user_prompt=_ITEM_USER + feedback,
                include_memory=False,
            )
        except Exception as exc:
            logger.error("[AgendaAgent] Item extraction failed: %s", exc, exc_info=True)
            return {}

        entities = flow.get("entities") or []
        items = self._sort(item_pass.items, entities)
        agenda = Agenda(
            notes=item_pass.notes,
            flow=", ".join(entity.get("name", "?") for entity in entities),
            items=items,
        )
        runtime = AgendaRuntime.from_agenda(agenda)
        dump = agenda.model_dump()

        artifacts["elicitation_agenda_artifact"] = {
            "session_id": state.get("session_id", ""),
            "created_at": datetime.now().isoformat(),
            "status": "pending_review",
            **dump,
            "summary": {
                "total": len(agenda.items),
                "needs": sum(1 for i in agenda.items if i.kind == "need"),
                "conflicts": sum(1 for i in agenda.items if i.kind == "conflict"),
                "concerns": sum(1 for i in agenda.items if i.kind == "concern"),
            },
        }

        updates: Dict[str, Any] = {
            "elicitation_agenda": runtime.model_dump(),
            "artifacts": artifacts,
        }
        if (state.get("elicitation_agenda_feedback") or "").strip():
            updates["elicitation_agenda_feedback"] = None
        return updates

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        if not artifacts.get("aspect_map_artifact"):
            return self.build_aspect_map(state)
        return self.build_agenda_items(state)
