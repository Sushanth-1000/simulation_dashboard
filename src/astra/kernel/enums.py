"""The canonical vocabulary of ASTRA.

Why this module exists
----------------------
Across the four ASTRA source documents the same concept appears under several
spellings: ``Nominal`` / ``NOMINAL``, ``highway_clear`` / ``HIGHWAY-CLEAR``,
``PASS/VETO`` / ``pass/veto``. In a system whose primary evidence artefact is an
audit log, a concept that serialises three different ways is a concept that
cannot be queried, and therefore cannot be used as certification evidence.

This module fixes one spelling for every term in the architecture. Every later
phase imports these enumerations rather than declaring string literals, so the
event log, the dashboard, the calibration knowledge base and the test suite all
agree by construction.

Design decision: ``StrEnum`` rather than ``Enum`` or ``IntEnum``
----------------------------------------------------------------
* ``StrEnum`` (Python 3.11+) members *are* strings, so ``json.dumps`` emits
  ``"VETO"`` with no custom encoder. The audit log stays human-readable, which
  matters because a human safety assessor is one of its consumers.
* ``IntEnum`` was rejected: it serialises to ``2``, which is unreadable in a log
  and silently comparable to unrelated integers.
* A plain ``Enum`` was rejected: it needs a custom JSON encoder in every writer,
  and a forgotten encoder becomes a crash on the audit path.

Trade-off accepted: ``StrEnum`` members compare equal to their string value, so
``Verdict.VETO == "VETO"`` is ``True``. This slightly weakens type safety, but
it is what makes round-tripping through JSONL and TOML free. mypy still rejects
passing a bare ``str`` where a ``Verdict`` is declared.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum, unique

__all__ = [
    "ArbitrationOutcome",
    "ContextClass",
    "EventSeverity",
    "ExecutionDomain",
    "FailSafeState",
    "FeedbackLoop",
    "GateId",
    "LayerId",
    "SensorModality",
    "StreamHealth",
    "TimingDomain",
    "Verdict",
]


@unique
class LayerId(StrEnum):
    """The nine functional layers of the ASTRA pipeline.

    Numbering follows the consolidated scheme used by ``ASTRA_shortened.pdf``,
    the MP-1 report, the patent report and the Prototype & Demo Plan. The
    earlier draft (``ASTRA_paper 1.pdf``) numbers Core-B's internal stages 4-6
    and RCM as layer 7; that draft is superseded. See
    ``docs/DOCUMENT_RECONCILIATION.md``, finding R-1.
    """

    L1_SENSOR_BUS = "L1_SENSOR_BUS"
    L2_DUAL_RATE_UKF = "L2_DUAL_RATE_UKF"
    L3_CONFORMAL_TRUST = "L3_CONFORMAL_TRUST"
    L4_CORE_A_CMDP = "L4_CORE_A_CMDP"
    L5_PINN_TWIN = "L5_PINN_TWIN"
    L6_MPC_ICP_GATE = "L6_MPC_ICP_GATE"
    L7_HARD_SAFETY_SHIELD = "L7_HARD_SAFETY_SHIELD"
    L8_FAILSAFE_FSM = "L8_FAILSAFE_FSM"
    L9_RCM = "L9_RCM"

    @property
    def ordinal(self) -> int:
        """Return the layer's 1-based number, e.g. ``3`` for ``L3_CONFORMAL_TRUST``.

        Returns:
            The integer following the leading ``L`` in the member name.
        """
        return int(self.name.split("_")[0][1:])

    @property
    def execution_domain(self) -> ExecutionDomain:
        """Return the process boundary this layer belongs to.

        The mapping is the architectural separation from Section 2.1 of the
        paper: shared upstream layers, the untrusted proposer, the safety
        island, and the arbitrator.

        Returns:
            The :class:`ExecutionDomain` that owns this layer.
        """
        return _LAYER_DOMAIN[self]


@unique
class ExecutionDomain(StrEnum):
    """The four isolation domains of the ASTRA process architecture.

    The trust boundary between :attr:`CORE_A` and :attr:`CORE_B` is asymmetric
    and unidirectional: Core-A may write a proposed command into Core-B and may
    read nothing back. In the software prototype this is modelled by a one-way
    queue; in the production target it is an AXI4-Lite bridge.
    """

    SHARED = "SHARED"
    """Layers read by both cores: the sensor bus, the UKF and the Trust Module."""

    CORE_A = "CORE_A"
    """The untrusted proposer. Developed to QM/ASIL-A."""

    CORE_B = "CORE_B"
    """The safety island. Developed to ASIL-D(D)."""

    ARBITRATOR = "ARBITRATOR"
    """Runtime Calibration Management: the sole issuer of actuator commands."""


_LAYER_DOMAIN: dict[LayerId, ExecutionDomain] = {
    LayerId.L1_SENSOR_BUS: ExecutionDomain.SHARED,
    LayerId.L2_DUAL_RATE_UKF: ExecutionDomain.SHARED,
    LayerId.L3_CONFORMAL_TRUST: ExecutionDomain.SHARED,
    LayerId.L4_CORE_A_CMDP: ExecutionDomain.CORE_A,
    LayerId.L5_PINN_TWIN: ExecutionDomain.CORE_B,
    LayerId.L6_MPC_ICP_GATE: ExecutionDomain.CORE_B,
    LayerId.L7_HARD_SAFETY_SHIELD: ExecutionDomain.CORE_B,
    LayerId.L8_FAILSAFE_FSM: ExecutionDomain.CORE_B,
    LayerId.L9_RCM: ExecutionDomain.ARBITRATOR,
}


@unique
class Verdict(StrEnum):
    """The judgement a Core-B gate returns for a proposed command.

    Two of the three values are judgements. The third records that the gate had
    no basis to make one, which is a different statement from either and was
    previously inexpressible -- see :attr:`ABSTAIN` and ADR-0016.
    """

    PASS = "PASS"  # noqa: S105 - a safety verdict, not a credential
    """The gate found no reason to block the command."""

    VETO = "VETO"
    """The gate blocks the command. Never overridable by another gate's PASS."""

    ABSTAIN = "ABSTAIN"
    """The gate had no basis on which to judge, and says so rather than guessing.

    Introduced by ADR-0016 for one specific, checkable condition: the statistical
    gate holds no finite conformal threshold for the context class it was handed,
    because no calibration data covers it. Before this value existed the gate had
    to choose between two lies -- a PASS asserting the proposal satisfied a
    threshold that does not exist, or a VETO asserting it violated one. It chose
    VETO, correctly, and the comment above that branch in
    :mod:`astra.layers.l6_statistical_gate.gate` says exactly why: *"a gate that
    cannot make a statistical claim must not report that the proposal satisfied
    one."* That reasoning wanted this third value.

    **An abstention is not a PASS.** It does not clear anything; it removes the
    gate from the aggregation for that tick. Two consequences follow and both are
    load-bearing:

    - A verdict set that is empty **or entirely abstentions** aggregates to
      ``VETO``. Nothing judged the command, so the command was not cleared. This
      is the same fail-closed rule that has always covered the empty set, and
      extending it is what stops abstention becoming a fail-open mode.
    - It must never be returned on a condition a reviewer cannot check after the
      fact. "I was uncertain" is not a licence to abstain; "I hold no threshold
      for this class, and the evidence record shows the sample count was zero"
      is.
    """

    @property
    def participates(self) -> bool:
        """Return whether this verdict counts toward the aggregate.

        Returns:
            ``True`` for ``PASS`` and ``VETO``, ``False`` for ``ABSTAIN``.
        """
        return self is not Verdict.ABSTAIN

    @classmethod
    def merge(cls, verdicts: Iterable[Verdict]) -> Verdict:
        """Combine gate verdicts under fail-closed aggregation.

        This is the executable form of separation invariant SI-3: a VETO from
        any gate -- and in particular from the Hard Safety Shield -- survives
        every PASS. The aggregation is deliberately *not* a vote, a weighted
        score, or a majority: those are all mechanisms by which one gate could
        cancel another, which is exactly what "structurally independent gates
        with unconditional veto authority" forbids.

        An empty input yields ``VETO``, not ``PASS``. A command that no gate
        inspected has not been cleared; it has been missed. This mirrors the
        FMEA mitigation for a silent Core-B crash, where the hardware crossbar
        defaults to VETO on a missed heartbeat.

        **Abstentions are removed before that rule is applied, never counted as
        PASS.** An input consisting only of abstentions is therefore
        indistinguishable from an empty one and yields ``VETO`` for the same
        reason: nothing judged the command. Returning ``PASS`` there would let a
        gate clear a command by declining to look at it, which is precisely the
        fail-open mode this method exists to prevent.

        Args:
            verdicts: Any iterable of :class:`Verdict` values.

        Returns:
            ``PASS`` only if at least one verdict participated and every
            participating verdict is ``PASS``; otherwise ``VETO``.
        """
        judged = tuple(verdict for verdict in verdicts if verdict.participates)
        if not judged:
            return cls.VETO
        if all(verdict is cls.PASS for verdict in judged):
            return cls.PASS
        return cls.VETO

    @property
    def is_blocking(self) -> bool:
        """Return whether this verdict prevents the proposed command from being issued.

        An abstention does not block on its own -- it withdraws from the
        judgement rather than opposing it. Whether the *tick* is blocked is a
        question for the aggregate, which fails closed when nothing judged.

        Returns:
            ``True`` for ``VETO``, ``False`` for ``PASS`` and ``ABSTAIN``.
        """
        return self is Verdict.VETO


