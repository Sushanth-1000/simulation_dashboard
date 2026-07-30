"""Measure the hot-path latency of the layers that exist.

Why this is a committed script rather than a note
--------------------------------------------------
The project's honesty boundaries require that any number it reports comes from
code that ran, and that every latency claim is labelled as either an analytical
hardware bound or a software measurement. A figure recorded in a document decays
the moment the code changes; a script anyone can re-run does not.

Run it with::

    uv run python benchmarks/latency.py
    # or, from an activated venv:
    python benchmarks/latency.py

What it does and does not measure
----------------------------------
It measures the wall-clock cost of one L1 fusion and one L2 fast update on the
host it runs on, in CPython, with synthetic measurements. That is the *software*
figure, and it is the only kind this project may report against the < 1 ms
per-layer and < 10 ms end-to-end software targets.

It is **not** the 1.25 microsecond Core-B intercept figure from the paper. That
number is an analytical worst-case execution-time bound for a hardware
implementation (AbsInt aiT, 500 MHz, 627 cycles) and is not measurable by a
Python prototype at all. The two must never be quoted as though they were the
same kind of claim.

The measurement covers the layers that exist -- L1, L2, L7a and L8 -- and
excludes the simulator, the audit sink, and L3, L4, L5, L6 and L9, which do not.
It is therefore a floor on the eventual end-to-end figure, not an estimate of
it.
"""

from __future__ import annotations

import argparse
import platform
import random
import statistics
import sys
import time
from typing import TYPE_CHECKING, NamedTuple

from astra.config.loader import load_settings
from astra.contracts.actuation import (
    ActuationChannel,
    ActuationSpace,
    CommandOrigin,
    ControlCommand,
    ProposedCommand,
)
from astra.contracts.assurance import SafetyVerdict
from astra.contracts.estimation import SlowStateEstimate
from astra.contracts.sensing import FusedSensorFrame, SensorSample
from astra.kernel.enums import LayerId, SensorModality
from astra.kernel.identifiers import ComponentId, TickId
from astra.kernel.matrix import SymmetricMatrix
from astra.kernel.time import Instant, ManualClock, Timeline
from astra.kernel.units import Probability, Seconds
from astra.layers.l1_sensing.bus import SharedSensorBus
from astra.layers.l2_estimation.filter import DualRateUKF
from astra.layers.l2_estimation.measurement import fast_measurement, slow_measurement
from astra.layers.l7_shield.shield import HardSafetyShield
from astra.layers.l8_failsafe.machine import FailSafeStateMachine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.layers.l2_estimation.measurement import Measurement

_NANOSECONDS_PER_MILLISECOND = 1_000_000
_WARMUP_TICKS = 200

# The per-layer software budgets from the paper's latency table. Reported
# against, never silently compared to the hardware figure.
_L1_BUDGET_MS = 1.0
_L2_BUDGET_MS = 1.0
_L7_BUDGET_MS = 1.0
_L8_BUDGET_MS = 1.0
_END_TO_END_BUDGET_MS = 10.0


class Latency(NamedTuple):
    """Summary statistics for one measured stage, in milliseconds."""

    label: str
    p50: float
    p95: float
    p99: float
    maximum: float
    budget: float

    @property
    def within_budget(self) -> bool:
        """Return whether the 99th percentile is inside the stage's budget."""
        return self.p99 < self.budget


