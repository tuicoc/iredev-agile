"""
interviewer.py - InterviewerAgent

InterviewerAgent runs the reviewed agenda one item at a time. The model chooses
conversational moves through tools; Python records the chosen action, updates
runtime data, and writes the interview_record artifact.

Design split
------------
Tool descriptions name what each tool does and its signature — they exist so
the model can pick the right tool. They do not teach how to think.
The ReAct addendum prompt teaches the thinking: turn control, question craft,
and closure judgment.
Persona text holds the agent's stable stance only.
Python only normalizes inputs, advances runtime, and writes the artifact.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from .agenda import AgendaRuntime
from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


CoverageStatus = Literal["covered", "covered_by_prior", "gap", "skipped"]
AssumptionStance = Literal["supports", "weakens", "qualifies", "unclear"]


# Words too generic to count toward prior-coverage detection. Keep short,
# domain-neutral; the goal is to filter glue words, not domain vocabulary.
_PRIOR_MATCH_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "your", "what", "when", "where",
    "from", "about", "have", "they", "their", "them", "into", "would", "could",
    "should", "been", "being", "than", "then", "some", "such", "much", "many",
    "only", "very", "also", "just", "more", "most", "make", "made", "make",
    "take", "took", "give", "gave", "want", "wanted", "tell", "told", "feel",
    "feels", "felt", "find", "found", "needs", "need", "needed", "still",
    "even", "every", "each", "while", "after", "before", "between", "above",
    "below", "during", "until", "without", "within", "across", "though",
    "because", "however", "though", "rather",
}


def _significant_words(text: str) -> List[str]:
    """Lowercase tokens >3 chars that are not glue words. Used by prior-match heuristic."""
    return [
        token
        for token in re.findall(r"[a-z][a-z0-9\-]+", (text or "").lower())
        if len(token) > 3 and token not in _PRIOR_MATCH_STOPWORDS
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Artifact pieces
# ─────────────────────────────────────────────────────────────────────────────

class CoverageEntry(BaseModel):
    point: str = Field(description="Agenda coverage point being judged.")
    status: CoverageStatus = Field(description="covered when the stakeholder's CURRENT answer settled the point. covered_by_prior when an episode from the SAME perspective in a prior agenda item already settled the same lived ground (no new question needed). gap when probed but not settled. skipped when prior evidence or item scope makes more probing unnecessary.")
    evidence: str = Field(description="Brief evidence text: stakeholder fact for covered; cited prior-episode trigger+decision for covered_by_prior; failed probe reason for gap; prior-evidence or scope reason for skipped. Required for every entry.")


class AssumptionEvidenceEntry(BaseModel):
    vision_ref: str = Field(description="Vision id (assumption, concern, or scope) this evidence speaks to. Must come from the current item's vision_refs.")
    stance: AssumptionStance = Field(description="How the evidence affects the referenced vision element: supports (aligns), weakens (contradicts), qualifies (true only under a condition/subset/boundary), unclear (role could not settle it).")
    evidence: str = Field(description="Brief stakeholder fact from the dialogue. Do not invent; cite what the role actually said.")
    implication: str = Field(description="What this evidence may change downstream: requirement, quality expectation, boundary, conflict, gap, or first-release note.")


class ELRecord(BaseModel):
    id: str = Field(description="Stable interview record id in EL-NNN format.")
    item: str = Field(description="Agenda item id (IT-NNN) that produced this record.")
    perspective: str = Field(description="Role perspective interviewed.")
    scene: str = Field(description="Lived scene the agenda item described.")
    close_when: str = Field(description="Stop condition used by the interviewer.")
    frictions_to_probe: List[str] = Field(default_factory=list, description="Frictions the agenda item asked the interviewer to drill.")
    coverage: List[CoverageEntry] = Field(default_factory=list, description="Per-friction verdict.")
    assumption_evidence: List[AssumptionEvidenceEntry] = Field(default_factory=list, description="Evidence about each vision assumption the answer touched.")
    gaps: List[str] = Field(default_factory=list, description="Frictions drilled but unresolved.")
    rule: Optional[str] = Field(default=None, description="Closure summary when the item settled.")
    talk: List[Dict[str, Any]] = Field(default_factory=list, description="Question/answer turns captured.")
    status: Literal["answered", "partial", "skipped"] = Field(description="Final interview status.")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt addendum — taught thinking
# ─────────────────────────────────────────────────────────────────────────────

_REACT_ADDENDUM = """\
TURN CONTROL
- Inspect TURN STATUS first.
- If Pending answer: yes → call record_answer.
- If Pending answer: no and AGENDA STATUS: OPEN → call ask_question
  (or call record_answer with done=true for a saturation close once
  the minimum-evidence budget has been met).
- If AGENDA STATUS: COMPLETE → call conclude.
- One tool call per turn. Closing one item does not complete the
  interview; the orchestrator advances you to the next item.


YOUR JOB

You are running a CRITICAL-INCIDENT INTERVIEW. The agenda gives
you a scene + a list of frictions worth landing in evidence.
Your job: invite the role to recount a specific past incident,
drill that incident until each friction has a concrete moment
on record, then close. The stakeholder is reactive — they only
answer. YOU decide what to ask, when to drill, when to pivot,
when to close.


HOW TO PICK THE NEXT QUESTION — READ THE CONTEXT YOU HAVE

You have two memory channels right now:

- CURRENT DIALOGUE THIS SCENE — every question you have asked
  and every answer the role has given inside this item.
- PRIOR EPISODES — what THIS perspective already settled in
  earlier items (recorded by the orchestrator when each item
  closed).

Before drafting your next question, read both. The question
that earns a turn is the one that would surface evidence NOT
YET ON RECORD — a new lived detail, a workaround the role
mentioned but left vague, a friction the agenda named that the
dialogue has not yet drilled, a consequence the role has not
yet described. A question that re-asks an angle the prior
turns already covered, in slightly different words, produces
paraphrase — wasted budget.

