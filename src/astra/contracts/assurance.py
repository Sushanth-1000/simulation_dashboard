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
    """

    tick: TickId
    trust_index: Probability
    context_class: ContextClass
    class_conditional_quantile: float
    coverage_target: Probability
    calibration_sample_count: int

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
        speed_cap: The hard speed limit this state imposes, or ``None``.
        lane_change_permitted: Whether lane changes are allowed in this state.
        human_intervention_requested: Whether the FSM has asked for a handover.
    """

    tick: TickId
    state: FailSafeState
    ood_counter: int
    speed_cap: MetresPerSecond | None = None
    lane_change_permitted: bool = True
    human_intervention_requested: bool = False

    def __post_init__(self) -> None:
        """Validate the counter and the speed cap.

        Raises:
            ContractViolationError: If the OOD counter is negative.
            RangeViolationError: If a speed cap is present and negative.
            NonFiniteValueError: If a present speed cap is not finite.
        """
        if self.ood_counter < 0:
            message = f"OOD counter must be non-negative, got {self.ood_counter}"
            raise ContractViolationError(message, context={"ood_counter": self.ood_counter})
        if self.speed_cap is not None:
            require_non_negative(self.speed_cap, name="speed_cap")
