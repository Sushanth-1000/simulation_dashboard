"""L1, L2 and the replay spine, wired together.

The Phase 2 exit criteria are properties of the *assembly*, not of any one
module: a recorded run must replay to an identical stream, and the filter must
track ground truth. Both are asserted here against a synthetic vehicle, so they
hold before a simulator is attached rather than after.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import pytest

from astra.config.schema import EstimationSettings
from astra.contracts.sensing import FusedSensorFrame, SensorSample
from astra.kernel.enums import SensorModality, StreamHealth
from astra.kernel.identifiers import RunId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l1_sensing.bus import SharedSensorBus
from astra.layers.l2_estimation.filter import DualRateUKF
from astra.layers.l2_estimation.measurement import (
    Measurement,
    fast_measurement,
    slow_measurement,
)
from astra.replay.harness import ReplayHarness
from astra.replay.recorder import StateRecorder
from astra.replay.tape import IdentityPayloadCodec

if TYPE_CHECKING:
    from pathlib import Path

    from astra.contracts.audit import JsonValue

TICK_PERIOD = Seconds(0.05)
STALENESS_BUDGET = Seconds(0.05)
CONFIG_HASH = "af00c940369eaf79"
STRAIGHT_TICKS = 120
TURNING_TICKS = 180
LATERAL_ACCELERATION = 3.0
CRUISE_SPEED = 20.0


def _settings() -> EstimationSettings:
    return EstimationSettings(
        fast_rate_hz=20.0,
        slow_rate_hz=1.0,
        innovation_gate_gamma=9.0,
        fast_process_noise=(0.02, 0.02, 0.05, 0.005, 0.30),
        slow_process_noise=(1e-5, 1e-6, 1e-5),
    )


class _Vehicle:
    """A kinematic ground truth: cruise straight, then hold a steady turn."""

    def __init__(self) -> None:
        self.position_x = 0.0
        self.position_y = 0.0
        self.speed = CRUISE_SPEED
        self.heading = 0.0
        self.lateral_acceleration = 0.0

    def advance(self, lateral_acceleration: float) -> None:
        yaw_rate = lateral_acceleration / self.speed
        self.position_x += self.speed * math.cos(self.heading) * TICK_PERIOD
        self.position_y += self.speed * math.sin(self.heading) * TICK_PERIOD
        self.heading += yaw_rate * TICK_PERIOD
        self.lateral_acceleration = lateral_acceleration


class _Extractor:
    """Reads the synthetic payloads L1 carried and turns them into measurements.

    Deliberately reads only the payload, never ground truth: this is the seam an
    adapter occupies, and a test extractor that peeked at the simulator would
    prove nothing about the real one.
    """

    def extract_fast(self, frame: FusedSensorFrame[JsonValue]) -> Measurement | None:
        gps = frame.sample_for(SensorModality.GPS)
        imu = frame.sample_for(SensorModality.IMU)
        observations: list[tuple[str, float, float]] = []
        if isinstance(gps, SensorSample) and isinstance(gps.payload, dict):
            observations.append(("position_x", float(gps.payload["x"]), 0.25))  # type: ignore[arg-type]
            observations.append(("position_y", float(gps.payload["y"]), 0.25))  # type: ignore[arg-type]
            observations.append(("speed", float(gps.payload["v"]), 0.01))  # type: ignore[arg-type]
        if isinstance(imu, SensorSample) and isinstance(imu.payload, dict):
            observations.append(
                ("lateral_acceleration", float(imu.payload["a_lat"]), 0.04)  # type: ignore[arg-type]
            )
        if not observations:
            return None
        return fast_measurement(observations)

    def extract_slow(self, frame: FusedSensorFrame[JsonValue]) -> Measurement | None:
        del frame
        return slow_measurement([("road_friction_coefficient", 0.85, 4e-4)])


def _drive(
    tape: Path,
    run: RunId,
    *,
    seed: int = 3,
) -> tuple[list[FusedSensorFrame[JsonValue]], _Vehicle, DualRateUKF[JsonValue]]:
    """Drive the synthetic vehicle through L1 and L2, recording every frame."""
    noise = random.Random(seed)
    clock = ManualClock(Instant(0, Timeline.MANUAL))
    bus: SharedSensorBus[JsonValue] = SharedSensorBus(
        clock=clock, staleness_budget=STALENESS_BUDGET
    )
    estimator: DualRateUKF[JsonValue] = DualRateUKF(
        settings=_settings(),
        extractor=_Extractor(),
        initial_fast_state=[0.0, 0.0, CRUISE_SPEED, 0.0, 0.0],
        initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0, 0.1, 1.0]),
        initial_slow_state=[0.85, 0.0, 1.0],
        initial_slow_covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
    )
    vehicle = _Vehicle()
    frames: list[FusedSensorFrame[JsonValue]] = []

    with StateRecorder(
        run=run,
        timeline=Timeline.MANUAL,
        config_hash=CONFIG_HASH,
        codec=IdentityPayloadCodec(),
        path=tape,
    ) as recorder:
        for tick in range(STRAIGHT_TICKS + TURNING_TICKS):
            vehicle.advance(0.0 if tick < STRAIGHT_TICKS else LATERAL_ACCELERATION)
            now = clock.now()
            bus.publish(
                SensorSample(
                    modality=SensorModality.GPS,
                    observed_at=now,
                    quality=Probability(0.9),
                    payload={
                        "x": vehicle.position_x + noise.gauss(0.0, 0.5),
                        "y": vehicle.position_y + noise.gauss(0.0, 0.5),
                        "v": vehicle.speed + noise.gauss(0.0, 0.1),
                    },
                )
            )
            bus.publish(
                SensorSample(
                    modality=SensorModality.IMU,
                    observed_at=now,
                    quality=Probability(1.0),
                    payload={
                        "a_lat": vehicle.lateral_acceleration + noise.gauss(0.0, 0.2),
                    },
                )
            )
            frame = bus.acquire(TickId(tick))
            frames.append(frame)
            recorder.record(frame)
            estimator.update_fast(frame)
            clock.advance(TICK_PERIOD)

    return frames, vehicle, estimator


# --------------------------------------------------------------------------- #
# Exit criterion: a recorded run replays to a byte-identical stream
# --------------------------------------------------------------------------- #


def test_a_recorded_run_replays_to_a_byte_identical_tape(tmp_path: Path, run: RunId) -> None:
    original = tmp_path / "original.jsonl"
    replayed = tmp_path / "replayed.jsonl"
    _drive(original, run)

    harness: ReplayHarness[JsonValue] = ReplayHarness(path=original, codec=IdentityPayloadCodec())
    with StateRecorder(
        run=harness.run,
        timeline=harness.header.timeline,
        config_hash=harness.header.config_hash,
        codec=IdentityPayloadCodec(),
        path=replayed,
    ) as recorder:
        for frame in harness.frames():
            recorder.record(frame)

    assert replayed.read_bytes() == original.read_bytes()


def test_replay_reproduces_every_frame_the_run_produced(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    frames, _, _ = _drive(tape, run)

    harness: ReplayHarness[JsonValue] = ReplayHarness(path=tape, codec=IdentityPayloadCodec())

    assert list(harness.frames()) == frames


def test_the_replay_clock_tracks_the_frame_it_is_yielding(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    _drive(tape, run)

    harness: ReplayHarness[JsonValue] = ReplayHarness(path=tape, codec=IdentityPayloadCodec())

    for frame in harness.frames():
        assert harness.clock.now() == frame.fused_at


# --------------------------------------------------------------------------- #
# Exit criterion: the filter tracks ground truth
# --------------------------------------------------------------------------- #


def test_the_filter_tracks_the_vehicle_through_a_turn(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    _, vehicle, estimator = _drive(tape, run)
    estimate = estimator.update_fast(
        FusedSensorFrame.build(
            tick=TickId(STRAIGHT_TICKS + TURNING_TICKS),
            fused_at=Instant((STRAIGHT_TICKS + TURNING_TICKS) * 50_000_000, Timeline.MANUAL),
            samples=(),
        )
    )

    position_error = math.hypot(
        estimate.position_x - vehicle.position_x,
        estimate.position_y - vehicle.position_y,
    )
    travelled = math.hypot(vehicle.position_x, vehicle.position_y)

    assert travelled > 100.0, "the synthetic drive should cover real ground"
    assert position_error < 5.0
    assert abs(estimate.speed - vehicle.speed) < 1.0
    assert abs(estimate.heading - vehicle.heading) < 0.2


def test_the_fast_covariance_stays_positive_definite_across_the_drive(
    tmp_path: Path, run: RunId
) -> None:
    # P_f supplies sigma(x) to the ICP gate. A covariance that lost positive
    # definiteness would drive sigma(x) toward zero and unbound the statistical
    # gate, turning a filter fault into a silently permissive safety gate.
    tape = tmp_path / "tape.jsonl"
    frames, _, _ = _drive(tape, run)
    estimator: DualRateUKF[JsonValue] = DualRateUKF(
        settings=_settings(),
        extractor=_Extractor(),
        initial_fast_state=[0.0, 0.0, CRUISE_SPEED, 0.0, 0.0],
        initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0, 0.1, 1.0]),
        initial_slow_state=[0.85, 0.0, 1.0],
        initial_slow_covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
    )

    for frame in frames:
        estimate = estimator.update_fast(frame)
        assert estimate.covariance.is_positive_definite()
        assert estimate.variance_of("lateral_acceleration") > 0.0


def test_the_innovation_monitor_stays_quiet_on_a_nominal_drive(tmp_path: Path, run: RunId) -> None:
    tape = tmp_path / "tape.jsonl"
    _, _, estimator = _drive(tape, run)

    history = estimator.innovation_history

    assert len(history) > 0
    assert all(math.isfinite(distance) and distance >= 0.0 for distance in history)
    innovation = estimator.latest_innovation()
    assert innovation is not None
    assert not innovation.fault_flagged


# --------------------------------------------------------------------------- #
# L1 and L2 agree about what a degraded frame means
# --------------------------------------------------------------------------- #


def test_a_stale_stream_is_degraded_and_the_filter_still_produces_an_estimate(
    tmp_path: Path, run: RunId
) -> None:
    # A sensor going quiet must not stop the pipeline: the filter predicts
    # without correcting and the covariance widens, which is what makes the
    # downstream gate more permissive exactly when the state is less certain.
    del tmp_path, run
    clock = ManualClock(Instant(0, Timeline.MANUAL))
    bus: SharedSensorBus[JsonValue] = SharedSensorBus(
        clock=clock, staleness_budget=STALENESS_BUDGET
    )
    estimator: DualRateUKF[JsonValue] = DualRateUKF(
        settings=_settings(),
        extractor=_Extractor(),
        initial_fast_state=[0.0, 0.0, CRUISE_SPEED, 0.0, 0.0],
        initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0, 0.1, 1.0]),
        initial_slow_state=[0.85, 0.0, 1.0],
        initial_slow_covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
    )

    bus.publish(
        SensorSample(
            modality=SensorModality.GPS,
            observed_at=clock.now(),
            quality=Probability(0.9),
            payload={"x": 0.0, "y": 0.0, "v": CRUISE_SPEED},
        )
    )
    clock.advance(Seconds(0.2))
    frame = bus.acquire(TickId(1))

    health = bus.health(frame)
    estimate = estimator.update_fast(frame)

    assert health[SensorModality.GPS] is StreamHealth.DEGRADED
    assert health[SensorModality.IMU] is StreamHealth.ABSENT
    assert bus.is_degraded(frame)
    assert estimate.covariance.is_positive_definite()


def test_a_frame_with_no_measurement_widens_the_covariance(tmp_path: Path, run: RunId) -> None:
    del tmp_path, run
    estimator: DualRateUKF[JsonValue] = DualRateUKF(
        settings=_settings(),
        extractor=_Extractor(),
        initial_fast_state=[0.0, 0.0, CRUISE_SPEED, 0.0, 0.0],
        initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0, 0.1, 1.0]),
        initial_slow_state=[0.85, 0.0, 1.0],
        initial_slow_covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
    )
    empty: FusedSensorFrame[JsonValue] = FusedSensorFrame.build(
        tick=TickId(0), fused_at=Instant(0, Timeline.MANUAL), samples=()
    )

    first = estimator.update_fast(empty)
    second = estimator.update_fast(
        FusedSensorFrame.build(
            tick=TickId(1), fused_at=Instant(50_000_000, Timeline.MANUAL), samples=()
        )
    )

    assert sum(second.covariance.diagonal) > sum(first.covariance.diagonal)
    assert estimator.latest_innovation() is None


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_the_drive_converges_for_several_noise_realisations(
    tmp_path: Path, run: RunId, seed: int
) -> None:
    # One seed passing could be luck. The filter has to track regardless of which
    # noise realisation it sees.
    tape = tmp_path / f"tape-{seed}.jsonl"
    _, vehicle, estimator = _drive(tape, run, seed=seed)
    estimate = estimator.update_fast(
        FusedSensorFrame.build(
            tick=TickId(STRAIGHT_TICKS + TURNING_TICKS),
            fused_at=Instant((STRAIGHT_TICKS + TURNING_TICKS) * 50_000_000, Timeline.MANUAL),
            samples=(),
        )
    )

    position_error = math.hypot(
        estimate.position_x - vehicle.position_x,
        estimate.position_y - vehicle.position_y,
    )

    assert position_error < 5.0
