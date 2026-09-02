# E18 - Calibration Data Definition

Defined **before** any test outcome was examined.

## Datasets

| set | seeds | runs | ticks | total samples | use |
|---|---|--:|--:|--:|---|
| **CALIBRATION** | `20260901 + i`, i = 0..29 | 30 per policy | 400 | 12,000 per policy | compute the threshold |
| **CLEAN TEST** | `20261001 + i`, i = 0..29 | 30 per policy | 400 | 12,000 per policy | measure false-alarm behaviour |
| **FAULT TEST** | `20260731 + i`, i = 0..29 | 30 per policy per cell | 400 | 1,260 runs | detection, after the freeze |

**Disjointness is verified programmatically** in `e18_calibrate.main`, which raises before any run if
the sets intersect. Calibration seeds are new to this project and have never been used elsewhere in
it. Fault-test seeds are the E17 set, retained deliberately so E18 detection results remain
comparable with E17 observability results.

## Scenario and environment

- Synthetic driving plant, `training/closed_loop.drive_closed_loop`
- Redundant sensing active (`RedundantSensing.build`, the ADR-0033 default) -- the same sensing path
  used in operation, which is the point: calibration under conditions that differ from operation is
  what produced OD-8
- No fault injected in either clean set
- 400 ticks per run, all ticks retained

## Sample selection

**All ticks of all clean runs are used.** No tick is excluded for being an outlier, and no burn-in
period is discarded.

This is a deliberate and consequential choice. Discarding a burn-in would improve the apparent
stationarity of P2 and would be indistinguishable, from the outside, from tuning. The cost is that
the first tick of every run classifies as `DEGRADED_SENSOR` rather than `URBAN_CLEAR` (30 of 12,000
samples per policy); this is recorded rather than removed.

## Temporal windows

- **Calibration:** whole run, ticks 0-399
- **Clean test:** whole run, ticks 0-399
- **Fault evaluation:** ticks 200-399 only, the post-injection window. Fault onset is tick 200, so
  pre-injection ticks would dilute detection with clean data

The asymmetry is intentional and is why per-run drift matters: a threshold calibrated over a whole
run is applied, during evaluation, only to that run's second half.

## Threshold procedure

Finite-sample conformal quantile at eps = 0.05 -- the `ceil((n+1)(1-eps))`-th order statistic of the
calibration scores. Two schemes were computed (global, policy-conditional) with the selection rule
fixed in advance.

## Contamination rules

1. No fault-test outcome may influence the threshold. Enforced structurally.
2. No held-out clean result may influence the threshold. The clean-test set is used only to *measure*
   false-alarm behaviour after the freeze.
3. No threshold may be revised after seeing detection results.

## Exclusion rules, fixed in advance

- A run with non-finite scores would be excluded and reported. **None occurred** -- `nonfinite = 0`
  across all six clean sets.
- A faulted run failing the delivered-signal integrity check is excluded from detection statistics
  and reported. **Nine occurred**, all P2 `lateral_noise`; on inspection these are false failures of
  a mis-specified check rather than failed injections -- see `integrity_checks.md`.
- No run is excluded for producing an inconvenient result.
