# Phase 5 - Data Management

Per the Phase 5 brief, source and configuration are version-controlled; large generated artifacts are
recorded rather than committed by default.

## Version-controlled

- `benchmarks/e17_*.py`, `benchmarks/e18_*.py` -- experiment code
- `experiments/phase5_od8_h7/**/*.md` -- protocols, configurations, analyses, decisions
- `experiments/phase5_od8_h7/**/processed_results/*.json` -- small processed summaries

## Recorded, not committed by default

| artifact | location | generation command | experiment |
|---|---|---|---|
| Clean calibration scores | `E18_OD8_CALIBRATION/raw_results/calibration.json` | `python -m benchmarks.e18_calibrate` | E18 |
| Clean test scores | `E18_OD8_CALIBRATION/raw_results/clean_test.json` | same | E18 |
| Fault evaluation | `E18_OD8_CALIBRATION/raw_results/fault_evaluation.json` | `python -m benchmarks.e18_evaluate` | E18 |
| E17 30-seed sweep | `results/E17_30SEED/raw/` (90 files) | `python -m benchmarks.e17_sweep` | E17 |
| E17 position re-run | `results/E17_POSITION/position_runs.json` | `python -m benchmarks.e17_position` | E17-Position |
| E17 integrity | `results/E17_INTEGRITY/` | `python -m benchmarks.e17_integrity`, `e17_controls` | E17 |

All are regenerable from the listed command plus the pinned environment
(Python 3.12, numpy 2.5.1, torch 2.13.0, CPU-only) and the recorded seeds.

## Confidentiality

The repository carries a confidentiality notice and an intended patent filing covering the
architecture. **Nothing here is to be distributed, demonstrated externally or published until filing
status is confirmed.** Whether raw artifacts are committed, and whether the branch is pushed, are
decisions for the project owner and have deliberately not been taken by tooling.

## Not yet committed

As of 1 September 2026 the entire Phase 5 tree, the E17 audit tree (`research/`, `results/`) and the
harness change to `training/closed_loop.py` exist only in the working tree. This is the single
largest risk to the work and is flagged for an explicit decision.

## E18-R1 artifacts (1 Sep 2026)

| artifact | location | generation command |
|---|---|---|
| Clean run-local calibration | `E18_R1/raw_results/clean_runlocal.json` | `python -m benchmarks.e18r1_calibrate --skip-faults` |
| Run manifest (60 runs) | `E18_R1/run_manifest.csv` | same |
| Artifact checksums | `E18_R1/artifact_manifest.csv` | same |

Faulted evaluation deliberately not run: P3 was not recovered, so detection numbers would describe an uncalibrated monitor.
