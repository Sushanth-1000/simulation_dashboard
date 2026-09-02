> # ⚠ SUPERSEDED IN PART — 1 September 2026
> **The two position-fault rows in this document are invalid.** `D_L2a = 0.500` for
> `position_bias` and `position_drift` is 0.5 **by construction**: the redundant sensing path
> (ADR-0033) regenerates the position channel from ground truth, so the injected fault never
> reached the pipeline. C1 is **NOT ESTABLISHED**.
> See [E17_INVALIDATION.md](E17_INVALIDATION.md). The speed, lateral and dropout results are
> unaffected and stand.
>
> **The L6 "detection-without-response gap" claim is also withdrawn.** L6's score shifts by 0.016
> against a firing threshold 2.0 away, and the gate returns PASS on every tick, faulted or clean —
> it never made a detection to ignore. Root cause is OD-8, not wiring.
> See [E17_L6_CORRECTION.md](E17_L6_CORRECTION.md).

# E17 — Statistical Analysis

**Data** 90 profiles × 6 faults = 540 records · n = 30 seeds per (policy, fault) cell
**Code** `benchmarks/e17_stats.py` (tests), `benchmarks/e17_analyse.py` (application)
**Everything below was specified in `results/E17_30SEED/manifests/PREREGISTRATION.md` before the sweep ran.**

---

## 1 · Unit of analysis

**The seed.** One `(policy, seed, fault)` triple contributes exactly one `D_s` per stage. Ticks
inside a run are autocorrelated and are never treated as independent samples — a constraint carried
from the freeze and honoured throughout. n = 30 per cell.

## 2 · Why the tests are hand-implemented

`scipy` is not in the pinned environment. The lockfile (`numpy` 2.5.1, `torch` 2.13.0) is what the
runtime measurements were taken against, and mutating it for the convenience of the analysis would
put every prior latency and gate measurement in question. Wilcoxon signed-rank, Holm–Bonferroni, BCa
bootstrap and Spearman are short enough to write directly against `numpy` + `statistics.NormalDist`.

Validated against known cases before use: shifted data *p* ≈ 2 × 10⁻⁶; null data *p* = 0.38;
degenerate input reports as degenerate; Holm output monotone; Spearman ρ = 0.95 on a
known-correlated pair.

## 3 · Primary test

