"""L1 contracts: what the shared sensor bus produces.

The architecture states a rule that this module has to make enforceable: *no
layer consumes raw sensor data directly*. Everything downstream of L2 reads the
UKF state estimate. L1's output therefore has exactly one legitimate consumer,
the dual-rate UKF, plus the Runtime Context Signature builder in L9, which reads
only the reliability metadata and never the payloads.

That asymmetry is why the payload is generic and the metadata is not. Health,
quality, staleness and provenance are architectural and identical across every
domain ASTRA might govern; the shape of a LiDAR return is not. Making the
payload a type parameter lets the automotive adapter say
``FusedSensorFrame[CarlaSensorPayload]`` while the pipeline's own code stays
domain-independent, as NFR5 requires.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra.kernel.enums import SensorModality, StreamHealth
from astra.kernel.errors import ContractViolationError
from astra.kernel.time import Instant, is_stale
from astra.kernel.validation import require_probability

if TYPE_CHECKING:
    from collections.abc import Iterable

    from astra.kernel.identifiers import TickId
    from astra.kernel.units import Probability, Seconds

__all__ = ["FusedSensorFrame", "SensorSample"]


@dataclass(frozen=True, slots=True)
class SensorSample[PayloadT]:
    """One timestamped reading from one modality.

    Mirrors the ``(value, timestamp, modality, quality)`` tuple the architecture
    specifies for the sensor bus, with health made explicit rather than derived
    at each call site.

    Attributes:
        modality: Which sensor produced the reading.
        observed_at: When the reading was taken, on the pipeline's timeline.
            This is the acquisition time required by FR1, not the arrival time:
            a reading delayed in transport is stale even though it has just
            arrived, and conflating the two hides exactly the fault the 50 ms
            staleness rule exists to catch.
        quality: Modality-reported confidence in ``[0, 1]``. Feeds the
            reliability weighting of the Runtime Context Signature, so that a
            degraded sensor lowers its own contribution rather than silently
            dominating the signature.
        payload: The measurement itself. Opaque to the pipeline.
    """

    modality: SensorModality
    observed_at: Instant
    quality: Probability
    payload: PayloadT

    def __post_init__(self) -> None:
        """Validate the reading's metadata.

        Raises:
            RangeViolationError: If ``quality`` lies outside ``[0, 1]``.
        """
        require_probability(self.quality, name=f"{self.modality.value}.quality")

    def health_at(self, now: Instant, staleness_budget: Seconds) -> StreamHealth:
        """Classify this reading's freshness against a budget.

        Only ``HEALTHY`` and ``DEGRADED`` can be decided here. ``FAULTED``
        requires the UKF's innovation-sequence Mahalanobis monitor, which knows
        what the reading *should* have been; a stale stream and a lying stream
        are different faults and are deliberately not collapsed.

        Args:
            now: The current instant, on the same timeline as ``observed_at``.
            staleness_budget: Maximum tolerated age, from configuration.

        Returns:
            :attr:`~astra.kernel.enums.StreamHealth.DEGRADED` if the reading has
            exceeded its budget, otherwise ``HEALTHY``.

        Raises:
            ContractViolationError: If the instants belong to different
                timelines.
        """
        if is_stale(self.observed_at, now, staleness_budget):
            return StreamHealth.DEGRADED
        return StreamHealth.HEALTHY


@dataclass(frozen=True, slots=True)
class FusedSensorFrame[PayloadT]:
    """The fused, timestamped multi-modal reading produced once per tick.

    Samples are held in a tuple rather than a mapping so the record is genuinely
    immutable: a ``dict`` field on a frozen dataclass is still mutable through
    the reference, which would let a downstream layer alter a frame another
    layer has already consumed. With at most five modalities, lookup by linear
    scan costs less than constructing a hash.

    Attributes:
        tick: The control tick this frame belongs to.
        fused_at: When fusion completed. The reference instant for staleness.
        samples: One sample per present modality, in no guaranteed order.
        absent_modalities: Modalities that produced nothing this tick. Recorded
            explicitly, because "no reading" and "an old reading" have different
            causes and different responses.
    """

    tick: TickId
    fused_at: Instant
    samples: tuple[SensorSample[PayloadT], ...]
    absent_modalities: frozenset[SensorModality] = frozenset()

    def __post_init__(self) -> None:
        """Validate structural consistency of the frame.

        Raises:
            ContractViolationError: If a modality appears twice, or appears in
                both the samples and the absent set.
        """
        present = [sample.modality for sample in self.samples]
        if len(present) != len(set(present)):
            message = "a fused frame must carry at most one sample per modality"
            raise ContractViolationError(
                message, context={"modalities": [modality.value for modality in present]}
            )
        overlap = self.absent_modalities.intersection(present)
        if overlap:
            message = "a modality cannot be both present and absent in the same frame"
            raise ContractViolationError(
                message, context={"modalities": sorted(modality.value for modality in overlap)}
            )

    def sample_for(self, modality: SensorModality) -> SensorSample[PayloadT] | None:
        """Return the sample for one modality, if present.

        Args:
            modality: The modality to look up.

        Returns:
            The sample, or ``None`` if that modality produced nothing this tick.
        """
        for sample in self.samples:
            if sample.modality is modality:
                return sample
        return None

    def health(self, staleness_budget: Seconds) -> dict[SensorModality, StreamHealth]:
        """Classify every modality's health for this frame.

        Args:
            staleness_budget: Maximum tolerated age, from configuration.

        Returns:
            A health verdict for every modality named in the frame, including
            :attr:`~astra.kernel.enums.StreamHealth.ABSENT` entries.

        Raises:
            ContractViolationError: If a sample's timeline differs from the
                frame's.
        """
        report: dict[SensorModality, StreamHealth] = dict.fromkeys(
            self.absent_modalities, StreamHealth.ABSENT
        )
        for sample in self.samples:
            report[sample.modality] = sample.health_at(self.fused_at, staleness_budget)
        return report

    def degraded_modalities(self, staleness_budget: Seconds) -> frozenset[SensorModality]:
        """Return the modalities that are not fully healthy.

        Args:
            staleness_budget: Maximum tolerated age, from configuration.

        Returns:
            The set of modalities in any state other than ``HEALTHY``.

        Raises:
            ContractViolationError: If a sample's timeline differs from the
                frame's.
        """
        report = self.health(staleness_budget)
        return frozenset(
            modality for modality, health in report.items() if health is not StreamHealth.HEALTHY
        )

    @classmethod
    def build(
        cls,
        *,
        tick: TickId,
        fused_at: Instant,
        samples: Iterable[SensorSample[PayloadT]],
    ) -> FusedSensorFrame[PayloadT]:
        """Assemble a frame, deriving the absent set from the modalities supplied.

        Args:
            tick: The control tick this frame belongs to.
            fused_at: When fusion completed.
            samples: The readings collected this tick.

        Returns:
            A frame whose ``absent_modalities`` is every modality not supplied.

        Raises:
            ContractViolationError: If a modality is supplied more than once.
        """
        materialised = tuple(samples)
        present = {sample.modality for sample in materialised}
        absent = frozenset(set(SensorModality) - present)
        return cls(tick=tick, fused_at=fused_at, samples=materialised, absent_modalities=absent)
