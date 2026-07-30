"""Typed identifiers used to correlate every artefact ASTRA produces.

Why identifiers get their own module
------------------------------------
NFR8 requires that every veto event, Trust Index value, FSM transition and
calibration switch is logged for post-hoc analysis and certification evidence.
That requirement is only satisfiable if the records can be *joined*: the Trust
Index at tick 4 200 has to be provably the one that informed the arbitration at
tick 4 200. Bare strings and ints cannot express that relationship, and the
first time a run identifier is passed where a profile identifier is expected,
the evidence archive is quietly corrupt.

Determinism is a hard requirement here
--------------------------------------
The Prototype & Demo Plan calls for replay tooling capable of freezing and
replaying a specific tick range, and warns that closed-loop debugging without
it costs days instead of hours. Replay is only useful if a replayed run
produces *comparable* records. Any identifier derived from ``uuid4()`` or a
wall-clock reading would differ on every replay and make a diff meaningless.

The rule adopted is therefore: exactly one identifier in the system is random
(:class:`RunId`, generated once per run and injectable for replay); every other
identifier is a pure function of run, tick and sequence. Two runs of the same
inputs then produce byte-comparable event streams.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Self, override

from astra.kernel.errors import ContractViolationError

if TYPE_CHECKING:
    from astra.kernel.enums import LayerId

__all__ = ["ComponentId", "EventId", "ProfileId", "RunId", "TickId"]

_RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
_PROFILE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
_MAX_COMPONENT_INSTANCE_LENGTH = 32


@dataclass(frozen=True, slots=True)
class RunId:
    """Identifies a single execution of the ASTRA pipeline.

    The only deliberately non-deterministic identifier in the system. A replay
    supplies the original run's identifier explicitly so that replayed records
    carry the identity of the run being reproduced.

    Attributes:
        value: Lower-case slug, 3-64 characters of ``[a-z0-9_-]``.
    """

    value: str

    def __post_init__(self) -> None:
        """Validate the identifier's shape.

        Raises:
            ContractViolationError: If the value is not a valid run slug.
        """
        if not _RUN_ID_PATTERN.match(self.value):
            message = f"run identifier {self.value!r} is not a 3-64 char [a-z0-9_-] slug"
            raise ContractViolationError(message, context={"value": self.value})

    @classmethod
    def generate(cls) -> Self:
        """Create a fresh, random run identifier.

        Returns:
            A run identifier of the form ``run-<16 hex chars>``.
        """
        return cls(f"run-{uuid.uuid4().hex[:16]}")

    @override
    def __str__(self) -> str:
        """Return the raw slug.

        Returns:
            The identifier value.
        """
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class TickId:
    """A monotonically increasing control-loop tick number.

    The primary correlation key of the whole system. Every record produced
    during a tick carries the same :class:`TickId`, which is what allows the
    dashboard to show a coherent snapshot and the replay harness to address a
    range.

    Ordered so that ``tick_a < tick_b`` reads naturally. Deliberately not a bare
    ``int``: ordering against an OOD counter or a profile version would then
    type-check, and both are also small monotonic integers.

    Attributes:
        value: Zero-based tick number.
    """

    ORIGIN: ClassVar[int] = 0
    """The tick number the pipeline starts from."""

    value: int

    def __post_init__(self) -> None:
        """Validate that the tick number is a non-negative integer.

        Raises:
            ContractViolationError: If the value is negative or not an ``int``.
        """
        # Deliberately checked despite the annotation: tick numbers arrive from
        # deserialised records, where the annotation is unverified. See the
        # note in astra.kernel.time.Instant.__post_init__.
        if not isinstance(self.value, int) or isinstance(  # type: ignore[redundant-expr]
            self.value, bool
        ):
            message = f"tick identifier must be an int, got {type(self.value).__name__}"
            raise ContractViolationError(message)
        if self.value < 0:
            message = f"tick identifier must be non-negative, got {self.value}"
            raise ContractViolationError(message, context={"value": self.value})

    @classmethod
    def origin(cls) -> Self:
        """Return the first tick of a run.

        Returns:
            ``TickId(0)``.
        """
        return cls(cls.ORIGIN)

    def next(self) -> Self:
        """Return the following tick.

        Returns:
            A new :class:`TickId` one greater than this one.
        """
        return type(self)(self.value + 1)

    @override
    def __str__(self) -> str:
        """Return the tick number as a zero-padded string for stable log alignment.

        Returns:
            The tick number padded to nine digits, e.g. ``"000004200"``.
        """
        return f"{self.value:09d}"


@dataclass(frozen=True, slots=True)
class ProfileId:
    """Identifies one immutable version of a calibration profile.

    NFR7 requires the Calibration Knowledge Base to store only versioned,
    immutable profiles, and requires profile retirement not to modify the active
    safety argument. Binding name and version into a single identifier is what
    makes that enforceable: there is no way to refer to "the highway profile"
    without saying which certified version, so an audit record can never be
    ambiguous about what was actually active.

    Attributes:
        name: Profile family name, e.g. ``"highway_clear"``.
        version: Monotonically increasing certified version, starting at 1.
    """

    name: str
    version: int

    def __post_init__(self) -> None:
        """Validate the profile name and version.

        Raises:
            ContractViolationError: If the name is malformed or the version is
                not a positive integer.
        """
        if not _PROFILE_NAME_PATTERN.match(self.name):
            message = f"profile name {self.name!r} is not a 3-48 char [a-z][a-z0-9_] slug"
            raise ContractViolationError(message, context={"name": self.name})
        # Deliberately checked despite the annotation: profile versions are
        # parsed from calibration files authored outside this codebase.
        if not isinstance(self.version, int) or isinstance(  # type: ignore[redundant-expr]
            self.version, bool
        ):
            message = f"profile version must be an int, got {type(self.version).__name__}"
            raise ContractViolationError(message)
        if self.version < 1:
            message = f"profile version must be >= 1, got {self.version}"
            raise ContractViolationError(message, context={"version": self.version})

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse the canonical ``name@vN`` form.

        Args:
            text: A string such as ``"rain_night@v2"``.

        Returns:
            The corresponding profile identifier.

        Raises:
            ContractViolationError: If the text is not in ``name@vN`` form.
        """
        name, separator, version_part = text.partition("@v")
        if not separator or not version_part.isdigit():
            message = f"profile identifier {text!r} is not in 'name@vN' form"
            raise ContractViolationError(message, context={"text": text})
        return cls(name=name, version=int(version_part))

    @override
    def __str__(self) -> str:
        """Return the canonical ``name@vN`` form.

        Returns:
            A string such as ``"rain_night@v2"``.
        """
        return f"{self.name}@v{self.version}"


