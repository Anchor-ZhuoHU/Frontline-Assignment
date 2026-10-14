# Frontline voice-agent evaluation design

## Goal and scope

This evaluation supports a merge decision for changes to the single-prompt freight negotiation agent. The default command must be deterministic, require no credentials, make no network calls, and have no production side effects.

The runner drives a pluggable model through a multi-turn conversation using the real prompt builders and tool schemas. All tools are in-memory fakes. A successful `get_load_context` replaces the initial system message with the real load-specific negotiation prompt, matching production. The scripted model supplies deterministic responses for CI; runner-produced traces are the behavioral evaluation input. Prompt-clause enforcement belongs to a default grader, not the scripted model.

A scripted model cannot measure nondeterministic model behavior or reliably predict the effect of arbitrary prompt wording changes. It can exercise the complete loop, while the prompt registry checks explicit contracts on the rendered prompts. Repeated live runs are the behavioral measurement and should remain non-gating until the team defines a flake policy.

Scripted caller turns are fixed independently of the agent's actual response. A live agent can therefore ask a question, recover from an error, or take a branch that makes the next scripted caller turn unnatural or inconsistent. Live traces must be reviewed for this drift; pass^k does not make the caller simulator adaptive.

In scope are carrier verification, load lookup, rate negotiation, agreement and above-max bid recording, call closure, human transfer, and behavior after dependency failures. Out of scope for the offline merge gate are real PSTN calls, provider availability, recognition accuracy on audio, synthesis quality, caller-heard latency, and transfer infrastructure.

## End-to-end system map

```text
PSTN / Daily room
  -> audio pipeline: Deepgram STT -> GPT-4.1 -> Cartesia TTS
  -> one initial prompt (identity, load lookup, tool and transfer rules)
  -> verify_carrier -> Highway/legacy carrier lookup -> caller identity in call context
  -> get_load_context -> Supabase load read -> load state + call/load link write
                      -> replace system message with full negotiation prompt
                         (initial rules + load facts + confidential pricing strategy)
  -> model/tool loop
       record_agreement -> negotiation row write -> carrier quote notification
       transfer_to_human -> Daily dial-out/room transfer + Slack notification
       end_call -> termination reason in context + pipeline end frame
  -> recording/call metadata persistence and upload
```

The offline evaluator follows the same prompt and tool-contract path without starting the audio pipeline or providers: JSON caller turns -> pluggable model -> production prompts and schemas -> in-memory tool fakes -> ordered trace -> deterministic graders -> Markdown/JSON report. A successful fake `get_load_context` performs the same prompt swap. The optional live adapter changes only the model implementation; all tools remain fake.

Production reads carrier identity from Highway or its legacy fallback and load data from Supabase. It writes call/load association, negotiation results, quote notifications, call termination state, transfer notifications, and recordings. None of those external reads or writes occur in the default or live-model evaluation modes.

## Risk coverage

| Product risk | Check | Scenario/evidence | Gate |
| --- | --- | --- | --- |
| Runner stops, loops forever, or hides a contract/tool exception | `runner.completed` | Every trace; exception or step-limit evidence | Scripted gate |
| A safety-critical production prompt instruction is removed | `prompt.critical_clauses` | Every rendered prompt; clause id and protected check; per-clause mutation test | Scripted gate |
| Goal or ceiling is spoken in digits, currency, or words | `pricing.no_confidential_leak` | Every agent turn in every scenario; offending amount/event | Scripted gate |
| A rate is quoted before load lookup succeeds | `pricing.no_rate_before_load` | Every trace, including injected load failures | Scripted gate |
| Load data is requested before verified or confirmed phone identity | `identity.verify_before_load` | Ordered successful tool results or explicit phone-identity fixture | Scripted gate |
| A persisted outcome misclassifies a price relative to the ceiling | `agreement.ceiling_policy` | Every `record_agreement` call: above-ceiling requires `above_max=true`, at/below-ceiling forbids it | Scripted gate |
| A tool call has missing, wrongly typed, or invalid-enum arguments | `tools.arguments_match_schema` | Every tool call against AST-loaded production schemas; unsafe enum/type variant | Scripted gate |
| Transfer happens unexpectedly or is omitted when required | `transfer.expected` | Scenario declaration compared with observed transfer calls | Scripted gate |
| The accepted price is not the value persisted | `agreement.correct_price` | Happy-path `record_agreement` arguments | Scripted gate |
| Agent counters above an already-below-goal carrier offer | `negotiation.no_counter_up` | All currency/spoken rate amounts before the next caller turn | Scripted gate |
| Agent claims agreement after persistence failed | `closing.no_agreement_after_failed_write` | Failed tool result followed by close behavior | Scripted gate |
| Call close reason disagrees with the successfully recorded agreement or bid | `closing.recorded_outcome_reason` | Successful write classification compared with the following `end_call` | Scripted gate |
| Agent hangs up before exactly three consecutive missing MC results, or fails to hang up on the third | `closing.third_mc_not_found` | Ordered `not_found` results, caller turns, and `end_call` reason | Scripted gate |
| Model behavior varies across identical calls | The same checks above plus pass^k | Repeated opt-in GPT-4.1 traces; infrastructure errors excluded and counted | Report-only |

