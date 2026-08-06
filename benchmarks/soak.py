"""Drive the closed loop for hours and ask whether anything moved.

Why this exists
----------------
The longest run in this project's history before this script was four hundred
ticks -- eight seconds of simulated time. Every number the repository reports
was measured inside that window, and a control loop that is stable for eight
seconds is not thereby stable for an hour. Oscillation, slow drift, an estimator
walking away from the truth, a rolling window that never rolls, a queue that
fills: none of those are visible in four hundred ticks, and all of them are
things this architecture could plausibly have.

So the question this script answers is deliberately narrow: **over a long
continuous drive, does anything move that should not?** It is not a performance
benchmark (``benchmarks/latency.py`` is), and it is not a gate-accuracy
measurement -- it cannot be, because the plant, the twin and the calibration
corpus all descend from the same kinematic equations. What it can find is a
system that slowly stops working, and that is worth knowing before anything is
built on top of it.

Run it with::

    uv run python -m benchmarks.soak --ticks 100000
    uv run python -m benchmarks.soak --ticks 2000 --window 200        # a smoke run
    uv run python -m benchmarks.soak --ticks 100000 --cold-path tunnel

Invoked as a module, not a path: it imports ``training``, which lives at the
repository root rather than in ``src``.

How the measurement avoids measuring itself
--------------------------------------------
Two deliberate choices, both of which the obvious implementation gets wrong.

*Memory.* The harness keeps **per-window aggregates only**, never a per-tick
array. A soak that accumulated a hundred thousand samples would grow its own
resident set by tens of megabytes and then report that growth as the pipeline's.
Window state is bounded by ``--window``, so what the resident-set series shows is
the pipeline.

*Latency.* Only ``pipeline.tick`` is timed. The sensor publish, the plant step
and this file's own bookkeeping sit outside the measured region, so the
percentiles describe ASTRA rather than the harness driving it.

What the pass/fail criteria are, and what they are not
-------------------------------------------------------
Seven criteria gate the exit status: availability, finiteness, evidence
completeness, twin identity, lane-deviation drift, veto-rate drift, resident
growth and latency growth. Each has a threshold with a stated reason, and each
is checked against a *trend* across windows rather than a single number.

**Oscillation is reported, not gated.** A sustained oscillation shows up as a
wide peak-to-peak with a flat trend, and the direction-change count and range
are printed for every series so a reader can see one. No threshold is asserted
because none has been justified by a measurement yet, and a gate whose number
was picked to make the current run pass would be decoration.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import platform
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from astra.config.loader import load_settings
from astra.contracts.actuation import CommandOrigin
from astra.kernel.constants import FAST_STATE_FIELDS
from astra.kernel.units import Probability
from astra.layers.l4_proposer.learned import LearnedPolicy
from astra.runtime.pipeline import ColdPathContext
from training.closed_loop import ENVIRONMENT, drive_closed_loop
from training.environment import EnvironmentSpec

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from training.closed_loop import ClosedLoopResult, TickSample

_POSITION_Y_INDEX = FAST_STATE_FIELDS.index("position_y")
_NANOSECONDS_PER_MILLISECOND = 1_000_000
_BYTES_PER_MEBIBYTE = 1024 * 1024
_STATM_PATH = Path("/proc/self/statm")
_STATM_RESIDENT_FIELD = 1

_DEFAULT_TICKS = 100_000
_DEFAULT_WINDOW = 1_000
_DEFAULT_SEED = 20260731
_DEFAULT_POLICY = Path("var/policy/synthetic.pt")
_DEFAULT_OUTPUT = Path("var/soak")

# --------------------------------------------------------------------------- #
# The cold path, and why a soak has to be able to turn it on
# --------------------------------------------------------------------------- #
# `drive_closed_loop` left `cold_path=None` for its whole history, which means
# every measurement taken through it describes a system with L9's knowledge
# base dormant: the arbitrator keeps its seed profile and bounded safe
# exploration -- the architecture's answer to "no certified profile covers
# this" -- can never engage. The first soak found an unbounded lane departure
# under exactly those conditions, so whether the cold path recovers it is the
# question these two contexts exist to answer.
#
# The pairs are (visibility, road complexity), matching `demo/run_pipeline.py`
# and `tests/integration/test_tunnel_scenario.py` so the three agree on what
# "open road" and "tunnel" mean.
_OPEN_ROAD: Final[tuple[float, float]] = (0.90, 0.22)
_INSIDE_TUNNEL: Final[tuple[float, float]] = (0.05, 0.95)
_TRAFFIC_DYNAMICITY = 0.32
_ARBITRATION_PERIOD_TICKS = 5
"""Hot ticks between cold-path evaluations, as the demo and the tunnel test use.

The cold path is not per-tick work: context changes on a timescale of seconds,
and re-searching the knowledge base at 20 Hz would spend the tick budget
re-deriving an unchanged answer.
"""

COLD_PATH_CONTEXTS: Final[dict[str, tuple[float, float] | None]] = {
    "off": None,
    "open": _OPEN_ROAD,
    "tunnel": _INSIDE_TUNNEL,
}
"""What ``--cold-path`` may name.

``off`` reproduces every run this repository took before August 2026. ``open``
turns the knowledge base on in a context the seed profiles cover. ``tunnel``
turns it on in a context none of them covers -- deliberately, because there is
no tunnel profile, and that omission is what makes bounded safe exploration
observable at all.
"""

# --------------------------------------------------------------------------- #
# Pass/fail thresholds, and why each is the number it is
# --------------------------------------------------------------------------- #
_WARMUP_WINDOWS = 1
"""Windows excluded from the latency and memory criteria.

