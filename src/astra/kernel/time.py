"""Time, clocks and staleness.

Why ASTRA does not call ``time.time()``
---------------------------------------
Three separate requirements make an injected clock non-optional rather than a
testing nicety.

1. **Correctness.** The sensor bus must flag any stream whose staleness exceeds
   50 ms. Staleness is a *duration*, and durations must be measured on a
   monotonic timeline. The wall clock is not monotonic: an NTP correction, a
   leap-second smear or a VM migration can move it backwards, and a negative
   staleness silently reads as "perfectly fresh". Using the wall clock to time
   a control loop is a latent fault, not a style preference.

2. **Replay.** The Prototype & Demo Plan requires tooling that can freeze and
   replay a specific tick range with one feedback loop's weights held constant,
   and states plainly that building it during closed-loop integration rather
   than before is the difference between debugging in hours and in days. Replay
   is impossible if components read a global clock; the recorded timeline has
   to be substitutable for the live one.

3. **Simulation.** CARLA in synchronous mode advances simulated time in fixed
   steps that do not track wall-clock time. A pipeline that measures its own
   latency against the wall clock while the simulator advances on its own
   timeline is measuring two different things and comparing them.

Design decision: timelines are part of the value
------------------------------------------------
Each :class:`Instant` records which :class:`Timeline` it came from, and
subtracting instants from different timelines raises rather than returning a
number. The alternative -- bare floats -- makes "simulated tick time minus
wall-clock arrival time" a perfectly valid expression that produces a
meaningless duration. Given that this system's central claim is about latency
and staleness, that class of defect is worth one integer comparison to prevent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, unique
from typing import Final, Protocol, Self, runtime_checkable

from astra.kernel.errors import ContractViolationError
from astra.kernel.units import Seconds
from astra.kernel.validation import require_non_negative

__all__ = [
    "UNIX_EPOCH",
    "Clock",
    "Instant",
    "ManualClock",
    "SystemClock",
    "Timeline",
    "is_stale",
    "staleness",
]

_NANOSECONDS_PER_SECOND = 1_000_000_000

UNIX_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
"""A fixed civil time, for clocks that must not report the real one.

Replay and test clocks report this instead of the wall clock. Both produce
records that have to be byte-reproducible, and a real civil time would differ on
every run -- defeating the comparison those records exist for. It is safe
precisely because the ``Clock`` protocol documents ``wall_clock`` as being for
human correlation only and never for arithmetic.
"""


@unique
class Timeline(StrEnum):
    """The timeline an :class:`Instant` is measured against.

    Instants from different timelines are not comparable. Recording the
    timeline in the value makes that a runtime error rather than a plausible
    number.
    """

    SYSTEM_MONOTONIC = "SYSTEM_MONOTONIC"
    """The host's monotonic counter. The default for live operation."""

    SIMULATED = "SIMULATED"
    """Simulator-advanced time, e.g. CARLA in synchronous mode."""

    MANUAL = "MANUAL"
    """A test- or replay-controlled timeline advanced explicitly."""


@dataclass(frozen=True, slots=True)
class Instant:
    """A point on a named monotonic timeline, in integer nanoseconds.

    Integer nanoseconds rather than a float of seconds: a float64 holding
    seconds-since-boot loses sub-microsecond resolution after a few days of
    uptime, and this system reports latencies whose target is measured in
    microseconds. Integers do not drift.

    Attributes:
        nanoseconds: Offset from the timeline's own, unspecified epoch. Only
            differences between instants on the same timeline are meaningful.
        timeline: Which timeline the offset is measured against.
    """

    nanoseconds: int
    timeline: Timeline = Timeline.SYSTEM_MONOTONIC

    def __post_init__(self) -> None:
        """Validate the instant.

        Raises:
            ContractViolationError: If the nanosecond count is not an integer.
        """
        # The isinstance check is deliberately kept although mypy proves the
        # left operand unreachable under the annotation: instants are built
        # from adapter and replay data, where the annotation is a claim about
        # the value, not a guarantee. A guard that only runs when the types
        # are already correct guards nothing.
        if not isinstance(self.nanoseconds, int) or isinstance(  # type: ignore[redundant-expr]
            self.nanoseconds, bool
        ):
            message = f"instant requires integer nanoseconds, got {type(self.nanoseconds).__name__}"
            raise ContractViolationError(message)

    @classmethod
    def from_seconds(cls, seconds: float, timeline: Timeline = Timeline.SYSTEM_MONOTONIC) -> Self:
        """Build an instant from a floating-point second offset.

        Args:
            seconds: Offset in seconds from the timeline's epoch.
            timeline: The timeline the offset belongs to.

        Returns:
            The corresponding instant, rounded to the nearest nanosecond.
        """
        return cls(nanoseconds=round(seconds * _NANOSECONDS_PER_SECOND), timeline=timeline)

    def elapsed_since(self, earlier: Instant) -> Seconds:
        """Return the signed interval from ``earlier`` to this instant.

        Args:
            earlier: The reference instant, which must share this timeline.

        Returns:
            The interval in seconds. Positive when this instant is later.

        Raises:
            ContractViolationError: If the two instants are on different
                timelines, in which case their difference has no meaning.
        """
        if earlier.timeline is not self.timeline:
            message = (
                f"cannot compare instants across timelines: "
                f"{self.timeline.value} and {earlier.timeline.value}"
            )
            raise ContractViolationError(
                message,
                context={"left": self.timeline.value, "right": earlier.timeline.value},
            )
        return Seconds((self.nanoseconds - earlier.nanoseconds) / _NANOSECONDS_PER_SECOND)

    def plus(self, interval: Seconds) -> Instant:
        """Return the instant a given interval after this one.

        Args:
            interval: Offset in seconds. May be negative.

        Returns:
            A new instant on the same timeline.
        """
        return Instant(
            nanoseconds=self.nanoseconds + round(interval * _NANOSECONDS_PER_SECOND),
            timeline=self.timeline,
        )

    def is_before(self, other: Instant) -> bool:
        """Return whether this instant precedes another on the same timeline.

        Args:
            other: The instant to compare against.

        Returns:
            ``True`` if this instant is strictly earlier.

        Raises:
            ContractViolationError: If the instants are on different timelines.
        """
        return other.elapsed_since(self) > 0.0


