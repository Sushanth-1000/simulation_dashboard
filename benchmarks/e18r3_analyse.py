"""E18-R3 analysis: does false-alarm variance fall as 1/sqrt(n)?

The runs-in-band count is the frozen criterion; the scaling exponent is the
mechanism test. A slope near -0.5 means independent-sample behaviour
(precision-limited). A slope near 0 means more data buys nothing
(dynamics-limited).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from benchmarks.e18r3_windows import EPS, FROZEN_V3, WINDOWS

BASE = Path("experiments/phase5_od8_h7/E18_R3")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=BASE)
    a = ap.parse_args()
    rows = json.loads((a.dir / "raw_results" / "long_runs.json").read_text(encoding="utf-8"))
    pols = sorted({r["policy"] for r in rows})
    out: dict = {"epsilon": EPS, "frozen_thresholds": FROZEN_V3, "windows": list(WINDOWS)}

    # ---- integrity ---------------------------------------------------------
    nf = sum(r["nonfinite"] for r in rows)
    short = [r["seed"] for r in rows if r["available_eval_ticks"] < max(WINDOWS)]
    print(f"INTEGRITY  runs={len(rows)}  non-finite scores={nf}  "
          f"runs too short for n={max(WINDOWS)}: {len(short)}")
    out["integrity"] = {"n_runs": len(rows), "nonfinite": nf, "short_runs": short}

    # ---- confounder: drift on the long runs (section 6) --------------------
    print("\nCONFOUNDER CHECK - within-run drift on the long runs")
    print(f"{'pol':<5}{'1st half':>11}{'2nd half':>11}{'drift':>10}{'drift/SD':>10}  verdict")
    drift_ok = True
    out["drift"] = {}
    for p in pols:
        g = [r for r in rows if r["policy"] == p]
        h1 = np.mean([r["first_half_mean"] for r in g])
        h2 = np.mean([r["second_half_mean"] for r in g])
        sd = np.mean([r["sd_within"] for r in g])
        ratio = abs(h2 - h1) / sd if sd > 0 else float("nan")
        ok = ratio <= 1.0
        drift_ok &= ok
        out["drift"][p] = {"first_half": float(h1), "second_half": float(h2),
                           "drift": float(h2 - h1), "drift_over_sd": float(ratio),
                           "within_limit": bool(ok)}
        print(f"{p:<5}{h1:>11.4f}{h2:>11.4f}{h2 - h1:>10.4f}{ratio:>10.2f}  "
              f"{'ok' if ok else 'EXCEEDS 1.0 -> R3 INCONCLUSIVE'}")

    # ---- runs in band vs window -------------------------------------------
    print("\nRUNS IN BAND vs EVALUATION WINDOW")
    hdr = f"{'pol':<5}" + "".join(f"{'n=' + str(n):>14}" for n in WINDOWS)
    print(hdr)
    band: dict[str, dict] = {}
    for p in pols:
        g = [r for r in rows if r["policy"] == p]
        cells = []
        band[p] = {}
        for n in WINDOWS:
            f = np.array([r[f"far_{n}"] for r in g], float)
            f = f[np.isfinite(f)]
            k = int(((f >= EPS / 2) & (f <= 2 * EPS)).sum())
            lo, hi = wilson(k, f.size)
            band[p][n] = {"in_band": k, "n_runs": int(f.size), "wilson": [lo, hi],
                          "median_far": float(np.median(f)) if f.size else float("nan"),
                          "sd_far": float(f.std(ddof=1)) if f.size > 1 else float("nan")}
            cells.append(f"{k}/{f.size}")
        print(f"{p:<5}" + "".join(f"{c:>14}" for c in cells))
    out["runs_in_band"] = band

    # ---- the mechanism test: scaling exponent ------------------------------
    print("\nMECHANISM TEST - how per-run FAR variability scales with window length")
    print(f"{'pol':<5}{'':>2}" + "".join(f"{'SD@' + str(n):>12}" for n in WINDOWS)
          + f"{'slope b':>11}{'binomial b':>12}  interpretation")
    out["scaling"] = {}
    for p in pols:
        g = [r for r in rows if r["policy"] == p]
        sds, ns = [], []
        for n in WINDOWS:
            f = np.array([r[f"far_{n}"] for r in g], float)
            f = f[np.isfinite(f)]
            if f.size > 1 and f.std(ddof=1) > 0:
                sds.append(f.std(ddof=1))
                ns.append(n)
        if len(ns) >= 3:
            b, aa = np.polyfit(np.log(ns), np.log(sds), 1)
        else:
            b = aa = float("nan")
        interp = ("precision-limited" if b <= -0.40 else
                  "dynamics-limited" if b >= -0.10 else
                  "partial pooling")
        out["scaling"][p] = {"slope": float(b), "windows": ns,
                             "sd": [float(x) for x in sds], "interpretation": interp}
        cells = "".join(f"{band[p][n]['sd_far']:>12.4f}" for n in WINDOWS)
        print(f"{p:<5}{'':>2}{cells}{b:>11.3f}{-0.5:>12.2f}  {interp}")

    # ---- observed vs binomial variance -------------------------------------
    print("\nOVERDISPERSION vs an independent-tick monitor")
    print(f"{'pol':<5}" + "".join(f"{'n=' + str(n):>12}" for n in WINDOWS))
    out["overdispersion"] = {}
    for p in pols:
        g = [r for r in rows if r["policy"] == p]
        cells = []
        out["overdispersion"][p] = {}
        for n in WINDOWS:
            f = np.array([r[f"far_{n}"] for r in g], float)
            f = f[np.isfinite(f)]
            if f.size > 1:
                pbar = f.mean()
                binom = np.sqrt(pbar * (1 - pbar) / n)
                ratio = f.std(ddof=1) / binom if binom > 0 else float("nan")
                neff = pbar * (1 - pbar) / f.var(ddof=1) if f.var(ddof=1) > 0 else float("nan")
            else:
                ratio = neff = float("nan")
            out["overdispersion"][p][n] = {"ratio": float(ratio), "n_eff": float(neff)}
            cells.append(f"{ratio:.1f}x")
        print(f"{p:<5}" + "".join(f"{c:>12}" for c in cells))

    # ---- verdict against the frozen criterion ------------------------------
    n_top = max(WINDOWS)
    p1 = band.get("P1", {}).get(n_top, {}).get("in_band", 0)
    if not drift_ok:
        verdict = "INCONCLUSIVE-R3"
        why = "drift/SD exceeded 1.0 on the long runs; the design could not isolate its variable"
    elif p1 >= 24:
        verdict = "PASS-R3"
        why = "precision-limited: a longer window restores per-run stability on the positive control"
    elif p1 >= 12:
        verdict = "PARTIAL-R3"
        why = "improving but below the frozen 24/30 bar"
    else:
        verdict = "FAIL-R3"
        why = "dynamics-limited: window length does not restore stability"
    out["verdict"] = verdict
    out["verdict_reason"] = why
    out["P1_in_band_at_max_window"] = p1
    print(f"\nPRIMARY CRITERION  P1 >= 24/30 at n={n_top}  ->  {p1}/30  ->  {verdict}")
    print(f"  {why}")

    proc = a.dir / "processed_results"
    proc.mkdir(parents=True, exist_ok=True)
    (proc / "analysis.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    with (proc / "E18R3_WINDOWS.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["policy", "window", "runs_in_band", "n_runs", "median_far", "sd_far",
                    "overdispersion", "n_eff", "threshold"])
        for p in pols:
            for n in WINDOWS:
                bb = band[p][n]
                od = out["overdispersion"][p][n]
                w.writerow([p, n, bb["in_band"], bb["n_runs"], f"{bb['median_far']:.6f}",
                            f"{bb['sd_far']:.6f}", f"{od['ratio']:.4f}", f"{od['n_eff']:.2f}",
                            FROZEN_V3[p]])
    print(f"  -> {proc / 'analysis.json'}")


if __name__ == "__main__":
    main()