Every default invariant applies to every scenario. Scenario-specific checks add outcome expectations; they cannot disable the defaults. All deterministic critical and major checks require 100 percent passage.

## Measurement and gate policy

- Scripted completion is the number of scenarios whose critical and major checks all pass, reported as passed and failed counts.
- Live reliability uses repeated runs and reports pass^1 and pass^k over behavioral runs. Infrastructure-error runs are counted separately and excluded from those calculations.
- Deterministic fixture/script replay is not presented as pass^k.
- Critical checks require 100 percent passage in the scripted gate.

### Flake policy

- The credential-free scripted suite is merge-gating. Every critical or major deterministic check must pass on every scenario; retries do not turn a failure into a pass.
- Prompt/schema loading, runner completion, tool argument schemas, identity ordering, pricing confidentiality and ceilings, pre-load grounding, expected transfer behavior, and scenario-specific closure/counter checks are gating in the scripted suite.
- Live GPT-4.1 runs are report-only. Reports include all attempts, errors, requested model settings, returned model ids and system fingerprints, plus pass^1 and pass^k; failed live checks do not fail the deterministic merge gate.
- Do not retry only failed live samples. Rerun the complete declared sample set and retain both reports. Promotion to gating requires a product-approved run count, pass^k threshold, retry budget, cost owner, and baseline owner.
- Rate-limit and server failures are retried with bounded backoff. An exhausted retry budget or another transport/authentication failure is recorded as an infrastructure-error trace, excluded from pass^k, and counted in the report. If a scenario has fewer than `k` behavioral runs left, its pass^k is reported as unavailable rather than as a model failure.

## Architecture

Readable JSON scenarios provide caller turns, in-memory carrier and load fixtures, and deterministic scripted-model responses. The runner loads `voice_prompt.py` and `negotiation_prompt.py` by path with an in-memory stub `src` package, avoiding the dependency-heavy package initializer. It parses `tool_definitions.py` with `ast` and converts its literal `FunctionSchema` declarations to model-facing JSON schemas. No prompt or schema content is copied into the evaluator.

Identity grading assumes a successful `verify_carrier` result unless a scenario explicitly sets `fixtures.phone_identity_confirmed` to `true`. That fixture represents production's phone-first prompt, where the caller has confirmed the carrier matched by phone lookup and no verification tool call is expected.

Every scenario declares `expected.transfer` as `true` or `false`. Transfer grading compares that declaration with observed `transfer_to_human` calls instead of trying to infer intent from caller wording; this detects both unwanted and missed transfers. Rate-leak grading recognizes standalone digits as well as currency and spoken amounts, while counter-direction grading intentionally limits amounts to currency-marked or spoken rates so dates and ZIP codes do not look like counters.

Each runner-produced trace is an ordered event log containing caller text, agent text, tool calls/results, system-prompt transitions, and fake end state. Pure graders return `pass` or `fail` with event-level evidence. The report stage aggregates results into `report.json` for automation and `report.md` for review.

Every report records the checked-out Git commit, canonical SHA-256 of the production tool schemas, SHA-256 of each scenario's rendered initial and negotiation prompts, model sampling settings, and runs per scenario. The output bundle saves deterministic traces as `traces/<scenario>.json` and live traces as `traces/<scenario>.run-<n>.json`. These hashes identify the evaluated contracts even when the working tree is not clean.

Runner failures are data: unknown tools, exhausted scripted responses, and model-step-limit violations become a critical `runner.completed` failure with the exception and attempted tool call in the trace. Prompt-contract mismatches are ordinary `prompt.critical_clauses` grader failures. Successful `end_call` and `transfer_to_human` results stop the loop before another caller turn. Scenarios default to 20 model steps and may set a lower cap.

Critical prompt contracts live in one evaluator registry. Each clause declares whether it applies to the initial or negotiation prompt and names the behavioral check it protects. The default `prompt.critical_clauses` invariant evaluates every rendered prompt; scenario scripts do not assert prompt fragments. Mutation tests remove each registered clause in turn and require a critical failure. The registry intentionally excludes the phone-identity replacement clauses already covered by `voice-agent/tests/test_voice_prompt_guardrails.py`.

The suite currently contains six end-to-end scripted scenarios covering successful agreement, above-ceiling bidding, below-goal negotiation, agreement-write failure, carrier-verification retries, and requested transfer. Default invariants grade every scenario; scenario-specific checks add the expected outcome. Unit tests inject load-lookup failure and mutate prompts, traces, tool arguments, and model behavior to prove the fakes and graders respond to their target defects.

Run the full evaluator tests and offline gate with:

```bash
python3 -m unittest discover -s evals/tests -v
python3 -m evals run
```

By default reports and saved traces go to `/tmp/frontline-evals`, keeping generated evidence out of the repository. Use `--output PATH` to retain a named evidence bundle.

