"""Injecting sensor faults into a closed-loop run, with ground truth attached.

Why this exists
----------------
Everything this project has measured so far shows that the machinery **runs**.
Section D of ``docs/CREDIBILITY_MATRIX.md`` -- what each gate actually
*catches*, which is the product claim -- has one row, and D-0 says why: nothing
in the synthetic plant is out-of-distribution in the sense L6 is calibrated for,
so no false-negative rate can be computed from it. Not with more ticks. Not with
a longer soak.

The missing ingredient is a fault with **known ground truth**: something wrong
with the world, whose shape, size and exact tick range are recorded
independently of whatever the gates then say about it. Given that, three
measurements become possible that are not possible today -- miss rate, detection
latency, and the false-alarm rate on the clean ticks either side. Given that,
``PENDING.md`` P3.5's comparison harness has its missing half: two instances,
same seed, same injected fault, one of which keeps moving.

Five separate open items reduce to this one. P3.4, P3.5, P4.2, section D of the
matrix, and P2.1's own stated limitation -- that the fail-safe speed cap has
only ever been observed under a *deliberate provocation*, never under a fault.

Where it attaches, and why not somewhere else
----------------------------------------------
At the **sensor boundary**: :func:`training.closed_loop._publish_state`, before
a reading reaches the bus. Nothing in ``src/astra/`` changes and nothing in
``src/astra/`` needs to know this module exists, which is the point --
fault-injection machinery inside a safety-critical package is a question with no
good answer, and the twelve import contracts plus ``make verify-install`` are
already the enforcement. See ADR-0022.

It also happens to be the honest place. From the pipeline's side a corrupted
reading is indistinguishable from a genuinely faulty sensor, because it *is* the
same event: L1 sees a payload, and nothing downstream can tell how it was
produced.

The five faults, and why each one
----------------------------------
Chosen so that each defeats a different defence, rather than for variety.

``BIAS``
    A constant offset. Miscalibrated IMU, a wheel-encoder scale error. The
    reading is fresh, well-formed and confidently wrong, so L1's staleness rule
    cannot see it and only the UKF's innovation sequence can.
``DRIFT``
    An offset ramping linearly to its final magnitude. The hardest case and the
    most realistic degradation: no single tick looks anomalous, so anything
    thresholding on a per-tick delta misses it by construction. This is the
    fault that separates a monitor from an alarm.
``STUCK_AT``
    The channel freezes at its last healthy value. Distinct from ``DROPOUT``
    because the reading remains **fresh** -- the classic failure a staleness
    check is powerless against, and the reason ``StreamHealth`` separates
    ``DEGRADED`` from ``FAULTED`` in the first place.
``NOISE_BURST``
    The declared sigma is multiplied while the sigma reported *to the filter*
    is not. The UKF over-trusts a stream that has stopped deserving it; the
    normalised innovations inflate, and the Trust Index is the layer that ought
    to notice.
``DROPOUT``
    The IMU publishes nothing. The one fault the existing machinery is designed
    for, included as the control: if a run under dropout shows nothing, the
    harness is broken rather than the system.

The rule this module exists to obey
------------------------------------
**A fault injector nobody has verified actually injects is worth nothing.** It
would produce a table of "faults the gates did not catch" that was really a
table of faults never injected, and -- exactly like the fail-safe speed cap
(OD-2) and the inert consolidation penalty (E-28) -- it would fail by making the
evidence look *better*, which is the failure mode this project has now been
bitten by three times and which testing cannot see by construction.

Two things follow, and both are load-bearing rather than decorative:

1. :class:`FaultSpec` **refuses to be configured inert.** A zero-magnitude bias,
   a window that ends before it starts, a magnitude on a fault that has no use
   for one -- each raises at construction. An injector that does nothing is not
   a quiet injector, it is a rejected one.
2. :class:`FaultEpisode` reports the peak error **measured while injecting**,
   not the magnitude that was requested. The two are equal when this module
   works and differ when it does not, so
   ``tests/unit/test_fault_injection.py`` can assert on the difference rather
   than on the intent.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "FaultChannel",
    "FaultEpisode",
    "FaultInjector",
    "FaultKind",
    "FaultSpec",
    "bias",
    "drift",
    "dropout",
    "noise_burst",
    "stuck_at",
]

_INJECTOR_SEED_OFFSET = 0x5AFE
"""Separates the injector's stream from the harness's measurement-noise stream.

