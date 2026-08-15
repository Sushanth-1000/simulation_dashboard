"""Is the innovation *sequence* white? The fifth candidate against the slow drift.

What has already been refuted, and why this is not a repeat
------------------------------------------------------------
Four detectors have been measured against ``position_drift`` and four are
silent. It matters exactly what each one tested:

``E-53``
    The innovation sequence. *"Ramping 2 m over 200 ticks is 1 cm per tick
    against a declared sigma of 0.1 m, so every step is well inside what the
    filter expects and the innovation never leaves its band."* A **magnitude**
    test, per tick.

``E-105``
    The innovation gate at ``gamma = 7.5``. Also a **magnitude** test, and it
    flagged tick 0 of every arm including the control.

``E-94``
    Analytical redundancy from the issued commands. Refuted structurally: FB1
    feeds the command into the filter's prediction step, so the two estimates
    were never independent (E-95).

``E-106``
    Cross-channel consistency. Caught the bias at 4.14x and sat at **0.99x** on
    the drift.

Both innovation candidates asked *"is this innovation too large?"*. **Neither
asked whether the sequence is white**, and that is a different question with a
different answer. A correctly tuned filter produces innovations that are
zero-mean and serially uncorrelated; that is the standard optimality property.
A slow drift injects a **small persistent one-sided bias** into them. Every
sample stays inside the band -- E-53 is right about that and this benchmark does
not dispute it -- while the *signs* stop being a fair coin.

That is what a CUSUM accumulates. N samples with a mean offset of ``d`` standard
deviations sum to ``sqrt(N) * d`` standard deviations of separation, so a bias
far too small to trip any per-tick threshold becomes detectable given enough
ticks. Whether ``d`` is large enough here, on a filter whose estimate is being
dragged toward the lie, is precisely the empirical question -- and it is the
question E-107 answered with an argument rather than a measurement.

The claim under test
---------------------
E-107 states it: *"a self-consistent lie slower than the sensor noise cannot be
distinguished from truth by any function of a single sensor chain."* This
benchmark is an honest attempt to falsify a claim this project made. If the
CUSUM separates, E-107 is too strong and must be narrowed. If it does not, E-107
gains its fourth independent confirmation and the argument for redundancy gets
stronger rather than weaker.

Either outcome is worth the run. The one thing that would not be worth it is
asserting the conclusion again without measuring.

The quantity this reads is computed and archived nowhere
----------------------------------------------------------
``InnovationRecord`` carries ``residual`` -- the **signed** measurement residual,
one element per observed dimension -- and ``mahalanobis_distance``, its norm.
**Only the norm is consumed.** The gates read it, the Trust Index reads it, the
audit record carries it from schema 3, and nothing anywhere reads the signed
vector. A norm is non-negative by construction, so the archive has thrown away
exactly the sign information a whiteness test needs, on every run ever recorded.

That is the sixth instance of the shape behind audit schemas 3, 5, 7, 8 and 10.
This benchmark therefore reaches into the estimator directly, which is what a
shadow measurement is for: nothing is wired, and if the detector earns its place
the archive has to change first.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.fault_study import SCENARIOS
from training.closed_loop import CHANNEL_SIGMAS, drive_closed_loop
from training.faults import FaultInjector

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["ArmReading", "Whiteness", "cusum", "evaluate", "render"]

_DEFAULT_TICKS: Final = 400
_DEFAULT_OPEN_AT: Final = 200
_DEFAULT_SEED: Final = 20260731
_DEFAULT_POLICY: Final = Path("artifacts/policy/policy.json")
_DEFAULT_OUTPUT: Final = Path("artifacts/whiteness")

COMPONENTS: Final = ("position_y", "speed", "lateral_acceleration")
"""The fast measurement's layout, from the closed loop's extractor."""

CUSUM_SLACK: Final = 0.5
"""Slack ``k``, in standard deviations. The textbook choice for detecting a
mean shift of ``2k``; it is what stops a zero-mean sequence from random-walking
into an alarm."""

_MINIMUM_SAMPLES: Final = 2
"""Below this a standard deviation is undefined, not small."""

_DEGENERATE_VARIANCE: Final = 1e-18
"""A spread at or below this would divide later arms by ~0 and manufacture a
detection out of arithmetic."""

CUSUM_THRESHOLD: Final = 5.0
"""Alarm threshold ``h``, in standard deviations. Chosen before any faulted arm
was run, and the control arm is reported against it so a reader can see whether
it was chosen to flatter the result."""


@dataclass(frozen=True, slots=True)
class Whiteness:
    """One component's whiteness statistics over the fault window.

    Attributes:
        component: Which measured dimension.
        mean_sigmas: Mean residual in units of the control run's standard
            deviation. The quantity a per-tick magnitude test cannot see.
        peak_cusum: The largest two-sided CUSUM excursion, in sigmas.
        detected_at: Ticks after the fault opened at which the CUSUM first
            crossed the threshold, or ``None``.
        longest_run: The longest run of same-signed residuals. A white sequence
            gives about ``log2(N)``; persistence gives far more.
        majority_sign_fraction: Fraction of ticks sharing the dominant sign.
            0.5 for a fair coin.
    """

    component: str
    mean_sigmas: float
    peak_cusum: float
    detected_at: int | None
    longest_run: int
    majority_sign_fraction: float


@dataclass(frozen=True, slots=True)
class ArmReading:
    """One fault arm's whiteness across every component."""

    arm: str
    components: tuple[Whiteness, ...]


