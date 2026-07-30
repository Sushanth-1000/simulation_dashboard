"""L2 contracts: the dual-rate UKF's outputs.

Everything downstream reads these records and nothing else. That single fact is
what makes L2 the most correctness-critical layer in the system, and also what
makes the shared state estimate the residual common-cause channel the papers
acknowledge across all three Core-B gates.

Two record types rather than one
--------------------------------
The fast and slow filters could share a generic ``StateEstimate`` carrying a
layout discriminator. They do not, deliberately. The fast state
``[px, py, v, psi, a_lat]`` and the slow state
``[mu_road, delta_tyre, rho_sensor]`` are consumed by different layers for
different purposes, and separate types give each one *named, unit-typed
accessors*. ``estimate.speed`` returning ``MetresPerSecond`` is checkable;
``estimate.mean[2]`` is a comment about an index, and an off-by-one there would
feed the Hard Safety Shield a heading where it expected a speed and still
produce a plausible number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra.kernel.constants import (
    FAST_STATE_DIMENSION,
    FAST_STATE_FIELDS,
    SLOW_STATE_DIMENSION,
    SLOW_STATE_FIELDS,
)
from astra.kernel.enums import LayerId
from astra.kernel.errors import ContractViolationError, DimensionMismatchError
from astra.kernel.units import (
    Dimensionless,
    Metres,
    MetresPerSecond,
    MetresPerSecondSquared,
    Probability,
    Radians,
)
from astra.kernel.validation import require_dimension, require_non_negative

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.kernel.identifiers import TickId
    from astra.kernel.matrix import SymmetricMatrix
    from astra.kernel.time import Instant

__all__ = ["FastStateEstimate", "InnovationRecord", "SlowStateEstimate"]

# Index of the state dimension whose variance normalises the ICP non-conformity
# score. Resolved from the canonical field ordering rather than written as a
# literal, so that reordering the state vector cannot silently repoint it.
_LATERAL_ACCELERATION_INDEX = FAST_STATE_FIELDS.index("lateral_acceleration")
_SPEED_INDEX = FAST_STATE_FIELDS.index("speed")


def _validate_estimate(
    mean: Sequence[float],
    covariance: SymmetricMatrix,
    *,
    dimension: int,
    label: str,
) -> tuple[float, ...]:
    """Check that a mean vector and covariance describe the same state space.

    Args:
        mean: The state mean.
        covariance: The state covariance.
        dimension: The required dimension for this filter.
        label: Name used in error messages.

    Returns:
        The mean as an immutable tuple.

    Raises:
        DimensionMismatchError: If the mean or the covariance has the wrong
            dimension.
    """
    validated = require_dimension(
        mean, expected=dimension, name=f"{label}.mean", layer=LayerId.L2_DUAL_RATE_UKF
    )
    if covariance.dimension != dimension:
        message = (
            f"{label}.covariance is {covariance.dimension}x{covariance.dimension}, "
            f"expected {dimension}x{dimension}"
        )
        raise DimensionMismatchError(
            message,
            layer=LayerId.L2_DUAL_RATE_UKF,
            context={"expected": dimension, "actual": covariance.dimension},
        )
    return validated


@dataclass(frozen=True, slots=True)
class FastStateEstimate:
    """The 20 Hz filter's output: ``x_f = [px, py, v, psi, a_lat]`` with ``P_f``.

    Attributes:
        tick: The control tick this estimate belongs to.
        valid_at: The instant the estimate describes.
        mean: The state mean, ordered per
            :data:`~astra.kernel.constants.FAST_STATE_FIELDS`.
        covariance: ``P_f``. Supplied directly to the ICP gate, which takes the
            square root of one of its diagonal entries as ``sigma(x)``.
    """

    tick: TickId
    valid_at: Instant
    mean: tuple[float, ...]
    covariance: SymmetricMatrix

    def __post_init__(self) -> None:
        """Validate dimensions and the numerical admissibility of the covariance.

        The covariance is checked only against the cheap ``O(n)`` necessary
        condition -- no negative variances -- because this record is
        constructed on the hot path once per tick. A full definiteness test is
        available on the matrix itself for the filter's own periodic health
        check, which runs on the cold path.

        Raises:
            DimensionMismatchError: If mean and covariance disagree on
                dimension, or either is not five-dimensional.
            ContractViolationError: If any variance is negative, which means the
                filter has diverged rather than merely become uncertain.
        """
        object.__setattr__(
            self,
            "mean",
            _validate_estimate(
                self.mean, self.covariance, dimension=FAST_STATE_DIMENSION, label="fast_state"
            ),
        )
        if not self.covariance.has_admissible_diagonal():
            message = "fast filter covariance has a negative variance; the filter has diverged"
            raise ContractViolationError(
                message,
                layer=LayerId.L2_DUAL_RATE_UKF,
                context={"diagonal": list(self.covariance.diagonal)},
            )

    @property
    def position_x(self) -> Metres:
        """Return the longitudinal position ``px``."""
        return Metres(self.mean[0])

    @property
    def position_y(self) -> Metres:
        """Return the lateral position ``py``."""
        return Metres(self.mean[1])

    @property
    def speed(self) -> MetresPerSecond:
        """Return the ego speed ``v``."""
        return MetresPerSecond(self.mean[_SPEED_INDEX])

    @property
    def heading(self) -> Radians:
        """Return the heading ``psi``."""
        return Radians(self.mean[3])

    @property
    def lateral_acceleration(self) -> MetresPerSecondSquared:
        """Return the lateral acceleration ``a_lat``, the Hard Safety Shield's input."""
        return MetresPerSecondSquared(self.mean[_LATERAL_ACCELERATION_INDEX])

    def variance_of(self, field: str) -> float:
        """Return the marginal variance of one named state dimension.

        The accessor the ICP gate uses to obtain ``P_f[control dim]``. Naming
        the dimension rather than indexing it is what keeps the normalisation
        term bound to the physical quantity it is supposed to normalise.

        Args:
            field: A name from :data:`~astra.kernel.constants.FAST_STATE_FIELDS`.

        Returns:
            The variance of that dimension.

        Raises:
            ContractViolationError: If the field name is not part of the fast
                state layout.
        """
        try:
            index = FAST_STATE_FIELDS.index(field)
        except ValueError:
            message = f"{field!r} is not a fast state field; expected one of {FAST_STATE_FIELDS}"
            raise ContractViolationError(
                message, layer=LayerId.L2_DUAL_RATE_UKF, context={"field": field}
            ) from None
        return self.covariance.variance_of(index)


