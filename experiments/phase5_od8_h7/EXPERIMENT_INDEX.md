# Experiment Index

| Experiment | Question | Status | Main result | Decision |
|---|---|---|---|---|
| E17 | Controlled fault observability | **Complete** | Heterogeneous observability; 1 of 6 faults well-posed absorption | Baseline |
| E17-Position | Does absorption survive correct injection? | **Complete** | Absorbed in 0 of 12 cells | Claim withdrawn |
| **E18** | Can OD-8 be validly calibrated? | **Complete, verdict revised** | D_s does not predict detection; P1 verdict withdrawn after window-mismatch correction | **PARTIAL** |
| **E18-R1** | Can run-local calibration recover P3? | **Complete** | P3 9/30; mechanism removed but estimator too noisy; **found E18 window defect** | **FAIL-P3** |
| **E18-R2** | Does matched-window pooled calibration work? | **Complete** | P1 13/30 (best of 3); obstacle is the score process, not the threshold | **PARTIAL-R2** |
| **E18-R3** | Precision-limited or dynamics-limited? | **Complete** | P1 30/30 at n=3200 (160 s). Precision-limited | **PASS-R3** |
| **E18-R3b** | Does it detect faults at the long window? | **Complete** | 4/6 at 100 %. Detection comes from the post-fault transient, not statistical power | **PASS, mechanism refuted** |
| **E18-R3c** | Duration-matched control: is detection aftermath or sustained? | **Complete** | Sustained `imu_dropout` alarms at 0.2 %, below clean baseline. Only 3 of 6 faults detected under sustained injection | **H-AFTERMATH SUPPORTED** |
| E19 | Does the observability profile predict monitor placement? | **Unblocked for P1** | - | - |
| E20 | How does single-channel manipulation propagate? | **Future** | - | - |

## E18 headline

OD-8's failure was **calibration-set provenance**, not threshold value: a global recalibration
reproduces the original defect exactly (0.00 % clean false alarms on P1/P3, 11.06 % on P2).
Policy-conditional calibration fixes it for one policy.

Frozen thresholds, version 1: **P1 3.7095 | P2 5.9024 | P3 3.4000** at eps = 0.05.

| policy | pooled FAR | per-run median [IQR] | runs in band | drift/SD | class |
|---|--:|---|:--:|--:|---|
| P1 | 5.47 % | 4.88 % [3.25, 7.25] | **21/30** | 0.09 | **VALID** |
| P3 | 8.16 % | 1.00 % [0.75, 12.56] | 4/30 | 0.03 | CONDITIONAL |
| P2 | 4.67 % | 0.00 % [0.00, 0.00] | 0/30 | **1.28** | **INVALID** |

**Pooled false-alarm rates were misleading for P2 and P3.** Changing the unit of analysis from tick
to run reduced the valid set from two policies to one.

## Findings carried forward

1. **`D_s` does not predict operational detection.** 17 of 28 cells disagree. `D_L1` vs detection:
   Spearman rho = **-0.480**, p = 0.0088 - a *negative* association.
2. **Fault-induced alarm suppression replicates** - 11 of 28 cells, all p < 0.05. `imu_dropout` on P1
   makes the monitor 55x *less* likely to alarm than clean operation.
3. **`speed_stuck` and `imu_dropout` are undetectable** by OD-8 at any tested severity, correctly
   calibrated, on both P1 and P3.
4. **P2 is INVALID for fixed-quantile calibration** - non-stationary score, 30/30 runs drift upward.

Updated after every experiment.


## E18-R1 correction to E18

E18 measured **false-alarm rate over ticks 0-399** and **detection over ticks 200-399**. On the
matched window:

| policy | E18 reported (whole run) | matched window | R1 run-local |
|---|--:|--:|--:|
| P1 runs in band /30 | 21 | **4** | 3 |
| P3 runs in band /30 | 4 | 5 | **9** |

**E18's "P1 VALID" is withdrawn.** No policy currently has defensible run-level false-alarm behaviour
on the window where detection decisions are made. E19 is blocked until E18-R2 resolves this.
