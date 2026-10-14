# Frontline voice-agent evaluations

This directory contains a credential-free conversation-level merge gate for the Frontline voice agent. Run all commands below from the repository root with Python 3.11. The offline suite uses only the standard library: do not install the voice-agent dependencies.

## Run the tests and offline gate

```bash
python3 -m unittest discover -s evals/tests -v
python3 -m evals run --output /tmp/frontline-evals
```

The first command tests the runner, fakes, graders, live adapter, report generation, and deliberately unsafe mutations. The second runs the six accepted scripted conversations through the real prompt builders and real tool schemas with in-memory tools. It exits zero only when every critical or major check passes. Review `/tmp/frontline-evals/report.md`; use `report.json` for automation and `traces/*.json` for the complete event sequence.

To enable this gate in GitHub Actions, copy [`ci/evaluation-gate.yml`](ci/evaluation-gate.yml) into `.github/workflows/evaluation-gate.yml` in a connection with permission to modify workflows.

The committed clean example is [`results/offline/report.md`](results/offline/report.md). A sensitivity run over deliberately unsafe scenarios is in [`results/unsafe/report.md`](results/unsafe/report.md). Reproduce the latter with:

```bash
python3 -m evals run --unsafe --output /tmp/frontline-evals-unsafe
```

That command is expected to exit nonzero. Unsafe scenarios are separate from `conversation_scenarios`, so they demonstrate detection without making the default gate fail.

## Run the optional live model

```bash
OPENAI_API_KEY=... python3 -m evals run \
  --live --runs 5 --k 2 --output /tmp/frontline-evals-live
```

Live mode sends the same production prompts, tool schemas, scripted caller turns, and fake-tool results to GPT-4.1. It uses production sampling (`temperature=0.7`, `frequency_penalty=0.6`, `presence_penalty=0.5`, no seed), saves every trace, and records returned model ids and system fingerprints. It never calls production tools. Live results and pass^k are report-only. Rate-limit and server errors are retried; exhausted infrastructure errors are saved and excluded from pass^k.

## Read a failure

Start with the failed scenario in `report.md`. Each line has a stable check id, severity, status, and evidence, for example:

```text
- agreement.ceiling_policy [critical]: fail, record-1 agreed_price=1900, maxRate=1800, above_max=False
```

Use the check id to identify the violated policy, then open the matching trace named in the reproducibility header. Trace events are ordered and include caller and agent text, tool calls, tool results, prompt swaps, and final fake state. `runner.completed` means the harness or model loop failed; other ids are behavioral or contract failures. Fix the earliest causal event, then rerun both unit tests and the offline gate.

## What this does not measure

- Live GPT-4.1 behavior unless `--live` is explicitly used.
- Speech recognition, speech synthesis, accents, noise, or transcription quality.
- Barge-in, turn-taking, dead air, caller-heard latency, or audio quality.
- Daily telephony and transfer behavior, Supabase, carrier lookup, quote delivery, Slack, recording upload, or any other provider integration.
- The prevalence and full variety of real caller behavior; scenarios are small and synthetic, and scripted caller turns can drift from a live model's preceding response.

See [`DESIGN.md`](DESIGN.md) for scope, risk coverage, assumptions, flake policy, and production gaps.
