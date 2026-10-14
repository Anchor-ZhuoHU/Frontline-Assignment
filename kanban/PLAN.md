# Plan: Frontline voice agent evaluation system

## Revised approach

Drive a small multi-turn conversation loop with the production prompt builders and production tool schemas. The loop owns in-memory fake tools, feeds each tool result back to the model, and swaps the initial system prompt for the full negotiation prompt after `get_load_context`, matching `call_helpers.py`. A pluggable scripted model keeps CI deterministic; an explicit live flag uses `gpt-4.1` at temperature `0.7`, repeats each scenario `k` times, and reports pass^k. T1's event traces, deterministic graders, and Markdown/JSON reporting remain the evaluation substrate. Judge and kappa work is removed.

The offline scripted model also validates critical prompt-contract clauses before responding. This makes deletion of those clauses fail CI, but it cannot predict how a wording-only prompt edit changes GPT-4.1 behavior. Only repeated live runs provide that behavioral signal.

## Tickets

## T1 · Design and fixture-grading skeleton   tier: mvp   status: done
- Serves: R2-R4, R8-R10 (C1-C3)
- Delivered: design note, event trace format, one agreement scenario, golden and known-bad traces, deterministic tool-argument grader, report, CLI, and 3 passing tests.
- Retained: graders and report format become the output stage of the conversation runner.

## T2 · Real-contract conversation runner   tier: mvp   status: done
- Serves: R2-R4, R6-R10 (C1-C4)
- Scope: dependency-free loaders for the real `voice_prompt.py` prompt builders using an in-memory stub `src` package and `tool_definitions.py` schemas using `ast`; model protocol; scripted model; multi-turn loop; fake clock and in-memory implementations of all five Room 1 tools; tool results fed back into the model; real prompt transition after `get_load_context`; pass^k in the conversation runner.
- Acceptance: a test observes the initial real prompt and real tool schemas, executes `get_load_context`, observes the load-specific real prompt, completes a scripted agreement, and proves no network, filesystem, database, telephony, quote, or notification side effect occurred.
- Test first: end-to-end runner test fails before the contract loader and conversation loop exist.
- Follow-up hardening: route CLI reports through runner traces; convert contract/unknown-tool errors into failed checks; stop on end/transfer and cap model steps; mirror production tool-result fields.

## T3 · Pricing-risk scenarios and graders   tier: signature   status: done
- Serves: R2-R4, R8-R9 (C1-C4)
- Scope: extend deterministic grading for call order, tool arguments, counteroffer direction, and ceiling policy; add (1) agreement above ceiling without `above_max=true` and (2) countering upward when the carrier bid is already below goal, alongside the happy path.
- Acceptance: safe scripted traces pass; each requested defect produces a critical failure with the offending amount and event id; the runner, not hand-authored traces, produces the evaluated traces.
- Test first: each deliberately unsafe scripted response reaches the grader and fails for the intended pricing rule.

## T3.1 · Production-shaped fault injection and lookup grounding   tier: signature   status: done
- Serves: R2-R4, R6-R9 (C1-C4)
- Scope: allow scenario fixtures to make `verify_carrier` return `not_found` or production-shaped `error` results and make `get_load_context` return production-shaped failures; add the third-consecutive-`not_found` MC flow from `voice_prompt.py:327`, requiring `end_call(reason="mc_not_found")`; add a default critical invariant that no rate is quoted before a successful `get_load_context` result.
- Acceptance: safe retry/error scenarios preserve the exact fake result in model context; the third `not_found` scenario calls `verify_carrier` and then ends with `mc_not_found`; deliberately quoting a currency or spoken rate before successful load lookup fails with event-level evidence.
- Test first: one failing regression for each injected result shape, the third-not-found close, and premature rate disclosure.

## T4 · Optional live GPT-4.1 repetitions, pass^k, and flake policy   tier: signature   status: done
- Serves: R2, R4, R8-R10 (C2-C4)
- Scope: opt-in model adapter behind `--live --runs K`; require only a nonempty API key without printing it; send the same real prompt, schemas, caller turns, and fake-tool results; use `gpt-4.1` at temperature `0.7`; record model, temperature, run index, token usage when returned, and errors; compute pass^1 and pass^k by scenario. Write a flake policy that makes deterministic critical invariants and runner integrity merge-gating, while repeated live-model behavior remains report-only until an approved sample size, pass^k threshold, retry policy, and baseline owner exist.
- Acceptance: fake HTTP/model tests prove request shape, tool-call parsing, no live call without both flag and key, and correct pass^k (`n=4, c=2, k=2` gives `1/6`). The report labels each check as gating or report-only. A live run is attempted only with the explicit flag and an available key.
- Test first: adapter and pass^k tests fail before implementation.

## T4.1 · Reproducible evidence bundle   tier: mvp   status: todo
- Serves: R3-R4, R8-R10 (C3-C6)
- Scope: add a reproducibility header to Markdown and JSON reports with Git commit, SHA-256 hashes of each rendered initial/negotiation prompt and the canonical production schemas, model id, temperature, `k`, and runs per scenario; save one complete trace per scripted scenario and every indexed live run under the selected output directory.
- Acceptance: fixed inputs produce stable hashes; reports contain no API key or unrelated environment data; trace filenames are deterministic and link back to scenario/run metadata; tests verify the header and trace inventory.
- Test first: report-schema and output-bundle tests fail before implementation.

