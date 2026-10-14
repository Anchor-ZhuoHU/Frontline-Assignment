# Review: COR-4078: Migrate voice calls and warm transfers to LiveKit/Telnyx

- PR: https://github.com/e3-solutions/Frontline-Assignment/pull/1
- Base: `main` at `5a98a66274322954a0a6255f54650eec6e50c41d`
- Head: `codex/cor-4078-daily-to-livekit-review` at `f93f7a5f79efdf08c18c583a6a6f7167084b93ae`
- Mode: review only

## Summary

This PR replaces Daily ingress, rooms, and transport with signed LiveKit webhooks and Telnyx-backed SIP participants. Its warm transfer is intended to pause the Room1 negotiation pipeline, play hold audio, brief a broker privately in Room2, move the broker into Room1, and retain a silent observer until either human leaves.

The design is thoughtful about answer gating, move reconciliation, and several transfer races, but the implementation is not ready to merge. Production webhook events reject every real SIP participant before bot startup, caller audio is not actually gated during hold or after handoff, every broker connection is rejected because a participant SID is used to query an identity-keyed map, and the failed-transfer recovery announcement cannot be constructed.

## Verdict

**Request changes.** Real inbound calls cannot start; the warm-transfer path cannot complete or notify the caller of failure; its intended privacy boundary does not stop carrier speech from reaching the model and transcript; and the provider replacement cannot be safely staged or rolled back.

| Severity | Findings | Must-fix |
| --- | ---: | ---: |
| Critical | 6 | 6 |
| High | 2 | 2 |
| Medium | 2 | 0 |
| Low | 0 | 0 |

## Tests and checks run

| Revision | Command | Result |
| --- | --- | --- |
| Environment setup | `python3 -m venv /tmp/kanban-solo/Frontline-Assignment/venv && /tmp/kanban-solo/Frontline-Assignment/venv/bin/python -m pip install -r /tmp/kanban-solo/Frontline-Assignment/head/voice-agent/requirements.txt -r /tmp/kanban-solo/Frontline-Assignment/head/voice-agent/tests/requirements-test.txt` | Failed before dependency installation: the host Python has no `ensurepip` and reports that `python3.11-venv` must be installed. Per instruction, work stopped after this failed installation attempt. |
| PR `f93f7a5` | `SUPABASE_URL=http://test-suite.local SUPABASE_SERVICE_ROLE_KEY=test-key python3 -m pytest ../shared/tests -v --tb=short` | Blocked before collection: `/usr/bin/python3: No module named pytest`; no dependencies were installed without approval. |
| PR `f93f7a5` | `python3 -m pytest tests -v --tb=short` | Blocked before collection by the same missing `pytest`; no pass count is claimed. |
| PR `f93f7a5` | `python3 -m compileall -q voice-agent shared scripts` | Passed, exit 0. |
| SDK source | `python3 -m zipfile -l /tmp/livekit_protocol-1.1.27-py3-none-any.whl \| rg 'livekit/protocol/(models\|models_pb2\|webhook)'` | Exit 0: the wheel lists `models.py`, `models.pyi`, `webhook.py`, and `webhook.pyi`; it contains no `models_pb2` module. |
| PR `f93f7a5` race reproduction | `python3 /tmp/reproduce_transfer_carrier_races.py` | Passed, exit 0. The script loads the real pinned `orchestrator.py` and `transfer_state.py` via `git show` and stubs only external telephony, notification, logging, and Pipecat-facing boundaries. Both carrier-departure races reproduced; event order is recorded in F5. |

Base and head test counts and installed-library probes are unavailable because the requested isolated environment could not be created. No suite was rerun and no SDK reproduction script was run after the setup failure.

