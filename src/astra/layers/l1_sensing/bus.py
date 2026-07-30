"""The shared sensor bus: latest-reading-per-modality, fused once per tick.

What this layer is responsible for
----------------------------------
Five sensor streams arrive asynchronously and at different rates. The control
loop needs, once per tick, a single coherent answer to "what does each modality
currently say, and how much should I trust its freshness?" That is the whole of
L1's job: collect, snapshot, timestamp, and classify staleness. It performs no
filtering, no state estimation and no interpretation of any payload.

The threading model, which is the crux of this module
------------------------------------------------------
Sensor readings do not arrive on the control thread. A simulator or a driver
delivers them from its own callback threads, at times the pipeline does not
choose. Meanwhile the control loop calls :meth:`SharedSensorBus.acquire` once
per tick and must not be delayed.

So the bus is a rendezvous between *many writer threads* and *one reader
thread*:

* :meth:`SharedSensorBus.publish` is called from arbitrary threads and holds the
  lock only long enough to replace one dictionary entry.
* :meth:`SharedSensorBus.acquire` holds it only long enough to copy at most five
  entries, then builds the frame outside the lock.

Both critical sections are a handful of instructions over a structure with at
most five keys, so contention is negligible against a 50 ms tick period. A
lock-free design (atomic swap of an immutable mapping) was considered and
rejected: it buys nothing measurable at this scale and costs real clarity in a
module whose correctness argument is exactly about ordering.

Why a *later* reading may not be replaced by an *earlier* one
--------------------------------------------------------------
Readings can arrive out of order -- a delayed frame, a retransmission, a
callback thread descheduled at the wrong moment. If the bus accepted whichever
sample arrived last, a late-arriving old reading would replace a fresh one and
the stream's measured staleness would *decrease going backwards in time*. A
stale stream would then look healthy, which is precisely the fault the 50 ms
rule exists to catch.

The bus therefore keeps the sample with the latest ``observed_at`` and counts
every superseded arrival. The count is a diagnostic, not a silent discard: a
stream that constantly delivers out of order is misconfigured, and the evidence
should say so.

Acquisition time, not arrival time
-----------------------------------
Staleness is measured from when a reading was *taken*, never from when it
arrived. A reading delayed 80 ms in transport is 80 ms stale the instant it
appears, and treating it as fresh because it just arrived would hide the
transport fault entirely. :class:`~astra.contracts.sensing.SensorSample` records
``observed_at`` for this reason, and this module never substitutes the clock's
reading for it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra.contracts.sensing import FusedSensorFrame, SensorSample
from astra.kernel.enums import LayerId, SensorModality, StreamHealth
from astra.kernel.errors import ContractViolationError
from astra.kernel.time import staleness
from astra.kernel.validation import require_non_negative

if TYPE_CHECKING:
    from collections.abc import Mapping

    from astra.kernel.identifiers import TickId
    from astra.kernel.time import Clock
    from astra.kernel.units import Seconds

__all__ = ["BusStatistics", "SharedSensorBus"]


@dataclass(frozen=True, slots=True)
class BusStatistics:
    """A snapshot of what the bus has seen, for diagnostics and evidence.

    Attributes:
        published: Total samples accepted, per modality.
        superseded: Samples rejected because a newer reading was already held,
            per modality. A persistently non-zero value means that stream is
            delivering out of order, which is a configuration or transport
            fault rather than a safety event.
        frames_acquired: How many fused frames have been produced.
    """

    published: Mapping[SensorModality, int]
    superseded: Mapping[SensorModality, int]
    frames_acquired: int

    @property
    def total_published(self) -> int:
        """Return the total number of accepted samples across all modalities."""
        return sum(self.published.values())

    @property
    def total_superseded(self) -> int:
        """Return the total number of out-of-order samples rejected."""
        return sum(self.superseded.values())


class SharedSensorBus[PayloadT]:
    """Collects asynchronous sensor readings and fuses them once per tick.

    Satisfies :class:`~astra.ports.pipeline.SensorSource` structurally. Generic
    in the payload so that the pipeline stays domain-independent: an adapter
    binds ``PayloadT`` to a concrete measurement type, and nothing in this class
    inspects it.

    Thread-safe. :meth:`publish` may be called concurrently from any number of
    sensor threads while the control thread calls :meth:`acquire`.
    """

    __slots__ = (
        "_clock",
        "_frames_acquired",
        "_latest",
        "_lock",
        "_published",
        "_staleness_budget",
        "_superseded",
    )

    def __init__(self, *, clock: Clock, staleness_budget: Seconds) -> None:
        """Initialise an empty bus.

        Args:
            clock: The injected time source. Every frame's fusion instant comes
                from here, and every published sample must share its timeline.
            staleness_budget: The freshness budget from configuration, in
                seconds. FR1's rule is 50 ms; it is a parameter rather than a
                constant because it differs per environment.

        Raises:
            NonFiniteValueError: If the budget is NaN or infinite. Checked
                explicitly because NaN defeats the staleness comparison rather
                than failing it -- ``staleness > nan`` is ``False``, so a NaN
                budget would report every stream healthy forever and silently
                disable FR1 altogether.
            RangeViolationError: If the budget is negative.
        """
        require_non_negative(staleness_budget, name="staleness_budget", layer=LayerId.L1_SENSOR_BUS)
        self._clock = clock
        self._staleness_budget = staleness_budget
        self._lock = threading.Lock()
        self._latest: dict[SensorModality, SensorSample[PayloadT]] = {}
        self._published: dict[SensorModality, int] = dict.fromkeys(SensorModality, 0)
        self._superseded: dict[SensorModality, int] = dict.fromkeys(SensorModality, 0)
        self._frames_acquired = 0

    # ----------------------------------------------------------------- #
    # Producer side -- called from sensor threads
    # ----------------------------------------------------------------- #

    def publish(self, sample: SensorSample[PayloadT]) -> bool:
        """Offer a reading to the bus.

        Thread-safe and non-blocking in any practical sense: the lock is held
        for one dictionary comparison and one assignment.

        Args:
            sample: The reading. Its ``observed_at`` must be on the bus clock's
                timeline.

        Returns:
            ``True`` if the sample was accepted as the modality's latest
            reading, ``False`` if a newer reading was already held and this one
            was therefore superseded.

        Raises:
            ContractViolationError: If the sample's timeline differs from the
                bus clock's. Mixing timelines would make every staleness
                computation meaningless, so it is refused at the boundary rather
                than allowed to produce a plausible number.
        """
        if sample.observed_at.timeline is not self._clock.timeline:
            message = (
                f"sensor sample for {sample.modality.value} is on timeline "
                f"{sample.observed_at.timeline.value}, but the bus clock runs on "
                f"{self._clock.timeline.value}"
            )
            raise ContractViolationError(
                message,
                layer=LayerId.L1_SENSOR_BUS,
                context={
                    "modality": sample.modality.value,
                    "sample_timeline": sample.observed_at.timeline.value,
                    "bus_timeline": self._clock.timeline.value,
                },
            )

        with self._lock:
            held = self._latest.get(sample.modality)
            if held is not None and not held.observed_at.is_before(sample.observed_at):
                # An equal or earlier acquisition time. Accepting it would let
                # measured staleness travel backwards, hiding a stale stream.
                self._superseded[sample.modality] += 1
                return False
            self._latest[sample.modality] = sample
            self._published[sample.modality] += 1
            return True

    # ----------------------------------------------------------------- #
    # Consumer side -- called from the control thread, once per tick
    # ----------------------------------------------------------------- #

    def acquire(self, tick: TickId) -> FusedSensorFrame[PayloadT]:
        """Fuse the latest reading from every modality into one frame.

        Modalities that have never delivered a reading are reported as absent
        rather than omitted, because "no sensor" and "an old reading" call for
        different responses and the frame must preserve the distinction.

        Samples are emitted in :class:`~astra.kernel.enums.SensorModality`
        declaration order, never in the order they happened to be published.
        The frame contract does not guarantee an order, so without this the
        order would depend on which sensor thread happened to deliver first --
        and two runs over identical inputs would produce frames that are equal
        in content but not in structure. That defeats frame-by-frame comparison
        between a run and its replay, which is the whole debugging technique the
        replay spine exists to support. Sorting five items costs nothing against
        a 50 ms tick.

        Args:
            tick: The control tick this frame belongs to.

        Returns:
            The fused frame, stamped with the fusion instant.
        """
        with self._lock:
            # The clock is read *inside* the critical section so that the
            # snapshot and the instant it is measured against are atomic. Read
            # outside, a sample published in the intervening window would carry
            # an `observed_at` after `fused_at` and be reported with negative
            # staleness -- manufacturing the future-timestamp fault signal out
            # of ordinary scheduling jitter.
            fused_at = self._clock.now()
            held = dict(self._latest)
            self._frames_acquired += 1
        snapshot = tuple(held[modality] for modality in SensorModality if modality in held)
        return FusedSensorFrame.build(tick=tick, fused_at=fused_at, samples=snapshot)

    def health(self, frame: FusedSensorFrame[PayloadT]) -> dict[SensorModality, StreamHealth]:
        """Classify every modality's freshness in a frame, against this bus's budget.

        A convenience over
        :meth:`~astra.contracts.sensing.FusedSensorFrame.health` that supplies
        the configured budget, so a caller cannot accidentally classify against
        a different one than the bus was built with.

        Args:
            frame: A frame this bus produced.

        Returns:
            The health of every modality named in the frame.
        """
        return frame.health(self._staleness_budget)

    def degraded_modalities(self, frame: FusedSensorFrame[PayloadT]) -> frozenset[SensorModality]:
        """Return the modalities in a frame that are not fully healthy.

        Args:
            frame: A frame this bus produced.

        Returns:
            Every modality whose stream is stale, absent or faulted.
        """
        return frame.degraded_modalities(self._staleness_budget)

    def is_degraded(self, frame: FusedSensorFrame[PayloadT]) -> bool:
        """Return whether any modality in a frame is not fully healthy.

        The predicate behind FR1's DEGRADED transition.

        Args:
            frame: A frame this bus produced.

        Returns:
            ``True`` if at least one stream is stale, absent or faulted.
        """
        return bool(self.degraded_modalities(frame))

    def staleness_of(
        self, frame: FusedSensorFrame[PayloadT], modality: SensorModality
    ) -> Seconds | None:
        """Return how old one modality's reading was at fusion time.

        Args:
            frame: A frame this bus produced.
            modality: The modality to measure.

        Returns:
            The age in seconds, or ``None`` if that modality was absent from the
            frame. A negative value means the reading carries a future
            timestamp, which is itself a fault signal and is surfaced rather
            than clamped.
        """
        sample = frame.sample_for(modality)
        if sample is None:
            return None
        return staleness(sample.observed_at, frame.fused_at)

    # ----------------------------------------------------------------- #
    # Introspection
    # ----------------------------------------------------------------- #

    @property
    def staleness_budget(self) -> Seconds:
        """Return the freshness budget this bus classifies against."""
        return self._staleness_budget

    @property
    def statistics(self) -> BusStatistics:
        """Return a consistent snapshot of the bus's counters.

        Returns:
            The counts of accepted and superseded samples per modality, and the
            number of frames produced.
        """
        with self._lock:
            return BusStatistics(
                published=dict(self._published),
                superseded=dict(self._superseded),
                frames_acquired=self._frames_acquired,
            )

    def latest(self, modality: SensorModality) -> SensorSample[PayloadT] | None:
        """Return the newest reading held for one modality.

        Provided for diagnostics and for the replay recorder. The pipeline reads
        frames, not the bus's internals, so this is not part of the hot path.

        Args:
            modality: The modality to inspect.

        Returns:
            The latest sample, or ``None`` if that modality has delivered
            nothing.
        """
        with self._lock:
            return self._latest.get(modality)

    def reset(self) -> None:
        """Discard every held reading and zero the counters.

        Used between replayed segments, so that a rerun does not inherit
        readings from the previous one and produce a frame that never existed.
        """
        with self._lock:
            self._latest.clear()
            self._published = dict.fromkeys(SensorModality, 0)
            self._superseded = dict.fromkeys(SensorModality, 0)
            self._frames_acquired = 0
