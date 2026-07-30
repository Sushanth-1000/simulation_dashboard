"""Instants, clocks and the staleness rule behind FR1."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from astra.kernel.errors import ContractViolationError, NonFiniteValueError
from astra.kernel.time import (
    Clock,
    Instant,
    ManualClock,
    SystemClock,
    Timeline,
    is_stale,
    staleness,
)
from astra.kernel.units import Seconds

_NS_PER_S = 1_000_000_000
_FIFTY_MS = Seconds(0.05)

# --------------------------------------------------------------------------- #
# Instant construction
# --------------------------------------------------------------------------- #


def test_an_instant_defaults_to_the_system_monotonic_timeline() -> None:
    assert Instant(0).timeline is Timeline.SYSTEM_MONOTONIC


@pytest.mark.parametrize("nanoseconds", [1.5, "0", None, 0.0])
def test_an_instant_rejects_non_integer_nanoseconds_from_replay_data(
    nanoseconds: object,
) -> None:
    with pytest.raises(ContractViolationError):
        Instant(nanoseconds)  # type: ignore[arg-type]


@pytest.mark.parametrize("nanoseconds", [True, False])
def test_an_instant_rejects_a_bool_even_though_bool_is_a_subclass_of_int(
    nanoseconds: bool,
) -> None:
    with pytest.raises(ContractViolationError):
        Instant(nanoseconds)


def test_a_negative_nanosecond_offset_is_permitted_because_the_epoch_is_unspecified() -> None:
    assert Instant(-5, Timeline.MANUAL).nanoseconds == -5


@pytest.mark.parametrize(
    ("seconds", "nanoseconds"),
    [
        (0.0, 0),
        (1.0, _NS_PER_S),
        (0.05, 50_000_000),
        (-0.25, -250_000_000),
        (6e-10, 1),
        (4e-10, 0),
        (0.0012345, 1_234_500),
    ],
)
def test_from_seconds_rounds_to_the_nearest_nanosecond(seconds: float, nanoseconds: int) -> None:
    assert Instant.from_seconds(seconds).nanoseconds == nanoseconds


def test_from_seconds_carries_the_requested_timeline() -> None:
    assert Instant.from_seconds(1.0, Timeline.SIMULATED).timeline is Timeline.SIMULATED


def test_from_seconds_defaults_to_the_system_monotonic_timeline() -> None:
    assert Instant.from_seconds(1.0).timeline is Timeline.SYSTEM_MONOTONIC


def test_instants_are_frozen_and_hashable() -> None:
    instant = Instant(7, Timeline.MANUAL)
    assert hash(instant) == hash(Instant(7, Timeline.MANUAL))
    with pytest.raises(AttributeError):
        instant.nanoseconds = 8  # type: ignore[misc]


def test_the_same_offset_on_two_timelines_is_not_the_same_instant() -> None:
    assert Instant(5, Timeline.MANUAL) != Instant(5, Timeline.SIMULATED)


# --------------------------------------------------------------------------- #
# Instant arithmetic
# --------------------------------------------------------------------------- #


def test_elapsed_since_is_positive_when_this_instant_is_later() -> None:
    later = Instant(1_500_000_000, Timeline.MANUAL)
    earlier = Instant(500_000_000, Timeline.MANUAL)
    assert later.elapsed_since(earlier) == pytest.approx(1.0)


def test_elapsed_since_is_negative_when_this_instant_is_earlier() -> None:
    earlier = Instant(0, Timeline.MANUAL)
    later = Instant(_NS_PER_S, Timeline.MANUAL)
    assert earlier.elapsed_since(later) == pytest.approx(-1.0)


def test_elapsed_since_itself_is_zero() -> None:
    instant = Instant(1234, Timeline.MANUAL)
    assert instant.elapsed_since(instant) == 0.0


def test_elapsed_since_resolves_single_nanoseconds() -> None:
    assert Instant(1, Timeline.MANUAL).elapsed_since(Instant(0, Timeline.MANUAL)) == 1e-9


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (Timeline.MANUAL, Timeline.SYSTEM_MONOTONIC),
        (Timeline.SIMULATED, Timeline.MANUAL),
        (Timeline.SYSTEM_MONOTONIC, Timeline.SIMULATED),
    ],
)
def test_subtracting_instants_from_different_timelines_raises(
    left: Timeline, right: Timeline
) -> None:
    with pytest.raises(ContractViolationError):
        Instant(10, left).elapsed_since(Instant(0, right))


def test_a_cross_timeline_comparison_names_both_timelines_in_its_audit_context() -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        Instant(10, Timeline.SIMULATED).elapsed_since(Instant(0, Timeline.MANUAL))
    assert excinfo.value.context == {"left": "SIMULATED", "right": "MANUAL"}
    assert "SIMULATED" in excinfo.value.message


def test_plus_moves_forward_on_the_same_timeline() -> None:
    result = Instant(0, Timeline.MANUAL).plus(Seconds(0.25))
    assert result == Instant(250_000_000, Timeline.MANUAL)


def test_plus_accepts_a_negative_interval() -> None:
    result = Instant(_NS_PER_S, Timeline.MANUAL).plus(Seconds(-0.5))
    assert result.nanoseconds == 500_000_000


def test_plus_preserves_the_timeline() -> None:
    assert Instant(0, Timeline.SIMULATED).plus(Seconds(1.0)).timeline is Timeline.SIMULATED


def test_plus_does_not_mutate_the_original_instant() -> None:
    original = Instant(0, Timeline.MANUAL)
    original.plus(Seconds(1.0))
    assert original.nanoseconds == 0


def test_plus_then_elapsed_since_recovers_the_interval() -> None:
    start = Instant(0, Timeline.MANUAL)
    assert start.plus(Seconds(0.05)).elapsed_since(start) == pytest.approx(0.05)


def test_is_before_is_true_for_a_strictly_earlier_instant() -> None:
    assert Instant(0, Timeline.MANUAL).is_before(Instant(1, Timeline.MANUAL)) is True


def test_is_before_is_false_for_a_later_instant() -> None:
    assert Instant(1, Timeline.MANUAL).is_before(Instant(0, Timeline.MANUAL)) is False


def test_is_before_is_false_for_the_same_instant() -> None:
    assert Instant(5, Timeline.MANUAL).is_before(Instant(5, Timeline.MANUAL)) is False


def test_is_before_raises_across_timelines() -> None:
    with pytest.raises(ContractViolationError):
        Instant(0, Timeline.MANUAL).is_before(Instant(1, Timeline.SIMULATED))


# --------------------------------------------------------------------------- #
# ManualClock
# --------------------------------------------------------------------------- #


def test_a_manual_clock_defaults_to_zero_on_the_manual_timeline() -> None:
    assert ManualClock().now() == Instant(0, Timeline.MANUAL)


def test_a_manual_clock_defaults_its_wall_clock_to_the_unix_epoch_for_byte_stability() -> None:
    assert ManualClock().wall_clock() == datetime(1970, 1, 1, tzinfo=UTC)


def test_a_manual_clock_reports_a_supplied_wall_clock() -> None:
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    assert ManualClock(wall_clock=stamp).wall_clock() == stamp


def test_a_manual_clock_takes_its_timeline_from_the_instant_it_was_seeded_with() -> None:
    assert ManualClock(Instant(0, Timeline.SIMULATED)).timeline is Timeline.SIMULATED
    assert ManualClock().timeline is Timeline.MANUAL


def test_now_does_not_advance_a_manual_clock(clock: ManualClock) -> None:
    first = clock.now()
    second = clock.now()
    assert first == second


def test_advance_moves_the_clock_forward_and_returns_the_new_instant(clock: ManualClock) -> None:
    returned = clock.advance(_FIFTY_MS)
    assert returned == clock.now()
    assert returned.nanoseconds == 50_000_000


def test_advancing_by_zero_is_permitted_and_leaves_the_clock_where_it_was(
    clock: ManualClock,
) -> None:
    before = clock.now()
    assert clock.advance(Seconds(0.0)) == before


def test_repeated_advances_accumulate(clock: ManualClock) -> None:
    for _ in range(4):
        clock.advance(Seconds(0.25))
    assert clock.now().nanoseconds == _NS_PER_S


@pytest.mark.parametrize("interval", [-1e-9, -0.05, -1.0, -3600.0])
def test_a_manual_clock_cannot_be_advanced_backwards(clock: ManualClock, interval: float) -> None:
    with pytest.raises(ContractViolationError):
        clock.advance(Seconds(interval))


def test_a_rejected_backwards_advance_leaves_the_clock_untouched(clock: ManualClock) -> None:
    clock.advance(Seconds(1.0))
    with pytest.raises(ContractViolationError):
        clock.advance(Seconds(-0.5))
    assert clock.now().nanoseconds == _NS_PER_S


def test_a_rejected_backwards_advance_records_the_interval_in_its_audit_context(
    clock: ManualClock,
) -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        clock.advance(Seconds(-0.5))
    assert excinfo.value.context == {"interval_s": -0.5}


def test_a_manual_clock_stays_on_its_own_timeline_when_advanced() -> None:
    manual = ManualClock(Instant(0, Timeline.SIMULATED))
    assert manual.advance(Seconds(1.0)).timeline is Timeline.SIMULATED


def test_a_manual_clock_satisfies_the_clock_protocol() -> None:
    assert isinstance(ManualClock(), Clock)


# --------------------------------------------------------------------------- #
# SystemClock
# --------------------------------------------------------------------------- #


def test_the_system_clock_reports_the_system_monotonic_timeline() -> None:
    assert SystemClock().timeline is Timeline.SYSTEM_MONOTONIC


def test_the_system_clock_stamps_its_instants_with_its_own_timeline() -> None:
    assert SystemClock().now().timeline is Timeline.SYSTEM_MONOTONIC


def test_the_system_clock_never_moves_backwards() -> None:
    system_clock = SystemClock()
    readings = [system_clock.now() for _ in range(50)]
    assert all(
        later.elapsed_since(earlier) >= 0.0 for earlier, later in itertools.pairwise(readings)
    )


def test_the_system_clock_reports_integer_nanoseconds() -> None:
    assert isinstance(SystemClock().now().nanoseconds, int)


def test_the_system_clock_wall_clock_is_timezone_aware_utc() -> None:
    stamp = SystemClock().wall_clock()
    assert stamp.tzinfo is not None
    assert stamp.utcoffset() == timedelta(0)


def test_the_system_clock_satisfies_the_clock_protocol() -> None:
    assert isinstance(SystemClock(), Clock)


# --------------------------------------------------------------------------- #
# staleness
# --------------------------------------------------------------------------- #


def test_staleness_is_the_age_of_an_observation() -> None:
    observed = Instant(0, Timeline.MANUAL)
    now = Instant(50_000_000, Timeline.MANUAL)
    assert staleness(observed, now) == pytest.approx(0.05)


def test_staleness_of_a_just_taken_observation_is_zero() -> None:
    instant = Instant(123, Timeline.MANUAL)
    assert staleness(instant, instant) == 0.0


def test_staleness_is_negative_for_a_future_timestamp_rather_than_clamped_to_zero() -> None:
    observed = Instant(_NS_PER_S, Timeline.MANUAL)
    now = Instant(0, Timeline.MANUAL)
    assert staleness(observed, now) == pytest.approx(-1.0)


def test_staleness_refuses_to_mix_timelines() -> None:
    with pytest.raises(ContractViolationError):
        staleness(Instant(0, Timeline.SIMULATED), Instant(1, Timeline.MANUAL))


def test_staleness_tracks_a_manual_clock(clock: ManualClock) -> None:
    observed = clock.now()
    clock.advance(_FIFTY_MS)
    assert staleness(observed, clock.now()) == pytest.approx(0.05)


# --------------------------------------------------------------------------- #
# is_stale -- the 50 ms rule of FR1
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("age_ns", "stale"),
    [
        (0, False),
        (1, False),
        (49_000_000, False),
        (49_999_999, False),
        (50_000_000, False),
        (50_000_001, True),
        (51_000_000, True),
        (1_000_000_000, True),
    ],
)
def test_the_fifty_millisecond_budget_is_exceeded_only_strictly_beyond_fifty_ms(
    age_ns: int, stale: bool
) -> None:
    observed = Instant(0, Timeline.MANUAL)
    now = Instant(age_ns, Timeline.MANUAL)
    assert is_stale(observed, now, _FIFTY_MS) is stale


def test_an_observation_exactly_at_the_budget_is_not_yet_stale() -> None:
    observed = Instant(0, Timeline.MANUAL)
    now = Instant(50_000_000, Timeline.MANUAL)
    assert is_stale(observed, now, _FIFTY_MS) is False


def test_a_future_timestamp_is_never_reported_as_stale() -> None:
    observed = Instant(_NS_PER_S, Timeline.MANUAL)
    now = Instant(0, Timeline.MANUAL)
    assert is_stale(observed, now, _FIFTY_MS) is False


def test_a_zero_budget_makes_any_positive_age_stale() -> None:
    observed = Instant(0, Timeline.MANUAL)
    assert is_stale(observed, Instant(1, Timeline.MANUAL), Seconds(0.0)) is True
    assert is_stale(observed, observed, Seconds(0.0)) is False


@pytest.mark.parametrize("budget", [-1e-12, -0.05, -1.0])
def test_a_negative_freshness_budget_is_rejected(budget: float) -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        is_stale(Instant(0, Timeline.MANUAL), Instant(1, Timeline.MANUAL), Seconds(budget))
    assert excinfo.value.context == {"field": "staleness_budget", "value": budget}


def test_is_stale_refuses_to_mix_timelines() -> None:
    with pytest.raises(ContractViolationError):
        is_stale(Instant(0, Timeline.SIMULATED), Instant(1, Timeline.MANUAL), _FIFTY_MS)


def test_the_budget_is_checked_before_the_timelines_are_compared() -> None:
    with pytest.raises(ContractViolationError) as excinfo:
        is_stale(Instant(0, Timeline.SIMULATED), Instant(1, Timeline.MANUAL), Seconds(-1.0))
    assert excinfo.value.context == {"field": "staleness_budget", "value": -1.0}


def test_a_stream_flagged_stale_under_a_manual_clock_needs_no_sleep(clock: ManualClock) -> None:
    observed = clock.now()
    clock.advance(Seconds(0.06))
    assert is_stale(observed, clock.now(), _FIFTY_MS) is True


# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #


def test_there_are_exactly_three_timelines() -> None:
    assert len(Timeline) == 3


def test_timeline_members_serialise_as_their_own_names() -> None:
    assert all(member.value == member.name for member in Timeline)


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_freshness_budget_is_rejected(budget: float) -> None:
    # NaN defeats the comparison instead of failing it: `staleness > nan` is
    # False, so a NaN budget would report every stream fresh forever.
    with pytest.raises(NonFiniteValueError):
        is_stale(Instant(0, Timeline.MANUAL), Instant(10**12, Timeline.MANUAL), Seconds(budget))
