"""What the filter is told, and who translates a sensor payload into it.

The domain-independence problem this solves
--------------------------------------------
The filter needs numbers: "the observed speed is 12.4 m/s, with variance 0.05".
The sensor bus carries payloads: a LiDAR return, a CAN frame, a simulator
snapshot. Turning one into the other requires knowing what the payload *is*,
which is exactly the knowledge the core is forbidden to hold (NFR5).

:class:`MeasurementExtractor` is the seam. The adapter that owns the payload type
supplies it; the filter consumes only :class:`Measurement`, which is plain
numbers plus the state dimensions they observe. The result is that L2 contains no
reference to any sensor format, and a new platform is a new extractor rather than
a change to the filter.

Why observations are indices into a named layout
-------------------------------------------------
A general Kalman filter takes an arbitrary observation function ``h(x)``.
:class:`Measurement` restricts that to *selecting a subset of state dimensions*:
GPS observes position, a wheel encoder observes speed, an IMU observes lateral
acceleration. Every measurement the architecture describes is of this form.

The restriction buys a real safety property. An arbitrary callable ``h`` could
observe the wrong dimension and still produce plausible numbers -- the failure
mode the state-vector layouts in :mod:`astra.kernel.constants` exist to prevent.
A measurement therefore carries the *layout* it addresses, so an observation
built for the fast state can never be applied to the slow filter, and the field
names are resolvable for the audit record.

A future sensor needing a genuinely non-linear ``h`` will need this type
extended, and that will be a visible, reviewable change rather than a silent one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from astra.kernel.constants import FAST_STATE_FIELDS, SLOW_STATE_FIELDS
from astra.kernel.enums import LayerId
from astra.kernel.errors import ContractViolationError, DimensionMismatchError
from astra.kernel.validation import require_finite, require_positive

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.contracts.sensing import FusedSensorFrame

__all__ = [
    "Measurement",
    "MeasurementExtractor",
    "fast_measurement",
    "slow_measurement",
]


@dataclass(frozen=True, slots=True)
class Measurement:
    """An observation of a subset of one state vector, with its noise.

    Attributes:
        values: The observed values ``z``, in SI units, one per observed
            dimension.
        state_indices: Which dimensions of :attr:`layout` these observe. Must be
            strictly increasing, so a measurement cannot observe the same
            dimension twice and cannot depend on the order the extractor
            happened to assemble it in.
        noise_variances: The diagonal of ``R``, one variance per observed
            dimension. Strictly positive: a zero-variance measurement asserts a
            perfect sensor, which drives the Kalman gain to unity and lets one
            reading overwrite the filter's entire history.
        layout: The canonical field order these indices address. Carrying it
            makes applying a fast-state measurement to the slow filter a
            construction-time error rather than a silent misinterpretation.
    """

    values: tuple[float, ...]
    state_indices: tuple[int, ...]
    noise_variances: tuple[float, ...]
    layout: tuple[str, ...] = field(default=FAST_STATE_FIELDS)

    def __post_init__(self) -> None:
        """Validate the measurement's shape, indices and noise.

        Raises:
            ContractViolationError: If the three tuples disagree in length, if
                the measurement is empty, or if the indices are not strictly
                increasing.
            DimensionMismatchError: If an index falls outside the layout.
            NonFiniteValueError: If a value is NaN or infinite.
            RangeViolationError: If a noise variance is not strictly positive.
        """
        if not self.values:
            message = "a measurement must observe at least one state dimension"
            raise ContractViolationError(message, layer=LayerId.L2_DUAL_RATE_UKF)
        if not len(self.values) == len(self.state_indices) == len(self.noise_variances):
            message = (
                f"measurement has {len(self.values)} values, "
                f"{len(self.state_indices)} indices and "
                f"{len(self.noise_variances)} variances; all three must agree"
            )
            raise ContractViolationError(
                message,
                layer=LayerId.L2_DUAL_RATE_UKF,
                context={
                    "values": len(self.values),
                    "indices": len(self.state_indices),
                    "variances": len(self.noise_variances),
                },
            )
        self._validate_indices()
        for position, value in enumerate(self.values):
            require_finite(
                value,
                name=f"measurement.{self.layout[self.state_indices[position]]}",
                layer=LayerId.L2_DUAL_RATE_UKF,
            )
        for position, variance in enumerate(self.noise_variances):
            require_positive(
                variance,
                name=f"measurement_noise.{self.layout[self.state_indices[position]]}",
                layer=LayerId.L2_DUAL_RATE_UKF,
            )

    def _validate_indices(self) -> None:
        """Validate that the observed indices are in range and strictly increasing.

        Raises:
            DimensionMismatchError: If an index falls outside the layout.
            ContractViolationError: If the indices are not strictly increasing.
        """
        for position, index in enumerate(self.state_indices):
            if not 0 <= index < len(self.layout):
                message = (
                    f"measurement observes index {index}, which is outside the "
                    f"{len(self.layout)}-dimensional state {self.layout}"
                )
                raise DimensionMismatchError(
                    message,
                    layer=LayerId.L2_DUAL_RATE_UKF,
                    context={"index": index, "dimension": len(self.layout)},
                )
            if position > 0 and index <= self.state_indices[position - 1]:
                message = (
                    f"measurement state indices must be strictly increasing, "
                    f"got {list(self.state_indices)}"
                )
                raise ContractViolationError(
                    message,
                    layer=LayerId.L2_DUAL_RATE_UKF,
                    context={"indices": list(self.state_indices)},
                )

    @property
    def dimension(self) -> int:
        """Return how many state dimensions this measurement observes."""
        return len(self.values)

    @property
    def observed_fields(self) -> tuple[str, ...]:
        """Return the names of the observed state dimensions.

        Returns:
            The field names, for diagnostics and audit records. Reading a
            measurement as names rather than indices is what makes a mis-wired
            extractor visible in a log.
        """
        return tuple(self.layout[index] for index in self.state_indices)


def _build(
    observations: Sequence[tuple[str, float, float]],
    layout: tuple[str, ...],
) -> Measurement:
    """Assemble a measurement from named observations against one layout.

    Args:
        observations: ``(field name, value, variance)`` triples, in any order.
        layout: The canonical field order to resolve the names against.

    Returns:
        The measurement, with indices sorted into canonical order.

    Raises:
        ContractViolationError: If a name is not part of the layout, or the same
            field is observed twice.
    """
    resolved: list[tuple[int, float, float]] = []
    for name, value, variance in observations:
        try:
            index = layout.index(name)
        except ValueError:
            message = f"{name!r} is not a field of the state {layout}"
            raise ContractViolationError(
                message, layer=LayerId.L2_DUAL_RATE_UKF, context={"field": name}
            ) from None
        resolved.append((index, value, variance))

    resolved.sort(key=lambda entry: entry[0])
    indices = tuple(entry[0] for entry in resolved)
    if len(set(indices)) != len(indices):
        message = "a measurement cannot observe the same state field twice"
        raise ContractViolationError(
            message,
            layer=LayerId.L2_DUAL_RATE_UKF,
            context={"fields": [name for name, _, _ in observations]},
        )
    return Measurement(
        values=tuple(entry[1] for entry in resolved),
        state_indices=indices,
        noise_variances=tuple(entry[2] for entry in resolved),
        layout=layout,
    )


def fast_measurement(observations: Sequence[tuple[str, float, float]]) -> Measurement:
    """Build a fast-state measurement from ``(field, value, variance)`` triples.

    The form an extractor should prefer. Naming the field rather than indexing it
    means a reordering of the state vector cannot silently repoint an
    observation at a different physical quantity.

    Args:
        observations: One triple per observed dimension, in any order. Field
            names come from :data:`~astra.kernel.constants.FAST_STATE_FIELDS`.

    Returns:
        The measurement.

    Raises:
        ContractViolationError: If a field name is unknown or repeated.
    """
    return _build(observations, FAST_STATE_FIELDS)


def slow_measurement(observations: Sequence[tuple[str, float, float]]) -> Measurement:
    """Build a slow-state measurement from ``(field, value, variance)`` triples.

    Args:
        observations: One triple per observed dimension, in any order. Field
            names come from :data:`~astra.kernel.constants.SLOW_STATE_FIELDS`.

    Returns:
        The measurement.

    Raises:
        ContractViolationError: If a field name is unknown or repeated.
    """
    return _build(observations, SLOW_STATE_FIELDS)


@runtime_checkable
class MeasurementExtractor[PayloadT](Protocol):
    """Turns a fused sensor frame into the measurements the filter can consume.

    Supplied by the adapter that knows what a payload is. This is the only
    component in the estimation path permitted to read a raw payload, which is
    what keeps SI-1 true above L2.
    """

    def extract_fast(self, frame: FusedSensorFrame[PayloadT]) -> Measurement | None:
        """Derive the fast filter's measurement from one frame.

        Args:
            frame: The fused frame for this tick.

        Returns:
            A measurement over
            :data:`~astra.kernel.constants.FAST_STATE_FIELDS`, or ``None`` if no
            modality in this frame observed anything usable. ``None`` is a
            legitimate outcome, not an error: the filter then predicts without
            correcting, which is the right response to a tick where every sensor
            was absent.
        """
        ...

    def extract_slow(self, frame: FusedSensorFrame[PayloadT]) -> Measurement | None:
        """Derive the slow filter's measurement from one frame.

        Args:
            frame: The fused frame at the slow filter's cadence.

        Returns:
            A measurement over
            :data:`~astra.kernel.constants.SLOW_STATE_FIELDS`, or ``None`` if
            nothing observed a degradation parameter this tick.
        """
        ...
