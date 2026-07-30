"""The constrained-MDP formulation: three constraints and a PID dual variable.

Why constrained rather than penalised
--------------------------------------
The obvious way to make an agent behave is to subtract a penalty from its
reward. The trouble is that a fixed penalty weight silently trades safety
against speed at a rate nobody chose: raise it and the agent crawls, lower it
and the constraint is violated whenever the reward is rich enough to pay for it.
The exchange rate is an emergent property of two numbers that were tuned
separately.

A constrained MDP states the limit instead of pricing it. The dual variable
``lambda`` is *derived* from how far the constraint is actually being violated,
so the price adapts until the constraint holds. What is configured is the limit,
which a safety engineer can reason about, rather than a weight, which nobody can.

Why the dual update is a PID controller
-----------------------------------------
A plain gradient-ascent dual update oscillates around the constraint boundary.
It only responds to present violation, so it consistently overshoots, corrects,
overshoots the other way, and the policy inherits that oscillation as
alternating over-cautious and over-aggressive behaviour.

The update below adds integral and derivative terms:

    ``lambda_{k+1} = [lambda_k + eta*(J_C - d) + K_i*sum(e) + K_d*(e_k - e_{k-1})]_+``

The integral term removes the steady-state offset that lets a small persistent
violation sit forever unpunished. The derivative term responds to the violation
*trend*, which is what damps the oscillation.

The projection onto non-negative values is not a detail: a negative multiplier
would turn the constraint into a bonus, rewarding the agent for violating it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from astra.kernel.enums import LayerId
from astra.kernel.errors import ConfigurationError
from astra.layers.l4_proposer.signal import TrainingSignal

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["ConstraintBudget", "LagrangianDual", "constraint_costs"]

COLLISION_BUDGET: Final = 0.0
"""Constraint C3's budget. Zero, and not configurable.

