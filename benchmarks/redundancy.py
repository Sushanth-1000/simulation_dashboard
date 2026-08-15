"""Can a second sensor see the lie that four other mechanisms could not?

Why this exists
----------------
Four independent mechanisms have now been measured against a slow position drift
and all four are silent: the innovation sequence (E-53), the innovation gate's
own flag (E-105), analytical redundancy from a command-only estimate (E-94), and
cross-channel consistency (E-106). Each fails for one shared reason:

    **A self-consistent lie slower than the sensor noise cannot be distinguished
    from truth by any function of a single sensor chain.**

Every quantity on the decision record is downstream of the same measurement, and
no rearrangement of downstream quantities creates information that was never
upstream. So the only remaining answer is to put *new information* in: a second
sensor that measures the same quantity and can disagree.

The thing that has been called a Phase 7 blocker three times, and is not
-------------------------------------------------------------------------
Every one of those refutations closed with the same sentence: *unmeasurable
here, because the reference plant publishes one ground truth to all five
modalities.* That was true and it was **half the story**, because two facts made
it true and both live in the harness rather than in physics:

1. ``_publish_state`` computes **one payload** and publishes it, byte-identical,
   to all five modalities.
2. ``_Extractor.extract_fast`` reads **the IMU only** and discards the other
   four entirely.

So the prototype has five sensor modalities and **one sensor**. That is a
property of thirty lines of test harness, not of the architecture: the core
already carries per-modality samples in :class:`FusedSensorFrame`, and the
``MeasurementExtractor`` is an injectable port. Nothing in ``src/`` needed to
change to run this.

**What still needs CARLA** is unchanged and worth stating so this does not
overclaim: real sensor models with real failure modes, real imagery for the
adversarial scenario, and a plant this project did not author, so the numbers
stop being self-referential. Redundancy can be *demonstrated* here. Its accuracy
against real faults still cannot.

How the measurement stays honest
---------------------------------
**Bit-identity is preserved.** The extra readings are drawn from a **separately
seeded** generator, so the IMU's own noise stream is untouched and a run with
redundancy configured but unused is identical to one without it. The precedent
is ``training/faults.py``, whose injector draws from its own offset seed for the
same reason -- an instrument that perturbs the thing it measures is not an
instrument.

**The monitor has no authority.** It records residuals and returns numbers. No
verdict changes, nothing escalates. That is the standing convention, and it has
now refuted four candidates that argued well.

**The fault goes into one channel.** That is the whole point: an injector that
corrupted every modality identically would be measuring nothing, because the
channels would agree with each other about the lie.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from astra.kernel.enums import SensorModality
from astra.layers.l4_proposer.learned import LearnedPolicy
from training.closed_loop import DEFAULT_CHANNEL_SIGMAS

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["CHANNELS", "Residuals", "run_arm"]

_SEED_OFFSET = 0x2ED0
"""Offset for the redundant channels' noise stream.

Drawn from a generator seeded ``seed ^ _SEED_OFFSET`` rather than from the run's
own, so adding redundant channels does not consume draws the IMU would have
taken. Without this, every recorded number in the evidence pack would shift and
a run "with redundancy off" would no longer reproduce.
"""

CHANNELS: tuple[SensorModality, ...] = (
    SensorModality.IMU,
    SensorModality.GPS,
    SensorModality.LIDAR,
)
"""The modalities that independently measure lateral position.

Three, because three is the smallest number that permits a **median** -- with
two, a disagreement tells you something is wrong and not which one. Two-out-of-
three voting is the standard automotive answer and this is its smallest form.

