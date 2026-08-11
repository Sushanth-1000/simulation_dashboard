"""Does the dashboard invent anything?

The rule this file enforces
----------------------------
P4.1 states it exactly: *"every number on screen must trace to a live
``DecisionRecord``. Nothing scripted, nothing interpolated."*

That is the kind of promise that decays. A smoothed line here, a default there,
a plausible value substituted when a stage did not run -- and the demonstration
stops being evidence and becomes a rendering of evidence, which is a different
thing and looks identical.

So :class:`~demo.dashboard.Frame` is a pure projection, and the tests below
check it **field by field against its source**. Not "the frame is populated":
each field equals the specific attribute of the specific record it claims to
come from.

The two fields that are not from the record
---------------------------------------------
``truth_y`` and ``truth_speed`` come from the simulator. They are on screen
because OD-9 is invisible without them -- the whole finding is that the estimate
and the truth diverge while every gate stays green -- and they are separated
into their own group, labelled on the page, and asserted here to be exactly the
two.

:func:`test_every_field_is_declared_as_record_or_simulator` is the one that
matters most: it fails if anyone adds a field without deciding which it is,
which is precisely how the distinction would erode.
"""

from __future__ import annotations

import dataclasses

import pytest

from astra.contracts.actuation import (
    ActuationChannel,
    ActuationSpace,
    CommandOrigin,
    ControlCommand,
    IssuedCommand,
)
from astra.contracts.assurance import FailSafeSnapshot, GateVerdict, SafetyVerdict, TrustAssessment
from astra.contracts.audit import DecisionRecord
from astra.contracts.estimation import FastStateEstimate
from astra.kernel.enums import (
    ContextClass,
    FailSafeState,
    GateId,
    LayerId,
    SensorModality,
    StreamHealth,
    Verdict,
)
from astra.kernel.identifiers import ComponentId, RunId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, Timeline
from astra.kernel.units import MetresPerSecond, Probability
from demo.dashboard import FAULT_WINDOW_TICKS, Frame, build_injector
from training.closed_loop import TickSample

RUN = RunId("run-dashboardtest01")
NOW = Instant(0, Timeline.MANUAL)
SPACE = ActuationSpace(
    (
        ActuationChannel(name="throttle", lower=0.0, upper=1.0, unit="1"),
        ActuationChannel(name="brake", lower=0.0, upper=1.0, unit="1"),
        ActuationChannel(name="steer", lower=-0.5, upper=0.5, unit="rad"),
    )
)


def record(tick: int = 7) -> DecisionRecord:
    """Return a fully populated decision record."""
    identifier = TickId(tick)
    return DecisionRecord(
        run=RUN,
        tick=identifier,
        config_hash="sha256:dashboard",
        frame_health=(
            (SensorModality.IMU, StreamHealth.DEGRADED),
            (SensorModality.CAMERA, StreamHealth.HEALTHY),
        ),
        fast_state=FastStateEstimate(
            tick=identifier,
            valid_at=NOW,
            mean=(1.0, -0.42, 13.0, 0.01, 0.2),
            covariance=SymmetricMatrix.from_diagonal((1.0, 1.0, 1.0, 1.0, 1.0)),
        ),
        fast_innovation=1.875,
        trust=TrustAssessment(
            tick=identifier,
            trust_index=Probability(0.83),
            context_class=ContextClass.URBAN_CLEAR,
            class_conditional_quantile=1.234,
            coverage_target=Probability(0.95),
            calibration_sample_count=1000,
            is_calibrated=True,
        ),
        safety_verdict=SafetyVerdict(
            tick=identifier,
            gate_verdicts=(
                GateVerdict(
                    tick=identifier,
                    gate=GateId.STATISTICAL,
                    verdict=Verdict.PASS,
                    reason_code="WITHIN_BAND",
                ),
                GateVerdict(
                    tick=identifier,
                    gate=GateId.PHYSICAL,
                    verdict=Verdict.VETO,
                    reason_code="LATERAL_JERK_EXCEEDS_LIMIT",
                ),
            ),
        ),
        failsafe=FailSafeSnapshot(
            tick=identifier,
            state=FailSafeState.DEGRADED,
            ood_counter=4,
            speed_cap=MetresPerSecond(11.5),
            lane_change_permitted=False,
            human_intervention_requested=False,
        ),
        issued=IssuedCommand(
            tick=identifier,
            issued_at=NOW,
            command=ControlCommand(space=SPACE, values=(0.3, 0.0, 0.05)),
            origin=CommandOrigin.RATE_LIMITED,
            issuer=ComponentId(LayerId.L9_RCM),
        ),
        ablation="shield",
    )


