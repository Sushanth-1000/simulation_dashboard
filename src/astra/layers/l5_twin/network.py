r"""The twin's network and its physics residual.

Why the state is not fed in raw
--------------------------------
The fast estimate is ``[px, py, v, psi, a_lat]``, but the twin is given
``[v, sin(psi), cos(psi), a_lat]``. Two deliberate omissions and one
substitution:

*Position is dropped.* A twin that conditioned its prediction on absolute world
coordinates would learn the route it was trained on rather than the dynamics,
and would produce confident nonsense the first time the vehicle drove somewhere
new. Nothing in the one-step command prediction depends on where the vehicle is,
only on how it is moving.

*Heading enters as its sine and cosine.* Feeding ``psi`` directly puts a
discontinuity at :math:`\\pm\\pi` in the middle of the input space, and the
network would have to spend capacity learning that two numerically distant
inputs describe the same heading. The pair is continuous everywhere and carries
exactly the same information.

The physics residual
--------------------
A plain regressor fits whatever it was shown. The residual below is what makes
this twin *physics-informed*: the command it predicts must be consistent with
the lateral acceleration the vehicle is actually experiencing, through the
platform's configured control effectiveness.

    ``L_phys = (B . pi_hat - a_lat)^2``

``B`` maps a command vector to the lateral acceleration it produces. It is
configuration rather than code because it is a fact about one platform, and
baking it into the layer would put a vehicle assumption inside the core (NFR5).

This is a linearisation and is honestly weaker than the general relation
:math:`a_{lat} = v^2/R`: it ignores the speed dependence of the steering
response. It is nonetheless a real constraint on the prediction, and it is the
constraint that keeps the twin's output physically meaningful when the training
distribution runs out -- which is the situation the whole architecture exists
to survive.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final, override

import torch
from torch import nn

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["FEATURE_DIMENSION", "TwinNetwork", "physics_residual", "state_features"]

FEATURE_DIMENSION: Final = 4
"""Number of inputs the network takes: ``v``, ``sin(psi)``, ``cos(psi)``, ``a_lat``."""


class TwinNetwork(nn.Module):
    """A single-hidden-layer network mapping motion features to a command.

    Deliberately small. The twin sits on the hot path ahead of two gates, and a
    deep network would buy accuracy the architecture cannot spend: the twin's
    job is to be a physically-grounded reference point for the non-conformity
    score, not to be the controller. A large twin that fitted Core-A's policy
    closely would make every score small and quietly disarm the statistical
    gate.

    Attributes:
        hidden: The hidden layer.
        output: The output layer. Elastic weight consolidation updates *only*
            this layer, so it is a named attribute rather than an anonymous
            entry in a ``Sequential``.
    """

    def __init__(self, *, hidden_width: int, command_dimension: int) -> None:
        """Build the network.

        Args:
            hidden_width: Width of the hidden layer.
            command_dimension: Number of actuation channels to predict.
        """
        super().__init__()
        self.hidden = nn.Linear(FEATURE_DIMENSION, hidden_width)
        self.output = nn.Linear(hidden_width, command_dimension)

    @override
    def forward(self, features: torch.Tensor) -> torch.Tensor:
        """Predict a command for each row of features.

        Args:
            features: A ``(batch, FEATURE_DIMENSION)`` tensor.

        Returns:
            A ``(batch, command_dimension)`` tensor of predicted commands.
        """
        predicted: torch.Tensor = self.output(torch.tanh(self.hidden(features)))
        return predicted


def state_features(
    mean: Sequence[float], *, speed_index: int, heading_index: int, lateral_index: int
) -> tuple[float, ...]:
    """Build the network's input row from a fast state mean.

    Args:
        mean: The fast state mean, ordered per ``FAST_STATE_FIELDS``.
        speed_index: Index of the speed field.
        heading_index: Index of the heading field.
        lateral_index: Index of the lateral-acceleration field.

    Returns:
        ``(v, sin(psi), cos(psi), a_lat)``.
    """
    heading = mean[heading_index]
    return (mean[speed_index], math.sin(heading), math.cos(heading), mean[lateral_index])


def physics_residual(
    commands: torch.Tensor, lateral_acceleration: torch.Tensor, effectiveness: torch.Tensor
) -> torch.Tensor:
    """Return the mean squared Newtonian inconsistency of predicted commands.

    Args:
        commands: A ``(batch, command_dimension)`` tensor of predicted commands.
        lateral_acceleration: A ``(batch,)`` tensor of the lateral acceleration
            the state says the vehicle is experiencing.
        effectiveness: A ``(command_dimension,)`` tensor mapping a command to
            the lateral acceleration it produces.

    Returns:
        A scalar tensor: the mean squared difference between the acceleration
        the predicted command implies and the acceleration actually observed.
    """
    implied = commands @ effectiveness
    return torch.mean((implied - lateral_acceleration) ** 2)
