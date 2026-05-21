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
from src.agent.distiller import (
    DistillerAgent,
    Requirement,
    _BATCH_EXTRACTION as DISTILLER_BATCH_EXTRACTION,
    _FINAL_ASSEMBLY as DISTILLER_FINAL_ASSEMBLY,
    _MERGE_SEEDS as DISTILLER_MERGE_SEEDS,
)
from src.agent.enduser import EndUserAgent
from src.agent.interviewer import InterviewerAgent, _REACT_ADDENDUM as INTERVIEWER_ADDENDUM
from src.agent.visionary import ProductVision, _GLOSSARY as VISIONARY_GLOSSARY


class PromptContractTest(unittest.TestCase):
    def test_visionary_defines_operating_terms_without_domain_examples(self) -> None:
        self.assertIn("sparse input", VISIONARY_GLOSSARY)
        self.assertIn("capability", VISIONARY_GLOSSARY)
        self.assertIn("interaction", VISIONARY_GLOSSARY)
        self.assertIn("Do not use domain examples", VISIONARY_GLOSSARY)

    def test_personas_stay_short_and_domain_neutral(self) -> None:
        for path in [
            "prompts/visionary_react.txt",
            "prompts/agenda_react.txt",
            "prompts/interviewer_react.txt",
            "prompts/enduser_react.txt",
            "prompts/distiller_react.txt",
        ]:
            persona = Path(path).read_text(encoding="utf-8")
            self.assertIn("ROLE", persona)
            self.assertIn("MISSION", persona)
            self.assertIn("STANCE", persona)
            self.assertIn("VOICE", persona)
            self.assertNotIn("for example", persona.lower())

    def test_legacy_interviewer_prompt_folder_is_removed(self) -> None:
        self.assertFalse(Path("prompts/interviewer").exists())

    def test_distiller_uses_batch_seed_extraction(self) -> None:
        self.assertIn("Read signals first", DISTILLER_BATCH_EXTRACTION)
        self.assertIn("Read talk units after signals", DISTILLER_BATCH_EXTRACTION)
        self.assertIn("information, action, state, prevention, recovery, or quality", DISTILLER_BATCH_EXTRACTION)
        self.assertIn("Keep cross-focus source_refs visible", DISTILLER_MERGE_SEEDS)
        self.assertIn("keep it as a gap instead of an out_of_scope requirement", DISTILLER_FINAL_ASSEMBLY)

    def test_interviewer_uses_toolkit_without_forced_probe(self) -> None:
        self.assertIn("specify", INTERVIEWER_ADDENDUM)
        self.assertIn("negate", INTERVIEWER_ADDENDUM)
        self.assertIn("stretch", INTERVIEWER_ADDENDUM)
        self.assertIn("conflict", INTERVIEWER_ADDENDUM)
        self.assertIn("why-deeper", INTERVIEWER_ADDENDUM)
        self.assertNotIn("coverage >= " + "80", INTERVIEWER_ADDENDUM)


class LLMConfigContractTest(unittest.TestCase):
    def test_profiled_llm_routes_interview_agents_to_profile(self) -> None:
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
    def test_product_vision_accepts_focus_driven_shape(self) -> None:
        vision = ProductVision(
            description="Provides requested product behavior for a product user.",
            notes="given signal was developed into a usable focus source",
            capabilities=[
                {
                    "id": "CAP-01",
                    "name": "Capability Alpha",
                    "need": "Role Alpha needs observable product behavior.",
                    "source_kind": "given",
                    "source_note": "The input states the desired product behavior.",
                    "notes": "",
                }
            ],
            roles=[
                {
                    "id": "ROLE-01",
                    "name": "Role Alpha",
                    "kind": "primary_user",
                    "need": "Uses the product behavior.",
                    "source_kind": "given",
                    "source_note": "The input names this product user.",
                    "notes": "",
                }
            ],
            entities=[
                {
                    "name": "Map Coordinate Alpha",
                    "purpose": "Grounds an operating scene.",
                    "steps": [
                        {
                            "name": "Action Alpha",
                            "actor": "Role Alpha",
                            "detail": "A meaningful product action occurs.",
                        }
                    ],
                    "notes": "",
                }
            ],
            links=[
                {
                    "id": "LINK-01",
                    "source": "Capability Alpha",
                    "target": "Map Coordinate Alpha",
                    "trigger": "A product action changes an operating condition.",
                    "affected_roles": ["Role Alpha"],
                    "detail": "The dependency may need interaction elicitation.",
                    "source_kind": "developed",
                    "source_note": "The capability and map coordinate are connected.",
                }
            ],
            duties=[],
            concerns=[],
            scope=[],
        )

        self.assertEqual(vision.capabilities[0].id, "CAP-01")
        self.assertEqual(vision.roles[0].kind, "primary_user")
        self.assertEqual(vision.links[0].id, "LINK-01")


