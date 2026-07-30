"""L9's hot path: deciding what the actuators actually receive.

The one rule that shapes everything else
------------------------------------------
:meth:`RuntimeCalibrationManager.issue` always returns a command. There is no
path through it that returns ``None`` and no verdict that makes it decline.

That is not permissiveness. A vehicle on a motorway that stops receiving
commands does not become safe; it becomes an obstacle whose behaviour nobody
predicted. Every system in the survey degrades to a halt, and this method is
where ASTRA declines to. What a VETO buys is a *different* command -- the
fallback controller's, or a capped one, or one inside the exploration envelope --
never no command.

Why the proposal is clamped here and nowhere earlier
------------------------------------------------------
:class:`~astra.contracts.actuation.ProposedCommand` deliberately permits an
inadmissible vector, because detecting one is the gates' job and a type that
could not represent a bad proposal would make the violation unrepresentable
rather than caught. :class:`~astra.contracts.actuation.IssuedCommand` refuses one
at construction.

Both are right, and this method is the seam between them: the gates see exactly
what Core-A asked for, and the actuators receive something admissible. Clamping
earlier would hide a misbehaving policy behind a correct-looking command.
Clamping later is impossible, because there is no later.

Why exploration narrows the *space* rather than the command
-------------------------------------------------------------
The exploration envelope bounds steering to a fifteen-degree cone. This layer
cannot apply that itself, because doing so would require knowing which channel
is steering -- a platform fact NFR5 keeps out of the core.

So the adapter, which does know, supplies a **restricted actuation space** whose
channel bounds already encode the envelope. L9 clamps to whichever space is in
force and never learns what a channel means. The same mechanism that makes the
ordinary clamp domain-independent makes the exploration clamp domain-independent.

The order of restriction
------------------------
Four regimes, most governing first: bounded exploration, then a blocking
verdict, then a fail-safe speed cap, then nominal. The origin recorded on the
issued command names which one applied, and that field is what lets the audit
log answer "why did the vehicle do that" -- finding R-7's definition of
explainability, which is decision provenance rather than model attribution.

Exploration outranks a blocking verdict because it is the regime in which least
is known: under an uncertified profile the fallback controller's assumptions are
no better supported than the policy's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from astra.contracts.actuation import CommandOrigin, ControlCommand, IssuedCommand
from astra.contracts.governance import ArbitrationDecision
from astra.kernel.enums import ArbitrationOutcome, LayerId
from astra.kernel.errors import ConfigurationError, SafetyPathError
from astra.kernel.units import Probability
from astra.layers.l9_rcm.knowledge_base import score_candidates
from astra.layers.l9_rcm.shadow import ShadowExecution

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from astra.contracts.actuation import ActuationSpace, ProposedCommand
    from astra.contracts.assurance import FailSafeSnapshot, SafetyVerdict, TrustAssessment
    from astra.contracts.governance import CalibrationProfile, RuntimeContextSignature
    from astra.kernel.identifiers import ComponentId, TickId
    from astra.kernel.time import Clock
    from astra.layers.l9_rcm.knowledge_base import SearchWeights

__all__ = ["SHADOW_PATIENCE", "FallbackController", "RuntimeCalibrationManager"]

SHADOW_PATIENCE: Final = 200
"""Comparisons after which a staging period that has not cleared is rolled back.

