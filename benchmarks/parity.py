"""Can a second estimate, built only from commands, see a lie the sensors tell?

The problem this exists for
----------------------------
OD-9's remaining two thirds. ADR-0024 closed the case where a channel goes
**quiet** -- ``StreamHealth`` sees that at the sensor boundary, before the filter
touches anything. It does nothing for a channel that lies *fluently*: a constant
offset, a slow ramp, a value frozen at its last good reading. Those keep the
stream perfectly fresh, and each per-tick step sits inside what the filter
expects, so every mechanism in the system reports normality. Measured, the slow
drift still ends **2.025 m** out with every detector silent (E-90).

The general answer is a second sensor that can disagree with the first. This
repository cannot buy one -- the reference plant publishes one ground truth to
all five modalities, so it is structurally incapable of disagreeing with itself.

**But there is a second source of truth that is not a sensor at all.** The system
knows exactly what it commanded. That is not a measurement, it is a fact about
its own output. Feed those commands through the process model and you get an
estimate of where the vehicle should be that shares **no channel** with the
sensors. Compare it against the filtered estimate and a disagreement is
information about the sensors.

This is **analytical redundancy**, and the technique is not new -- parity-space
and dedicated-observer fault detection are forty years old in control
engineering. What would have been new is where it sits: no runtime-assurance
stack in this project's prior-art table carries one, and here the output would
feed a *graduated posture machine* rather than a binary fault flag.

Why a disagreement should have meant something
------------------------------------------------
Follow what a position drift does. The fault adds a ramp to the *reading*. The
filter believes the reading. The controller steers to bring the reading back to
zero -- so it issues a **sustained, one-sided steering command**, and the vehicle
genuinely turns. Truth walks away from the lane centre while the estimate sits
on it.

So the two estimates should say incompatible things:

- The filtered estimate says *"I am at the lane centre and have been all along."*
- The open-loop propagation says *"you have commanded lateral acceleration in one
  direction for two hundred ticks; you cannot possibly be at the centre."*

Under nominal lane-keeping the commanded acceleration oscillates about zero, so
the propagation should stay near the filtered estimate and there is nothing to
report.

**That argument is wrong, and the measurement found the hole in it.** See the
verdict below.

Why the propagation is re-anchored
------------------------------------
An open-loop propagation is uncorrected by construction, so its error grows
without bound -- OD-4 is the cautionary tale, where a dead-reckoned lateral
position reached 2.9e6 m. Left running from tick zero it would diverge on a clean
run too and the test would have no power.

So it is **re-anchored to the filtered estimate every ``WINDOW`` ticks**. Within
a window the propagation is free-running and its divergence is the statistic; at
the boundary it is reset and the accumulated error is discarded. That bounds the
nominal divergence to whatever the process model accrues over one window, which
is a stationary quantity a threshold could be set against.

The cost is stated rather than hidden: **detection latency is bounded by the
window**, because a fault opening just after an anchor has the whole window to
accumulate while one opening just before it is truncated by the reset.

The tick timeline, because this is where the last four measurements went wrong
------------------------------------------------------------------------------
``drive_closed_loop`` does, per tick ``t``::

    publish(plant state)   <- reflects the command issued at t-1
    pipeline.tick()        <- issues command_t, estimates from that publish
    plant.step(command_t)
    observer(sample_t)

So ``record_t.fast_state`` is the estimate **before** ``command_t`` was applied,
and ``record_t.issued`` is ``command_t``. The propagation therefore steps
``state_t`` forward under ``command_t`` and compares the result against
``record_{t+1}.fast_state``. Getting this off by one reads plausibly and is
wrong; it cost ADR-0020's probe four attempts (C-4 in the decision log).

What this module is not
------------------------
It has **no authority over any verdict**. It reads decision records and returns
numbers. That is the standing convention -- *no mechanism gets authority until it
has run with none* -- and it exists because two feedback loops were measured in
shadow and both broke the gate they fed, invisibly (E-39, E-40). It caught a
third thing in P2.7: the *principled* candidate detector was silent on exactly
the fault it was wanted for. A monitor that cannot change a verdict cannot
flatter itself.

**Whether this one deserved to be wired was decided by the table it produced, not
by the argument above. It produced the table, and the answer was no.**

The verdict: refuted, 11 August 2026
--------------------------------------
**It does not work, and the reason is structural rather than a matter of
tuning.** Reproduce with ``uv run python -m benchmarks.parity``.

On a healthy, cruising vehicle the parity residual accumulates at **0.022 to
0.040 m per tick of window**:

======  ============  ===========  ==========
window  startup peak  cruise peak  per tick
======  ============  ===========  ==========
10      0.551 m       0.403 m      0.0403
20      1.200 m       0.544 m      0.0272
40      2.232 m       0.895 m      0.0224
100     5.411 m       2.260 m      0.0226
======  ============  ===========  ==========

The slow drift injects **0.010 m per tick**, by construction. So the noise floor
sits **2.2x to 4.0x above the signal**, and *both grow linearly with the window*
-- the ratio is roughly constant and **no window separates them**. Swept across
six windows and three faults, the faulted peak is below the clean peak in every
cell but two, and those two are non-monotonic in the window, which is the
signature of noise rather than of signal.

Why it cannot work, which is the part worth carrying forward
--------------------------------------------------------------
The argument at the top of this file has a hole.

**The filter is not sensor-only.** FB1 feeds the issued command into the filter's
*prediction* step, so the filtered estimate and the open-loop propagation share
the same process model **and the same command input**. They differ by exactly one
thing: the measurement correction. So the parity residual is not "commands versus
sensors" at all -- it is *"how far did the measurement pull the filter"*, which
under a slow drift is precisely the drift rate and nothing more.

Meanwhile the propagation's *own* error -- heading integrated from ``a_lat / v``,
then position integrated from heading, with no correction -- accumulates several
times faster than the fault does.

**The two estimates were never independent. FB1 coupled them, and FB1 is
load-bearing**: it is the mitigation for the shared-estimate common cause and is
not removable. The idea was refuted by a feedback loop that exists to fix the
very defect this monitor was built to attack.

What the refutation points at
-------------------------------
Integration is what kills it, so the surviving idea is a check that does not
integrate: compare the **position channel against the acceleration channel**
directly. Under a position drift the IMU is honest and reports a vehicle that is
genuinely turning, while the position reading says the vehicle has not moved in
the lane. That is a cross-channel inconsistency available *without* propagating
anything, and it does not pass through FB1.

It is a different monitor and it has **not** been measured. Recorded here rather
than in a comment, because the negative result is what identifies it.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from astra.config.loader import load_settings
from astra.kernel.constants import FAST_STATE_FIELDS
from astra.layers.l2_estimation.models import fast_transition
from astra.layers.l4_proposer.learned import LearnedPolicy
from training.closed_loop import ENVIRONMENT, TickSample, drive_closed_loop

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.contracts.audit import DecisionRecord

__all__ = ["WINDOW", "ParityMonitor", "ParityReading", "evaluate_parity", "render", "sweep"]

WINDOW = 100
"""Ticks between re-anchorings. Five seconds at 20 Hz.

