"""E17 fault-injection integrity audit.

Answers one question per fault, empirically: **does the injected corruption
actually reach each stage, as delivered, or is it regenerated from ground truth
somewhere along the way?**

This exists because the 30-seed sweep's headline result was an artefact. The
position channel is rebuilt from `plant._state[1]` inside `_publish_state` when
redundant sensing is active (the default since ADR-0033), so `FaultInjector`'s
POSITION_Y corruption never reached the pipeline -- while the *returned* payload
still carried it, so the instrumentation reported a fault that nothing consumed.

The rule this module enforces: **never trust the injector's output as evidence
that a fault happened.** Measure the signal where each consumer reads it.

Four boundaries are instrumented:

    1. injector      -- `FaultInjector.corrupt` return value
    2. bus / L1      -- the payload actually published, read off the fused frame
    3. estimator in  -- the `Measurement` values handed to the UKF
    4. downstream    -- innovation and fast state, via the tick observer

    python -m benchmarks.e17_integrity
"""

from __future__ import annotations

import argparse
import contextlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from astra.kernel.enums import SensorModality
from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.discriminability import CHANNEL_SIGMAS, _FAULT_FIRST
from benchmarks.fault_study import SCENARIOS
from training import closed_loop as cl
from training import redundant as rd
from training.closed_loop import drive_closed_loop
from training.faults import FaultChannel, FaultInjector

# Which payload key each scenario is *intended* to corrupt. Declared here from
# the scenario definitions in `fault_study.py`, not inferred from results.
INTENDED_CHANNEL: dict[str, str | None] = {
    "imu_dropout": None,  # frame-level: suppresses the IMU sample entirely
    "position_bias": FaultChannel.POSITION_Y.value,
    "position_drift": FaultChannel.POSITION_Y.value,
    "speed_stuck": FaultChannel.SPEED.value,
    "speed_bias": FaultChannel.SPEED.value,
    "lateral_noise": FaultChannel.LATERAL_ACCELERATION.value,
}

SEVERITY: dict[str, str] = {
    "imu_dropout": "suppress IMU",
    "position_bias": "1.0 m",
    "position_drift": "2.0 m final",
    "speed_stuck": "hold",
    "speed_bias": "3.0 m/s",
    "lateral_noise": "sigma x25",
}

_EPS = 1e-9


@dataclass(slots=True)
class Capture:
    """Everything one run exposes at the four instrumented boundaries."""

    injector_out: list[dict[str, float] | None] = field(default_factory=list)
    bus_imu: list[dict[str, float] | None] = field(default_factory=list)
    bus_positions: list[dict[str, float]] = field(default_factory=list)
    estimator_in: list[tuple[float, ...] | None] = field(default_factory=list)
    innovation: list[float] = field(default_factory=list)
    est_y: list[float] = field(default_factory=list)
    truth_y: list[float] = field(default_factory=list)
    ticks: list[int] = field(default_factory=list)


