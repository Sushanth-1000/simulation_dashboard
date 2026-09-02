"""Emit the E17 validation artifacts (CSVs) from the 30-seed raw output.

Rows for the two INVALID faults are retained and flagged rather than deleted:
an audit that erases its contaminated rows cannot be checked.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from benchmarks.e17_analyse import FAULTS, STAGES, load
from benchmarks.e17_integrity import SEVERITY
from benchmarks.e17_stats import bca_median_ci

VALID = {"imu_dropout", "speed_stuck", "speed_bias", "lateral_noise"}
INVALID_REASON = "ground-truth regeneration (ADR-0033): fault never reached the estimator"
ABSORPTION = 0.60


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("results/E17_30SEED"))
    ap.add_argument("--out", type=Path, default=Path("results/E17_FINAL"))
    args = ap.parse_args()
    rows = load(args.dir / "raw")
    manifest = json.loads((args.dir / "manifests" / "run_manifest.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)

    def status(f: str) -> tuple[str, str]:
        return ("VALID", "") if f in VALID else ("INVALID", INVALID_REASON)

    # --- E17_STAGEWISE_RESULTS.csv : one row per (seed, policy, fault, stage) --
    with (args.out / "E17_STAGEWISE_RESULTS.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["seed", "policy", "fault", "severity", "stage", "metric", "D_s",
             "A_f", "unique_absorption", "veto_rate", "mean_speed",
             "validity", "invalid_reason", "git_commit"]
        )
        for r in rows:
            st, reason = status(r["fault"])
            for s in STAGES:
                w.writerow([
                    r["seed"], r["policy"], r["fault"], SEVERITY.get(r["fault"], ""), s,
                    "AUC(faulted, matched-clean) folded to [0.5,1.0]",
                    f"{r['D'].get(s, float('nan')):.6f}",
                    r["absorption_point"], r["unique_absorption"],
                    f"{r['veto_rate']:.6f}", f"{r['mean_speed']:.4f}",
                    st, reason, manifest.get("git_commit", ""),
                ])

    # --- E17_SEED_SUMMARY.csv : one row per (seed, policy, fault) -------------
    with (args.out / "E17_SEED_SUMMARY.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["seed", "policy", "fault", "severity", "A_f", "unique_absorption",
             "threshold_crossings", "veto_rate", "mean_speed", "failure_status", "validity"]
        )
        for r in rows:
            st, _ = status(r["fault"])
            w.writerow([
                r["seed"], r["policy"], r["fault"], SEVERITY.get(r["fault"], ""),
                r["absorption_point"], r["unique_absorption"], r["threshold_crossings"],
                f"{r['veto_rate']:.6f}", f"{r['mean_speed']:.4f}", "ok", st,
            ])

    # --- E17_RESULTS_FINAL.csv : aggregate per (policy, fault, stage) ---------
    with (args.out / "E17_RESULTS_FINAL.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["policy", "fault", "severity", "stage", "n", "mean", "median", "sd",
             "ci_lo", "ci_hi", "min", "max", "validity"]
        )
        for p in sorted({r["policy"] for r in rows}):
            for f in FAULTS:
                st, _ = status(f)
                vals = [r for r in rows if r["policy"] == p and r["fault"] == f]
                for s in STAGES:
                    a = np.array([v["D"].get(s, np.nan) for v in vals], float)
                    a = a[np.isfinite(a)]
                    if a.size == 0:
                        continue
                    ci = bca_median_ci(a)
                    w.writerow([
                        p, f, SEVERITY.get(f, ""), s, a.size,
                        f"{a.mean():.6f}", f"{np.median(a):.6f}",
                        f"{a.std(ddof=1) if a.size > 1 else 0.0:.6f}",
                        f"{ci['lo']:.6f}", f"{ci['hi']:.6f}",
                        f"{a.min():.6f}", f"{a.max():.6f}", st,
                    ])

    # --- E17_ABSORPTION_POINTS.csv -------------------------------------------
    with (args.out / "E17_ABSORPTION_POINTS.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["policy", "fault", "severity", "modal_A_f", "modal_pct",
             "seeds_with_unique_absorption", "n", "stable_across_seeds",
             "A_f_well_posed", "threshold", "validity"]
        )
        for p in sorted({r["policy"] for r in rows}):
            for f in FAULTS:
                st, _ = status(f)
                vals = [r for r in rows if r["policy"] == p and r["fault"] == f]
                if not vals:
                    continue
                counts: dict[str, int] = {}
                for v in vals:
                    counts[str(v["absorption_point"])] = counts.get(str(v["absorption_point"]), 0) + 1
                modal, n_modal = max(counts.items(), key=lambda kv: kv[1])
                uniq = sum(1 for v in vals if v["unique_absorption"])
                w.writerow([
                    p, f, SEVERITY.get(f, ""), modal, f"{100 * n_modal / len(vals):.1f}",
                    uniq, len(vals), n_modal == len(vals), uniq == len(vals),
                    ABSORPTION, st,
                ])

    for name in ("E17_STAGEWISE_RESULTS", "E17_SEED_SUMMARY", "E17_RESULTS_FINAL", "E17_ABSORPTION_POINTS"):
        p = args.out / f"{name}.csv"
        print(f"  {name + '.csv':<32} {sum(1 for _ in p.open(encoding='utf-8')) - 1:>6} rows")


if __name__ == "__main__":
    main()