``CAMERA`` and ``RADAR`` are deliberately excluded: a real adapter would give
them different quantities and different rates, and pretending otherwise would
make the redundancy look better than it is.
"""

#: Per-channel measurement sigma. Deliberately **dissimilar** -- a real GNSS is
#: worse than an IMU over a second and better over a minute, and a lidar is
#: better than both in good visibility. Identical sigmas would model identical
#: sensors, which is the redundancy that fails in the field: two devices from
#: one batch drift the same way at the same temperature, and common-mode failure
#: is exactly what dissimilarity buys protection against.
SIGMAS = DEFAULT_CHANNEL_SIGMAS
"""Re-exported. Defined in ``training.closed_loop`` from 15 August 2026, because
that is the module that drives the vehicle with them (ADR-0033)."""


@dataclass(frozen=True, slots=True)
class Residuals:
    """What one arm's residual monitor saw.

    Attributes:
        name: Which arm.
        per_channel_clean: Peak ``|reading - median|`` per channel before the
            fault opened, in ``CHANNELS`` order.
        per_channel_faulted: The same after it opened.
        separation: Faulted peak over clean peak, per channel. **The faulted
            channel should separate and the others should not** -- a monitor
            where every channel separates is detecting the manoeuvre, not the
            fault.
        first_exceeded: For the faulted channel, ticks after the fault opened
            before its residual first exceeded the clean peak of any channel.
            ``None`` if it never did.
    """

    name: str
    per_channel_clean: tuple[float, ...]
    per_channel_faulted: tuple[float, ...]
    separation: tuple[float, ...]
    first_exceeded: int | None


def _readings(
    truth: float, *, generator: random.Random, faulted: SensorModality | None, offset: float
) -> dict[SensorModality, float]:
    """Return one independent position reading per channel.

    Args:
        truth: The plant's true lateral position.
        generator: The redundant channels' own noise source.
        faulted: The channel the fault is injected into, or ``None``.
        offset: The fault's current magnitude, added to the faulted channel only.

    Returns:
        A reading per channel in :data:`CHANNELS`.
    """
    return {
        channel: truth
        + generator.gauss(0.0, SIGMAS[channel])
        + (offset if channel is faulted else 0.0)
        for channel in CHANNELS
    }


def run_arm(
    *,
    name: str,
    ticks: int,
    seed: int,
    open_at: int,
    drift_per_tick: float,
    faulted: SensorModality | None,
    policy: LearnedPolicy | None,
) -> Residuals:
    """Drive one arm and measure the per-channel residuals.

    The plant is driven exactly as ``drive_closed_loop`` drives it; the redundant
    readings are generated alongside from the plant's own truth and are **not**
    fed back into the pipeline. This is a measurement of whether the information
    exists, not yet a mechanism that uses it -- the convention requires the first
    before the second.

    Args:
        name: Which arm.
        ticks: How many control ticks.
        seed: The run seed.
        open_at: The tick the drift opens on.
        drift_per_tick: Metres added to the faulted channel each tick.
        faulted: The channel to corrupt, or ``None`` for a clean arm.
        policy: The proposer.

    Returns:
        The residual measurement.
    """
    from training.closed_loop import drive_closed_loop  # noqa: PLC0415 - avoids a cycle

    truths: list[tuple[int, float]] = []
    drive_closed_loop(
        policy=policy,
        ticks=ticks,
        seed=seed,
        observer=lambda sample: truths.append((sample.tick, sample.lane_deviation_m)),
    )

    generator = random.Random(seed ^ _SEED_OFFSET)
    clean: dict[SensorModality, list[float]] = {channel: [] for channel in CHANNELS}
    after: dict[SensorModality, list[float]] = {channel: [] for channel in CHANNELS}
    first: int | None = None
    clean_ceiling = 0.0

    for tick, truth in truths:
        offset = drift_per_tick * (tick - open_at) if tick >= open_at else 0.0
        readings = _readings(truth, generator=generator, faulted=faulted, offset=offset)
        median = statistics.median(readings.values())
        for channel, reading in readings.items():
            residual = abs(reading - median)
            if tick < open_at:
                clean[channel].append(residual)
            else:
                after[channel].append(residual)
                if (
                    faulted is not None
                    and channel is faulted
                    and first is None
                    and clean_ceiling
                    and residual > clean_ceiling
                ):
                    first = tick - open_at
        if tick == open_at - 1:
            clean_ceiling = max(max(values, default=0.0) for values in clean.values())

    clean_peaks = tuple(max(clean[channel], default=0.0) for channel in CHANNELS)
    fault_peaks = tuple(max(after[channel], default=0.0) for channel in CHANNELS)
    return Residuals(
        name=name,
        per_channel_clean=clean_peaks,
        per_channel_faulted=fault_peaks,
        separation=tuple(
            (faulted_peak / clean_peak if clean_peak else 0.0)
            for clean_peak, faulted_peak in zip(clean_peaks, fault_peaks, strict=True)
        ),
        first_exceeded=first,
    )


def render(arms: Sequence[Residuals]) -> list[str]:
    """Return the report, as lines.

    Args:
        arms: One per arm, control first.

    Returns:
        Lines to print.
    """
    names = [channel.value for channel in CHANNELS]
    lines = [
        "",
        "  REDUNDANCY -- three dissimilar position channels, residual against the median.",
        "  The drift is injected into ONE channel. Reads nothing from the pipeline",
        "  and changes no verdict.",
        "",
        f"  {'arm':<22}" + "".join(f"{name:>22}" for name in names),
        f"  {'-' * 21:<22}" + "".join(f"{'-' * 21:>22}" for _ in names),
    ]
    for arm in arms:
        cells = "".join(
            f"{f'{clean:.3f}->{faulted:.3f} {sep:.1f}x':>22}"
            for clean, faulted, sep in zip(
                arm.per_channel_clean, arm.per_channel_faulted, arm.separation, strict=True
            )
        )
        lines.append(f"  {arm.name:<22}{cells}")
    lines.append("")
    for arm in arms:
        if arm.first_exceeded is not None:
            lines.append(
                f"  {arm.name}: the faulted channel's residual left every clean channel's"
                f" band at +{arm.first_exceeded} ticks."
            )
        elif arm.name != "control":
            lines.append(f"  {arm.name}: the faulted channel never left the clean band.")
    lines.extend(
        [
            "",
            "  Read the OTHER channels' separation, not just the faulted one. A run",
            "  where every channel separates is detecting the manoeuvre rather than",
            "  the fault, and would be a false alarm wearing a result's clothes.",
        ]
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero unless the policy checkpoint is missing.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", "-n", type=int, default=400)
    parser.add_argument("--open-at", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument("--drift-per-tick", type=float, default=0.01)
    parser.add_argument("--policy", type=Path, default=Path("var/policy/synthetic.pt"))
    arguments = parser.parse_args(argv)

    if not arguments.policy.exists():
        print(f"missing {arguments.policy}; see docs/EVIDENCE.md for how to regenerate it")
        return 1

    policy = LearnedPolicy.load(arguments.policy)
    shared: dict[str, Any] = {
        "ticks": arguments.ticks,
        "seed": arguments.seed,
        "open_at": arguments.open_at,
        "drift_per_tick": arguments.drift_per_tick,
        "policy": policy,
    }
    arms = [
        run_arm(name="control", faulted=None, **shared),
        run_arm(name="drift on IMU", faulted=SensorModality.IMU, **shared),
        run_arm(name="drift on GPS", faulted=SensorModality.GPS, **shared),
    ]
    for line in render(arms):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
