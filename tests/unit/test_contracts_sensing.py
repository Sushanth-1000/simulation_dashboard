"""Unit tests for the L1 sensing contracts."""

from __future__ import annotations

import pytest

from astra.contracts.sensing import FusedSensorFrame, SensorSample
from astra.kernel.enums import SensorModality, StreamHealth
from astra.kernel.errors import ContractViolationError, NonFiniteValueError, RangeViolationError
from astra.kernel.identifiers import TickId
from astra.kernel.time import Instant, Timeline
from astra.kernel.units import Probability, Seconds

STALENESS_BUDGET = Seconds(0.05)


def _sample(
    modality: SensorModality,
    observed_at: Instant,
    quality: float = 1.0,
) -> SensorSample[str]:
    return SensorSample(
        modality=modality,
        observed_at=observed_at,
        quality=Probability(quality),
        payload=f"{modality.value}-payload",
    )


# --------------------------------------------------------------------------- #
# SensorSample -- quality validation
# --------------------------------------------------------------------------- #


def test_sensor_sample_accepts_quality_at_both_ends_of_the_unit_interval(now: Instant) -> None:
    floor = _sample(SensorModality.CAMERA, now, quality=0.0)
    ceiling = _sample(SensorModality.LIDAR, now, quality=1.0)

    assert floor.quality == 0.0
    assert ceiling.quality == 1.0


def test_sensor_sample_with_quality_above_one_raises_range_violation(now: Instant) -> None:
    with pytest.raises(RangeViolationError):
        _sample(SensorModality.CAMERA, now, quality=1.000_001)


def test_sensor_sample_with_negative_quality_raises_range_violation(now: Instant) -> None:
    with pytest.raises(RangeViolationError):
        _sample(SensorModality.RADAR, now, quality=-0.1)


def test_sensor_sample_with_nan_quality_raises_non_finite_value(now: Instant) -> None:
    with pytest.raises(NonFiniteValueError):
        _sample(SensorModality.IMU, now, quality=float("nan"))


def test_sensor_sample_error_names_the_modality_that_reported_bad_quality(now: Instant) -> None:
    with pytest.raises(RangeViolationError) as raised:
        _sample(SensorModality.GPS, now, quality=2.0)

    assert raised.value.context["field"] == "GPS.quality"


# --------------------------------------------------------------------------- #
# SensorSample -- staleness
# --------------------------------------------------------------------------- #


def test_health_at_reports_healthy_for_a_reading_inside_the_staleness_budget(now: Instant) -> None:
    sample = _sample(SensorModality.CAMERA, now)

    assert sample.health_at(now.plus(Seconds(0.04)), STALENESS_BUDGET) is StreamHealth.HEALTHY


def test_health_at_reports_healthy_for_a_reading_exactly_at_the_staleness_budget(
    now: Instant,
) -> None:
    sample = _sample(SensorModality.CAMERA, now)

    assert sample.health_at(now.plus(STALENESS_BUDGET), STALENESS_BUDGET) is StreamHealth.HEALTHY


def test_health_at_reports_degraded_once_the_reading_exceeds_the_staleness_budget(
    now: Instant,
) -> None:
    sample = _sample(SensorModality.CAMERA, now)

    assert sample.health_at(now.plus(Seconds(0.06)), STALENESS_BUDGET) is StreamHealth.DEGRADED


def test_health_at_never_reports_faulted_because_that_needs_the_innovation_monitor(
    now: Instant,
) -> None:
    sample = _sample(SensorModality.LIDAR, now)

    verdicts = {
        sample.health_at(now.plus(Seconds(offset)), STALENESS_BUDGET) for offset in (0.0, 1.0, 10.0)
    }

    assert StreamHealth.FAULTED not in verdicts


def test_health_at_across_timelines_raises_contract_violation(now: Instant) -> None:
    sample = _sample(SensorModality.CAMERA, now)
    other_timeline = Instant(now.nanoseconds, Timeline.SIMULATED)

    with pytest.raises(ContractViolationError):
        sample.health_at(other_timeline, STALENESS_BUDGET)


# --------------------------------------------------------------------------- #
# FusedSensorFrame -- structural validation
# --------------------------------------------------------------------------- #


def test_fused_frame_with_two_samples_of_the_same_modality_raises_contract_violation(
    tick: TickId, now: Instant
) -> None:
    with pytest.raises(ContractViolationError):
        FusedSensorFrame(
            tick=tick,
            fused_at=now,
            samples=(
                _sample(SensorModality.CAMERA, now),
                _sample(SensorModality.CAMERA, now.plus(Seconds(0.001))),
            ),
        )


