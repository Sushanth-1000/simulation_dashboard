"""Policies the CMDP proposer can be driven by, and what each one is honestly worth.

Read this before using :class:`KinematicPlaceholderPolicy` for anything
------------------------------------------------------------------------
**There is no trained PPO policy in this repository.** Phase 4 of the roadmap
provides for one -- Stable-Baselines3 PPO under a Lagrangian constraint wrapper,
trained against CARLA over GPU wall-clock time that does not compress -- and that
work has not been done.

What lives here is a deterministic kinematic controller that produces
*plausibly-shaped* commands so the pipeline can be composed, exercised end to
end, and measured. It is scaffolding with a clear name, not a stand-in that
might be mistaken for the real thing.

Why that distinction is load-bearing rather than pedantic
-----------------------------------------------------------
ASTRA's entire premise is that the proposer is an **untrusted learned
component**: a policy that can be adversarially perturbed, that can drift from
its training distribution, and that can be confidently wrong in ways no
structural check would catch. Every gate downstream is designed against that
threat model.

A deterministic controller has none of those properties. It cannot hallucinate,
cannot drift, and cannot be attacked through its inputs in the way a network can.
So a pipeline driven by this policy demonstrates that the *plumbing* works --
that a command crosses the channel, meets three gates, reaches the arbitrator and
lands in the audit log. It demonstrates **nothing whatsoever** about whether the
gates catch what they exist to catch.

Concretely, the following must never be claimed from a run using this policy:

* any false-positive or false-negative rate,
* any veto rate,
* any statement about gate independence,
* any statement that ASTRA "caught" an unsafe command.

Those claims require the trained policy and the Phase 9 scenarios. This class
exists so that everything *around* them can be finished and measured first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.kernel.constants import FAST_STATE_FIELDS
from astra.kernel.enums import LayerId
from astra.kernel.errors import ContractViolationError
from astra.kernel.validation import (
    require_finite,
    require_non_negative,
    require_positive,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["KinematicPlaceholderPolicy"]

_STEERING_LIMIT = 0.5
"""Steering command bound, in radians. Matches the automotive actuation space's
steer channel; a command outside it would be clamped at the boundary anyway, and
proposing one would put an inadmissible command on the channel for no purpose."""


class KinematicPlaceholderPolicy:
    """A deterministic policy that holds a speed and centres the steering.

    Satisfies :class:`~astra.layers.l4_proposer.proposer.Policy` structurally.

    **Not a learned policy.** See the module docstring for what may and may not
    be concluded from a pipeline driven by it.

    The observation vector it is handed is the fast state followed by the Trust
    Index. It reads the speed and the lateral acceleration and ignores the rest,
    including the Trust Index -- a real policy may condition on trust, but a
    placeholder that did so would imply a relationship it has not learned.
    """

    __slots__ = (
        "_acceleration_budget",
        "_channel_count",
        "_speed_gain",
        "_speed_index",
        "_steer_effectiveness",
        "_steer_index",
        "_target_speed",
    )

    def __init__(
        self,
        *,
        channel_count: int,
        speed_index: int,
        steer_index: int,
        target_speed: float,
        steer_effectiveness: float,
        tick_period: float,
        maximum_jerk: float,
        speed_gain: float = 0.1,
        damping_fraction: float = 0.25,
    ) -> None:
        """Build the placeholder policy.

        Args:
            channel_count: How many channels the actuation space has.
            speed_index: Which channel carries the longitudinal command.
            steer_index: Which channel carries the steering command.
            target_speed: The speed the policy aims to hold, in m/s.
            steer_effectiveness: How much lateral acceleration one radian of
                steering produces, in m/s^2 per radian. **Required, not
                optional.** A damping gain expressed in command units with no
                reference to the plant gain is not a damping gain: the first
                version of this class used ``0.05`` against a plant of
                140 m/s^2/rad and commanded 6.3 m/s^2 of counter-acceleration
                into a vehicle turning at 1.5, which the physical gate correctly
                rejected as a 157 m/s^3 jerk.
            tick_period: The control period, in seconds. Converts a jerk limit
                into a per-tick acceleration change.
            maximum_jerk: The largest admissible rate of change of lateral
                acceleration, in m/s^3. The damping command is bounded so the
                proposer does not routinely ask for something L7b must reject.
            speed_gain: Proportional gain on the speed error.
            damping_fraction: What fraction of the per-tick jerk allowance the
                damping term may use. Below one so that a nominal proposal sits
                inside the bound rather than on it.

        Raises:
            ContractViolationError: If a channel index falls outside the space.
            RangeViolationError: If the target, a gain or a limit is negative.
        """
        for name, index in (("speed_index", speed_index), ("steer_index", steer_index)):
            if not 0 <= index < channel_count:
                message = f"{name} {index} is outside a {channel_count}-channel actuation space"
                raise ContractViolationError(message, layer=LayerId.L4_CORE_A_CMDP)
        require_non_negative(target_speed, name="target_speed", layer=LayerId.L4_CORE_A_CMDP)
        require_non_negative(speed_gain, name="speed_gain", layer=LayerId.L4_CORE_A_CMDP)
        require_positive(
            steer_effectiveness, name="steer_effectiveness", layer=LayerId.L4_CORE_A_CMDP
        )
        require_positive(tick_period, name="tick_period", layer=LayerId.L4_CORE_A_CMDP)
        require_non_negative(maximum_jerk, name="maximum_jerk", layer=LayerId.L4_CORE_A_CMDP)
        require_non_negative(
            damping_fraction, name="damping_fraction", layer=LayerId.L4_CORE_A_CMDP
        )

        self._channel_count = channel_count
        self._speed_index = speed_index
        self._steer_index = steer_index
        self._target_speed = target_speed
        self._speed_gain = speed_gain
        self._steer_effectiveness = steer_effectiveness
        # The largest lateral-acceleration change one tick may ask for, scaled
        # down so a nominal proposal is comfortably inside the bound.
        self._acceleration_budget = maximum_jerk * tick_period * damping_fraction

    def act(self, observation: Sequence[float]) -> Sequence[float]:
        """Return a command vector for one observation.

        Args:
            observation: The fast state followed by the Trust Index, in the
                order :class:`~astra.layers.l4_proposer.proposer.CmdpProposer`
                assembles it.

        Returns:
            A command vector aligned to the actuation space's channel order.

        Raises:
            NonFiniteValueError: If the observation carries a non-finite value
                in a field this policy reads.
        """
        speed_position = FAST_STATE_FIELDS.index("speed")
        lateral_position = FAST_STATE_FIELDS.index("lateral_acceleration")

        speed = require_finite(
            float(observation[speed_position]),
            name="observation.speed",
            layer=LayerId.L4_CORE_A_CMDP,
        )
        lateral = require_finite(
            float(observation[lateral_position]),
            name="observation.lateral_acceleration",
            layer=LayerId.L4_CORE_A_CMDP,
        )

        longitudinal = _unit_clamp(self._speed_gain * (self._target_speed - speed))

        # The steering command names the lateral acceleration the vehicle should
        # have *next* tick, not a correction to apply to it. That distinction is
        # the whole of this block, and getting it wrong is instructive:
        #
        # A damping law that commands an acceleration proportional to `-lateral`
        # asks a vehicle already turning at 1.5 m/s^2 to be at roughly zero one
        # tick later -- a demand of 30 m/s^3 against a limit of 8. It vetoes on
        # every tick of every turn, and the veto is correct. The physical gate is
        # not being strict; the controller is asking for something impossible.
        #
        # So the target is the *current* acceleration, walked toward zero by at
        # most one tick's jerk allowance. The vehicle holds its turn and unwinds
        # it gradually, which is both admissible and what a driver does.
        unwind = _symmetric_clamp(-lateral, limit=self._acceleration_budget)
        target_lateral = lateral + unwind
        steering = _symmetric_clamp(
            target_lateral / self._steer_effectiveness, limit=_STEERING_LIMIT
        )

        return tuple(
            longitudinal
            if index == self._speed_index
            else steering
            if index == self._steer_index
            else 0.0
            for index in range(self._channel_count)
        )


def _unit_clamp(value: float) -> float:
    """Confine a value to ``[0, 1]``.

    Args:
        value: The value to confine.

    Returns:
        The value limited to the unit interval.
    """
    return max(0.0, min(1.0, value))


def _symmetric_clamp(value: float, *, limit: float) -> float:
    """Confine a value to ``[-limit, limit]``.

    Args:
        value: The value to confine.
        limit: The interval's half-width.

    Returns:
        The clamped value.
    """
    return max(-limit, min(limit, value))
