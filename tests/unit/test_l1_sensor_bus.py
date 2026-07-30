"""Unit tests for the L1 shared sensor bus."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

import pytest

from astra.contracts.sensing import FusedSensorFrame, SensorSample
from astra.kernel.enums import SensorModality, StreamHealth
from astra.kernel.errors import ContractViolationError, NonFiniteValueError
from astra.kernel.identifiers import TickId
from astra.kernel.time import Instant, ManualClock, Timeline, is_stale
from astra.kernel.units import Probability, Seconds
from astra.layers.l1_sensing.bus import SharedSensorBus
from astra.ports.pipeline import SensorSource

if TYPE_CHECKING:
    from collections.abc import Callable

STALENESS_BUDGET = Seconds(0.05)
NANOSECONDS_PER_SECOND = 1_000_000_000

THREADS = 8
SAMPLES_PER_THREAD = 200
ACQUIRES = 500


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


def _bus(clock: ManualClock, budget: Seconds = STALENESS_BUDGET) -> SharedSensorBus[str]:
    return SharedSensorBus(clock=clock, staleness_budget=budget)


def _aged(clock: ManualClock, nanoseconds: int) -> Instant:
    return Instant(clock.now().nanoseconds - nanoseconds, clock.timeline)


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def test_a_negative_staleness_budget_raises_contract_violation(clock: ManualClock) -> None:
    with pytest.raises(ContractViolationError):
        _bus(clock, Seconds(-0.001))


def test_the_negative_budget_error_carries_the_offending_value(clock: ManualClock) -> None:
    with pytest.raises(ContractViolationError) as raised:
        _bus(clock, Seconds(-1.0))

    assert raised.value.context["field"] == "staleness_budget"
    assert raised.value.context["value"] == -1.0


def test_a_zero_staleness_budget_is_accepted(clock: ManualClock) -> None:
    assert _bus(clock, Seconds(0.0)).staleness_budget == 0.0


def test_the_staleness_budget_property_round_trips(clock: ManualClock) -> None:
    assert _bus(clock, Seconds(0.125)).staleness_budget == 0.125


@pytest.mark.parametrize(
    ("age_ns", "expected"),
    [
        (0, StreamHealth.HEALTHY),
        (1, StreamHealth.DEGRADED),
        (NANOSECONDS_PER_SECOND, StreamHealth.DEGRADED),
    ],
)
def test_under_a_zero_budget_only_a_simultaneous_reading_is_fresh(
    clock: ManualClock, tick: TickId, age_ns: int, expected: StreamHealth
) -> None:
    bus = _bus(clock, Seconds(0.0))
    bus.publish(_sample(SensorModality.CAMERA, _aged(clock, age_ns)))

    assert bus.health(bus.acquire(tick))[SensorModality.CAMERA] is expected


# --------------------------------------------------------------------------- #
# Fusion and the 50 ms rule (FR1)
# --------------------------------------------------------------------------- #


def test_a_modality_that_never_published_is_absent_from_the_frame(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    bus.publish(_sample(SensorModality.CAMERA, clock.now()))

    frame = bus.acquire(tick)

    assert frame.sample_for(SensorModality.LIDAR) is None
    assert bus.health(frame)[SensorModality.LIDAR] is StreamHealth.ABSENT


def test_a_bus_that_has_seen_nothing_reports_every_modality_absent(
    clock: ManualClock, tick: TickId
) -> None:
    frame = _bus(clock).acquire(tick)

    assert frame.absent_modalities == frozenset(SensorModality)
    assert frame.samples == ()


@pytest.mark.parametrize(
    ("age_ns", "expected"),
    [
        (0, StreamHealth.HEALTHY),
        (49_999_999, StreamHealth.HEALTHY),
        (50_000_000, StreamHealth.HEALTHY),
        (50_000_001, StreamHealth.DEGRADED),
        (200_000_000, StreamHealth.DEGRADED),
    ],
)
def test_health_classifies_a_reading_against_the_exact_staleness_budget_boundary(
    clock: ManualClock, tick: TickId, age_ns: int, expected: StreamHealth
) -> None:
    bus = _bus(clock)
    bus.publish(_sample(SensorModality.RADAR, _aged(clock, age_ns)))

    assert bus.health(bus.acquire(tick))[SensorModality.RADAR] is expected


def test_every_modality_is_accounted_for_in_a_partially_populated_frame(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    bus.publish(_sample(SensorModality.CAMERA, clock.now()))
    bus.publish(_sample(SensorModality.LIDAR, _aged(clock, 60_000_000)))

    frame = bus.acquire(tick)
    report = bus.health(frame)

    present = {sample.modality for sample in frame.samples}
    assert present | frame.absent_modalities == set(SensorModality)
    assert present.isdisjoint(frame.absent_modalities)
    assert set(report) == set(SensorModality)


def test_health_separates_fresh_stale_and_absent_streams_in_one_frame(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    bus.publish(_sample(SensorModality.CAMERA, _aged(clock, 10_000_000)))
    bus.publish(_sample(SensorModality.LIDAR, _aged(clock, 90_000_000)))

    assert bus.health(bus.acquire(tick)) == {
        SensorModality.CAMERA: StreamHealth.HEALTHY,
        SensorModality.LIDAR: StreamHealth.DEGRADED,
        SensorModality.IMU: StreamHealth.ABSENT,
        SensorModality.GPS: StreamHealth.ABSENT,
        SensorModality.RADAR: StreamHealth.ABSENT,
    }


def test_staleness_of_returns_none_for_a_modality_that_produced_nothing(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)

    assert bus.staleness_of(bus.acquire(tick), SensorModality.GPS) is None


def test_staleness_of_returns_the_age_of_a_present_reading(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    bus.publish(_sample(SensorModality.IMU, _aged(clock, 30_000_000)))

    assert bus.staleness_of(bus.acquire(tick), SensorModality.IMU) == pytest.approx(0.03)


def test_staleness_of_is_measured_from_acquisition_time_not_arrival_time(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    # A reading taken 80 ms ago that has only just arrived is 80 ms stale now.
    bus.publish(_sample(SensorModality.LIDAR, _aged(clock, 80_000_000)))

    frame = bus.acquire(tick)

    assert bus.staleness_of(frame, SensorModality.LIDAR) == pytest.approx(0.08)
    assert bus.health(frame)[SensorModality.LIDAR] is StreamHealth.DEGRADED


def test_staleness_of_surfaces_a_negative_age_for_a_future_timestamped_reading(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    bus.publish(_sample(SensorModality.GPS, clock.now().plus(Seconds(0.02))))

    assert bus.staleness_of(bus.acquire(tick), SensorModality.GPS) == pytest.approx(-0.02)


def test_degraded_modalities_agrees_with_health(clock: ManualClock, tick: TickId) -> None:
    bus = _bus(clock)
    bus.publish(_sample(SensorModality.CAMERA, clock.now()))
    bus.publish(_sample(SensorModality.LIDAR, _aged(clock, 90_000_000)))
    bus.publish(_sample(SensorModality.IMU, _aged(clock, 50_000_000)))

    frame = bus.acquire(tick)
    report = bus.health(frame)

    assert bus.degraded_modalities(frame) == frozenset(
        modality for modality, health in report.items() if health is not StreamHealth.HEALTHY
    )
    assert bus.degraded_modalities(frame) == frozenset(
        {SensorModality.LIDAR, SensorModality.GPS, SensorModality.RADAR}
    )


def test_is_degraded_is_true_exactly_when_some_modality_is_not_healthy(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    for modality in SensorModality:
        bus.publish(_sample(modality, clock.now()))

    healthy_frame = bus.acquire(tick)
    assert bus.degraded_modalities(healthy_frame) == frozenset()
    assert bus.is_degraded(healthy_frame) is False

    clock.advance(Seconds(0.06))
    stale_frame = bus.acquire(tick)
    assert bus.is_degraded(stale_frame) is True
    assert bus.degraded_modalities(stale_frame) == frozenset(SensorModality)


def test_an_absent_modality_alone_makes_the_frame_degraded(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    bus.publish(_sample(SensorModality.CAMERA, clock.now()))

    frame = bus.acquire(tick)

    assert bus.health(frame)[SensorModality.CAMERA] is StreamHealth.HEALTHY
    assert bus.is_degraded(frame) is True


# --------------------------------------------------------------------------- #
# Out-of-order rejection
# --------------------------------------------------------------------------- #


def test_publishing_the_first_reading_of_a_modality_is_accepted(clock: ManualClock) -> None:
    bus = _bus(clock)
    first = _sample(SensorModality.CAMERA, clock.now())

    assert bus.publish(first) is True
    assert bus.latest(SensorModality.CAMERA) is first


def test_latest_is_none_for_a_modality_that_produced_nothing(clock: ManualClock) -> None:
    assert _bus(clock).latest(SensorModality.RADAR) is None


def test_a_newer_reading_replaces_the_held_one(clock: ManualClock) -> None:
    bus = _bus(clock)
    base = clock.now()
    bus.publish(_sample(SensorModality.CAMERA, base))
    newer = _sample(SensorModality.CAMERA, base.plus(Seconds(0.01)))

    assert bus.publish(newer) is True
    assert bus.latest(SensorModality.CAMERA) is newer


def test_an_older_reading_is_rejected_and_does_not_replace_the_held_one(
    clock: ManualClock,
) -> None:
    bus = _bus(clock)
    base = clock.now()
    held = _sample(SensorModality.CAMERA, base)

    bus.publish(held)

    assert bus.publish(_sample(SensorModality.CAMERA, base.plus(Seconds(-0.01)))) is False
    assert bus.latest(SensorModality.CAMERA) is held


def test_a_reading_with_the_same_observed_at_is_rejected_as_not_strictly_newer(
    clock: ManualClock,
) -> None:
    bus = _bus(clock)
    base = clock.now()
    held = _sample(SensorModality.CAMERA, base)

    bus.publish(held)

    assert bus.publish(_sample(SensorModality.CAMERA, base, quality=0.1)) is False
    assert bus.latest(SensorModality.CAMERA) is held


def test_rejection_is_per_modality_and_does_not_block_another_stream(
    clock: ManualClock,
) -> None:
    bus = _bus(clock)
    base = clock.now()
    bus.publish(_sample(SensorModality.CAMERA, base))

    assert bus.publish(_sample(SensorModality.CAMERA, base)) is False
    assert bus.publish(_sample(SensorModality.LIDAR, base)) is True


def test_a_superseded_sample_is_counted_rather_than_silently_dropped(
    clock: ManualClock,
) -> None:
    bus = _bus(clock)
    base = clock.now()
    bus.publish(_sample(SensorModality.CAMERA, base.plus(Seconds(0.05))))

    for offset in (0.01, 0.02, 0.03):
        assert bus.publish(_sample(SensorModality.CAMERA, base.plus(Seconds(offset)))) is False

    statistics = bus.statistics
    assert statistics.published[SensorModality.CAMERA] == 1
    assert statistics.superseded[SensorModality.CAMERA] == 3


def test_a_rejected_out_of_order_publish_leaves_the_measured_staleness_unmoved(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    bus.publish(_sample(SensorModality.CAMERA, _aged(clock, 100_000_000)))
    before = bus.staleness_of(bus.acquire(tick), SensorModality.CAMERA)

    assert bus.publish(_sample(SensorModality.CAMERA, _aged(clock, 150_000_000))) is False

    frame = bus.acquire(tick)
    after = bus.staleness_of(frame, SensorModality.CAMERA)

    assert before is not None
    assert after is not None
    # The reason the rule exists: measured staleness must never travel backwards.
    assert after >= before
    assert after == pytest.approx(before)
    assert bus.health(frame)[SensorModality.CAMERA] is StreamHealth.DEGRADED


def test_measured_staleness_never_decreases_while_only_older_readings_arrive(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    base = clock.now()
    bus.publish(_sample(SensorModality.CAMERA, base))

    measured: list[float] = []
    for step in range(1, 5):
        clock.advance(Seconds(0.02))
        assert (
            bus.publish(_sample(SensorModality.CAMERA, base.plus(Seconds(-0.01 * step)))) is False
        )
        age = bus.staleness_of(bus.acquire(tick), SensorModality.CAMERA)
        assert age is not None
        measured.append(age)

    assert measured == sorted(measured)
    assert bus.statistics.superseded[SensorModality.CAMERA] == 4


# --------------------------------------------------------------------------- #
# Timeline discipline
# --------------------------------------------------------------------------- #


def test_publishing_a_sample_from_another_timeline_raises_contract_violation(
    clock: ManualClock,
) -> None:
    bus = _bus(clock)
    foreign = Instant(clock.now().nanoseconds, Timeline.SIMULATED)

    with pytest.raises(ContractViolationError):
        bus.publish(_sample(SensorModality.CAMERA, foreign))


def test_the_timeline_error_names_both_the_sample_and_the_bus_timeline(
    clock: ManualClock,
) -> None:
    bus = _bus(clock)
    foreign = Instant(0, Timeline.SYSTEM_MONOTONIC)

    with pytest.raises(ContractViolationError) as raised:
        bus.publish(_sample(SensorModality.GPS, foreign))

    assert raised.value.context["sample_timeline"] == Timeline.SYSTEM_MONOTONIC.value
    assert raised.value.context["bus_timeline"] == Timeline.MANUAL.value
    assert Timeline.SYSTEM_MONOTONIC.value in str(raised.value)
    assert Timeline.MANUAL.value in str(raised.value)


def test_a_rejected_cross_timeline_sample_is_not_counted_at_all(clock: ManualClock) -> None:
    bus = _bus(clock)

    with pytest.raises(ContractViolationError):
        bus.publish(_sample(SensorModality.IMU, Instant(0, Timeline.SIMULATED)))

    statistics = bus.statistics
    assert statistics.total_published == 0
    assert statistics.total_superseded == 0
    assert bus.latest(SensorModality.IMU) is None


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #


def test_a_fresh_bus_reports_zero_for_every_modality(clock: ManualClock) -> None:
    statistics = _bus(clock).statistics

    assert statistics.published == dict.fromkeys(SensorModality, 0)
    assert statistics.superseded == dict.fromkeys(SensorModality, 0)
    assert statistics.frames_acquired == 0
    assert statistics.total_published == 0
    assert statistics.total_superseded == 0


def test_published_and_superseded_counts_are_kept_per_modality(clock: ManualClock) -> None:
    bus = _bus(clock)
    base = clock.now()
    bus.publish(_sample(SensorModality.CAMERA, base.plus(Seconds(0.02))))
    bus.publish(_sample(SensorModality.CAMERA, base.plus(Seconds(0.01))))
    bus.publish(_sample(SensorModality.LIDAR, base))
    bus.publish(_sample(SensorModality.LIDAR, base.plus(Seconds(0.01))))

    statistics = bus.statistics

    assert statistics.published[SensorModality.CAMERA] == 1
    assert statistics.superseded[SensorModality.CAMERA] == 1
    assert statistics.published[SensorModality.LIDAR] == 2
    assert statistics.superseded[SensorModality.LIDAR] == 0
    assert statistics.published[SensorModality.RADAR] == 0


def test_totals_aggregate_the_per_modality_counts(clock: ManualClock) -> None:
    bus = _bus(clock)
    base = clock.now()
    for modality in SensorModality:
        bus.publish(_sample(modality, base.plus(Seconds(0.01))))
        bus.publish(_sample(modality, base))

    statistics = bus.statistics

    assert statistics.total_published == len(SensorModality)
    assert statistics.total_superseded == len(SensorModality)


def test_frames_acquired_increments_once_per_acquire(clock: ManualClock, tick: TickId) -> None:
    bus = _bus(clock)

    for expected in range(1, 4):
        bus.acquire(tick)
        assert bus.statistics.frames_acquired == expected


def test_statistics_is_a_snapshot_that_a_caller_cannot_mutate(clock: ManualClock) -> None:
    bus = _bus(clock)
    bus.publish(_sample(SensorModality.CAMERA, clock.now()))
    statistics = bus.statistics

    cast("dict[SensorModality, int]", statistics.published)[SensorModality.CAMERA] = 999
    cast("dict[SensorModality, int]", statistics.superseded)[SensorModality.LIDAR] = 999

    assert bus.statistics.published[SensorModality.CAMERA] == 1
    assert bus.statistics.superseded[SensorModality.LIDAR] == 0


def test_a_statistics_snapshot_does_not_change_when_the_bus_moves_on(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    snapshot = bus.statistics

    bus.publish(_sample(SensorModality.CAMERA, clock.now()))
    bus.acquire(tick)

    assert snapshot.total_published == 0
    assert snapshot.frames_acquired == 0


# --------------------------------------------------------------------------- #
# Resetting the bus between replayed segments
# --------------------------------------------------------------------------- #


def test_reset_discards_every_held_reading(clock: ManualClock, tick: TickId) -> None:
    bus = _bus(clock)
    for modality in SensorModality:
        bus.publish(_sample(modality, clock.now()))

    bus.reset()

    frame = bus.acquire(tick)
    assert frame.samples == ()
    assert frame.absent_modalities == frozenset(SensorModality)
    assert bus.health(frame) == dict.fromkeys(SensorModality, StreamHealth.ABSENT)
    assert bus.latest(SensorModality.CAMERA) is None


def test_reset_zeroes_every_counter(clock: ManualClock, tick: TickId) -> None:
    bus = _bus(clock)
    base = clock.now()
    bus.publish(_sample(SensorModality.CAMERA, base.plus(Seconds(0.01))))
    bus.publish(_sample(SensorModality.CAMERA, base))
    bus.acquire(tick)

    bus.reset()

    statistics = bus.statistics
    assert statistics.published == dict.fromkeys(SensorModality, 0)
    assert statistics.superseded == dict.fromkeys(SensorModality, 0)
    assert statistics.frames_acquired == 0


def test_after_reset_a_previously_rejected_older_reading_is_accepted(
    clock: ManualClock,
) -> None:
    bus = _bus(clock)
    base = clock.now()
    bus.publish(_sample(SensorModality.CAMERA, base.plus(Seconds(0.05))))
    older = _sample(SensorModality.CAMERA, base)

    assert bus.publish(older) is False

    bus.reset()

    assert bus.publish(older) is True
    assert bus.latest(SensorModality.CAMERA) is older


# --------------------------------------------------------------------------- #
# Protocol conformance
# --------------------------------------------------------------------------- #


def test_the_bus_satisfies_the_sensor_source_protocol(clock: ManualClock) -> None:
    bus = _bus(clock)

    assert isinstance(bus, SensorSource)


def test_the_bus_is_usable_through_the_sensor_source_port(clock: ManualClock, tick: TickId) -> None:
    source: SensorSource[str] = _bus(clock)

    assert isinstance(source.acquire(tick), FusedSensorFrame)


# --------------------------------------------------------------------------- #
# Thread safety
# --------------------------------------------------------------------------- #


def _publisher(
    bus: SharedSensorBus[str],
    *,
    thread_index: int,
    barrier: threading.Barrier,
    failures: list[BaseException],
) -> Callable[[], None]:
    def run() -> None:
        try:
            barrier.wait()
            for step in range(SAMPLES_PER_THREAD):
                # Strictly increasing per thread, and globally unique across threads.
                observed_at = Instant(step * THREADS + thread_index + 1, Timeline.MANUAL)
                for modality in SensorModality:
                    bus.publish(_sample(modality, observed_at))
        except Exception as error:  # noqa: BLE001 - a test must not lose a thread's failure
            failures.append(error)

    return run


def test_concurrent_publishers_lose_nothing_and_keep_the_newest_reading(
    clock: ManualClock,
) -> None:
    bus = _bus(clock)
    failures: list[BaseException] = []
    barrier = threading.Barrier(THREADS)
    threads = [
        threading.Thread(
            target=_publisher(bus, thread_index=index, barrier=barrier, failures=failures)
        )
        for index in range(THREADS)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []

    statistics = bus.statistics
    offered = THREADS * SAMPLES_PER_THREAD
    newest = SAMPLES_PER_THREAD * THREADS
    for modality in SensorModality:
        assert statistics.published[modality] + statistics.superseded[modality] == offered
        held = bus.latest(modality)
        assert held is not None
        assert held.observed_at.nanoseconds == newest

    assert statistics.total_published + statistics.total_superseded == offered * len(SensorModality)


def test_acquiring_while_publishers_run_always_yields_a_well_formed_frame(
    clock: ManualClock, tick: TickId
) -> None:
    bus = _bus(clock)
    failures: list[BaseException] = []
    barrier = threading.Barrier(THREADS + 1)
    frames: list[FusedSensorFrame[str]] = []

    def acquire_repeatedly() -> None:
        try:
            barrier.wait()
            frames.extend(bus.acquire(tick) for _ in range(ACQUIRES))
        except Exception as error:  # noqa: BLE001 - a test must not lose a thread's failure
            failures.append(error)

    threads = [
        threading.Thread(
            target=_publisher(bus, thread_index=index, barrier=barrier, failures=failures)
        )
        for index in range(THREADS)
    ]
    threads.append(threading.Thread(target=acquire_repeatedly))

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert len(frames) == ACQUIRES
    for frame in frames:
        present = {sample.modality for sample in frame.samples}
        assert len(present) == len(frame.samples)
        assert present.isdisjoint(frame.absent_modalities)
        assert present | frame.absent_modalities == set(SensorModality)
        assert frame.fused_at.timeline is Timeline.MANUAL
    assert bus.statistics.frames_acquired == ACQUIRES


# --------------------------------------------------------------------------- #
# A non-finite budget must not silently disable FR1
# --------------------------------------------------------------------------- #
# NaN defeats a comparison rather than failing it: `staleness > nan` is False,
# so a NaN budget would report every stream healthy forever. That is a
# fail-*open* mode in the one rule L1 exists to enforce, so it is refused at
# construction rather than discovered in a run.


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_staleness_budget_is_refused(clock: ManualClock, budget: float) -> None:
    with pytest.raises(NonFiniteValueError):
        SharedSensorBus[str](clock=clock, staleness_budget=Seconds(budget))


def test_a_nan_budget_cannot_be_used_to_report_an_ancient_reading_as_healthy(
    clock: ManualClock,
) -> None:
    # The regression this guards: before the budget was checked for finiteness,
    # a NaN made a reading 1000 s old classify as HEALTHY.
    with pytest.raises(NonFiniteValueError):
        SharedSensorBus[str](clock=clock, staleness_budget=Seconds(float("nan")))


def test_is_stale_refuses_a_non_finite_budget() -> None:
    with pytest.raises(NonFiniteValueError):
        is_stale(
            Instant(0, Timeline.MANUAL),
            Instant(1_000_000_000_000, Timeline.MANUAL),
            Seconds(float("nan")),
        )


# --------------------------------------------------------------------------- #
# The fusion instant and the snapshot are taken atomically
# --------------------------------------------------------------------------- #


def test_no_frame_reports_negative_staleness_while_publishing_concurrently() -> None:
    # If `acquire` read the clock outside the lock, a sample published in the
    # intervening window would carry `observed_at` after `fused_at` and be
    # reported with negative staleness -- manufacturing the future-timestamp
    # fault signal out of ordinary scheduling jitter.
    clock = ManualClock(Instant(0, Timeline.MANUAL))
    bus: SharedSensorBus[str] = SharedSensorBus(clock=clock, staleness_budget=Seconds(0.05))
    negatives: list[float] = []
    failures: list[BaseException] = []
    barrier = threading.Barrier(2)

    def publisher() -> None:
        try:
            barrier.wait()
            for step in range(1, 400):
                bus.publish(
                    SensorSample(
                        SensorModality.CAMERA,
                        Instant(step, Timeline.MANUAL),
                        Probability(1.0),
                        "payload",
                    )
                )
        except BaseException as error:  # noqa: BLE001 - recorded, then re-asserted
            failures.append(error)

    def consumer() -> None:
        try:
            barrier.wait()
            for step in range(400):
                frame = bus.acquire(TickId(step))
                negatives.extend(
                    step
                    for sample in frame.samples
                    if sample.observed_at.nanoseconds > frame.fused_at.nanoseconds
                )
        except BaseException as error:  # noqa: BLE001 - recorded, then re-asserted
            failures.append(error)

    threads = [threading.Thread(target=publisher), threading.Thread(target=consumer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert negatives == []


# --------------------------------------------------------------------------- #
# Frames are structurally deterministic
# --------------------------------------------------------------------------- #


def test_samples_are_emitted_in_modality_declaration_order_not_publish_order(
    clock: ManualClock,
) -> None:
    # Without this, the sample order depends on which sensor thread delivered
    # first, so two runs over identical inputs produce frames that are equal in
    # content but not in structure -- which defeats frame-by-frame comparison
    # between a run and its replay.
    bus = _bus(clock, STALENESS_BUDGET)
    for modality in reversed(list(SensorModality)):
        bus.publish(_sample(modality, clock.now()))

    frame = bus.acquire(TickId(0))

    assert [sample.modality for sample in frame.samples] == list(SensorModality)


def test_two_buses_fed_the_same_readings_in_different_orders_agree(
    clock: ManualClock,
) -> None:
    forward = _bus(clock, STALENESS_BUDGET)
    backward = _bus(clock, STALENESS_BUDGET)
    modalities = [SensorModality.GPS, SensorModality.IMU, SensorModality.CAMERA]
    for modality in modalities:
        forward.publish(_sample(modality, clock.now()))
    for modality in reversed(modalities):
        backward.publish(_sample(modality, clock.now()))

    assert forward.acquire(TickId(0)) == backward.acquire(TickId(0))
