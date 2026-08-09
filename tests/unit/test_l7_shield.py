"""Unit tests for the L7a Hard Safety Shield."""

from __future__ import annotations

import inspect
import math

import pytest

from astra.config.schema import ShieldSettings
from astra.contracts.actuation import (
    ActuationChannel,
    ActuationSpace,
    CommandOrigin,
    ControlCommand,
    ProposedCommand,
)
from astra.contracts.assurance import GateVerdict, SafetyVerdict
from astra.contracts.estimation import FastStateEstimate, SlowStateEstimate
from astra.kernel.enums import GateId, LayerId, Verdict
from astra.kernel.errors import SafetyDisposition, SafetyPathError
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, Timeline
from astra.kernel.units import STANDARD_GRAVITY
from astra.layers.l7_shield.shield import (
    REASON_CODES,
    REASON_CORRIDOR_DEPARTURE,
    REASON_LATERAL_ACCELERATION,
    REASON_LEGAL_SPEED,
    REASON_NOMINAL,
    REASON_STOPPING_DISTANCE,
    HardSafetyShield,
)
from astra.ports.pipeline import DeterministicShield

# The operating point is stated here rather than loaded, so the test asserts
# against bounds it declares rather than against whatever a safety engineer has
# most recently tuned.
LEGAL_SPEED_KMH = 120.0
LEGAL_SPEED_MPS = LEGAL_SPEED_KMH * 1000.0 / 3600.0
FRICTION_MARGIN = 0.8
MINIMUM_STOPPING_DISTANCE = 5.0
ASSURED_CLEAR_DISTANCE = 150.0

CORRIDOR_HALF_WIDTH = 1.75

DRY = 0.85
WET = 0.35
ICE = 0.15

SETTINGS = ShieldSettings(
    legal_speed_limit_kmh=LEGAL_SPEED_KMH,
    friction_margin=FRICTION_MARGIN,
    minimum_stopping_distance_m=MINIMUM_STOPPING_DISTANCE,
    assured_clear_distance_m=ASSURED_CLEAR_DISTANCE,
    lateral_corridor_half_width_m=CORRIDOR_HALF_WIDTH,
)

FAST_COVARIANCE = SymmetricMatrix.from_diagonal([1.0, 1.0, 0.25, 0.1, 0.5])
SLOW_COVARIANCE = SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01])


def _friction_limit(friction: float) -> float:
    return FRICTION_MARGIN * friction * STANDARD_GRAVITY


def _stopping_distance(speed: float, friction: float) -> float:
    return MINIMUM_STOPPING_DISTANCE + (speed * speed) / (
        2.0 * FRICTION_MARGIN * friction * STANDARD_GRAVITY
    )


def _state(
    speed: float, lateral_acceleration: float, lateral_offset: float = 0.0
) -> FastStateEstimate:
    return FastStateEstimate(
        tick=TickId(0),
        valid_at=Instant(0, Timeline.MANUAL),
        mean=(0.0, lateral_offset, speed, 0.0, lateral_acceleration),
        covariance=FAST_COVARIANCE,
    )


def _degradation(friction: float) -> SlowStateEstimate:
    return SlowStateEstimate(
        tick=TickId(0),
        valid_at=Instant(0, Timeline.MANUAL),
        mean=(friction, 0.0, 1.0),
        covariance=SLOW_COVARIANCE,
    )


def _proposal() -> ProposedCommand:
    space = ActuationSpace((ActuationChannel("throttle", 0.0, 1.0, "1"),))
    return ProposedCommand(
        tick=TickId(0),
        proposed_at=Instant(0, Timeline.MANUAL),
        command=ControlCommand(space, (0.5,)),
        origin=CommandOrigin.PROPOSED,
        source=ComponentId(LayerId.L4_CORE_A_CMDP),
    )


def _evaluate(speed: float, lateral_acceleration: float, friction: float) -> GateVerdict:
    return _evaluate_state(_state(speed, lateral_acceleration), friction)


