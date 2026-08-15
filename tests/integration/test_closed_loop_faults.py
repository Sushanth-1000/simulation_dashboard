"""An injected fault driven through the assembled pipeline, end to end.

What this file is for
----------------------
``tests/unit/test_fault_injection.py`` shows the injector corrupts a dictionary.
That is necessary and it is not the claim. The claim is that a fault injected at
the sensor boundary **arrives** -- that it reaches the estimator, that the
pipeline's behaviour changes because of it, and that the ground truth recorded
alongside it describes what actually happened rather than what was requested.

An injector verified only against its own return value is the same defect as the
fail-safe speed cap that was recorded on every capped tick and reached no
actuator (OD-2). Both would pass every unit test written about them. The thing
that caught the speed cap was a test that drove the *assembled* pipeline into
HALT and asserted the brake, and this file is the same move.

The two tests that carry the weight
------------------------------------
:func:`test_a_clean_run_and_an_injector_that_never_opens_are_the_same_run`
    The isolation property, and the one that makes a comparison possible at all.
    Two arms of a fault study must differ by the fault and by nothing else. If
    the injector perturbed the sensor-noise stream merely by existing, every
    reading after tick zero would differ between the arms and no difference in
    outcome could be attributed to the fault. This asserts equality of the whole
    trace, not a tolerance.

:func:`test_a_position_bias_arrives_at_the_estimator`
    The mutation test the flake harness's lesson demands: it fails on an
    injector that has silently become a no-op, because it measures the
    estimator's error against the plant's *truth* rather than anything the
    injector reports about itself. A no-op injector leaves that error where the
    clean run leaves it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from astra.kernel.enums import SensorModality, StreamHealth
from astra.layers.l4_proposer.learned import LearnedPolicy
from astra.layers.l4_proposer.proposer import Policy
from training.closed_loop import (
    CHANNEL_SIGMAS,
    CORPUS,
    TWIN,
    ClosedLoopResult,
    TickSample,
    drive_closed_loop,
)
from training.faults import FaultChannel, FaultInjector, FaultSpec, bias, dropout

IMU = SensorModality.IMU

POLICY = Path("var/policy/synthetic.pt")
TICKS = 400
SEED = 20260809

FAULT_FIRST = 200
"""Late enough that the run has left the startup transient before anything breaks.

The plant resets up to 1 m off the lane centre and ADR-0017's rate limiter walks
the correction in over about twenty ticks. A fault opening inside that window
would be measured against a system that was already recovering, and the two
would be impossible to separate.
"""

BIAS_METRES = 1.0
"""Two-thirds of a 1.75 m lane -- unmistakable, and survivable.

Large enough that the estimator's error cannot be confused with the 0.1 m
measurement sigma; small enough that the vehicle does not leave the road while
the test is looking at it.
"""

pytestmark = pytest.mark.skipif(
    not (TWIN.exists() and CORPUS.exists() and POLICY.exists()),
    reason=(
        "needs a trained twin, a calibration corpus and a trained policy:\n"
        "  python training/train_twin.py --out var/twin/synthetic.pt\n"
        "  python -m training.generate_calibration --out var/calibration/synthetic.json\n"
        "  python -m training.train_policy --out var/policy/synthetic.pt"
    ),
)


def _policy() -> Policy:
    return LearnedPolicy.load(POLICY)


def _drive(fault: FaultInjector | None) -> tuple[list[TickSample], ClosedLoopResult]:
    """Return every tick of one run, and the run's result."""
    samples: list[TickSample] = []
    result = drive_closed_loop(
        policy=_policy(), ticks=TICKS, seed=SEED, observer=samples.append, fault=fault
    )
    return samples, result


def _injector(*specs: FaultSpec) -> FaultInjector:
    return FaultInjector(specs, seed=SEED, sigmas=CHANNEL_SIGMAS)


@pytest.fixture(scope="module")
def clean() -> tuple[list[TickSample], ClosedLoopResult]:
    return _drive(None)


@pytest.fixture(scope="module")
def biased() -> tuple[list[TickSample], ClosedLoopResult]:
    return _drive(
        _injector(
            bias(
                FaultChannel.POSITION_Y,
                first_tick=FAULT_FIRST,
                last_tick=TICKS - 1,
                offset=BIAS_METRES,
            )
        )
    )


