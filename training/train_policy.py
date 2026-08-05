"""PID-Lagrangian PPO training for Core-A.

    python -m training.train_policy --out var/policy/synthetic.pt

Invoked as a module rather than a path because it imports ``training.environment``
alongside it; a bare script path would not put the repository root on ``sys.path``.

What the algorithm actually is
--------------------------------
PPO on the Lagrangian relaxation of the CMDP. The inner loop is ordinary PPO,
maximising ``r - sum_i lambda_i c_i``. The outer loop moves each ``lambda_i`` by
the PID rule in :class:`~astra.layers.l4_proposer.constraints.LagrangianDual`,
from the constraint costs the current policy actually realised.

The two loops are deliberately separated in time: multipliers are held fixed for
a whole batch of rollouts and updated between them. Updating them inside an
episode would make a step's contribution to the return depend on when it
happened rather than on what it cost, and the fixed point PPO converges to would
no longer be the fixed point of the constrained problem.

The dual variables start at zero. That is not a neutral choice and is worth
naming: the policy is unconstrained until it first violates something, so early
training is fast and unsafe. In a simulator that is free. It would not be an
acceptable schedule anywhere else, and this script is not a template for
training on hardware.

Why the export is a plain state_dict
--------------------------------------
Stable-Baselines3 saves a zip carrying pickled Python objects, its own version,
and the optimiser state. None of that belongs on a vehicle. What is exported is
the actor's weights, the actuation width, and the three feature normalisers,
loadable by :class:`~astra.layers.l4_proposer.learned.LearnedPolicy` with no RL
framework present -- the same arrangement the twin uses.

The transfer is exact rather than approximate: PPO is configured with
``net_arch={"pi": [64, 64]}`` and ``activation_fn=Tanh``, which makes SB3's
``mlp_extractor.policy_net`` plus ``action_net`` structurally identical to
:class:`~astra.layers.l4_proposer.network.PolicyNetwork`. A test asserts the two
agree on real inputs rather than trusting that correspondence.

What a policy from this script is worth
-----------------------------------------
It is a genuinely learned controller and it is trained on synthetic dynamics.
Both halves of that sentence must travel with any result produced from it; see
:mod:`astra.layers.l4_proposer.learned` for what may and may not be claimed.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import torch
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from torch import nn

from astra.layers.l4_proposer.constraints import COLLISION_BUDGET, LagrangianDual
from astra.layers.l4_proposer.network import POLICY_HIDDEN_WIDTH, PolicyNetwork
from training.environment import EnvironmentSpec, SyntheticDrivingEnv

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_OUT: Final = Path("var/policy/synthetic.pt")
DEFAULT_ROUNDS: Final = 48
DEFAULT_STEPS_PER_ROUND: Final = 16_384
"""786k timesteps, about five minutes on a laptop CPU.

Raised from 12 x 8,192 after the first soak run. At 98k timesteps the policy
learns lane centring and **not** speed control: it comes to a complete stop by
step 250 of a 500-step episode, holds the lane perfectly while stationary, and
satisfies every constraint. The measured difference, at a fixed seed and with
the action-rate fix in :class:`~training.environment.EnvironmentSpec` in place:

| timesteps | return | mean \\|long. acceleration\\| |
|---|---|---|
| 98k  | 549 | 1.289 m/s^2 -- decelerates, then sits at rest |
| 786k | 986 | 0.158 m/s^2 -- converges on 13.0 m/s and holds it |

Both changes were needed. 786k timesteps with the action-rate penalty still
applied to throttle and brake produces a return of 671 and the same 1.289
m/s^2: a stopping vehicle, more thoroughly trained. See ``docs/SOAK_REPORT.md``.
"""
DEFAULT_EVALUATION_EPISODES: Final = 8
DEFAULT_SEED: Final = 20260731

DUAL_LEARNING_RATE: Final = 0.05
DUAL_INTEGRAL_GAIN: Final = 0.002
DUAL_DERIVATIVE_GAIN: Final = 0.02
"""PID gains for the dual update. The derivative term is what damps the
oscillation a proportional-only dual shows at the constraint boundary: it
overshoots, the policy retreats, the multiplier decays, and the cycle repeats."""

INITIAL_LOG_STD: Final = -2.5
"""Initial exploration scale, in normalised action units (``sigma ~ 0.08``).

