# Claim Ledger

Permanent record of what may and may not be said. Every experiment updates this.

| Claim | Status | Evidence | Allowed wording |
|---|---|---|:--:|
| Position injection reaches the estimator | **Established** | E17-Position, 720/720 runs | **Yes** |
| `FaultChannel.POSITION_Y` was inert before the fix | **Established** | E17 Control C, 9 policy/seed pairs | **Yes** |
| All 9 layers domain-mapped; 3/3 Core-B gates verdict every tick | **Established** | live run, 300 ticks | **Yes** |
| Fault observability is heterogeneous | **Supported** | E17, n=30, 6 faults | **Yes** |
| `speed_stuck` absorbs at L2a on P1 | **Supported** | E17, well-posed 30/30, SD 0.0077 | **Yes** |
| The legacy L6 corpus was not exchangeable with live scores | **Established** | E18 diagnostic | **Yes** |
| OD-8 miscalibration is a calibration-set provenance failure, not a threshold value | **Established** | E18: global recalibration reproduces the defect | **Yes** |
| ~~OD-8 provides operational monitoring under specified policy constraints (P1 only)~~ | **WITHDRAWN** | E18-R1: on the matched evaluation window P1 is 4/30 runs in band, median run FAR 0.00 % | **No** |
| OD-8 is calibrated for any policy on the evaluation window | **Not established** | E18-R1: P1 4/30, P3 5/30 (E18 matched); P3 9/30 (R1) | **No** |
| E18 measured false-alarm rate and detection on different tick windows | **Established** | E18-R1 audit | **Yes** |
| P3 bimodality is caused by a per-run baseline offset | **Established** | corr(run mean, run FAR) = +0.909; removed to -0.469 by run-local calibration | **Yes** |
| Run-local calibration recovers P3 | **Rejected** | E18-R1: 9/30, below the frozen 12/30 floor | **No** |
| Matched-window calibration recovers P1 | **Rejected** | E18-R2: 13/30, below the frozen 24/30 bar | **No** |
| **The current OD-8 formulation cannot deliver per-run-stable false alarms at eps=0.05 on 200-tick windows** | **Established** | E18-R2: three schemes, best 13/30 vs 29.2/30 ideal | **Yes** |
| **P1's limit is within-run alarm clustering** | **Established** | lag-1 autocorr +0.359; 4.2x overdispersion; 11 effective ticks | **Yes** |
| **P3's limit is between-run baseline variation** | **Established** | lag-1 autocorr ~0; 9.2x overdispersion; 2 effective ticks | **Yes** |
| OD-8 is calibrated for P2 | **Rejected** | E18: 0/30 runs in band, drift/SD 1.28 | **No** |
| **`D_s` does not predict operational detection** | **Established** | E18, 17/28 cells disagree; D_L6 rho +0.29 (p=0.14) | **Yes** |
| **Higher sensor-level `D_L1` is associated with *lower* operational detection** | **Supported** | E18, Spearman rho = -0.480, p = 0.0088, n = 28 cells | **Yes, as an association** |
| **Fault-induced alarm suppression** | **Supported** | E18, 11/28 cells on valid policies, all p < 0.05 | **Yes, as observed** |
| `speed_stuck` and `imu_dropout` are undetectable by OD-8 at any tested severity | **Established** | E18, both valid policies | **Yes** |
| General L2a absorption | **Withdrawn** | E17 + E17-Position | **No** |
| Position faults are absorbed at L2a | **Withdrawn** | E17-Position, 0 of 12 cells | **No** |
| "Information is destroyed at L2a" | **Withdrawn** | the L6 statistic recovers part of it | **No** |
| L6 detection-without-response gap | **Withdrawn** | gate returns PASS on every tick | **No** |
| H-regime (veto rate as an operating-regime covariate) | **Withdrawn** | Simpson's paradox; veto rate is an OD-8 readout | **No** |
| `D_L2a > D_L1` under one-liar conditions | **Preliminary** | E17-Position R1, one condition | **Only as preliminary** |
| H7 monitor placement works | **Not tested** | E19 | **No** |
| Lying-sensor detection | **Not tested** | E20 | **No** |

## Terminology rules

- `D = 0.5` is **chance-level discriminability**, never "50 % accuracy".
- High `D` does **not** imply an operational gate fired. E18 measured this directly.
- Alarm suppression is **not** "better detection". It is a fault reducing the monitor's alarm rate
  below its clean baseline.
- Preferred phrasing for a collapse: *"the evaluated representation does not retain discriminative
  evidence"*. Never *"information is destroyed"*.
- The stage vector is the **fault observability profile**. `A(f)` is reported only where the profile
  crosses the absorption threshold at most once.
- A statistic is called "accuracy" only if it is classification accuracy.
- **No OD-8 operational-monitoring claim is currently permitted.** After the window-mismatch
  correction, no policy has defensible run-level false-alarm behaviour on the window where
  detection is measured. The permitted form is:
  *"The current OD-8 formulation does not provide a sufficiently reliable operational monitor
  under the evaluated conditions."*
- A false-alarm rate and a detection rate quoted together **must** be computed over the same tick
  range, and that range must be named in the pre-registration.
