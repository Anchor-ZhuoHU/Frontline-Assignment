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

## T4 · Optional live GPT-4.1 repetitions and pass^k   tier: signature   status: todo
- Serves: R2, R4, R8-R10 (C2-C4)
- Scope: opt-in model adapter behind `--live --runs K`; require only a nonempty API key without printing it; send the same real prompt, schemas, caller turns, and fake-tool results; use `gpt-4.1` at temperature `0.7`; record model, temperature, run index, token usage when returned, and errors; compute pass^1 and pass^k by scenario.
- Acceptance: fake HTTP/model tests prove request shape, tool-call parsing, no live call without both flag and key, and correct pass^k (`n=4, c=2, k=2` gives `1/6`). A live run is non-gating and is attempted only if an API key is already available.
- Test first: adapter and pass^k tests fail before implementation.

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

## Estimate and freeze plan

- At 23:22Z, 28 minutes remain until the requested 23:50Z freeze.
- Full revised scope is 40 to 50 minutes plus final-check time: T2 15 to 20, T3 10 to 12, T4 10 to 12, T5 8 to 10.
- To freeze by 23:50Z: deliver T2 and T3 first, then the pass^k metric and tested model interface from T4 if time remains. At 23:45Z, stop new code and finish the current coherent slice.
- Cut before freeze: real network execution, token/cost polish, CI workflow edit, broad scenario coverage, and report cosmetics. Preserve the live adapter contract in the design and implement it only if T2 and T3 are green by 23:40Z.
- After freeze: use remaining session time only for T5 documentation/evidence and `final-check`; submission remains a separate turn.

## Disagreements and risks

- No product disagreement with replacing fixture-only execution; it materially improves confidence.
- A deterministic scripted model cannot measure nondeterministic model behavior or reliably predict the effect of arbitrary prompt wording changes. It can exercise the complete loop and enforce explicit prompt contracts. Repeated live runs are the behavioral measurement and should remain non-gating until the team defines a flake policy.
- The real modules are not directly importable in this host: `voice_prompt.py` reaches the dependency-heavy `src` initializer and `tool_definitions.py` imports Pipecat. The runner must use a narrow loader or a small production contract-extraction refactor, not copied prompt/schema definitions.
- Live API behavior and request shape require official documentation verification. The `openai-docs` skill was permission-blocked and unavailable through the environment skill reader, so implementation must verify against repository-installed SDK source if dependencies become available or official OpenAI documentation via web before coding the adapter.
- A scripted model can accidentally encode the expected answer. Tests must separately prove runner wiring, fake-tool state, grader sensitivity, and prompt-contract loading.

## Cut order

1. Real network execution and saved live evidence.
2. CI workflow edit and report polish.
3. Additional scenarios beyond the two requested pricing failures and one happy path.
4. Token/cost reporting beyond recording provider-returned usage.
