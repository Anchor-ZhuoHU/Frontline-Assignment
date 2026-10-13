from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from evals.contracts import ProductionContracts
from evals.conversation import ScriptedModel, run_conversation
from evals.runner import run_suite


REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_DIR = REPO_ROOT / "evals"
SCENARIO = json.loads(
    (EVALS_DIR / "conversation_scenarios" / "agreement_happy_path.json").read_text(
        encoding="utf-8"
    )
)


class RunnerFailureContainmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contracts = ProductionContracts.load(REPO_ROOT)

    def test_broken_prompt_contract_is_trace_failure_not_exception(self) -> None:
        scenario = copy.deepcopy(SCENARIO)
        scenario["script"][0]["expect_system_contains"] = ["missing safety clause"]

        trace = run_conversation(scenario, ScriptedModel(scenario["script"]), self.contracts)

        self.assertEqual(trace["meta"]["status"], "error")
        error = next(e for e in trace["events"] if e["type"] == "runner_error")
        self.assertIn("missing safety clause", error["detail"])

    def test_unknown_tool_is_trace_failure_with_call_evidence(self) -> None:
        scenario = copy.deepcopy(SCENARIO)
        scenario["script"] = [
            {
                "text": "I will do something unsafe.",
                "tool_calls": [
                    {"id": "bad-1", "name": "delete_everything", "args": {}}
                ],
            }
        ]
        scenario["caller_turns"] = ["Hello"]

        trace = run_conversation(scenario, ScriptedModel(scenario["script"]), self.contracts)

        call = next(e for e in trace["events"] if e["type"] == "tool_call")
        self.assertEqual(call["name"], "delete_everything")
        error = next(e for e in trace["events"] if e["type"] == "runner_error")
        self.assertIn("absent from production schemas", error["detail"])

    def test_model_step_limit_stops_repeated_tool_calls(self) -> None:
        scenario = copy.deepcopy(SCENARIO)
        repeated = {
            "text": "Checking again.",
            "tool_calls": [
                {"name": "verify_carrier", "args": {"mc_number": "123456"}}
            ],
        }
        scenario["script"] = [copy.deepcopy(repeated) for _ in range(3)]
        scenario["caller_turns"] = ["My MC is 123456"]
        scenario["limits"] = {"max_model_steps": 2}

        trace = run_conversation(scenario, ScriptedModel(scenario["script"]), self.contracts)

        error = next(e for e in trace["events"] if e["type"] == "runner_error")
        self.assertIn("model step limit", error["detail"])
        self.assertEqual(len([e for e in trace["events"] if e["type"] == "tool_call"]), 2)

    def test_end_call_stops_before_later_caller_turns(self) -> None:
        scenario = copy.deepcopy(SCENARIO)
        scenario["caller_turns"] = ["Goodbye", "This turn must not be sent"]
        scenario["script"] = [
            {
                "text": "Goodbye.",
                "tool_calls": [
                    {"id": "end-now", "name": "end_call", "args": {"reason": "no_agreement"}}
                ],
            }
        ]

        trace = run_conversation(scenario, ScriptedModel(scenario["script"]), self.contracts)

        users = [e["text"] for e in trace["events"] if e["type"] == "user_transcript"]
        self.assertEqual(users, ["Goodbye"])
        self.assertEqual(trace["meta"]["terminated_by"], "end_call")


class RunnerReportTest(unittest.TestCase):
    def test_suite_reports_runner_produced_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_suite(EVALS_DIR, Path(tmp))

        self.assertEqual(report["runner_level"], "text_conversation")
        self.assertGreaterEqual(report["summary"]["scenarios"], 1)
        self.assertEqual(report["results"][0]["trace_source"], "conversation_runner")


if __name__ == "__main__":
    unittest.main()