@dataclass(frozen=True, slots=True)
class ComponentId:
    """Identifies the concrete component instance that produced a record.

    A layer may have more than one live instance: RCM runs the active and the
    candidate calibration table simultaneously during shadow execution, and both
    emit verdicts for the same tick. Without an instance discriminator those two
    record streams are indistinguishable, and the Calibration Divergence Index
    cannot be reconstructed from the log after the fact.

    Attributes:
        layer: The pipeline layer this component implements.
        instance: Discriminator within the layer. ``"primary"`` by default;
            ``"shadow"`` for the candidate table during a staged switch.
    """

    layer: LayerId
    instance: str = "primary"

    def __post_init__(self) -> None:
        """Validate the instance discriminator.

        Raises:
            ContractViolationError: If the instance name is empty or too long.
        """
        if not self.instance or len(self.instance) > _MAX_COMPONENT_INSTANCE_LENGTH:
            message = (
                f"component instance {self.instance!r} must be "
                f"1-{_MAX_COMPONENT_INSTANCE_LENGTH} characters"
            )
            raise ContractViolationError(message, context={"instance": self.instance})

    @override
    def __str__(self) -> str:
        """Return the canonical ``LAYER/instance`` form.

        Returns:
            A string such as ``"L9_RCM/shadow"``.
        """
        return f"{self.layer.value}/{self.instance}"


@dataclass(frozen=True, slots=True)
class EventId:
    """Deterministic identity of a single audit event.

    Composed purely of ``(run, tick, sequence)``. No randomness and no clock
    reading participate, so replaying a recorded run reproduces the same event
    identifiers and a diff of two event streams is meaningful.

    Not directly orderable. Comparing two :class:`RunId` values has no defined
    meaning -- one run is not "before" another -- so an ordering operator on
    this type would be arithmetic that type-checks but says nothing. Use
    :attr:`sort_key` to order events that are known to belong to the same run.

    Attributes:
        run: The run in which the event occurred.
        tick: The control-loop tick during which it was emitted.
        sequence: Monotonic counter within the tick, starting at 0.
    """

    run: RunId
    tick: TickId
    sequence: int

    def __post_init__(self) -> None:
        """Validate the intra-tick sequence number.

        Raises:
            ContractViolationError: If the sequence number is negative.
        """
        if self.sequence < 0:
            message = f"event sequence must be non-negative, got {self.sequence}"
            raise ContractViolationError(message, context={"sequence": self.sequence})

    @property
    def sort_key(self) -> tuple[str, int, int]:
        """Return a total-order key for events within a single run.

        Returns:
            ``(run slug, tick number, intra-tick sequence)``, which is
            chronological for events sharing a run.
        """
        return (self.run.value, self.tick.value, self.sequence)

    @override
    def __str__(self) -> str:
        """Return the canonical ``run:tick:sequence`` form.

        Returns:
            A string such as ``"run-1a2b3c:000004200:0003"``.
        """
        return f"{self.run}:{self.tick}:{self.sequence:04d}"
