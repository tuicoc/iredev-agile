"""
distiller_no_interview.py - Two TEST-ONLY DistillerAgent variants that
synthesise a RequirementList WITHOUT the multi-turn interview.

Why this file exists
────────────────────
The production DistillerAgent (`distiller.py`) derives requirements from
interview evidence — the lived Q&A talk the InterviewerAgent elicits. That
loop is slow and expensive, which makes iterating on the DOWNSTREAM artifacts
(requirement_list → product_backlog → acceptance criteria) painful.

These two variants skip the dialogue entirely and reason with the SAME
mechanism the production distiller uses — "what product obligations resolve
the pain points this role lived in the past" — but they read those past pain
points straight from artifacts that already exist before the interview:

  • VisionDistillerAgent       — pain points come from the Product Vision only
                                 (role needs, concerns, assumption forks).
  • VisionAgendaDistillerAgent — pain points come from the Product Vision PLUS
                                 the elicitation agenda's lived scenes
                                 (scene + frictions_to_probe + critical-incident
                                 prompt per role) — which ARE the past incidents
                                 the interview would have drilled.

Design rule honoured here (do NOT replace, only add)
─────────────────────────────────────────────────────
This module never overrides a single DistillerAgent method, so the production
interview → distiller run flow is provably untouched. It only:

  • REUSES, exactly 1-1, the parts that do not change — by calling the inherited
    methods: the Pass 2A clusterer (`_cluster`), the Pass 2B adjudicator
    (`_adjudicate`), every Python data-movement helper (`_assign_temp_ids`,
    `_apply_merge_groups`, `_assign_post_merge_ids`, `_filter_trace_refs`,
    `_drop_llm_emitted_oos`, `_ensure_vision_oos_preserved`, `_renumber_*`,
    `_compact_vision`, `_build_known_id_set`), the rate-limit retry wrappers,
    and the `Requirement` / `RequirementList` schemas + `_FOUNDATIONS`.

  • ADDS NEW passes for what changes — a new Pass 1 (its own prompt body + its
    own NEW-named methods that never shadow a parent method) plus a NEW
    orchestration entry point `build_requirement_list()`.

`distiller.py`, `graph.py`, `supervisor.py`, and `flow.py` are not modified.
Nothing here runs unless `run_iReDev.py` is invoked with
`--skip-interview-from-vision` or `--skip-interview-from-agenda`.

Why Pass 1 differs but Pass 2A/2B do not
────────────────────────────────────────
Pass 2A/2B and the Python pipeline operate on an obligation set; they are
source-agnostic, so they are reused verbatim. Only Pass 1 (the evidence source
and its prompt) is new. trace_refs cite VISION ids (ROLE-NN / ASM-NN /
CONCERN-NN), never interview turn ids — there are none — so the inherited
`_filter_trace_refs` keeps them against a vision-only known set. Agenda item ids
(IT-NNN) are context only and are not valid trace_refs, so the agenda variant
grounds obligations on the vision ids the scenes trace to.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .distiller import (
    DistillerAgent,
    MergeDecisions,
    PerspectiveExtraction,
    Requirement,
    RequirementList,
    VisionAndAdjudication,
    _FOUNDATIONS,
    _build_feedback_block,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# NEW Pass 1 prompt bodies — reframe the EVIDENCE SOURCE only.
#
# _FOUNDATIONS (inherited, reused 1-1) already defines what a requirement is,
# build-don't-transcribe, atomicity, the confidence dichotomy, AC the team can
# check, and grounded-in-cited-evidence. These bodies only re-point the evidence
# at the vision / agenda and keep the "resolve the lived pain point" mechanism.
# Purpose + guarantees only — no procedure, no magic numbers.
# ─────────────────────────────────────────────────────────────────────────────

_PASS_EXTRACT_FROM_VISION = """\
THIS PASS — OBLIGATIONS FROM ONE ROLE'S VISION-IMPLIED PAIN POINTS

You have no interview transcript. What you have is the Product Vision's account
of one role: the need that defines them, the concerns that weigh on their work,
and the assumption-forks the product still faces around them. Read these as a
description of the pain points this role lives with today — the friction,
workarounds, fear, and unmet need the product exists to remove. Your purpose is
exactly what it would be after interviewing this role: reason outward from those
pain points to the broadest honest set of distinct product obligations that
resolve them.

A concern names a pain; an obligation is the product's answer to it — the
mechanism, state, surface, recovery, or guarantee that makes the pain stop being
the role's problem. A role's need names the outcome they are trying to reach;
infer the obligations the product must carry for that outcome to actually hold,
not just the one happy-path capability. An assumption-fork the vision leans a
defensible way on is a decision you may commit to as an inferred obligation; a
fork it leaves balanced is a gap, not a guess.

