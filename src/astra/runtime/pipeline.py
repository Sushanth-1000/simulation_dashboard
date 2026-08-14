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

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from astra.contracts.assurance import GateVerdict, SafetyVerdict
from astra.contracts.audit import DecisionRecord
from astra.kernel.enums import (
    ArbitrationOutcome,
    ContextClass,
    GateId,
    LayerId,
    SensorModality,
    StreamHealth,
    Verdict,
)
from astra.kernel.errors import AstraError, SafetyPathError
from astra.layers.l6_statistical_gate.gate import CONTROL_DIMENSION, non_conformity_score
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
    from astra.layers.l2_estimation.measurement import IntegrityMonitor
    from astra.layers.l3_trust.mondrian import MondrianCalibration
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
class ShadowLoops:
    """What the dormant feedback loops *would* have done this tick.

    Deliberately not part of :class:`~astra.contracts.audit.DecisionRecord`. The
    audit log is a certification artefact and describes what the system did; a
    counterfactual produced by a loop that is switched off is a different kind of
    claim, and filing the two together would be a category error that a reader
    years from now has no way to unpick.

    Attributes:
        divergence: The largest absolute per-channel difference between the
            prediction the live twin made and the one the shadow would have made.
            Zero until the shadow's first consolidation fires.
        digest: The shadow twin's weights digest, so a run can show the shadow
            actually moved rather than assuming it did.
        adapted: Whether this tick's outcome was handed to the shadow at all.
            False on a tick that issued nothing, or one with no context to adapt
            in -- both are cases FB2 would also have skipped.
        quantile: The conformal quantile L6 actually used this tick -- static,
            because the corpus is seeded once and never updated.
        shadow_quantile: The quantile L6 *would* have used had FB3 been
            requantilising online on realised scores. **The FB3 counterfactual.**
        shadow_would_veto: Whether this tick's score exceeds that shadow
            quantile. Summed over a run it gives the veto rate FB3 would have
            produced.
        shadow_failsafe: The state a *second* fail-safe machine reaches when fed
            those counterfactual vetoes and nothing else.

            This is what answers D-1. A veto is not an intervention: it runs the
            fallback for one tick and nothing degrades until the OOD counter
            crosses theta-1. So "false-positive rate" has two readings -- per
            tick, which is epsilon by construction and not a defect, and per
            *intervention*, which is what a fleet operator actually pays for.
            They are not the same number and the target of < 1% never said
            which it meant.
        live_score: The non-conformity score L6 computed this tick, against the
            twin the gates actually read.
        shadow_score: The score L6 *would* have computed had it read the shadow
            twin instead. The pair is the whole question about FB2: the twin's
            module docstring says training it on the proposer's output would
            "make every score small and quietly disarm the statistical gate",
            and FB2's only labels are the proposer's commands. If the shadow's
            scores fall away from the live ones over a long run, that is the
            disarming, observed before it was ever given authority.

            Both are computed with
            :func:`~astra.layers.l6_statistical_gate.gate.non_conformity_score`,
            the gate's own arithmetic, because a comparison against a
            reimplementation would be evidence about the reimplementation.
    """

    divergence: float
    digest: str
    adapted: bool
    live_score: float
    shadow_score: float
    quantile: float
    shadow_quantile: float
    shadow_would_veto: bool
    shadow_failsafe: str


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
        shadow: FB2's counterfactual, when a shadow twin was supplied. ``None``
            means no shadow was running, which is the default.
    """

    record: DecisionRecord
    issued: IssuedCommand | None = None
    failed_stage: str | None = None
    shadow: ShadowLoops | None = None

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
        "_ablation",
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
        "_integrity",
        "_physical_gate",
        "_proposal_reader",
        "_proposal_writer",
        "_proposer",
        "_run",
        "_sensor_bus",
        "_shadow_calibration",
        "_shadow_failsafe",
        "_shadow_twin",
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
        shadow_twin: PhysicsInformedTwin | None = None,
        shadow_calibration: MondrianCalibration | None = None,
        shadow_failsafe: FailSafeStateMachine | None = None,
        ablation: str = "NONE",
        integrity: IntegrityMonitor[PayloadT] | None = None,
    ) -> None:
        """Assemble the pipeline from already-constructed layers.

        Args:
            run: The run these ticks belong to.
            config_hash: The frozen configuration's hash, stamped on every
                record so each number is attributable to an operating point.
            integrity: An adapter-supplied cross-modality monitor, or ``None``.
                It is the producer of ``StreamHealth.FAULTED`` -- the value L1
                reserves for a *lying* stream and cannot decide itself. ``None``
                leaves health exactly as L1 determined it, which is what every
                caller predating ADR-0026 gets.
            sensor_bus: L1.
            estimator: L2.
            trust_module: L3.
            proposer: L4.
            proposal_writer: Core-A's end of the one-way channel.
            proposal_reader: Core-B's end of the one-way channel.
            twin: L5. Never adapted by the tick loop: FB2 is not wired, and
                repairing its mechanism (ADR-0019) did not switch it on.
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
            shadow_twin: A second twin, of the same architecture and starting
                from the same checkpoint, which **is** fed executed outcomes.
                Nothing reads its predictions: it exists so a long run can
                measure how far FB2 would have moved the twin, and whether that
                movement would have been an improvement, before FB2 is given any
                authority over a command. ``None``, the default, runs no shadow.

                The idiom is L9's, not a new one -- :class:`ShadowExecution`
                stages a candidate calibration profile and measures its
                divergence before committing to it, for the same reason.
            ablation: Which layers were disarmed for this run, rendered by
                :meth:`~astra.runtime.ablation.AblationProfile.render`.
                ``"NONE"`` -- the default -- is a governed run. Carried here
                only so that every decision record can be stamped with it: an
                ablated run's evidence is otherwise indistinguishable from a
                governed run's, which is precisely what an ablation is
                (ADR-0021).
            shadow_failsafe: A second fail-safe machine, driven only by the
                counterfactual verdicts FB3's quantile would have produced. It
                governs nothing. It exists to answer D-1's real question: a veto
                runs the fallback for one tick, and nothing degrades until the
                OOD counter crosses theta-1, so the per-tick veto rate and the
                per-*intervention* rate are different numbers.
            shadow_calibration: A second Mondrian calibration, seeded from the
                same corpus as L6's, which **is** fed realised scores. Nothing
                thresholds against it. It answers FB3's question -- what would
                the acceptance quantile become, and what veto rate would that
                have produced -- without FB3 having any say in a verdict.
        """
        self._run = run
        self._config_hash = config_hash
        self._sensor_bus = sensor_bus
        self._integrity = integrity
        self._estimator = estimator
        self._trust_module = trust_module
        self._proposer = proposer
        self._proposal_writer = proposal_writer
        self._proposal_reader = proposal_reader
        self._twin = twin
        self._shadow_twin = shadow_twin
        self._shadow_calibration = shadow_calibration
        self._shadow_failsafe = shadow_failsafe
        self._ablation = ablation
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
            frame_health = self._frame_health(frame)
            state = self._estimate(frame, tick)
            innovation = self._estimator.latest_innovation()
            # Read once and threaded to both consumers and the record. Calling
            # `latest_innovation()` twice would be harmless today and is exactly
            # the kind of duplicate read that lets an audit row disagree with
            # the gate it claims to describe.
            fast_innovation = None if innovation is None else innovation.mahalanobis_distance
            trust = self._trust_module.assess(tick=tick, state=state, innovation=innovation)
            proposal = self._deliver(tick=tick, state=state, trust=trust)
            # The context L3 just classified selects the twin's output head, so
            # the non-conformity score's reference and the quantile it is
            # compared against are conditioned on the same partition (ADR-0019).
            prediction = self._twin.predict(tick=tick, state=state, context=trust.context_class)
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
        failsafe = self._failsafe.observe(
            tick=tick,
            verdict=verdict,
            frame_health=frame_health,
            exploring=self._is_exploring,
        )
        issued = self._issue(
            tick=tick,
            proposal=proposal,
            verdict=verdict,
            failsafe=failsafe,
            trust=trust,
            state=state,
        )

        self._reanchor(issued)
        shadow = self._shadow(
            tick=tick,
            state=state,
            issued=issued,
            proposal=proposal,
            prediction=prediction,
            trust=trust,
            failsafe=failsafe,
        )
        self._maybe_arbitrate(tick=tick, frame=frame, frame_health=frame_health, state=state)

        record = DecisionRecord(
            run=self._run,
            tick=tick,
            config_hash=self._config_hash,
            frame_health=frame_health,
            fast_state=state,
            fast_innovation=fast_innovation,
            trust=trust,
            proposal=proposal,
            prediction=prediction,
            twin_weights_digest=self._twin.weights_digest,
            prediction_admissible=prediction.command.is_admissible(),
            safety_verdict=verdict,
            failsafe=failsafe,
            arbitration=self._arbitration,
            issued=issued,
            ablation=self._ablation,
        )
        self._audit_sink.record_decision(record)
        return TickOutcome(record=record, issued=issued, shadow=shadow)

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

    def _shadow(
        self,
        *,
        tick: TickId,
        state: FastStateEstimate,
        issued: IssuedCommand | None,
        proposal: ProposedCommand,
        prediction: PredictedCommand,
        trust: TrustAssessment,
        failsafe: FailSafeSnapshot,
    ) -> ShadowLoops | None:
        """Run FB2 against a twin nothing reads, and report what it would do.

        Placed after the command has been issued, on the cold path, so the extra
        forward pass cannot enter the hot-path latency budget. Nothing here can
        change this tick's verdict or the next one's: the shadow twin is not the
        twin the gates consult, and the only thing that leaves this method is a
        number for a report.

        That isolation is the whole point. FB2 has never run, and the honest way
        to find out whether it should is to measure it -- how far it moves the
        twin over a real drive, and whether the movement tracks the plant or
        wanders. Choosing its step size first and observing afterwards is how
        ``ewc_lambda`` came to be set to a value that did nothing for months.

        Args:
            tick: The control tick.
            state: The fast state estimate, both the adaptation's target and the
                input the shadow's prediction is read at.
            issued: The command actually sent to the actuators, or ``None``.
            proposal: The untrusted proposal, the score's left operand.
            prediction: What the live twin predicted, to difference against.
            trust: Supplies the context the shadow adapts in.
            failsafe: The live posture, reported back unchanged when no shadow
                machine is running so the field is never empty.

        Returns:
            The counterfactual, or ``None`` if no shadow twin was supplied.
        """
        if self._shadow_twin is None:
            return None

        context = trust.context_class or ContextClass.UNCLASSIFIED
        shadow = self._shadow_twin.predict(tick=tick, state=state, context=context)
        divergence = max(
            (
                abs(mine - theirs)
                for mine, theirs in zip(
                    prediction.command.values, shadow.command.values, strict=True
                )
            ),
            default=0.0,
        )

        variance = state.variance_of(CONTROL_DIMENSION)
        live_score, _, _ = non_conformity_score(
            proposed=proposal.command.values,
            predicted=prediction.command.values,
            variance=variance,
        )
        shadow_score, _, _ = non_conformity_score(
            proposed=proposal.command.values,
            predicted=shadow.command.values,
            variance=variance,
        )

        # FB3's counterfactual. The live quantile is static -- the corpus is
        # seeded once -- so the pair says how far online requantilisation would
        # have moved the acceptance threshold, and whether this tick would have
        # been vetoed under the moved one.
        quantile = self._statistical_gate.quantile_for(context)
        shadow_quantile = quantile
        if self._shadow_calibration is not None:
            shadow_quantile = self._shadow_calibration.quantile(
                context, self._statistical_gate.effective_epsilon()
            )
            self._shadow_calibration.observe(context, live_score)

        # Adapt on the *issued* command, not the proposal: FB2's contract is that
        # the twin learns the vehicle's response, and the vehicle responds to
        # what it was told, which on a blocked tick is the fallback's command
        # rather than the proposer's.
        adapted = issued is not None
        if issued is not None:
            self._shadow_twin.adapt(applied=issued.command, measured=state, context=context)
        # Feed the counterfactual verdict to a fail-safe machine of its own, so
        # the escalation this veto rate would have caused is measured rather
        # than reasoned about. Independent instance: it must not perturb the one
        # the vehicle is actually governed by.
        would_veto = math.isfinite(shadow_quantile) and live_score > shadow_quantile
        shadow_state = failsafe.state.value
        if self._shadow_failsafe is not None:
            shadow_state = self._shadow_failsafe.observe(
                tick=tick,
                verdict=SafetyVerdict(
                    tick=tick,
                    gate_verdicts=(
                        GateVerdict(
                            tick=tick,
                            gate=GateId.STATISTICAL,
                            verdict=Verdict.VETO if would_veto else Verdict.PASS,
                            reason_code="SHADOW_REQUANTILISED",
                        ),
                    ),
                ),
            ).state.value

        return ShadowLoops(
            divergence=divergence,
            digest=self._shadow_twin.weights_digest,
            adapted=adapted,
            live_score=live_score,
            shadow_score=shadow_score,
            quantile=quantile,
            shadow_quantile=shadow_quantile,
            shadow_would_veto=would_veto,
            shadow_failsafe=shadow_state,
        )

    #: Health values ordered worst-last, so a merge can take a maximum.
    _HEALTH_SEVERITY: Final = (
        StreamHealth.HEALTHY,
        StreamHealth.DEGRADED,
        StreamHealth.FAULTED,
        StreamHealth.ABSENT,
    )

    def _frame_health(
        self, frame: FusedSensorFrame[PayloadT]
    ) -> tuple[tuple[SensorModality, StreamHealth], ...]:
        """Return per-modality health, merging staleness with integrity.

        L1 decides ``HEALTHY`` and ``DEGRADED`` from **freshness**. It cannot
        decide ``FAULTED``, and says so in its own docstring: a monitor that
        knows what a reading *should* have been is required, and *"a stale
        stream and a lying stream are different faults and are deliberately not
        collapsed"*.

        When an adapter supplies an :class:`IntegrityMonitor`, its verdict is
        merged here by taking the **worse** of the two per modality. Neither can
        mask the other -- a stale channel is stale whatever its values say, and
        a lying channel is lying however punctually it arrives -- and a modality
        the monitor omits keeps L1's verdict rather than being cleared by
        silence.

        This is the composition root, which is the only place that legitimately
        sees both. L1 acquires no knowledge of cross-modality checking and the
        monitor acquires none of staleness.

        Args:
            frame: The fused frame for this tick.

        Returns:
            One pair per modality, ordered as the sensor bus ordered them.
        """
        staleness = self._sensor_bus.health(frame)
        if self._integrity is None:
            return tuple(staleness.items())
        integrity = self._integrity.health(frame)
        return tuple(
            (
                modality,
                max(
                    health,
                    integrity.get(modality, health),
                    key=self._HEALTH_SEVERITY.index,
                ),
            )
            for modality, health in staleness.items()
        )

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

    @property
    def _is_exploring(self) -> bool:
        """Return whether L9 currently has bounded safe exploration engaged.

        Read by the fail-safe machine so it can freeze its counter rather than
        escalate a condition RCM has already answered -- ADR-0023.
        """
        return (
            self._arbitration is not None
            and self._arbitration.outcome is ArbitrationOutcome.SAFE_EXPLORATION
        )

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
            self._arbiter.engage_exploration(
                restricted_space(self._arbiter.space, envelope),
                speed_cap=float(envelope.speed_cap),
            )
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
            ablation=self._ablation,
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
