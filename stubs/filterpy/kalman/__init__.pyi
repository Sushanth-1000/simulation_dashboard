"""The FilterPy surface the estimation layer depends on."""

from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

class MerweScaledSigmaPoints:
    """Van der Merwe's scaled sigma-point selection for the unscented transform."""

    n: int
    alpha: float
    beta: float
    kappa: float
    def __init__(
        self,
        n: int,
        alpha: float,
        beta: float,
        kappa: float,
        sqrt_method: Callable[[NDArray[np.float64]], NDArray[np.float64]] | None = ...,
        subtract: Callable[..., Any] | None = ...,
    ) -> None: ...
    def num_sigmas(self) -> int: ...
    def sigma_points(
        self, x: NDArray[np.float64], P: NDArray[np.float64]
    ) -> NDArray[np.float64]: ...

class UnscentedKalmanFilter:
    """The unscented Kalman filter."""

    x: NDArray[np.float64]
    P: NDArray[np.float64]
    Q: NDArray[np.float64]
    R: NDArray[np.float64]
    y: NDArray[np.float64]
    S: NDArray[np.float64]
    K: NDArray[np.float64]
    x_prior: NDArray[np.float64]
    P_prior: NDArray[np.float64]
    x_post: NDArray[np.float64]
    P_post: NDArray[np.float64]
    @property
    def mahalanobis(self) -> float: ...
    def __init__(
        self,
        dim_x: int,
        dim_z: int,
        dt: float,
        hx: Callable[..., NDArray[np.float64]],
        fx: Callable[..., NDArray[np.float64]],
        points: MerweScaledSigmaPoints,
        sqrt_fn: Callable[..., Any] | None = ...,
        x_mean_fn: Callable[..., Any] | None = ...,
        z_mean_fn: Callable[..., Any] | None = ...,
        residual_x: Callable[..., Any] | None = ...,
        residual_z: Callable[..., Any] | None = ...,
        state_add: Callable[..., Any] | None = ...,
    ) -> None: ...
    def predict(
        self,
        dt: float | None = ...,
        UT: Callable[..., Any] | None = ...,
        fx: Callable[..., NDArray[np.float64]] | None = ...,
        **fx_args: Any,
    ) -> None: ...
    def update(
        self,
        z: NDArray[np.float64],
        R: NDArray[np.float64] | float | None = ...,
        UT: Callable[..., Any] | None = ...,
        hx: Callable[..., NDArray[np.float64]] | None = ...,
        **hx_args: Any,
    ) -> None: ...
