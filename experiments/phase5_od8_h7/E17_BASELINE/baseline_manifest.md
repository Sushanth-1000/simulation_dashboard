# E17 Baseline Manifest

**Recorded 2026-09-01 10:48:24Z** — read-only snapshot taken before any E18 change.

This exists so every later E18 modification stays distinguishable from the E17 state. Nothing in `results/E17_*` or `research/E17_*.md` was modified to produce it.

## Repository state

| | |
|---|---|
| Commit | `6383676a3491dc82d70f2db20cdafb942e5c588a` |
| Branch | `phase4-l5-twin-l7b-physical` |
| Working tree | **29 uncommitted paths** |
| Unpushed commits | 1 |

**The E17 results were generated from an uncommitted working tree.** The commit hash above identifies the last commit, *not* the exact code that produced the results. The manifest's per-file SHA-256 hashes are therefore the authoritative record of what ran, and are why this manifest exists in this form.

## Uncommitted paths at baseline

```
M benchmarks/tick_latency.py
 M src/astra/invariants/catalogue.py
 M tests/unit/test_tick_latency.py
 M training/closed_loop.py
?? benchmarks/discriminability.py
?? benchmarks/e17_analyse.py
?? benchmarks/e17_artifacts.py
?? benchmarks/e17_baseline_manifest.py
?? benchmarks/e17_controls.py
?? benchmarks/e17_integrity.py
?? benchmarks/e17_l6.py
?? benchmarks/e17_position.py
?? benchmarks/e17_position_analyse.py
?? benchmarks/e17_report.py
?? benchmarks/e17_stats.py
?? benchmarks/e17_sweep.py
?? benchmarks/e18_analyse.py
?? benchmarks/e18_calibrate.py
?? benchmarks/e18_evaluate.py
?? benchmarks/e18_report.py
?? conference.md
?? docs/ASTRA_Research_Collaboration_Briefing.pptx
?? docs/PAPER_REJECTION_RISK.md
?? docs/REBASELINE_2026-08-31.md
?? docs/build_astra_deck.py
?? experiments/
?? final_plan.md
?? research/
?? results/
```

## Artifact summary

| category | files | bytes |
|---|--:|--:|
| artifact | 4 | 229,466 |
| code | 15 | 185,173 |
| document | 13 | 94,770 |
| result | 120 | 2,378,092 |
| **total** | **152** | **2,887,501** |

Per-file SHA-256 in `artifact_manifest.csv`.

## Environment

| | |
|---|---|
| Python | 3.12.9 |
| Platform | Windows-11-10.0.26200-SP0 |
| numpy | 2.5.1 |
| torch | 2.13.0+cpu |

## Immutability rule

E17 results are **frozen**. E18 may read them and must not modify them. Any E17 correction requires a new dated document in `research/`, never an edit in place — the same rule that kept the invalidated position rows auditable rather than deleted.