def cusum(samples: Sequence[float], *, slack: float, threshold: float) -> tuple[float, int | None]:
    """Return the peak two-sided CUSUM excursion and the first crossing.

    Args:
        samples: The residual sequence, already normalised to standard
            deviations of the healthy run.
        slack: ``k``. Deviations smaller than this are absorbed rather than
            accumulated, which is what keeps a white sequence flat.
        threshold: ``h``. The excursion at which an alarm is declared.

    Returns:
        The largest excursion in either direction, and the index of the first
        crossing, or ``None`` if it never crossed.
    """
    high = 0.0
    low = 0.0
    peak = 0.0
    detected: int | None = None
    for index, sample in enumerate(samples):
        high = max(0.0, high + sample - slack)
        low = min(0.0, low + sample + slack)
        excursion = max(high, -low)
        peak = max(peak, excursion)
        if detected is None and excursion > threshold:
            detected = index
    return peak, detected


def _longest_run(samples: Sequence[float]) -> int:
    """Return the longest run of same-signed samples."""
    longest = 0
    current = 0
    previous = 0.0
    for sample in samples:
        if sample == 0.0:
            current = 0
        elif previous != 0.0 and (sample > 0) == (previous > 0):
            current += 1
        else:
            current = 1
        previous = sample
        longest = max(longest, current)
    return longest


def _majority_fraction(samples: Sequence[float]) -> float:
    """Return the fraction of samples sharing the dominant sign."""
    if not samples:
        return 0.0
    positive = sum(1 for sample in samples if sample > 0)
    return max(positive, len(samples) - positive) / len(samples)


def _standard_deviation(samples: Sequence[float]) -> float:
    """Return the sample standard deviation, or one if it is degenerate."""
    if len(samples) < _MINIMUM_SAMPLES:
        return 1.0
    mean = sum(samples) / len(samples)
    variance = sum((sample - mean) ** 2 for sample in samples) / (len(samples) - 1)
    # A degenerate spread would divide every later arm by ~0 and manufacture a
    # detection out of arithmetic. One leaves the residuals in their own units,
    # which is visibly wrong in the report rather than invisibly wrong.
    return math.sqrt(variance) if variance > _DEGENERATE_VARIANCE else 1.0


def _residuals(
    *,
    fault: FaultInjector | None,
    ticks: int,
    seed: int,
    policy: LearnedPolicy | None,
) -> list[tuple[float, ...]]:
    """Drive one arm and collect the signed innovation residual per tick.

    Reaches the estimator directly. The residual is computed on every corrected
    update and consumed by nothing -- only its norm reaches the gates and the
    archive -- so there is no wired path to read it from, and inventing one
    before the detector has earned its place would be backwards.

    Args:
        fault: The injector for this arm, or ``None`` for the control.
        ticks: How many control ticks to run.
        seed: The plant seed, shared across arms so they differ only by fault.
        policy: The trained proposer, or ``None`` for the placeholder.

    Returns:
        One signed residual vector per tick that produced a corrected update.
    """
    collected: list[tuple[float, ...]] = []
    holder: dict[str, Any] = {}

    def capture(_sample: object) -> None:
        estimator = holder["estimator"]
        innovation = estimator.latest_innovation()
        if innovation is not None:
            collected.append(tuple(innovation.residual))

    def remember(assembled: Any) -> None:  # noqa: ANN401
        holder["estimator"] = assembled.pipeline._estimator  # noqa: SLF001

    drive_closed_loop(
        policy=policy,
        ticks=ticks,
        seed=seed,
        fault=fault,
        observer=capture,
        on_assembled=remember,
    )
    return collected


