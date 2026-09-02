# E18-R1 — Implementation Plan

## New code

| file | purpose |
|---|---|
| `benchmarks/e18r1_calibrate.py` | run-local calibration + evaluation. Computes `q_r` from each run's ticks 1..200, scores ticks 201..400, emits per-run records. |
| `benchmarks/e18r1_analyse.py` | primary criterion, E18-vs-R1 comparison, bimodality check, figures, manifests. |

## No changes to

- `src/astra/` — nothing in the architecture is touched.
- E18 artifacts — `frozen_thresholds.md` version 1 stays frozen and on record regardless of R1's
  outcome. R1 produces a **version 2** calibration; it does not overwrite version 1.
- The fault catalogue, severities, seeds, or the E19 hypothesis.

## Reuse

Score extraction, integrity flags and the closed-loop driver are reused unchanged from
`benchmarks/e18_evaluate.py` so that R1 and E18 differ **only** in how the threshold is obtained.
That is what makes the comparison in section 12 of the brief interpretable: one variable changes.

## Execution order

1. Clean test runs, P1 and P3, 30 seeds — run-local thresholds, run-level FAR. **Primary criterion.**
2. Integrity checks.
3. Only then: faulted runs, six fault classes, existing severities — detection after recalibration.
4. Analysis, figures, manifests, decision.

## Reproducibility artifacts

`run_manifest.csv` — one row per run: experiment ID, git commit, seed, policy, calibration version,
threshold, calibration n, FAR, artifact path.
`artifact_manifest.csv` — path, bytes, SHA-256 for every raw and processed file.