Think the carve-up through in the reasoning field first, then list the
obligations. You ensure each is distinct from the others, is grounded in the
specific vision ids it cites (ROLE-NN / ASM-NN / CONCERN-NN), carries honest
confidence, and is stated so a team could build and check it. Build broadly —
overlap is expected and a later pass folds it; the only unrecoverable loss is a
real obligation never proposed. Do not fold near-duplicates here and do not emit
out_of_scope items. Where the vision raises a decision it never settles, surface
it as a gap rather than inventing the answer.
"""


_PASS_EXTRACT_FROM_AGENDA = """\
THIS PASS — OBLIGATIONS FROM ONE PERSPECTIVE'S LIVED SCENES

You have no interview transcript, but you have something close: the elicitation
agenda's scenes for this role. Each scene is a concrete past moment in their life
(a triggering event + the activity they were doing), carrying the specific
frictions an interviewer would have drilled and the critical-incident prompt that
would have opened that drilling — plus the Product Vision the scenes were drawn
from. Treat each scene and its frictions as the lived pain points the interview
would have surfaced, and reason from them exactly as you would from interview
evidence.

For each friction in a scene, infer the product obligations that resolve that
pain — the mechanism, state, surface, recovery, signal, or guarantee that means
the role no longer hits it. One scene usually implies several distinct
obligations; follow each the friction implies rather than collapsing a scene into
a single capability. Let the real density of the scenes decide how many
obligations you draw — a rich scene yields many, a thin one few — and never aim
at a number.

Think the carve-up through in the reasoning field first, then list the
obligations. The scenes give you the lived specifics, but ground each obligation
on the vision ids it traces to (ROLE-NN / ASM-NN / CONCERN-NN) — the agenda's own
item ids are context, not citable evidence. You ensure each obligation is
distinct, carries honest confidence, and is stated so a team could build and
check it. Build broadly — overlap is expected and folded later; under-proposing
is the only loss that cannot be recovered. Do not fold near-duplicates here and
do not emit out_of_scope items. Where a scene raised a decision it never settled,
surface it as a gap rather than guessing.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Shared base. Subclasses DistillerAgent ONLY to reuse its methods by calling
# them (inheritance, never override). Adds new-named passes + a new entry point.
# ─────────────────────────────────────────────────────────────────────────────

