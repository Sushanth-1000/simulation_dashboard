"""The four-state fail-safe machine and its out-of-distribution counter.

The counter, and why it is a counter
-------------------------------------
Transitions are driven by an integer that increments on a VETO and decrements on
a PASS. That single mechanism gives the machine three properties it would
otherwise need separate machinery for.

*It distinguishes a glitch from a fault.* One VETO moves the counter by one and
changes nothing. Ten consecutive VETOs cross a threshold. A system that
escalated on the first VETO would spend its life in DEGRADED, and one that
needed an explicit "fault confirmed" signal would need something else to decide
when to send it.

*Recovery is the same mechanism run backwards.* A PASS decrements. Sustained
PASSes walk the counter back down through the thresholds and the machine
de-escalates on its own, without a restart and without a separate recovery path
that could disagree with the escalation path.

*It is auditable.* The counter is one integer in every snapshot, so the full
history of why the machine was where it was can be reconstructed from the
evidence log.

Why HALT is different
---------------------
Every other transition is symmetric. HALT is not: the machine will escalate into
it on the counter, but will not leave it on the counter alone. A controlled
pull-over is not something to reverse because a few ticks happened to pass --
the vehicle is stopping, and resuming automatically because the sensor that
failed briefly reported plausible data again is precisely the behaviour that
makes a fail-safe untrustworthy. Leaving HALT requires
:meth:`FailSafeStateMachine.reset`, which is a deliberate external act.

Hysteresis
----------
The escalation thresholds are the configured ``theta`` values. De-escalation
happens at a *lower* counter value, by a configured margin. Without that gap a
counter sitting exactly on a threshold would oscillate between two states on
alternating verdicts, and an oscillating safety posture is worse than either of
the states it flips between: it makes the speed cap and the lane-change
permission change every tick.

Bounds
------
The counter lives in ``[0, ood_threshold_halt]``. The ceiling was added on
2 August 2026 after a soak recorded 1,508 by tick 2,000 and climbing; nothing
consulted the excess, because the machine had been in HALT since 100 and HALT
does not look at the counter.

The bound also puts a *duration* on the recovery promised above, which is the
part worth stating: outside HALT the counter cannot exceed
``ood_threshold_halt``, because reaching it is what enters HALT. So the longest
walk back to NOMINAL is ``ood_threshold_halt - ood_threshold_degraded +
hysteresis`` consecutive clean ticks -- 91 at the simulation profile's
thresholds, 4.6 seconds at 20 Hz. Recovery is automatic *and* bounded, not
merely automatic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from astra.contracts.assurance import FailSafeSnapshot
from astra.kernel.enums import FailSafeState, LayerId
from astra.kernel.errors import ContractViolationError
from astra.kernel.units import MetresPerSecond

if TYPE_CHECKING:
    from astra.config.schema import FailSafeSettings
    from astra.contracts.assurance import SafetyVerdict
    from astra.kernel.identifiers import TickId

__all__ = ["FailSafeStateMachine"]

_COUNTER_FLOOR: Final = 0
"""The counter never goes below zero. A long run of clean ticks must not build
up 'credit' that would let a later burst of vetoes pass unnoticed."""

_HYSTERESIS: Final = 1
"""How far below an escalation threshold the counter must fall before the
machine de-escalates. One is the smallest value that breaks the oscillation
described in the module docstring; it is a constant rather than configuration
because it is a property of the mechanism, not an operating point."""


class FailSafeStateMachine:
    """Walks NOMINAL -> DEGRADED -> LIMP -> HALT on the OOD counter, and back.

    Satisfies :class:`~astra.ports.pipeline.SafetyStateMachine` structurally.

    Stateful by necessity -- the counter *is* the layer -- and not thread-safe.
    It is driven once per tick from the control thread; a lock would add
    synchronisation cost to the hot path to guard against a call pattern the
    architecture does not permit.
    """

    __slots__ = ("_counter", "_human_intervention_requested", "_settings", "_state", "_tick")

    def __init__(self, settings: FailSafeSettings) -> None:
        """Start the machine in NOMINAL with a zero counter.

        Args:
            settings: The three OOD thresholds and the per-state speed caps. The
                schema has already validated that the thresholds strictly
                increase; without that, a state would be unreachable and the
                graduated response would silently have a missing step.
        """
        self._settings = settings
        self._state = FailSafeState.NOMINAL
        self._counter = _COUNTER_FLOOR
        self._tick: TickId | None = None
        self._human_intervention_requested = False

    def observe(self, *, tick: TickId, verdict: SafetyVerdict) -> FailSafeSnapshot:
        """Advance the machine with one tick's verdict.

        Args:
            tick: The control tick.
            verdict: Core-B's combined verdict. Only its aggregate is consulted:
                *which* gate vetoed is evidence for the log, not an input to the
                escalation policy. Weighting gates differently here would make
                the machine's response depend on gate identity and would give
                one gate more authority than another, which SI-3 forbids.

        Returns:
            The safety posture after the transition.
        """
        self._counter = self._advanced_counter(blocking=verdict.is_blocking)
        self._state = self._next_state()
        self._tick = tick
        if self._state is FailSafeState.HALT:
            self._human_intervention_requested = True
        return self.snapshot

    def _advanced_counter(self, *, blocking: bool) -> int:
        """Return the counter after one verdict, bounded at both ends.

        The floor stops a long clean run building 'credit'. The ceiling is the
        HALT threshold, because no value above it can change any decision: the
        machine is already in HALT, HALT is terminal, and
        :meth:`_next_state` returns before consulting the counter at all. An
        integer that grows without bound and influences nothing is noise, and
        this one is written into every :class:`FailSafeSnapshot` and every audit
        row. A 100,000-tick soak recorded 1,508 by tick 2,000 and climbing.

        Time spent in HALT is not lost by capping it: the snapshot carries the
        tick, and the tick HALT was entered is in the log. Reading it off the
        counter would mean one field answering two questions, which is how an
        evidence log becomes ambiguous.

        Args:
            blocking: Whether this tick's verdict was blocking.

        Returns:
            The new counter, in ``[0, ood_threshold_halt]``.
        """
        if not blocking:
            return max(_COUNTER_FLOOR, self._counter - 1)
        return min(self._settings.ood_threshold_halt, self._counter + 1)

    def _next_state(self) -> FailSafeState:
        """Resolve the state the current counter implies.

        Returns:
            The new state, applying hysteresis on the way down and refusing to
            leave HALT automatically.
        """
        if self._state is FailSafeState.HALT:
            # Latched. Only `reset` leaves HALT; see the module docstring.
            return FailSafeState.HALT

        settings = self._settings
        if self._counter >= settings.ood_threshold_halt:
            return FailSafeState.HALT

        escalated = self._escalated_state()
        if escalated.severity_rank > self._state.severity_rank:
            return escalated
        # De-escalate only once the counter has fallen clear of the threshold
        # that put the machine here, so a counter sitting on the boundary does
        # not flip the posture on alternating verdicts.
        return self._de_escalated_state()

    def _escalated_state(self) -> FailSafeState:
        """Return the state the counter implies when escalating.

        Returns:
            The state for the current counter, ignoring hysteresis.
        """
        settings = self._settings
        if self._counter >= settings.ood_threshold_limp:
            return FailSafeState.LIMP
        if self._counter >= settings.ood_threshold_degraded:
            return FailSafeState.DEGRADED
        return FailSafeState.NOMINAL

    def _de_escalated_state(self) -> FailSafeState:
        """Return the state the counter implies when recovering.

        Returns:
            The state for the current counter with the hysteresis margin
            applied, never more severe than the current state.
        """
        settings = self._settings
        if self._counter >= settings.ood_threshold_limp - _HYSTERESIS:
            recovered = FailSafeState.LIMP
        elif self._counter >= settings.ood_threshold_degraded - _HYSTERESIS:
            recovered = FailSafeState.DEGRADED
        else:
            recovered = FailSafeState.NOMINAL
        if recovered.severity_rank > self._state.severity_rank:
            return self._state
        return recovered

    @property
    def snapshot(self) -> FailSafeSnapshot:
        """Return the current posture without advancing the machine.

        Returns:
            The state, the counter and the operating limits it imposes.

        Raises:
            ContractViolationError: If the machine has never been driven, since
                a snapshot with no tick could not be joined to any decision.
        """
        if self._tick is None:
            message = (
                "the fail-safe machine has produced no snapshot yet; "
                "call observe() at least once before reading one"
            )
            raise ContractViolationError(message, layer=LayerId.L8_FAILSAFE_FSM)
        return FailSafeSnapshot(
            tick=self._tick,
            state=self._state,
            ood_counter=self._counter,
            speed_cap=self.speed_cap,
            lane_change_permitted=self._state is FailSafeState.NOMINAL,
            human_intervention_requested=self._human_intervention_requested,
        )

    @property
    def state(self) -> FailSafeState:
        """Return the current state."""
        return self._state

    @property
    def ood_counter(self) -> int:
        """Return the current out-of-distribution counter."""
        return self._counter

    @property
    def speed_cap(self) -> MetresPerSecond | None:
        """Return the speed cap the current state imposes.

        Returns:
            The cap in metres per second, or ``None`` in NOMINAL where no cap
            applies. HALT returns zero rather than ``None``: a controlled
            pull-over is a commanded stop, and reporting "no cap" there would
            invert the meaning.
        """
        if self._state is FailSafeState.NOMINAL:
            return None
        if self._state is FailSafeState.DEGRADED:
            return self._settings.degraded_speed_cap
        if self._state is FailSafeState.LIMP:
            return self._settings.limp_speed_cap
        return MetresPerSecond(0.0)

    def reset(self) -> None:
        """Return the machine to NOMINAL and clear the counter.

        The only way out of HALT. Deliberately explicit: leaving a controlled
        pull-over is an engineering or operator decision, not something a run of
        clean ticks should accomplish on its own.
        """
        self._state = FailSafeState.NOMINAL
        self._counter = _COUNTER_FLOOR
        self._human_intervention_requested = False
