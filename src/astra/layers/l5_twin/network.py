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

from astra.kernel.enums import ContextClass

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["FEATURE_DIMENSION", "TwinNetwork", "physics_residual", "state_features"]

FEATURE_DIMENSION: Final = 4
"""Number of inputs the network takes: ``v``, ``sin(psi)``, ``cos(psi)``, ``a_lat``."""


class TwinNetwork(nn.Module):
    """A shared trunk with one output head per operational context.

    Deliberately small. The twin sits on the hot path ahead of two gates, and a
    deep network would buy accuracy the architecture cannot spend: the twin's
    job is to be a physically-grounded reference point for the non-conformity
    score, not to be the controller. A large twin that fitted Core-A's policy
    closely would make every score small and quietly disarm the statistical
    gate.

    Why the heads are per context
    -----------------------------
    Two reasons, and the second is the stronger one.

    *Forgetting becomes impossible rather than penalised.* FB2 adapts one head,
    so a rainstorm cannot write to the parameters the highway is read from.
    Before ADR-0019 this was the job of an elastic-weight-consolidation penalty,
    which was measured on 2 August 2026 and found to be a brake rather than a
    consolidator: across every value of its strength, the ratio of forgetting to
    learning was constant to three significant figures. It could not be
    otherwise -- adaptation touched a single 16x2 readout that both contexts used
    in full, so there was no disjoint subspace for a Fisher-weighted penalty to
    protect.

    *The non-conformity score's two operands are now conditioned alike.*
    ``alpha = |pi_prop - pi_hat| / sigma(x)`` is compared against a **per-context**
    conformal quantile, but ``pi_hat`` came from a context-blind twin. L3, L6 and
    L9 are all Mondrian-conditioned on :class:`~astra.kernel.enums.ContextClass`;
    L5 was the only component that was not. This is a correctness fix that would
    be worth making even if forgetting were not a problem.

    :attr:`~astra.kernel.enums.ContextClass.UNCLASSIFIED` gets a head like the
    others and is **never adapted**. It is the pristine offline-trained twin, and
    it is what answers when the context is unknown -- a twin that rewrote itself
    while it could not tell where it was would be the failure mode the whole
    architecture exists to prevent.

    Attributes:
        hidden: The shared trunk. Frozen during adaptation, so every head keeps
            reading the same features and the heads stay comparable.
        heads: One output layer per context, keyed by the context's value.
    """

    def __init__(self, *, hidden_width: int, command_dimension: int) -> None:
        """Build the network.

        Args:
            hidden_width: Width of the shared hidden layer.
            command_dimension: Number of actuation channels to predict.
        """
        super().__init__()
        self.hidden = nn.Linear(FEATURE_DIMENSION, hidden_width)
        self.heads = nn.ModuleDict(
            {context.value: nn.Linear(hidden_width, command_dimension) for context in ContextClass}
        )

    def head(self, context: ContextClass | None) -> nn.Linear:
        """Return the output layer for a context.

        Args:
            context: The operational context, or ``None`` when no classification
                was produced this tick.

        Returns:
            That context's head, or ``UNCLASSIFIED``'s when the context is
            unknown -- which is the untouched offline twin.
        """
        key = (context or ContextClass.UNCLASSIFIED).value
        selected: nn.Linear = self.heads[key]  # type: ignore[assignment]
        return selected

    def seed_heads_from(self, context: ContextClass = ContextClass.UNCLASSIFIED) -> None:
        """Copy one head into every other, discarding their initialisation.

        Offline training fits the trunk and a *single* head -- there is no corpus
        of per-context data to fit the rest against, and inventing one would be
        worse than admitting there is none. Without this call the other heads
        keep their random initialisation, and a twin loaded from that checkpoint
        would predict noise in every context but one. That defect shipped for
        about an hour on 2 August 2026 and was caught by
        ``test_l5_forgetting.py`` refusing to agree that the offline twin knew
        the highway.

        Broadcasting is also the semantically right answer rather than merely a
        repair: the offline twin *is* the common starting point every context
        then adapts away from, which is exactly what a pre-ADR-0019 checkpoint
        means when it is migrated.

        Args:
            context: The head to copy from.
        """
        source = self.head(context)
        with torch.no_grad():
            for name, head in self.heads.items():
                if name == context.value:
                    continue
                head.weight.copy_(source.weight)  # type: ignore[operator]
                head.bias.copy_(source.bias)  # type: ignore[operator]

    @override
    def forward(self, features: torch.Tensor, context: ContextClass | None = None) -> torch.Tensor:
        """Predict a command for each row of features.

        Args:
            features: A ``(batch, FEATURE_DIMENSION)`` tensor.
            context: Which head to read. All rows share one, because a batch is
                one context's buffer by construction -- ``adapt`` discards the
                partial buffer when the context changes precisely so that no
                update ever mixes two.

        Returns:
            A ``(batch, command_dimension)`` tensor of predicted commands.
        """
        predicted: torch.Tensor = self.head(context)(torch.tanh(self.hidden(features)))
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