@runtime_checkable
class Clock(Protocol):
    """The source of time for every ASTRA component.

    No component may read time other than through an injected instance of this
    protocol. The architecture test suite enforces this by forbidding imports of
    ``time`` and ``datetime`` outside this module and the adapters that
    implement it.
    """

    @property
    def timeline(self) -> Timeline:
        """Return the timeline this clock measures against."""
        ...

    def now(self) -> Instant:
        """Return the current instant on this clock's timeline.

        Returns:
            A monotonically non-decreasing instant.
        """
        ...

    def wall_clock(self) -> datetime:
        """Return the current civil time, for human-readable audit records only.

        Never used for arithmetic. The value exists so a safety assessor reading
        an audit record can correlate it with an external event; every duration
        in the system is computed from :meth:`now`.

        Returns:
            A timezone-aware datetime in UTC.
        """
        ...


class SystemClock:
    """The production clock: the host's monotonic counter plus UTC civil time."""

    __slots__ = ()

    @property
    def timeline(self) -> Timeline:
        """Return :attr:`Timeline.SYSTEM_MONOTONIC`.

        Returns:
            The system monotonic timeline.
        """
        return Timeline.SYSTEM_MONOTONIC

    def now(self) -> Instant:
        """Return the current monotonic instant.

        Returns:
            An instant sourced from :func:`time.monotonic_ns`.
        """
        return Instant(nanoseconds=time.monotonic_ns(), timeline=Timeline.SYSTEM_MONOTONIC)

    def wall_clock(self) -> datetime:
        """Return the current UTC civil time.

        Returns:
            A timezone-aware datetime in UTC.
        """
        return datetime.now(UTC)


class ManualClock:
    """A clock advanced explicitly, for tests and for the replay harness.

    Time never moves unless a caller moves it. This is what makes a test of the
    50 ms staleness rule deterministic and instantaneous rather than a
    ``sleep``-based test that is both slow and flaky, and it is the substitution
    point the Phase 3 replay tooling will use to re-drive a recorded tick range.
    """

    __slots__ = ("_instant", "_wall_clock")

    def __init__(
        self,
        start: Instant | None = None,
        wall_clock: datetime | None = None,
    ) -> None:
        """Initialise the clock.

        Args:
            start: The initial instant. Defaults to zero on the manual timeline.
            wall_clock: The civil time reported by :meth:`wall_clock`. Defaults
                to the Unix epoch so that records produced under test are
                byte-stable.
        """
        self._instant = start if start is not None else Instant(0, Timeline.MANUAL)
        self._wall_clock = wall_clock if wall_clock is not None else UNIX_EPOCH

    @property
    def timeline(self) -> Timeline:
        """Return the timeline of the instant this clock was seeded with.

        Returns:
            Usually :attr:`Timeline.MANUAL`, or the seeded instant's timeline.
        """
        return self._instant.timeline

    def now(self) -> Instant:
        """Return the current instant without advancing it.

        Returns:
            The instant this clock currently holds.
        """
        return self._instant

    def wall_clock(self) -> datetime:
        """Return the fixed civil time this clock was configured with.

        Returns:
            A timezone-aware datetime.
        """
        return self._wall_clock

    def advance(self, interval: Seconds) -> Instant:
        """Move the clock forward.

        Args:
            interval: A non-negative number of seconds to advance by.

        Returns:
            The new current instant.

        Raises:
            ContractViolationError: If ``interval`` is negative. A monotonic
                clock that can be wound backwards is not monotonic, and a test
                that relies on doing so is testing behaviour the production
                clock cannot produce.
        """
        if interval < 0:
            message = f"a monotonic clock cannot be advanced by {interval} s"
            raise ContractViolationError(message, context={"interval_s": interval})
        self._instant = self._instant.plus(interval)
        return self._instant


def staleness(observed_at: Instant, now: Instant) -> Seconds:
    """Return how old an observation is.

    Args:
        observed_at: When the observation was taken.
        now: The current instant, from the same timeline.

    Returns:
        Age in seconds. Negative if the observation carries a future timestamp,
        which is itself a fault signal worth surfacing rather than clamping.

    Raises:
        ContractViolationError: If the instants are on different timelines.
    """
    return now.elapsed_since(observed_at)


def is_stale(observed_at: Instant, now: Instant, budget: Seconds) -> bool:
    """Return whether an observation has exceeded its freshness budget.

    Implements the rule behind FR1's 50 ms staleness flag. The budget is a
    parameter rather than a constant because it differs per modality and per
    environment, and belongs in configuration.

    Args:
        observed_at: When the observation was taken.
        now: The current instant, from the same timeline.
        budget: The maximum tolerated age, in seconds.

    Returns:
        ``True`` if the observation is older than the budget.

    Raises:
        NonFiniteValueError: If the budget is NaN or infinite. This is checked
            rather than assumed because NaN defeats the comparison below instead
            of failing it: ``staleness > nan`` is ``False``, so a NaN budget
            would silently report every stream as fresh forever -- the exact
            fail-*open* mode this rule exists to catch.
        RangeViolationError: If the budget is negative.
        ContractViolationError: If the instants are on different timelines.
    """
    require_non_negative(budget, name="staleness_budget")
    return staleness(observed_at, now) > budget