Both are seeded from the run seed, and if they shared a generator then adding a
fault would re-phase every subsequent noise draw. The ASTRA-versus-baseline
comparison P3.5 exists to make would then differ in two ways at once -- the
fault, and every sensor reading after it -- and no difference in outcome could
be attributed to either. The value is arbitrary; that it is applied is not.
"""


@unique
class FaultKind(StrEnum):
    """How a fault corrupts the reading it is applied to."""

    BIAS = "BIAS"
    DRIFT = "DRIFT"
    STUCK_AT = "STUCK_AT"
    NOISE_BURST = "NOISE_BURST"
    DROPOUT = "DROPOUT"


@unique
class FaultChannel(StrEnum):
    """Which published quantity a fault corrupts.

    The values are the payload keys the synthetic plant publishes, so a channel
    indexes the reading directly and there is no second mapping to drift out of
    step with the first.
    """

    POSITION_Y = "y"
    SPEED = "v"
    LATERAL_ACCELERATION = "a"


_VALUELESS_KINDS = frozenset({FaultKind.DROPOUT, FaultKind.STUCK_AT})
"""Kinds that take no magnitude.

``DROPOUT`` removes the reading and ``STUCK_AT`` holds whatever the last healthy
one was; neither has a number to be given. Accepting one silently would let a
caller believe they had configured a severity that was never read.
"""


@dataclass(frozen=True, slots=True)
class FaultSpec:
    """One fault, its window, and its severity.

    Windows are **inclusive at both ends**, because the natural way to describe
    an injected fault is "ticks 500 through 700" and a half-open window makes
    every ground-truth comparison an off-by-one waiting to happen.

    Attributes:
        kind: How the reading is corrupted.
        first_tick: The first tick the fault applies to, inclusive.
        last_tick: The last tick the fault applies to, inclusive.
        magnitude: The severity, interpreted per kind: metres, metres per
            second or metres per second squared of offset for ``BIAS``; the
            *final* offset reached at ``last_tick`` for ``DRIFT``; a
            multiplier on the injected sigma for ``NOISE_BURST``. Must be
            omitted for ``DROPOUT`` and ``STUCK_AT``.
        channel: Which quantity is corrupted. Must be omitted for ``DROPOUT``,
            which removes the whole reading rather than one field of it.
    """

    kind: FaultKind
    first_tick: int
    last_tick: int
    magnitude: float = 0.0
    channel: FaultChannel | None = None

    def __post_init__(self) -> None:
        """Reject any specification that could not inject anything.

        Every branch here exists because the alternative is an injector that
        runs, reports, and does nothing -- which is worse than one that fails,
        since the resulting evidence would read as "the gates missed it".

        Raises:
            ValueError: If the window is empty or starts before tick zero, if
                the channel is present or absent contrary to the kind, or if
                the magnitude is missing, superfluous, or inert.
        """
        if self.first_tick < 0:
            message = f"first_tick must not be negative, got {self.first_tick}"
            raise ValueError(message)
        if self.last_tick < self.first_tick:
            message = (
                f"the window is empty: last_tick {self.last_tick} precedes "
                f"first_tick {self.first_tick}"
            )
            raise ValueError(message)

        wants_channel = self.kind is not FaultKind.DROPOUT
        if wants_channel and self.channel is None:
            message = f"{self.kind} corrupts one channel, so a channel is required"
            raise ValueError(message)
        if not wants_channel and self.channel is not None:
            message = f"{self.kind} removes the whole reading, so it takes no channel"
            raise ValueError(message)

        if self.kind in _VALUELESS_KINDS:
            if self.magnitude != 0.0:
                message = f"{self.kind} takes no magnitude, got {self.magnitude}"
                raise ValueError(message)
            return
        if not math.isfinite(self.magnitude):
            message = f"{self.kind} needs a finite magnitude, got {self.magnitude}"
            raise ValueError(message)
        if self.magnitude == 0.0:
            message = f"{self.kind} with magnitude 0.0 would inject nothing"
            raise ValueError(message)
        if self.kind is FaultKind.NOISE_BURST and self.magnitude <= 1.0:
            message = (
                "NOISE_BURST multiplies the injected sigma, so a magnitude of "
                f"{self.magnitude} would leave the stream no worse than clean"
            )
            raise ValueError(message)

    @property
    def tick_count(self) -> int:
        """Return how many ticks the window spans."""
        return self.last_tick - self.first_tick + 1

    def covers(self, tick: int) -> bool:
        """Return whether this fault applies to a tick.

        Args:
            tick: The control tick.

        Returns:
            ``True`` if the tick falls inside the inclusive window.
        """
        return self.first_tick <= tick <= self.last_tick


def bias(channel: FaultChannel, *, first_tick: int, last_tick: int, offset: float) -> FaultSpec:
    """Build a constant-offset fault.

    Args:
        channel: The quantity to corrupt.
        first_tick: First affected tick, inclusive.
        last_tick: Last affected tick, inclusive.
        offset: The offset added to every reading in the window.

    Returns:
        The specification.
    """
    return FaultSpec(
        kind=FaultKind.BIAS,
        first_tick=first_tick,
        last_tick=last_tick,
        magnitude=offset,
        channel=channel,
    )


def drift(channel: FaultChannel, *, first_tick: int, last_tick: int, final: float) -> FaultSpec:
    """Build a linearly ramping offset.

    Args:
        channel: The quantity to corrupt.
        first_tick: First affected tick, inclusive. The offset is zero here.
        last_tick: Last affected tick, inclusive. The offset is ``final`` here.
        final: The offset reached at the end of the window.

    Returns:
        The specification.
    """
    return FaultSpec(
        kind=FaultKind.DRIFT,
        first_tick=first_tick,
        last_tick=last_tick,
        magnitude=final,
        channel=channel,
    )


def stuck_at(channel: FaultChannel, *, first_tick: int, last_tick: int) -> FaultSpec:
    """Build a frozen-reading fault.

    Args:
        channel: The quantity to freeze.
        first_tick: First affected tick, inclusive. The value published on this
            tick is the one held for the rest of the window.
        last_tick: Last affected tick, inclusive.

    Returns:
        The specification.
    """
    return FaultSpec(
        kind=FaultKind.STUCK_AT, first_tick=first_tick, last_tick=last_tick, channel=channel
    )


def noise_burst(
    channel: FaultChannel, *, first_tick: int, last_tick: int, sigma_multiplier: float
) -> FaultSpec:
    """Build a variance-inflation fault.

    Args:
        channel: The quantity to corrupt.
        first_tick: First affected tick, inclusive.
        last_tick: Last affected tick, inclusive.
        sigma_multiplier: How much noisier the stream becomes. The sigma
            *declared to the filter* is unchanged, which is what makes this a
            fault rather than a configuration change.

    Returns:
        The specification.
    """
    return FaultSpec(
        kind=FaultKind.NOISE_BURST,
        first_tick=first_tick,
        last_tick=last_tick,
        magnitude=sigma_multiplier,
        channel=channel,
    )


def dropout(*, first_tick: int, last_tick: int) -> FaultSpec:
    """Build a reading-loss fault.

    Args:
        first_tick: First affected tick, inclusive.
        last_tick: Last affected tick, inclusive.

    Returns:
        The specification.
    """
    return FaultSpec(kind=FaultKind.DROPOUT, first_tick=first_tick, last_tick=last_tick)


@dataclass(frozen=True, slots=True)
class FaultEpisode:
    """What one fault specification actually did, as opposed to what it asked for.

    This is the ground truth a detection measurement is scored against, and the
    separation between *requested* and *achieved* is the whole reason the type
    exists. ``spec.magnitude`` is intent; ``peak_absolute_error`` is measurement.
    An injector that had silently stopped injecting would report a spec
    unchanged and a peak of zero, and the assertion that catches it lives in
    ``tests/unit/test_fault_injection.py``.

    Attributes:
        spec: The specification this episode realises.
        ticks_applied: How many ticks the fault was actually applied on.
        peak_absolute_error: The largest ``|corrupted - clean|`` observed while
            injecting, or ``None`` for ``DROPOUT`` -- where no reading was
            published, so "how wrong was it" has no answer. A stale stream and
            a lying stream are different faults and this field declines to
            collapse them, the same distinction ``StreamHealth`` draws.
    """

    spec: FaultSpec
    ticks_applied: int
    peak_absolute_error: float | None


class FaultInjector:
    """Applies a fixed set of faults to sensor payloads, and records what it did.

    The injector is a pure function of ``(specs, seed, tick)`` and holds only
    the state it cannot avoid: the frozen values ``STUCK_AT`` needs, and the
    per-spec tallies that become :attr:`episodes`.

    **It draws no randomness on a tick where nothing is active.** That is what
    makes a run with an inactive injector bit-identical to a run with no
    injector at all, which in turn is what makes the fault the only difference
    between the two arms of a comparison. The property is pinned by
    ``test_an_injector_with_nothing_active_draws_no_randomness``, not left to
    inspection -- the same reasoning as the shadow harness's isolation tests,
    which caught two defects no other test would have.
    """

    __slots__ = ("_frozen", "_peaks", "_random", "_sigmas", "_specs", "_tallies")

    def __init__(
        self,
        specs: Sequence[FaultSpec],
        *,
        seed: int,
        sigmas: Mapping[FaultChannel, float],
    ) -> None:
        """Build an injector.

        Args:
            specs: The faults to apply, in order. Two specs may overlap on the
                same channel; the later one is applied to the earlier one's
                output, which is how a drifting sensor that then freezes is
                described.
            seed: The run seed. Offset internally so the injector's stream is
                disjoint from the harness's measurement noise -- see
                :data:`_INJECTOR_SEED_OFFSET`.
            sigmas: The measurement sigma **declared to the filter** for each
                channel. Passed in rather than imported, because the sensor
                model belongs to the harness that publishes readings and a
                second copy of it here is a second thing to drift. Only
                ``NOISE_BURST`` reads it, and what makes that a fault rather
                than a configuration change is precisely that this number does
                not move when the injected noise does.
        """
        self._specs = tuple(specs)
        self._random = random.Random(seed ^ _INJECTOR_SEED_OFFSET)
        self._sigmas = dict(sigmas)
        self._frozen: dict[int, float] = {}
        self._tallies: dict[int, int] = {}
        self._peaks: dict[int, float] = {}

    @property
    def specs(self) -> tuple[FaultSpec, ...]:
        """Return the faults this injector was built with."""
        return self._specs

    def is_active(self, tick: int) -> bool:
        """Return whether any fault applies to a tick.

        This is the ground-truth label a detection measurement joins against:
        for each tick, *was something actually wrong* beside *did any gate say
        so*. Without it a veto rate is a number with no denominator.

        Args:
            tick: The control tick.

        Returns:
            ``True`` if at least one specification covers the tick.
        """
        return any(spec.covers(tick) for spec in self._specs)

    def drops_reading(self, tick: int) -> bool:
        """Return whether the reading is suppressed entirely on a tick.

        Args:
            tick: The control tick.

        Returns:
            ``True`` if a ``DROPOUT`` specification covers the tick.
        """
        return any(spec.kind is FaultKind.DROPOUT and spec.covers(tick) for spec in self._specs)

    def corrupt(self, payload: Mapping[str, float], *, tick: int) -> dict[str, float] | None:
        """Return the payload as the sensors would report it under fault.

        A dropout short-circuits every other fault on the same tick: a reading
        that was never published cannot also be biased, and counting it as both
        would inflate the ground truth the detection rate is divided by.

        Args:
            payload: The clean reading, keyed by :class:`FaultChannel` value.
            tick: The control tick.

        Returns:
            The corrupted reading, or ``None`` if the reading is suppressed.
        """
        if self.drops_reading(tick):
            for index, spec in enumerate(self._specs):
                if spec.kind is FaultKind.DROPOUT and spec.covers(tick):
                    self._tallies[index] = self._tallies.get(index, 0) + 1
            return None

        corrupted = dict(payload)
        for index, spec in enumerate(self._specs):
            channel = spec.channel
            if channel is None or not spec.covers(tick):
                continue
            clean = float(payload[channel.value])
            corrupted[channel.value] = self._apply(
                spec, index, tick=tick, channel=channel, clean=corrupted[channel.value]
            )
            self._tallies[index] = self._tallies.get(index, 0) + 1
            self._peaks[index] = max(
                self._peaks.get(index, 0.0), abs(corrupted[channel.value] - clean)
            )
        return corrupted

    def _apply(
        self, spec: FaultSpec, index: int, *, tick: int, channel: FaultChannel, clean: float
    ) -> float:
        """Return one channel's corrupted value.

        Args:
            spec: The fault to apply.
            index: Its position in :attr:`specs`, used to key per-spec state.
            tick: The control tick.
            channel: The channel being corrupted, already resolved by the
                caller so this method never has to reason about ``None``.
            clean: The value as it stands before this fault.

        Returns:
            The corrupted value.

        Raises:
            RuntimeError: If called with ``DROPOUT``, which :meth:`corrupt`
                handles before reaching here.
        """
        match spec.kind:
            case FaultKind.BIAS:
                return clean + spec.magnitude
            case FaultKind.DRIFT:
                # Zero at the first tick, `magnitude` at the last. A one-tick
                # window has no ramp to walk, so it arrives at full magnitude.
                span = spec.tick_count - 1
                fraction = 1.0 if span == 0 else (tick - spec.first_tick) / span
                return clean + spec.magnitude * fraction
            case FaultKind.STUCK_AT:
                return self._frozen.setdefault(index, clean)
            case FaultKind.NOISE_BURST:
                # Additional noise at `magnitude` times the sigma the filter was
                # told about, so the stream's true sigma becomes
                # `declared * sqrt(1 + magnitude**2)` while the declared one
                # does not move. That gap is the fault.
                #
                # Drawn only here, so a tick with nothing active consumes no
                # randomness -- see the class docstring.
                return clean + self._random.gauss(0.0, self._sigmas[channel] * spec.magnitude)
            case FaultKind.DROPOUT:  # pragma: no cover - handled in corrupt()
                message = "DROPOUT is handled by corrupt() and never reaches _apply"
                raise RuntimeError(message)

    @property
    def episodes(self) -> tuple[FaultEpisode, ...]:
        """Return what each specification achieved, in specification order.

        Read after a run. An episode reporting ``ticks_applied == 0`` means the
        window fell outside the run; one reporting a zero peak means the
        injector ran and changed nothing, which is a defect in this module.

        Returns:
            One episode per specification.
        """
        return tuple(
            FaultEpisode(
                spec=spec,
                ticks_applied=self._tallies.get(index, 0),
                peak_absolute_error=(
                    None if spec.kind is FaultKind.DROPOUT else self._peaks.get(index, 0.0)
                ),
            )
            for index, spec in enumerate(self._specs)
        )
