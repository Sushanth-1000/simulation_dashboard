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
        "_ceiling",
        "_counter",
        "_decay",
        "_human_intervention_requested",
        "_integrity",
        "_settings",
        "_state",
        "_tick",
        "_withdrawn",
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
        self._withdrawn: tuple[str, ...] = ()
        self._ceiling = FailSafeState.NOMINAL
        self._decay: dict[SensorModality, float] = {}

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
        self._withdrawn = self._withdrawn_capabilities(frame_health=frame_health)
        self._ceiling = self._advanced_ceiling(frame_health=frame_health)
        self._advance_decay(frame_health=frame_health)
        self._state = self._next_state()
        self._tick = tick
        if self._state is FailSafeState.HALT:
            self._human_intervention_requested = True
        return self.snapshot

    def _advanced_ceiling(
        self, *, frame_health: Sequence[tuple[SensorModality, StreamHealth]]
    ) -> FailSafeState:
        """Return the worst posture the current sensor health may justify.

        **The level was being thrown away.** L1 distinguishes four health
        values and, until 15 August, this machine read one bit of them: anything
        that was not ``HEALTHY`` escalated identically, so a camera arriving
        *late* stopped the vehicle exactly as a camera that was *gone* (E-134).
        That is OD-18's shape one level in -- one response for situations the
        system had already gone to the trouble of telling apart.

        **Why a ceiling is the right instrument here and was the wrong one for
        modalities.** ADR-0029 rejected a per-*modality* severity ceiling
        because modality identity is not a severity: a ceiling says *how far*,
        and *which sensor* is not a question about how far. ``StreamHealth`` is
        different. It **is** a severity -- literally how far past the staleness
        budget a stream has fallen -- so mapping it onto how far the posture may
        escalate keeps the vocabulary honest. No weight is invented and nothing
        needs defending beyond *a late reading is less bad than no reading*.

        **It is a high-water mark, not an instantaneous read, and that is a bug
        this method would otherwise have.** The ceiling caps a counter that
        persists across ticks. Recomputing it from the current frame alone would
        mean a modality that recovered lifted the cap while the counter was
        still elevated -- so a vehicle held at LIMP by a stale camera would
        **HALT at the moment the camera came back**, punished for recovering.
        So the ceiling only rises while a fault persists, and resets when the
        counter reaches its floor, which is the point at which it stops
        mattering anyway.

        Args:
            frame_health: Per-modality health for this tick.

        Returns:
            The current ceiling. ``NOMINAL`` when the counter has fully
            recovered, which caps nothing because the band is ``NOMINAL`` there
            too.
        """
        ceiling = self._settings.integrity_ceiling
        if not ceiling:
            # Undeclared means uncapped, which is the behaviour that shipped
            # before this field existed and the most conservative reading of it.
            return FailSafeState.HALT

        critical = self._settings.critical_modalities
        worst = FailSafeState.NOMINAL
        for modality, health in frame_health:
            if health is StreamHealth.HEALTHY or modality not in critical:
                continue
            for level, permitted in ceiling:
                if level is health:
                    worst = _worse(worst, permitted)
                    break
            else:
                # A level the deployment did not name is uncapped. Silence in a
                # safety file is not permission to be lenient.
                worst = FailSafeState.HALT

        if worst is FailSafeState.NOMINAL and self._integrity <= _COUNTER_FLOOR:
            return FailSafeState.NOMINAL
        return _worse(self._ceiling, worst)

    def _advance_decay(
        self, *, frame_health: Sequence[tuple[SensorModality, StreamHealth]]
    ) -> None:
        """Update each modality's decayed unhealth fraction.

        **The counter cannot see an intermittent fault, and this is the
        measurement that says so.** The integrity counter moves ``+1`` on an
        unhealthy frame and ``-1`` on a healthy one, so *any* duty cycle at or
        below 50% nets to zero and never escalates -- however long it runs.
        Measured over a full minute at 20 Hz: a camera dark on alternate frames
        spent **600 of 1,200 ticks absent** and held ``NOMINAL`` with the
        counter peaking at **1**; dark 3 frames in 13, it held ``NOMINAL`` with
        the counter peaking at 3 (E-135). A sensor dropping a quarter of its
        frames is failing, and the machine reported perfect health.

        The counter is not wrong -- it answers *"am I in trouble now?"* and the
        answer really is no. It simply cannot answer *"is this sensor dying?"*,
        because it is memoryless by design: that is the same property that makes
        recovery automatic, and giving it up would cost more than it bought.

        So this is a **separate, per-modality** exponential average of the
        unhealth indicator, which converges to exactly the duty cycle the
        counter cancels out. It is deliberately not a third counter: the
        quantity it reports is a **fraction of recent frames**, which has units
        and a meaning a maintenance engineer can act on, rather than an
        invented weight of the kind ADR-0028 and ADR-0029 both refused.

        **It changes no posture, issues no veto, and gates no command.** A
        slowly decaying sensor is a *service* condition, not an emergency, and a
        vehicle that stopped for maintenance would be the nuisance stop OD-18
        removed, re-introduced through a different door. It reports; the fleet
        decides. This is the project's standing rule that no mechanism gets
        authority until it has run with none.

        Args:
            frame_health: Per-modality health for this tick. A modality absent
                from the map is not updated rather than treated as healthy: no
                observation is not evidence of health, and decaying it toward
                zero would let a stream that stopped being *reported* look like
                one that recovered.
        """
        # Every modality, not only the critical ones. Criticality decides what
        # may change the posture; nothing about it makes a non-critical sensor's
        # decay less worth knowing, and a fleet operator servicing a camera
        # cares whether it is dying regardless of what it is allowed to stop.
        alpha = 2.0 / (self._settings.decay_window_ticks + 1.0)
        for modality, health in frame_health:
            unhealthy = 0.0 if health is StreamHealth.HEALTHY else 1.0
            previous = self._decay.get(modality, 0.0)
            self._decay[modality] = previous + alpha * (unhealthy - previous)

    def _withdrawn_capabilities(
        self, *, frame_health: Sequence[tuple[SensorModality, StreamHealth]]
    ) -> tuple[str, ...]:
        """Return the autonomy functions this frame's sensor health withdraws.

        **The second axis.** Everything else in this machine answers *how bad is
        this getting* and answers it with a severity level. This answers *what is
        broken* and answers it with a set of lost functions. ADR-0029 is the
        record of why one integer could not do both: before it, losing a camera
        either stopped the vehicle or did nothing, and could not do the one
        thing a camera failure actually calls for -- stop offering lane changes
        and keep driving.

        **Deliberately not filtered by ``critical_modalities``, and that is the
        whole point.** The critical set decides whether a modality may change the
        *posture*. This decides which *functions* it carries. A camera can be
        non-critical -- never a reason to slow down -- and still be the only
        thing a lane change depends on. Filtering here would re-couple the two
        axes and reproduce OD-18 one level down.

        **No counter, no hysteresis, and that asymmetry with the two counters is
        deliberate.** A counter exists to distinguish a glitch from a fault
        because escalating the *posture* on one bad frame would spend the
        vehicle's life in DEGRADED. Withdrawing a capability has no comparable
        cost: the vehicle keeps driving and declines one function. Paying a
        detection delay to avoid a cheap action would be the wrong trade, and it
        would mean a lane change could be *granted* during the ticks a camera
        had already gone dark.

        **Restoration is symmetric today and probably should not stay that
        way.** A modality that flaps between healthy and stale will flap the
        capability with it. The fix is a restore debounce -- withdraw at once,
        restore after N clean ticks, because the two errors do not cost the same
        -- but N is an operating point and no flap rate has been measured on this
        platform. Inventing one would be the same unfalsifiable number that got
        weighted counters rejected in ADR-0028. The field is not added until a
        measurement asks for it.

        Args:
            frame_health: Per-modality health for this tick. Empty means the
                caller has no sensor bus; nothing is withdrawn, which is what a
                caller with no sensors means and what every test written against
                the verdict half of this machine relies on.

        Returns:
            The withdrawn capability names in name order, so that two runs with
            the same health produce byte-identical audit rows. The order comes
            from the settings, which sort the pairs at load precisely so that
            nothing downstream has to re-sort to be deterministic.
        """
        unhealthy = {
            modality for modality, health in frame_health if health is not StreamHealth.HEALTHY
        }
        if not unhealthy:
            return ()
        return tuple(
            name
            for name, required in self._settings.capabilities
            if unhealthy.intersection(required)
        )

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

        **Only the modalities the deployment calls critical, and a quorum of
        those.** Two decisions, taken four days apart, both because the first
        version of this line was too blunt.

        *Which modalities count* -- ADR-0028. This counted **every** modality
        until 11 August, so a camera failure halted the vehicle exactly as an
        IMU failure did, measured, even though the estimator does not read the
        camera. A nuisance stop caused by a component that was not contributing.
        ``critical_modalities`` is the deployment's declaration of which sensors
        the safety argument depends on; a modality outside it is still
        **recorded** in the frame health and every audit record, and simply does
        not move this counter.

        *How many may fail* -- ADR-0027, and this line is the successor
        ADR-0024 That record said: *"any modality, not a quorum ... when
        redundancy exists this is the line that should become a vote, and it
        needs its own decision record when it does."* Redundancy arrived with
        ADR-0026 and the prediction came true immediately: one faulted channel
        of three HALTed a vehicle driving at 0.042 m on the other two (E-116).

        So the counter rises when the number of unhealthy modalities **exceeds
        what the deployment has declared it can absorb**, and
        ``integrity_tolerated_faults`` is that declaration. At **zero** -- the
        value every shipped profile sets, and the only honest one without
        redundancy -- this is bit-identical to counting "any modality", because
        one unhealthy channel already exceeds zero.

        **The threshold is configuration and not a constant on purpose.** How
        many lying channels a vehicle can absorb is a property of *its sensor
        set*, which is exactly the kind of platform knowledge NFR5 keeps out of
        the layers. L8 counts; the deployment declares. Raising it above zero is
        a claim that something excludes the liar from the fusion, and it belongs
        in a file a safety engineer signs (ADR-0027).

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
        critical = self._settings.critical_modalities
        unhealthy = sum(
            1
            for modality, health in frame_health
            if health is not StreamHealth.HEALTHY and modality in critical
        )
        if unhealthy <= self._settings.integrity_tolerated_faults:
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
        if self._counter >= settings.ood_threshold_halt:
            return FailSafeState.HALT
        if (
            self._integrity_band(
                degraded=settings.integrity_threshold_degraded,
                limp=settings.integrity_threshold_limp,
            )
            is FailSafeState.HALT
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
            self._integrity_band(
                degraded=settings.integrity_threshold_degraded,
                limp=settings.integrity_threshold_limp,
            ),
        )

    def _integrity_band(self, *, degraded: int, limp: int) -> FailSafeState:
        """Return the integrity counter's band, capped at what the health allows.

        The one place the sensor-integrity counter is turned into a posture, so
        it is the one place the ceiling has to be applied. Splitting it out of
        :meth:`_escalated_state` is not tidying: the counter reaches a posture
        from **three** sites -- escalation, de-escalation, and the HALT check
        that short-circuits both -- and a cap applied at two of them would be a
        fail-safe that escalated past its own ceiling on one path.

        Args:
            degraded: The counter value at or above which DEGRADED applies.
            limp: The counter value at or above which LIMP applies.

        Returns:
            The band, never more severe than the current ceiling.
        """
        if self._integrity >= self._settings.integrity_threshold_halt:
            band = FailSafeState.HALT
        else:
            band = _band(self._integrity, degraded=degraded, limp=limp)
        ceiling = self._ceiling
        return band if band.severity_rank <= ceiling.severity_rank else ceiling

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
            self._integrity_band(
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
            withdrawn_capabilities=self._withdrawn,
            sensor_decay=self.sensor_decay,
            sensors_needing_service=self.sensors_needing_service,
            # Reported beside `lane_change_permitted`, not folded into it. L8
            # would have to know that the string "lane_change" names the
            # capability behind that field, and a layer that knows what a lane
            # is has lost NFR5. Composition -- posture AND capability, an
            # intersection that can only subtract -- belongs to the domain
            # adapter that reads the names. OD-11 wall 4 is where the automotive
            # field itself goes, and the two merge there (ADR-0029).
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
    def withdrawn_capabilities(self) -> tuple[str, ...]:
        """Return the capabilities the last frame's sensor health withdrew."""
        return self._withdrawn

    @property
    def sensor_decay(self) -> tuple[tuple[str, float], ...]:
        """Return each modality's decayed unhealth fraction, sorted by modality."""
        return tuple(sorted((modality.value, value) for modality, value in self._decay.items()))

    @property
    def sensors_needing_service(self) -> tuple[str, ...]:
        """Return the modalities whose decay has crossed the service threshold.

        Empty when no threshold is declared. Reporting every sensor as needing
        service, or none, are both wrong answers to a question the deployment
        has not asked -- so the mechanism stays silent until it is.

        Returns:
            The modality names, sorted, or empty.
        """
        threshold = self._settings.decay_service_threshold
        if threshold is None:
            return ()
        return tuple(
            sorted(modality.value for modality, value in self._decay.items() if value >= threshold)
        )

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

        **The withdrawn capabilities are deliberately not cleared.** A reset
        clears what the *machine* decided; it cannot clear what the *sensors*
        reported. The counters are accumulated state and belong to the machine,
        so zeroing them is the machine forgetting its own history. The withdrawn
        set is not state at all -- it is a pure function of the last frame's
        health -- and setting it empty here would assert that every sensor is
        healthy, which a reset has no way to know and no authority to say. An
        operator who resets a vehicle whose camera is still dark should still
        find lane changes withdrawn, and will.

        **The decay history is not cleared either, and for a stronger reason.**
        A reset that zeroed it would let an intermittently failing sensor be
        forgiven by the very act of dealing with the trouble it caused: halt,
        reset, halt, reset, and the record shows a healthy fleet. Decay measures
        the sensor's history, and an operator resetting a vehicle does not make
        the camera younger.

        **The ceiling *is* cleared**, because it is neither of those things --
        it is a high-water mark held only to cap a counter that is about to be
        zeroed, and a ceiling outliving its counter would cap a fresh one.
        """
        self._state = FailSafeState.NOMINAL
        self._counter = _COUNTER_FLOOR
        self._integrity = _COUNTER_FLOOR
        self._ceiling = FailSafeState.NOMINAL
        self._human_intervention_requested = False