Kept at the value the first measurement used, because the sweep showed the
choice does not matter: the noise and the signal both scale with the window, so
every value fails for the same reason. Retaining the original rather than
retuning it keeps the refutation legible.
"""

_CRUISE_FROM = 200
"""Tick from which a run counts as cruise rather than startup.

The plant starts up to 1 m off centre and the correction is a sustained
one-sided manoeuvre -- the same shape a fault response has. Reporting the two
together would flatter the noise floor by attributing a real manoeuvre to it.
"""

_DRIFT_PER_TICK_M = 0.01
"""What ``benchmarks.fault_study``'s slow drift injects per tick: 2 m over 200."""

_PY = FAST_STATE_FIELDS.index("position_y")


@dataclass(frozen=True, slots=True)
class ParityReading:
    """One run's divergence signal, reduced to what a threshold decision needs.

    Attributes:
        name: Which arm.
        peak: The largest divergence reached, in metres.
        peak_tick: The tick it was reached on.
        mean: Mean divergence over the ticks that had one.
        p95: 95th percentile, which is what a threshold would be set against.
        peak_before_fault: The largest divergence on ticks with no fault active.
            **This is the false-alarm budget** -- a threshold below it fires on a
            healthy vehicle.
        peak_after_fault: The largest divergence while the fault was active.
        separation: ``peak_after_fault / peak_before_fault``, or ``inf`` when the
            clean half never diverged. **The number that decided this**: below
            about 2 there is no threshold that separates the two populations.
            Measured at **0.20x to 1.61x**.
        ticks: How many ticks contributed a divergence.
    """

    name: str
    peak: float
    peak_tick: int
    mean: float
    p95: float
    peak_before_fault: float
    peak_after_fault: float
    separation: float
    ticks: int


