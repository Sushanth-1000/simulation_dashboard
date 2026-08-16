"""How long does one *assembled* tick take, and how stable is the tail?

Why this exists beside ``benchmarks/latency.py``
--------------------------------------------------
``latency.py`` times four layers in isolation -- L1 fusion, the L2 fast update,
the L7a shield, the L8 machine -- and reports a combined hot path of well under
a millisecond. That figure is real and it is not the one A-2 is about. A-2
claims **10 ms per tick at 20 Hz**, and a tick is the whole pipeline: the twin's
forward pass, three gates, arbitration, and an audit record written.

For nine months nothing measured that. On 16 August 2026 a verification pass
found the A-Z knowledge base asserting *"no end-to-end latency measurement
appears in the evidence pack"* -- which was wrong, because the soak records a
full-pipeline p99 (E-8), and also nearly right, because nothing measured it
directly and on demand. This closes that gap with a command.

Why it runs the measurement more than once
--------------------------------------------
Because the first time it was run once, and the single run said *"one tick in
2,000 over budget"*. Five runs said **0 to 31 ticks over budget**, with p99
ranging 2.768 ms to 10.460 ms and one run's p99 exceeding the budget outright.
The median was stable across every run to within 5%; the tail was not stable at
all.

**A tail statistic from one run is not a tail statistic.** That is the same
lesson as E-161's single sample and E-143's single configuration, arriving
through a third door, and it is why ``--runs`` defaults to five rather than one.

What this does NOT measure
----------------------------
The host is idle. ``benchmarks/flake_hunt.py`` puts the same machine under
``stress-ng`` and the test suite runs about 2.6x slower; nothing here says what
the tick tail does under contention. It also excludes any simulator round trip,
which is exactly what CARLA will add to every tick.

CPython offers no timing guarantee, so a figure from this tool is a
characterisation and never a bound.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from astra.layers.l4_proposer.learned import LearnedPolicy
from training.closed_loop import TickSample, drive_closed_loop

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["RunReading", "measure", "percentile", "render"]

_DEFAULT_RUNS: Final = 5
_DEFAULT_TICKS: Final = 2200
_DEFAULT_WARMUP: Final = 200
_DEFAULT_SEED: Final = 20260809
_DEFAULT_POLICY: Final = Path("var/policy/synthetic.pt")

BUDGET_MS: Final = 10.0
"""A-2's per-tick budget at 20 Hz. An assumption, not a measured bound."""

_NANOSECONDS_PER_MILLISECOND: Final = 1e6


@dataclass(frozen=True, slots=True)
class RunReading:
    """One run's tick-duration distribution.

    Attributes:
        seed: The plant seed this run used. Runs differ only by seed.
        samples: How many ticks contributed, after warm-up.
        p50: Median tick duration in milliseconds.
        p95: 95th percentile.
        p99: 99th percentile.
        maximum: The slowest single tick.
        over_budget: How many ticks exceeded :data:`BUDGET_MS`.
    """

    seed: int
    samples: int
    p50: float
    p95: float
    p99: float
    maximum: float
    over_budget: int


