"""The ASTRA exception hierarchy and its fail-closed disposition policy.

Why a hierarchy at all
----------------------
In ordinary application code an exception's job is to tell a developer what
went wrong. In a safety-governed system it has a second, more important job: it
must tell the *runtime* what the system is now permitted to do. An exception
raised while the ICP gate is scoring a command is not merely a bug report --
it is a statement that the command has not been validated, and therefore must
not be issued.

Every exception in ASTRA therefore carries a :class:`SafetyDisposition`
declaring what the system does when it escapes. This turns "handle errors
carefully" from a review-time hope into a property attached to the type.

The three dispositions
----------------------
``FAIL_FAST``
    The system cannot start, or cannot continue, in a defensible state. Used
    for configuration and invariant violations. Refusing to start is safe;
    starting with an unverified configuration is not.

``FAIL_CLOSED``
    The safety pipeline could not complete its judgement. The command under
    inspection must be treated as VETOed and the fail-safe FSM must see a
    VETO event. This mirrors the hardware FMEA mitigation for a silent Core-B
    crash: the crossbar defaults to VETO on a missed heartbeat, so the absence
    of a verdict is a veto, never a pass.

``FAIL_OPERATIONAL``
    The failure is outside the safety argument -- a dashboard websocket
    dropping, an offline evidence file failing to write. The pipeline continues;
    the incident is recorded. Only failures that provably cannot influence a
    command carry this disposition.

Design decision: exceptions, not error return values
-----------------------------------------------------
A ``Result``/``Either`` type was considered and rejected. Python has no
syntactic support for it, so every call site grows an explicit unwrap, and the
resulting code is harder for the mixed-experience team that will maintain this
to read correctly. Exceptions with typed dispositions give the same safety
property -- the failure mode is part of the signature's contract -- without
fighting the language. The hot-path cost is nil in the nominal case, because
Python only pays for an exception when one is raised.

What is deliberately *not* here
-------------------------------
No fail-closed decorator or guard context manager is provided in Phase 1. The
policy above is data; the machinery that applies it belongs with the pipeline
that it guards, which arrives in Phase 2. Building the mechanism now would mean
building it against an imagined caller. See ADR-0006.
"""

from __future__ import annotations

from enum import StrEnum, unique
from typing import TYPE_CHECKING, Any, ClassVar, override

from astra.kernel.enums import EventSeverity

if TYPE_CHECKING:
    from astra.kernel.enums import LayerId

__all__ = [
    "AdapterError",
    "AstraError",
    "ConfigurationError",
    "ContractViolationError",
    "DimensionMismatchError",
    "InvariantViolationError",
    "NonFiniteValueError",
    "RangeViolationError",
    "SafetyDisposition",
    "SafetyPathError",
    "SchemaVersionError",
    "TimingBudgetExceededError",
]


@unique
class SafetyDisposition(StrEnum):
    """What the runtime must do when an exception of a given class escapes."""

    FAIL_FAST = "FAIL_FAST"
    """Refuse to start or terminate the run. Used at startup and for invariants."""

    FAIL_CLOSED = "FAIL_CLOSED"
    """Treat the command under inspection as VETOed and notify the fail-safe FSM."""

    FAIL_OPERATIONAL = "FAIL_OPERATIONAL"
    """Record and continue. Only for failures outside the safety argument."""


