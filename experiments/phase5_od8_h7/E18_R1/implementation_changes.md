# E18-R1 - Implementation Changes

## Source code (`src/astra/`)

**None.** No ASTRA layer, contract or gate was touched.

## New code

| file | purpose |
|---|---|
| `benchmarks/e18r1_calibrate.py` | run-local calibration and evaluation. Computes `q_r` from each run's ticks 1-200 and scores ticks 201-400. Reuses `_run` and the score extraction from `benchmarks/e18_evaluate.py` unchanged, so R1 and E18 differ **only** in how the threshold is obtained. |

## Unchanged, deliberately

- E18's frozen thresholds (`frozen_thresholds.md` version 1) - **not overwritten**. R1 produces
  version 2 alongside it.
- The fault catalogue, severities and seeds.
- The E19 hypothesis and its `D_s` predictor.
- P2 - not tuned for, not pooled, not rescued.
- `_FAULT_FIRST = 200`, which is what fixes the window length and keeps it out of the space of
  tunable parameters.

## Reproduction

```
python -m benchmarks.e18r1_calibrate --skip-faults
```

`--skip-faults` was used deliberately: the faulted evaluation is scoped to establishing that a
**recovered** monitor remains operational, and P3 was not recovered.

Environment: Python 3.12, numpy 2.5.1, torch 2.13.0 (lockfile-pinned), CPU-only, Windows 11.
Analysis uses numpy and stdlib only.
