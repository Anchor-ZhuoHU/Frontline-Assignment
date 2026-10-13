# Frontline voice-agent evaluation design

## Goal and scope

This evaluation supports a merge decision for changes to the single-prompt freight negotiation agent. The default command must be deterministic, require no credentials, make no network calls, and have no production side effects.

The initial runner replays reviewed event traces through deterministic graders. It gives direct evidence that the scenario specifications, graders, diagnostics, reporting, and eventual gate detect targeted regressions. It does not claim that the current live model produced the fixture traces. Later layers can run the real prompt against fake tools and can qualify the audio pipeline separately.

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
- A qualitative judge remains report-only until independently labeled calibration reaches Cohen's kappa >= 0.60 and failure recall >= 0.80. Constructed goldens and known-bad traces validate judge plumbing but are not independent human calibration.

## Architecture

Readable JSON scenarios point to reviewed golden traces. Each trace is an ordered event log containing caller text, agent text, tool calls/results, transfer or call-end events, and fake end state. Pure graders return pass, fail, not-applicable, or error with event-level evidence. The runner aggregates results into `report.json` for automation and `report.md` for review.

The first walking skeleton implements a subset argument check for `record_agreement`. Its golden fixture must pass; a copy with only the agreed price corrupted must fail and display the observed value. Further checks will reuse the same interface rather than compare exact assistant wording.

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
- Text traces can inject transcription-like errors, but they cannot measure real ASR, TTS, barge-in timing, dead air, or caller-perceived latency.
- The production model uses temperature 0.7. Any future live score needs repeated runs, pinned model metadata, and pass^k rather than a single deterministic claim.

## Follow-up qualification

Add scenarios derived from redacted production calls, obtain independent labels for qualitative criteria, run repeated real-prompt evaluations with fake tools, and schedule a small audio-level release suite for recognition, latency, interruption, and transfer behavior.
