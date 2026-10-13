# Brief: Frontline voice agent evaluation system

- Started: 2026-10-13T22:33:08Z
- Time box: 105 minutes; freeze new build work by 23:53Z; final check by 00:13Z; reserve the final 5 minutes for a separate submission turn
- Repository: `/run/e3-hosted-codex/workspaces/2fdde2b9-9dbb-42d1-8a83-f263c42e5c35/workspace`, pinned at `5a98a66274322954a0a6255f54650eec6e50c41d`
- Documented tests: from `voice-agent/`, `python -m pytest ../shared/tests -v --tb=short` and `python -m pytest tests -v --tb=short`
- Baseline: blocked before collection. `python` is absent (exit 127); `python3 -m pytest` reports `No module named pytest` (exit 1); `python3` also has no `pip` or application dependencies. No test passed or failed because no test ran.

## Requirements (the task's own words)

- R1: Work from the Frontline Assignment repository, main at commit `5a98a66274322954a0a6255f54650eec6e50c41d`.
- R2: Design and implement an evaluation system that gives the engineering team meaningful confidence in the agent's behavior before future changes are merged.
- R3: Understand how the application works, what outcomes matter, and where failures have the greatest impact.
- R4: Decide what should be evaluated, which techniques are appropriate, and how success should be measured; prefer a useful system over a large undirected test collection.
- R5: Ask questions when missing product context would materially change the approach; state assumptions when proceeding without clarification.
- R6: Keep the existing single-prompt architecture and intended product behavior intact.
- R7: Make only justified small changes for observability or evaluability.
- R8: The suite must run safely without production credentials or live side effects.
- R9: Identify assumptions, mocked boundaries, and behavior that remains unverified.
- R10: Do not rely on undocumented infrastructure or services.

## Rubric

- C1 (20): Build an accurate model of the system and prioritize evaluations around meaningful product and engineering risks.
- C2 (25): Choose suitable evaluation methods and credible success criteria, including sound treatment of nondeterminism and external dependencies.
- C3 (20): Deliver a maintainable, safe, repeatable evaluation system that fits the repository and supports future changes.
- C4 (15): Run the evaluation system, inspect results, and provide useful evidence and failure diagnostics.
- C5 (10): Use the coding agent deliberately while independently reviewing, correcting, and validating its output.
- C6 (10): Explain assumptions, tradeoffs, omissions, limitations, and follow-up questions clearly.

## Deliverables

- A runnable evaluation suite and support code under `evals/`, using only the Python standard library for the default offline path.
- `evals/README.md` with run commands, metric interpretation, and explicit unmeasured areas.
- `evals/DESIGN.md` with scope, success criteria, design reasoning, assumptions, omissions, and limitations.
- Scenarios plus reviewed golden and known-bad traces covering the highest-risk call outcomes.
- Deterministic graders, metrics, optional judge plumbing, report generation, baseline, thresholds, and a zero-credential gate.
- Evidence from a completed offline evaluation run in committed JSON and Markdown reports.

## Repository facts

- Python 3.11 voice service built on Pipecat. `voice-agent/bot.py` creates a Daily/Deepgram/OpenAI/Cartesia pipeline and registers five carrier-facing tools.
- The production model is `gpt-4.1` with temperature `0.7`, so live behavior is nondeterministic.
- The single prompt is assembled by `voice-agent/voice_prompt.py` and `shared/src/negotiation_prompt.py`; load-specific values include confidential goal and ceiling rates.
- Carrier flow: verify MC, confirm identity, retrieve load, negotiate, record agreement or above-max bid, end call; human transfer is allowed only after a successful load lookup.
- Tool contracts: `verify_carrier(mc_number)`, `get_load_context(load_id)`, `record_agreement(agreed_price, above_max?, carrier_contact_name?, carrier_contact_phone?)`, `end_call(reason)`, and `transfer_to_human(reason, load_number, price_asked_by_carrier?, best_price_offered_by_bot?)`.
- State-changing boundaries are database writes, quote notification, Daily transfer/dial-out, Slack notification, call termination, and recording upload. They must be fake or absent in default evals.
- Highest-impact failures: unverified data access, confidential rate leakage, agreement at the wrong price, missing contact data/write, incorrect close reason, premature or missed transfer, fabricated success after a tool error, and mishandled IDs/numbers.
- Existing tests cover service helpers, carrier lookup/verification, transfer guards, and static prompt guardrails. There is no conversation-level eval harness.
- CI installs full runtime dependencies and runs shared and selected voice tests. Local baseline could not collect in this hosted image because package tooling and dependencies are absent.
- A working call requires Daily, OpenAI, Deepgram, Cartesia, Supabase, and optional transfer/quote services. Therefore the default gate must not instantiate the production pipeline.

## Assumptions and product decisions

- An accepted agreement or stored above-max bid is the primary business outcome, but policy and data-integrity failures override completion.
- Every critical deterministic check must pass. With a small initial dataset, rates are always shown with counts and are not treated as statistically representative.
- Text/offline evaluation is the merge gate. Real ASR/TTS, caller-heard latency, barge-in timing, audio quality, telephony, and provider integrations remain release checks and are reported as not measured.
- Reviewed fixture traces establish grader behavior and a reproducible baseline; they do not establish current live-model quality. An optional live-model adapter, if time permits, uses fake tools and repeated runs, never production services.
- Qualitative judge criteria do not gate until independently labeled calibration meets the predeclared bar (kappa >= 0.60 and failure recall >= 0.80). Constructed examples may validate plumbing but are not independent calibration.

## Open questions

- None blocks the plan. Product owners should later confirm the acceptable manager-escalation policy for Zone 2 and supply representative, redacted production transcripts and latency targets.
