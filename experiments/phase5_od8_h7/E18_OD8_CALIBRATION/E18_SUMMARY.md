# E18 — Summary

**1 September 2026** · 72,000 clean calibration/test ticks · 1,260 faulted runs · thresholds frozen
before evaluation and never revised.

---

# DECISION: PARTIAL

**OD-8 provides operational monitoring under specified policy constraints — P1 only.**

---

## The ten questions

### 1 · Is OD-8 calibrated?

**Partially.** The *procedure* is now defensible — calibration data is exchangeable with live clean
operation, thresholds were frozen before any fault was seen, and no test result influenced them. The
*result* holds for one policy of three.

### 2 · Under which policies?

| policy | pooled FAR | per-run FAR median [IQR] | runs in band | drift/SD | classification |
|---|--:|---|:--:|--:|---|
| **P1** | 5.47 % | 4.88 % [3.25 %, 7.25 %] | **21/30** | 0.09 | **VALID** |
| **P3** | 8.16 % | **1.00 %** [0.75 %, 12.56 %] | **4/30** | 0.03 | **CONDITIONAL — not usable as-is** |
| **P2** | 4.67 % | **0.00 %** [0.00 %, 0.00 %] | **0/30** | **1.28** | **INVALID** |

**The pooled figure is misleading for P2 and P3 and this is the single most important methodological
result in E18.** P2's respectable 4.67 % pooled rate is produced by a minority of runs alarming
heavily while the median run never alarms at all. P3's 8.16 % averages runs at ~1 % with a tail above
12 %. Only P1 has false-alarm behaviour that is stable *per run*, which is the unit at which an
operational monitor is actually experienced.

This is exactly the failure mode §10 of the brief warned against: *do not claim "calibrated" merely
because one aggregate number looks reasonable.* Our own first pass made that error and reported
P1 + P3 valid; the per-run analysis corrected it.

### 3 · What is the false-alarm behaviour?

On **P1**: 5.47 % pooled against a nominal 5 %, with 21 of 30 runs inside the pre-registered
[2.5 %, 10 %] band. Defensible.

On **P3 and P2**: bimodal and unstable. Not defensible at the run level despite acceptable pooled
values.

### 4 · Which faults are operationally detectable?

On P1, at the frozen threshold, minimum detectable severity:

| fault | MDS (detection ≥ 90 %) |
|---|---|
| `position_bias` | **0.25 m** — routine GNSS multipath, caught on every seed |
| `position_drift` | **0.5 m final** |
| `lateral_noise` | **×5 σ** |
| `speed_bias` | 6.0 m/s (high only) |

### 5 · Which faults remain undetectable?

**`speed_stuck` and `imu_dropout` — at every tested severity, on both P1 and P3**, with correct
calibration. `imu_dropout` on P1 reaches only 3 % detection.

This is not a calibration failure. It is a property of the conformal score: neither fault moves it
toward the threshold.

### 6 · Does `D_s` predict operational detection?

**No — and the association at the sensor stage runs the wrong way.**

- **17 of 28 cells disagree** between `D_L6 ≥ 0.9` and detection `≥ 0.9`
- Spearman `D_L6` vs detection: **ρ = +0.291, p = 0.137** — not significant
- Spearman `D_L1` vs detection: **ρ = −0.480, p = 0.0088** — significant and **negative**

**Higher sensor-level discriminability is associated with *lower* operational detection.** The
clearest single case: `speed_bias` at 3.0 m/s has `D_L1` = 1.000 — perfect statistical separability —
and 57 % detection on P1, 0 % on P2.

This has a direct consequence for E19, recorded before E19 is designed: **a monitor-placement
prediction derived from `D_s` alone is likely to be not merely uninformative but actively
anti-correlated with the operational outcome.**

### 7 · What happened with P2?

**Classification: INVALID** for operational calibration under the current OD-8 formulation.

- Within-run drift 4.1902 → 5.3711, **drift/SD = 1.28**, upward in **30 of 30 runs** (Wilcoxon
  p = 1.8 × 10⁻⁶)
- **0 of 30 runs** have a per-run false-alarm rate inside the target band
- Pooled FAR of 4.67 % is an artefact of averaging a bimodal distribution

P2 is **not deleted**. Its non-stationarity is a finding: it demonstrates that a fixed conformal
quantile cannot serve a policy whose score is non-stationary, which is a genuine limitation of the
current OD-8 formulation rather than a defect of the policy. A time-varying or windowed calibration
would be required, and that is a new experiment, not an adjustment to this one.

### 8 · Did alarm suppression replicate?

**Yes — 11 of 28 cells on the valid policies, every one at p < 0.05.**

| policy | fault | severity | fault alarm rate | clean FAR | ratio |
|---|---|---|--:|--:|--:|
| P1 | `imu_dropout` | — | **0.10 %** | 5.47 % | **0.018×** |
| P1 | `speed_bias` | 3.0 m/s | 0.47 % | 5.47 % | 0.085× |
| P3 | `speed_bias` | 3.0 m/s | 0.48 % | 8.16 % | 0.059× |
| P1 | `speed_stuck` | — | 1.30 % | 5.47 % | 0.237× |

The original observation (`imu_dropout` on P1, ≈ 0.10 % vs ≈ 5.47 %) replicates at the frozen
threshold: the fault makes the monitor **55× less likely to alarm than clean operation**.

**This is not better detection.** It is fault-induced suppression of an anomaly monitor. It is more
dangerous than a missed detection, because the monitor's silence is then positive evidence of
normality. Classified as a **genuine observation**, quantified, mechanism unexplained.

### 9 · What limitations remain?

- One plant model, three policies, simulation only. `[M-syn]`; `[M-ext]` remains **0 of 30**
- One context class in practice (99.75 % `URBAN_CLEAR`), so Mondrian conditioning is untested
- ε = 0.05 is a convention, not derived from a hazard analysis
- Per-tick alarms are not per-event alarms; no persistence or debouncing model
- Ticks within a run are autocorrelated, so the conformal coverage guarantee is weaker than
  n = 12,000 implies
- The alarm-suppression mechanism is measured, not explained
- P2's drift is measured, not explained
- **A fifth measurement defect was found in our own integrity check** — it compared mean estimated
  *position* for a zero-mean *lateral-acceleration* fault, producing 9 false integrity failures. The
  check needs to be per-channel

### 10 · Is E19 scientifically justified?

**Yes, but weakly — and the gate is narrower than expected.**

| §23 gate requirement | status |
|---|:--:|
| A valid operational monitor exists | **Yes — P1 only** |
| Calibration is frozen | **Yes** |
| Held-out behaviour is defensible | **Yes for P1; no for P2, P3** |
| Integrity checks pass | **Yes** — 1,251/1,260, the 9 exceptions explained and confined to P2 |
| Monitor can be fairly compared across locations | **Yes on P1** |

E19 would run on **a single policy**. That is a real scientific weakness: with n = 1 policy, any
monitor-placement result is confounded with policy identity and cannot be shown to generalise —
the same confound that killed the H-regime claim in E17.

**Recommendation:** proceed to E19 on P1, but treat the single-policy restriction as a first-class
limitation and pre-register that a positive result cannot be claimed to generalise. Alternatively,
run the minimum repair experiment in `final_decision.md` §5 first to recover P3.
