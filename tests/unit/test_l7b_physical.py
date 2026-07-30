"""Unit tests for the L7b physical admissibility gate."""

from __future__ import annotations

import math

import pytest

from astra.config.schema import PhysicalGateSettings, ShieldSettings
from astra.contracts.actuation import (
    ActuationChannel,
    ActuationSpace,
    CommandOrigin,
    ControlCommand,
    PredictedCommand,
    ProposedCommand,
)
from astra.contracts.assurance import GateVerdict
from astra.contracts.estimation import FastStateEstimate, SlowStateEstimate
from astra.kernel.enums import GateId, LayerId, Verdict
from astra.kernel.errors import SafetyPathError
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, Timeline
from astra.kernel.units import Seconds
from astra.layers.l7_shield.shield import HardSafetyShield
from astra.layers.l7b_physical.checker import (
    REASON_CODES,
    REASON_LATERAL_JERK,
    REASON_MODEL_DIVERGENCE,
    REASON_NOMINAL,
    PhysicalAdmissibilityGate,
)
from astra.ports.pipeline import PhysicalAdmissibilityChecker

# Stated here rather than loaded, so the tests assert against bounds they
# declare rather than against whatever has most recently been tuned.
MAX_JERK = 12.0
ADMISSIBLE_DIVERGENCE = 4.0
TICK_PERIOD = 0.05  # 20 Hz
# One channel, gain 100 m/s^2 per unit: an implied acceleration is just
# 100 * value, which keeps the arithmetic in each test readable.
EFFECTIVENESS = (100.0,)

SPACE = ActuationSpace((ActuationChannel(name="steer", lower=-1.0, upper=1.0, unit="rad"),))
AT = Instant(1_000, Timeline.MANUAL)


def _gate(**overrides: float) -> PhysicalAdmissibilityGate:
    return PhysicalAdmissibilityGate(
        settings=PhysicalGateSettings(
            max_lateral_jerk_mps3=overrides.get("max_lateral_jerk_mps3", MAX_JERK),
            admissible_divergence_mps2=overrides.get(
                "admissible_divergence_mps2", ADMISSIBLE_DIVERGENCE
            ),
        ),
        control_effectiveness=EFFECTIVENESS,
        tick_period=Seconds(TICK_PERIOD),
    )


def _state(lateral: float, speed: float = 20.0) -> FastStateEstimate:
    return FastStateEstimate(
        tick=TickId(1),
        valid_at=AT,
        mean=(0.0, 0.0, speed, 0.0, lateral),
        covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5]),
    )


def _proposal(value: float) -> ProposedCommand:
    return ProposedCommand(
        tick=TickId(1),
        proposed_at=AT,
        command=ControlCommand(space=SPACE, values=(value,)),
        origin=CommandOrigin.PROPOSED,
        source=ComponentId(LayerId.L4_CORE_A_CMDP),
    )


def _prediction(value: float) -> PredictedCommand:
    return PredictedCommand(
        tick=TickId(1),
        predicted_at=AT,
        command=ControlCommand(space=SPACE, values=(value,)),
        source=ComponentId(LayerId.L5_PINN_TWIN),
    )


def _evaluate(
    gate: PhysicalAdmissibilityGate, *, proposed: float, predicted: float, current: float
) -> GateVerdict:
    return gate.evaluate(
        tick=TickId(1),
        proposal=_proposal(proposed),
        prediction=_prediction(predicted),
        state=_state(current),
    )


# --------------------------------------------------------------------------- #
# Port conformance and verdict shape
# --------------------------------------------------------------------------- #


def test_the_gate_satisfies_the_physical_admissibility_port() -> None:
    assert isinstance(_gate(), PhysicalAdmissibilityChecker)


def test_a_reachable_and_agreeing_proposal_passes() -> None:
    # 0.01 -> 1.0 m/s^2 implied; current 0.8; jerk = 0.2/0.05 = 4 < 12.
    verdict = _evaluate(_gate(), proposed=0.01, predicted=0.01, current=0.8)

    assert verdict.verdict is Verdict.PASS
    assert verdict.gate is GateId.PHYSICAL
    assert verdict.reason_code == REASON_NOMINAL


def test_every_reason_code_the_gate_emits_is_declared() -> None:
    emitted = {
        _evaluate(_gate(), proposed=0.01, predicted=0.01, current=0.8).reason_code,
        _evaluate(_gate(), proposed=0.5, predicted=0.5, current=0.0).reason_code,
        _evaluate(_gate(), proposed=0.1, predicted=0.0, current=9.9).reason_code,
    }

    assert emitted <= set(REASON_CODES)


def test_evidence_is_recorded_on_a_pass_not_only_on_a_veto() -> None:
    # An analyst needs the margin the vehicle actually had, not merely the fact
    # that it was inside the limit.
    verdict = _evaluate(_gate(), proposed=0.01, predicted=0.01, current=0.8)

    assert dict(verdict.evidence)["demanded_jerk_mps3"] == pytest.approx(4.0)
    assert dict(verdict.evidence)["max_lateral_jerk_mps3"] == pytest.approx(MAX_JERK)


# --------------------------------------------------------------------------- #
# Bound 1 -- lateral jerk
# --------------------------------------------------------------------------- #


def test_a_step_change_in_lateral_acceleration_is_vetoed() -> None:
    # 0.5 -> 50 m/s^2 implied, from 0: jerk = 50/0.05 = 1000 m/s^3.
    verdict = _evaluate(_gate(), proposed=0.5, predicted=0.5, current=0.0)

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_LATERAL_JERK


