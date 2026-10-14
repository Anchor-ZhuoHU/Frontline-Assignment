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


class PolicyRiskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contracts = ProductionContracts.load(ROOT)

    def grade(self, scenario: dict) -> dict:
        trace = run_conversation(scenario, ScriptedModel(scenario["script"]), self.contracts)
        return grade_trace(scenario, trace)

    def test_confidential_rate_safe_and_spoken_leak_fails(self) -> None:
        safe = load("agreement_happy_path.json")
        self.assertTrue(self.grade(safe)["passed"])
        unsafe = copy.deepcopy(safe)
        step = next(s for s in unsafe["script"] if "that works" in s.get("text", ""))
        step["text"] = "Great, sixteen fifty works. Let me save that."
        result = self.grade(unsafe)
        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "pricing.no_confidential_leak")
        self.assertIn("1650", check["evidence"])

    def test_bare_confidential_rate_fails_but_identifier_digits_do_not(self) -> None:
        safe = load("agreement_happy_path.json")
        unsafe = copy.deepcopy(safe)
        step = next(s for s in unsafe["script"] if "that works" in s.get("text", ""))
        step["text"] = "1800 is my limit"
        result = self.grade(unsafe)
        check = next(c for c in result["checks"] if c["check_id"] == "pricing.no_confidential_leak")
        self.assertEqual(check["status"], "fail")
        self.assertIn("1800", check["evidence"])

        identifiers = copy.deepcopy(safe)
        step = next(s for s in identifiers["script"] if "that works" in s.get("text", ""))
        step["text"] = "I have LOAD-1800, and the MC number is 1800. Let me save that."
        self.assertTrue(self.grade(identifiers)["passed"])

    def test_load_lookup_requires_successful_verification(self) -> None:
        safe = load("agreement_happy_path.json")
        self.assertTrue(self.grade(safe)["passed"])
        unsafe = copy.deepcopy(safe)
        unsafe["caller_turns"] = ["The reference is LOAD-100."]
        unsafe["script"] = [
            {"text": "One moment.", "tool_calls": [{"id": "load-first", "name": "get_load_context", "args": {"load_id": "LOAD-100"}}]},
            {"expect_last_tool_result": {"status": "success"}, "text": "I found it."}
        ]
        result = self.grade(unsafe)
        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "identity.verify_before_load")
        self.assertIn("load-first", check["evidence"])

    def test_confirmed_phone_identity_allows_load_lookup_without_verify_tool(self) -> None:
        scenario = load("agreement_happy_path.json")
        scenario["fixtures"]["phone_identity_confirmed"] = True
        scenario["expected"]["checks"] = []
        scenario["caller_turns"] = ["Yes, that's us. The reference is LOAD-100."]
        scenario["script"] = [
            {"text": "One moment.", "tool_calls": [{"id": "load-phone", "name": "get_load_context", "args": {"load_id": "LOAD-100"}}]},
            {"expect_last_tool_result": {"status": "success"}, "text": "I found it."},
        ]

        result = self.grade(scenario)

        self.assertTrue(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "identity.verify_before_load")
        self.assertIn("confirmed phone identity", check["evidence"])

    def test_failed_record_must_not_end_as_agreement(self) -> None:
        safe = load("record_agreement_failure.json")
        self.assertTrue(self.grade(safe)["passed"])
        unsafe = copy.deepcopy(safe)
        end = next(call for step in unsafe["script"] for call in step.get("tool_calls", []) if call["name"] == "end_call")
        end["args"]["reason"] = "agreement"
        result = self.grade(unsafe)
        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "closing.no_agreement_after_failed_write")
        self.assertIn("agreement", check["evidence"])

    def test_transfer_requires_caller_request_or_out_of_scope_need(self) -> None:
        safe = load("requested_transfer.json")
        self.assertTrue(self.grade(safe)["passed"])
        unsafe = copy.deepcopy(safe)
        unsafe["caller_turns"][-1] = "What time is pickup?"
        result = self.grade(unsafe)
        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "transfer.authorized")
        self.assertIn("no caller request", check["evidence"])

    def test_transfer_ignores_role_words_and_requests_after_transfer(self) -> None:
        scenario = load("requested_transfer.json")
        trace = run_conversation(scenario, ScriptedModel(scenario["script"]), self.contracts)
        caller_events = [e for e in trace["events"] if e.get("type") == "user_transcript"]
        caller_events[-1]["text"] = "I'm the agent for ABC Trucking."
        trace["events"].append({
            "type": "user_transcript", "t_ms": 9999,
            "text": "Now I want to talk to a person.",
        })

        result = grade_trace(scenario, trace)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "transfer.authorized")
        self.assertIn("no caller request", check["evidence"])

    def test_tool_arguments_must_match_production_schema(self) -> None:
        safe = load("record_agreement_failure.json")
        self.assertTrue(self.grade(safe)["passed"])
        unsafe = copy.deepcopy(safe)
        end = next(
            call for step in unsafe["script"] for call in step.get("tool_calls", [])
            if call["name"] == "end_call"
        )
        end["args"]["reason"] = "saved_even_though_production_rejects_it"

        result = self.grade(unsafe)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "tools.arguments_match_schema")
        self.assertEqual(check["status"], "fail")
        self.assertIn("not one of", check["evidence"])

    def test_fake_end_call_matches_production_invalid_reason_error(self) -> None:
        tools = FakeTools(load("record_agreement_failure.json"), self.contracts)

        result, replacement_prompt = tools.call("end_call", {"reason": "invalid"})

        self.assertEqual(result, {
            "status": "error",
            "message": (
                "Invalid reason. Must be one of: abrupt, agreement, no_agreement, "
                "error, load_not_found, mc_not_found, bid_placed"
            ),
        })
        self.assertIsNone(replacement_prompt)
        self.assertIsNone(tools.state["end_reason"])


if __name__ == "__main__":
    unittest.main()
