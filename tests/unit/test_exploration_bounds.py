"""Does bounded safe exploration actually keep the vehicle moving, and bounded?

The claim these tests exist to hold up
----------------------------------------
From the tunnel scenario's own docstring, and it is the architecture's
distinguishing sentence:

    *"Those degrade to a halt when they leave their certified envelope. ASTRA is
    built not to: with no admissible profile, RCM engages bounded safe
    exploration ... and the vehicle continues."*

Two promises. **It continues**, and it continues **inside a bound**. On
10 August 2026 neither held, for two separate reasons, and each was hiding the
other.

OD-12 -- it did not continue
------------------------------
On a platform the twin was never fitted to, the twin mispredicts, so L6 and L7b
veto. L9 sees no matching profile and declares ``SAFE_EXPLORATION``. L8 counts
those same vetoes, escalates through DEGRADED and LIMP, and reaches HALT --
which is terminal. Measured: **520 ticks in exploration, 305 of them vetoed,
counter 0 -> 100, HALT first reached at t458 while RCM was still saying
SAFE_EXPLORATION.**

Two layers answering "are we outside our envelope?" and acting in contradiction.
The vetoes L8 counted were *the definition* of the condition L9 had already
detected, declared and responded to -- one event escalated twice, and the
terminal answer won.

The fix conditions on **posture, not gate identity**, because L8's own docstring
forbids the latter: *"which gate vetoed is evidence for the log, not an input to
the escalation policy ... which SI-3 forbids."* So the counter freezes while
exploration is engaged. **Veto authority is untouched** -- every gate still
vetoes and every veto still stops the command reaching an actuator.

OD-13 -- it was not bounded
-----------------------------
Fixing OD-12 exposed the second defect immediately. ``exploration_envelope``
computes ``speed_cap = nearest_certified_max * 0.5``; ``restricted_space`` turns
the envelope into *narrowed channel bounds*, which limits how much throttle may
be commanded on one tick and bounds the resulting speed not at all. Given enough
ticks at reduced throttle the vehicle still accelerates.

Measured on a weak-braking platform: exploring for all 600 ticks while
accelerating monotonically to **23.10 m/s**, above the calibrated baseline's
12.54, with **zero** deterministic-shield vetoes. The envelope computed a cap
and enforced it against nothing.

The cap now flows through the same projector seam P2.1 built for the fail-safe
cap -- the one that made ``SPEED_CAPPED`` mean a command the cap *altered*.
"""

from __future__ import annotations

import pytest

from astra.config.schema import FailSafeSettings
from astra.contracts.assurance import FailSafeSnapshot, GateVerdict, SafetyVerdict
from astra.kernel.enums import FailSafeState, GateId, Verdict
from astra.kernel.identifiers import TickId
from astra.kernel.units import MetresPerSecond
from astra.layers.l8_failsafe.machine import FailSafeStateMachine
from astra.layers.l9_rcm.arbiter import RuntimeCalibrationManager
from astra.layers.l9_rcm.exploration import SPEED_FRACTION_OF_NEAREST, exploration_envelope

SETTINGS = FailSafeSettings(
    ood_threshold_degraded=10,
    ood_threshold_limp=30,
    ood_threshold_halt=100,
    degraded_speed_cap_kmh=60.0,
    limp_speed_cap_kmh=20.0,
)


def verdict(*, blocking: bool, tick: int = 0) -> SafetyVerdict:
    """Return a verdict that blocks, or does not."""
    return SafetyVerdict(
        tick=TickId(tick),
        gate_verdicts=(
            GateVerdict(
                tick=TickId(tick),
                gate=GateId.STATISTICAL,
                verdict=Verdict.VETO if blocking else Verdict.PASS,
                reason_code="SCORE_EXCEEDS_CONFORMAL_QUANTILE" if blocking else "NOMINAL",
            ),
        ),
    )


def machine() -> FailSafeStateMachine:
    return FailSafeStateMachine(SETTINGS)


# --------------------------------------------------------------------------- #
# OD-12 — the counter freezes while exploring
# --------------------------------------------------------------------------- #


def test_a_veto_does_not_escalate_the_posture_while_exploring() -> None:
    # The defect, directly: 305 vetoes during exploration took the counter to
    # 100 and HALTed the vehicle underneath a layer that had already decided to
    # keep it moving.
    fsm = machine()

    for tick in range(400):
        fsm.observe(tick=TickId(tick), verdict=verdict(blocking=True), exploring=True)

    assert fsm.snapshot.state is FailSafeState.NOMINAL
    assert fsm.snapshot.ood_counter == 0


