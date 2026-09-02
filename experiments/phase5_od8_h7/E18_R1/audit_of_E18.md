# E18-R1 — Audit of the E18 Implementation

Performed **before** any R1 code was written, per section 4 of the brief.

---

## 1 · How calibration samples are constructed

`benchmarks/e18_calibrate.py` drives clean closed-loop runs and records, per tick, the
`non_conformity_score` from the STATISTICAL gate's evidence tuple. **The collector has no
fault-injection code path**, so calibration contamination is prevented structurally rather than by
discipline.

Three seed sets, disjointness asserted programmatically before any run:

| set | seeds | n per policy |
|---|---|--:|
| CALIBRATION | `20260901 + i`, i = 0..29 | 12,000 ticks |
| CLEAN TEST | `20261001 + i`, i = 0..29 | 12,000 ticks |
| FAULT TEST | `20260731 + i`, i = 0..29 | 30 runs per cell |

## 2 · How temporal windows are defined

**They are not.** E18 pools all 400 ticks of all 30 calibration runs into one sample of 12,000 and
computes a single quantile per policy. There is no windowing, no per-run structure, and no temporal
locality.

Evaluation, by contrast, uses **ticks 200–399 only** (the post-injection window). So E18 calibrates
over a whole run and evaluates over its second half. **This asymmetry is the seam R1 examines.**

## 3 · How thresholds are calculated

Finite-sample conformal order statistic, `ceil((n+1)(1-eps))`-th of the sorted calibration scores,
eps = 0.05, per policy. Frozen in `E18_OD8_CALIBRATION/frozen_thresholds.md` version 1 and hard-coded
as `FROZEN_QUANTILE` in `benchmarks/e18_evaluate.py`.

## 4 · Calibration / test leakage

**None found.** Verified along four paths:

- the calibration collector cannot inject a fault;
- `e18_analyse.py` loads no fault file;
- seed sets are disjoint and asserted at runtime;
- thresholds were written to disk before `e18_evaluate.py` first executed.

## 5 · How run-level FAR is calculated

In E18 Part 1 it **was not** — only pooled tick-level FAR was reported, and that produced a reading
(P1 + P3 valid) which the run-level analysis later overturned. Run-level FAR was added in
`benchmarks/e18_final.py` as `mean(score > q)` within each run, over that run's finite scores.

## 6 · Clean / faulted separation

Separate seed sets and separate collectors. Faulted runs additionally carry a per-record
`fault_reached_estimator` flag from the delivered-signal integrity rule.

## 7 · Seed handling

Deterministic and contiguous. The fault injector draws from an offset seed, so a clean run is
bit-identical to a faulted run outside the injection window.

## 8 · Policy handling

Three checkpoints, thresholds are policy-conditional. The selection between global and
policy-conditional was made by a rule fixed in advance.

## 9 · Freeze ordering

Verified: `configuration.md` and `frozen_thresholds.md` were written before the first
`e18_evaluate` run. No version 2 exists.

## 10 · Can P3 bimodality be traced to calibration-window behaviour?

**Yes. The mechanism is identified.**

| policy | per-run mean spread | threshold headroom | corr(run mean, run FAR) | between/within variance |
|---|--:|--:|--:|--:|
| P1 | 0.0132 | 0.0235 | +0.652 | **0.03** |
| **P3** | **0.0277** | **0.0170** | **+0.909** | **0.67** |
| P2 | 1.9550 | 1.1217 | +0.697 | 0.28 |

**Each P3 run has its own baseline score level, and the spread of those baselines (0.0277) is larger
than the gap between the pooled mean and the threshold (0.0170).** A run whose baseline sits ~0.01
high alarms on most ticks; one ~0.01 low never alarms. The correlation between a run's mean score and
its false-alarm rate is **+0.909** — the run's own baseline almost entirely determines its FAR.

P1 escapes this because its between-run variance is only 3 % of its within-run variance: its runs
share a baseline. P3's is 67 %.

**This is a between-run offset problem, not a within-run drift problem.** P3's drift/SD is 0.03 —
essentially zero. The two policies fail for opposite reasons: P2 drifts *within* runs; P3 differs
*between* runs.

## 11 · What this implies for the R1 design

A calibration pooled across runs cannot correct a per-run baseline offset — it estimates one number
for a quantity that varies by run. The scientifically indicated correction is **run-local
calibration**: estimate the threshold from each run's own early, fault-free ticks.

This is derived from the diagnostic above, which uses **E18 data only**. No R1 outcome exists yet.
