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

# E17 — 30-Seed Sweep Results

**Run** 31 Aug – 1 Sep 2026 · 90 profiles · 2,160 closed-loop runs of 400 ticks · 12,708 s · **0 failures**
**Raw** `results/E17_30SEED/raw/` · **Analysis** `results/E17_30SEED/statistics/analysis.json`
**Pre-registration** `results/E17_30SEED/manifests/PREREGISTRATION.md` — written and committed to disk
**before** the sweep was launched.

---

## 1 · Configuration actually run

| | Planned in `ASTRA_RESEARCH_FREEZE.md` | **Run** | Why |
|---|---|---|---|
| faults | 13 | **6** | only 6 are built in `benchmarks/fault_study.py`; the 13-fault registry is a plan. Building the other 7 means adding fault definitions, which the freeze forbids |
| severities | 3 | **1** | same reason |
| seeds | 30 | **30** | — |
| policies | — | **3** | P1 `synthetic`, P2 `long`, P3 `jerkscaled` |

**This is a deviation from the prompt and is reported, not resolved silently.** The claim this sweep
can support is correspondingly narrower than a 13×3 sweep would support.

Seeds: `20260731 + i`, i = 0…29. Unit of analysis is **the seed**, n = 30 per cell. Ticks are
autocorrelated within a run and were never treated as independent.

## 2 · Headline

**The position-fault result reproduces exactly, on every seed, on every policy.**

| | `position_bias` | `position_drift` |
|---|---|---|
| `D_L1` | **1.000** on all 90 runs | 0.970 [0.966, 0.974] |
| `D_L2a` | **0.500** on all 90 runs | **0.500** on all 90 runs |
| every downstream stage | 0.500 | 0.500 |
| `A(f)` | **L2a, 30/30 seeds, all 3 policies** | **L2a, 30/30 seeds, all 3 policies** |
| unique absorption | **30/30** | **30/30** |
| effect `D_L1 − D_L2a` | 0.500 (zero variance) | 0.470 [0.467, 0.472] |
| Holm-adjusted *p* | 2.8 × 10⁻⁷ | 9.1 × 10⁻⁶ |

The BCa intervals for `position_bias` are **degenerate — a point, not an interval — because all 30
seeds returned the identical value.** That is reported as a point rather than given a fabricated
width.

**All 18 pre-registered falsification checks came back negative.** (3 criteria × 2 primary faults ×
3 policies.)

## 3 · Full stage profiles

See `results/E17_30SEED/tables/tableA_stage_profiles.md` and
`results/E17_30SEED/plots/fig1_stage_profile_P{1,2,3}.svg`.

Median across 30 seeds, BCa 95% CI. Policy P3 shown; P1 and P2 in the table file.

| fault | L1 | L2a | L2b | L3 | L6 | L7 | L8 |
|---|--:|--:|--:|--:|--:|--:|--:|
| imu_dropout | 0.998 | 0.803 | 0.634 | 0.803 | 0.709 | 0.500 | 0.988 |
| **position_bias** | **1.000** | **0.500** | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |
| **position_drift** | **0.971** | **0.500** | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |
| speed_stuck | 0.988 | 0.559 | 0.509 | 0.558 | **0.630** | 0.500 | 0.500 |
| speed_bias | 1.000 | 0.513 | 0.621 | 0.508 | **0.963** | 0.500 | 0.500 |
| lateral_noise | 1.000 | 0.980 | 0.901 | 0.980 | 0.988 | 0.765 | 0.845 |

## 4 · Three findings that are not the headline

### 4.1 Statistical significance is not absorption — `lateral_noise`

`lateral_noise` rejects at *p* = 1.8 × 10⁻⁶ on all three policies. **The effect is 0.019.**
`D` goes 0.999 → 0.979 and never falls below 0.60 at any stage.

With n = 30 and a near-deterministic simulator, the signed-rank test detects differences far too
small to mean anything. **Reporting "L1 vs L2a significant for lateral_noise" would be true and
actively misleading.** Every significance claim in this study is paired with its effect size for
this reason. `lateral_noise` is **PERSISTENT — not absorbed at any stage.**

