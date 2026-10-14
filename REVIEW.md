# Review: COR-4078: Migrate voice calls and warm transfers to LiveKit/Telnyx

- PR: https://github.com/e3-solutions/Frontline-Assignment/pull/1
- Base: `main` at `5a98a66274322954a0a6255f54650eec6e50c41d`
- Head: `codex/cor-4078-daily-to-livekit-review` at `f93f7a5f79efdf08c18c583a6a6f7167084b93ae`
- Mode: review only

## Summary

This PR replaces Daily ingress, rooms, and transport with signed LiveKit webhooks and Telnyx-backed SIP participants. Its warm transfer is intended to pause the Room1 negotiation pipeline, play hold audio, brief a broker privately in Room2, move the broker into Room1, and retain a silent observer until either human leaves.

The design is thoughtful about answer gating, move reconciliation, and several transfer races, but the implementation is not ready to merge. The transfer's first media-gating call is incompatible with the pinned Pipecat implementation, normal agent-ended calls do not disconnect the SIP caller, and the migration removes the only working path without a cutover or rollback mechanism.

## Verdict

**Request changes.** Two common paths are broken at runtime, and the provider replacement cannot be safely staged or rolled back.

| Severity | Findings | Must-fix |
| --- | ---: | ---: |
| Critical | 2 | 2 |
| High | 3 | 3 |
| Medium | 1 | 0 |
| Low | 0 | 0 |

## Tests and checks run

| Revision | Command | Result |
| --- | --- | --- |
| Environment setup | `python3 -m venv /tmp/kanban-solo/Frontline-Assignment/venv && /tmp/kanban-solo/Frontline-Assignment/venv/bin/python -m pip install -r /tmp/kanban-solo/Frontline-Assignment/head/voice-agent/requirements.txt -r /tmp/kanban-solo/Frontline-Assignment/head/voice-agent/tests/requirements-test.txt` | Failed before dependency installation: the host Python has no `ensurepip` and reports that `python3.11-venv` must be installed. Per instruction, work stopped after this failed installation attempt. |
| PR `f93f7a5` | `SUPABASE_URL=http://test-suite.local SUPABASE_SERVICE_ROLE_KEY=test-key python3 -m pytest ../shared/tests -v --tb=short` | Blocked before collection: `/usr/bin/python3: No module named pytest`; no dependencies were installed without approval. |
| PR `f93f7a5` | `python3 -m pytest tests -v --tb=short` | Blocked before collection by the same missing `pytest`; no pass count is claimed. |
| PR `f93f7a5` | `python3 -m compileall -q voice-agent shared scripts` | Passed, exit 0. |

Base and head test counts and installed-library probes are unavailable because the requested isolated environment could not be created. No suite was rerun and no SDK reproduction script was run after the setup failure.

I also compared the PR fakes with the actual Pipecat 0.0.95 source. In particular, its `LiveKitInputTransport` inherits `BaseInputTransport`, which supports frame-driven `pause(StopFrame)` but has no `pause_processing_frames` or `resume_processing_frames` methods. Pipecat's default pipeline idle timeout is 300 seconds; passing `None` disables its idle observer. Sources: [Pipecat 0.0.95 LiveKit transport](https://github.com/pipecat-ai/pipecat/blob/v0.0.95/src/pipecat/transports/livekit/transport.py), [base input transport](https://github.com/pipecat-ai/pipecat/blob/v0.0.95/src/pipecat/transports/base_input.py), and [pipeline task](https://github.com/pipecat-ai/pipecat/blob/v0.0.95/src/pipecat/pipeline/task.py).

## Findings

### Critical

#### F1. Every warm transfer fails at the first media-gating call

