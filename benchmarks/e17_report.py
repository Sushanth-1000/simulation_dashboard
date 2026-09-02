"""Render E17 sweep tables (Markdown) and figures (SVG).

SVG is written directly because `matplotlib` is not in the pinned environment.
The figures are vector and paper-ready; no plotting dependency is introduced.

This module renders. It does not decide anything -- interpretation lives in the
`E17_*` Markdown documents, written by hand against these outputs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.e17_analyse import FAULTS, PRIMARY_STAGE, STAGES

W, H = 760, 300
PAD_L, PAD_R, PAD_T, PAD_B = 58, 18, 34, 46
PALETTE = ("#1b6ca8", "#c0392b", "#27795b", "#8e44ad", "#b8860b", "#2c3e50")


def _svg(body: str, w: int = W, h: int = H, title: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="Georgia,serif" font-size="11">'
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>'
        f'<text x="{w / 2:.0f}" y="18" text-anchor="middle" font-size="13" '
        f'font-weight="bold">{title}</text>{body}</svg>'
    )


def _axes(ylo: float, yhi: float, xlabels: list[str], h: int = H) -> tuple[str, object, object]:
    """Return (svg fragment, x(i), y(v)) for a plot with categorical x."""
    n = max(len(xlabels), 2)
    x0, x1 = PAD_L, W - PAD_R
    y0, y1 = h - PAD_B, PAD_T

    def x(i: float) -> float:
        return x0 + (x1 - x0) * (i / (n - 1))

    def y(v: float) -> float:
        return y0 + (y1 - y0) * ((v - ylo) / (yhi - ylo))

    parts = [
        f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" stroke="#333"/>',
        f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="#333"/>',
    ]
    steps = 5
    for k in range(steps + 1):
        v = ylo + (yhi - ylo) * k / steps
        yy = y(v)
        parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="#eee"/>')
        parts.append(
            f'<text x="{x0 - 6}" y="{yy + 3:.1f}" text-anchor="end" fill="#444">{v:.2f}</text>'
        )
    for i, lab in enumerate(xlabels):
        parts.append(
            f'<text x="{x(i):.1f}" y="{y0 + 15}" text-anchor="middle" fill="#444">{lab}</text>'
        )
    return "".join(parts), x, y


def fig1_stage_profiles(a: dict, dest: Path) -> None:
    """D_s across stages, one panel per policy, one line per fault."""
    tA = a["tableA_stage_profiles"]
    for p in a["policies"]:
        frag, x, y = _axes(0.4, 1.0, list(STAGES))
        parts = [frag]
        # absorption threshold
        parts.append(
            f'<line x1="{PAD_L}" y1="{y(0.60):.1f}" x2="{W - PAD_R}" y2="{y(0.60):.1f}" '
            f'stroke="#c0392b" stroke-dasharray="5,3"/>'
            f'<text x="{W - PAD_R - 2}" y="{y(0.60) - 4:.1f}" text-anchor="end" '
            f'fill="#c0392b">absorption threshold 0.60</text>'
        )
        for k, f in enumerate(FAULTS):
            cell = tA.get(f"{p}|{f}")
            if not cell:
                continue
            col = PALETTE[k % len(PALETTE)]
            band = []
            pts = []
            for i, s in enumerate(STAGES):
                c = cell[s]
                pts.append(f"{x(i):.1f},{y(c['median']):.1f}")
                band.append((x(i), y(c["hi"]), y(c["lo"])))
            top = " ".join(f"{bx:.1f},{bh:.1f}" for bx, bh, _ in band)
            bot = " ".join(f"{bx:.1f},{bl:.1f}" for bx, _, bl in reversed(band))
            parts.append(f'<polygon points="{top} {bot}" fill="{col}" opacity="0.10"/>')
            parts.append(
                f'<polyline points="{" ".join(pts)}" fill="none" stroke="{col}" stroke-width="1.8"/>'
            )
            parts.append(
                f'<text x="{W - PAD_R - 4}" y="{PAD_T + 10 + k * 12}" text-anchor="end" '
                f'fill="{col}">{f}</text>'
            )
        (dest / f"fig1_stage_profile_{p}.svg").write_text(
            _svg("".join(parts), title=f"Figure 1{p} - stage-wise discriminability, policy {p} (median, BCa 95% CI, n=30)"),
            encoding="utf-8",
        )


def fig2_effects(a: dict, dest: Path) -> None:
    """Forest plot of D_L1 - D_L2a with BCa CIs."""
    tB = a["tableB_primary_test"]
    rows = [
        (f"{p}  {f}", tB[p][f]["effect_L1_minus_L2a"], tB[p][f]["primary"])
        for p in a["policies"]
        for f in FAULTS
        if f in tB.get(p, {})
    ]
    h = 60 + 20 * len(rows)
    x0, x1 = 190, W - 30
    lo = min(0.0, min(r[1]["lo"] for r in rows)) - 0.05
    hi = max(0.0, max(r[1]["hi"] for r in rows)) + 0.05

    def X(v: float) -> float:
        return x0 + (x1 - x0) * (v - lo) / (hi - lo)

    parts = [
        f'<line x1="{X(0):.1f}" y1="34" x2="{X(0):.1f}" y2="{h - 26}" stroke="#c0392b" stroke-dasharray="4,3"/>',
        f'<text x="{X(0):.1f}" y="{h - 14}" text-anchor="middle" fill="#c0392b">no effect</text>',
    ]
    for i, (label, e, primary) in enumerate(rows):
        yy = 48 + 20 * i
        col = "#1b6ca8" if primary else "#666"
        weight = "bold" if primary else "normal"
        parts.append(
            f'<text x="{x0 - 8}" y="{yy + 3}" text-anchor="end" font-weight="{weight}" fill="{col}">{label}</text>'
        )
        if e.get("degenerate"):
            parts.append(
                f'<circle cx="{X(e["median"]):.1f}" cy="{yy}" r="3.5" fill="{col}"/>'
                f'<text x="{X(e["median"]) + 8:.1f}" y="{yy + 3}" fill="#888" font-size="9">'
                f'identical across all 30 seeds</text>'
            )
        else:
            parts.append(
                f'<line x1="{X(e["lo"]):.1f}" y1="{yy}" x2="{X(e["hi"]):.1f}" y2="{yy}" stroke="{col}" stroke-width="1.5"/>'
                f'<circle cx="{X(e["median"]):.1f}" cy="{yy}" r="3.5" fill="{col}"/>'
            )
    (dest / "fig2_effect_sizes.svg").write_text(
        _svg("".join(parts), h=h, title=f"Figure 2 - D_L1 minus D_{PRIMARY_STAGE}, median and BCa 95% CI"),
        encoding="utf-8",
    )


def fig3_regime(a: dict, rows: list[dict], dest: Path) -> None:
    """D_L1 against veto rate for the speed faults -- the regime hypothesis."""
    for f in ("speed_bias", "speed_stuck"):
        pts = [r for r in rows if r["fault"] == f]
        if not pts:
            continue
        frag, _, y = _axes(0.4, 1.0, [])
        x0, x1 = PAD_L, W - PAD_R
        parts = [frag]
        vmax = max((p["veto_rate"] for p in pts if p["veto_rate"] == p["veto_rate"]), default=1.0)
        vmax = max(vmax, 0.05)

        def X(v: float) -> float:
            return x0 + (x1 - x0) * min(v / vmax, 1.0)

        for k in range(6):
            v = vmax * k / 5
            parts.append(
                f'<text x="{X(v):.1f}" y="{H - PAD_B + 15}" text-anchor="middle" fill="#444">{v:.2f}</text>'
            )
        parts.append(
            f'<text x="{(x0 + x1) / 2:.0f}" y="{H - 12}" text-anchor="middle" fill="#333">'
            f'veto rate (faulted arm)</text>'
        )
        parts.append(
            f'<line x1="{x0}" y1="{y(0.60):.1f}" x2="{x1}" y2="{y(0.60):.1f}" '
            f'stroke="#c0392b" stroke-dasharray="5,3"/>'
        )
        for k, p in enumerate(sorted({r["policy"] for r in pts})):
            col = PALETTE[k % len(PALETTE)]
            for r in pts:
                if r["policy"] != p:
                    continue
                d = r["D"].get("L1")
                if d is None or d != d or r["veto_rate"] != r["veto_rate"]:
                    continue
                parts.append(
                    f'<circle cx="{X(r["veto_rate"]):.1f}" cy="{y(max(0.4, min(1.0, d))):.1f}" '
                    f'r="2.6" fill="{col}" opacity="0.75"/>'
                )
            parts.append(
                f'<text x="{x1 - 4}" y="{PAD_T + 10 + k * 12}" text-anchor="end" fill="{col}">{p}</text>'
            )
        sp = a["H_regime_secondary"][f]["spearman_D_L1_vs_veto_rate"]
        rho = sp.get("rho")
        note = "n/a" if rho is None or rho != rho else f'rho = {rho:+.3f}, p = {sp["p"]:.4f}'
        parts.append(
            f'<text x="{x0 + 6}" y="{PAD_T + 10}" fill="#333">{note}  (EXPLORATORY)</text>'
        )
        (dest / f"fig3_regime_{f}.svg").write_text(
            _svg("".join(parts), title=f"Figure 3 - D_L1 vs veto rate, {f}"), encoding="utf-8"
        )


def fig4_absorption(a: dict, dest: Path) -> None:
    """Modal absorption stage and its stability, per policy and fault."""
    tC = a["tableC_absorption_stability"]
    rows = [(p, f, tC[f"{p}|{f}"]) for p in a["policies"] for f in FAULTS if f"{p}|{f}" in tC]
    h = 60 + 20 * len(rows)
    x0, x1 = 190, W - 90
    parts = []
    for i, (p, f, c) in enumerate(rows):
        yy = 48 + 20 * i
        frac = c["modal_fraction"]
        col = "#27795b" if frac == 1.0 else ("#b8860b" if frac >= 0.8 else "#c0392b")
        parts.append(
            f'<text x="{x0 - 8}" y="{yy + 3}" text-anchor="end" fill="#333">{p}  {f}</text>'
            f'<rect x="{x0}" y="{yy - 6}" width="{(x1 - x0) * frac:.1f}" height="12" fill="{col}" opacity="0.8"/>'
            f'<rect x="{x0}" y="{yy - 6}" width="{x1 - x0}" height="12" fill="none" stroke="#ddd"/>'
            f'<text x="{x1 + 6}" y="{yy + 3}" fill="#333">{c["modal"]}  {frac * 100:.0f}%</text>'
        )
    (dest / "fig4_absorption_stability.svg").write_text(
        _svg("".join(parts), h=h, title="Figure 4 - modal absorption stage and its across-seed stability"),
        encoding="utf-8",
    )


def _fmt(c: dict) -> str:
    if c.get("degenerate"):
        return f"{c['median']:.3f}"
    return f"{c['median']:.3f} [{c['lo']:.3f}, {c['hi']:.3f}]"


def tables(a: dict, dest: Path) -> None:
    tA, tB, tC, tD = (
        a["tableA_stage_profiles"],
        a["tableB_primary_test"],
        a["tableC_absorption_stability"],
        a["tableD_regime"],
    )
    L = ["# Table A - stage-wise discriminability", "", "Median across 30 seeds, BCa 95% CI. A bare number means every seed gave the identical value.", ""]
    for p in a["policies"]:
        L += [f"## Policy {p}", "", "| fault | " + " | ".join(STAGES) + " |", "|---|" + "--:|" * len(STAGES)]
        for f in FAULTS:
            c = tA.get(f"{p}|{f}")
            if c:
                L.append(f"| {f} | " + " | ".join(_fmt(c[s]) for s in STAGES) + " |")
        L.append("")
    (dest / "tableA_stage_profiles.md").write_text("\n".join(L), encoding="utf-8")

    L = [
        f"# Table B - primary test: D_L1 vs D_{PRIMARY_STAGE}",
        "",
        "Wilcoxon signed-rank, two-sided, paired by seed. Holm-Bonferroni across the six faults within each policy. Effect is the median paired difference with a BCa 95% CI.",
        "",
    ]
    for p in a["policies"]:
        L += [
            f"## Policy {p}",
            "",
            "| fault | primary | n | W | z | p (raw) | p (Holm) | reject | effect L1-L2a |",
            "|---|:--:|--:|--:|--:|--:|--:|:--:|---|",
        ]
        for f in FAULTS:
            d = tB[p][f]
            w, hm, e = d["wilcoxon"], d["holm"], d["effect_L1_minus_L2a"]
            z = "n/a" if w["z"] != w["z"] else f"{w['z']:.2f}"
            L.append(
                f"| {f} | {'**yes**' if d['primary'] else 'no'} | {w['n']} | {w['W']:.0f} | {z} | "
                f"{hm['p_raw']:.2e} | {hm['p_holm']:.2e} | {'**yes**' if hm['reject'] else 'no'} | {_fmt(e)} |"
            )
        L.append("")
    (dest / "tableB_primary_test.md").write_text("\n".join(L), encoding="utf-8")

    L = [
        "# Table C - absorption-stage stability",
        "",
        "`unique` counts seeds whose D_s curve crosses the 0.60 threshold at most once. A non-monotonic curve has no well-posed absorption point and is reported as such rather than forced.",
        "",
        "| policy | fault | modal A(f) | modal % | unique / n | distribution |",
        "|---|---|:--:|--:|--:|---|",
    ]
    for p in a["policies"]:
        for f in FAULTS:
            c = tC.get(f"{p}|{f}")
            if not c:
                continue
            dist = ", ".join(f"{k}:{v}" for k, v in sorted(c["absorption_counts"].items()))
            L.append(
                f"| {p} | {f} | {c['modal']} | {c['modal_fraction'] * 100:.0f}% | "
                f"{c['n_unique_absorption']}/{c['n']} | {dist} |"
            )
    (dest / "tableC_absorption_stability.md").write_text("\n".join(L), encoding="utf-8")

    L = [
        "# Table D - operating regime",
        "",
        "Regime cut points were fixed in `PREREGISTRATION.md` section 3 before the sweep ran.",
        "",
        "| policy | veto rate median [min, max] | mean speed median [min, max] | regime counts |",
        "|---|---|---|---|",
    ]
    for p in a["policies"]:
        d = tD[p]
        v, s = d["veto_rate"], d["mean_speed"]
        rc = ", ".join(f"{k}:{n}" for k, n in sorted(d["regime_counts"].items()))
        L.append(
            f"| {p} | {v['median']:.4f} [{v['min']:.4f}, {v['max']:.4f}] | "
            f"{s['median']:.2f} [{s['min']:.2f}, {s['max']:.2f}] | {rc} |"
        )
    (dest / "tableD_regime.md").write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("results/E17_30SEED"))
    args = ap.parse_args()
    a = json.loads((args.dir / "statistics" / "analysis.json").read_text(encoding="utf-8"))

    from benchmarks.e17_analyse import load

    rows = load(args.dir / "raw")
    plots, tabs = args.dir / "plots", args.dir / "tables"
    plots.mkdir(parents=True, exist_ok=True)
    tabs.mkdir(parents=True, exist_ok=True)

    fig1_stage_profiles(a, plots)
    fig2_effects(a, plots)
    fig3_regime(a, rows, plots)
    fig4_absorption(a, plots)
    tables(a, tabs)
    print(f"  figures -> {plots}")
    print(f"  tables  -> {tabs}")


if __name__ == "__main__":
    main()
