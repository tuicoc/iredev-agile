import importlib.util
import sys
import types
import unittest
from pathlib import Path

if importlib.util.find_spec("langchain_core") is None:
    langchain_core = types.ModuleType("langchain_core")
    messages = types.ModuleType("langchain_core.messages")

    class BaseMessage:  # pragma: no cover - schema tests never instantiate it.
        pass

    messages.BaseMessage = BaseMessage
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.messages"] = messages

from src.agent.agenda import AgendaRuntime
from src.agent.base import BaseAgent
from src.agent.distiller import Requirement, _PASS1 as DISTILLER_PASS1
from src.agent.interviewer import InterviewerAgent, _REACT_ADDENDUM as INTERVIEWER_ADDENDUM
from src.agent.sprint import SprintAgent
from src.agent.visionary import (
    ProductVision,
    _PASS1 as VISIONARY_PASS1,
    _PASS1_AUDIT as VISIONARY_PASS1_AUDIT,
    _PASS3 as VISIONARY_PASS3,
    _PASS4 as VISIONARY_PASS4,
)


class PromptContractTest(unittest.TestCase):
    def test_visionary_flow_keeps_anchored_operational_entity_inference(self) -> None:
        self.assertIn("operationally entailed", VISIONARY_PASS1)
        self.assertIn("both anchors are present", VISIONARY_PASS1)
        self.assertIn("product domain gives the object a natural name", VISIONARY_PASS1)
        self.assertIn("Do not reuse a fixed", VISIONARY_PASS1)
        self.assertIn("same schema", VISIONARY_PASS1_AUDIT)
        self.assertIn("orphan concept test", VISIONARY_PASS1_AUDIT)
        self.assertIn("shared resource", VISIONARY_PASS4)
        self.assertNotIn("Seating Resource", VISIONARY_PASS1)
        self.assertNotIn("Bookable Resource", VISIONARY_PASS1)

    def test_visionary_flow_separates_actors_from_entities(self) -> None:
        self.assertIn("actor boundary test", VISIONARY_PASS1)
        self.assertIn("Being the subject of another entity is not enough", VISIONARY_PASS1)
        self.assertIn("name the managed record", VISIONARY_PASS1)
        self.assertIn("must not be entities", VISIONARY_PASS1_AUDIT)
        self.assertIn("partner role", VISIONARY_PASS3)

    def test_visionary_persona_stays_domain_neutral(self) -> None:
        persona = Path("prompts/visionary_react.txt").read_text(encoding="utf-8")
        self.assertIn("fixed entity names", persona)
        self.assertNotIn("bookings, queues", persona)
        self.assertNotIn("Seating Resource", persona)

    def test_distiller_is_not_one_to_one_with_interview_records(self) -> None:
        self.assertIn(
            "One interview record may produce zero, one, or many requirements",
            DISTILLER_PASS1,
        )
        self.assertIn("signals as the preferred atomic evidence source", DISTILLER_PASS1)
        self.assertIn("Multiple requirements may share the same EL source id", DISTILLER_PASS1)

    def test_interviewer_records_atomic_signals_for_distiller(self) -> None:
        self.assertIn("signals carry the independent facts", INTERVIEWER_ADDENDUM)
        self.assertIn("Do not merge them", INTERVIEWER_ADDENDUM)


class LLMConfigContractTest(unittest.TestCase):
    def test_profiled_llm_routes_interview_agents_to_smaller_model(self) -> None:
        config = {
            "llm": {
                "default": {
                    "type": "openai",
                    "api_key": "token",
                    "model": "general-model",
                    "base_url": "https://example.test/v1",
                    "temperature": 0.2,
                },
                "interview": {
                    "model": "interview-model",
                    "temperature": 0.7,
                },
                "agents": {
                    "interviewer": "interview",
                    "enduser": "interview",
                },
            },
            "iredev": {"agents": {}},
        }

        interviewer_cfg = BaseAgent._resolve_llm_config(config, "interviewer")
        enduser_cfg = BaseAgent._resolve_llm_config(config, "enduser")
        visionary_cfg = BaseAgent._resolve_llm_config(config, "visionary")

        self.assertEqual(interviewer_cfg["model"], "interview-model")
        self.assertEqual(enduser_cfg["model"], "interview-model")
        self.assertEqual(visionary_cfg["model"], "general-model")
        self.assertEqual(interviewer_cfg["type"], "openai")
        self.assertEqual(interviewer_cfg["base_url"], "https://example.test/v1")

    def test_legacy_flat_llm_config_still_resolves(self) -> None:
        config = {
            "llm": {
                "type": "openai",
                "api_key": "token",
                "model": "legacy-model",
            },
            "iredev": {"agents": {}},
        }

        self.assertEqual(
            BaseAgent._resolve_llm_config(config, "agenda")["model"],
            "legacy-model",
        )


