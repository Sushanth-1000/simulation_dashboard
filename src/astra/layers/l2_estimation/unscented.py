"""The unscented transform, in this repository rather than in a 2018 dependency.

Why this exists
----------------
L2 was built on FilterPy's ``UnscentedKalmanFilter`` and
``MerweScaledSigmaPoints``. FilterPy's final release is **1.4.5, from 2018**; the
project is unmaintained. That is a problem in three separate ways, and only the
first is the obvious one:

1. **It sits inside the safety path.** ISO 26262 §8-12 asks for a qualification
   argument for a software component in that position, and "the upstream is
   gone" is a poor opening.
2. **It drags in a dependency tree nobody chose.** FilterPy requires `scipy`,
   which pulls `matplotlib` and `pillow`. Nothing in ``src/astra/`` imports any
   of the three -- they were transitive weight on a runtime that otherwise needs
   only NumPy -- and each is a separate qualification argument.
3. **The surface actually used was small.** Strict typing had forced its
   enumeration into a local stub directory: two classes and about a dozen
   attributes. A qualification argument for a 2018 dependency was always
   going to cost more than writing the two hundred lines it stands in for,
   and the stub directory is deleted along with the dependency.

What this is, and what it deliberately is not
-----------------------------------------------
This is **FilterPy's algorithm, reimplemented to match it** -- not a better UKF.
Where a choice was available, the one FilterPy makes was taken, including one
that is arguably worse:

    The Kalman gain is computed as ``Pxz @ inv(S)``, inverting the innovation
    covariance explicitly. ``np.linalg.solve`` would be better conditioned and
    is what a fresh implementation should use.

That is on purpose. Replacing a library and improving its numerics in the same
change makes any difference in the results unattributable to either -- and this
filter's outputs are what `EVIDENCE.md` rests on, down to veto counts that are
threshold crossings and can flip on the last bit. **Swapping to ``solve`` is a
separate change, and one that can be measured against this one.**

The equations
--------------
Van der Merwe's scaled sigma points, for state dimension ``n``::

    lambda = alpha^2 (n + kappa) - n
    U      = chol((n + lambda) P)            (upper triangular)
    X_0    = x
    X_k    = x + U_k         for k in 1..n   (U_k is the k-th row of U)
    X_n+k  = x - U_k

with weights::

    Wm_0 = lambda / (n + lambda)
    Wc_0 = lambda / (n + lambda) + (1 - alpha^2 + beta)
    Wm_i = Wc_i = 1 / (2 (n + lambda))       for i > 0

The unscented transform of a sigma set through a function, with additive noise
``N``::

    mean = sum_i Wm_i Y_i
    cov  = sum_i Wc_i (Y_i - mean)(Y_i - mean)^T + N

Predict applies it to ``fx``; update applies it to ``hx`` and then corrects
through the cross-covariance ``Pxz``.

Fail-closed numerics
---------------------
Nothing here catches a numerical failure. ``np.linalg.cholesky`` raises
``LinAlgError`` on a covariance that has stopped being positive definite, and
that exception is allowed to propagate to
:meth:`~astra.layers.l2_estimation.filter.DualRateUKF._step`, which converts it
into a ``SafetyPathError`` and therefore into a VETO. A filter that quietly
repaired its own covariance would return a state estimate nobody could justify,
and the layer above would have no way to know.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import NDArray

__all__ = ["MerweScaledSigmaPoints", "UnscentedKalmanFilter", "unscented_transform"]


class MerweScaledSigmaPoints:
    """Van der Merwe's scaled sigma-point selection.

    Attributes:
        n: State dimension.
        alpha: Spread of the sigma points about the mean. Small and positive;
            the layer uses 1e-3, which keeps the points close enough that the
            transform stays a local linearisation.
        beta: Prior knowledge of the distribution. Two is optimal for Gaussian.
        kappa: Secondary scaling, conventionally ``0`` or ``3 - n``.
    """

    __slots__ = ("_lambda", "alpha", "beta", "kappa", "n")

    def __init__(self, n: int, alpha: float, beta: float, kappa: float) -> None:
        """Initialise the selection.

        Args:
            n: State dimension.
            alpha: Spread parameter.
            beta: Distribution parameter.
            kappa: Secondary scaling parameter.
        """
        self.n = n
        self.alpha = alpha
        self.beta = beta
        self.kappa = kappa
        self._lambda = alpha * alpha * (n + kappa) - n

    def num_sigmas(self) -> int:
        """Return the number of sigma points, ``2n + 1``."""
        return 2 * self.n + 1

    def sigma_points(
        self, x: NDArray[np.float64], covariance: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Return the ``2n + 1`` sigma points for a mean and covariance.

        Args:
            x: The state mean, shape ``(n,)``.
            covariance: The state covariance, shape ``(n, n)``.

        Returns:
            The sigma points, shape ``(2n + 1, n)``, with the mean first.

        Raises:
            LinAlgError: If the covariance is not positive definite. Deliberately
                uncaught -- see the module docstring.
        """
        mean = np.asarray(x, dtype=np.float64).reshape(self.n)
        scaled = (self.n + self._lambda) * np.asarray(covariance, dtype=np.float64)
        # NumPy's factor is lower triangular and FilterPy takes rows of the
        # upper one, so transpose. Row k of U is column k of L, which is the
        # same vector -- the transpose is about indexing, not about the maths.
        upper = np.linalg.cholesky(scaled).T

        points = np.zeros((self.num_sigmas(), self.n), dtype=np.float64)
        points[0] = mean
        for k in range(self.n):
            points[k + 1] = mean + upper[k]
            points[self.n + k + 1] = mean - upper[k]
        return points

    def weights(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Return the mean and covariance weights, in that order.

        Returns:
            ``(Wm, Wc)``, each of shape ``(2n + 1,)``. They differ only in the
            first entry, and only by ``1 - alpha^2 + beta``.
        """
        count = self.num_sigmas()
        shared = 0.5 / (self.n + self._lambda)
        mean_weights = np.full(count, shared, dtype=np.float64)
        covariance_weights = np.full(count, shared, dtype=np.float64)
        mean_weights[0] = self._lambda / (self.n + self._lambda)
        covariance_weights[0] = mean_weights[0] + (1.0 - self.alpha * self.alpha + self.beta)
        return mean_weights, covariance_weights


def unscented_transform(
    sigmas: NDArray[np.float64],
    mean_weights: NDArray[np.float64],
    covariance_weights: NDArray[np.float64],
    noise: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return the weighted mean and covariance of a transformed sigma set.

    Args:
        sigmas: The transformed points, shape ``(m, d)``.
        mean_weights: ``Wm``, shape ``(m,)``.
        covariance_weights: ``Wc``, shape ``(m,)``.
        noise: Additive noise covariance, shape ``(d, d)``.

    Returns:
        ``(mean, covariance)``.
    """
    mean = mean_weights @ sigmas
    residual = sigmas - mean[np.newaxis, :]
    # Associated as `y.T @ (diag(Wc) @ y)` rather than the cheaper
    # `(y.T * Wc) @ y`. They are the same identity and they round differently,
    # and matching the association this replaces is worth more here than saving
    # one temporary -- see the module docstring on why the swap is measured
    # rather than improved.
    covariance = residual.T @ (np.diag(covariance_weights) @ residual) + noise
    return mean, covariance


class UnscentedKalmanFilter:
    """A dual-purpose UKF matching the surface L2 depended on.

    Attributes:
        x: The state mean. Written directly by the composition root at
            construction, which is why it is public.
        P: The state covariance.
        Q: Process noise.
        R: Default measurement noise, overridable per update.
        y: The innovation from the last update, ``z - h(x)``.
        S: The innovation covariance from the last update.
        K: The Kalman gain from the last update.
    """

    # No `__slots__`, deliberately, and it is the one place this file departs
    # from the house style. Two of these exist per pipeline and both are built
    # once at assembly, so the memory a slots layout would save is two
    # dictionaries -- while the seven tests that pin L2's fail-closed behaviour
    # inject numerical failures by replacing a bound method on the instance,
    # which slots forbid. Those tests are the *specification* of "anything
    # numerically wrong here becomes a VETO", and rewriting them to accommodate
    # an implementation detail of their subject would be the tail wagging the
    # dog. The object this replaces was patchable; so is this one.

    def __init__(
        self,
        *,
        dim_x: int,
        dim_z: int,
        dt: float,
        hx: Callable[..., NDArray[np.float64]],
        fx: Callable[..., NDArray[np.float64]],
        points: MerweScaledSigmaPoints,
    ) -> None:
        """Initialise the filter with an identity state and covariance.

        Args:
            dim_x: State dimension.
            dim_z: Default measurement dimension.
            dt: The timestep passed to ``fx``.
            hx: Observation function, ``h(state) -> measurement``.
            fx: Process model, ``f(state, dt) -> state``.
            points: The sigma-point selection.
        """
        self._dim_x = dim_x
        self._dim_z = dim_z
        self._dt = dt
        self._hx = hx
        self._fx = fx
        self._points = points
        self._mean_weights, self._covariance_weights = points.weights()

        self.x = np.zeros(dim_x, dtype=np.float64)
        self.P = np.eye(dim_x, dtype=np.float64)
        self.Q = np.eye(dim_x, dtype=np.float64)
        self.R = np.eye(dim_z, dtype=np.float64)
        self.y = np.zeros(dim_z, dtype=np.float64)
        self.S = np.eye(dim_z, dtype=np.float64)
        self.K = np.zeros((dim_x, dim_z), dtype=np.float64)
        self._sigmas_f = np.zeros((points.num_sigmas(), dim_x), dtype=np.float64)

    @property
    def mahalanobis(self) -> float:
        """Return the last innovation's Mahalanobis distance under ``S``.

        The statistic L3's Trust Index and L6's covariate-shift window are both
        computed from -- and, since audit schema v5, the one quantity in the
        decision record that can *disagree* with the state estimate, because it
        is taken before the filter settles rather than after.

        Returns:
            ``sqrt(y^T S^-1 y)``.
        """
        return float(np.sqrt(self.y @ np.linalg.inv(self.S) @ self.y))

    def predict(self) -> None:
        """Advance the state through the process model by one timestep.

        **The sigma points are redrawn after the transform, and that is the one
        place this class deliberately departs from FilterPy** (OD-10, ADR-0032).

        FilterPy leaves ``sigmas_f`` holding the points *propagated through*
        ``fx``, whose spread is the transform's covariance **before** ``Q`` is
        added. :meth:`update` then observes that stale set, so the innovation
        covariance comes out as ``H (P - Q) Hᵀ + R`` -- short by exactly the
        process-noise term. Every Mahalanobis distance the filter has ever
        reported was inflated by the shortfall: measured, **1.24x at the
        median** (E-71).

        A UKF has no ``H`` to add ``H Q Hᵀ`` with -- not having one is the whole
        point of the sigma-point formulation -- so the term cannot be bolted on.
        Redrawing from the ``Q``-inflated ``P`` is how the textbook formulation
        carries it, and it puts the process noise into the measurement sigma set
        where the transform can find it.

        **It also changes the gain, and that is correct rather than incidental.**
        The cross-covariance is accumulated from the same points, so it becomes
        ``P Hᵀ`` with the predicted covariance rather than the pre-noise one --
        which is what the Kalman gain is defined against. A fix that corrected
        ``S`` and left the cross-covariance on the old sigma set would have made
        the two inconsistent.

        Costs a second Cholesky factorisation per tick. On a 5x5 matrix at
        20 Hz that is not measurable against the sigma-point propagation it
        already does, and the module docstring's rule applies: this is a
        deviation from FilterPy, so it is made alone and measured.

        Raises:
            LinAlgError: If ``P`` has stopped being positive definite.
                Deliberately uncaught.
        """
        sigmas = self._points.sigma_points(self.x, self.P)
        propagated = np.array([self._fx(point, self._dt) for point in sigmas], dtype=np.float64)
        self.x, self.P = unscented_transform(
            propagated, self._mean_weights, self._covariance_weights, self.Q
        )
        self._sigmas_f = self._points.sigma_points(self.x, self.P)

    def update(
        self,
        z: NDArray[np.float64],
        *,
        R: NDArray[np.float64] | None = None,
        hx: Callable[..., NDArray[np.float64]] | None = None,
    ) -> None:
        """Correct the predicted state with a measurement.

        The observation function is overridable per call because a measurement
        need not cover the whole state: L2 passes ``state[indices]``, so the
        measurement dimension varies with what the extractor produced this tick
        and is taken from the transformed sigma points rather than declared.

        Args:
            z: The measurement.
            R: Measurement noise for this update, or ``None`` for :attr:`R`.
            hx: Observation function for this update, or ``None`` for the one
                given at construction.

        Raises:
            LinAlgError: If the innovation covariance is singular. Deliberately
                uncaught.
        """
        observe = self._hx if hx is None else hx
        noise = self.R if R is None else np.asarray(R, dtype=np.float64)
        measurement = np.asarray(z, dtype=np.float64)

        sigmas_h = np.array([observe(point) for point in self._sigmas_f], dtype=np.float64)
        predicted, innovation_covariance = unscented_transform(
            sigmas_h, self._mean_weights, self._covariance_weights, noise
        )

        # Accumulated as a sum of weighted outer products, in index order,
        # for the same reason: it is what this replaces, and a matrix product
        # sums in a different order and lands a nanosecond of state away.
        cross = np.zeros((self._dim_x, sigmas_h.shape[1]), dtype=np.float64)
        for index in range(self._sigmas_f.shape[0]):
            cross += self._covariance_weights[index] * np.outer(
                self._sigmas_f[index] - self.x, sigmas_h[index] - predicted
            )
        # `inv` rather than `solve`, matching FilterPy exactly. See the module
        # docstring: improving this is a separate change so that its effect can
        # be measured rather than absorbed into a library swap.
        gain = cross @ np.linalg.inv(innovation_covariance)

        self.y = measurement - predicted
        self.S = innovation_covariance
        self.K = gain
        self.x = self.x + gain @ self.y
        # `K @ (S @ K.T)`, not `(K @ S) @ K.T`. Same identity, different
        # rounding, and the right-associated form is the one this replaces.
        self.P = self.P - gain @ (innovation_covariance @ gain.T)
