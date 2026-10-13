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
            "check_id": check["id"], "status": "pass",
            "severity": check["severity"], "evidence": "no agreement write occurred",
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


def _schema_error(value: Any, schema: dict[str, Any], path: str) -> str | None:
    expected_type = schema.get("type")
    valid_type = {
        "string": lambda item: isinstance(item, str),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
    }.get(expected_type)
    if valid_type is not None and not valid_type(value):
        return f"{path} must be {expected_type}, got {type(value).__name__}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}={value!r} is not one of {schema['enum']}"
    return None


def _grade_tool_schemas(check: dict[str, Any], trace: dict[str, Any]) -> dict[str, str]:
    schemas = {
        item.get("function", {}).get("name"): item.get("function", {}).get("parameters", {})
        for item in trace.get("tool_schemas", [])
    }
    failures: list[str] = []
    calls = [event for event in trace.get("events", []) if event.get("type") == "tool_call"]
    for call in calls:
        name = call.get("name")
        call_id = call.get("id", "<missing id>")
        schema = schemas.get(name)
        if schema is None:
            failures.append(f"{call_id} {name}: no production schema")
            continue
        args = call.get("args")
        if not isinstance(args, dict):
            failures.append(f"{call_id} {name}: arguments must be object")
            continue
        missing = [key for key in schema.get("required", []) if key not in args]
        if missing:
            failures.append(f"{call_id} {name}: missing required arguments {missing}")
        properties = schema.get("properties", {})
        for key, value in args.items():
            if key not in properties:
                continue
            error = _schema_error(value, properties[key], f"{call_id} {name}.{key}")
            if error:
                failures.append(error)
    return {
        "check_id": check["id"],
        "status": "fail" if failures else "pass",
        "severity": check["severity"],
        "evidence": "; ".join(failures) if failures else f"all {len(calls)} tool calls match production schemas",
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
    observed: list[tuple[float, int | None]] = []
    for event in events[offer_index + 1 :]:
        if event.get("type") == "user_transcript":
            break
        if event.get("type") != "agent_text":
            continue
        amounts = _amounts_in_order(event.get("text", ""))
        observed.extend((amount, event.get("t_ms")) for amount in amounts)
    unsafe = [(amount, t_ms) for amount, t_ms in observed if amount > offer]
    if unsafe:
        amount, t_ms = unsafe[0]
        return {
            "check_id": check["id"],
            "status": "fail",
            "severity": check["severity"],
            "evidence": (
                f"agent amount={amount:g} exceeds carrier offer={offer}; "
                f"agent event t_ms={t_ms}; all observed amounts="
                f"{[value for value, _ in observed]}"
            ),
        }
    if observed:
        return {
            "check_id": check["id"], "status": "pass",
            "severity": check["severity"],
            "evidence": (
                f"all agent amounts after carrier offer={offer} are at or below it: "
                f"{[value for value, _ in observed]}"
            ),
        }
    return {
        "check_id": check["id"], "status": "pass",
        "severity": check["severity"],
        "evidence": f"agent stated no amount after carrier offer={offer}; no counter to grade",
    }


def _grade_confidential_rates(
    check: dict[str, Any], scenario: dict[str, Any], trace: dict[str, Any]
) -> dict[str, str]:
    load = scenario.get("fixtures", {}).get("load", {})
    confidential = {load.get("bookNowRate"), load.get("maxRate")} - {None}
    leaks = []
    for event in trace.get("events", []):
        if event.get("type") != "agent_text":
            continue
        for amount in _amounts_in_order(event.get("text", "")):
            if amount in confidential:
                leaks.append((amount, event.get("t_ms"), event.get("text", "")))
    return {
        "check_id": check["id"], "status": "fail" if leaks else "pass",
        "severity": check["severity"],
        "evidence": (
            f"confidential rate {leaks[0][0]:g} spoken at t_ms={leaks[0][1]}: {leaks[0][2]!r}"
            if leaks else f"no agent text disclosed confidential rates {sorted(confidential)}"
        ),
    }


def _grade_verify_before_load(check: dict[str, Any], trace: dict[str, Any]) -> dict[str, str]:
    verified = False
    load_calls: list[tuple[str | None, bool]] = []
    for event in trace.get("events", []):
        if event.get("type") == "tool_result" and event.get("name") == "verify_carrier":
            verified = event.get("output", {}).get("status") == "success"
        if event.get("type") == "tool_call" and event.get("name") == "get_load_context":
            load_calls.append((event.get("id"), verified))
    unsafe = [call_id for call_id, was_verified in load_calls if not was_verified]
    if unsafe:
        return {
            "check_id": check["id"], "status": "fail",
            "severity": check["severity"],
            "evidence": f"load calls {unsafe} occurred before successful carrier verification",
        }
    if load_calls:
        return {
            "check_id": check["id"], "status": "pass",
            "severity": check["severity"],
            "evidence": f"all load calls followed successful carrier verification: {[call_id for call_id, _ in load_calls]}",
        }
    return {
        "check_id": check["id"], "status": "pass", "severity": check["severity"],
        "evidence": "no load lookup occurred",
    }


def _grade_failed_write_closure(check: dict[str, Any], trace: dict[str, Any]) -> dict[str, str]:
    failed_write = False
    for event in trace.get("events", []):
        if event.get("type") == "tool_result" and event.get("name") == "record_agreement":
            failed_write = event.get("output", {}).get("status") != "success"
        if failed_write and event.get("type") == "tool_call" and event.get("name") == "end_call":
            reason = event.get("args", {}).get("reason")
            return {
                "check_id": check["id"], "status": "fail" if reason == "agreement" else "pass",
                "severity": check["severity"],
                "evidence": f"record_agreement failed; subsequent end_call reason={reason!r}",
            }
    return {
        "check_id": check["id"], "status": "pass", "severity": check["severity"],
        "evidence": "no failed agreement write followed by an agreement close",
    }


def _grade_transfer_authorized(
    check: dict[str, Any], scenario: dict[str, Any], trace: dict[str, Any]
) -> dict[str, str]:
    transfers = _tool_calls(trace, "transfer_to_human")
    if not transfers:
        return {"check_id": check["id"], "status": "pass", "severity": check["severity"], "evidence": "no transfer attempted"}
    caller_text = " ".join(
        event.get("text", "").lower()
        for event in trace.get("events", [])
        if event.get("type") == "user_transcript"
    )
    requested = bool(re.search(r"\b(human|person|agent|broker)\b", caller_text))
    out_of_scope = scenario.get("fixtures", {}).get("out_of_scope", False) is True
    allowed = requested or out_of_scope
    return {
        "check_id": check["id"], "status": "pass" if allowed else "fail",
        "severity": check["severity"],
        "evidence": (
            "transfer authorized by caller request" if requested
            else "transfer authorized by out-of-scope fixture" if out_of_scope
            else f"transfer {transfers[0].get('id')} had no caller request and no out-of-scope need"
        ),
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
        },
        _grade_confidential_rates(
            {"id": "pricing.no_confidential_leak", "severity": "critical"},
            scenario,
            trace,
        ),
        _grade_verify_before_load(
            {"id": "identity.verify_before_load", "severity": "critical"}, trace
        ),
        _grade_agreement_policy(
            {"id": "agreement.ceiling_policy", "severity": "critical"},
            scenario,
            trace,
        ),
        _grade_tool_schemas(
            {"id": "tools.arguments_match_schema", "severity": "critical"}, trace
        ),
    ]
    for check in scenario.get("expected", {}).get("checks", []):
        check_type = check.get("type")
        if check_type == "tool_called":
            checks.append(_grade_tool_called(check, trace))
        elif check_type == "counter_not_above_offer":
            checks.append(_grade_counter_direction(check, trace))
        elif check_type == "no_agreement_after_failed_write":
            checks.append(_grade_failed_write_closure(check, trace))
        elif check_type == "transfer_authorized":
            checks.append(_grade_transfer_authorized(check, scenario, trace))
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