class _SyntheticExtractor:
    """Produces plausible measurements without a simulator.

    The point of the benchmark is the cost of the filter's arithmetic, which
    does not depend on whether the numbers are physically meaningful -- only on
    how many dimensions are observed. Using synthetic values keeps the benchmark
    runnable on any machine, including one with no CARLA build.
    """

    __slots__ = ("_random",)

    def __init__(self, seed: int) -> None:
        """Initialise with an explicit seed so a rerun measures the same work.

        Args:
            seed: Seed for the local random source. A local generator is used
                rather than the module-level one so the benchmark cannot perturb
                anything else in the process.
        """
        self._random = random.Random(seed)

    def extract_fast(self, frame: FusedSensorFrame[object]) -> Measurement | None:
        """Return a four-dimensional observation of the kinematic state.

        Args:
            frame: The fused frame. Unused; the values are synthetic.

        Returns:
            The measurement.
        """
        del frame
        return fast_measurement(
            [
                ("position_x", self._random.gauss(0.0, 1.0), 0.25),
                ("position_y", self._random.gauss(0.0, 1.0), 0.25),
                ("speed", 20.0 + self._random.gauss(0.0, 0.1), 0.01),
                ("lateral_acceleration", self._random.gauss(0.0, 0.2), 0.04),
            ]
        )

    def extract_slow(self, frame: FusedSensorFrame[object]) -> Measurement | None:
        """Return a one-dimensional observation of the degradation state.

        Args:
            frame: The fused frame. Unused.

        Returns:
            The measurement.
        """
        del frame
        return slow_measurement([("road_friction_coefficient", 0.85, 4e-4)])


def _summarise(label: str, samples: Sequence[float], budget: float) -> Latency:
    """Reduce a sample of durations to percentiles.

    Percentiles rather than a mean: a control loop is bounded by its worst
    ticks, and a mean hides exactly the tail that would miss a deadline.

    Args:
        label: The stage name.
        samples: Durations in milliseconds.
        budget: The stage's software budget in milliseconds.

    Returns:
        The summary.
    """
    ordered = sorted(samples)
    return Latency(
        label=label,
        p50=statistics.median(ordered),
        p95=ordered[int(len(ordered) * 0.95)],
        p99=ordered[int(len(ordered) * 0.99)],
        maximum=ordered[-1],
        budget=budget,
    )


def _frame(tick: int, period: Seconds) -> FusedSensorFrame[object]:
    """Build a frame carrying no samples, for driving the filter.

    Args:
        tick: The tick number.
        period: The tick period in seconds.

    Returns:
        The frame.
    """
    return FusedSensorFrame.build(
        tick=TickId(tick),
        fused_at=Instant(int(tick * period * 1e9), Timeline.SIMULATED),
        samples=(),
    )


