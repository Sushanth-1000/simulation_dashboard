"""Correlation context: which run, tick and component the current work belongs to.

The problem this solves
-----------------------
Audit records are only evidence if they can be joined. Every record needs to
name its run, its tick and the component that produced it -- but threading three
identifiers through every function signature in the pipeline would put
bookkeeping into the signature of every safety-relevant call, which is both
noise and a thing to get wrong.

``contextvars`` puts the correlation data beside the call stack instead of
inside it. A component asks "which tick am I in?" and gets an answer, without
its caller having had to pass one.

Design decision: ``contextvars``, not thread-locals or a global
---------------------------------------------------------------
A module-level global would break the moment RCM's shadow execution runs the
active and candidate calibration tables concurrently -- both are in the same
tick and both emit records, and a single global cannot represent two component
identities at once. Thread-locals would handle threads but not the async
boundaries a dashboard backend introduces. ``contextvars`` handles both, and its
tokens make scope exit exact: :func:`tick_scope` restores precisely the previous
value rather than clearing to a default, so nested and concurrent scopes cannot
corrupt each other.

Event sequencing lives here too
-------------------------------
:class:`~astra.kernel.identifiers.EventId` is ``run:tick:sequence`` with no
randomness, so that a replayed run produces byte-comparable event identifiers.
The sequence counter is therefore per-tick and resets at each tick boundary,
which is exactly what :func:`tick_scope` manages.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from itertools import count
from typing import TYPE_CHECKING

from astra.kernel.errors import InvariantViolationError
from astra.kernel.identifiers import EventId

if TYPE_CHECKING:
    from collections.abc import Iterator

    from astra.kernel.identifiers import ComponentId, RunId, TickId

__all__ = [
    "current_component",
    "current_run",
    "current_tick",
    "next_event_id",
    "run_scope",
    "tick_scope",
]

_run: ContextVar[RunId | None] = ContextVar("astra_run", default=None)
_tick: ContextVar[TickId | None] = ContextVar("astra_tick", default=None)
_component: ContextVar[ComponentId | None] = ContextVar("astra_component", default=None)
_sequence: ContextVar[count[int] | None] = ContextVar("astra_sequence", default=None)


def current_run() -> RunId | None:
    """Return the run in scope, if any.

    Returns:
        The current run identifier, or ``None`` outside a run scope.
    """
    return _run.get()


def current_tick() -> TickId | None:
    """Return the tick in scope, if any.

    Returns:
        The current tick identifier, or ``None`` outside a tick scope.
    """
    return _tick.get()


def current_component() -> ComponentId | None:
    """Return the component in scope, if any.

    Returns:
        The current component identifier, or ``None`` if unset. Distinguishes
        the active from the shadow instance during a staged calibration switch.
    """
    return _component.get()


def next_event_id() -> EventId:
    """Return the next deterministic event identifier for the current tick.

    The sequence is per-tick and starts at zero, so a replayed run reproduces
    the same identifiers and a diff of two event streams is meaningful.

    Returns:
        The next ``run:tick:sequence`` identifier.

    Raises:
        InvariantViolationError: If called outside a tick scope. An event with
            no tick cannot be joined to the decision it belongs to, and an
            unjoinable record is not evidence -- so this fails rather than
            inventing a placeholder tick.
    """
    run = _run.get()
    tick = _tick.get()
    sequence = _sequence.get()
    if run is None or tick is None or sequence is None:
        message = "an audit event cannot be identified outside a tick scope"
        raise InvariantViolationError(
            message,
            context={
                "has_run": run is not None,
                "has_tick": tick is not None,
            },
        )
    return EventId(run=run, tick=tick, sequence=next(sequence))


@contextmanager
def run_scope(run: RunId, component: ComponentId | None = None) -> Iterator[RunId]:
    """Bind a run, and optionally a component, for the duration of the block.

    Args:
        run: The run every record produced inside the block belongs to.
        component: The component identity to bind, when the whole run is
            attributable to one.

    Yields:
        The bound run identifier.
    """
    run_token = _run.set(run)
    component_token = _component.set(component) if component is not None else None
    try:
        yield run
    finally:
        if component_token is not None:
            _component.reset(component_token)
        _run.reset(run_token)


@contextmanager
def tick_scope(tick: TickId, component: ComponentId | None = None) -> Iterator[TickId]:
    """Bind a tick, and reset the intra-tick event sequence, for the block.

    Args:
        tick: The tick every record produced inside the block belongs to.
        component: The component identity to bind for this tick. Supplied by the
            shadow instance during a staged calibration switch so its records
            are distinguishable from the active instance's.

    Yields:
        The bound tick identifier.

    Raises:
        InvariantViolationError: If entered outside a run scope. A tick that
            belongs to no run cannot be placed in an evidence archive.
    """
    if _run.get() is None:
        message = "a tick scope must be entered inside a run scope"
        raise InvariantViolationError(message, context={"tick": tick.value})
    tick_token = _tick.set(tick)
    sequence_token = _sequence.set(count())
    component_token = _component.set(component) if component is not None else None
    try:
        yield tick
    finally:
        if component_token is not None:
            _component.reset(component_token)
        _sequence.reset(sequence_token)
        _tick.reset(tick_token)
