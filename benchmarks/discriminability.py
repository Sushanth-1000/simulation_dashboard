"""E17 -- fault discriminability profiling across pipeline stages.

The question
--------------
A fault enters at the sensor boundary and is transformed by every stage it
passes through. This measures **how separable a faulted run is from its matched
clean run** at each stage, using the statistic that stage actually publishes.

    D_s(f) = AUC( T_s | faulted , T_s | matched-clean )        in [0.5, 1.0]

`D_s = 0.5` means the stage carries no information distinguishing the faulted
run from the clean one. `D_s = 1.0` means perfect separation.

Derived, per `ASTRA_RESEARCH_FREEZE.md` section 8:

    R_s  = (D_s - 0.5) / (D_L1 - 0.5)         retention relative to sensing
    A(f) = min{ s : D_s < 0.60 }              the absorption point

What this does not measure
----------------------------
Discriminability is not information in the Shannon sense, and a fall in `D_s`
is **not** evidence that information was destroyed -- only that the statistic
this stage publishes no longer separates the two runs. Freeze section 13 forbids
the stronger wording and so does this module's output.

Pairing
---------
Faulted and clean runs share a seed, a policy and a tick index, so the pair
differs by the injected fault and by nothing else. AUC is computed over the
fault window only; ticks before the fault opens carry no signal by construction
and would dilute the estimate.

    python -m benchmarks.discriminability
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.fault_study import SCENARIOS
from training.closed_loop import CHANNEL_SIGMAS, TickSample, drive_closed_loop
from training.faults import FaultInjector

_SEED = 20260731
_TICKS = 400
_FAULT_FIRST = 200
_ABSORPTION_THRESHOLD = 0.60
_BOOTSTRAP = 2000


# --------------------------------------------------------------------------
# Stage statistics
# --------------------------------------------------------------------------
def _health_degraded_count(s: TickSample) -> float:
    """Number of modalities not HEALTHY. The right L1 statistic for a *dropout*.

    A dropout suppresses the reading entirely, so there is no value to compare;
    absence is the observable. For every other fault the stream stays fresh by
    construction and this statistic is identically zero in both arms -- which is
    the defect that invalidated the first E17 run.
    """
    health = getattr(s.record, "frame_health", None)
    if health is None:
        return float("nan")
    items = health.items() if hasattr(health, "items") else health
    return float(sum(1 for _, h in items if getattr(h, "name", str(h)) != "HEALTHY"))


def _measured_position(s: TickSample) -> float:
    """Lateral position as the sensors reported it: after fault, before fusion."""
    v = getattr(s, "measured_position_m", None)
    return float("nan") if v is None else float(v)


def _measured_speed(s: TickSample) -> float:
    """Speed as the sensors reported it: after fault, before fusion."""
    v = getattr(s, "measured_speed_mps", None)
    return float("nan") if v is None else float(v)


def _measured_lateral_accel(s: TickSample) -> float:
    """Lateral acceleration as the sensors reported it."""
    v = getattr(s, "measured_lateral_acceleration_mps2", None)
    return float("nan") if v is None else float(v)


DISPERSION_WINDOW = 10
"""Ticks in the rolling window for dispersion-type faults.

Fixed at 10 to match ``PATIENCE`` in ``training/redundant.py`` -- a constant the
project already committed to for "one excursion is noise, a sustained one is a
fault". Reusing it means the window was not chosen after seeing an E17 result.
"""


class _RollingDispersion:
    """Rolling standard deviation of a channel over ``DISPERSION_WINDOW`` ticks.

    ``NOISE_BURST`` adds zero-mean Gaussian noise, so it changes **dispersion**
    and not location. AUC on raw values tests a location shift and is blind to
    it -- which is why the corrected run still reported ``D_L1 = 0.504`` for
    ``lateral_noise``. This statistic tests the quantity the fault actually
    moves.

    Stateful across ticks, and therefore constructed fresh per run.
    """

    __slots__ = ("_channel", "_history")

    def __init__(self, channel: Callable[[TickSample], float]) -> None:
        self._channel = channel
        self._history: list[float] = []

    def __call__(self, s: TickSample) -> float:
        v = self._channel(s)
        if not np.isfinite(v):
            return float("nan")
        self._history.append(v)
        if len(self._history) > DISPERSION_WINDOW:
            self._history.pop(0)
        if len(self._history) < DISPERSION_WINDOW:
            return float("nan")  # window not yet full
        return float(np.std(self._history, ddof=1))


L1_STATISTIC: dict[str, Callable[[TickSample], float]] = {
    "imu_dropout": _health_degraded_count,
    "position_bias": _measured_position,
    "position_drift": _measured_position,
    "speed_stuck": _measured_speed,
    "speed_bias": _measured_speed,
    "lateral_noise": _measured_lateral_accel,
}
"""The raw observable each fault corrupts.