def evaluate(
    *, ticks: int, open_at: int, seed: int, policy: LearnedPolicy | None
) -> list[ArmReading]:
    """Measure innovation whiteness on the control and every fault arm.

    The control arm sets the scale. Each component is normalised by the standard
    deviation the *healthy* run produced over the same window, which is how a
    deployment would calibrate this monitor and is the only normalisation that
    does not let a faulted arm set its own yardstick.

    Args:
        ticks: Total control ticks per arm.
        open_at: The tick each fault opens on. Statistics are taken from here.
        seed: Shared plant seed.
        policy: The trained proposer.

    Returns:
        The control reading first, then one per scenario.
    """
    control = _residuals(fault=None, ticks=ticks, seed=seed, policy=policy)
    windowed = control[open_at:]
    scales = [
        _standard_deviation([row[index] for row in windowed if index < len(row)])
        for index in range(len(COMPONENTS))
    ]

    def reading(name: str, rows: list[tuple[float, ...]]) -> ArmReading:
        window = rows[open_at:]
        stats: list[Whiteness] = []
        for index, component in enumerate(COMPONENTS):
            samples = [row[index] / scales[index] for row in window if index < len(row)]
            peak, detected = cusum(samples, slack=CUSUM_SLACK, threshold=CUSUM_THRESHOLD)
            stats.append(
                Whiteness(
                    component=component,
                    mean_sigmas=(sum(samples) / len(samples)) if samples else 0.0,
                    peak_cusum=peak,
                    detected_at=detected,
                    longest_run=_longest_run(samples),
                    majority_sign_fraction=_majority_fraction(samples),
                )
            )
        return ArmReading(arm=name, components=tuple(stats))

    readings = [reading("control", control)]
    for scenario in SCENARIOS:
        rows = _residuals(
            fault=FaultInjector(
                scenario.build(open_at, ticks - 1), seed=seed, sigmas=CHANNEL_SIGMAS
            ),
            ticks=ticks,
            seed=seed,
            policy=policy,
        )
        readings.append(reading(scenario.name, rows))
    return readings


def render(readings: Sequence[ArmReading]) -> list[str]:
    """Return the comparison table and the verdict it supports.

    Args:
        readings: The control reading first, then the fault arms.

    Returns:
        Printable lines.
    """
    lines = [
        "",
        "Innovation whiteness -- does the SEQUENCE betray what no single sample does?",
        "=" * 88,
        (
            f"  CUSUM slack k = {CUSUM_SLACK} sigma, alarm h = {CUSUM_THRESHOLD} sigma,"
            " both fixed before the faulted arms ran"
        ),
        "",
        f"{'arm':<17}{'component':<22}{'mean':<9}{'peak':<10}{'alarm':<9}{'run':<7}{'sign'}",
        "-" * 88,
    ]
    for entry in readings:
        for index, component in enumerate(entry.components):
            arm = entry.arm if index == 0 else ""
            alarm = "--" if component.detected_at is None else f"+{component.detected_at}"
            lines.append(
                f"{arm:<17}{component.component:<22}{component.mean_sigmas:>+7.3f}  "
                f"{component.peak_cusum:>8.2f}  {alarm:<9}{component.longest_run:<7}"
                f"{component.majority_sign_fraction:.2f}"
            )
        lines.append("")
    lines.append("-" * 88)

    control = readings[0]
    control_alarmed = any(c.detected_at is not None for c in control.components)
    drift = next((r for r in readings if r.arm == "position_drift"), None)
    if drift is not None:
        alarmed = [c for c in drift.components if c.detected_at is not None]
        if alarmed and not control_alarmed:
            first = min(c.detected_at or 0 for c in alarmed)
            lines.extend(
                [
                    "",
                    f"position_drift ALARMS at +{first} ticks and the control does not.",
                    "  E-107 said no function of a single sensor chain can separate this.",
                    "  That claim is too strong and must be narrowed -- see the ADR.",
                ]
            )
        elif control_alarmed:
            lines.extend(
                [
                    "",
                    "The CONTROL alarms. Whatever the faulted arms do, this threshold is",
                    "  useless: a monitor that fires on a healthy run is E-105 again.",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "position_drift does NOT alarm. E-107 gains a fourth confirmation:",
                    "  a self-consistent lie slower than the sensor noise cannot be found",
                    "  by any function of a single sensor chain -- now including the one",
                    "  statistic the earlier candidates had not tried.",
                ]
            )
    return lines


