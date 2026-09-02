"""Does the central phenomenon survive correct position-fault injection?

The original claim: position faults are absorbed at the estimator, `D_L1` ~ 1.0
collapsing to `D_L2a` = 0.500. That rested on a fault that never arrived.

This asks the same question of a fault that does arrive, under two conditions:

    R1  one lying channel  -- the median over three positions should reject it
    R2  two lying channels -- the median should follow them

Absorption is only testable under R2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.e17_stats import bca_median_ci, wilcoxon_signed_rank

STAGES = ("L1", "L2a", "L2b", "L3", "L6", "L7", "L8")
ABSORPTION = 0.60


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("results/E17_POSITION"))
    args = ap.parse_args()
    rows = json.loads((args.dir / "position_runs.json").read_text(encoding="utf-8"))

    conds = sorted({r["condition"] for r in rows})
    pols = sorted({r["policy"] for r in rows})
    faults = sorted({r["fault"] for r in rows})
    out: dict = {"n_records": len(rows)}

    print(f"records: {len(rows)}\n")
    reached = sum(1 for r in rows if r["fault_reached_estimator"])
    print(f"INTEGRITY: fault reached the estimator in {reached}/{len(rows)} runs")
    out["integrity_reached"] = f"{reached}/{len(rows)}"

    print("\n=== Stage profiles: median [BCa 95% CI], n=30 ===")
    tbl: dict = {}
    for cond in conds:
        print(f"\n--- {cond} ---")
        print(f"{'policy':<7}{'fault':<17}" + "".join(f"{s:>16}" for s in STAGES))
        for p in pols:
            for f in faults:
                g = [r for r in rows if r["condition"] == cond and r["policy"] == p and r["fault"] == f]
                if not g:
                    continue
                cells = []
                rec = {}
                for s in STAGES:
                    a = np.array([x["D"].get(s, np.nan) for x in g], float)
                    a = a[np.isfinite(a)]
                    ci = bca_median_ci(a)
                    rec[s] = ci
                    cells.append(f"{ci['median']:.3f}")
                tbl[f"{cond}|{p}|{f}"] = rec
                print(f"{p:<7}{f:<17}" + "".join(f"{c:>16}" for c in cells))
    out["stage_profiles"] = tbl

    print("\n=== Absorption test: is D_L2a below 0.60? ===")
    verdicts = []
    for cond in conds:
        for p in pols:
            for f in faults:
                g = [r for r in rows if r["condition"] == cond and r["policy"] == p and r["fault"] == f]
                if not g:
                    continue
                l1 = np.array([x["D"]["L1"] for x in g], float)
                l2a = np.array([x["D"]["L2a"] for x in g], float)
                ci = bca_median_ci(l2a)
                w = wilcoxon_signed_rank(l1, l2a)
                absorbed = ci["median"] < ABSORPTION
                verdicts.append(
                    {
                        "condition": cond, "policy": p, "fault": f,
                        "D_L1_median": float(np.median(l1)),
                        "D_L2a_median": ci["median"],
                        "D_L2a_lo": ci["lo"], "D_L2a_hi": ci["hi"],
                        "absorbed_at_L2a": bool(absorbed),
                        "wilcoxon_p": w["p"],
                    }
                )
                print(
                    f"  {cond:<14}{p:<4}{f:<17} D_L1={np.median(l1):.3f}  "
                    f"D_L2a={ci['median']:.3f} [{ci['lo']:.3f},{ci['hi']:.3f}]  "
                    f"absorbed={'YES' if absorbed else 'NO'}"
                )
    out["absorption_verdicts"] = verdicts

    n_abs = sum(1 for v in verdicts if v["absorbed_at_L2a"])
    print(f"\n  absorbed at L2a: {n_abs} of {len(verdicts)} (condition, policy, fault) cells")
    out["survives"] = n_abs > 0

    print("\n=== L6 threshold headroom (can the gate fire?) ===")
    print(f"{'cond':<14}{'pol':<5}{'fault':<17}{'shift':>9}{'headroom':>10}{'ratio':>9}{'fires?':>8}")
    l6 = []
    for cond in conds:
        for p in pols:
            for f in faults:
                g = [r for r in rows if r["condition"] == cond and r["policy"] == p and r["fault"] == f]
                if not g:
                    continue
                sh = float(np.nanmean([x["l6_shift"] for x in g]))
                hd = float(np.nanmean([x["l6_headroom"] for x in g]))
                ra = float(np.nanmean([x["l6_shift_over_headroom"] for x in g]))
                fires = any(
                    np.isfinite(x["l6_shift"]) and np.isfinite(x["l6_headroom"]) and x["l6_shift"] >= x["l6_headroom"]
                    for x in g
                )
                l6.append({"condition": cond, "policy": p, "fault": f, "shift": sh,
                           "headroom": hd, "ratio": ra, "could_fire": fires})
                print(f"  {cond:<14}{p:<5}{f:<17}{sh:>9.4f}{hd:>10.4f}{ra:>9.4f}{str(fires):>8}")
    out["l6_headroom"] = l6

    (args.dir / "analysis.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\n  -> {args.dir / 'analysis.json'}")


if __name__ == "__main__":
    main()
