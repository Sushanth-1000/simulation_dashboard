"""Ports for the infrastructure the pipeline depends on but does not own.

The pipeline needs to record evidence, load calibration profiles, drive
actuators and route feedback. Each of those touches the world outside the
process, and each therefore sits behind a port so the core never learns what is
on the other side. The audit sink might be a JSONL file today and a signed log
tomorrow; the actuation sink is CARLA in the prototype and a CAN bus in a
vehicle. Neither change should reach the layers.

Timing domains are part of these contracts
------------------------------------------
:class:`EventSink.emit` is documented as non-blocking, and that is a safety
requirement rather than a performance preference: the hot path has a < 10 ms
end-to-end budget at 20 Hz, and an ``fsync`` inside a tick would blow it. SI-8
demands that cold-path work never blocks a tick, so the implementation queues
and a background writer drains. A sink that blocks satisfies the type and
violates the architecture, which is why the requirement is stated here where an
implementer will read it.

Clock
-----
:class:`~astra.kernel.time.Clock` is the fourth infrastructure port. It lives in
:mod:`astra.kernel.time` rather than here because the kernel's own primitives
(:class:`~astra.kernel.time.Instant`, staleness) are defined in terms of it and
the kernel may not import upward. It is named here so this module reads as the
complete inventory of injected infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator

    from astra.contracts.actuation import IssuedCommand
    from astra.contracts.audit import AuditEvent, DecisionRecord, ExecutionOutcome
    from astra.contracts.governance import CalibrationProfile
    from astra.kernel.enums import ContextClass
    from astra.kernel.identifiers import ProfileId

__all__ = [
    "ActuationSink",
    "EventSink",
    "FeedbackBus",
    "ProfileRepository",
]


@runtime_checkable
class EventSink(Protocol):
    """Where audit evidence goes.

    The implementation behind this port produces the artefact NFR8 calls
    certification evidence, so its guarantees are part of the safety argument:
    append-only, ordered within a run, schema-versioned, and complete from the
    first tick.
    """

    def emit(self, event: AuditEvent) -> None:
        """Record one audit event.

        **Must not block.** Called from the hot path; the implementation queues
        and a background writer performs the I/O (SI-8).

        Args:
            event: The event to record.
        """
        ...

    def record_decision(self, record: DecisionRecord) -> None:
        """Record one tick's full decision provenance.

        **Must not block**, for the same reason as :meth:`emit`.

        Args:
            record: The decision record for the tick.
        """
        ...

    def record_outcome(self, outcome: ExecutionOutcome) -> None:
        """Record what actually happened after a command was applied.

        Args:
            outcome: The executed outcome and the loops it feeds.
        """
        ...

    def flush(self) -> None:
        """Drain any buffered records to durable storage.

        Blocking, and therefore never called from within a tick. The composition
        root calls it at shutdown so that a run's evidence is complete even if
        the process is stopping.
        """
        ...


@runtime_checkable
class ProfileRepository(Protocol):
    """The calibration knowledge base.

    Profiles are immutable and versioned (NFR7), so this port offers no update
    or delete: a change to a profile is a new version, and retirement is a
    lookup that stops returning it. There is deliberately no ``save`` on the
    runtime path -- certification produces profiles offline, and a pipeline that
    could write its own calibration could also poison it.
    """

    def get(self, profile_id: ProfileId) -> CalibrationProfile:
        """Return one profile by its versioned identity.

        Args:
            profile_id: The ``name@vN`` identity.

        Returns:
            The certified profile.

        Raises:
            ConfigurationError: If no profile with that identity exists.
        """
        ...

    def for_context(self, context_class: ContextClass) -> tuple[CalibrationProfile, ...]:
        """Return every certified profile for one context class.

        Args:
            context_class: The class to search.

        Returns:
            The matching profiles, possibly empty. An empty result is the
            expected outcome for an uncertified context -- the tunnel case --
            and is what triggers bounded safe exploration rather than an error.
        """
        ...

    def __iter__(self) -> Iterator[CalibrationProfile]:
        """Iterate every profile in the knowledge base.

        Returns:
            An iterator used by RCM's cold-path search and by the startup
            integrity check.
        """
        ...


@runtime_checkable
class ActuationSink(Protocol):
    """Where an issued command goes: the simulator, or a real actuator bus.

    The signature accepts only an
    :class:`~astra.contracts.actuation.IssuedCommand`, which by construction can
    only have been built by an L9 component. Sole actuation authority (SI-7) is
    therefore enforced at the type level all the way to the boundary: there is
    no way to hand this port a command that some other layer produced.
    """

    def apply(self, command: IssuedCommand) -> None:
        """Send a command to the actuators.

        Args:
            command: The command L9 issued for this tick.

        Raises:
            AdapterError: If the actuator transport failed. Implementations on
                the safety path override the disposition to ``FAIL_CLOSED``.
        """
        ...


@runtime_checkable
class FeedbackBus(Protocol):
    """Routes executed outcomes back to the layers that learn from them.

    The four feedback loops are brought up one at a time, and each must be
    individually removable so the ablation study can measure what it contributes.
    Routing through a bus rather than by direct calls between layers is what
    makes "disable FB2 and re-run" a configuration change instead of a code
    change -- and it keeps L5 from importing L9 to receive its own feedback.
    """

    def publish(self, outcome: ExecutionOutcome) -> None:
        """Publish an executed outcome to every loop it names.

        Args:
            outcome: The outcome, carrying the set of loops it feeds.
        """
        ...
