from __future__ import annotations

import copy
import json
import urllib.request
from typing import Any, Protocol


MODEL = "gpt-4.1"
TEMPERATURE = 0.7
FREQUENCY_PENALTY = 0.6
PRESENCE_PENALTY = 0.5


class ChatTransport(Protocol):
    def create(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class OpenAIHTTPTransport:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for --live")
        self._api_key = api_key

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))


def to_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert runner messages to the Chat Completions wire format."""
    converted: list[dict[str, Any]] = []
    for message in messages:
        item = {key: copy.deepcopy(value) for key, value in message.items() if key != "tool_calls"}
        calls = message.get("tool_calls")
        if calls:
            item["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call.get("args", {}), sort_keys=True),
                    },
                }
                for call in calls
            ]
        converted.append(item)
    return converted


class OpenAIChatModel:
    model_id = MODEL

    def __init__(self, transport: ChatTransport) -> None:
        self._transport = transport
        self.metadata: dict[str, Any] = {
            "requested_model": MODEL,
            "temperature": TEMPERATURE,
            "frequency_penalty": FREQUENCY_PENALTY,
            "presence_penalty": PRESENCE_PENALTY,
            "seed": None,
            "response_model": None,
            "system_fingerprints": [],
            "usage": [],
        }

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload = {
            "model": MODEL,
            "temperature": TEMPERATURE,
            "frequency_penalty": FREQUENCY_PENALTY,
            "presence_penalty": PRESENCE_PENALTY,
            "messages": to_chat_messages(messages),
            "tools": copy.deepcopy(tools),
        }
        response = self._transport.create(payload)
        self.metadata["response_model"] = response.get("model")
        fingerprint = response.get("system_fingerprint")
        if fingerprint not in self.metadata["system_fingerprints"]:
            self.metadata["system_fingerprints"].append(fingerprint)
        if response.get("usage") is not None:
            self.metadata["usage"].append(copy.deepcopy(response["usage"]))
        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("OpenAI response has no assistant message") from exc
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            try:
                arguments = json.loads(function.get("arguments", "{}"))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"tool {function.get('name')!r} returned invalid JSON arguments"
                ) from exc
            calls.append({
                "id": call.get("id"),
                "name": function.get("name"),
                "args": arguments,
            })
        return {"text": message.get("content") or "", "tool_calls": calls}
