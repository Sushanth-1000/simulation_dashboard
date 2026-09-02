"""E17 position faults, re-injected through the per-channel redundancy path.

`FaultInjector` cannot reach the position channel once redundant sensing is the
driven path (ADR-0033): `_publish_state` regenerates `y` per channel from
`plant._state[1]`, so the corruption is erased before any consumer sees it. That
invalidated the original position result. This module injects where the fault
can actually land -- `RedundantSensing.offset`, which is per channel.

**Two conditions, because they answer different questions.** Position is fused
as the median of three readings (IMU, GPS, LIDAR):

    R1  one channel lies   -> the median rejects it.  Tests *redundancy*.
    R2  two channels lie   -> the median follows them. Tests *absorption*.

Only R2 can test whether the estimator absorbs a position fault, because only
R2 delivers one. R1 is the control that shows the rejection in R1 is redundancy
working rather than the fault failing to arrive again.

Severities match `fault_study.py` exactly -- 1.0 m bias, 2.0 m final drift over
the 200-tick window -- so nothing is silently changed.

    python -m benchmarks.e17_position
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from astra.kernel.enums import SensorModality
from astra.layers.l4_proposer.learned import LearnedPolicy
from benchmarks.discriminability import _FAULT_FIRST, _stages_for, auc
from training.closed_loop import DEFAULT_CHANNEL_SIGMAS, RedundantSensing, drive_closed_loop

STAGES = ("L1", "L2a", "L2b", "L3", "L6", "L7", "L8")
BIAS_METRES = 1.0  # == _BIAS_METRES in fault_study.py
DRIFT_METRES = 2.0  # == _DRIFT_METRES
TICKS = 400
POLICIES = {"P1": "synthetic", "P2": "long", "P3": "jerkscaled"}
CONDITIONS = {
    "R1_one_liar": (SensorModality.IMU, ()),
    "R2_two_liars": (SensorModality.IMU, (SensorModality.GPS,)),
}


def _sensing(seed: int, fault: str, liar: Any, extra: tuple, active: bool) -> RedundantSensing:
    """Redundancy spec, faulted or clean, with the seed handling unchanged."""
    if not active:
        return RedundantSensing.build(sigmas=DEFAULT_CHANNEL_SIGMAS, seed=seed)
    span = TICKS - 1 - _FAULT_FIRST
    return RedundantSensing.build(
        sigmas=DEFAULT_CHANNEL_SIGMAS,
        seed=seed,
        faulted=liar,
        also_faulted=extra,
        opens_at=_FAULT_FIRST,
        bias=BIAS_METRES if fault == "position_bias" else 0.0,
        drift_per_tick=0.0 if fault == "position_bias" else DRIFT_METRES / span,
    )


def _l6(s: Any) -> tuple[float, float]:
    """(non-conformity score, conformal quantile) for this tick."""
    score = quant = float("nan")
    sv = getattr(s.record, "safety_verdict", None)
    if sv is None:
        return score, quant
    for gv in getattr(sv, "gate_verdicts", ()):
        if str(getattr(gv, "gate", "")).endswith("STATISTICAL"):
            for k, v in getattr(gv, "evidence", ()):
                if k == "non_conformity_score":
                    score = float(v)
                elif "quantile" in str(k):
                    quant = float(v)
    return score, quant


def _run(policy: Any, sensing: RedundantSensing, seed: int, fault: str) -> dict[str, Any]:
    stages = _stages_for(fault)
    vals: dict[str, list[float]] = {c: [] for c, _, _ in stages}
    ticks: list[int] = []
    scores: list[float] = []
    quants: list[float] = []
    est_y: list[float] = []

    def obs(s: Any) -> None:
        ticks.append(s.tick)
        for code, _, fn in stages:
            vals[code].append(fn(s))
        sc, q = _l6(s)
        scores.append(sc)
        quants.append(q)
        st = getattr(s.record, "fast_state", None)
        m = getattr(st, "mean", None) if st is not None else None
        est_y.append(float(m[1]) if m is not None and len(m) > 1 else float("nan"))

    r = drive_closed_loop(
        policy=policy, ticks=TICKS, seed=seed, observer=obs, fault=None, redundant=sensing
    )
    return {
        "values": vals,
        "ticks": ticks,
        "scores": scores,
        "quantiles": quants,
        "est_y": est_y,
        "veto_rate": float(r.vetoed) / float(r.ticks) if r.ticks else float("nan"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--base-seed", type=int, default=20260731)
    ap.add_argument("--out", type=Path, default=Path("results/E17_POSITION"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pols = {k: LearnedPolicy.load(Path(f"var/policy/{v}.pt")) for k, v in POLICIES.items()}

    records: list[dict[str, Any]] = []
    total = args.seeds * len(pols) * len(CONDITIONS) * 2
    done = 0
    t0 = time.time()

    for cond, (liar, extra) in CONDITIONS.items():
        for pname, policy in pols.items():
            for i in range(args.seeds):
                seed = args.base_seed + i
                for fault in ("position_bias", "position_drift"):
                    clean = _run(policy, _sensing(seed, fault, liar, extra, False), seed, fault)
                    faulted = _run(policy, _sensing(seed, fault, liar, extra, True), seed, fault)
                    win = [j for j, t in enumerate(clean["ticks"]) if t >= _FAULT_FIRST]

                    D = {}
                    for code, _, _ in _stages_for(fault):
                        c = np.array([clean["values"][code][j] for j in win], float)
                        f = np.array([faulted["values"][code][j] for j in win], float)
                        D[code] = auc(f, c)

                    def m(d: dict, key: str) -> float:
                        a = np.array([d[key][j] for j in win], float)
                        a = a[np.isfinite(a)]
                        return float(a.mean()) if a.size else float("nan")

                    sc_c, sc_f, q = m(clean, "scores"), m(faulted, "scores"), m(faulted, "quantiles")
                    ey_c, ey_f = m(clean, "est_y"), m(faulted, "est_y")
                    records.append(
                        {
                            "condition": cond,
                            "policy": pname,
                            "seed": seed,
                            "fault": fault,
                            "D": D,
                            "est_y_shift": abs(ey_f - ey_c),
                            "l6_score_clean": sc_c,
                            "l6_score_faulted": sc_f,
                            "l6_shift": abs(sc_f - sc_c),
                            "l6_threshold": q,
                            "l6_headroom": q - sc_c,
                            "l6_shift_over_headroom": (
                                abs(sc_f - sc_c) / (q - sc_c) if np.isfinite(q) and q > sc_c else float("nan")
                            ),
                            "veto_rate": faulted["veto_rate"],
                            "fault_reached_estimator": bool(abs(ey_f - ey_c) > 1e-6),
                        }
                    )
                done += 2
            print(f"  [{done:>4}/{total}] {cond} {pname}  {time.time() - t0:.0f}s", flush=True)

    (args.out / "position_runs.json").write_text(
        json.dumps(records, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n  {len(records)} records -> {args.out / 'position_runs.json'}")


if __name__ == "__main__":
    main()
