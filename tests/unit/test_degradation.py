"""Does the degradation table describe the machine, or just restate the file?

The distinction is the whole value of the tool. A degradation concept written by
hand beside a state machine maintained separately is a document that drifts, and
a drifted safety document is worse than none because it is trusted. So
``benchmarks/degradation.py`` *drives the real fail-safe machine* once per
modality and reports what happened.

These tests pin that it does. The rows must follow the machine's behaviour --
including into the two configurations the shipped profiles deliberately do not
have, because a table that only works on the conservative profile would be
useless to the integrator who narrows it:

- a **graceful** row, where the vehicle keeps driving and declines a function
- an **inert** row, where losing a sensor does nothing at all, which is the
  integration bug this table exists to surface
"""

from __future__ import annotations

from astra.config.schema import FailSafeSettings
from astra.kernel.enums import FailSafeState, SensorModality
from benchmarks.degradation import assess, render

ALL_MODALITIES = (
    SensorModality.CAMERA,
    SensorModality.LIDAR,
    SensorModality.IMU,
    SensorModality.GPS,
    SensorModality.RADAR,
)

CAPABILITIES = (
    ("lane_change", (SensorModality.CAMERA, SensorModality.RADAR)),
    ("route_following", (SensorModality.GPS,)),
)


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


def test_one_row_per_installed_modality_in_the_order_supplied() -> None:
    """The installed set is an input, so a vehicle without a radar has no radar row."""
    rows = assess(settings=settings(), installed=(SensorModality.IMU, SensorModality.GPS))
    assert [row.modality for row in rows] == ["IMU", "GPS"]


def test_a_critical_modality_halts_and_says_what_it_withdrew() -> None:
    """Both axes reported on one row, which is the point of the table."""
    (row,) = assess(settings=settings(), installed=(SensorModality.GPS,))
    assert row.critical is True
    assert row.posture == FailSafeState.HALT.value
    assert row.withdrawn == ("route_following",)
    assert row.inert is False


def test_a_graceful_row_keeps_driving_and_declines_the_function() -> None:
    """The behaviour ADR-0029 exists to make expressible, in the table.

    NOMINAL, integrity counter at zero, and a function withdrawn. No row of the
    previous two-response design could have looked like this.
    """
    narrowed = settings(critical=(SensorModality.IMU,))
    (row,) = assess(settings=narrowed, installed=(SensorModality.CAMERA,))

    assert row.posture == FailSafeState.NOMINAL.value
    assert row.integrity_counter == 0
    assert row.withdrawn == ("lane_change",)
    assert row.inert is False, "a withdrawn function is not nothing"

    assert any("degrade gracefully" in line for line in render([row]))


def test_an_inert_modality_is_flagged() -> None:
    """The integration bug the table exists to surface.

    LIDAR is neither critical nor required by any declared capability, so losing
    it moves no posture and withdraws no function. Nothing in the code says so;
    the row does.
    """
    narrowed = settings(critical=(SensorModality.IMU,))
    (row,) = assess(settings=narrowed, installed=(SensorModality.LIDAR,))

    assert row.inert is True
    assert row.posture == FailSafeState.NOMINAL.value
    assert row.withdrawn == ()

    rendered = render([row])
    assert any("INERT" in line for line in rendered)
    assert any("do nothing when they fail" in line for line in rendered)


def test_inertness_is_measured_rather_than_deduced_from_the_configuration() -> None:
    """A modality that is critical is never inert, however few functions name it.

    ``inert`` asks the machine what it did rather than recomputing what the
    config said. The two agree here -- and would part company the moment the
    derivation regressed, which is the failure a restating table would hide.
    """
    (row,) = assess(settings=settings(), installed=(SensorModality.LIDAR,))
    assert row.withdrawn == (), "no declared capability names the lidar"
    assert row.critical is True
    assert row.inert is False, "it still stops the vehicle, so it does something"


def test_the_table_renders_every_row_and_no_warning_when_none_is_earned() -> None:
    """The shipped-profile shape: all critical, nothing inert, nothing graceful."""
    rows = assess(settings=settings(), installed=ALL_MODALITIES)
    rendered = render(rows)

    for modality in ALL_MODALITIES:
        assert any(modality.value in line for line in rendered)
    assert not any("INERT" in line for line in rendered)
    assert not any("degrade gracefully" in line for line in rendered)


def test_a_modality_with_no_capability_and_no_criticality_renders_a_dash() -> None:
    """An empty withdrawal is printed, not omitted -- a blank column reads as lost."""
    narrowed = settings(critical=(SensorModality.IMU,))
    rows = assess(settings=narrowed, installed=(SensorModality.LIDAR,))
    assert any("--" in line for line in render(rows))