class ProductVisionContractTest(unittest.TestCase):
    def test_product_vision_accepts_nfr_concerns_with_legacy_scope_shape(self) -> None:
        vision = ProductVision(
            description="Tracks a persistent concept through stakeholder work.",
            notes="audit",
            flow={
                "entities": [
                    {
                        "name": "TrackedConcept",
                        "kind": "primary",
                        "purpose": "Represents the main thing being tracked.",
                        "steps": [
                            {"name": "ConceptCreated", "detail": "The concept starts."}
                        ],
                        "related_to": None,
                        "order": 1,
                        "signal": "Named by the product concept.",
                    }
                ],
                "links": [],
            },
            roles=[
                {
                    "name": "Operator",
                    "kind": "operator",
                    "duties": [
                        {
                            "id": "MD-01",
                            "rule": "Create the tracked concept when work begins.",
                            "risk": "Work cannot be followed if creation is unclear.",
                            "aspect": "operational_rule",
                            "entity": "TrackedConcept",
                            "step": "ConceptCreated",
                            "entity_refs": ["TrackedConcept"],
                            "flow_step_refs": ["ConceptCreated"],
                            "priority": "high",
                        }
                    ],
                }
            ],
            nfr_concerns=[
                {
                    "category": "reliability",
                    "theme": "preserved history",
                    "attached_to": ["TrackedConcept", "ConceptCreated"],
                    "affected_roles": ["Operator"],
                    "rationale": "The operator needs history to remain available.",
                }
            ],
            scope=[
                {
                    "id": "OOS-01",
                    "item": "External billing",
                    "reason": "Not implied by the product concept.",
                }
            ],
        )

        self.assertEqual(vision.nfr_concerns[0].theme, "preserved history")
        self.assertEqual(vision.scope[0].item, "External billing")


class AgendaRuntimeContractTest(unittest.TestCase):
    def test_runtime_loads_legacy_need_and_new_concern_items(self) -> None:
        runtime = AgendaRuntime.from_agenda_artifact(
            {
                "items": [
                    {
                        "id": "IT-01",
                        "entity": "TrackedConcept",
                        "step": "ConceptCreated",
                        "role": "Operator",
                        "aspect": "operational_rule",
                        "trap": "straw_man",
                        "kind": "need",
                        "baseline": "Operator creates the concept.",
                        "scene": "Work begins.",
                        "risk": "Operator cannot start work when the creation condition is unclear.",
                        "probe": "Creation is always simple.",
                        "gap": "creation condition",
                        "close": "Creation rule is explicit.",
                        "source": "MD-01",
                        "peer": None,
                    },
                    {
                        "id": "IT-02",
                        "entity": "TrackedConcept",
                        "step": "ConceptCreated",
                        "role": "Operator",
                        "aspect": "quality_concern",
                        "trap": "quality_probe",
                        "kind": "concern",
                        "baseline": "Reliability concern around preserved history.",
                        "scene": "History is needed during work.",
                        "risk": "Operator loses needed history when normal continuity fails.",
                        "probe": "History is always available enough.",
                        "gap": "acceptable loss condition",
                        "close": "Quality evidence is explicit.",
                        "source": "CONCERN-01",
                        "peer": None,
                        "concern_ref": "CONCERN-01",
                        "concern_category": "reliability",
                        "concern_theme": "preserved history",
                    },
                ]
            }
        )

        self.assertEqual(runtime.items[0].kind, "need")
        self.assertEqual(
            runtime.items[0].risk,
            "Operator cannot start work when the creation condition is unclear.",
        )
        self.assertEqual(runtime.items[1].kind, "concern")
        self.assertEqual(runtime.items[1].concern_theme, "preserved history")
        self.assertEqual(
            runtime.items[1].risk,
            "Operator loses needed history when normal continuity fails.",
        )


