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
Three regimes select a command -- a blocking verdict first, then bounded
exploration, then nominal -- and the fail-safe speed cap is then applied to
whichever of them governed. The origin recorded on the issued command names what
shaped it, and that field is what lets the audit log answer "why did the vehicle
do that" -- finding R-7's definition of explainability, which is decision
provenance rather than model attribution.

**The cap is applied last rather than being a fourth regime**, because a posture
is not a branch. As a branch it was reachable only on a tick that was neither
blocked nor exploring, so in HALT -- where every tick is blocked -- it was never
consulted at all; and the branch clamped to the actuation space exactly as the
uncapped one did, so it changed nothing when it *was* reached. A 100,000-tick run
held 17.2 m/s in HALT, whose cap is 0.0 m/s, with 99,000 ticks recorded as
capped. If the FSM says the vehicle may not exceed a speed, that is equally true
of the fallback's command and the rate limiter's.

**The verdict comes first, and that ordering is ADR-0016.** It used to be the
other way round, on the reasoning that under an uncertified profile the
fallback's assumptions are no better supported than the policy's. That reasoning
is sound and the conclusion did not follow: it made a veto advisory whenever the
envelope was engaged, and at the shipped operating point the envelope is engaged
almost always. Measured before the change: 99,808 of 100,000 ticks issued the
proposal under a blocking verdict. What was really wrong was upstream -- a gate
with no calibration for the context was *vetoing* rather than abstaining, so
exploration had to override something that should never have been said.

