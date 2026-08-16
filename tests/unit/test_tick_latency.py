"""The full-tick latency benchmark's arithmetic and its verdict text.

Why this file exists at all
-----------------------------
Two reasons, and the second is the load-bearing one.

**It checks the statistics.** A percentile helper that is quietly off by one
produces a latency figure that looks entirely plausible, which is the failure
mode this project has met four times (C-4) and has a name for.

**It puts the module under `mypy --strict`.** ``files = ["src", "tests"]``, so a
benchmark is type-checked only if a test imports it. A benchmark nobody imports
is a benchmark whose types nobody checks -- and on 16 August 2026 a change to
``benchmarks/whiteness.py`` broke its own ``--sweep`` path, caught only because
a test happened to import the module. Every benchmark carrying a number this
project quotes should be in scope, and importing it here is what puts it there.

The verdict tests are the interesting ones. The tool has to say something
different depending on whether the budget was met at the tail, at the median, or
not at all, and *saying the reassuring thing when the tail is bad* is precisely
the mistake the latency figures in this project have already made once.
"""

from __future__ import annotations

import pytest

from benchmarks.tick_latency import BUDGET_MS, RunReading, percentile, render


def reading(*, p99: float, maximum: float, over: int = 0, p50: float = 2.2) -> RunReading:
    """Return a reading with only the fields the verdict reads set meaningfully."""
    return RunReading(
        seed=20260809,
        samples=2000,
        p50=p50,
        p95=p50,
        p99=p99,
        maximum=maximum,
        over_budget=over,
    )


# --------------------------------------------------------------------------- #
# percentile
# --------------------------------------------------------------------------- #


def test_the_median_of_an_odd_sequence_is_its_middle_value() -> None:
    assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0


def test_the_extremes_are_the_extremes() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]

    assert percentile(values, 0.0) == 1.0
    assert percentile(values, 1.0) == 5.0


def test_the_input_order_does_not_matter() -> None:
    ascending = [float(n) for n in range(100)]
    descending = list(reversed(ascending))

    assert percentile(ascending, 0.99) == percentile(descending, 0.99)


def test_a_single_sample_is_every_percentile() -> None:
    # Not a weaker measurement -- a different kind of thing (E-161). The tool
    # must not divide by zero or index past the end when asked anyway.
    assert percentile([7.0], 0.99) == 7.0
    assert percentile([7.0], 0.0) == 7.0


def test_the_result_is_a_sample_that_actually_occurred() -> None:
    """Nearest-rank, not interpolated.

    An interpolated p99 can report a duration no tick ever took, which is the
    wrong thing to quote when the question is *"did any tick miss its slot?"*
    """
    values = [1.0, 2.0, 100.0]

    assert percentile(values, 0.75) in set(values)


# --------------------------------------------------------------------------- #
# The verdict, which is the part that can flatter
# --------------------------------------------------------------------------- #


def test_a_p99_over_budget_is_reported_as_the_tail_not_the_median() -> None:
    lines = render([reading(p99=BUDGET_MS + 0.5, maximum=BUDGET_MS + 30.0, over=31)])

    assert any("EXCEEDED" in line for line in lines)
    assert any("tail" in line for line in lines)


def test_a_clean_p99_with_a_bad_maximum_still_says_nothing_notices() -> None:
    """The case that actually occurred, and the one most likely to be misread.

    Four runs in five had a p99 inside the budget and a maximum four times over
    it. Reporting only the p99 there would be true and would hide the finding.
    """
    lines = render([reading(p99=7.3, maximum=57.0, over=1)])

    assert not any("EXCEEDED" in line for line in lines)
    assert any("deadline monitor" in line for line in lines)


def test_a_run_inside_budget_everywhere_says_so_plainly() -> None:
    lines = render([reading(p99=3.0, maximum=8.0)])

    assert any("No tick exceeded the budget" in line for line in lines)


def test_the_spread_across_runs_is_reported_because_one_run_is_not_a_tail() -> None:
    lines = render(
        [
            reading(p99=2.768, maximum=7.676),
            reading(p99=10.460, maximum=46.958, over=31),
        ]
    )
    spread = next(line for line in lines if "p99 spread" in line)

    assert "2.768" in spread
    assert "10.460" in spread


def test_the_breach_range_is_reported_rather_than_a_total() -> None:
    # A sum would read as "32 breaches in 4,000 ticks", which averages away the
    # fact that one run had none and the other had 31.
    lines = render([reading(p99=3.0, maximum=8.0), reading(p99=10.5, maximum=46.9, over=31)])
    breaches = next(line for line in lines if "breaches" in line)

    assert "0" in breaches
    assert "31" in breaches


@pytest.mark.parametrize("count", [1, 5])
def test_every_run_gets_a_row(count: int) -> None:
    lines = render([reading(p99=3.0, maximum=8.0) for _ in range(count)])
    numbered = [line for line in lines if line.strip().startswith(("1 ", "2 ", "3 ", "4 ", "5 "))]

    assert len(numbered) == count
