"""All ten layers, composed, running ticks end to end.

Until the tick loop existed the project was ten individually-tested components
with nothing joining them. These tests assert the property that arrival buys:
a command leaves the proposer, crosses the one-way channel, meets three gates,
passes through the fail-safe machine, reaches the arbitrator and lands in the
audit log as one complete evidence row.

They also assert the thing that matters more than "it runs" -- that the gates
still *discriminate* once composed. A pipeline where every tick passes is
indistinguishable from a pipeline with no gates at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from astra.config.loader import load_settings
from astra.contracts.sensing import SensorSample
from astra.kernel.enums import FailSafeState, GateId, SensorModality, Verdict
from astra.kernel.identifiers import RunId, TickId
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l2_estimation.measurement import fast_measurement, slow_measurement
from astra.layers.l3_trust.corpus import CalibrationCorpus
from astra.observability.audit import JsonlAuditSink
from astra.runtime.assembly import assemble_pipeline

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from astra.contracts.audit import JsonValue
    from astra.layers.l2_estimation.measurement import Measurement
    from astra.runtime.assembly import AssembledPipeline

TWIN_CHECKPOINT = Path("var/twin/synthetic.pt")
CRUISE_SPEED = 25.0
DRY_FRICTION = 0.85
ICE_FRICTION = 0.12
CORPUS_PATH = Path("var/calibration/synthetic.json")
# Lateral acceleration added per tick when ramping into a turn. Half the
# configured jerk limit of 8 m/s^3 over a 50 ms tick, so a ramped turn is
# comfortably admissible and the physical gate has no reason to fire.
RAMP_PER_TICK = 0.2

pytestmark = pytest.mark.skipif(
    not (TWIN_CHECKPOINT.exists() and CORPUS_PATH.exists()),
    reason=(
        "needs a trained twin and a calibration corpus:\n"
        "  python training/train_twin.py --out var/twin/synthetic.pt\n"
        "  python -m training.generate_calibration --out var/calibration/synthetic.json\n"
        "Without the twin, two gates veto every tick on physically absurd predictions. "
        "Without the corpus, the conformal quantile is infinite and L6 vetoes everything "
        "as CONTEXT_NOT_CALIBRATED. Both are correct behaviour and neither is informative."
    ),
)


class _Extractor:
    """Reads the synthetic payload L1 carried, as a CARLA adapter would."""

    def __init__(self, friction: float) -> None:
        self._friction = friction

    def extract_fast(self, frame: object) -> Measurement | None:
        sample = frame.sample_for(SensorModality.IMU)  # type: ignore[attr-defined]
        if sample is None:
            return None
        payload = sample.payload
        return fast_measurement(
            [
                ("speed", float(payload["v"]), 0.01),
                ("lateral_acceleration", float(payload["a"]), 0.04),
            ]
        )

    def extract_slow(self, frame: object) -> Measurement | None:
        del frame
        return slow_measurement([("road_friction_coefficient", self._friction, 4e-4)])


def _build(
    tmp_path: Path, *, friction: float = DRY_FRICTION
) -> tuple[AssembledPipeline[JsonValue], JsonlAuditSink, ManualClock, Seconds]:
    resolved = load_settings(environment="simulation", include_environment_variables=False)
    settings = resolved.settings
    clock = ManualClock(Instant(0, Timeline.MANUAL))
    run = RunId("run-integration01")
    sink = JsonlAuditSink(run=run, directory=tmp_path, fsync_each_record=False)
    built: AssembledPipeline[JsonValue] = assemble_pipeline(
        run=run,
        config_hash=resolved.hash,
        settings=settings,
        clock=clock,
        extractor=_Extractor(friction),
        audit_sink=sink,
        initial_speed=settings.shield.legal_speed_limit,
        twin_checkpoint=TWIN_CHECKPOINT,
        corpus=CalibrationCorpus.read(CORPUS_PATH),
    )
    return built, sink, clock, Seconds(1.0 / settings.estimation.fast_rate_hz)


def _drive(
    built: AssembledPipeline[JsonValue],
    clock: ManualClock,
    period: Seconds,
    feed: Callable[[int], dict[str, float]],
    ticks: int,
) -> Iterator[object]:
    for index in range(ticks):
        built.sensor_bus.publish(
            SensorSample(
                modality=SensorModality.IMU,
                observed_at=clock.now(),
                quality=Probability(1.0),
                payload=feed(index),  # type: ignore[arg-type]
            )
        )
        outcome = built.pipeline.tick(TickId(index))
        if outcome.record.fast_state is not None:
            built.fallback.observe(outcome.record.fast_state)
        clock.advance(period)
        yield outcome


def _nominal(_index: int) -> dict[str, float]:
    return {"v": CRUISE_SPEED, "a": 0.0}


# --------------------------------------------------------------------------- #
# Stage 1 exit criterion
# --------------------------------------------------------------------------- #


def test_a_command_travels_the_whole_pipeline_and_is_issued(tmp_path: Path) -> None:
    built, sink, clock, period = _build(tmp_path)

    outcomes = list(_drive(built, clock, period, _nominal, ticks=6))
    sink.flush()

    assert all(outcome.verdict is Verdict.PASS for outcome in outcomes)  # type: ignore[attr-defined]
    assert all(outcome.was_issued for outcome in outcomes)  # type: ignore[attr-defined]
    assert all(outcome.failed_stage is None for outcome in outcomes)  # type: ignore[attr-defined]


def test_every_tick_produces_one_complete_evidence_row(tmp_path: Path) -> None:
    built, sink, clock, period = _build(tmp_path)
    ticks = 6

    list(_drive(built, clock, period, _nominal, ticks=ticks))
    sink.flush()

    lines = [
        line
        for path in tmp_path.rglob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == ticks

    record = json.loads(lines[-1])
    # The Stage 1 exit criterion names these two explicitly: a verdict is only
    # traceable if the record says which operating point and which model it
    # rests on.
    assert record["config_hash"]
    assert record["twin_weights_digest"]
    for field in ("fast_state", "trust", "proposal", "prediction", "safety_verdict", "failsafe"):
        assert record[field] is not None, f"{field} missing from the evidence row"
    assert record["issued"] is not None


def test_all_three_gates_appear_in_every_recorded_verdict(tmp_path: Path) -> None:
    built, sink, clock, period = _build(tmp_path)

    outcomes = list(_drive(built, clock, period, _nominal, ticks=4))
    sink.flush()

    for outcome in outcomes:
        verdict = outcome.record.safety_verdict  # type: ignore[attr-defined]
        assert verdict is not None
        assert {gate_verdict.gate for gate_verdict in verdict.gate_verdicts} == {
            GateId.STATISTICAL,
            GateId.PHYSICAL,
            GateId.DETERMINISTIC,
        }


def test_a_nominal_drive_keeps_the_machine_in_nominal(tmp_path: Path) -> None:
    built, sink, clock, period = _build(tmp_path)

    outcomes = list(_drive(built, clock, period, _nominal, ticks=12))
    sink.flush()

    for outcome in outcomes:
        assert outcome.record.failsafe.state is FailSafeState.NOMINAL  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# The gates still discriminate once composed
# --------------------------------------------------------------------------- #


def _vetoing_gates(outcomes: list[object]) -> set[GateId]:
    fired: set[GateId] = set()
    for outcome in outcomes:
        verdict = outcome.record.safety_verdict  # type: ignore[attr-defined]
        if verdict is None:
            continue
        fired.update(verdict.vetoing_gates)
    return fired


def test_a_nominal_drive_fires_no_gate(tmp_path: Path) -> None:
    # The control case. Without it, every veto below could be a pipeline that
    # simply rejects everything.
    built, sink, clock, period = _build(tmp_path)

    outcomes = list(_drive(built, clock, period, _nominal, ticks=12))
    sink.flush()

    assert _vetoing_gates(outcomes) == set()


def test_exceeding_the_legal_speed_fires_only_the_deterministic_gate(
    tmp_path: Path,
) -> None:
    built, sink, clock, period = _build(tmp_path)

    outcomes = list(
        _drive(
            built,
            clock,
            period,
            lambda index: {"v": 45.0 if index > 4 else CRUISE_SPEED, "a": 0.0},
            ticks=12,
        )
    )
    sink.flush()

    assert _vetoing_gates(outcomes) == {GateId.DETERMINISTIC}


def test_the_same_manoeuvre_fires_a_gate_only_once_the_road_is_ice(
    tmp_path: Path,
) -> None:
    # The discrimination result worth having: identical commanded motion, two
    # different road surfaces, different verdicts. This is the shape of the
    # independence argument, though not yet the evidence for it: that needs a
    # trained policy and the Phase 9 scenarios.
    #
    # The turn is *ramped*, not stepped. A step from 0 to 5 m/s^2 in one 50 ms
    # tick is a 100 m/s^3 jerk against a limit of 8 -- the physical gate would
    # veto it on both surfaces and the comparison would say nothing about the
    # road. Real cornering ramps, and so does this.
    def cornering(index: int) -> dict[str, float]:
        onset = max(0, index - 4)
        return {"v": CRUISE_SPEED, "a": min(5.0, onset * RAMP_PER_TICK)}

    dry_built, dry_sink, dry_clock, period = _build(tmp_path / "dry", friction=DRY_FRICTION)
    dry = _vetoing_gates(list(_drive(dry_built, dry_clock, period, cornering, ticks=20)))
    dry_sink.flush()

    ice_built, ice_sink, ice_clock, _ = _build(tmp_path / "ice", friction=ICE_FRICTION)
    ice = _vetoing_gates(list(_drive(ice_built, ice_clock, period, cornering, ticks=20)))
    ice_sink.flush()

    assert dry == set(), "an admissible ramped turn on dry tarmac must fire nothing"
    assert dry < ice, "ice must fire strictly more gates than dry tarmac"
    assert GateId.DETERMINISTIC in ice


# --------------------------------------------------------------------------- #
# Fail-closed behaviour survives composition
# --------------------------------------------------------------------------- #


def test_a_tick_with_no_sensor_reading_still_produces_a_record(tmp_path: Path) -> None:
    # Nothing is published, so the extractor returns no measurement and the
    # filter predicts without correcting. The tick must still complete and be
    # recorded rather than raising into the caller.
    built, sink, clock, period = _build(tmp_path)

    outcome = built.pipeline.tick(TickId(0))
    clock.advance(period)
    sink.flush()

    assert outcome.record is not None
    assert outcome.record.safety_verdict is not None


def test_no_exception_escapes_a_tick_driven_with_absent_sensors(tmp_path: Path) -> None:
    built, sink, clock, period = _build(tmp_path)

    for index in range(8):
        built.pipeline.tick(TickId(index))
        clock.advance(period)
    sink.flush()

    lines = [
        line
        for path in tmp_path.rglob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 8