@unique
class GateId(StrEnum):
    """The three structurally independent safety gates inside Core-B.

    The independence claim of the architecture is a claim about *failure
    modes*, not about code paths merely being separate files: the statistical
    gate fails on a statistical anomaly, the physical gate on a violation of
    Newtonian admissibility, and the deterministic gate on a hard-bound
    violation. Phase 5 of the validation plan (adversarial camera perturbation)
    is designed so that exactly one of these fires while the other two pass.
    """

    STATISTICAL = "STATISTICAL"
    """L6: Inductive Conformal Prediction on the non-conformity score."""

    PHYSICAL = "PHYSICAL"
    """L5/L7b: PINN-based admissibility of the predicted next state."""

    DETERMINISTIC = "DETERMINISTIC"
    """L7a: Hard Safety Shield. Unconditional veto authority."""


@unique
class FailSafeState(StrEnum):
    """The four states of the Core-B fail-safe state machine (L8).

    Transitions are driven by an out-of-distribution counter that increments on
    every VETO and decrements on every PASS, which is what makes recovery from
    DEGRADED and LIMP bidirectional and automatic without a restart. HALT is
    terminal by design: :meth:`~astra.layers.l8_failsafe.machine.FailSafeStateMachine.reset`
    is the only exit, because leaving a pull-over is an engineering or operator
    decision rather than something a run of clean ticks should accomplish.

    **The speed caps these states report are not enforced on any actuator.**
    :attr:`~astra.contracts.assurance.FailSafeSnapshot.speed_cap` is recorded in
    the evidence and read by nothing:
    :meth:`~astra.layers.l9_rcm.arbiter.RuntimeCalibrationManager.issue` returns
    on the blocked path before the cap is consulted, and the branch that does
    consult it clamps only to the actuation space -- the identical call the
    uncapped path makes. Converting a cap in m/s into a throttle and brake
    vector needs to know which channel brakes and how hard, which is platform
    knowledge NFR5 keeps out of the core; the seam for it is the open question
    recorded as P2.1 in ``docs/PENDING.md``. Measured: a 100,000-tick run held
    17.2 m/s in HALT, whose cap is 0.0 m/s.
    """

    NOMINAL = "NOMINAL"
    """Commands pass unmodified."""

    DEGRADED = "DEGRADED"
    """OOD counter above theta-1. Fallback PID governs. Reports a reduced speed
    cap, which is recorded and not enforced -- see the class docstring."""

    LIMP = "LIMP"
    """OOD counter above theta-2. Lane changes excluded. Reports a hard speed
    cap, which is recorded and not enforced -- see the class docstring."""

    HALT = "HALT"
    """Hardware fault, BIST failure, or counter above theta-3. Reports a cap of
    0.0 m/s -- a commanded stop -- which is recorded and not enforced. The
    intent is a controlled pull-over; the implemented behaviour is a terminal
    state that constrains nothing but the origin label. See the class
    docstring."""

    @property
    def severity_rank(self) -> int:
        """Return a monotonically increasing rank, ``0`` for NOMINAL to ``3`` for HALT.

        Provided so that comparisons express intent (``state.severity_rank >
        other.severity_rank``) instead of relying on declaration order, which
        would silently change meaning if a state were ever inserted.

        Returns:
            The state's rank in order of increasing severity.
        """
        return _FAILSAFE_RANK[self]


