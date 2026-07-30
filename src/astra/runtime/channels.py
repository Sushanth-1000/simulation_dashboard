"""The one-way Core-A to Core-B channel, and why it is two types.

Separation invariant SI-5
--------------------------
Core-A may write a proposed command into Core-B. It may read *nothing* back: no
verdict, no fail-safe state, no calibration table, no quantile. The reason is
adversarial rather than tidy. Core-A is a learned policy trained by
optimisation, and anything it can observe it can learn to exploit. A proposer
that can see the gate can learn to slip past it, which converts defence in depth
into a single adversarial optimisation problem with the safety monitor as its
objective.

Why a capability pair, not a queue with a convention
-----------------------------------------------------
The obvious implementation is one queue object shared by both cores, with a
comment saying Core-A must only call ``put``. That is a convention, and a
convention is a comment that does not fail a build.

Instead the channel is created as a *pair of endpoints* with disjoint methods:

* :class:`ProposalWriter` has ``send`` and no way to read.
* :class:`ProposalReader` has ``receive`` and no way to write.

Core-A is handed the writer. It cannot read a verdict back through this channel
because the object it holds has no method that returns one -- not because it has
been told not to. The illegal operation is unrepresentable rather than
forbidden, which is the same technique
:class:`~astra.contracts.actuation.IssuedCommand` uses for SI-7.

The runtime guard on top
------------------------
The type discipline covers the channel. It does not cover a component that
acquires a Core-B artefact some other way -- through a shared object, a global,
a constructor argument. :func:`guard_core_a_isolation` is the check for that
case, and it exists because SI-5's enforcement in the invariant catalogue claims
a runtime guard, and a claim of enforcement that nothing implements is worse
than an honest admission of none.

Bounded, and what a full queue means
-------------------------------------
The queue is bounded. If it fills, Core-B has stopped consuming, and a proposal
that cannot be delivered must not block Core-A's tick -- the proposer is on the
hot path too. :meth:`ProposalWriter.send` therefore returns ``False`` rather
than blocking, and the caller treats an undelivered proposal as a tick that
produced no proposal at all. Core-B seeing no proposal produces an empty verdict
set, which by :meth:`~astra.kernel.enums.Verdict.merge` is a VETO. The
fail-closed path is reached by the ordinary route, with nothing special-cased.
"""

from __future__ import annotations

import queue
from typing import TYPE_CHECKING, Final

from astra.kernel.enums import ExecutionDomain, LayerId
from astra.kernel.errors import InvariantViolationError

if TYPE_CHECKING:
    from astra.contracts.actuation import ProposedCommand
    from astra.kernel.identifiers import ComponentId

__all__ = [
    "ProposalReader",
    "ProposalWriter",
    "guard_core_a_isolation",
    "open_proposal_channel",
]

DEFAULT_CAPACITY: Final = 4
"""How many undelivered proposals the channel holds.

Small on purpose. A proposal is only meaningful for the tick it was computed
for: at 20 Hz, the fifth queued proposal describes a world 250 ms old, and
acting on it would be worse than acting on nothing. A deep queue would convert
a Core-B stall into a burst of stale commands rather than into the VETOs it
should produce.
"""


class ProposalWriter:
    """Core-A's end of the channel. Can send; has no way to read.

    The absence of a read method is the enforcement of SI-5, not an oversight.
    """

    __slots__ = ("_queue",)

    def __init__(self, channel: queue.Queue[ProposedCommand]) -> None:
        """Wrap the shared queue in a write-only endpoint.

        Args:
            channel: The underlying queue. Private to this module; neither core
                is given a reference to it.
        """
        self._queue = channel

    def send(self, proposal: ProposedCommand) -> bool:
        """Offer a proposal to Core-B without blocking.

        Args:
            proposal: The proposed command for this tick.

        Returns:
            ``True`` if the proposal was queued, ``False`` if the channel was
            full. A ``False`` means Core-B has stalled; the caller treats the
            tick as having produced no proposal, which reaches a VETO through
            the ordinary fail-closed path rather than a special case.
        """
        try:
            self._queue.put_nowait(proposal)
        except queue.Full:
            return False
        return True

    @property
    def pending(self) -> int:
        """Return how many proposals are queued but not yet consumed.

        A diagnostic, and the one thing Core-A may observe about the channel. It
        is a property of the transport, not a Core-B artefact: it says whether
        the pipe is backing up, and nothing whatever about any verdict.

        Returns:
            The approximate queue depth.
        """
        return self._queue.qsize()