class AgendaRuntimeContractTest(unittest.TestCase):
    def test_runtime_loads_focus_items(self) -> None:
        runtime = AgendaRuntime.from_agenda_artifact(
            {
                "items": [
                    {
                        "id": "IT-001",
                        "focus_kind": "capability",
                        "focus_ref": "CAP-01",
                        "perspective": "Role Alpha",
                        "context": "A role needs to use a product behavior.",
                        "seed_question": "What makes this behavior successful for you?",
                        "close_when": "Success, failure, and responsibility are clear.",
                        "notes": "Covers a capability focus.",
                    }
                ]
            }
        )

        self.assertEqual(runtime.items[0].focus_kind, "capability")
        self.assertEqual(runtime.items[0].perspective, "Role Alpha")
        self.assertEqual(runtime.items[0].status, "pending")


class DistillerContractTest(unittest.TestCase):
    def test_distiller_batches_by_perspective_not_agenda_order(self) -> None:
        batches = DistillerAgent._build_batches(
            [
                {"id": "EL-001", "perspective": "Role Alpha", "signals": ["first"]},
                {"id": "EL-002", "perspective": "Role Beta", "signals": ["second"]},
                {"id": "EL-003", "perspective": "Role Alpha", "signals": ["third"]},
            ]
        )

        self.assertEqual([batch["perspective"] for batch in batches], ["Role Alpha", "Role Beta"])
        self.assertEqual([item["id"] for item in batches[0]["items"]], ["EL-001", "EL-003"])
        self.assertEqual([item["id"] for item in batches[1]["items"]], ["EL-002"])

    def test_requirement_accepts_focus_trace_fields(self) -> None:
        requirement = Requirement(
            id="NFR-001",
            type="non_functional",
            stakeholder="Role Alpha",
            statement="The product should satisfy a stated quality boundary.",
            focus_kind="concern",
            focus_ref="CONCERN-01",
            trace_refs=["EL-001", "CONCERN-01"],
            entity=None,
            step=None,
            quality_theme="Concern Alpha",
            requires_threshold=True,
            rationale="EL-001 evidence states a defensible qualitative boundary.",
            acceptance_criteria=["The stated qualitative boundary can be reviewed."],
            priority="high",
            source="EL-001",
            origin="interview",
            status="confirmed",
        )

        self.assertTrue(requirement.requires_threshold)
        self.assertEqual(requirement.focus_kind, "concern")
        self.assertEqual(requirement.focus_ref, "CONCERN-01")

    def test_requirement_accepts_system_type(self) -> None:
        requirement = Requirement(
            id="SYS-001",
            type="system",
            stakeholder=None,
            statement="The product shall preserve a shared operating state.",
            focus_kind="interaction",
            focus_ref="LINK-01",
            trace_refs=["EL-001-T01"],
            requires_threshold=False,
            rationale="The cited evidence requires one shared product behavior.",
            acceptance_criteria=["The shared state is preserved for the cited behavior."],
            priority="high",
            source="EL-001",
            origin="interview",
            status="confirmed",
        )

        self.assertEqual(requirement.type, "system")
        self.assertIsNone(requirement.stakeholder)