@dataclass(frozen=True, slots=True)
class SlowStateEstimate:
    """The 1 Hz (0.1 Hz in prototype) filter's output: degradation parameters.

    Tracks ``x_s = [mu_road, delta_tyre, rho_sensor]``. Consumed by the Hard
    Safety Shield, whose tyre-friction bound ``a_lat <= mu*g`` depends on the
    estimated road friction rather than a fixed constant, and by RCM, whose
    Runtime Context Signature includes aggregate sensor reliability.

    Attributes:
        tick: The control tick at which this estimate was last refreshed.
        valid_at: The instant the estimate describes.
        mean: The parameter mean, ordered per
            :data:`~astra.kernel.constants.SLOW_STATE_FIELDS`.
        covariance: The parameter covariance.
    """

    tick: TickId
    valid_at: Instant
    mean: tuple[float, ...]
    covariance: SymmetricMatrix

    def __post_init__(self) -> None:
        """Validate dimensions and covariance admissibility.

        Raises:
            DimensionMismatchError: If mean and covariance disagree on
                dimension, or either is not three-dimensional.
            ContractViolationError: If any variance is negative.
        """
        object.__setattr__(
            self,
            "mean",
            _validate_estimate(
                self.mean, self.covariance, dimension=SLOW_STATE_DIMENSION, label="slow_state"
            ),
        )
        if not self.covariance.has_admissible_diagonal():
            message = "slow filter covariance has a negative variance; the filter has diverged"
            raise ContractViolationError(
                message,
                layer=LayerId.L2_DUAL_RATE_UKF,
                context={"diagonal": list(self.covariance.diagonal)},
            )

    @property
    def road_friction_coefficient(self) -> Dimensionless:
        """Return ``mu_road``, the estimated tyre-road friction coefficient."""
        return Dimensionless(self.mean[0])

    @property
    def tyre_wear_index(self) -> Dimensionless:
        """Return ``delta_tyre``, the accumulated tyre wear index."""
        return Dimensionless(self.mean[1])

    @property
    def sensor_health_score(self) -> Probability:
        """Return ``rho_sensor``, the aggregate sensor health score in ``[0, 1]``."""
        return Probability(self.mean[SLOW_STATE_FIELDS.index("sensor_health_score")])


@dataclass(frozen=True, slots=True)
class InnovationRecord:
    """The filter's innovation ``nu_t = z_t - z_hat_t`` and its interpretation.

    The innovation sequence does double duty in ASTRA and both duties are
    safety-relevant, which is why it is a first-class record rather than an
    internal filter detail:

    * a Mahalanobis-distance spike above ``gamma`` raises a sensor-fault flag;
    * the rolling innovation distribution is the covariate-shift signal for the
      ICP gate -- a physics-grounded alternative to feature-space divergence.

    It is also the first line of defence against the acknowledged common-cause
    weakness: because all three gates read the same UKF state, an undetected
    filter divergence would degrade all three at once, and this monitor is what
    detects it independently.

    Attributes:
        tick: The control tick this innovation belongs to.
        residual: The measurement residual, one element per observed dimension.
        mahalanobis_distance: ``||nu_t||`` under the innovation covariance.
            Carried as a value rather than computed here because it requires an
            inverse that belongs in the filter.
        fault_flagged: Whether the distance exceeded the configured gate
            ``gamma``. The decision, not the threshold, is recorded: thresholds
            change between environments, and a record that only stored the
            distance could not be interpreted years later without also knowing
            which configuration was active.
    """

    tick: TickId
    residual: tuple[float, ...]
    mahalanobis_distance: float
    fault_flagged: bool

    def __post_init__(self) -> None:
        """Validate the innovation record.

        Raises:
            ContractViolationError: If the residual is empty.
            RangeViolationError: If the Mahalanobis distance is negative or not
                finite. A distance is a norm; a negative one indicates the
                covariance used to compute it was not positive definite.
        """
        if not self.residual:
            message = "innovation residual must have at least one element"
            raise ContractViolationError(message, layer=LayerId.L2_DUAL_RATE_UKF)
        object.__setattr__(self, "residual", tuple(self.residual))
        require_non_negative(
            self.mahalanobis_distance,
            name="innovation.mahalanobis_distance",
            layer=LayerId.L2_DUAL_RATE_UKF,
        )