def sweep(*, ticks: int, open_at: int, seed: int, policy: LearnedPolicy | None) -> list[str]:
    """Sweep the CUSUM slack and report separation against the clean run.

    **A detector that only works at a slack chosen after seeing the fault is not
    a detector**, so this follows E-94's precedent and sweeps the free parameter
    rather than quoting one value. Two things have to be true at the same slack:
    the faulted peak must clear the clean peak by a wide margin, *and* the clean
    peak must be measured with the **startup transient included**. The plant
    starts up to 1 m off centre and corrects, which is a sustained one-sided
    manoeuvre -- the same shape a fault response has (E-96) -- so a threshold
    set from a cruise-only window would fire on every launch.

    Args:
        ticks: Total control ticks per arm.
        open_at: The tick each fault opens on.
        seed: Shared plant seed.
        policy: The trained proposer, or ``None`` for the placeholder.

    Returns:
        Printable lines: the separation table, then the false-alarm surface.
    """
    position = COMPONENTS.index("position_y")
    control = _residuals(fault=None, ticks=ticks, seed=seed, policy=policy)
    faults = {
        scenario.name: _residuals(
            fault=FaultInjector(
                scenario.build(open_at, ticks - 1), seed=seed, sigmas=CHANNEL_SIGMAS
            ),
            ticks=ticks,
            seed=seed,
            policy=policy,
        )
        for scenario in SCENARIOS
        if scenario.name in {"position_drift", "position_bias"}
    }
    scale = _standard_deviation([row[position] for row in control[open_at:]])

    def series(rows: Sequence[tuple[float, ...]], start: int) -> list[float]:
        return [row[position] / scale for row in rows[start:]]

    lines = [
        "",
        "position_y innovation -- CUSUM peak against the slack k",
        "=" * 78,
        f"{'k':<8}{'clean':<10}{'drift':<10}{'ratio':<10}{'bias':<10}{'separates'}",
        "-" * 78,
    ]
    for slack in _SWEEP_SLACKS:
        clean, _ = cusum(series(control, open_at), slack=slack, threshold=math.inf)
        drift, _ = cusum(series(faults["position_drift"], open_at), slack=slack, threshold=math.inf)
        bias, _ = cusum(series(faults["position_bias"], open_at), slack=slack, threshold=math.inf)
        ratio = drift / clean if clean else math.inf
        lines.append(
            f"{slack:<8.2f}{clean:<10.2f}{drift:<10.2f}{ratio:<10.2f}{bias:<10.2f}"
            f"{'YES' if ratio > _SEPARATION else 'no'}"
        )

    lines.extend(
        [
            "-" * 78,
            "",
            "The false-alarm surface a cruise-only window hides (E-96):",
            "  the same clean run, measured from tick 0 so the startup manoeuvre counts",
            "",
            (
                f"{'k':<8}{'clean 0..N':<14}{'clean cruise':<16}"
                f"{'inflation':<12}{'threshold must clear'}"
            ),
            "-" * 78,
        ]
    )
    for slack in _SWEEP_SLACKS[2:]:
        full, _ = cusum(series(control, 0), slack=slack, threshold=math.inf)
        cruise, _ = cusum(series(control, open_at), slack=slack, threshold=math.inf)
        lines.append(
            f"{slack:<8.2f}{full:<14.2f}{cruise:<16.2f}"
            f"{(full / cruise if cruise else 0):<12.2f}{full:.2f}"
        )
    lines.append("-" * 78)
    return lines


_SWEEP_SLACKS: Final = (0.50, 0.40, 0.30, 0.25, 0.20, 0.15, 0.10, 0.05, 0.02)
"""Slack values swept. Descending, so a reader sees the textbook 0.5 fail first
and can watch where separation begins rather than being shown only the winner."""

_SEPARATION: Final = 3.0
"""The faulted-to-clean ratio at which separation is called. Three is the figure
E-94 could not reach on any window, quoted here so the two measurements are
being judged against the same bar."""


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero unless the policy checkpoint is missing. A refuted detector is a
        result, not a failure.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--open-at", type=int, default=_DEFAULT_OPEN_AT)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    parser.add_argument("--output", "-o", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="sweep the CUSUM slack instead of running one setting",
    )
    arguments = parser.parse_args(argv)

    policy = LearnedPolicy.load(arguments.policy) if arguments.policy.exists() else None
    if policy is None:
        print(f"NO POLICY at {arguments.policy}; running the placeholder proposer.")
        print("  The four earlier refutations (E-53, E-94, E-105, E-106) used the")
        print("  trained one, so absolute figures are NOT comparable with them.")
        print("  Control and faulted arms share this proposer, so the separation")
        print("  between them is still internally valid.")

    if arguments.sweep:
        for line in sweep(
            ticks=arguments.ticks,
            open_at=arguments.open_at,
            seed=arguments.seed,
            policy=policy,
        ):
            print(line)
        return 0

    readings = evaluate(
        ticks=arguments.ticks,
        open_at=arguments.open_at,
        seed=arguments.seed,
        policy=policy,
    )
    for line in render(readings):
        print(line)

    arguments.output.mkdir(parents=True, exist_ok=True)
    (arguments.output / "whiteness.json").write_text(
        json.dumps(
            {
                "ticks": arguments.ticks,
                "open_at": arguments.open_at,
                "seed": arguments.seed,
                "cusum_slack": CUSUM_SLACK,
                "cusum_threshold": CUSUM_THRESHOLD,
                "arms": [asdict(reading) for reading in readings],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
