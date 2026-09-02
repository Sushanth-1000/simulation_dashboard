# E18 - Integrity Checks

The standing rule, carried from E17:

> A sweep result cannot be trusted unless the faulted arm is demonstrated to differ from the clean
> arm **at the delivered signal**.

## Checks run, and outcomes

| # | check | method | result |
|---|---|---|---|
| 1 | Seed sets disjoint | computed programmatically in `e18_calibrate.main`, raises before any run | **PASS** -- calibration(30), clean_test(30), fault_test(30), pairwise disjoint |
| 2 | Expected sample counts | 30 seeds x 400 ticks per policy per set | **PASS** -- n = 12,000 per policy per set, six sets |
| 3 | No NaN / Inf in scores | counted per policy per set | **PASS** -- `nonfinite = 0` in all six |
| 4 | Context distribution recorded, not assumed | per-tick capture | **PASS** -- 11,970 `URBAN_CLEAR` / 30 `DEGRADED_SENSOR` per policy per set |
| 5 | No calibration leakage | the collector cannot inject a fault; the analyser loads no fault file | **PASS** by construction |
| 6 | Fault reaches the estimator | per-run comparison of mean estimated lateral position, faulted vs clean | **PASS** -- 42/42 in the smoke test; recorded per record as `fault_reached_estimator` in the full sweep |
| 7 | Threshold frozen before fault evaluation | `configuration.md` written and thresholds hard-coded before `e18_evaluate` first ran | **PASS** |

## Why check 6 matters here specifically

The two position faults reach the estimator only through `RedundantSensing.offset`. Under the old
`FaultInjector` path they were silently erased by ground-truth regeneration, which invalidated 180
records in E17. Every E18 record carries `fault_reached_estimator`, so the failure cannot recur
undetected.

## Known gap

Check 6 verifies that the faulted and clean arms differ at the estimator. It does **not** verify that
the difference has the intended magnitude at every severity level. A severity mis-specification that
still produced some difference would pass. Recorded as a limitation rather than closed.
