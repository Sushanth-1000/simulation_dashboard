"""The interface each of the nine pipeline layers implements.

Why ports exist before any layer does
-------------------------------------
Phase 1 deliberately ships no layer logic. It ships the *shape* of every layer,
for three reasons that all pay off later.

1. **The dependency graph is fixed now.** With every layer expressed as a
   protocol over contracts, the composition root can wire a pipeline out of
   fakes before a single UKF exists, and the architecture fitness contracts have
   something concrete to constrain. A port added after its implementation is a
   description of what was built; a port added before is a decision about what
   may be built.

2. **Substitutability is the testing strategy.** Every exit criterion in the
   roadmap is of the form "layer X validated in isolation before it is wired to
   anything". That is only possible if X's collaborators can be replaced by
   trivial stand-ins. These protocols are structural, so a five-line fake in
   ``tests/`` satisfies one with no inheritance and no registration.

3. **The unit policy is enforced at the boundary.** No signature here mentions
   a non-SI type: :data:`~astra.kernel.units.KilometresPerHour` and
   :data:`~astra.kernel.units.Degrees` exist so human-facing values are visible
   in configuration and adapters, and an architecture test asserts they never
   reach a port.

Design decision: ``Protocol``, not an abstract base class
---------------------------------------------------------
Structural typing keeps the dependency arrow pointing the right way. An adapter
implementing :class:`SensorSource` does not import an ASTRA base class, so the
CARLA adapter never inherits from the core and the core never learns that CARLA
exists. That is what makes the R-6 interpreter problem a deployment detail
rather than an architectural one, and what delivers the domain independence
NFR5 demands.

Protocols are ``@runtime_checkable`` where the check is cheap and useful --
which for a protocol means an ``isinstance`` test of *method presence only*,
never of signatures. The composition root uses it as a wiring sanity check, not
as a substitute for type checking.

Separation invariants visible in these signatures
-------------------------------------------------
* :class:`CommandProposer` (L4, Core-A) takes state and trust, and returns a
  proposal. It is given no verdict, no FSM state and no calibration table, so
  the one-way channel of SI-5 is expressed in the type, not just the wiring.
* :class:`DeterministicShield` (L7a) takes *only* the state estimate. It cannot
  see the twin's prediction or the statistical gate's score, which is what makes
  its veto structurally independent (R-3).
* No gate protocol receives a :class:`~astra.contracts.assurance.TrustAssessment`,
  which is SI-4 in signature form.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.contracts.actuation import (
        ControlCommand,
        IssuedCommand,
        PredictedCommand,
        ProposedCommand,
    )
    from astra.contracts.assurance import (
        FailSafeSnapshot,
        GateVerdict,
        SafetyVerdict,
        TrustAssessment,
    )
    from astra.contracts.estimation import FastStateEstimate, InnovationRecord, SlowStateEstimate
    from astra.contracts.governance import (
        ArbitrationDecision,
        CalibrationProfile,
        RuntimeContextSignature,
    )
    from astra.contracts.sensing import FusedSensorFrame
    from astra.kernel.identifiers import TickId

__all__ = [
    "CalibrationArbiter",
    "CommandProjector",
    "CommandProposer",
    "DeterministicShield",
    "DynamicsPredictor",
    "PhysicalAdmissibilityChecker",
    "SafetyStateMachine",
    "SensorSource",
    "StateEstimator",
    "StatisticalGate",
    "TrustEstimator",
]


@runtime_checkable
class SensorSource[PayloadT](Protocol):
    """L1 -- the shared sensor bus.

    The only component permitted to touch raw sensor payloads (SI-1). Generic in
    the payload so the pipeline stays domain-independent while an adapter binds
    a concrete measurement type.
    """

    def acquire(self, tick: TickId) -> FusedSensorFrame[PayloadT]:
        """Acquire and fuse one tick's readings from every available modality.

        Args:
            tick: The control tick to acquire for.

        Returns:
            The fused frame, including the modalities that produced nothing.

        Raises:
            AdapterError: If the underlying sensor transport failed.
        """
        ...


@runtime_checkable
class StateEstimator[PayloadT](Protocol):
    """L2 -- the dual-rate unscented Kalman filter.

    The sole source of state for every layer above it (SI-2), and therefore the
    system's single common-cause channel. Generic in the payload for the same
    reason :class:`SensorSource` is: ``FusedSensorFrame`` is invariant in its
    payload, so a non-generic protocol would only ever be satisfiable by an
    estimator written against ``object`` -- which is every estimator except the
    real ones. The fast and slow updates are separate
    methods because they run at different rates: the caller drives the fast
    filter every tick and the slow filter on its own schedule.
    """

    def update_fast(self, frame: FusedSensorFrame[PayloadT]) -> FastStateEstimate:
        """Run the 20 Hz update and return the new fast state and covariance.

        Args:
            frame: This tick's fused sensor frame.

        Returns:
            The updated fast estimate ``(x_f, P_f)``.

        Raises:
            SafetyPathError: If the filter could not complete its update.
        """
        ...

    def update_slow(self, frame: FusedSensorFrame[PayloadT]) -> SlowStateEstimate:
        """Run the slow update tracking the degradation parameters.

        Args:
            frame: The fused sensor frame at the slow filter's cadence.

        Returns:
            The updated slow estimate.

        Raises:
            SafetyPathError: If the filter could not complete its update.
        """
        ...

    def latest_innovation(self) -> InnovationRecord | None:
        """Return the most recent innovation record.

        Feeds two consumers: the Mahalanobis sensor-fault monitor, and the
        rolling innovation distribution the statistical gate uses as its
        physics-grounded covariate-shift signal.

        Returns:
            The latest innovation, or ``None`` before the first update.
        """
        ...


@runtime_checkable
class TrustEstimator(Protocol):
    """L3 -- the conformal Trust Module.

    Produces the Trust Index by Mondrian-conditioned conformal prediction. Its
    output routes to L4 and L9 only; by SI-4 it never participates in Core-B's
    verdict.
    """

    def assess(
        self,
        *,
        tick: TickId,
        state: FastStateEstimate,
        innovation: InnovationRecord | None,
    ) -> TrustAssessment:
        """Estimate how typical the current situation is for its context class.

        Args:
            tick: The control tick.
            state: The current fast state estimate.
            innovation: The latest innovation record, if the filter has run.

        Returns:
            The Trust Index with the class and quantile that produced it.
        """
        ...

    def recalibrate(self, *, non_conformity_score: float, was_correct: bool) -> None:
        """Update the class-conditional quantiles from an executed outcome.

        This is feedback loop FB3. Kept on the protocol rather than hidden inside
        the implementation because the roadmap requires each loop to be brought
        up, measured and removable one at a time.

        Args:
            non_conformity_score: The realised score for the executed command.
            was_correct: Whether the executed outcome matched the prediction
                within the certified tolerance.
        """
        ...


@runtime_checkable
class CommandProposer(Protocol):
    """L4 -- Core-A, the untrusted constrained-MDP proposer.

    Takes state and trust; returns a proposal. It is deliberately given no way
    to observe Core-B: no verdict, no FSM state, no calibration table and no
    veto rate appear in this signature. That is separation invariant SI-5 (and
    SI-6) expressed as a type rather than as a convention.
    """

    def propose(
        self,
        *,
        tick: TickId,
        state: FastStateEstimate,
        trust: TrustAssessment,
    ) -> ProposedCommand:
        """Propose one command for this tick.

        Args:
            tick: The control tick.
            state: The current fast state estimate.
            trust: The Trust Index, as a monitoring input only.

        Returns:
            The proposed command ``pi_prop``, to cross the one-way channel.
        """
        ...


@runtime_checkable
class DynamicsPredictor(Protocol):
    """L5 -- the physics-informed digital twin inside Core-B.

    Predicts the command the modelled physics expects next. The departure of the
    untrusted proposal from this prediction, normalised by state uncertainty, is
    the statistical gate's non-conformity score.
    """

    def predict(self, *, tick: TickId, state: FastStateEstimate) -> PredictedCommand:
        """Predict the next command from the current state.

        Args:
            tick: The control tick.
            state: The current fast state estimate.

        Returns:
            The predicted command ``pi_hat_{t+1}``.

        Raises:
            SafetyPathError: If the twin could not produce a prediction.
        """
        ...

    def adapt(self, *, applied: ControlCommand, measured: FastStateEstimate) -> None:
        """Adapt the twin from a measured outcome under elastic weight consolidation.

        Feedback loop FB2. The implementation updates the output layer only,
        Fisher-anchored on historical samples, so that adapting to a new context
        does not catastrophically forget an old one.

        Args:
            applied: The command that was actually applied.
            measured: The state measured after applying it.
        """
        ...


@runtime_checkable
class StatisticalGate(Protocol):
    """L6 -- the inductive conformal prediction gate. Fires on a statistical anomaly.

    Computes ``alpha = |pi_prop - pi_hat| / sigma(x)`` with
    ``sigma(x) = sqrt(P_f[control dim])`` and compares it against the
    class-conditional quantile, tightening the significance level when the
    covariate-shift detector fires.

    Its failure mode is distinctive and is the reason there is more than one
    gate: the conformal coverage guarantee assumes exchangeability, which an
    adversarial perturbation violates by construction.
    """

    def evaluate(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        prediction: PredictedCommand,
        state: FastStateEstimate,
    ) -> GateVerdict:
        """Score the proposal against the conformal acceptance band.

        Args:
            tick: The control tick.
            proposal: The untrusted proposed command.
            prediction: The twin's prediction.
            state: The fast estimate, supplying ``sigma(x)`` from ``P_f``.

        Returns:
            A verdict tagged :attr:`~astra.kernel.enums.GateId.STATISTICAL`,
            carrying the score and threshold as evidence.

        Raises:
            SafetyPathError: If the gate could not complete its evaluation, in
                which case the caller treats the tick as a VETO.
        """
        ...


@runtime_checkable
class PhysicalAdmissibilityChecker(Protocol):
    """L7b -- the physical gate. Fires when the predicted next state is not admissible.

    Distinct from the deterministic shield: this gate asks whether the predicted
    evolution is *Newtonian-admissible* according to the twin, so its failure
    mode is PINN drift beyond what elastic weight consolidation can correct. The
    shield asks only whether a hard bound is exceeded. Splitting them is finding
    R-3, and it is what lets the shield remain independent of L5 and L6 while
    the physical recheck still exists.
    """

    def evaluate(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        prediction: PredictedCommand,
        state: FastStateEstimate,
    ) -> GateVerdict:
        """Check the physical admissibility of the proposal's predicted outcome.

        Args:
            tick: The control tick.
            proposal: The untrusted proposed command.
            prediction: The twin's prediction of the next command.
            state: The current fast state estimate.

        Returns:
            A verdict tagged :attr:`~astra.kernel.enums.GateId.PHYSICAL`.

        Raises:
            SafetyPathError: If admissibility could not be determined.
        """
        ...


@runtime_checkable
class CommandProjector(Protocol):
    """Turns a target lateral acceleration back into a command vector.

    The one piece of platform knowledge L9 needs and cannot derive: which
    channel steers, and how much lateral acceleration a unit of it produces.
    Supplied by the adapter, exactly as the actuation space is, so that NFR5's
    domain independence survives -- a warehouse AGV supplies a different
    projector and no layer changes.

    Why only the inverse direction
    -------------------------------
    The forward projection already exists and is already published. L7b computes
    the proposal's implied lateral acceleration to evaluate its jerk bound, and
    records it, the current value and the limit in the verdict's evidence. L9
    reads those three numbers rather than recomputing them, which keeps one
    projection in the system instead of two that could disagree -- and two that
    disagreed would mean the arbitrator was rate-limiting toward a target the
    gate would not recognise.

    See ADR-0017 for why L9 needs this at all.
    """

    def with_lateral_acceleration(
        self, values: Sequence[float], target: float
    ) -> tuple[float, ...]:
        """Return the command vector that produces a target lateral acceleration.

        Every other channel is carried through unchanged: the projector adjusts
        the vehicle's *path*, never its speed. A rate-limited command is a
        bounded step toward what the proposer asked for laterally, and it must
        not quietly become a longitudinal intervention as well.

        Args:
            values: The command vector to adjust, in actuation-space order.
            target: The lateral acceleration the result should imply, in m/s^2.

        Returns:
            A vector in the same space. Not clamped to it: the caller owns
            admissibility, as it does everywhere else on this path.
        """
        ...

    def with_speed_cap(
        self, values: Sequence[float], *, current_speed: float, cap: float
    ) -> tuple[float, ...]:
        """Return the command with propulsion withdrawn if the cap is exceeded.

        The other half of the platform knowledge L9 lacks. A fail-safe speed cap
        arrives in m/s and the actuation space is throttle, brake and steer;
        turning one into the other needs to know which channel drives, which
        brakes, and that steering is none of its business.

        **Braking, not just coasting.** Withdrawing propulsion is not enough:
        HALT's cap is 0.0 m/s -- a commanded stop -- and a vehicle that merely
        stops accelerating is still travelling. On a platform with drag the
        distinction is a matter of time; on one without it, the vehicle never
        stops at all.

        Below the cap the command passes through untouched. A cap is a ceiling,
        not a target, and a projector that also *accelerated* toward it would
        make the fail-safe posture into a controller.

        Args:
            values: The command vector to adjust, in actuation-space order.
            current_speed: The vehicle's speed, in m/s.
            cap: The ceiling the fail-safe posture imposes, in m/s.

        Returns:
            A vector in the same space, unchanged when within the cap.
        """
        ...


@runtime_checkable
class DeterministicShield(Protocol):
    """L7a -- the Hard Safety Shield. Unconditional veto authority.

    Reads **only** the state estimate and the slow degradation parameters. It
    never sees the twin's prediction, the conformal score or the Trust Index,
    and that absence is the whole point: its three O(1) bounds --
    ``a_lat <= mu*g``, ``d_stop <= d_avail`` and ``v <= v_legal`` -- fail only if
    the UKF state itself is wrong, which is a failure mode no other gate shares.

    Its VETO can never be overridden by any other component's PASS (SI-3).
    """

    def evaluate(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        state: FastStateEstimate,
        degradation: SlowStateEstimate,
    ) -> GateVerdict:
        """Check the proposal against the hard deterministic bounds.

        Args:
            tick: The control tick.
            proposal: The untrusted proposed command.
            state: The current fast state estimate.
            degradation: The slow estimate, supplying the friction coefficient
                that makes the lateral-acceleration bound adaptive rather than
                fixed.

        Returns:
            A verdict tagged :attr:`~astra.kernel.enums.GateId.DETERMINISTIC`.

        Raises:
            SafetyPathError: If a bound could not be evaluated.
        """
        ...


@runtime_checkable
class SafetyStateMachine(Protocol):
    """L8 -- the fail-safe finite state machine.

    Walks NOMINAL -> DEGRADED -> LIMP -> HALT under an out-of-distribution
    counter that increments on a VETO and decrements on a PASS, which is what
    makes recovery automatic and bidirectional without a restart.
    """

    def observe(self, *, tick: TickId, verdict: SafetyVerdict) -> FailSafeSnapshot:
        """Advance the machine with this tick's verdict and return the new posture.

        Args:
            tick: The control tick.
            verdict: Core-B's combined verdict for this tick.

        Returns:
            The state, counter and operating limits after the transition.
        """
        ...

    @property
    def snapshot(self) -> FailSafeSnapshot:
        """Return the current posture without advancing the machine."""
        ...


@runtime_checkable
class CalibrationArbiter(Protocol):
    """L9 -- Runtime Calibration Management, and the sole issuer of commands (SI-7).

    Two responsibilities on two timing domains, deliberately split across two
    methods so that the split is impossible to lose:

    * :meth:`issue` runs on the **hot path**. It is an active-table lookup and a
      decision, and it must complete inside the tick budget.
    * :meth:`arbitrate` runs on the **cold path**: the Mahalanobis knowledge-base
      search, the mandatory gates, ``T(c)`` scoring and shadow execution. It must
      never block a tick (SI-8).
    """

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

        The only method in the system permitted to produce an
        :class:`~astra.contracts.actuation.IssuedCommand`. When the verdict
        blocks, it issues a fallback, a capped or a bounded-exploration command
        rather than nothing: the architecture requires the vehicle to keep
        moving under a controlled envelope instead of halting.

        Args:
            tick: The control tick.
            proposal: The untrusted proposal.
            verdict: Core-B's combined verdict.
            failsafe: The FSM's posture, supplying speed caps and permissions.
            trust: The Trust Index, used for routing only.
            state: The fast state estimate. Read for the speed the fail-safe cap
                is compared against, and nothing else.

        Returns:
            The command actually sent to the actuators.

        Raises:
            SafetyPathError: If no command could be produced, which the caller
                escalates to the fail-safe machine.
        """
        ...

    def arbitrate(
        self,
        *,
        tick: TickId,
        signature: RuntimeContextSignature,
    ) -> ArbitrationDecision:
        """Evaluate the calibration knowledge base against the current context.

        Cold path only. Runs the Mahalanobis search, the mandatory gates and
        ``T(c)`` scoring, and decides whether to continue, stage a switch,
        commit, roll back, or engage bounded safe exploration.

        Args:
            tick: The control tick the evaluation was triggered at.
            signature: The current Runtime Context Signature.

        Returns:
            The arbitration decision with its scored evidence.
        """
        ...

    def active_profile(self) -> CalibrationProfile:
        """Return the calibration profile currently in force.

        Returns:
            The active, certified profile.
        """
        ...
