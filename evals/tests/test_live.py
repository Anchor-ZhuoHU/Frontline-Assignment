from __future__ import annotations

import json
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evals.live import InfrastructureError, OpenAIChatModel, OpenAIHTTPTransport, to_chat_messages
from evals.conversation import run_conversation
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

    def test_transport_retries_429_and_5xx_with_backoff(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices": [{"message": {"content": "ok"}}]}'

        outcomes = [429, 503, Response()]
        sleeps = []

        def opener(_request, timeout):
            self.assertEqual(timeout, 60)
            outcome = outcomes.pop(0)
            if isinstance(outcome, int):
                raise urllib.error.HTTPError(
                    "https://api.openai.com", outcome, "error", {}, io.BytesIO(b"error")
                )
            return outcome

        transport = OpenAIHTTPTransport(
            "test-key", opener=opener, sleeper=sleeps.append, backoff_seconds=0.25
        )

        response = transport.create({"model": "gpt-4.1"})

        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        self.assertEqual(sleeps, [0.25, 0.5])
        self.assertEqual(transport.last_attempts, 3)
        self.assertEqual(transport.total_retries, 2)

    def test_transport_exhaustion_is_infrastructure_error(self) -> None:
        def opener(_request, timeout):
            raise urllib.error.HTTPError(
                "https://api.openai.com", 500, "error", {}, io.BytesIO(b"error")
            )

        transport = OpenAIHTTPTransport(
            "test-key", opener=opener, sleeper=lambda _delay: None
        )

        with self.assertRaisesRegex(InfrastructureError, "after 3 attempt"):
            transport.create({"model": "gpt-4.1"})

    def test_runner_tags_infrastructure_error_separately(self) -> None:
        class FailingModel:
            model_id = "gpt-4.1"
            metadata = {"transport_retries": 2}

            def complete(self, _messages, _tools):
                raise InfrastructureError("OpenAI HTTP 429 after 3 attempt(s)")

        contracts = SimpleNamespace(
            room1_tools=[], initial_prompt=lambda org_name=None: "system"
        )
        scenario = {
            "id": "infra", "caller_turns": ["hello"], "fixtures": {},
            "expected": {"transfer": False, "checks": []},
        }

        trace = run_conversation(scenario, FailingModel(), contracts)

        self.assertEqual(trace["meta"]["status"], "infrastructure_error")
        error = next(event for event in trace["events"] if event["type"] == "runner_error")
        self.assertEqual(error["kind"], "infrastructure")
        self.assertEqual(trace["meta"]["model_metadata"]["transport_retries"], 2)

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
                patch("evals.runner._reproducibility", return_value={
                    "git_commit": "abc", "git_dirty": True,
                    "evals_tree_sha256": "evals", "tool_schemas_sha256": "schema",
                    "prompt_sha256": {"only": {"initial": "prompt"}},
                    "hash_algorithm": "sha256",
                }),
                patch("evals.runner.run_conversation", return_value=trace) as run,
                patch("evals.runner.grade_trace", side_effect=fake_grade),
            ):
                report = run_live_suite(evals_dir, Path(output), DummyModel, runs=3, k=2)

            self.assertEqual(run.call_count, 3)
            self.assertAlmostEqual(report["summary"]["pass_at_1"], 2 / 3)
            self.assertAlmostEqual(report["summary"]["pass_at_k"], 1 / 3)
            self.assertEqual(report["results"][0]["model_metadata"]["system_fingerprints"], ["fp_x"])
            self.assertTrue(report["execution"]["live_run_occurred"])

    def test_infrastructure_run_is_excluded_from_pass_hat_k(self) -> None:
        class DummyModel:
            model_id = "gpt-4.1"

        traces = [
            {"meta": {"status": "infrastructure_error", "model_metadata": {}}, "events": []},
            {"meta": {"status": "completed", "model_metadata": {}}, "events": []},
        ]
        grades = [
            {"scenario_id": "only", "passed": False, "checks": [], "trace_source": "conversation_runner"},
            {"scenario_id": "only", "passed": True, "checks": [], "trace_source": "conversation_runner"},
        ]
        repro = {
            "git_commit": "abc", "git_dirty": True,
            "evals_tree_sha256": "evals", "tool_schemas_sha256": "schema",
            "prompt_sha256": {"only": {"initial": "prompt"}}, "hash_algorithm": "sha256",
        }
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output:
            evals_dir = Path(source)
            (evals_dir / "conversation_scenarios").mkdir()
            (evals_dir / "conversation_scenarios" / "only.json").write_text(
                json.dumps({"id": "only"}), encoding="utf-8"
            )
            with (
                patch("evals.runner.ProductionContracts.load", return_value=object()),
                patch("evals.runner._reproducibility", return_value=repro),
                patch("evals.runner.run_conversation", side_effect=traces),
                patch("evals.runner.grade_trace", side_effect=grades),
            ):
                report = run_live_suite(evals_dir, Path(output), DummyModel, runs=2, k=1)

            self.assertEqual(report["summary"]["excluded_infrastructure_runs"], 1)
            self.assertEqual(report["summary"]["included_behavioral_runs"], 1)
            self.assertEqual(report["summary"]["failed"], 0)
            self.assertEqual(report["summary"]["pass_at_1"], 1.0)
            self.assertEqual(report["summary"]["pass_at_k"], 1.0)
            self.assertTrue(report["results"][0]["excluded_from_pass_k"])
            self.assertEqual(len(list((Path(output) / "traces").glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
