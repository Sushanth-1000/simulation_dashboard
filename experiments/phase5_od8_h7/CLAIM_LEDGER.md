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
| ~~The current OD-8 formulation cannot deliver per-run-stable false alarms at eps=0.05~~ | **SUPERSEDED** | E18-R3: the qualifier *on 200-tick windows* was load-bearing. At n=3200 (160 s) P1 reaches 30/30 | **No — use the row below** |
| **OD-8 delivers per-run-stable clean-data behaviour on P1 at a 160-second evaluation window** | **Established** | E18-R3: 30/30 runs in band, frozen threshold, held-out seeds, no drift | **Yes, with the window stated** |
| **The P1 instability was precision-limited, not dynamics-limited** | **Established** | E18-R3: FAR variability falls with window length; 12/30 → 30/30 | **Yes** |
| **P3's residual failure is threshold bias, not instability** | **Supported** | E18-R3: variance collapses (slope −0.918) but median FAR converges to 1.16 %, below the 2.5 % floor | **Yes** |
| **OD-8 detects 4 of 6 faults at a 160-second window on P1** | **Established** | E18-R3b: position_bias, position_drift, lateral_noise, imu_dropout all 100 % | **Yes, with the window stated** |
| **A fault can be undetectable while active and strongly detectable after it ends** | **Established** | E18-R3b per-tick series: `imu_dropout` alarms on 0.4 % of ticks during the fault, 99.1 % immediately after | **Yes** |
| **Alarm suppression is a property of the fault *while active*, not of the fault** | **Established** | E18-R3b: same fault, 0.4 % during vs 99.1 % after | **Yes** |
| Longer windows improve detection by statistical power | **Refuted** | E18-R3b: the fault occupies 6 % of the window; detection comes from the post-fault transient | **No** |
| Longer windows improve detection by covering the recovery transient | **Supported** | E18-R3b, phase-resolved scores; needs a duration-matched control | **Yes, as supported** |
| `speed_bias` and `speed_stuck` are detectable at any window | **Rejected** | E18-R3b: 50 % and 10 %; scores flat in every phase | **No** |
| **P1's limit is within-run alarm clustering** | **Established** | lag-1 autocorr +0.359; 4.2x overdispersion; 11 effective ticks | **Yes** |
| **P3's limit is between-run baseline variation** | **Established** | lag-1 autocorr ~0; 9.2x overdispersion; 2 effective ticks | **Yes** |
| OD-8 is calibrated for P2 | **Rejected** | E18: 0/30 runs in band, drift/SD 1.28 | **No** |
| **`D_s` does not predict operational detection** | **Established** | E18, 17/28 cells disagree; D_L6 rho +0.29 (p=0.14) | **Yes** |
| **Higher sensor-level `D_L1` is associated with *lower* operational detection** | **Supported** | E18, Spearman rho = -0.480, p = 0.0088, n = 28 cells | **Yes, as an association** |
| **Fault-induced alarm suppression** | **Supported** | E18, 11/28 cells on valid policies, all p < 0.05 | **Yes, as observed** |
| ~~`speed_stuck` and `imu_dropout` are undetectable by OD-8 at any tested severity~~ | **SUPERSEDED for `imu_dropout`** | E18-R3b: 100 % at a 160 s window, via the post-fault transient. `speed_stuck` stands at 10 % | **No — split the two** |
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
- **OD-8 claims must state the evaluation window.** E18-R3 showed the window was the binding
  variable, so a claim without it is meaningless. The permitted form is:
  *"OD-8 provides operationally stable clean-data behaviour on P1 at a 160-second evaluation
  window."* Any claim about **detection** at that window is **not yet permitted** — R3 measured
  false alarms only.
- A false-alarm rate and a detection rate quoted together **must** be computed over the same tick
  range, and that range must be named in the pre-registration.
- **Detection must be reported phase-resolved** — during-fault and post-fault separately. E18-R3b
  showed a fault that is undetectable during its own duration and near-certain afterwards;
  a window-aggregate detection rate hides that completely and would be misleading.
