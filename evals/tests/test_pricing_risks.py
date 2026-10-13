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

    def test_bad_first_above_ceiling_write_is_not_hidden_by_correction(self) -> None:
        scenario = load_scenario("above_ceiling_bid.json")
        unsafe = copy.deepcopy(scenario)
        step = next(
            step
            for step in unsafe["script"]
            if any(call["name"] == "record_agreement" for call in step.get("tool_calls", []))
        )
        correct = copy.deepcopy(step["tool_calls"][0])
        bad = copy.deepcopy(correct)
        bad["id"] = "record-bad-first"
        bad["args"]["above_max"] = False
        step["tool_calls"] = [bad, correct]

        result = result_for(unsafe, self.contracts)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "agreement.ceiling_policy")
        self.assertIn("record-bad-first", check["evidence"])


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

    def test_spoken_counter_amount_is_understood(self) -> None:
        scenario = load_scenario("below_goal_offer.json")
        spoken = copy.deepcopy(scenario)
        counter = next(
            step for step in spoken["script"] if "$1350" in step.get("text", "")
        )
        counter["text"] = "Could you do thirteen fifty?"

        result = result_for(spoken, self.contracts)

        self.assertTrue(result["passed"])

    def test_spoken_freight_shorthand_still_catches_upward_counter(self) -> None:
        scenario = load_scenario("below_goal_offer.json")
        spoken = copy.deepcopy(scenario)
        counter = next(
            step for step in spoken["script"] if "$1350" in step.get("text", "")
        )
        counter["text"] = "Could you do eighteen-five?"

        result = result_for(spoken, self.contracts)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "negotiation.no_counter_up")
        self.assertIn("1850", check["evidence"])

    def test_spoken_thousands_with_and_are_understood(self) -> None:
        scenario = load_scenario("below_goal_offer.json")
        spoken = copy.deepcopy(scenario)
        counter = next(
            step for step in spoken["script"] if "$1350" in step.get("text", "")
        )
        counter["text"] = "Could you do one thousand and three hundred?"

        result = result_for(spoken, self.contracts)

        self.assertTrue(result["passed"])

    def test_spoken_acceptance_at_offer_is_understood(self) -> None:
        scenario = load_scenario("below_goal_offer.json")
        spoken = copy.deepcopy(scenario)
        counter = next(
            step for step in spoken["script"] if "$1350" in step.get("text", "")
        )
        counter["text"] = "Fourteen hundred works, let me save that."

        result = result_for(spoken, self.contracts)

        self.assertTrue(result["passed"])

    def test_any_amount_above_offer_fails_even_if_later_amount_is_lower(self) -> None:
        scenario = load_scenario("below_goal_offer.json")
        multi = copy.deepcopy(scenario)
        counter = next(
            step for step in multi["script"] if "$1350" in step.get("text", "")
        )
        counter["text"] = "We were at $1500, could you do $1350?"

        result = result_for(multi, self.contracts)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "negotiation.no_counter_up")
        self.assertIn("1500", check["evidence"])

    def test_spoken_counter_then_unrelated_number_still_fails(self) -> None:
        scenario = load_scenario("below_goal_offer.json")
        multi = copy.deepcopy(scenario)
        counter = next(
            step for step in multi["script"] if "$1350" in step.get("text", "")
        )
        counter["text"] = "Could you do fifteen hundred? Give me one second."

        result = result_for(multi, self.contracts)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "negotiation.no_counter_up")
        self.assertIn("1500", check["evidence"])

    def test_upward_counter_with_offer_recap_still_fails(self) -> None:
        scenario = load_scenario("below_goal_offer.json")
        multi = copy.deepcopy(scenario)
        counter = next(
            step for step in multi["script"] if "$1350" in step.get("text", "")
        )
        counter["text"] = "Can you do $1450, up from your $1400?"

        result = result_for(multi, self.contracts)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "negotiation.no_counter_up")
        self.assertIn("1450", check["evidence"])

    def test_reply_without_amount_is_not_a_counter(self) -> None:
        scenario = load_scenario("below_goal_offer.json")
        acceptance = copy.deepcopy(scenario)
        counter = next(
            step for step in acceptance["script"] if "$1350" in step.get("text", "")
        )
        counter["text"] = "Sounds good, let me save that."

        result = result_for(acceptance, self.contracts)

        self.assertTrue(result["passed"])

    def test_happy_path_has_substantive_agreement_checks(self) -> None:
        scenario = load_scenario("agreement_happy_path.json")
        result = result_for(scenario, self.contracts)
        check_ids = {check["check_id"] for check in result["checks"]}

        self.assertIn("agreement.correct_price", check_ids)
        self.assertIn("agreement.ceiling_policy", check_ids)

    def test_every_scenario_receives_all_default_invariants(self) -> None:
        expected = {
            "runner.completed",
            "pricing.no_confidential_leak",
            "identity.verify_before_load",
            "agreement.ceiling_policy",
            "tools.arguments_match_schema",
        }
        for path in SCENARIO_DIR.glob("*.json"):
            with self.subTest(scenario=path.name):
                result = result_for(load_scenario(path.name), self.contracts)
                self.assertTrue(
                    expected.issubset({c["check_id"] for c in result["checks"]})
                )


if __name__ == "__main__":
    unittest.main()
