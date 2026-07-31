"""The dual-rate UKF and its innovation monitor.

Why an unscented filter
------------------------
The fast process model is non-linear: heading integrates ``a_lat / v``, and
position integrates ``v`` through trigonometric functions of heading. An extended
Kalman filter would linearise those about the current estimate and accumulate the
error of that approximation exactly where the vehicle is turning hardest -- the
manoeuvres that matter most. The unscented transform propagates a deterministic
set of sigma points through the true non-linear model instead, which is accurate
to second order with no Jacobians to derive, hand-code and get wrong.

The scaled sigma points are van der Merwe's formulation of the Julier-Uhlmann
scaled unscented transform. ``alpha`` controls the spread about the mean,
``beta = 2`` is the standard choice for a Gaussian prior, and ``kappa = 0``
is the usual secondary scaling for a state of this size.

The innovation monitor is not a diagnostic
-------------------------------------------
All three Core-B gates read this filter's output, which the architecture
acknowledges as a genuine common-cause channel: if the filter silently diverges,
all three gates degrade together and their "independence" protects nothing. The
innovation sequence is the one signal that detects that from inside L2, because
it compares what the sensors said against what the model expected -- a
disagreement no downstream consumer of the state can see.

So the monitor is part of the layer. Its Mahalanobis distance raises a
sensor-fault flag above the configured gate, and the rolling innovation
distribution it maintains is the physics-grounded covariate-shift signal that
L6's detector will consume in Phase 5.

Fail-closed numerics
---------------------
A UKF can fail numerically: a covariance can lose positive definiteness through
accumulated round-off, and the Cholesky factorisation inside the sigma-point
generation then raises. That is a state-estimation failure, and a state estimate
that could not be computed must never be silently replaced by the previous one --
downstream gates would validate a command against a stale world. Every numerical
failure here is therefore converted to a :class:`~astra.kernel.errors.SafetyPathError`,
whose disposition is ``FAIL_CLOSED``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
from filterpy.kalman import MerweScaledSigmaPoints, UnscentedKalmanFilter

from astra.contracts.estimation import FastStateEstimate, InnovationRecord, SlowStateEstimate
from astra.kernel.constants import (
    FAST_STATE_DIMENSION,
    FAST_STATE_FIELDS,
    SLOW_STATE_DIMENSION,
    SLOW_STATE_FIELDS,
)
from astra.kernel.enums import LayerId
from astra.kernel.errors import ContractViolationError, SafetyPathError
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.validation import require_dimension, require_finite
from astra.layers.l2_estimation.models import fast_transition, slow_transition

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

    from astra.config.schema import EstimationSettings
    from astra.contracts.sensing import FusedSensorFrame
    from astra.kernel.identifiers import TickId
    from astra.layers.l2_estimation.measurement import Measurement, MeasurementExtractor

__all__ = ["DualRateUKF"]

_SIGMA_ALPHA: Final = 1e-3
"""Sigma-point spread. Small keeps the points close to the mean, which is
appropriate for a well-conditioned vehicle state."""

_SIGMA_BETA: Final = 2.0
"""Optimal for a Gaussian prior, per van der Merwe."""

_SIGMA_KAPPA: Final = 0.0
"""Secondary scaling. Zero is the standard choice for a state of this size."""

_INNOVATION_HISTORY_LIMIT: Final = 512
"""How many innovation records the rolling window retains for L6's
covariate-shift detector. Bounded so a long run cannot grow without limit."""


class DualRateUKF[PayloadT]:
    """Two unscented Kalman filters at different rates, plus an innovation monitor.

    Satisfies :class:`~astra.ports.pipeline.StateEstimator` structurally.

    Not thread-safe, deliberately. The filter is driven from the control thread
    only; adding a lock would put a synchronisation cost on the hot path to guard
    against a call pattern the architecture forbids.
    """

    __slots__ = (
        "_applied_lateral_acceleration",
        "_extractor",
        "_fast",
        "_fast_updates",
        "_innovation_history",
        "_latest_innovation",
        "_settings",
        "_slow",
        "_slow_updates",
    )

    def __init__(
        self,
        *,
        settings: EstimationSettings,
        extractor: MeasurementExtractor[PayloadT],
        initial_fast_state: Sequence[float],
        initial_fast_covariance: SymmetricMatrix,
        initial_slow_state: Sequence[float],
        initial_slow_covariance: SymmetricMatrix,
    ) -> None:
        """Build both filters from the configured operating point.

        Args:
            settings: The estimation settings, supplying rates, process noise
                and the innovation gate.
            extractor: Turns a fused frame into measurements. Adapter-supplied.
            initial_fast_state: The fast state mean at tick zero.
            initial_fast_covariance: ``P_f`` at tick zero. Must be positive
                definite: a singular initial covariance asserts that some
                direction of the state is known exactly, which for a filter that
                has seen no measurement is false.
            initial_slow_state: The slow state mean at tick zero.
            initial_slow_covariance: ``P_s`` at tick zero.

        Raises:
            DimensionMismatchError: If an initial state or covariance has the
                wrong dimension.
            ContractViolationError: If an initial covariance is not positive
                definite.
        """
        self._settings = settings
        self._extractor = extractor
        self._latest_innovation: InnovationRecord | None = None
        self._innovation_history: list[float] = []
        self._fast_updates = 0
        self._slow_updates = 0

        _require_positive_definite(initial_fast_covariance, label="initial fast covariance")
        _require_positive_definite(initial_slow_covariance, label="initial slow covariance")

        self._applied_lateral_acceleration: float | None = None
        fast_dt = 1.0 / settings.fast_rate_hz
        slow_dt = 1.0 / settings.slow_rate_hz
        minimum_speed = settings.yaw_rate_minimum_speed

        self._fast = UnscentedKalmanFilter(
            dim_x=FAST_STATE_DIMENSION,
            dim_z=FAST_STATE_DIMENSION,
            dt=fast_dt,
            hx=_identity_observation,
            fx=lambda state, dt: fast_transition(
                state,
                dt,
                yaw_rate_minimum_speed=minimum_speed,
                commanded_lateral_acceleration=self._applied_lateral_acceleration,
            ),
            points=MerweScaledSigmaPoints(
                n=FAST_STATE_DIMENSION, alpha=_SIGMA_ALPHA, beta=_SIGMA_BETA, kappa=_SIGMA_KAPPA
            ),
        )
        self._fast.x = _as_vector(initial_fast_state, FAST_STATE_DIMENSION, "initial_fast_state")
        self._fast.P = _as_matrix(initial_fast_covariance)
        self._fast.Q = np.diag(np.asarray(settings.fast_process_noise, dtype=np.float64))

        self._slow = UnscentedKalmanFilter(
            dim_x=SLOW_STATE_DIMENSION,
            dim_z=SLOW_STATE_DIMENSION,
            dt=slow_dt,
            hx=_identity_observation,
            fx=slow_transition,
            points=MerweScaledSigmaPoints(
                n=SLOW_STATE_DIMENSION, alpha=_SIGMA_ALPHA, beta=_SIGMA_BETA, kappa=_SIGMA_KAPPA
            ),
        )
        self._slow.x = _as_vector(initial_slow_state, SLOW_STATE_DIMENSION, "initial_slow_state")
        self._slow.P = _as_matrix(initial_slow_covariance)
        self._slow.Q = np.diag(np.asarray(settings.slow_process_noise, dtype=np.float64))

    # ----------------------------------------------------------------- #
    # StateEstimator protocol
    # ----------------------------------------------------------------- #

    def update_fast(self, frame: FusedSensorFrame[PayloadT]) -> FastStateEstimate:
        """Run the fast predict/update cycle for one tick.

        A frame from which the extractor derives no measurement still advances
        the filter: it predicts without correcting, which widens ``P_f`` and is
        exactly the right response to a tick where every sensor was absent. The
        widened covariance then propagates into the ICP gate's ``sigma(x)``, so
        the statistical gate automatically becomes more permissive precisely
        when the state is less certain -- which is the mechanism the paper
        describes, arising here rather than being special-cased.

        Args:
            frame: This tick's fused sensor frame.

        Returns:
            The updated fast estimate.

        Raises:
            SafetyPathError: If the filter could not complete its update, which
                the caller must treat as fail-closed.
        """
        measurement = self._extractor.extract_fast(frame)
        self._step(self._fast, measurement, label="fast", layout=FAST_STATE_FIELDS)
        self._fast_updates += 1
        if measurement is not None:
            self._record_innovation(frame.tick, measurement)
        return FastStateEstimate(
            tick=frame.tick,
            valid_at=frame.fused_at,
            mean=tuple(float(value) for value in self._fast.x),
            covariance=_to_symmetric(self._fast.P, label="fast covariance"),
        )

    def update_slow(self, frame: FusedSensorFrame[PayloadT]) -> SlowStateEstimate:
        """Run the slow predict/update cycle.

        Args:
            frame: The fused frame at the slow filter's cadence.

        Returns:
            The updated slow estimate.

        Raises:
            SafetyPathError: If the filter could not complete its update.
        """
        measurement = self._extractor.extract_slow(frame)
        self._step(self._slow, measurement, label="slow", layout=SLOW_STATE_FIELDS)
        self._slow_updates += 1
        return SlowStateEstimate(
            tick=frame.tick,
            valid_at=frame.fused_at,
            mean=tuple(float(value) for value in self._slow.x),
            covariance=_to_symmetric(self._slow.P, label="slow covariance"),
        )

    def apply_command(self, lateral_acceleration: float | None) -> None:
        """Tell the filter what the last issued command demands. Feedback loop FB1.

        Called by the pipeline after L9 has issued, so the *next* prediction
        propagates from the commanded lateral acceleration instead of assuming
        the last estimate persists.

        Deliberately a prediction input rather than a state assignment. Writing
        the commanded value into ``x`` would make the estimate agree with the
        command by construction, which destroys the innovation the whole system
        uses to detect that the vehicle is not doing what it was told -- the
        filter would report perfect health precisely when the actuator had
        failed. As a control input the covariance still grows around it and a
        measurement can still overrule it.

        Args:
            lateral_acceleration: The lateral acceleration implied by the issued
                command, or ``None`` when no command was issued. ``None``
                restores the constant-acceleration assumption, which is the
                right model for a tick on which nothing was commanded.

        Raises:
            NonFiniteValueError: If a non-finite value is supplied. A NaN would
                propagate into every sigma point and silently destroy the state.
        """
        if lateral_acceleration is not None:
            require_finite(
                lateral_acceleration,
                name="applied_lateral_acceleration",
                layer=LayerId.L2_DUAL_RATE_UKF,
            )
        self._applied_lateral_acceleration = lateral_acceleration

    @property
    def applied_lateral_acceleration(self) -> float | None:
        """Return the command input the next prediction will use, if any."""
        return self._applied_lateral_acceleration

    def latest_innovation(self) -> InnovationRecord | None:
        """Return the most recent innovation record.

        Returns:
            The latest record, or ``None`` before the first corrected update.
        """
        return self._latest_innovation

    # ----------------------------------------------------------------- #
    # Introspection
    # ----------------------------------------------------------------- #

    @property
    def innovation_history(self) -> tuple[float, ...]:
        """Return the rolling window of Mahalanobis distances.

        The physics-grounded covariate-shift signal L6's detector consumes: a
        distribution shift in the innovation sequence means the world has stopped
        matching the model, which is a statement about the operating context
        rather than about any single reading.

        Returns:
            The retained distances, oldest first.
        """
        return tuple(self._innovation_history)

    @property
    def fast_updates(self) -> int:
        """Return how many fast cycles have run."""
        return self._fast_updates

    @property
    def slow_updates(self) -> int:
        """Return how many slow cycles have run."""
        return self._slow_updates

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #

    def _step(
        self,
        filter_: UnscentedKalmanFilter,
        measurement: Measurement | None,
        *,
        label: str,
        layout: tuple[str, ...],
    ) -> None:
        """Predict, and correct if a measurement is available.

        Args:
            filter_: The filter to advance.
            measurement: The measurement, or ``None`` to predict only.
            label: Which filter, for diagnostics.
            layout: The state layout this filter tracks. A measurement built
                against a different one is refused.

        Raises:
            ContractViolationError: If the measurement addresses a different
                state layout than this filter tracks.
            SafetyPathError: If the numerics failed.
        """
        if measurement is not None and measurement.layout != layout:
            # The failure this prevents is silent and severe. A slow-state
            # measurement applied to the fast filter has indices 0, 1, 2 that
            # are perfectly valid there -- so nothing raises, and road friction
            # is written into the state as position and speed. Every gate above
            # L2 then reads a corrupted state, and the innovation monitor
            # reports it as an ordinary sensor fault rather than a wiring fault.
            # Carrying the layout is what makes this detectable; checking it
            # here is what makes carrying it worth anything.
            message = (
                f"the {label} filter tracks {layout}, but the extractor returned a "
                f"measurement against {measurement.layout}. Applying it would write "
                f"one physical quantity into another's state dimension"
            )
            raise ContractViolationError(
                message,
                layer=LayerId.L2_DUAL_RATE_UKF,
                context={
                    "filter": label,
                    "expected_layout": list(layout),
                    "measurement_layout": list(measurement.layout),
                },
            )
        try:
            filter_.predict()
            if measurement is not None:
                indices = list(measurement.state_indices)
                filter_.update(
                    np.asarray(measurement.values, dtype=np.float64),
                    R=np.diag(np.asarray(measurement.noise_variances, dtype=np.float64)),
                    hx=lambda state, indices=indices: state[indices],
                )
        except (
            np.linalg.LinAlgError,
            ValueError,
            ZeroDivisionError,
            IndexError,
            FloatingPointError,
        ) as error:
            # IndexError is caught alongside the numerical failures on purpose.
            # Anything that escapes this method uncaught escapes without a
            # SafetyDisposition, which means the caller's single reviewable
            # `except SafetyPathError` -- the whole basis of "anything wrong
            # here becomes a VETO" -- does not fire.
            message = (
                f"the {label} filter could not complete its update: {error}. "
                f"The state estimate for this tick does not exist, so the tick "
                f"must be treated as VETOed rather than reusing the previous state"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L2_DUAL_RATE_UKF,
                context={"filter": label, "error": str(error)},
            ) from error

    def _record_innovation(self, tick: TickId, measurement: Measurement) -> None:
        """Capture the innovation from the update just performed.

        Args:
            tick: The tick the innovation belongs to.
            measurement: The measurement that produced it, for field naming.
        """
        residual = tuple(float(value) for value in np.atleast_1d(self._fast.y))
        distance = float(self._fast.mahalanobis)
        if not np.isfinite(distance):
            # A non-finite Mahalanobis distance means the innovation covariance
            # was singular. That is a filter fault, and reporting it as a
            # distance of zero would mark a broken filter healthy.
            message = (
                "the innovation covariance is singular, so the Mahalanobis "
                "distance is not defined; the filter has diverged"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L2_DUAL_RATE_UKF,
                context={"observed_fields": list(measurement.observed_fields)},
            )
        self._innovation_history.append(distance)
        if len(self._innovation_history) > _INNOVATION_HISTORY_LIMIT:
            del self._innovation_history[0]
        self._latest_innovation = InnovationRecord(
            tick=tick,
            residual=residual,
            mahalanobis_distance=distance,
            fault_flagged=distance > self._settings.innovation_gate_gamma,
        )


def _identity_observation(state: NDArray[np.float64]) -> NDArray[np.float64]:
    """Observe the whole state.

    The filter's declared ``hx``. Every real update overrides it with a selector
    for the dimensions that measurement actually observes; this exists so the
    filter is constructible and is never used unmodified.

    Args:
        state: The state to observe.

    Returns:
        The state, unchanged.
    """
    return state


def _as_vector(values: Sequence[float], dimension: int, name: str) -> NDArray[np.float64]:
    """Convert a sequence to a validated NumPy state vector.

    Args:
        values: The values.
        dimension: The required length.
        name: Field name for diagnostics.

    Returns:
        The vector.

    Raises:
        DimensionMismatchError: If the length is wrong.
    """
    checked = require_dimension(
        values, expected=dimension, name=name, layer=LayerId.L2_DUAL_RATE_UKF
    )
    return np.asarray(checked, dtype=np.float64)


def _as_matrix(matrix: SymmetricMatrix) -> NDArray[np.float64]:
    """Expand a packed symmetric matrix into a dense NumPy array.

    The NumPy seam. The kernel deliberately holds no NumPy, so the conversion
    happens here, at the boundary of the layer that needs it.

    Args:
        matrix: The packed matrix.

    Returns:
        The dense array.
    """
    return np.asarray(matrix.to_rows(), dtype=np.float64)


def _to_symmetric(array: NDArray[np.float64], *, label: str) -> SymmetricMatrix:
    """Convert a NumPy covariance back into the packed immutable form.

    The filter's arithmetic leaves the covariance symmetric only to within
    round-off, so the array is symmetrised before packing. Averaging with the
    transpose is the standard treatment and is the operation that makes the
    packed representation -- in which asymmetry is unrepresentable -- an accurate
    record rather than an arbitrary choice of triangle.

    Args:
        array: The dense covariance.
        label: Name for diagnostics.

    Returns:
        The packed symmetric matrix.

    Raises:
        SafetyPathError: If the covariance contains a non-finite entry, which
            means the filter has diverged.
    """
    if not np.all(np.isfinite(array)):
        message = f"{label} contains a non-finite entry; the filter has diverged"
        raise SafetyPathError(message, layer=LayerId.L2_DUAL_RATE_UKF)
    symmetrised = (array + array.T) / 2.0
    return SymmetricMatrix.from_rows([[float(value) for value in row] for row in symmetrised])


def _require_positive_definite(matrix: SymmetricMatrix, *, label: str) -> None:
    """Reject an initial covariance that is not positive definite.

    Args:
        matrix: The covariance to check.
        label: Name for diagnostics.

    Raises:
        ContractViolationError: If the matrix is not positive definite.
    """
    if not matrix.is_positive_definite():
        message = (
            f"{label} is not positive definite; a singular covariance asserts that "
            f"some direction of the state is known exactly, which is false for a "
            f"filter that has seen no measurement"
        )
        raise ContractViolationError(
            message,
            layer=LayerId.L2_DUAL_RATE_UKF,
            context={"diagonal": list(matrix.diagonal)},
        )
