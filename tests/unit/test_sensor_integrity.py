"""Can the fail-safe machine see a fault that produces no vetoes?

The defect these tests exist to close
---------------------------------------
OD-9, and it is the worst one this project has found. Every Core-B gate reads
L2's fast estimate, and the proposer closes its loop on that same estimate, so a
corrupted sensor reading is *actively driven* to the value the gates consider
safe. Measured on 9 August 2026: a 200-tick IMU dropout put the vehicle **4.199 m
off a 1.75 m lane**, 73 ticks outside the corridor, with the corridor bound
reading **0.023 m**, a veto count and reason codes **identical to the clean
control's**, and the fail-safe machine ``NOMINAL`` on all 400 ticks (E-46, E-48).

**A veto could not have fixed it.** L9's fallback controller reads the same
corrupted estimate, so refusing the proposal substitutes one command computed
from a lie for another. That is the sentence worth carrying out of OD-9: *you
cannot veto your way out of a lying sensor.*

So the answer is not a fourth gate. It is a second **counter** — driven by
``StreamHealth``, which L1 computes at the sensor boundary before the filter
touches anything, and which is therefore the one input to this machine that sits
upstream of the common cause. See ADR-0024.

What was measured after
------------------------
Same command, same seed, same fault (``uv run python -m benchmarks.fault_study``):

===================  ===============  =========================
scenario             final ``|dev|``  escalation after the fault
===================  ===============  =========================
``imu_dropout``      4.199 m → 0.167  DEGRADED +5, LIMP +15, HALT +40
control              0.009 m          none, integrity counter 0
``position_drift``   2.025 m          none, integrity counter 0
===================  ===============  =========================

The departure began at +73. HALT arrives at +40, so the vehicle is stopping
**1.65 seconds before** it would have left its lane.

**And it catches exactly one of the six faults.** ``BIAS``, ``DRIFT``,
``STUCK_AT`` and the two speed faults all keep the stream perfectly *fresh* —
that is why they were chosen — so ``StreamHealth`` never moves and this counter
never rises. Half of these tests exist to pin that silence, because a mechanism
whose scope is not asserted is a mechanism whose scope will be overstated.
"""

from __future__ import annotations

import pytest

from astra.config.schema import FailSafeSettings
from astra.contracts.assurance import GateVerdict, SafetyVerdict
from astra.kernel.enums import FailSafeState, GateId, SensorModality, StreamHealth, Verdict
from astra.kernel.identifiers import TickId
from astra.layers.l8_failsafe.machine import FailSafeStateMachine

SETTINGS = FailSafeSettings(
    ood_threshold_degraded=10,
    ood_threshold_limp=30,
    ood_threshold_halt=100,
    degraded_speed_cap_kmh=60.0,
    limp_speed_cap_kmh=20.0,
    integrity_threshold_degraded=5,
    integrity_threshold_limp=15,
    integrity_threshold_halt=40,
)

HEALTHY = ((SensorModality.IMU, StreamHealth.HEALTHY), (SensorModality.GPS, StreamHealth.HEALTHY))
IMU_DARK = ((SensorModality.IMU, StreamHealth.ABSENT), (SensorModality.GPS, StreamHealth.HEALTHY))
IMU_DEGRADED = (
    (SensorModality.IMU, StreamHealth.DEGRADED),
    (SensorModality.GPS, StreamHealth.HEALTHY),
)


def passing(tick: int = 0) -> SafetyVerdict:
    """Return a verdict every gate passed.

    The point of most of these tests: the verdict stream is **clean** and the
    posture escalates anyway, which is impossible on the OOD counter alone and
    is the whole of OD-9.
    """
    return SafetyVerdict(
        tick=TickId(tick),
        gate_verdicts=(
            GateVerdict(
                tick=TickId(tick),
                gate=GateId.STATISTICAL,
                verdict=Verdict.PASS,
                reason_code="NOMINAL",
            ),
        ),
    )


def blocking(tick: int = 0) -> SafetyVerdict:
    """Return a blocking verdict."""
    return SafetyVerdict(
        tick=TickId(tick),
        gate_verdicts=(
            GateVerdict(
                tick=TickId(tick),
                gate=GateId.STATISTICAL,
                verdict=Verdict.VETO,
                reason_code="SCORE_EXCEEDS_CONFORMAL_QUANTILE",
            ),
        ),
    )


def machine() -> FailSafeStateMachine:
    return FailSafeStateMachine(SETTINGS)


# --------------------------------------------------------------------------- #
# The defect itself — escalation with no veto at all
# --------------------------------------------------------------------------- #


