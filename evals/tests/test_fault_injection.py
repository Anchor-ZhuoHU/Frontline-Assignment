from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from evals.contracts import ProductionContracts
from evals.conversation import FakeTools, ScriptedModel, run_conversation
from evals.grading import grade_trace


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "evals" / "conversation_scenarios"


def load(name: str) -> dict:
    return json.loads((SCENARIOS / name).read_text(encoding="utf-8"))


class FaultInjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contracts = ProductionContracts.load(ROOT)

    def grade(self, scenario: dict) -> dict:
        trace = run_conversation(scenario, ScriptedModel(scenario["script"]), self.contracts)
        return grade_trace(scenario, trace)

    def test_carrier_error_and_load_failure_preserve_production_shapes(self) -> None:
        scenario = load("agreement_happy_path.json")
        scenario["fixtures"]["tool_results"] = {
            "verify_carrier": [
                {"status": "error", "message": "carrier service unavailable"}
            ],
            "get_load_context": [
                {"status": "error", "message": "No load found with ID: LOAD-404"}
            ],
        }
        tools = FakeTools(scenario, self.contracts)

        carrier, carrier_prompt = tools.call("verify_carrier", {"mc_number": "123456"})
        load_result, load_prompt = tools.call("get_load_context", {"load_id": "LOAD-404"})

        self.assertEqual(carrier, {"status": "error", "message": "carrier service unavailable"})
        self.assertEqual(load_result, {"status": "error", "message": "No load found with ID: LOAD-404"})
        self.assertIsNone(carrier_prompt)
        self.assertIsNone(load_prompt)
        self.assertIsNone(tools.state["verified_carrier"])
        self.assertIsNone(tools.state["loaded_reference"])

    def test_third_not_found_ends_with_mc_not_found(self) -> None:
        result = self.grade(load("third_mc_not_found.json"))

        self.assertTrue(result["passed"])
        close = next(c for c in result["checks"] if c["check_id"] == "closing.third_mc_not_found")
        self.assertEqual(close["status"], "pass")
        grounding = next(c for c in result["checks"] if c["check_id"] == "pricing.no_rate_before_load")
        self.assertEqual(grounding["status"], "pass")

    def test_mc_not_found_close_before_third_miss_fails(self) -> None:
        base = load("third_mc_not_found.json")
        for misses in (1, 2):
            with self.subTest(misses=misses):
                scenario = copy.deepcopy(base)
                scenario["caller_turns"] = scenario["caller_turns"][:misses]
                scenario["fixtures"]["tool_results"]["verify_carrier"] = (
                    scenario["fixtures"]["tool_results"]["verify_carrier"][:misses]
                )
                script = scenario["script"][: misses * 2]
                script[-1]["text"] = "Sorry, I can't verify that MC."
                script[-1]["tool_calls"] = [
                    {"id": f"end-early-{misses}", "name": "end_call", "args": {"reason": "mc_not_found"}}
                ]
                scenario["script"] = script

                result = self.grade(scenario)

                self.assertFalse(result["passed"])
                check = next(c for c in result["checks"] if c["check_id"] == "closing.third_mc_not_found")
                self.assertIn(f"followed {misses} not_found", check["evidence"])

    def test_caller_turn_between_third_miss_and_close_fails(self) -> None:
        scenario = load("third_mc_not_found.json")
        trace = run_conversation(scenario, ScriptedModel(scenario["script"]), self.contracts)
        close_index = next(
            i for i, event in enumerate(trace["events"])
            if event.get("type") == "tool_call" and event.get("name") == "end_call"
        )
        trace["events"].insert(
            close_index,
            {"t_ms": 999, "type": "user_transcript", "text": "Wait, let me try again."},
        )

        result = grade_trace(scenario, trace)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "closing.third_mc_not_found")
        self.assertIn("caller_turn_after_last_not_found=True", check["evidence"])

    def test_money_quote_before_successful_load_lookup_fails(self) -> None:
        for quote in ["I can offer $1500.", "I can offer fifteen hundred dollars."]:
            with self.subTest(quote=quote):
                scenario = load("agreement_happy_path.json")
                scenario["script"][0]["text"] = quote
                result = self.grade(scenario)
                self.assertFalse(result["passed"])
                check = next(c for c in result["checks"] if c["check_id"] == "pricing.no_rate_before_load")
                self.assertEqual(check["status"], "fail")
                self.assertIn(quote, check["evidence"])

    def test_non_money_numbers_before_load_do_not_fail(self) -> None:
        scenario = load("agreement_happy_path.json")
        safe = copy.deepcopy(scenario)
        safe["script"][0]["text"] = (
            "MC one two three four five six. One moment while I check reference 2026."
        )

        result = self.grade(safe)

        self.assertTrue(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "pricing.no_rate_before_load")
        self.assertEqual(check["status"], "pass")


if __name__ == "__main__":
    unittest.main()
