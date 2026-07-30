"""Unit policy: SI internally, conversion only at the boundary."""

from __future__ import annotations

import math

import pytest

from astra.kernel.units import (
    STANDARD_GRAVITY,
    Degrees,
    Dimensionless,
    Hertz,
    Kilograms,
    KilometresPerHour,
    Metres,
    MetresPerSecond,
    MetresPerSecondSquared,
    Milliseconds,
    Probability,
    Radians,
    RadiansPerSecond,
    Seconds,
    degrees_to_radians,
    kmh_to_mps,
    mps_to_kmh,
    ms_to_seconds,
    radians_to_degrees,
    seconds_to_ms,
)

# --------------------------------------------------------------------------- #
# NewType aliases are erased at runtime
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "alias",
    [
        Seconds,
        Metres,
        Kilograms,
        MetresPerSecond,
        MetresPerSecondSquared,
        Radians,
        RadiansPerSecond,
        Hertz,
        KilometresPerHour,
        Degrees,
        Milliseconds,
        Probability,
        Dimensionless,
    ],
)
def test_every_unit_alias_is_erased_to_a_plain_float_at_runtime(alias: object) -> None:
    constructed = alias(3.25)  # type: ignore[operator]
    assert constructed == 3.25
    assert type(constructed) is float


def test_unit_aliases_are_distinct_objects_so_mypy_can_tell_them_apart() -> None:
    aliases = [Metres, MetresPerSecond, Radians, Degrees, Probability, Dimensionless]
    assert len({id(alias) for alias in aliases}) == len(aliases)
    assert len({alias.__name__ for alias in aliases}) == len(aliases)


# --------------------------------------------------------------------------- #
# Speed
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("kmh", "mps"),
    [
        (0.0, 0.0),
        (3.6, 1.0),
        (36.0, 10.0),
        (20.0, 5.555555555555555),
        (60.0, 16.666666666666668),
        (-18.0, -5.0),
    ],
)
def test_kmh_to_mps_uses_the_exact_si_definition(kmh: float, mps: float) -> None:
    assert kmh_to_mps(KilometresPerHour(kmh)) == pytest.approx(mps)


@pytest.mark.parametrize(
    ("mps", "kmh"),
    [
        (0.0, 0.0),
        (1.0, 3.6),
        (10.0, 36.0),
        (-5.0, -18.0),
    ],
)
def test_mps_to_kmh_uses_the_exact_si_definition(mps: float, kmh: float) -> None:
    assert mps_to_kmh(MetresPerSecond(mps)) == pytest.approx(kmh)


@pytest.mark.parametrize("kmh", [0.0, 20.0, 60.0, 130.0, -12.5])
def test_speed_conversion_round_trips_within_floating_point_tolerance(kmh: float) -> None:
    recovered = mps_to_kmh(kmh_to_mps(KilometresPerHour(kmh)))
    assert recovered == pytest.approx(kmh)


def test_the_fsm_limp_cap_of_twenty_kmh_is_five_and_five_ninths_mps() -> None:
    assert kmh_to_mps(KilometresPerHour(20.0)) == pytest.approx(20.0 / 3.6)


# --------------------------------------------------------------------------- #
# Angle
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("degrees", "radians"),
    [
        (0.0, 0.0),
        (90.0, math.pi / 2),
        (180.0, math.pi),
        (-15.0, -math.pi / 12),
        (15.0, math.pi / 12),
    ],
)
def test_degrees_to_radians_matches_the_mathematical_definition(
    degrees: float, radians: float
) -> None:
    assert degrees_to_radians(Degrees(degrees)) == pytest.approx(radians)


@pytest.mark.parametrize(
    ("radians", "degrees"),
    [
        (0.0, 0.0),
        (math.pi, 180.0),
        (math.pi / 4, 45.0),
        (-math.pi / 2, -90.0),
    ],
)
def test_radians_to_degrees_matches_the_mathematical_definition(
    radians: float, degrees: float
) -> None:
    assert radians_to_degrees(Radians(radians)) == pytest.approx(degrees)


@pytest.mark.parametrize("degrees", [0.0, 15.0, -15.0, 33.75, 359.5])
def test_angle_conversion_round_trips_within_floating_point_tolerance(degrees: float) -> None:
    assert radians_to_degrees(degrees_to_radians(Degrees(degrees))) == pytest.approx(degrees)


def test_the_safe_exploration_steering_limit_of_fifteen_degrees_is_a_quarter_radian_or_less() -> (
    None
):
    assert degrees_to_radians(Degrees(15.0)) < 0.27


# --------------------------------------------------------------------------- #
# Duration
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("milliseconds", "seconds"),
    [
        (0.0, 0.0),
        (50.0, 0.05),
        (1000.0, 1.0),
        (-250.0, -0.25),
    ],
)
def test_ms_to_seconds_divides_by_exactly_one_thousand(milliseconds: float, seconds: float) -> None:
    assert ms_to_seconds(Milliseconds(milliseconds)) == pytest.approx(seconds)


@pytest.mark.parametrize(
    ("seconds", "milliseconds"),
    [
        (0.0, 0.0),
        (0.05, 50.0),
        (1.0, 1000.0),
        (-0.25, -250.0),
    ],
)
def test_seconds_to_ms_multiplies_by_exactly_one_thousand(
    seconds: float, milliseconds: float
) -> None:
    assert seconds_to_ms(Seconds(seconds)) == pytest.approx(milliseconds)


@pytest.mark.parametrize("milliseconds", [0.0, 10.0, 50.0, 1234.5])
def test_duration_conversion_round_trips_within_floating_point_tolerance(
    milliseconds: float,
) -> None:
    recovered = seconds_to_ms(ms_to_seconds(Milliseconds(milliseconds)))
    assert recovered == pytest.approx(milliseconds)


def test_the_fifty_millisecond_staleness_budget_is_fifty_thousandths_of_a_second() -> None:
    assert ms_to_seconds(Milliseconds(50.0)) == pytest.approx(0.05)


# --------------------------------------------------------------------------- #
# Physical constants
# --------------------------------------------------------------------------- #


def test_standard_gravity_is_the_cgpm_defined_value() -> None:
    assert STANDARD_GRAVITY == 9.80665


def test_standard_gravity_is_a_plain_float_usable_in_arithmetic() -> None:
    assert type(STANDARD_GRAVITY) is float
    assert pytest.approx(6.864655) == 0.7 * STANDARD_GRAVITY


def test_standard_gravity_is_finite_and_positive_so_the_friction_bound_is_meaningful() -> None:
    assert math.isfinite(STANDARD_GRAVITY)
    assert STANDARD_GRAVITY > 0.0
