from __future__ import annotations

import json
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from evals.contracts import ProductionContracts
from evals.conversation import ConversationModel, ScriptedModel, pass_hat_k, run_conversation
from evals.grading import grade_trace, load_json


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    evidence = (
        [
            "> Evidence source: repeated live GPT-4.1 conversations with scripted caller",
            "> turns, production prompts/schemas, and in-memory fake tools.",
        ]
        if report["execution"]["live_run_occurred"]
        else [
            "> Evidence source: deterministic scripted conversations using the production",
            "> prompt builders and tool schemas with in-memory fake tools. This does not",
            "> measure current live-model or audio quality.",
        ]
    )
    lines = [
        "# Frontline evaluation report",
        "",
        *evidence,
        "",
        f"- Generated: {report['generated_at']}",
        f"- Runner level: {report['runner_level']}",
        (
            "- Live run: yes"
            if report["execution"]["live_run_occurred"]
            else "- Live run: no: no live model request was made for this report"
        ),
        f"- Model: {report['execution']['model']}",
        (
            "- Sampling: temperature={temperature}, frequency_penalty={frequency_penalty}, "
            "presence_penalty={presence_penalty}, seed={seed}".format(**report["execution"])
        ),
        f"- Runs per scenario: {report['execution']['runs_per_scenario']}",
        f"- k: {report['execution']['k']}",
        f"- Gate policy: {report['execution']['gate_policy']}",
        f"- Git commit: {report['reproducibility']['git_commit']}",
        f"- Git tree dirty: {str(report['reproducibility']['git_dirty']).lower()}",
        f"- Evals tree SHA-256: {report['reproducibility']['evals_tree_sha256']}",
        f"- Tool schemas SHA-256: {report['reproducibility']['tool_schemas_sha256']}",
        f"- Scenarios: {summary['scenarios']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
    ]
    if "excluded_infrastructure_runs" in summary:
        lines.extend([
            f"- Infrastructure runs excluded from pass^k: {summary['excluded_infrastructure_runs']}",
            f"- pass^1: {summary['pass_at_1']}",
            f"- pass^{report['execution']['k']}: {summary['pass_at_k']}",
        ])
    lines.extend([
        "",
        "## Rendered prompt hashes",
        "",
    ])
    for scenario_id, hashes in report["reproducibility"]["prompt_sha256"].items():
        rendered = ", ".join(f"{name}={value}" for name, value in hashes.items())
        lines.append(f"- {scenario_id}: {rendered}")
    lines.extend([
        "",
        "## Scenario results",
        "",
    ])
    for result in report["results"]:
        status = (
            "INFRASTRUCTURE_ERROR"
            if result.get("excluded_from_pass_k")
            else "PASS" if result["passed"] else "FAIL"
        )
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
        json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    (output_dir / "report.md").write_text(_markdown(report), encoding="utf-8")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={repo_root}", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_dirty(repo_root: Path) -> bool:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={repo_root}", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(completed.stdout.strip())