class _StaticDistillerBase(DistillerAgent):
    """A DistillerAgent whose NEW Pass 1 reads static artifacts instead of talk.

    Reuses the production distiller's persona, config, Pass 2A/2B, schemas, and
    every Python helper by inheritance (calling them). Subclasses implement only
    ``_build_pass1_results`` (build one PerspectiveExtraction per role from the
    available artifacts). No parent method is overridden, so an instance still
    runs the original interview-based ``process`` / ``_synthesise`` unchanged if
    ever called that way — the runner calls ``build_requirement_list`` instead.
    """

    # Subclasses set this so logs / artifact notes name the evidence source.
    SOURCE_LABEL: str = "static"

    # ── NEW entry point (does NOT override process / _synthesise) ──────────────
    def build_requirement_list(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesise requirement_list from the vision (+ agenda), no interview.

        Mirrors the production pipeline's shape but sources Pass 1 from static
        artifacts: NEW Pass 1 → reused Pass 2A (`_cluster`) → reused Pass 2B
        (`_adjudicate`) → reused Python assembly helpers. Returns the same update
        dict shape the production distiller returns.
        """
        artifacts = dict(state.get("artifacts") or {})
        raw_vision = (
            artifacts.get("reviewed_product_vision")
            or state.get("product_vision")
            or artifacts.get("product_vision")
            or {}
        )
        if not raw_vision:
            logger.warning(
                "[%s] No product vision present — cannot synthesise requirements.",
                type(self).__name__,
            )
            return {}

        feedback = (state.get("requirement_list_feedback") or "").strip()
        feedback_block = _build_feedback_block(feedback)
        feedback_block_2b = _build_feedback_block(feedback, include_conflict_clause=True)

        compact_vision = self._compact_vision(raw_vision)

        # ── NEW Pass 1: per-role assembly from static artifacts ────────
        perspective_results, perspective_notes, map_failures = self._build_pass1_results(
            state, raw_vision, compact_vision, feedback_block
        )

        # Assign T-NNN temp ids in Pass 1 order (reused helper; mutates item.id).
        pass1_items_in_order = self._assign_temp_ids(perspective_results)
        pass1_item_count = len(pass1_items_in_order)

        perspective_extractions: List[Dict[str, Any]] = []
        for persp, batch in perspective_results:
            perspective_extractions.append({
                "perspective": persp,
                "record_ids": [],
                "notes": batch.notes,
                "items": [item.model_dump() for item in (batch.items or [])],
                "gaps": list(batch.gaps or []),
                "conflicts": [c.model_dump() for c in (batch.conflicts or [])],
            })

        # ── Pass 2A (cluster) — REUSED 1-1 via inherited _cluster ──────
        cluster_result: Optional[MergeDecisions] = None
        adjudicate_result: Optional[VisionAndAdjudication] = None
        pass2_failures: List[str] = []
        try:
            cluster_result = self._cluster(
                compact_vision, perspective_extractions, feedback_block
            )
            if cluster_result and (cluster_result.reasoning or "").strip():
                logger.info(
                    "[%s] Pass 2A reasoning:\n%s",
                    type(self).__name__, cluster_result.reasoning.strip(),
                )
        except Exception as exc:
            logger.error(
                "[%s] Pass 2A (cluster) failed: %s", type(self).__name__, exc,
                exc_info=True,
            )
            pass2_failures.append(f"Pass 2A (cluster): {exc}")

        merge_groups = (cluster_result.merge_groups if cluster_result else []) or []
        merged_items, unknown_temp_ids, applied_groups = self._apply_merge_groups(
            pass1_items_in_order, merge_groups,
        )
        if unknown_temp_ids:
            logger.info(
                "[%s] Pass 2A referenced %d unknown temp id(s): %s",
                type(self).__name__, len(unknown_temp_ids), ", ".join(unknown_temp_ids[:8]),
            )

        self._assign_post_merge_ids(merged_items)

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
                (it for it in merged_items if (it.id or "").startswith("M-")),
                merge_groups,
            )
        ]

        # ── Pass 2B (adjudicate) — REUSED 1-1 via inherited _adjudicate ─
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
                "[%s] Pass 2B (adjudicate) failed: %s", type(self).__name__, exc,
                exc_info=True,
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

        # Known ids for the no-interview path = vision ids only (no turn ids exist).
        known_ids = self._build_known_id_set(compact_vision, [])
        dropped_refs = self._filter_trace_refs(final_items, known_ids)
        if dropped_refs:
            logger.info(
                "[%s] Dropped %d trace_ref entries with unknown ids.",
                type(self).__name__, dropped_refs,
            )

        llm_oos_dropped = self._drop_llm_emitted_oos(final_items)
        if llm_oos_dropped:
            logger.info(
                "[%s] Dropped %d LLM-emitted out_of_scope item(s); vision scope is "
                "handled by Python.",
                type(self).__name__, llm_oos_dropped,
            )

        vision_oos_added = self._ensure_vision_oos_preserved(final_items, raw_vision)
        if vision_oos_added:
            logger.info(
                "[%s] Preserved %d vision scope item(s) as out_of_scope.",
                type(self).__name__, vision_oos_added,
            )

        final_items = self._renumber_requirements(final_items)
        final_conflicts = self._renumber_conflicts(final_conflicts)

        for item in final_items:
            icon = "✓" if item.confidence == "confirmed" else "~"
            logger.info(
                "[%s]   %s [%s] (%s) %s",
                type(self).__name__, icon, item.id, item.type,
                (item.statement or "")[:100],
            )

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
            f"{applied_groups}; items folded: {pass1_item_count - len(merged_items)}"
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
                f"SYNTHESISED WITHOUT INTERVIEW — source: {self.SOURCE_LABEL}\n\n"
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
            "source": f"no_interview:{self.SOURCE_LABEL}",
            **final.model_dump(),
            "status": "pending_conflicts" if final.conflicts else "pending_review",
        }

        return {
            "artifacts": artifacts,
            "interview_complete": True,
            "_needs_srs_synthesis": False,
            "requirement_list_feedback": None,
        }

    # ── NEW Pass 1 hook (subclass-provided) ────────────────────────────────────
    def _build_pass1_results(
        self,
        state: Dict[str, Any],
        raw_vision: Dict[str, Any],
        compact_vision: Dict[str, Any],
        feedback_block: str,
    ) -> Tuple[List[Tuple[str, PerspectiveExtraction]], List[str], List[str]]:
        """Return (perspective_results, perspective_notes, map_failures)."""
        raise NotImplementedError

    # ── NEW Pass 1 driver (NEW names — never shadow _arun_pass1 / _aextract_*) ──
    async def _aextract_static_perspective(
        self,
        perspective: str,
        evidence_payload: Dict[str, Any],
        compact_vision: Dict[str, Any],
        pass_body: str,
        feedback_block: str,
    ) -> PerspectiveExtraction:
        """One NEW Pass 1 call for one role's static evidence corpus."""
        label = f"{self.SOURCE_LABEL} extract {perspective}"

        async def _call() -> PerspectiveExtraction:
            return await self.aextract_structured(
                schema=PerspectiveExtraction,
                system_prompt=(
                    self.profile.prompt
                    + "\n\n" + _FOUNDATIONS
                    + "\n\n" + pass_body
                    + feedback_block
                ),
                user_prompt=(
                    f"COMPACT PRODUCT VISION:\n{self._json(compact_vision)}\n\n"
                    f"FOCUS PERSPECTIVE EVIDENCE (the role and the past pain points "
                    f"to resolve):\n{self._json(evidence_payload)}\n\n"
                    "Return a PerspectiveExtraction whose perspective equals this "
                    "role. Build the broadest set of distinct product obligations "
                    "these pain points imply, each grounded in the vision ids it "
                    "cites (ROLE-NN / ASM-NN / CONCERN-NN). Do not fold near-"
                    "duplicates and do not emit out_of_scope items."
                ),
                include_memory=False,
            )

        return await self._a_with_rate_limit_retry(label, _call)

    async def _arun_static_pass1(
        self,
        batches: List[Tuple[str, Dict[str, Any]]],
        compact_vision: Dict[str, Any],
        pass_body: str,
        feedback_block: str,
    ) -> List[Tuple[str, Any]]:
        """Drive every per-role batch concurrently, capped by ``_max_parallel``."""
        semaphore = asyncio.Semaphore(self._max_parallel)

        async def _bounded(persp: str, payload: Dict[str, Any]) -> PerspectiveExtraction:
            async with semaphore:
                return await self._aextract_static_perspective(
                    persp, payload, compact_vision, pass_body, feedback_block
                )

        persps = [persp for persp, _payload in batches]
        coros = [_bounded(persp, payload) for persp, payload in batches]
        results = await asyncio.gather(*coros, return_exceptions=True)
        return list(zip(persps, results))

    def _run_static_pass1_batches(
        self,
        batches: List[Tuple[str, Dict[str, Any]]],
        compact_vision: Dict[str, Any],
        pass_body: str,
        feedback_block: str,
    ) -> Tuple[List[Tuple[str, PerspectiveExtraction]], List[str], List[str]]:
        """Run all batches and split successes from failures."""
        perspective_results: List[Tuple[str, PerspectiveExtraction]] = []
        perspective_notes: List[str] = []
        map_failures: List[str] = []

        if not batches:
            return perspective_results, perspective_notes, map_failures

        results = asyncio.run(
            self._arun_static_pass1(batches, compact_vision, pass_body, feedback_block)
        )
        for persp, batch_or_exc in results:
            if isinstance(batch_or_exc, BaseException):
                logger.warning(
                    "[%s] Pass 1 batch failed for perspective '%s': %s",
                    type(self).__name__, persp, batch_or_exc,
                )
                map_failures.append(f"perspective '{persp}': {batch_or_exc}")
                continue
            batch = batch_or_exc
            if (batch.reasoning or "").strip():
                logger.info(
                    "[%s] Pass 1 reasoning [%s]:\n%s",
                    type(self).__name__, persp, batch.reasoning.strip(),
                )
            if (batch.notes or "").strip():
                perspective_notes.append(f"[{persp}] {batch.notes.strip()}")
            perspective_results.append((persp, batch))

        return perspective_results, perspective_notes, map_failures

    # ── Shared evidence helper (NEW) ────────────────────────────────────────────
    @staticmethod
    def _concerns_for_role(
        concerns: List[Dict[str, Any]], role: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Concerns that name this role in affected_roles (by id or name).

        A concern with no affected_roles is product-wide and applies to every
        role. Matching tolerates affected_roles holding role ids or role names.
        """
        rid = str(role.get("id") or "").strip()
        rname = str(role.get("name") or "").strip()
        out: List[Dict[str, Any]] = []
        for concern in concerns:
            affected = [str(a).strip() for a in (concern.get("affected_roles") or [])]
            if not affected or (rid and rid in affected) or (rname and rname in affected):
                out.append(concern)
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Variant 1 — requirements from the Product Vision only.
# ─────────────────────────────────────────────────────────────────────────────

class VisionDistillerAgent(_StaticDistillerBase):
    """Synthesise a RequirementList from the Product Vision alone (no agenda, no
    interview). Pain points per role come from the role's need, the concerns that
    affect it, and the product-wide assumption forks.
    """

    SOURCE_LABEL = "product_vision"

    def _build_pass1_results(self, state, raw_vision, compact_vision, feedback_block):
        roles = raw_vision.get("roles") or []
        concerns = raw_vision.get("concerns") or []
        assumptions = raw_vision.get("assumptions") or []
        scope = raw_vision.get("scope") or []

        batches: List[Tuple[str, Dict[str, Any]]] = []
        for role in roles:
            rname = str(role.get("name") or "").strip() or str(role.get("id") or "role")
            payload = {
                "perspective": rname,
                "role": {
                    "id": role.get("id"),
                    "name": role.get("name"),
                    "need": role.get("need"),
                    "anchor": role.get("anchor"),
                },
                "pain_points_from_concerns": self._concerns_for_role(concerns, role),
                "forks_from_assumptions": assumptions,
                "boundaries": scope,
            }
            batches.append((rname, payload))

        # No roles named in the vision — fall back to one product-wide batch so
        # the vision's concerns/assumptions still produce obligations.
        if not batches:
            batches.append((
                "(product-wide)",
                {
                    "perspective": "(product-wide)",
                    "role": None,
                    "pain_points_from_concerns": concerns,
                    "forks_from_assumptions": assumptions,
                    "boundaries": scope,
                },
            ))

        return self._run_static_pass1_batches(
            batches, compact_vision, _PASS_EXTRACT_FROM_VISION, feedback_block
        )


# ─────────────────────────────────────────────────────────────────────────────
# Variant 2 — requirements from the Product Vision + elicitation agenda.
# ─────────────────────────────────────────────────────────────────────────────

class VisionAgendaDistillerAgent(_StaticDistillerBase):
    """Synthesise a RequirementList from the Product Vision PLUS the elicitation
    agenda (no interview). Pain points per role come from the agenda's lived
    scenes (scene + frictions_to_probe + critical-incident prompt) grounded on the
    role's vision concerns and assumption forks.
    """

    SOURCE_LABEL = "vision+agenda"

    def _build_pass1_results(self, state, raw_vision, compact_vision, feedback_block):
        artifacts = state.get("artifacts") or {}
        agenda = (
            artifacts.get("reviewed_elicitation_agenda")
            or artifacts.get("elicitation_agenda_artifact")
            or {}
        )
        items = agenda.get("items") or []

        # No agenda content — degrade gracefully to the vision-only batches so the
        # run still produces a list rather than failing.
        if not items:
            logger.warning(
                "[VisionAgendaDistillerAgent] Agenda has no items; falling back to "
                "vision-only pain points."
            )
            return VisionDistillerAgent._build_pass1_results(
                self, state, raw_vision, compact_vision, feedback_block
            )

        roles = raw_vision.get("roles") or []
        roles_by_name = {
            str(r.get("name") or "").strip(): r for r in roles if r.get("name")
        }
        concerns = raw_vision.get("concerns") or []
        assumptions = raw_vision.get("assumptions") or []
        scope = raw_vision.get("scope") or []

        # Group agenda scenes by their perspective (role).
        scenes_by_perspective: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            persp = str(item.get("perspective") or "").strip() or "(unknown)"
            scenes_by_perspective.setdefault(persp, []).append(item)

        batches: List[Tuple[str, Dict[str, Any]]] = []
        for persp, persp_items in scenes_by_perspective.items():
            role = roles_by_name.get(persp)
            payload = {
                "perspective": persp,
                "role": (
                    {
                        "id": role.get("id"),
                        "name": role.get("name"),
                        "need": role.get("need"),
                        "anchor": role.get("anchor"),
                    }
                    if role else None
                ),
                "lived_scenes": [
                    {
                        "id": it.get("id"),
                        "scene": it.get("scene"),
                        "frictions_to_probe": list(it.get("frictions_to_probe") or []),
                        "critical_incident_prompt": it.get("critical_incident_prompt"),
                    }
                    for it in persp_items
                ],
                "pain_points_from_concerns": (
                    self._concerns_for_role(concerns, role) if role else concerns
                ),
                "forks_from_assumptions": assumptions,
                "boundaries": scope,
            }
            batches.append((persp, payload))

        return self._run_static_pass1_batches(
            batches, compact_vision, _PASS_EXTRACT_FROM_AGENDA, feedback_block
        )
