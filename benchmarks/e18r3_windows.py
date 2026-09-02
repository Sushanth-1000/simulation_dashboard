"""E18-R3 - is the monitor's instability precision-limited or dynamics-limited?

One variable: evaluation window length. The threshold is the FROZEN v3 value
from E18-R2 and is not recalculated here - this module contains no quantile
computation, so recalibration is prevented by construction.

Long clean runs are executed once and analysed at nested window lengths. The
nested points share data and are read as a trend, not as independent samples.

    python -m benchmarks.e18r3_windows
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
from training.closed_loop import drive_closed_loop

# FROZEN. E18_R2/processed_results/verdict.json. Not recomputed in this module.
FROZEN_V3 = {"P1": 3.7024, "P3": 3.3953}
EPS = 0.05
POLICIES = {"P1": "synthetic", "P3": "jerkscaled"}  # P2 excluded, untouched
BASE_SEED = 20261001
N_SEEDS = 30
TICKS = 3400
WIN_START = 200
WINDOWS = (200, 400, 800, 1600, 3200)


def _clean_scores(policy: Any, seed: int, ticks: int) -> list[float]:
    out: list[float] = []

    def obs(s: Any) -> None:
        sc = float("nan")
        sv = getattr(s.record, "safety_verdict", None)
        if sv is not None:
            for gv in getattr(sv, "gate_verdicts", ()):
                if str(getattr(gv, "gate", "")).endswith("STATISTICAL"):
                    for k, v in getattr(gv, "evidence", ()):
                        if k == "non_conformity_score":
                            sc = float(v)
        out.append(sc)

    drive_closed_loop(policy=policy, ticks=ticks, seed=seed, observer=obs, fault=None)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    ap.add_argument("--ticks", type=int, default=TICKS)
    ap.add_argument("--out", type=Path,
                    default=Path("experiments/phase5_od8_h7/E18_R3/raw_results"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    pols = {k: LearnedPolicy.load(Path(f"var/policy/{v}.pt")) for k, v in POLICIES.items()}

    records: list[dict[str, Any]] = []
    t0 = time.time()
    print(f"frozen thresholds (v3, not recomputed): {FROZEN_V3}")
    print(f"{a.seeds} seeds x {len(pols)} policies x {a.ticks} ticks\n")

    for pname, policy in pols.items():
        for i in range(a.seeds):
            seed = BASE_SEED + i
            sc = np.asarray(_clean_scores(policy, seed, a.ticks), float)
            nonfinite = int((~np.isfinite(sc)).sum())
            ev_all = sc[WIN_START:]
            ev_all = ev_all[np.isfinite(ev_all)]
            q = FROZEN_V3[pname]
            rec: dict[str, Any] = {
                "experiment_id": "E18-R3", "git_commit": commit, "policy": pname,
                "seed": seed, "ticks": a.ticks, "threshold": q,
                "calibration_version": "v3-frozen-from-R2",
                "nonfinite": nonfinite, "available_eval_ticks": int(ev_all.size),
            }
            for n in WINDOWS:
                w = ev_all[:n]
                rec[f"far_{n}"] = float((w > q).mean()) if w.size == n else float("nan")
                rec[f"mean_{n}"] = float(w.mean()) if w.size == n else float("nan")
            # drift confounder, section 6 - same statistic as E18
            h = ev_all.size // 2
            rec["first_half_mean"] = float(ev_all[:h].mean())
            rec["second_half_mean"] = float(ev_all[h:].mean())
            rec["sd_within"] = float(ev_all.std(ddof=1))
            records.append(rec)
        fars = [r[f"far_{WINDOWS[-1]}"] for r in records if r["policy"] == pname]
        inb = sum(1 for v in fars if EPS / 2 <= v <= 2 * EPS)
        print(f"  {pname}: at n={WINDOWS[-1]}  runs in band {inb}/{len(fars)}   "
              f"median FAR {np.median(fars):.2%}   [{time.time() - t0:.0f}s]", flush=True)

    (a.out / "long_runs.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"\n  {len(records)} runs -> {a.out / 'long_runs.json'}")


if __name__ == "__main__":
    main()
