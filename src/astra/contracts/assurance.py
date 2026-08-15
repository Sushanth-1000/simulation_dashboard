"""Assurance contracts: trust, gate verdicts, the safety verdict and the FSM snapshot.

These are the records the Core-B safety island and the Trust Module produce.
Two separation invariants are enforced structurally here rather than by review:

* **SI-4 (trust isolation).** :class:`SafetyVerdict` has no Trust Index field
  and no way to acquire one. The Trust Index is monitoring and routing
  information; letting it into the binary safety verdict would couple the
  gates' pass/fail decision to a confidence score, which is precisely the
  coupling the architecture forbids. An architecture test asserts the absence;
  the type makes the assertion true.

* **SI-3 (unconditional veto).** :attr:`SafetyVerdict.aggregate` is computed
  only through :meth:`~astra.kernel.enums.Verdict.merge`, whose fail-closed
  semantics mean no PASS can ever suppress a VETO and an empty verdict set is a
  VETO. There is no other path to the aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra.kernel.enums import GateId, Verdict
from astra.kernel.errors import ContractViolationError
from astra.kernel.validation import require_finite, require_non_negative, require_probability

if TYPE_CHECKING:
    from astra.kernel.enums import ContextClass, FailSafeState
    from astra.kernel.identifiers import TickId
    from astra.kernel.units import MetresPerSecond, Probability, Seconds

__all__ = [
    "FailSafeSnapshot",
    "GateVerdict",
    "SafetyVerdict",
    "TrustAssessment",
]


@dataclass(frozen=True, slots=True)
class TrustAssessment:
    """The Trust Module's (L3) output for a tick: the Trust Index and its basis.

    ``TI = 1 - F_hat_k(alpha_{t+1})`` is the conformal estimate of how ordinary
    the current proposal is under the class-conditional non-conformity
    distribution. It flows to L4 (as a monitoring signal) and to L9 (as a
    routing input), and -- by SI-4 -- never into Core-B's verdict.

    Attributes:
        tick: The control tick this assessment is for.
        trust_index: ``TI`` in ``[0, 1]``. Higher means the proposal is more
            typical of the calibration data for its context.
        context_class: The Mondrian class the proposal was conditioned on.
        class_conditional_quantile: The ``1 - epsilon`` empirical quantile of
            the non-conformity score for :attr:`context_class`, the threshold
            the ICP gate compares against.
        coverage_target: The conformal coverage level ``1 - epsilon`` this
            assessment was produced at.
        calibration_sample_count: How many calibration residuals backed the
            quantile. A quantile from too few samples is not yet trustworthy,
            and recording the count lets a reviewer see when that was the case.
        is_calibrated: Whether the class had enough calibration data for the
            conformal threshold to mean anything.

            **Required, not defaulted.** Without this field the uncalibrated
            case was encoded as a quantile of ``0.0``, which is the right
            fail-closed *behaviour* and an ambiguous *record*: a reader cannot
            tell "no calibration, so reject everything" from "calibrated, and
            this class genuinely has a threshold near zero". The distinction was
            recoverable by comparing ``calibration_sample_count`` against
            ``minimum_samples_for(epsilon)``, but only by a reader who knew to,
            and who still had the epsilon to hand.

            A default would defeat the point. ``True`` would be fail-open, and
            ``False`` would quietly mark every hand-built assessment
            uncalibrated. The constructor makes the caller say which.
    """

    tick: TickId
    trust_index: Probability
    context_class: ContextClass
    class_conditional_quantile: float
    coverage_target: Probability
    calibration_sample_count: int
    is_calibrated: bool

    def __post_init__(self) -> None:
        """Validate the probabilistic fields and the sample count.

        Raises:
            RangeViolationError: If the Trust Index or coverage target is
                outside ``[0, 1]``.
            NonFiniteValueError: If the quantile is NaN or infinite.
            ContractViolationError: If the calibration sample count is negative.
        """
        require_probability(self.trust_index, name="trust_index")
        require_probability(self.coverage_target, name="coverage_target")
        require_non_negative(self.class_conditional_quantile, name="class_conditional_quantile")
        if self.calibration_sample_count < 0:
            message = (
                f"calibration sample count must be non-negative, "
                f"got {self.calibration_sample_count}"
            )
            raise ContractViolationError(message, context={"count": self.calibration_sample_count})


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """One gate's judgement on the proposed command, with the evidence behind it.

    The three gates fail for structurally different reasons, and each records
    *why* it decided as it did: the reason code names the failure mode
    categorically and the evidence map carries the named numeric quantities that
    drove it (the non-conformity score and its threshold, a physical bound and
    the value that breached it). Storing evidence rather than only the verdict
    is what makes the audit log support post-hoc analysis rather than merely
    recording outcomes.

    Attributes:
        tick: The control tick this verdict is for.
        gate: Which of the three gates produced it.
        verdict: The binary judgement.
        reason_code: Stable, greppable identifier for the reason, e.g.
            ``"ALPHA_ABOVE_QUANTILE"`` or ``"NOMINAL"``. Part of the evidence
            schema; never repurposed.
        evidence: Named numeric quantities that informed the verdict. Stored as
            an ordered tuple of pairs rather than a mapping so the record is
            genuinely immutable and serialises deterministically.
        evaluation_duration: Wall-clock cost of evaluating the gate, for the
            latency-budget accounting the timing-domain separation requires.
    """

    tick: TickId
    gate: GateId
    verdict: Verdict
    reason_code: str
    evidence: tuple[tuple[str, float], ...] = ()
    evaluation_duration: Seconds | None = None

    def __post_init__(self) -> None:
        """Validate the reason code, evidence values and duration.

        Raises:
            ContractViolationError: If the reason code is empty.
            NonFiniteValueError: If an evidence value or the duration is not
                finite.
            RangeViolationError: If the duration is negative.
        """
        if not self.reason_code:
            message = "a gate verdict must carry a non-empty reason code"
            raise ContractViolationError(message, context={"gate": self.gate.value})
        for key, value in self.evidence:
            require_finite(value, name=f"evidence.{key}")
        if self.evaluation_duration is not None:
            require_non_negative(self.evaluation_duration, name="evaluation_duration")

    def evidence_map(self) -> dict[str, float]:
        """Return the evidence as a plain dictionary.

        Returns:
            A fresh mapping of evidence name to value, safe for the caller to
            embed in a JSON audit payload.
        """
        return dict(self.evidence)


@dataclass(frozen=True, slots=True)
class SafetyVerdict:
    """Core-B's combined judgement for a tick. Carries no Trust Index by design.

    The aggregate is *only* ever the fail-closed merge of the gate verdicts.
    There is no constructor argument for it and no field to override it, so the
    unconditional-veto invariant (SI-3) cannot be defeated by supplying a
    contradictory aggregate, and the trust-isolation invariant (SI-4) cannot be
    defeated by smuggling in a confidence score: neither has a place to live.

    Attributes:
        tick: The control tick this verdict is for.
        gate_verdicts: One :class:`GateVerdict` per gate that evaluated the
            command, in no guaranteed order.
    """

    tick: TickId
    gate_verdicts: tuple[GateVerdict, ...]

    def __post_init__(self) -> None:
        """Validate that no gate reported twice.

        A repeated gate would make the merge count one gate's opinion twice and
        would make the evidence log ambiguous about which evaluation was
        authoritative.

        Raises:
            ContractViolationError: If two verdicts share a gate.
        """
        gates = [gate_verdict.gate for gate_verdict in self.gate_verdicts]
        if len(gates) != len(set(gates)):
            message = "a safety verdict must contain at most one verdict per gate"
            raise ContractViolationError(message, context={"gates": [gate.value for gate in gates]})

    @property
    def aggregate(self) -> Verdict:
        """Return the fail-closed combination of every gate verdict.

        An empty gate set yields ``VETO``: a command no gate inspected has not
        been cleared, it has been missed.

        Returns:
            ``PASS`` only if there is at least one verdict and all are ``PASS``;
            otherwise ``VETO``.
        """
        return Verdict.merge(gate_verdict.verdict for gate_verdict in self.gate_verdicts)

    @property
    def is_blocking(self) -> bool:
        """Return whether the aggregate blocks the proposed command.

        Returns:
            ``True`` if the aggregate is a VETO.
        """
        return self.aggregate.is_blocking

    @property
    def vetoing_gates(self) -> tuple[GateId, ...]:
        """Return the gates that vetoed, in a stable canonical order.

        Returns:
            The gates whose verdict was ``VETO``, ordered by :class:`GateId`
            declaration so the sequence is reproducible across runs.
        """
        vetoed = {
            gate_verdict.gate
            for gate_verdict in self.gate_verdicts
            if gate_verdict.verdict is Verdict.VETO
        }
        return tuple(gate for gate in GateId if gate in vetoed)


@dataclass(frozen=True, slots=True)
class FailSafeSnapshot:
    """The L8 fail-safe state machine's state at the end of a tick.

    Records not only which state the FSM is in but the operating limits that
    state imposes, so the audit log captures the full safety posture rather than
    just a label. A speed cap of ``None`` means the current state imposes none.

    Attributes:
        tick: The control tick this snapshot describes.
        state: The FSM state after this tick's transition.
        ood_counter: The out-of-distribution counter that drives transitions.
            Increments on a VETO, decrements on a PASS; its value is what makes
            recovery from DEGRADED and LIMP automatic.
        speed_cap: The speed limit this state calls for, or ``None``. L9 projects
            it onto the issued command, so this is both the record and the thing
            that binds; see :class:`~astra.kernel.enums.FailSafeState`.
        lane_change_permitted: Whether lane changes are allowed in this state.
        human_intervention_requested: Whether the FSM has asked for a handover.
        integrity_counter: The sensor-integrity counter, which rises on any
            modality worse than ``HEALTHY`` and falls on a clean frame. **A
            separate integer from ``ood_counter`` deliberately**: the two answer
            different questions -- "is the command being refused?" and "can I
            still believe what I am being told?" -- and a reader of this record
            needs to know which one escalated the posture, because the remedies
            differ. See ADR-0024 and OD-9.

            It defaults to zero so that a snapshot constructed by a caller with
            no sensor bus is not asserting a fault it never looked for.
        withdrawn_capabilities: The autonomy functions unavailable this tick
            because a modality they require is not ``HEALTHY``, sorted by name.

            **A second axis, not a second severity.** ``state`` says how bad
            things are getting; this says *what is broken*, and the two are
            independent -- a vehicle can be NOMINAL with lane changes withdrawn
            (a non-critical camera is dark) or DEGRADED with every capability
            intact (the gates are refusing commands and every sensor is fine).
            Collapsing them into one field would lose exactly the distinction a
            driver and a technician each need. See ADR-0029.

            Withdrawal is **subtractive only**: this list can remove a function
            the posture would have allowed and can never restore one the posture
            forbids. Consumers must therefore intersect, never override.

            Empty means either that nothing is withdrawn or that the deployment
            declared no capabilities at all. Those are different situations and
            this field cannot distinguish them -- ``failsafe.capabilities`` in
            the active profile is what says which, and
            ``benchmarks/commissioning.py`` prints it.
        sensor_decay: Per-modality **fraction of recent frames that were not
            healthy**, smoothed over ``failsafe.decay_window_ticks``, sorted by
            modality.

            **The one field here that is about the sensor rather than about the
            vehicle.** Every counter above answers *"am I in trouble now?"* and
            resets when the trouble passes. This does not: it accumulates the
            duty cycle of a fault, which is the quantity the integrity counter
            cancels to zero. A camera dark on alternate frames holds that
            counter at 1 forever and shows **0.5** here (E-135).

            It has units and a meaning -- *this stream missed a fifth of its
            frames* -- rather than being a weight someone chose, which is what
            makes it defensible where a weighted counter was not.

            **It drives nothing.** No posture, no veto, no command. A decaying
            sensor is a maintenance condition, and a vehicle that stopped for
            maintenance would re-introduce the nuisance stop OD-18 removed.
        sensors_needing_service: The modalities whose decay has crossed
            ``failsafe.decay_service_threshold``, sorted.

            Empty when no threshold is declared, which is the shipped default:
            what fraction of dropped frames means *service this* is a property
            of a particular sensor on a particular vehicle, and this project
            has measured no such number. The mechanism ships reporting only.
    """

    tick: TickId
    state: FailSafeState
    ood_counter: int
    speed_cap: MetresPerSecond | None = None
    lane_change_permitted: bool = True
    human_intervention_requested: bool = False
    integrity_counter: int = 0
    withdrawn_capabilities: tuple[str, ...] = ()
    sensor_decay: tuple[tuple[str, float], ...] = ()
    sensors_needing_service: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the counter and the speed cap.

        Raises:
            ContractViolationError: If either counter is negative.
            RangeViolationError: If a speed cap is present and negative.
            NonFiniteValueError: If a present speed cap is not finite.
        """
        if self.ood_counter < 0:
            message = f"OOD counter must be non-negative, got {self.ood_counter}"
            raise ContractViolationError(message, context={"ood_counter": self.ood_counter})
        if self.integrity_counter < 0:
            message = f"integrity counter must be non-negative, got {self.integrity_counter}"
            raise ContractViolationError(
                message, context={"integrity_counter": self.integrity_counter}
            )
        if self.speed_cap is not None:
            require_non_negative(self.speed_cap, name="speed_cap")
