# E18-R3 — Precision or Dynamics?

# VERDICT: PASS-R3   |   E19 UNBLOCKED FOR P1

| | |
|---|---|
| Question | Is the monitor's instability precision-limited or dynamics-limited? |
| Design | One variable: evaluation window length. Frozen v3 threshold, no recalibration |
| Frozen criterion | P1 ≥ 24/30 runs in band at n = 3200 |
| **Result** | **P1 30/30 → PASS-R3** |
| Mechanism | Scaling slope −0.739 (P1), −0.918 (P3) — variance falls with window length |
| Confounder | Drift/SD 0.05 and 0.08 — clean, R3 isolated its variable |
| Realism | n = 3200 at 20 Hz = **160 s of driving** |

## Headline

**The score was not unfit for purpose. It was being asked to decide on 10 seconds of data.**

| policy | n=200 | n=400 | n=800 | n=1600 | n=3200 |
|---|:--:|:--:|:--:|:--:|:--:|
| **P1** | 12/30 | 16/30 | 21/30 | 29/30 | **30/30** |
| P3 | 2/30 | 4/30 | 6/30 | 6/30 | 5/30 |

## Two things to read carefully

**P3's failure changed character.** Its variance collapses too (slope −0.918) but converges to a
median FAR of 1.16 %, below the 2.5 % floor. That is **threshold bias, not instability** — a
different problem with a different fix, and the fix is a new experiment (E18-R4), not a
reinterpretation of this one.

**The slopes are steeper than binomial and that is not explained.** −0.5 is the independent-sampling
floor and correlated data should give a shallower slope. Probable measurement artefact (FAR is
quantised and bounded at short windows), but it is a hypothesis. The PASS does not depend on it.

## What this does not license

Nothing about detection. R3 measures clean-data false alarms only. **E18-R3b — detection at the long
window — is the experiment that decides whether this PASS is worth anything**, given that E18 found
`speed_stuck` and `imu_dropout` undetectable at any severity.

## Read

`preregistration.md` → `final_decision.md` → `processed_results/E18R3_WINDOWS.csv`
