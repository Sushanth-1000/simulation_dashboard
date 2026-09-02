"""E18-R1 - run-local (windowed) calibration.

Differs from E18 in exactly one respect: the threshold is estimated from each
run's own pre-injection prefix rather than pooled across 30 runs. Everything
else -- score extraction, driver, seeds, faults, severities -- is reused
unchanged, so the comparison isolates the calibration scheme.

    calibration window  ticks   1..200   (clean by construction: fault onset is 200)
    evaluation window   ticks 201..400

Window length is fixed by `_FAULT_FIRST`, set in E17 long before OD-8 was
examined. It is not a searched parameter. See `preregistration.md` section 2.

    python -m benchmarks.e18r1_calibrate
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
from benchmarks.discriminability import _FAULT_FIRST, _stages_for, auc
from benchmarks.e18_evaluate import SEVERITIES, _run

EPS = 0.05
TICKS = 400
POLICIES = {"P1": "synthetic", "P3": "jerkscaled"}  # P2 excluded, per preregistration section 6
CLEAN_TEST_BASE = 20261001
FAULT_TEST_BASE = 20260731
N_SEEDS = 30
CALIBRATION_VERSION = "R1-v2-runlocal"


def conformal_q(scores: np.ndarray, eps: float = EPS) -> float:
    """Finite-sample conformal order statistic, identical to E18's estimator."""
    s = np.sort(scores[np.isfinite(scores)])
    n = s.size
    if n == 0:
        return float("nan")
    k = int(np.ceil((n + 1) * (1.0 - eps)))
    return float(s[-1] if k > n else s[k - 1])


def _split(run: dict) -> tuple[np.ndarray, np.ndarray]:
    """(calibration prefix, evaluation window) scores for one run."""
    sc = np.asarray(run["scores"], float)
    tk = np.asarray(run["ticks"], int) if "ticks" in run else np.arange(len(sc))
    cal = sc[tk < _FAULT_FIRST]
    ev = sc[tk >= _FAULT_FIRST]
    return cal[np.isfinite(cal)], ev[np.isfinite(ev)]


def _clean_run(policy: Any, seed: int) -> dict:
    r = _run(policy, "position_bias", None, seed, active=False)  # fault inactive => clean
    return {"scores": r["scores"], "ticks": r["ticks"], "est_y": r["est_y"], "values": r["values"]}


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    ap.add_argument("--skip-faults", action="store_true")
    ap.add_argument("--out", type=Path,
                    default=Path("experiments/phase5_od8_h7/E18_R1/raw_results"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    commit = git_commit()
    pols = {k: LearnedPolicy.load(Path(f"var/policy/{v}.pt")) for k, v in POLICIES.items()}
    t0 = time.time()

    # ---- PRIMARY: clean runs, run-local threshold, run-level FAR ----------
    clean_records: list[dict] = []
    print("PRIMARY - clean runs, run-local calibration")
    for pname, policy in pols.items():
        for i in range(a.seeds):
            seed = CLEAN_TEST_BASE + i
            r = _clean_run(policy, seed)
            cal, ev = _split(r)
            q = conformal_q(cal)
            alarms = int((ev > q).sum())
            far = alarms / ev.size if ev.size else float("nan")
            clean_records.append({
                "experiment": "E18-R1", "git_commit": commit,
                "calibration_version": CALIBRATION_VERSION,
                "policy": pname, "seed": seed, "condition": "clean",
                "threshold": q, "calibration_n": int(cal.size),
                "calibration_window": "ticks 1-200", "evaluation_n": int(ev.size),
                "alarm_count": alarms, "run_far": far,
                "cal_mean": float(cal.mean()), "cal_sd": float(cal.std(ddof=1)),
                "eval_mean": float(ev.mean()), "eval_sd": float(ev.std(ddof=1)),
                "drift": float(ev.mean() - cal.mean()),
                "threshold_margin": float(ev.mean() - q),
            })
        fars = [x["run_far"] for x in clean_records if x["policy"] == pname]
        inband = sum(1 for v in fars if EPS / 2 <= v <= 2 * EPS)
        print(f"  {pname}: runs in band {inband}/{len(fars)}   "
              f"median FAR {np.median(fars):.2%}   [{time.time() - t0:.0f}s]", flush=True)
    (a.out / "clean_runlocal.json").write_text(json.dumps(clean_records, indent=2, default=str),
                                               encoding="utf-8")

    if a.skip_faults:
        print("\n  (faulted evaluation skipped)")
        return

    # ---- SECONDARY: detection after recalibration -------------------------
    print("\nSECONDARY - faulted runs, detection at run-local thresholds")
    fault_records: list[dict] = []
    combos = [(f, lvl, mag) for f, spec in SEVERITIES.items() for lvl, mag in spec["levels"].items()]
    total = len(combos) * len(pols) * a.seeds
    done = 0
    for pname, policy in pols.items():
        for fault, level, mag in combos:
            for i in range(a.seeds):
                seed = FAULT_TEST_BASE + i
                clean = _run(policy, fault, mag, seed, False)
                faulted = _run(policy, fault, mag, seed, True)
                # Threshold from the FAULTED run's own clean prefix - causally
                # realizable and uncontaminated, since injection starts at 200.
                cal_f, ev_f = _split(faulted)
                cal_c, ev_c = _split(clean)
                q = conformal_q(cal_f)
                alarms = ev_f > q
                first = next((k for k, v in enumerate(alarms) if v), None)
                win = [j for j, t in enumerate(clean["ticks"]) if t >= _FAULT_FIRST]
                D = {}
                for code, _, _ in _stages_for(fault):
                    c = np.array([clean["values"][code][j] for j in win], float)
                    fv = np.array([faulted["values"][code][j] for j in win], float)
                    D[code] = auc(fv, c)
                ey_c = float(np.nanmean([clean["est_y"][j] for j in win]))
                ey_f = float(np.nanmean([faulted["est_y"][j] for j in win]))
                fault_records.append({
                    "experiment": "E18-R1", "git_commit": commit,
                    "calibration_version": CALIBRATION_VERSION,
                    "policy": pname, "fault": fault, "severity_level": level,
                    "severity_value": mag, "seed": seed, "condition": "faulted",
                    "threshold": q, "calibration_n": int(cal_f.size),
                    "alarm_rate_faulted": float(alarms.mean()) if ev_f.size else float("nan"),
                    "alarm_rate_clean_same_seed": float((ev_c > conformal_q(cal_c)).mean())
                    if ev_c.size else float("nan"),
                    "detected": bool(alarms.any()),
                    "detection_latency_ticks": None if first is None else int(first),
                    "threshold_margin": float(ev_f.mean() - q) if ev_f.size else float("nan"),
                    "D": D,
                    "fault_reached_estimator": bool(abs(ey_f - ey_c) > 1e-9),
                })
                done += 1
            print(f"  [{done:>4}/{total}] {pname} {fault} {level}  {time.time() - t0:.0f}s",
                  flush=True)
    (a.out / "faulted_runlocal.json").write_text(json.dumps(fault_records, indent=2, default=str),
                                                 encoding="utf-8")
    reached = sum(1 for r in fault_records if r["fault_reached_estimator"])
    print(f"\n  {len(fault_records)} faulted records | reached estimator {reached}/{len(fault_records)}")
    print(f"  -> {a.out}")


if __name__ == "__main__":
    main()