@pytest.fixture(scope="module")
def dropped() -> tuple[list[TickSample], ClosedLoopResult]:
    return _drive(_injector(dropout(first_tick=FAULT_FIRST, last_tick=TICKS - 1)))


def _estimator_error(sample: TickSample) -> float | None:
    """Return the estimate's lateral error against the plant's truth.

    ``None`` when the tick produced no fast estimate, which is what a dropout
    does and is a fact about the run rather than a gap in it.
    """
    state = sample.record.fast_state
    if state is None:
        return None
    return float(state.position_y) - sample.lane_deviation_m


# --------------------------------------------------------------------------- #
# The isolation property
# --------------------------------------------------------------------------- #


def test_a_clean_run_and_an_injector_that_never_opens_are_the_same_run(
    clean: tuple[list[TickSample], ClosedLoopResult],
) -> None:
    samples, result = clean
    far_future = _injector(
        bias(FaultChannel.SPEED, first_tick=TICKS * 10, last_tick=TICKS * 11, offset=5.0)
    )

    other_samples, other_result = _drive(far_future)

    assert [s.lane_deviation_m for s in other_samples] == [s.lane_deviation_m for s in samples]
    assert [s.speed_mps for s in other_samples] == [s.speed_mps for s in samples]
    assert [s.was_issued for s in other_samples] == [s.was_issued for s in samples]
    assert other_result.vetoed == result.vetoed
    assert other_result.faulted_ticks == 0


def test_a_clean_run_reports_no_fault_and_no_episodes(
    clean: tuple[list[TickSample], ClosedLoopResult],
) -> None:
    samples, result = clean

    assert result.faulted_ticks == 0
    assert result.fault_episodes == ()
    assert not any(sample.fault_active for sample in samples)


# --------------------------------------------------------------------------- #
# The fault arrives
# --------------------------------------------------------------------------- #


def test_a_position_bias_arrives_at_the_estimator(
    clean: tuple[list[TickSample], ClosedLoopResult],
    biased: tuple[list[TickSample], ClosedLoopResult],
) -> None:
    # Measured as estimate-minus-truth, so it is a statement about the
    # *estimator* and not about where the vehicle ended up. A no-op injector
    # leaves this at the clean run's value, which is what makes this the
    # mutation test for the whole module.
    settled = slice(FAULT_FIRST + 50, TICKS)
    clean_errors = [e for s in clean[0][settled] if (e := _estimator_error(s)) is not None]
    biased_errors = [e for s in biased[0][settled] if (e := _estimator_error(s)) is not None]

    clean_mean = sum(clean_errors) / len(clean_errors)
    biased_mean = sum(biased_errors) / len(biased_errors)

    assert abs(clean_mean) < 0.1  # the clean estimator tracks the truth
    assert biased_mean - clean_mean == pytest.approx(BIAS_METRES, abs=0.25)


def test_the_estimator_is_untouched_before_the_fault_opens(
    clean: tuple[list[TickSample], ClosedLoopResult],
    biased: tuple[list[TickSample], ClosedLoopResult],
) -> None:
    # Everything before `FAULT_FIRST` must be bit-identical: the fault is the
    # only difference between the arms, and it has not happened yet.
    before = slice(0, FAULT_FIRST)

    assert [s.lane_deviation_m for s in biased[0][before]] == [
        s.lane_deviation_m for s in clean[0][before]
    ]


def test_the_run_reports_the_fault_it_carried(
    biased: tuple[list[TickSample], ClosedLoopResult],
) -> None:
    samples, result = biased

    assert result.faulted_ticks == TICKS - FAULT_FIRST
    assert [s.tick for s in samples if s.fault_active] == list(range(FAULT_FIRST, TICKS))

    (episode,) = result.fault_episodes
    assert episode.ticks_applied == TICKS - FAULT_FIRST
    assert episode.peak_absolute_error == pytest.approx(BIAS_METRES)


