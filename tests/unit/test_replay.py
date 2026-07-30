"""Unit tests for the replay tape, the recorder and the replay harness.

The headline property is byte-identity: recording a run, replaying it and
re-recording every replayed frame must produce the same bytes. That is a Phase 2
exit criterion, because a diff between two runs is only meaningful if two tapes
of the same inputs are the same file.

Everything here is hermetic. The only clock is a
:class:`~astra.kernel.time.ManualClock`, every tape is written under ``tmp_path``
and nothing sleeps: a replay test that depended on wall-clock time would be
testing the opposite of what replay promises.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from astra.contracts.audit import JsonValue
from astra.contracts.sensing import FusedSensorFrame, SensorSample
from astra.kernel.enums import SensorModality
from astra.kernel.errors import AdapterError, ContractViolationError, SchemaVersionError
from astra.kernel.identifiers import RunId, TickId
from astra.kernel.time import Clock, Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l1_sensing.bus import SharedSensorBus
from astra.replay.harness import ReplayClock, ReplayHarness
from astra.replay.recorder import StateRecorder
from astra.replay.tape import (
    TAPE_SCHEMA_VERSION,
    IdentityPayloadCodec,
    PayloadCodec,
    TapeHeader,
    decode_frame,
    encode_frame,
    render_line,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

CONFIG_HASH = "sha256:9f86d081884c7d65"
STALENESS_BUDGET = Seconds(0.05)
TICK_PERIOD = Seconds(0.05)
TICKS = 24

# Fixed per modality so that a recorded quality is a constant of the scenario
# rather than of the order the test happened to run in.
QUALITY: dict[SensorModality, float] = {
    SensorModality.CAMERA: 1.0,
    SensorModality.LIDAR: 0.875,
    SensorModality.IMU: 0.5,
    SensorModality.GPS: 0.25,
    SensorModality.RADAR: 0.0,
}

# Any of these on a tape would differ on every recording and destroy the one
# property the artefact exists to provide.
WALL_CLOCK_KEYS = ("created_at", "recorded_at", "wall_clock", "timestamp", "written_at")

FIXED_WALL_CLOCK = datetime(1970, 1, 1, tzinfo=UTC)


class _RecordingAbortedError(Exception):
    pass


# --------------------------------------------------------------------------- #
# A synthetic run with uneven sensor rates
# --------------------------------------------------------------------------- #
# Camera every tick, LiDAR every second, IMU every third, GPS every fifth and
# radar never. First publication follows SensorModality declaration order, so
# the bus's own sample order and the tape's canonical order coincide and the
# replayed frames compare equal to the originals.


def _scheduled(step: int) -> tuple[SensorModality, ...]:
    scheduled = [SensorModality.CAMERA]
    if step % 2 == 1:
        scheduled.append(SensorModality.LIDAR)
    if step % 3 == 2:
        scheduled.append(SensorModality.IMU)
    if step % 5 == 4:
        scheduled.append(SensorModality.GPS)
    return tuple(scheduled)


def _payload(modality: SensorModality, step: int) -> JsonValue:
    return {"modality": modality.value, "step": step, "reading": [step * 0.5, step, None]}


def _sample(modality: SensorModality, observed_at: Instant, step: int) -> SensorSample[JsonValue]:
    return SensorSample(
        modality=modality,
        observed_at=observed_at,
        quality=Probability(QUALITY[modality]),
        payload=_payload(modality, step),
    )


def _recorder(path: Path, run: RunId) -> StateRecorder[JsonValue]:
    return StateRecorder[JsonValue](
        run=run,
        timeline=Timeline.MANUAL,
        config_hash=CONFIG_HASH,
        codec=IdentityPayloadCodec(),
        path=path,
    )


def _harness(path: Path) -> ReplayHarness[JsonValue]:
    return ReplayHarness[JsonValue](path=path, codec=IdentityPayloadCodec())


def _record_run(path: Path, run: RunId, ticks: int = TICKS) -> list[FusedSensorFrame[JsonValue]]:
    clock = ManualClock(Instant(0, Timeline.MANUAL))
    bus: SharedSensorBus[JsonValue] = SharedSensorBus(
        clock=clock, staleness_budget=STALENESS_BUDGET
    )
    frames: list[FusedSensorFrame[JsonValue]] = []
    with _recorder(path, run) as recorder:
        for step in range(ticks):
            clock.advance(TICK_PERIOD)
            for modality in _scheduled(step):
                bus.publish(_sample(modality, clock.now(), step))
            frame = bus.acquire(TickId(step))
            recorder.record(frame)
            frames.append(frame)
    return frames


def _replay_onto(source: Path, target: Path) -> list[FusedSensorFrame[JsonValue]]:
    harness = _harness(source)
    frames: list[FusedSensorFrame[JsonValue]] = []
    with StateRecorder[JsonValue](
        run=harness.run,
        timeline=harness.header.timeline,
        config_hash=harness.header.config_hash,
        codec=IdentityPayloadCodec(),
        path=target,
    ) as recorder:
        for frame in harness.frames():
            recorder.record(frame)
            frames.append(frame)
    return frames


def _write_lines(path: Path, lines: Sequence[str]) -> Path:
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def _header_line(run: RunId, timeline: Timeline = Timeline.MANUAL) -> str:
    return render_line(TapeHeader(run=run, timeline=timeline, config_hash=CONFIG_HASH).to_payload())


def _frame_line(tick: int, fused_at_ns: int) -> str:
    payload: dict[str, JsonValue] = {
        "record_type": "frame",
        "tick": tick,
        "fused_at": fused_at_ns,
        "samples": [
            {
                "modality": SensorModality.CAMERA.value,
                "observed_at": fused_at_ns,
                "quality": 1.0,
                "payload": tick,
            }
        ],
    }
    return render_line(payload)


def _tape_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


# --------------------------------------------------------------------------- #
# THE headline property: byte-identical replay (Phase 2 exit criterion)
# --------------------------------------------------------------------------- #


def test_replaying_a_recorded_run_and_re_recording_it_produces_byte_identical_tapes(
    tmp_path: Path, run: RunId
) -> None:
    original_tape = tmp_path / "original.jsonl"
    replayed_tape = tmp_path / "replayed.jsonl"
    _record_run(original_tape, run)

    _replay_onto(original_tape, replayed_tape)

    assert replayed_tape.read_bytes() == original_tape.read_bytes()


def test_replayed_frames_compare_equal_to_the_frames_that_were_recorded(
    tmp_path: Path, run: RunId
) -> None:
    original_tape = tmp_path / "original.jsonl"
    replayed_tape = tmp_path / "replayed.jsonl"
    originals = _record_run(original_tape, run)

    replayed = _replay_onto(original_tape, replayed_tape)

    assert len(replayed) == TICKS
    assert replayed == originals


def test_the_synthetic_run_really_does_have_uneven_rates_and_absent_modalities(
    tmp_path: Path, run: RunId
) -> None:
    # Guards the byte-identity test above from degenerating into a test of a
    # uniform stream, where canonical ordering would be trivially satisfied.
    frames = _record_run(tmp_path / "original.jsonl", run)

    present_counts = {
        modality: sum(1 for frame in frames if frame.sample_for(modality) is not None)
        for modality in SensorModality
    }
    assert present_counts[SensorModality.RADAR] == 0
    assert frames[0].absent_modalities == frozenset(SensorModality) - {SensorModality.CAMERA}
    assert len({present_counts[modality] for modality in SensorModality}) > 1
    assert any(frame.absent_modalities for frame in frames)


def test_a_run_recorded_twice_from_the_same_inputs_produces_the_same_bytes(
    tmp_path: Path, run: RunId
) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"

    _record_run(first, run)
    _record_run(second, run)

    assert first.read_bytes() == second.read_bytes()


def test_replaying_the_same_tape_through_two_harnesses_yields_the_same_bytes(
    tmp_path: Path, run: RunId
) -> None:
    original_tape = tmp_path / "original.jsonl"
    _record_run(original_tape, run)

    first = tmp_path / "replay-a.jsonl"
    second = tmp_path / "replay-b.jsonl"
    _replay_onto(original_tape, first)
    _replay_onto(original_tape, second)

    assert first.read_bytes() == second.read_bytes()


def test_the_replayed_tape_adopts_the_identity_of_the_run_it_reproduces(
    tmp_path: Path, run: RunId
) -> None:
    original_tape = tmp_path / "original.jsonl"
    _record_run(original_tape, run)

    harness = _harness(original_tape)

    assert harness.run == run
    assert harness.header.config_hash == CONFIG_HASH
    assert harness.header.timeline is Timeline.MANUAL


# --------------------------------------------------------------------------- #
# Tape format
# --------------------------------------------------------------------------- #


def test_the_first_line_of_a_tape_is_the_header_record(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run, ticks=3)

    header = json.loads(_tape_lines(tape)[0])

    assert header["record_type"] == "header"
    assert header["run"] == run.value
    assert header["timeline"] == Timeline.MANUAL.value
    assert header["config_hash"] == CONFIG_HASH
    assert header["schema_version"] == TAPE_SCHEMA_VERSION


def test_every_line_of_a_tape_is_valid_json(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run, ticks=5)

    assert [json.loads(line)["record_type"] for line in _tape_lines(tape)] == [
        "header",
        *["frame"] * 5,
    ]


def test_the_header_carries_no_wall_clock_field(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run, ticks=2)

    header = json.loads(_tape_lines(tape)[0])

    for key in WALL_CLOCK_KEYS:
        assert key not in header
    assert set(header) == {"record_type", "schema_version", "run", "timeline", "config_hash"}


@pytest.mark.parametrize("key", WALL_CLOCK_KEYS)
def test_no_line_of_a_tape_mentions_a_wall_clock_key(tmp_path: Path, run: RunId, key: str) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run, ticks=6)

    assert key not in tape.read_text(encoding="utf-8")


def test_an_empty_configuration_hash_is_refused(run: RunId) -> None:
    with pytest.raises(ContractViolationError):
        TapeHeader(run=run, timeline=Timeline.MANUAL, config_hash="")


def test_a_header_from_another_schema_version_is_refused(run: RunId) -> None:
    payload = TapeHeader(run=run, timeline=Timeline.MANUAL, config_hash=CONFIG_HASH).to_payload()
    payload["schema_version"] = TAPE_SCHEMA_VERSION + 1

    with pytest.raises(SchemaVersionError) as raised:
        TapeHeader.from_payload(payload)

    assert raised.value.context["declared"] == TAPE_SCHEMA_VERSION + 1


@pytest.mark.parametrize("field", ["run", "timeline", "config_hash", "schema_version"])
def test_a_header_missing_a_field_names_the_field(run: RunId, field: str) -> None:
    payload = TapeHeader(run=run, timeline=Timeline.MANUAL, config_hash=CONFIG_HASH).to_payload()
    del payload[field]

    with pytest.raises(ContractViolationError) as raised:
        TapeHeader.from_payload(payload)

    assert raised.value.context["field"] == field
    assert field in str(raised.value)


def test_a_header_with_a_malformed_timeline_is_refused(run: RunId) -> None:
    payload = TapeHeader(run=run, timeline=Timeline.MANUAL, config_hash=CONFIG_HASH).to_payload()
    payload["timeline"] = "NOT_A_TIMELINE"

    with pytest.raises(ContractViolationError):
        TapeHeader.from_payload(payload)


def test_a_header_round_trips_through_its_payload(run: RunId) -> None:
    header = TapeHeader(run=run, timeline=Timeline.SIMULATED, config_hash=CONFIG_HASH)

    assert TapeHeader.from_payload(header.to_payload()) == header


# --------------------------------------------------------------------------- #
# Canonical sample ordering -- what makes byte-identity possible
# --------------------------------------------------------------------------- #


def _frame_with_samples_in(
    modalities: Sequence[SensorModality],
) -> FusedSensorFrame[JsonValue]:
    return FusedSensorFrame.build(
        tick=TickId(7),
        fused_at=Instant(700_000_000, Timeline.MANUAL),
        samples=[
            SensorSample(
                modality=modality,
                observed_at=Instant(600_000_000, Timeline.MANUAL),
                quality=Probability(QUALITY[modality]),
                payload=modality.value,
            )
            for modality in modalities
        ],
    )


def test_samples_are_encoded_in_modality_declaration_order_not_frame_order() -> None:
    reversed_frame = _frame_with_samples_in(list(reversed(list(SensorModality))))

    encoded = encode_frame(reversed_frame, IdentityPayloadCodec())
    entries = cast("list[dict[str, JsonValue]]", encoded["samples"])

    assert [entry["modality"] for entry in entries] == [
        modality.value for modality in SensorModality
    ]


def test_the_rendered_line_lists_modalities_in_declaration_order() -> None:
    line = render_line(
        encode_frame(
            _frame_with_samples_in(list(reversed(list(SensorModality)))),
            IdentityPayloadCodec(),
        )
    )

    positions = [line.index(f'"modality":"{modality.value}"') for modality in SensorModality]

    assert positions == sorted(positions)


def test_two_frames_differing_only_in_sample_order_render_the_same_line() -> None:
    forward = _frame_with_samples_in(list(SensorModality))
    backward = _frame_with_samples_in(list(reversed(list(SensorModality))))

    assert forward.samples != backward.samples
    assert render_line(encode_frame(forward, IdentityPayloadCodec())) == render_line(
        encode_frame(backward, IdentityPayloadCodec())
    )


def test_a_partially_populated_frame_keeps_declaration_order() -> None:
    frame = _frame_with_samples_in([SensorModality.GPS, SensorModality.CAMERA])

    encoded = encode_frame(frame, IdentityPayloadCodec())
    entries = cast("list[dict[str, JsonValue]]", encoded["samples"])

    assert [entry["modality"] for entry in entries] == [
        SensorModality.CAMERA.value,
        SensorModality.GPS.value,
    ]


def test_encode_and_decode_preserve_modality_instant_quality_and_payload() -> None:
    original: FusedSensorFrame[JsonValue] = FusedSensorFrame.build(
        tick=TickId(11),
        fused_at=Instant(1_234_567_891, Timeline.MANUAL),
        samples=[
            SensorSample(
                modality=SensorModality.LIDAR,
                observed_at=Instant(1_234_000_000, Timeline.MANUAL),
                quality=Probability(0.875),
                payload={"points": [1, 2.5, None], "sweep": "front"},
            )
        ],
    )
    codec = IdentityPayloadCodec()

    restored = decode_frame(encode_frame(original, codec), codec, Timeline.MANUAL)

    assert restored == original
    sample = restored.sample_for(SensorModality.LIDAR)
    assert sample is not None
    assert sample.modality is SensorModality.LIDAR
    assert sample.observed_at == Instant(1_234_000_000, Timeline.MANUAL)
    assert sample.quality == 0.875
    assert sample.payload == {"points": [1, 2.5, None], "sweep": "front"}


def test_decoding_applies_the_header_timeline_to_every_instant() -> None:
    codec = IdentityPayloadCodec()
    encoded = encode_frame(_frame_with_samples_in([SensorModality.IMU]), codec)

    restored = decode_frame(encoded, codec, Timeline.SIMULATED)

    assert restored.fused_at.timeline is Timeline.SIMULATED
    assert restored.samples[0].observed_at.timeline is Timeline.SIMULATED


def test_an_empty_frame_round_trips() -> None:
    codec = IdentityPayloadCodec()
    empty: FusedSensorFrame[JsonValue] = FusedSensorFrame.build(
        tick=TickId(0), fused_at=Instant(0, Timeline.MANUAL), samples=[]
    )

    assert decode_frame(encode_frame(empty, codec), codec, Timeline.MANUAL) == empty


# --------------------------------------------------------------------------- #
# ReplayClock
# --------------------------------------------------------------------------- #


def test_the_replay_clock_runs_on_the_timeline_declared_by_the_header(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run, ticks=3)

    harness = _harness(tape)

    assert harness.clock.timeline is harness.header.timeline
    assert harness.clock.timeline is Timeline.MANUAL


def test_the_replay_clock_reports_the_instant_of_the_frame_being_yielded(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run)
    harness = _harness(tape)

    seen = 0
    for frame in harness.frames():
        assert harness.clock.now() == frame.fused_at
        assert harness.clock.now().timeline is Timeline.MANUAL
        seen += 1

    assert seen == TICKS


def test_the_replay_clock_starts_at_the_timeline_origin_before_any_frame(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run, ticks=3)

    assert _harness(tape).clock.now() == Instant(0, Timeline.MANUAL)


def test_the_replay_clock_reports_a_fixed_timezone_aware_wall_clock(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run, ticks=3)
    harness = _harness(tape)

    first = harness.clock.wall_clock()
    for _ in harness.frames():
        assert harness.clock.wall_clock() == first

    assert first == FIXED_WALL_CLOCK
    assert first.tzinfo is not None
    assert first.utcoffset() == FIXED_WALL_CLOCK.utcoffset()


def test_two_harnesses_over_the_same_tape_report_the_same_wall_clock(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run, ticks=3)

    assert _harness(tape).clock.wall_clock() == _harness(tape).clock.wall_clock()


def test_the_replay_clock_satisfies_the_clock_protocol(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run, ticks=3)

    harness = _harness(tape)

    assert isinstance(harness.clock, Clock)
    assert isinstance(ReplayClock(Timeline.SIMULATED), Clock)


def test_the_replay_clock_is_usable_through_the_clock_protocol() -> None:
    clock: Clock = ReplayClock(Timeline.MANUAL)

    assert clock.timeline is Timeline.MANUAL
    assert clock.now() == Instant(0, Timeline.MANUAL)
    assert clock.wall_clock() == FIXED_WALL_CLOCK


def test_a_tape_whose_instants_go_backwards_is_refused_during_replay(
    tmp_path: Path, run: RunId
) -> None:
    tape = _write_lines(
        tmp_path / "backwards.jsonl",
        [_header_line(run), _frame_line(0, 2_000_000_000), _frame_line(1, 1_000_000_000)],
    )

    with pytest.raises(ContractViolationError) as raised:
        list(_harness(tape).frames())

    assert raised.value.context["from_ns"] == 2_000_000_000
    assert raised.value.context["to_ns"] == 1_000_000_000


def test_a_tape_that_repeats_an_instant_is_accepted_because_it_never_moves_backwards(
    tmp_path: Path, run: RunId
) -> None:
    tape = _write_lines(
        tmp_path / "flat.jsonl",
        [_header_line(run), _frame_line(0, 1_000_000_000), _frame_line(1, 1_000_000_000)],
    )

    assert [frame.tick.value for frame in _harness(tape).frames()] == [0, 1]


def test_a_frame_instant_on_another_timeline_is_refused() -> None:
    clock = ReplayClock(Timeline.MANUAL)

    with pytest.raises(ContractViolationError) as raised:
        clock._advance_to(Instant(1_000, Timeline.SIMULATED))

    assert Timeline.SIMULATED.value in str(raised.value)
    assert Timeline.MANUAL.value in str(raised.value)


# --------------------------------------------------------------------------- #
# Segment replay -- freezing a tick range
# --------------------------------------------------------------------------- #


def _ticks_of(
    tape: Path, *, first_tick: TickId | None = None, last_tick: TickId | None = None
) -> list[int]:
    return [
        frame.tick.value
        for frame in _harness(tape).frames(first_tick=first_tick, last_tick=last_tick)
    ]


def test_a_segment_yields_exactly_the_inclusive_tick_range(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run)

    assert _ticks_of(tape, first_tick=TickId(5), last_tick=TickId(10)) == [5, 6, 7, 8, 9, 10]


def test_a_segment_bounded_only_below_runs_to_the_end_of_the_tape(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run)

    assert _ticks_of(tape, first_tick=TickId(20)) == [20, 21, 22, 23]


def test_a_segment_bounded_only_above_starts_at_the_beginning_of_the_tape(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run)

    assert _ticks_of(tape, last_tick=TickId(3)) == [0, 1, 2, 3]


def test_an_unbounded_segment_yields_the_whole_tape(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run)

    assert _ticks_of(tape) == list(range(TICKS))


def test_a_single_tick_segment_yields_one_frame(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run)

    assert _ticks_of(tape, first_tick=TickId(9), last_tick=TickId(9)) == [9]


@pytest.mark.parametrize(
    ("first_tick", "last_tick"),
    [
        (TickId(TICKS), None),
        (TickId(TICKS + 50), TickId(TICKS + 60)),
        (TickId(10), TickId(9)),
    ],
)
def test_a_range_beyond_the_tape_yields_nothing(
    tmp_path: Path, run: RunId, first_tick: TickId, last_tick: TickId | None
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run)

    assert _ticks_of(tape, first_tick=first_tick, last_tick=last_tick) == []


def test_replaying_the_same_segment_twice_yields_identical_frames(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run)
    bounds = {"first_tick": TickId(4), "last_tick": TickId(12)}

    first = list(_harness(tape).frames(**bounds))
    second = list(_harness(tape).frames(**bounds))

    assert first == second
    assert [frame.tick.value for frame in first] == list(range(4, 13))


def test_replaying_the_same_segment_twice_re_records_to_identical_bytes(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    originals = _record_run(tape, run)

    outputs: list[bytes] = []
    for name in ("segment-a.jsonl", "segment-b.jsonl"):
        target = tmp_path / name
        with _recorder(target, run) as recorder:
            for frame in _harness(tape).frames(first_tick=TickId(4), last_tick=TickId(12)):
                recorder.record(frame)
        outputs.append(target.read_bytes())

    assert outputs[0] == outputs[1]
    assert len(originals) == TICKS


def test_a_segment_yields_the_same_frames_the_full_replay_yields_for_those_ticks(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    originals = _record_run(tape, run)

    segment = list(_harness(tape).frames(first_tick=TickId(6), last_tick=TickId(11)))

    assert segment == originals[6:12]


def test_one_harness_can_replay_the_same_segment_repeatedly(tmp_path: Path, run: RunId) -> None:
    # Investigating an oscillation means re-running the same ticks against
    # successive fixes, so a harness that could only be traversed once would be
    # useless for the workflow it exists to serve.
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run)
    harness: ReplayHarness[JsonValue] = ReplayHarness(path=tape, codec=IdentityPayloadCodec())

    first = list(harness.frames(first_tick=TickId(5), last_tick=TickId(9)))
    second = list(harness.frames(first_tick=TickId(5), last_tick=TickId(9)))
    third = list(harness.frames())

    assert first == second
    assert [frame.tick.value for frame in first] == [5, 6, 7, 8, 9]
    assert len(third) == TICKS


def test_replaying_twice_leaves_the_clock_on_the_last_frame_of_the_second_pass(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run)
    harness: ReplayHarness[JsonValue] = ReplayHarness(path=tape, codec=IdentityPayloadCodec())

    last_of_first = list(harness.frames())[-1]
    last_of_second = list(harness.frames())[-1]

    assert harness.clock.now() == last_of_second.fused_at
    assert last_of_first.fused_at == last_of_second.fused_at


# --------------------------------------------------------------------------- #
# Codecs -- the domain-independence claim (NFR5)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload",
    [
        {"a": 1, "b": [2, 3], "c": {"d": None}},
        [1, "two", 3.5, False, None],
        42,
        -1.25,
        "a string",
        None,
        True,
        False,
        {},
        [],
    ],
)
def test_the_identity_codec_returns_json_values_unchanged(payload: JsonValue) -> None:
    codec = IdentityPayloadCodec()

    assert codec.encode(payload) == payload
    assert codec.decode(codec.encode(payload)) == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"a": 1, "b": [2, 3], "c": {"d": None}},
        [1, "two", 3.5, False, None],
        42,
        -1.25,
        "a string",
        None,
        True,
        False,
    ],
)
def test_a_json_payload_survives_a_full_record_and_replay_round_trip(
    tmp_path: Path, run: RunId, payload: JsonValue
) -> None:
    tape = tmp_path / "tape.jsonl"
    frame = FusedSensorFrame.build(
        tick=TickId(1),
        fused_at=Instant(1_000, Timeline.MANUAL),
        samples=[
            SensorSample(
                modality=SensorModality.CAMERA,
                observed_at=Instant(900, Timeline.MANUAL),
                quality=Probability(1.0),
                payload=payload,
            )
        ],
    )
    with _recorder(tape, run) as recorder:
        recorder.record(frame)

    replayed = list(_harness(tape).frames())

    assert replayed == [frame]
    sample = replayed[0].sample_for(SensorModality.CAMERA)
    assert sample is not None
    assert sample.payload == payload


@dataclass(frozen=True, slots=True)
class LidarSweep:
    """A payload type the tape knows nothing about, standing in for an adapter's."""

    label: str
    returns: tuple[float, ...]