Reviewed evidence is committed at [`results/offline/report.md`](results/offline/report.md), with all six runner traces beside it. [`results/unsafe/report.md`](results/unsafe/report.md) records deliberately unsafe sensitivity variants and their failing check evidence; it is not part of the green default gate. See [`README.md`](README.md) for commands and interpretation.

## External boundaries and safety

The production pipeline initializes Daily, Deepgram, OpenAI, Cartesia, Supabase, Highway or the legacy carrier API, the KCH quote API, and Slack. The default evaluator initializes none of them. Opt-in live-model runs call only OpenAI; they still use in-memory fake tools and capped model steps and repetitions. Live-model results remain separate from the credential-free merge gate.

## Production code gaps found while building the evaluator

### Code-confirmed

- `record_agreement` validates that a load is present, converts the price, and requires contact details for `above_max`, but it does not compare `agreed_price` with the loaded `maxRate`. Ceiling enforcement currently depends on the prompt and evaluator; the persistence boundary can store an over-ceiling row without `above_max=true`.
- `get_load_context` does not require a preceding successful `verify_carrier` result or an explicit phone-identity confirmation. Identity-before-load authorization currently depends on the prompt and evaluator.
- `get_load_context` passes `org_id` to `NegotiationDBService.get_load_by_reference`, and its comment describes multi-tenant isolation, but `get_load_by_reference` explicitly ignores `org_id` and delegates to an unscoped reference lookup because the current load schema has no tenant ownership field. A reference collision can therefore cross the isolation boundary implied by the call site.

These are observations, not production changes: this assessment keeps the existing single-prompt architecture and production behavior intact.

### Inferred or not verified here

- Fixed scripted caller turns can drift from a live model's preceding question. This is a runner-design limitation, not evidence of a production defect.
- Text traces cannot establish ASR accuracy, synthesized speech quality, interruption behavior, caller-heard latency, or provider reliability.
- The scenarios are synthetic and small. Their risk coverage is deliberate, but without redacted production calls they do not establish the frequency or full variety of real caller behavior.

## Assumptions and limitations

- The highest business priority is a correct, authorized negotiation outcome; policy or data-integrity failures override apparent task completion.
- The repository has no product-approved latency target, redacted production calls, or independent judge labels.
- Hand-authored fixture results measure harness sensitivity, not production model quality.
- Scripted conversation results measure integration, prompt contracts, and deterministic scenario logic, not GPT-4.1 response quality.
- Text traces can inject transcription-like errors, but they cannot measure real ASR, TTS, barge-in timing, dead air, or caller-perceived latency.
- The production model uses temperature 0.7. Any future live score needs repeated runs, pinned model metadata, and pass^k rather than a single deterministic claim.

## Product questions and current assumptions

- **When KCH `startRate` equals confidential `bookNowRate`, which instruction wins?** Assume confidentiality wins: the agent must not speak the goal. This is currently an unresolved production prompt contradiction because normalization maps both fields from `offer_rate` while the opening sequence requires saying `startRate`; the unsafe equal-rates scenario makes the collision visible.
- **Is any agreement above `maxRate` ever authorized without human approval?** Assume no: it is a critical failure unless stored with `above_max=true` for follow-up, not as an agreement.
- **Does “below goal” include equality, and may the agent simply accept a firm bid?** Assume bids at or below `bookNowRate` must never receive a higher counter; a firm bid may be accepted immediately, otherwise one lower counter is allowed.
- **Are two counteroffers mandatory even when the carrier is already below goal?** Assume the specific Zone 1 rule overrides the general two-round rule.
- **Must ordinary agreements include contact name and phone, even though the backend only enforces these for above-max bids?** Assume yes because the production prompt's closing sequence requires both; caller ID may satisfy phone only when the caller explicitly says to use it.
- **Should live GPT-4.1 results gate merges?** Assume no until run count, acceptable flake rate, budget, and baseline-approval ownership are defined; report live pass^k separately.
- **What value of `k` and how many repeats are affordable?** Assume CLI default `k=2` with `n=3` live repetitions per scenario, configurable and capped.
- **Which caller identity path is release-critical, MC-first or phone-first?** Assume MC-first for these pricing scenarios; phone-first remains a separate future scenario because the feature flag defaults off.
- **Are synthetic callers sufficient for initial acceptance?** Assume yes for the requested pricing invariants; redacted production transcripts are the next dataset source.
- **What latency and audio thresholds apply?** Assume none for this text runner; report ASR, TTS, barge-in, and caller-heard latency as not measured.

## Review and correction process

The evaluator was developed in reviewed increments. After each revision, the product reviewer ran the suite, inspected traces and reports against production code, and supplied concrete counterexamples. Those reviews corrected grader blind spots (all writes versus the last write, spoken and bare-number parsing, transfer intent, phone-first identity, third-strike timing, infrastructure exclusions, and prompt mutation coverage), removed stale design claims, and added the production gaps recorded above. The final deterministic tests preserve those corrections as regressions; scripted coverage is still not presented as live-model quality.

## Follow-up qualification

Add scenarios derived from redacted production calls, obtain independent labels for qualitative criteria, run repeated real-prompt evaluations with fake tools, and schedule a small audio-level release suite for recognition, latency, interruption, and transfer behavior.