_FAILSAFE_RANK: dict[FailSafeState, int] = {
    FailSafeState.NOMINAL: 0,
    FailSafeState.DEGRADED: 1,
    FailSafeState.LIMP: 2,
    FailSafeState.HALT: 3,
}


@unique
class ContextClass(StrEnum):
    """Operational context classes.

    These serve two roles simultaneously, which the source documents treat as
    one: they are the Mondrian conditioning classes of the Trust Module (L3)
    and the seed profiles of RCM's Calibration Knowledge Base (L9). The
    Prototype & Demo Plan states the two sets match, so they are modelled as
    one enumeration.

    A tunnel class is deliberately absent. The validation plan withholds a
    tunnel profile so that Phase 3.5 exercises the bounded safe-exploration
    path; :attr:`UNCLASSIFIED` is what the classifier returns there.
    """

    HIGHWAY_CLEAR = "HIGHWAY_CLEAR"
    URBAN_CLEAR = "URBAN_CLEAR"
    RAIN_NIGHT = "RAIN_NIGHT"
    DEGRADED_SENSOR = "DEGRADED_SENSOR"
    UNCLASSIFIED = "UNCLASSIFIED"
    """No certified class matches the current Runtime Context Signature."""

    @property
    def is_certified(self) -> bool:
        """Return whether a certified calibration profile may exist for this class.

        Returns:
            ``False`` for :attr:`UNCLASSIFIED`, ``True`` otherwise.
        """
        return self is not ContextClass.UNCLASSIFIED