The first window pays for lazy imports, the filter's convergence and every
allocation CPython has not yet made. Including it would compare a cold process
against a warm one and call the difference drift.
"""

_DEVIATION_DRIFT_FRACTION = 0.10
"""Permitted change in mean |lane deviation| between the run's halves.

Expressed as a fraction of the lane half-width rather than an absolute distance,
because the quantity that matters is how much of the lane the drift consumed. A
tenth of the half-width is well inside the lane and well outside measurement
noise at this window size.
"""

_VETO_RATE_DRIFT_LIMIT = 0.05
"""Permitted change in veto rate between the run's halves, in absolute terms.

The veto rate is the loop's clearest feedback signal: if Core-B is progressively
rejecting more or less of what Core-A proposes with no change in conditions,
something in the loop is integrating. Five points is small enough to catch a
trend and large enough not to fire on binomial noise across two 50k-tick halves.
"""

_RESIDENT_GROWTH_LIMIT_BYTES = 64 * _BYTES_PER_MEBIBYTE
"""Permitted growth in resident set from the first post-warmup window to the peak.

Every rolling structure in the pipeline is bounded -- the Mondrian buckets and
the MMD detector are ``deque(maxlen=...)``, the twin's Fisher history is
truncated to ``fisher_sample_count`` -- so the expected growth is zero and the
budget is for allocator behaviour, not for the pipeline. It is generous on
purpose: a leak worth finding is not 64 MiB, it is unbounded.
"""

_LATENCY_GROWTH_FACTOR = 1.5
"""Permitted ratio of the last decile's p99 tick cost to the first decile's.

A loop whose per-tick cost grows is a loop accumulating work per tick, which is
the same defect as a memory leak seen from the other side. Half again allows for
a noisy shared host without allowing a trend.
"""

_TERMINAL_FAILSAFE_STATE = "HALT"
"""The fail-safe state a run must not end latched in.

Added after a 100,000-tick run reported STABLE on every other criterion --
0.0003 m of lane deviation, a 0.00% veto rate, speed held to 13.03 m/s for the
whole drive -- while the fail-safe machine sat in HALT for 99,000 of those ticks.
Twenty-one transient jerk vetoes in the first window had pushed the
out-of-distribution counter past ``ood_threshold_halt``, and HALT is terminal by
design: ``reset()`` is its only exit, because leaving a pull-over is meant to be
an engineering decision rather than something a run of clean ticks accomplishes.

Both halves of that are defensible and the composition is not. A soak that scores
the vehicle and never the safety posture will call this stable, which is how the
instrument came to disagree with the system it was measuring. The vehicle was
fine; the system had declared an emergency and stayed in it.
"""

_MOVING_SPEED_FLOOR_MPS = 0.5
"""Mean speed the final window must exceed for the run to count as stable.

Added after the first cold-path run reported STABLE for a vehicle that had come
to a complete stop and therefore had no lane drift to measure. Degrading to a
halt is the single behaviour this architecture exists to avoid -- the exploration
module's docstring says so in its first paragraph -- and a stability criterion
that scores it as a pass is measuring the wrong thing.