def _evaluate_state(state: FastStateEstimate, friction: float) -> GateVerdict:
    """Evaluate a fully-built state.

    For bounds that read state fields the scalar helper does not expose.
    """
    return HardSafetyShield(SETTINGS).evaluate(
        tick=TickId(0),
        proposal=_proposal(),
        state=state,
        degradation=_degradation(friction),
    )


# --------------------------------------------------------------------------- #
# Bound 1: tyre friction
# --------------------------------------------------------------------------- #


def test_lateral_acceleration_within_the_friction_limit_passes() -> None:
    verdict = _evaluate(20.0, _friction_limit(DRY) * 0.5, DRY)

    assert verdict.verdict is Verdict.PASS
    assert verdict.reason_code == REASON_NOMINAL


def test_lateral_acceleration_above_the_friction_limit_is_vetoed() -> None:
    verdict = _evaluate(20.0, _friction_limit(DRY) * 1.01, DRY)

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_LATERAL_ACCELERATION


def test_the_friction_bound_is_on_the_absolute_value() -> None:
    # Cornering the other way is equally a slide. A signed comparison would let
    # a hard right-hand turn through while vetoing the identical left-hander.
    verdict = _evaluate(20.0, -_friction_limit(DRY) * 1.5, DRY)

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_LATERAL_ACCELERATION


def test_the_same_lateral_acceleration_passes_on_tarmac_and_vetoes_on_ice() -> None:
    # The adaptive-friction property, and the reason the bound reads the slow
    # filter rather than a constant. A shield with a hard-coded mu passes both.
    lateral_acceleration = _friction_limit(ICE) * 2.0

    on_ice = _evaluate(20.0, lateral_acceleration, ICE)
    on_tarmac = _evaluate(20.0, lateral_acceleration, DRY)

    assert on_ice.verdict is Verdict.VETO
    assert on_tarmac.verdict is Verdict.PASS


@pytest.mark.parametrize("friction", [ICE, WET, DRY])
def test_the_friction_bound_is_inclusive_at_the_limit(friction: float) -> None:
    # The comparison is `>`, so exactly at the limit is admissible. Scaled down
    # by one ulp-ish factor to survive the float round-trip through the record.
    at_limit = _friction_limit(friction) * (1.0 - 1e-12)

    assert _evaluate(10.0, at_limit, friction).verdict is Verdict.PASS


# --------------------------------------------------------------------------- #
# Bound 2: stopping distance
# --------------------------------------------------------------------------- #


def test_a_stopping_distance_inside_the_assured_clear_distance_passes() -> None:
    assert _stopping_distance(20.0, DRY) < ASSURED_CLEAR_DISTANCE

    assert _evaluate(20.0, 0.0, DRY).verdict is Verdict.PASS


def test_a_stopping_distance_beyond_the_assured_clear_distance_is_vetoed() -> None:
    # Lawful speed, wet road: the vehicle cannot stop inside the distance its
    # ODD assures. This is why the bound is not a restatement of the speed limit.
    speed = 32.0
    assert speed < LEGAL_SPEED_MPS
    assert _stopping_distance(speed, WET) > ASSURED_CLEAR_DISTANCE

    verdict = _evaluate(speed, 0.0, WET)

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_STOPPING_DISTANCE


def test_the_stopping_distance_bound_is_adaptive_in_friction() -> None:
    speed = 30.0

    on_tarmac = _evaluate(speed, 0.0, DRY)
    on_ice = _evaluate(speed, 0.0, ICE)

    assert on_tarmac.verdict is Verdict.PASS
    assert on_ice.verdict is Verdict.VETO
    assert on_ice.reason_code == REASON_STOPPING_DISTANCE


def test_the_stopping_distance_matches_the_hand_computed_formula() -> None:
    # A cross-check against a value computed independently of the source, so the
    # test cannot pass by restating the implementation.
    speed = 25.0
    friction = 0.5
    expected = 5.0 + (25.0 * 25.0) / (2.0 * 0.8 * 0.5 * 9.80665)

    evidence = _evaluate(speed, 0.0, friction).evidence_map()

    assert evidence["stopping_distance_m"] == pytest.approx(expected, rel=1e-12)
    assert evidence["stopping_distance_m"] == pytest.approx(84.6, abs=0.1)


