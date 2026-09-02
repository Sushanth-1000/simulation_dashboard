"""E18 finalisation: stationarity, alarm suppression, P2 classification, tables, figures.

Adds what a pooled AUC cannot answer. Ticks inside a run are autocorrelated, so a
statistic computed over pooled ticks overstates its own evidence; the unit of
analysis here is the run wherever a per-run quantity exists.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from benchmarks.e17_stats import bca_median_ci, wilcoxon_signed_rank
from benchmarks.e18_evaluate import FROZEN_QUANTILE, SEVERITIES

BASE = Path("experiments/phase5_od8_h7/E18_OD8_CALIBRATION")
POLICIES = ("P1", "P2", "P3")
STAGES = ("L1", "L2a", "L2b", "L3", "L6", "L7", "L8")
EPS = 0.05
LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}
W, H = 720, 300
PAL = {"P1": "#1b6ca8", "P2": "#c0392b", "P3": "#27795b"}


# ------------------------------------------------------------------ svg ----
def svg(body: str, title: str, w: int = W, h: int = H) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" font-family="Georgia,serif" font-size="11">'
            f'<rect width="{w}" height="{h}" fill="#fff"/>'
            f'<text x="{w/2:.0f}" y="17" text-anchor="middle" font-size="12.5" '
            f'font-weight="bold">{title}</text>{body}</svg>')


def axes(xlo, xhi, ylo, yhi, xlab, ylab, w=W, h=H, pl=62, pr=18, pt=34, pb=44):
    x0, x1, y0, y1 = pl, w - pr, h - pb, pt
    def X(v): return x0 + (x1 - x0) * (v - xlo) / (xhi - xlo) if xhi > xlo else x0
    def Y(v): return y0 + (y1 - y0) * (v - ylo) / (yhi - ylo) if yhi > ylo else y0
    p = [f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" stroke="#333"/>',
         f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="#333"/>']
    for k in range(6):
        v = ylo + (yhi - ylo) * k / 5
        p.append(f'<line x1="{x0}" y1="{Y(v):.1f}" x2="{x1}" y2="{Y(v):.1f}" stroke="#eee"/>')
        p.append(f'<text x="{x0-6}" y="{Y(v)+3:.1f}" text-anchor="end" fill="#444">{v:.3g}</text>')
    for k in range(6):
        v = xlo + (xhi - xlo) * k / 5
        p.append(f'<text x="{X(v):.1f}" y="{y0+15}" text-anchor="middle" fill="#444">{v:.3g}</text>')
    p.append(f'<text x="{(x0+x1)/2:.0f}" y="{h-8}" text-anchor="middle" fill="#333">{xlab}</text>')
    p.append(f'<text x="14" y="{(y0+y1)/2:.0f}" text-anchor="middle" fill="#333" '
             f'transform="rotate(-90 14 {(y0+y1)/2:.0f})">{ylab}</text>')
    return "".join(p), X, Y


def hist(a, lo, hi, bins=40):
    c, e = np.histogram(a, bins=bins, range=(lo, hi))
    return c / max(c.max(), 1), e


# ------------------------------------------------------------- analysis ----
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=BASE)
    a = ap.parse_args()
    cal = json.loads((a.dir / "raw_results" / "calibration.json").read_text(encoding="utf-8"))
    tst = json.loads((a.dir / "raw_results" / "clean_test.json").read_text(encoding="utf-8"))
    ev = json.loads((a.dir / "raw_results" / "fault_evaluation.json").read_text(encoding="utf-8"))
    fig = a.dir / "figures"; fig.mkdir(parents=True, exist_ok=True)
    proc = a.dir / "processed_results"; proc.mkdir(parents=True, exist_ok=True)
    out: dict = {}

    def runs(doc, p): return [np.array(r["scores"], float) for r in doc["runs"][p]]
    def flat(doc, p):
        x = np.concatenate(runs(doc, p)); return x[np.isfinite(x)]

    # ---- Table A + per-run FAR (the diagnostic pooled FAR hides) ----------
    print("TABLE A - CALIBRATION")
    print(f"{'pol':<5}{'cal N':>8}{'threshold':>11}{'eps':>7}{'exp FAR':>9}{'held-out FAR':>14}"
          f"{'per-run FAR median [IQR]':>28}{'runs in band':>14}")
    tableA = {}
    for p in POLICIES:
        q = FROZEN_QUANTILE[p]
        c = flat(cal, p)
        per = np.array([float((r[np.isfinite(r)] > q).mean()) for r in runs(tst, p)])
        pooled = float(np.concatenate([r[np.isfinite(r)] for r in runs(tst, p)]) > q).__float__() \
            if False else float((np.concatenate([r[np.isfinite(r)] for r in runs(tst, p)]) > q).mean())
        inband = int(((per >= EPS / 2) & (per <= 2 * EPS)).sum())
        ci = bca_median_ci(per)
        tableA[p] = {"calibration_n": int(c.size), "threshold": q, "epsilon": EPS,
                     "expected_far": EPS, "heldout_far_pooled": pooled,
                     "per_run_far_median": ci["median"], "per_run_far_ci": [ci["lo"], ci["hi"]],
                     "per_run_far_iqr": [float(np.percentile(per, 25)), float(np.percentile(per, 75))],
                     "runs_in_band": inband, "n_runs": int(per.size),
                     "status": "in band" if EPS / 2 <= pooled <= 2 * EPS else "OUT OF BAND"}
        print(f"{p:<5}{c.size:>8}{q:>11.4f}{EPS:>7.2f}{EPS:>9.1%}{pooled:>14.2%}"
              f"{f'{ci[chr(109)+chr(101)+chr(100)+chr(105)+chr(97)+chr(110)]:.2%} [{np.percentile(per,25):.2%},{np.percentile(per,75):.2%}]':>28}"
              f"{f'{inband}/{per.size}':>14}")
    out["tableA"] = tableA

    # ---- stationarity: per-run drift, unit = run --------------------------
    print("\nSTATIONARITY (unit of analysis = run, n=30)")
    print(f"{'pol':<5}{'1st half':>10}{'2nd half':>10}{'drift':>9}{'drift/SD':>10}"
          f"{'runs w/ +drift':>16}{'Wilcoxon p':>12}")
    stat = {}
    for p in POLICIES:
        rs = [r[np.isfinite(r)] for r in runs(cal, p)]
        h1 = np.array([r[: len(r) // 2].mean() for r in rs])
        h2 = np.array([r[len(r) // 2:].mean() for r in rs])
        sd = flat(cal, p).std(ddof=1)
        w = wilcoxon_signed_rank(h2, h1)
        stat[p] = {"first_half": float(h1.mean()), "second_half": float(h2.mean()),
                   "drift": float(h2.mean() - h1.mean()), "drift_over_sd": float(abs(h2.mean()-h1.mean())/sd),
                   "runs_with_positive_drift": int((h2 > h1).sum()), "n_runs": len(rs),
                   "wilcoxon_p": w["p"]}
        print(f"{p:<5}{h1.mean():>10.4f}{h2.mean():>10.4f}{h2.mean()-h1.mean():>9.4f}"
              f"{abs(h2.mean()-h1.mean())/sd:>10.2f}{f'{(h2>h1).sum()}/{len(rs)}':>16}{w['p']:>12.2e}")
    out["stationarity"] = stat

    # ---- Section 14: alarm suppression, tested per seed --------------------
    print("\nALARM SUPPRESSION (fault alarm rate vs that policy's clean per-run FAR)")
    print(f"{'pol':<5}{'fault':<16}{'sev':<8}{'fault alarm':>13}{'clean FAR':>11}{'ratio':>8}"
          f"{'Wilcoxon p':>12}{'suppressed?':>13}")
    supp = []
    for p in ("P1", "P3", "P2"):
        q = FROZEN_QUANTILE[p]
        clean_per = np.array([float((r[np.isfinite(r)] > q).mean()) for r in runs(tst, p)])
        for f, spec in SEVERITIES.items():
            for lvl in sorted(spec["levels"], key=lambda k: LEVEL_ORDER.get(k, 9)):
                g = [r for r in ev if r["policy"] == p and r["fault"] == f
                     and r["severity_level"] == lvl and r["fault_reached_estimator"]]
                if not g:
                    continue
                fa = np.array([r["alarm_rate_faulted"] for r in g], float)
                fa = fa[np.isfinite(fa)]
                n = min(len(fa), len(clean_per))
                w = wilcoxon_signed_rank(fa[:n], clean_per[:n])
                ratio = fa.mean() / clean_per.mean() if clean_per.mean() > 0 else np.nan
                is_supp = bool(fa.mean() < clean_per.mean() and w["p"] < 0.05)
                supp.append({"policy": p, "fault": f, "severity": lvl,
                             "fault_alarm_rate": float(fa.mean()),
                             "clean_far": float(clean_per.mean()), "ratio": float(ratio),
                             "wilcoxon_p": w["p"], "suppressed": is_supp,
                             "policy_valid": p in ("P1", "P3")})
                if is_supp:
                    print(f"{p:<5}{f:<16}{lvl:<8}{fa.mean():>13.2%}{clean_per.mean():>11.2%}"
                          f"{ratio:>8.3f}{w['p']:>12.2e}{'YES':>13}")
    out["alarm_suppression"] = supp
    n_supp = sum(1 for s in supp if s["suppressed"] and s["policy_valid"])
    print(f"  -> {n_supp} suppressed cells on valid policies (of "
          f"{sum(1 for s in supp if s['policy_valid'])})")

    # ---- Table C: D_s vs operational detection ----------------------------
    print("\nTABLE C - D_s vs OPERATIONAL DETECTION (valid policies)")
    tc = []
    for p in ("P1", "P3"):
        for f, spec in SEVERITIES.items():
            for lvl in sorted(spec["levels"], key=lambda k: LEVEL_ORDER.get(k, 9)):
                g = [r for r in ev if r["policy"] == p and r["fault"] == f
                     and r["severity_level"] == lvl and r["fault_reached_estimator"]]
                if not g:
                    continue
                d1 = float(np.nanmedian([r["D"]["L1"] for r in g]))
                d6 = float(np.nanmedian([r["D"]["L6"] for r in g]))
                det = float(np.mean([r["detected"] for r in g]))
                agree = "agree" if (d6 >= 0.9) == (det >= 0.9) else "DISAGREE"
                tc.append({"policy": p, "fault": f, "severity": lvl, "D_L1": d1, "D_L6": d6,
                           "detection_rate": det, "agreement": agree})
    dis = [r for r in tc if r["agreement"] == "DISAGREE"]
    print(f"  {len(dis)} of {len(tc)} cells DISAGREE between D_L6>=0.9 and detection>=0.9")
    for r in dis[:8]:
        print(f"    {r['policy']} {r['fault']:<15} {r['severity']:<7} "
              f"D_L1={r['D_L1']:.3f} D_L6={r['D_L6']:.3f} detect={r['detection_rate']:.0%}")
    # rank correlation, unit = cell
    from benchmarks.e17_stats import spearman
    sp = spearman(np.array([r["D_L6"] for r in tc]), np.array([r["detection_rate"] for r in tc]))
    sp1 = spearman(np.array([r["D_L1"] for r in tc]), np.array([r["detection_rate"] for r in tc]))
    out["tableC"] = {"cells": tc, "spearman_DL6_vs_detection": sp, "spearman_DL1_vs_detection": sp1}
    print(f"  Spearman D_L6 vs detection: rho={sp['rho']:+.3f} p={sp['p']:.4f} (n={sp['n']})")
    print(f"  Spearman D_L1 vs detection: rho={sp1['rho']:+.3f} p={sp1['p']:.4f} (n={sp1['n']})")

    # ---- Figures ----------------------------------------------------------
    # F1: clean score distribution + frozen threshold
    for p in POLICIES:
        c = flat(cal, p); q = FROZEN_QUANTILE[p]
        lo, hi = min(c.min(), q) - 0.1, max(c.max(), q) + 0.1
        frag, X, Y = axes(lo, hi, 0, 1.05, "non-conformity score", "density (scaled)")
        n, e = hist(c, lo, hi)
        bars = "".join(f'<rect x="{X(e[i]):.1f}" y="{Y(n[i]):.1f}" '
                       f'width="{max(X(e[i+1])-X(e[i])-0.5,0.5):.1f}" '
                       f'height="{Y(0)-Y(n[i]):.1f}" fill="{PAL[p]}" opacity="0.55"/>'
                       for i in range(len(n)) if n[i] > 0)
        thr = (f'<line x1="{X(q):.1f}" y1="{Y(0):.1f}" x2="{X(q):.1f}" y2="{Y(1.05):.1f}" '
               f'stroke="#b0362a" stroke-width="1.8" stroke-dasharray="5,3"/>'
               f'<text x="{X(q)+5:.1f}" y="{Y(1.0):.1f}" fill="#b0362a">frozen q = {q:.4f}</text>')
        (fig / f"fig1_clean_distribution_{p}.svg").write_text(
            svg(frag + bars + thr, f"Figure 1{p} - clean calibration scores and frozen threshold ({p}, n={c.size})"),
            encoding="utf-8")

    # F2: calibration vs held-out
    for p in POLICIES:
        c, t = flat(cal, p), flat(tst, p)
        lo, hi = min(c.min(), t.min()) - 0.05, max(c.max(), t.max()) + 0.05
        frag, X, Y = axes(lo, hi, 0, 1.05, "non-conformity score", "density (scaled)")
        body = frag
        for arr, col, off in ((c, "#1b6ca8", 0), (t, "#b8860b", 1)):
            n, e = hist(arr, lo, hi)
            body += "".join(f'<rect x="{X(e[i]):.1f}" y="{Y(n[i]):.1f}" '
                            f'width="{max(X(e[i+1])-X(e[i])-0.5,0.5):.1f}" '
                            f'height="{Y(0)-Y(n[i]):.1f}" fill="{col}" opacity="0.42"/>'
                            for i in range(len(n)) if n[i] > 0)
            body += (f'<rect x="{W-190}" y="{36+off*14}" width="10" height="10" fill="{col}" '
                     f'opacity="0.6"/><text x="{W-174}" y="{45+off*14}" fill="#333">'
                     f'{"calibration" if off==0 else "held-out clean"}</text>')
        (fig / f"fig2_cal_vs_heldout_{p}.svg").write_text(
            svg(body, f"Figure 2{p} - calibration vs held-out clean ({p})"), encoding="utf-8")

    # F6: P2 temporal drift, per-run traces
    for p in POLICIES:
        rs = [r[np.isfinite(r)] for r in runs(cal, p)]
        lo = min(r.min() for r in rs); hi = max(r.max() for r in rs)
        frag, X, Y = axes(0, 400, lo, hi, "tick", "non-conformity score")
        body = frag
        for r in rs[:12]:
            step = max(len(r) // 120, 1)
            pts = " ".join(f"{X(i):.1f},{Y(r[i]):.1f}" for i in range(0, len(r), step))
            body += f'<polyline points="{pts}" fill="none" stroke="{PAL[p]}" stroke-width="0.7" opacity="0.5"/>'
        q = FROZEN_QUANTILE[p]
        if lo <= q <= hi:
            body += (f'<line x1="{X(0):.1f}" y1="{Y(q):.1f}" x2="{X(400):.1f}" y2="{Y(q):.1f}" '
                     f'stroke="#b0362a" stroke-dasharray="5,3"/>')
        d = stat[p]
        body += (f'<text x="{X(10):.1f}" y="{Y(hi)-6:.1f}" fill="#333">'
                 f'drift/SD = {d["drift_over_sd"]:.2f}   {d["runs_with_positive_drift"]}/{d["n_runs"]} runs drift upward</text>')
        (fig / f"fig6_temporal_drift_{p}.svg").write_text(
            svg(body, f"Figure 6{p} - within-run score trajectories ({p}, 12 of 30 runs)"), encoding="utf-8")

    # F7: D_L6 vs operational detection
    frag, X, Y = axes(0.4, 1.02, -0.05, 1.05, "D_L6  (statistical discriminability)",
                      "operational detection rate")
    body = frag
    for r in tc:
        col = PAL[r["policy"]]
        body += (f'<circle cx="{X(min(r["D_L6"],1.02)):.1f}" cy="{Y(r["detection_rate"]):.1f}" '
                 f'r="3.6" fill="{col}" opacity="0.75"/>')
    body += (f'<text x="{X(0.42):.1f}" y="{Y(1.0):.1f}" fill="#333">'
             f'Spearman rho = {sp["rho"]:+.3f}, p = {sp["p"]:.3f}   '
             f'{len(dis)}/{len(tc)} cells disagree</text>')
    for i, p in enumerate(("P1", "P3")):
        body += (f'<rect x="{W-90}" y="{36+i*14}" width="10" height="10" fill="{PAL[p]}"/>'
                 f'<text x="{W-74}" y="{45+i*14}" fill="#333">{p}</text>')
    (fig / "fig7_Ds_vs_detection.svg").write_text(
        svg(body, "Figure 7 - statistical discriminability does not predict operational detection"),
        encoding="utf-8")

    # F4/F5: detection by fault and severity
    frag, X, Y = axes(-0.5, 2.5, 0, 1.05, "severity level (low / medium / high)", "detection rate")
    body = frag
    faults = list(SEVERITIES)
    marks = {"P1": 0, "P3": 1}
    for p in ("P1", "P3"):
        for k, f in enumerate(faults):
            xs, ys = [], []
            for lvl in sorted(SEVERITIES[f]["levels"], key=lambda z: LEVEL_ORDER.get(z, 9)):
                g = [r for r in tc if r["policy"] == p and r["fault"] == f and r["severity"] == lvl]
                if g:
                    xs.append(LEVEL_ORDER.get(lvl, 1) + (marks[p] - 0.5) * 0.12)
                    ys.append(g[0]["detection_rate"])
            if xs:
                col = ["#1b6ca8", "#c0392b", "#27795b", "#8e44ad", "#b8860b", "#2c3e50"][k]
                if len(xs) > 1:
                    body += (f'<polyline points="{" ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))}" '
                             f'fill="none" stroke="{col}" stroke-width="1.4" '
                             f'{"stroke-dasharray=\'4,2\'" if p == "P3" else ""} opacity="0.85"/>')
                for x, y in zip(xs, ys):
                    body += f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3" fill="{col}"/>'
    for k, f in enumerate(faults):
        col = ["#1b6ca8", "#c0392b", "#27795b", "#8e44ad", "#b8860b", "#2c3e50"][k]
        body += (f'<text x="{W-24}" y="{40+k*13}" text-anchor="end" fill="{col}" font-size="9.5">{f}</text>')
    body += (f'<line x1="{X(-0.4):.1f}" y1="{Y(0.9):.1f}" x2="{X(2.4):.1f}" y2="{Y(0.9):.1f}" '
             f'stroke="#b0362a" stroke-dasharray="4,3"/>'
             f'<text x="{X(-0.35):.1f}" y="{Y(0.9)-4:.1f}" fill="#b0362a" font-size="9">MDS criterion 90%</text>')
    (fig / "fig5_detection_vs_severity.svg").write_text(
        svg(body, "Figure 5 - detection rate vs severity (solid P1, dashed P3)"), encoding="utf-8")

    # ---- write tables ------------------------------------------------------
    with (proc / "TABLE_A_calibration.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["policy", "calibration_n", "threshold", "epsilon", "expected_far",
                    "heldout_far_pooled", "per_run_far_median", "per_run_far_lo",
                    "per_run_far_hi", "runs_in_band", "n_runs", "status"])
        for p, v in tableA.items():
            w.writerow([p, v["calibration_n"], f"{v['threshold']:.4f}", v["epsilon"],
                        f"{v['expected_far']:.4f}", f"{v['heldout_far_pooled']:.4f}",
                        f"{v['per_run_far_median']:.4f}", f"{v['per_run_far_ci'][0]:.4f}",
                        f"{v['per_run_far_ci'][1]:.4f}", v["runs_in_band"], v["n_runs"], v["status"]])
    with (proc / "TABLE_C_ds_vs_detection.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(tc[0].keys()))
        w.writeheader(); w.writerows(tc)
    with (proc / "alarm_suppression.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(supp[0].keys()))
        w.writeheader(); w.writerows(supp)
    (proc / "final_analysis.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\n  figures -> {fig}\n  tables  -> {proc}")


if __name__ == "__main__":
    main()
