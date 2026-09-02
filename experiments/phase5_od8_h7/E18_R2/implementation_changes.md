# E18-R2 — Implementation Changes

## Source code (`src/astra/`)

**None.**

## New code

| file | purpose |
|---|---|
| `benchmarks/e18r2_calibrate.py` | pooled calibration on ticks 201–400, per-run held-out evaluation, verdict against the frozen criterion, manifests. |

## No new closed-loop runs

`calibration.json` and `clean_test.json` from E18 already contain all 400 ticks per run. R2 changes
only which ticks enter the quantile. **The score data is byte-identical to E18's**, so the difference
in outcome is attributable to the calibration window and to nothing else — not a re-run, a reseed, or
a changed code path. This is why R2 cost seconds rather than hours.

## Unchanged, deliberately

- E18 version 1 and E18-R1 version 2 thresholds — **not overwritten**. R2 adds version 3.
- eps, estimator, pooling, seeds, acceptance band.
- The fault catalogue and the E19 `D_s` predictor.
- P2 — computed for the record, not tuned for, not claimed.

## Reproduction

```
python -m benchmarks.e18r2_calibrate
```

Environment: Python 3.12, numpy 2.5.1, torch 2.13.0 (lockfile-pinned), CPU-only, Windows 11.