def sample(**overrides: object) -> TickSample:
    """Return a tick sample wrapping a populated record."""
    defaults: dict[str, object] = {
        "tick": 7,
        "record": record(),
        "was_issued": True,
        "lane_deviation_m": 2.5,
        "speed_mps": 12.75,
        "lateral_acceleration_mps2": 0.2,
        "pipeline_duration_ns": 1_000_000,
        "fault_active": True,
    }
    defaults.update(overrides)
    return TickSample(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Every field, against the thing it claims to come from
# --------------------------------------------------------------------------- #


def test_every_field_is_declared_as_record_or_simulator() -> None:
    # The test that stops the distinction eroding. Adding a field without
    # deciding which group it belongs to fails here, at the moment it is added.
    declared = set(Frame.from_record()) | set(Frame.from_simulator())
    actual = {field.name for field in dataclasses.fields(Frame)}

    assert declared == actual
    assert not set(Frame.from_record()) & set(Frame.from_simulator())


def test_exactly_two_values_come_from_the_simulator() -> None:
    # Plus the injector's own ground-truth label. If this ever grows, the page's
    # footer is wrong and the separation is no longer what it says.
    assert set(Frame.from_simulator()) == {"truth_y", "truth_speed", "fault_active"}


def test_the_trust_fields_are_the_records_own() -> None:
    source = record()
    frame = Frame.from_sample(sample(record=source))

    assert source.trust is not None
    assert frame.trust_index == float(source.trust.trust_index)
    assert frame.context == source.trust.context_class.value
    assert frame.quantile == float(source.trust.class_conditional_quantile)


def test_the_gate_panel_is_the_records_own_verdicts_in_order() -> None:
    source = record()
    frame = Frame.from_sample(sample(record=source))

    assert source.safety_verdict is not None
    assert frame.gates == tuple(
        (gate.gate.value, gate.verdict.value, gate.reason_code)
        for gate in source.safety_verdict.gate_verdicts
    )
    assert frame.blocking is source.safety_verdict.is_blocking


def test_the_failsafe_fields_are_the_records_own() -> None:
    source = record()
    frame = Frame.from_sample(sample(record=source))

    assert source.failsafe is not None
    assert frame.failsafe_state == source.failsafe.state.value
    assert frame.ood_counter == source.failsafe.ood_counter
    assert source.failsafe.speed_cap is not None
    assert frame.speed_cap == float(source.failsafe.speed_cap)


def test_the_issued_command_is_the_records_own() -> None:
    source = record()
    frame = Frame.from_sample(sample(record=source))

    assert source.issued is not None
    assert frame.origin == source.issued.origin.value
    assert frame.issued == tuple(float(v) for v in source.issued.command.values)


def test_the_estimate_and_innovation_are_the_records_own() -> None:
    source = record()
    frame = Frame.from_sample(sample(record=source))

    assert source.fast_state is not None
    assert frame.estimate_y == float(source.fast_state.position_y)
    assert frame.innovation == source.fast_innovation
    assert frame.ablation == source.ablation


def test_the_ground_truth_fields_are_the_simulators_own() -> None:
    observed = sample(lane_deviation_m=4.199, speed_mps=11.9, fault_active=True)

    frame = Frame.from_sample(observed)

    assert frame.truth_y == observed.lane_deviation_m
    assert frame.truth_speed == observed.speed_mps
    assert frame.fault_active is True


# --------------------------------------------------------------------------- #
# A stage that did not run must render as absent, never as plausible
# --------------------------------------------------------------------------- #


def test_a_tick_with_no_trust_assessment_reports_nothing_rather_than_a_default() -> None:
    # A Trust Index of 1.0 substituted for "L3 did not run" would read on screen
    # as perfect confidence. Absence must stay absence.
    bare = DecisionRecord(run=RUN, tick=TickId(3), config_hash="sha256:bare")

    frame = Frame.from_sample(sample(record=bare))

    assert frame.trust_index is None
    assert frame.context is None
    assert frame.quantile is None


def test_a_tick_with_no_verdict_shows_no_gates_rather_than_passing_ones() -> None:
    bare = DecisionRecord(run=RUN, tick=TickId(3), config_hash="sha256:bare")

    frame = Frame.from_sample(sample(record=bare))

    assert frame.gates == ()
    assert frame.blocking is False


def test_a_tick_that_issued_nothing_says_so() -> None:
    bare = DecisionRecord(run=RUN, tick=TickId(3), config_hash="sha256:bare")

    frame = Frame.from_sample(sample(record=bare, was_issued=False))

    assert frame.origin is None
    assert frame.issued is None


def test_a_governed_run_reports_its_ablation_as_none_rather_than_empty() -> None:
    bare = DecisionRecord(run=RUN, tick=TickId(3), config_hash="sha256:bare")

    assert Frame.from_sample(sample(record=bare)).ablation == "NONE"


def test_a_nominal_failsafe_with_no_cap_renders_absent_rather_than_zero() -> None:
    # The bug this test was written for. A NOMINAL machine imposes no cap, and
    # `speed_cap` is None -- rendering that as 0.0 would put "commanded stop",
    # the most alarming reading this panel has, onto every healthy tick.
    #
    # It was found by running the dashboard rather than by the tests above,
    # because every fixture here set a cap. Which is the usual lesson: a
    # fixture that only builds the populated case tests only the populated case.
    nominal = dataclasses.replace(
        record(),
        failsafe=FailSafeSnapshot(
            tick=TickId(7),
            state=FailSafeState.NOMINAL,
            ood_counter=0,
            speed_cap=None,
            lane_change_permitted=True,
            human_intervention_requested=False,
        ),
    )

    frame = Frame.from_sample(sample(record=nominal))

    assert frame.speed_cap is None
    assert frame.failsafe_state == "NOMINAL"


def test_the_frame_is_json_serialisable() -> None:
    import json  # noqa: PLC0415

    payload = json.dumps(dataclasses.asdict(Frame.from_sample(sample())))

    assert json.loads(payload)["tick"] == 7


# --------------------------------------------------------------------------- #
# The button the audience presses
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kind", ["dropout", "position_bias", "position_drift", "speed_stuck", "lateral_noise"]
)
def test_every_offered_fault_builds_a_valid_specification(kind: str) -> None:
    spec = build_injector(kind, tick=500, seed=0)

    assert spec.first_tick == 500
    assert spec.last_tick == 500 + FAULT_WINDOW_TICKS
    assert spec.tick_count == FAULT_WINDOW_TICKS + 1


def test_a_fault_the_demonstration_does_not_offer_is_refused() -> None:
    # Rather than silently arming nothing, which would give an audience a button
    # that appears to work.
    with pytest.raises(ValueError, match="not a fault this demonstration offers"):
        build_injector("explode", tick=0, seed=0)


def test_arming_a_fault_mid_run_affects_no_earlier_tick() -> None:
    from training.closed_loop import CHANNEL_SIGMAS  # noqa: PLC0415
    from training.faults import FaultInjector  # noqa: PLC0415

    injector = FaultInjector((), seed=1, sigmas=CHANNEL_SIGMAS)
    clean = {"y": 0.1, "v": 13.0, "a": 0.0}

    before = injector.corrupt(clean, tick=100)
    injector.arm(build_injector("position_bias", tick=101, seed=0))
    after = injector.corrupt(clean, tick=101)

    assert before == clean
    assert after is not None
    assert after["y"] != clean["y"]