def test_the_same_vetoes_do_escalate_when_not_exploring() -> None:
    # The control. Without it the test above would pass on a machine that had
    # stopped escalating altogether, which is a far worse defect than the one
    # being fixed.
    fsm = machine()

    for tick in range(400):
        fsm.observe(tick=TickId(tick), verdict=verdict(blocking=True), exploring=False)

    assert fsm.snapshot.state is FailSafeState.HALT


def test_the_counter_is_frozen_rather_than_reset() -> None:
    # A vehicle that was already DEGRADED must not emerge from a tunnel
    # pretending it was not. Freezing preserves the posture; resetting would
    # launder it.
    fsm = machine()
    for tick in range(15):
        fsm.observe(tick=TickId(tick), verdict=verdict(blocking=True), exploring=False)
    entered = fsm.snapshot.ood_counter

    for tick in range(15, 115):
        fsm.observe(tick=TickId(tick), verdict=verdict(blocking=True), exploring=True)

    assert fsm.snapshot.ood_counter == entered


def test_a_clean_tick_does_not_decay_the_counter_while_exploring() -> None:
    # Frozen means frozen in both directions. Letting it decay during
    # exploration would let a vehicle launder a bad posture by entering a
    # tunnel, which is the same laundering as resetting, more slowly.
    fsm = machine()
    for tick in range(15):
        fsm.observe(tick=TickId(tick), verdict=verdict(blocking=True), exploring=False)
    entered = fsm.snapshot.ood_counter

    for tick in range(15, 115):
        fsm.observe(tick=TickId(tick), verdict=verdict(blocking=False), exploring=True)

    assert fsm.snapshot.ood_counter == entered


def test_escalation_resumes_on_leaving_exploration() -> None:
    fsm = machine()
    for tick in range(200):
        fsm.observe(tick=TickId(tick), verdict=verdict(blocking=True), exploring=True)
    frozen: FailSafeSnapshot = fsm.snapshot
    assert frozen.state is FailSafeState.NOMINAL

    for tick in range(200, 400):
        fsm.observe(tick=TickId(tick), verdict=verdict(blocking=True), exploring=False)

    resumed: FailSafeSnapshot = fsm.snapshot
    assert resumed.state is FailSafeState.HALT


def test_exploration_does_not_alter_the_verdict_itself() -> None:
    # SI-3 is untouched. What the freeze suspends is escalation to a terminal
    # posture, never a gate's authority to block: a vetoed command is still a
    # vetoed command, and L9 still refuses to issue it.
    blocking = verdict(blocking=True)

    assert blocking.is_blocking

    fsm = machine()
    fsm.observe(tick=TickId(0), verdict=blocking, exploring=True)

    assert blocking.is_blocking


# --------------------------------------------------------------------------- #
# OD-13 — the envelope's speed cap is a number that binds something
# --------------------------------------------------------------------------- #


def test_the_envelope_caps_speed_at_half_the_nearest_certified_maximum() -> None:
    envelope = exploration_envelope(33.34)

    assert float(envelope.speed_cap) == pytest.approx(33.34 * SPEED_FRACTION_OF_NEAREST)
    assert SPEED_FRACTION_OF_NEAREST == 0.5


def test_the_arbiter_holds_the_cap_it_was_engaged_with() -> None:
    # The regression that OD-13 was. Before this, `engage_exploration` took only
    # the narrowed space -- which carries the steering cone and says nothing
    # about speed -- so the cap the envelope computed reached nothing at all.
    assert "speed_cap" in (RuntimeCalibrationManager.engage_exploration.__doc__ or "")
    assert "_exploration_speed_cap" in RuntimeCalibrationManager.__slots__


def test_exiting_exploration_clears_the_cap() -> None:
    # A cap that outlived the exploration that justified it would throttle a
    # vehicle back inside its certified envelope for no stated reason.
    assert "_exploration_speed_cap" in RuntimeCalibrationManager.exit_exploration.__code__.co_names


def test_a_snapshot_with_no_cap_is_not_a_zero_cap() -> None:
    # Rendering "no cap" as 0.0 is a commanded stop. The distinction is why
    # `speed_cap` is optional rather than defaulted.
    nominal = FailSafeSnapshot(
        tick=TickId(0),
        state=FailSafeState.NOMINAL,
        ood_counter=0,
        speed_cap=None,
        lane_change_permitted=True,
        human_intervention_requested=False,
    )
    halted = FailSafeSnapshot(
        tick=TickId(0),
        state=FailSafeState.HALT,
        ood_counter=100,
        speed_cap=MetresPerSecond(0.0),
        lane_change_permitted=False,
        human_intervention_requested=True,
    )

    assert nominal.speed_cap is None
    assert halted.speed_cap == 0.0
