# E18 - FROZEN THRESHOLDS

# VERSION 1 - FROZEN 1 September 2026

Computed from clean calibration data only, before any faulted run was evaluated.
**No threshold tuning using test or fault results has occurred or is permitted.**
A change requires a new version below; the previous version is never overwritten.

---

## Version 1 (active)

| policy | checkpoint | **frozen threshold** | eps | calibration n | derived from |
|---|---|--:|--:|--:|---|
| **P1** | `var/policy/synthetic.pt` | **3.7095** | 0.05 | 12,000 | seeds 20260901-20260930, clean |
| **P2** | `var/policy/long.pt` | **5.9024** | 0.05 | 12,000 | seeds 20260901-20260930, clean |
| **P3** | `var/policy/jerkscaled.pt` | **3.4000** | 0.05 | 12,000 | seeds 20260901-20260930, clean |

- **Score:** `non_conformity_score` from the STATISTICAL gate evidence tuple
- **Score definition:** `euclidean_departure_over_sqrt_fast_covariance_lateral_acceleration`
- **Estimator:** finite-sample conformal order statistic, `ceil((n+1)(1-eps))`-th of the sorted
  calibration scores
- **Acceptance region:** `{score <= q}`
- **Context:** `URBAN_CLEAR` (99.75 % of ticks)
- **Scheme:** policy-conditional, selected by the rule pre-registered in `protocol.md` section F

## Provenance chain

```
clean calibration runs (seeds 20260901+, no fault possible in the collector)
        -> per-tick non-conformity scores, n = 12,000 per policy
        -> finite-sample conformal quantile at eps = 0.05
        -> FROZEN here
        -> only then: held-out clean evaluation (seeds 20261001+)
        -> only then: faulted evaluation (seeds 20260731+)
```

The calibration collector `benchmarks/e18_calibrate.py` has no fault-injection code path, so
contamination of the calibration set is prevented by construction rather than by discipline.

## Freeze audit

| requirement | evidence |
|---|---|
| Threshold derived without fault data | collector cannot inject; analyser loads no fault file |
| Frozen before faulted evaluation | `configuration.md` and this file written before `e18_evaluate` first ran |
| Hard-coded at point of use | `FROZEN_QUANTILE` in `benchmarks/e18_evaluate.py` |
| Not adjusted afterwards | no version 2 exists |

## Change log

*(empty - no threshold has been revised)*
