"""Record the E17 baseline so every later E18 change stays distinguishable from it.

Read-only with respect to E17: this module hashes and describes, it never edits
an E17 result.
"""

from __future__ import annotations

import csv
import hashlib
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments" / "phase5_od8_h7" / "E17_BASELINE"

E17_TREES = [
    ("results/E17_30SEED", "E17 30-seed sweep"),
    ("results/E17_POSITION", "E17 corrected position re-run"),
    ("results/E17_INTEGRITY", "E17 fault-injection integrity + negative controls"),
    ("results/E17_FINAL", "E17 CSV artifacts"),
]
E17_CODE = [
    "benchmarks/discriminability.py", "benchmarks/fault_study.py", "benchmarks/e17_sweep.py",
    "benchmarks/e17_stats.py", "benchmarks/e17_analyse.py", "benchmarks/e17_report.py",
    "benchmarks/e17_integrity.py", "benchmarks/e17_controls.py", "benchmarks/e17_position.py",
    "benchmarks/e17_position_analyse.py", "benchmarks/e17_artifacts.py", "benchmarks/e17_l6.py",
    "training/closed_loop.py", "training/faults.py", "training/redundant.py",
]
E17_DOCS = sorted((ROOT / "research").glob("E17_*.md"))
ARTIFACTS = ["var/policy/synthetic.pt", "var/policy/long.pt", "var/policy/jerkscaled.pt",
             "var/calibration/synthetic.json"]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unavailable"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    commit = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    status = git("status", "--porcelain")
    dirty = [ln for ln in status.splitlines() if ln.strip()]

    rows: list[dict] = []
    for rel, desc in E17_TREES:
        base = ROOT / rel
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                rows.append({"category": "result", "path": str(p.relative_to(ROOT)).replace("\\", "/"),
                             "bytes": p.stat().st_size, "sha256": sha256(p), "description": desc})
    for rel in E17_CODE:
        p = ROOT / rel
        if p.exists():
            rows.append({"category": "code", "path": rel, "bytes": p.stat().st_size,
                         "sha256": sha256(p), "description": "E17 experiment / harness code"})
    for p in E17_DOCS:
        rows.append({"category": "document", "path": str(p.relative_to(ROOT)).replace("\\", "/"),
                     "bytes": p.stat().st_size, "sha256": sha256(p), "description": "E17 audit record"})
    for rel in ARTIFACTS:
        p = ROOT / rel
        if p.exists():
            rows.append({"category": "artifact", "path": rel, "bytes": p.stat().st_size,
                         "sha256": sha256(p), "description": "policy checkpoint / calibration corpus"})

    with (OUT / "artifact_manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["category", "path", "bytes", "sha256", "description"])
        w.writeheader()
        w.writerows(rows)

    total = sum(r["bytes"] for r in rows)
    by_cat: dict[str, list[int]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["bytes"])

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "# E17 Baseline Manifest",
        "",
        f"**Recorded {ts}** — read-only snapshot taken before any E18 change.",
        "",
        "This exists so every later E18 modification stays distinguishable from the E17 state. "
        "Nothing in `results/E17_*` or `research/E17_*.md` was modified to produce it.",
        "",
        "## Repository state",
        "",
        "| | |",
        "|---|---|",
        f"| Commit | `{commit}` |",
        f"| Branch | `{branch}` |",
        f"| Working tree | **{len(dirty)} uncommitted paths** |",
        f"| Unpushed commits | {git('rev-list', '--count', 'origin/' + branch + '..HEAD')} |",
        "",
        "**The E17 results were generated from an uncommitted working tree.** The commit hash above "
        "identifies the last commit, *not* the exact code that produced the results. The manifest's "
        "per-file SHA-256 hashes are therefore the authoritative record of what ran, and are why "
        "this manifest exists in this form.",
        "",
        "## Uncommitted paths at baseline",
        "",
        "```",
        *dirty,
        "```",
        "",
        "## Artifact summary",
        "",
        "| category | files | bytes |",
        "|---|--:|--:|",
    ]
    for cat in sorted(by_cat):
        lines.append(f"| {cat} | {len(by_cat[cat])} | {sum(by_cat[cat]):,} |")
    lines += [f"| **total** | **{len(rows)}** | **{total:,}** |", "",
              "Per-file SHA-256 in `artifact_manifest.csv`.", "",
              "## Environment", "",
              "| | |", "|---|---|",
              f"| Python | {sys.version.split()[0]} |",
              f"| Platform | {platform.platform()} |"]
    for mod in ("numpy", "torch"):
        try:
            m = __import__(mod)
            lines.append(f"| {mod} | {m.__version__} |")
        except Exception:
            lines.append(f"| {mod} | not importable |")
    lines += ["", "## Immutability rule", "",
              "E17 results are **frozen**. E18 may read them and must not modify them. Any E17 "
              "correction requires a new dated document in `research/`, never an edit in place — "
              "the same rule that kept the invalidated position rows auditable rather than deleted."]

    (OUT / "baseline_manifest.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  manifest: {len(rows)} files, {total:,} bytes")
    print(f"  commit {commit[:12]} on {branch}, {len(dirty)} uncommitted paths")
    print(f"  -> {OUT}")


if __name__ == "__main__":
    main()