If the role has named a workaround / manual fix / informal
fallback and you have not yet drilled it, the workaround IS
the next question. Workarounds are the fingerprint of an unmet
capability and carry the richest evidence — do not pivot to a
different friction while the workaround is still vague.

The first turn of each item opens with the agenda's
critical_incident_prompt (verbatim or lightly adapted to read
naturally). It is meant to bring one specific past incident
into the conversation. Subsequent turns stay inside that
incident — the role's continuity rule keeps them there — and
probe new angles on it.


HOW TO PHRASE THE QUESTION

One question per turn. Open. Concrete. Past tense. No multi-
part. No thanks / recap / praise at the start. Refuse to ask
anything that asks the role to evaluate a proposed product,
imagine future use, or describe a general pattern without a
concrete incident anchor — those framings produce hypothetical
or aggregated answers that downstream synthesis cannot lift.

Do not lift question phrasings from a template. Let the
question emerge from what the role's most recent answer puts
on the table; a question that does not fit the answer in front
of you fails even if it is well-phrased in the abstract.


FRICTION COVERAGE

The agenda's `frictions_to_probe` is a checklist of what should
land in evidence before you close — not a serial walk. Move
through frictions in the order the dialogue invites; when an
answer surfaces a friction further down the list, follow it;
when the role surfaces a friction the agenda did not list,
drill it too.

A friction is COMPLETE in the coverage list when:
  - covered — the dialogue put a specific past incident on
    record (what the role did, what happened, one consequence);
  - covered_by_prior — a prior episode (PRIOR EPISODES section)
    already settled this friction; cite the prior episode in
    `evidence`;
  - gap — you drilled the friction and the role could not give
    a concrete incident (declined / no recall / no longer
    encounters); name the failed drill;
  - skipped — the friction is genuinely subsumed by another
    covered friction in this same item; name the subsuming
    friction.

No friction without a verdict before close. Skipping silently
because you did not drill is a defect — explicit gap is the
honest record.


CLOSURE — EVIDENCE SATURATION

Close when evidence has saturated, not when a turn count has
been hit. Saturation = the last two answers stopped surfacing
lived detail you would write down; the next question you can
think to ask is a rephrase of an earlier one. When you reach
that state, close via record_answer with done=true:

- If a pending answer is in hand, that is the standard close.
- If no fresh answer is pending and the minimum-evidence
  budget is met, the orchestrator allows a SATURATION CLOSE:
  call record_answer with done=true bringing the coverage and
  assumption_evidence already grounded in the turns recorded.

Do not close prematurely (a friction is still vague, a
workaround is still un-drilled, a new lived detail surfaced in
the last answer). Do not pad with hollow questions either —
hollow re-asks are the saturation signal; act on it.

