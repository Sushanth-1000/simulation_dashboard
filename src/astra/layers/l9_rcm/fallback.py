"""The deterministic controller L9 falls back to when the proposal is vetoed.

What this is for
-----------------
A VETO says the proposed command must not be issued. It does not say the vehicle
should stop being controlled. Something still has to drive, and that something
cannot be the component whose output was just rejected.

This controller is that something. It is deliberately the least interesting code
in the repository: a proportional law over the state estimate, no learning, no
memory beyond its own integral term, and no dependency on anything Core-B
decided. Its value is precisely that it is boring enough to reason about
completely.

Why proportional-integral and not something better
---------------------------------------------------
A fallback that is sophisticated is a fallback nobody can certify. The point of
this path is that a safety assessor can read it in one sitting and be sure of
what it does in every state. A model-predictive fallback would control better and
would move the hardest part of the safety argument into the component that exists
to be the simple answer.

The integral term is present only to remove steady-state error against the target
speed; it is clamped, because an unclamped integrator that accumulates during a
long veto sequence would produce a large command the moment the vehicle is
released back to it -- an integrator windup that turns a recovery into a lurch.

What it does not read
----------------------
It takes a state estimate and a target. It does not take the verdict that caused
the fallback, the FSM posture, the Trust Index or the proposal it is replacing.
That is not an oversight: a fallback that varied with *why* it was invoked would
have as many behaviours as there are failure modes, and each one would need its
own argument.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astra.kernel.enums import LayerId
from astra.kernel.errors import ContractViolationError
from astra.kernel.validation import require_finite, require_non_negative

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.contracts.estimation import FastStateEstimate
    from astra.kernel.units import MetresPerSecond, Seconds

__all__ = ["ProportionalFallbackController"]


class ProportionalFallbackController:
    """A clamped PI speed controller over one actuation channel.

    Satisfies :class:`~astra.layers.l9_rcm.arbiter.FallbackController`
    structurally.

    Holds the vehicle at a target speed and commands zero on every other
    channel. Commanding zero steering rather than holding the last steering
    value is the conservative choice: a vetoed tick is not evidence that the
    previous steering command was good, and continuing to turn on the strength
    of a command nobody validated is how a fallback becomes the fault.
    """

    __slots__ = (
        "_channel_count",
        "_integral",
        "_integral_limit",
        "_proportional_gain",
        "_speed_index",
        "_target_speed",
        "_tick_period",
    )

    def __init__(
        self,
        *,
        channel_count: int,
        speed_index: int,
        target_speed: MetresPerSecond,
        proportional_gain: float,
        tick_period: Seconds,
        integral_limit: float = 1.0,
    ) -> None:
        """Build the controller.

        Args:
            channel_count: How many channels the actuation space has.
            speed_index: Which channel carries the longitudinal command.
            target_speed: The speed to hold, in metres per second.
            proportional_gain: The proportional gain.
            tick_period: The control period, for integrating the error.
            integral_limit: Clamp on the accumulated integral term. Bounds
                windup during a long veto sequence.

        Raises:
            ContractViolationError: If the channel count is not positive or the
                speed index falls outside it.
            RangeViolationError: If a gain, the target or the limit is negative.
        """
        if channel_count < 1:
            message = f"an actuation space needs at least one channel, got {channel_count}"
            raise ContractViolationError(message, layer=LayerId.L9_RCM)
        if not 0 <= speed_index < channel_count:
            message = (
                f"speed channel index {speed_index} is outside a "
                f"{channel_count}-channel actuation space"
            )
            raise ContractViolationError(message, layer=LayerId.L9_RCM)
        require_non_negative(target_speed, name="target_speed", layer=LayerId.L9_RCM)
        require_non_negative(proportional_gain, name="proportional_gain", layer=LayerId.L9_RCM)
        require_non_negative(tick_period, name="tick_period", layer=LayerId.L9_RCM)
        require_non_negative(integral_limit, name="integral_limit", layer=LayerId.L9_RCM)

        self._channel_count = channel_count
        self._speed_index = speed_index
        self._target_speed = target_speed
        self._proportional_gain = proportional_gain
        self._tick_period = tick_period
        self._integral_limit = integral_limit
        self._integral = 0.0

    def observe(self, state: FastStateEstimate) -> None:
        """Update the controller's error term from the current state.

        Called once per tick, whether or not the fallback ends up commanding.
        A controller that only integrated on the ticks it was used would carry a
        stale error into the moment it is needed.

        Args:
            state: The current fast state estimate.

        Raises:
            NonFiniteValueError: If the estimated speed is not finite.
        """
        speed = require_finite(float(state.speed), name="fallback.speed", layer=LayerId.L9_RCM)
        error = float(self._target_speed) - speed
        self._integral = _clamp(
            self._integral + error * float(self._tick_period),
            limit=self._integral_limit,
        )

    def command(self) -> Sequence[float]:
        """Return the fallback command vector.

        Returns:
            A vector aligned to the actuation space's channel order, carrying
            the speed command on its channel and zero elsewhere.
        """
        effort = _clamp(self._proportional_gain * self._integral, limit=1.0)
        return tuple(
            effort if index == self._speed_index else 0.0 for index in range(self._channel_count)
        )

    def reset(self) -> None:
        """Clear the integral term.

        Called when the vehicle returns to nominal control, so that error
        accumulated while the fallback was governing does not survive into a
        period it no longer describes.
        """
        self._integral = 0.0

    @property
    def integral(self) -> float:
        """Return the accumulated integral term, for diagnostics."""
        return self._integral


def _clamp(value: float, *, limit: float) -> float:
    """Confine a value to a symmetric interval.

    Args:
        value: The value to confine.
        limit: The interval's half-width.

    Returns:
        ``value`` limited to ``[-limit, limit]``.
    """
    return max(-limit, min(limit, value))
