"""E18 — compute the calibration, test it on held-out clean data, and freeze.

Runs strictly in the order `protocol.md` fixes: quantile from CALIBRATION only,
false-alarm rate on CLEAN TEST, exchangeability and drift checks, then the
pre-registered selection rule, then the freeze. No fault data is loaded by this
module at all.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.e17_stats import bca_median_ci
from benchmarks.e18_calibrate import POLICIES

EPSILON = 0.05  # pre-registered
BASE = Path("experiments/phase5_od8_h7/E18_OD8_CALIBRATION")


def flat(doc: dict, policy: str) -> np.ndarray:
    a = np.array([v for r in doc["runs"][policy] for v in r["scores"]], float)
    return a[np.isfinite(a)]


def per_run(doc: dict, policy: str) -> list[np.ndarray]:
    out = []
    for r in doc["runs"][policy]:
        a = np.array(r["scores"], float)
        out.append(a[np.isfinite(a)])
    return out


def conformal_q(scores: np.ndarray, eps: float) -> float:
    """Finite-sample conformal quantile: ceil((n+1)(1-eps))-th order statistic."""
    n = scores.size
    k = int(np.ceil((n + 1) * (1.0 - eps)))
    if k > n:
        return float(np.max(scores))
    return float(np.sort(scores)[k - 1])


def auc(a: np.ndarray, b: np.ndarray) -> float:
    """Folded Mann-Whitney AUC - exchangeability check. 0.5 means indistinguishable."""
    pooled = np.concatenate([a, b])
    order = pooled.argsort().argsort().astype(float) + 1.0
    for v in np.unique(pooled):
        m = pooled == v
        if m.sum() > 1:
            order[m] = order[m].mean()
    u = order[: a.size].sum() - a.size * (a.size + 1) / 2.0
    val = u / (a.size * b.size)
    return max(val, 1.0 - val)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eps", type=float, default=EPSILON)
    args = ap.parse_args()
    cal = json.loads((BASE / "raw_results" / "calibration.json").read_text(encoding="utf-8"))
    tst = json.loads((BASE / "raw_results" / "clean_test.json").read_text(encoding="utf-8"))
    eps = args.eps
    res: dict = {"epsilon": eps, "schemes": {}, "diagnostics": {}}

    print(f"epsilon = {eps}   nominal clean false-alarm rate = {eps:.1%}")
    print(f"acceptance band [eps/2, 2*eps] = [{eps/2:.1%}, {2*eps:.1%}]\n")

    # ---- clean distributions + drift + exchangeability ---------------------
    print("CLEAN BEHAVIOUR (calibration set) and EXCHANGEABILITY vs held-out clean test")
    print(f"{'pol':<5}{'mean':>9}{'sd':>9}{'min':>9}{'max':>9}{'exch AUC':>11}"
          f"{'1st half':>10}{'2nd half':>10}{'drift/sd':>10}")
    for p in POLICIES:
        c, t = flat(cal, p), flat(tst, p)
        halves = [np.mean([r[: len(r) // 2].mean() for r in per_run(cal, p)]),
                  np.mean([r[len(r) // 2:].mean() for r in per_run(cal, p)])]
        drift = abs(halves[1] - halves[0]) / c.std(ddof=1)
        a = auc(c, t)
        res["diagnostics"][p] = {
            "mean": float(c.mean()), "sd": float(c.std(ddof=1)),
            "min": float(c.min()), "max": float(c.max()),
            "exchangeability_auc": a,
            "first_half_mean": float(halves[0]), "second_half_mean": float(halves[1]),
            "drift_over_sd": float(drift),
        }
        print(f"{p:<5}{c.mean():>9.4f}{c.std(ddof=1):>9.4f}{c.min():>9.4f}{c.max():>9.4f}"
              f"{a:>11.4f}{halves[0]:>10.4f}{halves[1]:>10.4f}{drift:>10.2f}")

    # ---- scheme 1: global --------------------------------------------------
    pooled = np.concatenate([flat(cal, p) for p in POLICIES])
    q_global = conformal_q(pooled, eps)
    g = {"quantile": q_global, "n_calibration": int(pooled.size), "per_policy": {}}
    print(f"\nSCHEME 1 - GLOBAL   quantile = {q_global:.4f}  (n = {pooled.size})")
    print(f"{'pol':<5}{'clean FAR':>12}{'nominal':>10}{'in band?':>10}{'headroom':>11}")
    for p in POLICIES:
        t = flat(tst, p)
        far = float((t > q_global).mean())
        ok = eps / 2 <= far <= 2 * eps
        g["per_policy"][p] = {"far": far, "in_band": bool(ok),
                              "headroom": float(q_global - flat(cal, p).mean())}
        print(f"{p:<5}{far:>12.4%}{eps:>10.1%}{str(ok):>10}"
              f"{q_global - flat(cal, p).mean():>11.4f}")
    g["all_in_band"] = all(v["in_band"] for v in g["per_policy"].values())
    res["schemes"]["global"] = g

    # ---- scheme 2: policy-conditional --------------------------------------
    pc = {"per_policy": {}}
    print(f"\nSCHEME 2 - POLICY-CONDITIONAL")
    print(f"{'pol':<5}{'quantile':>11}{'clean FAR':>12}{'nominal':>10}{'in band?':>10}{'headroom':>11}")
    for p in POLICIES:
        c, t = flat(cal, p), flat(tst, p)
        q = conformal_q(c, eps)
        far = float((t > q).mean())
        ok = eps / 2 <= far <= 2 * eps
        ci = bca_median_ci(np.array([conformal_q(r, eps) for r in per_run(cal, p) if r.size > 20]))
        pc["per_policy"][p] = {
            "quantile": q, "far": far, "in_band": bool(ok),
            "headroom": float(q - c.mean()),
            "quantile_ci": [ci["lo"], ci["hi"]], "n_calibration": int(c.size),
        }
        print(f"{p:<5}{q:>11.4f}{far:>12.4%}{eps:>10.1%}{str(ok):>10}{q - c.mean():>11.4f}")
    pc["all_in_band"] = all(v["in_band"] for v in pc["per_policy"].values())
    res["schemes"]["policy_conditional"] = pc

    # ---- pre-registered selection rule -------------------------------------
    chosen = "global" if g["all_in_band"] else "policy_conditional"
    res["selected_scheme"] = chosen
    res["selection_rule"] = (
        "protocol.md section F: prefer global unless its clean false-alarm rate falls outside "
        "[eps/2, 2*eps] for at least one policy."
    )
    print(f"\nSELECTION (pre-registered): global all-in-band = {g['all_in_band']}  "
          f"-> scheme = {chosen.upper()}")

    # ---- fail criteria from protocol.md section C --------------------------
    sel = res["schemes"][chosen]
    far_ok = (sel["all_in_band"] if chosen == "global"
              else all(v["in_band"] for v in sel["per_policy"].values()))
    exch_ok = all(v["exchangeability_auc"] <= 0.70 for v in res["diagnostics"].values())
    drift_ok = all(v["drift_over_sd"] <= 1.0 for v in res["diagnostics"].values())
    res["fail_criteria"] = {
        "C1_false_alarm_in_band": bool(far_ok),
        "C2_exchangeable_auc_le_0.70": bool(exch_ok),
        "C3_drift_within_between_run_spread": bool(drift_ok),
    }
    verdict = "PASS" if (far_ok and exch_ok and drift_ok) else (
        "PARTIAL" if far_ok or exch_ok else "FAIL")
    res["verdict"] = verdict
    print("\nPRE-REGISTERED FAIL CRITERIA")
    for k, v in res["fail_criteria"].items():
        print(f"  {'OK  ' if v else 'FAIL'}  {k}")
    print(f"\n  E18 VERDICT: {verdict}")

    (BASE / "processed_results").mkdir(parents=True, exist_ok=True)
    (BASE / "processed_results" / "calibration_analysis.json").write_text(
        json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(f"  -> {BASE / 'processed_results' / 'calibration_analysis.json'}")


if __name__ == "__main__":
    main()
