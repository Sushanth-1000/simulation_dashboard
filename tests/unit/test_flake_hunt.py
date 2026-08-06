"""The flake-hunting harness, and whether it can see what it is looking for.

`benchmarks/flake_hunt.py` exists to produce one claim: *the suite ran N times
under load and nothing hung*. That claim is worth exactly as much as the
harness's ability to notice a hang, so these tests give it a test that really
does hang and check that it says so.

The rest pin the parts that would otherwise fail silently: a run whose output is
discarded, a load that never started, a campaign that calls itself clean while
holding a failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.flake_hunt import Campaign, RunOutcome, _Load, _run_once

# Long enough that the harness's timeout is what ends it, short enough that a
# broken timeout does not wedge the suite: `_run_once` kills the child, and if
# it did not, pytest's own collection would still finish in seconds.
HANGING_TEST = """
import time

def test_that_never_finishes() -> None:
    time.sleep(600)
"""

FAILING_TEST = """
def test_that_fails() -> None:
    assert False, "deliberate"
"""

PASSING_TEST = """
def test_that_passes() -> None:
    assert True
"""

HANG_TIMEOUT = 5.0
"""Two of these run on every gate invocation, so it is as small as it can be
while still being unambiguous. The child sleeps for ten minutes, so it cannot
finish within any timeout; five seconds only has to be longer than the interval
in which a *timeout mechanism* could plausibly misfire, not longer than pytest
takes to start."""


def _write(directory: Path, name: str, body: str) -> str:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- #
# The three outcomes
# --------------------------------------------------------------------------- #


def test_a_passing_run_is_recorded_as_a_pass_and_leaves_no_log(tmp_path: Path) -> None:
    selector = (_write(tmp_path, "test_ok.py", PASSING_TEST),)
    logs = tmp_path / "logs"

    outcome = _run_once(index=1, selector=selector, timeout=120.0, log_directory=logs)

    assert outcome.outcome == "pass"
    assert outcome.returncode == 0
    assert not logs.exists(), "passing runs must not write logs; there would be thousands"


def test_a_failing_run_is_recorded_as_a_fail_and_keeps_its_output(tmp_path: Path) -> None:
    selector = (_write(tmp_path, "test_bad.py", FAILING_TEST),)
    logs = tmp_path / "logs"

    outcome = _run_once(index=7, selector=selector, timeout=120.0, log_directory=logs)

    assert outcome.outcome == "fail"
    assert outcome.returncode not in (0, None)
    assert "deliberate" in (logs / "fail-0007.log").read_text(encoding="utf-8")


def test_a_hanging_run_is_recorded_as_a_hang_rather_than_a_fail(tmp_path: Path) -> None:
    # THE test. The harness's whole purpose is to distinguish these two, because
    # the defect it was written for hung rather than failed -- and a harness that
    # reported a hang as a failure would send the next reader looking for an
    # assertion that does not exist.
    selector = (_write(tmp_path, "test_hangs.py", HANGING_TEST),)
    logs = tmp_path / "logs"

    outcome = _run_once(index=3, selector=selector, timeout=HANG_TIMEOUT, log_directory=logs)

    assert outcome.outcome == "hang"
    assert outcome.returncode is None, "nothing exited, so there is no code to report"
    assert outcome.seconds == pytest.approx(HANG_TIMEOUT, abs=2.0)
    assert "killed after" in (logs / "hang-0003.log").read_text(encoding="utf-8")


def test_a_hang_does_not_leave_the_child_running(tmp_path: Path) -> None:
    # A harness that timed out but left the process alive would accumulate one
    # busy child per hang, and the runs after the first would be measuring a
    # machine the harness itself had loaded.
    selector = (_write(tmp_path, "test_hangs.py", HANGING_TEST),)

    _run_once(index=1, selector=selector, timeout=HANG_TIMEOUT, log_directory=tmp_path / "logs")
    second = _run_once(
        index=2,
        selector=(_write(tmp_path, "test_ok.py", PASSING_TEST),),
        timeout=120.0,
        log_directory=tmp_path / "logs",
    )

    assert second.outcome == "pass"


# --------------------------------------------------------------------------- #
# The campaign's own accounting
# --------------------------------------------------------------------------- #


def _outcome(index: int, outcome: str) -> RunOutcome:
    return RunOutcome(index=index, outcome=outcome, seconds=1.0, returncode=None)


def test_a_campaign_of_passes_is_clean() -> None:
    campaign = Campaign(
        name="x", selector=("tests",), runs=tuple(_outcome(i, "pass") for i in range(5))
    )

    assert campaign.is_clean
    assert campaign.failed == ()
    assert campaign.hung == ()


def test_one_hang_in_a_hundred_passes_is_not_clean() -> None:
    # The asymmetry that matters. A flake campaign reporting "99% passed" as a
    # success would be reporting the opposite of what it measured.
    runs = [_outcome(i, "pass") for i in range(99)]
    runs.insert(50, _outcome(99, "hang"))
    campaign = Campaign(name="x", selector=("tests",), runs=tuple(runs))

    assert not campaign.is_clean
    assert len(campaign.hung) == 1


def test_a_failure_counts_against_the_campaign_but_is_not_a_hang() -> None:
    campaign = Campaign(
        name="x", selector=("tests",), runs=(_outcome(1, "pass"), _outcome(2, "fail"))
    )

    assert not campaign.is_clean
    assert len(campaign.failed) == 1
    assert campaign.hung == ()


# --------------------------------------------------------------------------- #
# The load
# --------------------------------------------------------------------------- #


def test_no_load_is_requested_when_workers_is_zero() -> None:
    load = _Load(workers=0, seconds=1.0, stress_ng=None)
    try:
        assert load.kind == "none"
        assert load.workers == 0
    finally:
        load.stop()


def test_the_absent_stress_ng_falls_back_to_the_spinner_rather_than_to_nothing() -> None:
    # "stress-ng is not installed" must not silently become "the campaign ran
    # unloaded and everything passed". The fallback is weaker; being weaker and
    # labelled is the point.
    load = _Load(workers=2, seconds=1.0, stress_ng=None)
    try:
        assert load.kind == "python-spinner"
        assert load.workers == 2
    finally:
        load.stop()


def test_stopping_a_load_twice_is_harmless() -> None:
    # `stop` runs in a `finally`, and a campaign interrupted mid-run can reach it
    # by two paths.
    load = _Load(workers=2, seconds=1.0, stress_ng=None)
    load.stop()
    load.stop()

    assert load.workers == 2