class ParityMonitor:
    """Propagates a command-only estimate and reports its divergence.

    Stateful across ticks, which is what distinguishes it from the pure
    per-record detectors in :mod:`benchmarks.detectors`. It is still read-only:
    it consumes records and produces numbers, and holds no reference to anything
    that could act.
    """

    __slots__ = ("_effectiveness", "_period", "_since_anchor", "_state", "_window", "_yaw_minimum")

    def __init__(
        self,
        *,
        effectiveness: Sequence[float],
        period_seconds: float,
        yaw_rate_minimum_speed: float,
        window: int = WINDOW,
    ) -> None:
        """Build a monitor.

        Args:
            effectiveness: The platform's control-effectiveness row, one gain per
                actuation channel. The commanded lateral acceleration is the dot
                product of this with the issued command -- the same arithmetic
                FB1 uses in ``pipeline._reanchor``, and **that is exactly why
                this does not work**: the filter is fed the same number.
            period_seconds: The tick period. ``1 / estimation.fast_rate_hz``.
            yaw_rate_minimum_speed: Passed through to the process model.
            window: Ticks between re-anchorings.
        """
        self._effectiveness = tuple(float(gain) for gain in effectiveness)
        self._period = float(period_seconds)
        self._yaw_minimum = float(yaw_rate_minimum_speed)
        self._window = int(window)
        self._state: np.ndarray | None = None
        self._since_anchor = 0

    def observe(self, record: DecisionRecord) -> float | None:
        """Advance the propagation by one tick and return the divergence.

        Args:
            record: The tick's decision record.

        Returns:
            ``|open-loop position_y - filtered position_y|`` in metres, or
            ``None`` on a tick that could not contribute -- no state estimate, or
            the tick immediately after an anchoring, where the two agree by
            construction and reporting zero would bias every statistic downward.
        """
        estimate = record.fast_state
        if estimate is None:
            self._state = None
            return None

        filtered = np.asarray(estimate.mean, dtype=np.float64)

        if self._state is None or self._since_anchor >= self._window:
            # Re-anchor. The propagation restarts from the filtered estimate and
            # the accumulated error is discarded rather than carried.
            self._state = filtered.copy()
            self._since_anchor = 0
            divergence = None
        else:
            divergence = abs(float(self._state[_PY]) - float(filtered[_PY]))

        self._state = self._advanced(self._state, record)
        self._since_anchor += 1
        return divergence

    def _advanced(self, state: np.ndarray, record: DecisionRecord) -> np.ndarray:
        """Step the open-loop state forward under this tick's issued command.

        **The speed channel is an honest weakness.** ``fast_transition`` carries
        speed forward unchanged -- the process model has no longitudinal
        dynamics, all of which live in ``Q`` -- so a propagation across a window
        in which the vehicle brakes hard will hold a speed the vehicle no longer
        has, and the lateral integration inherits that error. It is bounded by
        the window, and it is not the reason this monitor fails.

        Args:
            state: The current open-loop state.
            record: The tick's record, for the issued command.

        Returns:
            The propagated state.
        """
        issued = record.issued
        commanded: float | None = None
        if issued is not None:
            values = issued.command.values
            if len(values) == len(self._effectiveness):
                commanded = sum(
                    gain * float(value)
                    for gain, value in zip(self._effectiveness, values, strict=True)
                )
        return fast_transition(
            state,
            self._period,
            yaw_rate_minimum_speed=self._yaw_minimum,
            commanded_lateral_acceleration=commanded,
        )


