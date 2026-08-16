"""Single channel against three, clean and lied to, in one table.

Why this exists
-----------------
E-152 and E-153 are the strongest measurements this project has: driven by three
position channels instead of one, the clean run improves six-fold, and a 1 m
bias injected into one channel **never reaches the estimator at all**.

Both rows cited a command that does not produce them. ``benchmarks/redundancy``
prints the *shadow* residual monitor -- a different measurement, of a mechanism
with no authority -- and the figures actually came from calling
``drive_closed_loop`` with ``single_channel`` toggled, which lived in nobody's
script. A verification pass on 16 August 2026 found this by running the cited
command and not recognising the output.

**A number whose command cannot be re-run is not evidence.** This is that
command.

What the four arms are for
----------------------------
The table is a 2x2 and every cell earns its place::

                     clean            1 m bias on one channel
    single channel   the baseline     what the fault costs when nothing outvotes it
    redundant        the improvement  what the fault costs when something does

Read it **across the bottom row**. If the two redundant cells agree, the biased
vehicle and the healthy one are indistinguishable, which is what outvoting a
liar looks like when it works. Read it **down the left column** and you get the
cost of the fault without redundancy, which is the thing being fixed.

Peak estimator error, and why it is not the deviation
-------------------------------------------------------
Two quantities, and conflating them hides the mechanism:

``final |dev|``
    Where the vehicle ended up. A *control* outcome -- it includes the
    controller successfully compensating for a corrupted estimate.

``peak est err``
    The largest gap between the filter's ``position_y`` and the plant's truth.
    An *estimator* outcome. This is the one that says whether the lie arrived.

A fault can leave the deviation small while the estimate is badly wrong, which
is precisely OD-9's shape: the proposer closes the loop on the corrupted number
and drives *it* to zero. So the estimator column is the honest one, and it is
read from ``record.fast_state.mean[1]`` against ``TickSample.lane_deviation_m``.

Two earlier probes silently returned ``nan`` here, having guessed at field names
that do not exist on ``TickSample``. If this tool ever prints ``nan``, the
layout moved and the answer is to look, not to report around it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from astra.layers.l4_proposer.learned import LearnedPolicy
from training.closed_loop import CHANNEL_SIGMAS, TickSample, drive_closed_loop
from training.faults import FaultChannel, FaultInjector, bias

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["ArmReading", "NoEstimateError", "estimator_error", "measure", "render"]

_DEFAULT_TICKS: Final = 400
_DEFAULT_OPEN_AT: Final = 200
_DEFAULT_SEED: Final = 20260809
_DEFAULT_BIAS_M: Final = 1.0
_DEFAULT_POLICY: Final = Path("var/policy/synthetic.pt")

_AGREEMENT_M: Final = 1e-4
"""Below this the two redundant arms are quoted as agreeing.

