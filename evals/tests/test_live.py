from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evals.live import OpenAIChatModel, OpenAIHTTPTransport, to_chat_messages
from evals.runner import run_live_suite


class FakeTransport:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    def create(self, payload: dict) -> dict:
        self.requests.append(payload)
        return self.responses.pop(0)


class LiveAdapterTest(unittest.TestCase):
    def test_live_transport_requires_api_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            OpenAIHTTPTransport("")

    def test_message_conversion_is_centralized(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": "Checking.",
                "tool_calls": [
                    {"id": "call-1", "name": "verify_carrier", "args": {"mc_number": "123"}}
                ],
            },
            {
                "role": "tool", "tool_call_id": "call-1", "name": "verify_carrier",
                "content": '{"status":"success"}',
            },
        ]

        converted = to_chat_messages(messages)

        wire_call = converted[1]["tool_calls"][0]
        self.assertEqual(wire_call["type"], "function")
        self.assertEqual(wire_call["function"]["name"], "verify_carrier")
        self.assertEqual(json.loads(wire_call["function"]["arguments"]), {"mc_number": "123"})
        self.assertEqual(converted[2]["tool_call_id"], "call-1")

    def test_fake_transport_observes_production_sampling_and_response_metadata(self) -> None:
        transport = FakeTransport([{
            "model": "gpt-4.1-2026-01-01",
            "system_fingerprint": "fp_test123",
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            "choices": [{
                "message": {
                    "content": "Let me check.",
                    "tool_calls": [{
                        "id": "call-1", "type": "function",
                        "function": {"name": "verify_carrier", "arguments": '{"mc_number":"123"}'},
                    }],
                }
            }],
        }])
        model = OpenAIChatModel(transport)

        result = model.complete(
            [{"role": "system", "content": "system"}, {"role": "user", "content": "MC 123"}],
            [{"type": "function", "function": {"name": "verify_carrier", "parameters": {"type": "object"}}}],
        )

        request = transport.requests[0]
        self.assertEqual(request["model"], "gpt-4.1")
        self.assertEqual(request["temperature"], 0.7)
        self.assertEqual(request["frequency_penalty"], 0.6)
        self.assertEqual(request["presence_penalty"], 0.5)
        self.assertNotIn("seed", request)
        self.assertEqual(result["tool_calls"][0], {
            "id": "call-1", "name": "verify_carrier", "args": {"mc_number": "123"}
        })
        self.assertEqual(model.metadata["response_model"], "gpt-4.1-2026-01-01")
        self.assertEqual(model.metadata["system_fingerprints"], ["fp_test123"])

    def test_live_suite_repeats_scenarios_and_reports_pass_hat_k(self) -> None:
        class DummyModel:
            model_id = "gpt-4.1"

        trace = {
            "meta": {"model_metadata": {"response_model": "gpt-4.1-test", "system_fingerprints": ["fp_x"]}}
        }
        outcomes = iter([True, True, False])

        def fake_grade(_scenario: dict, _trace: dict) -> dict:
            passed = next(outcomes)
            return {"scenario_id": "only", "passed": passed, "checks": [], "trace_source": "conversation_runner"}

        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output:
            evals_dir = Path(source)
            (evals_dir / "conversation_scenarios").mkdir()
            (evals_dir / "conversation_scenarios" / "only.json").write_text(
                json.dumps({"id": "only"}), encoding="utf-8"
            )
            with (
                patch("evals.runner.ProductionContracts.load", return_value=object()),
                patch("evals.runner.run_conversation", return_value=trace) as run,
                patch("evals.runner.grade_trace", side_effect=fake_grade),
            ):
                report = run_live_suite(evals_dir, Path(output), DummyModel, runs=3, k=2)

            self.assertEqual(run.call_count, 3)
            self.assertAlmostEqual(report["summary"]["pass_at_1"], 2 / 3)
            self.assertAlmostEqual(report["summary"]["pass_at_k"], 1 / 3)
            self.assertEqual(report["results"][0]["model_metadata"]["system_fingerprints"], ["fp_x"])
            self.assertTrue(report["execution"]["live_run_occurred"])


if __name__ == "__main__":
    unittest.main()
