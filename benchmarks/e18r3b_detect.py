"""E18-R3b - does the long window detect faults, not just avoid false alarms?

Same frozen v3 threshold as R3, same window, same seeds. One variable:
evaluation window length. This module computes no quantile.

Per-tick scores ARE stored. R3 stored only per-run summaries, which meant a
corrected threshold could not be evaluated without a fresh run - a false
economy at ~2-3 MB per experiment.

    python -m benchmarks.e18r3b_detect
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.discriminability import _FAULT_FIRST
from benchmarks.e18_evaluate import SEVERITIES, _build_injector, _sensing
from training.closed_loop import drive_closed_loop

FROZEN_V3_P1 = 3.7024          # E18_R2/processed_results/verdict.json. Not recomputed.
POLICY, CKPT = "P1", "synthetic"
BASE_SEED, N_SEEDS, TICKS = 20260731, 30, 3400
WINDOWS = (200, 400, 800, 1600, 3200)
HZ = 20.0
LEVEL = "medium"               # E17-comparable severity

# Run-level decision boundary: the 95th percentile of the CLEAN per-run alarm
# rate at each window, from E18-R3's 30 clean P1 runs. Derived from clean data
# only; no faulted run informed it. See preregistration.md section 3b.
#
# "Any alarm in the window" is not a usable criterion at a 5 % per-tick false
# alarm rate - P(at least one alarm | 200 ticks) is about 1.0, so every run
# detects, clean ones included. This fixes the run-level false-positive rate
# at 5 % by construction.
RUN_LEVEL_BOUND = {200: 0.185, 400: 0.1405, 800: 0.110812,
                   1600: 0.088594, 3200: 0.072484}


def _run_faulted(policy: Any, fault: str, mag: float | None, seed: int, ticks: int) -> dict:
    scores: list[float] = []
    est_y: list[float] = []

    def obs(s: Any) -> None:
        sc = float("nan")
        sv = getattr(s.record, "safety_verdict", None)
        if sv is not None:
            for gv in getattr(sv, "gate_verdicts", ()):
                if str(getattr(gv, "gate", "")).endswith("STATISTICAL"):
                    for k, v in getattr(gv, "evidence", ()):
                        if k == "non_conformity_score":
                            sc = float(v)
        scores.append(sc)
        st = getattr(s.record, "fast_state", None)
        m = getattr(st, "mean", None) if st is not None else None
        est_y.append(float(m[1]) if m is not None and len(m) > 1 else float("nan"))

    drive_closed_loop(
        policy=policy, ticks=ticks, seed=seed, observer=obs,
        fault=_build_injector(fault, mag, seed),
        redundant=_sensing(fault, mag, seed, True),
    )
    return {"scores": scores, "est_y": est_y}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    ap.add_argument("--ticks", type=int, default=TICKS)
    ap.add_argument("--out", type=Path,
                    default=Path("experiments/phase5_od8_h7/E18_R3b/raw_results"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    policy = LearnedPolicy.load(Path(f"var/policy/{CKPT}.pt"))
    q = FROZEN_V3_P1
    faults = [(f, SEVERITIES[f]["levels"].get(LEVEL)) for f in SEVERITIES
              if LEVEL in SEVERITIES[f]["levels"]]

    print(f"frozen threshold (v3, not recomputed): {POLICY} = {q}")
    print(f"{len(faults)} faults x {a.seeds} seeds x {a.ticks} ticks, faulted arm only\n")

    records: list[dict[str, Any]] = []
    ticks_store: dict[str, list[float]] = {}
    t0 = time.time()
    for fault, mag in faults:
        for i in range(a.seeds):
            seed = BASE_SEED + i
            r = _run_faulted(policy, fault, mag, seed, a.ticks)
            sc = np.asarray(r["scores"], float)
            ev_all = sc[_FAULT_FIRST:]
            ev_all = ev_all[np.isfinite(ev_all)]
            key = f"{fault}_{seed}"
            ticks_store[key] = [round(float(x), 6) for x in sc]

            rec: dict[str, Any] = {
                "experiment_id": "E18-R3b", "git_commit": commit, "policy": POLICY,
                "fault": fault, "severity_level": LEVEL, "severity_value": mag,
                "seed": seed, "ticks": a.ticks, "threshold": q,
                "calibration_version": "v3-frozen-from-R2",
                "tick_series_key": key,
                "nonfinite": int((~np.isfinite(sc)).sum()),
            }
            for n in WINDOWS:
                w = ev_all[:n]
                if w.size == n:
                    al = w > q
                    first = next((k for k, v in enumerate(al) if v), None)
                    rate = float(al.mean())
                    rec[f"detected_{n}"] = bool(rate > RUN_LEVEL_BOUND[n])
                    rec[f"any_alarm_{n}"] = bool(al.any())   # kept for the record
                    rec[f"alarm_rate_{n}"] = rate
                    rec[f"bound_{n}"] = RUN_LEVEL_BOUND[n]
                    rec[f"latency_{n}"] = None if first is None else int(first)
                    rec[f"margin_{n}"] = float(w.mean() - q)
                else:
                    rec[f"detected_{n}"] = None
                    rec[f"alarm_rate_{n}"] = float("nan")
                    rec[f"latency_{n}"] = None
                    rec[f"margin_{n}"] = float("nan")
            h = ev_all.size // 2
            rec["drift_over_sd"] = float(
                abs(ev_all[h:].mean() - ev_all[:h].mean()) / ev_all.std(ddof=1)
            ) if ev_all.std(ddof=1) > 0 else float("nan")
            ey = np.asarray(r["est_y"], float)[_FAULT_FIRST:]
            rec["est_y_mean"] = float(np.nanmean(ey))
            records.append(rec)

        g = [x for x in records if x["fault"] == fault]

        def rate(n: int) -> str:
            vals = [x[f"detected_{n}"] for x in g if x[f"detected_{n}"] is not None]
            return f"{np.mean(vals):>6.0%}" if vals else "     -"

        print(f"  {fault:<16} n=200 {rate(200)}  ->  n={WINDOWS[-1]} {rate(WINDOWS[-1])}   "
              f"[{time.time() - t0:.0f}s]", flush=True)

    (a.out / "faulted_long.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (a.out / "tick_series.json").write_text(json.dumps(ticks_store), encoding="utf-8")
    print(f"\n  {len(records)} runs -> {a.out / 'faulted_long.json'}")
    print(f"  per-tick series -> {a.out / 'tick_series.json'} "
          f"({(a.out / 'tick_series.json').stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
