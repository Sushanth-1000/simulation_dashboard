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
from astra.contracts.actuation import CommandOrigin
from astra.contracts.sensing import SensorSample
from astra.kernel.enums import FailSafeState, GateId, SensorModality, Verdict
from astra.kernel.identifiers import RunId, TickId
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l2_estimation.measurement import fast_measurement, slow_measurement
from astra.layers.l3_trust.corpus import CalibrationCorpus
from astra.observability.audit import JsonlAuditSink
from astra.runtime.assembly import BRAKE_INDEX, THROTTLE_INDEX, assemble_pipeline

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
# Read rather than written: these are durations expressed in ticks, and the last
# time a test hardcoded one it went on asserting a threshold the config no
# longer had.
THETA_HALT = load_settings(
    environment="simulation", include_environment_variables=False
).settings.failsafe.ood_threshold_halt

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
    tmp_path: Path, *, friction: float = DRY_FRICTION, shadow_fb2: bool = False
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
        shadow_fb2=shadow_fb2,
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
        # Every modality, every tick, which is what `training/closed_loop.py`
        # does and what a vehicle does. Until 11 August this rig published the
        # IMU alone and the other four read ABSENT on every frame -- harmless
        # while nothing consulted stream health, and a vehicle with four dead
        # sensors once L8 started to (ADR-0024). Publishing one modality was
        # modelling a fault the rig did not intend to inject.
        for modality in SensorModality:
            built.sensor_bus.publish(
                SensorSample(
                    modality=modality,
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
        assert outcome.record.failsafe.integrity_counter == 0  # type: ignore[attr-defined]


def test_a_vehicle_publishing_one_modality_does_not_stay_nominal(tmp_path: Path) -> None:
    """A frame missing four of five modalities is a fault, and now reads as one.

    This is the assertion the rig above quietly made until 11 August: it
    published the IMU alone, four modalities read ``ABSENT`` on every frame, and
    the machine held NOMINAL because nothing in it looked. The behaviour is kept
    here rather than deleted, because a reader of ADR-0024 will reasonably ask
    what happens on a platform that simply has fewer sensors -- and the answer,
    today, is that it degrades.

    **That is a real deployment constraint and it is recorded as one.** A
    deployment whose modality set differs from :class:`SensorModality` needs a
    declared *required* set rather than the whole enumeration; the alternative
    -- escalating only on a modality that has published at least once -- was
    rejected because it silently tolerates a sensor that is dead at boot, which
    is the worst failure of the three to tolerate.
    """
    built, sink, clock, period = _build(tmp_path)

    failsafe = None
    for index in range(8):
        built.sensor_bus.publish(
            SensorSample(
                modality=SensorModality.IMU,
                observed_at=clock.now(),
                quality=Probability(1.0),
                payload=_nominal(index),  # type: ignore[arg-type]
            )
        )
        failsafe = built.pipeline.tick(TickId(index)).record.failsafe
        clock.advance(period)
    sink.flush()

    assert failsafe is not None
    assert failsafe.state is not FailSafeState.NOMINAL
    assert failsafe.integrity_counter > 0


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
# The fail-safe posture reaches an actuator
# --------------------------------------------------------------------------- #
#
# Finding F2 of the 6 August soak review: every layer below was correct and the
# composition was not. L8 computed a speed cap, recorded it in the evidence and
# reported it to L9; L9 wrote SPEED_CAPPED into the origin. No one ever changed
# a number in the command vector. A run could sit in HALT -- a commanded stop --
# holding 17.2 m/s, and the audit log would agree that it was capped.
#
# The unit tests around the arbiter and the projector pin the two halves. These
# pin the wiring, which is where the defect actually lived, and they are the
# only tests in the suite that watch a *posture* become a *pedal*.


def _speeding(index: int) -> dict[str, float]:
    # 45 m/s against a 33.3 m/s limit: the deterministic gate blocks every tick
    # and nothing else has to be provoked. Sustained refusal is what walks the
    # machine down, and refusal is all this needs to be.
    del index
    return {"v": 45.0, "a": 0.0}


def test_a_sustained_refusal_walks_the_posture_down_to_halt(tmp_path: Path) -> None:
    # The premise of the two tests below. If the drive never reached HALT they
    # would pass vacuously, asserting things about an empty list.
    built, sink, clock, period = _build(tmp_path)

    outcomes = list(_drive(built, clock, period, _speeding, ticks=THETA_HALT + 4))
    sink.flush()

    states = [outcome.record.failsafe.state for outcome in outcomes]  # type: ignore[attr-defined]

    assert states[0] is FailSafeState.NOMINAL
    assert states[-1] is FailSafeState.HALT


def test_the_command_issued_in_halt_actually_brakes(tmp_path: Path) -> None:
    # THE regression test for F2. HALT's cap is zero and the vehicle is doing
    # 45 m/s, so the issued vector must command a stop -- not merely be labelled
    # as though it had been.
    built, sink, clock, period = _build(tmp_path)

    outcomes = list(_drive(built, clock, period, _speeding, ticks=THETA_HALT + 4))
    sink.flush()

    halted = [
        outcome.record.issued  # type: ignore[attr-defined]
        for outcome in outcomes
        if outcome.record.failsafe.state is FailSafeState.HALT  # type: ignore[attr-defined]
    ]

    assert halted, "the drive never reached HALT; see the test above"
    for issued in halted:
        assert issued is not None
        assert issued.origin is CommandOrigin.SPEED_CAPPED
        assert issued.command.values[THROTTLE_INDEX] == pytest.approx(0.0)
        assert issued.command.values[BRAKE_INDEX] == pytest.approx(1.0)


def test_a_nominal_drive_issues_nothing_labelled_speed_capped(tmp_path: Path) -> None:
    # The control. A cap that binds when there is no cap would be a brake that
    # comes on for no reason, which is its own hazard -- and it would make the
    # test above pass for the wrong reason.
    built, sink, clock, period = _build(tmp_path)

    outcomes = list(_drive(built, clock, period, _nominal, ticks=12))
    sink.flush()

    for outcome in outcomes:
        issued = outcome.record.issued  # type: ignore[attr-defined]
        assert issued is not None
        assert issued.origin is not CommandOrigin.SPEED_CAPPED


# --------------------------------------------------------------------------- #
# FB2 in shadow has no authority
# --------------------------------------------------------------------------- #
#
# FB2 has never run. Rather than choose its step size and observe afterwards --
# which is how `ewc_lambda` came to sit at a value that did nothing -- it runs
# against a twin nothing reads, so a long drive can say what adaptation would
# have done before it is allowed to do it.
#
# That argument is worth exactly as much as the isolation being real, which is
# what these pin.


def test_the_shadow_changes_no_command_and_no_verdict(tmp_path: Path) -> None:
    # THE test. Same seed, same sensors, same everything: turning the shadow on
    # must produce a bit-identical drive. If it does not, the shadow is not a
    # shadow and every number it reports is contaminated by its own presence.
    plain, plain_sink, plain_clock, period = _build(tmp_path / "plain")
    with_shadow, shadow_sink, shadow_clock, _ = _build(tmp_path / "shadow", shadow_fb2=True)

    plain_outcomes = list(_drive(plain, plain_clock, period, _nominal, ticks=24))
    shadow_outcomes = list(_drive(with_shadow, shadow_clock, period, _nominal, ticks=24))
    plain_sink.flush()
    shadow_sink.flush()

    for left, right in zip(plain_outcomes, shadow_outcomes, strict=True):
        assert left.verdict is right.verdict  # type: ignore[attr-defined]
        assert left.record.issued is not None  # type: ignore[attr-defined]
        assert right.record.issued is not None  # type: ignore[attr-defined]
        assert left.record.issued.command.values == pytest.approx(  # type: ignore[attr-defined]
            right.record.issued.command.values  # type: ignore[attr-defined]
        )


def test_the_live_twin_never_moves_while_the_shadow_runs(tmp_path: Path) -> None:
    # The twin the gates consult is the one the run started with. FB2 being
    # switched on in shadow must not become FB2 being switched on.
    built, sink, clock, period = _build(tmp_path, shadow_fb2=True)

    outcomes = list(_drive(built, clock, period, _nominal, ticks=24))
    sink.flush()

    digests = {outcome.record.twin_weights_digest for outcome in outcomes}  # type: ignore[attr-defined]

    assert len(digests) == 1, "the live twin moved; only the shadow may adapt"


def test_no_shadow_runs_unless_one_is_asked_for(tmp_path: Path) -> None:
    # Off by default, and observably so. A shadow that appeared without being
    # requested would put a second twin on every run's cold path.
    built, sink, clock, period = _build(tmp_path)

    outcomes = list(_drive(built, clock, period, _nominal, ticks=4))
    sink.flush()

    assert all(outcome.shadow is None for outcome in outcomes)  # type: ignore[attr-defined]


def test_the_shadow_reports_a_divergence_and_a_digest(tmp_path: Path) -> None:
    # The control for the tests above, which would all pass on a shadow that was
    # never constructed.
    built, sink, clock, period = _build(tmp_path, shadow_fb2=True)

    outcomes = list(_drive(built, clock, period, _nominal, ticks=8))
    sink.flush()

    for outcome in outcomes:
        assert outcome.shadow is not None  # type: ignore[attr-defined]
        assert outcome.shadow.digest  # type: ignore[attr-defined]
        assert outcome.shadow.divergence >= 0.0  # type: ignore[attr-defined]


def test_the_shadow_starts_agreeing_with_the_live_twin(tmp_path: Path) -> None:
    # Both load the same checkpoint, so before FB2's first consolidation the two
    # predictions must be identical. A non-zero divergence on tick zero would
    # mean the shadow started somewhere else, and every later reading would be
    # measuring that difference rather than adaptation.
    built, sink, clock, period = _build(tmp_path, shadow_fb2=True)

    first = next(iter(_drive(built, clock, period, _nominal, ticks=1)))
    sink.flush()

    assert first.shadow is not None  # type: ignore[attr-defined]
    assert first.shadow.divergence == pytest.approx(0.0)  # type: ignore[attr-defined]


def test_the_shadows_live_score_is_the_one_the_gate_actually_recorded(tmp_path: Path) -> None:
    # The comparison FB2 is judged on is live score against shadow score. If the
    # "live" half were computed by a copy of the gate's arithmetic rather than by
    # the gate's arithmetic, the whole experiment would be measuring the copy.
    # This is what makes the two halves comparable.
    built, sink, clock, period = _build(tmp_path, shadow_fb2=True)

    outcomes = list(_drive(built, clock, period, _nominal, ticks=8))
    sink.flush()

    for outcome in outcomes:
        verdict = outcome.record.safety_verdict  # type: ignore[attr-defined]
        assert verdict is not None
        recorded = next(
            value
            for gate_verdict in verdict.gate_verdicts
            if gate_verdict.gate is GateId.STATISTICAL
            for name, value in gate_verdict.evidence
            if name == "non_conformity_score"
        )
        assert outcome.shadow is not None  # type: ignore[attr-defined]
        assert outcome.shadow.live_score == pytest.approx(recorded)  # type: ignore[attr-defined]


def test_the_shadow_and_live_scores_agree_before_the_first_adaptation(tmp_path: Path) -> None:
    # Both twins start from the same checkpoint, so the two scores must be
    # identical on the first tick. Any gap there would be a difference in setup
    # masquerading as a difference made by FB2.
    built, sink, clock, period = _build(tmp_path, shadow_fb2=True)

    first = next(iter(_drive(built, clock, period, _nominal, ticks=1)))
    sink.flush()

    assert first.shadow is not None  # type: ignore[attr-defined]
    assert first.shadow.shadow_score == pytest.approx(  # type: ignore[attr-defined]
        first.shadow.live_score  # type: ignore[attr-defined]
    )


def test_fb3s_shadow_quantile_starts_equal_to_the_live_one(tmp_path: Path) -> None:
    # Both calibrations are seeded from the same corpus, so before FB3 has
    # observed anything they must agree exactly. A gap on the first tick would
    # mean the two started from different distributions, and every later
    # difference would be measuring the seeding rather than the loop.
    built, sink, clock, period = _build(tmp_path, shadow_fb2=True)

    first = next(iter(_drive(built, clock, period, _nominal, ticks=1)))
    sink.flush()

    assert first.shadow is not None  # type: ignore[attr-defined]
    assert first.shadow.shadow_quantile == pytest.approx(  # type: ignore[attr-defined]
        first.shadow.quantile  # type: ignore[attr-defined]
    )


def test_fb3s_shadow_quantile_diverges_from_the_live_one(tmp_path: Path) -> None:
    # The control. Every claim about FB3 rests on the shadow calibration
    # actually requantilising and on the two coming apart.
    #
    # Not "the live quantile is static": it is not, and that is correct. It is
    # `quantile(context, effective_epsilon())`, and the epsilon tightens when the
    # covariate-shift detector fires, so the live threshold moves even though the
    # *distribution* under it never does. Asserting staticness here would have
    # been asserting a bug.
    built, sink, clock, period = _build(tmp_path, shadow_fb2=True)

    outcomes = list(_drive(built, clock, period, _nominal, ticks=40))
    sink.flush()
    shadows = [o.shadow for o in outcomes]  # type: ignore[attr-defined]

    assert any(s.shadow_quantile != s.quantile for s in shadows), (
        "FB3's quantile never came apart from the live one; either the shadow "
        "calibration is not observing, or it is not being read"
    )


def test_the_shadow_is_not_written_into_the_evidence_log(tmp_path: Path) -> None:
    # The audit log is a certification artefact and says what the system did. A
    # counterfactual from a loop that is switched off is a different kind of
    # claim, and filing the two together would leave a reader years from now no
    # way to tell them apart.
    built, sink, clock, period = _build(tmp_path, shadow_fb2=True)

    list(_drive(built, clock, period, _nominal, ticks=4))
    sink.flush()

    written = "".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.jsonl"))

    assert "shadow" not in written


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