def _evals_tree_hash(evals_dir: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted(
        path for path in evals_dir.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and "results" not in path.relative_to(evals_dir).parts
        and path.suffix != ".pyc"
    )
    for path in paths:
        digest.update(path.relative_to(evals_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _reproducibility(
    repo_root: Path,
    contracts: ProductionContracts,
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt_hashes: dict[str, dict[str, str]] = {}
    for scenario in scenarios:
        hashes = {
            "initial": _sha256(contracts.initial_prompt(org_name=scenario.get("org_name")))
        }
        uses_load = any(
            call.get("name") == "get_load_context"
            for step in scenario.get("script", [])
            for call in step.get("tool_calls", [])
        )
        if uses_load:
            hashes["negotiation"] = _sha256(
                contracts.negotiation_prompt(scenario["fixtures"]["load"])
            )
        prompt_hashes[scenario["id"]] = hashes
    canonical_schemas = json.dumps(
        contracts.room1_tools, sort_keys=True, separators=(",", ":")
    )
    return {
        "git_commit": _git_commit(repo_root),
        "git_dirty": _git_dirty(repo_root),
        "evals_tree_sha256": _evals_tree_hash(repo_root / "evals"),
        "tool_schemas_sha256": _sha256(canonical_schemas),
        "prompt_sha256": prompt_hashes,
        "hash_algorithm": "sha256",
    }


def _write_trace(output_dir: Path, filename: str, trace: dict[str, Any]) -> None:
    persisted = dict(trace)
    schemas = persisted.pop("tool_schemas", [])
    persisted["tool_schemas_sha256"] = _sha256(
        json.dumps(schemas, sort_keys=True, separators=(",", ":"))
    )
    persisted["tool_schema_count"] = len(schemas)
    persisted["rendered_prompts"] = [
        {
            "kind": prompt["kind"],
            "sha256": _sha256(prompt["content"]),
            "characters": len(prompt["content"]),
        }
        for prompt in trace.get("rendered_prompts", [])
    ]
    persisted["events"] = []
    for event in trace.get("events", []):
        compact_event = dict(event)
        prompt = compact_event.pop("prompt", None)
        if prompt is not None:
            compact_event["prompt_sha256"] = _sha256(prompt)
            compact_event["prompt_characters"] = len(prompt)
        persisted["events"].append(compact_event)
    trace_dir = output_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / filename).write_text(
        json.dumps(persisted, separators=(",", ":")) + "\n", encoding="utf-8"
    )


def run_suite(
    evals_dir: Path,
    output_dir: Path,
    scenario_dir: Path | None = None,
) -> dict[str, Any]:
    results = []
    scenario_definitions = []
    contracts = ProductionContracts.load(evals_dir.parent)
    scenario_dir = scenario_dir or evals_dir / "conversation_scenarios"
    for scenario_path in sorted(scenario_dir.glob("*.json")):
        scenario = load_json(scenario_path)
        scenario_definitions.append(scenario)
        trace = run_conversation(scenario, ScriptedModel(scenario["script"]), contracts)
        _write_trace(output_dir, f"{scenario['id']}.json", trace)
        results.append(grade_trace(scenario, trace))

    passed = sum(result["passed"] for result in results)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runner_level": "text_conversation",
        "reproducibility": {
            **_reproducibility(evals_dir.parent, contracts, scenario_definitions),
            "trace_files": [f"traces/{scenario['id']}.json" for scenario in scenario_definitions],
        },
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
            "scenarios": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
        "results": results,
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
    scenario_definitions = []
    runs_by_scenario: dict[str, list[bool]] = {}
    for scenario_path in sorted((evals_dir / "conversation_scenarios").glob("*.json")):
        scenario = load_json(scenario_path)
        scenario_definitions.append(scenario)
        outcomes = []
        for run_index in range(1, runs + 1):
            model = model_factory()
            trace = run_conversation(scenario, model, contracts)
            _write_trace(
                output_dir, f"{scenario['id']}.run-{run_index}.json", trace
            )
            result = grade_trace(scenario, trace)
            result["run_index"] = run_index
            result["model_metadata"] = trace["meta"].get("model_metadata", {})
            infrastructure_error = trace["meta"].get("status") == "infrastructure_error"
            result["excluded_from_pass_k"] = infrastructure_error
            results.append(result)
            if not infrastructure_error:
                outcomes.append(result["passed"])
        runs_by_scenario[scenario["id"]] = outcomes
    included = [result for result in results if not result["excluded_from_pass_k"]]
    passed = sum(result["passed"] for result in included)
    excluded = len(results) - len(included)
    enough_for_k = all(len(values) >= k for values in runs_by_scenario.values())
    have_every_scenario = all(values for values in runs_by_scenario.values())
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runner_level": "text_conversation",
        "reproducibility": {
            **_reproducibility(evals_dir.parent, contracts, scenario_definitions),
            "trace_files": [
                f"traces/{scenario['id']}.run-{run_index}.json"
                for scenario in scenario_definitions
                for run_index in range(1, runs + 1)
            ],
        },
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
            "failed": len(included) - passed,
            "excluded_infrastructure_runs": excluded,
            "included_behavioral_runs": len(included),
            "pass_at_1": (
                sum(sum(values) / len(values) for values in runs_by_scenario.values())
                / len(runs_by_scenario)
                if have_every_scenario else None
            ),
            "pass_at_k": pass_hat_k(runs_by_scenario, k) if enough_for_k else None,
            "pass_at_k_status": "computed" if enough_for_k else "insufficient_valid_runs",
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