Half a metre per second because that is
``training.environment._YAW_RATE_MINIMUM_SPEED``, below which the plant's
kinematic model stops describing a vehicle. Checked on the **final** window
rather than every window, so a transient dip on the way to recovery is not a
failure -- only ending at rest is.
"""


def _resident_bytes() -> int | None:
    """Return this process's resident set size, or ``None`` where unavailable.

    Read from ``/proc/self/statm`` rather than through ``psutil``: a dependency
    added to a safety-adjacent repository has to be justified in a safety case
    eventually, and two lines of stdlib is not worth that. Windows and macOS
    return ``None``, and the memory criterion is then reported as unmeasured
    rather than silently passed.

    Returns:
        Resident bytes, or ``None`` if this platform has no ``statm``.
    """
    try:
        fields = _STATM_PATH.read_text(encoding="ascii").split()
    except OSError:
        return None
    return int(fields[_STATM_RESIDENT_FIELD]) * os.sysconf("SC_PAGE_SIZE")


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    """Return a percentile of an already-sorted sample.

    Args:
        ordered: Samples in ascending order. Must be non-empty.
        fraction: The percentile as a fraction in ``[0, 1]``.

    Returns:
        The nearest-rank percentile.
    """
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


@dataclass(frozen=True, slots=True)
class WindowSummary:
    """What one window of ticks did.

    A window is the unit of evidence in a soak: a single tick says nothing about
    a trend, and the full per-tick series costs memory the run is trying to
    measure.

    Attributes:
        index: The window's position in the run, from zero.
        first_tick: First tick in the window.
        ticks: How many ticks the window covers.
        issued: Ticks on which a command reached the actuation sink. Anything
            below ``ticks`` breaks the availability claim.
        vetoed: Ticks on which Core-B's aggregate verdict was blocking.
        mean_absolute_deviation_m: Mean ``|lane deviation|`` the plant held.
        max_absolute_deviation_m: Worst single-tick lane deviation.
        mean_speed_mps: Mean true speed.
        mean_estimator_error_m: Mean ``|position_y estimate - truth|``. The
            extractor never measures ``position_y``, so the UKF propagates it
            from the process model alone -- which makes this the most sensitive
            drift signal the run produces.
        mean_trust_index: Mean Trust Index over ticks that reached L3.
        p50_tick_ms: Median cost of ``pipeline.tick``.
        p99_tick_ms: 99th-percentile cost of ``pipeline.tick``.
        max_tick_ms: Worst tick in the window.
        resident_bytes: Resident set size at the window's end, or ``None``.
        twin_digest: The twin weights digest in force, or ``None`` if no tick
            in the window reached L5.
        failsafe_states: Every fail-safe state visited, sorted.
        reasons: Veto counts by ``gate:reason_code`` within this window.
        origins: Counts by :class:`~astra.contracts.actuation.CommandOrigin` of
            the commands actually issued. The only thing that distinguishes
            "the fallback governed" from "bounded safe exploration governed",
            and therefore the series the cold-path experiment turns on.
        arbitrations: Counts by arbitration outcome, or empty when the cold
            path is dormant and no evaluation ran.
        proposals_issued_under_veto: Ticks on which Core-B's aggregate verdict
            was blocking and the proposal was nonetheless issued, because
            bounded safe exploration was engaged and
            :meth:`~astra.layers.l9_rcm.arbiter.RuntimeCalibrationManager.issue`
            tests the exploration envelope before it tests the verdict.
            Reported, never gated: whether that ordering is correct is a design
            question this instrument has no standing to answer.
        mean_shadow_divergence: Mean gap between the live twin's prediction and
            the one a shadow twin running FB2 would have made, or ``None`` when
            no shadow was running. Also never gated, and for a stronger reason:
            FB2 is switched off, so this is a counterfactual and a criterion
            built on it would be gating the run on something that did not happen.
        max_shadow_divergence: The largest such gap in the window.
        shadow_digest: The shadow twin's weights digest, so a flat divergence can
            be told apart from a shadow that never moved.
        mean_live_score: Mean non-conformity score against the twin the gates
            read, or ``None``.
        mean_shadow_score: Mean score against the shadow twin, or ``None``. The
            twin's own docstring says training it on the proposer's output would
            "make every score small and quietly disarm the statistical gate";
            FB2's only labels are the proposer's commands, so this column is
            where that would show up first.
    """

    index: int
    first_tick: int
    ticks: int
    issued: int
    vetoed: int
    mean_absolute_deviation_m: float
    max_absolute_deviation_m: float
    mean_speed_mps: float
    mean_estimator_error_m: float
    mean_trust_index: float
    p50_tick_ms: float
    p99_tick_ms: float
    max_tick_ms: float
    resident_bytes: int | None
    twin_digest: str | None
    failsafe_states: tuple[str, ...]
    reasons: tuple[tuple[str, int], ...]
    origins: tuple[tuple[str, int], ...] = ()
    arbitrations: tuple[tuple[str, int], ...] = ()
    proposals_issued_under_veto: int = 0
    mean_shadow_divergence: float | None = None
    max_shadow_divergence: float | None = None
    shadow_digest: str | None = None
    mean_live_score: float | None = None
    mean_shadow_score: float | None = None

    @property
    def veto_rate(self) -> float:
        """Return the fraction of ticks Core-B blocked in this window."""
        return self.vetoed / self.ticks if self.ticks else 0.0

    def to_payload(self) -> dict[str, object]:
        """Render the window as a JSON-serialisable dictionary.

        Returns:
            One evidence row, with the same key set in every window so the
            series reads as a table rather than a ragged join.
        """
        return {
            "index": self.index,
            "first_tick": self.first_tick,
            "ticks": self.ticks,
            "issued": self.issued,
            "vetoed": self.vetoed,
            "veto_rate": self.veto_rate,
            "mean_absolute_deviation_m": self.mean_absolute_deviation_m,
            "max_absolute_deviation_m": self.max_absolute_deviation_m,
            "mean_speed_mps": self.mean_speed_mps,
            "mean_estimator_error_m": self.mean_estimator_error_m,
            "mean_trust_index": self.mean_trust_index,
            "p50_tick_ms": self.p50_tick_ms,
            "p99_tick_ms": self.p99_tick_ms,
            "max_tick_ms": self.max_tick_ms,
            "resident_bytes": self.resident_bytes,
            "twin_digest": self.twin_digest,
            "failsafe_states": list(self.failsafe_states),
            "reasons": dict(self.reasons),
            "origins": dict(self.origins),
            "arbitrations": dict(self.arbitrations),
            "proposals_issued_under_veto": self.proposals_issued_under_veto,
            "mean_shadow_divergence": self.mean_shadow_divergence,
            "max_shadow_divergence": self.max_shadow_divergence,
            "shadow_digest": self.shadow_digest,
            "mean_live_score": self.mean_live_score,
            "mean_shadow_score": self.mean_shadow_score,
        }


@dataclass(slots=True)
class _WindowAccumulator:
    """Per-window running state, reset every time a window closes.

    Bounded by construction: the only unbounded-looking member is the duration
    list, which is cleared on every ``close``. That is what keeps the harness's
    own footprint flat while it measures the pipeline's.
    """

    index: int = 0
    first_tick: int = 0
    ticks: int = 0
    issued: int = 0
    vetoed: int = 0
    deviation_total: float = 0.0
    deviation_peak: float = 0.0
    speed_total: float = 0.0
    estimator_error_total: float = 0.0
    estimator_samples: int = 0
    trust_total: float = 0.0
    trust_samples: int = 0
    non_finite: int = 0
    durations_ms: list[float] = field(default_factory=list)
    twin_digest: str | None = None
    failsafe_states: set[str] = field(default_factory=set)
    reasons: Counter[str] = field(default_factory=Counter)
    origins: Counter[str] = field(default_factory=Counter)
    arbitrations: Counter[str] = field(default_factory=Counter)
    overridden: int = 0
    shadow_total: float = 0.0
    shadow_peak: float = 0.0
    shadow_samples: int = 0
    shadow_digest: str | None = None
    live_score_total: float = 0.0
    shadow_score_total: float = 0.0

    def observe(self, sample: TickSample) -> None:
        """Fold one tick into the window.

        Args:
            sample: The tick, as the closed-loop driver saw it.
        """
        record = sample.record
        self.ticks += 1
        self.issued += int(sample.was_issued)
        deviation = abs(sample.lane_deviation_m)
        if not math.isfinite(deviation) or not math.isfinite(sample.speed_mps):
            self.non_finite += 1
            return
        self.deviation_total += deviation
        self.deviation_peak = max(self.deviation_peak, deviation)
        self.speed_total += sample.speed_mps
        self.durations_ms.append(sample.pipeline_duration_ns / _NANOSECONDS_PER_MILLISECOND)

        if record.fast_state is not None:
            estimated = record.fast_state.mean[_POSITION_Y_INDEX]
            self.estimator_error_total += abs(estimated - sample.lane_deviation_m)
            self.estimator_samples += 1
        if record.trust is not None:
            self.trust_total += float(record.trust.trust_index)
            self.trust_samples += 1
        if record.twin_weights_digest is not None:
            self.twin_digest = record.twin_weights_digest
        if record.failsafe is not None:
            self.failsafe_states.add(record.failsafe.state.value)
        if record.issued is not None:
            self.origins[record.issued.origin.value] += 1
        if record.arbitration is not None:
            self.arbitrations[record.arbitration.outcome.value] += 1
        verdict = record.safety_verdict
        if verdict is not None and verdict.is_blocking:
            self.vetoed += 1
            if (
                record.issued is not None
                and record.issued.origin is CommandOrigin.EXPLORATION_BOUNDED
            ):
                self.overridden += 1
        for gate_verdict in verdict.gate_verdicts if verdict else ():
            if gate_verdict.verdict.is_blocking:
                self.reasons[f"{gate_verdict.gate.value}:{gate_verdict.reason_code}"] += 1

        if sample.shadow_divergence_m_s2 is not None:
            self.shadow_total += sample.shadow_divergence_m_s2
            self.shadow_peak = max(self.shadow_peak, sample.shadow_divergence_m_s2)
            self.shadow_samples += 1
            self.shadow_digest = sample.shadow_digest
            self.live_score_total += sample.live_score or 0.0
            self.shadow_score_total += sample.shadow_score or 0.0

    def close(self) -> WindowSummary:
        """Summarise the window and reset for the next one.

        Returns:
            The window's summary.
        """
        ordered = sorted(self.durations_ms)
        summary = WindowSummary(
            index=self.index,
            first_tick=self.first_tick,
            ticks=self.ticks,
            issued=self.issued,
            vetoed=self.vetoed,
            mean_absolute_deviation_m=self.deviation_total / max(1, self.ticks),
            max_absolute_deviation_m=self.deviation_peak,
            mean_speed_mps=self.speed_total / max(1, self.ticks),
            mean_estimator_error_m=(
                self.estimator_error_total / self.estimator_samples
                if self.estimator_samples
                else 0.0
            ),
            mean_trust_index=(self.trust_total / self.trust_samples if self.trust_samples else 0.0),
            p50_tick_ms=statistics.median(ordered) if ordered else 0.0,
            p99_tick_ms=_percentile(ordered, 0.99) if ordered else 0.0,
            max_tick_ms=ordered[-1] if ordered else 0.0,
            resident_bytes=_resident_bytes(),
            twin_digest=self.twin_digest,
            failsafe_states=tuple(sorted(self.failsafe_states)),
            reasons=tuple(sorted(self.reasons.items())),
            origins=tuple(sorted(self.origins.items())),
            arbitrations=tuple(sorted(self.arbitrations.items())),
            proposals_issued_under_veto=self.overridden,
            mean_shadow_divergence=(
                self.shadow_total / self.shadow_samples if self.shadow_samples else None
            ),
            max_shadow_divergence=self.shadow_peak if self.shadow_samples else None,
            shadow_digest=self.shadow_digest,
            mean_live_score=(
                self.live_score_total / self.shadow_samples if self.shadow_samples else None
            ),
            mean_shadow_score=(
                self.shadow_score_total / self.shadow_samples if self.shadow_samples else None
            ),
        )
        self.index += 1
        self.first_tick += self.ticks
        self.ticks = 0
        self.issued = 0
        self.vetoed = 0
        self.deviation_total = 0.0
        self.deviation_peak = 0.0
        self.speed_total = 0.0
        self.estimator_error_total = 0.0
        self.estimator_samples = 0
        self.trust_total = 0.0
        self.trust_samples = 0
        self.durations_ms.clear()
        self.failsafe_states.clear()
        self.reasons.clear()
        self.origins.clear()
        self.arbitrations.clear()
        self.overridden = 0
        self.shadow_total = 0.0
        self.shadow_peak = 0.0
        self.shadow_samples = 0
        self.live_score_total = 0.0
        self.shadow_score_total = 0.0
        return summary


@dataclass(frozen=True, slots=True)
class Trend:
    """How one series behaved across the run.

    Attributes:
        label: The series name.
        first_half_mean: Mean over the first half of the windows.
        second_half_mean: Mean over the second half.
        minimum: Smallest window value.
        maximum: Largest window value.
        direction_changes: How many times the window-to-window difference
            changed sign. A drifting series changes direction rarely; an
            oscillating one changes constantly. Reported, never gated.
    """

    label: str
    first_half_mean: float
    second_half_mean: float
    minimum: float
    maximum: float
    direction_changes: int

    @property
    def drift(self) -> float:
        """Return the change between the two halves, signed."""
        return self.second_half_mean - self.first_half_mean

    @property
    def span(self) -> float:
        """Return the peak-to-peak range of the series."""
        return self.maximum - self.minimum

    def to_payload(self) -> dict[str, object]:
        """Render the trend as a JSON-serialisable dictionary.

        Returns:
            The trend's fields plus its two derived quantities.
        """
        return {
            "label": self.label,
            "first_half_mean": self.first_half_mean,
            "second_half_mean": self.second_half_mean,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "direction_changes": self.direction_changes,
            "drift": self.drift,
            "span": self.span,
        }


def trend(label: str, values: Sequence[float]) -> Trend:
    """Reduce a per-window series to a trend.

    Halves rather than a fitted slope: a least-squares line over a series with
    one step change in it reports a gentle slope that never happened, and the
    failure this is looking for -- *the second half is not like the first* -- is
    exactly what a halves comparison states.

    Args:
        label: The series name.
        values: One value per window, in order. Must be non-empty.

    Returns:
        The trend.

    Raises:
        ValueError: If the series is empty. An empty series has no trend, and
            returning zeros would report stability that was never measured.
    """
    if not values:
        message = f"cannot summarise the trend of an empty series: {label}"
        raise ValueError(message)
    midpoint = len(values) // 2
    first = values[:midpoint] or values
    second = values[midpoint:] or values
    changes = 0
    previous_sign = 0
    for earlier, later in itertools.pairwise(values):
        sign = (later > earlier) - (later < earlier)
        if sign and previous_sign and sign != previous_sign:
            changes += 1
        if sign:
            previous_sign = sign
    return Trend(
        label=label,
        first_half_mean=statistics.fmean(first),
        second_half_mean=statistics.fmean(second),
        minimum=min(values),
        maximum=max(values),
        direction_changes=changes,
    )


@dataclass(frozen=True, slots=True)
class Criterion:
    """One pass/fail statement about the run.

    Attributes:
        name: What was checked.
        passed: Whether it held. ``None`` means the property could not be
            measured on this host, which is neither a pass nor a failure and
            must not be reported as either.
        detail: The measurement behind the verdict, in the units it was taken.
    """

    name: str
    passed: bool | None
    detail: str


def evaluate(
    windows: Sequence[WindowSummary],
    *,
    dropped_records: int,
    lane_half_width_m: float,
    non_finite_ticks: int,
) -> tuple[Criterion, ...]:
    """Judge a completed soak against the stability criteria.

    Args:
        windows: Every window the run produced, in order.
        dropped_records: Audit records the sink discarded.
        lane_half_width_m: The plant's lane half-width, which the deviation
            budget is expressed as a fraction of.
        non_finite_ticks: Ticks whose plant state was NaN or infinite.

    Returns:
        One criterion per checked property, in reporting order.

    Raises:
        ValueError: If no windows were produced.
    """
    if not windows:
        message = "a soak with no completed windows cannot be judged"
        raise ValueError(message)

    warm = windows[_WARMUP_WINDOWS:] or windows
    shortfall = sum(window.ticks - window.issued for window in windows)
    digests = {window.twin_digest for window in windows if window.twin_digest is not None}

    deviation = trend("mean |lane deviation| (m)", [w.mean_absolute_deviation_m for w in warm])
    veto = trend("veto rate", [w.veto_rate for w in warm])
    latency = trend("p99 tick (ms)", [w.p99_tick_ms for w in warm])
    deviation_budget = _DEVIATION_DRIFT_FRACTION * lane_half_width_m

    resident = [w.resident_bytes for w in warm if w.resident_bytes is not None]
    if resident:
        growth = max(resident) - resident[0]
        memory = Criterion(
            name="resident set does not grow",
            passed=growth <= _RESIDENT_GROWTH_LIMIT_BYTES,
            detail=(
                f"{resident[0] / _BYTES_PER_MEBIBYTE:.1f} MiB at the first warm window, "
                f"peak +{growth / _BYTES_PER_MEBIBYTE:.1f} MiB "
                f"(budget {_RESIDENT_GROWTH_LIMIT_BYTES / _BYTES_PER_MEBIBYTE:.0f} MiB)"
            ),
        )
    else:
        memory = Criterion(
            name="resident set does not grow",
            passed=None,
            detail="no /proc/self/statm on this host; not measured",
        )

    latency_ratio = (
        latency.second_half_mean / latency.first_half_mean if latency.first_half_mean else 0.0
    )
    return (
        Criterion(
            name="a command is issued on every tick",
            passed=shortfall == 0,
            detail=f"{shortfall} tick(s) issued nothing across {len(windows)} window(s)",
        ),
        Criterion(
            name="the plant state stays finite",
            passed=non_finite_ticks == 0,
            detail=f"{non_finite_ticks} tick(s) produced a non-finite state",
        ),
        Criterion(
            name="the evidence has no gaps",
            passed=dropped_records == 0,
            detail=f"{dropped_records} audit record(s) dropped by the sink",
        ),
        Criterion(
            name="the twin is the one the run started with",
            passed=len(digests) <= 1,
            detail=(
                f"{len(digests)} distinct twin weights digest(s); "
                f"FB2 is not wired, so more than one would mean the model moved unbidden"
            ),
        ),
        Criterion(
            name="the fail-safe machine is not latched at the end",
            passed=windows[-1].failsafe_states != (_TERMINAL_FAILSAFE_STATE,),
            detail=(
                f"final window visited {list(windows[-1].failsafe_states)}; "
                f"{_TERMINAL_FAILSAFE_STATE} is terminal, so ending there means the run "
                f"finished in an emergency posture however well the vehicle drove"
            ),
        ),
        Criterion(
            name="the vehicle is still moving at the end",
            passed=windows[-1].mean_speed_mps > _MOVING_SPEED_FLOOR_MPS,
            detail=(
                f"{windows[-1].mean_speed_mps:.3f} m/s in the final window "
                f"(floor {_MOVING_SPEED_FLOOR_MPS:.1f}); degrading to a stop is the "
                f"behaviour the architecture exists to avoid"
            ),
        ),
        Criterion(
            name="lane deviation does not drift",
            passed=abs(deviation.drift) <= deviation_budget,
            detail=(
                f"{deviation.first_half_mean:.4f} -> {deviation.second_half_mean:.4f} m "
                f"(drift {deviation.drift:+.4f}, budget +/-{deviation_budget:.4f})"
            ),
        ),
        Criterion(
            name="the veto rate does not drift",
            passed=abs(veto.drift) <= _VETO_RATE_DRIFT_LIMIT,
            detail=(
                f"{veto.first_half_mean:.1%} -> {veto.second_half_mean:.1%} "
                f"(drift {veto.drift:+.1%}, budget +/-{_VETO_RATE_DRIFT_LIMIT:.0%})"
            ),
        ),
        memory,
        Criterion(
            name="per-tick cost does not grow",
            passed=latency_ratio <= _LATENCY_GROWTH_FACTOR,
            detail=(
                f"p99 {latency.first_half_mean:.3f} -> {latency.second_half_mean:.3f} ms "
                f"(x{latency_ratio:.2f}, budget x{_LATENCY_GROWTH_FACTOR:.1f})"
            ),
        ),
    )


def trends(windows: Sequence[WindowSummary]) -> tuple[Trend, ...]:
    """Return every reported series' trend, warm-up windows excluded.

    Args:
        windows: Every window the run produced, in order.

    Returns:
        The trends, in reporting order.
    """
    warm = windows[_WARMUP_WINDOWS:] or windows
    return (
        trend("mean |lane deviation| (m)", [w.mean_absolute_deviation_m for w in warm]),
        trend("max |lane deviation| (m)", [w.max_absolute_deviation_m for w in warm]),
        trend("veto rate", [w.veto_rate for w in warm]),
        trend("mean speed (m/s)", [w.mean_speed_mps for w in warm]),
        trend("estimator |position_y| error (m)", [w.mean_estimator_error_m for w in warm]),
        trend("mean trust index", [w.mean_trust_index for w in warm]),
        trend("p50 tick (ms)", [w.p50_tick_ms for w in warm]),
        trend("p99 tick (ms)", [w.p99_tick_ms for w in warm]),
    )


def cold_path_context(name: str) -> ColdPathContext | None:
    """Build the cold-path context ``--cold-path`` named.

    The settings are re-resolved here rather than threaded out of
    ``drive_closed_loop``, which resolves them privately. Both read
    :data:`training.closed_loop.ENVIRONMENT`, so they describe the same
    operating point, and the decision record's ``config_hash`` is what proves
    it after the fact.

    Args:
        name: A key of :data:`COLD_PATH_CONTEXTS`.

    Returns:
        The context, or ``None`` for ``off``.

    Raises:
        KeyError: If the name is not one of the known contexts.
    """
    where = COLD_PATH_CONTEXTS[name]
    if where is None:
        return None
    settings = load_settings(environment=ENVIRONMENT, include_environment_variables=False).settings
    return ColdPathContext(
        period_ticks=_ARBITRATION_PERIOD_TICKS,
        trust_threshold=settings.arbitration.trust_threshold_tau,
        divergence_limit=settings.arbitration.divergence_limit_delta,
        platform="synthetic-prototype",
        legal_speed_limit=settings.shield.legal_speed_limit,
        visibility=Probability(where[0]),
        traffic_dynamicity=Probability(_TRAFFIC_DYNAMICITY),
        road_complexity=Probability(where[1]),
    )


def totals(
    windows: Sequence[WindowSummary], select: Callable[[WindowSummary], Sequence[tuple[str, int]]]
) -> tuple[tuple[str, int], ...]:
    """Sum one of a window's counters across the whole run.

    Args:
        windows: Every window the run produced.
        select: Which counter to read from each window.

    Returns:
        The summed counts, largest first.
    """
    counter: Counter[str] = Counter()
    for window in windows:
        counter.update(dict(select(window)))
    return tuple(counter.most_common())


@dataclass(frozen=True, slots=True)
class SoakReport:
    """Everything one soak produced.

    Attributes:
        ticks: How many control ticks ran.
        windows: The per-window series.
        criteria: The pass/fail judgements.
        series: The reported trends, gated and ungated alike.
        result: The driver's own aggregate result.
        wall_seconds: How long the run took.
        policy: What drove the proposer, for the record.
        audit_path: Where the evidence was written.
        cold_path: Which cold-path context was in force, by name.
    """

    ticks: int
    windows: tuple[WindowSummary, ...]
    criteria: tuple[Criterion, ...]
    series: tuple[Trend, ...]
    result: ClosedLoopResult
    wall_seconds: float
    policy: str
    audit_path: Path | None
    cold_path: str = "off"

    @property
    def stable(self) -> bool:
        """Return whether every measurable criterion held.

        An unmeasurable criterion does not fail the run; it is reported as
        unmeasured, which is a different claim and has to stay one.
        """
        return all(criterion.passed is not False for criterion in self.criteria)

    def to_payload(self) -> dict[str, object]:
        """Render the report as a JSON-serialisable dictionary.

        Returns:
            The full summary, less the per-window series, which is written
            separately as JSONL.
        """
        return {
            "ticks": self.ticks,
            "windows": len(self.windows),
            "wall_seconds": self.wall_seconds,
            "policy": self.policy,
            "cold_path": self.cold_path,
            "origins": dict(totals(self.windows, lambda w: w.origins)),
            "arbitrations": dict(totals(self.windows, lambda w: w.arbitrations)),
            "audit_path": None if self.audit_path is None else str(self.audit_path),
            "host": platform.platform(),
            "python": platform.python_version(),
            "stable": self.stable,
            "issued": self.result.issued,
            "vetoed": self.result.vetoed,
            "veto_rate": self.result.veto_rate,
            "mean_absolute_deviation_m": self.result.mean_absolute_deviation_m,
            "peak_lateral_jerk_mps3": self.result.peak_lateral_jerk_mps3,
            "dropped_records": self.result.dropped_records,
            "reasons": dict(self.result.reasons),
            "criteria": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.criteria
            ],
            "series": [series.to_payload() for series in self.series],
        }


def run(
    *,
    ticks: int,
    window: int,
    seed: int,
    policy_path: Path | None,
    output: Path,
    shadow_fb2: bool = False,
    progress_every: int,
    cold_path: str = "off",
) -> SoakReport:
    """Drive the closed loop and summarise what it did.

    Args:
        ticks: How many control ticks to run.
        window: Ticks per evidence window.
        seed: Seed for the plant's initial condition.
        policy_path: The trained policy checkpoint, or ``None`` for the
            deterministic placeholder.
        output: Directory for the window series, the summary and the audit log.
        progress_every: Print a progress line every this many windows. Zero
            silences it.
        shadow_fb2: Run a second twin that FB2 adapts and nothing reads. The
            run behaves identically either way; the only difference is that the
            windows carry a divergence column and the report grows a section.
        cold_path: Which entry of :data:`COLD_PATH_CONTEXTS` to run under.

    Returns:
        The report.
    """
    output.mkdir(parents=True, exist_ok=True)
    series_path = output / "windows.jsonl"
    spec = EnvironmentSpec()
    accumulator = _WindowAccumulator()
    completed: list[WindowSummary] = []

    policy = None
    label = "placeholder"
    if policy_path is not None:
        policy = LearnedPolicy.load(policy_path)
        label = str(policy_path)

    with series_path.open("w", encoding="utf-8") as handle:

        def observe(sample: TickSample) -> None:
            """Fold a tick in, and close the window when it is full.

            Args:
                sample: The tick, as the closed-loop driver saw it.
            """
            accumulator.observe(sample)
            if accumulator.ticks < window:
                return
            summary = accumulator.close()
            completed.append(summary)
            handle.write(json.dumps(summary.to_payload(), separators=(",", ":")) + "\n")
            handle.flush()
            if progress_every and summary.index % progress_every == 0:
                resident = summary.resident_bytes
                memory = "" if resident is None else f"  rss {resident / _BYTES_PER_MEBIBYTE:6.1f}M"
                print(
                    f"  window {summary.index:>5}  tick {summary.first_tick:>8}  "
                    f"veto {summary.veto_rate:6.1%}  |dev| {summary.mean_absolute_deviation_m:.4f}m"
                    f"  p99 {summary.p99_tick_ms:6.2f}ms{memory}",
                    flush=True,
                )

        started = time.perf_counter()
        result = drive_closed_loop(
            policy=policy,
            ticks=ticks,
            seed=seed,
            spec=spec,
            directory=output / "audit",
            observer=observe,
            cold_path=cold_path_context(cold_path),
            shadow_fb2=shadow_fb2,
        )
        wall = time.perf_counter() - started
        non_finite = accumulator.non_finite
        if accumulator.ticks:
            summary = accumulator.close()
            completed.append(summary)
            handle.write(json.dumps(summary.to_payload(), separators=(",", ":")) + "\n")

    report = SoakReport(
        ticks=ticks,
        windows=tuple(completed),
        criteria=evaluate(
            completed,
            dropped_records=result.dropped_records,
            lane_half_width_m=spec.lane_half_width_m,
            non_finite_ticks=non_finite,
        ),
        series=trends(completed),
        result=result,
        wall_seconds=wall,
        policy=label,
        audit_path=result.audit_path,
        cold_path=cold_path,
    )
    (output / "summary.json").write_text(
        json.dumps(report.to_payload(), indent=2) + "\n", encoding="utf-8"
    )
    return report


def plot(windows: Sequence[WindowSummary], path: Path) -> bool:
    """Write the per-window series as a figure.

    Args:
        windows: The series to plot.
        path: Where to write the PNG.

    Returns:
        Whether a figure was written. ``False`` means matplotlib is not
        installed, which is not an error -- the numbers are in the JSONL either
        way, and the figure is a reading aid.
    """
    try:
        import matplotlib as mpl  # noqa: PLC0415

        mpl.use("Agg")
        from matplotlib import pyplot as plt  # noqa: PLC0415
    except ImportError:
        return False

    ticks = [w.first_tick for w in windows]
    panels: tuple[tuple[str, list[float]], ...] = (
        ("veto rate", [w.veto_rate for w in windows]),
        ("mean |lane deviation| (m)", [w.mean_absolute_deviation_m for w in windows]),
        ("estimator |position_y| error (m)", [w.mean_estimator_error_m for w in windows]),
        ("mean trust index", [w.mean_trust_index for w in windows]),
        ("p99 tick (ms)", [w.p99_tick_ms for w in windows]),
        (
            "resident set (MiB)",
            [
                (w.resident_bytes or 0) / _BYTES_PER_MEBIBYTE
                for w in windows
                if w.resident_bytes is not None
            ],
        ),
    )
    figure, axes = plt.subplots(len(panels), 1, figsize=(10, 2.2 * len(panels)), sharex=True)
    for axis, (title, values) in zip(axes, panels, strict=True):
        axis.plot(ticks[: len(values)], values, linewidth=0.9)
        axis.set_ylabel(title, fontsize=8)
        axis.grid(alpha=0.3)
    axes[-1].set_xlabel("tick")
    figure.suptitle(f"ASTRA closed-loop soak, {len(windows)} windows", fontsize=11)
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return True


def render(report: SoakReport) -> Iterable[str]:
    """Yield the report as lines for a terminal.

    Args:
        report: The completed soak.

    Yields:
        One line at a time.
    """
    yield f"host      {platform.platform()} / {platform.machine()}"
    yield f"python    CPython {platform.python_version()}"
    yield f"policy    {report.policy}"
    yield (
        f"cold path {report.cold_path}"
        f"{'  -- L9 knowledge base dormant' if report.cold_path == 'off' else ''}"
    )
    yield (
        f"run       {report.ticks} ticks in {report.wall_seconds:.1f} s "
        f"({report.wall_seconds / max(1, report.ticks) * 1000:.2f} ms/tick wall)"
    )
    yield f"evidence  {report.audit_path}"
    yield ""
    yield "  SELF-REFERENTIAL. The plant, the twin and the corpus share one set of"
    yield "  kinematic equations, so this measures whether the loop stays stable,"
    yield "  never whether the gates are right."
    yield ""
    yield "  trends, warm-up excluded"
    yield (
        f"  {'series':<34}{'first half':>12}{'second half':>13}"
        f"{'drift':>12}{'range':>11}{'turns':>7}"
    )
    for series in report.series:
        yield (
            f"  {series.label:<34}{series.first_half_mean:>12.4f}{series.second_half_mean:>13.4f}"
            f"{series.drift:>+12.4f}{series.span:>11.4f}{series.direction_changes:>7}"
        )
    yield ""
    yield "  what governed, by issued-command origin"
    for name, count in totals(report.windows, lambda w: w.origins):
        yield f"  {name:<34}{count:>12}{count / max(1, report.ticks):>13.1%}"
    arbitrations = totals(report.windows, lambda w: w.arbitrations)
    overridden = sum(w.proposals_issued_under_veto for w in report.windows)
    if overridden:
        yield (
            f"  {'(of which issued under a VETO)':<34}{overridden:>12}"
            f"{overridden / max(1, report.ticks):>13.1%}"
        )
    yield ""
    yield "  cold-path arbitration"
    if arbitrations:
        for name, count in arbitrations:
            yield f"  {name:<34}{count:>12}"
    else:
        yield "  none ran -- the knowledge base was dormant"
    shadowed = [w for w in report.windows if w.mean_shadow_divergence is not None]
    if shadowed:
        first, last = shadowed[0], shadowed[-1]
        peak = max(w.max_shadow_divergence or 0.0 for w in shadowed)
        digests = {w.shadow_digest for w in shadowed if w.shadow_digest}
        yield ""
        yield "  FB2 in shadow -- adapted, read by nothing, gating nothing"
        yield (
            f"  {'twin divergence':<34}"
            f"{first.mean_shadow_divergence:>12.5f} -> {last.mean_shadow_divergence:.5f}"
            f"  peak {peak:.5f}"
        )
        yield (
            f"  {'distinct shadow digests':<34}{len(digests):>12}"
            f"{'  -- the shadow never moved' if len(digests) <= 1 else ''}"
        )
        if first.mean_live_score is not None and last.mean_shadow_score is not None:
            yield (
                f"  {'non-conformity, live twin':<34}"
                f"{first.mean_live_score:>12.4f} -> {last.mean_live_score:.4f}"
            )
            yield (
                f"  {'non-conformity, shadow twin':<34}"
                f"{first.mean_shadow_score:>12.4f} -> {last.mean_shadow_score:.4f}"
            )
            yield (
                "  a shadow score falling away from the live one is the "
                "statistical gate disarming itself"
            )

    yield ""
    yield "  criteria"
    for criterion in report.criteria:
        mark = {True: "pass", False: "FAIL", None: "n/a "}[criterion.passed]
        yield f"  [{mark}] {criterion.name}"
        yield f"         {criterion.detail}"
    yield ""
    yield f"  verdict: {'STABLE over this run' if report.stable else 'NOT STABLE'}"


def main(argv: Sequence[str] | None = None) -> int:
    """Run a soak and report it.

    Args:
        argv: Argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` if every measurable criterion held, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--window", "-w", type=int, default=_DEFAULT_WINDOW)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--output", "-o", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    parser.add_argument(
        "--placeholder",
        action="store_true",
        help="drive the deterministic placeholder policy instead of a checkpoint",
    )
    parser.add_argument(
        "--cold-path",
        choices=sorted(COLD_PATH_CONTEXTS),
        default="off",
        help=(
            "engage L9's knowledge base: 'open' in a context the seed profiles "
            "cover, 'tunnel' in one none of them does. 'off' is what every run "
            "before August 2026 used"
        ),
    )
    parser.add_argument(
        "--shadow-fb2",
        action="store_true",
        help=(
            "run FB2 against a twin nothing reads, and report how far it would "
            "have moved the model. Changes no verdict and gates no criterion"
        ),
    )
    parser.add_argument("--progress-every", type=int, default=10)
    arguments = parser.parse_args(argv)

    policy_path: Path | None = None if arguments.placeholder else arguments.policy
    if policy_path is not None and not policy_path.exists():
        print(f"no policy at {policy_path}; train one with `python -m training.train_policy`")
        print("or pass --placeholder to soak the deterministic controller instead")
        return 1

    report = run(
        ticks=arguments.ticks,
        window=arguments.window,
        seed=arguments.seed,
        policy_path=policy_path,
        output=arguments.output,
        progress_every=arguments.progress_every,
        cold_path=arguments.cold_path,
        shadow_fb2=arguments.shadow_fb2,
    )
    print()
    for line in render(report):
        print(line)
    figure = arguments.output / "soak.png"
    if plot(report.windows, figure):
        print(f"\n  figure:  {figure}")
    print(f"  series:  {arguments.output / 'windows.jsonl'}")
    print(f"  summary: {arguments.output / 'summary.json'}")
    return 0 if report.stable else 1


if __name__ == "__main__":
    sys.exit(main())
