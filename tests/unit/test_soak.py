"""The soak harness's judgement, tested against runs it should and should not pass.

The harness is the instrument that decides whether the closed loop is stable
over long runs, and an instrument that reports stability whatever it is shown is
worse than no instrument -- it converts an unknown into a false assurance. So
every criterion here is exercised twice: once with a series that should pass it
and once with a series constructed to break exactly that one.

``benchmarks/`` is deliberately not an installable package; the repository root
is on ``pythonpath`` for the same reason the integration tests can import
``training``.
"""

from __future__ import annotations

import json
import math

import pytest

from benchmarks.soak import (
    SoakReport,
    WindowSummary,
    _percentile,
    evaluate,
    trend,
    trends,
)
from training.closed_loop import ClosedLoopResult

LANE_HALF_WIDTH_M = 1.75
MEBIBYTE = 1024 * 1024


def window(
    index: int,
    *,
    ticks: int = 1000,
    issued: int | None = None,
    vetoed: int = 100,
    deviation: float = 0.20,
    speed: float = 22.0,
    p99: float = 4.0,
    resident: int | None = 200 * MEBIBYTE,
    digest: str | None = "twin-abc",
    overridden: int = 0,
    failsafe: tuple[str, ...] = ("NOMINAL",),
) -> WindowSummary:
    return WindowSummary(
        index=index,
        first_tick=index * ticks,
        ticks=ticks,
        issued=ticks if issued is None else issued,
        vetoed=vetoed,
        mean_absolute_deviation_m=deviation,
        max_absolute_deviation_m=deviation * 2,
        mean_speed_mps=speed,
        mean_estimator_error_m=0.01,
        mean_trust_index=0.8,
        p50_tick_ms=p99 / 2,
        p99_tick_ms=p99,
        max_tick_ms=p99 * 1.5,
        resident_bytes=resident,
        twin_digest=digest,
        failsafe_states=failsafe,
        reasons=(("PHYSICAL:LATERAL_JERK_EXCEEDS_LIMIT", vetoed),),
        origins=(("PROPOSED", ticks - vetoed), ("FALLBACK_PID", vetoed)),
        arbitrations=(),
        proposals_issued_under_veto=overridden,
    )


def steady(count: int = 20) -> list[WindowSummary]:
    return [window(index) for index in range(count)]


def judge(
    windows: list[WindowSummary],
    *,
    dropped_records: int = 0,
    non_finite_ticks: int = 0,
) -> dict[str, bool | None]:
    criteria = evaluate(
        windows,
        dropped_records=dropped_records,
        lane_half_width_m=LANE_HALF_WIDTH_M,
        non_finite_ticks=non_finite_ticks,
    )
    return {criterion.name: criterion.passed for criterion in criteria}


# --------------------------------------------------------------------------- #
# The trend reduction
# --------------------------------------------------------------------------- #


def test_a_flat_series_has_no_drift() -> None:
    result = trend("flat", [0.5] * 10)

    assert result.drift == pytest.approx(0.0)
    assert result.span == pytest.approx(0.0)


def test_a_rising_series_reports_the_rise() -> None:
    result = trend("rising", [float(value) for value in range(10)])

    assert result.drift > 0
    assert result.span == pytest.approx(9.0)


def test_an_oscillating_series_reports_turns_where_a_drifting_one_does_not() -> None:
    # The whole reason direction changes are reported separately from drift: an
    # oscillation and a flat line have the same halves and are not the same
    # finding.
    oscillating = trend("oscillating", [0.0, 1.0] * 10)
    drifting = trend("drifting", [float(value) for value in range(20)])

    assert oscillating.direction_changes > 0
    assert drifting.direction_changes == 0
    assert oscillating.drift == pytest.approx(0.0)


def test_an_empty_series_raises_rather_than_reporting_stability() -> None:
    # Returning zeros here would report "nothing moved" for a run that measured
    # nothing, which is the one answer that must never be produced by accident.
    with pytest.raises(ValueError, match="empty series"):
        trend("nothing", [])