class AstraError(Exception):
    """Base class for every error raised by ASTRA itself.

    Catching :class:`AstraError` catches exactly the failures ASTRA understands
    and models, and leaves genuine programming errors (``TypeError``,
    ``AttributeError``) to propagate, where they belong. A bare ``except
    Exception`` in a safety path hides the difference; the ``BLE`` lint rule is
    enabled project-wide to prevent one being introduced.

    Attributes:
        code: Stable, greppable identifier. Appears verbatim in audit records,
            so it must never be reused for a different meaning.
        disposition: What the runtime does when this error escapes.
        severity: How the incident is ranked in the audit log.
    """

    code: ClassVar[str] = "ASTRA-000"
    disposition: ClassVar[SafetyDisposition] = SafetyDisposition.FAIL_FAST
    severity: ClassVar[EventSeverity] = EventSeverity.SAFETY_CRITICAL

    def __init__(
        self,
        message: str,
        *,
        layer: LayerId | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the error.

        Args:
            message: Human-readable description. Written for the engineer who
                will read it in a log six months from now, not for the one
                writing it today.
            layer: The pipeline layer in which the failure occurred, when known.
            context: Structured key/value detail attached to the audit record.
                Must contain only JSON-serialisable values.
        """
        super().__init__(message)
        self.message = message
        self.layer = layer
        self.context: dict[str, Any] = dict(context) if context else {}

    def to_audit_fields(self) -> dict[str, Any]:
        """Render the error as a flat, JSON-serialisable audit payload.

        Returns:
            A mapping suitable for embedding directly in an audit record. Keys
            are stable across releases; adding a key is a minor change, removing
            or repurposing one requires an audit schema version bump.
        """
        return {
            "error_code": self.code,
            "error_type": type(self).__name__,
            "message": self.message,
            "disposition": self.disposition.value,
            "severity": self.severity.value,
            "layer": self.layer.value if self.layer is not None else None,
            "context": self.context,
        }

    @override
    def __str__(self) -> str:
        """Return the message prefixed with the stable error code.

        Returns:
            A string of the form ``"[ASTRA-CFG-001] message"``.
        """
        return f"[{self.code}] {self.message}"


# --------------------------------------------------------------------------- #
# Startup and configuration failures -- FAIL_FAST
# --------------------------------------------------------------------------- #


class ConfigurationError(AstraError):
    """The system is not configured in a state it is willing to run in.

    Always ``FAIL_FAST``. A safety system that starts with a configuration it
    could not fully validate has no basis for any subsequent claim it makes,
    and the cheapest moment to fail is before the vehicle moves.
    """

    code: ClassVar[str] = "ASTRA-CFG-001"
    disposition: ClassVar[SafetyDisposition] = SafetyDisposition.FAIL_FAST
    severity: ClassVar[EventSeverity] = EventSeverity.SAFETY_CRITICAL


class SchemaVersionError(ConfigurationError):
    """A configuration file or persisted record declares an unsupported schema version.

    Loading a file whose schema version is unknown is refused rather than
    attempted on a best-effort basis. A calibration profile silently
    misinterpreted because a field moved is precisely the calibration-poisoning
    failure mode the architecture defends against.
    """

    code: ClassVar[str] = "ASTRA-CFG-002"


# --------------------------------------------------------------------------- #
# Data contract failures -- FAIL_CLOSED
# --------------------------------------------------------------------------- #


class ContractViolationError(AstraError):
    """A value violated the invariant its type promises to maintain.

    ``FAIL_CLOSED`` rather than ``FAIL_FAST``: a single malformed sensor frame
    should degrade the current tick to a VETO and be counted by the fail-safe
    FSM, not abort a moving vehicle's control loop. Sustained violations reach
    HALT through the ordinary OOD-counter path, which is the graduated response
    the architecture exists to provide.
    """

    code: ClassVar[str] = "ASTRA-CTR-001"
    disposition: ClassVar[SafetyDisposition] = SafetyDisposition.FAIL_CLOSED
    severity: ClassVar[EventSeverity] = EventSeverity.SAFETY_RELEVANT


class RangeViolationError(ContractViolationError):
    """A value fell outside its permitted range.

    Raised, for example, by a Trust Index outside [0, 1] or a negative speed
    where the contract requires a magnitude.
    """

    code: ClassVar[str] = "ASTRA-CTR-002"


class NonFiniteValueError(ContractViolationError):
    """A NaN or infinity reached a contract boundary.

    Given its own class because it has a distinct root cause: NaN propagates
    silently through arithmetic and through most comparisons, so a NaN that
    reaches a threshold test makes every comparison false and can turn a VETO
    into a PASS. It is caught at the boundary for that reason specifically.
    """

    code: ClassVar[str] = "ASTRA-CTR-003"


class DimensionMismatchError(ContractViolationError):
    """A vector or matrix had the wrong dimension for the layout it claims.

    Guards the fixed layouts in :mod:`astra.kernel.constants`: a 4-element
    Runtime Context Signature cannot be compared against a 5-dimensional
    certified centroid, and failing loudly beats producing a Mahalanobis
    distance from mismatched vectors.
    """

    code: ClassVar[str] = "ASTRA-CTR-004"


# --------------------------------------------------------------------------- #
# Safety pipeline failures -- FAIL_CLOSED
# --------------------------------------------------------------------------- #


class SafetyPathError(AstraError):
    """A component on the command-validation path could not complete its work.

    The base class for failures inside Core-B and RCM. Its existence lets the
    Phase 2 pipeline express "anything that goes wrong here becomes a VETO" as
    a single, reviewable ``except SafetyPathError`` rather than as a policy
    repeated at every call site.
    """

    code: ClassVar[str] = "ASTRA-SAF-001"
    disposition: ClassVar[SafetyDisposition] = SafetyDisposition.FAIL_CLOSED
    severity: ClassVar[EventSeverity] = EventSeverity.SAFETY_RELEVANT


class TimingBudgetExceededError(SafetyPathError):
    """A layer overran the latency budget declared for its timing domain.

    The software targets from the paper's per-layer latency table are treated
    as budgets, not aspirations: exceeding one on the hot path means the tick
    is late, and a late verdict about a vehicle that has already moved is not a
    verdict. ``FAIL_CLOSED`` is the only defensible response.
    """

    code: ClassVar[str] = "ASTRA-SAF-002"
    severity: ClassVar[EventSeverity] = EventSeverity.SAFETY_CRITICAL


# --------------------------------------------------------------------------- #
# Architectural failures -- FAIL_FAST
# --------------------------------------------------------------------------- #


class InvariantViolationError(AstraError):
    """A declared separation invariant was breached at runtime.

    These are not recoverable conditions. If Core-A has obtained a reference to
    a Core-B verdict, or a component other than RCM has issued an actuator
    command, the architecture's safety argument no longer describes the running
    system, and no graduated response is meaningful. The run stops.
    """

    code: ClassVar[str] = "ASTRA-INV-001"
    disposition: ClassVar[SafetyDisposition] = SafetyDisposition.FAIL_FAST
    severity: ClassVar[EventSeverity] = EventSeverity.SAFETY_CRITICAL


# --------------------------------------------------------------------------- #
# External system failures -- FAIL_OPERATIONAL by default
# --------------------------------------------------------------------------- #


class AdapterError(AstraError):
    """An external system an adapter depends on failed.

    Defaults to ``FAIL_OPERATIONAL`` because most adapters -- the dashboard
    stream, the evidence writer -- sit outside the safety argument. Adapters
    that *are* inside it (a sensor source, the actuation sink) must subclass
    this and override the disposition to ``FAIL_CLOSED``; the architecture test
    suite checks that every adapter in the safety path has done so.
    """

    code: ClassVar[str] = "ASTRA-ADP-001"
    disposition: ClassVar[SafetyDisposition] = SafetyDisposition.FAIL_OPERATIONAL
    severity: ClassVar[EventSeverity] = EventSeverity.WARNING