- Severity: Critical
- Label: must-fix
- Location: `voice-agent/livekit_transfer_media.py:57`, `voice-agent/tests/test_livekit_transfer_media.py:9`
- Scenario: A carrier requests a broker. `TransferOrchestrator.execute_transfer_to_room2()` creates Room2, then calls `gate_primary_media(True)` before starting hold music or dialing. The call raises `AttributeError` because the real Pipecat 0.0.95 LiveKit input has neither method being invoked. The exception is converted into a failed transfer, so no broker can ever be reached.
- Cause: lines 64 and 66 call `pause_processing_frames()` and `resume_processing_frames()`. The test fake supplies those invented methods with `AsyncMock`, so the tests prove behavior against a surface the real dependency does not expose. The pinned `BaseInputTransport` instead handles `StopFrame` through `pause()` and has no matching resume helper.
- Fix: Implement gating using a supported processor or transport contract. A dedicated frame processor that drops caller audio while held is safer than pausing the shared transport, because restore must be explicit and testable. Test the adapter against Pipecat 0.0.95's real input type or at least use an interface-conformance test built from that class, rather than a free-form `SimpleNamespace`.
- Test: Add an integration-level transfer-media test that constructs the pinned LiveKit transport/input boundary, enters and exits hold, and asserts carrier frames do not reach STT/LLM while held and do resume afterward. It must fail on the current `AttributeError`.

#### F2. `end_call` leaves the SIP caller connected to an empty room

- Severity: Critical
- Label: must-fix
- Location: `voice-agent/call_helpers.py:833`, `voice-agent/bot.py:602`, `voice-agent/livekit_telephony_service.py:219`
- Scenario: A normal negotiation reaches agreement or another terminal reason and the model calls `end_call`. The queued `EndFrame` stops Pipecat and disconnects only the bot participant. The SIP participant remains in Room1, so the person hears silence instead of the phone call ending; the call can continue billing until they hang up themselves.
- Cause: Daily implicitly tied the phone room to the bot lifecycle. The LiveKit path preserved the same `EndFrame` tool but added no normal-call cleanup that removes the SIP participant or deletes Room1. The only calls to `delete_room` for Room1 are inside transfer handoff cleanup. LiveKit documents that `Room.disconnect()` only makes that participant leave, while `DeleteRoom` forcibly disconnects all participants, including SIP; its end-call examples explicitly delete the room.
- Fix: Give the normal call lifecycle an idempotent `end_room()` operation that deletes the LiveKit room after the final spoken response has drained. Invoke it for tool-requested termination, unrecoverable pipeline errors, and idle timeout, while keeping caller-originated hang-up handling safe if the room is already gone. Do not rely on the bot transport disconnect to hang up SIP.
- Test: Drive `end_call` through a normal LiveKit call with a fake that models separate bot and SIP participants. Assert the final response drains, Room1 is deleted exactly once, the SIP participant is disconnected, the recording is flushed, and `finish_call` records the requested reason.

### High

#### F3. The migration removes the 300-second idle fail-safe

- Severity: High
- Label: must-fix
- Location: `voice-agent/bot.py:363`
- Scenario: A carrier goes silent, the media connection stalls without a participant-disconnected event, or the LLM stops producing turns. On base, `PipelineTask` uses Pipecat 0.0.95's 300-second default and cancels an idle pipeline. The PR passes `idle_timeout_secs=None`, so the task, SIP participant, recording, and single-call runner slot can remain active indefinitely.
- Cause: The explicit `None` disables the idle monitor. There is no replacement call-duration timer, SIP `max_call_duration`, or pipeline idle handler. This also amplifies F2 because there is no server-side backstop for an abandoned call.
- Fix: Preserve a bounded idle timeout, make it configurable with a safe default, and on timeout play any required closing prompt before using the same idempotent Room1 termination from F2. Also set a provider-side maximum call duration as a final guard.
- Test: Use a short configured timeout and no `BotSpeakingFrame` or `UserSpeakingFrame`; assert the pipeline ends, recording and call record finalize, Room1 is deleted, and the bot-runner slot becomes available.

#### F4. There is no safe cutover or rollback path after deleting Daily

