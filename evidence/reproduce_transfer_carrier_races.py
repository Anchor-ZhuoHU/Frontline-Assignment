import asyncio
import os
import subprocess
import sys
import types
from dataclasses import dataclass
from types import SimpleNamespace

REPO = os.environ.get("FRONTLINE_REPO", "/tmp/frontline-assignment-clone")
HEAD = "f93f7a5f79efdf08c18c583a6a6f7167084b93ae"


def source(path):
    return subprocess.check_output(
        ["git", "show", f"{HEAD}:{path}"], cwd=REPO, text=True
    )


class Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


loguru = types.ModuleType("loguru")
loguru.logger = Logger()
sys.modules["loguru"] = loguru

telephony_module = types.ModuleType("livekit_telephony_service")
telephony_module.LiveKitTelephonyService = object
telephony_module.ParticipantMoveOutcomeUnknown = type(
    "ParticipantMoveOutcomeUnknown", (Exception,), {}
)
sys.modules[telephony_module.__name__] = telephony_module


@dataclass
class PrimaryMediaBinding:
    room_name: str
    room_url: str
    task: object
    context: object
    transport: object


media_module = types.ModuleType("livekit_transfer_media")
media_module.LiveKitTransferMedia = object
media_module.PrimaryMediaBinding = PrimaryMediaBinding
sys.modules[media_module.__name__] = media_module

models_module = types.ModuleType("models")
models_module.TransferMessage = lambda **kwargs: kwargs
sys.modules[models_module.__name__] = models_module

number_module = types.ModuleType("number_strategy")
number_module.RandomSelectionStrategy = type(
    "RandomSelectionStrategy", (), {"select": lambda self, number: number}
)
sys.modules[number_module.__name__] = number_module

room2_module = types.ModuleType("room2_pipeline_service")
room2_module.Room2PipelineService = object
sys.modules[room2_module.__name__] = room2_module

notifier_module = types.ModuleType("transfer_notifier")
notifier_module.NotificationType = SimpleNamespace(SLACK="slack")
notifier_module.TransferNotifier = lambda *_args, **_kwargs: None
sys.modules[notifier_module.__name__] = notifier_module

state_module = types.ModuleType("transfer_state")
sys.modules[state_module.__name__] = state_module
exec(compile(source("voice-agent/transfer_state.py"), "transfer_state.py", "exec"), state_module.__dict__)

orchestrator_module = types.ModuleType("orchestrator_under_test")
exec(
    compile(source("voice-agent/orchestrator.py"), "orchestrator.py", "exec"),
    orchestrator_module.__dict__,
)


class FakeMedia:
    def __init__(self, events, **_kwargs):
        self.events = events

    async def gate_primary_media(self, gated):
        self.events.append(f"media.gate({gated})")

    async def start_hold(self):
        self.events.append("media.start_hold")

    async def restore_primary(self):
        self.events.append("media.restore_primary")

    async def play_primary_announcement(self, _text):
        self.events.append("media.announce")

    async def cleanup(self):
        self.events.append("media.cleanup")

    async def stop_hold(self, *, retain_observer):
        self.events.append(f"media.stop_hold(retain_observer={retain_observer})")

    async def detach_primary_publisher(self):
        self.events.append("media.detach_primary_publisher")

    async def quarantine_ambiguous_handoff(self):
        self.events.append("media.quarantine_ambiguous_handoff")
        await self.stop_hold(retain_observer=True)
        await self.detach_primary_publisher()

    async def end_primary_pipeline(self):
        self.events.append("media.end_primary_pipeline")


class FakeRoom2:
    def __init__(self, events):
        self.events = events

    async def start(self, **_kwargs):
        self.events.append("room2_pipeline.start")

    async def stop(self):
        self.events.append("room2_pipeline.stop")

    async def mark_broker_answered(self):
        self.events.append("room2_pipeline.mark_broker_answered")

    async def wait_for_broker(self, _timeout):
        self.events.append("room2_pipeline.wait_for_broker")


class FakeTelephony:
    def __init__(self, events, create_gate=None, move_gate=None, move_error=None):
        self.events = events
        self.create_gate = create_gate
        self.move_gate = move_gate
        self.move_error = move_error
        self.config = SimpleNamespace(livekit_url="wss://test")

    async def create_room(self, **_kwargs):
        self.events.append("telephony.create_room.enter")
        if self.create_gate:
            self.create_gate[0].set()
            await self.create_gate[1].wait()
        self.events.append("telephony.create_room.return(room2)")
        return SimpleNamespace(name="room2", token="token2")

    def issue_room_token(self, *_args):
        self.events.append("telephony.issue_hold_token")
        return "hold-token"

    async def dial_phone(self, **kwargs):
        self.events.append(f"telephony.dial_phone({kwargs['room_name']})")
        return SimpleNamespace(
            identity=kwargs["participant_identity"],
            participant_id="PA_broker",
            provider_call_id="call-broker",
        )

    async def delete_room(self, room_name):
        self.events.append(f"telephony.delete_room({room_name})")

    async def remove_participant(self, **kwargs):
        self.events.append(
            "telephony.remove_participant"
            f"({kwargs['room_name']},{kwargs['participant_identity']})"
        )

    async def move_participant_verified(self, **kwargs):
        self.events.append("telephony.move.enter")
        if self.move_gate:
            self.move_gate[0].set()
            await self.move_gate[1].wait()
        if self.move_error:
            self.events.append("telephony.move.outcome_unknown")
            raise self.move_error
        self.events.append("telephony.move.success(broker_in_room1)")


class BlockingNotifier:
    def __init__(self, events, entered, release):
        self.events = events
        self.entered = entered
        self.release = release

    async def notify(self, _message):
        self.events.append("notifier.enter")
        self.entered.set()
        await self.release.wait()
        self.events.append("notifier.return")


