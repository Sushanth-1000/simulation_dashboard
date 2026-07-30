"""L4 -- Core-A, the untrusted proposer, and what it is not allowed to know.

Untrusted is a design position, not an insult
----------------------------------------------
Core-A is the only learned component with a say in what the vehicle does, and
the entire architecture is built on the assumption that it will eventually be
wrong in a way nothing upstream detects. Treating it as untrusted is what lets
the rest of the system be simple: no gate has to reason about *why* a proposal
is bad, only whether it is.

What this layer cannot see
---------------------------
:meth:`CmdpProposer.propose` takes a tick, a state estimate and a Trust Index.
That is the whole surface. There is no parameter through which a verdict, a
fail-safe state, a calibration table or a veto rate could arrive, and the layer
holds a :class:`~astra.runtime.channels.ProposalWriter` whose public methods are
``send`` and ``pending`` -- there is no read direction to misuse.

This is SI-5, and it is adversarial rather than tidy. Core-A is trained by
optimisation, and anything it can observe it can learn to exploit. A proposer
that could see the gate would, given enough episodes, learn to slip past it,
which converts defence in depth into a single optimisation problem with the
safety monitor as its objective.

The Trust Index is the one Core-B-adjacent value that does reach Core-A, and it
reaches it here as a *monitoring* input. It never enters the training signal --
see :mod:`astra.layers.l4_proposer.signal` for why a monitoring input that
reaches the reward stops being one.

Why the policy is injected
---------------------------
The policy arrives as a callable rather than as a Stable-Baselines3 model held
inside this class. Three reasons, in order of importance:

*The safety argument should not depend on a reinforcement-learning library.*
Everything in this module -- the trust boundary, the actuation-space mapping,
the fail-closed behaviour -- is reviewable without reading SB3's source.

*It keeps the layer testable without a trained model.* A deterministic stub
policy exercises every path in this file, which is what lets the proposer be
verified before a GPU has been anywhere near it.

*It keeps the door open.* The Demo Plan's fallback controller is a PID, not a
network. Both satisfy the same callable, so switching between them is a
composition-root decision rather than a rewrite.

Failure policy
--------------
A policy that returns a non-finite value, or a vector of the wrong width, raises
rather than proposing. A malformed proposal is a Core-A fault, and Core-B is not
the right place to discover it: the gates would each report a different symptom
of the same broken upstream, and the evidence log would describe three failures
instead of one.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from astra.contracts.actuation import CommandOrigin, ControlCommand, ProposedCommand
from astra.kernel.enums import LayerId
from astra.kernel.errors import ConfigurationError, SafetyPathError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.contracts.actuation import ActuationSpace
    from astra.contracts.assurance import TrustAssessment
    from astra.contracts.estimation import FastStateEstimate
    from astra.kernel.identifiers import ComponentId, TickId
    from astra.kernel.time import Clock

__all__ = ["CmdpProposer", "Policy"]


@runtime_checkable
class Policy(Protocol):
    """A learned or deterministic map from observation to command vector.

    Structural, so a Stable-Baselines3 model wrapper, a PID fallback controller
    and a test stub all satisfy it without inheriting anything.
    """

    def act(self, observation: Sequence[float]) -> Sequence[float]:
        """Return a command vector for one observation.

        Args:
            observation: The observation vector, in the order the policy was
                trained on.

        Returns:
            A command vector aligned to the actuation space's channel order.
        """
        ...


class CmdpProposer:
    """Core-A. Satisfies :class:`~astra.ports.pipeline.CommandProposer`.

    Holds a policy, the actuation space it emits into, and the write end of the
    one-way channel. It holds no reader, no verdict and no gate.
    """

    __slots__ = ("_clock", "_component", "_policy", "_space")

    def __init__(
        self,
        *,
        policy: Policy,
        space: ActuationSpace,
        component: ComponentId,
        clock: Clock,
    ) -> None:
        """Build the proposer.

        Args:
            policy: The trained policy, or a deterministic fallback.
            space: The actuation space proposals are vectors over.
            component: The L4 component identity stamped on every proposal.
            clock: The injected clock.

        Raises:
            ConfigurationError: If the component is not an L4 component.
                :class:`~astra.contracts.actuation.ProposedCommand` refuses a
                non-L4 source at construction anyway, but failing here names the
                misconfiguration at start-up rather than on the first tick.
        """
        if component.layer is not LayerId.L4_CORE_A_CMDP:
            message = (
                f"the Core-A proposer must be constructed with an L4 component, got "
                f"{component.layer.value}; a proposal attributed to another layer would "
                f"misdescribe the trust boundary in the evidence log"
            )
            raise ConfigurationError(message, layer=component.layer)
        self._policy = policy
        self._space = space
        self._component = component
        self._clock = clock

    def propose(
        self, *, tick: TickId, state: FastStateEstimate, trust: TrustAssessment
    ) -> ProposedCommand:
        """Propose one command for this tick.

        Args:
            tick: The control tick.
            state: The current fast state estimate.
            trust: The Trust Index. A monitoring input: it is appended to the
                observation so the policy may condition on how confident the
                system is, and it never reaches the training signal (SI-6).

        Returns:
            The proposed command, ready to cross the one-way channel.

        Raises:
            SafetyPathError: If the state is non-finite, or if the policy
                returns a vector of the wrong width or containing a non-finite
                value. Discovering a malformed proposal here rather than in
                Core-B means the evidence log records one upstream fault instead
                of three gates each reporting a different symptom of it.
        """
        observation = (*state.mean, float(trust.trust_index))
        self._require_finite(tick, observation, what="observation")

        values = tuple(float(value) for value in self._policy.act(observation))
        if len(values) != self._space.dimension:
            message = (
                f"the policy returned {len(values)} values but the actuation space has "
                f"{self._space.dimension} channels {self._space.names}; a proposal of the "
                f"wrong width cannot be scored against this platform"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L4_CORE_A_CMDP,
                context={
                    "tick": tick.value,
                    "returned": len(values),
                    "expected": self._space.dimension,
                },
            )
        self._require_finite(tick, values, what="proposal")

        # Deliberately *not* clamped to the space. An inadmissible proposal is
        # exactly what the gates exist to catch, and silently clamping it here
        # would hide a misbehaving policy behind a correct-looking command --
        # the same reason `ControlCommand` does not reject one at construction.
        return ProposedCommand(
            tick=tick,
            proposed_at=self._clock.now(),
            command=ControlCommand(space=self._space, values=values),
            origin=CommandOrigin.PROPOSED,
            source=self._component,
        )

    @staticmethod
    def _require_finite(tick: TickId, values: Sequence[float], *, what: str) -> None:
        """Refuse to continue with a non-finite vector.

        Args:
            tick: The control tick.
            values: The vector to check.
            what: ``"observation"`` or ``"proposal"``, for the evidence record.

        Raises:
            SafetyPathError: If any entry is NaN or infinite.
        """
        offenders = [index for index, value in enumerate(values) if not math.isfinite(value)]
        if offenders:
            message = (
                f"the Core-A proposer cannot work with a non-finite {what} at indices "
                f"{offenders}; a NaN command would defeat every bound comparison in "
                f"Core-B rather than failing it"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L4_CORE_A_CMDP,
                context={"tick": tick.value, "indices": offenders, "source": what},
            )
