# E17 — Correction: the L6 "detection-without-response gap"

**1 September 2026.** Withdraws a claim made earlier the same day.

---

## 1 · The claim being withdrawn

> "The conformal gate recovers a signal the estimator absorbed, and nothing downstream acts on it.
> ASTRA detects this fault and does not respond to it."

Based on `D_L6 = 0.963` for `speed_bias` on P3 (0.994 on P2) against `D_L7 = D_L8 = 0.500`.

**The claim is wrong in a way that matters.**

## 2 · What the gate actually does

Policy P3, `speed_bias` **+3.0 m/s**, seed 20260731, 200 post-injection ticks:

| | clean | faulted |
|---|--:|--:|
| STATISTICAL verdict | PASS ×200 | **PASS ×200** |
| L6 non-conformity score | mean **3.3927** | mean **3.3771** |
| conformal quantile (firing threshold) | 5.375 / 5.430 | 5.375 / 5.430 |

Live scores sit near **3.39**. The threshold is **5.40**. **Headroom ≈ 2.0.** The faulted mean is
*lower* than the clean mean.

All three Core-B gates were confirmed wired and verdicting on every tick (3 verdicts × 300 ticks),
so this is **not** a wiring defect.

## 3 · Why `D_L6 = 0.963` was misleading

**AUC is scale-free.** It reports near-perfect separation for a **0.016** mean shift, because two
tight distributions barely overlap — not because the shift is large. The gate's decision threshold is
**2.0 away**, roughly **125×** the observed shift.

`D_L6 = 0.963` and "the gate would fire" are unrelated statements. Reading the first as the second is
the same significance-vs-magnitude error already flagged for `lateral_noise` (*p* = 1.8 × 10⁻⁶ at an
effect of 0.019) — **operating inside the study's own headline finding.**

## 4 · Root cause: OD-8, not wiring

This is the **conformal exchangeability violation already logged in the repository** as OD-8: live
non-conformity scores and the calibration corpus do not overlap, so the conformal quantile sits above
anything the running system produces. The STATISTICAL gate is **structurally incapable of vetoing**
under these conditions, faulted or not.

## 5 · Corrected statement

> **L6's non-conformity statistic separates the faulted run from the clean one at a magnitude roughly
> two orders below its own decision threshold, and that threshold is miscalibrated (OD-8) such that no
> live input can reach it.** The gate is not ignoring a detection; it never made one.

## 6 · Consequences

1. **`D_s` alone cannot support any claim about whether a monitor would act.** Every stage-wise `D`
   needs a companion measure of the shift relative to that stage's decision threshold. Added to the
   stage-wise CSV as `l6_threshold`, `l6_shift`, `l6_headroom`, `l6_shift_over_headroom`.
2. **Finding 3 in `E17_VALIDATION_REPORT.md` is downgraded** from VALIDATED to VALIDATED-as-restated.
3. **H7's premise shifts.** Monitor *placement* is not the binding constraint; monitor *calibration*
   is. Placing a monitor at L6 buys nothing while its quantile is unreachable. **This makes OD-8 a
   blocking prerequisite for H7, not a parallel workstream.**
4. The `speed_bias` L6 "recovery" (0.629–0.994) is still a real property of the *statistic*. It is
   not evidence of a detection.

---

## 7 · Measured headroom across all valid faults (n = 10 seeds)

`shift` = |mean faulted score − mean clean score| · `headroom` = conformal quantile − mean clean
score · `ratio` = shift / headroom. **The gate needs ratio ≥ 1.0 to fire.**

| policy | fault | clean score | shift | threshold | headroom | ratio | fires? |
|---|---|--:|--:|--:|--:|--:|:--:|
| **P1** | imu_dropout | 3.6872 | 0.0069 | 5.4129 | 1.7258 | **0.0040** | no |
| **P1** | speed_stuck | 3.6872 | 0.0005 | 5.4264 | 1.7393 | **0.0003** | no |
| **P1** | speed_bias | 3.6872 | 0.0033 | 5.4275 | 1.7404 | **0.0019** | no |
| **P1** | lateral_noise | 3.6872 | 0.1425 | 5.4097 | 1.7225 | **0.0828** | no |
| **P2** | imu_dropout | **5.1488** | 0.4804 | 5.4093 | **0.2605** | **1.5732** | **yes** |
| **P2** | speed_stuck | **5.1488** | 0.4733 | 5.4115 | **0.2627** | **1.3716** | **yes** |
| **P2** | speed_bias | **5.1488** | 0.7826 | 5.4145 | **0.2657** | **1.1724** | **yes** |
| **P2** | lateral_noise | **5.1488** | 0.6947 | 5.4142 | **0.2654** | **1.3701** | **yes** |
| **P3** | imu_dropout | 3.3833 | 0.0052 | 5.4138 | 2.0306 | **0.0026** | no |
| **P3** | speed_stuck | 3.3833 | 0.0010 | 5.4268 | 2.0435 | **0.0005** | no |
| **P3** | speed_bias | 3.3833 | 0.0076 | 5.4274 | 2.0441 | **0.0037** | no |
| **P3** | lateral_noise | 3.3833 | 0.2352 | 5.4103 | 2.0270 | **0.1161** | no |

## 8 · OD-8 is miscalibrated in **both** directions

The threshold is essentially constant (**5.41–5.43**) across every policy and fault. What moves is the
**baseline**.

**P1 and P3 — guaranteed false negatives.** Clean scores sit at 3.38–3.69, leaving 1.7–2.0 of
headroom. Fault-induced shifts are **0.0005–0.24**, i.e. **0.03 % to 12 %** of what would be needed.
No fault in this study can make this gate fire on these policies. The strongest case,
`lateral_noise` on P3, still needs **8.6×** its observed shift.

**P2 — false positives.** Clean score is **5.1488** against a threshold of 5.41: headroom **0.26**.
P2's *nominal* operation is already nearly non-conforming. Every fault crosses, but so would almost
any perturbation — the ratio exceeds 1.0 for all four faults with shifts of 0.47–0.78.

**This also explains P2's 87 % veto rate**, which the regime analysis treated as a policy property
and used as a covariate. It is not a property of the policy's driving. **It is L6 firing on P2's
baseline.** The gate is not detecting faults on P2; it is reporting that P2 is out of distribution
relative to the calibration corpus, on every tick, fault or no fault.

**Neither regime is detection.** The gate is uninformative where it is silent (P1, P3) and
uninformative where it fires (P2).

## 9 · Consequence for the regime analysis

`E17_REGIME_ANALYSIS.md` withdrew H-regime as a Simpson's paradox. That withdrawal stands, and this
strengthens the reason: **veto rate was never an independent operating-regime covariate.** It is
largely a readout of L6's calibration error against each policy's baseline. Stratifying on it
stratifies on conformal miscalibration, not on how the vehicle is driving.

**OD-8 is therefore a blocking prerequisite for H7**, not a parallel workstream. Monitor placement
cannot be studied while the monitor's threshold is unreachable on two policies and permanently
tripped on the third.
