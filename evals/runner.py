from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from evals.contracts import ProductionContracts
from evals.conversation import ConversationModel, ScriptedModel, pass_hat_k, run_conversation
from evals.grading import grade_trace, load_json


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Frontline offline evaluation report",
        "",
        "> Evidence source: deterministic scripted conversations using the production",
        "> prompt builders and tool schemas with in-memory fake tools. This does not",
        "> measure current live-model or audio quality.",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Runner level: {report['runner_level']}",
        (
            "- Live run: yes"
            if report["execution"]["live_run_occurred"]
            else "- Live run: no — no live model request was made for this report"
        ),
        f"- Model: {report['execution']['model']}",
        f"- Runs per scenario: {report['execution']['runs_per_scenario']}",
        f"- Gate policy: {report['execution']['gate_policy']}",
        f"- Scenarios: {summary['scenarios']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        "",
        "## Scenario results",
        "",
    ]
    for result in report["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        run_suffix = f" (run {result['run_index']})" if "run_index" in result else ""
        lines.append(f"### {result['scenario_id']}{run_suffix}: {status}")
        lines.append("")
        for check in result["checks"]:
            lines.append(
                f"- {check['check_id']} [{check['severity']}]: "
                f"{check['status']}, {check['evidence']}"
            )
        lines.append("")
    labels = {
        "live_model_behavior": "Live GPT-4.1 behavior and nondeterminism.",
        "speech_recognition_and_synthesis": "Speech recognition and synthesis quality.",
        "caller_heard_latency_and_turn_taking": "Caller-heard latency, interruptions, and turn-taking.",
        "external_provider_integrations": "Daily, Supabase, carrier lookup, quote, Slack, and broker-transfer integrations.",
    }
    lines.extend(["## Not measured", ""])
    lines.extend(f"- {labels[item]}" for item in report["not_measured"])
    lines.append("")
    return "\n".join(lines)


def _write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "report.md").write_text(_markdown(report), encoding="utf-8")


def run_suite(evals_dir: Path, output_dir: Path) -> dict[str, Any]:
    scenarios = []
    contracts = ProductionContracts.load(evals_dir.parent)
    for scenario_path in sorted(
        (evals_dir / "conversation_scenarios").glob("*.json")
    ):
        scenario = load_json(scenario_path)
        trace = run_conversation(scenario, ScriptedModel(scenario["script"]), contracts)
        scenarios.append(grade_trace(scenario, trace))

    passed = sum(result["passed"] for result in scenarios)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runner_level": "text_conversation",
        "execution": {
            "live_run_occurred": False,
            "model": "scripted",
            "temperature": None,
            "frequency_penalty": None,
            "presence_penalty": None,
            "seed": None,
            "runs_per_scenario": 1,
            "k": None,
            "gate_policy": "gating deterministic critical and major checks",
        },
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

    _write_report(report, output_dir)
    return report


def run_live_suite(
    evals_dir: Path,
    output_dir: Path,
    model_factory: Callable[[], ConversationModel],
    runs: int,
    k: int,
) -> dict[str, Any]:
    if runs < 1 or k < 1 or k > runs:
        raise ValueError("live runs must satisfy runs >= k >= 1")
    contracts = ProductionContracts.load(evals_dir.parent)
    results = []
    runs_by_scenario: dict[str, list[bool]] = {}
    for scenario_path in sorted((evals_dir / "conversation_scenarios").glob("*.json")):
        scenario = load_json(scenario_path)
        outcomes = []
        for run_index in range(1, runs + 1):
            model = model_factory()
            trace = run_conversation(scenario, model, contracts)
            result = grade_trace(scenario, trace)
            result["run_index"] = run_index
            result["model_metadata"] = trace["meta"].get("model_metadata", {})
            results.append(result)
            outcomes.append(result["passed"])
        runs_by_scenario[scenario["id"]] = outcomes
    passed = sum(result["passed"] for result in results)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runner_level": "text_conversation",
        "execution": {
            "live_run_occurred": True,
            "model": "gpt-4.1",
            "temperature": 0.7,
            "frequency_penalty": 0.6,
            "presence_penalty": 0.5,
            "seed": None,
            "runs_per_scenario": runs,
            "k": k,
            "gate_policy": "report-only live behavioral evidence",
        },
        "summary": {
            "scenarios": len(runs_by_scenario),
            "runs": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "pass_at_1": sum(sum(values) / len(values) for values in runs_by_scenario.values()) / len(runs_by_scenario),
            "pass_at_k": pass_hat_k(runs_by_scenario, k),
        },
        "results": results,
        "not_measured": [
            "speech_recognition_and_synthesis",
            "caller_heard_latency_and_turn_taking",
            "external_provider_integrations",
        ],
    }
    _write_report(report, output_dir)
    return report
