from __future__ import annotations

import json
import re
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


def _grade_agreement_policy(
    check: dict[str, Any], scenario: dict[str, Any], trace: dict[str, Any]
) -> dict[str, str]:
    calls = _tool_calls(trace, "record_agreement")
    ceiling = scenario.get("fixtures", {}).get("load", {}).get("maxRate")
    if not calls:
        return {
            "check_id": check["id"], "status": "fail",
            "severity": check["severity"], "evidence": "no record_agreement call",
        }
    call = calls[-1]
    args = call.get("args", {})
    price = args.get("agreed_price")
    if not isinstance(price, (int, float)) or not isinstance(ceiling, (int, float)):
        return {
            "check_id": check["id"], "status": "fail",
            "severity": check["severity"],
            "evidence": f"non-numeric agreed_price={price!r} or maxRate={ceiling!r}",
        }
    above_max = args.get("above_max") is True
    passed = price <= ceiling or above_max
    return {
        "check_id": check["id"],
        "status": "pass" if passed else "fail",
        "severity": check["severity"],
        "evidence": (
            f"tool call {call.get('id')} agreed_price={price}, "
            f"maxRate={ceiling}, above_max={above_max}"
        ),
    }


def _grade_counter_direction(
    check: dict[str, Any], trace: dict[str, Any]
) -> dict[str, str]:
    offer = check.get("carrier_offer")
    events = trace.get("events", [])
    offer_index = next(
        (
            index
            for index, event in enumerate(events)
            if event.get("type") == "user_transcript"
            and str(offer) in event.get("text", "").replace(",", "")
        ),
        None,
    )
    if offer_index is None:
        return {
            "check_id": check["id"], "status": "fail",
            "severity": check["severity"],
            "evidence": f"carrier offer {offer} not found in caller trace",
        }
    for event in events[offer_index + 1 :]:
        if event.get("type") == "user_transcript":
            break
        if event.get("type") != "agent_text":
            continue
        amounts = [
            float(value.replace(",", ""))
            for value in re.findall(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", event.get("text", ""))
        ]
        if not amounts:
            continue
        counter = amounts[0]
        return {
            "check_id": check["id"],
            "status": "pass" if counter <= offer else "fail",
            "severity": check["severity"],
            "evidence": (
                f"agent counter={counter:g} after carrier offer={offer}; "
                f"agent event t_ms={event.get('t_ms')}"
            ),
        }
    return {
        "check_id": check["id"], "status": "fail",
        "severity": check["severity"],
        "evidence": f"no dollar counter found after carrier offer={offer}",
    }


def grade_trace(
    scenario: dict[str, Any], trace: dict[str, Any]
) -> dict[str, Any]:
    if trace.get("scenario_id") != scenario.get("id"):
        raise ValueError(
            f"trace scenario_id {trace.get('scenario_id')!r} does not match "
            f"scenario {scenario.get('id')!r}"
        )

    runner_errors = [
        event for event in trace.get("events", []) if event.get("type") == "runner_error"
    ]
    checks = [
        {
            "check_id": "runner.completed",
            "status": "fail" if runner_errors else "pass",
            "severity": "critical",
            "evidence": (
                runner_errors[0].get("detail", "runner error")
                if runner_errors
                else "conversation runner completed without error"
            ),
        }
    ]
    for check in scenario.get("expected", {}).get("checks", []):
        check_type = check.get("type")
        if check_type == "tool_called":
            checks.append(_grade_tool_called(check, trace))
        elif check_type == "agreement_policy":
            checks.append(_grade_agreement_policy(check, scenario, trace))
        elif check_type == "counter_not_above_offer":
            checks.append(_grade_counter_direction(check, trace))
        else:
            raise ValueError(f"unsupported check type: {check.get('type')!r}")

    blocking_failures = [
        check
        for check in checks
        if check["status"] != "pass" and check["severity"] in {"critical", "major"}
    ]
    return {
        "scenario_id": scenario["id"],
        "passed": not blocking_failures,
        "checks": checks,
        "trace_source": (
            "conversation_runner"
            if trace.get("meta", {}).get("runner_level") == "text_conversation"
            else "reviewed_fixture"
        ),
    }