def test_fused_frame_duplicate_modality_error_lists_the_offending_modalities(
    tick: TickId, now: Instant
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        FusedSensorFrame(
            tick=tick,
            fused_at=now,
            samples=(
                _sample(SensorModality.LIDAR, now),
                _sample(SensorModality.LIDAR, now),
            ),
        )

    assert raised.value.context["modalities"] == ["LIDAR", "LIDAR"]


def test_fused_frame_with_a_modality_both_present_and_absent_raises_contract_violation(
    tick: TickId, now: Instant
) -> None:
    with pytest.raises(ContractViolationError) as raised:
        FusedSensorFrame(
            tick=tick,
            fused_at=now,
            samples=(_sample(SensorModality.CAMERA, now),),
            absent_modalities=frozenset({SensorModality.CAMERA, SensorModality.RADAR}),
        )

    assert raised.value.context["modalities"] == ["CAMERA"]


def test_fused_frame_with_disjoint_present_and_absent_sets_is_accepted(
    tick: TickId, now: Instant
) -> None:
    frame = FusedSensorFrame(
        tick=tick,
        fused_at=now,
        samples=(_sample(SensorModality.CAMERA, now),),
        absent_modalities=frozenset({SensorModality.RADAR}),
    )

    assert frame.tick == tick
    assert frame.absent_modalities == frozenset({SensorModality.RADAR})


def test_fused_frame_defaults_to_an_empty_absent_set(tick: TickId, now: Instant) -> None:
    frame: FusedSensorFrame[str] = FusedSensorFrame(tick=tick, fused_at=now, samples=())

    assert frame.absent_modalities == frozenset()


# --------------------------------------------------------------------------- #
# FusedSensorFrame -- lookup
# --------------------------------------------------------------------------- #


def test_sample_for_returns_the_sample_of_a_present_modality(tick: TickId, now: Instant) -> None:
    camera = _sample(SensorModality.CAMERA, now)
    frame = FusedSensorFrame(
        tick=tick, fused_at=now, samples=(camera, _sample(SensorModality.LIDAR, now))
    )

    assert frame.sample_for(SensorModality.CAMERA) is camera


def test_sample_for_returns_none_for_a_modality_that_produced_nothing(
    tick: TickId, now: Instant
) -> None:
    frame = FusedSensorFrame(tick=tick, fused_at=now, samples=(_sample(SensorModality.IMU, now),))

    assert frame.sample_for(SensorModality.GPS) is None


# --------------------------------------------------------------------------- #
# FusedSensorFrame -- health reporting
# --------------------------------------------------------------------------- #


def test_health_classifies_present_absent_and_stale_modalities_separately(
    tick: TickId, now: Instant
) -> None:
    frame = FusedSensorFrame(
        tick=tick,
        fused_at=now,
        samples=(
            _sample(SensorModality.CAMERA, now),
            _sample(SensorModality.LIDAR, now.plus(Seconds(-0.2))),
        ),
        absent_modalities=frozenset({SensorModality.RADAR}),
    )

    assert frame.health(STALENESS_BUDGET) == {
        SensorModality.CAMERA: StreamHealth.HEALTHY,
        SensorModality.LIDAR: StreamHealth.DEGRADED,
        SensorModality.RADAR: StreamHealth.ABSENT,
    }


def test_health_omits_modalities_the_frame_never_names(tick: TickId, now: Instant) -> None:
    frame = FusedSensorFrame(tick=tick, fused_at=now, samples=(_sample(SensorModality.IMU, now),))

    assert set(frame.health(STALENESS_BUDGET)) == {SensorModality.IMU}


def test_degraded_modalities_reports_every_modality_that_is_not_healthy(
    tick: TickId, now: Instant
) -> None:
    frame = FusedSensorFrame(
        tick=tick,
        fused_at=now,
        samples=(
            _sample(SensorModality.CAMERA, now),
            _sample(SensorModality.LIDAR, now.plus(Seconds(-0.2))),
        ),
        absent_modalities=frozenset({SensorModality.RADAR}),
    )

    assert frame.degraded_modalities(STALENESS_BUDGET) == frozenset(
        {SensorModality.LIDAR, SensorModality.RADAR}
    )


def test_degraded_modalities_is_empty_when_every_stream_is_fresh(
    tick: TickId, now: Instant
) -> None:
    frame = FusedSensorFrame(
        tick=tick,
        fused_at=now,
        samples=(_sample(SensorModality.CAMERA, now), _sample(SensorModality.IMU, now)),
    )

    assert frame.degraded_modalities(STALENESS_BUDGET) == frozenset()


# --------------------------------------------------------------------------- #
# FusedSensorFrame.build
# --------------------------------------------------------------------------- #


def test_build_derives_the_absent_set_from_the_modalities_supplied(
    tick: TickId, now: Instant
) -> None:
    frame = FusedSensorFrame.build(
        tick=tick,
        fused_at=now,
        samples=[_sample(SensorModality.CAMERA, now), _sample(SensorModality.LIDAR, now)],
    )

    assert frame.absent_modalities == frozenset(
        {SensorModality.IMU, SensorModality.GPS, SensorModality.RADAR}
    )


def test_build_with_no_samples_marks_every_modality_absent(tick: TickId, now: Instant) -> None:
    frame: FusedSensorFrame[str] = FusedSensorFrame.build(tick=tick, fused_at=now, samples=[])

    assert frame.absent_modalities == frozenset(SensorModality)
    assert frame.health(STALENESS_BUDGET) == dict.fromkeys(SensorModality, StreamHealth.ABSENT)


def test_build_materialises_a_lazy_iterable_of_samples(tick: TickId, now: Instant) -> None:
    frame = FusedSensorFrame.build(
        tick=tick,
        fused_at=now,
        samples=(_sample(modality, now) for modality in (SensorModality.GPS, SensorModality.IMU)),
    )

    assert len(frame.samples) == 2
    assert frame.sample_for(SensorModality.GPS) is not None


def test_build_rejects_a_modality_supplied_twice(tick: TickId, now: Instant) -> None:
    with pytest.raises(ContractViolationError):
        FusedSensorFrame.build(
            tick=tick,
            fused_at=now,
            samples=[_sample(SensorModality.GPS, now), _sample(SensorModality.GPS, now)],
        )