What a blocked tick yields
--------------------------
The fallback's command, or -- where the objection was specifically that the
proposal changed lateral acceleration too fast -- the largest step toward it that
the jerk bound permits. That second case is ADR-0017, and it exists because zero
steering is, of every available command, the one that most guarantees the *next*
proposal is equally inadmissible: it pins the achieved acceleration at zero,
which is exactly what the bound is measured from. The vetoed proposal is still
not issued; a different, admissible command is.
"""

from __future__ import annotations

import math
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
    from astra.contracts.estimation import FastStateEstimate
    from astra.contracts.governance import CalibrationProfile, RuntimeContextSignature
    from astra.kernel.identifiers import ComponentId, TickId
    from astra.kernel.time import Clock
    from astra.layers.l9_rcm.knowledge_base import SearchWeights
    from astra.ports.pipeline import CommandProjector

__all__ = ["SHADOW_PATIENCE", "FallbackController", "RuntimeCalibrationManager"]

# The physical gate's evidence keys that rate limiting reads. Named here rather
# than imported from L7b: the arbitrator must not depend on a gate's module, and
# these three are part of the evidence *record* -- a schema shared through the
# audit log, not a private detail of the component that writes it. Pinned by
# `test_l9_arbiter.py`, which fails if either side renames one.
_EVIDENCE_CURRENT: Final = "current_lateral_acceleration_mps2"
_EVIDENCE_PROPOSED: Final = "proposed_lateral_acceleration_mps2"
_EVIDENCE_JERK: Final = "demanded_jerk_mps3"
_EVIDENCE_JERK_LIMIT: Final = "max_lateral_jerk_mps3"

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
        "_exploration_speed_cap",
        "_fallback",
        "_profiles",
        "_projector",
        "_rate_limited_reasons",
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
        projector: CommandProjector | None = None,
        rate_limited_reasons: frozenset[str] = frozenset(),
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
            projector: Turns a target lateral acceleration back into a command
                vector. ``None`` disables rate limiting entirely and the
                fallback governs every blocked tick, which is the behaviour
                every run before ADR-0017 had.
            rate_limited_reasons: The gate reason codes a bounded approach can
                satisfy. Empty by default, and supplied by the composition root
                rather than imported: which reasons are rate-limitable is a fact
                about how the gates are configured, and
                :mod:`astra.runtime.assembly` is the module that decides what
                every layer is. Importing the constant from L7b would give the
                arbitrator an opinion about a gate's internal vocabulary.

                **Only reasons that are genuinely about rate belong here.** A
                twin-divergence veto is not a rate problem, and ratcheting
                toward a divergent proposal would walk the vehicle to it in
                bounded steps -- defeating the gate rather than respecting it.

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
        self._projector = projector
        self._rate_limited_reasons = rate_limited_reasons
        self._shadow: ShadowExecution | None = None
        self._exploration_space: ActuationSpace | None = None
        self._exploration_speed_cap: float | None = None

    @property
    def space(self) -> ActuationSpace:
        """Return the nominal actuation space, before any narrowing.

        Exposed so the cold path can derive an exploration envelope from the
        space commands are actually issued in, rather than being handed a second
        copy that could drift from it.
        """
        return self._space

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

    def engage_exploration(
        self, restricted_space: ActuationSpace, *, speed_cap: float | None = None
    ) -> None:
        """Enter bounded safe exploration inside a narrowed actuation space.

        Args:
            restricted_space: A space whose channel bounds already encode the
                exploration envelope. Built by the adapter, which knows which
                channel is steering; this layer only clamps to it.
            speed_cap: The envelope's maximum speed, in m/s, or ``None`` to
                bound nothing.

                **This parameter exists because OD-13 was that it did not.**
                A narrowed *space* bounds how much throttle may be commanded on
                any one tick; it does not bound the speed that results. Measured
                on a platform with weak brakes, the vehicle explored for all 600
                ticks while accelerating monotonically to **23.10 m/s** -- above
                the calibrated baseline's 12.54 -- with no gate objecting,
                because no gate had been given the number to object with. The
                envelope computed a cap and enforced it against nothing.

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
        self._exploration_speed_cap = speed_cap

    def exit_exploration(self) -> None:
        """Leave bounded safe exploration and return to the nominal space."""
        self._exploration_space = None
        self._exploration_speed_cap = None

    def issue(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        verdict: SafetyVerdict,
        failsafe: FailSafeSnapshot,
        trust: TrustAssessment,
        state: FastStateEstimate,
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
            state: The current fast state estimate. Read for one thing only --
                the speed the fail-safe cap is compared against. A cap in m/s
                cannot be enforced without knowing how fast the vehicle is
                going, and inferring it from the command would be modelling the
                platform inside the arbitrator.

        Returns:
            The command actually sent to the actuators. Never ``None``: a
            blocked tick yields the fallback controller's command, not silence.

        Raises:
            SafetyPathError: If the fallback controller returns a vector of the
                wrong width. There is no deeper fallback than the fallback, so
                it is the one failure this method cannot absorb.
        """
        del trust  # cold-path routing input; the hot-path decision does not read it

        # The verdict is tested first, and nothing below it can reach the
        # actuators past a VETO. That ordering is ADR-0016, and it replaced one
        # in which the exploration envelope was tested *first* -- which made a
        # veto advisory whenever exploration was engaged. Measured before the
        # change: 99,808 of 100,000 ticks issued the proposal under a blocking
        # verdict, because at the shipped operating point exploration is engaged
        # almost always.
        #
        # Exploration no longer needs to out-rank anything. The verdicts it used
        # to override were L6 declaring a proposal anomalous against a
        # calibration it does not hold for the context; L6 now abstains there,
        # so there is no veto left to work around, and the two gates whose
        # bounds are configuration rather than calibration keep full authority
        # inside the envelope exactly as they do outside it.
        chosen, origin = self._govern(tick, proposal, verdict)

        # The cap is applied to whatever governed, last, rather than being one
        # branch among several. It used to be a fourth branch -- reachable only
        # on a tick that was neither blocked nor exploring -- and that branch
        # called the same `_clamp` as the uncapped one, so `SPEED_CAPPED`
        # labelled a command bit-identical to `PROPOSED`. Measured: a
        # 100,000-tick run held 17.2 m/s in HALT, whose cap is 0.0 m/s, and
        # 99,000 of those ticks were recorded as capped.
        #
        # A posture is not a branch. If the FSM says the vehicle may not exceed
        # a speed, that is true of the fallback's command and the rate limiter's
        # too, and most of all in HALT -- where the old ordering meant the cap
        # was never even consulted, because a blocked tick returned first.
        capped = self._speed_capped(chosen, failsafe, state)
        if capped is not None:
            return self._build(tick, capped, CommandOrigin.SPEED_CAPPED)
        return self._build(tick, chosen, origin)

    def _govern(
        self, tick: TickId, proposal: ProposedCommand, verdict: SafetyVerdict
    ) -> tuple[tuple[float, ...], CommandOrigin]:
        """Return the command the regimes select, before any speed cap.

        Args:
            tick: The control tick.
            proposal: The untrusted proposal.
            verdict: Core-B's combined verdict.

        Returns:
            The command and the origin naming which regime produced it.
        """
        if verdict.is_blocking:
            limited = self._rate_limited(proposal, verdict)
            if limited is not None:
                return limited, CommandOrigin.RATE_LIMITED
            return self._fallback_values(tick), CommandOrigin.FALLBACK_PID
        if self._exploration_space is not None:
            return self._clamp(proposal.command.values), CommandOrigin.EXPLORATION_BOUNDED
        return self._clamp(proposal.command.values), CommandOrigin.PROPOSED

    def _speed_capped(
        self,
        values: tuple[float, ...],
        failsafe: FailSafeSnapshot,
        state: FastStateEstimate,
    ) -> tuple[float, ...] | None:
        """Return the command with whichever speed cap binds, or ``None``.

        ``None`` means the cap did not change anything -- either no cap is in
        force, no projector was supplied, or the vehicle is already within it.
        That is what makes :attr:`~astra.contracts.actuation.CommandOrigin.SPEED_CAPPED`
        mean something: it now labels a command the cap *altered*, rather than
        one issued while a cap happened to be reported.

        Args:
            values: The command the regimes selected.
            failsafe: The FSM's posture, supplying one of the two caps.
            state: The current fast state estimate, supplying the speed.

        Returns:
            The capped command, or ``None`` if the cap did not bind.
        """
        # The tighter of the two caps in force. The fail-safe machine's cap
        # answers "how degraded is the posture"; the exploration envelope's
        # answers "how far outside its certified envelope is the vehicle". Both
        # are real bounds and neither subsumes the other, so the binding one is
        # whichever is lower -- and taking the minimum means adding exploration
        # can only ever tighten, never loosen, a cap already in force.
        candidates = [
            value
            for value in (failsafe.speed_cap, self._exploration_speed_cap)
            if value is not None
        ]
        if not candidates or self._projector is None:
            return None
        cap = min(float(value) for value in candidates)
        capped = self._clamp(
            self._projector.with_speed_cap(values, current_speed=float(state.speed), cap=float(cap))
        )
        return None if capped == values else capped

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
                signature=signature,
            )

        best = admissible[0]
        if best.profile.profile_id == active_id:
            self._shadow = None
            return ArbitrationDecision(
                tick=tick,
                outcome=ArbitrationOutcome.CONTINUE,
                active_profile=active_id,
                signature=signature,
            )

        if self._shadow is None:
            self._shadow = ShadowExecution()
            return self._staged(
                tick=tick,
                active=active_id,
                candidate=best.profile.profile_id,
                score=best.trust_score,
                index=None,
                signature=signature,
            )

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
                signature=signature,
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
                signature=signature,
            )

        return self._staged(
            tick=tick,
            active=active_id,
            candidate=best.profile.profile_id,
            score=best.trust_score,
            index=Probability(index),
            signature=signature,
        )

    @staticmethod
    def _staged(
        *,
        tick: TickId,
        active: object,
        candidate: object,
        score: float,
        index: Probability | None,
        signature: RuntimeContextSignature,
    ) -> ArbitrationDecision:
        """Build a SHADOW_EXECUTION decision.

        Args:
            tick: The control tick.
            active: The active profile identifier.
            candidate: The staged candidate's identifier.
            score: The candidate's ``T(c)``.
            index: The divergence index so far, or ``None`` on the first tick of
                the staging period, when no comparison has been made.
            signature: The context this decision was taken about.

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
            signature=signature,
        )

    def _rate_limited(
        self, proposal: ProposedCommand, verdict: SafetyVerdict
    ) -> tuple[float, ...] | None:
        """Return the largest admissible step toward a rate-vetoed proposal.

        The deadlock this exists to break, in four lines: the fallback commands
        zero steering, so the vehicle's lateral acceleration is pinned at zero; a
        proposal correcting a large lane error is then always a step too big from
        there; it is vetoed; and the fallback governs again, re-establishing the
        pin. A proposal only moves the achieved acceleration if it is *executed*,
        so no proposer -- however well trained -- can climb a ramp it is never
        allowed to stand on. Measured across three policies: the vehicle left the
        lane and never came back.

        The answer is the one every physical actuator already implements. The
        gate is not wrong; the tyres genuinely cannot make that transition in one
        tick. What was wrong was substituting the single worst command for
        re-approaching the target. This issues the step the bound permits, in the
        direction asked for, so the achieved acceleration advances by at most the
        limit per tick and the proposal becomes admissible on its own after a few
        of them.

        **The veto is not overridden.** The proposal is not issued; a different
        command is, derived from the very bound that refused it and therefore
        admissible under it by construction. ADR-0016 is untouched.

        Returns ``None`` -- deferring to the fallback -- whenever anything is not
        exactly right: no projector, no rate-limitable reason, a blocking verdict
        from any other gate, or evidence that does not carry the three numbers
        this needs. Every one of those is a case where a bounded approach is not
        obviously correct, and the fallback is the answer that needs no argument.

        Args:
            proposal: The vetoed proposal.
            verdict: Core-B's combined verdict, whose gate evidence supplies the
                current and proposed lateral accelerations and the bound. Read
                from the record rather than recomputed, so that one projection
                exists in the system rather than two that could disagree.

        Returns:
            An admissible command vector, or ``None`` to use the fallback.
        """
        if self._projector is None or not self._rate_limited_reasons:
            return None

        blocking = [gate for gate in verdict.gate_verdicts if gate.verdict.is_blocking]
        if not blocking or any(
            gate.reason_code not in self._rate_limited_reasons for gate in blocking
        ):
            # Something other than a rate bound objected. Approaching the
            # proposal in small steps would not answer it -- it would arrive at
            # the refused command a few ticks later, which is worse than
            # refusing it outright because it looks like compliance.
            return None

        evidence = dict(blocking[0].evidence)
        try:
            current = evidence[_EVIDENCE_CURRENT]
            proposed = evidence[_EVIDENCE_PROPOSED]
            limit = evidence[_EVIDENCE_JERK_LIMIT]
        except KeyError:
            return None
        if not all(math.isfinite(value) for value in (current, proposed, limit)):
            return None

        step = limit * self._tick_period_from(evidence)
        target = current + math.copysign(min(step, abs(proposed - current)), proposed - current)
        return self._clamp(
            self._projector.with_lateral_acceleration(proposal.command.values, target)
        )

    @staticmethod
    def _tick_period_from(evidence: dict[str, float]) -> float:
        """Recover the tick period the gate computed its jerk over.

        The gate publishes the demanded jerk and the accelerations it came from,
        so the period is recoverable rather than needing to be injected -- which
        keeps the arbitrator from holding a second copy of a number that would
        silently disagree if the tick rate changed.

        Args:
            evidence: The physical gate's evidence for this tick.

        Returns:
            The period in seconds, or ``0.0`` if the jerk was zero and the
            period cannot be recovered -- in which case the step is zero and the
            caller issues the current acceleration unchanged, which is safe.
        """
        jerk = abs(evidence.get(_EVIDENCE_JERK, 0.0))
        delta = abs(evidence[_EVIDENCE_PROPOSED] - evidence[_EVIDENCE_CURRENT])
        return delta / jerk if jerk > 0.0 else 0.0

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
