"""E18 Part 2 - detection at the FROZEN thresholds, plus severity analysis.

Reports operational detection (did the gate fire?) separately from statistical
discriminability (D_s). Conflating the two produced a withdrawn claim earlier in
this project, so they never share a column here.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from benchmarks.e17_stats import bca_median_ci
from benchmarks.e18_evaluate import FROZEN_QUANTILE, SEVERITIES

BASE = Path("experiments/phase5_od8_h7/E18_OD8_CALIBRATION")
STAGES = ("L1", "L2a", "L2b", "L3", "L6", "L7", "L8")
CLEAN_FAR = {"P1": 0.0547, "P2": 0.0468, "P3": 0.0823}  # E18 Part 1, held-out
VALID_POLICIES = ("P1", "P3")  # P2 excluded: failed the drift criterion
LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=BASE)
    args = ap.parse_args()
    rows = json.loads((args.dir / "raw_results" / "fault_evaluation.json").read_text(encoding="utf-8"))
    out: dict = {"n_records": len(rows), "frozen_quantile": FROZEN_QUANTILE}

    # ---- integrity first ---------------------------------------------------
    bad = [r for r in rows if not r["fault_reached_estimator"]]
    out["integrity"] = {
        "reached": len(rows) - len(bad),
        "total": len(rows),
        "failures": [
            {"policy": r["policy"], "fault": r["fault"], "severity_level": r["severity_level"],
             "severity_value": r["severity_value"], "seed": r["seed"]} for r in bad
        ],
    }
    print(f"INTEGRITY: fault reached the estimator in {len(rows) - len(bad)}/{len(rows)}")
    if bad:
        grp: dict[tuple, list[int]] = defaultdict(list)
        for r in bad:
            grp[(r["policy"], r["fault"], r["severity_level"], r["severity_value"])].append(r["seed"])
        print("  FAILURES (excluded from detection statistics):")
        for (p, f, lvl, val), seeds in sorted(grp.items()):
            print(f"    {p} {f} {lvl} (={val})  n={len(seeds)}  seeds={seeds[:6]}")
    print()

    ok = [r for r in rows if r["fault_reached_estimator"]]

    # ---- detection at the frozen threshold --------------------------------
    print("OPERATIONAL DETECTION at the frozen threshold  (P2 shown but EXCLUDED - drift criterion)")
    print(f"{'pol':<4}{'fault':<16}{'sev':<8}{'value':>8}{'det.rate':>10}{'alarm rate':>12}"
          f"{'clean FAR':>11}{'latency':>9}{'margin':>10}{'D_L1':>8}{'D_L6':>8}")
    detect: dict[str, dict] = {}
    for p in ("P1", "P3", "P2"):
        for fault, spec in SEVERITIES.items():
            for lvl in sorted(spec["levels"], key=lambda k: LEVEL_ORDER.get(k, 9)):
                g = [r for r in ok if r["policy"] == p and r["fault"] == fault
                     and r["severity_level"] == lvl]
                if not g:
                    continue
                det = float(np.mean([r["detected"] for r in g]))
                alarm = float(np.nanmean([r["alarm_rate_faulted"] for r in g]))
                lat = [r["detection_latency_ticks"] for r in g if r["detection_latency_ticks"] is not None]
                margin = float(np.nanmean([r["threshold_margin"] for r in g]))
                d1 = float(np.nanmedian([r["D"].get("L1", np.nan) for r in g]))
                d6 = float(np.nanmedian([r["D"].get("L6", np.nan) for r in g]))
                ci = bca_median_ci(np.array([1.0 if r["detected"] else 0.0 for r in g]))
                detect[f"{p}|{fault}|{lvl}"] = {
                    "detection_rate": det, "detection_ci": [ci["lo"], ci["hi"]],
                    "alarm_rate_faulted": alarm, "clean_far": CLEAN_FAR[p],
                    "median_latency_ticks": float(np.median(lat)) if lat else None,
                    "threshold_margin": margin,
                    "D": {s: float(np.nanmedian([r["D"].get(s, np.nan) for r in g])) for s in STAGES},
                    "severity_value": g[0]["severity_value"], "n": len(g),
                    "policy_valid": p in VALID_POLICIES,
                }
                print(f"{p:<4}{fault:<16}{lvl:<8}"
                      f"{('n/a' if g[0]['severity_value'] is None else f'{g[0]['severity_value']:.2f}'):>8}"
                      f"{det:>10.2%}{alarm:>12.2%}{CLEAN_FAR[p]:>11.2%}"
                      f"{(f'{np.median(lat):.0f}' if lat else '-'):>9}"
                      f"{margin:>10.4f}{d1:>8.3f}{d6:>8.3f}")
        print()
    out["detection"] = detect

    # ---- minimum detectable severity --------------------------------------
    # Pre-specified criterion: detection rate >= 0.90 across seeds.
    MDS_CRITERION = 0.90
    print(f"MINIMUM DETECTABLE SEVERITY  (criterion: detection rate >= {MDS_CRITERION:.0%})")
    mds: dict[str, dict] = {}
    for p in VALID_POLICIES:
        for fault, spec in SEVERITIES.items():
            found = None
            for lvl in sorted(spec["levels"], key=lambda k: LEVEL_ORDER.get(k, 9)):
                k = f"{p}|{fault}|{lvl}"
                if k in detect and detect[k]["detection_rate"] >= MDS_CRITERION:
                    found = (lvl, detect[k]["severity_value"])
                    break
            mds[f"{p}|{fault}"] = {
                "mds_level": None if found is None else found[0],
                "mds_value": None if found is None else found[1],
                "unit": spec["unit"],
            }
            label = "NOT DETECTED at any tested severity" if found is None else \
                f"{found[0]} ({found[1] if found[1] is not None else 'n/a'} {spec['unit']})"
            print(f"  {p}  {fault:<16} {label}")
    out["minimum_detectable_severity"] = mds
    out["mds_criterion"] = MDS_CRITERION

    # ---- CSV ---------------------------------------------------------------
    proc = args.dir / "processed_results"
    proc.mkdir(parents=True, exist_ok=True)
    with (proc / "E18_DETECTION.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["policy", "policy_valid", "fault", "severity_level", "severity_value",
                    "n", "detection_rate", "det_ci_lo", "det_ci_hi", "alarm_rate_faulted",
                    "clean_far", "median_latency_ticks", "threshold_margin", "frozen_quantile",
                    *[f"D_{s}" for s in STAGES]])
        for key, v in detect.items():
            p, f, lvl = key.split("|")
            w.writerow([p, v["policy_valid"], f, lvl, v["severity_value"], v["n"],
                        f"{v['detection_rate']:.4f}", f"{v['detection_ci'][0]:.4f}",
                        f"{v['detection_ci'][1]:.4f}", f"{v['alarm_rate_faulted']:.4f}",
                        f"{v['clean_far']:.4f}",
                        "" if v["median_latency_ticks"] is None else f"{v['median_latency_ticks']:.0f}",
                        f"{v['threshold_margin']:.4f}", FROZEN_QUANTILE[p],
                        *[f"{v['D'][s]:.4f}" for s in STAGES]])
    (proc / "detection_analysis.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\n  -> {proc / 'E18_DETECTION.csv'}")
    print(f"  -> {proc / 'detection_analysis.json'}")


if __name__ == "__main__":
    main()