def test_every_reported_series_survives_a_single_window_run() -> None:
    # A smoke run produces one window; the trend reduction must not divide by a
    # half that does not exist.
    assert len(trends([window(0)])) > 0


# --------------------------------------------------------------------------- #
# Percentiles
# --------------------------------------------------------------------------- #


def test_the_percentile_of_a_sorted_sample_is_the_nearest_rank() -> None:
    ordered = [float(value) for value in range(100)]

    assert _percentile(ordered, 0.5) == pytest.approx(50.0)
    assert _percentile(ordered, 0.99) == pytest.approx(99.0)


def test_the_top_percentile_never_indexes_past_the_end() -> None:
    assert _percentile([1.0], 1.0) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# The criteria, each against a run built to break it
# --------------------------------------------------------------------------- #


def test_a_steady_run_passes_every_criterion() -> None:
    assert all(passed is not False for passed in judge(steady()).values())


def test_a_tick_that_issued_nothing_fails_the_availability_criterion() -> None:
    # The headline claim of the architecture. One tick is enough to break it.
    windows = steady()
    windows[7] = window(7, issued=999)

    assert judge(windows)["a command is issued on every tick"] is False


def test_a_non_finite_tick_fails() -> None:
    assert judge(steady(), non_finite_ticks=1)["the plant state stays finite"] is False


def test_a_dropped_audit_record_fails_the_evidence_criterion() -> None:
    # A run whose evidence has a gap is not a run that can be reported as
    # complete, however well it drove.
    assert judge(steady(), dropped_records=3)["the evidence has no gaps"] is False


def test_a_twin_that_changed_mid_run_fails_while_fb2_is_unwired() -> None:
    windows = steady()
    windows[12] = window(12, digest="twin-def")

    assert judge(windows)["the twin is the one the run started with"] is False


def test_lane_deviation_drifting_across_the_run_fails() -> None:
    # The failure RK-3 names first: not a blow-up, a slow walk.
    windows = [window(index, deviation=0.2 + 0.02 * index) for index in range(20)]

    assert judge(windows)["lane deviation does not drift"] is False


def test_lane_deviation_wandering_within_budget_passes() -> None:
    # The control for the test above. Noise is not drift, and a criterion that
    # cannot tell them apart fires on every run and is then ignored.
    windows = [window(index, deviation=0.2 + 0.001 * (index % 3)) for index in range(20)]

    assert judge(windows)["lane deviation does not drift"] is True


def test_a_run_that_ends_latched_in_halt_fails_however_well_it_drove() -> None:
    # The criterion this file existed without for two runs. A 100,000-tick soak
    # scored STABLE on every other measure -- 0.0003 m of lane deviation, a 0.00%
    # veto rate, speed held for the whole drive -- while the fail-safe machine
    # sat in HALT for 99,000 of those ticks after twenty-one transient vetoes in
    # the first window. The vehicle was fine; the system had declared an
    # emergency and, HALT being terminal, stayed in it.
    windows = [window(index, failsafe=("HALT",)) for index in range(20)]

    assert judge(windows)["the fail-safe machine is not latched at the end"] is False
    assert judge(windows)["lane deviation does not drift"] is True


def test_passing_through_halt_and_recovering_is_not_a_failure() -> None:
    # The control. The criterion is about ending latched, not about ever having
    # been severe -- a run that degrades and recovers is the graduated response
    # working, which is the opposite of a finding.
    windows = [
        window(index, failsafe=("HALT", "LIMP") if index < 10 else ("NOMINAL",))
        for index in range(20)
    ]

    assert judge(windows)["the fail-safe machine is not latched at the end"] is True


def test_a_vehicle_that_came_to_a_stop_fails_however_steady_it_looks() -> None:
    # The criterion this file existed without for one run. A stopped vehicle has
    # no lane drift, no veto-rate movement and flat memory, so every other
    # criterion passes it -- and degrading to a halt is the one behaviour the
    # architecture exists to avoid.
    windows = [window(index, speed=0.0, deviation=0.33) for index in range(20)]

    assert judge(windows)["the vehicle is still moving at the end"] is False
    assert judge(windows)["lane deviation does not drift"] is True