class DistillerContractTest(unittest.TestCase):
    def test_requirement_accepts_nfr_trace_fields(self) -> None:
        requirement = Requirement(
            id="NFR-001",
            type="non_functional",
            stakeholder="Operator",
            statement="The system should preserve concept history under normal operation.",
            entity="TrackedConcept",
            step="ConceptCreated",
            aspect="quality_concern",
            category="reliability",
            concern_theme="preserved history",
            entity_refs=["TrackedConcept"],
            flow_step_refs=["ConceptCreated"],
            requires_threshold=True,
            rationale="The stakeholder described preserved history as necessary.",
            acceptance_criteria=["History is available after normal restart."],
            priority="high",
            source="EL-001",
            origin="interview",
            status="confirmed",
        )

        self.assertTrue(requirement.requires_threshold)
        self.assertEqual(requirement.category, "reliability")


class BacklogContractTest(unittest.TestCase):
    def test_requirement_trace_normalizes_distiller_item(self) -> None:
        trace = SprintAgent._normalise_requirement_trace(
            {
                "id": "FR-001",
                "type": "functional",
                "stakeholder": "Customer",
                "statement": "Customers can create a booking.",
                "entity": "Booking",
                "step": "Create Booking",
                "aspect": "permission",
                "rationale": "Customers need a reservation.",
                "acceptance_criteria": ["Booking request is captured."],
                "priority": "high",
                "source": "EL-001",
                "origin": "interview",
                "status": "confirmed",
            }
        )

        self.assertEqual(trace["requirement_id"], "FR-001")
        self.assertEqual(trace["requirement_type"], "functional")
        self.assertEqual(trace["entity"], "Booking")
        self.assertEqual(trace["source"], "EL-001")

    def test_split_child_keeps_original_requirement_trace(self) -> None:
        agent = SprintAgent.__new__(SprintAgent)
        state = {
            "split_round": 0,
            "artifacts": {
                "user_story_draft": {
                    "stories": [
                        {
                            "source_story_id": "FR-004",
                            "source_requirement_id": "FR-004",
                            "type": "functional",
                            "domain": "Booking",
                            "title": "Modify Booking Details",
                            "description": (
                                "As a Customer, I can modify booking details, "
                                "so that my reservation stays accurate."
                            ),
                            "requirement_trace": {
                                "requirement_id": "FR-004",
                                "requirement_type": "functional",
                                "stakeholder": "Customer",
                                "statement": "Customers can modify booking details.",
                                "entity": "Booking",
                                "step": "Modify Booking",
                                "aspect": "permission",
                                "category": None,
                                "concern_theme": None,
                                "entity_refs": [],
                                "flow_step_refs": [],
                                "requires_threshold": False,
                                "rationale": "Customers need reservation flexibility.",
                                "acceptance_criteria": [],
                                "priority": "medium",
                                "source": "EL-003",
                                "origin": "interview",
                                "status": "confirmed",
                            },
                            "is_split_child": False,
                            "split": {
                                "parent_story_id": None,
                                "suffix": None,
                                "reasoning": None,
                            },
                        }
                    ]
                },
                "analyst_estimation": {
                    "stories": [
                        {
                            "source_story_id": "FR-004",
                            "needs_split": True,
                            "split_proposals": [
                                {
                                    "title": "Modify Booking Before Cutoff",
                                    "capability": "modify booking details before the cut-off time",
                                    "reasoning": "This covers the allowed modification path.",
                                },
                                {
                                    "title": "Handle Late Modification",
                                    "capability": "see the late-modification path after the cut-off time",
                                    "reasoning": "This covers the blocked modification path.",
                                },
                            ],
                        }
                    ]
                },
            },
        }

        updates = agent.process_splits(state)
        stories = updates["artifacts"]["user_story_draft"]["stories"]

        self.assertEqual(stories[0]["source_story_id"], "FR-004a")
        self.assertEqual(stories[0]["source_requirement_id"], "FR-004")
        self.assertEqual(stories[0]["requirement_trace"]["requirement_id"], "FR-004")
        self.assertTrue(stories[0]["is_split_child"])
        self.assertNotIn("analyst_estimation", updates["artifacts"])


