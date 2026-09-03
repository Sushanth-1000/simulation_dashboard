"""E18-R3c - duration-matched control: faults active for the WHOLE window.

R3b's channel faults (via FaultInjector) ran ticks 200-399 only, so their
detection came from the post-fault aftermath. R3c holds every fault active from
tick 200 to the end of the run, so "during-fault" and "the whole window" are the
same thing. Comparing R3c against R3b isolates aftermath detection from
sustained-fault detection.

Two corrections relative to R3b, both to make the fault genuinely sustained and
correctly scaled - not to change any threshold:
  - channel faults: last_tick = ticks-1 instead of the TICKS=400 constant.
  - position_drift: drift_per_tick scaled to reach the intended final offset at
    the true run end (R3b scaled it for a 200-tick window and then ran it for
    3200, reaching ~32 m instead of 2 m).

Frozen v3 threshold P1 = 3.7024. No quantile is computed in this module.

    python -m benchmarks.e18r3c_sustained
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

from astra.kernel.enums import SensorModality
from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.discriminability import CHANNEL_SIGMAS, _FAULT_FIRST
from benchmarks.e18_evaluate import SEVERITIES
from benchmarks.e18r3b_detect import RUN_LEVEL_BOUND
from training.closed_loop import DEFAULT_CHANNEL_SIGMAS, RedundantSensing, drive_closed_loop
from training.faults import (FaultChannel, FaultInjector, bias, dropout,
                             noise_burst, stuck_at)

FROZEN_V3_P1 = 3.7024
POLICY, CKPT = "P1", "synthetic"
BASE_SEED, N_SEEDS, TICKS = 20260731, 30, 3400
WINDOWS = (200, 400, 800, 1600, 3200)
LEVEL = "medium"
POSITION = ("position_bias", "position_drift")


def _injector_full(fault: str, mag: float | None, seed: int, ticks: int):
    """Channel-fault injector active for the whole window (last_tick = ticks-1)."""
    last = ticks - 1
    if fault == "speed_bias":
        specs = (bias(FaultChannel.SPEED, first_tick=_FAULT_FIRST, last_tick=last, offset=float(mag)),)
    elif fault == "speed_stuck":
        specs = (stuck_at(FaultChannel.SPEED, first_tick=_FAULT_FIRST, last_tick=last),)
    elif fault == "lateral_noise":
        specs = (noise_burst(FaultChannel.LATERAL_ACCELERATION, first_tick=_FAULT_FIRST,
                             last_tick=last, sigma_multiplier=float(mag)),)
    elif fault == "imu_dropout":
        specs = (dropout(first_tick=_FAULT_FIRST, last_tick=last),)
    else:
        return None
    return FaultInjector(specs, seed=seed, sigmas=CHANNEL_SIGMAS)


def _sensing_full(fault: str, mag: float | None, seed: int, ticks: int, active: bool):
    """Position fault sustained the whole window, drift scaled to the true run end."""
    if fault not in POSITION or not active:
        return RedundantSensing.build(sigmas=DEFAULT_CHANNEL_SIGMAS, seed=seed)
    span = ticks - 1 - _FAULT_FIRST            # CORRECTED: real run length, not TICKS=400
    return RedundantSensing.build(
        sigmas=DEFAULT_CHANNEL_SIGMAS, seed=seed,
        faulted=SensorModality.IMU, also_faulted=(SensorModality.GPS,),
        opens_at=_FAULT_FIRST,
        bias=float(mag) if fault == "position_bias" else 0.0,
        drift_per_tick=0.0 if fault == "position_bias" else float(mag) / span,
    )


def _run_sustained(policy, fault, mag, seed, ticks):
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
        fault=_injector_full(fault, mag, seed, ticks),
        redundant=_sensing_full(fault, mag, seed, ticks, True),
    )
    return {"scores": scores, "est_y": est_y}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    ap.add_argument("--ticks", type=int, default=TICKS)
    ap.add_argument("--out", type=Path,
                    default=Path("experiments/phase5_od8_h7/E18_R3c/raw_results"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    policy = LearnedPolicy.load(Path(f"var/policy/{CKPT}.pt"))
    q = FROZEN_V3_P1
    faults = [(f, SEVERITIES[f]["levels"].get(LEVEL)) for f in SEVERITIES
              if LEVEL in SEVERITIES[f]["levels"]]
    print(f"frozen threshold (v3, not recomputed): {POLICY} = {q}")
    print(f"faults sustained ticks 200-{a.ticks - 1}\n")

    records: list[dict[str, Any]] = []
    ticks_store: dict[str, list[float]] = {}
    t0 = time.time()
    for fault, mag in faults:
        for i in range(a.seeds):
            seed = BASE_SEED + i
            r = _run_sustained(policy, fault, mag, seed, a.ticks)
            sc = np.asarray(r["scores"], float)
            ev_all = sc[_FAULT_FIRST:]
            ev_all = ev_all[np.isfinite(ev_all)]
            key = f"{fault}_{seed}"
            ticks_store[key] = [round(float(x), 6) for x in sc]
            rec: dict[str, Any] = {
                "experiment_id": "E18-R3c", "git_commit": commit, "policy": POLICY,
                "fault": fault, "severity_level": LEVEL, "severity_value": mag,
                "seed": seed, "ticks": a.ticks, "threshold": q,
                "sustained": True, "tick_series_key": key,
                "nonfinite": int((~np.isfinite(sc)).sum()),
            }
            for n in WINDOWS:
                w = ev_all[:n]
                if w.size == n:
                    al = w > q
                    rate = float(al.mean())
                    rec[f"detected_{n}"] = bool(rate > RUN_LEVEL_BOUND[n])
                    rec[f"alarm_rate_{n}"] = rate
                    rec[f"bound_{n}"] = RUN_LEVEL_BOUND[n]
                    rec[f"margin_{n}"] = float(w.mean() - q)
                else:
                    rec[f"detected_{n}"] = None
                    rec[f"alarm_rate_{n}"] = float("nan")
                    rec[f"margin_{n}"] = float("nan")
            ey = np.asarray(r["est_y"], float)[_FAULT_FIRST:]
            rec["est_y_mean"] = float(np.nanmean(ey))
            records.append(rec)
        g = [x for x in records if x["fault"] == fault]

        def rate(n: int, rows=None) -> str:
            rows = rows if rows is not None else g
            vals = [x[f"detected_{n}"] for x in rows if x[f"detected_{n}"] is not None]
            return f"{np.mean(vals):>6.0%}" if vals else "     -"

        print(f"  {fault:<16} n=200 {rate(200)}  ->  n={WINDOWS[-1]} {rate(WINDOWS[-1])}   "
              f"[{time.time() - t0:.0f}s]", flush=True)

    (a.out / "faulted_sustained.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (a.out / "tick_series.json").write_text(json.dumps(ticks_store), encoding="utf-8")
    print(f"\n  {len(records)} runs -> {a.out / 'faulted_sustained.json'}")


if __name__ == "__main__":
    main()