# --------------------------------------------------------------------------- #
# Bound 3: legal speed
# --------------------------------------------------------------------------- #


def test_speed_at_the_legal_limit_passes() -> None:
    verdict = _evaluate(LEGAL_SPEED_MPS * (1.0 - 1e-12), 0.0, DRY)

    assert verdict.verdict is Verdict.PASS


def test_speed_above_the_legal_limit_is_vetoed() -> None:
    # Chosen so the stopping-distance bound is comfortably satisfied and the
    # legal bound is the one that fires.
    verdict = _evaluate(LEGAL_SPEED_MPS * 1.05, 0.0, DRY)

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_LEGAL_SPEED


# --------------------------------------------------------------------------- #
# Verdict shape
# --------------------------------------------------------------------------- #

_EXPECTED_EVIDENCE_KEYS = frozenset(
    {
        "speed_mps",
        "lateral_acceleration_mps2",
        "friction_limit_mps2",
        "road_friction",
        "stopping_distance_m",
        "assured_clear_distance_m",
        "legal_speed_mps",
        "lateral_offset_m",
        "lateral_corridor_half_width_m",
    }
)


@pytest.mark.parametrize(
    ("speed", "lateral_acceleration", "friction"),
    [
        (20.0, 1.0, DRY),  # PASS
        (20.0, 50.0, DRY),  # friction VETO
        (32.0, 0.0, WET),  # stopping-distance VETO
        (LEGAL_SPEED_MPS * 1.05, 0.0, DRY),  # legal-speed VETO
    ],
)
def test_every_verdict_carries_the_full_evidence_set(
    speed: float, lateral_acceleration: float, friction: float
) -> None:
    # Evidence on a PASS too: an analyst needs the margin the vehicle actually
    # had, not merely that it was inside the limit.
    verdict = _evaluate(speed, lateral_acceleration, friction)

    assert set(verdict.evidence_map()) == _EXPECTED_EVIDENCE_KEYS
    assert all(math.isfinite(value) for _, value in verdict.evidence)


@pytest.mark.parametrize(
    ("speed", "lateral_acceleration", "friction"),
    [(20.0, 1.0, DRY), (20.0, 50.0, DRY), (32.0, 0.0, WET)],
)
def test_every_verdict_is_tagged_as_the_deterministic_gate(
    speed: float, lateral_acceleration: float, friction: float
) -> None:
    verdict = _evaluate(speed, lateral_acceleration, friction)

    assert verdict.gate is GateId.DETERMINISTIC
    assert verdict.reason_code in REASON_CODES


# --------------------------------------------------------------------------- #
# Fail-closed on a non-finite state
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["speed", "lateral_acceleration", "friction"])
def test_a_non_finite_state_fails_closed_rather_than_passing(field: str, bad: float) -> None:
    # NaN defeats every comparison rather than failing it: `nan > limit` is
    # False, so a NaN state would satisfy all three bounds and PASS.
    speed = bad if field == "speed" else 20.0
    lateral_acceleration = bad if field == "lateral_acceleration" else 1.0
    friction = bad if field == "friction" else DRY

    with pytest.raises(SafetyPathError) as raised:
        _evaluate(speed, lateral_acceleration, friction)

    assert raised.value.disposition is SafetyDisposition.FAIL_CLOSED


def test_the_non_finite_error_names_the_offending_field() -> None:
    with pytest.raises(SafetyPathError) as raised:
        _evaluate(float("nan"), 1.0, DRY)

    assert "speed" in raised.value.context["fields"]
    assert raised.value.layer is LayerId.L7_HARD_SAFETY_SHIELD


# --------------------------------------------------------------------------- #
# Degenerate friction
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("friction", [0.0, 1e-9])
def test_effectively_zero_friction_vetoes_with_a_finite_stopping_distance(
    friction: float,
) -> None:
    # Dividing by the raw friction would overflow. The floor makes the veto an
    # explicit decision and keeps the evidence readable.
    verdict = _evaluate(20.0, 0.0, friction)

    assert verdict.verdict is Verdict.VETO
    assert math.isfinite(verdict.evidence_map()["stopping_distance_m"])