def test_the_jerk_bound_is_inclusive_at_the_limit() -> None:
    # Demanded jerk exactly 12.0: 12 * 0.05 = 0.6 m/s^2 change.
    verdict = _evaluate(_gate(), proposed=0.006, predicted=0.006, current=0.0)

    assert dict(verdict.evidence)["demanded_jerk_mps3"] == pytest.approx(12.0)
    assert verdict.verdict is Verdict.PASS


def test_the_jerk_bound_is_on_the_absolute_change() -> None:
    # Decelerating laterally as fast as accelerating is equally impossible.
    verdict = _evaluate(_gate(), proposed=0.0, predicted=0.0, current=50.0)

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_LATERAL_JERK


def test_the_same_command_is_reachable_from_a_near_state_and_not_from_a_far_one() -> None:
    # The bound is about the *change*, so the identical proposal is admissible
    # or not depending on where the vehicle already is.
    near = _evaluate(_gate(), proposed=0.05, predicted=0.05, current=4.9)
    far = _evaluate(_gate(), proposed=0.05, predicted=0.05, current=0.0)

    assert near.verdict is Verdict.PASS
    assert far.verdict is Verdict.VETO


# --------------------------------------------------------------------------- #
# Bound 2 -- model divergence
# --------------------------------------------------------------------------- #


def test_a_proposal_far_from_the_twin_is_vetoed() -> None:
    # Reachable (jerk small) but the twin expects something else entirely.
    verdict = _evaluate(_gate(), proposed=0.1, predicted=0.0, current=9.9)

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_MODEL_DIVERGENCE


def test_the_divergence_bound_is_inclusive_at_the_limit() -> None:
    # |100*0.1 - 100*0.06| = 4.0, exactly the limit.
    verdict = _evaluate(_gate(), proposed=0.1, predicted=0.06, current=9.9)

    assert dict(verdict.evidence)["model_divergence_mps2"] == pytest.approx(4.0)
    assert verdict.verdict is Verdict.PASS


def test_jerk_is_reported_before_divergence_when_both_are_breached() -> None:
    # A proposal the vehicle physically cannot execute is the more fundamental
    # fault, so it is the one the reason code should name.
    verdict = _evaluate(_gate(), proposed=0.9, predicted=0.0, current=0.0)

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_LATERAL_JERK


# --------------------------------------------------------------------------- #
# Independence from the deterministic shield
# --------------------------------------------------------------------------- #


def test_the_physical_gate_vetoes_a_command_the_shield_passes() -> None:
    # This is the property the whole two-gate split exists for. A modest
    # steering command on dry tarmac at low speed is comfortably inside every
    # hard bound, so L7a passes it -- but demanded as a step change from zero it
    # is not physically reachable, and L7b catches it.
    shield = HardSafetyShield(
        settings=ShieldSettings(
            legal_speed_limit_kmh=120.0,
            friction_margin=0.85,
            minimum_stopping_distance_m=2.0,
            assured_clear_distance_m=500.0,
        )
    )
    state = _state(lateral=0.0, speed=10.0)
    degradation = SlowStateEstimate(
        tick=TickId(1),
        valid_at=AT,
        mean=(0.9, 0.1, 0.95),
        covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
    )

    shield_verdict = shield.evaluate(
        tick=TickId(1), proposal=_proposal(0.5), state=state, degradation=degradation
    )
    physical_verdict = _evaluate(_gate(), proposed=0.5, predicted=0.5, current=0.0)

    assert shield_verdict.verdict is Verdict.PASS
    assert physical_verdict.verdict is Verdict.VETO


# --------------------------------------------------------------------------- #
# Fail-closed behaviour
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_state_fails_closed(bad: float) -> None:
    # nan > limit is False, so a NaN would satisfy both bounds and report PASS.
    with pytest.raises(SafetyPathError):
        _evaluate(_gate(), proposed=0.01, predicted=0.01, current=bad)


def test_a_dimension_mismatch_fails_closed() -> None:
    # Scoring a two-channel command against a one-channel effectiveness row
    # produces a plausible number for the wrong vehicle.
    two_channel = ActuationSpace(
        (
            ActuationChannel(name="throttle", lower=0.0, upper=1.0, unit="1"),
            ActuationChannel(name="steer", lower=-1.0, upper=1.0, unit="rad"),
        )
    )
    proposal = ProposedCommand(
        tick=TickId(1),
        proposed_at=AT,
        command=ControlCommand(space=two_channel, values=(0.2, 0.1)),
        origin=CommandOrigin.PROPOSED,
        source=ComponentId(LayerId.L4_CORE_A_CMDP),
    )

    with pytest.raises(SafetyPathError, match="channel"):
        _gate().evaluate(
            tick=TickId(1),
            proposal=proposal,
            prediction=_prediction(0.1),
            state=_state(0.0),
        )


def test_the_gate_holds_no_state_between_ticks() -> None:
    # A gate that accumulated state could be walked into a permissive mode by a
    # crafted sequence, so the same inputs must always give the same verdict.
    gate = _gate()
    first = _evaluate(gate, proposed=0.5, predicted=0.5, current=0.0)
    for _ in range(20):
        _evaluate(gate, proposed=0.01, predicted=0.01, current=0.8)
    last = _evaluate(gate, proposed=0.5, predicted=0.5, current=0.0)

    assert first.verdict is last.verdict
    assert first.evidence == last.evidence
