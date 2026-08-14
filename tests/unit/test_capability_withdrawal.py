"""Does the vehicle respond to *which* sensor failed, or only to how bad it is?

The gap these tests exist to close
-----------------------------------
OD-19. Until 15 August 2026 the fail-safe machine had exactly **two** responses
to a sensor failure, and which one you got depended on a single boolean:

===================  ======================================================
the sensor is...     what happened
===================  ======================================================
critical             the whole ladder -- DEGRADED, LIMP, HALT, identically
                     for every critical sensor
non-critical         nothing at all
===================  ======================================================

``critical_modalities`` (ADR-0028) is a *switch*, not a dial. It can say "this
sensor does not matter". It cannot say "this sensor matters, but only this
much", and it certainly cannot say the useful thing: *lose the camera, stop
offering lane changes, and keep driving.*

Measured before the change, on the shipped profile: a dark camera and a dark IMU
both reached ``HALT`` in 2.0 s, indistinguishable in the posture and in the log
(E-126). One of those is a vehicle that cannot tell where it is. The other is a
vehicle that cannot see lane markings, which is a reason to stop changing lanes
and not a reason to stop.

The fix is not a third counter
-------------------------------
It is a second **axis**. One integer was being asked two questions:

- *how bad is this getting?* -- answered by a severity level, already correct
- *what is broken?* -- answered by a set of lost functions, previously missing

``failsafe.capabilities`` declares what each function requires; a function is
withdrawn while any modality it requires is unhealthy. The two axes compose by
**intersection**, so withdrawal can only ever subtract -- a capability set able
to *grant* what the posture forbids would be a fourth gate with veto-override
authority and SI-3 forbids exactly that. See ADR-0029.

What these tests pin
---------------------
The headline is :func:`test_a_dark_camera_withdraws_lane_changes_and_drives_on`,
which is the behaviour the two-response design could not express at all. The
rest pin the properties that make the mechanism safe rather than merely useful:
that withdrawal never restores, that it is independent of the critical set, that
an empty declaration reproduces the previous behaviour exactly, and that
``reset`` cannot clear an observation it has no authority to make.
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

CAPABILITIES = (
    ("adaptive_cruise", (SensorModality.RADAR, SensorModality.IMU)),
    ("lane_change", (SensorModality.CAMERA, SensorModality.RADAR)),
    ("lane_keeping", (SensorModality.CAMERA,)),
    ("obstacle_avoidance", (SensorModality.LIDAR, SensorModality.RADAR)),
    ("route_following", (SensorModality.GPS,)),
)
"""The shipped profiles' declaration, mirrored so these tests fail when it and
the machine's derivation disagree."""


def settings(
    *,
    critical: tuple[SensorModality, ...] = ALL_MODALITIES,
    capabilities: tuple[tuple[str, tuple[SensorModality, ...]], ...] = CAPABILITIES,
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
        capabilities=capabilities,
    )


def passing(tick: int = 0) -> SafetyVerdict:
    """Return a verdict every gate passed.

    Every test in this file uses it. The verdict stream is clean throughout:
    nothing here is driven by refusal, which is the point -- the capability axis
    reads sensor health and nothing else.
    """
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
    *, dark: SensorModality | None = None, level: StreamHealth = StreamHealth.ABSENT
) -> tuple[tuple[SensorModality, StreamHealth], ...]:
    """Return a frame-health map with at most one modality unhealthy."""
    return tuple(
        (modality, level if modality is dark else StreamHealth.HEALTHY)
        for modality in ALL_MODALITIES
    )


def drive(
    machine: FailSafeStateMachine,
    frame_health: tuple[tuple[SensorModality, StreamHealth], ...],
    *,
    ticks: int,
    start: int = 0,
) -> None:
    """Advance the machine for ``ticks`` ticks on one health map."""
    for tick in range(start, start + ticks):
        machine.observe(tick=TickId(tick), verdict=passing(tick), frame_health=frame_health)


# --------------------------------------------------------------------------- #
# The behaviour the two-response design could not express
# --------------------------------------------------------------------------- #


def test_a_dark_camera_withdraws_lane_changes_and_drives_on() -> None:
    """The headline. This is what OD-19 was opened for.

    A camera the deployment has *not* declared critical goes dark. The vehicle
    holds ``NOMINAL`` -- it does not slow down, it does not stop, it does not ask
    for a handover -- and it stops offering the two functions that need to see
    lane markings.

    Before ADR-0029 neither half of this was reachable: with the camera critical
    the vehicle HALTed, and with it non-critical absolutely nothing happened.
    """
    machine = FailSafeStateMachine(
        settings(critical=tuple(m for m in ALL_MODALITIES if m is not SensorModality.CAMERA))
    )
    drive(machine, health(dark=SensorModality.CAMERA), ticks=60)
    snapshot = machine.snapshot

    posture: FailSafeState = snapshot.state
    assert posture is FailSafeState.NOMINAL
    assert snapshot.integrity_counter == 0
    assert snapshot.speed_cap is None
    assert snapshot.human_intervention_requested is False
    assert snapshot.withdrawn_capabilities == ("lane_change", "lane_keeping")


