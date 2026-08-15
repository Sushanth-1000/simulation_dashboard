"""Can the machine see a sensor that is dying rather than dead?

The defect these tests close
------------------------------
OD-21. The integrity counter moves ``+1`` on an unhealthy frame and ``-1`` on a
healthy one, so **any duty cycle at or below 50% nets to zero and never
escalates, however long it runs.** Measured over a full minute at 20 Hz on the
shipped profile (E-135):

=====================  ==========  ==========  ==============
pattern                ticks dark  peak ``phi`` worst posture
=====================  ==========  ==========  ==============
1 dark / 1 clean       600 / 1200  1           NOMINAL
3 dark / 3 clean       600 / 1200  3           NOMINAL
3 dark / 10 clean      279 / 1200  3           NOMINAL
20 dark / 20 clean     600 / 1200  20          LIMP
=====================  ==========  ==========  ==============

A camera dropping every other frame for a minute reported perfect health. A
camera dropping a quarter of its frames reported perfect health. Both are
failing hardware.

**The counter is not wrong.** It answers *"am I in trouble now?"* and the answer
really is no -- the estimator got a fresh reading a tick ago. It is memoryless
by design, which is the same property that makes recovery automatic and bounded,
and giving that up would cost more than it bought. So the fix is not to change
the counter; it is to measure the quantity the counter cancels out.

What decay is, and what it deliberately is not
------------------------------------------------
A per-modality exponential average of the unhealth indicator, which converges to
exactly the duty cycle. It reports a **fraction of recent frames**, which has
units and a meaning a maintenance engineer can act on -- unlike the invented
weights ADR-0028 and ADR-0029 both refused.

**It drives nothing.** No posture, no veto, no command, no gate. A decaying
sensor is a service condition, and a vehicle that stopped for maintenance would
be the nuisance stop OD-18 removed arriving through a different door.
:func:`test_decay_changes_no_posture` is the test that pins it, and it should
outlive any later decision to give the mechanism authority. See ADR-0031.
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


def settings(
    *,
    window: int = 200,
    threshold: float | None = None,
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
        decay_window_ticks=window,
        decay_service_threshold=threshold,
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


def health(
    *, dark: bool, on: SensorModality = SensorModality.CAMERA
) -> tuple[tuple[SensorModality, StreamHealth], ...]:
    """Return a frame-health map with one modality absent or not."""
    return tuple(
        (
            modality,
            StreamHealth.ABSENT if (dark and modality is on) else StreamHealth.HEALTHY,
        )
        for modality in ALL_MODALITIES
    )


def intermittent(machine: FailSafeStateMachine, *, on: int, off: int, ticks: int = 1200) -> int:
    """Drive an alternating fault and return the peak integrity counter."""
    peak = 0
    for tick in range(ticks):
        dark = (tick % (on + off)) < on
        machine.observe(tick=TickId(tick), verdict=passing(tick), frame_health=health(dark=dark))
        peak = max(peak, machine.integrity_counter)
    return peak


def decay_of(machine: FailSafeStateMachine, modality: SensorModality) -> float:
    """Return one modality's decayed unhealth fraction."""
    return dict(machine.sensor_decay)[modality.value]


# --------------------------------------------------------------------------- #
# The blind spot, and that decay fills it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("on", "off", "expected"),
    [(1, 1, 0.5), (3, 3, 0.5), (3, 10, 3 / 13), (10, 10, 0.5), (1, 3, 0.25)],
)
def test_decay_converges_to_the_duty_cycle(on: int, off: int, expected: float) -> None:
    """The number means something: the fraction of recent frames that were unhealthy.

    That is what makes it defensible where a weight would not be. Nobody has to
    accept *"the camera is worth 0.4"*; this says *"this stream missed 23% of
    its frames"*, which is checkable against the sensor.
    """
    machine = FailSafeStateMachine(settings())
    intermittent(machine, on=on, off=off)
    assert decay_of(machine, SensorModality.CAMERA) == pytest.approx(expected, abs=0.03)


def test_the_counter_stays_blind_and_the_decay_does_not() -> None:
    """The whole of OD-21 in one assertion.

    Both halves are asserted deliberately. If a later change made the counter
    escalate here, this test should fail and force someone to argue for it --
    the counter's memorylessness is what makes recovery bounded, and trading it
    away silently would be a worse defect than the one being fixed.
    """
    machine = FailSafeStateMachine(settings())
    peak = intermittent(machine, on=1, off=1)

    assert peak <= 1, "half the frames dark for a minute, and the counter never moves"
    posture: FailSafeState = machine.state
    assert posture is FailSafeState.NOMINAL
    assert decay_of(machine, SensorModality.CAMERA) == pytest.approx(0.5, abs=0.03)


def test_decay_changes_no_posture() -> None:
    """Decay reports; it does not act. This test should outlive any later change.

    A vehicle that stopped for maintenance would be the nuisance stop OD-18
    removed, arriving through a different door.
    """
    machine = FailSafeStateMachine(settings(threshold=0.1))
    intermittent(machine, on=1, off=1)

    assert machine.sensors_needing_service == ("CAMERA",)
    posture: FailSafeState = machine.state
    assert posture is FailSafeState.NOMINAL
    assert machine.integrity_counter <= 1
    assert machine.snapshot.speed_cap is None


