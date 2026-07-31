"""The synthetic CMDP the proposer is trained on, and the Lagrangian wrapper around it.

Offline. Nothing in :mod:`astra` imports this module, and nothing here runs on a
tick. It lives outside ``src/`` for that reason: Stable-Baselines3 and Gymnasium
are training dependencies, and putting them on the runtime import graph would
make the vehicle's control path depend on an RL framework it does not need.

The task
---------
Lane-follow a straight reference at a target speed. Not an interesting driving
task, and it is not meant to be -- the interesting object is the *constrained*
optimisation around it. What a good policy here has to do is trade progress
against the three constraint costs while a dual variable moves the price of each
one underneath it.

Dynamics are the kinematic bicycle model of
:func:`astra.layers.l2_estimation.models.fast_transition`, driven by the same
control-effectiveness row the twin uses. Reusing the pipeline's own transition
rather than writing a second one means a policy trained here is trained against
the motion the UKF assumes, which is the only reason its commands are meaningful
to the gates at all. It also means the limitation is inherited whole: the
generating model and the modelled model agree by construction, so nothing
observed here is out-of-distribution in the sense the statistical gate is
calibrated for.

SI-6, mechanically
-------------------
:meth:`SyntheticDrivingEnv.step` builds a
:class:`~astra.layers.l4_proposer.signal.TrainingSignal` and computes reward and
constraint costs from *that object only*. The environment holds no gate, no
verdict and no reference to Core-B; there is nothing here for a veto rate to be
read from even by accident. The frozen field set makes the stronger version of
that guarantee, and ``assert_signal_excludes_core_b`` fires if the set changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, override

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from numpy.typing import NDArray

from astra.layers.l2_estimation.models import fast_transition
from astra.layers.l4_proposer.constraints import ConstraintBudget, constraint_costs
from astra.layers.l4_proposer.network import (
    POLICY_FEATURE_COUNT,
    command_from_normalised,
    policy_features,
)
from astra.layers.l4_proposer.signal import TrainingSignal

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["EnvironmentSpec", "EpisodeStatistics", "SyntheticDrivingEnv"]

_THROTTLE: Final = 0
_BRAKE: Final = 1
_STEER: Final = 2
_CHANNELS: Final = 3

_COLLISION_OFFSET_M: Final = 6.0
"""Lateral offset treated as leaving the road. Not a lane-departure threshold --
that is constraint C1's budget, which is smaller and merely costly. This is the
episode-ending failure C3 prices at infinity."""

_YAW_RATE_MINIMUM_SPEED: Final = 0.5
"""Below this, yaw rate is taken as zero rather than ``a_lat / v``, matching the
UKF's transition so a policy is not trained against a singularity the estimator
does not have."""


@dataclass(frozen=True, slots=True)
class EnvironmentSpec:
    """Everything that defines the task, in one auditable record.

    Written into the checkpoint so a policy always carries the environment it was
    trained on. A policy evaluated at a different reference speed from the one it
    learned is not obviously broken from its behaviour, and this is what makes
    the discrepancy visible.

    Attributes:
        step_seconds: Integration step. Matched to the pipeline's fast rate.
        episode_steps: Steps before truncation.
        reference_speed_mps: Target speed for the progress reward.
        lane_half_width_m: Normaliser for the lateral offset feature.
        lateral_acceleration_limit_mps2: Comfort limit, and the normaliser for
            the lateral-acceleration feature.
        steer_effectiveness: Lateral acceleration produced per radian of steer.
            This is the ``B`` row of ``twin.control_effectiveness``, and the
            convention is the twin's: ``B . pi = a_lat`` directly, with no step
            factor. Introducing one here would train the policy against a plant
            fifty times less responsive than the one L5 predicts, and every
            proposal would then look like a physics violation to L7b.
        channel_lower: Per-channel lower bounds of the actuation space the
            policy emits into.
        channel_upper: Per-channel upper bounds.
        acceleration_authority_mps2: Longitudinal acceleration at full throttle.
        braking_authority_mps2: Deceleration at full brake. Larger than the
            acceleration authority, as on any real vehicle.
        initial_offset_m: Half-range of the uniform initial lateral offset.
        initial_speed_fraction: Half-range of the uniform initial speed error, as
            a fraction of the reference.
        action_rate_weight: Weight on the squared change in the normalised
            action between consecutive steps.

            Not a constraint, and deliberately not one: C1--C3 are fixed by the
            architecture and none of them bounds how fast the *lateral* command
            may move. L7b does -- it requires
            ``|a_proposed - a_current| / dt <= max_lateral_jerk`` -- and a policy
            optimised against C1--C3 alone has no reason to respect it. Measured
            rather than assumed: the first policy trained here satisfied all
            three constraints with a mean lane deviation of 0.10 m and was
            vetoed by L7b on 100% of ticks, because it reached its target
            lateral acceleration in a single 20 ms step.

            This term closes that gap without touching the constraint set or
            :class:`~astra.layers.l4_proposer.signal.TrainingSignal`, because it
            reads neither the vehicle nor any safety component -- only the
            policy's own consecutive outputs. It is ordinary action-rate
            regularisation, and the honest description of it is that the
            architecture's stated constraints are insufficient to produce a
            physically admissible proposer, and this is the objective term that
            compensates.
    """

    step_seconds: float = 0.02
    episode_steps: int = 500
    reference_speed_mps: float = 13.0
    lane_half_width_m: float = 1.75
    lateral_acceleration_limit_mps2: float = 3.0
    steer_effectiveness: float = 140.0
    acceleration_authority_mps2: float = 3.0
    braking_authority_mps2: float = 8.0
    initial_offset_m: float = 1.0
    initial_speed_fraction: float = 0.25
    action_rate_weight: float = 6.0
    channel_lower: tuple[float, float, float] = (0.0, 0.0, -0.5)
    channel_upper: tuple[float, float, float] = (1.0, 1.0, 0.5)

    def budget(self) -> ConstraintBudget:
        """Return the constraint budget this task is trained against.

        Returns:
            C1 at half the lane half-width, C2 at the braking authority. C3's
            budget is zero and not configurable.
        """
        return ConstraintBudget(
            lane_deviation_limit_m=self.lane_half_width_m / 2.0,
            longitudinal_acceleration_limit_mps2=self.braking_authority_mps2 / 2.0,
        )


@dataclass(slots=True)
class EpisodeStatistics:
    """What one episode realised, for the dual update and the training log.

    Attributes:
        steps: How many steps the episode ran.
        task_return: Undiscounted sum of the task reward, before any penalty.
        costs: Mean per-step cost of C1, C2 and C3.
        collided: Whether the episode ended in a collision.
        mean_absolute_deviation_m: Mean ``|lane deviation|``, ``J_C1``.
        mean_absolute_acceleration_mps2: Mean ``|longitudinal acceleration|``,
            ``J_C2``.
        peak_lateral_jerk_mps3: Largest single-step change in commanded lateral
            acceleration, divided by the step. Not a constraint and not part of
            the reward -- a diagnostic, so a run can be compared against the
            limit L7b will hold the policy to without that limit ever entering
            training.

    The last two are the *realised constraint costs* the dual update is driven
    against, and they are deliberately not the floored excesses in
    :attr:`costs`. An excess is zero whenever the constraint is satisfied, so a
    dual driven against it sees a non-negative error forever and ratchets its
    multiplier upward even while the policy is comfortably inside the budget.
    Comparing ``J_C`` against ``d`` lets the error go negative, which is what
    makes the multiplier decay again -- and is what the dual's own interface
    asks for.
    """

    steps: int = 0
    task_return: float = 0.0
    costs: tuple[float, float, float] = (0.0, 0.0, 0.0)
    collided: bool = False
    mean_absolute_deviation_m: float = 0.0
    mean_absolute_acceleration_mps2: float = 0.0
    peak_lateral_jerk_mps3: float = 0.0


class SyntheticDrivingEnv(gym.Env[NDArray[np.float32], NDArray[np.float32]]):
    """Lane-following on the pipeline's own kinematic model.

    The observation the network sees is the *feature* vector, not the raw state,
    and it is produced by :func:`~astra.layers.l4_proposer.network.policy_features`
    -- the same call :class:`~astra.layers.l4_proposer.learned.LearnedPolicy`
    makes at inference. Sharing the function rather than the formula is what
    makes train/inference feature drift impossible rather than merely unlikely.

    The Trust Index component is fixed at 1.0 during training. Honest reason: the
    trust signal is produced by L3 from a calibration corpus that does not exist
    inside this environment, and feeding the policy a fabricated confidence score
    would teach it to condition on a number that means something different at
    runtime. A constant is the one value that teaches it nothing.
    """

    metadata: dict[str, Any] = {"render_modes": []}  # noqa: RUF012 - Env declares it

    def __init__(self, spec: EnvironmentSpec | None = None) -> None:
        """Build the environment.

        Args:
            spec: The task definition. Defaults to :class:`EnvironmentSpec`.
        """
        super().__init__()
        self.spec_ = spec or EnvironmentSpec()
        self._budget = self.spec_.budget()
        # Normalised, symmetric and unit-scaled -- the shape a Gaussian policy
        # can actually explore. `command_from_normalised` is the only place it
        # becomes throttle, brake and steering, and the runtime policy calls the
        # same function on the same bounds.
        self.action_space = spaces.Box(
            low=-1.0, high=1.0, shape=(len(self.spec_.channel_lower),), dtype=np.float32
        )
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(POLICY_FEATURE_COUNT,),
            dtype=np.float32,
        )
        self._state = np.zeros(5, dtype=np.float64)
        self._step_index = 0
        self._multipliers: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._statistics = EpisodeStatistics()
        self._cost_totals = np.zeros(3, dtype=np.float64)
        self._deviation_total = 0.0
        self._acceleration_total = 0.0
        self._previous_action = np.zeros(len(self.spec_.channel_lower), dtype=np.float64)
        self._peak_jerk = 0.0

    # ----------------------------------------------------------------- #
    # The Lagrangian wrapper
    # ----------------------------------------------------------------- #

    def set_multipliers(self, multipliers: Sequence[float]) -> None:
        """Set the dual variables the reward is penalised by.

        Called between rollouts, never inside one: a multiplier that moved
        mid-episode would make the return the policy is credited with depend on
        when in the episode a violation happened, which is not what the
        constrained objective says.

        Args:
            multipliers: Current ``(lambda_1, lambda_2, lambda_3)``.

        Raises:
            ValueError: If three non-negative finite values are not supplied.
        """
        values = tuple(float(value) for value in multipliers)
        if len(values) != _CHANNELS:
            message = f"expected {_CHANNELS} multipliers, got {len(values)}"
            raise ValueError(message)
        for value in values:
            if not math.isfinite(value) or value < 0.0:
                message = f"a multiplier must be finite and non-negative, got {value}"
                raise ValueError(message)
        self._multipliers = (values[0], values[1], values[2])

    @property
    def statistics(self) -> EpisodeStatistics:
        """Return the statistics of the episode that just finished."""
        return self._statistics

    # ----------------------------------------------------------------- #
    # Gymnasium interface
    # ----------------------------------------------------------------- #

    @override
    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[NDArray[np.float32], dict[str, Any]]:
        """Start a new episode from a randomised lane offset and speed error.

        Args:
            seed: Seed for the episode's initial condition.
            options: Unused; present for the Gymnasium signature.

        Returns:
            The first observation and an empty info mapping.
        """
        del options
        super().reset(seed=seed)
        spec = self.spec_
        offset = float(self.np_random.uniform(-spec.initial_offset_m, spec.initial_offset_m))
        speed_error = float(
            self.np_random.uniform(-spec.initial_speed_fraction, spec.initial_speed_fraction)
        )
        heading = float(self.np_random.uniform(-0.05, 0.05))
        self._state = np.array(
            [0.0, offset, spec.reference_speed_mps * (1.0 + speed_error), heading, 0.0],
            dtype=np.float64,
        )
        self._step_index = 0
        self._cost_totals = np.zeros(3, dtype=np.float64)
        self._deviation_total = 0.0
        self._acceleration_total = 0.0
        self._previous_action = np.zeros(len(spec.channel_lower), dtype=np.float64)
        self._peak_jerk = 0.0
        self._statistics = EpisodeStatistics()
        return self._observation(), {}

    @override
    def step(
        self, action: NDArray[np.float32]
    ) -> tuple[NDArray[np.float32], float, bool, bool, dict[str, Any]]:
        """Advance one control step under a command.

        Args:
            action: A normalised action in ``[-1, 1]`` per channel. Mapped onto
                the actuation space and then clipped to it, because this is the
                *plant*: a physical actuator saturates. Core-A's proposals are
                not clipped anywhere on the pipeline; catching an inadmissible
                one is the gates' job, not the vehicle's.

        Returns:
            The Gymnasium five-tuple. The reward is the Lagrangian
            ``r - sum(lambda_i * c_i)``, not the task reward alone.
        """
        spec = self.spec_
        normalised = np.asarray(action, dtype=np.float64).reshape(-1)
        roughness = float(np.sum((normalised - self._previous_action) ** 2))
        self._previous_action = normalised.copy()
        command = np.clip(
            command_from_normalised(
                [float(value) for value in np.asarray(action).reshape(-1)],
                lower=spec.channel_lower,
                upper=spec.channel_upper,
            ),
            spec.channel_lower,
            spec.channel_upper,
        )
        previous_speed = float(self._state[2])

        longitudinal = (
            float(command[_THROTTLE]) * spec.acceleration_authority_mps2
            - float(command[_BRAKE]) * spec.braking_authority_mps2
        )
        # `B . pi = a_lat`, exactly the platform model `twin.control_effectiveness`
        # states and L7b assumes -- saturated at the tyre limit, which is a real
        # bound and does not change the model's form. An actuator lag was tried
        # here and removed: it made the plant respond differently from the model
        # the physical gate scores against, which trains a proposer for a vehicle
        # that is not this one.
        previous_lateral = float(self._state[4])
        lateral = max(
            -spec.lateral_acceleration_limit_mps2,
            min(
                spec.lateral_acceleration_limit_mps2,
                float(command[_STEER]) * spec.steer_effectiveness,
            ),
        )

        # Longitudinal integration is explicit because `fast_transition` holds
        # speed constant: it is the *estimator's* model, which has no command
        # input. The plant does.
        speed = max(0.0, previous_speed + longitudinal * spec.step_seconds)
        self._state[2] = speed
        self._state[4] = lateral
        self._state = fast_transition(
            self._state, spec.step_seconds, yaw_rate_minimum_speed=_YAW_RATE_MINIMUM_SPEED
        )

        deviation = float(self._state[1])
        collided = abs(deviation) >= _COLLISION_OFFSET_M
        signal = TrainingSignal(
            lane_deviation_m=deviation,
            longitudinal_acceleration_mps2=(speed - previous_speed) / spec.step_seconds,
            speed_mps=speed,
            collided=collided,
            progress_m=speed * spec.step_seconds,
        )

        costs = constraint_costs(signal, self._budget)
        task_reward = self._reward(signal) - spec.action_rate_weight * roughness
        penalty = sum(
            multiplier * cost for multiplier, cost in zip(self._multipliers, costs, strict=True)
        )

        self._step_index += 1
        self._cost_totals += np.asarray(costs, dtype=np.float64)
        self._deviation_total += abs(deviation)
        self._acceleration_total += abs(signal.longitudinal_acceleration_mps2)
        self._peak_jerk = max(self._peak_jerk, abs(lateral - previous_lateral) / spec.step_seconds)
        self._statistics.task_return += task_reward

        truncated = self._step_index >= spec.episode_steps
        if collided or truncated:
            self._finish(collided=collided)

        return self._observation(), task_reward - penalty, collided, truncated, {}

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #

    def _reward(self, signal: TrainingSignal) -> float:
        """Return the vehicle-dependent part of the task reward for one step.

        Reads :class:`TrainingSignal` and nothing else, which is what makes SI-6
        a property of the code rather than of the author's discipline. The
        action-rate term is added by the caller and is not computed here
        precisely because it is *not* a fact about the vehicle: it is a fact
        about the policy's own output, and giving it a signal field it does not
        need would widen the permitted set for no reason.

        Args:
            signal: This step's signal.

        Returns:
            Progress toward the reference speed, plus a centring term, less a
            flat collision penalty.
        """
        spec = self.spec_
        speed_error = abs(signal.speed_mps - spec.reference_speed_mps) / spec.reference_speed_mps
        progress = 1.0 - min(1.0, speed_error)
        centring = 1.0 - min(1.0, abs(signal.lane_deviation_m) / spec.lane_half_width_m)
        collision = 50.0 if signal.collided else 0.0
        return progress + centring - collision

    def _finish(self, *, collided: bool) -> None:
        """Freeze the episode statistics the dual update reads.

        Args:
            collided: Whether the episode ended in a collision.
        """
        steps = max(1, self._step_index)
        totals = self._cost_totals / steps
        self._statistics.steps = self._step_index
        self._statistics.costs = (float(totals[0]), float(totals[1]), float(totals[2]))
        self._statistics.collided = collided
        self._statistics.mean_absolute_deviation_m = self._deviation_total / steps
        self._statistics.mean_absolute_acceleration_mps2 = self._acceleration_total / steps
        self._statistics.peak_lateral_jerk_mps3 = self._peak_jerk

    def _observation(self) -> NDArray[np.float32]:
        """Return the current feature vector.

        Returns:
            The same features :class:`LearnedPolicy` computes at inference, from
            the same function.
        """
        spec = self.spec_
        raw = (*(float(value) for value in self._state), 1.0)
        features = policy_features(
            raw,
            lane_half_width_m=spec.lane_half_width_m,
            reference_speed_mps=spec.reference_speed_mps,
            lateral_acceleration_limit_mps2=spec.lateral_acceleration_limit_mps2,
        )
        return np.asarray(features, dtype=np.float32)