def test_zero_friction_with_zero_speed_still_reports_finite_evidence() -> None:
    verdict = _evaluate(0.0, 0.0, 0.0)

    assert all(math.isfinite(value) for _, value in verdict.evidence)


# --------------------------------------------------------------------------- #
# Independence -- the architectural point
# --------------------------------------------------------------------------- #


def test_evaluate_offers_no_parameter_for_another_gates_evidence() -> None:
    # The signature is the enforcement. There is no parameter through which a
    # twin prediction, a conformal score, a Trust Index or an FSM state could
    # arrive, so the shield cannot inherit another gate's failure mode.
    parameters = set(inspect.signature(HardSafetyShield.evaluate).parameters) - {"self"}

    assert parameters == {"tick", "proposal", "state", "degradation"}


def test_the_shield_holds_no_state_between_evaluations() -> None:
    # A shield that accumulated state could be driven into a permissive mode by
    # a sequence of inputs, and its verdict would stop being a pure function of
    # what it was given.
    shield = HardSafetyShield(SETTINGS)
    unsafe = _state(20.0, 50.0)
    safe = _state(20.0, 1.0)
    dry = _degradation(DRY)

    first = shield.evaluate(tick=TickId(0), proposal=_proposal(), state=unsafe, degradation=dry)
    between = shield.evaluate(tick=TickId(1), proposal=_proposal(), state=safe, degradation=dry)
    again = shield.evaluate(tick=TickId(2), proposal=_proposal(), state=unsafe, degradation=dry)

    assert first.verdict is Verdict.VETO
    assert between.verdict is Verdict.PASS
    assert again.verdict is Verdict.VETO


def test_evaluating_the_same_inputs_twice_gives_equal_verdicts() -> None:
    shield = HardSafetyShield(SETTINGS)
    proposal = _proposal()
    state = _state(20.0, 1.0)
    degradation = _degradation(DRY)

    first = shield.evaluate(tick=TickId(0), proposal=proposal, state=state, degradation=degradation)
    second = shield.evaluate(
        tick=TickId(0), proposal=proposal, state=state, degradation=degradation
    )

    assert first == second


def test_the_shield_satisfies_the_deterministic_shield_port() -> None:
    assert isinstance(HardSafetyShield(SETTINGS), DeterministicShield)


# --------------------------------------------------------------------------- #
# SI-3 -- no PASS can suppress the shield's VETO
# --------------------------------------------------------------------------- #


def _passes(count: int) -> tuple[GateVerdict, ...]:
    gates = (GateId.STATISTICAL, GateId.PHYSICAL)
    return tuple(
        GateVerdict(TickId(0), gates[index], Verdict.PASS, REASON_NOMINAL) for index in range(count)
    )


def test_a_shield_veto_survives_passes_from_both_other_gates() -> None:
    shield_veto = _evaluate(20.0, 50.0, DRY)
    assert shield_veto.verdict is Verdict.VETO

    combined = SafetyVerdict(TickId(0), (*_passes(2), shield_veto))

    assert combined.aggregate is Verdict.VETO
    assert combined.vetoing_gates == (GateId.DETERMINISTIC,)


@pytest.mark.parametrize("pass_count", [0, 1, 2])
def test_no_number_of_passes_changes_the_aggregate(pass_count: int) -> None:
    shield_veto = _evaluate(20.0, 50.0, DRY)

    combined = SafetyVerdict(TickId(0), (*_passes(pass_count), shield_veto))

    assert combined.aggregate is Verdict.VETO


def test_the_aggregate_does_not_depend_on_verdict_order() -> None:
    shield_veto = _evaluate(20.0, 50.0, DRY)
    passes = _passes(2)

    forward = SafetyVerdict(TickId(0), (*passes, shield_veto))
    backward = SafetyVerdict(TickId(0), (shield_veto, *reversed(passes)))

    assert forward.aggregate is backward.aggregate is Verdict.VETO
    assert forward.vetoing_gates == backward.vetoing_gates