Four decimals is the precision E-153 states its result to, and the claim being
made is exactly that the biased and healthy arms are indistinguishable at it."""

_POSITION_Y: Final = 1
"""Index of ``position_y`` in ``FAST_STATE_FIELDS`` -- ``[px, py, v, psi, a_lat]``."""


class NoEstimateError(RuntimeError):
    """Raised when an arm produced no state estimate on any tick.

    Same shape as ``whiteness.StationaryVehicleError`` and the exchangeability
    benchmark's sample floor: **refuse to report from a configuration where the
    measurement is meaningless**, rather than reporting a number that is
    arithmetically correct and says nothing.

    An empty error set would otherwise reduce to a peak of zero, which reads as
    a perfect estimator.
    """


@dataclass(frozen=True, slots=True)
class ArmReading:
    r"""One arm of the 2x2.

    Attributes:
        label: Human-readable arm name.
        single_channel: Whether this arm drove from one channel or three.
        faulted: Whether a bias was injected.
        peak_estimator_error_m: Largest \\|estimate - truth\\| over the run.
        final_deviation_m: \\|lane deviation\\| after the last tick.
        vetoed: Ticks on which the aggregate verdict was blocking.
        final_speed_mps: The plant's speed at the end.
    """

    label: str
    single_channel: bool
    faulted: bool
    peak_estimator_error_m: float
    final_deviation_m: float
    vetoed: int
    final_speed_mps: float


def estimator_error(sample: TickSample) -> float | None:
    """Return the filter's lateral error against the plant's truth, signed.

    ``fast_state`` is optional on the record: a tick that produced no corrected
    update has no estimate, and there is nothing to compare. Those ticks are
    skipped rather than counted as zero error -- treating a missing estimate as
    a perfect one is the fail-open shape this project keeps finding, and here it
    would flatter the very column that carries the claim.

    Args:
        sample: One tick of a driven run.

    Returns:
        ``estimate - truth`` in metres, or ``None`` if this tick has no
        estimate. Both quantities are signed, so the sign says which side of the
        truth the filter sits on.
    """
    estimate = sample.record.fast_state
    if estimate is None:
        return None
    return float(estimate.mean[_POSITION_Y]) - float(sample.lane_deviation_m)


def _injector(*, open_at: int, ticks: int, offset: float, seed: int) -> FaultInjector:
    """Return an injector that biases one position channel from ``open_at``."""
    return FaultInjector(
        (
            bias(
                FaultChannel.POSITION_Y,
                first_tick=open_at,
                last_tick=ticks - 1,
                offset=offset,
            ),
        ),
        seed=seed,
        sigmas=CHANNEL_SIGMAS,
    )


def measure(
    *, ticks: int, open_at: int, seed: int, offset: float, policy: Path
) -> list[ArmReading]:
    """Drive all four arms and read both outcome quantities from each.

    Every arm shares the seed, so the arms differ by the two variables under
    test and by nothing else.

    Args:
        ticks: Ticks per arm.
        open_at: The tick the bias opens on.
        seed: Shared plant seed.
        offset: The injected bias, in metres.
        policy: The trained proposer checkpoint.

    Returns:
        Four readings: single/clean, single/faulted, redundant/clean,
        redundant/faulted.
    """
    readings: list[ArmReading] = []
    for single in (True, False):
        for faulted in (False, True):
            samples: list[TickSample] = []
            result = drive_closed_loop(
                policy=LearnedPolicy.load(policy),
                ticks=ticks,
                seed=seed,
                observer=samples.append,
                fault=(
                    _injector(open_at=open_at, ticks=ticks, offset=offset, seed=seed)
                    if faulted
                    else None
                ),
                single_channel=single,
            )
            errors = [abs(e) for sample in samples if (e := estimator_error(sample)) is not None]
            if not errors:
                message = (
                    f"no tick of the {'single-channel' if single else 'redundant'} arm "
                    "produced a state estimate, so there is nothing to compare against "
                    "the truth. Reporting a peak error of zero here would be a fail-open "
                    "reading of an absent measurement."
                )
                raise NoEstimateError(message)
            readings.append(
                ArmReading(
                    label=("single channel" if single else "redundant")
                    + (f" / {offset:.0f} m bias" if faulted else " / clean"),
                    single_channel=single,
                    faulted=faulted,
                    peak_estimator_error_m=max(errors),
                    final_deviation_m=abs(result.final_absolute_deviation_m),
                    vetoed=result.vetoed,
                    final_speed_mps=result.final_speed_mps,
                )
            )
    return readings


def render(readings: Sequence[ArmReading], *, offset: float) -> list[str]:
    """Return the table and the one comparison that carries the claim.

    Args:
        readings: The four arms, in the order :func:`measure` returns them.
        offset: The injected bias, for the verdict text.

    Returns:
        Printable lines.
    """
    lines = [
        "",
        f"Driven arms -- one position channel against three, with and without a {offset:.0f} m lie",
        "=" * 86,
        f"  {'arm':<28}{'peak est err':>15}{'final |dev|':>14}{'vetoes':>9}{'final m/s':>12}",
        f"  {'-' * 28}{'-' * 14:>15}{'-' * 13:>14}{'-' * 8:>9}{'-' * 11:>12}",
    ]
    lines.extend(
        f"  {reading.label:<28}{reading.peak_estimator_error_m:>15.4f}"
        f"{reading.final_deviation_m:>14.4f}{reading.vetoed:>9}"
        f"{reading.final_speed_mps:>12.4f}"
        for reading in readings
    )

    by_key = {(r.single_channel, r.faulted): r for r in readings}
    redundant_clean = by_key[False, False]
    redundant_faulted = by_key[False, True]
    single_faulted = by_key[True, True]

    lines.append("")
    outvoted = abs(
        redundant_faulted.final_deviation_m - redundant_clean.final_deviation_m
    ) < _AGREEMENT_M
    if outvoted:
        lines.extend(
            [
                "  The two redundant arms agree to four decimals: under redundancy the",
                "  biased vehicle and the healthy one are INDISTINGUISHABLE. That is what",
                "  outvoting a liar looks like when it works, and it is a stronger",
                "  statement than 'the error got smaller'.",
                "",
                (
                    f"  Without it the same lie costs "
                    f"{single_faulted.final_deviation_m:.4f} m of lane position and puts"
                ),
                f"  {single_faulted.peak_estimator_error_m:.4f} m of error into the estimate.",
            ]
        )
    else:
        lines.extend(
            [
                "  The redundant arms DIFFER. The bias is reaching the estimator, which",
                "  is the behaviour ADR-0033 was adopted to remove -- check the channel",
                "  count and the sigmas before reading anything else here.",
            ]
        )
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
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--open-at", type=int, default=_DEFAULT_OPEN_AT)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--bias", type=float, default=_DEFAULT_BIAS_M)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    arguments = parser.parse_args(argv)

    if not arguments.policy.exists():
        print(f"missing {arguments.policy}; run `make artifacts` first")
        return 1

    readings = measure(
        ticks=arguments.ticks,
        open_at=arguments.open_at,
        seed=arguments.seed,
        offset=arguments.bias,
        policy=arguments.policy,
    )
    for line in render(readings, offset=arguments.bias):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
