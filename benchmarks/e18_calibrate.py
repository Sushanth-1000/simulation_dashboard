"""E18 — collect clean L6 non-conformity scores for calibration and testing.

Clean runs only. No fault is injected anywhere in this module: the calibration
quantile must never see fault data, and the cleanest way to guarantee that is
for the collector to be incapable of injecting one.

Three disjoint seed sets (see `protocol.md` section E):

    CALIBRATION  20260901 + i   -> computes the quantile
    CLEAN TEST   20261001 + i   -> measures the false-alarm rate
    (FAULT TEST  20260731 + i   -> evaluated later, only after the freeze)

    python -m benchmarks.e18_calibrate
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from astra.layers.l4_proposer.learned import LearnedPolicy
from training.closed_loop import drive_closed_loop

POLICIES = {"P1": "synthetic", "P2": "long", "P3": "jerkscaled"}
SETS = {"calibration": 20260901, "clean_test": 20261001}
TICKS = 400
N_SEEDS = 30


def _scores(policy: Any, seed: int, ticks: int) -> dict[str, Any]:
    """Per-tick non-conformity score, quantile and context for one clean run."""
    score: list[float] = []
    quant: list[float] = []
    ctx: list[str] = []

    def obs(s: Any) -> None:
        tr = getattr(s.record, "trust", None)
        ctx.append(str(getattr(tr, "context_class", None)).split(".")[-1] if tr else "NONE")
        sc = q = float("nan")
        sv = getattr(s.record, "safety_verdict", None)
        if sv is not None:
            for gv in getattr(sv, "gate_verdicts", ()):
                if str(getattr(gv, "gate", "")).endswith("STATISTICAL"):
                    for k, v in getattr(gv, "evidence", ()):
                        if k == "non_conformity_score":
                            sc = float(v)
                        elif "quantile" in str(k):
                            q = float(v)
        score.append(sc)
        quant.append(q)

    r = drive_closed_loop(policy=policy, ticks=ticks, seed=seed, observer=obs, fault=None)
    return {
        "seed": seed,
        "scores": score,
        "legacy_quantiles": quant,
        "contexts": ctx,
        "veto_rate": float(r.vetoed) / float(r.ticks) if r.ticks else float("nan"),
        "n_ticks": len(score),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    ap.add_argument("--ticks", type=int, default=TICKS)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("experiments/phase5_od8_h7/E18_OD8_CALIBRATION/raw_results"),
    )
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    # Integrity check 5: the seed sets must be disjoint, verified rather than assumed.
    built = {k: {base + i for i in range(args.seeds)} for k, base in SETS.items()}
    built["fault_test"] = {20260731 + i for i in range(args.seeds)}
    names = sorted(built)
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            overlap = built[names[a]] & built[names[b]]
            if overlap:
                raise SystemExit(f"seed sets {names[a]} and {names[b]} overlap: {sorted(overlap)[:5]}")
    print(f"  seed sets disjoint: {', '.join(f'{k}({len(v)})' for k, v in built.items())}\n")

    pols = {k: LearnedPolicy.load(Path(f"var/policy/{v}.pt")) for k, v in POLICIES.items()}
    t0 = time.time()
    for set_name, base in SETS.items():
        out: dict[str, Any] = {"set": set_name, "base_seed": base, "ticks": args.ticks, "runs": {}}
        for pname, policy in pols.items():
            runs = []
            for i in range(args.seeds):
                runs.append(_scores(policy, base + i, args.ticks))
            out["runs"][pname] = runs
            flat = np.array([v for r in runs for v in r["scores"]], float)
            flat = flat[np.isfinite(flat)]
            nonfinite = sum(1 for r in runs for v in r["scores"] if not np.isfinite(v))
            ctxs: dict[str, int] = {}
            for r in runs:
                for c in r["contexts"]:
                    ctxs[c] = ctxs.get(c, 0) + 1
            print(
                f"  {set_name:<12} {pname}  n={flat.size:<6} "
                f"mean={flat.mean():.4f} sd={flat.std(ddof=1):.4f} "
                f"min={flat.min():.4f} max={flat.max():.4f}  "
                f"nonfinite={nonfinite}  ctx={ctxs}  [{time.time() - t0:.0f}s]",
                flush=True,
            )
        (args.out / f"{set_name}.json").write_text(json.dumps(out), encoding="utf-8")
    print(f"\n  -> {args.out}")


if __name__ == "__main__":
    main()
