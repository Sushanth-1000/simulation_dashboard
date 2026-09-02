"""Analyse the E17 30-seed sweep per `manifests/PREREGISTRATION.md`.

Every choice this script makes -- primary stage, primary faults, regime cut
points, test, correction, effect size -- is fixed in that document, which was
written before the sweep produced output. This script does not choose anything.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from benchmarks.e17_stats import bca_median_ci, holm_bonferroni, spearman, wilcoxon_signed_rank

STAGES = ("L1", "L2a", "L2b", "L3", "L6", "L7", "L8")
FAULTS = (
    "imu_dropout",
    "position_bias",
    "position_drift",
    "speed_stuck",
    "speed_bias",
    "lateral_noise",
)
PRIMARY_FAULTS = ("position_bias", "position_drift")
PRIMARY_STAGE = "L2a"
SPEED_FAULTS = ("speed_bias", "speed_stuck")
ABSORPTION = 0.60

# Pre-registered regime cut points -- see PREREGISTRATION.md section 3.
VETO_NORMAL = 0.10
VETO_DEGRADED = 0.50


def regime_of(veto_rate: float) -> str:
    if not np.isfinite(veto_rate):
        return "UNKNOWN"
    if veto_rate < VETO_NORMAL:
        return "NORMAL"
    if veto_rate >= VETO_DEGRADED:
        return "DEGRADED"
    return "INTERMEDIATE"


def load(raw: Path) -> list[dict]:
    """Flatten raw run files into one record per (policy, seed, fault)."""
    rows: list[dict] = []
    for f in sorted(raw.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        for fault, sc in doc["scenarios"].items():
            d = {s["stage"]: float(s["D"]) for s in sc["stages"]}
            reg = sc.get("regime", {})
            vr = float(reg.get("veto_rate_faulted", float("nan")))
            rows.append(
                {
                    "run_id": doc["run_id"],
                    "policy": doc["policy"],
                    "seed": doc["seed"],
                    "fault": fault,
                    "D": d,
                    "absorption_point": sc.get("absorption_point"),
                    "unique_absorption": sc.get("unique_absorption"),
                    "threshold_crossings": sc.get("threshold_crossings"),
                    "veto_rate": vr,
                    "veto_rate_clean": float(reg.get("veto_rate_clean", float("nan"))),
                    "mean_speed": float(reg.get("mean_speed_faulted", float("nan"))),
                    "mean_speed_clean": float(reg.get("mean_speed_clean", float("nan"))),
                    "regime": regime_of(vr),
                }
            )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("results/E17_30SEED"))
    args = ap.parse_args()
    rows = load(args.dir / "raw")
    if not rows:
        raise SystemExit("no raw runs found")

    policies = sorted({r["policy"] for r in rows})
    out: dict[str, object] = {
        "n_runs": len({r["run_id"] for r in rows}),
        "n_records": len(rows),
        "policies": policies,
        "prereg": "manifests/PREREGISTRATION.md",
    }

    # --- Table A: D_s per (policy, fault, stage), median + BCa CI ----------
    tableA: dict[str, dict] = {}
    for p in policies:
        for f in FAULTS:
            vals = [r for r in rows if r["policy"] == p and r["fault"] == f]
            cell = {}
            for s in STAGES:
                arr = np.array([v["D"].get(s, np.nan) for v in vals], float)
                ci = bca_median_ci(arr)
                cell[s] = {
                    "median": ci["median"],
                    "lo": ci["lo"],
                    "hi": ci["hi"],
                    "degenerate": ci.get("degenerate", False),
                    "n_finite": int(np.isfinite(arr).sum()),
                }
            tableA[f"{p}|{f}"] = cell
    out["tableA_stage_profiles"] = tableA

    # --- Table B: primary test, L1 vs L2a, Holm within policy --------------
    tableB: dict[str, dict] = {}
    for p in policies:
        praw: dict[str, float] = {}
        detail: dict[str, dict] = {}
        for f in FAULTS:
            vals = [r for r in rows if r["policy"] == p and r["fault"] == f]
            l1 = np.array([v["D"].get("L1", np.nan) for v in vals], float)
            l2a = np.array([v["D"].get(PRIMARY_STAGE, np.nan) for v in vals], float)
            w = wilcoxon_signed_rank(l1, l2a)
            eff = bca_median_ci(l1 - l2a)
            praw[f] = w["p"]
            detail[f] = {"wilcoxon": w, "effect_L1_minus_L2a": eff}
        holm = holm_bonferroni(praw)
        for f in FAULTS:
            detail[f]["holm"] = holm[f]
            detail[f]["primary"] = f in PRIMARY_FAULTS
        tableB[p] = detail
    out["tableB_primary_test"] = tableB

    # --- Table C: absorption stage stability across seeds -------------------
    tableC: dict[str, dict] = {}
    for p in policies:
        for f in FAULTS:
            vals = [r for r in rows if r["policy"] == p and r["fault"] == f]
            counts: dict[str, int] = defaultdict(int)
            for v in vals:
                counts[str(v["absorption_point"])] += 1
            uniq = sum(1 for v in vals if v["unique_absorption"])
            tableC[f"{p}|{f}"] = {
                "absorption_counts": dict(counts),
                "modal": max(counts.items(), key=lambda kv: kv[1])[0] if counts else None,
                "modal_fraction": (max(counts.values()) / len(vals)) if vals else 0.0,
                "n_unique_absorption": uniq,
                "n": len(vals),
            }
    out["tableC_absorption_stability"] = tableC

    # --- Table D: operating regime ------------------------------------------
    reg: dict[str, dict] = {}
    for p in policies:
        vr = np.array([r["veto_rate"] for r in rows if r["policy"] == p], float)
        ms = np.array([r["mean_speed"] for r in rows if r["policy"] == p], float)
        counts: dict[str, int] = defaultdict(int)
        for r in rows:
            if r["policy"] == p:
                counts[r["regime"]] += 1
        reg[p] = {
            "veto_rate": {
                "median": float(np.nanmedian(vr)),
                "min": float(np.nanmin(vr)),
                "max": float(np.nanmax(vr)),
            },
            "mean_speed": {
                "median": float(np.nanmedian(ms)),
                "min": float(np.nanmin(ms)),
                "max": float(np.nanmax(ms)),
            },
            "regime_counts": dict(counts),
        }
    out["tableD_regime"] = reg

    # --- H-regime: secondary, exploratory ----------------------------------
    hreg: dict[str, dict] = {}
    for f in SPEED_FAULTS:
        vals = [r for r in rows if r["fault"] == f]
        hreg[f] = {
            "spearman_D_L1_vs_veto_rate": spearman(
                np.array([v["veto_rate"] for v in vals], float),
                np.array([v["D"].get("L1", np.nan) for v in vals], float),
            ),
            "spearman_D_L1_vs_mean_speed": spearman(
                np.array([v["mean_speed"] for v in vals], float),
                np.array([v["D"].get("L1", np.nan) for v in vals], float),
            ),
            "note": "EXPLORATORY -- hypothesis generated from the n=1 observation it is tested on.",
        }
    out["H_regime_secondary"] = hreg

    # --- Pre-registered falsification checks --------------------------------
    checks: list[dict] = []
    for p in policies:
        for f in PRIMARY_FAULTS:
            cell = tableA[f"{p}|{f}"][PRIMARY_STAGE]
            checks.append(
                {
                    "criterion": "F1: median D_L2a > 0.60",
                    "policy": p,
                    "fault": f,
                    "value": cell["median"],
                    "falsified": bool(cell["median"] > ABSORPTION),
                }
            )
            eff = tableB[p][f]["effect_L1_minus_L2a"]
            checks.append(
                {
                    "criterion": "F2: effect CI crosses zero",
                    "policy": p,
                    "fault": f,
                    "value": [eff["lo"], eff["hi"]],
                    "falsified": bool(eff["lo"] <= 0.0 <= eff["hi"])
                    and not eff.get("degenerate"),
                }
            )
            stab = tableC[f"{p}|{f}"]
            checks.append(
                {
                    "criterion": "F3: absorption stage varies across seeds",
                    "policy": p,
                    "fault": f,
                    "value": stab["modal_fraction"],
                    "falsified": bool(stab["modal_fraction"] < 1.0),
                }
            )
    out["falsification_checks"] = checks
    out["any_falsified"] = any(c["falsified"] for c in checks)

    dest = args.dir / "statistics"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "analysis.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    print(f"  runs analysed : {out['n_runs']}")
    print(f"  records       : {out['n_records']}")
    print(f"  any falsified : {out['any_falsified']}")
    print(f"  -> {dest / 'analysis.json'}")


if __name__ == "__main__":
    main()
