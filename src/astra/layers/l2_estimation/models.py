"""The process models the two filters propagate state with.

Fast filter: a kinematic bicycle model
---------------------------------------
The fast state is ``[px, py, v, psi, a_lat]``. Between measurements it evolves
as a vehicle does:

.. code-block:: text

    px'    = px + v cos(psi) dt
    py'    = py + v sin(psi) dt
    v'     = v
    psi'   = psi + (a_lat / v) dt
    a_lat' = a_lat

Two of those lines deserve their reasoning stated.

**``v' = v`` and ``a_lat' = a_lat``.** Longitudinal acceleration and the rate of
change of lateral acceleration are not part of the state and are not measured, so
the model cannot predict them. Rather than invent a jerk term, the model holds
them constant and lets the process noise ``Q`` account for the discrepancy. That
is the honest formulation: ``Q`` is where "the model does not know" belongs, and
inflating the state with unobservable derivatives would produce confident
estimates of quantities nothing constrains.

**``psi' = psi + (a_lat / v) dt``.** For a vehicle in a steady turn the lateral
acceleration is ``a_lat = v * yaw_rate``, so the yaw rate is ``a_lat / v``. This
couples heading to lateral acceleration through actual physics rather than
treating the two as independent, which is what lets a lateral-acceleration
measurement correct the heading estimate at all.

The division is guarded. Below a configured speed the yaw rate is taken as zero:
at a standstill ``a_lat / v`` is numerically unbounded and physically
meaningless, and a filter that propagated it would inject an enormous heading
change on the tick a stopped vehicle registers any lateral noise.

Slow filter: a random walk
---------------------------
The slow state ``[mu_road, delta_tyre, rho_sensor]`` tracks degradation
processes. Nothing in the architecture describes their dynamics, and inventing a
decay model would be asserting physics the documents do not contain. They are
therefore modelled as a random walk -- ``x' = x``, with all of the movement in
``Q`` -- which says exactly what is known: these quantities drift, slowly, in no
predicted direction.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from astra.kernel.constants import FAST_STATE_FIELDS

if TYPE_CHECKING:
    from numpy.typing import NDArray

__all__ = ["fast_transition", "slow_transition"]

_PX = FAST_STATE_FIELDS.index("position_x")
_PY = FAST_STATE_FIELDS.index("position_y")
_V = FAST_STATE_FIELDS.index("speed")
_PSI = FAST_STATE_FIELDS.index("heading")
_A_LAT = FAST_STATE_FIELDS.index("lateral_acceleration")


def fast_transition(
    state: NDArray[np.float64], dt: float, *, yaw_rate_minimum_speed: float
) -> NDArray[np.float64]:
    """Propagate the fast kinematic state forward by one step.

    Args:
        state: The current fast state, ordered per
            :data:`~astra.kernel.constants.FAST_STATE_FIELDS`.
        dt: The step in seconds.
        yaw_rate_minimum_speed: Speed below which the yaw rate is taken as zero
            rather than computed from ``a_lat / v``.

    Returns:
        The propagated state, as a new array.
    """
    speed = float(state[_V])
    heading = float(state[_PSI])
    lateral_acceleration = float(state[_A_LAT])

    yaw_rate = 0.0 if abs(speed) < yaw_rate_minimum_speed else lateral_acceleration / speed

    return np.array(
        [
            state[_PX] + speed * math.cos(heading) * dt,
            state[_PY] + speed * math.sin(heading) * dt,
            speed,
            heading + yaw_rate * dt,
            lateral_acceleration,
        ],
        dtype=np.float64,
    )


def slow_transition(state: NDArray[np.float64], dt: float) -> NDArray[np.float64]:
    """Propagate the slow degradation state forward by one step.

    A random walk: the mean is unchanged and all of the evolution is carried by
    the process noise. ``dt`` is accepted to satisfy the filter's transition
    signature and is deliberately unused -- the drift is in ``Q``, not here.

    Args:
        state: The current slow state, ordered per
            :data:`~astra.kernel.constants.SLOW_STATE_FIELDS`.
        dt: The step in seconds. Unused.

    Returns:
        A copy of the state.
    """
    del dt
    return state.copy()