I also compared the PR fakes with the actual Pipecat 0.0.95 and LiveKit SDK source. `WebhookReceiver.receive()` returns a protobuf `WebhookEvent`; in `livekit-protocol` 1.1.27, `ParticipantInfo.kind` is an integer-backed enum and the wheel contains `livekit/protocol/models.py`, not `models_pb2.py`. Pipecat 0.0.95's `TTSSpeakFrame` dataclass accepts only `text`. `LiveKitInputTransport` inherits `BaseInputTransport`, which in turn inherits the `FrameProcessor` methods `pause_processing_frames()` and `resume_processing_frames()`. Those methods pause only frames traversing that processor's internal input/process queues. LiveKit audio instead enters through `push_audio_frame()` and `BaseInputTransport`'s separate audio task, which calls `push_frame()` directly and is controlled by the transport `_paused` state, not the frame-processor queue pause. Pipecat's participant callbacks pass SIDs, while LiveKit RTC's `Room.remote_participants` map is keyed by identity. Pipecat's default pipeline idle timeout is 300 seconds; passing `None` disables its idle observer. Sources: [LiveKit webhook receiver](https://github.com/livekit/python-sdks/blob/main/livekit-api/livekit/api/webhook.py), [LiveKit protocol models](https://github.com/livekit/python-sdks/blob/main/livekit-protocol/livekit/protocol/models.py), [Pipecat 0.0.95 frames](https://github.com/pipecat-ai/pipecat/blob/v0.0.95/src/pipecat/frames/frames.py), [frame processor](https://github.com/pipecat-ai/pipecat/blob/v0.0.95/src/pipecat/processors/frame_processor.py), [LiveKit transport](https://github.com/pipecat-ai/pipecat/blob/v0.0.95/src/pipecat/transports/livekit/transport.py), [base input transport](https://github.com/pipecat-ai/pipecat/blob/v0.0.95/src/pipecat/transports/base_input.py), [LiveKit RTC room API](https://docs.livekit.io/reference/python/livekit/rtc/room.html), and [pipeline task](https://github.com/pipecat-ai/pipecat/blob/v0.0.95/src/pipecat/pipeline/task.py).

## Findings

### Critical

#### F1. Every real inbound SIP webhook is rejected before the bot starts

- Severity: Critical
- Label: must-fix
- Location: `voice-agent/livekit_ingress.py:195`, `voice-agent/tests/test_livekit_ingress.py:31`
- Scenario: LiveKit sends a signed `participant_joined` webhook for an inbound SIP caller. The production `WebhookReceiver.receive()` returns a protobuf `WebhookEvent`, so `participant.kind` is the integer enum value `3`. `_participant_is_sip()` derives the string `"3"`, fails its name checks, then its fallback import raises `ImportError`; the helper returns `False`. The ingress rejects the valid event with HTTP 422 `NOT_SIP_PARTICIPANT`, and no bot starts for any real inbound call.
- Cause: The helper assumes the protobuf enum value exposes a `.name` or stringifies to an enum name. It then imports `ParticipantInfo` from `livekit.protocol.models_pb2`, but the resolved `livekit-protocol` 1.1.27 wheel ships `livekit/protocol/models.py` and no `models_pb2.py`. The unit fake sets `kind="SIP"`, a representation the real protobuf does not return, so it bypasses the broken fallback.
- Fix: Import the generated model from the supported package surface, for example `from livekit.protocol.models import ParticipantInfo`, and compare the numeric value with `ParticipantInfo.SIP` (or use `ParticipantInfo.Kind.Name(value)`). Pin the exact LiveKit API/protocol versions so this production boundary is reproducible.
- Test: Build a real `livekit.protocol.webhook.WebhookEvent` with `participant.kind = ParticipantInfo.SIP`, pass it through `parse_verified_sip_event()`, and assert it is accepted. Also assert `STANDARD` is rejected. Do not represent protobuf enums as strings in the fake.

#### F2. Hold and handoff do not stop carrier audio from reaching STT, the LLM, tools, or the saved transcript

- Severity: Critical
- Label: must-fix
- Location: `voice-agent/livekit_transfer_media.py:57`, `voice-agent/call_helpers.py:792`, `voice-agent/tests/test_livekit_transfer_media.py:9`
- Scenario: A carrier requests a broker and continues speaking while on hold, or speaks with the broker after handoff. `gate_primary_media(True)` returns successfully, but the carrier's audio continues downstream through STT and the Room1 LLM. Those utterances can be acted on by the model and are appended to the saved transcript. During hold, `skip_tts` suppresses audible bot output but does not stop inference or tools; `end_call` is blocked only in `HUMAN_ONLY`, not the `TRANSFER_HOLD` state, so the hidden Room1 agent can still terminate the call. After handoff the primary pipeline remains present as an observer, so the human conversation remains exposed to STT/LLM and persistence.
- Cause: Pipecat 0.0.95 does define `pause_processing_frames()` on `FrameProcessor`, inherited by `BaseInputTransport`; the defect is semantic, not a missing method. That pause blocks the processor's own queued-frame task. LiveKit's input task calls `push_audio_frame()`, and `BaseInputTransport`'s separate audio task sends audio with `push_frame()` when its transport `_paused` flag is false. `pause_processing_frames()` does not set `_paused`, so this media path bypasses the paused processor queue. The fake only asserts that the two methods were called and never sends an audio frame through the real input path.
- Fix: Put an explicit input gate before STT (or use a transport operation that demonstrably gates `push_audio_frame`/the audio task) and keep it closed throughout consultation and human-only handoff. Disable Room1 model/tool processing while gated, guard `end_call` for every non-bot-active state, and ensure the post-handoff observer is isolated from conversation media. Define explicitly whether held speech is discarded rather than replayed on resume.
- Test: With the pinned Pipecat input implementation, send carrier audio before hold, during `TRANSFER_HOLD`, after a failed-transfer resume, and after `HUMAN_ONLY` handoff. Assert only the permitted frames reach STT, LLM/tool dispatch, and transcript persistence; also assert an `end_call` attempt during hold cannot terminate the call.

#### F3. Room2 rejects the real broker because it looks up a SID in an identity-keyed map

- Severity: Critical
- Label: must-fix
- Location: `voice-agent/room2_pipeline_service.py:246`, `voice-agent/tests/test_room2_pipeline_service.py:10`
- Scenario: The broker answers and Pipecat emits participant/audio events with the broker SID. `track_human()` cannot recover the broker identity, compares `None` with the expected identity, and returns `False`. `_broker_connected` and `_broker_media_ready` are never both established, so `wait_for_broker()` times out and transfer cleanup drops the answered broker. This makes every normally configured warm transfer fail before handoff.
- Cause: line 254 calls `remote_participants.get(participant_id)`, but Pipecat's callbacks supply `participant.sid` and LiveKit RTC documents and implements `remote_participants` as a map keyed by participant identity. Pipecat 0.0.95's `get_participant_metadata(participant_id)` makes the same SID-as-key lookup and therefore does not rescue the identity. The unit fake hides both mismatches by constructing `remote_participants={"PA_broker": participant}`, keyed by SID, and omitting a `sid` attribute, unlike the real SDK.
- Fix: Resolve the callback SID by searching the real participant values for a matching `participant.sid` (or retain an explicit SID-to-identity mapping from the SDK participant event), then compare the resolved identity with the dialed identity. Avoid reaching through `_client` where possible; encapsulate the Pipecat-version workaround in one adapter.
- Test: Make the fake match LiveKit: key the map by `broker-expected`, set `participant.identity="broker-expected"` and `participant.sid="PA_broker"`, and emit `PA_broker`. Assert connected/media-ready are set only for that pair, then cover an unexpected SID and unexpected identity. Add an adapter test against the pinned SDK mapping contract.

#### F4. Failed transfers silently strand the caller after hold music stops

- Severity: Critical
- Label: must-fix
- Location: `voice-agent/livekit_transfer_media.py:145`, `voice-agent/orchestrator.py:450`, `voice-agent/orchestrator.py:492`, `voice-agent/transfer_tool_handler.py:135`
- Scenario: A transfer fails or times out. Recovery stops hold music and restores the primary path, then tries to tell the carrier that the transfer is unavailable. Constructing `TTSSpeakFrame(text=text, append_to_context=False)` raises `TypeError`, because Pipecat 0.0.95's frame has only a `text` field. Both orchestrator call sites suppress that exception. The carrier therefore hears the hold music stop but receives no failure announcement. The Room1 context is not updated either: its last tool result still says `status: "transferring"`. Because F3 makes every broker attempt time out, this is the current outcome for every caller who requests a broker after the ingress blocker is fixed.
- Cause: The implementation uses a frame argument that does not exist in the pinned Pipecat version, tests the orchestrator with a `FakeMedia.play_primary_announcement()` that never constructs the real frame, and deliberately discards all announcement exceptions. Recovery changes transport state but provides neither a reliable caller notification nor a failure state to the single-prompt agent.
- Fix: Queue `TTSSpeakFrame(text=text)` using the pinned API and separately append a bounded transfer-failure event/result to the Room1 context before resuming the LLM. Do not silently suppress customer-notification failures: log them and use a tested fallback or terminate the call cleanly if speech cannot be restored.
- Test: Exercise `_terminal_failure()` with the real `LiveKitTransferMedia.play_primary_announcement()` boundary and a collecting pipeline task. Assert hold stops, the input gate is restored, exactly one valid `TTSSpeakFrame` containing `TRANSFER_UNAVAILABLE_MESSAGE` is queued, and the Room1 context no longer says the transfer is in progress. Make the queue fail in a second test and assert the failure is observable and follows the defined fallback.

#### F5. Carrier departure does not cancel an in-flight transfer attempt

- Severity: Critical
- Label: must-fix
- Location: `voice-agent/orchestrator.py:130`, `voice-agent/orchestrator.py:215`, `voice-agent/orchestrator.py:316`, `voice-agent/transfer_state.py:90`
- Scenario: `on_carrier_left_primary()` calls `_terminal_failure()`, cleans the resources currently known, and marks the attempt complete, but it neither cancels nor joins the coroutine running `execute_transfer_to_room2()`. That coroutine does not re-check terminal state after awaited operations. If departure occurs during Slack notification, cleanup deletes Room2 and stops its pipeline; the resumed attempt nevertheless transitions to `DIALING_BROKER`, dials a broker into the deleted room, then dereferences the now-`None` pipeline. The answered late leg is never removed. If departure occurs while `create_room()` is pending, cleanup knows no Room2 yet; after the API returns, the cancelled attempt builds the media and pipeline, dials the broker, and transitions back to `CONSULTING` with no carrier and with Room2 still owned.
- Cause: The orchestrator stores no attempt task or cancellation token. Terminal cleanup races independently with the still-running sequence, and `TransferState.transition()` unconditionally overwrites terminal phases, allowing `CANCELLED` or `FAILED` attempts to become active again. The exception handler's later `_terminal_failure()` is a no-op because `_transfer_in_progress` is already false, so it cannot clean resources created after the first cleanup.
- Fix: Give each attempt an owned task plus immutable attempt ID/cancellation signal. On carrier departure, signal cancellation, cancel and await the attempt, then clean every resource it created, including a late answered broker. After each external await, verify that the same attempt is still active before mutating state or starting the next side effect. Make terminal phases absorbing in `transition()` and reject transitions for stale attempts. Keep cleanup idempotent so cancellation during `create_room`, notify, dial, and media readiness converges on one terminal owner.
- Test: Cover carrier departure while each external await is blocked. Assert no post-terminal dial or active-phase transition, and assert late-created rooms and late-answered participants are removed. The real-orchestrator reproduction produced these event orders:

  - During Slack notify: `create_room → gate/start hold → Room2 pipeline start → notifier enter → carrier disconnect → pipeline stop → delete Room2 → media cleanup → phase=cancelled → notifier return → dial_phone(deleted Room2) → phase=dialing_broker, room2_name=None`.
  - During `create_room`: `create_room enter → carrier disconnect → phase=cancelled → create_room returns → gate/start hold → Room2 pipeline start → notify → dial_phone → mark answered → wait for broker → phase=consulting, room2_name=room2, pipeline still owned`.

#### F6. `end_call` leaves the SIP caller connected to an empty room

- Severity: Critical
- Label: must-fix
- Location: `voice-agent/call_helpers.py:833`, `voice-agent/bot.py:602`, `voice-agent/livekit_telephony_service.py:219`
- Scenario: A normal negotiation reaches agreement or another terminal reason and the model calls `end_call`. The queued `EndFrame` stops Pipecat and disconnects only the bot participant. The SIP participant remains in Room1, so the person hears silence instead of the phone call ending; the call can continue billing until they hang up themselves.
- Cause: Daily implicitly tied the phone room to the bot lifecycle. The LiveKit path preserved the same `EndFrame` tool but added no normal-call cleanup that removes the SIP participant or deletes Room1. The only calls to `delete_room` for Room1 are inside transfer handoff cleanup. LiveKit documents that `Room.disconnect()` only makes that participant leave, while `DeleteRoom` forcibly disconnects all participants, including SIP; its end-call examples explicitly delete the room.
- Fix: Give the normal call lifecycle an idempotent `end_room()` operation that deletes the LiveKit room after the final spoken response has drained. Invoke it for tool-requested termination, unrecoverable pipeline errors, and idle timeout, while keeping caller-originated hang-up handling safe if the room is already gone. Do not rely on the bot transport disconnect to hang up SIP.
- Test: Drive `end_call` through a normal LiveKit call with a fake that models separate bot and SIP participants. Assert the final response drains, Room1 is deleted exactly once, the SIP participant is disconnected, the recording is flushed, and `finish_call` records the requested reason.

### High

#### F7. The migration removes the 300-second idle fail-safe and can permanently occupy the only runner slot

- Severity: High
- Label: must-fix
- Location: `voice-agent/bot.py:365`, `voice-agent/bot.py:693`, `voice-agent/server_utils.py:44`
- Scenario: A carrier can hang up after the webhook starts the bot task but before the bot joins Room1. Because the caller has already left, the bot receives no participant-connected or participant-disconnected event to cancel its pipeline. With `idle_timeout_secs=None`, the pipeline waits indefinitely and `_active_bot_task` permanently occupies the single-call runner. Every later `/start` receives 409 at `bot.py:693`; `start_bot_local()` converts that rejection to 503 at `server_utils.py:46`, so all subsequent inbound calls receive no agent until the process restarts. Silence, stalled media, or an LLM that stops producing turns can reach the same unbounded state.
- Cause: The explicit `None` disables Pipecat's 300-second idle monitor. There is no bot-join deadline, call-duration timer, SIP `max_call_duration`, or pipeline idle handler, and runner admission has no stale-task reclamation. This also amplifies F6 because there is no server-side backstop for an abandoned call.
- Fix: Preserve a bounded idle timeout with a safe default, add a short deadline for the expected caller to be observed after bot startup, and make either timeout cancel/finalize the pipeline and release `_active_bot_task`. On ordinary timeout, play any required closing prompt before using the idempotent Room1 termination from F6. Add a provider-side maximum duration as a final guard.
- Test: Start the bot after the expected SIP participant has already left and emit no participant event. With short configured join/idle deadlines, assert the pipeline exits and a second `/start` is accepted rather than returning 409/503. Retain a silence test that asserts recording and call records finalize and Room1 is deleted.

#### F8. There is no safe cutover or rollback path after deleting Daily

- Severity: High
- Label: must-fix
- Location: `voice-agent/server.py:108`, `voice-agent/requirements.txt:1`, `docs/LOCAL_SETUP.md:73`
- Scenario: Deploy the application before every number, webhook, trunk, dispatch rule, and secret is switched. Daily continues sending existing or late callbacks to its former endpoint, which is now absent, while new LiveKit calls may not yet route. If LiveKit/Telnyx fails qualification after deployment, rollback requires reverting code and dependencies and reconfiguring provider webhooks, rather than flipping traffic back. In-flight calls have no provider-pinned route for late events.
- Cause: The PR deletes the Daily endpoint, client, room pool, dependency, and configuration in the same change. There is no per-number or per-tenant provider flag, no compatibility handler, no staged routing plan, and no documented rollback verification. The additive database columns support dual attribution, but the runtime does not support dual operation.
- Fix: Keep both provider paths temporarily behind one call-start routing decision that is stored on the call record. Roll out by test number or tenant, preserve the Daily webhook until all old calls and provider retries have drained, label metrics by provider, and document the order for provisioning, traffic shift, validation, rollback, and eventual Daily removal. If a dual runtime is intentionally impossible, split removal into a later PR and provide an operational maintenance-window plan with tested revert steps.
- Test: Add routing tests for Daily-selected and LiveKit-selected calls, including a flag flip during an active call and a late Daily completion after new calls have moved to LiveKit. Each event must stay on the provider recorded at call start.

### Medium

#### F9. Fixing participant identity lookup will expose caller phone numbers in new logs

- Severity: Medium
- Label: suggestion
- Location: `voice-agent/bot.py:521`, `voice-agent/bot.py:532`
- Scenario: Today `_participant_identity()` repeats F3's SID lookup against an identity-keyed map, so lines 521 and 532 log `identity=None`; this is not a current phone-number disclosure. Once F3 is fixed, the same info-level log statements will receive the real SIP identity. LiveKit's default inbound identity can be the caller's phone number unless the dispatch rule hides it or assigns another identity, making the leak latent in the required fix.
- Cause: The new log statements interpolate the resolved identity without masking, while repository setup neither requires `hide_phone_number` nor assigns an opaque identity. The fake events use `sip-caller-1`, concealing the production default. Base already logs full transcripts at info level; that is pre-existing and should be handled separately.
- Fix: Never log participant identity or phone attributes directly. Log an internal call ID and opaque event/participant SID, mask any operationally necessary number, and document or provision `hide_phone_number` on the inbound dispatch rule. Audit exception logging for provider payloads as part of the same change.
- Test: Feed an inbound participant whose identity is an E.164 number, capture info-level logs, and assert neither the full number nor transcript content appears.

#### F10. Webhook deduplication is racy and process-local

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
| Call start | Daily waits for both `on_dialin_connected` and the real participant before recording, call creation, and `LLMRunFrame`. | A real protobuf SIP kind is rejected with 422 before the bot runner is called. | Broken, F1. |
| Caller hangs up | Matching Daily client disconnect stops recording and cancels the task. | Matching LiveKit participant disconnect stops recording, handles transfer cancellation if active, and cancels the task. | Preserved in code. |
| Agent ends call | Ending the Daily pipeline also ends the bot-owned phone room. | `EndFrame` disconnects only the bot and does not delete Room1 or remove SIP. | Broken, F6. |
| Idle timeout | Pipecat default: 300 seconds. | Explicitly disabled with `None`; no caller-join deadline or provider maximum replaces it. | Regression, F7. |

## What the broker hears and what is recorded

The intended Room2 boundary is correct in shape: the broker is dialed into Room2, and the Room2 LLM starts only after both `wait_until_answered` returns and broker audio is subscribed. In practice F3 prevents that opening from starting. Independently, F2 means the carrier remains audible to the Room1 STT/LLM while held and after handoff; suppressing TTS does not prevent hidden inference, tool calls, or transcript capture. Thus the implementation does not provide the stated private consultation/human-only boundary.

If participant recognition is fixed, the Room2 prompt briefs from the entire carrier conversation, including transfer reason, load number, offered prices, and internal pricing, and instructs the model to share all context with the broker. The broker consultation is recorded separately and appended to the call transcript with a `[BROKER CONSULTATION]` prefix.

This remains unqualified against a real call. `wait_until_answered` treats voicemail as answered, which the PR explicitly defers, and there is no human confirmation or voicemail classifier. The prompt also has no explicit minimization or grounding rule for sensitive caller statements. Because those limitations are disclosed in the PR description, I treat them as accepted scope risks rather than additional defects, but production enablement should require voicemail handling and a bounded, PII-minimized briefing contract.

## Requirements

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| R1 | Migrate webhook, rooms, Pipecat transport, and outbound dialing from Daily to LiveKit/Telnyx. | Not met | Real inbound LiveKit SIP events are rejected before startup, and normal termination and idle lifecycle are not equivalent (F1, F6, F7). |
| R2 | Preserve the single-prompt negotiation architecture. | Met | Room1 retains one context and existing tool handlers in `voice-agent/bot.py`. |
| R3 | Keep the carrier connected and privately brief the broker before handoff. | Not met | The carrier audio is not gated from the Room1 model/transcript (F2), and the real broker is rejected before briefing because SID and identity are confused (F3). |
| R4 | Distinguish answer from early media and verify participant movement before success. | Met in code, not integration-tested | Answer plus subscribed-audio gates and destination reconciliation are present; declared tests could not run locally. |
| R5 | Clean both rooms across success, failure, disconnect, timeout, and competing callbacks. | Not met | Failed-transfer recovery is silent, carrier departure can resurrect a cancelled attempt and leak late resources, normal-call rooms are omitted, and webhook idempotency is racy (F4, F5, F6, F10). |
| R6 | Record transfer only after broker arrival; preserve transcript and consultation recording references. | Met in code, not integration-tested | `HANDOFF_COMPLETE` follows verified movement; audit data is appended during finalization. |
| R7 | Isolate Slack failure and attribute records by provider. | Met in code | Notification exceptions are isolated; schema and dashboard add provider fields. |
| R8 | Provide merge-ready evidence and operational safety for a real-time calling migration. | Not met | Tests were not runnable in this environment, ingress, media-gate, and Room2 participant fakes do not model the resolved libraries' behavior, and no cutover/rollback exists. |

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