@unique
class SensorModality(StrEnum):
    """The five sensor modalities fused by the shared sensor bus (L1)."""

    CAMERA = "CAMERA"
    LIDAR = "LIDAR"
    IMU = "IMU"
    GPS = "GPS"
    RADAR = "RADAR"


@unique
class StreamHealth(StrEnum):
    """Per-modality health, assessed on the sensor bus from staleness and quality.

    ``DEGRADED`` is the state produced by the 50 ms staleness rule of FR1. It
    is distinct from ``FAULTED``, which is raised by the UKF's innovation-
    sequence Mahalanobis monitor: a stale stream and a lying stream demand
    different responses, and collapsing them loses that distinction.
    """

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAULTED = "FAULTED"
    ABSENT = "ABSENT"


@unique
class TimingDomain(StrEnum):
    """The two timing domains of the architecture.

    Separating them is what lets RCM run an expensive knowledge-base search
    without ever blocking the tick in flight. Any component added in a later
    phase must declare which domain it runs in; the declaration is what makes
    an accidental blocking call on the hot path reviewable.
    """

    HOT_PATH = "HOT_PATH"
    """Per-tick control loop. Software budget: < 10 ms end to end at 20 Hz."""

    COLD_PATH = "COLD_PATH"
    """Calibration search and shadow execution. Millisecond-to-second timescale."""


@unique
class ArbitrationOutcome(StrEnum):
    """What RCM (L9) decided to do on a given cold-path evaluation.

    Mirrors the RCM decision policy table of the paper, plus the rollback branch
    described in the shadow-execution text.
    """

    CONTINUE = "CONTINUE"
    """The active table remains admissible. No action."""

    SHADOW_EXECUTION = "SHADOW_EXECUTION"
    """A better candidate was found; both tables now evaluate in parallel."""

    SWITCH_COMMITTED = "SWITCH_COMMITTED"
    """The Calibration Divergence Index cleared; the candidate is now active."""

    ROLLBACK = "ROLLBACK"
    """Sustained divergence during shadow execution; the previous table is retained."""

    SAFE_EXPLORATION = "SAFE_EXPLORATION"
    """No admissible candidate. Bounded exploration engaged; evidence logged."""


@unique
class FeedbackLoop(StrEnum):
    """The four closed feedback loops.

    Ordering is significant: the Prototype & Demo Plan requires them to be
    brought online one at a time in this order, confirming stability at each
    step, because FB1's correctness is a precondition for the other three.
    """

    FB1_UKF_REANCHOR = "FB1_UKF_REANCHOR"
    """Applied command -> L2. Keeps the filter anchored to what actually happened."""

    FB2_PINN_ADAPT = "FB2_PINN_ADAPT"
    """Measured outcome -> L5. EWC update of the output layer only."""

    FB3_TRUST_RECALIBRATE = "FB3_TRUST_RECALIBRATE"
    """Executed outcome -> L3. Online Mondrian quantile update."""

    FB4_SIMULATOR_SYNC = "FB4_SIMULATOR_SYNC"
    """Executed command -> simulator. Prototype-only; no deployment counterpart."""

    @property
    def is_deployment_relevant(self) -> bool:
        """Return whether this loop exists in a real-vehicle deployment.

        Returns:
            ``False`` for :attr:`FB4_SIMULATOR_SYNC`, ``True`` otherwise.
        """
        return self is not FeedbackLoop.FB4_SIMULATOR_SYNC


@unique
class EventSeverity(StrEnum):
    """Severity of an audit event.

    Deliberately not reusing the ``logging`` module's levels. Diagnostic
    logging severity ("this is worth printing") and safety-event severity
    ("this changed the safety state of the vehicle") are different questions,
    and a component that must be silent in the console may still be emitting
    ``SAFETY_CRITICAL`` audit records.
    """

    INFO = "INFO"
    """Routine, expected activity."""

    NOTICE = "NOTICE"
    """Noteworthy but nominal: a calibration switch, a context-class change."""

    WARNING = "WARNING"
    """A degradation that the system absorbed: a stale stream, a single VETO."""

    SAFETY_RELEVANT = "SAFETY_RELEVANT"
    """A change to the safety state: an FSM transition, safe exploration entry."""

    SAFETY_CRITICAL = "SAFETY_CRITICAL"
    """A HALT, a BIST failure, or a fail-closed degradation of the pipeline."""
