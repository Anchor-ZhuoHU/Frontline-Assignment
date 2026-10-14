# Frontline voice-agent evaluation design

## Goal and scope

This evaluation supports a merge decision for changes to the single-prompt freight negotiation agent. The default command must be deterministic, require no credentials, make no network calls, and have no production side effects.

The runner drives a pluggable model through a multi-turn conversation using the real prompt builders and tool schemas. All tools are in-memory fakes. A successful `get_load_context` replaces the initial system message with the real load-specific negotiation prompt, matching production. The scripted model makes CI deterministic and asserts that safety-critical prompt clauses and tool results reach the model. Reviewed traces remain grader fixtures, while runner-produced traces are the behavioral evaluation input.

A scripted model cannot measure nondeterministic model behavior or reliably predict the effect of arbitrary prompt wording changes. It can exercise the complete loop and enforce explicit prompt contracts. Repeated live runs are the behavioral measurement and should remain non-gating until the team defines a flake policy.

Scripted caller turns are fixed independently of the agent's actual response. A live agent can therefore ask a question, recover from an error, or take a branch that makes the next scripted caller turn unnatural or inconsistent. Live traces must be reviewed for this drift; pass^k does not make the caller simulator adaptive.

In scope are carrier verification, load lookup, rate negotiation, agreement and above-max bid recording, call closure, human transfer, and behavior after dependency failures. Out of scope for the offline merge gate are real PSTN calls, provider availability, recognition accuracy on audio, synthesis quality, caller-heard latency, and transfer infrastructure.

## Prioritized success conditions

| Call type | Condition | Evidence | Method | Severity |
| --- | --- | --- | --- | --- |
| Agreement | Persist the caller-accepted price for the loaded freight | `record_agreement` arguments and fake end state | Code | Critical |
| Any negotiation | Never reveal the internal goal or ceiling | Agent text compared with fixture pricing | Code | Critical |
| Any load discussion | Verify carrier before load lookup | Ordered tool calls and successful results | Code | Critical |
| Above-max bid | Capture price, name, and phone with `above_max=true` | Tool arguments and fake end state | Code | Critical |
| Transfer | Transfer only after identity and load verification, and only when expected | Ordered calls and transfer event | Code | Critical |
| Tool failure | Do not claim success after an error result | Tool result followed by agent text | Code, with judge as a later report-only cross-check | Critical |
| Closure | Record the outcome with the matching end reason | `end_call` argument | Code | Major |
| Any call | Speak naturally without exposing internal function names | Agent text | Code for names; calibrated judge for tone | Major or minor |

## Measurement and gate policy

- Task completion: scenarios whose critical and major checks all pass, always reported as a count and rate.
- Policy compliance: calls with no critical confidentiality, identity, or grounding violation.
- Transfer correctness: expected versus observed transfers, separated from containment.
- Field capture: normalized expected values compared with tool arguments and fake end state.
- Reliability: live or simulated nondeterministic scenarios must use repeated runs and report pass^k. Fixture replay is deterministic and must not be presented as pass^k.
- Critical checks require 100 percent. With a small initial dataset, a percentage is never presented without its numerator and denominator.

### Flake policy

- The credential-free scripted suite is merge-gating. Every critical or major deterministic check must pass on every scenario; retries do not turn a failure into a pass.
- Prompt/schema loading, runner completion, tool argument schemas, identity ordering, pricing confidentiality and ceilings, pre-load grounding, expected transfer behavior, and scenario-specific closure/counter checks are gating in the scripted suite.
- Live GPT-4.1 runs are report-only. Reports include all attempts, errors, requested model settings, returned model ids and system fingerprints, plus pass^1 and pass^k; failed live checks do not fail the deterministic merge gate.
- Do not retry only failed live samples. Rerun the complete declared sample set and retain both reports. Promotion to gating requires a product-approved run count, pass^k threshold, retry budget, cost owner, and baseline owner.
- Transport/authentication failures make that live evidence set invalid rather than converting it into a model-policy failure. The report must still retain the error trace.

## Architecture