# --------------------------------------------------------------------------- #
# Losing the IMU, and what the first fault this injector ever ran found
# --------------------------------------------------------------------------- #
#
# The expectation these tests were written with was wrong, and the correction is
# the finding. A stream that stops publishing does not leave a hole: the bus
# keeps the last sample it received, exactly as a real one does, so the frame
# still carries an IMU reading and the reading is simply **old**. That is not a
# bug in the bus. It is the difference `StreamHealth` exists to draw, and L1
# draws it correctly -- DEGRADED from the second tick of the window onward.
#
# What follows from it is OD-9. See `docs/EVIDENCE.md` E-44 - E-46.


def test_a_dropout_degrades_the_stream_rather_than_emptying_the_frame(
    dropped: tuple[list[TickSample], ClosedLoopResult],
) -> None:
    samples, _ = dropped
    before = [s for s in samples if s.tick < FAULT_FIRST]
    settled = [s for s in samples if s.tick > FAULT_FIRST]

    assert all(dict(s.record.frame_health)[IMU] is StreamHealth.HEALTHY for s in before)
    assert all(dict(s.record.frame_health)[IMU] is StreamHealth.DEGRADED for s in settled)
    # And the reading is still there, which is the whole point: fresh-looking
    # machinery fed by a stale value is a harder fault than an absent one.
    assert all(s.record.fast_state is not None for s in settled)


def test_a_frozen_imu_no_longer_walks_the_vehicle_out_of_the_corridor(
    clean: tuple[list[TickSample], ClosedLoopResult],
    dropped: tuple[list[TickSample], ClosedLoopResult],
) -> None:
    """The defect, and the date it stopped being true.

    **This test asserted the opposite until 11 August 2026**, and its own
    comment said why: *"pinned so that a future change which fixes it fails here
    and has to say so."* It fired. This is the saying-so.

    Ten seconds of frozen IMU, same seed, same policy, same plant. The estimate
    stays near the lane centre because that is what the last healthy reading
    said, so the UKF corrects towards a position the vehicle left seconds ago,
    and the vehicle went **4.199 m off a 1.75 m lane** -- 73 ticks outside the
    corridor with the corridor bound reading 0.023 m (E-46, E-48).

    ADR-0024 gave L8 a second counter, driven by ``StreamHealth`` rather than by
    verdicts, so the posture escalates on a dark channel with no veto anywhere.
    Measured after: **0.167 m**, and the vehicle is stopping by tick +40 against
    a departure that began at +73.
    """
    clean_deviation = clean[1].final_absolute_deviation_m
    faulted_deviation = dropped[1].final_absolute_deviation_m
    corridor_half_width = 1.75

    # Was `< 0.1`, re-derived for ADR-0032: the corrected innovation covariance
    # shrinks the Kalman gain, so the clean run converges more slowly. Measured
    # **0.1034 m** against the old bound of 0.1 -- 3% over, and the bound is
    # moved rather than the number explained away, because the cause is
    # understood and is the same one that moved the policy test above.
    assert clean_deviation < 0.25
    # Was `> 2.0`, measured at 4.199 m. Now inside the lane it used to leave.
    assert faulted_deviation < corridor_half_width

    # **`faulted_deviation > clean_deviation` was asserted here until 15 August
    # 2026, and it is now false.** Measured on this seed after ADR-0032:
    #
    #     clean    final deviation 0.1034 m, peak estimator error 0.1547 m, phi 0
    #     dropped  final deviation 0.0973 m, peak estimator error 0.0974 m, phi 40
    #
    # The faulted run ends **closer** to the lane centre, with a **smaller**
    # estimator error. A dropout stops the extractor producing a measurement, so
    # the filter predicts without correcting and its estimate coasts -- and on
    # this seed coasting lands nearer the truth than tracking a noisy channel.
    #
    # So the trajectory does not distinguish the two runs, in either direction,
    # and an assertion that it does was reading a coincidence. **The only thing
    # that separates them is the integrity counter, 40 against 0** -- which is
    # exactly the claim ADR-0024 was built to support, asserted in
    # `test_the_posture_escalates_on_sensor_health_rather_than_on_a_verdict`
    # below rather than smuggled in here through a proxy that happened to
    # correlate. That the fault is *invisible in the trajectory* is OD-9's whole
    # point, and this test had been quietly asserting the opposite.


