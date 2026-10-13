from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _tool_calls(trace: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [
        event
        for event in trace.get("events", [])
        if event.get("type") == "tool_call" and event.get("name") == name
    ]


def _grade_tool_called(
    check: dict[str, Any], trace: dict[str, Any]
) -> dict[str, str]:
    expected = check.get("args", {})
    calls = _tool_calls(trace, check["name"])
    for call in calls:
        observed = call.get("args", {})
        if all(observed.get(key) == value for key, value in expected.items()):
            return {
                "check_id": check["id"],
                "status": "pass",
                "severity": check["severity"],
                "evidence": f"tool call {call.get('id', '<missing id>')} args={observed}",
            }
    observed_calls = [call.get("args", {}) for call in calls]
    return {
        "check_id": check["id"],
        "status": "fail",
        "severity": check["severity"],
        "evidence": f"expected subset {expected}; observed {observed_calls or 'no call'}",
    }


def grade_trace(
    scenario: dict[str, Any], trace: dict[str, Any]
) -> dict[str, Any]:
    if trace.get("scenario_id") != scenario.get("id"):
        raise ValueError(
            f"trace scenario_id {trace.get('scenario_id')!r} does not match "
            f"scenario {scenario.get('id')!r}"
        )

    checks = []
    for check in scenario.get("expected", {}).get("checks", []):
        if check.get("type") != "tool_called":
            raise ValueError(f"unsupported check type: {check.get('type')!r}")
        checks.append(_grade_tool_called(check, trace))

    blocking_failures = [
        check
        for check in checks
        if check["status"] != "pass" and check["severity"] in {"critical", "major"}
    ]
    return {
        "scenario_id": scenario["id"],
        "passed": not blocking_failures,
        "checks": checks,
    }

