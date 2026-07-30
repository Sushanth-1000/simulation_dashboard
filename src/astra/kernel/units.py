"""Unit policy for ASTRA: SI internally, converted only at system boundaries.

Why this module exists
----------------------
The ASTRA source documents mix unit systems freely. The Hard Safety Shield is
specified with ``a_lat <= mu*g`` in metres per second squared, the sensor-fault
injection scenario uses ``15 m/s^2``, and the Fail-Safe FSM is specified with a
``20 km/h`` LIMP cap and a ``60 km/h`` nominal recovery target. Safe exploration
limits steering to ``+-15 degrees`` while every kinematic equation in the
mathematical model is written in radians.

A safety-critical control system that silently mixes those unit systems has a
latent defect of exactly the kind that destroyed the Mars Climate Orbiter. The
policy adopted here is therefore absolute:

    Every quantity crossing an ASTRA interface is in strict SI base units.
    Conversion happens only in an adapter, at the boundary, explicitly.

Design decision: ``NewType`` rather than a units library
--------------------------------------------------------
Three options were considered.

1. A runtime units library (``pint``, ``astropy.units``). Rejected: every
   arithmetic operation allocates a wrapper object and dispatches through a
   registry. The software latency target for the Core-B intercept path is
   < 5 ms and for the end-to-end hot path < 10 ms at a 20 Hz tick. Paying a
   50-100x arithmetic penalty on the hot path to buy a check that a type
   checker can perform statically is a bad trade.
2. Plain ``float`` with a naming convention (``speed_mps``). Rejected: a
   convention that is not machine-checked is a comment, and comments do not
   fail builds.
3. ``typing.NewType`` aliases over ``float``. Chosen. ``NewType`` is erased at
   runtime -- ``MetresPerSecond(3.0)`` is exactly ``3.0`` and costs one function
   call at construction only -- while mypy treats the alias as a distinct type.
   Passing a ``Radians`` where a ``MetresPerSecond`` is expected is a build
   failure, at zero runtime cost.

Trade-off accepted: ``NewType`` does not propagate through arithmetic
(``a + b`` where both are ``Metres`` is inferred as ``float``, not ``Metres``).
This is a real weakness. It is tolerated because the alternative is runtime
cost on a hard real-time path, and because the boundary that matters most --
the signature of every port in :mod:`astra.ports` -- is fully protected.

Future phases
-------------
Later layers annotate their state vectors with these aliases: the fast UKF
state ``[px, py, v, psi, a_lat]`` becomes
``tuple[Metres, Metres, MetresPerSecond, Radians, MetresPerSecondSquared]``,
which makes the ordering of that vector self-documenting and mis-ordering a
type error rather than a silent physical-nonsense result.
"""

from __future__ import annotations

import math
from typing import Final, NewType

__all__ = [
    "STANDARD_GRAVITY",
    "Degrees",
    "Dimensionless",
    "Hertz",
    "Kilograms",
    "KilometresPerHour",
    "Metres",
    "MetresPerSecond",
    "MetresPerSecondSquared",
    "Milliseconds",
    "Probability",
    "Radians",
    "RadiansPerSecond",
    "Seconds",
    "degrees_to_radians",
    "kmh_to_mps",
    "mps_to_kmh",
    "ms_to_seconds",
    "radians_to_degrees",
    "seconds_to_ms",
]

# --------------------------------------------------------------------------- #
# SI base and derived quantities used inside ASTRA
# --------------------------------------------------------------------------- #

Seconds = NewType("Seconds", float)
"""Time interval in seconds (SI base unit). The canonical duration type."""

Metres = NewType("Metres", float)
"""Length in metres (SI base unit). Positions, distances, stopping distance."""

Kilograms = NewType("Kilograms", float)
"""Mass in kilograms (SI base unit). Vehicle mass ``m`` in the PINN physics loss."""

MetresPerSecond = NewType("MetresPerSecond", float)
"""Linear speed. The canonical representation of ego speed ``v``."""

MetresPerSecondSquared = NewType("MetresPerSecondSquared", float)
"""Linear acceleration. Lateral acceleration ``a_lat`` and commanded ``a_cmd``."""

Radians = NewType("Radians", float)
"""Plane angle in radians (SI coherent unit). Heading ``psi``, steering angle."""

RadiansPerSecond = NewType("RadiansPerSecond", float)
"""Angular rate. Yaw rate, steering rate limits."""

Hertz = NewType("Hertz", float)
"""Frequency. Filter rates: 20 Hz fast UKF, 1 Hz / 0.1 Hz slow UKF."""

