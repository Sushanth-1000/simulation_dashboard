# E18-R2 — Final Decision

**1 September 2026** · matched-window pooled calibration (version 3) · no new closed-loop runs
**Criterion frozen in `preregistration.md` before any quantile was computed.**

---

# VERDICT: PARTIAL-R2

**P1: 13/30 runs in band.** The frozen criterion required ≥ 24/30 for PASS. 13 falls in the
12–23 PARTIAL range.
**P3: 2/30 → INVALID.**

---

# AND: THE OBSTACLE IS NOW IDENTIFIED, AND IT IS NOT THE CALIBRATION

---

## 1 · Results

Thresholds (version 3, frozen before evaluation):

| policy | v3 matched | v1 whole-run | direction |
|---|--:|--:|---|
| P1 | **3.7024** | 3.7095 | lower, **as predicted** |
| P3 | **3.3953** | 3.4000 | lower, **as predicted** |
| P2 | 6.0000 | 5.9024 | higher |

Prediction 3 in `preregistration.md` §10 — that matched-window calibration would yield a *lower*
quantile, because false alarms were concentrated early in the run — is **confirmed** for both P1 and
P3.

Held-out per-run false-alarm behaviour, three calibration schemes:

| policy | v1 whole-run pooled | v2 run-local | **v3 matched pooled** |
|---|:--:|:--:|:--:|
| **P1 runs in band /30** | 4 | 3 | **13** |
| P1 median run FAR | 0.00 % | 0.00 % | **3.00 %** |
| P1 IQR | 1.00 % | 0.00 % | [1.50 %, 5.38 %] |
| **P3 runs in band /30** | 5 | 9 | **2** |
| P3 median run FAR | 0.50 % | 0.50 % | 1.00 % |
| P2 runs in band /30 | 0 | — | 0 |

**Matched-window calibration is the best of the three for P1** — a threefold improvement over both
alternatives, and the median run now alarms at 3.00 % against a 5 % nominal rather than at 0.00 %.
**It is the worst of the three for P3.**

## 2 · Why 13/30 and not 24/30 — the decisive diagnostic

**An ideal monitor with independent ticks at a 5 % rate would put 29.2 of 30 runs in band.** The
criterion is achievable in principle. It is not being missed because 24/30 is unreasonable.

| policy | per-run FAR SD observed | binomial expectation (n = 200) | overdispersion | implied effective ticks | alarm lag-1 autocorrelation |
|---|--:|--:|--:|--:|--:|
| **P1** | 6.98 % | 1.66 % | **4.2×** | **11** of 200 | **+0.359** |
| **P3** | 18.85 % | 2.04 % | **9.2×** | **2** of 200 | ≈ 0 |

**P1 and P3 fail for different reasons, and neither is a calibration problem.**

**P1 — within-run alarm clustering.** The alarm indicator has lag-1 autocorrelation **+0.359**:
alarms arrive in bursts, not independently. A 200-tick window therefore carries the statistical
information of about **11** independent observations. No threshold placed anywhere can make 11
effective samples produce a run-level rate concentrated inside a factor-of-four band.

**P3 — between-run baseline variation.** Alarm autocorrelation is ≈ 0, so P3's alarms are *not*
clustered in time. Its overdispersion is **9.2×** with an effective sample size of **2**, which means
essentially all its variance is between runs rather than within them. This is the same per-run
baseline offset measured in the E18 audit (corr = +0.909 between run mean and run FAR), and a pooled
threshold cannot correct it no matter which window supplies the sample.

**This is why R1 and R2 failed in opposite directions.** R1's run-local thresholds addressed P3's
mechanism (offset) and were defeated by estimation noise. R2's matched pooled threshold addressed the
window defect and helped P1, whose mechanism is clustering, while making P3 worse by removing the
per-run adaptation R1 had provided.

## 3 · What this establishes

# The current OD-8 formulation cannot deliver per-run-stable false-alarm behaviour at eps = 0.05 on 200-tick evaluation windows, for any tested policy.

Three calibration schemes have now been tried — pooled whole-run, run-local windowed, pooled
matched-window. The best result for any policy is **13/30**. The limitation is a property of the
**score process** — its temporal clustering and its between-run baseline variation — not of the
threshold, the window, or the estimator.

This is a **negative result about the monitor**, and it is precisely characterised rather than
merely asserted.

## 4 · P2

Untouched, as required across R1 and R2. Under v3 it is 0/30 with 25 of 30 runs raising no alarm at
all, alongside a pooled rate of 8.37 % — the same bimodal signature, unchanged. Its INVALID status
under fixed-quantile calibration stands and is not revisited.

## 5 · Gate to E19

# DO NOT PROCEED

No policy has defensible run-level false-alarm behaviour. The best available monitor (P1 under v3)
holds 13 of 30 runs in a factor-of-four band around its nominal rate, against 29.2/30 for an ideal
monitor.

E19 measures whether a predicted monitor *location* yields better operational detection. That
measurement requires an instrument whose false-alarm behaviour is stable enough that a detection
difference between locations is attributable to the location. **At 4.2× overdispersion it is not.**

## 6 · Minimum required repair — and why it is no longer a calibration change

The two mechanisms in §2 point to two specific, testable repairs. **Neither is a threshold or window
adjustment, so neither belongs in the E18 series.**

**Repair A — event-level alarm rule (addresses P1's clustering).** Replace the per-tick alarm with a
persistence rule: an alarm is raised only when the score exceeds the threshold for `k` consecutive
ticks, or `m` of the last `n`. This directly targets the +0.359 clustering and is standard practice
for exactly this reason. `k` must be pre-registered from the autocorrelation structure, **not
searched against the resulting false-alarm rate.**

**Repair B — longer evaluation window (addresses the sample-size floor).** At 11 effective ticks per
200, matching an independent 200-tick monitor would need roughly **3,600 ticks** per run. This is
cheap in simulation and would settle whether P1's shortfall is purely a precision problem.

**Repair C — per-run adaptation with an adequate sample (addresses P3's offset).** R1's run-local
approach was correct in mechanism and defeated by using only 200 prefix ticks. Combined with Repair
B's longer runs, a run-local threshold from ~1,800 prefix ticks would have roughly the sample size
that made the pooled estimate stable.

**Recommended order:** B first, because it is a pure compute change with no new rule to pre-register,
and it discriminates between "not enough samples" and "wrong monitor" for both policies at once. If
longer windows alone recover P1, the finding is a precision limit. If they do not, the finding is
that the OD-8 score is unsuitable as a per-tick operational monitor and the contribution reframes
around that.

## 7 · If no repair succeeds

The defensible contribution becomes the demonstrated limitation itself:

> A conformal non-conformity score that separates faulted from clean runs at high AUC can
> nonetheless fail to support a per-run-stable operational monitor, because its alarm process is
> temporally clustered and its baseline varies between runs. Statistical discriminability, calibration
> validity and operational stability are three distinct properties, and this system has the first
> without the third.

That is a real and publishable methodological result, and it is consistent with everything else this
project has measured — including that `D_L1` correlates **negatively** with operational detection.
