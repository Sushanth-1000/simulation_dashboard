"""The four-state fail-safe machine and its two counters.

Two counters, because there are two ways to be in trouble
----------------------------------------------------------
**This is the layer's most important structural fact and it is four days old.**

The OOD counter answers *"is the command being refused?"* It rises on a VETO and
falls on a PASS. It is the original mechanism and everything below about
glitches, recovery and hysteresis is about it.

The **sensor-integrity counter** answers a different question -- *"can I still
believe what I am being told?"* -- and it exists because OD-9 proved the first
question cannot reach the second. Every Core-B gate reads L2's fast estimate,
and the proposer closes its loop on that same estimate, so a corrupted sensor
reading is driven toward the value the gates consider safe. Measured: a 200-tick
IMU dropout put the vehicle **4.199 m off a 1.75 m lane** with the corridor bound
reading **0.023 m**, a verdict trace **identical to the clean control's**, and
this machine NOMINAL on all 400 ticks (E-46, E-48).

No amount of veto counting finds that, because there were no vetoes. **A veto
could not have helped either**: L9's fallback controller reads the same corrupted
estimate, so refusing the proposal substitutes one command computed from a lie
for another. You cannot veto your way out of a lying sensor.

So the integrity counter reads :class:`~astra.kernel.enums.StreamHealth`, which
L1 computes at the sensor boundary **before the filter touches anything**. That
is the whole point: it is the one input in this machine that is upstream of the
common cause. See ADR-0024.

The two counters drive the same four states and the more severe of the two wins.
They are reported separately in every snapshot and every audit record, because
"the gates refused forty commands" and "a sensor was dark for forty ticks" need
different responses from whoever reads the log, and one integer cannot say which
happened.

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
6 August 2026 after a soak recorded 1,508 by tick 2,000 and climbing; nothing
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
from astra.kernel.enums import FailSafeState, LayerId, StreamHealth
from astra.kernel.errors import ContractViolationError
from astra.kernel.units import MetresPerSecond

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.config.schema import FailSafeSettings
    from astra.contracts.assurance import SafetyVerdict
    from astra.kernel.enums import SensorModality
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


def _band(counter: int, *, degraded: int, limp: int) -> FailSafeState:
    """Return the state one counter implies against its own two thresholds.

    Args:
        counter: The counter value.
        degraded: The threshold at or above which DEGRADED applies.
        limp: The threshold at or above which LIMP applies.

    Returns:
        NOMINAL, DEGRADED or LIMP. HALT is resolved by the caller, because it is
        latching and the two counters reach it independently.
    """
    if counter >= limp:
        return FailSafeState.LIMP
    if counter >= degraded:
        return FailSafeState.DEGRADED
    return FailSafeState.NOMINAL


def _worse(left: FailSafeState, right: FailSafeState) -> FailSafeState:
    """Return the more severe of two states.

    Args:
        left: One state.
        right: The other.

    Returns:
        Whichever has the higher severity rank; ``left`` if they are equal.
    """
    return left if left.severity_rank >= right.severity_rank else right


class FailSafeStateMachine:
    """Walks NOMINAL -> DEGRADED -> LIMP -> HALT on the OOD counter, and back.

    Satisfies :class:`~astra.ports.pipeline.SafetyStateMachine` structurally.

    Stateful by necessity -- the counter *is* the layer -- and not thread-safe.
    It is driven once per tick from the control thread; a lock would add
    synchronisation cost to the hot path to guard against a call pattern the
    architecture does not permit.
    """

    __slots__ = (
        "_counter",
        "_human_intervention_requested",
        "_integrity",
        "_settings",
        "_state",
        "_tick",
    )

    def __init__(self, settings: FailSafeSettings) -> None:
        """Start the machine in NOMINAL with both counters at zero.

        Args:
            settings: The two threshold triples and the per-state speed caps. The
                schema has already validated that each triple strictly
                increases; without that, a state would be unreachable and the
                graduated response would silently have a missing step.
        """
        self._settings = settings
        self._state = FailSafeState.NOMINAL
        self._counter = _COUNTER_FLOOR
        self._integrity = _COUNTER_FLOOR
        self._tick: TickId | None = None
        self._human_intervention_requested = False

    def observe(
        self,
        *,
        tick: TickId,
        verdict: SafetyVerdict,
        frame_health: Sequence[tuple[SensorModality, StreamHealth]] = (),
        exploring: bool = False,
    ) -> FailSafeSnapshot:
        """Advance the machine with one tick's verdict and sensor health.

        Args:
            tick: The control tick.
            verdict: Core-B's combined verdict. Only its aggregate is consulted:
                *which* gate vetoed is evidence for the log, not an input to the
                escalation policy. Weighting gates differently here would make
                the machine's response depend on gate identity and would give
                one gate more authority than another, which SI-3 forbids.
            frame_health: Per-modality stream health for this tick, as L1
                determined it. **The one input this machine has that is upstream
                of L2**, and therefore the only one that can see a fault the
                estimator has absorbed -- see :meth:`_advanced_integrity` and
                ADR-0024. Empty is treated as healthy, which is what a caller
                with no sensor bus means; the default exists so that the
                hundreds of tests written against the verdict half of this
                machine keep testing exactly that.
            exploring: Whether L9 has declared bounded safe exploration for this
                tick. **The OOD counter freezes while it has, and the integrity
                counter does not** -- see :meth:`_advanced_counter`, ADR-0023 and
                ADR-0024.

        Returns:
            The safety posture after the transition.
        """
        self._counter = self._advanced_counter(blocking=verdict.is_blocking, exploring=exploring)
        self._integrity = self._advanced_integrity(frame_health=frame_health)
        self._state = self._next_state()
        self._tick = tick
        if self._state is FailSafeState.HALT:
            self._human_intervention_requested = True
        return self.snapshot

    def _advanced_integrity(
        self, *, frame_health: Sequence[tuple[SensorModality, StreamHealth]]
    ) -> int:
        """Return the sensor-integrity counter after one frame.

        Rises on any modality worse than ``HEALTHY``, falls on a frame where
        every modality is healthy, and is bounded exactly as the OOD counter is
        and for the same reasons.

        **It does not freeze during bounded safe exploration, and the asymmetry
        is deliberate.** ADR-0023 froze the OOD counter while L9 owns the
        out-of-envelope condition, and recorded as an accepted risk that a fault
        arising *during* exploration would then not escalate either. That risk
        is real for a fault the gates can see. It is not accepted here: L9
        narrowing its envelope is a response to *the world being unfamiliar*, and
        says nothing whatever about whether the sensors are still telling the
        truth. A vehicle exploring a tunnel with a dead IMU is in more trouble
        than one doing either alone, not less.

        **Any modality, not a quorum.** A single unhealthy channel is enough,
        because the modalities are not redundant in this build -- there is one
        publisher per modality and no cross-check to fall back on. When
        redundancy exists (Phase 7, and P2.7 option D) this is the line that
        should become a vote, and it needs its own decision record when it does.

        **Scope, stated because silence would overclaim it.** ``StreamHealth``
        is computed from *staleness*: a modality that stops publishing goes
        ``DEGRADED`` and then ``ABSENT``. A modality that publishes a **fresh,
        well-formed, wrong** value stays ``HEALTHY`` for ever. So this counter
        catches ``DROPOUT`` and is silent on ``BIAS``, ``DRIFT`` and
        ``STUCK_AT``, which is exactly what the shadow measurement found (E-51)
        and exactly why those three faults were chosen. It closes the worst
        third of OD-9 and is honest about the other two.

        Args:
            frame_health: Per-modality health for this tick. Empty means the
                caller has no sensor bus and is treated as healthy rather than
                as unknown -- the alternative would escalate every test that
                drives this machine directly.

        Returns:
            The new counter, in ``[0, integrity_threshold_halt]``.
        """
        unhealthy = any(health is not StreamHealth.HEALTHY for _, health in frame_health)
        if not unhealthy:
            return max(_COUNTER_FLOOR, self._integrity - 1)
        return min(self._settings.integrity_threshold_halt, self._integrity + 1)

    def _advanced_counter(self, *, blocking: bool, exploring: bool = False) -> int:
        """Return the counter after one verdict, bounded at both ends.

        **Frozen during bounded safe exploration, and that is ADR-0023.** The
        counter exists to *detect* sustained out-of-distribution operation and
        degrade the posture in response. While L9 has declared
        ``SAFE_EXPLORATION`` that condition has already been detected, declared,
        logged, and responded to -- by a narrowed actuation envelope. Counting
        it again escalates one event twice, and measured on a platform the twin
        was never fitted to it escalated all the way: RCM held
        ``SAFE_EXPLORATION`` for 520 ticks while this counter climbed 0 -> 100
        and HALTed the vehicle underneath it (OD-12).

        That defeated the architecture's distinguishing claim -- *"others
        degrade to a halt when they leave their certified envelope; ASTRA is
        built not to"* -- using ASTRA's own fail-safe machine.

        **Veto authority is untouched.** Every gate still vetoes and every veto
        still stops the command reaching an actuator; SI-3 is exactly as it was.
        What is suspended is escalation to a *terminal* posture, and the
        exploration envelope -- half the nearest certified speed, a +/-15 degree
        steering cone, no lane changes -- is the risk control in its place,
        which is what that envelope is for.

        The freeze is deliberately not a decay. On leaving exploration the
        machine resumes from the posture it held on entering, so a vehicle that
        was already DEGRADED does not emerge from a tunnel pretending it was
        not.

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
            exploring: Whether L9 has declared bounded safe exploration. The
                counter neither rises nor falls while it has.

        Returns:
            The new counter, in ``[0, ood_threshold_halt]``.
        """
        if exploring:
            return self._counter
        if not blocking:
            return max(_COUNTER_FLOOR, self._counter - 1)
        return min(self._settings.ood_threshold_halt, self._counter + 1)

    def _next_state(self) -> FailSafeState:
        """Resolve the state the two counters imply, taking the worse.

        **Neither counter can be overruled by the other's good news.** The
        machine escalates on whichever is more severe and de-escalates only when
        both agree it may, because the two describe unrelated conditions: a
        clean verdict stream says nothing about whether the sensors are honest,
        and a healthy sensor frame says nothing about whether the commands are
        admissible. Taking the maximum is the only combination that preserves
        each counter's meaning; taking a sum or an average would make a moderate
        amount of each look like a lot of one.

        Returns:
            The new state, applying hysteresis on the way down and refusing to
            leave HALT automatically.
        """
        if self._state is FailSafeState.HALT:
            # Latched. Only `reset` leaves HALT; see the module docstring.
            return FailSafeState.HALT

        settings = self._settings
        if (
            self._counter >= settings.ood_threshold_halt
            or self._integrity >= settings.integrity_threshold_halt
        ):
            return FailSafeState.HALT

        escalated = self._escalated_state()
        if escalated.severity_rank > self._state.severity_rank:
            return escalated
        # De-escalate only once both counters have fallen clear of the threshold
        # that put the machine here, so a counter sitting on the boundary does
        # not flip the posture on alternating verdicts.
        return self._de_escalated_state()

    def _escalated_state(self) -> FailSafeState:
        """Return the more severe of the two states the counters imply.

        Returns:
            The state for the current counters, ignoring hysteresis.
        """
        settings = self._settings
        return _worse(
            _band(
                self._counter,
                degraded=settings.ood_threshold_degraded,
                limp=settings.ood_threshold_limp,
            ),
            _band(
                self._integrity,
                degraded=settings.integrity_threshold_degraded,
                limp=settings.integrity_threshold_limp,
            ),
        )

    def _de_escalated_state(self) -> FailSafeState:
        """Return the state the counters imply when recovering.

        Returns:
            The more severe of the two bands with the hysteresis margin applied,
            never more severe than the current state.
        """
        settings = self._settings
        recovered = _worse(
            _band(
                self._counter,
                degraded=settings.ood_threshold_degraded - _HYSTERESIS,
                limp=settings.ood_threshold_limp - _HYSTERESIS,
            ),
            _band(
                self._integrity,
                degraded=settings.integrity_threshold_degraded - _HYSTERESIS,
                limp=settings.integrity_threshold_limp - _HYSTERESIS,
            ),
        )
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
            integrity_counter=self._integrity,
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
    def integrity_counter(self) -> int:
        """Return the current sensor-integrity counter."""
        return self._integrity

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
        """Return the machine to NOMINAL and clear both counters.

        The only way out of HALT. Deliberately explicit: leaving a controlled
        pull-over is an engineering or operator decision, not something a run of
        clean ticks should accomplish on its own.

        **Both counters clear, and that is not a convenience.** A reset that left
        the integrity counter standing would re-escalate within a tick or two if
        the sensor were still dark, which reads as the reset having failed rather
        than as the fault having persisted. An operator who resets a vehicle
        whose IMU is still dead should watch it escalate again from zero and see
        the counter climb -- the log then shows a second, independent
        escalation, which is the truth.
        """
        self._state = FailSafeState.NOMINAL
        self._counter = _COUNTER_FLOOR
        self._integrity = _COUNTER_FLOOR
        self._human_intervention_requested = False
