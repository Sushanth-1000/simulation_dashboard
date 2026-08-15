"""Does the *kind* of sensor fault change how far the posture escalates?

The gap these tests close
--------------------------
OD-20. L1 distinguishes four health values and, until 15 August 2026, the
fail-safe machine read one bit of them -- `health is not HEALTHY` -- in both
places it consulted them. Measured, holding a camera at each level for three
seconds on the shipped profile (E-134):

===============  ========  =====
camera health    posture   phi
===============  ========  =====
``DEGRADED``     HALT      40
``FAULTED``      HALT      40
``ABSENT``       HALT      40
===============  ========  =====

A camera arriving *late* stopped the vehicle exactly as a camera that was
*gone*. That is OD-18's shape one level in: one response for situations the
system had already gone to the trouble of telling apart.

Why a ceiling here, having rejected one for modalities
--------------------------------------------------------
ADR-0029 rejected a per-*modality* severity ceiling on the grounds that a
ceiling says *how far* and *which sensor* is not a question about how far.
``StreamHealth`` is not like that. It **is** a severity -- how far past the
staleness budget a stream has fallen -- so mapping it to how far the posture may
escalate invents no weight and need only defend *a late reading is less bad than
no reading*. See ADR-0030.

The bug these tests exist to keep fixed
-----------------------------------------
:func:`test_a_recovering_sensor_does_not_lift_the_cap_and_halt_the_vehicle`.
The ceiling caps a counter that persists across ticks, so computing it from the
current frame alone would let a modality that *recovered* lift the cap while the
counter was still high -- halting the vehicle at the moment the sensor came
back. The ceiling is therefore a high-water mark that resets with the counter,
and that test is the reason.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from astra.config.schema import FailSafeSettings
from astra.contracts.assurance import GateVerdict, SafetyVerdict
from astra.kernel.enums import FailSafeState, GateId, SensorModality, StreamHealth, Verdict
from astra.kernel.identifiers import TickId
from astra.layers.l8_failsafe.machine import FailSafeStateMachine

ALL_MODALITIES = (
    SensorModality.CAMERA,
    SensorModality.LIDAR,
    SensorModality.IMU,
    SensorModality.GPS,
    SensorModality.RADAR,
)

CEILING = (
    (StreamHealth.DEGRADED, FailSafeState.LIMP),
    (StreamHealth.FAULTED, FailSafeState.HALT),
    (StreamHealth.ABSENT, FailSafeState.HALT),
)


def settings(
    *,
    ceiling: tuple[tuple[StreamHealth, FailSafeState], ...] = CEILING,
    critical: tuple[SensorModality, ...] = ALL_MODALITIES,
) -> FailSafeSettings:
    """Return fail-safe settings at the simulation profile's operating point."""
    return FailSafeSettings(
        ood_threshold_degraded=10,
        ood_threshold_limp=30,
        ood_threshold_halt=100,
        degraded_speed_cap_kmh=60.0,
        limp_speed_cap_kmh=20.0,
        integrity_threshold_degraded=5,
        integrity_threshold_limp=15,
        integrity_threshold_halt=40,
        integrity_tolerated_faults=0,
        critical_modalities=critical,
        integrity_ceiling=ceiling,
    )


def passing(tick: int = 0) -> SafetyVerdict:
    """Return a verdict every gate passed."""
    return SafetyVerdict(
        tick=TickId(tick),
        gate_verdicts=(
            GateVerdict(
                tick=TickId(tick),
                gate=GateId.STATISTICAL,
                verdict=Verdict.PASS,
                reason_code="NOMINAL",
            ),
        ),
    )


def blocking(tick: int = 0) -> SafetyVerdict:
    """Return a blocking verdict, to drive the OOD counter instead."""
    return SafetyVerdict(
        tick=TickId(tick),
        gate_verdicts=(
            GateVerdict(
                tick=TickId(tick),
                gate=GateId.STATISTICAL,
                verdict=Verdict.VETO,
                reason_code="OUT_OF_DISTRIBUTION",
            ),
        ),
    )


