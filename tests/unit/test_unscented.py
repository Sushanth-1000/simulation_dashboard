"""Does the first-party UKF do what the one it replaced did?

Why this file exists
---------------------
L2 ran on FilterPy for the project's whole life, and FilterPy's outputs are what
`EVIDENCE.md` rests on. Replacing it is therefore not a refactor -- it is a
change to the thing every gate reads, and the risk is not that it breaks loudly
but that it agrees to nine decimal places and disagrees on the tenth, at exactly
one threshold crossing, in a run nobody re-measures.

Two kinds of test answer that, and both are needed:

**Against the mathematics**, here. The unscented transform of a linear map *is*
that map, so on a linear system ``predict`` has a closed form to check against
that owes nothing to FilterPy or to this implementation -- the check that would
survive both being wrong in the same way.

Writing that test found something. The *update* does **not** reproduce the
linear Kalman filter, because it reuses the sigma points ``predict`` pushed
through ``fx`` -- whose spread is ``F P F^T``, without the ``Q`` that predict
added analytically. The innovation covariance is therefore short by ``H Q H^T``,
and at this project's noise settings that is not a rounding matter: it inflates
the Mahalanobis distance by up to 22x on one channel. That is OD-10, it is
inherited from the library rather than introduced by the port, and
:func:`test_the_innovation_covariance_omits_the_process_noise_term` pins it so
that changing it has to be a decision.

**Against the recorded numbers**, in the benchmarks. E-68 records that the fault
study and the comparison harness reproduce every figure they produced under
FilterPy, which is the check that matters for the evidence pack.

What is deliberately not asserted
----------------------------------
Bit-identity with FilterPy. It is not reachable: FilterPy factors covariance
with SciPy's upper-triangular Cholesky and this uses NumPy's lower-triangular
one, and the two LAPACK paths round differently in the last places. Measured
over 2,000 predict/update steps the state agrees to **6e-10** and the covariance
to **1e-14** -- and eliminating even that would mean keeping SciPy, which is the
dependency being removed. What matters is whether the difference changes a
decision, and E-68 measures that it does not.
"""

from __future__ import annotations

import numpy as np
import pytest

from astra.layers.l2_estimation.unscented import (
    MerweScaledSigmaPoints,
    UnscentedKalmanFilter,
    unscented_transform,
)

ALPHA, BETA, KAPPA = 1e-3, 2.0, 0.0


def points(n: int) -> MerweScaledSigmaPoints:
    return MerweScaledSigmaPoints(n=n, alpha=ALPHA, beta=BETA, kappa=KAPPA)


# --------------------------------------------------------------------------- #
# Sigma points
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("n", [1, 3, 5, 8])
def test_there_are_two_n_plus_one_sigma_points(n: int) -> None:
    selection = points(n)
    generated = selection.sigma_points(np.zeros(n), np.eye(n))

    assert selection.num_sigmas() == 2 * n + 1
    assert generated.shape == (2 * n + 1, n)


def test_the_first_sigma_point_is_the_mean() -> None:
    mean = np.array([1.0, -2.0, 3.5])

    generated = points(3).sigma_points(mean, np.eye(3))

    assert np.array_equal(generated[0], mean)


def test_the_sigma_points_are_symmetric_about_the_mean() -> None:
    # Each `+U_k` point has a `-U_k` twin, so the weighted mean of the set is
    # the mean it was built from. A selection that lost that symmetry would
    # bias every estimate without failing anything else.
    n = 4
    mean = np.array([0.5, -1.0, 2.0, 0.25])
    covariance = np.diag([0.4, 0.1, 0.9, 0.2]) + 0.05

    generated = points(n).sigma_points(mean, covariance)

    for k in range(n):
        assert np.allclose(generated[k + 1] - mean, -(generated[n + k + 1] - mean))


def test_the_weighted_mean_of_the_sigma_points_recovers_the_mean() -> None:
    mean = np.array([3.0, -1.5, 0.0])
    covariance = np.diag([0.3, 0.7, 0.2]) + 0.01
    selection = points(3)

    generated = selection.sigma_points(mean, covariance)
    mean_weights, _ = selection.weights()

    assert np.allclose(mean_weights @ generated, mean)


def test_the_weighted_covariance_of_the_sigma_points_recovers_the_covariance() -> None:
    mean = np.array([1.0, 2.0])
    covariance = np.array([[0.5, 0.1], [0.1, 0.3]])
    selection = points(2)

    generated = selection.sigma_points(mean, covariance)
    mean_weights, covariance_weights = selection.weights()
    _, recovered = unscented_transform(
        generated, mean_weights, covariance_weights, np.zeros((2, 2))
    )

    assert np.allclose(recovered, covariance)


