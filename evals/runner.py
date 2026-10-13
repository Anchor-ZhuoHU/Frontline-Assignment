from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.grading import grade_trace, load_json


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Frontline offline evaluation report",
        "",
        "> Evidence source: reviewed fixture replay. This validates the evaluation",
        "> harness and expected outcomes, not current live-model or audio quality.",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Runner level: {report['runner_level']}",
        f"- Scenarios: {summary['scenarios']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        "",
        "## Scenario results",
        "",
    ]
    for result in report["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        lines.append(f"### {result['scenario_id']}: {status}")
        lines.append("")
        for check in result["checks"]:
            lines.append(
                f"- {check['check_id']} [{check['severity']}]: "
                f"{check['status']}, {check['evidence']}"
            )
        lines.append("")
    lines.extend(
        [
            "## Not measured",
            "",
            "- Live GPT-4.1 behavior and nondeterminism.",
            "- Speech recognition and synthesis quality.",
            "- Caller-heard latency, interruptions, and turn-taking.",
            "- Daily, Supabase, carrier lookup, quote, Slack, and broker-transfer integrations.",
            "",
        ]
    )
    return "\n".join(lines)


def run_suite(evals_dir: Path, output_dir: Path) -> dict[str, Any]:
    scenarios = []
    for scenario_path in sorted((evals_dir / "scenarios").glob("*.json")):
        scenario = load_json(scenario_path)
        trace_path = evals_dir / scenario["fixture_trace"]
        scenarios.append(grade_trace(scenario, load_json(trace_path)))

    passed = sum(result["passed"] for result in scenarios)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runner_level": "offline_fixture_replay",
        "summary": {
            "scenarios": len(scenarios),
            "passed": passed,
            "failed": len(scenarios) - passed,
        },
        "results": scenarios,
        "not_measured": [
            "live_model_behavior",
            "speech_recognition_and_synthesis",
            "caller_heard_latency_and_turn_taking",
            "external_provider_integrations",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    return report