class ProposalReader:
    """Core-B's end of the channel. Can receive; has no way to send.

    The write direction is absent for symmetry of reasoning rather than for
    SI-5: nothing forbids Core-B from writing to Core-A, but there is no channel
    for it to write to, and one endpoint that could both send and receive would
    invite exactly the shared-object design this pair exists to avoid.
    """

    __slots__ = ("_queue",)

    def __init__(self, channel: queue.Queue[ProposedCommand]) -> None:
        """Wrap the shared queue in a read-only endpoint.

        Args:
            channel: The underlying queue.
        """
        self._queue = channel

    def receive(self) -> ProposedCommand | None:
        """Take the next proposal, without blocking.

        Never blocks. Core-B waiting on a proposer that has stalled would put
        Core-A's fault inside Core-B's tick budget, which is the coupling the
        two-core split exists to prevent.

        Returns:
            The next proposal, or ``None`` if none is waiting. ``None`` is a
            legitimate outcome: no proposal means no command to validate, an
            empty verdict set, and therefore a VETO.
        """
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def drain(self) -> ProposedCommand | None:
        """Take the most recent proposal and discard any older ones.

        The right read for a control loop that fell behind. A proposal computed
        three ticks ago describes a world that no longer exists, and validating
        it would produce a verdict about a situation the vehicle has already
        left. Discarded proposals are dropped silently here because the drop is
        visible where it matters -- as a gap in the tick sequence of the
        evidence log.

        Returns:
            The newest queued proposal, or ``None`` if the channel was empty.
        """
        newest: ProposedCommand | None = None
        while True:
            try:
                newest = self._queue.get_nowait()
            except queue.Empty:
                return newest


def open_proposal_channel(
    capacity: int = DEFAULT_CAPACITY,
) -> tuple[ProposalWriter, ProposalReader]:
    """Create a one-way channel and return its two endpoints.

    The only way to build a channel. There is deliberately no accessor for the
    underlying queue: a caller that could obtain it could hand the same object
    to both cores and reintroduce the bidirectional path this design exists to
    remove.

    Args:
        capacity: How many undelivered proposals to hold. See
            :data:`DEFAULT_CAPACITY` for why the default is small.

    Returns:
        ``(writer, reader)`` -- the writer for Core-A, the reader for Core-B.

    Raises:
        InvariantViolationError: If the capacity is not positive. A
            zero-capacity channel would silently drop every proposal, so Core-B
            would validate nothing and every tick would VETO -- a system that
            looks fail-safe while being entirely non-functional.
    """
    if capacity < 1:
        message = (
            f"a proposal channel needs a capacity of at least 1, got {capacity}; "
            f"a zero-capacity channel drops every proposal and would make the "
            f"pipeline veto every tick while appearing to operate"
        )
        raise InvariantViolationError(message, context={"capacity": capacity})
    channel: queue.Queue[ProposedCommand] = queue.Queue(maxsize=capacity)
    return ProposalWriter(channel), ProposalReader(channel)


def guard_core_a_isolation(reader: ComponentId, artefact: str) -> None:
    """Assert that a Core-B artefact is not being read by Core-A (SI-5).

    The type discipline above prevents Core-A reading through the *channel*.
    This guards the paths it cannot see: an artefact reaching Core-A through a
    constructor argument, a shared object or a global.

    Args:
        reader: The component about to read the artefact.
        artefact: What is being read, named for the audit record -- ``"verdict"``,
            ``"failsafe_state"``, ``"calibration_table"``.

    Raises:
        InvariantViolationError: If the reader belongs to the Core-A domain. Not
            recoverable: a proposer that has observed a Core-B artefact can be
            trained against it, and the independence argument no longer
            describes the running system.
    """
    if reader.layer.execution_domain is ExecutionDomain.CORE_A:
        message = (
            f"{reader} is in Core-A and may not read the Core-B artefact "
            f"{artefact!r}; the proposer is trained by optimisation, and anything "
            f"it can observe it can learn to exploit (SI-5)"
        )
        raise InvariantViolationError(
            message,
            layer=reader.layer,
            context={"reader": str(reader), "artefact": artefact},
        )


def guard_proposal_origin(source: ComponentId) -> None:
    """Assert that only Core-A writes proposals into the channel.

    The counterpart of :func:`guard_core_a_isolation`. A proposal arriving from
    a Core-B component would mean the safety island is proposing commands to
    itself, which makes the verdict a self-assessment.

    Args:
        source: The component that produced the proposal.

    Raises:
        InvariantViolationError: If the source is not the Core-A proposer.
    """
    if source.layer is not LayerId.L4_CORE_A_CMDP:
        message = (
            f"{source} is not the Core-A proposer and may not write to the "
            f"proposal channel; a proposal from inside Core-B would make the "
            f"safety verdict a self-assessment (SI-5)"
        )
        raise InvariantViolationError(message, layer=source.layer, context={"source": str(source)})