# --------------------------------------------------------------------------- #
# Non-SI quantities, permitted only at boundaries
# --------------------------------------------------------------------------- #
# These types exist so that a non-SI value is *visibly* non-SI in a signature.
# They must never appear on an interface in `astra.ports`; they appear only in
# configuration files (which humans author) and in adapter code.

KilometresPerHour = NewType("KilometresPerHour", float)
"""Speed in km/h. Human-facing only: FSM speed caps, legal limits, operator UI."""

Degrees = NewType("Degrees", float)
"""Angle in degrees. Human-facing only: the +-15 deg safe-exploration limit."""

Milliseconds = NewType("Milliseconds", float)
"""Duration in milliseconds. Human-facing only: the 50 ms staleness threshold."""

# --------------------------------------------------------------------------- #
# Dimensionless quantities
# --------------------------------------------------------------------------- #
# These are dimensionless but *not* interchangeable, which is exactly why they
# are distinct types. The Trust Index and a friction coefficient are both bare
# numbers; confusing them is a serious defect.

Probability = NewType("Probability", float)
"""A value constrained to [0, 1]. Trust Index, coverage level, CDI, validation fraction.

Construction does not enforce the bound -- ``NewType`` cannot. Use
:func:`astra.kernel.validation.require_probability` at the boundary where the
value enters the system.
"""

Dimensionless = NewType("Dimensionless", float)
"""An unconstrained dimensionless ratio: friction coefficient, non-conformity score."""

# --------------------------------------------------------------------------- #
# Physical constants
# --------------------------------------------------------------------------- #

STANDARD_GRAVITY: Final[MetresPerSecondSquared] = MetresPerSecondSquared(9.80665)
"""Standard acceleration due to gravity, ``g``, per CGPM (1901): 9.80665 m/s^2.

Used by the Hard Safety Shield's tyre-friction bound ``a_lat <= mu * g``. Fixed
here as an exact defined constant rather than a configurable value: it is a
definition of the unit system, not a tuning parameter, and making it
configurable would create a path by which a bad configuration file weakens a
hard safety bound.
"""

_SECONDS_PER_HOUR: Final = 3600.0
_METRES_PER_KILOMETRE: Final = 1000.0
_MS_PER_SECOND: Final = 1000.0

# --------------------------------------------------------------------------- #
# Boundary conversions
# --------------------------------------------------------------------------- #
# Each conversion is a named function rather than an inline literal. A grep for
# `kmh_to_mps` enumerates every place in the system where a unit boundary is
# crossed, which is precisely the audit question a safety reviewer asks.


def kmh_to_mps(value: KilometresPerHour) -> MetresPerSecond:
    """Convert kilometres per hour to metres per second.

    Args:
        value: Speed in km/h, as it appears in configuration and operator UI.

    Returns:
        The equivalent speed in m/s for use inside the pipeline.
    """
    return MetresPerSecond(value * _METRES_PER_KILOMETRE / _SECONDS_PER_HOUR)


def mps_to_kmh(value: MetresPerSecond) -> KilometresPerHour:
    """Convert metres per second to kilometres per hour.

    Args:
        value: Speed in m/s, as held internally.

    Returns:
        The equivalent speed in km/h for display or logging.
    """
    return KilometresPerHour(value * _SECONDS_PER_HOUR / _METRES_PER_KILOMETRE)


def degrees_to_radians(value: Degrees) -> Radians:
    """Convert degrees to radians.

    Args:
        value: Angle in degrees, e.g. the +-15 deg safe-exploration steering limit.

    Returns:
        The equivalent angle in radians for use in kinematic computation.
    """
    return Radians(math.radians(value))


def radians_to_degrees(value: Radians) -> Degrees:
    """Convert radians to degrees.

    Args:
        value: Angle in radians, as held internally.

    Returns:
        The equivalent angle in degrees for display or logging.
    """
    return Degrees(math.degrees(value))


def ms_to_seconds(value: Milliseconds) -> Seconds:
    """Convert milliseconds to seconds.

    Args:
        value: Duration in milliseconds, e.g. the 50 ms sensor staleness budget.

    Returns:
        The equivalent duration in seconds.
    """
    return Seconds(value / _MS_PER_SECOND)


def seconds_to_ms(value: Seconds) -> Milliseconds:
    """Convert seconds to milliseconds.

    Args:
        value: Duration in seconds, as held internally.

    Returns:
        The equivalent duration in milliseconds for display or logging.
    """
    return Milliseconds(value * _MS_PER_SECOND)
