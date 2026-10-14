from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from evals.contracts import ProductionContracts
from evals.grading import grade_trace, load_json
from evals.runner import run_suite


EVALS_DIR = Path(__file__).resolve().parents[1]


class AgreementGraderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = load_json(
            EVALS_DIR / "scenarios" / "agreement_happy_path.json"
        )
        self.contracts = ProductionContracts.load(EVALS_DIR.parent)

    def grade_fixture(self, trace: dict) -> dict:
        trace = copy.deepcopy(trace)
        trace["tool_schemas"] = self.contracts.room1_tools
        return grade_trace(self.scenario, trace)

    def test_golden_trace_passes_with_tool_call_evidence(self) -> None:
        trace = load_json(EVALS_DIR / "traces" / "agreement_happy_path.json")

        result = self.grade_fixture(trace)

        self.assertTrue(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "agreement.correct_price")
        self.assertEqual(check["status"], "pass")
        self.assertIn("record-1", check["evidence"])

    def test_known_bad_price_fails_with_observed_arguments(self) -> None:
        trace = load_json(
            EVALS_DIR / "traces" / "known_bad" / "agreement_wrong_price.json"
        )

        result = self.grade_fixture(trace)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "agreement.correct_price")
        self.assertEqual(check["status"], "fail")
        self.assertIn("1700", check["evidence"])

    def test_bad_first_write_is_not_hidden_by_later_correct_write(self) -> None:
        trace = load_json(EVALS_DIR / "traces" / "agreement_happy_path.json")
        trace = copy.deepcopy(trace)
        correct_index = next(
            index
            for index, event in enumerate(trace["events"])
            if event.get("type") == "tool_call"
            and event.get("name") == "record_agreement"
        )
        trace["events"].insert(
            correct_index,
            {
                "t_ms": 250,
                "type": "tool_call",
                "id": "record-bad-first",
                "name": "record_agreement",
                "args": {"agreed_price": 1700},
            },
        )

        result = self.grade_fixture(trace)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "agreement.correct_price")
        self.assertIn("record-bad-first", check["evidence"])
        self.assertIn("1700", check["evidence"])

    def test_suite_writes_human_and_machine_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_suite(EVALS_DIR, Path(tmp))

            self.assertEqual(report["summary"]["scenarios"], 6)
            self.assertEqual(report["summary"]["passed"], 6)
            self.assertTrue((Path(tmp) / "report.json").is_file())
            markdown = (Path(tmp) / "report.md").read_text(encoding="utf-8")
            self.assertIn("agreement_happy_path", markdown)
            self.assertIn("scripted conversations", markdown.lower())
            persisted = json.loads(
                (Path(tmp) / "report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(persisted, report)


if __name__ == "__main__":
    unittest.main()