Readable JSON scenarios provide caller turns, in-memory carrier and load fixtures, and deterministic scripted-model responses. The runner loads `voice_prompt.py` and `negotiation_prompt.py` by path with an in-memory stub `src` package, avoiding the dependency-heavy package initializer. It parses `tool_definitions.py` with `ast` and converts its literal `FunctionSchema` declarations to model-facing JSON schemas. No prompt or schema content is copied into the evaluator.

Identity grading assumes a successful `verify_carrier` result unless a scenario explicitly sets `fixtures.phone_identity_confirmed` to `true`. That fixture represents production's phone-first prompt, where the caller has confirmed the carrier matched by phone lookup and no verification tool call is expected.

Every scenario declares `expected.transfer` as `true` or `false`. Transfer grading compares that declaration with observed `transfer_to_human` calls instead of trying to infer intent from caller wording; this detects both unwanted and missed transfers. Rate-leak grading recognizes standalone digits as well as currency and spoken amounts, while counter-direction grading intentionally limits amounts to currency-marked or spoken rates so dates and ZIP codes do not look like counters.

Each runner-produced trace is an ordered event log containing caller text, agent text, tool calls/results, system-prompt transitions, and fake end state. Pure graders return pass, fail, not-applicable, or error with event-level evidence. The report stage aggregates results into `report.json` for automation and `report.md` for review.

Every report records the checked-out Git commit, canonical SHA-256 of the production tool schemas, SHA-256 of each scenario's rendered initial and negotiation prompts, model sampling settings, and runs per scenario. The output bundle saves deterministic traces as `traces/<scenario>.json` and live traces as `traces/<scenario>.run-<n>.json`. These hashes identify the evaluated contracts even when the working tree is not clean.

Runner failures are data: prompt-contract mismatches, unknown tools, exhausted scripts, and model-step-limit violations become a critical `runner.completed` failure with the exception and attempted tool call in the trace. Successful `end_call` and `transfer_to_human` results stop the loop before another caller turn. Scenarios default to 20 model steps and may set a lower cap.

Critical prompt contracts live in one evaluator registry. Each clause declares whether it applies to the initial or negotiation prompt and names the behavioral check it protects. The default `prompt.critical_clauses` invariant evaluates every rendered prompt; scenario scripts do not assert prompt fragments. Mutation tests remove each registered clause in turn and require a critical failure. The registry intentionally excludes the phone-identity replacement clauses already covered by `voice-agent/tests/test_voice_prompt_guardrails.py`.

The first grader implements a subset argument check for `record_agreement`. Its golden fixture passes; a copy with only the agreed price corrupted fails and displays the observed value. The conversation skeleton now executes carrier verification, load retrieval, the real prompt transition, agreement recording, and call closure through the same event interface. Further checks reuse this interface rather than compare exact assistant wording.

Run the current skeleton with:

```bash
python3 -m unittest evals.tests.test_grading
python3 -m evals run
```

By default reports go to `/tmp/frontline-evals`, keeping routine output out of the repository. A reviewed baseline report will be added deliberately once scenario breadth and thresholds are complete.

## External boundaries and safety

The production pipeline initializes Daily, Deepgram, OpenAI, Cartesia, Supabase, Highway or the legacy carrier API, the KCH quote API, and Slack. The default evaluator initializes none of them. Future real-prompt runs must replace every state-changing tool with an in-memory fake and cap turns, duration, and repetitions. Live-model runs remain separate from the credential-free merge gate.

## Assumptions and limitations

- The highest business priority is a correct, authorized negotiation outcome; policy or data-integrity failures override apparent task completion.
- The repository has no product-approved latency target, redacted production calls, or independent judge labels.
- Hand-authored fixture results measure harness sensitivity, not production model quality.
- Scripted conversation results measure integration, prompt contracts, and deterministic scenario logic, not GPT-4.1 response quality.
- Text traces can inject transcription-like errors, but they cannot measure real ASR, TTS, barge-in timing, dead air, or caller-perceived latency.
- The production model uses temperature 0.7. Any future live score needs repeated runs, pinned model metadata, and pass^k rather than a single deterministic claim.

## Follow-up qualification

Add scenarios derived from redacted production calls, obtain independent labels for qualitative criteria, run repeated real-prompt evaluations with fake tools, and schedule a small audio-level release suite for recognition, latency, interruption, and transfer behavior.