# --------------------------------------------------------------------------- #
# The lateral corridor -- the hazard the other three bounds could not see
# --------------------------------------------------------------------------- #


def test_a_vehicle_outside_its_corridor_is_vetoed() -> None:
    # THE test this gate existed without. On 5 August a 100,000-tick run put the
    # vehicle 2.9 km outside a corridor 1.75 m wide with a 0.00% veto rate and a
    # Trust Index of exactly 1.00. Nothing in Core-B measured where the vehicle
    # was: this gate bounded speed, lateral acceleration and stopping distance;
    # L7b bounds jerk and divergence from the twin; L6 scores the proposal
    # against the twin. The hazard that actually occurred was outside the union
    # of what all three checked.
    verdict = _evaluate_state(
        _state(speed=13.0, lateral_acceleration=0.0, lateral_offset=CORRIDOR_HALF_WIDTH + 0.5),
        DRY,
    )

    assert verdict.verdict is Verdict.VETO
    assert verdict.reason_code == REASON_CORRIDOR_DEPARTURE


def test_the_corridor_bound_is_symmetric() -> None:
    for offset in (CORRIDOR_HALF_WIDTH + 0.5, -CORRIDOR_HALF_WIDTH - 0.5):
        verdict = _evaluate_state(
            _state(speed=13.0, lateral_acceleration=0.0, lateral_offset=offset), DRY
        )
        assert verdict.reason_code == REASON_CORRIDOR_DEPARTURE


def test_a_vehicle_inside_its_corridor_passes() -> None:
    # The control. A bound that vetoed everywhere would also satisfy the test
    # above, and would stop the vehicle for driving normally.
    verdict = _evaluate_state(
        _state(speed=13.0, lateral_acceleration=0.0, lateral_offset=CORRIDOR_HALF_WIDTH - 0.01),
        DRY,
    )

    assert verdict.verdict is Verdict.PASS


def test_the_corridor_edge_itself_is_admissible() -> None:
    # `>` not `>=`: sitting exactly on the boundary is inside it. Stated because
    # an off-by-one here is a gate that vetoes a vehicle doing nothing wrong.
    verdict = _evaluate_state(
        _state(speed=13.0, lateral_acceleration=0.0, lateral_offset=CORRIDOR_HALF_WIDTH), DRY
    )

    assert verdict.verdict is Verdict.PASS


def test_a_non_finite_lateral_offset_fails_closed_like_every_other_state_field() -> None:
    # NaN defeats `abs(offset) > corridor` rather than failing it, so an
    # unchecked NaN position would silently satisfy the bound.
    with pytest.raises(SafetyPathError):
        _evaluate_state(_state(speed=13.0, lateral_acceleration=0.0, lateral_offset=math.nan), DRY)


def test_the_corridor_breach_is_reported_in_the_evidence() -> None:
    verdict = _evaluate_state(_state(speed=13.0, lateral_acceleration=0.0, lateral_offset=3.0), DRY)
    evidence = dict(verdict.evidence)

    assert evidence["lateral_offset_m"] == pytest.approx(3.0)
    assert evidence["lateral_corridor_half_width_m"] == pytest.approx(CORRIDOR_HALF_WIDTH)


def test_the_corridor_bound_reads_the_estimate_and_is_blind_to_a_wrong_one() -> None:
    # An honest limitation, pinned so it cannot be forgotten in the safety case.
    # The bound refuses a departure the *filter* knows about. On 5 August the
    # filter did not: lateral position was measured by nothing, so the estimate
    # sat at zero while the vehicle left the corridor entirely. Had this bound
    # existed then it would have passed every tick.
    #
    # Making the quantity observable is what closed that hazard. This bound adds
    # that a departure the filter can see is refused by a gate rather than
    # noticed by nobody. Neither substitutes for the other.
    believed_centred = _evaluate_state(
        _state(speed=13.0, lateral_acceleration=0.0, lateral_offset=0.0), DRY
    )

    assert believed_centred.verdict is Verdict.PASS
