"""Capture L6 threshold-relative metrics for the four integrity-valid faults.

`D_s` is scale-free: it reports near-perfect separation for a shift two orders
below the gate's firing threshold. So `D_L6` alone cannot support any claim
about whether the gate would *act*. This module measures the quantity that can:

    shift      = |mean score faulted - mean score clean|
    headroom   = conformal quantile - mean score clean
    ratio      = shift / headroom      (>= 1.0 would be needed to fire)

Supplementary sample: 10 seeds, not the sweep's 30. The quantity is a property
of the corpus and the operating point rather than of the seed, and 10 seeds is
enough to show the order of magnitude -- which is the entire point. Labelled
n=10 wherever it is reported.

    python -m benchmarks.e17_l6
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.discriminability import CHANNEL_SIGMAS, _FAULT_FIRST
from benchmarks.e17_position import _l6
from benchmarks.fault_study import SCENARIOS
from training.closed_loop import drive_closed_loop
from training.faults import FaultInjector

VALID = ("imu_dropout", "speed_stuck", "speed_bias", "lateral_noise")
POLICIES = {"P1": "synthetic", "P2": "long", "P3": "jerkscaled"}
TICKS = 400


def _capture(policy: Any, fault: Any, seed: int) -> tuple[float, float]:
    scores: list[float] = []
    quants: list[float] = []

    def obs(s: Any) -> None:
        if s.tick < _FAULT_FIRST:
            return
        sc, q = _l6(s)
        scores.append(sc)
        quants.append(q)

    drive_closed_loop(policy=policy, ticks=TICKS, seed=seed, observer=obs, fault=fault)
    a = np.array(scores, float)
    b = np.array(quants, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    return (float(a.mean()) if a.size else float("nan"),
            float(b.mean()) if b.size else float("nan"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--base-seed", type=int, default=20260731)
    ap.add_argument("--out", type=Path, default=Path("results/E17_FINAL"))
    args = ap.parse_args()
    scen = {s.name: s for s in SCENARIOS}
    pols = {k: LearnedPolicy.load(Path(f"var/policy/{v}.pt")) for k, v in POLICIES.items()}

    rows: list[dict[str, Any]] = []
    for pname, policy in pols.items():
        for fname in VALID:
            for i in range(args.seeds):
                seed = args.base_seed + i
                sc_c, q_c = _capture(policy, None, seed)
                inj = FaultInjector(
                    scen[fname].build(_FAULT_FIRST, TICKS - 1), seed=seed, sigmas=CHANNEL_SIGMAS
                )
                sc_f, q_f = _capture(policy, inj, seed)
                q = q_f if np.isfinite(q_f) else q_c
                head = q - sc_c
                shift = abs(sc_f - sc_c)
                rows.append(
                    {
                        "policy": pname, "fault": fname, "seed": seed,
                        "l6_score_clean": sc_c, "l6_score_faulted": sc_f,
                        "l6_shift": shift, "l6_threshold": q, "l6_headroom": head,
                        "l6_shift_over_headroom": shift / head if np.isfinite(head) and head > 0 else float("nan"),
                        "could_fire": bool(np.isfinite(head) and shift >= head),
                    }
                )
            print(f"  {pname} {fname:<15} done", flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "E17_L6_THRESHOLD.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    import csv

    with (args.out / "E17_L6_THRESHOLD.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n{'policy':<8}{'fault':<16}{'score_clean':>12}{'shift':>10}{'threshold':>11}{'headroom':>10}{'ratio':>9}{'fires?':>8}")
    for p in POLICIES:
        for f in VALID:
            g = [r for r in rows if r["policy"] == p and r["fault"] == f]
            if not g:
                continue
            print(
                f"{p:<8}{f:<16}{np.mean([x['l6_score_clean'] for x in g]):>12.4f}"
                f"{np.mean([x['l6_shift'] for x in g]):>10.4f}"
                f"{np.mean([x['l6_threshold'] for x in g]):>11.4f}"
                f"{np.mean([x['l6_headroom'] for x in g]):>10.4f}"
                f"{np.nanmean([x['l6_shift_over_headroom'] for x in g]):>9.4f}"
                f"{str(any(x['could_fire'] for x in g)):>8}"
            )


if __name__ == "__main__":
    main()