SB3's default of ``0`` means unit-variance exploration across the whole
normalised range. On the steer channel that is roughly +/-70 m/s^2 of sampled
lateral acceleration, so essentially every rollout leaves the road before the
advantage estimate can distinguish a good action from a bad one. The failure
presents as "PPO will not learn this task"; the cause is that it never samples
inside the band where the task is defined."""

EXPECTED_EXTRACTOR_LAYERS: Final = 2

MULTIPLIER_CEILING: Final = 100.0
"""A dual variable above this is a divergence report, not a price. Left
unbounded, an unsatisfiable constraint drives the multiplier upward without limit
and the policy collapses to inaction -- which reads as "very safe" in every
constraint metric and is the failure mode this ceiling exists to make loud."""


def _dual_variables() -> tuple[LagrangianDual, LagrangianDual, LagrangianDual]:
    """Return the three dual variables, one per constraint.

    Returns:
        Duals for C1, C2 and C3, each starting at zero.
    """
    return (
        LagrangianDual(
            learning_rate=DUAL_LEARNING_RATE,
            integral_gain=DUAL_INTEGRAL_GAIN,
            derivative_gain=DUAL_DERIVATIVE_GAIN,
        ),
        LagrangianDual(
            learning_rate=DUAL_LEARNING_RATE,
            integral_gain=DUAL_INTEGRAL_GAIN,
            derivative_gain=DUAL_DERIVATIVE_GAIN,
        ),
        LagrangianDual(
            learning_rate=DUAL_LEARNING_RATE * 4.0,
            integral_gain=DUAL_INTEGRAL_GAIN,
            derivative_gain=DUAL_DERIVATIVE_GAIN,
        ),
    )


@dataclass(frozen=True, slots=True)
class Realised:
    """What a deterministic rollout actually cost, in the units the budgets use.

    Attributes:
        task_return: Mean undiscounted task return, before any penalty.
        deviation_m: ``J_C1``, mean ``|lane deviation|``.
        acceleration_mps2: ``J_C2``, mean ``|longitudinal acceleration|``.
        collision_rate: ``J_C3``, collisions per episode.
        peak_lateral_jerk_mps3: Largest single-step lateral jerk observed. A
            **diagnostic**, never a training input: it is reported so a run can
            be compared against the limit L7b will hold the policy to, and the
            gap between the constraint set and that limit stays visible.
    """

    task_return: float
    deviation_m: float
    acceleration_mps2: float
    collision_rate: float
    peak_lateral_jerk_mps3: float

    def costs(self) -> tuple[float, float, float]:
        """Return the three realised costs in constraint order."""
        return (self.deviation_m, self.acceleration_mps2, self.collision_rate)


def evaluate(model: PPO, spec: EnvironmentSpec, *, episodes: int, seed: int) -> Realised:
    """Roll the deterministic policy out and measure what it realised.

    Deterministic on purpose. The dual update must respond to what the policy
    *does*, and a stochastic rollout mixes the exploration noise into the
    measured constraint cost, so the multiplier ends up pricing the sampler.

    Args:
        model: The current PPO model.
        spec: The environment definition.
        episodes: How many episodes to average over.
        seed: Base seed; each episode uses ``seed + index`` so the evaluation is
            reproducible and the episodes are not identical.

    Returns:
        The realised costs, in the same units as the constraint budgets.
    """
    env = SyntheticDrivingEnv(spec)
    returns = 0.0
    collisions = 0
    deviation = 0.0
    acceleration = 0.0
    peak_jerk = 0.0

    for index in range(episodes):
        observation, _ = env.reset(seed=seed + index)
        while True:
            action, _ = model.predict(observation, deterministic=True)
            observation, _, terminated, truncated, _ = env.step(action)
            if terminated or truncated:
                break
        statistics = env.statistics
        returns += statistics.task_return
        collisions += int(statistics.collided)
        deviation += statistics.mean_absolute_deviation_m
        acceleration += statistics.mean_absolute_acceleration_mps2
        peak_jerk = max(peak_jerk, statistics.peak_lateral_jerk_mps3)

    return Realised(
        task_return=returns / episodes,
        deviation_m=deviation / episodes,
        acceleration_mps2=acceleration / episodes,
        collision_rate=collisions / episodes,
        peak_lateral_jerk_mps3=peak_jerk,
    )


def export_actor(model: PPO, spec: EnvironmentSpec) -> dict[str, object]:
    """Extract the actor's weights into the runtime architecture.

    Args:
        model: The trained PPO model.
        spec: The environment the policy was trained on.

    Returns:
        A checkpoint payload for
        :class:`~astra.layers.l4_proposer.learned.PolicyCheckpoint`.

    Raises:
        RuntimeError: If SB3's extractor is not the two-layer tanh stack this
            export assumes. Silently exporting a mismatched subset would produce
            a partly-random actor that still returns plausible commands.
    """
    policy = model.policy
    extractor = policy.mlp_extractor.policy_net
    linears = [module for module in extractor if isinstance(module, nn.Linear)]
    if len(linears) != EXPECTED_EXTRACTOR_LAYERS or linears[0].out_features != POLICY_HIDDEN_WIDTH:
        message = (
            f"expected a two-layer policy extractor of width {POLICY_HIDDEN_WIDTH}, got "
            f"{[module.out_features for module in linears]}; the runtime PolicyNetwork "
            f"cannot represent this actor and exporting it would lose layers silently"
        )
        raise RuntimeError(message)

    network = PolicyNetwork(command_dimension=int(policy.action_space.shape[0]))
    with torch.no_grad():
        network.body[0].weight.copy_(linears[0].weight)
        network.body[0].bias.copy_(linears[0].bias)
        network.body[2].weight.copy_(linears[1].weight)
        network.body[2].bias.copy_(linears[1].bias)
        network.head.weight.copy_(policy.action_net.weight)
        network.head.bias.copy_(policy.action_net.bias)

    return {
        "weights": {key: value.cpu() for key, value in network.state_dict().items()},
        "command_dimension": int(policy.action_space.shape[0]),
        "lane_half_width_m": spec.lane_half_width_m,
        "reference_speed_mps": spec.reference_speed_mps,
        "lateral_acceleration_limit_mps2": spec.lateral_acceleration_limit_mps2,
        "channel_lower": tuple(spec.channel_lower),
        "channel_upper": tuple(spec.channel_upper),
    }


def train(
    *,
    out: Path,
    rounds: int,
    steps_per_round: int,
    episodes: int,
    seed: int,
    device: str,
) -> int:
    """Run the constrained training loop and write the checkpoint.

    Args:
        out: Where to write the checkpoint.
        rounds: Outer iterations. Each is one PPO batch plus one dual update.
        steps_per_round: Environment steps per outer iteration.
        episodes: Evaluation episodes per round.
        seed: Base seed for the run.
        device: Torch device for PPO.

    Returns:
        ``0`` if training finished with every constraint inside its budget,
        ``1`` otherwise. A non-zero exit is the honest outcome for a run whose
        policy is still violating a constraint it was trained to satisfy.
    """
    spec = EnvironmentSpec()
    budget = spec.budget()
    # `J_C(pi) <= d`, in the units the budget is stated in. Deliberately not the
    # floored excess `constraint_costs` produces: that is zero whenever the
    # constraint holds, so a dual driven against it never sees a negative error
    # and its multiplier only ever grows. Driving it against the realised cost
    # lets a satisfied constraint pull its own price back down.
    limits = (
        budget.lane_deviation_limit_m,
        budget.longitudinal_acceleration_limit_mps2,
        COLLISION_BUDGET,
    )

    env = Monitor(SyntheticDrivingEnv(spec))
    model = PPO(
        "MlpPolicy",
        env,
        seed=seed,
        device=device,
        n_steps=2_048,
        batch_size=256,
        gae_lambda=0.95,
        gamma=0.99,
        learning_rate=3e-4,
        ent_coef=0.0,
        policy_kwargs={
            "net_arch": {"pi": [POLICY_HIDDEN_WIDTH] * 2, "vf": [64, 64]},
            "activation_fn": nn.Tanh,
            "log_std_init": INITIAL_LOG_STD,
        },
        verbose=0,
    )
    duals = _dual_variables()

    print(f"training on {device}; budgets C1={limits[0]:.3f} m  C2={limits[1]:.3f} m/s^2  C3=0")
    print(f"{'round':>5}  {'return':>8}  {'J_C1 m':>8}  {'J_C2':>7}  {'coll':>5}  duals")

    diverged = False
    for round_index in range(rounds):
        model.learn(total_timesteps=steps_per_round, reset_num_timesteps=False)
        realised = evaluate(model, spec, episodes=episodes, seed=seed + 1_000 * (round_index + 1))

        multipliers = tuple(
            dual.update(realised_cost=value, budget=limit)
            for dual, value, limit in zip(duals, realised.costs(), limits, strict=True)
        )
        if any(value > MULTIPLIER_CEILING for value in multipliers):
            diverged = True
            print(f"  dual variable exceeded {MULTIPLIER_CEILING}: {multipliers}")
            break

        # The wrapper is inside a Monitor, hence the unwrap.
        inner = env.unwrapped
        if not isinstance(inner, SyntheticDrivingEnv):
            message = (
                f"expected a SyntheticDrivingEnv under the Monitor, got {type(inner).__name__}"
            )
            raise TypeError(message)
        inner.set_multipliers(multipliers)

        print(
            f"{round_index:>5}  {realised.task_return:>8.1f}  {realised.deviation_m:>8.3f}  "
            f"{realised.acceleration_mps2:>7.3f}  {realised.collision_rate:>5.2f}  "
            f"({multipliers[0]:.2f}, {multipliers[1]:.2f}, {multipliers[2]:.2f})"
            f"  jerk {realised.peak_lateral_jerk_mps3:>7.1f}"
        )

    final = evaluate(model, spec, episodes=episodes * 2, seed=seed + 999_983)

    payload = export_actor(model, spec)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, out)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()[:16]

    satisfied = all(value <= limit for value, limit in zip(final.costs(), limits, strict=True))
    print()
    print(f"wrote {out}  sha256:{digest}")
    print(f"C1  mean |lane deviation|      {final.deviation_m:.4f} m      (budget {limits[0]:.3f})")
    print(
        f"C2  mean |long. acceleration|  {final.acceleration_mps2:.4f} m/s^2  "
        f"(budget {limits[1]:.3f})"
    )
    print(
        f"C3  collision rate             {final.collision_rate:.4f}        (budget {limits[2]:.3f})"
    )
    print(f"constraints satisfied: {'yes' if satisfied and not diverged else 'NO'}")
    print(
        f"peak lateral jerk (diagnostic, not a constraint) {final.peak_lateral_jerk_mps3:.2f} m/s^3"
    )
    return 0 if satisfied and not diverged else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and train.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--steps-per-round", type=int, default=DEFAULT_STEPS_PER_ROUND)
    parser.add_argument("--episodes", type=int, default=DEFAULT_EVALUATION_EPISODES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--device", default="cpu")
    arguments = parser.parse_args(argv)

    return train(
        out=arguments.out,
        rounds=arguments.rounds,
        steps_per_round=arguments.steps_per_round,
        episodes=arguments.episodes,
        seed=arguments.seed,
        device=arguments.device,
    )


if __name__ == "__main__":
    sys.exit(main())
