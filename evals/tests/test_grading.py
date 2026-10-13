from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evals.grading import grade_trace, load_json
from evals.runner import run_suite


EVALS_DIR = Path(__file__).resolve().parents[1]


class AgreementGraderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = load_json(
            EVALS_DIR / "scenarios" / "agreement_happy_path.json"
        )

    def test_golden_trace_passes_with_tool_call_evidence(self) -> None:
        trace = load_json(EVALS_DIR / "traces" / "agreement_happy_path.json")

        result = grade_trace(self.scenario, trace)

        self.assertTrue(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "agreement.correct_price")
        self.assertEqual(check["status"], "pass")
        self.assertIn("record-1", check["evidence"])

    def test_known_bad_price_fails_with_observed_arguments(self) -> None:
        trace = load_json(
            EVALS_DIR / "traces" / "known_bad" / "agreement_wrong_price.json"
        )

        result = grade_trace(self.scenario, trace)

        self.assertFalse(result["passed"])
        check = next(c for c in result["checks"] if c["check_id"] == "agreement.correct_price")
        self.assertEqual(check["status"], "fail")
        self.assertIn("1700", check["evidence"])

    def test_suite_writes_human_and_machine_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_suite(EVALS_DIR, Path(tmp))

            self.assertEqual(report["summary"]["scenarios"], 3)
            self.assertEqual(report["summary"]["passed"], 3)
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