- Severity: High
- Label: must-fix
- Location: `voice-agent/server.py:108`, `voice-agent/requirements.txt:1`, `docs/LOCAL_SETUP.md:73`
- Scenario: Deploy the application before every number, webhook, trunk, dispatch rule, and secret is switched. Daily continues sending existing or late callbacks to its former endpoint, which is now absent, while new LiveKit calls may not yet route. If LiveKit/Telnyx fails qualification after deployment, rollback requires reverting code and dependencies and reconfiguring provider webhooks, rather than flipping traffic back. In-flight calls have no provider-pinned route for late events.
- Cause: The PR deletes the Daily endpoint, client, room pool, dependency, and configuration in the same change. There is no per-number or per-tenant provider flag, no compatibility handler, no staged routing plan, and no documented rollback verification. The additive database columns support dual attribution, but the runtime does not support dual operation.
- Fix: Keep both provider paths temporarily behind one call-start routing decision that is stored on the call record. Roll out by test number or tenant, preserve the Daily webhook until all old calls and provider retries have drained, label metrics by provider, and document the order for provisioning, traffic shift, validation, rollback, and eventual Daily removal. If a dual runtime is intentionally impossible, split removal into a later PR and provide an operational maintenance-window plan with tested revert steps.
- Test: Add routing tests for Daily-selected and LiveKit-selected calls, including a flag flip during an active call and a late Daily completion after new calls have moved to LiveKit. Each event must stay on the provider recorded at call start.

#### F5. The new logs can emit caller phone numbers as participant identities

- Severity: High
- Label: must-fix
- Location: `voice-agent/bot.py:521`, `voice-agent/bot.py:532`
- Scenario: An inbound SIP caller joins under the default LiveKit dispatch behavior. The start and carrier-tracking logs write `identity={identity}` at info level. LiveKit documents that SIP participant identity defaults to the phone number unless the dispatch rule hides phone numbers or assigns another identity, so production application logs receive caller PII.
- Cause: The repository setup configures a dispatch rule but neither requires `hide_phone_number` nor masks identities before logging. The fake events use `sip-caller-1`, which conceals the real default. Base already logs full transcripts at info level; that is pre-existing and should be handled separately, but these identity log lines are introduced by this PR.
- Fix: Never log participant identity or phone attributes directly. Log an internal call ID and opaque event/participant SID, mask any operationally necessary number, and document or provision `hide_phone_number` on the inbound dispatch rule. Audit exception logging for provider payloads as part of the same change.
- Test: Feed an inbound participant whose identity is an E.164 number, capture info-level logs, and assert neither the full number nor transcript content appears.

### Medium

#### F6. Webhook deduplication is racy and process-local

- Severity: Medium
- Label: suggestion
- Location: `voice-agent/server.py:123`
- Scenario: LiveKit retries the same signed event while the first request is still awaiting the bot runner, or two server instances receive it. Both requests observe that the ID is absent because the set is updated only after the side effect. They can both mint tokens and start the agent. In one runner the second request becomes a 503; with multiple runners it can start two bots for one caller. The in-memory set also grows for the life of the process and is lost on restart.
- Cause: the handler performs a non-atomic check at lines 123-124, awaits the side effect at line 140, and only records the event at line 141. The test sends duplicates sequentially and therefore misses the race.
- Fix: Claim the event ID atomically before the side effect in a bounded shared idempotency store, track processing/succeeded states, and return a successful acknowledgement for duplicate deliveries. If the fixed single-process deployment is a hard constraint, at minimum guard the bounded set with a lock and reserve the ID before awaiting.
- Test: Issue two concurrent requests with the same verified event and a blocked bot starter. Assert one start call and successful idempotent responses; add a restart or second-instance test if the service can scale horizontally.

## Normal-call parity

| Behavior | Daily base | LiveKit PR | Assessment |
| --- | --- | --- | --- |
| Call start | Daily waits for both `on_dialin_connected` and the real participant before recording, call creation, and `LLMRunFrame`. | Signed `participant_joined` ingress starts the bot; Pipecat also detects participants already in the room and matches the supplied SID/identity. | Substantially preserved, subject to real-service qualification. |
| Caller hangs up | Matching Daily client disconnect stops recording and cancels the task. | Matching LiveKit participant disconnect stops recording, handles transfer cancellation if active, and cancels the task. | Preserved in code. |
| Agent ends call | Ending the Daily pipeline also ends the bot-owned phone room. | `EndFrame` disconnects only the bot and does not delete Room1 or remove SIP. | Broken, F2. |
| Idle timeout | Pipecat default: 300 seconds. | Explicitly disabled with `None`; no provider maximum replaces it. | Regression, F3. |