def percentile(values: Sequence[float], fraction: float) -> float:
    """Return the value at ``fraction`` through the sorted sequence.

    Nearest-rank rather than interpolated. With 2,000 samples the difference is
    immaterial and the rank is a value that actually occurred, which is the
    right thing to quote for a latency figure.

    Args:
        values: The sample set. Must be non-empty.
        fraction: A value in ``[0, 1]``.

    Returns:
        The sample at that rank.
    """
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def measure(*, runs: int, ticks: int, warmup: int, seed: int, policy: Path) -> list[RunReading]:
    """Drive the assembled loop ``runs`` times and read the per-tick cost.

    The duration comes from ``TickSample.pipeline_duration_ns``, which the loop
    records around the whole assembled pipeline. Warm-up ticks are dropped
    because the first pass through any Python code path pays for imports,
    first-touch allocation and JIT-free interpreter warm-up that a steady-state
    figure should not carry.

    Args:
        runs: How many independent runs. More than one on purpose; see module
            docstring.
        ticks: Ticks per run, including warm-up.
        warmup: Leading ticks to discard.
        seed: The first run's seed. Each later run adds its index.
        policy: The trained proposer checkpoint.

    Returns:
        One reading per run, in run order.
    """
    readings: list[RunReading] = []
    for index in range(runs):
        samples: list[TickSample] = []
        drive_closed_loop(
            policy=LearnedPolicy.load(policy),
            ticks=ticks,
            seed=seed + index,
            observer=samples.append,
        )
        durations = [
            sample.pipeline_duration_ns / _NANOSECONDS_PER_MILLISECOND
            for sample in samples[warmup:]
        ]
        readings.append(
            RunReading(
                seed=seed + index,
                samples=len(durations),
                p50=percentile(durations, 0.50),
                p95=percentile(durations, 0.95),
                p99=percentile(durations, 0.99),
                maximum=max(durations),
                over_budget=sum(1 for value in durations if value > BUDGET_MS),
            )
        )
    return readings


def render(readings: Sequence[RunReading]) -> list[str]:
    """Return the per-run table and the spread that matters.

    Args:
        readings: One entry per run.

    Returns:
        Printable lines.
    """
    lines = [
        "",
        "Full assembled tick -- the whole pipeline, not the four-layer hot path",
        "=" * 78,
        f"  budget {BUDGET_MS} ms per tick (A-2, 20 Hz). SOFTWARE characterisation,",
        "  on an idle host, with no simulator in the loop. Never a bound.",
        "",
        f"  {'run':<6}{'seed':>12}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>10}{'over budget':>16}",
        f"  {'-' * 6}{'-' * 11:>12}{'-' * 8:>9}{'-' * 8:>9}{'-' * 8:>9}{'-' * 9:>10}"
        f"{'-' * 15:>16}",
    ]
    for index, reading in enumerate(readings, start=1):
        lines.append(
            f"  {index:<6}{reading.seed:>12}{reading.p50:>9.3f}{reading.p95:>9.3f}"
            f"{reading.p99:>9.3f}{reading.maximum:>10.3f}"
            f"{f'{reading.over_budget} / {reading.samples}':>16}"
        )

    p99s = [reading.p99 for reading in readings]
    maxima = [reading.maximum for reading in readings]
    breaches = [reading.over_budget for reading in readings]
    lines.extend(
        [
            "",
            (
                f"  p50 spread   {min(r.p50 for r in readings):.3f} - "
                f"{max(r.p50 for r in readings):.3f} ms"
            ),
            f"  p99 spread   {min(p99s):.3f} - {max(p99s):.3f} ms",
            f"  max spread   {min(maxima):.3f} - {max(maxima):.3f} ms",
            f"  breaches     {min(breaches)} - {max(breaches)} ticks per run",
            "",
        ]
    )

    if max(p99s) > BUDGET_MS:
        lines.extend(
            [
                "  At least one run's p99 EXCEEDED the budget. The median is not the",
                "  figure a 20 Hz control loop is judged on; the tail is.",
            ]
        )
    elif max(maxima) > BUDGET_MS:
        lines.extend(
            [
                "  Every p99 sits inside the budget and at least one individual tick",
                "  did not. There is no deadline monitor, so an overrun is written to",
                "  the record identically to a punctual tick -- invisible in exactly",
                "  the log that exists to make behaviour reconstructible.",
            ]
        )
    else:
        lines.append("  No tick exceeded the budget in any run.")
    lines.append("")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero unless the policy checkpoint is missing.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", "-r", type=int, default=_DEFAULT_RUNS)
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--warmup", type=int, default=_DEFAULT_WARMUP)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    arguments = parser.parse_args(argv)

    if not arguments.policy.exists():
        print(f"missing {arguments.policy}; run `make artifacts` first")
        return 1

    readings = measure(
        runs=arguments.runs,
        ticks=arguments.ticks,
        warmup=arguments.warmup,
        seed=arguments.seed,
        policy=arguments.policy,
    )
    for line in render(readings):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