A staging period that never resolves is its own hazard: the candidate never
commits, the active table is never re-evaluated against anything else, and the
system sits indefinitely in a state whose evidence record says only "shadow
execution". Bounding it forces a decision either way.
"""


@runtime_checkable
class FallbackController(Protocol):
    """The deterministic controller that governs when a gate refuses.

    Takes no arguments. The port hands :meth:`RuntimeCalibrationManager.issue`
    no state estimate, and that is not an oversight to route around: a PID
    controller runs continuously and is fed by whoever owns it, so asking it for
    its current output is the honest interface. Passing it a state here would
    imply L9 drives it, which would put a controller inside the arbitrator.
    """

    def command(self) -> Sequence[float]:
        """Return the controller's current command vector.

        Returns:
            A vector aligned to the actuation space's channel order.
        """
        ...


class RuntimeCalibrationManager:
    """L9. Satisfies :class:`~astra.ports.pipeline.CalibrationArbiter`.

    Holds the knowledge base, the active profile, the fallback controller and
    any staging period in progress. The hot path reads; the cold path writes.
    """

    __slots__ = (
        "_active",
        "_clock",
        "_component",
        "_exploration_space",
        "_fallback",
        "_profiles",
        "_shadow",
        "_space",
        "_weights",
    )

    def __init__(
        self,
        *,
        component: ComponentId,
        space: ActuationSpace,
        clock: Clock,
        fallback: FallbackController,
        profiles: Sequence[CalibrationProfile],
        weights: SearchWeights,
        active: CalibrationProfile,
    ) -> None:
        """Build the arbiter.

        Args:
            component: The L9 identity stamped on every issued command.
            space: The nominal actuation space.
            clock: The injected clock.
            fallback: The deterministic controller for blocked ticks.
            profiles: The calibration knowledge base.
            weights: The four certified scoring weights.
            active: The profile in force. Required rather than optional: the
                system boots under a certified profile, and the tunnel scenario
                is "the active profile no longer matches", not "there is no
                active profile". An optional active profile would make every
                downstream record ambiguous about which of those it meant.

        Raises:
            ConfigurationError: If the component is not an L9 component. The
                contract refuses a non-L9 issuer anyway; failing here names the
                misconfiguration at start-up rather than on the first tick.
        """
        if component.layer is not LayerId.L9_RCM:
            message = (
                f"the calibration arbiter must be constructed with an L9 component, got "
                f"{component.layer.value}; SI-7 makes L9 the sole actuation authority, and "
                f"an arbitrator attributed elsewhere would misdescribe it"
            )
            raise ConfigurationError(message, layer=component.layer)
        self._component = component
        self._space = space
        self._clock = clock
        self._fallback = fallback
        self._profiles = tuple(profiles)
        self._weights = weights
        self._active = active
        self._shadow: ShadowExecution | None = None
        self._exploration_space: ActuationSpace | None = None

    @property
    def active_profile(self) -> CalibrationProfile:
        """Return the calibration profile currently in force."""
        return self._active

    @property
    def is_exploring(self) -> bool:
        """Return whether bounded safe exploration is engaged."""
        return self._exploration_space is not None

    @property
    def shadow(self) -> ShadowExecution | None:
        """Return the staging period in progress, if any."""
        return self._shadow

    def engage_exploration(self, restricted_space: ActuationSpace) -> None:
        """Enter bounded safe exploration inside a narrowed actuation space.

        Args:
            restricted_space: A space whose channel bounds already encode the
                exploration envelope. Built by the adapter, which knows which
                channel is steering; this layer only clamps to it.

        Raises:
            ConfigurationError: If the restricted space does not describe the
                same channels as the nominal one. A space with different
                channels is a different platform, not a narrower envelope.
        """
        if restricted_space.names != self._space.names:
            message = (
                f"the exploration space describes channels {restricted_space.names} but the "
                f"nominal space describes {self._space.names}; a different channel set is a "
                f"different platform rather than a narrower envelope"
            )
            raise ConfigurationError(
                message, layer=LayerId.L9_RCM, context={"channels": list(restricted_space.names)}
            )
        self._exploration_space = restricted_space

    def exit_exploration(self) -> None:
        """Leave bounded safe exploration and return to the nominal space."""
        self._exploration_space = None

    def issue(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        verdict: SafetyVerdict,
        failsafe: FailSafeSnapshot,
        trust: TrustAssessment,
    ) -> IssuedCommand:
        """Decide and issue the final actuator command for this tick.

        Args:
            tick: The control tick.
            proposal: The untrusted proposal.
            verdict: Core-B's combined verdict.
            failsafe: The FSM's posture, supplying the speed cap.
            trust: The Trust Index. Accepted because the port routes it to L9,
                and deliberately unused in this decision: it informs the cold
                path's calibration routing, and SI-4 keeps it out of any verdict.

        Returns:
            The command actually sent to the actuators. Never ``None``: a
            blocked tick yields the fallback controller's command, not silence.

        Raises:
            SafetyPathError: If the fallback controller returns a vector of the
                wrong width. There is no deeper fallback than the fallback, so
                it is the one failure this method cannot absorb.
        """
        del trust  # cold-path routing input; the hot-path decision does not read it

        if self._exploration_space is not None:
            return self._build(
                tick, self._clamp(proposal.command.values), CommandOrigin.EXPLORATION_BOUNDED
            )
        if verdict.is_blocking:
            return self._build(tick, self._fallback_values(tick), CommandOrigin.FALLBACK_PID)
        if failsafe.speed_cap is not None:
            return self._build(
                tick, self._clamp(proposal.command.values), CommandOrigin.SPEED_CAPPED
            )
        return self._build(tick, self._clamp(proposal.command.values), CommandOrigin.PROPOSED)

    def arbitrate(
        self,
        *,
        tick: TickId,
        signature: RuntimeContextSignature,
        threshold: float,
        divergence_limit: float,
        platform: str,
        now: datetime,
    ) -> ArbitrationDecision:
        """Run one cold-path evaluation of the knowledge base.

        Args:
            tick: The tick this evaluation is attributed to.
            signature: The current runtime context signature.
            threshold: ``tau``, the admissibility threshold.
            divergence_limit: ``delta_CDI``.
            platform: The platform the running system is certified for.
            now: The current time, for the expiry gate.

        Returns:
            The decision, naming the outcome and any candidate it concerns.
        """
        active_id = self._active.profile_id
        candidates, _ = score_candidates(
            signature=signature,
            profiles=self._profiles,
            weights=self._weights,
            platform=platform,
            now=now,
            active_profile_context=self._active.context_class,
        )
        admissible = [candidate for candidate in candidates if candidate.is_admissible(threshold)]

        if not admissible:
            self._shadow = None
            return ArbitrationDecision(
                tick=tick,
                outcome=ArbitrationOutcome.SAFE_EXPLORATION,
                active_profile=active_id,
            )

        best = admissible[0]
        if best.profile.profile_id == active_id:
            self._shadow = None
            return ArbitrationDecision(
                tick=tick, outcome=ArbitrationOutcome.CONTINUE, active_profile=active_id
            )

        if self._shadow is None:
            self._shadow = ShadowExecution()
            return self._staged(tick, active_id, best.profile.profile_id, best.trust_score, None)

        index = self._shadow.divergence_index
        if self._shadow.has_cleared(divergence_limit):
            self._active = best.profile
            self._shadow = None
            return ArbitrationDecision(
                tick=tick,
                outcome=ArbitrationOutcome.SWITCH_COMMITTED,
                active_profile=best.profile.profile_id,
                candidate_profile=best.profile.profile_id,
                trust_score=best.trust_score,
                calibration_divergence_index=Probability(index),
            )

        if self._shadow.sample_count >= SHADOW_PATIENCE:
            self._shadow = None
            return ArbitrationDecision(
                tick=tick,
                outcome=ArbitrationOutcome.ROLLBACK,
                active_profile=active_id,
                candidate_profile=best.profile.profile_id,
                trust_score=best.trust_score,
                calibration_divergence_index=Probability(index),
            )

        return self._staged(
            tick, active_id, best.profile.profile_id, best.trust_score, Probability(index)
        )

    @staticmethod
    def _staged(
        tick: TickId,
        active: object,
        candidate: object,
        score: float,
        index: Probability | None,
    ) -> ArbitrationDecision:
        """Build a SHADOW_EXECUTION decision.

        Args:
            tick: The control tick.
            active: The active profile identifier.
            candidate: The staged candidate's identifier.
            score: The candidate's ``T(c)``.
            index: The divergence index so far, or ``None`` on the first tick of
                the staging period, when no comparison has been made.

        Returns:
            The decision.
        """
        return ArbitrationDecision(
            tick=tick,
            outcome=ArbitrationOutcome.SHADOW_EXECUTION,
            active_profile=active,  # type: ignore[arg-type]
            candidate_profile=candidate,  # type: ignore[arg-type]
            trust_score=score,
            calibration_divergence_index=index,
        )

    def _fallback_values(self, tick: TickId) -> tuple[float, ...]:
        """Return the fallback controller's command, width-checked and clamped.

        Args:
            tick: The control tick.

        Returns:
            An admissible command vector.

        Raises:
            SafetyPathError: If the controller returns the wrong width.
        """
        raw = tuple(float(value) for value in self._fallback.command())
        if len(raw) != self._space.dimension:
            message = (
                f"the fallback controller returned {len(raw)} values but the actuation "
                f"space has {self._space.dimension} channels; there is no deeper fallback "
                f"than the fallback, so this tick cannot be recovered"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L9_RCM,
                context={"tick": tick.value, "returned": len(raw)},
            )
        return self._clamp(raw)

    def _clamp(self, values: Sequence[float]) -> tuple[float, ...]:
        """Confine a vector to whichever actuation space is in force.

        Args:
            values: The candidate vector.

        Returns:
            An admissible vector.
        """
        space = self._exploration_space or self._space
        return space.clamp(values)

    def _build(
        self, tick: TickId, values: tuple[float, ...], origin: CommandOrigin
    ) -> IssuedCommand:
        """Construct the issued command.

        Args:
            tick: The control tick.
            values: An admissible command vector.
            origin: Which regime produced it.

        Returns:
            The issued command.
        """
        return IssuedCommand(
            tick=tick,
            issued_at=self._clock.now(),
            command=ControlCommand(space=self._space, values=values),
            origin=origin,
            issuer=self._component,
        )