@contextlib.contextmanager
def _instrumented(cap: Capture):
    """Patch the injector and **both** extractors for the duration of a run.

    Which extractor the pipeline uses depends on whether redundant sensing is
    active, and patching only one is how an audit silently measures nothing:
    the first version of this module patched ``RedundantExtractor`` alone and
    captured zero samples under ``single_channel=True``.
    """
    orig_corrupt = FaultInjector.corrupt
    orig_red = rd.RedundantExtractor.extract_fast
    orig_single = cl._Extractor.extract_fast

    def corrupt(self, payload, *, tick):  # noqa: ANN001
        out = orig_corrupt(self, payload, tick=tick)
        cap.injector_out.append(None if out is None else dict(out))
        return out

    def extract(self, frame):  # noqa: ANN001
        sample = frame.sample_for(SensorModality.IMU)
        cap.bus_imu.append(None if sample is None else dict(sample.payload))
        try:
            cap.bus_positions.append({str(k): float(v) for k, v in rd.positions(frame).items()})
        except Exception:  # noqa: BLE001 - a frame with no positions is data
            cap.bus_positions.append({})
        m = orig_red(self, frame)
        cap.estimator_in.append(None if m is None else tuple(float(v) for v in m.values))
        return m

    def extract_single(self, frame):  # noqa: ANN001
        sample = frame.sample_for(SensorModality.IMU)
        cap.bus_imu.append(None if sample is None else dict(sample.payload))
        cap.bus_positions.append({} if sample is None else {"IMU": float(sample.payload["y"])})
        m = orig_single(self, frame)
        cap.estimator_in.append(None if m is None else tuple(float(v) for v in m.values))
        return m

    FaultInjector.corrupt = corrupt  # type: ignore[method-assign]
    rd.RedundantExtractor.extract_fast = extract  # type: ignore[method-assign]
    cl._Extractor.extract_fast = extract_single  # type: ignore[method-assign]
    try:
        yield
    finally:
        FaultInjector.corrupt = orig_corrupt  # type: ignore[method-assign]
        rd.RedundantExtractor.extract_fast = orig_red  # type: ignore[method-assign]
        cl._Extractor.extract_fast = orig_single  # type: ignore[method-assign]


def _run(policy: Any, fault: Any, seed: int, ticks: int, **kw: Any) -> Capture:
    cap = Capture()

    def observe(s: Any) -> None:
        cap.ticks.append(s.tick)
        cap.innovation.append(float(getattr(s.record, "fast_innovation", np.nan) or np.nan))
        st = getattr(s.record, "fast_state", None)
        mean = getattr(st, "mean", None) if st is not None else None
        cap.est_y.append(float(mean[1]) if mean is not None and len(mean) > 1 else np.nan)
        cap.truth_y.append(float(s.lane_deviation_m))

    with _instrumented(cap):
        drive_closed_loop(
            policy=policy, ticks=ticks, seed=seed, observer=observe, fault=fault, **kw
        )
    return cap


def _differs(a: list, b: list, key: str | None, lo: int) -> tuple[bool, float]:
    """Max absolute difference between two per-tick sequences over the window."""
    best = 0.0
    n = min(len(a), len(b))
    for i in range(lo, n):
        x, y = a[i], b[i]
        if x is None or y is None:
            if (x is None) != (y is None):
                return True, float("inf")  # presence itself differs
            continue
        if key is not None:
            if key not in x or key not in y:
                continue
            x, y = x[key], y[key]
        if isinstance(x, dict):
            # No single channel named (dropout): compare every shared key. A
            # suppressed IMU publish leaves a *stale* sample on the bus rather
            # than an absent one -- staleness is what L1's 50 ms rule is for --
            # so the difference shows up in the values, not in presence.
            for k in set(x) & set(y):
                best = max(best, abs(float(x[k]) - float(y[k])))
            continue
        if isinstance(x, tuple):
            best = max(best, max(abs(p - q) for p, q in zip(x, y)))
        else:
            best = max(best, abs(float(x) - float(y)))
    return best > _EPS, best