def evaluate_parity(
    name: str,
    records: Sequence[DecisionRecord],
    *,
    fault_active: Sequence[bool],
    effectiveness: Sequence[float],
    period_seconds: float,
    yaw_rate_minimum_speed: float,
    window: int = WINDOW,
) -> ParityReading:
    """Run the monitor over one arm and reduce it to a reading.

    Args:
        name: Which arm.
        records: The run's decision records, in tick order.
        fault_active: Per-tick ground truth, the same length as ``records``.
        effectiveness: The platform's control-effectiveness row.
        period_seconds: The tick period.
        yaw_rate_minimum_speed: Passed to the process model.
        window: Ticks between re-anchorings.

    Returns:
        The divergence signal, split by whether a fault was active.
    """
    monitor = ParityMonitor(
        effectiveness=effectiveness,
        period_seconds=period_seconds,
        yaw_rate_minimum_speed=yaw_rate_minimum_speed,
        window=window,
    )
    clean: list[float] = []
    faulted: list[float] = []
    everything: list[tuple[int, float]] = []

    for index, record in enumerate(records):
        divergence = monitor.observe(record)
        if divergence is None:
            continue
        everything.append((index, divergence))
        (faulted if fault_active[index] else clean).append(divergence)

    values = [value for _, value in everything]
    if not values:
        return ParityReading(name, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)

    peak_tick, peak = max(everything, key=lambda pair: pair[1])
    before = max(clean) if clean else 0.0
    after = max(faulted) if faulted else 0.0
    separation = math.inf if before == 0.0 else after / before

    ordered = sorted(values)
    return ParityReading(
        name=name,
        peak=peak,
        peak_tick=peak_tick,
        mean=sum(values) / len(values),
        p95=ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))],
        peak_before_fault=before,
        peak_after_fault=after,
        separation=separation,
        ticks=len(values),
    )


def render(readings: Sequence[ParityReading]) -> list[str]:
    """Return the divergence table, as lines.

    Args:
        readings: One per arm, control first.

    Returns:
        Lines to print.
    """
    lines = [
        "",
        "  Analytical redundancy -- a command-only estimate, compared against the",
        f"  filtered one, re-anchored every {WINDOW} ticks. REFUTED; reads records,",
        "  changes nothing, and is kept as the evidence for the refutation.",
        "",
        (
            f"  {'scenario':<16}{'peak m':>10}{'at tick':>9}{'mean m':>9}"
            f"{'p95 m':>9}{'clean pk':>10}{'fault pk':>10}{'ratio':>9}"
        ),
        (
            f"  {'-' * 16}{'-' * 9:>10}{'-' * 8:>9}{'-' * 8:>9}{'-' * 8:>9}"
            f"{'-' * 9:>10}{'-' * 9:>10}{'-' * 8:>9}"
        ),
    ]
    for reading in readings:
        ratio = "inf" if math.isinf(reading.separation) else f"{reading.separation:.2f}x"
        lines.append(
            f"  {reading.name:<16}{reading.peak:>10.3f}{reading.peak_tick:>9}"
            f"{reading.mean:>9.3f}{reading.p95:>9.3f}"
            f"{reading.peak_before_fault:>10.3f}{reading.peak_after_fault:>10.3f}{ratio:>9}"
        )
    lines.extend(
        [
            "",
            "  'ratio' is the faulted peak over the clean peak within the same run.",
            "  Below about 2 there is no threshold that separates the two. Measured:",
            "  0.20x to 1.61x. The signal is smaller than the noise it must clear.",
        ]
    )
    return lines