def test_a_dark_sensor_escalates_the_posture_with_no_veto_anywhere() -> None:
    # OD-9 in one assertion. Before ADR-0024 this machine stayed NOMINAL for
    # every one of these ticks, because nothing it read had changed.
    fsm = machine()

    for tick in range(60):
        fsm.observe(tick=TickId(tick), verdict=passing(tick), frame_health=IMU_DARK)

    assert fsm.state is FailSafeState.HALT
    assert fsm.ood_counter == 0


def test_the_escalation_arrives_at_the_configured_thresholds() -> None:
    # Not "it escalates eventually" -- the tick each posture arrives on is the
    # number that decides whether the response beats the hazard. Measured
    # against a 73-tick departure, so all three must land well inside it.
    fsm = machine()
    arrived: dict[FailSafeState, int] = {}

    for tick in range(60):
        snapshot = fsm.observe(tick=TickId(tick), verdict=passing(tick), frame_health=IMU_DARK)
        arrived.setdefault(snapshot.state, tick)

    assert arrived[FailSafeState.DEGRADED] == SETTINGS.integrity_threshold_degraded - 1
    assert arrived[FailSafeState.LIMP] == SETTINGS.integrity_threshold_limp - 1
    assert arrived[FailSafeState.HALT] == SETTINGS.integrity_threshold_halt - 1


def test_degraded_is_reached_before_the_measured_departure() -> None:
    # The claim that makes this worth shipping, stated as a bound rather than a
    # story: every configured threshold must land inside the 73 ticks the
    # measured departure took (E-46).
    departure_ticks = 73

    assert SETTINGS.integrity_threshold_halt < departure_ticks


def test_a_degraded_stream_counts_the_same_as_an_absent_one() -> None:
    # StreamHealth has four values and only HEALTHY is healthy. Treating
    # DEGRADED as tolerable would mean the machine waits for a channel to go
    # fully absent, and L1 reports DEGRADED first -- so it would discard the
    # earliest warning it has.
    fsm = machine()

    for tick in range(SETTINGS.integrity_threshold_degraded):
        fsm.observe(tick=TickId(tick), verdict=passing(tick), frame_health=IMU_DEGRADED)

    assert fsm.state is FailSafeState.DEGRADED


# --------------------------------------------------------------------------- #
# The control — it must not fire on a healthy vehicle
# --------------------------------------------------------------------------- #


def test_a_healthy_frame_never_escalates() -> None:
    # The measured control run has zero false alarms over 400 ticks. Without
    # this test, a machine that escalated on everything would pass the test
    # above and be far worse than the defect it fixed.
    fsm = machine()

    for tick in range(400):
        fsm.observe(tick=TickId(tick), verdict=passing(tick), frame_health=HEALTHY)

    assert fsm.state is FailSafeState.NOMINAL
    assert fsm.integrity_counter == 0


def test_no_health_information_is_treated_as_healthy() -> None:
    # The default. A caller with no sensor bus -- every test written against the
    # verdict half of this machine -- means "I did not look", and escalating on
    # that would turn an absent input into a fault report.
    fsm = machine()

    for tick in range(400):
        fsm.observe(tick=TickId(tick), verdict=passing(tick))

    assert fsm.state is FailSafeState.NOMINAL
    assert fsm.integrity_counter == 0


def test_the_counter_recovers_when_the_stream_does() -> None:
    fsm = machine()
    for tick in range(SETTINGS.integrity_threshold_limp):
        fsm.observe(tick=TickId(tick), verdict=passing(tick), frame_health=IMU_DARK)
    escalated: FailSafeState = fsm.state
    assert escalated is FailSafeState.LIMP

    for tick in range(SETTINGS.integrity_threshold_limp, 200):
        fsm.observe(tick=TickId(tick), verdict=passing(tick), frame_health=HEALTHY)

    recovered: FailSafeState = fsm.state
    assert recovered is FailSafeState.NOMINAL
    assert fsm.integrity_counter == 0


def test_a_single_bad_frame_is_not_an_alarm() -> None:
    # One dropped frame in a stream is a glitch, and a machine that escalated on
    # it would spend its life in DEGRADED -- the same argument the OOD counter
    # was built on.
    fsm = machine()

    for tick in range(200):
        health = IMU_DARK if tick % 20 == 0 else HEALTHY
        fsm.observe(tick=TickId(tick), verdict=passing(tick), frame_health=health)

    assert fsm.state is FailSafeState.NOMINAL


# --------------------------------------------------------------------------- #
# The two counters are independent, and neither hides the other
# --------------------------------------------------------------------------- #