class InterviewerGuardTest(unittest.TestCase):
    def test_conclude_refuses_open_agenda(self) -> None:
        agent = InterviewerAgent.__new__(InterviewerAgent)
        runtime = AgendaRuntime.from_agenda_artifact(
            {
                "items": [
                    {
                        "id": "IT-01",
                        "entity": "TrackedConcept",
                        "step": "ConceptCreated",
                        "role": "Operator",
                        "aspect": "operational_rule",
                        "trap": "straw_man",
                        "kind": "need",
                        "baseline": "Operator creates the concept.",
                        "scene": "Work begins.",
                        "risk": "Operator cannot start work when the creation condition is unclear.",
                        "probe": "Creation is always simple.",
                        "gap": "creation condition",
                        "close": "Creation rule is explicit.",
                        "source": "MD-01",
                    }
                ]
            }
        )

        result = agent._tool_conclude(state={"elicitation_agenda": runtime.model_dump()})

        self.assertFalse(result.should_return)
        self.assertNotIn("artifacts", result.state_updates)

    def test_record_answer_keeps_item_open_without_settled_statement(self) -> None:
        agent = InterviewerAgent.__new__(InterviewerAgent)
        runtime = AgendaRuntime.from_agenda_artifact(
            {
                "items": [
                    {
                        "id": "IT-01",
                        "entity": "TrackedConcept",
                        "step": "ConceptCreated",
                        "role": "Operator",
                        "aspect": "quality_concern",
                        "trap": "quality_probe",
                        "kind": "concern",
                        "baseline": "Reliability concern.",
                        "scene": "Work begins.",
                        "risk": "Operator loses needed history when normal continuity fails.",
                        "probe": "History is always available enough.",
                        "gap": "acceptable loss condition",
                        "close": "Quality evidence is explicit.",
                        "source": "CONCERN-01",
                        "concern_ref": "CONCERN-01",
                        "concern_category": "reliability",
                        "concern_theme": "preserved history",
                    }
                ]
            }
        )

        result = agent._tool_record_answer(
            align="narrower",
            done=True,
            rule="",
            signals=["History matters."],
            state={
                "elicitation_agenda": runtime.model_dump(),
                "enduser_answer": "History loss is painful, but I do not know the exact limit.",
            },
        )

        updated = AgendaRuntime(**result.state_updates["elicitation_agenda"])
        self.assertTrue(result.should_return)
        self.assertEqual(updated.current_index, 0)
        self.assertEqual(updated.items[0].status, "pending")


