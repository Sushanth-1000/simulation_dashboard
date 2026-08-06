"""Run the test suite repeatedly under CPU contention, hunting for flakes.

Why this exists
---------------
On 1 August 2026 a concurrency test in ``tests/unit/test_l1_sensor_bus.py``
*hung* under 12-way load. Not failed -- hung, with no output and no exit, which
is the worst failure mode a test can have: CI reports a timeout on some job
minutes later, and the suite has no idea which of two thousand tests is
responsible. ``RENDEZVOUS_TIMEOUT`` and ``JOIN_TIMEOUT`` were added so that a
thread that never arrives fails with a name attached instead of blocking.

Adding a timeout is a claim. This harness is the evidence for it, and it is
committed rather than run once from a shell because a number in
``docs/EVIDENCE.md`` whose command cannot be re-run on a clean checkout is not
evidence of anything.

What it measures
----------------
Three outcomes per run, not two, because the distinction is the whole point:

``pass``
    Exit zero.
``fail``
    Non-zero exit, with pytest's own output kept. A flake that fails loudly is
    an ordinary bug report.
``hang``
    Killed by this harness's own wall-clock timeout. **This is the outcome the
    fix was for.** A single one means the timeouts did not close the hole.

Two campaigns run in sequence. The broad one runs the whole suite, because a
flake elsewhere would be just as damaging and nothing has ever looked. The
focused one runs only the threaded tests, many more times, because that is where
the risk is concentrated and they are cheap -- a hundred runs of six tests buys
far more statistical power than a hundred runs of two thousand.

Load
----
``stress-ng`` if present, otherwise a pure-Python spinner over the same number of
processes. The spinner is worse -- it is one interpreter per worker and the GIL
makes each one less hostile than a native busy-loop -- but "stress-ng is not
installed" must not silently become "the campaign ran unloaded and everything
passed".

Usage:
    python -m benchmarks.flake_hunt
    python -m benchmarks.flake_hunt --repeats 20 --focus-repeats 200
    python -m benchmarks.flake_hunt --load none    # the control
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

__all__ = ["main"]

_DEFAULT_REPEATS: Final = 20
"""Full-suite runs. Twenty is what `PENDING.md` P2.2 asks for, and it is enough
to catch a flake with a per-run probability above roughly 15%."""

_DEFAULT_FOCUS_REPEATS: Final = 200
"""Runs of the threaded tests alone. Ten times the breadth for a fraction of the
cost, because they are the tests the campaign is actually about."""

_DEFAULT_OVERSUBSCRIPTION: Final = 2.0
"""Load workers per core. Above 1.0 the scheduler must preempt, which is what
makes a rendezvous miss its barrier; at exactly 1.0 a well-behaved run may never
be descheduled at an interesting moment."""

_SUITE_TIMEOUT_SECONDS: Final = 1800.0
"""Wall clock before a full-suite run is called a hang. Generous: the suite takes
about 50 s unloaded, and heavy contention can multiply that several times over.
A timeout tight enough to fire on a slow machine would manufacture the outcome it
is meant to detect."""

_FOCUS_TIMEOUT_SECONDS: Final = 300.0
"""The same for the threaded tests, which take about a second unloaded. Still far
above `JOIN_TIMEOUT` (60 s), so a test that hits its own timeout reports itself
as a failure rather than being killed from outside -- which is the behaviour the
fix installed, and this harness must not mask it."""

_BUS_TESTS: Final = "tests/unit/test_l1_sensor_bus.py"
_FOCUS_SELECTOR: Final = (
    f"{_BUS_TESTS}::test_concurrent_publishers_lose_nothing_and_keep_the_newest_reading",
    f"{_BUS_TESTS}::test_acquiring_while_publishers_run_always_yields_a_well_formed_frame",
    f"{_BUS_TESTS}::test_no_frame_reports_negative_staleness_while_publishing_concurrently",
    "tests/unit/test_si8_timing.py",
)
"""The threaded tests, named explicitly. A marker would be tidier, but naming
them here keeps the campaign's scope visible in the file that reports on it --
and a marker silently applied to a fourth test would change what a published
number means without changing the number."""

_SPINNER: Final = (
    "import time\n"
    "deadline = time.monotonic() + float(__import__('sys').argv[1])\n"
    "x = 0\n"
    "while time.monotonic() < deadline:\n"
    "    x = (x * 1103515245 + 12345) % 2147483648\n"
)
"""The fallback load. A linear congruential generator because it is arithmetic
the interpreter cannot optimise away."""


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """One invocation of pytest.

    Attributes:
        index: Which run this was, from one.
        outcome: ``pass``, ``fail`` or ``hang``.
        seconds: Wall clock.
        returncode: Pytest's exit code, or ``None`` if it was killed.
    """

    index: int
    outcome: str
    seconds: float
    returncode: int | None


@dataclass(frozen=True, slots=True)
class Campaign:
    """The result of one series of runs.

    Attributes:
        name: What was run.
        selector: The pytest arguments used.
        runs: Every outcome, in order.
    """

    name: str
    selector: tuple[str, ...]
    runs: tuple[RunOutcome, ...]

    @property
    def failed(self) -> tuple[RunOutcome, ...]:
        """Return the runs that failed or hung."""
        return tuple(run for run in self.runs if run.outcome != "pass")

    @property
    def hung(self) -> tuple[RunOutcome, ...]:
        """Return the runs killed by the harness."""
        return tuple(run for run in self.runs if run.outcome == "hang")

    @property
    def is_clean(self) -> bool:
        """Return whether every run passed."""
        return not self.failed


class _Load:
    """Background CPU contention for the duration of a campaign."""

    def __init__(self, *, workers: int, seconds: float, stress_ng: str | None) -> None:
        """Start the load.

        Args:
            workers: How many busy processes to run.
            seconds: How long they should live. They are killed on exit
                regardless; this is a backstop against orphaning a busy-loop on
                a developer's machine if the harness dies.
            stress_ng: Absolute path to ``stress-ng``, or ``None`` if absent.
        """
        self._processes: list[subprocess.Popen[bytes]] = []
        self._workers = workers
        self.kind = "none"
        if workers <= 0:
            return
        if stress_ng is not None:
            self.kind = "stress-ng"
            self._processes.append(
                subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                    [
                        stress_ng,
                        "--cpu",
                        str(workers),
                        "--timeout",
                        f"{int(seconds)}s",
                        "--metrics-brief",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            return
        self.kind = "python-spinner"
        self._processes.extend(
            subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                [sys.executable, "-c", _SPINNER, str(seconds)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(workers)
        )

    @property
    def workers(self) -> int:
        """Return how many load processes were asked for."""
        return self._workers

    def stop(self) -> None:
        """Terminate every load process."""
        for process in self._processes:
            if process.poll() is None:
                process.terminate()
        for process in self._processes:
            try:
                process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                process.kill()
        self._processes.clear()


def _run_once(
    *, index: int, selector: tuple[str, ...], timeout: float, log_directory: Path
) -> RunOutcome:
    """Run pytest once and classify the result.

    Args:
        index: Which run this is, from one.
        selector: Pytest arguments.
        timeout: Wall clock before the run is called a hang.
        log_directory: Where to write the output of runs that do not pass.

    Returns:
        The outcome. Output is kept only for failures and hangs -- two thousand
        passing runs' worth of pytest output is not evidence, it is a disk.
    """
    command = [sys.executable, "-m", "pytest", "-q", *selector]
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        elapsed = time.monotonic() - started
        captured = (expired.stdout or b"").decode("utf-8", "replace")
        log_directory.mkdir(parents=True, exist_ok=True)
        (log_directory / f"hang-{index:04d}.log").write_text(
            f"killed after {elapsed:.1f}s\n\n{captured}", encoding="utf-8"
        )
        return RunOutcome(index=index, outcome="hang", seconds=elapsed, returncode=None)

    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        log_directory.mkdir(parents=True, exist_ok=True)
        (log_directory / f"fail-{index:04d}.log").write_text(
            completed.stdout.decode("utf-8", "replace")
            + "\n--- stderr ---\n"
            + completed.stderr.decode("utf-8", "replace"),
            encoding="utf-8",
        )
        return RunOutcome(
            index=index, outcome="fail", seconds=elapsed, returncode=completed.returncode
        )
    return RunOutcome(index=index, outcome="pass", seconds=elapsed, returncode=0)


def _run_campaign(
    *, name: str, selector: tuple[str, ...], repeats: int, timeout: float, output: Path
) -> Campaign:
    """Run one series and report progress as it goes.

    Args:
        name: What is being run, for the console.
        selector: Pytest arguments.
        repeats: How many times.
        timeout: Per-run wall clock before a hang is declared.
        output: Directory for the logs of runs that do not pass.

    Returns:
        The campaign.
    """
    print(f"\n  {name}: {repeats} run(s), timeout {timeout:.0f}s each")
    runs: list[RunOutcome] = []
    for index in range(1, repeats + 1):
        outcome = _run_once(
            index=index, selector=selector, timeout=timeout, log_directory=output / name
        )
        runs.append(outcome)
        marker = {"pass": ".", "fail": "F", "hang": "H"}[outcome.outcome]
        print(marker, end="", flush=True)
        if index % 50 == 0:
            print(f" {index}", flush=True)
    print(flush=True)
    return Campaign(name=name, selector=selector, runs=tuple(runs))


def _report(campaigns: list[Campaign], *, load_kind: str, workers: int) -> bool:
    """Print the summary and return whether everything was clean.

    Args:
        campaigns: Every campaign run.
        load_kind: Which load was applied.
        workers: How many load processes.

    Returns:
        True if no run failed or hung.
    """
    print("\n" + "=" * 78)
    print(f"  load: {load_kind}, {workers} worker(s)")
    for campaign in campaigns:
        total = len(campaign.runs)
        passed = total - len(campaign.failed)
        seconds = [run.seconds for run in campaign.runs]
        print(f"\n  {campaign.name}")
        print(f"    {passed}/{total} passed")
        if seconds:
            print(
                f"    wall clock  min {min(seconds):.1f}s"
                f"  median {sorted(seconds)[len(seconds) // 2]:.1f}s"
                f"  max {max(seconds):.1f}s"
            )
        if campaign.hung:
            indices = ", ".join(str(run.index) for run in campaign.hung)
            print(f"    HUNG on run(s) {indices} -- the timeouts did not close the hole")
        failures = tuple(run for run in campaign.failed if run.outcome == "fail")
        if failures:
            indices = ", ".join(str(run.index) for run in failures)
            print(f"    failed on run(s) {indices}; output kept alongside the summary")

    clean = all(campaign.is_clean for campaign in campaigns)
    print("\n" + "=" * 78)
    print(f"  verdict: {'NO FLAKE OBSERVED' if clean else 'FLAKE REPRODUCED'}")
    if clean:
        print("           absence of evidence over this many runs, not proof of absence")
    return clean


def main(argv: list[str] | None = None) -> int:
    """Run the campaigns and write the summary.

    Args:
        argv: Command-line arguments, or ``None`` to read ``sys.argv``.

    Returns:
        Zero if every run passed, one otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=_DEFAULT_REPEATS)
    parser.add_argument("--focus-repeats", type=int, default=_DEFAULT_FOCUS_REPEATS)
    parser.add_argument("--load", choices=("auto", "none"), default="auto")
    parser.add_argument("--oversubscription", type=float, default=_DEFAULT_OVERSUBSCRIPTION)
    parser.add_argument("--output", type=Path, default=Path("var/flake"))
    arguments = parser.parse_args(argv)

    cores = os.cpu_count() or 1
    workers = 0 if arguments.load == "none" else max(1, round(cores * arguments.oversubscription))
    stress_ng = shutil.which("stress-ng")
    budget = (
        arguments.repeats * _SUITE_TIMEOUT_SECONDS
        + arguments.focus_repeats * _FOCUS_TIMEOUT_SECONDS
    )

    print(f"  cores: {cores}")
    if workers and stress_ng is None:
        print("  stress-ng not found; falling back to a Python spinner (weaker contention)")

    load = _Load(workers=workers, seconds=budget, stress_ng=stress_ng)
    campaigns: list[Campaign] = []
    try:
        campaigns.append(
            _run_campaign(
                name="full-suite",
                selector=("tests",),
                repeats=arguments.repeats,
                timeout=_SUITE_TIMEOUT_SECONDS,
                output=arguments.output,
            )
        )
        campaigns.append(
            _run_campaign(
                name="threaded-tests",
                selector=_FOCUS_SELECTOR,
                repeats=arguments.focus_repeats,
                timeout=_FOCUS_TIMEOUT_SECONDS,
                output=arguments.output,
            )
        )
    except KeyboardInterrupt:
        print("\n  interrupted", flush=True)
        return signal.SIGINT + 128
    finally:
        load.stop()

    clean = _report(campaigns, load_kind=load.kind, workers=load.workers)

    arguments.output.mkdir(parents=True, exist_ok=True)
    summary = arguments.output / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "cores": cores,
                "load": load.kind,
                "workers": load.workers,
                "clean": clean,
                "campaigns": [
                    {
                        "name": campaign.name,
                        "selector": list(campaign.selector),
                        "runs": [asdict(run) for run in campaign.runs],
                    }
                    for campaign in campaigns
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  summary: {summary}")
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