L1's statistic must be the signal the fault actually touches. Using one
statistic for every fault -- as the first E17 run did -- measures whether the
*health verdict* moved, not whether the *raw observation* did, and the two are
different questions. The channel mapping here mirrors `FaultChannel` in
`training/faults.py` exactly.
"""


def _innovation(s: TickSample) -> float:
    """L2a -- the filter's innovation. Computed before the estimate settles."""
    v = getattr(s.record, "fast_innovation", None)
    return float("nan") if v is None else float(v)


def _estimated_lateral(s: TickSample) -> float:
    """L2b -- lateral position as the filter concluded it. Post-estimation."""
    st = getattr(s.record, "fast_state", None)
    mean = getattr(st, "mean", None) if st is not None else None
    if mean is None or len(mean) < 2:
        return float("nan")
    return abs(float(mean[1]))


def _trust_index(s: TickSample) -> float:
    """L3 -- trust index. Derived from the innovation sequence."""
    t = getattr(s.record, "trust", None)
    v = getattr(t, "trust_index", None) if t is not None else None
    return float("nan") if v is None else float(v)


def _nonconformity(s: TickSample) -> float:
    """L6 -- the statistical gate's non-conformity score.

    Read from the STATISTICAL verdict's evidence rather than from
    ``TickSample.live_score``. The latter is populated only when the FB2 shadow
    is running, which the first E17 run did not enable -- that is why L6 was
    empty, and it was an observer-plumbing gap rather than a missing signal. The
    gate computes and records the score on every tick regardless.
    """
    sv = getattr(s.record, "safety_verdict", None)
    if sv is None:
        return float("nan")
    for gv in getattr(sv, "gate_verdicts", ()):
        if str(getattr(gv, "gate", "")).endswith("STATISTICAL"):
            for key, value in getattr(gv, "evidence", ()):
                if key == "non_conformity_score":
                    return float(value)
    return float("nan")


def _any_veto(s: TickSample) -> float:
    """L6/L7 -- did any gate object this tick. Binary."""
    sv = getattr(s.record, "safety_verdict", None)
    agg = getattr(sv, "aggregate", None) if sv is not None else None
    if agg is None:
        return float("nan")
    return 1.0 if getattr(agg, "name", str(agg)) != "PASS" else 0.0


def _posture(s: TickSample) -> float:
    """L8 -- fail-safe posture as an ordinal."""
    fs = getattr(s.record, "failsafe", None)
    st = getattr(fs, "state", None) if fs is not None else None
    if st is None:
        return float("nan")
    order = {"NOMINAL": 0.0, "DEGRADED": 1.0, "LIMP": 2.0, "HALT": 3.0}
    return order.get(getattr(st, "name", str(st)), float("nan"))


STAGES: tuple[tuple[str, str, Callable[[TickSample], float]], ...] = (
    ("L1", "raw measured channel", _health_degraded_count),  # replaced per scenario
    ("L2a", "innovation (pre-settle)", _innovation),
    ("L2b", "estimated state", _estimated_lateral),
    ("L3", "trust index", _trust_index),
    ("L6", "non-conformity score", _nonconformity),
    ("L7", "gate verdict", _any_veto),
    ("L8", "fail-safe posture", _posture),
)
"""Ordered by position in the pipeline. L1 is the only pre-estimation stage."""


