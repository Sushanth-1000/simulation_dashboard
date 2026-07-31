"""The learned policy's network, and the feature map training and inference share.

Why the feature map lives here rather than in the training script
------------------------------------------------------------------
:class:`~astra.layers.l4_proposer.proposer.CmdpProposer` hands its policy the
raw observation ``(px, py, v, psi, a_lat, TI)``. Two of those numbers are
unusable as network inputs: ``px`` and ``py`` are absolute world coordinates
that grow without bound along a route, and a network fed them learns the
*training route* rather than the task.

So the policy needs a feature map. The dangerous place to put one is the
training script, because then the runtime has to reimplement it, and a policy
whose inference features have drifted from its training features does not fail
loudly -- it produces confident, wrong commands that look like a badly tuned
controller. Defining it once, in the module the runtime already imports, makes
that drift impossible: the trainer imports this function too.

The same argument produced ``state_features`` in :mod:`astra.layers.l5_twin`.

What the features are
----------------------
Six numbers, each dimensionless and bounded on the operating envelope:

* lateral offset from the lane centre, normalised by the lane half-width;
* speed error against the reference, normalised by the reference;
* ``sin`` and ``cos`` of the heading, so the discontinuity at ``+/-pi`` is not
  presented to the network as a jump;
* lateral acceleration, normalised by the comfort limit;
* the Trust Index, already in ``[0, 1]``.

``px`` is deliberately absent. Longitudinal position along a straight reference
carries no control-relevant information, and including it is the most direct way
to teach a policy the route instead of the task.

Why this file has no Stable-Baselines3 import
-----------------------------------------------
SB3 is a training dependency. The runtime loads a plain ``state_dict`` into the
architecture defined below, exactly as the twin does, so the vehicle's control
path does not depend on the RL framework that produced the weights -- and a
checkpoint remains loadable after that framework's next breaking release.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final, override

import torch
from torch import nn

from astra.kernel.constants import FAST_STATE_FIELDS

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "POLICY_FEATURE_COUNT",
    "POLICY_HIDDEN_WIDTH",
    "PolicyNetwork",
    "command_from_normalised",
    "policy_features",
]

_PY = FAST_STATE_FIELDS.index("position_y")
_V = FAST_STATE_FIELDS.index("speed")
_PSI = FAST_STATE_FIELDS.index("heading")
_A_LAT = FAST_STATE_FIELDS.index("lateral_acceleration")

POLICY_FEATURE_COUNT: Final = 6
"""Width of the feature vector :func:`policy_features` produces."""

POLICY_HIDDEN_WIDTH: Final = 64
"""Units per hidden layer. Matches the ``net_arch`` the trainer configures."""


def policy_features(
    observation: Sequence[float],
    *,
    lane_half_width_m: float,
    reference_speed_mps: float,
    lateral_acceleration_limit_mps2: float,
) -> tuple[float, ...]:
    """Map a raw pipeline observation to the network's input features.

    Args:
        observation: ``(px, py, v, psi, a_lat, TI)`` as assembled by
            :meth:`~astra.layers.l4_proposer.proposer.CmdpProposer.propose`.
        lane_half_width_m: Normaliser for the lateral offset.
        reference_speed_mps: Normaliser for the speed error.
        lateral_acceleration_limit_mps2: Normaliser for lateral acceleration.

    Returns:
        Six dimensionless features, in a fixed order.
    """
    heading = float(observation[_PSI])
    return (
        float(observation[_PY]) / lane_half_width_m,
        (float(observation[_V]) - reference_speed_mps) / reference_speed_mps,
        math.sin(heading),
        math.cos(heading),
        float(observation[_A_LAT]) / lateral_acceleration_limit_mps2,
        float(observation[len(FAST_STATE_FIELDS)]),
    )


def command_from_normalised(
    normalised: Sequence[float],
    *,
    lower: Sequence[float],
    upper: Sequence[float],
) -> tuple[float, ...]:
    """Map a normalised action in ``[-1, 1]`` onto the actuation channels.

    The network learns and emits in normalised coordinates, and this is the one
    place that becomes throttle, brake and steering. It is shared between the
    training plant and :class:`~astra.layers.l4_proposer.learned.LearnedPolicy`
    for the same reason :func:`policy_features` is: a policy whose action scale
    at inference differs from the one it trained under does not fail visibly.

    Why normalise at all. The steer channel spans ``[-0.5, 0.5]`` radians while
    the platform's control effectiveness is 140 m/s^2 per radian, so the band
    that produces comfortable lateral acceleration is roughly four percent of
    the channel. A Gaussian policy exploring at unit scale across that channel
    never spends meaningful time inside the band, and what looks like a failure
    to learn the task is a failure to sample it.

    **Not clamped.** An out-of-range normalised value maps to an out-of-envelope
    command, and it must: Core-A is the untrusted component, and a proposer that
    could not physically express an inadmissible command would make every gate
    downstream untestable.

    Args:
        normalised: The network's output, nominally in ``[-1, 1]``.
        lower: Per-channel lower bounds of the actuation space.
        upper: Per-channel upper bounds.

    Returns:
        One command value per channel.
    """
    return tuple(
        low + (float(value) + 1.0) * 0.5 * (high - low)
        for value, low, high in zip(normalised, lower, upper, strict=True)
    )


class PolicyNetwork(nn.Module):
    """The actor: two tanh hidden layers onto a command vector.

    Structurally identical to the ``pi`` branch of Stable-Baselines3's
    ``ActorCriticPolicy`` under ``net_arch={"pi": [64, 64]}``, followed by its
    ``action_net`` head. That correspondence is what lets the trainer export
    plain weights rather than a framework-specific archive, and it is asserted
    by a test rather than left to a comment.

    The output is the Gaussian policy's *mean* in normalised coordinates,
    unsquashed; :func:`command_from_normalised` turns it into actuation values.
    Squashing here would quietly clamp an out-of-envelope proposal, and an
    inadmissible proposal is precisely what the gates exist to catch -- the same
    reason :class:`~astra.layers.l4_proposer.proposer.CmdpProposer` does not
    clamp either.
    """

    def __init__(self, *, command_dimension: int) -> None:
        """Build the actor.

        Args:
            command_dimension: Number of actuation channels to emit.
        """
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(POLICY_FEATURE_COUNT, POLICY_HIDDEN_WIDTH),
            nn.Tanh(),
            nn.Linear(POLICY_HIDDEN_WIDTH, POLICY_HIDDEN_WIDTH),
            nn.Tanh(),
        )
        self.head = nn.Linear(POLICY_HIDDEN_WIDTH, command_dimension)

    @override
    def forward(self, features: torch.Tensor) -> torch.Tensor:
        """Return the command mean for a batch of features.

        Args:
            features: Shape ``(batch, POLICY_FEATURE_COUNT)``.

        Returns:
            Shape ``(batch, command_dimension)``, in normalised coordinates.
        """
        output: torch.Tensor = self.head(self.body(features))
        return output
