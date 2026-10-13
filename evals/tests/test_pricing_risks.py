from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from evals.contracts import ProductionContracts
from evals.conversation import ScriptedModel, run_conversation
from evals.grading import grade_trace


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO_ROOT / "evals" / "conversation_scenarios"


def load_scenario(name: str) -> dict:
    return json.loads((SCENARIO_DIR / name).read_text(encoding="utf-8"))


def result_for(scenario: dict, contracts: ProductionContracts) -> dict:
    trace = run_conversation(scenario, ScriptedModel(scenario["script"]), contracts)
    return grade_trace(scenario, trace)


class PricingRiskGraderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contracts = ProductionContracts.load(REPO_ROOT)

    def test_above_ceiling_bid_is_stored_as_above_max(self) -> None:
        scenario = load_scenario("above_ceiling_bid.json")

        result = result_for(scenario, self.contracts)

        self.assertTrue(result["passed"])

    def test_agreement_above_ceiling_without_above_max_fails(self) -> None:
        scenario = load_scenario("above_ceiling_bid.json")
        unsafe = copy.deepcopy(scenario)
        record = next(
            call
            for step in unsafe["script"]
            for call in step.get("tool_calls", [])
            if call["name"] == "record_agreement"
        )
        record["args"]["above_max"] = False

        result = result_for(unsafe, self.contracts)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "agreement.ceiling_policy")
        self.assertEqual(check["status"], "fail")
        self.assertIn("1900", check["evidence"])
        self.assertIn("1800", check["evidence"])

    def test_below_goal_counter_moves_down(self) -> None:
        scenario = load_scenario("below_goal_offer.json")

        result = result_for(scenario, self.contracts)

        self.assertTrue(result["passed"])

    def test_countering_up_from_below_goal_offer_fails(self) -> None:
        scenario = load_scenario("below_goal_offer.json")
        unsafe = copy.deepcopy(scenario)
        counter = next(
            step for step in unsafe["script"] if "$1350" in step.get("text", "")
        )
        counter["text"] = "Could you do $1500?"

        result = result_for(unsafe, self.contracts)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "negotiation.no_counter_up")
        self.assertEqual(check["status"], "fail")
        self.assertIn("1500", check["evidence"])
        self.assertIn("1400", check["evidence"])


if __name__ == "__main__":
    unittest.main()
