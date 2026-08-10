"""A warehouse AGV, to find out whether NFR5 is true.

The claim under test
---------------------
NFR5 says the platform core is domain-independent: the layers hold no knowledge
of vehicles, and a different platform is supplied entirely through adapters.
`ASSUMPTIONS.md` A-1 records it as **asserted, structurally defended, never
tested**, and `EVIDENCE.md` N-6 has said so since the pack was written.

`astra/runtime/assembly.py` states the claim in its own module docstring:

    *"``automotive_actuation_space`` is the single place where this codebase
    says a vehicle has a throttle... A different platform supplies a different
    space and no layer notices."*

This module is the attempt to be that different platform. It is a
**differential-drive warehouse AGV**: two wheels, commanded in rad/s, no
throttle, no brake pedal, no steering angle. It turns by driving its wheels at
different speeds. Nothing about it is a car.

The exit criterion from P3.4's sibling entry is exact: get it through the
pipeline **without touching ``src/astra/`` outside adapters**. Either the claim
is validated, or it is revealed to be automotive-shaped -- and `PENDING.md` says
the second is the more valuable outcome. It was the second.

What this found, in the order the walls arrived
-------------------------------------------------
Recorded here rather than only in `EVIDENCE.md` because the next person to try
this deserves the list before they start.

**Wall 1 -- the actuation space is not injectable.** ``assemble_pipeline`` calls
``automotive_actuation_space()`` directly. There is no parameter. The docstring
three hundred lines above says a different platform supplies a different space;
the composition root gives it no way to. This is the claim being contradicted
inside the same file that makes it.

**Wall 2 -- the command projector is automotive by construction.**
``AutomotiveCommandProjector`` divides a target lateral acceleration by a
steering effectiveness to get a steering angle. A differential-drive platform
has no steering angle: the same target is a *wheel-speed difference*. Also not
injectable.

**Wall 3 -- the process model in L2 is a bicycle model.**
``astra.layers.l2_estimation.models.fast_transition`` derives yaw rate from
``a_lat / v`` and takes a ``yaw_rate_minimum_speed`` below which it refuses to.
That is a car: an AGV's yaw rate is commanded directly and is well defined at
zero forward speed, which is exactly where a warehouse robot spends much of its
time -- turning on the spot. This is domain knowledge **inside a layer**, which
is the thing NFR5 forbids.

**Wall 4 -- the kernel names automotive quantities.**
``SLOW_STATE_FIELDS`` is ``("road_friction_coefficient", "tyre_wear_index",
"sensor_health_score")`` and ``ContextClass`` is ``HIGHWAY_CLEAR``,
``URBAN_CLEAR``, ``RAIN_NIGHT``. A warehouse has floors, not roads, and aisles,
not highways. These are cosmetic in a way walls 1-3 are not -- the *shapes* are
right, only the names are wrong -- but they are in ``astra.kernel``, which is
the layer with no dependencies and the strongest claim to neutrality.

The honest summary is that **NFR5 holds for the gates and fails for the
plumbing**. L3, L6, L7a and L7b genuinely do not care what platform they are
bounding; every one of their inputs is a number with a unit. What is
automotive is the *composition root*, the *process model* and the *vocabulary*,
and the first two are load-bearing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from astra.contracts.actuation import ActuationChannel, ActuationSpace

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

__all__ = [
    "AgvSpec",
    "DifferentialDriveProjector",
    "WarehouseAgv",
    "WarehousePolicy",
    "differential_drive_actuation_space",
]

LEFT_WHEEL, RIGHT_WHEEL = 0, 1

_STATIONARY_MPS = 1e-6
"""Below this the AGV is not moving forward, so a target lateral acceleration
has no wheel-speed difference that achieves it: yaw times zero speed is zero
acceleration whatever the wheels do. The car's projector has no equivalent
case because it steers by angle rather than by differential."""


def differential_drive_actuation_space() -> ActuationSpace:
    """Return the two-channel actuation space of a differential-drive AGV.

    Returns:
        Left and right wheel angular velocity, in radians per second. Two
        channels, not three; no throttle, no brake, no steering angle.
    """
    return ActuationSpace(
        (
            ActuationChannel(name="left_wheel", lower=-8.0, upper=8.0, unit="rad/s"),
            ActuationChannel(name="right_wheel", lower=-8.0, upper=8.0, unit="rad/s"),
        )
    )


@dataclass(frozen=True, slots=True)
class AgvSpec:
    """The platform constants of the AGV.

    Attributes:
        wheel_radius_m: Drive wheel radius.
        track_width_m: Distance between the wheel contact points. With the
            radius this fixes the whole kinematics: forward speed is the mean
            wheel speed times the radius, yaw rate is their difference times
            the radius over the track.
        aisle_half_width_m: The corridor the AGV must stay inside. A warehouse
            aisle, playing the part a lane plays for a car.
        speed_limit_mps: Site speed limit. Warehouses set these in m/s and
            they are far below any road limit.
        timestep_s: Control period.
    """

    wheel_radius_m: float = 0.1
    track_width_m: float = 0.5
    aisle_half_width_m: float = 0.6
    speed_limit_mps: float = 1.5
    timestep_s: float = 0.05

    def kinematics(self, left: float, right: float) -> tuple[float, float]:
        """Return ``(forward speed, yaw rate)`` for a pair of wheel speeds.

        Args:
            left: Left wheel angular velocity, rad/s.
            right: Right wheel angular velocity, rad/s.

        Returns:
            Forward speed in m/s and yaw rate in rad/s.
        """
        forward = self.wheel_radius_m * (right + left) / 2.0
        yaw = self.wheel_radius_m * (right - left) / self.track_width_m
        return forward, yaw


class WarehouseAgv:
    """A differential-drive plant, in the same shape the driving plant has.

    Deliberately minimal. The question this module asks is whether the
    *pipeline* accepts a non-automotive platform, and a more faithful AGV would
    not make that answer any clearer.
    """

    __slots__ = ("_spec", "_state")

    def __init__(self, spec: AgvSpec | None = None) -> None:
        """Initialise the AGV a little off the aisle centre line.

        Args:
            spec: The platform constants.
        """
        self._spec = spec or AgvSpec()
        # (x, y, speed, heading, lateral_acceleration), matching FAST_STATE_FIELDS.
        self._state = np.array([0.0, 0.3, 0.0, 0.0, 0.0], dtype=np.float64)

    @property
    def spec(self) -> AgvSpec:
        """Return the platform constants."""
        return self._spec

    @property
    def state(self) -> NDArray[np.float64]:
        """Return the true state."""
        return self._state.copy()

    def step(self, command: Sequence[float]) -> None:
        """Advance the AGV by one control period.

        Args:
            command: Left and right wheel angular velocity, rad/s.
        """
        spec = self._spec
        left = float(np.clip(command[LEFT_WHEEL], -8.0, 8.0))
        right = float(np.clip(command[RIGHT_WHEEL], -8.0, 8.0))
        forward, yaw = spec.kinematics(left, right)

        dt = spec.timestep_s
        heading = self._state[3] + yaw * dt
        # Yaw rate is commanded directly and is defined at zero forward speed --
        # an AGV turns on the spot, which the bicycle model in L2 cannot express.
        self._state[0] += forward * math.cos(heading) * dt
        self._state[1] += forward * math.sin(heading) * dt
        self._state[4] = forward * yaw
        self._state[2] = forward
        self._state[3] = heading


class DifferentialDriveProjector:
    """Turns a target lateral acceleration into a wheel-speed difference.

    The differential-drive counterpart of
    :class:`~astra.runtime.assembly.AutomotiveCommandProjector`, and the reason
    that class cannot simply be reused: it divides by a *steering
    effectiveness* to produce a steering angle, and this platform has no
    steering angle at all. The same physical intent -- "turn less hard" -- is a
    different arithmetic on a different channel pair.

    Attributes:
        spec: The platform constants.
    """

    __slots__ = ("spec",)

    def __init__(self, spec: AgvSpec) -> None:
        """Initialise the projector.

        Args:
            spec: The platform constants.
        """
        self.spec = spec

    def project(self, values: Sequence[float], *, lateral_acceleration: float) -> tuple[float, ...]:
        """Return the command achieving a target lateral acceleration.

        Args:
            values: The command to adjust, in actuation-space order.
            lateral_acceleration: The target.

        Returns:
            The adjusted wheel speeds, preserving forward speed.
        """
        left, right = float(values[LEFT_WHEEL]), float(values[RIGHT_WHEEL])
        forward, _ = self.spec.kinematics(left, right)
        if abs(forward) < _STATIONARY_MPS:
            return (left, right)
        target_yaw = lateral_acceleration / forward
        difference = target_yaw * self.spec.track_width_m / self.spec.wheel_radius_m
        mean = (left + right) / 2.0
        return (mean - difference / 2.0, mean + difference / 2.0)


class WarehousePolicy:
    """A proportional aisle-follower. Satisfies the ``Policy`` protocol structurally.

    Not learned and not good; it exists so that something produces commands in
    the AGV's actuation space. What is being tested is the pipeline's
    indifference to the platform, not this controller.
    """

    __slots__ = ("_spec",)

    def __init__(self, spec: AgvSpec) -> None:
        """Initialise the follower.

        Args:
            spec: The platform constants.
        """
        self._spec = spec

    def act(self, observation: Sequence[float]) -> Sequence[float]:
        """Return wheel speeds that steer back to the aisle centre.

        Args:
            observation: ``(x, y, speed, heading, a_lat, trust)``.

        Returns:
            Left and right wheel angular velocity.
        """
        spec = self._spec
        offset, heading = float(observation[1]), float(observation[3])
        cruise = spec.speed_limit_mps * 0.6 / spec.wheel_radius_m
        correction = -2.0 * offset - 3.0 * heading
        difference = correction * spec.track_width_m / spec.wheel_radius_m
        return (cruise - difference / 2.0, cruise + difference / 2.0)
