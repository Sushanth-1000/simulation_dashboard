"""E17 red-team negative controls.

Four experiments designed to expose false conclusions, not to confirm them.

    A  fault on a channel the target stage does not consume  -> expect no effect
    B  fault on the actual estimator input                   -> expect an effect
    C  ground-truth bypass disabled (`single_channel=True`)  -> expect the
       position fault to propagate, which is what proves the ADR-0033
       regeneration is the mechanism rather than a story that fits
    D  clean data, no fault                                  -> expect no
       systematic fault evidence

Control C is the load-bearing one. If disabling redundant sensing makes the
position fault reach the estimator, the bypass diagnosis is established
causally. If it does not, the diagnosis is wrong and must be withdrawn.

    python -m benchmarks.e17_controls
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.discriminability import (
    CHANNEL_SIGMAS,
    _FAULT_FIRST,
    _collect,
    _stages_for,
    auc,
)
from benchmarks.fault_study import SCENARIOS
from training.faults import FaultInjector

SCEN = {s.name: s for s in SCENARIOS}
STAGE_KEYS = ("L1", "L2a", "L2b", "L3", "L6", "L7", "L8")


def _profile(policy: Any, name: str, seed: int, ticks: int, **kw: Any) -> dict[str, float]:
    """D_s for one scenario, with extra kwargs threaded to the closed loop."""
    scen = SCEN[name]
    stages = _stages_for(name)
    clean = _collect_kw(policy, None, seed, ticks, stages, kw)
    win = [i for i, t in enumerate(clean.ticks) if t >= _FAULT_FIRST]
    inj = FaultInjector(scen.build(_FAULT_FIRST, ticks - 1), seed=seed, sigmas=CHANNEL_SIGMAS)
    faulted = _collect_kw(policy, inj, seed, ticks, _stages_for(name), kw)
    out = {}
    for code, _, _ in stages:
        c = np.array([clean.values[code][i] for i in win], float)
        f = np.array([faulted.values[code][i] for i in win], float)
        out[code] = auc(f, c)
    return out


def _collect_kw(policy, fault, seed, ticks, stages, kw):  # noqa: ANN001, ANN201
    """`_collect`, but able to pass `single_channel` through to the closed loop."""
    if not kw:
        return _collect(policy, fault, seed, ticks, stages)
    from training.closed_loop import TickSample, drive_closed_loop  # noqa: F401
    from benchmarks.discriminability import Trace

    trace = Trace(values={c: [] for c, _, _ in stages}, ticks=[], speeds=[])

    def observe(s):  # noqa: ANN001
        trace.ticks.append(s.tick)
        trace.speeds.append(float(s.speed_mps))
        for code, _, fn in stages:
            trace.values[code].append(fn(s))

    r = drive_closed_loop(
        policy=policy, ticks=ticks, seed=seed, observer=observe, fault=fault, **kw
    )
    trace.veto_rate = float(r.vetoed) / float(r.ticks) if r.ticks else float("nan")
    trace.total_ticks, trace.veto_ticks = int(r.ticks), int(r.vetoed)
    if trace.speeds:
        trace.mean_speed = float(np.mean(trace.speeds))
    return trace


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=Path("var/policy/synthetic.pt"))
    ap.add_argument("--seed", type=int, default=20260731)
    ap.add_argument("--ticks", type=int, default=400)
    ap.add_argument("--out", type=Path, default=Path("results/E17_INTEGRITY"))
    args = ap.parse_args()
    policy = LearnedPolicy.load(args.policy)
    res: dict[str, Any] = {}

    def show(title: str, prof: dict[str, float], expect: str) -> None:
        row = "  ".join(f"{k}={prof.get(k, float('nan')):.3f}" for k in STAGE_KEYS)
        print(f"\n{title}\n  expect: {expect}\n  {row}")

    # --- A: channel the estimator's position path does not consume ----------
    # position_bias under the *default* (redundant) path. The position channel
    # is regenerated, so this is a fault on a signal nothing consumes.
    a = _profile(policy, "position_bias", args.seed, args.ticks)
    res["A_unconsumed_channel"] = a
    show("CONTROL A - position_bias, redundancy ON (channel not consumed)", a, "no downstream effect: D ~ 0.5 from L2a on")

    # --- B: fault on the actual estimator input ------------------------------
    b = _profile(policy, "speed_bias", args.seed, args.ticks)
    res["B_consumed_channel"] = b
    show("CONTROL B - speed_bias (channel IS consumed)", b, "measurable downstream effect")

    # --- C: disable the ground-truth regeneration ----------------------------
    # Measured at the BOUNDARY, not end-to-end. The first version of this
    # control compared D_s with redundancy on and off and concluded "bypass not
    # confirmed" -- wrong, because D_s is confounded by closed-loop
    # compensation: the vehicle steers to null a position bias, so the sensor
    # reading returns toward nominal even while the fault is fully present in
    # the signal. Only the delivered signal answers the question.
    from benchmarks.e17_integrity import audit as integrity_audit

    on = integrity_audit(policy, args.seed, args.ticks, only=["position_bias", "position_drift"])
    off = integrity_audit(
        policy, args.seed, args.ticks, only=["position_bias", "position_drift"],
        single_channel=True,
    )
    res["C_bypass_on"] = on
    res["C_bypass_off"] = off
    print("\nCONTROL C - ground-truth bypass, measured at the delivered signal")
    print("  expect: redundancy OFF restores propagation if the diagnosis is right")
    print(f"  {'fault':<16}{'redundancy':<12}{'injector':>10}{'L1':>10}{'estimator':>11}{'innov':>10}")
    for label, rows in (("ON", on), ("OFF", off)):
        for r in rows:
            print(
                f"  {r['fault']:<16}{label:<12}{r['injector_magnitude']:>10.4g}"
                f"{r['L1_magnitude']:>10.4g}{r['estimator_magnitude']:>11.4g}"
                f"{r['innovation_magnitude']:>10.4g}"
            )
    restored = all(r["reaches_estimator"] for r in off)
    blocked = all(not r["reaches_estimator"] for r in on)
    res["C_verdict"] = (
        "BYPASS CONFIRMED - redundancy blocks the fault; disabling it restores propagation"
        if (restored and blocked)
        else "BYPASS NOT CONFIRMED - diagnosis must be revisited"
    )
    print(f"  -> {res['C_verdict']}")

    # --- D: clean data, two different seeds ----------------------------------
    # Clean-vs-clean on the SAME seed is bit-identical and would trivially give
    # 0.5. Different seeds is the honest control: it asks whether the metric
    # manufactures fault evidence from ordinary run-to-run variation.
    stages = _stages_for("position_bias")
    c1 = _collect(policy, None, args.seed, args.ticks, stages)
    c2 = _collect(policy, None, args.seed + 1, args.ticks, _stages_for("position_bias"))
    win = [i for i, t in enumerate(c1.ticks) if t >= _FAULT_FIRST]
    d = {
        code: auc(
            np.array([c2.values[code][i] for i in win], float),
            np.array([c1.values[code][i] for i in win], float),
        )
        for code, _, _ in stages
    }
    res["D_clean_vs_clean"] = d
    show("CONTROL D - clean vs clean, different seeds", d, "no systematic fault evidence; D near 0.5")
    hi = [k for k, v in d.items() if np.isfinite(v) and v > 0.75]
    res["D_verdict"] = (
        f"CAUTION - stages above 0.75 on clean data: {hi}" if hi else "OK - no stage manufactures strong evidence"
    )
    print(f"  -> {res['D_verdict']}")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "controls.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(f"\n  -> {args.out / 'controls.json'}")


if __name__ == "__main__":
    main()