class ImmediateNotifier:
    def __init__(self, events):
        self.events = events

    async def notify(self, _message):
        self.events.append("notifier.return")


def build(events, telephony, notifier):
    orchestrator = orchestrator_module.TransferOrchestrator(
        telephony=telephony,
        media_factory=lambda **kwargs: FakeMedia(events, **kwargs),
        room2_factory=lambda *_args: FakeRoom2(events),
        notifier=notifier,
    )
    context = SimpleNamespace(room_name="room1", load_context=None)
    aggregator = SimpleNamespace(_context=SimpleNamespace(messages=[]))
    orchestrator.set_room1_references(
        room1_url="wss://test",
        room1_token="token1",
        task=SimpleNamespace(),
        context=context,
        context_aggregator=aggregator,
        transport=SimpleNamespace(),
        room1_name="room1",
    )
    orchestrator.set_transfer_metadata(
        reason="requested", human_phone_number="+15550001111"
    )
    return orchestrator


async def execute(orchestrator):
    await orchestrator.execute_transfer_to_room2(
        http_session=None,
        stt=None,
        tts=None,
        llm=None,
        skip_tts_processor=None,
        transcript=None,
        speech_sync=None,
        audiobuffer=None,
        context_aggregator=None,
    )


async def during_slack():
    events = []
    entered, release = asyncio.Event(), asyncio.Event()
    telephony = FakeTelephony(events)
    orchestrator = build(
        events, telephony, BlockingNotifier(events, entered, release)
    )
    task = asyncio.create_task(execute(orchestrator))
    await entered.wait()
    events.append("carrier.disconnect")
    await orchestrator.on_carrier_left_primary()
    events.append(f"after_disconnect.phase={orchestrator.state.phase.value}")
    release.set()
    await task
    events.append(f"final.phase={orchestrator.state.phase.value}")
    events.append(f"final.room2_name={orchestrator.state.room2_name}")
    return events


async def during_create_room():
    events = []
    entered, release = asyncio.Event(), asyncio.Event()
    telephony = FakeTelephony(events, (entered, release))
    orchestrator = build(events, telephony, ImmediateNotifier(events))
    task = asyncio.create_task(execute(orchestrator))
    await entered.wait()
    events.append("carrier.disconnect")
    await orchestrator.on_carrier_left_primary()
    events.append(f"after_disconnect.phase={orchestrator.state.phase.value}")
    release.set()
    await task
    events.append(f"final.phase={orchestrator.state.phase.value}")
    events.append(f"final.room2_name={orchestrator.state.room2_name}")
    events.append(
        f"final.pipeline_owned={orchestrator._room2_pipeline is not None}"
    )
    return events


async def start_consultation(orchestrator):
    task = asyncio.create_task(execute(orchestrator))
    for _ in range(1000):
        if orchestrator.state.phase is state_module.TransferPhase.CONSULTING:
            return task
        await asyncio.sleep(0)
    raise RuntimeError(f"consultation did not start: {orchestrator.state.phase}")


async def consultation_timeout_during_move():
    events = []
    move_entered, move_release = asyncio.Event(), asyncio.Event()
    telephony = FakeTelephony(events, move_gate=(move_entered, move_release))
    orchestrator = build(events, telephony, ImmediateNotifier(events))
    old_timeout = os.environ.get("LIVEKIT_TRANSFER_CONSULTATION_TIMEOUT_SECONDS")
    os.environ["LIVEKIT_TRANSFER_CONSULTATION_TIMEOUT_SECONDS"] = "0.01"
    try:
        consultation = await start_consultation(orchestrator)
        handoff = asyncio.create_task(
            orchestrator.execute_transfer_human_to_room1(None)
        )
        await move_entered.wait()
        await consultation
        events.append(f"after_timeout.phase={orchestrator.state.phase.value}")
        move_release.set()
        await handoff
        events.append(f"final.phase={orchestrator.state.phase.value}")
        events.append(f"final.room2_name={orchestrator.state.room2_name}")
    finally:
        if old_timeout is None:
            os.environ.pop("LIVEKIT_TRANSFER_CONSULTATION_TIMEOUT_SECONDS", None)
        else:
            os.environ["LIVEKIT_TRANSFER_CONSULTATION_TIMEOUT_SECONDS"] = old_timeout
    return events


async def ambiguous_move_without_arrival():
    events = []
    unknown = telephony_module.ParticipantMoveOutcomeUnknown(
        "participant location unknown"
    )
    telephony = FakeTelephony(events, move_error=unknown)
    orchestrator = build(events, telephony, ImmediateNotifier(events))
    orchestrator.state.carrier_participant_id = "PA_carrier"
    consultation = await start_consultation(orchestrator)
    await orchestrator.execute_transfer_human_to_room1(None)
    await consultation
    events.append(f"after_unknown.phase={orchestrator.state.phase.value}")
    events.append("carrier.disconnect_after_quarantine")
    before = len(events)
    await orchestrator.on_handoff_ended("PA_carrier")
    events.append(f"handoff_ended_side_effects={len(events) - before}")
    events.append(f"final.room1_name={orchestrator.state.room1_name}")
    return events


async def main():
    for name, scenario in (
        ("disconnect_during_slack", during_slack),
        ("disconnect_during_create_room", during_create_room),
        ("consultation_timeout_during_move", consultation_timeout_during_move),
        ("ambiguous_move_without_arrival", ambiguous_move_without_arrival),
    ):
        print(name)
        for index, event in enumerate(await scenario(), 1):
            print(f"  {index:02d}. {event}")


asyncio.run(main())