Every other limit in this project is configuration because a safety engineer has
to choose it for an operational design domain. This one is not a choice. A
non-zero collision budget would state that some rate of collisions is acceptable
during training, and no value other than zero is defensible in a document
anybody has to sign.
"""


@dataclass(frozen=True, slots=True)
class ConstraintBudget:
    """The three constraint limits Core-A is trained against.

    Attributes:
        lane_deviation_limit_m: ``d_max`` for constraint C1.
        longitudinal_acceleration_limit_mps2: ``a_max`` for constraint C2, applied
            to the magnitude so that harsh braking is constrained exactly as
            harsh acceleration is.
    """

    lane_deviation_limit_m: float
    longitudinal_acceleration_limit_mps2: float

    def __post_init__(self) -> None:
        """Validate that both limits are finite and positive.

        Raises:
            ConfigurationError: If a limit is not finite or not positive. A zero
                lane-deviation limit is unsatisfiable and would drive the dual
                variable upward without bound; a negative one is meaningless.
        """
        for name, value in (
            ("lane_deviation_limit_m", self.lane_deviation_limit_m),
            (
                "longitudinal_acceleration_limit_mps2",
                self.longitudinal_acceleration_limit_mps2,
            ),
        ):
            if not math.isfinite(value) or value <= 0.0:
                message = (
                    f"{name} must be finite and positive, got {value}; an unsatisfiable "
                    f"constraint drives the dual variable upward without bound and the "
                    f"policy collapses to inaction"
                )
                raise ConfigurationError(
                    message,
                    layer=LayerId.L4_CORE_A_CMDP,
                    context={"parameter": name, "value": value},
                )


def constraint_costs(
    signal: TrainingSignal, budget: ConstraintBudget
) -> tuple[float, float, float]:
    """Return the three constraint costs for one step.

    Each cost is the amount by which the step exceeded its limit, floored at
    zero. A step inside its limits contributes nothing, so the dual variable
    only grows while the constraint is actually being violated.

    Args:
        signal: The step's training signal. Note the type: this function cannot
            read a Core-B artefact because :class:`TrainingSignal` has no field
            that carries one (SI-6).
        budget: The configured limits.

    Returns:
        ``(c1, c2, c3)`` -- lane-deviation excess in metres, longitudinal
        acceleration excess in m/s^2, and 1.0 for a collision or 0.0 otherwise.
    """
    c1 = max(0.0, abs(signal.lane_deviation_m) - budget.lane_deviation_limit_m)
    c2 = max(
        0.0,
        abs(signal.longitudinal_acceleration_mps2) - budget.longitudinal_acceleration_limit_mps2,
    )
    c3 = 1.0 if signal.collided else COLLISION_BUDGET
    return (c1, c2, c3)


class LagrangianDual:
    """One constraint's dual variable, updated by the PID rule of the paper.

    Stateful by nature -- the integral and derivative terms are what distinguish
    it from plain gradient ascent, and both need history. That state belongs to
    *training*, never to a tick: nothing on the hot path reads this object.
    """

    __slots__ = (
        "_derivative_gain",
        "_integral",
        "_integral_gain",
        "_previous_error",
        "_rate",
        "_value",
    )

    def __init__(
        self,
        *,
        learning_rate: float,
        integral_gain: float = 0.0,
        derivative_gain: float = 0.0,
        initial_value: float = 0.0,
    ) -> None:
        """Build a dual variable.

        Args:
            learning_rate: ``eta``, the proportional step size.
            integral_gain: ``K_i``. Removes the steady-state offset that lets a
                small persistent violation sit unpunished.
            derivative_gain: ``K_d``. Responds to the violation trend, which is
                what damps oscillation at the boundary.
            initial_value: Starting multiplier. Zero means the constraint costs
                nothing until it is first violated.

        Raises:
            ConfigurationError: If any gain is negative or non-finite, or if the
                initial value is negative. A negative multiplier turns the
                constraint into a bonus and rewards violating it.
        """
        for name, value in (
            ("learning_rate", learning_rate),
            ("integral_gain", integral_gain),
            ("derivative_gain", derivative_gain),
            ("initial_value", initial_value),
        ):
            if not math.isfinite(value) or value < 0.0:
                message = (
                    f"{name} must be finite and non-negative, got {value}; a negative "
                    f"multiplier turns the constraint into a bonus and trains the agent "
                    f"to violate it"
                )
                raise ConfigurationError(
                    message,
                    layer=LayerId.L4_CORE_A_CMDP,
                    context={"parameter": name, "value": value},
                )
        self._rate = learning_rate
        self._integral_gain = integral_gain
        self._derivative_gain = derivative_gain
        self._value = initial_value
        self._integral = 0.0
        self._previous_error: float | None = None

    @property
    def value(self) -> float:
        """Return the current multiplier."""
        return self._value

    def update(self, *, realised_cost: float, budget: float) -> float:
        """Advance the multiplier by one PID step.

        Args:
            realised_cost: ``J_C(pi_k)``, the constraint cost the policy actually
                incurred over the episode.
            budget: ``d``, the cost the constraint permits.

        Returns:
            The updated multiplier, projected onto the non-negative reals.

        Raises:
            ConfigurationError: If either argument is non-finite. A NaN would
                propagate into the multiplier and from there into every
                subsequent reward, silently disabling the constraint.
        """
        for name, value in (("realised_cost", realised_cost), ("budget", budget)):
            if not math.isfinite(value):
                message = (
                    f"{name} must be finite, got {value}; a non-finite dual update "
                    f"propagates into every subsequent reward and disables the constraint "
                    f"without raising anything"
                )
                raise ConfigurationError(
                    message,
                    layer=LayerId.L4_CORE_A_CMDP,
                    context={"parameter": name, "value": value},
                )

        error = realised_cost - budget
        self._integral += error
        derivative = 0.0 if self._previous_error is None else error - self._previous_error
        self._previous_error = error

        proposed = (
            self._value
            + self._rate * error
            + self._integral_gain * self._integral
            + self._derivative_gain * derivative
        )
        # Projection onto the non-negative reals, `[.]_+` in the paper.
        self._value = max(0.0, proposed)
        return self._value

    def penalty(self, costs: Sequence[float]) -> float:
        """Return this multiplier's contribution to the Lagrangian.

        Args:
            costs: The realised constraint costs for the step.

        Returns:
            ``lambda * sum(costs)``.
        """
        return self._value * sum(costs)