def audit(
    policy: Any, seed: int, ticks: int, only: list[str] | None = None, **kw: Any
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scen in SCENARIOS:
        if only is not None and scen.name not in only:
            continue
        clean = _run(policy, None, seed, ticks, **kw)
        inj = FaultInjector(scen.build(_FAULT_FIRST, ticks - 1), seed=seed, sigmas=CHANNEL_SIGMAS)
        faulted = _run(policy, inj, seed, ticks, **kw)

        ch = INTENDED_CHANNEL[scen.name]
        # The injector runs only on the faulted arm, so its own output is
        # compared against the clean arm's *bus* payload -- the pre-corruption
        # reading is what the clean run published.
        inj_hit, inj_mag = _differs(faulted.injector_out, clean.bus_imu, ch, _FAULT_FIRST)
        l1_hit, l1_mag = _differs(faulted.bus_imu, clean.bus_imu, ch, _FAULT_FIRST)
        est_hit, est_mag = _differs(faulted.estimator_in, clean.estimator_in, None, _FAULT_FIRST)
        inn_hit, inn_mag = _differs(faulted.innovation, clean.innovation, None, _FAULT_FIRST)
        sty_hit, sty_mag = _differs(faulted.est_y, clean.est_y, None, _FAULT_FIRST)

        # Ground-truth bypass: the injector produced a corrupted reading, and
        # the bus did not carry it. That is the ADR-0033 regeneration.
        bypass = bool(inj_hit and not l1_hit)

        # Dropout is frame-level. A suppressed publish does not empty the slot:
        # the bus keeps the last-known IMU sample, so the frame carries a stale
        # reading rather than no reading. That is deliberate -- L1's staleness
        # rule is the defence this fault is built to exercise -- so "reaches L1"
        # is measured as the reading going stale, and `bypass` is meaningless
        # here because no channel value was regenerated.
        if scen.name == "imu_dropout":
            absent = sum(
                1 for i in range(_FAULT_FIRST, len(faulted.bus_imu)) if faulted.bus_imu[i] is None
            )
            bypass = False
            l1_mag = max(l1_mag, float(absent))
            l1_hit = l1_mag > _EPS

        rows.append(
            {
                "fault": scen.name,
                "severity": SEVERITY[scen.name],
                "channel": ch or "frame-level (IMU)",
                "injector_corrupts": inj_hit,
                "injector_magnitude": inj_mag,
                "reaches_L1": l1_hit,
                "L1_magnitude": l1_mag,
                "reaches_estimator": est_hit,
                "estimator_magnitude": est_mag,
                "reaches_downstream": bool(inn_hit or sty_hit),
                "innovation_magnitude": inn_mag,
                "est_state_magnitude": sty_mag,
                "ground_truth_bypass": bypass,
                "verdict": "INVALID" if (bypass or not est_hit) else "VALID",
            }
        )
    return rows


def render(rows: list[dict[str, Any]]) -> str:
    L = [
        "| Fault | Severity | Intended channel | Reaches L1? | Reaches estimator? | Reaches downstream? | Ground-truth bypass? | Verdict |",
        "|---|---|---|:--:|:--:|:--:|:--:|:--:|",
    ]
    tick = {True: "**yes**", False: "**NO**"}
    for r in rows:
        L.append(
            f"| `{r['fault']}` | {r['severity']} | `{r['channel']}` | "
            f"{tick[r['reaches_L1']]} | {tick[r['reaches_estimator']]} | "
            f"{tick[r['reaches_downstream']]} | "
            f"{'**YES**' if r['ground_truth_bypass'] else 'no'} | "
            f"{'**INVALID**' if r['verdict'] == 'INVALID' else 'VALID'} |"
        )
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=Path("var/policy/synthetic.pt"))
    ap.add_argument("--seed", type=int, default=20260731)
    ap.add_argument("--ticks", type=int, default=400)
    ap.add_argument("--out", type=Path, default=Path("results/E17_INTEGRITY"))
    args = ap.parse_args()

    policy = LearnedPolicy.load(args.policy)
    rows = audit(policy, args.seed, args.ticks)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "integrity.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (args.out / "integrity_table.md").write_text(render(rows), encoding="utf-8")

    print(render(rows))
    print()
    for r in rows:
        print(
            f"  {r['fault']:<15} injector={r['injector_magnitude']:<10.5g} "
            f"L1={r['L1_magnitude']:<10.5g} est_in={r['estimator_magnitude']:<10.5g} "
            f"innov={r['innovation_magnitude']:<10.5g} est_y={r['est_state_magnitude']:<10.5g}"
        )
    bad = [r["fault"] for r in rows if r["verdict"] == "INVALID"]
    print(f"\n  INVALID: {bad if bad else 'none'}")


if __name__ == "__main__":
    main()