def health(
    level: StreamHealth, *, on: SensorModality = SensorModality.CAMERA
) -> tuple[tuple[SensorModality, StreamHealth], ...]:
    """Return a frame-health map with one modality at ``level``."""
    return tuple(
        (modality, level if modality is on else StreamHealth.HEALTHY) for modality in ALL_MODALITIES
    )


def drive(
    machine: FailSafeStateMachine,
    frame_health: tuple[tuple[SensorModality, StreamHealth], ...],
    *,
    ticks: int,
    start: int = 0,
    verdict: object = None,
) -> None:
    """Advance the machine for ``ticks`` ticks on one health map."""
    for tick in range(start, start + ticks):
        machine.observe(
            tick=TickId(tick),
            verdict=passing(tick) if verdict is None else verdict(tick),  # type: ignore[operator]
            frame_health=frame_health,
        )


# --------------------------------------------------------------------------- #
# The behaviour the one-bit read could not express
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (StreamHealth.DEGRADED, FailSafeState.LIMP),
        (StreamHealth.FAULTED, FailSafeState.HALT),
        (StreamHealth.ABSENT, FailSafeState.HALT),
    ],
)
def test_the_posture_stops_where_the_health_level_says_it_may(
    level: StreamHealth, expected: FailSafeState
) -> None:
    """A stale stream caps at LIMP; a gone one still halts.

    Before ADR-0030 all three rows read HALT. The DEGRADED row is the whole
    point: the vehicle slows to the limp cap and keeps driving on a camera that
    is merely late.
    """
    machine = FailSafeStateMachine(settings())
    drive(machine, health(level), ticks=120)

    posture: FailSafeState = machine.state
    assert posture is expected
    assert machine.integrity_counter == 40, "the counter is untouched; only the posture is capped"


def test_a_recovering_sensor_does_not_lift_the_cap_and_halt_the_vehicle() -> None:
    """The bug a per-frame ceiling would have. Read the module docstring.

    A camera holds DEGRADED long enough to drive the counter past the HALT
    threshold, capped at LIMP. It then recovers. If the ceiling were recomputed
    from the current frame it would lift -- no modality is unhealthy -- and the
    still-high counter would take the vehicle straight to HALT, punishing it for
    the sensor coming back.
    """
    machine = FailSafeStateMachine(settings())
    drive(machine, health(StreamHealth.DEGRADED), ticks=120)
    capped: FailSafeState = machine.state
    assert capped is FailSafeState.LIMP
    assert machine.integrity_counter == 40

    drive(machine, health(StreamHealth.HEALTHY), ticks=1, start=120)

    recovered: FailSafeState = machine.state
    assert recovered is not FailSafeState.HALT
    assert machine.integrity_counter == 39


def test_a_worsening_fault_raises_the_cap_at_once() -> None:
    """A stale camera that goes dark halts immediately, on the counter it built.

    The high-water mark must not become a *low*-water mark: holding the milder
    ceiling after the fault worsened would be the mirror of the bug above.
    """
    machine = FailSafeStateMachine(settings())
    drive(machine, health(StreamHealth.DEGRADED), ticks=120)
    capped: FailSafeState = machine.state
    assert capped is FailSafeState.LIMP

    drive(machine, health(StreamHealth.ABSENT), ticks=1, start=120)
    worsened: FailSafeState = machine.state
    assert worsened is FailSafeState.HALT


def test_the_cap_survives_the_full_recovery_and_then_clears() -> None:
    """Once the counter reaches its floor the ceiling stops applying."""
    machine = FailSafeStateMachine(settings())
    drive(machine, health(StreamHealth.DEGRADED), ticks=120)
    drive(machine, health(StreamHealth.HEALTHY), ticks=60, start=120)

    settled: FailSafeState = machine.state
    assert settled is FailSafeState.NOMINAL
    assert machine.integrity_counter == 0

    drive(machine, health(StreamHealth.ABSENT), ticks=60, start=180)
    assert machine.state is FailSafeState.HALT, "a fresh fault escalates on a fresh ceiling"