### 4.2 The conformal gate recovers what the estimator absorbs — and nothing acts on it

`speed_bias`, P3: `L1 1.000 → L2a 0.513 → L2b 0.621 → L3 0.508 → ` **`L6 0.963`** ` → L7 0.500 → L8 0.500`.
Same shape on P2 (**L6 0.994**) and weakly on P1 (L6 0.629).

The statistical gate **re-detects, at near-perfect separation, a fault the estimator drove to
chance.** The information was evidently not gone — it was absent from the estimator's output and
recoverable from the conformal statistic.

Then `D_L7 = 0.500` and `D_L8 = 0.500`. **~~The recovery does not propagate.~~ **WITHDRAWN** — there was no detection to propagate; see [E17_L6_CORRECTION.md](E17_L6_CORRECTION.md).** L6 separates the faulted
run from the clean one almost perfectly, and the deterministic gate and fail-safe posture are at
chance. This is a **detection-without-response gap**, and it is a finding about ASTRA's own wiring
rather than about fault propagation. It should be reported as such, not buried.

### 4.3 "100 % modal agreement" overstates stability — `A(f)` is often not well-posed

| policy · fault | modal `A(f)` | modal % | **unique / 30** |
|---|:--:|--:|--:|
| P1 · speed_bias | L2a | **100 %** | **0 / 30** |
| P3 · speed_bias | L2a | **100 %** | **0 / 30** |
| P3 · speed_stuck | L2a | **100 %** | 8 / 30 |
| P1 · imu_dropout | L7 | 60 % | **0 / 30** |
| P3 · imu_dropout | L2b | 37 % | **0 / 30** |
| P2 · speed_stuck | L2b | 57 % | 4 / 30 |
| P2 · speed_bias | L2a | 40 % | 7 / 30 |

`speed_bias` on P1 and P3 shows **100 % agreement on the modal absorption stage and zero seeds with a
well-posed absorption point.** Every seed crosses the 0.60 threshold more than once, because of the
L6 recovery in §4.2.

**A table reporting only the modal stage would have claimed perfect stability for a quantity that is
undefined in all 30 seeds.** The `threshold_crossings` counter was added before the sweep for exactly
this reason. Only the two position faults have `A(f)` well-posed on every seed.

## 5 · Fault classification

| fault | class | `A(f)` | reproduces across policies? |
|---|---|:--:|---|
| **position_bias** | **ABSORBED** | **L2a** | **yes — 90/90 runs identical** |
| **position_drift** | **ABSORBED** | **L2a** | **yes — 90/90 runs** |
| speed_stuck | absorbed then partly recovered at L6 | not well-posed | P1/P3 yes; P2 unstable |
| speed_bias | absorbed then **strongly** recovered at L6 | **not well-posed (0/30 unique)** | P1/P3 yes; P2 unstable |
| imu_dropout | **NON-MONOTONIC** | **none — 0/30 unique on P1, P3** | no — modal stage differs by policy |
| lateral_noise | **PERSISTENT** | **none** | yes — never absorbed on any policy |

**Two of six faults support the absorption claim. Four do not, in four different ways.** That
heterogeneity is a result, not noise, and is not being averaged away.

## 6 · Limitations

One plant model · one severity per fault · 6 of 13 planned faults · three policies is not a sample of
policies · `[M-syn]`, and **30 seeds does not upgrade this to `[M-ext]` — `[M-ext]` remains 0 of 30**
· seed-reproducibility is not external validity · stage statistics are one defensible choice among
several and a different `T_s` could move `D_s` · the L6 recovery in §4.2 is measured, but *why* the
conformal statistic retains what the estimator does not is not established here.

## 7 · Companion documents

`E17_STATISTICAL_ANALYSIS.md` · `E17_REGIME_ANALYSIS.md` · `E17_FINAL_DECISION.md`
