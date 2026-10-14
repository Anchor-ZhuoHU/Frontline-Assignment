# Plan

1. Establish baseline: run the declared shared and voice suites once without installing anything. Record missing dependencies or other blockers exactly.
2. Build parity traces for Daily base versus LiveKit head: inbound/outbound start, normal hang-up, explicit end-call, idle timeout, persistence, recording, and cleanup.
3. Trace successful and failed warm transfers, including what the broker hears, caller/broker disconnect races, voicemail, timeouts, duplicate callbacks, and room/leg cleanup.
4. Compare every relevant test fake with the real pinned LiveKit and Pipecat implementations. Validate uncertain provider behavior against pinned source or primary documentation.
5. Review webhook security/idempotency, PII in prompts/logs/records, database/dashboard compatibility, and operational observability.
6. Evaluate cutover and rollback: Daily routes and dependencies are deleted with no feature flag, so verify in-flight-call behavior, provider configuration sequencing, reversible data changes, and rollback instructions.
7. Write `REVIEW.md` with verified findings ordered by severity, evidence, exact tests/results, requirements status, assumptions, and unresolved questions.
8. Run the toolkit final check. Leave only `REVIEW.md` and the temporary small `kanban/` files in the workspace.

Out of scope: source fixes, production credentials, live calls, PR comments, merge, or push.