**Wilcoxon signed-rank**, two-sided, paired by seed, `D_L1` against `D_L2a`. Normal approximation
with tie correction and continuity correction — n = 30 is well past where the exact distribution
matters. Zero differences dropped (Wilcoxon's own handling) with the reduced n reported; with a
metric that saturates at 0.500 these are common and silently retaining them would deflate the test.

**Holm–Bonferroni** across the six faults within each policy, α = 0.05, with monotonicity enforced.

**Effect size**: median paired difference with a **BCa bootstrap 95 % CI**, B = 10,000, seed
20260731, jackknife acceleration.

**Primary stage L2a and primary faults `position_bias` / `position_drift` were named in advance**,
because C1 predicts absorption at the estimator. They were not selected after inspecting results.

## 4 · Primary result

| policy | fault | n | W | z | *p* raw | *p* Holm | reject | effect `D_L1 − D_L2a` |
|---|---|--:|--:|--:|--:|--:|:--:|---|
| P1 | **position_bias** | 30 | 0 | −5.47 | 4.6e−08 | **2.8e−07** | **yes** | **0.500** (degenerate) |
| P1 | **position_drift** | 30 | 0 | −4.77 | 1.8e−06 | 9.1e−06 | **yes** | 0.470 [0.467, 0.472] |
| P2 | **position_bias** | 30 | 0 | −5.47 | 4.6e−08 | **2.8e−07** | **yes** | **0.500** (degenerate) |
| P2 | **position_drift** | 30 | 0 | −4.77 | 1.8e−06 | 9.1e−06 | **yes** | 0.470 [0.466, 0.471] |
| P3 | **position_bias** | 30 | 0 | −5.47 | 4.6e−08 | **2.8e−07** | **yes** | **0.500** (degenerate) |
| P3 | **position_drift** | 30 | 0 | −4.77 | 1.8e−06 | 9.1e−06 | **yes** | 0.471 [0.469, 0.474] |

`W = 0` means **every one of the 30 seeds moved in the same direction**, on all three policies.

**On the degenerate intervals:** `position_bias` returned `D_L1 = 1.000` and `D_L2a = 0.500` on all
90 runs. The paired difference has zero variance, so the bootstrap CI is a point. This is reported as
`0.500` rather than dressed with an interval the data does not contain. `bca_median_ci` detects this
case explicitly and flags `degenerate: true`.

**Caveat on the z-statistic:** with zero variance the normal approximation is being applied at the
boundary of its validity. The *p*-values are reported for completeness, but **the evidence here is
carried by "90 of 90 runs identical", which needs no test at all.** A reader should weight the
reproducibility, not the *p*.

## 5 · The significance/magnitude split — mandatory reading

Every one of the 18 (policy × fault) comparisons rejected at Holm-corrected α = 0.05. **That is not
the finding it appears to be.**

| policy | fault | *p* Holm | effect | absorbed? |
|---|---|--:|--:|:--:|
| P1 | position_bias | 2.8e−07 | **0.500** | **yes** |
| P1 | speed_bias | 9.1e−06 | 0.484 | at L2a, then recovered at L6 |
| P1 | imu_dropout | 9.1e−06 | 0.138 | **no** — non-monotonic |
| P1 | **lateral_noise** | **1.8e−06** | **0.019** | **no** — 0.999 → 0.979, never below 0.60 |
| P2 | speed_stuck | 9.0e−03 | 0.176 | unstable across seeds |

`lateral_noise` is significant at *p* = 1.8 × 10⁻⁶ with an effect of **0.019**. Both stages sit far
above the 0.60 absorption threshold. With n = 30 and a near-deterministic simulator, the signed-rank
test resolves differences two orders of magnitude smaller than anything that matters.

**Any table in the paper reporting these *p*-values without the adjacent effect size would be
technically accurate and substantively false.** The effect column is not optional.

## 6 · Absorption-point stability

`A(f)` is only meaningful for a `D_s` curve that crosses the 0.60 threshold once. `threshold_crossings`
and `unique_absorption` were added before the sweep so a non-monotonic curve reports "no well-posed
`A(f)`" instead of silently returning its first crossing.

| policy · fault | modal `A(f)` | modal % | unique / 30 | reading |
|---|:--:|--:|--:|---|
| all · position_bias | L2a | 100 % | **30/30** | **well-posed and stable** |
| all · position_drift | L2a | 100 % | **30/30** | **well-posed and stable** |
| P1 · speed_bias | L2a | 100 % | **0/30** | **modal agreement is spurious** |
| P3 · speed_bias | L2a | 100 % | **0/30** | **modal agreement is spurious** |
| P3 · speed_stuck | L2a | 100 % | 8/30 | mostly not well-posed |
| P1 · imu_dropout | L7 | 60 % | 0/30 | no `A(f)` |
| P3 · imu_dropout | L2b | 37 % | 0/30 | no `A(f)` |
| P2 · speed_stuck | L2b | 57 % | 4/30 | unstable |
| P2 · speed_bias | L2a | 40 % | 7/30 | unstable |

**Four cells show 100 % modal agreement on a quantity that is undefined in most or all of their
seeds.** Reporting the modal column alone would have claimed perfect stability for `speed_bias` on
two policies where *not one seed* has a well-posed absorption point.

## 7 · Pre-registered falsification checks

Three criteria × two primary faults × three policies = 18 checks. **All 18 negative.**

| criterion | worst observed | threshold | fired? |
|---|---|---|:--:|
| F1 median `D_L2a` > 0.60 | 0.500 | 0.60 | no |
| F2 effect CI crosses zero | [0.4664, 0.4715] | contains 0 | no |
| F3 absorption stage varies across seeds | modal fraction 1.00 | < 1.00 | no |

C1 had three specified ways to die. None fired.

## 8 · Secondary hypothesis

H-regime was pre-registered as exploratory. The pooled result was significant and in the predicted
direction; a stated robustness check showed it to be a Simpson's paradox and it is **withdrawn**. See
`E17_REGIME_ANALYSIS.md`.

## 9 · Multiplicity ledger

- **Pre-registered and corrected:** 18 Wilcoxon tests (Holm within policy), 2 pooled Spearman.
- **Stated robustness, not used to claim an effect:** 6 within-policy Spearman, 2 pooled Spearman
  against mean speed. These *withdrew* a result rather than establishing one.
- **Not performed:** no stage was selected after seeing significance; no seed was dropped; no
  threshold was tuned; no fault was excluded after inspection. The two faults excluded from the
  `A(f)` test (`imu_dropout`, `lateral_noise`) were excluded in the pre-registration, on the stated
  ground that `A(f)` is ill-posed for non-monotonic and persistent curves, and both are reported in
  full.

## 10 · Statistical limitations

n = 30 seeds under one plant model — this bounds sampling error, not model error. Three policies is
not a sample of policies and no inference generalises across policy space. The near-determinism of
the simulator makes *p*-values easy to obtain and largely uninformative; effect sizes and the
90-of-90 reproducibility carry the argument. The normal approximation is strained at zero variance
(§4). `[M-syn]` throughout — **`[M-ext]` remains 0 of 30.**
