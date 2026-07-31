"""Bounded safe exploration: what the vehicle does when nothing matches.

The behaviour this exists to avoid
------------------------------------
Every runtime-assurance system in the survey degrades to a stop. That is
defensible on a test track and useless on a motorway, where an unexplained halt
in live traffic is itself the hazard. The tunnel scenario is built to force the
question: GPS drops, the context signature moves somewhere no certified profile
covers, and every candidate fails the admissibility conjunction.

The answer here is not to relax the gates. It is to shrink the envelope until
the vehicle's behaviour is defensible *without* a certified profile, and keep
moving inside it.

Why each bound is what it is
-----------------------------
**Speed at half the nearest profile's certified maximum.** Halving is not a
tuning choice dressed as physics -- it is the acknowledgement that the nearest
profile is *not* a match. Its certified limit was established for a context the
vehicle is no longer in, so it bounds nothing directly; halving it buys margin
proportional to the only evidence available.

**No lane changes.** A lane change commits the vehicle to a trajectory it cannot
abandon halfway. Under an uncertified profile the system cannot predict the
outcome well enough to start one.

**Steering within a fixed cone.** Bounds the lateral acceleration reachable in
one tick without needing a friction estimate the situation may not support.

**Evidence logged, and logged nowhere near the safety argument.** Every
``(signature, command, outcome)`` triple is recorded for the offline
certification pipeline that will eventually produce a profile for this context.
None of it feeds a gate. That is SI-10, and it matters here more than anywhere
else in the system: exploration is precisely when the temptation to let the
system calibrate itself out of a corner is strongest, and doing so would mean
the safety argument was written by the situation it was meant to judge.

Exploration ends, and never by halting
----------------------------------------
Four exit conditions, checked in order of severity. Three of them return the
vehicle to normal operation or to a *graduated* fail-safe posture; none of them
is a stop. Reaching HALT remains L8's decision, taken on its own counter, and
this module has no way to cause it directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final

from astra.contracts.actuation import ActuationChannel, ActuationSpace
from astra.kernel.enums import LayerId
from astra.kernel.errors import ConfigurationError
from astra.kernel.units import MetresPerSecond, Radians

__all__ = [
    "ExplorationEnvelope",
    "ExplorationExit",
    "exploration_envelope",
    "restricted_space",
]

SPEED_FRACTION_OF_NEAREST: Final = 0.5
"""Fraction of the nearest certified profile's maximum speed.

An architectural constant rather than configuration. It expresses a fact about
the situation -- the nearest profile does not apply -- and not an operating point
a safety engineer chooses per deployment. Making it configurable would invite
raising it, which is the one direction it must not move.
"""

MAXIMUM_STEERING_RADIANS: Final = math.radians(15.0)
"""The exploration steering cone, +/- 15 degrees, per the validation plan."""


@unique
class ExplorationExit(StrEnum):
    """Why bounded safe exploration ended.

    Ordered by severity. Every one of them leaves the vehicle moving: none is a
    halt, and this module cannot cause one.
    """

    TIMEOUT = "TIMEOUT"
    """The wall-clock budget elapsed. The most conservative exit."""

    DEGRADED = "DEGRADED"
    """Core-B's OOD counter rose and the FSM left NOMINAL. L8 now governs."""

    PROFILE_REACQUIRED = "PROFILE_REACQUIRED"
    """The signature drifted back within reach of a certified centroid."""

    OPERATOR_REQUESTED = "OPERATOR_REQUESTED"
    """A human explicitly asked for intervention."""


@dataclass(frozen=True, slots=True)
class ExplorationEnvelope:
    """The command envelope in force during bounded safe exploration.

    Attributes:
        speed_cap: Maximum speed, half the nearest certified profile's maximum.
        steering_limit: Maximum absolute steering, the fixed cone.
        lane_changes_permitted: Always ``False``. Present as a field rather than
            implied so that a consumer reads the prohibition from the envelope
            rather than having to know it.
    """

    speed_cap: MetresPerSecond
    steering_limit: Radians
    lane_changes_permitted: bool = False

    def __post_init__(self) -> None:
        """Validate that the envelope is a real restriction.

        Raises:
            ConfigurationError: If the speed cap is negative or non-finite, if
                the steering limit is negative or exceeds the cone, or if lane
                changes are permitted. The last is not defensive: an envelope
                that allowed a lane change would not be a safe-exploration
                envelope, whatever it was called.
        """
        if not math.isfinite(self.speed_cap) or self.speed_cap < 0.0:
            message = (
                f"the exploration speed cap must be finite and non-negative, got {self.speed_cap}"
            )
            raise ConfigurationError(
                message, layer=LayerId.L9_RCM, context={"speed_cap": str(self.speed_cap)}
            )
        if not math.isfinite(self.steering_limit) or not (
            0.0 <= self.steering_limit <= MAXIMUM_STEERING_RADIANS
        ):
            message = (
                f"the exploration steering limit must lie in [0, {MAXIMUM_STEERING_RADIANS:.4f}] "
                f"radians, got {self.steering_limit}; the cone is what bounds reachable "
                f"lateral acceleration without a friction estimate the situation may not support"
            )
            raise ConfigurationError(
                message,
                layer=LayerId.L9_RCM,
                context={"steering_limit": str(self.steering_limit)},
            )
        if self.lane_changes_permitted:
            message = (
                "lane changes are never permitted during bounded safe exploration; a lane "
                "change commits the vehicle to a trajectory it cannot abandon halfway, and "
                "under an uncertified profile the outcome cannot be predicted well enough "
                "to start one"
            )
            raise ConfigurationError(message, layer=LayerId.L9_RCM)