# --------------------------------------------------------------------------- #
# What it measures, and for whom
# --------------------------------------------------------------------------- #


def test_decay_is_per_modality() -> None:
    """A dying camera must not make the IMU look ill.

    The integrity counter is aggregate -- one integer for the whole frame -- so
    it cannot attribute. This can, which is what makes it useful to a fleet.
    """
    machine = FailSafeStateMachine(settings())
    intermittent(machine, on=1, off=1, ticks=600)

    assert decay_of(machine, SensorModality.CAMERA) == pytest.approx(0.5, abs=0.03)
    for modality in (SensorModality.IMU, SensorModality.GPS, SensorModality.RADAR):
        assert decay_of(machine, modality) == pytest.approx(0.0, abs=1e-6)


def test_a_non_critical_modality_is_still_tracked() -> None:
    """Criticality governs the posture, not what is worth knowing.

    A fleet operator servicing a camera cares whether it is dying regardless of
    whether it is allowed to stop the vehicle.
    """
    machine = FailSafeStateMachine(settings(critical=(SensorModality.IMU,)))
    intermittent(machine, on=1, off=1)

    assert machine.state is FailSafeState.NOMINAL
    assert decay_of(machine, SensorModality.CAMERA) == pytest.approx(0.5, abs=0.03)


def test_a_modality_missing_from_the_frame_is_not_decayed_toward_health() -> None:
    """No observation is not evidence of health.

    Decaying an unreported modality toward zero would let a stream that stopped
    being *reported* look like one that recovered -- the same inversion this
    register has filed twice.
    """
    machine = FailSafeStateMachine(settings())
    for tick in range(200):
        machine.observe(
            tick=TickId(tick),
            verdict=passing(tick),
            frame_health=((SensorModality.CAMERA, StreamHealth.ABSENT),),
        )
    established = decay_of(machine, SensorModality.CAMERA)
    assert established > 0.5

    for tick in range(200, 400):
        machine.observe(
            tick=TickId(tick),
            verdict=passing(tick),
            frame_health=((SensorModality.IMU, StreamHealth.HEALTHY),),
        )
    assert decay_of(machine, SensorModality.CAMERA) == pytest.approx(established)


def test_a_healthy_run_decays_to_zero() -> None:
    """The ordinary case, so a derivation that only ever rises cannot pass."""
    machine = FailSafeStateMachine(settings(window=20))
    intermittent(machine, on=1, off=0, ticks=200)
    assert decay_of(machine, SensorModality.CAMERA) == pytest.approx(1.0, abs=0.05)

    for tick in range(200, 600):
        machine.observe(tick=TickId(tick), verdict=passing(tick), frame_health=health(dark=False))
    assert decay_of(machine, SensorModality.CAMERA) == pytest.approx(0.0, abs=0.05)


def test_reset_does_not_forgive_a_decaying_sensor() -> None:
    """Otherwise halt-reset-halt-reset would launder a failing sensor clean.

    A reset clears what the machine decided. It does not make the camera
    younger, and a mechanism that let an operator zero the wear record by
    dealing with the trouble it caused would report a healthy fleet forever.
    """
    machine = FailSafeStateMachine(settings())
    intermittent(machine, on=1, off=1, ticks=600)
    before = decay_of(machine, SensorModality.CAMERA)

    machine.reset()

    assert machine.integrity_counter == 0
    assert decay_of(machine, SensorModality.CAMERA) == pytest.approx(before)


def test_the_decay_report_is_sorted() -> None:
    """Two runs with the same history must produce byte-identical audit rows."""
    machine = FailSafeStateMachine(settings())
    intermittent(machine, on=1, off=1, ticks=100)
    names = [modality for modality, _ in machine.sensor_decay]
    assert names == sorted(names)


# --------------------------------------------------------------------------- #
# The service signal, which no shipped profile arms
# --------------------------------------------------------------------------- #


def test_no_threshold_means_no_service_signal() -> None:
    """The shipped default. Decay is measured and reported, and flags nothing.

    What fraction of dropped frames means *service this* is a property of a
    particular sensor on a particular vehicle, and this project has measured no
    such number. Reporting every sensor, or none, are both wrong answers to a
    question the deployment has not asked.
    """
    machine = FailSafeStateMachine(settings())
    intermittent(machine, on=1, off=0, ticks=600)

    assert decay_of(machine, SensorModality.CAMERA) > 0.9
    assert machine.sensors_needing_service == ()


def test_a_declared_threshold_names_the_sensors_that_crossed_it() -> None:
    """And only those, so the signal is attributable."""
    machine = FailSafeStateMachine(settings(threshold=0.2))
    intermittent(machine, on=3, off=10)

    assert machine.sensors_needing_service == ("CAMERA",)


@pytest.mark.parametrize("threshold", [0.0, 1.0, -0.1, 1.5])
def test_a_threshold_outside_the_unit_interval_is_refused(threshold: float) -> None:
    """Zero flags every sensor that ever glitched; one is unreachable by smoothing.

    A threshold nothing can clear and a threshold everything trips are the same
    bug wearing different numbers.
    """
    with pytest.raises(ValidationError, match="fraction strictly"):
        settings(threshold=threshold)