def test_the_two_axes_are_independent() -> None:
    """A posture and a capability set that disagree, in both directions.

    NOMINAL with functions withdrawn, and every function intact while the
    posture escalates. If one field could be derived from the other, one of
    these two would be impossible.
    """
    quiet = FailSafeStateMachine(
        settings(critical=(SensorModality.IMU,)),
    )
    drive(quiet, health(dark=SensorModality.CAMERA), ticks=60)
    assert quiet.state is FailSafeState.NOMINAL
    assert quiet.withdrawn_capabilities == ("lane_change", "lane_keeping")

    refusing = FailSafeStateMachine(settings())
    for tick in range(60):
        refusing.observe(
            tick=TickId(tick),
            verdict=SafetyVerdict(
                tick=TickId(tick),
                gate_verdicts=(
                    GateVerdict(
                        tick=TickId(tick),
                        gate=GateId.STATISTICAL,
                        verdict=Verdict.VETO,
                        reason_code="OUT_OF_DISTRIBUTION",
                    ),
                ),
            ),
            frame_health=health(),
        )
    assert refusing.state is not FailSafeState.NOMINAL
    assert refusing.withdrawn_capabilities == ()


@pytest.mark.parametrize(
    ("dark", "expected"),
    [
        (SensorModality.CAMERA, ("lane_change", "lane_keeping")),
        (SensorModality.LIDAR, ("obstacle_avoidance",)),
        (SensorModality.IMU, ("adaptive_cruise",)),
        (SensorModality.GPS, ("route_following",)),
        (
            SensorModality.RADAR,
            ("adaptive_cruise", "lane_change", "obstacle_avoidance"),
        ),
    ],
)
def test_each_modality_withdraws_exactly_what_declared_it(
    dark: SensorModality, expected: tuple[str, ...]
) -> None:
    """Every modality's loss withdraws the functions that named it, and no more.

    This is the whole degradation table, asserted. ``benchmarks/commissioning.py``
    prints the same rows for a real profile; if the two ever disagree, one of
    them is lying to a safety engineer.
    """
    machine = FailSafeStateMachine(settings())
    drive(machine, health(dark=dark), ticks=1)
    assert machine.withdrawn_capabilities == expected


def test_a_capability_falls_to_either_of_its_two_sensors() -> None:
    """``lane_change`` needs the camera *and* the radar; either one loses it."""
    for dark in (SensorModality.CAMERA, SensorModality.RADAR):
        machine = FailSafeStateMachine(settings())
        drive(machine, health(dark=dark), ticks=1)
        assert "lane_change" in machine.withdrawn_capabilities


# --------------------------------------------------------------------------- #
# The properties that make it safe rather than merely useful
# --------------------------------------------------------------------------- #


def test_withdrawal_is_immediate_and_needs_no_counter() -> None:
    """One bad frame withdraws, on the first tick, with the counter still at zero.

    Deliberately unlike the two counters, which debounce because escalating the
    *posture* on a glitch would be intolerable. Declining one function costs the
    vehicle almost nothing, so paying a detection delay to avoid it would be the
    wrong trade -- and would mean granting a lane change during the ticks the
    camera had already gone dark.
    """
    machine = FailSafeStateMachine(settings())
    machine.observe(tick=TickId(0), verdict=passing(), frame_health=health(dark=SensorModality.GPS))

    assert machine.withdrawn_capabilities == ("route_following",)
    assert machine.integrity_counter == 1
    assert machine.state is FailSafeState.NOMINAL


def test_a_degraded_stream_withdraws_as_an_absent_one_does() -> None:
    """Anything worse than HEALTHY withdraws. Only HEALTHY keeps a function."""
    for level in (StreamHealth.DEGRADED, StreamHealth.FAULTED, StreamHealth.ABSENT):
        machine = FailSafeStateMachine(settings())
        drive(machine, health(dark=SensorModality.GPS, level=level), ticks=1)
        assert machine.withdrawn_capabilities == ("route_following",), level


def test_a_recovered_stream_restores_its_capabilities() -> None:
    """Restoration is symmetric today, and the docstring says why it may not stay so."""
    machine = FailSafeStateMachine(settings())
    drive(machine, health(dark=SensorModality.GPS), ticks=30)
    withdrawn: tuple[str, ...] = machine.withdrawn_capabilities
    assert withdrawn == ("route_following",)

    drive(machine, health(), ticks=1, start=30)
    restored: tuple[str, ...] = machine.withdrawn_capabilities
    assert restored == ()


def test_withdrawal_can_only_subtract() -> None:
    """No health map produces a capability that was never declared.

    The intersection is what makes the composition safe: this set removes
    functions the posture would have allowed and can never add one. A set able
    to grant would be a fourth gate with veto-override authority (SI-3).
    """
    declared = {name for name, _ in CAPABILITIES}
    for dark in (None, *ALL_MODALITIES):
        machine = FailSafeStateMachine(settings())
        drive(machine, health(dark=dark), ticks=1)
        assert set(machine.withdrawn_capabilities) <= declared