def test_the_two_counters_are_reported_separately() -> None:
    # "The gates refused forty commands" and "a sensor was dark for forty ticks"
    # need different responses from whoever reads the log, and one integer
    # cannot say which happened.
    fsm = machine()

    for tick in range(20):
        fsm.observe(tick=TickId(tick), verdict=blocking(tick), frame_health=IMU_DARK)

    assert fsm.snapshot.ood_counter == 20
    assert fsm.snapshot.integrity_counter == 20


def test_a_clean_verdict_stream_does_not_walk_back_a_sensor_escalation() -> None:
    # The failure this guards: taking a sum, an average, or "the OOD counter
    # unless the integrity one is higher" would all let good news on one axis
    # cancel bad news on the other. The machine takes the worse of the two.
    fsm = machine()

    for tick in range(200):
        fsm.observe(tick=TickId(tick), verdict=passing(tick), frame_health=IMU_DARK)

    assert fsm.state is FailSafeState.HALT


def test_a_healthy_sensor_does_not_walk_back_a_veto_escalation() -> None:
    # The same guard in the other direction.
    fsm = machine()

    for tick in range(200):
        fsm.observe(tick=TickId(tick), verdict=blocking(tick), frame_health=HEALTHY)

    assert fsm.state is FailSafeState.HALT


def test_the_integrity_counter_is_bounded_at_its_own_threshold() -> None:
    # Same reasoning as the OOD counter's ceiling: an integer that grows without
    # bound and influences nothing is noise, and this one is written into every
    # audit row. A soak once recorded 1,508 (OD-5).
    fsm = machine()

    for tick in range(500):
        fsm.observe(tick=TickId(tick), verdict=passing(tick), frame_health=IMU_DARK)

    assert fsm.integrity_counter == SETTINGS.integrity_threshold_halt


# --------------------------------------------------------------------------- #
# Exploration — the asymmetry, and why ADR-0023's accepted risk is now smaller
# --------------------------------------------------------------------------- #


def test_the_integrity_counter_does_not_freeze_during_exploration() -> None:
    # ADR-0023 froze the OOD counter while L9 owns the out-of-envelope
    # condition, and recorded as an accepted risk that a fault arising *during*
    # exploration would then not escalate. That risk is not accepted here: a
    # narrowed envelope is a response to the world being unfamiliar and says
    # nothing about whether the sensors are honest.
    fsm = machine()

    for tick in range(60):
        fsm.observe(
            tick=TickId(tick), verdict=blocking(tick), frame_health=IMU_DARK, exploring=True
        )

    assert fsm.state is FailSafeState.HALT
    assert fsm.ood_counter == 0
    assert fsm.integrity_counter == SETTINGS.integrity_threshold_halt


def test_exploration_still_freezes_the_ood_counter() -> None:
    # The control for the test above. Without it, that one would pass on a
    # machine that had simply stopped honouring ADR-0023.
    fsm = machine()

    for tick in range(400):
        fsm.observe(tick=TickId(tick), verdict=blocking(tick), frame_health=HEALTHY, exploring=True)

    assert fsm.state is FailSafeState.NOMINAL
    assert fsm.ood_counter == 0


# --------------------------------------------------------------------------- #
# Scope — the three faults this cannot see, asserted rather than implied
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ticks", [50, 200, 400])
def test_a_fresh_well_formed_wrong_reading_is_invisible_to_this_counter(ticks: int) -> None:
    # BIAS, DRIFT and STUCK_AT all keep the stream perfectly fresh, so L1
    # reports HEALTHY and this counter never moves. Measured: position_drift
    # still ends 2.025 m out with the integrity counter at 0.
    #
    # This is the honest half of ADR-0024 and it is asserted so that nobody can
    # later describe the mechanism as "detects sensor faults" without a test
    # turning red. The general answer is redundancy and a cross-check (P2.7
    # option D), which the reference plant cannot express -- it publishes one
    # ground truth to all five modalities -- and which is therefore Phase 7.
    fsm = machine()

    for tick in range(ticks):
        fsm.observe(tick=TickId(tick), verdict=passing(tick), frame_health=HEALTHY)

    assert fsm.state is FailSafeState.NOMINAL
    assert fsm.integrity_counter == 0


def test_reset_clears_both_counters() -> None:
    # A reset that left the integrity counter standing would re-escalate within
    # a tick or two if the sensor were still dark, which reads as the reset
    # having failed rather than as the fault having persisted.
    fsm = machine()
    for tick in range(60):
        fsm.observe(tick=TickId(tick), verdict=blocking(tick), frame_health=IMU_DARK)
    halted: FailSafeState = fsm.state
    assert halted is FailSafeState.HALT

    fsm.reset()

    after: FailSafeState = fsm.state
    assert after is FailSafeState.NOMINAL
    assert fsm.ood_counter == 0
    assert fsm.integrity_counter == 0
