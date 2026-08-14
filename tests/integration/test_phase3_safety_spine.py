"""The deterministic safety spine, wired to the state estimate it judges.

Phase 3's exit criteria are assembly properties: a shield VETO that no PASS can
suppress, and a fail-safe machine that walks the full escalation ladder and back
without a restart. Both are asserted here against L1 and L2 driving real state
into L7a, rather than against hand-built records, so the layers are shown to
agree about what a state estimate means.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest

from astra.config.schema import EstimationSettings, FailSafeSettings, ShieldSettings
from astra.contracts.actuation import (
    ActuationChannel,
    ActuationSpace,
    CommandOrigin,
    ControlCommand,
    ProposedCommand,
)
from astra.contracts.assurance import GateVerdict, SafetyVerdict
from astra.contracts.estimation import SlowStateEstimate
from astra.contracts.sensing import FusedSensorFrame, SensorSample
from astra.kernel.enums import FailSafeState, GateId, LayerId, SensorModality, Verdict
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l1_sensing.bus import SharedSensorBus
from astra.layers.l2_estimation.filter import DualRateUKF
from astra.layers.l2_estimation.measurement import fast_measurement, slow_measurement
from astra.layers.l7_shield.shield import (
    REASON_LATERAL_ACCELERATION,
    REASON_NOMINAL,
    HardSafetyShield,
)
from astra.layers.l8_failsafe.machine import FailSafeStateMachine
from astra.runtime.channels import open_proposal_channel

if TYPE_CHECKING:
    from astra.contracts.audit import JsonValue
    from astra.layers.l2_estimation.measurement import Measurement

TICK_PERIOD = Seconds(0.05)
CRUISE_SPEED = 25.0
DRY_FRICTION = 0.85
ICE_FRICTION = 0.15

THETA_DEGRADED = 3
THETA_LIMP = 6
THETA_HALT = 10


def _shield_settings() -> ShieldSettings:
    return ShieldSettings(
        legal_speed_limit_kmh=120.0,
        friction_margin=0.8,
        minimum_stopping_distance_m=5.0,
        assured_clear_distance_m=150.0,
        lateral_corridor_half_width_m=1000.0,
    )


def _failsafe_settings() -> FailSafeSettings:
    return FailSafeSettings(
        ood_threshold_degraded=THETA_DEGRADED,
        ood_threshold_limp=THETA_LIMP,
        ood_threshold_halt=THETA_HALT,
        degraded_speed_cap_kmh=60.0,
        limp_speed_cap_kmh=20.0,
        integrity_threshold_degraded=5,
        integrity_threshold_limp=15,
        integrity_threshold_halt=40,
        integrity_tolerated_faults=0,
        critical_modalities=(
            SensorModality.CAMERA,
            SensorModality.LIDAR,
            SensorModality.IMU,
            SensorModality.GPS,
            SensorModality.RADAR,
        ),
    )


def _estimation_settings() -> EstimationSettings:
    return EstimationSettings(
        innovation_gate_gamma=9.0,
        fast_process_noise=(0.02, 0.02, 0.05, 0.005, 0.30),
        slow_process_noise=(1e-5, 1e-6, 1e-5),
    )


class _Extractor:
    """Observes the payloads L1 carried, as an adapter would."""

    def extract_fast(self, frame: FusedSensorFrame[JsonValue]) -> Measurement | None:
        sample = frame.sample_for(SensorModality.IMU)
        if sample is None or not isinstance(sample.payload, dict):
            return None
        return fast_measurement(
            [
                ("speed", float(sample.payload["v"]), 0.01),  # type: ignore[arg-type]
                ("lateral_acceleration", float(sample.payload["a_lat"]), 0.04),  # type: ignore[arg-type]
            ]
        )

    def extract_slow(self, frame: FusedSensorFrame[JsonValue]) -> Measurement | None:
        del frame
        return slow_measurement([("road_friction_coefficient", DRY_FRICTION, 4e-4)])


def _proposal(tick: int) -> ProposedCommand:
    space = ActuationSpace((ActuationChannel("throttle", 0.0, 1.0, "1"),))
    return ProposedCommand(
        tick=TickId(tick),
        proposed_at=Instant(tick, Timeline.MANUAL),
        command=ControlCommand(space, (0.5,)),
        origin=CommandOrigin.PROPOSED,
        source=ComponentId(LayerId.L4_CORE_A_CMDP),
    )


def _degradation(friction: float) -> SlowStateEstimate:
    return SlowStateEstimate(
        tick=TickId(0),
        valid_at=Instant(0, Timeline.MANUAL),
        mean=(friction, 0.0, 1.0),
        covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
    )


def _drive_to_state(lateral_acceleration: float, ticks: int = 40) -> object:
    """Run L1 and L2 until the filter has converged on a commanded manoeuvre."""
    clock = ManualClock(Instant(0, Timeline.MANUAL))
    bus: SharedSensorBus[JsonValue] = SharedSensorBus(clock=clock, staleness_budget=Seconds(0.05))
    estimator: DualRateUKF[JsonValue] = DualRateUKF(
        settings=_estimation_settings(),
        extractor=_Extractor(),
        initial_fast_state=[0.0, 0.0, CRUISE_SPEED, 0.0, 0.0],
        initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0, 0.1, 1.0]),
        initial_slow_state=[DRY_FRICTION, 0.0, 1.0],
        initial_slow_covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
    )
    estimate = None
    for tick in range(ticks):
        bus.publish(
            SensorSample(
                modality=SensorModality.IMU,
                observed_at=clock.now(),
                quality=Probability(1.0),
                payload={"v": CRUISE_SPEED, "a_lat": lateral_acceleration},
            )
        )
        estimate = estimator.update_fast(bus.acquire(TickId(tick)))
        clock.advance(TICK_PERIOD)
    return estimate


# --------------------------------------------------------------------------- #
# The shield judges real state produced by L1 and L2
# --------------------------------------------------------------------------- #


def test_the_shield_passes_a_manoeuvre_the_filter_reports_as_within_friction() -> None:
    shield = HardSafetyShield(_shield_settings())
    state = _drive_to_state(lateral_acceleration=1.5)

    verdict = shield.evaluate(
        tick=TickId(0),
        proposal=_proposal(0),
        state=state,  # type: ignore[arg-type]
        degradation=_degradation(DRY_FRICTION),
    )

    assert verdict.verdict is Verdict.PASS
    assert verdict.reason_code == REASON_NOMINAL


def test_the_same_manoeuvre_is_vetoed_once_the_road_is_ice() -> None:
    # The adaptive-friction property, end to end: identical state estimate,
    # identical proposal, opposite verdicts. A shield with a hard-coded friction
    # constant would pass both.
    shield = HardSafetyShield(_shield_settings())
    state = _drive_to_state(lateral_acceleration=5.0)

    on_tarmac = shield.evaluate(
        tick=TickId(0),
        proposal=_proposal(0),
        state=state,  # type: ignore[arg-type]
        degradation=_degradation(DRY_FRICTION),
    )
    on_ice = shield.evaluate(
        tick=TickId(0),
        proposal=_proposal(0),
        state=state,  # type: ignore[arg-type]
        degradation=_degradation(ICE_FRICTION),
    )

    assert on_tarmac.verdict is Verdict.PASS
    assert on_ice.verdict is Verdict.VETO
    assert on_ice.reason_code == REASON_LATERAL_ACCELERATION


# --------------------------------------------------------------------------- #
# Exit criterion: no PASS can suppress the shield's VETO (SI-3)
# --------------------------------------------------------------------------- #


def test_no_number_of_passes_can_suppress_a_shield_veto() -> None:
    shield = HardSafetyShield(_shield_settings())
    state = _drive_to_state(lateral_acceleration=5.0)
    shield_veto = shield.evaluate(
        tick=TickId(0),
        proposal=_proposal(0),
        state=state,  # type: ignore[arg-type]
        degradation=_degradation(ICE_FRICTION),
    )
    assert shield_veto.verdict is Verdict.VETO

    passes = (
        GateVerdict(TickId(0), GateId.STATISTICAL, Verdict.PASS, "NOMINAL"),
        GateVerdict(TickId(0), GateId.PHYSICAL, Verdict.PASS, "NOMINAL"),
    )

    assert SafetyVerdict(TickId(0), (shield_veto,)).aggregate is Verdict.VETO
    assert SafetyVerdict(TickId(0), (*passes, shield_veto)).aggregate is Verdict.VETO
    assert SafetyVerdict(TickId(0), (shield_veto, *passes)).aggregate is Verdict.VETO
    assert SafetyVerdict(TickId(0), (*passes, shield_veto)).vetoing_gates == (GateId.DETERMINISTIC,)


def test_a_tick_no_gate_inspected_is_a_veto_not_a_pass() -> None:
    # The fail-closed default. A command nothing looked at has not been cleared.
    assert SafetyVerdict(TickId(0), ()).aggregate is Verdict.VETO


# --------------------------------------------------------------------------- #
# Exit criterion: the FSM walks the ladder and back without a restart
# --------------------------------------------------------------------------- #


def _verdict(tick: int, *, blocking: bool) -> SafetyVerdict:
    gate_verdict = GateVerdict(
        tick=TickId(tick),
        gate=GateId.DETERMINISTIC,
        verdict=Verdict.VETO if blocking else Verdict.PASS,
        reason_code="TEST",
    )
    return SafetyVerdict(TickId(tick), (gate_verdict,))


def test_the_machine_walks_nominal_to_limp_and_back_without_a_restart() -> None:
    machine = FailSafeStateMachine(_failsafe_settings())
    tick = 0

    def drive(count: int, *, blocking: bool) -> FailSafeState:
        nonlocal tick
        state = machine.state
        for _ in range(count):
            state = machine.observe(
                tick=TickId(tick), verdict=_verdict(tick, blocking=blocking)
            ).state
            tick += 1
        return state

    assert drive(1, blocking=False) is FailSafeState.NOMINAL
    assert drive(THETA_DEGRADED, blocking=True) is FailSafeState.DEGRADED
    assert drive(THETA_LIMP - THETA_DEGRADED, blocking=True) is FailSafeState.LIMP
    # Recovery is the same mechanism run backwards. No reset() is called.
    assert drive(THETA_LIMP + 2, blocking=False) is FailSafeState.NOMINAL
    assert machine.ood_counter == 0


def test_halt_is_latched_and_only_an_explicit_reset_leaves_it() -> None:
    machine = FailSafeStateMachine(_failsafe_settings())
    for tick in range(THETA_HALT):
        machine.observe(tick=TickId(tick), verdict=_verdict(tick, blocking=True))
    assert machine.state is FailSafeState.HALT

    for tick in range(200):
        machine.observe(tick=TickId(tick), verdict=_verdict(tick, blocking=False))

    assert machine.state is FailSafeState.HALT, "a controlled pull-over must not self-resume"
    assert machine.snapshot.human_intervention_requested is True


def test_an_explicit_reset_returns_a_halted_machine_to_nominal() -> None:
    machine = FailSafeStateMachine(_failsafe_settings())
    for tick in range(THETA_HALT):
        machine.observe(tick=TickId(tick), verdict=_verdict(tick, blocking=True))

    machine.reset()

    assert machine.state is FailSafeState.NOMINAL
    assert machine.ood_counter == 0


def test_the_speed_cap_tightens_as_the_posture_degrades() -> None:
    machine = FailSafeStateMachine(_failsafe_settings())
    caps: list[float | None] = []
    for tick in range(THETA_HALT):
        snapshot = machine.observe(tick=TickId(tick), verdict=_verdict(tick, blocking=True))
        caps.append(None if snapshot.speed_cap is None else float(snapshot.speed_cap))

    present = [cap for cap in caps if cap is not None]

    assert caps[0] is None, "NOMINAL imposes no cap"
    assert present == sorted(present, reverse=True), "the cap must only tighten"
    assert present[-1] == 0.0, "HALT commands a stop, which is a cap of zero, not None"


# --------------------------------------------------------------------------- #
# The shield and the machine, driven together
# --------------------------------------------------------------------------- #


def test_a_sustained_friction_breach_escalates_the_machine_to_halt() -> None:
    # The spine end to end: a state the shield rejects, sustained, walks the
    # posture all the way down without any component special-casing anything.
    shield = HardSafetyShield(_shield_settings())
    machine = FailSafeStateMachine(_failsafe_settings())
    state = _drive_to_state(lateral_acceleration=5.0)
    observed: list[FailSafeState] = []

    for tick in range(THETA_HALT):
        gate_verdict = shield.evaluate(
            tick=TickId(tick),
            proposal=_proposal(tick),
            state=state,  # type: ignore[arg-type]
            degradation=_degradation(ICE_FRICTION),
        )
        snapshot = machine.observe(
            tick=TickId(tick), verdict=SafetyVerdict(TickId(tick), (gate_verdict,))
        )
        observed.append(snapshot.state)

    assert observed[-1] is FailSafeState.HALT
    assert FailSafeState.DEGRADED in observed
    assert FailSafeState.LIMP in observed
    assert [state.severity_rank for state in observed] == sorted(
        state.severity_rank for state in observed
    ), "the posture must escalate monotonically under a sustained breach"


def test_a_nominal_drive_never_leaves_nominal() -> None:
    shield = HardSafetyShield(_shield_settings())
    machine = FailSafeStateMachine(_failsafe_settings())
    state = _drive_to_state(lateral_acceleration=1.0)

    for tick in range(50):
        gate_verdict = shield.evaluate(
            tick=TickId(tick),
            proposal=_proposal(tick),
            state=state,  # type: ignore[arg-type]
            degradation=_degradation(DRY_FRICTION),
        )
        snapshot = machine.observe(
            tick=TickId(tick), verdict=SafetyVerdict(TickId(tick), (gate_verdict,))
        )
        assert snapshot.state is FailSafeState.NOMINAL
        assert snapshot.speed_cap is None


# --------------------------------------------------------------------------- #
# SI-5: the proposal reaches Core-B and nothing comes back
# --------------------------------------------------------------------------- #


def test_a_proposal_crosses_to_core_b_and_the_writer_offers_no_way_back() -> None:
    writer, reader = open_proposal_channel()
    sent = _proposal(7)

    assert writer.send(sent) is True
    received = reader.receive()

    assert received == sent
    # The enforcement is the absence: Core-A holds an object with no method that
    # could return a verdict, an FSM state or a calibration table.
    assert {name for name in dir(writer) if not name.startswith("_")} == {"send", "pending"}


def test_a_stalled_core_b_makes_the_tick_veto_rather_than_blocking_core_a() -> None:
    writer, _reader = open_proposal_channel(capacity=2)
    for tick in range(2):
        assert writer.send(_proposal(tick)) is True

    # Core-B has stopped consuming. The send must fail rather than block.
    delivered = writer.send(_proposal(2))

    assert delivered is False
    # An undelivered proposal means Core-B validates nothing, which is an empty
    # verdict set, which merges to VETO through the ordinary path.
    assert SafetyVerdict(TickId(2), ()).aggregate is Verdict.VETO


# --------------------------------------------------------------------------- #
# The spine costs almost nothing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("lateral_acceleration", [0.0, 1.0, 3.0, 5.0, -5.0])
def test_the_shield_is_a_pure_function_of_its_inputs(lateral_acceleration: float) -> None:
    # Statelessness matters: a shield that accumulated state could be driven
    # into a permissive mode by a sequence of inputs, and its verdict would stop
    # being independently auditable.
    shield = HardSafetyShield(_shield_settings())
    state = _drive_to_state(lateral_acceleration=lateral_acceleration)
    proposal = _proposal(0)
    degradation = _degradation(DRY_FRICTION)

    first = shield.evaluate(
        tick=TickId(0),
        proposal=proposal,
        state=state,  # type: ignore[arg-type]
        degradation=degradation,
    )
    second = shield.evaluate(
        tick=TickId(0),
        proposal=proposal,
        state=state,  # type: ignore[arg-type]
        degradation=degradation,
    )

    assert first == second
    assert all(math.isfinite(value) for _, value in first.evidence)