def test_the_critical_set_does_not_filter_the_capability_set() -> None:
    """Withdrawal ignores ``critical_modalities`` entirely, and must.

    Filtering here would re-couple the two axes and reproduce OD-18 one level
    down: a camera that is no reason to slow down is still the only thing a
    lane change depends on.
    """
    for critical in ((SensorModality.IMU,), ALL_MODALITIES):
        machine = FailSafeStateMachine(settings(critical=critical))
        drive(machine, health(dark=SensorModality.CAMERA), ticks=1)
        assert machine.withdrawn_capabilities == ("lane_change", "lane_keeping")


def test_a_halted_vehicle_still_reports_what_is_broken() -> None:
    """HALT does not collapse the second axis into the first.

    A technician arriving at a stopped vehicle needs to know *which* function
    went first. A record that said only HALT would have thrown that away.
    """
    machine = FailSafeStateMachine(settings())
    drive(machine, health(dark=SensorModality.IMU), ticks=60)

    posture: FailSafeState = machine.state
    assert posture is FailSafeState.HALT
    assert machine.withdrawn_capabilities == ("adaptive_cruise",)


def test_reset_does_not_clear_a_capability_the_sensors_still_withdraw() -> None:
    """``reset`` clears what the machine decided, never what the sensors reported.

    The counters are the machine's own accumulated state and zeroing them is the
    machine forgetting its history. The withdrawn set is a pure function of the
    last frame; emptying it here would assert every sensor healthy, which a
    reset has no way to know.
    """
    machine = FailSafeStateMachine(settings())
    drive(machine, health(dark=SensorModality.CAMERA), ticks=60)
    halted: FailSafeState = machine.state
    assert halted is FailSafeState.HALT

    machine.reset()

    recovered: FailSafeState = machine.state
    assert recovered is FailSafeState.NOMINAL
    assert machine.integrity_counter == 0
    assert machine.withdrawn_capabilities == ("lane_change", "lane_keeping")


# --------------------------------------------------------------------------- #
# The previous behaviour, reproduced exactly
# --------------------------------------------------------------------------- #


def test_declaring_no_capabilities_reproduces_the_previous_behaviour() -> None:
    """An empty declaration withdraws nothing, whatever fails.

    Why the field defaults to empty and A-4 is not being bent: an empty
    ``critical_modalities`` would disable a counter that already escalates, so
    it is a fail-open *claim* and is refused. An empty ``capabilities`` is the
    absence of a claim, and reproduces the system as shipped before the field.
    """
    for dark in ALL_MODALITIES:
        machine = FailSafeStateMachine(settings(capabilities=()))
        drive(machine, health(dark=dark), ticks=60)
        assert machine.withdrawn_capabilities == ()
        assert machine.state is FailSafeState.HALT, "the posture axis is untouched"


def test_a_caller_with_no_sensor_bus_withdraws_nothing() -> None:
    """Empty health means "no sensors", not "every sensor is broken"."""
    machine = FailSafeStateMachine(settings())
    machine.observe(tick=TickId(0), verdict=passing())
    assert machine.withdrawn_capabilities == ()


def test_a_healthy_frame_withdraws_nothing() -> None:
    """The ordinary case, pinned so a derivation bug cannot pass unnoticed."""
    machine = FailSafeStateMachine(settings())
    drive(machine, health(), ticks=60)
    assert machine.withdrawn_capabilities == ()
    assert machine.state is FailSafeState.NOMINAL


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_a_capability_requiring_nothing_is_refused() -> None:
    """A capability with no requirement could never be withdrawn.

    It would sit in the commissioning table looking like a modelled function and
    would survive the loss of every sensor on the vehicle -- the same fail-open
    shape as an empty critical set, refused for the same reason.
    """
    with pytest.raises(ValidationError, match="can never be withdrawn"):
        settings(capabilities=(("lane_change", ()),))


def test_an_unnamed_capability_is_refused() -> None:
    """A blank name cannot be reported, so it cannot be declared."""
    with pytest.raises(ValidationError, match="unnamed capability"):
        settings(capabilities=(("  ", (SensorModality.CAMERA,)),))


def test_a_declaration_is_sorted_so_the_config_hash_ignores_file_order() -> None:
    """Two profiles declaring the same capabilities differently ordered agree.

    The config hash pins a run to its operating point, and two files that differ
    only in the order of a TOML table are the same operating point. Sorting at
    load is what makes that true without anything downstream re-sorting.
    """
    forwards = FailSafeSettings.model_validate(
        {
            **settings().model_dump(exclude={"capabilities"}),
            "capabilities": {
                "route_following": ("GPS",),
                "lane_keeping": ("CAMERA",),
            },
        }
    )
    backwards = FailSafeSettings.model_validate(
        {
            **settings().model_dump(exclude={"capabilities"}),
            "capabilities": {
                "lane_keeping": ("CAMERA",),
                "route_following": ("GPS",),
            },
        }
    )
    assert forwards.capabilities == backwards.capabilities
    assert [name for name, _ in forwards.capabilities] == ["lane_keeping", "route_following"]