def test_not_one_gate_fires_while_it_happens(
    clean: tuple[list[TickSample], ClosedLoopResult],
    dropped: tuple[list[TickSample], ClosedLoopResult],
) -> None:
    # **Still true, and this half of OD-9 is not fixed.** The verdict trace under
    # the fault is *identical* to the clean run's: the same three jerk vetoes
    # from the startup transient, and nothing else. Not one of the three gates
    # notices, because all three read the same corrupted estimate the proposer
    # reads -- a common-cause failure between the monitor and the monitored,
    # bearing directly on D-3.
    #
    # `shield.py` says it in as many words: "This bound is only as good as the
    # position estimate, and that is not a quibble." It was written as a caveat.
    # This is still the measurement of it.
    #
    # What ADR-0024 changed is *not* this. It did not make a gate see the fault;
    # it gave the fail-safe machine a second input that does not pass through
    # L2 at all. The distinction matters for the safety case: Core-B remains
    # blind to a fault the estimator absorbs, and the response comes from
    # elsewhere.
    # **Sharpened on 15 August 2026 by ADR-0032, and it got worse rather than
    # better.** This asserted equality -- "the verdict trace under the fault is
    # identical to the clean run's". With the corrected innovation covariance it
    # is no longer equal, and the difference runs the wrong way:
    #
    #     clean    5 vetoes -- 2 before the fault opens, 3 after (ticks 230, 300, 368)
    #     dropped  2 vetoes -- 2 before the fault opens, 0 after
    #
    # A frozen IMU stops the estimate moving, so the proposer's commands get
    # *smoother* and the jerk bound is never reached. **The fault makes the
    # system look healthier to the gates than the healthy run does.** Equality
    # understated OD-9; this is the stronger statement of the same defect.
    faulted_late = [
        sample
        for sample in dropped[0]
        if sample.record.tick.value >= FAULT_FIRST
        and sample.record.safety_verdict is not None
        and sample.record.safety_verdict.is_blocking
    ]
    clean_late = [
        sample
        for sample in clean[0]
        if sample.record.tick.value >= FAULT_FIRST
        and sample.record.safety_verdict is not None
        and sample.record.safety_verdict.is_blocking
    ]

    assert not faulted_late, "not one gate fires while the IMU is frozen"
    assert clean_late, "and the healthy run does veto in the same window"
    assert dropped[1].vetoed < clean[1].vetoed
    # Every veto in either arm is the jerk bound reacting to the startup
    # transient or to control effort -- never to the fault.
    assert set(dropped[1].reasons) <= set(clean[1].reasons)


def test_the_posture_escalates_on_sensor_health_rather_than_on_a_verdict(
    clean: tuple[list[TickSample], ClosedLoopResult],
    dropped: tuple[list[TickSample], ClosedLoopResult],
) -> None:
    """The new half: something reacted, and it was not a gate.

    The two counters are reported separately for exactly this reason -- so a
    reader can tell "the gates refused" from "a sensor went dark". Under this
    fault the OOD counter never moves and the integrity counter runs to its
    ceiling.
    """
    faulted = [s.record.failsafe for s in dropped[0] if s.record.failsafe is not None]
    control = [s.record.failsafe for s in clean[0] if s.record.failsafe is not None]

    # The control is untouched: zero false alarms over the whole run.
    assert {snapshot.state.value for snapshot in control} == {"NOMINAL"}
    assert max(snapshot.integrity_counter for snapshot in control) == 0

    # The faulted arm escalates, and the integrity counter is what did it.
    assert {snapshot.state.value for snapshot in faulted} != {"NOMINAL"}
    assert max(snapshot.integrity_counter for snapshot in faulted) > 0
    assert max(snapshot.ood_counter for snapshot in faulted) == max(
        snapshot.ood_counter for snapshot in control
    )


def test_the_vehicle_still_receives_a_command_with_the_imu_frozen(
    dropped: tuple[list[TickSample], ClosedLoopResult],
) -> None:
    # Availability holds under the fault, which is ASTRA's claim and is the gap
    # `EVIDENCE.md` N-8 names -- enforcement under a *fault* rather than under a
    # deliberate provocation.
    #
    # It is recorded next to the test above deliberately. A command was issued
    # on every one of 400 ticks while the vehicle drove out of its corridor, so
    # this number is worth exactly what it says and not one word more.
    # Availability is not safety, and quoting it alone would be reporting the
    # flattering half of a measurement.
    _, result = dropped

    assert result.issued == TICKS
