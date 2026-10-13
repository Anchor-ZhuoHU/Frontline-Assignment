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
    mismatches = [
        call
        for call in calls
        if not all(
            call.get("args", {}).get(key) == value for key, value in expected.items()
        )
    ]
    if calls and not mismatches:
        evidence = "; ".join(
            f"tool call {call.get('id', '<missing id>')} args={call.get('args', {})}"
            for call in calls
        )
        return {
            "check_id": check["id"], "status": "pass",
            "severity": check["severity"], "evidence": evidence,
        }
    observed_calls = [
        {"id": call.get("id", "<missing id>"), "args": call.get("args", {})}
        for call in (mismatches or calls)
    ]
    return {
        "check_id": check["id"],
        "status": "fail",
        "severity": check["severity"],
        "evidence": (
            f"every {check['name']} call must include {expected}; "
            f"mismatches={observed_calls or 'no call'}"
        ),
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
    if not isinstance(ceiling, (int, float)):
        return {
            "check_id": check["id"], "status": "fail",
            "severity": check["severity"],
            "evidence": f"non-numeric maxRate={ceiling!r}",
        }
    unsafe = []
    summaries = []
    for call in calls:
        args = call.get("args", {})
        price = args.get("agreed_price")
        above_max = args.get("above_max") is True
        summary = (
            f"{call.get('id')} agreed_price={price}, maxRate={ceiling}, "
            f"above_max={above_max}"
        )
        summaries.append(summary)
        if not isinstance(price, (int, float)) or (price > ceiling and not above_max):
            unsafe.append(summary)
    return {
        "check_id": check["id"],
        "status": "fail" if unsafe else "pass",
        "severity": check["severity"],
        "evidence": "; ".join(unsafe or summaries),
    }


_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}


def _spoken_number(words: list[str]) -> float:
    words = [word for word in words if word != "and"]
    values = [_NUMBER_WORDS.get(word) for word in words]
    if (
        len(words) == 2
        and values[0] is not None
        and 10 <= values[0] <= 19
        and values[1] in {20, 30, 40, 50, 60, 70, 80, 90}
    ):
        return float(values[0] * 100 + values[1])
    if (
        len(words) == 2
        and values[0] is not None
        and 10 <= values[0] <= 19
        and values[1] is not None
        and 1 <= values[1] <= 9
    ):
        return float(values[0] * 100 + values[1] * 10)
    total = 0
    current = 0
    for word in words:
        if word == "hundred":
            current = max(current, 1) * 100
        elif word == "thousand":
            total += max(current, 1) * 1000
            current = 0
        else:
            current += _NUMBER_WORDS[word]
    return float(total + current)


def _amounts_in_order(text: str) -> list[float]:
    found: list[tuple[int, float]] = []
    for match in re.finditer(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text):
        found.append((match.start(), float(match.group(1).replace(",", ""))))

    tokens = list(re.finditer(r"[A-Za-z]+", text.replace("-", " ")))
    group: list[re.Match[str]] = []
    recognized = set(_NUMBER_WORDS) | {"hundred", "thousand", "and"}
    for token in tokens + [None]:
        word = token.group(0).lower() if token is not None else None
        if word in recognized:
            group.append(token)
            continue
        if group:
            words = [item.group(0).lower() for item in group]
            found.append((group[0].start(), _spoken_number(words)))
            group = []
    return [amount for _, amount in sorted(found)]


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
        amounts = _amounts_in_order(event.get("text", ""))
        if not amounts:
            continue
        counter = amounts[-1]
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