# --------------------------------------------------------------------------- #
# Silence is not leniency
# --------------------------------------------------------------------------- #


def test_declaring_no_ceiling_reproduces_the_previous_behaviour() -> None:
    """An undeclared ceiling caps nothing, which is the system as it shipped."""
    for level in (StreamHealth.DEGRADED, StreamHealth.FAULTED, StreamHealth.ABSENT):
        machine = FailSafeStateMachine(settings(ceiling=()))
        drive(machine, health(level), ticks=120)
        assert machine.state is FailSafeState.HALT, level


def test_a_level_the_deployment_did_not_name_is_uncapped() -> None:
    """Omitting a level must not quietly make it the mildest one.

    A file that names DEGRADED and forgets ABSENT is far more likely to be
    incomplete than to intend that a vanished sensor never escalates.
    """
    partial = ((StreamHealth.DEGRADED, FailSafeState.LIMP),)
    machine = FailSafeStateMachine(settings(ceiling=partial))
    drive(machine, health(StreamHealth.ABSENT), ticks=120)
    assert machine.state is FailSafeState.HALT


def test_a_non_critical_modality_does_not_raise_the_ceiling() -> None:
    """The ceiling caps the integrity counter, which only critical modalities move.

    A ceiling raised by a modality that cannot move the counter would cap
    nothing on the way up and could only ever *raise* a cap set by a sensor that
    does count.
    """
    machine = FailSafeStateMachine(
        settings(critical=(SensorModality.IMU,)),
    )
    drive(machine, health(StreamHealth.ABSENT), ticks=120)

    posture: FailSafeState = machine.state
    assert posture is FailSafeState.NOMINAL
    assert machine.integrity_counter == 0


def test_the_ood_counter_is_not_capped_by_a_sensor_ceiling() -> None:
    """A ceiling on sensor health must not limit escalation on refusal.

    The two counters answer unrelated questions, and a cap derived from one
    silencing the other would be the coupling ADR-0024 exists to prevent.
    """
    machine = FailSafeStateMachine(settings())
    for tick in range(200):
        machine.observe(
            tick=TickId(tick),
            verdict=blocking(tick),
            frame_health=health(StreamHealth.DEGRADED),
        )
    assert machine.state is FailSafeState.HALT


def test_reset_clears_the_ceiling() -> None:
    """Unlike the withdrawn set and the decay, the ceiling is machine state.

    It is a high-water mark held only to cap a counter that reset zeroes, so a
    ceiling outliving its counter would cap a fresh one.
    """
    machine = FailSafeStateMachine(settings())
    drive(machine, health(StreamHealth.DEGRADED), ticks=120)
    machine.reset()

    drive(machine, health(StreamHealth.ABSENT), ticks=120, start=120)
    assert machine.state is FailSafeState.HALT


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_naming_healthy_in_the_ceiling_is_refused() -> None:
    """HEALTHY is not a fault; a ceiling for it would govern nothing."""
    with pytest.raises(ValidationError, match="must not name HEALTHY"):
        settings(ceiling=((StreamHealth.HEALTHY, FailSafeState.LIMP),))


def test_a_ceiling_that_falls_as_health_worsens_is_refused() -> None:
    """A gone sensor capped below a stale one says no reading is safer than a late one."""
    with pytest.raises(ValidationError, match="falls as health worsens"):
        settings(
            ceiling=(
                (StreamHealth.DEGRADED, FailSafeState.HALT),
                (StreamHealth.ABSENT, FailSafeState.LIMP),
            )
        )


def test_the_ceiling_is_ordered_by_severity_whatever_the_file_says() -> None:
    """Declaration order must not reach the config hash, or two identical profiles differ."""
    declared = FailSafeSettings.model_validate(
        {
            **settings().model_dump(exclude={"integrity_ceiling"}),
            "integrity_ceiling": {"ABSENT": "HALT", "DEGRADED": "LIMP"},
        }
    )
    assert [level for level, _ in declared.integrity_ceiling] == [
        StreamHealth.DEGRADED,
        StreamHealth.ABSENT,
    ]