@unittest.skipUnless(
    importlib.util.find_spec("langgraph") is not None,
    "graph review payload import requires langgraph",
)
class ReviewPayloadContractTest(unittest.TestCase):
    def test_product_vision_payload_includes_concerns_and_scope_shape(self) -> None:
        from src.orchestrator.graph import _build_product_vision_review_payload

        payload = _build_product_vision_review_payload(
            {
                "product_name": "Concept Tracker",
                "concept_summary": "Tracks a persistent concept.",
                "description": "Tracks a persistent concept.",
                "flow": {"entities": [], "links": []},
                "roles": [
                    {
                        "name": "Operator",
                        "kind": "operator",
                        "duties": [
                            {
                                "id": "MD-01",
                                "rule": "Create the concept.",
                                "risk": "Missing creation rule.",
                                "aspect": "operational_rule",
                                "entity": "TrackedConcept",
                                "step": "ConceptCreated",
                                "entity_refs": ["TrackedConcept"],
                                "flow_step_refs": ["ConceptCreated"],
                                "priority": "high",
                            }
                        ],
                    }
                ],
                "nfr_concerns": [{"category": "reliability", "theme": "preserved history"}],
                "scope": [
                    {
                        "id": "OOS-01",
                        "item": "External billing",
                        "reason": "Not implied by the product concept.",
                    }
                ],
            }
        )

        self.assertEqual(payload["nfr_concerns"][0]["theme"], "preserved history")
        self.assertEqual(payload["scope"][0]["item"], "External billing")
        self.assertEqual(payload["roles"][0]["duties"][0]["entity_refs"], ["TrackedConcept"])

    def test_agenda_payload_includes_risk_hooks(self) -> None:
        from src.orchestrator.graph import _build_elicitation_agenda_review_payload

        payload = _build_elicitation_agenda_review_payload(
            {
                "items": [
                    {
                        "id": "IT-01",
                        "entity": "TrackedConcept",
                        "step": "ConceptCreated",
                        "role": "Operator",
                        "aspect": "operational_rule",
                        "trap": "straw_man",
                        "kind": "need",
                        "baseline": "Operator creates the concept.",
                        "scene": "Work begins.",
                        "risk": "Operator cannot start work when creation is unclear.",
                        "probe": "Creation is always simple.",
                        "gap": "creation condition",
                        "close": "Creation rule is explicit.",
                        "source": "MD-01",
                    }
                ]
            },
            {
                "entries": [
                    {
                        "id": "AM-01",
                        "entity": "TrackedConcept",
                        "step": "ConceptCreated",
                        "role": "Operator",
                        "aspect": "operational_rule",
                        "source": "MD-01",
                        "kind": "need",
                        "note": "Mapped from duty.",
                        "risk": "Operator cannot start work when creation is unclear.",
                    }
                ]
            },
        )

        self.assertEqual(
            payload["aspect_entries"][0]["risk"],
            "Operator cannot start work when creation is unclear.",
        )
        self.assertEqual(
            payload["items"][0]["risk"],
            "Operator cannot start work when creation is unclear.",
        )

    def test_product_backlog_payload_shows_requirement_trace(self) -> None:
        from src.orchestrator.graph import _build_product_backlog_review_payload

        payload = _build_product_backlog_review_payload(
            {
                "items": [
                    {
                        "id": "PBI-001a",
                        "source_story_id": "FR-004a",
                        "source_requirement_id": "FR-004",
                        "title": "Modify Booking Before Cutoff",
                        "type": "functional",
                        "description": (
                            "As a Customer, I can modify booking details before "
                            "the cut-off time, so that my reservation stays accurate."
                        ),
                        "requirement_trace": {
                            "requirement_id": "FR-004",
                            "requirement_type": "functional",
                            "stakeholder": "Customer",
                            "entity": "Booking",
                            "step": "Modify Booking",
                            "aspect": "permission",
                            "priority": "medium",
                            "source": "EL-003",
                            "origin": "interview",
                            "statement": "Customers can modify booking details.",
                            "rationale": "Customers need reservation flexibility.",
                            "acceptance_criteria": ["Modification before cut-off succeeds."],
                        },
                        "estimation": {"story_points": 3},
                        "prioritization": {"priority_rank": 1, "wsjf_score": 5.0},
                        "quality": {"invest_flags": []},
                        "planning": {"status": "ready"},
                        "dependencies": {"blocked_by": [], "blocks": []},
                    }
                ]
            }
        )

        story = payload["stories"][0]
        self.assertEqual(story["source_story_id"], "FR-004a")
        self.assertEqual(story["source_requirement_id"], "FR-004")
        self.assertEqual(story["requirement_trace"]["requirement_id"], "FR-004")
        self.assertEqual(story["requirement_trace"]["statement"], "Customers can modify booking details.")

    def test_requirement_list_payload_exposes_conflicts(self) -> None:
        from src.orchestrator.graph import (
            _build_requirement_conflict_summary,
            _build_requirement_list_review_payload,
        )

        req_list = {
            "session_id": "demo",
            "items": [
                {"id": "FR-001", "type": "functional", "priority": "high"},
                {"id": "FR-002", "type": "functional", "priority": "medium"},
            ],
            "conflicts": [
                {
                    "id": "CF-01",
                    "kind": "clash",
                    "left": "FR-001",
                    "right": "FR-002",
                    "scope": "Booking creation",
                    "issue": "The two booking limits cannot both apply.",
                    "paths": ["Keep FR-001", "Keep FR-002"],
                    "refs": ["EL-001"],
                }
            ],
        }

        payload = _build_requirement_list_review_payload(req_list, req_list["items"])
        summary = _build_requirement_conflict_summary(req_list["conflicts"])

        self.assertTrue(payload["has_conflicts"])
        self.assertEqual(payload["conflicts"][0]["id"], "CF-01")
        self.assertIn("hard gate", summary)
        self.assertIn("FR-001", summary)


if __name__ == "__main__":
    unittest.main()
