"""The tick loop: the one place where all ten layers become a system.

Until this module existed the project was ten individually-tested components
with nothing composing them. That gap is what separates "architecture complete"
from "prototype complete", and closing it is what this file does.

The order, and why it is this order
------------------------------------
::

    L1  acquire      fused frame for the tick
    L2  estimate     state + covariance + innovation      (sole state source, SI-2)
    L3  trust        Trust Index from the conformal core
    L4  propose      pi_prop from the untrusted proposer
        ----------- the one-way channel (SI-5) -----------
    L5  predict      pi_hat, the twin's one-step prediction
    L6  statistical  |pi_prop - pi_hat| / sigma(x) against the conformal band
    L7b physical     is the proposal physically reachable
    L7a deterministic three hard bounds from the state alone
        merge        fail-closed aggregation (SI-3)
    L8  fail-safe    posture from the aggregate verdict
    L9  issue        the only component that may command an actuator (SI-7)
        record       one DecisionRecord, one audit row

Two orderings here are load-bearing rather than incidental.

**The proposal crosses the channel before any gate sees it.** It would be
simpler to hand the `ProposedCommand` straight from L4 to L6. Going through
`ProposalWriter`/`ProposalReader` costs a queue round-trip and buys the property
the channel exists for: Core-A holds an endpoint with no read method, so the
topology in the running system is the topology the safety argument describes. A
pipeline that bypassed the channel would pass every test the channel has while
making the invariant it enforces vacuous.

**The shield is evaluated last but is not privileged.** L7a runs after the other
two purely so that a reader of this file meets the gates in the order the paper
lists them. It has no more authority in the merge than any other gate --
`Verdict.merge` is fail-closed and symmetric, and giving one gate a distinguished
position in the aggregation is exactly what SI-3 forbids.

Fail-closed, everywhere
-----------------------
Every stage that can raise is wrapped. A gate that throws becomes a VETO from
that gate; a stage before the gates that throws ends the tick with an empty
verdict set, which `Verdict.merge` also reads as a VETO. There is no path
through this function that produces an issued command without three gate
verdicts, and no exception escapes as anything other than a recorded VETO.

That is why the fail-closed behaviour is *structural* here rather than a policy
each caller must remember: the tick either produces a `DecisionRecord` naming
what stopped it, or it produces one naming the command it issued.

What this module does not do
-----------------------------
It does not construct anything. Every layer arrives through the constructor,
already built, because the composition root is the only place that decides what
a layer *is* -- and a tick loop that could build its own gate could build a
different one than the one the configuration describes.

It does not drive itself. There is no thread, no timer and no sleep: the caller
decides when a tick happens. A simulator advances on its own clock, a replay
advances through recorded instants, and a live run advances on a real one. A
loop that owned its own timing would be unable to serve all three.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra.contracts.assurance import GateVerdict, SafetyVerdict
from astra.contracts.audit import DecisionRecord
from astra.kernel.enums import (
    ArbitrationOutcome,
    GateId,
    LayerId,
    SensorModality,
    StreamHealth,
    Verdict,
)
from astra.kernel.errors import AstraError, SafetyPathError
from astra.layers.l9_rcm.exploration import exploration_envelope, restricted_space
from astra.layers.l9_rcm.signature import build_signature

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from astra.contracts.actuation import IssuedCommand, PredictedCommand, ProposedCommand
    from astra.contracts.assurance import FailSafeSnapshot, TrustAssessment
    from astra.contracts.estimation import FastStateEstimate, SlowStateEstimate
    from astra.contracts.governance import ArbitrationDecision
    from astra.contracts.sensing import FusedSensorFrame
    from astra.kernel.identifiers import RunId, TickId
    from astra.kernel.time import Clock
    from astra.kernel.units import MetresPerSecond, Probability, Seconds
    from astra.layers.l1_sensing.bus import SharedSensorBus
    from astra.layers.l2_estimation.filter import DualRateUKF
    from astra.layers.l3_trust.trust import ConformalTrustModule
    from astra.layers.l4_proposer.proposer import CmdpProposer
    from astra.layers.l5_twin.twin import PhysicsInformedTwin
    from astra.layers.l6_statistical_gate.gate import IcpStatisticalGate
    from astra.layers.l7_shield.shield import HardSafetyShield
    from astra.layers.l7b_physical.checker import PhysicalAdmissibilityGate
    from astra.layers.l8_failsafe.machine import FailSafeStateMachine
    from astra.layers.l9_rcm.arbiter import RuntimeCalibrationManager
    from astra.observability.audit import JsonlAuditSink
    from astra.runtime.channels import ProposalReader, ProposalWriter

__all__ = ["ColdPathContext", "GovernancePipeline", "TickOutcome"]

# Reason codes for the stages that can end a tick before the gates run. They are
# emitted as gate verdicts so that a failure upstream of Core-B still appears in
# the evidence log in the same shape as a gate's own veto -- an analyst reading
# the archive should not need a second code path to understand why a tick
# produced no command.
REASON_STAGE_FAILED = "UPSTREAM_STAGE_FAILED"
REASON_GATE_FAILED = "GATE_EVALUATION_FAILED"
REASON_NO_PROPOSAL = "NO_PROPOSAL_DELIVERED"


@dataclass(frozen=True, slots=True)
class ColdPathContext:
    """What RCM needs to evaluate the knowledge base, and how often.

    Three of the five signature components -- visibility, traffic dynamicity and
    road complexity -- are not observable from the pipeline's own state. They
    arrive here rather than being invented, so a reader can see exactly where
    each number came from. See :mod:`astra.layers.l9_rcm.signature`.

    Attributes:
        period_ticks: How many hot ticks pass between cold-path evaluations. The
            cold path is not per-tick work: the context a vehicle is in changes
            on a timescale of seconds, and re-searching the knowledge base at
            20 Hz would spend the tick budget re-deriving an unchanged answer.
        trust_threshold: ``tau``, the admissibility threshold.
        divergence_limit: ``delta_CDI``, the shadow-execution divergence bound.
        platform: The platform identifier the mandatory gate matches against.
        legal_speed_limit: What the ego-speed component is normalised by.
        visibility: Externally supplied signature component.
        traffic_dynamicity: Externally supplied signature component.
        road_complexity: Externally supplied signature component.
    """

    period_ticks: int
    trust_threshold: float
    divergence_limit: float
    platform: str
    legal_speed_limit: MetresPerSecond
    visibility: Probability
    traffic_dynamicity: Probability
    road_complexity: Probability


@dataclass(frozen=True, slots=True)
class TickOutcome:
    """Everything one tick produced.

    Attributes:
        record: The decision record, always present. A tick that failed early
            still produces one; it simply has fewer fields populated, and the
            absence is itself evidence.
        issued: The command sent to the actuators, or ``None`` if the tick was
            vetoed or could not complete.
        failed_stage: The pipeline stage that raised, if one did. ``None`` on a
            tick that completed, whether the verdict was PASS or VETO -- a VETO
            is a working pipeline reaching a conclusion, not a failure.
    """

    record: DecisionRecord
    issued: IssuedCommand | None = None
    failed_stage: str | None = None

    @property
    def was_issued(self) -> bool:
        """Return whether a command reached the actuators this tick."""
        return self.issued is not None

    @property
    def verdict(self) -> Verdict:
        """Return the aggregate safety verdict for the tick.

        Returns:
            The aggregate, or ``VETO`` if the tick never reached the gates. An
            empty verdict set merges to VETO, so the fail-closed answer arrives
            through the ordinary path rather than a special case.
        """
        if self.record.safety_verdict is None:
            return Verdict.VETO
        return self.record.safety_verdict.aggregate


class GovernancePipeline[PayloadT]:
    """Runs one tick of the nine-layer pipeline and records what happened.

    Not thread-safe, and deliberately so. The pipeline is driven from one
    control thread; L2's filter and L8's counter are both stateful, and a lock
    would put synchronisation cost on the hot path to guard against a call
    pattern the architecture does not permit.
    """

    __slots__ = (
        "_arbiter",
        "_arbitration",
        "_audit_sink",
        "_clock",
        "_config_hash",
        "_context",
        "_control_effectiveness",
        "_degradation",
        "_estimator",
        "_failsafe",
        "_physical_gate",
        "_proposal_reader",
        "_proposal_writer",
        "_proposer",
        "_run",
        "_sensor_bus",
        "_shield",
        "_slow_period_ticks",
        "_staleness_budget",
        "_statistical_gate",
        "_trust_module",
        "_twin",
    )

    def __init__(
        self,
        *,
        run: RunId,
        config_hash: str,
        sensor_bus: SharedSensorBus[PayloadT],
        estimator: DualRateUKF[PayloadT],
        trust_module: ConformalTrustModule,
        proposer: CmdpProposer,
        proposal_writer: ProposalWriter,
        proposal_reader: ProposalReader,
        twin: PhysicsInformedTwin,
        statistical_gate: IcpStatisticalGate,
        physical_gate: PhysicalAdmissibilityGate,
        shield: HardSafetyShield,
        failsafe: FailSafeStateMachine,
        arbiter: RuntimeCalibrationManager,
        audit_sink: JsonlAuditSink,
        clock: Clock,
        staleness_budget: Seconds,
        slow_period_ticks: int,
        context: ColdPathContext | None = None,
        control_effectiveness: Sequence[float] | None = None,
    ) -> None:
        """Assemble the pipeline from already-constructed layers.

        Args:
            run: The run these ticks belong to.
            config_hash: The frozen configuration's hash, stamped on every
                record so each number is attributable to an operating point.
            sensor_bus: L1.
            estimator: L2.
            trust_module: L3.
            proposer: L4.
            proposal_writer: Core-A's end of the one-way channel.
            proposal_reader: Core-B's end of the one-way channel.
            twin: L5.
            statistical_gate: L6.
            physical_gate: L7b.
            shield: L7a.
            failsafe: L8.
            arbiter: L9.
            audit_sink: Where decision records are written.
            clock: The injected time source. Used only for the civil time the
                cold path's expiry gate needs -- every duration in the pipeline
                comes from the instants the frames carry.
            staleness_budget: The freshness budget for frame health.
            slow_period_ticks: How many fast ticks pass between slow-filter
                updates. Derived by the composition root from the two configured
                rates, not guessed here.
            control_effectiveness: The platform's ``B`` row, mapping a command
                vector to the lateral acceleration it implies. Enables feedback
                loop FB1. ``None`` leaves the loop open, so the filter keeps its
                constant-acceleration model -- which is what every run before
                FB1 existed did, and is retained so an ablation can turn the
                loop off and measure the difference rather than argue about it.
            context: What the cold path needs to run: the arbitration cadence,
                the thresholds, and the three signature components the pipeline
                cannot observe. ``None`` leaves the cold path dormant, which is
                what every test that only exercises the hot path wants.
        """
        self._run = run
        self._config_hash = config_hash
        self._sensor_bus = sensor_bus
        self._estimator = estimator
        self._trust_module = trust_module
        self._proposer = proposer
        self._proposal_writer = proposal_writer
        self._proposal_reader = proposal_reader
        self._twin = twin
        self._statistical_gate = statistical_gate
        self._physical_gate = physical_gate
        self._shield = shield
        self._failsafe = failsafe
        self._arbiter = arbiter
        self._audit_sink = audit_sink
        self._clock = clock
        self._staleness_budget = staleness_budget
        self._slow_period_ticks = max(1, slow_period_ticks)
        self._control_effectiveness = (
            None
            if control_effectiveness is None
            else tuple(float(g) for g in control_effectiveness)
        )
        self._degradation: SlowStateEstimate | None = None
        self._context = context
        self._arbitration: ArbitrationDecision | None = None

    def tick(self, tick: TickId) -> TickOutcome:
        """Run one full control tick and write its decision record.

        Args:
            tick: The control tick to run.

        Returns:
            What the tick produced. A record is always written, whether the tick
            issued a command, was vetoed, or failed upstream of the gates.
        """
        frame_health: tuple[tuple[SensorModality, StreamHealth], ...] = ()
        state: FastStateEstimate | None = None
        trust: TrustAssessment | None = None
        proposal: ProposedCommand | None = None
        prediction: PredictedCommand | None = None

        try:
            frame = self._sensor_bus.acquire(tick)
            frame_health = tuple(self._sensor_bus.health(frame).items())
            state = self._estimate(frame, tick)
            trust = self._trust_module.assess(
                tick=tick, state=state, innovation=self._estimator.latest_innovation()
            )
            proposal = self._deliver(tick=tick, state=state, trust=trust)
            prediction = self._twin.predict(tick=tick, state=state)
        except AstraError as error:
            return self._abort(
                tick=tick,
                stage=_stage_of(error),
                frame_health=frame_health,
                state=state,
                trust=trust,
                proposal=proposal,
            )

        verdict = self._adjudicate(tick=tick, proposal=proposal, prediction=prediction, state=state)
        failsafe = self._failsafe.observe(tick=tick, verdict=verdict)
        issued = self._issue(
            tick=tick,
            proposal=proposal,
            verdict=verdict,
            failsafe=failsafe,
            trust=trust,
            state=state,
        )

        self._reanchor(issued)
        self._maybe_arbitrate(tick=tick, frame=frame, frame_health=frame_health, state=state)

        record = DecisionRecord(
            run=self._run,
            tick=tick,
            config_hash=self._config_hash,
            frame_health=frame_health,
            fast_state=state,
            trust=trust,
            proposal=proposal,
            prediction=prediction,
            twin_weights_digest=self._twin.weights_digest,
            prediction_admissible=prediction.command.is_admissible(),
            safety_verdict=verdict,
            failsafe=failsafe,
            arbitration=self._arbitration,
            issued=issued,
        )
        self._audit_sink.record_decision(record)
        return TickOutcome(record=record, issued=issued)

    # ----------------------------------------------------------------- #
    # Stages
    # ----------------------------------------------------------------- #

    def _estimate(self, frame: FusedSensorFrame[PayloadT], tick: TickId) -> FastStateEstimate:
        """Advance the filters, running the slow one only on its own cadence.

        Args:
            frame: This tick's fused frame.
            tick: The control tick.

        Returns:
            The fast state estimate.
        """
        state = self._estimator.update_fast(frame)
        if self._degradation is None or tick.value % self._slow_period_ticks == 0:
            self._degradation = self._estimator.update_slow(frame)
        innovation = self._estimator.latest_innovation()
        if innovation is not None:
            # The rolling innovation distribution is the physics-grounded
            # covariate-shift signal. Feeding it here rather than inside L6
            # keeps the gate a pure function of what it is given.
            self._statistical_gate.observe_innovation(innovation.mahalanobis_distance)
        return state

    def _deliver(
        self, *, tick: TickId, state: FastStateEstimate, trust: TrustAssessment
    ) -> ProposedCommand:
        """Propose a command and pass it across the one-way channel.

        The round-trip through the channel is the point: Core-A writes, Core-B
        reads, and Core-A holds an endpoint with no method that could return a
        verdict.

        Args:
            tick: The control tick.
            state: The current state estimate.
            trust: The Trust Index, a monitoring input to the proposer.

        Returns:
            The proposal, as read from Core-B's end of the channel.

        Raises:
            SafetyPathError: If the channel could not deliver it.
        """
        proposal = self._proposer.propose(tick=tick, state=state, trust=trust)
        if not self._proposal_writer.send(proposal):
            message = (
                "the proposal channel is full, so Core-B received no proposal "
                "this tick; the tick is treated as having produced nothing to "
                "validate, which is a VETO"
            )
            raise SafetyPathError(
                message,
                layer=LayerId.L4_CORE_A_CMDP,
                context={"tick": tick.value, "reason": REASON_NO_PROPOSAL},
            )
        delivered = self._proposal_reader.receive()
        if delivered is None:
            message = "the proposal channel delivered nothing to Core-B this tick"
            raise SafetyPathError(
                message,
                layer=LayerId.L4_CORE_A_CMDP,
                context={"tick": tick.value, "reason": REASON_NO_PROPOSAL},
            )
        return delivered

    def _adjudicate(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        prediction: PredictedCommand,
        state: FastStateEstimate,
    ) -> SafetyVerdict:
        """Run all three gates and merge their verdicts fail-closed.

        Every gate is evaluated even if an earlier one vetoed. Short-circuiting
        would be faster and would destroy the evidence: the validation scenarios
        turn on *which* gates fired for a given fault, and a gate that was never
        asked cannot answer.

        Args:
            tick: The control tick.
            proposal: The untrusted proposal.
            prediction: The twin's prediction.
            state: The state estimate.

        Returns:
            The merged verdict. A gate that raised contributes a VETO carrying
            the failure as evidence, so a broken gate can never be a silent
            absence.
        """
        verdicts = (
            self._guarded(
                GateId.STATISTICAL,
                tick,
                lambda: self._statistical_gate.evaluate(
                    tick=tick, proposal=proposal, prediction=prediction, state=state
                ),
            ),
            self._guarded(
                GateId.PHYSICAL,
                tick,
                lambda: self._physical_gate.evaluate(
                    tick=tick, proposal=proposal, prediction=prediction, state=state
                ),
            ),
            self._guarded(
                GateId.DETERMINISTIC,
                tick,
                lambda: self._shield.evaluate(
                    tick=tick,
                    proposal=proposal,
                    state=state,
                    degradation=self._require_degradation(),
                ),
            ),
        )
        return SafetyVerdict(tick=tick, gate_verdicts=verdicts)

    def _issue(
        self,
        *,
        tick: TickId,
        proposal: ProposedCommand,
        verdict: SafetyVerdict,
        failsafe: FailSafeSnapshot,
        trust: TrustAssessment,
        state: FastStateEstimate,
    ) -> IssuedCommand | None:
        """Ask L9 for the final command.

        Args:
            tick: The control tick.
            proposal: The untrusted proposal.
            verdict: Core-B's combined verdict.
            failsafe: The posture after this tick.
            trust: The Trust Index, a routing input for L9.
            state: The fast state estimate, for the fail-safe speed cap.

        Returns:
            The issued command, or ``None`` if the arbitrator could not produce
            one. A failure here is recorded rather than raised: L9 declining to
            issue is the system working, and the record says so.
        """
        try:
            return self._arbiter.issue(
                tick=tick,
                proposal=proposal,
                verdict=verdict,
                failsafe=failsafe,
                trust=trust,
                state=state,
            )
        except AstraError:
            return None

    @property
    def is_exploring(self) -> bool:
        """Return whether bounded safe exploration is currently engaged.

        A read-only view for a driver or a dashboard. The envelope itself lives
        on the arbitrator, which is the only component that may narrow it.
        """
        return self._arbiter.is_exploring

    @property
    def arbitration(self) -> ArbitrationDecision | None:
        """Return the most recent cold-path decision, if one has been made."""
        return self._arbitration

    def enter_context(self, context: ColdPathContext) -> None:
        """Replace what the cold path knows about the world outside the state.

        Visibility, traffic and road complexity are not observable from the
        pipeline's own state, so something outside it has to say when they
        change. A scenario driver knows because it authored them; a CARLA
        adapter would derive them from the simulator's world.

        Args:
            context: The new cold-path context.
        """
        self._context = context

    def _reanchor(self, issued: IssuedCommand | None) -> None:
        """Feed the issued command back into the estimator. Feedback loop FB1.

        Runs after the command has been issued and before the cold path, so the
        *next* tick's prediction starts from what the vehicle was actually told
        to do rather than from the assumption that its lateral acceleration has
        not changed.

        FB1 is first among the four loops because the others depend on the state
        estimate it corrects, and because it is the mitigation for the shared
        estimate that couples Core-A and Core-B: an estimator blind to the
        commands being issued diverges from the vehicle in exactly the situation
        -- an actuator not doing what it was told -- where both cores are
        reading the same wrong number.

        The command feeds the *prediction*, never the state. See
        :meth:`~astra.layers.l2_estimation.filter.DualRateUKF.apply_command` for
        why that distinction is what keeps the innovation meaningful.

        Args:
            issued: The command L9 issued, or ``None`` if the tick issued none.
                ``None`` clears the input, restoring the constant-acceleration
                model, which is the correct assumption for a tick on which
                nothing was commanded.
        """
        if issued is None or self._control_effectiveness is None:
            self._estimator.apply_command(None)
            return
        effectiveness = self._control_effectiveness
        values = issued.command.values
        if len(effectiveness) != len(values):
            # A mismatch means the configured platform row and the actuation
            # space disagree about how many channels this vehicle has. Feeding
            # the loop anyway would anchor the filter to a number computed from
            # the wrong channels, so the loop opens rather than lies.
            self._estimator.apply_command(None)
            return
        self._estimator.apply_command(
            sum(
                float(gain) * float(value)
                for gain, value in zip(effectiveness, values, strict=True)
            )
        )

    def _maybe_arbitrate(
        self,
        *,
        tick: TickId,
        frame: FusedSensorFrame[PayloadT],
        frame_health: tuple[tuple[SensorModality, StreamHealth], ...],
        state: FastStateEstimate,
    ) -> None:
        """Run one cold-path evaluation, if this tick is due one.

        Runs *after* the command has been issued, deliberately. The hot path's
        answer must never wait on the knowledge base (SI-8), and running the
        cold path last means a slow arbitration delays the next tick's start
        rather than this tick's command.

        Arbitration failures are absorbed rather than raised. The cold path
        chooses which calibration to run *under*; failing to choose leaves the
        previous choice in force, which is a degraded but safe state. Letting it
        abort a tick would give the cold path authority over the hot one --
        exactly the coupling SI-8 exists to prevent.

        Args:
            tick: The control tick.
            frame: This tick's fused frame.
            frame_health: Per-modality health for that frame.
            state: The fast state estimate.
        """
        context = self._context
        if context is None or tick.value % max(1, context.period_ticks) != 0:
            return
        try:
            signature = build_signature(
                tick=tick,
                frame=frame,
                health=dict(frame_health),
                state=state,
                legal_speed_limit=context.legal_speed_limit,
                visibility=context.visibility,
                traffic_dynamicity=context.traffic_dynamicity,
                road_complexity=context.road_complexity,
            )
            decision = self._arbiter.arbitrate(
                tick=tick,
                signature=signature,
                threshold=context.trust_threshold,
                divergence_limit=context.divergence_limit,
                platform=context.platform,
                now=self._clock.wall_clock(),
            )
            self._arbitration = decision
            self._follow(decision)
        except AstraError:
            # The previous decision stays in force; see the docstring.
            return

    def _follow(self, decision: ArbitrationDecision) -> None:
        """Act on what arbitration decided.

        Without this, ``arbitrate`` computes a verdict that nothing obeys: the
        decision would say ``SAFE_EXPLORATION`` while the vehicle carried on
        under the full nominal envelope. A decision nothing acts on is a log
        entry, not a control action.

        Entering exploration **narrows the actuation space** rather than
        clamping commands at the point of issue. That routes the envelope
        through the check that already guards every command --
        :class:`~astra.contracts.actuation.IssuedCommand` refuses a vector
        outside its space -- so a second issue path could not bypass it.

        Args:
            decision: What the cold path decided this evaluation.
        """
        exploring = self._arbiter.is_exploring
        wants_exploration = decision.outcome is ArbitrationOutcome.SAFE_EXPLORATION

        if wants_exploration and not exploring:
            envelope = exploration_envelope(float(self._arbiter.active_profile.max_speed))
            self._arbiter.engage_exploration(restricted_space(self._arbiter.space, envelope))
        elif exploring and not wants_exploration:
            # A certified profile is reachable again -- ExplorationExit
            # PROFILE_REACQUIRED. Every exit leaves the vehicle moving; none of
            # them is a halt.
            self._arbiter.exit_exploration()

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #

    def _guarded(
        self,
        gate: GateId,
        tick: TickId,
        evaluate: Callable[[], GateVerdict],
    ) -> GateVerdict:
        """Evaluate one gate, converting any failure into that gate's VETO.

        Args:
            gate: Which gate is being evaluated.
            tick: The control tick.
            evaluate: A zero-argument callable returning the gate's verdict.

        Returns:
            The gate's verdict, or a VETO naming the failure.
        """
        try:
            return evaluate()
        except AstraError:
            return GateVerdict(
                tick=tick,
                gate=gate,
                verdict=Verdict.VETO,
                reason_code=REASON_GATE_FAILED,
                evidence=(("failed", 1.0),),
            )

    def _require_degradation(self) -> SlowStateEstimate:
        """Return the slow estimate, which the shield needs.

        Returns:
            The latest slow estimate.

        Raises:
            SafetyPathError: If the slow filter has never run, which would mean
                the shield's friction bound had no friction to read.
        """
        if self._degradation is None:
            message = "the slow filter has not run, so the shield has no friction estimate"
            raise SafetyPathError(message, layer=LayerId.L2_DUAL_RATE_UKF)
        return self._degradation

    def _abort(
        self,
        *,
        tick: TickId,
        stage: str,
        frame_health: tuple[tuple[SensorModality, StreamHealth], ...],
        state: FastStateEstimate | None,
        trust: TrustAssessment | None,
        proposal: ProposedCommand | None,
    ) -> TickOutcome:
        """End a tick that failed before the gates, recording why.

        The FSM still observes the tick. A pipeline that failed upstream
        produced no verdict, and an unobserved failure would leave the OOD
        counter blind to exactly the condition it exists to escalate on.

        Args:
            tick: The control tick.
            stage: Which stage failed.
            frame_health: Whatever health was determined before the failure.
            state: The state estimate, if one was produced.
            trust: The trust assessment, if one was produced.
            proposal: The proposal, if one was produced.

        Returns:
            The outcome, with no issued command.
        """
        verdict = SafetyVerdict(
            tick=tick,
            gate_verdicts=(
                GateVerdict(
                    tick=tick,
                    gate=GateId.DETERMINISTIC,
                    verdict=Verdict.VETO,
                    reason_code=REASON_STAGE_FAILED,
                    evidence=(("stage_failed", 1.0),),
                ),
            ),
        )
        failsafe = self._failsafe.observe(tick=tick, verdict=verdict)
        record = DecisionRecord(
            run=self._run,
            tick=tick,
            config_hash=self._config_hash,
            frame_health=frame_health,
            fast_state=state,
            trust=trust,
            proposal=proposal,
            twin_weights_digest=self._twin.weights_digest,
            safety_verdict=verdict,
            failsafe=failsafe,
        )
        self._audit_sink.record_decision(record)
        return TickOutcome(record=record, issued=None, failed_stage=stage)


def _stage_of(error: AstraError) -> str:
    """Name the pipeline stage an error came from.

    Args:
        error: The error that ended the tick.

    Returns:
        The layer's identifier, or ``"UNKNOWN"`` if the error named none.
    """
    return error.layer.value if error.layer is not None else "UNKNOWN"