class InterviewerGuardTest(unittest.TestCase):
    def test_conclude_refuses_open_agenda(self) -> None:
        agent = InterviewerAgent.__new__(InterviewerAgent)
        agent._max_turns_per_item = 5
        runtime = AgendaRuntime.from_agenda_artifact(
            {
                "items": [
                    {
                        "id": "IT-001",
                        "focus_kind": "scene",
                        "focus_ref": "DUTY-01",
                        "perspective": "Role Alpha",
                        "context": "A role acts in an operating situation.",
                        "seed_question": "What happens in this situation?",
                        "close_when": "Condition, exception, permission, and consequence are clear.",
                    }
                ]
            }
        )

        result = agent._tool_conclude(state={"elicitation_agenda": runtime.model_dump()})

        self.assertFalse(result.should_return)
        self.assertNotIn("artifacts", result.state_updates)

    def test_record_answer_keeps_item_open_without_done(self) -> None:
        agent = InterviewerAgent.__new__(InterviewerAgent)
        agent._max_turns_per_item = 5
        runtime = AgendaRuntime.from_agenda_artifact(
            {
                "items": [
                    {
                        "id": "IT-001",
                        "focus_kind": "concern",
                        "focus_ref": "CONCERN-01",
                        "perspective": "Role Alpha",
                        "context": "A role experiences a quality concern.",
                        "seed_question": "What boundary matters in this situation?",
                        "close_when": "Boundary, condition, and impact are clear.",
                    }
                ]
            }
        )

        result = agent._tool_record_answer(
            done=False,
            rule="",
            signals=["A quality boundary matters."],
            evidence=["The answer states that the boundary matters."],
            coverage_note="Boundary is mentioned but not settled.",
            technique_used="specify",
            state={
                "elicitation_agenda": runtime.model_dump(),
                "enduser_answer": "The boundary matters, but I cannot state it yet.",
                "item_turn_count": 1,
            },
        )

        updated = AgendaRuntime(**result.state_updates["elicitation_agenda"])
        self.assertTrue(result.should_return)
        self.assertEqual(updated.current_index, 0)
        self.assertEqual(updated.items[0].status, "pending")


class EndUserGuardTest(unittest.TestCase):
    def test_empty_response_is_not_fabricated(self) -> None:
        agent = EndUserAgent.__new__(EndUserAgent)

        result = agent._tool_respond(message="", state={"conversation": []})

        self.assertFalse(result.should_return)
        self.assertNotIn("enduser_answer", result.state_updates)


@unittest.skipUnless(
    importlib.util.find_spec("langgraph") is not None,
    "graph review payload import requires langgraph",
)
class ReviewPayloadContractTest(unittest.TestCase):
    def test_product_vision_payload_includes_focus_shape(self) -> None:
        from src.orchestrator.graph import _build_product_vision_review_payload

        payload = _build_product_vision_review_payload(
            {
                "description": "Provides requested product behavior.",
                "notes": "audit note",
                "capabilities": [{"id": "CAP-01", "name": "Capability Alpha"}],
                "roles": [{"id": "ROLE-01", "name": "Role Alpha", "kind": "primary_user"}],
                "entities": [],
                "links": [],
                "duties": [],
                "concerns": [{"id": "CONCERN-01", "theme": "Concern Alpha"}],
                "scope": [],
            }
        )

        self.assertEqual(payload["capabilities"][0]["id"], "CAP-01")
        self.assertEqual(payload["roles"][0]["name"], "Role Alpha")
        self.assertEqual(payload["concerns"][0]["theme"], "Concern Alpha")

    def test_agenda_payload_includes_focus_items(self) -> None:
        from src.orchestrator.graph import _build_elicitation_agenda_review_payload

        payload = _build_elicitation_agenda_review_payload(
            {
                "items": [
                    {
                        "id": "IT-001",
                        "focus_kind": "interaction",
                        "focus_ref": "LINK-01",
                        "perspective": "Role Alpha",
                        "context": "A dependency affects a role.",
                        "seed_question": "What changes when the dependency happens?",
                        "close_when": "Order, consequence, and role impact are clear.",
                        "notes": "Covers dependency evidence.",
                    }
                ]
            }
        )

        self.assertEqual(payload["items"][0]["focus_kind"], "interaction")
        self.assertEqual(payload["items"][0]["focus_ref"], "LINK-01")


if __name__ == "__main__":
    unittest.main()