## What the broker hears and what is recorded

The intended privacy boundary is correct in shape: the broker is dialed into Room2, and the Room2 LLM starts only after both `wait_until_answered` returns and broker audio is subscribed. The prompt briefs from the entire carrier conversation, includes transfer reason, load number, offered prices, and internal pricing, and instructs the model to share all context with the broker. The broker consultation is recorded separately and appended to the call transcript with a `[BROKER CONSULTATION]` prefix.

This remains unqualified against a real call. `wait_until_answered` treats voicemail as answered, which the PR explicitly defers, and there is no human confirmation or voicemail classifier. The prompt also has no explicit minimization or grounding rule for sensitive caller statements. Because those limitations are disclosed in the PR description, I treat them as accepted scope risks rather than additional defects, but production enablement should require voicemail handling and a bounded, PII-minimized briefing contract.

## Requirements

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| R1 | Migrate webhook, rooms, Pipecat transport, and outbound dialing from Daily to LiveKit/Telnyx. | Partly met | New boundaries exist, but normal termination and idle lifecycle are not equivalent (F2, F3). |
| R2 | Preserve the single-prompt negotiation architecture. | Met | Room1 retains one context and existing tool handlers in `voice-agent/bot.py`. |
| R3 | Keep the carrier connected and privately brief the broker before handoff. | Not met | The first hold/gating operation cannot run against Pipecat 0.0.95 (F1). |
| R4 | Distinguish answer from early media and verify participant movement before success. | Met in code, not integration-tested | Answer plus subscribed-audio gates and destination reconciliation are present; declared tests could not run locally. |
| R5 | Clean both rooms across success, failure, disconnect, timeout, and competing callbacks. | Partly met | Transfer cleanup is extensive, but normal-call rooms are omitted and webhook idempotency is racy (F2, F6). |
| R6 | Record transfer only after broker arrival; preserve transcript and consultation recording references. | Met in code, not integration-tested | `HANDOFF_COMPLETE` follows verified movement; audit data is appended during finalization. |
| R7 | Isolate Slack failure and attribute records by provider. | Met in code | Notification exceptions are isolated; schema and dashboard add provider fields. |
| R8 | Provide merge-ready evidence and operational safety for a real-time calling migration. | Not met | Tests were not runnable in this environment, core fakes diverge from pinned code, and no cutover/rollback exists. |

## Questions for the author

- Q1. Which exact `livekit-api` version was used for the claimed signature check? `requirements.txt` allows any `>=1,<2`, so the installation is not fully pinned or reproducible.
- Q2. Is the webhook server guaranteed to remain a single process for its entire lifetime? The PR states transfer state is process-local to a fixed single-call runner, but that does not establish ingress idempotency across deploys or replicas.
- Q3. Is sharing the complete carrier conversation and all internal pricing with every configured transfer destination an approved data policy? If not, Room2 needs explicit field allowlisting, grounding, masking, and output length limits.

## Assumptions and unresolved integration risks

- I assumed standard LiveKit Cloud because `MoveParticipant` is Cloud-only. A self-hosted target would make the handoff unsupported.
- I treated voicemail classification and durable crash recovery as declared future scope, not hidden findings. They remain launch risks.
- Real LiveKit/Telnyx calls, speech providers, Supabase persistence, Slack, and the dashboard were not exercised because no provisioned development services or credentials were available.
- The existing info-level full-transcript logging predates this PR. It is a material PII concern, but not a PR-introduced finding.

## Not reviewed

- Existing review comments and every other pull request, by instruction.
- Production provider configuration or live calls.
- Visual dashboard behavior and the private UI package build.
- Exact Telnyx trunk behavior beyond LiveKit's documented SIP contract.