def exploration_envelope(nearest_max_speed: float) -> ExplorationEnvelope:
    """Build the exploration envelope from the nearest certified profile.

    Args:
        nearest_max_speed: The maximum speed of the nearest profile, certified
            for a context the vehicle is *not* in. It bounds nothing directly,
            which is why the envelope takes half of it rather than all.

    Returns:
        The envelope.

    Raises:
        ConfigurationError: If the speed is negative or non-finite. Note that
            zero is permitted and yields a stationary envelope: that is a
            legitimate description of "the nearest thing we know about is not
            allowed to move either", and it is the caller's business whether to
            act on it, not this function's business to invent a floor.
    """
    if not math.isfinite(nearest_max_speed) or nearest_max_speed < 0.0:
        message = (
            f"the nearest profile's maximum speed must be finite and non-negative, got "
            f"{nearest_max_speed}"
        )
        raise ConfigurationError(
            message, layer=LayerId.L9_RCM, context={"speed": str(nearest_max_speed)}
        )
    return ExplorationEnvelope(
        speed_cap=MetresPerSecond(nearest_max_speed * SPEED_FRACTION_OF_NEAREST),
        steering_limit=Radians(MAXIMUM_STEERING_RADIANS),
    )


def restricted_space(
    space: ActuationSpace,
    envelope: ExplorationEnvelope,
    *,
    longitudinal_channel: str = "throttle",
    steering_channel: str = "steer",
) -> ActuationSpace:
    """Narrow an actuation space to the exploration envelope.

    This is what makes the envelope *enforceable* rather than advisory. L9 issues
    commands as vectors in an actuation space, and
    :class:`~astra.contracts.actuation.IssuedCommand` refuses any vector outside
    its space's bounds -- so narrowing the space narrows what can physically be
    issued, through the same check that already guards every other command.

    The alternative would be to clamp commands against the envelope at the point
    of issue. That works until somebody adds a second issue path, and then the
    envelope is enforced in one of them.

    Only two channels are narrowed. Braking is deliberately left at full
    authority: exploration bounds what the vehicle may *do*, and taking away its
    ability to stop would make the safety envelope less safe.

    Args:
        space: The nominal actuation space.
        envelope: The exploration envelope in force.
        longitudinal_channel: Name of the channel carrying propulsion.
        steering_channel: Name of the channel carrying steering.

    Returns:
        A space with the steering channel narrowed to the cone and the
        longitudinal channel scaled by the envelope's speed fraction.

    Raises:
        ContractViolationError: If either named channel is absent from the space.
    """
    fraction = _longitudinal_fraction(envelope)
    narrowed: list[ActuationChannel] = []
    for channel in space.channels:
        if channel.name == steering_channel:
            limit = min(float(envelope.steering_limit), max(abs(channel.lower), channel.upper))
            narrowed.append(
                ActuationChannel(name=channel.name, lower=-limit, upper=limit, unit=channel.unit)
            )
        elif channel.name == longitudinal_channel:
            narrowed.append(
                ActuationChannel(
                    name=channel.name,
                    lower=channel.lower,
                    upper=channel.upper * fraction,
                    unit=channel.unit,
                )
            )
        else:
            narrowed.append(channel)

    # `channel()` raises if a name is absent, so this is the check that the
    # caller named channels this space actually has -- performed after building
    # so the error names the space rather than a half-built one.
    space.channel(longitudinal_channel)
    space.channel(steering_channel)
    return ActuationSpace(tuple(narrowed))


def _longitudinal_fraction(envelope: ExplorationEnvelope) -> float:
    """Return how much of the propulsion range exploration may use.

    The envelope bounds *speed*, and the actuation space bounds *command*. There
    is no general mapping between the two without a plant model, so the fraction
    is taken directly from the architectural constant the envelope was built
    with. Deriving it from the speed cap would require dividing by a certified
    maximum that the envelope no longer carries.

    Args:
        envelope: The envelope in force.

    Returns:
        The fraction of the longitudinal channel's upper bound that remains.
    """
    del envelope
    return SPEED_FRACTION_OF_NEAREST
