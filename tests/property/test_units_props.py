"""Properties of the boundary unit conversions.

The conversions are the only place a non-SI value becomes an SI one. A defect
here is silent and systemic, so they are exercised over the whole finite range
that can physically occur rather than at a handful of chosen points.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from astra.kernel.units import (
    Degrees,
    KilometresPerHour,
    MetresPerSecond,
    Milliseconds,
    Radians,
    Seconds,
    degrees_to_radians,
    kmh_to_mps,
    mps_to_kmh,
    ms_to_seconds,
    radians_to_degrees,
    seconds_to_ms,
)

pytestmark = pytest.mark.property

# Hypothesis' deadline is a latency assertion, and a shared CI runner is not a
# latency measurement instrument. Timing is asserted in the Phase 6 latency
# suite against a real budget, not incidentally here.
_SETTINGS = settings(deadline=None, max_examples=200)

_RELATIVE_TOLERANCE = 1e-9


def _magnitudes(*, largest: float, smallest: float = 1e-6) -> st.SearchStrategy[float]:
    """Return finite floats in ``+-[smallest, largest]``, plus exact zero.

    Values below ``smallest`` are excluded deliberately rather than by
    ``assume``: a round trip through a division and a multiplication near the
    subnormal boundary loses bits for reasons that have nothing to do with the
    conversion being correct.

    Args:
        largest: The largest permitted magnitude.
        smallest: The smallest permitted non-zero magnitude.

    Returns:
        A strategy over signed finite floats and zero.
    """
    positive = st.floats(
        min_value=smallest,
        max_value=largest,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    )
    return st.one_of(st.just(0.0), positive, positive.map(lambda value: -value))


_SPEEDS_KMH = _magnitudes(largest=1e6)
_SPEEDS_MPS = _magnitudes(largest=1e6)
_ANGLES_DEGREES = _magnitudes(largest=1e6)
_ANGLES_RADIANS = _magnitudes(largest=1e6)
_DURATIONS_MS = _magnitudes(largest=1e9)
_DURATIONS_SECONDS = _magnitudes(largest=1e9)


def _sign(value: float) -> int:
    """Return ``-1``, ``0`` or ``1`` for a finite value.

    Args:
        value: The value to classify.

    Returns:
        The sign as an integer.
    """
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


# --------------------------------------------------------------------------- #
# Round trips
# --------------------------------------------------------------------------- #


@_SETTINGS
@given(value=_SPEEDS_KMH)
def test_kilometres_per_hour_survive_a_round_trip_through_metres_per_second(
    value: float,
) -> None:
    restored = mps_to_kmh(kmh_to_mps(KilometresPerHour(value)))
    assert math.isclose(restored, value, rel_tol=_RELATIVE_TOLERANCE, abs_tol=0.0)


@_SETTINGS
@given(value=_SPEEDS_MPS)
def test_metres_per_second_survive_a_round_trip_through_kilometres_per_hour(
    value: float,
) -> None:
    restored = kmh_to_mps(mps_to_kmh(MetresPerSecond(value)))
    assert restored == pytest.approx(value, rel=_RELATIVE_TOLERANCE, abs=0.0)


@_SETTINGS
@given(value=_ANGLES_DEGREES)
def test_degrees_survive_a_round_trip_through_radians(value: float) -> None:
    restored = radians_to_degrees(degrees_to_radians(Degrees(value)))
    assert math.isclose(restored, value, rel_tol=_RELATIVE_TOLERANCE, abs_tol=0.0)


@_SETTINGS
@given(value=_ANGLES_RADIANS)
def test_radians_survive_a_round_trip_through_degrees(value: float) -> None:
    restored = degrees_to_radians(radians_to_degrees(Radians(value)))
    assert restored == pytest.approx(value, rel=_RELATIVE_TOLERANCE, abs=0.0)


@_SETTINGS
@given(value=_DURATIONS_MS)
def test_milliseconds_survive_a_round_trip_through_seconds(value: float) -> None:
    restored = seconds_to_ms(ms_to_seconds(Milliseconds(value)))
    assert math.isclose(restored, value, rel_tol=_RELATIVE_TOLERANCE, abs_tol=0.0)


@_SETTINGS
@given(value=_DURATIONS_SECONDS)
def test_seconds_survive_a_round_trip_through_milliseconds(value: float) -> None:
    restored = ms_to_seconds(seconds_to_ms(Seconds(value)))
    assert restored == pytest.approx(value, rel=_RELATIVE_TOLERANCE, abs=0.0)


# --------------------------------------------------------------------------- #
# Monotonicity
# --------------------------------------------------------------------------- #


@_SETTINGS
@given(first=_SPEEDS_KMH, second=_SPEEDS_KMH)
def test_converting_speed_to_metres_per_second_preserves_order(first: float, second: float) -> None:
    if first <= second:
        assert kmh_to_mps(KilometresPerHour(first)) <= kmh_to_mps(KilometresPerHour(second))
    else:
        assert kmh_to_mps(KilometresPerHour(first)) >= kmh_to_mps(KilometresPerHour(second))


@_SETTINGS
@given(first=_ANGLES_DEGREES, second=_ANGLES_DEGREES)
def test_converting_degrees_to_radians_preserves_order(first: float, second: float) -> None:
    if first <= second:
        assert degrees_to_radians(Degrees(first)) <= degrees_to_radians(Degrees(second))
    else:
        assert degrees_to_radians(Degrees(first)) >= degrees_to_radians(Degrees(second))


@_SETTINGS
@given(first=_DURATIONS_MS, second=_DURATIONS_MS)
def test_converting_milliseconds_to_seconds_preserves_order(first: float, second: float) -> None:
    if first <= second:
        assert ms_to_seconds(Milliseconds(first)) <= ms_to_seconds(Milliseconds(second))
    else:
        assert ms_to_seconds(Milliseconds(first)) >= ms_to_seconds(Milliseconds(second))


# --------------------------------------------------------------------------- #
# Sign preservation
# --------------------------------------------------------------------------- #


@_SETTINGS
@given(value=_SPEEDS_KMH)
def test_speed_conversion_never_changes_the_direction_of_travel(value: float) -> None:
    assert _sign(kmh_to_mps(KilometresPerHour(value))) == _sign(value)
    assert _sign(mps_to_kmh(MetresPerSecond(value))) == _sign(value)


@_SETTINGS
@given(value=_ANGLES_DEGREES)
def test_angle_conversion_never_changes_the_direction_of_rotation(value: float) -> None:
    assert _sign(degrees_to_radians(Degrees(value))) == _sign(value)
    assert _sign(radians_to_degrees(Radians(value))) == _sign(value)


@_SETTINGS
@given(value=_DURATIONS_MS)
def test_duration_conversion_never_changes_the_sign_of_an_interval(value: float) -> None:
    assert _sign(ms_to_seconds(Milliseconds(value))) == _sign(value)
    assert _sign(seconds_to_ms(Seconds(value))) == _sign(value)


# --------------------------------------------------------------------------- #
# Scale
# --------------------------------------------------------------------------- #


@_SETTINGS
@given(value=_SPEEDS_KMH)
def test_a_speed_in_metres_per_second_is_never_larger_in_magnitude_than_in_kmh(
    value: float,
) -> None:
    assert abs(kmh_to_mps(KilometresPerHour(value))) <= abs(value)


@_SETTINGS
@given(value=_DURATIONS_MS)
def test_a_duration_in_seconds_is_never_larger_in_magnitude_than_in_milliseconds(
    value: float,
) -> None:
    assert abs(ms_to_seconds(Milliseconds(value))) <= abs(value)