# --------------------------------------------------------------------------
# AUC
# --------------------------------------------------------------------------
def auc(faulted: np.ndarray, clean: np.ndarray) -> float:
    """Return the Mann-Whitney AUC, folded to [0.5, 1.0].

    Direction is not assumed: a stage may move either way under a fault, and
    only the magnitude of the separation is of interest here. Ties contribute
    0.5, which is what makes a constant statistic return exactly 0.5 rather
    than an artefact of sort order.
    """
    f = faulted[np.isfinite(faulted)]
    c = clean[np.isfinite(clean)]
    if f.size == 0 or c.size == 0:
        return float("nan")
    if np.all(f == f[0]) and np.all(c == c[0]) and f[0] == c[0]:
        return 0.5
    pooled = np.concatenate([f, c])
    ranks = pooled.argsort().argsort().astype(float) + 1.0
    # average ranks for ties
    order = np.sort(pooled)
    for v in np.unique(pooled):
        idx = pooled == v
        if idx.sum() > 1:
            ranks[idx] = ranks[idx].mean()
    r_f = ranks[: f.size].sum()
    u = r_f - f.size * (f.size + 1) / 2.0
    a = u / (f.size * c.size)
    return max(a, 1.0 - a)  # fold: separation, not direction


def auc_ci(faulted: np.ndarray, clean: np.ndarray, n: int = _BOOTSTRAP) -> tuple[float, float]:
    """Percentile bootstrap interval for the AUC."""
    f = faulted[np.isfinite(faulted)]
    c = clean[np.isfinite(clean)]
    if f.size == 0 or c.size == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(_SEED)
    vals = [
        auc(rng.choice(f, f.size, replace=True), rng.choice(c, c.size, replace=True))
        for _ in range(n)
    ]
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Trace:
    """Per-tick stage statistics for one run, plus its operating regime.

    `veto_rate` and `mean_speed` are recorded because the n=1 second-policy
    checkpoint found the speed-channel result diverging on a policy that was
    vetoed on 70% of ticks and drove at half speed. Whether that is regime
    dependence or policy dependence cannot be separated without measuring the
    regime, so it is measured on every run rather than inferred afterwards.
    """

    values: dict[str, list[float]]
    ticks: list[int]
    speeds: list[float]
    veto_rate: float = float("nan")
    mean_speed: float = float("nan")
    speed_std: float = float("nan")
    total_ticks: int = 0
    veto_ticks: int = 0


def _collect(policy: Any, faults: Any, seed: int, ticks: int, stages: Any = None) -> Trace:
    stages = STAGES if stages is None else stages
    trace = Trace(values={code: [] for code, _, _ in stages}, ticks=[], speeds=[])

    def observe(s: TickSample) -> None:
        trace.ticks.append(s.tick)
        trace.speeds.append(float(s.speed_mps))
        for code, _, fn in stages:
            trace.values[code].append(fn(s))

    result = drive_closed_loop(
        policy=policy, ticks=ticks, seed=seed, observer=observe, fault=faults
    )
    trace.veto_rate = float(result.vetoed) / float(result.ticks) if result.ticks else float("nan")
    trace.total_ticks = int(result.ticks)
    trace.veto_ticks = int(result.vetoed)
    if trace.speeds:
        trace.mean_speed = float(np.mean(trace.speeds))
        trace.speed_std = float(np.std(trace.speeds, ddof=1)) if len(trace.speeds) > 1 else 0.0
    return trace


DISPERSION_FAULTS = frozenset({"lateral_noise"})
"""Faults whose mechanism changes dispersion rather than location.

Derived from ``FaultKind``: ``NOISE_BURST`` is the only kind that perturbs
variance. Declared here rather than inferred from results.
"""


def _stages_for(scenario_name: str) -> tuple[tuple[str, str, Callable[[TickSample], float]], ...]:
    """Return STAGES with L1 bound to the observable this fault actually moves.

    A fresh statistic object is built per call because the dispersion statistic
    carries per-run state.
    """
    base = L1_STATISTIC.get(scenario_name, _health_degraded_count)
    if scenario_name in DISPERSION_FAULTS:
        return (("L1", f"raw channel dispersion (w={DISPERSION_WINDOW})", _RollingDispersion(base)),) + STAGES[1:]
    label = "raw measured channel" if base is not _health_degraded_count else "stream health (dropout)"
    return (("L1", label, base),) + STAGES[1:]