def test_the_mean_weights_sum_to_one() -> None:
    mean_weights, _ = points(5).weights()

    assert mean_weights.sum() == pytest.approx(1.0)


def test_a_covariance_that_is_not_positive_definite_raises_rather_than_repairing() -> None:
    # Fail-closed. `DualRateUKF._step` turns this into a SafetyPathError and
    # therefore a VETO. A filter that quietly repaired its own covariance would
    # hand back an estimate nobody could justify and the layer above would have
    # no way to know.
    with pytest.raises(np.linalg.LinAlgError):
        points(2).sigma_points(np.zeros(2), np.array([[1.0, 2.0], [2.0, 1.0]]))


# --------------------------------------------------------------------------- #
# The filter, against a closed form that owes nothing to either implementation
# --------------------------------------------------------------------------- #


def test_the_prediction_step_matches_the_linear_kalman_filter_exactly() -> None:
    # The unscented transform of a linear map *is* that map, so on a linear
    # system predict must agree with `F P F^T + Q` to machine precision. This
    # is the assertion that would catch this implementation and the one it
    # replaced being wrong in the same way, because it owes nothing to either.
    dt = 0.1
    transition = np.array([[1.0, dt], [0.0, 1.0]])
    process_noise = np.eye(2) * 1e-3

    filter_ = UnscentedKalmanFilter(
        dim_x=2,
        dim_z=1,
        dt=dt,
        hx=lambda state: state[[0]],
        fx=lambda state, step: np.array([[1.0, step], [0.0, 1.0]]) @ state,
        points=points(2),
    )
    filter_.x = np.array([0.0, 1.0])
    filter_.P = np.eye(2) * 0.5
    filter_.Q = process_noise.copy()
    x, covariance = filter_.x.copy(), filter_.P.copy()

    filter_.predict()

    assert np.allclose(filter_.x, transition @ x, atol=1e-14)
    assert np.allclose(
        filter_.P, transition @ covariance @ transition.T + process_noise, atol=1e-14
    )


def test_the_innovation_covariance_omits_the_process_noise_term() -> None:
    """Pin a real characteristic of this formulation, so it cannot change silently.

    The update reuses the sigma points that ``predict`` pushed through ``fx``,
    whose spread is ``F P F^T`` -- **without** ``Q``, which ``predict`` adds
    analytically to the covariance rather than into the points. So the
    innovation covariance is ``H (F P F^T) H^T + R``, understating the textbook
    ``H (F P F^T + Q) H^T + R`` by exactly ``H Q H^T``.

    This is what the library being replaced did, and reproducing it is the
    point (see the module docstring). It is **not** free: the Mahalanobis
    distance is inflated in consequence, and at this project's process- and
    measurement-noise settings that inflation is large. Recorded as OD-10 with
    the numbers, and asserted here so that changing the formulation has to be a
    decision rather than a drift.
    """
    dt = 0.1
    transition = np.array([[1.0, dt], [0.0, 1.0]])
    observation = np.array([[1.0, 0.0]])
    process_noise = np.eye(2) * 1e-3
    measurement_noise = np.array([[0.05]])

    filter_ = UnscentedKalmanFilter(
        dim_x=2,
        dim_z=1,
        dt=dt,
        hx=lambda state: observation @ state,
        fx=lambda state, step: np.array([[1.0, step], [0.0, 1.0]]) @ state,
        points=points(2),
    )
    filter_.x = np.array([0.0, 1.0])
    filter_.P = np.eye(2) * 0.5
    filter_.Q = process_noise.copy()
    prior_covariance = transition @ filter_.P @ transition.T

    filter_.predict()
    filter_.update(np.array([0.0]), R=measurement_noise)

    without_q = observation @ prior_covariance @ observation.T + measurement_noise
    with_q = observation @ (prior_covariance + process_noise) @ observation.T + measurement_noise

    assert np.allclose(filter_.S, without_q, atol=1e-12)
    assert not np.allclose(filter_.S, with_q, atol=1e-6)


def test_predicting_without_correcting_widens_the_covariance() -> None:
    # The response to a tick where every sensor was absent, and the reason L2
    # advances the filter on a frame it got no measurement from: the widened
    # covariance propagates into the ICP gate's sigma(x).
    filter_ = UnscentedKalmanFilter(
        dim_x=2,
        dim_z=2,
        dt=0.1,
        hx=lambda state: state,
        fx=lambda state, step: state + np.array([step, 0.0]),
        points=points(2),
    )
    filter_.P = np.eye(2) * 0.1
    filter_.Q = np.eye(2) * 0.01
    before = np.trace(filter_.P)

    filter_.predict()

    assert np.trace(filter_.P) > before