def test_a_transient_dip_to_a_crawl_is_not_a_stop() -> None:
    # The control. Speed recovering is a drive, not a halt, and a criterion that
    # cannot tell them apart would fire on the very first cold-path run.
    windows = [window(index, speed=0.1 if index < 10 else 20.0) for index in range(20)]

    assert judge(windows)["the vehicle is still moving at the end"] is True


def test_a_veto_rate_that_climbs_fails() -> None:
    windows = [window(index, vetoed=50 + 20 * index) for index in range(20)]

    assert judge(windows)["the veto rate does not drift"] is False


def test_resident_memory_growing_without_bound_fails() -> None:
    windows = [window(index, resident=(200 + 16 * index) * MEBIBYTE) for index in range(20)]

    assert judge(windows)["resident set does not grow"] is False


def test_resident_memory_is_unmeasured_rather_than_passed_where_statm_is_absent() -> None:
    # Windows and macOS have no /proc/self/statm. Reporting a pass there would
    # claim a measurement that was never taken.
    windows = [window(index, resident=None) for index in range(20)]

    assert judge(windows)["resident set does not grow"] is None


def test_per_tick_cost_growing_fails() -> None:
    windows = [window(index, p99=4.0 + 0.5 * index) for index in range(20)]

    assert judge(windows)["per-tick cost does not grow"] is False


def test_a_soak_with_no_windows_raises_rather_than_passing() -> None:
    with pytest.raises(ValueError, match="no completed windows"):
        judge([])


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #


def report_for(windows: list[WindowSummary]) -> SoakReport:
    return SoakReport(
        ticks=sum(w.ticks for w in windows),
        windows=tuple(windows),
        criteria=evaluate(
            windows,
            dropped_records=0,
            lane_half_width_m=LANE_HALF_WIDTH_M,
            non_finite_ticks=0,
        ),
        series=trends(windows),
        result=ClosedLoopResult(ticks=sum(w.ticks for w in windows)),
        wall_seconds=1.0,
        policy="placeholder",
        audit_path=None,
    )


def test_an_unmeasurable_criterion_does_not_fail_the_run() -> None:
    # "Not measured" and "measured and fine" are different claims. Only the
    # second may be reported, and neither may fail the run.
    assert report_for([window(index, resident=None) for index in range(20)]).stable is True


def test_a_failed_criterion_fails_the_run() -> None:
    assert report_for([window(index, p99=4.0 + 0.5 * index) for index in range(20)]).stable is False


def test_the_summary_payload_is_json_serialisable() -> None:
    assert json.dumps(report_for(steady()).to_payload())


# --------------------------------------------------------------------------- #
# The window record
# --------------------------------------------------------------------------- #


def test_a_window_renders_the_same_keys_whatever_it_saw() -> None:
    # The series is read back as a table. A ragged one is a parsing problem
    # dressed up as evidence.
    full = window(0).to_payload()
    sparse = window(1, resident=None, digest=None).to_payload()

    assert full.keys() == sparse.keys()


def test_a_proposal_issued_under_a_veto_is_counted_and_not_gated() -> None:
    # Whether bounded safe exploration should out-rank a VETO is a design
    # question. Counting it is this instrument's job; deciding it is not.
    windows = [window(index, overridden=1000) for index in range(20)]

    assert windows[0].to_payload()["proposals_issued_under_veto"] == 1000
    assert all(passed is not False for passed in judge(windows).values())


def test_a_windows_veto_rate_is_its_vetoes_over_its_ticks() -> None:
    assert window(0, vetoed=250).veto_rate == pytest.approx(0.25)


def test_an_empty_window_reports_a_zero_veto_rate_rather_than_dividing_by_zero() -> None:
    assert math.isfinite(window(0, ticks=0, issued=0, vetoed=0).veto_rate)
