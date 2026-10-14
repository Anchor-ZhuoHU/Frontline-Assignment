from __future__ import annotations

import json
import unittest
from pathlib import Path

from evals.conversation import ScriptedModel, pass_hat_k, run_conversation
from evals.contracts import ProductionContracts


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_PATH = (
    REPO_ROOT / "evals" / "conversation_scenarios" / "agreement_happy_path.json"
)


class ProductionContractTest(unittest.TestCase):
    def test_loads_real_prompt_and_room_one_tool_schemas(self) -> None:
        contracts = ProductionContracts.load(REPO_ROOT)

        initial = contracts.initial_prompt(org_name="KCH")
        self.assertIn("can I get your MC number?", initial)
        self.assertIn("MANDATORY TOOL-CALL RULE", initial)
        self.assertEqual(
            [tool["function"]["name"] for tool in contracts.room1_tools],
            [
                "verify_carrier",
                "get_load_context",
                "record_agreement",
                "end_call",
                "transfer_to_human",
            ],
        )
        record = next(
            tool
            for tool in contracts.room1_tools
            if tool["function"]["name"] == "record_agreement"
        )
        self.assertEqual(
            record["function"]["parameters"]["required"], ["agreed_price"]
        )


class ConversationRunnerTest(unittest.TestCase):
    def test_scripted_model_runs_real_prompt_transition_with_fake_tools(self) -> None:
        scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
        contracts = ProductionContracts.load(REPO_ROOT)
        model = ScriptedModel(scenario["script"])

        trace = run_conversation(scenario, model, contracts)

        self.assertEqual(trace["meta"]["model"], "scripted")
        self.assertTrue(trace["meta"]["production_prompt_loaded"])
        self.assertTrue(trace["meta"]["production_tool_schemas_loaded"])
        self.assertEqual(trace["end_state"]["agreement"]["agreed_price"], 1650)
        self.assertEqual(trace["end_state"]["end_reason"], "agreement")
        self.assertEqual(trace["end_state"]["external_side_effects"], [])

        calls = [e for e in trace["events"] if e["type"] == "tool_call"]
        self.assertEqual(
            [event["name"] for event in calls],
            ["verify_carrier", "get_load_context", "record_agreement", "end_call"],
        )
        swaps = [e for e in trace["events"] if e["type"] == "system_prompt_changed"]
        self.assertEqual(len(swaps), 1)
        self.assertIn("CONFIDENTIAL PRICING", swaps[0]["prompt"])
        self.assertIn("Internal Ceiling", swaps[0]["prompt"])

        tool_results = [e for e in trace["events"] if e["type"] == "tool_result"]
        self.assertEqual(len(tool_results), 4)
        self.assertGreaterEqual(model.requests_with_tool_results, 3)

    def test_pass_hat_k_uses_per_scenario_combinations(self) -> None:
        self.assertAlmostEqual(pass_hat_k({"s1": [True, True, False, False]}, 2), 1 / 6)
        self.assertAlmostEqual(
            pass_hat_k({"s1": [True, True, False], "s2": [True, True, True]}, 2),
            2 / 3,
        )


if __name__ == "__main__":
    unittest.main()
