# E18 - Implementation Changes

## Source code (`src/astra/`)

**None.** No ASTRA layer, contract or gate was modified. E18 measures and recalibrates; it does not
change architecture.

## Harness / benchmarks

| file | change | why |
|---|---|---|
| `benchmarks/e18_calibrate.py` | **new** | collects clean L6 scores on three disjoint seed sets. Cannot inject a fault by construction -- the calibration quantile must never see fault data, and the safest guarantee is a collector incapable of producing one. |
| `benchmarks/e18_analyse.py` | **new** | computes both schemes, runs the exchangeability and drift checks, applies the pre-registered selection rule, emits the verdict. Loads no fault data at all. |
| `benchmarks/e18_evaluate.py` | **new** | evaluates all six faults at three severity levels against the **frozen** thresholds, which are hard-coded constants read from `configuration.md`. |

## Carried in from the E17 audit (already in the working tree)

| file | change |
|---|---|
| `training/closed_loop.py` | `RedundantSensing` gained `bias` (constant per-channel offset; the field previously supported only linear drift) and `also_faulted` (more than one lying channel). Backward compatible -- drift-only behaviour is bit-identical. This is the injection path the position faults now use. |
| `benchmarks/discriminability.py` | operating-regime covariates; L6 read from gate evidence; rolling-dispersion statistic for variance faults; threshold-crossing counter. |

## Quantile estimator

`conformal_q` in `e18_analyse.py` uses the finite-sample conformal order statistic
`ceil((n+1)(1-eps))` rather than a plain percentile. With n = 12,000 the difference is negligible; it
is used because it is the correct estimator, and the difference is not what should decide a
calibration.

## What was deliberately NOT changed

- The context classifier. Live ticks classify as `URBAN_CLEAR`; reclassifying them to
  `HIGHWAY_CLEAR` would have "fixed" the mismatch by changing L3 to solve an L6 problem, and was not
  pre-registered.
- Epsilon. Fixed at 0.05 before any result.
- The score definition.
- Fault definitions, and the severities of the four original faults at their `medium` level, which
  match E17 exactly so results stay comparable.