For each vision assumption the dialogue touched, record one
AssumptionEvidenceEntry (stance + evidence + implication).
"""


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class InterviewerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="interviewer")
        custom = (
            self._raw_config.get("iredev", {})
            .get("agents", {})
            .get("interviewer", {})
            .get("custom_params", {})
        )
        self._max_turns_per_item = int(custom.get("max_turns_per_item", 5) or 5)
        min_turns = int(custom.get("min_turns_per_assumption_item", 2) or 2)
        self._min_turns_per_assumption_item = max(1, min(min_turns, self._max_turns_per_item))

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="record_answer",
            description=(
                "Persist the closure decision for the current agenda item: "
                "judge friction coverage, record vision-assumption evidence, "
                "and either keep the item open (done=false) or close it "
                "(done=true). The raw Q/A talk is already appended to the "
                "runtime item by the orchestrator; downstream synthesis "
                "(distiller) reads the talk turns directly, so this tool "
                "does not take a separate signals payload.\n\n"
                "Use in three situations:\n"
                "  - Pending answer: yes — judge whether the answer "
                "saturates the frictions; set done=true to close or "
                "done=false to keep drilling.\n"
                "  - Prior-coverage short-circuit — every friction is "
                "already settled by an earlier item with the same "
                "perspective; close with done=true and every friction "
                "marked covered_by_prior citing the prior episode.\n"
                "  - Saturation close — the minimum-evidence budget is "
                "met and recent turns have stopped surfacing new lived "
                "detail; close with done=true even without a fresh "
                "pending answer.\n\n"
                "Arguments:\n"
                "  done (bool, required): close the item when meaningfully "
                "covered.\n"
                "  rule (str): closure summary capturing what the item "
                "settled; empty when closing on gaps only.\n"
                "  assumption_evidence (list[dict]): each entry is "
                "{vision_ref, stance, evidence, implication}; stance is "
                "supports | weakens | qualifies | unclear.\n"
                "  coverage (list[dict]): each entry is "
                "{point, status, evidence}; status is covered | "
                "covered_by_prior | gap | skipped.\n"
                "  gaps (list[str]): drilled-but-unresolved frictions.\n"
                'Input: {"done": bool, "rule": str, '
                '"assumption_evidence": list, "coverage": list, '
                '"gaps": list}'
            ),
            func=self._tool_record_answer,
        ))
        self.register_tool(Tool(
            name="ask_question",
            description=(
                "Deliver exactly one open question to the current stakeholder "
                "for the current agenda item.\n\n"
                "Use when TURN STATUS says Pending answer: no and "
                "AGENDA STATUS: OPEN.\n\n"
                "Arguments:\n"
                "  message (str, required): one open question.\n"
                'Input: {"message": str}'
            ),
            func=self._tool_ask_question,
        ))
        self.register_tool(Tool(
            name="conclude",
            description=(
                "Compile the interview_record artifact across the whole agenda.\n\n"
                "Hard precondition: call only when AGENDA STATUS: COMPLETE.\n"
                "Input: {}"
            ),
            func=self._tool_conclude,
        ))

    # ── Normalization helpers (no product logic) ─────────────────────────────

    @staticmethod
    def _normalize_coverage(
        raw_coverage: Optional[List[Any]],
    ) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        allowed = {"covered", "covered_by_prior", "gap", "skipped"}
        for raw in raw_coverage or []:
            if not isinstance(raw, dict):
                continue
            point = str(raw.get("point") or "").strip()
            status = str(raw.get("status") or "").strip().lower()
            evidence = str(raw.get("evidence") or "").strip()
            if not point or status not in allowed or not evidence:
                continue
            normalized.append({
                "point": point,
                "status": status,
                "evidence": evidence,
            })
        return normalized

    @staticmethod
    def _merge_coverage(
        existing: Optional[List[Dict[str, Any]]],
        incoming: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        merged: Dict[str, Dict[str, str]] = {}
        for raw in existing or []:
            if not isinstance(raw, dict):
                continue
            point = str(raw.get("point") or "").strip()
            status = str(raw.get("status") or "").strip().lower()
            evidence = str(raw.get("evidence") or "").strip()
            if point and status:
                merged[point.lower()] = {
                    "point": point,
                    "status": status,
                    "evidence": evidence,
                }
        for entry in incoming:
            merged[entry["point"].lower()] = entry
        return list(merged.values())

    @staticmethod
    def _normalize_assumption_evidence(
        raw_entries: Optional[List[Any]],
        allowed_refs: Optional[List[str]],
    ) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        allowed_stances = {"supports", "weakens", "qualifies", "unclear"}
        allowed = {str(ref or "").strip() for ref in allowed_refs or [] if str(ref or "").strip()}
        for raw in raw_entries or []:
            if not isinstance(raw, dict):
                continue
            ref = str(raw.get("vision_ref") or raw.get("assumption_ref") or "").strip()
            stance = str(raw.get("stance") or "").strip().lower()
            evidence = str(raw.get("evidence") or "").strip()
            implication = str(raw.get("implication") or "").strip()
            if not ref or stance not in allowed_stances or not evidence or not implication:
                continue
            if allowed and ref not in allowed:
                continue
            normalized.append({
                "vision_ref": ref,
                "stance": stance,
                "evidence": evidence,
                "implication": implication,
            })
        return normalized

    @staticmethod
    def _merge_assumption_evidence(
        existing: Optional[List[Dict[str, Any]]],
        incoming: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        merged: List[Dict[str, str]] = []
        seen = set()
        for raw in list(existing or []) + incoming:
            if not isinstance(raw, dict):
                continue
            ref = str(raw.get("vision_ref") or raw.get("assumption_ref") or "").strip()
            stance = str(raw.get("stance") or "").strip().lower()
            evidence = str(raw.get("evidence") or "").strip()
            implication = str(raw.get("implication") or "").strip()
            key = (ref.lower(), stance, evidence.rstrip(".").lower(), implication.rstrip(".").lower())
            if not ref or not stance or not evidence or not implication or key in seen:
                continue
            seen.add(key)
            merged.append({
                "vision_ref": ref,
                "stance": stance,
                "evidence": evidence,
                "implication": implication,
            })
        return merged

    @staticmethod
    def _append_unique_text(existing: Optional[List[str]], incoming: List[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for text in list(existing or []) + list(incoming or []):
            value = str(text or "").strip()
            key = value.rstrip(".").lower()
            if not value or key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result

    @staticmethod
    def _coverage_complete(
        coverage_points: Optional[List[str]],
        coverage: Optional[List[Dict[str, Any]]],
    ) -> bool:
        points = [point.strip() for point in coverage_points or [] if point.strip()]
        if not points:
            return False
        settled = {
            str(entry.get("point") or "").strip().lower()
            for entry in coverage or []
            if (
                str(entry.get("status") or "").strip().lower()
                in {"covered", "covered_by_prior", "gap", "skipped"}
                and str(entry.get("evidence") or "").strip()
            )
        }
        return all(point.lower() in settled for point in points)

    @staticmethod
    def _has_meaningful_coverage(
        coverage: Optional[List[Dict[str, Any]]],
    ) -> bool:
        return any(
            str(entry.get("status") or "").strip().lower()
            in {"covered", "covered_by_prior"}
            and str(entry.get("evidence") or "").strip()
            for entry in coverage or []
        )

    @staticmethod
    def _all_covered_by_prior(
        coverage_points: Optional[List[str]],
        coverage: Optional[List[Dict[str, Any]]],
    ) -> bool:
        points = [point.strip().lower() for point in coverage_points or [] if point.strip()]
        if not points:
            return False
        prior_settled = {
            str(entry.get("point") or "").strip().lower()
            for entry in coverage or []
            if str(entry.get("status") or "").strip().lower() == "covered_by_prior"
            and str(entry.get("evidence") or "").strip()
        }
        return all(point in prior_settled for point in points)

    def _min_turns_for_item(self, item: Any) -> int:
        # Single config-controlled minimum. The earlier vision_refs special
        # case is obsolete now that agenda items do not carry typed refs.
        return self._min_turns_per_assumption_item

    # ── Episodic memory helpers ─────────────────────────────────────────────
    #
    # Each closed item produces one Episode keyed by the role perspective.
    # When a later item opens with the same perspective, we recall those
    # episodes so the interviewer can mark coverage_points already settled by
    # a prior episode as covered_by_prior — saving a turn while preserving
    # the audit trail.

    def _prior_episodes(self, perspective: str) -> List[Dict[str, Any]]:
        if not perspective or self.memory is None:
            return []
        try:
            return self.memory.recall_episodes(entity_id=perspective, limit=30)
        except Exception as exc:
            logger.warning(
                "[InterviewerAgent] recall_episodes failed for %r: %s",
                perspective, exc,
            )
            return []

    def _record_item_episode(self, item: Any, closed_via_prior: bool = False) -> None:
        if self.memory is None:
            return
        perspective = (getattr(item, "perspective", "") or "").strip()
        if not perspective:
            return
        # Episode trigger is the lived scene; decision is the closure rule
        # the interviewer summarised. Talk turns themselves live on the
        # runtime item; episodic memory carries the headline only.
        decision = (getattr(item, "rule", "") or "").strip()
        outcome_label = "closed_from_prior" if closed_via_prior else (
            getattr(item, "status", "") or "answered"
        )
        try:
            self.memory.record_episode(
                entity_id=perspective,
                trigger=(
                    f"item {getattr(item, 'id', '')}: "
                    f"{getattr(item, 'scene', '') or '(no scene)'}"
                ),
                decision=decision or "(no rule captured)",
                outcome=f"{outcome_label}: {decision or '(no rule)'}",
            )
        except Exception as exc:
            logger.warning(
                "[InterviewerAgent] record_episode failed for %r: %s",
                perspective, exc,
            )

    @staticmethod
    def _suggest_covered_by_prior(
        coverage_points: List[str],
        prior_episodes: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """Heuristic: suggest which coverage_points have a prior episode worth checking.

        Bag-of-significant-words overlap between each coverage_point and the
        union of every episode's trigger + decision. A point is suggested
        when ≥2 distinct significant words overlap with the BEST matching
        episode (different sentences naming the same product object or
        same activity tend to share at least two anchor nouns even with
        different framing).

        Deliberately permissive — this is only a SUGGESTION layer. The
        interviewer must still read the prior episode and current
        coverage_point and judge whether the prior actually settles the
        same lived ground before marking covered_by_prior. False positives
        are recoverable (interviewer probes anyway); false negatives are
        not (silent duplicate work).
        """
        if not coverage_points or not prior_episodes:
            return []
        episode_bags: List[Tuple[Dict[str, Any], set]] = []
        for ep in prior_episodes:
            blob = f"{ep.get('trigger', '')} {ep.get('decision', '')}"
            episode_bags.append((ep, set(_significant_words(blob))))
        suggestions: List[Dict[str, str]] = []
        for cp in coverage_points:
            cp_words = _significant_words(cp)
            if not cp_words:
                continue
            best_ep = None
            best_overlap: List[str] = []
            for ep, bag in episode_bags:
                overlap = [w for w in cp_words if w in bag]
                if len(overlap) > len(best_overlap):
                    best_overlap = overlap
                    best_ep = ep
            if best_ep is None or len(best_overlap) < 2:
                continue
            suggestions.append({
                "point": cp,
                "evidence_hint": (
                    f"prior episode (trigger: {best_ep.get('trigger', '')[:120]}…) "
                    f"already settled: {best_ep.get('decision', '')[:200]}"
                ),
                "matched_words": ", ".join(best_overlap),
            })
        return suggestions

    @staticmethod
    def _strong_match(cp: str, episode_blob: str) -> bool:
        """A coverage_point is strongly matched by an episode blob when the
        overlap covers at least half of the coverage_point's significant words
        (with a floor of 3 words). Used for the auto-skip ROUTING decision —
        deliberately stricter than the suggestion heuristic so false positives
        do not trap process() in a record_answer loop the LLM cannot exit.
        """
        cp_words = _significant_words(cp)
        if len(cp_words) < 3:
            return False
        bag = set(_significant_words(episode_blob))
        overlap = sum(1 for w in cp_words if w in bag)
        return overlap >= max(3, (len(cp_words) + 1) // 2)

    def _prior_coverage_analysis(
        self,
        item: Any,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]], bool]:
        """Return (episodes, suggestions, fully_covered_by_prior).

        - suggestions: lenient (≥2 word overlap) — surfaced in the task as
          hints; the LLM judges per point whether to mark covered_by_prior.
        - fully_covered_by_prior: STRICT — every coverage_point has at least
          one prior episode that strongly matches it (≥50% overlap, floor 3
          words). Triggers the auto-skip route in process(); rarely fires but
          when it does the EndUser would almost certainly retell the same
          scene, so the skip is safe.
        """
        perspective = (getattr(item, "perspective", "") or "").strip()
        coverage_points = list(getattr(item, "frictions_to_probe", []) or [])
        episodes = self._prior_episodes(perspective)
        if not coverage_points or not episodes:
            return episodes, [], False
        suggestions = self._suggest_covered_by_prior(coverage_points, episodes)
        # Strong-match check for routing: every point must have at least one
        # episode whose trigger+decision strongly matches it.
        fully = True
        for cp in coverage_points:
            if not any(
                self._strong_match(cp, f"{ep.get('trigger', '')} {ep.get('decision', '')}")
                for ep in episodes
            ):
                fully = False
                break
        return episodes, suggestions, fully

    # ── Tools ────────────────────────────────────────────────────────────────

    def _tool_record_answer(
        self,
        done: bool = False,
        rule: str = "",
        assumption_evidence: Optional[List[Any]] = None,
        coverage: Optional[List[Any]] = None,
        gaps: Optional[List[str]] = None,
        state: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> ToolResult:
        state = state or {}
        answer = (state.get("enduser_answer") or "").strip()
        normalized_coverage_preview = self._normalize_coverage(coverage)
        coverage_points_preview: List[str] = []
        turns_recorded_preview = 0
        min_turns_preview = self._min_turns_per_assumption_item
        runtime_preview = self._load_runtime(state)
        if runtime_preview is not None:
            current_preview = runtime_preview.current_item()
            if current_preview is not None:
                coverage_points_preview = list(
                    getattr(current_preview, "frictions_to_probe", []) or []
                )
                turns_recorded_preview = len(
                    getattr(current_preview, "talk", []) or []
                )
                min_turns_preview = self._min_turns_for_item(current_preview)
        skip_via_prior = bool(
            not answer
            and done
            and coverage_points_preview
            and self._all_covered_by_prior(coverage_points_preview, normalized_coverage_preview)
        )
        # Saturation close: model has heard enough on this scene and
        # closes by calling record_answer with done=true even though no
        # fresh answer is pending. Allowed once min_turns for the item
        # is met and the model brings meaningful evidence (coverage or
        # assumption_evidence) so closure is grounded.
        saturation_close = bool(
            not answer
            and done
            and not skip_via_prior
            and turns_recorded_preview >= min_turns_preview
            and (
                normalized_coverage_preview
                or (assumption_evidence or [])
            )
        )
        if not answer and not (skip_via_prior or saturation_close):
            # No fresh answer is pending and the call did not satisfy a
            # closure path. End this turn cleanly; the next turn falls
            # through to ask_question because _disabled_prior_skip
            # blocks process() from re-routing.
            return ToolResult(
                observation=(
                    "[record_answer] Pending answer is empty and the call "
                    "did not satisfy a closure path (no covered_by_prior "
                    "marks, and either min_turns not yet met or no "
                    "meaningful coverage / evidence supplied). Reverting "
                    "to ask_question on the next turn."
                ),
                state_updates={"_disabled_prior_skip": True},
                should_return=True,
            )

        runtime = self._load_runtime(state)
        if runtime is None:
            return ToolResult(
                observation="[record_answer] Agenda runtime is missing.",
                is_error=True,
                should_return=True,
            )

        item = runtime.current_item()
        if item is None:
            return ToolResult(
                observation="[record_answer] Agenda already complete.",
                should_return=True,
            )

        if answer:
            item.answer = answer
            item.talk.append({
                "question": item.question or "",
                "answer": answer,
                "recorded_at": datetime.now().isoformat(),
            })
        elif skip_via_prior:
            # No question was asked because prior episodes already cover every
            # point. Record a synthetic talk entry so the audit trail shows the
            # item closed via prior-episode short-circuit rather than silent
            # omission.
            item.talk.append({
                "question": "(no question asked — closed from prior episodes)",
                "answer": "(no answer; coverage cited from prior items with same perspective)",
                "recorded_at": datetime.now().isoformat(),
            })
        elif saturation_close:
            # No new question was asked because the model judged the scene
            # had reached evidence saturation. Record a synthetic talk entry
            # so the audit trail shows the closure path explicitly.
            item.talk.append({
                "question": "(no question asked — closed on evidence saturation)",
                "answer": "(no answer; evidence captured from prior turns of this scene)",
                "recorded_at": datetime.now().isoformat(),
            })
        normalized_assumption_evidence = self._normalize_assumption_evidence(
            assumption_evidence,
            getattr(item, "vision_refs", []),
        )
        item.assumption_evidence = self._merge_assumption_evidence(
            getattr(item, "assumption_evidence", []),
            normalized_assumption_evidence,
        )
        item.gaps = self._append_unique_text(list(item.gaps), list(gaps or []))
        normalized_coverage = self._normalize_coverage(coverage)
        item.coverage = self._merge_coverage(getattr(item, "coverage", []), normalized_coverage)
        settled_points = {
            str(entry.get("point") or "").strip().lower()
            for entry in item.coverage
            if str(entry.get("status") or "").strip().lower() in {"covered", "skipped"}
        }
        if settled_points:
            item.gaps = [
                gap for gap in list(item.gaps)
                if str(gap or "").strip().lower() not in settled_points
            ]
        for entry in normalized_coverage:
            if entry.get("status") == "gap":
                point = entry.get("point") or ""
                item.gaps = self._append_unique_text(list(item.gaps), [point])

        settled_rule = rule.strip()
        coverage_complete = self._coverage_complete(
            getattr(item, "coverage_points", []),
            getattr(item, "coverage", []),
        )
        requested_done = bool(
            (done and self._has_meaningful_coverage(getattr(item, "coverage", [])))
            or coverage_complete
        )
        turns_recorded = len(getattr(item, "talk", []) or [])
        min_turns = self._min_turns_for_item(item)
        min_turns_met = turns_recorded >= min_turns
        reached_limit = turns_recorded >= self._max_turns_per_item
        # Prior-coverage short-circuit and saturation-close bypass the
        # min-turn gate. The saturation path is already gated upstream
        # (saturation_close was only computed True when min_turns_met +
        # meaningful coverage / evidence were present), so accepting it
        # here without re-checking min_turns is consistent.
        done = bool(
            (requested_done and (min_turns_met or reached_limit))
            or skip_via_prior
            or saturation_close
        )

        if not done and not reached_limit:
            depth_note = ""
            if requested_done and not min_turns_met:
                depth_note = (
                    f" Minimum evidence turns for this item are {min_turns}; "
                    f"{turns_recorded} recorded."
                )
            return ToolResult(
                observation=(
                    f"Answer recorded for {item.id}; the item remains open for another question."
                    f"{depth_note}"
                ),
                state_updates={
                    "elicitation_agenda": runtime.model_dump(),
                    "enduser_answer": "",
                    "current_question": "",
                    "_agenda_needs_question": True,
                },
                should_return=True,
            )

        item.rule = settled_rule or None
        item.status = "answered" if done else "partial"
        self._record_item_episode(item, closed_via_prior=skip_via_prior)
        runtime.advance()
        next_item = runtime.current_item()

        if skip_via_prior:
            status_text = "closed without a new question (covered_by_prior)"
        elif saturation_close:
            status_text = "closed on evidence saturation (no new lived detail surfacing)"
        elif done:
            status_text = "closed"
        else:
            status_text = "marked partial at the item turn limit"
        return ToolResult(
            observation=f"Answer recorded and item {item.id} {status_text}.",
            state_updates={
                "elicitation_agenda": runtime.model_dump(),
                "enduser_answer": "",
                "current_question": "",
                "current_stakeholder_role": next_item.perspective if next_item else "",
                "item_turn_count": 0,
                "conversation": [],
                "_agenda_needs_question": True,
                "_disabled_prior_skip": False,
            },
            should_return=True,
        )

    def _tool_ask_question(
        self,
        message: str = "",
        state: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> ToolResult:
        state = state or {}
        # Orchestration guard: if a stakeholder answer is pending, the agent
        # must record it first; delivering a fresh question would silently
        # discard the prior turn's evidence.
        if (state.get("enduser_answer") or "").strip():
            return ToolResult(
                observation=(
                    "[ask_question] There is a pending stakeholder answer that has "
                    "not been recorded. Call record_answer first to persist "
                    "assumption_evidence and coverage; then ask the next question."
                ),
                should_return=False,
            )
        runtime = self._load_runtime(state)
        delivered = message.strip()
        if not delivered:
            return ToolResult(
                observation="[ask_question] message is empty. Ask exactly one open question for the current item.",
                should_return=False,
            )

        conversation = list(state.get("conversation") or [])
        conversation.append({
            "role": "interviewer",
            "content": delivered,
            "timestamp": datetime.now().isoformat(),
        })

        item_turn_count = (state.get("item_turn_count") or 0) + 1
        if runtime is not None:
            item = runtime.current_item()
            if item is not None:
                item.question = delivered

        updates: Dict[str, Any] = {
            "current_question": delivered,
            "conversation": conversation,
            "item_turn_count": item_turn_count,
            "_agenda_needs_question": False,
        }
        if runtime is not None:
            updates["elicitation_agenda"] = runtime.model_dump()

        return ToolResult(
            observation=f"Question delivered: {delivered}",
            state_updates=updates,
            should_return=True,
        )

    def _tool_conclude(
        self,
        state: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> ToolResult:
        state = state or {}
        runtime = self._load_runtime(state)
        lines: List[str] = []
        records: List[Dict[str, Any]] = []

        if runtime is not None:
            current = runtime.current_item()
            if current is not None and not runtime.elicitation_complete:
                return ToolResult(
                    observation=(
                        "[conclude] Agenda is still open. Ask the next question "
                        "or record the pending answer instead."
                    ),
                    should_return=False,
                )

            for index, item in enumerate(runtime.items, 1):
                talk = list(item.talk or [])
                answer_text = "\n".join(
                    f"Q: {turn.get('question') or '(not recorded)'}\n"
                    f"A: {turn.get('answer') or '(no answer provided)'}"
                    for turn in talk
                )
                final_status: Literal["answered", "partial", "skipped"]
                if item.status in {"answered", "partial"}:
                    final_status = item.status
                else:
                    final_status = "skipped"
                record = ELRecord(
                    id=f"EL-{index:03d}",
                    item=item.id,
                    perspective=item.perspective,
                    scene=getattr(item, "scene", "") or "",
                    close_when=item.close_when,
                    frictions_to_probe=list(getattr(item, "frictions_to_probe", []) or []),
                    coverage=[
                        CoverageEntry(**entry)
                        for entry in (getattr(item, "coverage", []) or [])
                        if isinstance(entry, dict)
                    ],
                    assumption_evidence=[
                        AssumptionEvidenceEntry(**entry)
                        for entry in (getattr(item, "assumption_evidence", []) or [])
                        if isinstance(entry, dict)
                    ],
                    gaps=list(item.gaps or []),
                    rule=item.rule,
                    talk=talk,
                    status=final_status,
                ).model_dump()
                records.append(record)
                if answer_text:
                    lines.append(
                        f"[{item.id}] {item.perspective}\n{answer_text}"
                    )

        notes = "\n\n".join(lines) or "(no answers recorded)"
        interview_record = {
            "session_id": state.get("session_id", ""),
            "project_description": state.get("project_description", ""),
            "created_at": datetime.now().isoformat(),
            "items": records,
            "notes": notes,
            "status": "pending_review",
        }

        artifacts = dict(state.get("artifacts") or {})
        artifacts["interview_record"] = interview_record

        return ToolResult(
            observation="Interview complete. interview_record artifact written.",
            state_updates={
                "elicitation_notes": notes,
                "artifacts": artifacts,
                "_needs_srs_synthesis": True,
            },
            should_return=True,
        )

    # ── Runtime helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _load_runtime(state: Optional[Dict[str, Any]]) -> Optional[AgendaRuntime]:
        state = state or {}
        artifacts = state.get("artifacts") or {}
        raw = (
            state.get("elicitation_agenda")
            or artifacts.get("reviewed_elicitation_agenda")
            or artifacts.get("elicitation_agenda_artifact")
        )
        if raw is None:
            return None
        if isinstance(raw, AgendaRuntime):
            return raw
        try:
            return AgendaRuntime.from_agenda_artifact(raw)
        except Exception as exc:
            logger.warning("[InterviewerAgent] Could not load agenda runtime: %s", exc)
            return None

    @staticmethod
    def _role_detail(vision: Dict[str, Any], perspective: str) -> str:
        lines: List[str] = []
        wanted = perspective.strip().lower()
        for role in (vision.get("roles") or []):
            if (role.get("name") or "").strip().lower() != wanted:
                continue
            if role.get("need"):
                lines.append(f"  Role need: {role.get('need', '')}")
            lens = role.get("lens") or ""
            anchor = role.get("anchor") or ""
            if lens or anchor:
                lines.append(f"  Role source: [{lens}] {anchor}".rstrip())
            break
        return "\n".join(lines)

    @staticmethod
    def _role_memory(runtime: AgendaRuntime, perspective: str, current_id: str) -> str:
        rules: List[str] = []
        answers: List[str] = []
        for item in runtime.items:
            if item.id == current_id:
                break
            if item.perspective != perspective:
                continue
            if item.rule:
                rules.append(item.rule)
            elif item.answer:
                answers.append(item.answer)
        lines: List[str] = []
        if rules:
            lines.append("  Settled evidence:")
            lines.extend(f"    - {rule}" for rule in rules[-4:])
        if answers:
            lines.append("  Prior answers:")
            lines.extend(f"    - {answer}" for answer in answers[-4:])
        return "\n".join(lines)

    @staticmethod
    def _vision_refs_detail(vision: Dict[str, Any], vision_refs: List[str]) -> str:
        """Render every vision element (assumptions / concerns / scope) so
        the interviewer can recognise when a stakeholder utterance touches
        one and record an AssumptionEvidenceEntry against its id.

        Agenda items no longer carry typed refs (the lived-scene design
        decoupled them), so we expose the full vision menu rather than a
        pre-selected subset.
        """
        assumptions = list(vision.get("assumptions") or [])
        concerns = list(vision.get("concerns") or [])
        scope = list(vision.get("scope") or [])
        if not (assumptions or concerns or scope):
            return ""

        def _source_line(item: Dict[str, Any]) -> str:
            lens = item.get("lens") or ""
            anchor = item.get("anchor") or ""
            if not lens and not anchor:
                return ""
            return f"    source: [{lens}] {anchor}".rstrip()

        lines = [
            "VISION ELEMENTS (touch one by id when the dialogue gives "
            "stance evidence on it — record an AssumptionEvidenceEntry):"
        ]
        for item in assumptions:
            lines.append(f"  - {item.get('id')} [assumption]: {item.get('statement', '')}")
            if item.get("why_it_matters"):
                lines.append(f"    why_it_matters: {item.get('why_it_matters')}")
            source_line = _source_line(item)
            if source_line:
                lines.append(source_line)
        for item in concerns:
            lines.append(f"  - {item.get('id')} [concern]: {item.get('theme', '')}")
            if item.get("rationale"):
                lines.append(f"    rationale: {item.get('rationale')}")
            source_line = _source_line(item)
            if source_line:
                lines.append(source_line)
        for item in scope:
            lines.append(f"  - {item.get('id')} [scope]: {item.get('item', '')}")
            if item.get("reason"):
                lines.append(f"    reason: {item.get('reason')}")
            source_line = _source_line(item)
            if source_line:
                lines.append(source_line)
        return "\n".join(lines)

    def _build_task(self, state: Dict[str, Any]) -> str:
        runtime = self._load_runtime(state)
        vision = (
            (state.get("artifacts") or {}).get("reviewed_product_vision")
            or state.get("product_vision")
            or {}
        )

        if runtime is None:
            return "Agenda runtime is unavailable. Do not fabricate; await orchestration."
        if runtime.elicitation_complete:
            return "AGENDA STATUS: COMPLETE\nAll agenda items are complete. Call conclude."

        item = runtime.current_item()
        if item is None:
            return "AGENDA STATUS: COMPLETE\nAgenda is complete. Call conclude."

        answered = sum(1 for agenda_item in runtime.items if agenda_item.status in {"answered", "partial"})
        total = len(runtime.items)
        role_detail = self._role_detail(vision, item.perspective)
        role_memory = self._role_memory(runtime, item.perspective, item.id)
        assumption_detail = self._vision_refs_detail(
            vision,
            list(getattr(item, "vision_refs", []) or []),
        )
        pending = bool((state.get("enduser_answer") or "").strip())
        prior_episodes, prior_suggestions, fully_covered_by_prior = (
            self._prior_coverage_analysis(item)
        )

        sections = [
            "AGENDA STATUS: OPEN",
            "Conclude is forbidden while this status is OPEN. Work only on the current item.",
            "",
            f"AGENDA: {answered}/{total} items closed or partial.",
            "",
            "CURRENT ITEM:",
            f"  id: {item.id}",
            f"  vision_refs: {', '.join(getattr(item, 'vision_refs', []) or []) or '(none)'}",
            f"  decision_target: {getattr(item, 'decision_target', '') or '(not provided)'}",
            f"  perspective: {item.perspective}",
            "",
            "PERSPECTIVE CONTEXT:",
            role_detail or "  (no extra role detail)",
        ]
        if assumption_detail:
            sections.extend(["", assumption_detail])
        if role_memory:
            sections.extend(["", "SESSION MEMORY:", role_memory])
        if prior_episodes:
            sections.extend([
                "",
                f"PRIOR EPISODES FROM SAME PERSPECTIVE ({len(prior_episodes)}):",
            ])
            for ep in prior_episodes[-6:]:
                trigger = (ep.get("trigger") or "").strip()
                decision = (ep.get("decision") or "").strip()
                outcome = (ep.get("outcome") or "").strip()
                sections.append(f"  - scene: {trigger}")
                if decision:
                    sections.append(f"    settled: {decision}")
                if outcome:
                    sections.append(f"    outcome: {outcome}")
        if prior_suggestions:
            sections.extend([
                "",
                "COVERAGE POINTS LIKELY ALREADY SETTLED BY PRIOR (heuristic suggestion):",
            ])
            for s in prior_suggestions:
                sections.append(f"  - point: {s['point']}")
                sections.append(f"    evidence hint: {s['evidence_hint']}")
                if s.get("matched_words"):
                    sections.append(f"    matched words: {s['matched_words']}")
            if fully_covered_by_prior:
                sections.extend([
                    "",
                    "PRIOR-COVERAGE SHORT-CIRCUIT:",
                    "  Every coverage_point on this item appears already settled by a",
                    "  prior episode from the same perspective. Call record_answer NOW",
                    "  with done=true and one coverage entry per point with",
                    "  status=covered_by_prior + evidence citing the prior episode.",
                    "  Do NOT ask a new question — the EndUser will not produce new",
                    "  evidence for ground already covered, and re-asking burns a turn.",
                ])
            else:
                sections.extend([
                    "",
                    "PARTIAL PRIOR COVERAGE:",
                    "  Some points may be settled by prior; some still need a fresh",
                    "  probe. Open the next question targeted at an uncovered point;",
                    "  in record_answer assign status=covered_by_prior to the matched",
                    "  points (citing the prior episode) and probe only the rest.",
                ])

        frictions_to_probe = list(getattr(item, "frictions_to_probe", []) or [])
        min_turns = self._min_turns_for_item(item)
        turns_recorded = len(getattr(item, "talk", []) or [])
        sections.extend([
            "",
            "SCENE:",
            f"  {getattr(item, 'scene', '') or '(not provided)'}",
            "",
            "PRIVATE INTERVIEWER CONTEXT:",
            f"  critical_incident_prompt: {getattr(item, 'critical_incident_prompt', '') or '(not provided)'}",
            f"  close_when: {item.close_when}",
            "  frictions_to_probe:",
            *(
                [f"    - {friction}" for friction in frictions_to_probe]
                if frictions_to_probe
                else ["    - (not provided; use close_when as the fallback stop condition)"]
            ),
            f"  notes: {item.notes or '(not provided)'}",
            "",
            "TURN STATUS:",
            f"  Turn count for item: {state.get('item_turn_count', 0)}",
            f"  Recorded answer turns for item: {turns_recorded}",
            f"  Minimum evidence turns for this item: {min_turns}",
            f"  Minimum evidence turns met: {'yes' if turns_recorded >= min_turns else 'no'}",
            f"  Item turn limit: {self._max_turns_per_item}",
            f"  Pending answer: {'yes' if pending else 'no'}",
        ])

        conversation = state.get("conversation") or []
        if conversation:
            sections.extend(["", "CURRENT DIALOGUE:"])
            for turn in conversation[-8:]:
                sections.append(
                    f"  [{str(turn.get('role', '')).upper()}] {turn.get('content', '')}"
                )
        if pending:
            sections.extend(["", "PENDING ANSWER:", f"  {state.get('enduser_answer', '')}"])
        coverage = list(getattr(item, "coverage", []) or [])
        if coverage:
            sections.extend(["", "COVERAGE SO FAR:"])
            for entry in coverage:
                if not isinstance(entry, dict):
                    continue
                point = entry.get("point", "")
                status = entry.get("status", "")
                evidence = entry.get("evidence", "")
                suffix = f" — {evidence}" if evidence else ""
                sections.append(f"  - {status}: {point}{suffix}")
        assumption_evidence = list(getattr(item, "assumption_evidence", []) or [])
        if assumption_evidence:
            sections.extend(["", "ASSUMPTION EVIDENCE SO FAR:"])
            for entry in assumption_evidence:
                if not isinstance(entry, dict):
                    continue
                ref = entry.get("vision_ref") or entry.get("assumption_ref", "")
                stance = entry.get("stance", "")
                evidence = entry.get("evidence", "")
                implication = entry.get("implication", "")
                sections.append(f"  - {ref} {stance}: {evidence} -> {implication}")

        return "\n".join(sections)

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        # Orchestration sets a tool_choice when the next move is unambiguous;
        # otherwise it leaves the choice to the model so the model can decide
        # to drill further or close the item on evidence saturation.
        #   pending answer                               → force record_answer
        #   agenda complete                              → force conclude
        #   no pending + open + fully prior-covered      → force record_answer
        #   no pending + open + min_turns NOT yet met    → force ask_question
        #   no pending + open + min_turns met            → auto (model picks
        #                                                  ask vs saturation-
        #                                                  close via record)
        runtime = self._load_runtime(state)
        pending = bool((state.get("enduser_answer") or "").strip())
        agenda_complete = bool(runtime is not None and runtime.elicitation_complete)
        fully_prior_covered = False
        prior_skip_blocked = bool(state.get("_disabled_prior_skip"))
        current_item = None
        if (
            not pending
            and runtime is not None
            and not agenda_complete
            and not prior_skip_blocked
        ):
            current_item = runtime.current_item()
            if current_item is not None:
                _, _, fully_prior_covered = self._prior_coverage_analysis(current_item)

        def _force(tool_name: str) -> Dict[str, Any]:
            return {"type": "function", "function": {"name": tool_name}}

        if pending:
            tool_choice: Any = _force("record_answer")
        elif agenda_complete:
            tool_choice = _force("conclude")
        elif fully_prior_covered:
            tool_choice = _force("record_answer")
        else:
            # No pending answer, open agenda. If the minimum-evidence budget
            # for this item is not yet met, force a question so the drill
            # has room to surface evidence. Once the minimum is met, leave
            # the choice to the model — it may ask another question or
            # close on saturation by calling record_answer with done=true.
            min_turns = (
                self._min_turns_for_item(current_item)
                if current_item is not None
                else self._min_turns_per_assumption_item
            )
            turns_recorded = (
                len(getattr(current_item, "talk", []) or [])
                if current_item is not None
                else 0
            )
            if turns_recorded < min_turns:
                tool_choice = _force("ask_question")
            else:
                tool_choice = "auto"

        return self.react(
            state=state,
            task=self._build_task(state),
            tool_choice=tool_choice,
            profile_addendum=_REACT_ADDENDUM,
            include_memory=False,
        )
