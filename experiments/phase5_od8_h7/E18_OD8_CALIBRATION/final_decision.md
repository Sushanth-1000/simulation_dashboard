# E18 — Final Decision

**1 September 2026** · calibration 36,000 clean ticks × 2 disjoint sets · evaluation 1,260 faulted runs
**Thresholds frozen before evaluation and never revised.** Version 1 in `frozen_thresholds.md`.

---

# VERDICT: PARTIAL

**OD-8 provides operational monitoring under specified policy constraints. P1 only.**

---

## 1 · Quantitative basis for the decision

| policy | pooled FAR | per-run FAR median [IQR] | runs in band | drift/SD | classification |
|---|--:|---|:--:|--:|---|
| **P1** | 5.47 % | 4.88 % [3.25 %, 7.25 %] | **21/30** | 0.09 | **VALID** |
| **P3** | 8.16 % | 1.00 % [0.75 %, 12.56 %] | **4/30** | 0.03 | **CONDITIONAL** |
| **P2** | 4.67 % | 0.00 % [0.00 %, 0.00 %] | **0/30** | **1.28** | **INVALID** |

Not PASS, because two of three policies fail at the run level.
Not FAIL, because P1 is genuinely calibrated and detects four of six faults.
Not INVALID, because the measurement chain is sound and integrity checks pass.

## 2 · A correction to our own earlier reading

An earlier pass on this experiment reported **P1 and P3 valid** on the strength of pooled false-alarm
rates of 5.47 % and 8.16 %. **That reading was wrong.**

Changing the unit of analysis from the tick to the run — the unit at which an operational monitor is
actually experienced, and the unit this project has repeatedly insisted on elsewhere — shows P3 has
only **4 of 30** runs inside the target band, with a bimodal distribution (median 1.00 %, upper
quartile 12.56 %). The pooled figure averaged across two behaviours.

This is the failure mode §10 of the brief names explicitly: *do not claim "calibrated" merely because
one aggregate number looks reasonable.* It is recorded here rather than silently corrected, and the
E19 gate narrows from two policies to one as a result.

## 3 · What E18 established

**OD-8's failure was calibration-set provenance, not threshold value.** A *global* recalibration
reproduces the original defect exactly — 0.00 % clean false alarms on P1 and P3, 11.06 % on P2. The
diagnosis is therefore causal, not merely consistent.

**A working monitor now exists on P1** where none did before. A 0.25 m position bias — routine GNSS
multipath — is caught on every seed, against a legacy configuration in which no fault at any tested
severity could make the gate fire.

**Two faults are undetectable by this gate at any severity**, on both P1 and P3: `speed_stuck` and
`imu_dropout`. That is a property of the conformal score, not of the calibration.

**`D_s` does not predict operational detection, and at L1 the association is negative** — Spearman
ρ = −0.480, p = 0.0088 across 28 cells. 17 of 28 cells disagree between `D_L6 ≥ 0.9` and
detection ≥ 0.9.

**Fault-induced alarm suppression replicates** — 11 of 28 cells on valid policies, all p < 0.05,
with `imu_dropout` on P1 making the monitor **55× less likely to alarm than clean operation**.

## 4 · P2 classification

# P2: INVALID

Within-run drift of 1.18 score units, **drift/SD = 1.28**, upward in **30 of 30 runs**
(Wilcoxon p = 1.8 × 10⁻⁶). **0 of 30** runs achieve a per-run false-alarm rate in the target band.

A fixed conformal quantile cannot serve a non-stationary score. This is a limitation of the current
**OD-8 formulation**, not a defect of the policy, and P2 remains in the analysis as the evidence for
that limitation. It is not deleted and not excluded for convenience.

## 5 · Minimum repair experiment, if P3 is wanted back

**E18-R1 — windowed or adaptive calibration.** The P3 bimodality suggests the score has two operating
regimes within a run rather than one. The minimum experiment:

1. Calibrate on a **sliding window** rather than the whole run, at a window length fixed in advance.
2. Re-measure per-run FAR on the same held-out clean set. Success criterion, pre-registered:
   **≥ 24 of 30 runs in band** (matching P1's 21/30 with margin).
3. If it succeeds for P3, test whether it also recovers P2.

This is a **new calibration version**, not an edit to version 1. The version-1 thresholds stay
frozen and on record regardless of outcome.

## 6 · Gate to E19

**PROCEED — on P1 only, with the single-policy restriction pre-registered as a first-class
limitation.**

All five §23 gate conditions are met on P1: a valid monitor exists, calibration is frozen, held-out
behaviour is defensible, integrity checks pass, and the monitor can be compared fairly across
candidate locations.

**The honest caveat:** E19 on one policy cannot show that a monitor-placement result generalises.
Policy identity is perfectly confounded with everything else. That is the same confound that killed
the H-regime claim, and E19 must pre-register that a positive result will be reported as
*policy-specific* until replicated.

**A defensible alternative** is to run E18-R1 first and enter E19 with two policies. That is the
stronger scientific path and costs one additional calibration experiment. **Recommended**, but the
choice is the project owner's.

## 7 · Warning carried into E19

E18 supplies H7's dependent variable and a specific warning about its independent variable.
`D_L1` is **negatively** associated with operational detection (ρ = −0.480, p = 0.0088).

A monitor-placement prediction derived from `D_s` alone is therefore likely to be **actively wrong**,
not merely uninformative. **The prediction must still be pre-registered from `D_s` as planned** — a
falsified pre-registered prediction is a real result, and E18 has already told us where to expect the
falsification. Changing the predictor now, before testing it, would be fitting the hypothesis to the
data.

## 8 · Open items

1. **Per-channel integrity statistic** — the current check compares mean estimated position and is
   blind to zero-mean dispersion faults on other channels. Fifth defect of this class in the project.
2. **Explain P2's drift** — measured, not explained.
3. **Explain alarm suppression** — why do some faults push the score away from the threshold?
4. **`speed_stuck` and `imu_dropout` undetectable** — whether another stage detects them is E19's
   question, and is now the strongest motivation for running it.
5. **E18-R1** if P3 is to be recovered.