def measure(*, environment: str, iterations: int, seed: int) -> list[Latency]:
    """Run the benchmark and return one summary per stage.

    Args:
        environment: Which configuration to load the operating point from.
        iterations: How many timed samples to take per stage.
        seed: Seed for the synthetic measurements.

    Returns:
        The per-stage summaries, plus the combined figure.
    """
    settings = load_settings(environment=environment, include_environment_variables=False).settings
    period = Seconds(1.0 / settings.estimation.fast_rate_hz)

    estimator: DualRateUKF[object] = DualRateUKF(
        settings=settings.estimation,
        extractor=_SyntheticExtractor(seed),
        initial_fast_state=[0.0, 0.0, 20.0, 0.0, 0.0],
        initial_fast_covariance=SymmetricMatrix.from_diagonal([1.0, 1.0, 1.0, 0.1, 1.0]),
        initial_slow_state=[0.85, 0.0, 1.0],
        initial_slow_covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
    )
    clock = ManualClock(Instant(0, Timeline.MANUAL))
    bus: SharedSensorBus[object] = SharedSensorBus(
        clock=clock, staleness_budget=settings.sensing.staleness_budget
    )

    # Warm up: let the filter converge and CPython's caches settle, so the
    # measurement reflects steady-state cost rather than first-call overhead.
    for tick in range(_WARMUP_TICKS):
        estimator.update_fast(_frame(tick, period))

    estimation_samples: list[float] = []
    for tick in range(iterations):
        start = time.perf_counter_ns()
        estimator.update_fast(_frame(tick, period))
        estimation_samples.append((time.perf_counter_ns() - start) / _NANOSECONDS_PER_MILLISECOND)

    fusion_samples: list[float] = []
    for tick in range(iterations):
        for modality in SensorModality:
            bus.publish(
                SensorSample(
                    modality=modality,
                    observed_at=clock.now(),
                    quality=Probability(0.9),
                    payload={"tick": tick},
                )
            )
        start = time.perf_counter_ns()
        bus.acquire(TickId(tick))
        fusion_samples.append((time.perf_counter_ns() - start) / _NANOSECONDS_PER_MILLISECOND)
        clock.advance(period)

    # L7a and L8 -- the deterministic safety spine. Measured on a nominal state
    # so the figures reflect the PASS path, which is the one taken every tick.
    shield = HardSafetyShield(settings.shield)
    machine = FailSafeStateMachine(settings.failsafe)
    space = ActuationSpace((ActuationChannel("throttle", 0.0, 1.0, "1"),))
    proposal = ProposedCommand(
        tick=TickId(0),
        proposed_at=Instant(0, Timeline.SIMULATED),
        command=ControlCommand(space, (0.5,)),
        origin=CommandOrigin.PROPOSED,
        source=ComponentId(LayerId.L4_CORE_A_CMDP),
    )
    state = estimator.update_fast(_frame(0, period))
    degradation = SlowStateEstimate(
        tick=TickId(0),
        valid_at=Instant(0, Timeline.SIMULATED),
        mean=(0.85, 0.0, 1.0),
        covariance=SymmetricMatrix.from_diagonal([0.01, 0.01, 0.01]),
    )

    shield_samples: list[float] = []
    machine_samples: list[float] = []
    for tick in range(iterations):
        start = time.perf_counter_ns()
        verdict = shield.evaluate(
            tick=TickId(tick), proposal=proposal, state=state, degradation=degradation
        )
        shield_samples.append((time.perf_counter_ns() - start) / _NANOSECONDS_PER_MILLISECOND)

        combined_verdict = SafetyVerdict(tick=TickId(tick), gate_verdicts=(verdict,))
        start = time.perf_counter_ns()
        machine.observe(tick=TickId(tick), verdict=combined_verdict)
        machine_samples.append((time.perf_counter_ns() - start) / _NANOSECONDS_PER_MILLISECOND)

    combined = [
        fusion + estimation + shield_cost + machine_cost
        for fusion, estimation, shield_cost, machine_cost in zip(
            fusion_samples, estimation_samples, shield_samples, machine_samples, strict=True
        )
    ]
    return [
        _summarise("L1 acquire (fusion)", fusion_samples, _L1_BUDGET_MS),
        _summarise("L2 update_fast (UKF)", estimation_samples, _L2_BUDGET_MS),
        _summarise("L7a shield (3 bounds)", shield_samples, _L7_BUDGET_MS),
        _summarise("L8 fail-safe FSM", machine_samples, _L8_BUDGET_MS),
        _summarise("hot path so far", combined, _END_TO_END_BUDGET_MS),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark and print the report.

    Args:
        argv: Argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` if every stage is inside its budget, ``1`` otherwise, so the
        benchmark can gate a build if anyone chooses to wire it in.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--environment", "-e", default="simulation")
    parser.add_argument("--iterations", "-n", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=11)
    arguments = parser.parse_args(argv)

    results = measure(
        environment=arguments.environment,
        iterations=arguments.iterations,
        seed=arguments.seed,
    )

    print(f"host      {platform.platform()} / {platform.machine()}")
    print(f"python    CPython {platform.python_version()}")
    print(f"config    {arguments.environment}")
    print(f"samples   {arguments.iterations} per stage, after {_WARMUP_TICKS} warm-up ticks")
    print()
    print("SOFTWARE measurement. NOT the 1.25 us analytical hardware WCET bound,")
    print("which a Python prototype cannot measure and must never be quoted as.")
    print()
    print(f"  {'stage':<24}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}{'budget':>9}   ")
    for result in results:
        verdict = "within" if result.within_budget else "OVER"
        print(
            f"  {result.label:<24}{result.p50:>9.3f}{result.p95:>9.3f}"
            f"{result.p99:>9.3f}{result.maximum:>9.3f}{result.budget:>9.1f}   {verdict}"
        )
    print("\n  all figures in milliseconds")

    return 0 if all(result.within_budget for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
