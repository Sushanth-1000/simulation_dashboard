"""E18-R2 - matched-window pooled calibration (calibration version 3).

One change from E18 version 1: the calibration sample is drawn from ticks
200-399 instead of 0-399, matching the window the monitor is evaluated in.
Everything else -- pooling, estimator, eps, seeds, score data -- is identical.

No new closed-loop runs. The existing clean score files already contain all 400
ticks per run, so the score data is byte-identical to E18's and any difference
in outcome is attributable to the calibration window alone.

    python -m benchmarks.e18r2_calibrate
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from benchmarks.e18_evaluate import FROZEN_QUANTILE as V1_QUANTILE

EPS = 0.05
CAL_LO, CAL_HI = 200, 400  # matched window, fixed by _FAULT_FIRST
POLICIES = ("P1", "P3", "P2")  # P2 computed for the record only; untouched, not claimed
PRIMARY = "P1"
E18 = Path("experiments/phase5_od8_h7/E18_OD8_CALIBRATION/raw_results")
OUT = Path("experiments/phase5_od8_h7/E18_R2")
CALIBRATION_VERSION = "R2-v3-matched-pooled"


def conformal_q(scores: np.ndarray, eps: float = EPS) -> float:
    s = np.sort(scores[np.isfinite(scores)])
    n = s.size
    if n == 0:
        return float("nan")
    k = int(np.ceil((n + 1) * (1.0 - eps)))
    return float(s[-1] if k > n else s[k - 1])


def runs_of(doc: dict, p: str) -> list[np.ndarray]:
    return [np.asarray(r["scores"], float) for r in doc["runs"][p]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eps", type=float, default=EPS)
    a = ap.parse_args()
    cal = json.loads((E18 / "calibration.json").read_text(encoding="utf-8"))
    tst = json.loads((E18 / "clean_test.json").read_text(encoding="utf-8"))
    (OUT / "raw_results").mkdir(parents=True, exist_ok=True)
    (OUT / "processed_results").mkdir(parents=True, exist_ok=True)

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    config = {
        "calibration_version": CALIBRATION_VERSION, "scheme": "pooled, matched window",
        "calibration_window_ticks": [CAL_LO + 1, CAL_HI],
        "evaluation_window_ticks": [CAL_LO + 1, CAL_HI],
        "epsilon": a.eps, "estimator": "ceil((n+1)(1-eps)) order statistic",
        "acceptance_band": [a.eps / 2, 2 * a.eps],
        "primary_criterion": f"{PRIMARY} >= 24/30 runs in band",
    }
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]

    # ---- integrity: window bounds and sample counts -----------------------
    print(f"INTEGRITY  calibration window ticks {CAL_LO + 1}-{CAL_HI}  (no pre-200 tick included)")
    thresholds: dict[str, float] = {}
    records: list[dict] = []
    for p in POLICIES:
        c = np.concatenate([r[CAL_LO:CAL_HI] for r in runs_of(cal, p)])
        nonfinite = int((~np.isfinite(c)).sum())
        c = c[np.isfinite(c)]
        thresholds[p] = conformal_q(c, a.eps)
        print(f"  {p}: calibration n = {c.size:>5}  nonfinite = {nonfinite}  "
              f"q_v3 = {thresholds[p]:.4f}   (v1 was {V1_QUANTILE[p]:.4f}, "
              f"{'lower' if thresholds[p] < V1_QUANTILE[p] else 'higher'})")

    (OUT / "processed_results" / "configuration.json").write_text(
        json.dumps({"config_hash": config_hash, "thresholds": thresholds, **config}, indent=2),
        encoding="utf-8")
    print(f"\nFROZEN as calibration version 3, config_hash {config_hash}\n")

    # ---- held-out per-run evaluation ---------------------------------------
    print("HELD-OUT CLEAN EVALUATION (per run, ticks 201-400)")
    summary: dict[str, dict] = {}
    for p in POLICIES:
        q = thresholds[p]
        fars = []
        for i, r in enumerate(runs_of(tst, p)):
            ev = r[CAL_LO:CAL_HI]
            ev = ev[np.isfinite(ev)]
            alarms = int((ev > q).sum())
            far = alarms / ev.size if ev.size else float("nan")
            fars.append(far)
            records.append({
                "experiment_id": "E18-R2", "git_commit": commit, "config_hash": config_hash,
                "calibration_version": CALIBRATION_VERSION, "policy": p,
                "seed": tst["runs"][p][i]["seed"], "condition": "clean",
                "calibration_window": f"ticks {CAL_LO + 1}-{CAL_HI} pooled",
                "threshold": q, "evaluation_n": int(ev.size), "alarm_count": alarms,
                "run_far": far, "in_band": bool(a.eps / 2 <= far <= 2 * a.eps),
                "eval_mean": float(ev.mean()), "eval_sd": float(ev.std(ddof=1)),
                "threshold_margin": float(ev.mean() - q),
            })
        f = np.array(fars)
        inb = int(((f >= a.eps / 2) & (f <= 2 * a.eps)).sum())
        summary[p] = {
            "threshold": q, "runs_in_band": inb, "n_runs": int(f.size),
            "pooled_far": float(f.mean()), "median_far": float(np.median(f)),
            "iqr": [float(np.percentile(f, 25)), float(np.percentile(f, 75))],
            "zero_alarm_runs": int((f == 0).sum()),
        }
        print(f"  {p}: runs in band {inb:>2}/30   median FAR {np.median(f):>6.2%}   "
              f"IQR [{np.percentile(f, 25):.2%}, {np.percentile(f, 75):.2%}]   "
              f"pooled {f.mean():.2%}   zero-alarm runs {int((f == 0).sum())}")

    with (OUT / "run_manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(records[0].keys()))
        w.writeheader()
        w.writerows(records)
    (OUT / "raw_results" / "clean_matched.json").write_text(
        json.dumps(records, indent=2, default=str), encoding="utf-8")
    (OUT / "processed_results" / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    # ---- verdict against the frozen criterion ------------------------------
    n = summary[PRIMARY]["runs_in_band"]
    verdict = "PASS-R2" if n >= 24 else ("PARTIAL-R2" if n >= 12 else "FAIL-R2")
    p3 = summary["P3"]["runs_in_band"]
    p3class = "VALID" if p3 >= 24 else ("CONDITIONAL" if p3 >= 12 else "INVALID")
    print(f"\nPRIMARY CRITERION  {PRIMARY} >= 24/30  ->  {n}/30  ->  {verdict}")
    print(f"SECONDARY          P3 {p3}/30  ->  {p3class}")
    (OUT / "processed_results" / "verdict.json").write_text(
        json.dumps({"verdict": verdict, "primary_runs_in_band": n,
                    "P3_runs_in_band": p3, "P3_classification": p3class,
                    "config_hash": config_hash, "thresholds": thresholds}, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    main()