def profile(policy: Any, seed: int, ticks: int) -> dict[str, Any]:
    """Profile every scenario against its matched clean run."""
    out: dict[str, Any] = {}
    for scenario in SCENARIOS:
        clean = _collect(policy, None, seed, ticks, _stages_for(scenario.name))
        window = [i for i, t in enumerate(clean.ticks) if t >= _FAULT_FIRST]
        specs = scenario.build(_FAULT_FIRST, ticks - 1)
        injector = FaultInjector(specs, seed=seed, sigmas=CHANNEL_SIGMAS)
        stages = _stages_for(scenario.name)
        faulted = _collect(policy, injector, seed, ticks, stages)
        rows = []
        for code, label, _ in stages:
            f = np.asarray([faulted.values[code][i] for i in window], dtype=float)
            c = np.asarray([clean.values[code][i] for i in window], dtype=float)
            d = auc(f, c)
            lo, hi = auc_ci(f, c)
            rows.append(
                {"stage": code, "label": label, "D": d, "ci_lo": lo, "ci_hi": hi, "n": len(window)}
            )
        d_l1 = rows[0]["D"]
        for r in rows:
            denom = d_l1 - 0.5
            r["R"] = (r["D"] - 0.5) / denom if denom > 1e-9 and np.isfinite(r["D"]) else float("nan")
        absorbed = [r["stage"] for r in rows if np.isfinite(r["D"]) and r["D"] < _ABSORPTION_THRESHOLD]
        crossings = sum(
            1
            for a, b in zip(rows, rows[1:])
            if np.isfinite(a["D"])
            and np.isfinite(b["D"])
            and (a["D"] < _ABSORPTION_THRESHOLD) != (b["D"] < _ABSORPTION_THRESHOLD)
        )
        out[scenario.name] = {
            "stages": rows,
            "absorption_point": absorbed[0] if absorbed else None,
            "threshold_crossings": crossings,
            "unique_absorption": bool(absorbed) and crossings <= 1,
            "regime": {
                "veto_rate_clean": clean.veto_rate,
                "veto_rate_faulted": faulted.veto_rate,
                "mean_speed_clean": clean.mean_speed,
                "mean_speed_faulted": faulted.mean_speed,
                "speed_std_faulted": faulted.speed_std,
                "total_ticks": faulted.total_ticks,
                "veto_ticks_faulted": faulted.veto_ticks,
            },
        }
    return out


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def render(result: dict[str, Any]) -> None:
    print()
    print("E17 -- fault discriminability by pipeline stage")
    print("=" * 78)
    print(f"  D_s = AUC(faulted, matched-clean), folded to [0.5, 1.0]")
    print(f"  absorption point A(f) = first stage with D_s < {_ABSORPTION_THRESHOLD}")
    print()
    header = "  scenario         " + "".join(f"{c:>10}" for c, _, _ in STAGES) + "      A(f)"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, data in result.items():
        cells = "".join(
            f"{r['D']:>10.3f}" if np.isfinite(r["D"]) else f"{'--':>10}" for r in data["stages"]
        )
        ap = data["absorption_point"] or "none"
        print(f"  {name:<17}{cells}{ap:>10}")
    print()
    print("  A(f) = 'none' means no stage fell below the threshold: the fault")
    print("  stayed separable all the way through.")
    print()
    print("  Read D_s = 0.5 as 'this stage's statistic does not separate the")
    print("  faulted run from the clean one'. It is NOT evidence that information")
    print("  was destroyed -- only that this statistic no longer carries it.")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=_SEED)
    ap.add_argument("--ticks", type=int, default=_TICKS)
    ap.add_argument("--policy", type=Path, default=Path("var/policy/synthetic.pt"))
    ap.add_argument("--output", type=Path, default=Path("var/discriminability"))
    args = ap.parse_args()

    policy = LearnedPolicy.load(args.policy)
    result = profile(policy, args.seed, args.ticks)
    render(result)

    args.output.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment_id": "E17",
        "seed": args.seed,
        "ticks": args.ticks,
        "policy": str(args.policy),
        "absorption_threshold": _ABSORPTION_THRESHOLD,
        "stages": [{"code": c, "label": l} for c, l, _ in STAGES],
        "scenarios": result,
    }
    (args.output / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  summary: {args.output / 'summary.json'}")


if __name__ == "__main__":
    main()