def test_correcting_narrows_the_covariance() -> None:
    filter_ = UnscentedKalmanFilter(
        dim_x=2,
        dim_z=2,
        dt=0.1,
        hx=lambda state: state,
        fx=lambda state, step: state * (1.0 + 0.0 * step),
        points=points(2),
    )
    filter_.P = np.eye(2) * 0.5
    filter_.Q = np.eye(2) * 1e-6

    filter_.predict()
    widened = np.trace(filter_.P)
    filter_.update(np.zeros(2), R=np.eye(2) * 0.01)

    assert np.trace(filter_.P) < widened


def test_the_covariance_stays_symmetric_over_many_steps() -> None:
    # Asymmetry accumulating in P is the classic way a UKF stops being a UKF:
    # the next Cholesky either fails or silently factors something that is no
    # longer a covariance.
    rng = np.random.default_rng(20260810)
    filter_ = UnscentedKalmanFilter(
        dim_x=3,
        dim_z=3,
        dt=0.05,
        hx=lambda state: state,
        fx=lambda state, step: state + step * np.array([state[1], -state[0], 0.05]),
        points=points(3),
    )
    filter_.P = np.eye(3) * 0.2
    filter_.Q = np.eye(3) * 1e-4

    for _ in range(300):
        filter_.predict()
        filter_.update(rng.normal(size=3) * 0.1, R=np.eye(3) * 0.05)
        assert np.allclose(filter_.P, filter_.P.T, atol=1e-12)


def test_a_partial_observation_updates_only_what_it_observes() -> None:
    # L2 passes `state[indices]`, so the measurement dimension varies with what
    # the extractor produced. The unobserved dimension must still be reachable
    # through the covariance rather than frozen.
    filter_ = UnscentedKalmanFilter(
        dim_x=3,
        dim_z=3,
        dt=0.1,
        hx=lambda state: state,
        fx=lambda state, step: state + 0.0 * step,
        points=points(3),
    )
    filter_.x = np.array([0.0, 0.0, 0.0])
    filter_.P = np.eye(3) * 0.4
    filter_.Q = np.eye(3) * 1e-6

    prior = filter_.P[0, 0] + filter_.Q[0, 0]
    filter_.predict()
    filter_.update(np.array([5.0]), R=np.array([[0.01]]), hx=lambda state: state[[0]])

    # The gain is P/(P+R), not 1 -- the filter moves most of the way to a
    # measurement it trusts forty times more than its prior, and no further.
    expected = 5.0 * (prior - filter_.Q[0, 0]) / (prior - filter_.Q[0, 0] + 0.01)
    assert filter_.x[0] == pytest.approx(expected, rel=1e-6)
    assert filter_.x[1] == pytest.approx(0.0, abs=1e-6)
    assert filter_.x[2] == pytest.approx(0.0, abs=1e-6)


def test_the_mahalanobis_distance_is_zero_when_the_measurement_was_predicted() -> None:
    filter_ = UnscentedKalmanFilter(
        dim_x=2,
        dim_z=2,
        dt=0.1,
        hx=lambda state: state,
        fx=lambda state, step: state + 0.0 * step,
        points=points(2),
    )
    filter_.x = np.array([1.0, 2.0])
    filter_.P = np.eye(2) * 0.1
    filter_.Q = np.eye(2) * 1e-9

    filter_.predict()
    filter_.update(np.array([1.0, 2.0]), R=np.eye(2) * 0.01)

    assert filter_.mahalanobis == pytest.approx(0.0, abs=1e-9)


def test_the_mahalanobis_distance_grows_with_the_innovation() -> None:
    def distance(offset: float) -> float:
        filter_ = UnscentedKalmanFilter(
            dim_x=2,
            dim_z=2,
            dt=0.1,
            hx=lambda state: state,
            fx=lambda state, step: state + 0.0 * step,
            points=points(2),
        )
        filter_.x = np.array([0.0, 0.0])
        filter_.P = np.eye(2) * 0.1
        filter_.Q = np.eye(2) * 1e-9
        filter_.predict()
        filter_.update(np.array([offset, 0.0]), R=np.eye(2) * 0.01)
        return filter_.mahalanobis

    assert distance(0.5) < distance(1.0) < distance(4.0)


def test_the_innovation_is_the_measurement_minus_the_prediction() -> None:
    filter_ = UnscentedKalmanFilter(
        dim_x=2,
        dim_z=2,
        dt=0.1,
        hx=lambda state: state,
        fx=lambda state, step: state + 0.0 * step,
        points=points(2),
    )
    filter_.x = np.array([1.0, 1.0])
    filter_.P = np.eye(2) * 0.1
    filter_.Q = np.eye(2) * 1e-9

    filter_.predict()
    filter_.update(np.array([3.0, 1.0]), R=np.eye(2) * 0.01)

    assert filter_.y == pytest.approx(np.array([2.0, 0.0]), abs=1e-6)
