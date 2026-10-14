from __future__ import annotations

import copy
import json
from math import comb
from typing import Any, Protocol

from evals.contracts import ProductionContracts


class ConversationModel(Protocol):
    model_id: str

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


class ScriptedModel:
    """Deterministic model double that also checks the request it receives."""

    model_id = "scripted"

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self._script = copy.deepcopy(script)
        self._index = 0
        self.requests_with_tool_results = 0

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if self._index >= len(self._script):
            raise RuntimeError("scripted model ran out of responses")
        step = self._script[self._index]
        self._index += 1

        system_prompt = messages[0].get("content", "")
        for fragment in step.get("expect_system_contains", []):
            if fragment not in system_prompt:
                raise AssertionError(f"production system prompt is missing {fragment!r}")
        expected_tools = step.get("expect_tools")
        if expected_tools is not None:
            observed = [tool["function"]["name"] for tool in tools]
            if observed != expected_tools:
                raise AssertionError(
                    f"tool schema names differ: expected {expected_tools}, observed {observed}"
                )
        expected_result = step.get("expect_last_tool_result")
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        if tool_messages:
            self.requests_with_tool_results += 1
        if expected_result is not None:
            if not tool_messages:
                raise AssertionError("expected a tool result in model context")
            result = json.loads(tool_messages[-1]["content"])
            for key, value in expected_result.items():
                if result.get(key) != value:
                    raise AssertionError(
                        f"last tool result {key!r}: expected {value!r}, got {result.get(key)!r}"
                    )
        return {
            "text": step.get("text", ""),
            "tool_calls": copy.deepcopy(step.get("tool_calls", [])),
        }

    def assert_consumed(self) -> None:
        if self._index != len(self._script):
            raise AssertionError(
                f"script has {len(self._script) - self._index} unused responses"
            )