def sweep(*, ticks: int, seed: int, policy_path: Path, windows: Sequence[int]) -> list[str]:
    """Measure the parity residual against the window, on a clean run.

    **Calibrated on the clean run and on nothing else.** A window chosen because
    it best separated the six faults in ``benchmarks.fault_study`` would be
    fitted to its own test set -- six faults picked by hand to defeat six named
    defences are not a population, and that is the defect E-41 records for the
    conformal corpus. So this reports the *noise floor* per window and leaves the
    comparison against the fault's injection rate explicit.

    Args:
        ticks: How many ticks to drive.
        seed: The run seed.
        policy_path: The trained proposer.
        windows: Window lengths to sweep.

    Returns:
        Lines to print.
    """
    settings = load_settings(environment=ENVIRONMENT, include_environment_variables=False).settings
    effectiveness = tuple(float(gain) for gain in settings.twin.control_effectiveness)
    period = 1.0 / float(settings.estimation.fast_rate_hz)
    yaw_minimum = float(settings.estimation.yaw_rate_minimum_speed)

    samples: list[TickSample] = []
    drive_closed_loop(
        policy=LearnedPolicy.load(policy_path), ticks=ticks, seed=seed, observer=samples.append
    )

    lines = [
        "",
        "  Parity residual on a CLEAN run -- the noise floor this monitor would",
        "  have to clear. Startup and cruise separated; see the docstring.",
        "",
        f"  {'window':>7}{'startup pk':>12}{'cruise pk':>12}{'cruise p95':>12}{'per tick':>11}",
        f"  {'-' * 6:>7}{'-' * 11:>12}{'-' * 11:>12}{'-' * 11:>12}{'-' * 10:>11}",
    ]
    for window in windows:
        monitor = ParityMonitor(
            effectiveness=effectiveness,
            period_seconds=period,
            yaw_rate_minimum_speed=yaw_minimum,
            window=window,
        )
        startup: list[float] = []
        cruise: list[float] = []
        for sample in samples:
            divergence = monitor.observe(sample.record)
            if divergence is None:
                continue
            (startup if sample.tick < _CRUISE_FROM else cruise).append(divergence)
        if not cruise or not startup:
            continue
        ordered = sorted(cruise)
        lines.append(
            f"  {window:>7}{max(startup):>12.3f}{max(cruise):>12.3f}"
            f"{ordered[int(0.95 * len(ordered))]:>12.3f}{max(cruise) / window:>11.4f}"
        )
    lines.extend(
        [
            "",
            f"  The slow drift injects {_DRIFT_PER_TICK_M:.4f} m per tick, by construction.",
            "",
            "  Both the noise and the signal grow linearly with the window, so the",
            "  ratio is roughly constant and no window separates them. That is the",
            "  refutation, and it is structural rather than a tuning failure: FB1",
            "  feeds the issued command into the filter's prediction, so the two",
            "  estimates were never independent.",
        ]
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Entry point for the sweep.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero unless an input artefact is missing.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", "-n", type=int, default=800)
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument("--policy", type=Path, default=Path("var/policy/synthetic.pt"))
    arguments = parser.parse_args(argv)

    if not arguments.policy.exists():
        print(f"missing {arguments.policy}; see docs/EVIDENCE.md for how to regenerate it")
        return 1

    for line in sweep(
        ticks=arguments.ticks,
        seed=arguments.seed,
        policy_path=arguments.policy,
        windows=(10, 20, 30, 40, 60, 100),
    ):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
