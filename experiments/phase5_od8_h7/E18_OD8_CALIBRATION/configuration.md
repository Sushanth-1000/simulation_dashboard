# E18 — FROZEN CONFIGURATION

# ⛔ THRESHOLDS FROZEN — 1 September 2026

Computed from **clean calibration data only**. Frozen **before** any faulted run was evaluated.
**No change is permitted without opening a new experiment (E18-R1).**

---

## 1 · Frozen thresholds

Scheme selected by the pre-registered rule in `protocol.md` §F: **POLICY-CONDITIONAL**, because the
global scheme's clean false-alarm rate fell outside `[ε/2, 2ε]` for all three policies.

| policy | checkpoint | **frozen quantile** | headroom | calibration n |
|---|---|--:|--:|--:|
| **P1** | `var/policy/synthetic.pt` | **3.7095** | 0.0235 | 12,000 |
| **P2** | `var/policy/long.pt` | **5.9024** | 1.1217 | 12,000 |
| **P3** | `var/policy/jerkscaled.pt` | **3.4000** | 0.0170 | 12,000 |

- ε = **0.05** (pre-registered)
- Quantile estimator: finite-sample conformal, `ceil((n+1)(1−ε))`-th order statistic
- Context class: `URBAN_CLEAR` (99.75 % of ticks; `DEGRADED_SENSOR` on the first tick of each run)
- Calibration seeds: `20260901 + i`, i = 0…29 · 400 ticks · clean only
- Score: `non_conformity_score` from the STATISTICAL gate evidence tuple
- Score definition: `euclidean_departure_over_sqrt_fast_covariance_lateral_acceleration`

## 2 · Held-out clean false-alarm rate

Measured on the **CLEAN TEST** set (seeds `20261001 + i`), disjoint from calibration.

| policy | quantile | clean FAR | nominal | in band [2.5 %, 10 %] |
|---|--:|--:|--:|:--:|
| P1 | 3.7095 | **5.47 %** | 5.0 % | **yes** |
| P2 | 5.9024 | **4.68 %** | 5.0 % | **yes** |
| P3 | 3.4000 | **8.23 %** | 5.0 % | **yes** |

## 3 · Why the global scheme was rejected

| policy | global q = 5.6449 | clean FAR | in band? |
|---|--:|--:|:--:|
| P1 | headroom 1.9589 | **0.0000 %** | no — never fires |
| P2 | headroom 0.8642 | **11.06 %** | no — too high |
| P3 | headroom 2.2619 | **0.0000 %** | no — never fires |

**This reproduces OD-8 exactly.** A single threshold across policies gives a gate that cannot fire on
P1/P3 and over-fires on P2 — the same two-directional failure observed with the legacy corpus. It is
direct evidence that the original defect was a **calibration-set provenance** problem, not a
threshold-value problem, and that policy-conditional calibration is required rather than preferred.

## 4 · Exchangeability check

AUC between calibration and held-out clean-test scores. 0.5 = indistinguishable.

| policy | exchangeability AUC | verdict |
|---|--:|---|
| P1 | 0.5154 | exchangeable |
| P2 | 0.5372 | exchangeable |
| P3 | 0.5277 | exchangeable |

All well under the pre-registered 0.70 limit. **The recalibrated corpus is exchangeable with live
clean operation** — which the legacy corpus was not.

## 5 · Temporal drift — the criterion that failed

| policy | 1st-half mean | 2nd-half mean | drift / SD | within limit (≤ 1.0)? |
|---|--:|--:|--:|:--:|
| P1 | 3.6850 | 3.6870 | **0.09** | yes |
| P3 | 3.3831 | 3.3828 | **0.03** | yes |
| **P2** | **4.1902** | **5.3711** | **1.28** | **NO** |

**P2's score drifts upward within a run by more than its between-run spread.** A fixed quantile
cannot achieve stable coverage on a non-stationary score: P2's per-tick alarm rate is necessarily
higher late in a run than early, even though the pooled rate (4.68 %) lands in band.

This also explains an earlier observation retrospectively: P2 measured ≈ 5.15 over ticks 200–400 and
2.56–4.46 over ticks 0–200. That was drift, not a regime difference.

## 6 · Reproduction

```
python -m benchmarks.e18_calibrate      # collect clean calibration + clean test
python -m benchmarks.e18_analyse        # compute, test, select, freeze
```

Raw: `raw_results/{calibration,clean_test}.json` · Processed:
`processed_results/calibration_analysis.json`

Environment: Python 3.12, numpy 2.5.1, torch 2.13.0 (lockfile-pinned), CPU-only, Windows 11.
The analysis uses numpy + stdlib only; `scipy` is deliberately not installed in the measurement venv.

## 7 · Scope of the freeze

These thresholds apply to **E19 and E20**. They were derived without reference to any faulted run and
must not be revisited in light of detection results. If detection is poor, that is a finding about
the gate, not a reason to move the threshold.