## T4.2 · Critical prompt mutation sensitivity   tier: signature   status: todo
- Serves: R2-R4, R8-R9 (C1-C4)
- Scope: define one evaluator-owned list of critical prompt clauses, each mapped to the behavioral check it protects; verify that list against every rendered initial and negotiation prompt as a default invariant, outside scripted-model steps. Exclude clauses already covered by `voice-agent/tests/test_voice_prompt_guardrails.py`. Add a test-only prompt transformation seam and delete each listed clause in turn.
- Acceptance: every unmodified rendered prompt satisfies its applicable critical clauses; each single-clause mutation fails with the clause id and protected check in evidence; scenario scripts contain no prompt-clause assertions for this contract.
- Test first: parameterized mutation test deletes each listed clause and proves the default prompt-contract invariant fails.

## T4.3 · System map, risk coverage, and production code gaps   tier: mvp   status: todo
- Serves: R1-R4, R6-R10 (C3-C6)
- Scope: extend `DESIGN.md` with a concise end-to-end system map, a table mapping each product risk to its scenario/check/evidence and gating status, and a clearly labeled list of production gaps discovered during evaluation, including `record_agreement` not enforcing `maxRate` and `get_load_context` not enforcing verified identity.
- Acceptance: every critical default invariant and scenario-specific check appears in the risk table; inferred gaps are distinguished from code-confirmed gaps; the map covers prompts, model turns, tools, external side effects, persisted data, and termination. Review manually; do not add tests that grep `DESIGN.md` or the README.

## T5 · Gate, evidence, documentation, and CI   tier: mvp   status: todo
- Serves: all deliverables (C3-C6)
- Scope: update design and README; scenario assumptions and product questions; thresholds and baseline; make the offline scripted run the credential-free gate; save one completed runner-produced report; add the command to existing CI.
- Acceptance: offline gate exits zero for the accepted scripted run and nonzero for a selected unsafe model fixture; report labels scripted versus live evidence and marks audio/provider behavior not measured; documented commands run in this host.
- Test first: gate regression and documentation/CI checks fail before integration.

## Product questions and current assumptions

- Is any agreement above `maxRate` ever authorized without human approval? Assume no: it is a critical failure unless stored with `above_max=true` for follow-up, not as an agreement.
- Does “below goal” include equality, and may the agent simply accept a firm bid? Assume bids at or below `bookNowRate` must never receive a higher counter; a firm bid may be accepted immediately, otherwise one lower counter is allowed.
- Are two counteroffers mandatory even when the carrier is already below goal? Assume the specific Zone 1 rule overrides the general two-round rule.
- Must ordinary agreements include contact name and phone, even though the backend only enforces these for above-max bids? Assume yes because the production prompt's closing sequence requires both; caller ID may satisfy phone only when the caller explicitly says to use it.
- Should live GPT-4.1 results gate merges? Assume no until run count, acceptable flake rate, budget, and baseline-approval ownership are defined; report live pass^k separately.
- What value of `k` and how many repeats are affordable? Assume CLI default `k=2` with `n=3` live repetitions per scenario, configurable and capped.
- Which caller identity path is release-critical, MC-first or phone-first? Assume MC-first for these pricing scenarios; phone-first remains a separate future scenario because the feature flag defaults off.
- Are synthetic callers sufficient for initial acceptance? Assume yes for the requested pricing invariants; redacted production transcripts are the next dataset source.
- What latency and audio thresholds apply? Assume none for this text runner; report ASR, TTS, barge-in, and caller-heard latency as not measured.

## Disagreements and risks

- No product disagreement with replacing fixture-only execution; it materially improves confidence.
- A deterministic scripted model cannot measure nondeterministic model behavior or reliably predict the effect of arbitrary prompt wording changes. It can exercise the complete loop and enforce explicit prompt contracts. Repeated live runs are the behavioral measurement and should remain non-gating until the team defines a flake policy.
- The real modules are not directly importable in this host: `voice_prompt.py` reaches the dependency-heavy `src` initializer and `tool_definitions.py` imports Pipecat. The runner must use a narrow loader or a small production contract-extraction refactor, not copied prompt/schema definitions.
- Live API behavior and request shape require official documentation verification. The `openai-docs` skill was permission-blocked and unavailable through the environment skill reader, so implementation must verify against repository-installed SDK source if dependencies become available or official OpenAI documentation via web before coding the adapter.
- A scripted model can accidentally encode the expected answer. Tests must separately prove runner wiring, fake-tool state, grader sensitivity, and prompt-contract loading.
- Change: fault injection should return the same structured results as production rather than throw exceptions; this exercises the model's recovery path and keeps runner failures reserved for harness/model failures.
- Change: hash rendered prompt instances and canonical schema JSON, not source files. That captures scenario-specific prompt inputs and avoids irrelevant source-format changes invalidating evidence.
- Change: save every live run trace, not only one trace per scenario, because pass^k cannot be audited from a representative trace.
- Cut if time is constrained: do not make an actual paid live request, edit CI, or add broad provider/audio fault coverage. Keep the tested live adapter and flake policy, deterministic fault scenarios, evidence metadata, mutation test, and design coverage.
- Do not cut the premature-rate check, bidirectional transfer expectation, schema validation, or trace persistence; these are the auditable safety core.

## Cut order

1. Actual paid live execution and saved live-provider evidence; retain the mocked adapter tests.
2. CI workflow edit and cosmetic report formatting.
3. Provider/audio fault modes beyond carrier/load result injection.
4. Token/cost reporting beyond recording provider-returned usage.
