# Plan: Frontline voice agent evaluation system

## Approach

Build a small, dependency-free offline harness around readable JSON scenarios and event traces. Grade outcomes and policy invariants from tool calls, ordering, arguments, agent text, and end state. Use reviewed golden and one-defect known-bad traces to prove each grader, then aggregate counts into a human and machine report with a strict CI gate. Integrate the gate into the existing workflow without touching the production prompt or pipeline. Label replay evidence honestly: it validates the eval system and contracts, while live model, audio, and providers remain unverified.

## Tickets

## T1 · Design and end-to-end walking skeleton   tier: mvp   status: done
- Serves: R2-R4, R8-R10 (C1-C3)
- Scope: `evals/DESIGN.md`, package skeleton, one agreement scenario, golden/bad trace, loader, one grader, runner, report and CLI.
- Acceptance: `python3 -m unittest evals.tests.test_grading` passes; `python3 -m evals run` produces JSON/Markdown with scenario evidence without credentials or network.
- Test first: loader/grader/CLI test fails because the eval package and command do not exist.

## T2 · High-risk deterministic graders and scenario breadth   tier: signature   status: todo
- Serves: R2-R4, R8-R9 (C1-C4)
- Scope: graders for tool args/order, forbidden disclosures, agreement sequence, transfer correctness, failure grounding, end reason; scenarios/traces for verification, happy agreement, above-max bid, human transfer, tool failure, out-of-scope request, and ASR-like ID correction.
- Acceptance: each critical grader passes its golden and fails its targeted known-bad trace with event-level evidence; scenario coverage table has every critical condition represented.
- Test first: table-driven grader tests fail on missing checks and fixtures.

## T3 · Metrics, judge calibration plumbing, baseline, and gate   tier: mvp   status: todo
- Serves: R2, R4, R8-R10 (C2-C4)
- Scope: task completion, policy compliance, transfer matrix, field capture, pass^k and Cohen's kappa helpers; fake-client judge parser/cache tests; thresholds, baseline, reports, gate.
- Acceptance: metric unit tests use hand-calculated values; malformed judge output is an error; baseline gate exits 0 and a known-regression report exits nonzero; qualitative criteria remain report-only unless calibration qualifies.
- Test first: metric, judge-plumbing, and gate tests fail before implementations exist.

## T4 · Agent contract checks and optional safe live seam   tier: signature   status: todo
- Serves: R2-R4, R6-R10 (C1-C3)
- Scope: load the real generated prompt when available, verify safety-critical instructions and production tool names; document or implement a fake-tool live-model seam that cannot reach production services.
- Acceptance: prompt contract check fails when a required policy fragment is removed; offline gate needs no provider packages or keys; any live mode is explicit, capped, and non-gating with repeated-run/pass^k semantics.
- Test first: contract test fails before the adapter/check exists.

## T5 · CI, run evidence, and hand-off documentation   tier: mvp   status: todo
- Serves: R2, R8-R10 and all deliverables (C3-C6)
- Scope: `evals/README.md`, existing GitHub workflow, final reports and baseline, limitations and release-check checklist.
- Acceptance: documented commands work in this environment; CI runs the offline gate before dependency-heavy functional tests; a clean full eval run writes inspectable evidence with counts and unmeasured metrics.
- Test first: README command and CI-step checks fail before documentation/integration.

## T6 · Extra personas and report polish   tier: stretch   status: todo
- Serves: R2-R4 (C2, C4)
- Scope: additional Zone 1/2/3 negotiation variants, richer Markdown breakdowns, optional audio-run manifest.
- Acceptance: new scenarios add a distinct risk or edge case and remain covered by a targeted known-bad trace.
- Test first: coverage assertion names the missing risk tag.

## Cut order

1. T6 extra personas and report polish.
2. Optional live-model execution in T4; retain the safe seam and explicit design.
3. Judge features beyond parser/cache/calibration metrics; never claim unrun judge quality.
4. Reduce scenario count while retaining one case per critical risk and every required end-to-end layer.

## Risks

- Hosted Python lacks pip and project dependencies. Fallback: default harness and its tests use only the standard library; existing dependency-heavy tests remain a documented baseline blocker.
- Production agent has no simple text-turn function and its Pipecat pipeline initializes external providers. Fallback: offline trace grading plus direct prompt contract checks; clearly distinguish harness validation from live-agent validation.
- Hand-authored traces can make baseline scores look stronger than warranted. Reports will label their provenance, include known-bad sensitivity evidence, show N, and avoid a claim of measured production quality.
- Time is tight. Freeze new work at 23:53Z, preserve T1-T5, then run `final-check`; submission stays in a separate user-requested turn.