class FakeTools:
    def __init__(
        self, scenario: dict[str, Any], contracts: ProductionContracts
    ) -> None:
        self._scenario = scenario
        self._contracts = contracts
        self.state: dict[str, Any] = {
            "verified_carrier": None,
            "loaded_reference": None,
            "agreement": None,
            "end_reason": None,
            "transfer": None,
            "external_side_effects": [],
        }

    def call(self, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        fixtures = self._scenario["fixtures"]
        if name == "verify_carrier":
            carrier = fixtures["carrier"]
            if str(args.get("mc_number")) != str(carrier["mc_number"]):
                return {"status": "not_found"}, None
            self.state["verified_carrier"] = copy.deepcopy(carrier)
            return {
                "status": "success",
                "message": f"Carrier found: {carrier['carrier_name']}",
                "carrier_name": carrier["carrier_name"],
                "mc_number": carrier["mc_number"],
            }, None
        if name == "get_load_context":
            load = fixtures["load"]
            if args.get("load_id") != load["id"]:
                return {"status": "error", "message": "load not found"}, None
            self.state["loaded_reference"] = load["id"]
            prompt = self._contracts.negotiation_prompt(copy.deepcopy(load))
            return {
                "status": "success",
                "message": f"Load {load['id']} information retrieved successfully",
                "load_data": copy.deepcopy(load),
                "call_id": "fake-call-1",
            }, prompt
        if name == "record_agreement":
            if self.state["loaded_reference"] is None:
                return {"status": "error", "message": "load not loaded"}, None
            if fixtures.get("tool_failures", {}).get("record_agreement"):
                return {"status": "error", "message": "Failed to record in database"}, None
            self.state["agreement"] = copy.deepcopy(args)
            above_max = args.get("above_max", False)
            message = (
                f"Above-max bid stored. We'll contact {args.get('carrier_contact_name')} if conditions change."
                if above_max
                else f"Agreement recorded at ${float(args['agreed_price'])}"
            )
            return {
                "status": "success",
                "message": message,
                "negotiation_id": "fake-negotiation-1",
            }, None
        if name == "end_call":
            valid_reasons = [
                "abrupt", "agreement", "no_agreement", "error",
                "load_not_found", "mc_not_found", "bid_placed",
            ]
            reason = args.get("reason")
            if not reason or reason not in valid_reasons:
                return {
                    "status": "error",
                    "message": f"Invalid reason. Must be one of: {', '.join(valid_reasons)}",
                }, None
            self.state["end_reason"] = reason
            return {
                "status": "success",
                "message": f"Call ending with reason: {reason}",
            }, None
        if name == "transfer_to_human":
            if self.state["loaded_reference"] is None:
                return {"status": "error", "message": "load not loaded"}, None
            self.state["transfer"] = copy.deepcopy(args)
            return {
                "status": "transferring",
                "message": (
                    "Tell the carrier you are placing them on a brief hold while you "
                    "connect them with the appropriate person. Be warm and professional."
                ),
            }, None
        raise ValueError(f"unknown fake tool: {name}")


def run_conversation(
    scenario: dict[str, Any],
    model: ConversationModel,
    contracts: ProductionContracts,
) -> dict[str, Any]:
    tool_names = {tool["function"]["name"] for tool in contracts.room1_tools}
    system_prompt = contracts.initial_prompt(org_name=scenario.get("org_name"))
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    events: list[dict[str, Any]] = []
    fake_tools = FakeTools(scenario, contracts)
    next_t_ms = 0
    call_number = 0
    model_steps = 0
    max_model_steps = scenario.get("limits", {}).get("max_model_steps", 20)
    terminated_by: str | None = None
    runner_error: str | None = None

    def event(event_type: str, **data: Any) -> None:
        nonlocal next_t_ms
        events.append({"t_ms": next_t_ms, "type": event_type, **data})
        next_t_ms += 100

    try:
        for caller_text in scenario["caller_turns"]:
            if terminated_by is not None:
                break
            messages.append({"role": "user", "content": caller_text})
            event("user_transcript", text=caller_text)

            while terminated_by is None:
                if model_steps >= max_model_steps:
                    raise RuntimeError(
                        f"model step limit exceeded: {model_steps}/{max_model_steps}"
                    )
                model_steps += 1
                response = model.complete(copy.deepcopy(messages), contracts.room1_tools)
                text = response.get("text", "")
                calls = response.get("tool_calls", [])
                assistant_message: dict[str, Any] = {"role": "assistant", "content": text}
                if calls:
                    assistant_message["tool_calls"] = copy.deepcopy(calls)
                messages.append(assistant_message)
                if text:
                    event("agent_text", text=text)
                if not calls:
                    break

                for call in calls:
                    name = call["name"]
                    args = call.get("args", {})
                    call_number += 1
                    call_id = call.get("id", f"call-{call_number}")
                    event("tool_call", id=call_id, name=name, args=copy.deepcopy(args))
                    if name not in tool_names:
                        raise ValueError(
                            f"model called tool absent from production schemas: {name}"
                        )
                    result, replacement_prompt = fake_tools.call(name, args)
                    if replacement_prompt is not None:
                        messages[0] = {"role": "system", "content": replacement_prompt}
                        event("system_prompt_changed", prompt=replacement_prompt)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": name,
                            "content": json.dumps(result, sort_keys=True),
                        }
                    )
                    event(
                        "tool_result",
                        id=call_id,
                        name=name,
                        output=copy.deepcopy(result),
                    )
                    if name in {"end_call", "transfer_to_human"} and result.get(
                        "status"
                    ) in {"success", "transferring"}:
                        terminated_by = name
                        break

        if isinstance(model, ScriptedModel):
            model.assert_consumed()
    except Exception as exc:
        runner_error = f"{type(exc).__name__}: {exc}"
        event("runner_error", detail=runner_error)
    return {
        "schema_version": 1,
        "scenario_id": scenario["id"],
        "tool_schemas": copy.deepcopy(contracts.room1_tools),
        "meta": {
            "runner_level": "text_conversation",
            "model": model.model_id,
            "production_prompt_loaded": True,
            "production_tool_schemas_loaded": True,
            "status": "error" if runner_error else "completed",
            "model_steps": model_steps,
            "max_model_steps": max_model_steps,
            "terminated_by": terminated_by,
        },
        "events": events,
        "end_state": fake_tools.state,
    }


def pass_hat_k(runs_by_scenario: dict[str, list[bool]], k: int) -> float:
    if not runs_by_scenario:
        raise ValueError("at least one scenario is required")
    if k < 1:
        raise ValueError("k must be at least 1")
    scores = []
    for scenario_id, runs in runs_by_scenario.items():
        n = len(runs)
        if n < k:
            raise ValueError(f"{scenario_id}: need at least {k} runs, got {n}")
        successes = sum(runs)
        scores.append(comb(successes, k) / comb(n, k))
    return sum(scores) / len(scores)
