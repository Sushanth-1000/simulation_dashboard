"""The automotive adapter's command projector.

This is one of exactly two places in the repository that says anything about
vehicles -- which channel drives, which brakes, which steers, and how much
lateral acceleration a unit of steering produces. The layers are kept ignorant
of all four so that NFR5's domain-independence claim survives, and the cost of
that is that everything platform-specific concentrates *here*.

It went untested until 6 August 2026. Added with ADR-0017 and exercised only
through a stub in the arbiter's tests, so the arithmetic that turns a target
lateral acceleration into a steering command, and a speed cap into a braking
command, ran in production and nowhere else.
"""

from __future__ import annotations

import math

import pytest

from astra.kernel.errors import ConfigurationError
from astra.ports.pipeline import CommandProjector
from astra.runtime.assembly import (
    BRAKE_INDEX,
    STEER_INDEX,
    THROTTLE_INDEX,
    AutomotiveCommandProjector,
    automotive_actuation_space,
)

EFFECTIVENESS = 140.0
NOMINAL = (0.6, 0.2, 0.05)


def _projector(effectiveness: float = EFFECTIVENESS) -> AutomotiveCommandProjector:
    return AutomotiveCommandProjector(steering_index=STEER_INDEX, effectiveness=effectiveness)


def test_the_projector_satisfies_its_port() -> None:
    assert isinstance(_projector(), CommandProjector)


# --------------------------------------------------------------------------- #
# Lateral acceleration -> steering (ADR-0017's rate limiter depends on this)
# --------------------------------------------------------------------------- #


def test_a_target_becomes_the_steer_that_produces_it() -> None:
    # The inverse of `B . pi = a_lat`, the same relation the twin and L7b use.
    result = _projector().with_lateral_acceleration(NOMINAL, 2.8)

    assert result[STEER_INDEX] == pytest.approx(2.8 / EFFECTIVENESS)


def test_the_round_trip_returns_the_target() -> None:
    # If this ever stops holding, L9 rate-limits toward a value L7b would not
    # recognise, and the two would disagree about what was issued.
    for target in (-3.0, -0.4, 0.0, 0.4, 3.0):
        result = _projector().with_lateral_acceleration(NOMINAL, target)

        assert result[STEER_INDEX] * EFFECTIVENESS == pytest.approx(target)


def test_only_the_steering_channel_moves() -> None:
    # Rate limiting adjusts the vehicle's path. It must not quietly become a
    # longitudinal intervention as well.
    result = _projector().with_lateral_acceleration(NOMINAL, 2.8)

    assert result[THROTTLE_INDEX] == pytest.approx(NOMINAL[THROTTLE_INDEX])
    assert result[BRAKE_INDEX] == pytest.approx(NOMINAL[BRAKE_INDEX])


def test_a_zero_effectiveness_is_refused_at_construction() -> None:
    # It would make every lateral target unreachable and the division undefined.
    # Returning the input instead would leave a rate limiter that never limits.
    with pytest.raises(ConfigurationError, match="finite and non-zero"):
        _projector(effectiveness=0.0)


@pytest.mark.parametrize("effectiveness", [math.nan, math.inf, -math.inf])
def test_a_non_finite_effectiveness_is_refused(effectiveness: float) -> None:
    with pytest.raises(ConfigurationError):
        _projector(effectiveness=effectiveness)


# --------------------------------------------------------------------------- #
# Speed cap -> propulsion and braking
# --------------------------------------------------------------------------- #


def test_below_the_cap_the_command_is_untouched() -> None:
    # A cap is a ceiling, not a target. A projector that also accelerated toward
    # it would turn a fail-safe posture into a controller.
    result = _projector().with_speed_cap(NOMINAL, current_speed=10.0, cap=20.0)

    assert result == pytest.approx(NOMINAL)


def test_above_the_cap_propulsion_is_withdrawn_and_the_brake_goes_on() -> None:
    result = _projector().with_speed_cap(NOMINAL, current_speed=25.0, cap=20.0)

    assert result[THROTTLE_INDEX] == pytest.approx(0.0)
    assert result[BRAKE_INDEX] == pytest.approx(1.0)


def test_the_cap_brakes_rather_than_merely_coasting() -> None:
    # THE property, and the reason withdrawing throttle is not enough. HALT's
    # cap is 0.0 m/s -- a commanded stop. On a platform without drag a vehicle
    # that merely stops accelerating never stops at all, and a 100,000-tick run
    # held 17.2 m/s in HALT for exactly that reason.
    result = _projector().with_speed_cap(NOMINAL, current_speed=17.2, cap=0.0)

    assert result[BRAKE_INDEX] == pytest.approx(1.0)


def test_the_cap_leaves_steering_alone() -> None:
    # Capping speed must not straighten the wheel. The vehicle is slowing, not
    # abandoning the path it was on.
    result = _projector().with_speed_cap(NOMINAL, current_speed=25.0, cap=20.0)

    assert result[STEER_INDEX] == pytest.approx(NOMINAL[STEER_INDEX])


def test_exactly_at_the_cap_is_within_it() -> None:
    # `<=`, so sitting on the ceiling is not a breach. An off-by-one here brakes
    # a vehicle that is obeying the cap precisely.
    result = _projector().with_speed_cap(NOMINAL, current_speed=20.0, cap=20.0)

    assert result == pytest.approx(NOMINAL)


def test_the_capped_command_is_admissible_in_the_automotive_space() -> None:
    # The projector is not required to clamp -- the caller owns admissibility --
    # but a result outside the space would make every capped tick a contract
    # violation at construction, so this pins that it does not happen.
    result = _projector().with_speed_cap(NOMINAL, current_speed=25.0, cap=20.0)

    assert automotive_actuation_space().contains(result)