class LidarSweepCodec:
    """The codec an adapter owning :class:`LidarSweep` would supply."""

    __slots__ = ()

    def encode(self, payload: LidarSweep) -> JsonValue:
        return [payload.label, list(payload.returns)]

    def decode(self, raw: JsonValue) -> LidarSweep:
        entries = cast("list[JsonValue]", raw)
        return LidarSweep(
            label=cast("str", entries[0]),
            returns=tuple(cast("list[float]", entries[1])),
        )


def _sweep_frame(tick: int, sweep: LidarSweep) -> FusedSensorFrame[LidarSweep]:
    return FusedSensorFrame.build(
        tick=TickId(tick),
        fused_at=Instant(tick * 1_000, Timeline.MANUAL),
        samples=[
            SensorSample(
                modality=SensorModality.LIDAR,
                observed_at=Instant(tick * 1_000 - 100, Timeline.MANUAL),
                quality=Probability(0.5),
                payload=sweep,
            )
        ],
    )


def test_a_custom_codec_carries_a_non_json_payload_through_record_and_replay(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "sweeps.jsonl"
    originals = [
        _sweep_frame(1, LidarSweep(label="front", returns=(1.0, 2.5, 3.25))),
        _sweep_frame(2, LidarSweep(label="rear", returns=())),
    ]
    with StateRecorder[LidarSweep](
        run=run,
        timeline=Timeline.MANUAL,
        config_hash=CONFIG_HASH,
        codec=LidarSweepCodec(),
        path=tape,
    ) as recorder:
        for frame in originals:
            recorder.record(frame)

    replayed = list(ReplayHarness[LidarSweep](path=tape, codec=LidarSweepCodec()).frames())

    assert replayed == originals
    sample = replayed[0].sample_for(SensorModality.LIDAR)
    assert sample is not None
    assert sample.payload == LidarSweep(label="front", returns=(1.0, 2.5, 3.25))


def test_a_custom_codec_replays_byte_identically(tmp_path: Path, run: RunId) -> None:
    original_tape = tmp_path / "sweeps.jsonl"
    replayed_tape = tmp_path / "sweeps-replayed.jsonl"
    with StateRecorder[LidarSweep](
        run=run,
        timeline=Timeline.MANUAL,
        config_hash=CONFIG_HASH,
        codec=LidarSweepCodec(),
        path=original_tape,
    ) as recorder:
        for tick in range(1, 21):
            recorder.record(_sweep_frame(tick, LidarSweep(label=f"s{tick}", returns=(tick / 4,))))

    harness = ReplayHarness[LidarSweep](path=original_tape, codec=LidarSweepCodec())
    with StateRecorder[LidarSweep](
        run=harness.run,
        timeline=harness.header.timeline,
        config_hash=harness.header.config_hash,
        codec=LidarSweepCodec(),
        path=replayed_tape,
    ) as recorder:
        for frame in harness.frames():
            recorder.record(frame)

    assert replayed_tape.read_bytes() == original_tape.read_bytes()


def test_the_custom_codec_never_reaches_the_tape_as_an_object(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "sweeps.jsonl"
    with StateRecorder[LidarSweep](
        run=run,
        timeline=Timeline.MANUAL,
        config_hash=CONFIG_HASH,
        codec=LidarSweepCodec(),
        path=tape,
    ) as recorder:
        recorder.record(_sweep_frame(1, LidarSweep(label="front", returns=(1.0,))))

    entries = json.loads(_tape_lines(tape)[1])["samples"]

    assert entries[0]["payload"] == ["front", [1.0]]


@pytest.mark.parametrize("codec", [IdentityPayloadCodec(), LidarSweepCodec()])
def test_both_codecs_satisfy_the_payload_codec_protocol(codec: object) -> None:
    assert isinstance(codec, PayloadCodec)


def test_an_object_without_encode_and_decode_is_not_a_payload_codec() -> None:
    assert not isinstance(object(), PayloadCodec)


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #


def test_opening_a_tape_that_does_not_exist_raises_an_adapter_error(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere" / "missing.jsonl"

    with pytest.raises(AdapterError) as raised:
        _harness(missing)

    assert raised.value.context["path"] == str(missing)


def test_opening_an_empty_tape_raises_a_contract_violation(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")

    with pytest.raises(ContractViolationError) as raised:
        _harness(empty)

    assert raised.value.context["path"] == str(empty)


def test_opening_a_tape_whose_first_line_is_blank_raises_a_contract_violation(
    tmp_path: Path,
) -> None:
    blank = tmp_path / "blank.jsonl"
    blank.write_text("   \n{}\n", encoding="utf-8")

    with pytest.raises(ContractViolationError):
        _harness(blank)


def test_opening_a_tape_whose_first_line_is_not_json_raises_a_contract_violation(
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken.jsonl"
    broken.write_text("this is not json\n", encoding="utf-8")

    with pytest.raises(ContractViolationError) as raised:
        _harness(broken)

    assert raised.value.context["line"] == 1


def test_opening_a_tape_whose_first_line_is_not_an_object_raises_a_contract_violation(
    tmp_path: Path,
) -> None:
    array_header = tmp_path / "array.jsonl"
    array_header.write_text("[1,2]\n", encoding="utf-8")

    with pytest.raises(ContractViolationError) as raised:
        _harness(array_header)

    assert "not a JSON object" in str(raised.value)


def test_replaying_a_tape_that_vanished_after_its_header_was_read_raises_an_adapter_error(
    tmp_path: Path, run: RunId
) -> None:
    tape = tmp_path / "tape.jsonl"
    _record_run(tape, run, ticks=3)
    harness = _harness(tape)
    tape.unlink()

    with pytest.raises(AdapterError) as raised:
        list(harness.frames())

    assert raised.value.context["path"] == str(tape)


def test_a_frame_line_that_is_not_json_raises_a_contract_violation(
    tmp_path: Path, run: RunId
) -> None:
    tape = _write_lines(
        tmp_path / "torn.jsonl", [_header_line(run), _frame_line(0, 1_000), "{not json"]
    )

    with pytest.raises(ContractViolationError) as raised:
        list(_harness(tape).frames())

    assert raised.value.context["line"] == 3


def test_a_frame_missing_the_tick_field_names_the_field(tmp_path: Path, run: RunId) -> None:
    payload = json.loads(_frame_line(0, 1_000))
    del payload["tick"]
    tape = _write_lines(tmp_path / "untitled.jsonl", [_header_line(run), render_line(payload)])

    with pytest.raises(ContractViolationError) as raised:
        list(_harness(tape).frames())

    assert raised.value.context["field"] == "tick"
    assert "tick" in str(raised.value)


def test_a_frame_missing_the_samples_field_names_the_field(tmp_path: Path, run: RunId) -> None:
    payload = json.loads(_frame_line(0, 1_000))
    del payload["samples"]
    tape = _write_lines(tmp_path / "nosamples.jsonl", [_header_line(run), render_line(payload)])

    with pytest.raises(ContractViolationError) as raised:
        list(_harness(tape).frames())

    assert raised.value.context["field"] == "samples"


def test_a_frame_whose_sample_list_is_not_a_list_is_refused(tmp_path: Path, run: RunId) -> None:
    payload = json.loads(_frame_line(0, 1_000))
    payload["samples"] = {"CAMERA": 1}
    tape = _write_lines(tmp_path / "badsamples.jsonl", [_header_line(run), render_line(payload)])

    with pytest.raises(ContractViolationError):
        list(_harness(tape).frames())


def test_a_frame_with_an_unknown_modality_is_refused(tmp_path: Path, run: RunId) -> None:
    payload = json.loads(_frame_line(0, 1_000))
    payload["samples"][0]["modality"] = "SONAR"
    tape = _write_lines(tmp_path / "sonar.jsonl", [_header_line(run), render_line(payload)])

    with pytest.raises(ContractViolationError):
        list(_harness(tape).frames())


def test_recording_into_a_location_that_cannot_be_created_raises_an_adapter_error(
    tmp_path: Path, run: RunId
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("this is a file, not a directory", encoding="utf-8")

    with pytest.raises(AdapterError) as raised:
        _recorder(blocker / "tape.jsonl", run)

    assert raised.value.context["path"] == str(blocker / "tape.jsonl")


def test_recording_after_close_raises_an_adapter_error(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    recorder = _recorder(tape, run)
    frame = _frame_with_samples_in([SensorModality.CAMERA])
    recorder.close()

    with pytest.raises(AdapterError) as raised:
        recorder.record(frame)

    assert raised.value.context["path"] == str(tape)


def test_closing_a_recorder_twice_is_harmless(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    recorder = _recorder(tape, run)
    recorder.record(_frame_with_samples_in([SensorModality.CAMERA]))

    recorder.close()
    recorder.close()

    assert len(_tape_lines(tape)) == 2
    assert recorder.frames_recorded == 1


def test_the_recorder_closes_its_tape_on_the_exception_path(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    frame = _frame_with_samples_in([SensorModality.CAMERA])
    opened: list[StateRecorder[JsonValue]] = []

    def abort() -> None:
        with _recorder(tape, run) as recorder:
            opened.append(recorder)
            recorder.record(frame)
            raise _RecordingAbortedError

    with pytest.raises(_RecordingAbortedError):
        abort()

    # A truncated tape is still replayable up to its last complete line.
    assert len(_tape_lines(tape)) == 2
    assert [f.tick.value for f in _harness(tape).frames()] == [7]
    with pytest.raises(AdapterError):
        opened[0].record(frame)


def test_the_recorder_counts_the_frames_it_wrote(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"

    with _recorder(tape, run) as recorder:
        assert recorder.frames_recorded == 0
        assert recorder.path == tape
        assert recorder.header.run == run
        for tick in range(3):
            recorder.record(
                FusedSensorFrame.build(
                    tick=TickId(tick),
                    fused_at=Instant(tick * 1_000, Timeline.MANUAL),
                    samples=[],
                )
            )

    assert recorder.frames_recorded == 3


# --------------------------------------------------------------------------- #
# Forward compatibility of the reader
# --------------------------------------------------------------------------- #


def test_blank_lines_in_a_tape_are_skipped(tmp_path: Path, run: RunId) -> None:
    tape = _write_lines(
        tmp_path / "gappy.jsonl",
        [_header_line(run), _frame_line(0, 1_000), "", "   ", _frame_line(1, 2_000), ""],
    )

    assert [frame.tick.value for frame in _harness(tape).frames()] == [0, 1]


def test_records_of_an_unknown_type_are_skipped(tmp_path: Path, run: RunId) -> None:
    marker: dict[str, JsonValue] = {"record_type": "marker", "note": "a future record type"}
    tape = _write_lines(
        tmp_path / "future.jsonl",
        [_header_line(run), _frame_line(0, 1_000), render_line(marker), _frame_line(1, 2_000)],
    )

    assert [frame.tick.value for frame in _harness(tape).frames()] == [0, 1]


def test_a_record_without_a_record_type_is_skipped(tmp_path: Path, run: RunId) -> None:
    tape = _write_lines(
        tmp_path / "untyped.jsonl",
        [_header_line(run), render_line({"note": "no record_type"}), _frame_line(0, 1_000)],
    )

    assert [frame.tick.value for frame in _harness(tape).frames()] == [0]


def test_a_tape_with_a_header_and_no_frames_replays_as_nothing(tmp_path: Path, run: RunId) -> None:
    tape = _write_lines(tmp_path / "headeronly.jsonl", [_header_line(run)])

    assert list(_harness(tape).frames()) == []
