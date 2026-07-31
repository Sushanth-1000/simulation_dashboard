"""The separation invariants SI-1 ... SI-10, as data and as runtime guards.

Why the invariants are a data structure
---------------------------------------
The architecture's first objective is *formally defined separation invariants*,
and the implementation plan is explicit that they must be machine-checked --
"verify this with a code-level check (no import, no shared memory region, no
queue), not just a comment". Prose in a design document cannot fail a build.

This module makes each invariant a value: identifier, statement, rationale,
what happens if it is violated, and how it is enforced. That buys three things a
document cannot. The CLI can print the catalogue, so an assessor can see the
safety argument and its enforcement status without reading the source. The
composition root verifies the catalogue at startup, so a malformed or
depopulated safety argument stops the run. And the architecture tests assert
properties *of the catalogue itself* -- that every invariant has an enforcement
mechanism, that none is silently downgraded to review-only -- which is what
stops the argument eroding under deadline pressure.

Enforcement honesty
-------------------
:class:`EnforcementKind` distinguishes what is actually checked from what is
merely asserted. An invariant marked :attr:`EnforcementKind.REVIEW` is one the
codebase does *not* mechanically enforce yet, and it says so rather than
implying a guarantee it cannot make. Several invariants here are review-only in
Phase 1 because the components they constrain do not exist yet; each names the
phase that upgrades it. Overstating enforcement would be exactly the kind of
unbacked claim the project's honesty boundaries forbid.

The two runtime guards
----------------------
Most invariants are enforced statically -- by import contracts, by a type that
makes the illegal state unrepresentable. Two need a runtime check as well, and
they are the two whose violation is catastrophic and whose trigger is dynamic:
:func:`guard_verdict_aggregation` (SI-3) and :func:`guard_actuation_authority`
(SI-7).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING

from astra.kernel.enums import LayerId, Verdict
from astra.kernel.errors import InvariantViolationError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from astra.kernel.identifiers import ComponentId

__all__ = [
    "SEPARATION_INVARIANTS",
    "EnforcementKind",
    "SeparationInvariant",
    "guard_actuation_authority",
    "guard_verdict_aggregation",
    "invariant",
]


@unique
class EnforcementKind(StrEnum):
    """How an invariant is actually checked. Deliberately distinguishes real from aspirational."""

    STATIC = "STATIC"
    """Enforced at build time: an import contract, or a type that makes the violation
    unrepresentable. Cannot be violated by a running system."""

    RUNTIME = "RUNTIME"
    """Enforced by a guard that raises when the violation occurs."""

    TEST = "TEST"
    """Enforced by an assertion in the test suite, which fails the build."""

    REVIEW = "REVIEW"
    """Not yet mechanically enforced. Depends on human review. Named honestly so that
    an unenforced invariant is visible rather than implied to be safe."""


@dataclass(frozen=True, slots=True)
class SeparationInvariant:
    """One invariant of the safety argument, with its enforcement.

    Attributes:
        identifier: The stable ``SI-n`` label used across the papers, the
            documentation and the audit log.
        title: A short name for display.
        statement: What must always be true. Written as an assertion about the
            running system, not as advice.
        rationale: Why the architecture requires it -- the failure it prevents.
        consequence: What is no longer true if it is violated. This is the field
            a safety assessor reads to judge severity.
        enforcement: How it is checked.
        mechanism: The concrete artefact doing the checking -- a contract name, a
            guard function, a test module -- or, for review-only invariants, the
            phase that will upgrade it.
    """

    identifier: str
    title: str
    statement: str
    rationale: str
    consequence: str
    enforcement: EnforcementKind
    mechanism: str

    @property
    def is_mechanically_enforced(self) -> bool:
        """Return whether a machine, rather than a reviewer, checks this invariant.

        Returns:
            ``True`` for static, runtime and test enforcement.
        """
        return self.enforcement is not EnforcementKind.REVIEW


SEPARATION_INVARIANTS: tuple[SeparationInvariant, ...] = (
    SeparationInvariant(
        identifier="SI-1",
        title="Sensor opacity",
        statement=(
            "No layer above L2 reads a raw sensor payload. L9 may read reliability metadata only."
        ),
        rationale=(
            "If a downstream layer could re-read the sensors it would become a second, "
            "uncontrolled state source, and the pipeline would no longer have a single "
            "auditable notion of what the world looked like at a tick."
        ),
        consequence=(
            "State provenance becomes ambiguous; two layers can disagree about the world "
            "with no way to say which was right."
        ),
        enforcement=EnforcementKind.STATIC,
        mechanism="import-linter forbidden contract; payload held behind a type parameter",
    ),
    SeparationInvariant(
        identifier="SI-2",
        title="Single state source",
        statement=(
            "Every layer obtains state exclusively from L2's estimates; no layer "
            "re-derives state from sensors."
        ),
        rationale=(
            "One state source is what makes the three gates' inputs comparable and the "
            "audit record joinable. It is also, acknowledged openly, the system's single "
            "common-cause channel."
        ),
        consequence=(
            "Gate independence is weakened in an undocumented way: gates would differ "
            "because their inputs differed, not because their failure modes differ."
        ),
        enforcement=EnforcementKind.STATIC,
        mechanism="import-linter layering; StateEstimator is the only port returning an estimate",
    ),
    SeparationInvariant(
        identifier="SI-3",
        title="Unconditional veto",
        statement=(
            "No PASS from any component can suppress a VETO. Aggregation is fail-closed, "
            "and an empty verdict set is a VETO."
        ),
        rationale=(
            "The Hard Safety Shield's authority is only meaningful if it is unconditional. "
            "A vote, a weighted score or a majority would each be a mechanism by which one "
            "gate cancels another."
        ),
        consequence=(
            "The deterministic safety bound becomes advisory, and the strongest claim in "
            "the safety argument is void."
        ),
        enforcement=EnforcementKind.RUNTIME,
        mechanism=(
            "Verdict.merge; SafetyVerdict.aggregate; guard_verdict_aggregation; "
            "import-linter si-3-shield-independence and l8-judges-verdicts-only"
        ),
    ),
    SeparationInvariant(
        identifier="SI-4",
        title="Trust isolation",
        statement=(
            "The Trust Index must not participate in Core-B's binary verdict. It flows to "
            "L4 for monitoring and L9 for routing only."
        ),
        rationale=(
            "A gate that consulted a confidence score would fail whenever the score was "
            "wrong, coupling three supposedly independent gates to one estimator."
        ),
        consequence=(
            "Gate independence is lost; a single miscalibrated estimator can pass a bad command."
        ),
        enforcement=EnforcementKind.STATIC,
        mechanism="SafetyVerdict has no trust field; no gate port accepts a TrustAssessment",
    ),
    SeparationInvariant(
        identifier="SI-5",
        title="One-way core channel",
        statement=(
            "Core-A may write pi_prop to Core-B; it may not read any Core-B artefact -- "
            "verdict, FSM state, calibration table or quantile."
        ),
        rationale=(
            "The proposer is untrusted and is trained by optimisation. Anything it can "
            "observe, it can learn to exploit; a proposer that can see the gate can learn "
            "to slip past it."
        ),
        consequence=(
            "The learned policy can adapt to the safety monitor, which converts defence in "
            "depth into a single adversarial optimisation problem."
        ),
        enforcement=EnforcementKind.STATIC,
        mechanism=(
            "runtime.channels capability pair -- ProposalWriter has no read method at all; "
            "guard_core_a_isolation and guard_proposal_origin; CommandProposer.propose "
            "accepts no Core-B type. The import-linter contract naming l4_proposer "
            "activates in Phase 4 when that module exists"
        ),
    ),
    SeparationInvariant(
        identifier="SI-6",
        title="Veto-rate exclusion",
        statement=(
            "Core-B's veto rate may be logged as a diagnostic but must never enter Core-A's "
            "reward or constraint computation."
        ),
        rationale=(
            "Rewarding a low veto rate trains the proposer to avoid detection rather than "
            "to be safe. The two are indistinguishable to the optimiser and opposite in "
            "effect."
        ),
        consequence="The proposer optimises against its own safety monitor.",
        enforcement=EnforcementKind.TEST,
        mechanism=(
            "TrainingSignal is a frozen record over a closed permitted field set; "
            "assert_signal_excludes_core_b compares its fields against that set and "
            "rejects any name containing a Core-B term. Asserted by "
            "tests/unit/test_l4_proposer.py"
        ),
    ),
    SeparationInvariant(
        identifier="SI-7",
        title="Sole actuation authority",
        statement="Only L9 may emit a command to the actuation sink.",
        rationale=(
            "A single issuer is what makes the actuation boundary a boundary. With two, no "
            "record could say which component moved the vehicle."
        ),
        consequence=(
            "The governance pipeline can be bypassed entirely; the architecture's central "
            "claim no longer describes the running system."
        ),
        enforcement=EnforcementKind.RUNTIME,
        mechanism=(
            "IssuedCommand rejects a non-L9 issuer; guard_actuation_authority; ActuationSink typing"
        ),
    ),
    SeparationInvariant(
        identifier="SI-8",
        title="Timing-domain separation",
        statement="Cold-path work must never block a hot-path tick.",
        rationale=(
            "The knowledge-base search and evidence writing are unbounded in time. A tick "
            "that waits for either is late, and a late verdict about a vehicle that has "
            "already moved is not a verdict."
        ),
        consequence=(
            "The end-to-end latency budget is violated and control degrades under "
            "exactly the load that matters."
        ),
        enforcement=EnforcementKind.TEST,
        mechanism="non-blocking EventSink contract; queue-based audit writer; Phase 6 latency test",
    ),
    SeparationInvariant(
        identifier="SI-9",
        title="Independent calibration validation",
        statement=(
            "Core-B independently validates any calibration table -- signed checksum plus "
            "quantile monotonicity and range -- before activation, even though RCM proposed it."
        ),
        rationale=(
            "A table that is not monotonic can map a higher non-conformity score to a lower "
            "rejection threshold. That is the precise shape a calibration-poisoning attack "
            "takes, and the component that proposes a table cannot be the only one that "
            "checks it."
        ),
        consequence=(
            "The statistical gate can be silently disabled by a corrupt or hostile "
            "calibration table."
        ),
        enforcement=EnforcementKind.STATIC,
        mechanism="require_non_decreasing in CalibrationProfile; Phase 6 checksum verification",
    ),
    SeparationInvariant(
        identifier="SI-10",
        title="Evidence non-influence",
        statement=(
            "Evidence logged during safe exploration must not modify the live safety "
            "argument; it feeds only the offline certification pipeline."
        ),
        rationale=(
            "Exploration evidence is uncertified by definition. Letting it widen a live "
            "acceptance band would let the system certify itself from its own unreviewed "
            "behaviour."
        ),
        consequence=(
            "The system can bootstrap its way out of its certified envelope without human review."
        ),
        enforcement=EnforcementKind.STATIC,
        mechanism="import-linter contract forbidding evidence modules from being imported by gates",
    ),
)
"""The complete safety argument, in the order the documentation presents it."""


def invariant(identifier: str) -> SeparationInvariant:
    """Return one invariant by its ``SI-n`` identifier.

    Args:
        identifier: The identifier, e.g. ``"SI-3"``.

    Returns:
        The matching invariant.

    Raises:
        KeyError: If no invariant carries that identifier.
    """
    for candidate in SEPARATION_INVARIANTS:
        if candidate.identifier == identifier:
            return candidate
    message = f"{identifier!r} is not a declared separation invariant"
    raise KeyError(message)


def guard_verdict_aggregation(aggregate: Verdict, components: Iterable[Verdict]) -> None:
    """Assert that an aggregated verdict did not suppress a VETO (SI-3).

    A defence-in-depth check on the aggregation itself. The merge is already
    fail-closed by construction, so under correct operation this guard never
    fires -- which is the point: if it ever does, something has computed an
    aggregate by a path other than
    :meth:`~astra.kernel.enums.Verdict.merge`, and the unconditional-veto
    property can no longer be assumed.

    Args:
        aggregate: The aggregate that was computed.
        components: The individual verdicts it was computed from.

    Raises:
        InvariantViolationError: If any component is a VETO while the aggregate
            is a PASS, or if a non-empty aggregation of all-PASS produced a
            surprising result.
    """
    materialised = tuple(components)
    expected = Verdict.merge(materialised)
    if aggregate is not expected:
        message = (
            f"verdict aggregation produced {aggregate.value} where fail-closed merging "
            f"requires {expected.value} (SI-3)"
        )
        raise InvariantViolationError(
            message,
            context={
                "aggregate": aggregate.value,
                "expected": expected.value,
                "components": [verdict.value for verdict in materialised],
            },
        )


def guard_actuation_authority(issuer: ComponentId) -> None:
    """Assert that a component is permitted to issue an actuator command (SI-7).

    :class:`~astra.contracts.actuation.IssuedCommand` already refuses a non-L9
    issuer at construction, so this guard exists for the call sites that decide
    *before* building a record -- an adapter about to write to a bus, a test
    harness checking a wiring change. Both paths are guarded, because an
    invariant enforced in only one place is enforced until someone adds a second
    place.

    Args:
        issuer: The component proposing to issue a command.

    Raises:
        InvariantViolationError: If the issuer is not an L9 component.
    """
    if issuer.layer is not LayerId.L9_RCM:
        message = (
            f"only L9 (RCM) may issue an actuator command; {issuer.layer.value} attempted to (SI-7)"
        )
        raise InvariantViolationError(message, layer=issuer.layer, context={"issuer": str(issuer)})
