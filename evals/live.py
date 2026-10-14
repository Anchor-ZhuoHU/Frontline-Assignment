from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.request
from typing import Any, Protocol


MODEL = "gpt-4.1"
TEMPERATURE = 0.7
FREQUENCY_PENALTY = 0.6
PRESENCE_PENALTY = 0.5


class ChatTransport(Protocol):
    def create(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class InfrastructureError(RuntimeError):
    infrastructure_error = True


class OpenAIHTTPTransport:
    def __init__(
        self,
        api_key: str,
        *,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        opener: Any = urllib.request.urlopen,
        sleeper: Any = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for --live")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._api_key = api_key
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._opener = opener
        self._sleeper = sleeper
        self.total_retries = 0
        self.last_attempts = 0

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
        for attempt in range(1, self._max_attempts + 1):
            self.last_attempts = attempt
            try:
                with self._opener(request, timeout=60) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code <= 599
                if retryable and attempt < self._max_attempts:
                    self.total_retries += 1
                    self._sleeper(self._backoff_seconds * (2 ** (attempt - 1)))
                    continue
                raise InfrastructureError(
                    f"OpenAI HTTP {exc.code} after {attempt} attempt(s)"
                ) from exc
            except urllib.error.URLError as exc:
                raise InfrastructureError(f"OpenAI transport error: {exc.reason}") from exc
        raise AssertionError("unreachable retry loop")


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
            "transport_attempts": 0,
            "transport_retries": 0,
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
        try:
            response = self._transport.create(payload)
        finally:
            self.metadata["transport_attempts"] += getattr(
                self._transport, "last_attempts", 1
            )
            self.metadata["transport_retries"] = getattr(
                self._transport, "total_retries", 0
            )
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
