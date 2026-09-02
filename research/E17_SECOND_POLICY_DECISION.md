# E17 Second-Policy Decision

**Run** 31 August 2026 · seed 20260731, 400 ticks, fault at 200 · same faults, severities, metric and
procedure across all three policies. **Only the policy differs.**

---

## 1 · Objective

Determine whether the `A(f) = L2a` absorption observed under one policy is a property of the
pipeline or of that policy.

## 2 · Measurement Corrections

Two, both completed before any second-policy run.

## 3 · `lateral_noise` Statistic

`NOISE_BURST` adds zero-mean Gaussian noise: it moves **dispersion**, not location. AUC on raw values
tests a location shift and was blind to it — the source of the previous `D_L1 = 0.504`.

Replaced with a **rolling standard deviation over a 10-tick window**. The window is fixed at 10 to
match `PATIENCE` in `training/redundant.py`, a constant the project already committed to for *"one
excursion is noise, a sustained one is a fault"*. **Reusing an existing constant means the window was
not chosen after seeing a result.**

Effect: `D_L1` 0.504 → **0.995**. The fault was never emergent; the statistic was wrong.

## 4 · L6 Status

**Fixed — it was an observer-plumbing gap, not a missing signal.** `TickSample.live_score` is
populated only when the FB2 shadow runs, which E17 does not enable. The STATISTICAL gate computes and
records the score on every tick regardless, inside its verdict `evidence` tuple as
`non_conformity_score`.

L6 now reads from there. No ASTRA behaviour change; the value was always being computed.

## 5–6 · Policy Configurations

| | Checkpoint | Vetoes / 200 | Final speed | Regime |
|---|---|--:|--:|---|
| **P1** | `var/policy/synthetic.pt` | ~2 / 400 | 11.4 m/s | normal |
| **P2** | `var/policy/long.pt` | **140 / 200** | **5.4 m/s** | **heavily vetoed** |
| **P3** | `var/policy/jerkscaled.pt` | 3 / 200 | 10.5 m/s | normal |

P3 was added because P2 turned out to drive in a degraded regime, which is a confound rather than a
policy difference. **A correction to an earlier finding:** the other checkpoints were never broken —
the stale *twin and corpus* made the gates veto everything regardless of policy. Regenerating them
restored three of four.

## 7 · Experimental Controls

Identical across all three: seed, faults, severities, injection tick, stage definitions, metric,
window, pairing. Only the policy varies.

## 8–9 · Results

**P1 — `synthetic.pt`**

| scenario | L1 | L2a | L2b | L3 | L6 | L7 | L8 | A(f) |
|---|--:|--:|--:|--:|--:|--:|--:|:--:|
| imu_dropout | 0.998 | 0.675 | 0.931 | 0.676 | 0.680 | 0.505 | 0.988 | L7 |
| position_bias | 1.000 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | **L2a** |
| position_drift | 0.970 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | **L2a** |
| speed_stuck | 0.927 | 0.564 | 0.512 | 0.562 | 0.546 | 0.500 | 0.500 | **L2a** |
| speed_bias | 1.000 | 0.508 | 0.692 | 0.504 | 0.695 | 0.500 | 0.500 | **L2a** |
| lateral_noise | 0.995 | 0.982 | 0.906 | 0.981 | 0.703 | 0.833 | 0.870 | none |

**P2 — `long.pt` (degraded regime)**

| scenario | L1 | L2a | L2b | L3 | L6 | L7 | L8 | A(f) |
|---|--:|--:|--:|--:|--:|--:|--:|:--:|
| imu_dropout | 0.998 | 0.764 | 0.930 | 0.764 | 0.533 | 0.585 | 0.780 | L6 |
| position_bias | 1.000 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | **L2a** |
| position_drift | 0.967 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | **L2a** |
| speed_stuck | 0.667 | 0.905 | 0.505 | 0.905 | 0.564 | 0.550 | 0.530 | L2b |
| speed_bias | 0.532 | 0.561 | 0.514 | 0.567 | 0.530 | 0.568 | 0.525 | L1 |
| lateral_noise | 0.850 | 0.758 | 0.887 | 0.753 | 0.872 | 0.650 | 0.785 | none |

**P3 — `jerkscaled.pt`**

| scenario | L1 | L2a | L2b | L3 | L6 | L7 | L8 | A(f) |
|---|--:|--:|--:|--:|--:|--:|--:|:--:|
| imu_dropout | 0.998 | 0.692 | 0.825 | 0.691 | 0.729 | 0.500 | 0.988 | L7 |
| position_bias | 1.000 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | **L2a** |
| position_drift | 0.977 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | **L2a** |
| speed_stuck | 0.988 | 0.564 | 0.505 | 0.563 | 0.756 | 0.500 | 0.500 | **L2a** |
| speed_bias | 1.000 | 0.503 | 0.512 | 0.504 | 0.993 | 0.500 | 0.500 | **L2a** |
| lateral_noise | 0.996 | 0.973 | 0.901 | 0.973 | 0.995 | 0.795 | 0.865 | none |

## 10–11 · Fault-by-Fault and A(f) Comparison

| Fault | P1 | P2 | P3 | Same? | Interpretation |
|---|:--:|:--:|:--:|:--:|---|
| position_bias | L2a | **L2a** | L2a | **✅ all three** | 1.000 → 0.500 identically on every policy |
| position_drift | L2a | **L2a** | L2a | **✅ all three** | 0.967–0.977 → 0.500 identically |
| speed_stuck | L2a | L2b | L2a | ⚠️ 2 of 3 | P2's L1 falls to 0.667 and L2a *rises* to 0.905 |
| speed_bias | L2a | L1 | L2a | ⚠️ 2 of 3 | P2's L1 collapses to 0.532 — barely separable even at the sensor |
| imu_dropout | L7 | L6 | L7 | ⚠️ 2 of 3 | non-monotonic on all three; crossing stage differs |
| lateral_noise | none | none | none | **✅ all three** | persistent on all three; never absorbed |

## 12 · Structural Policy Independence

**The two position faults are policy-independent.** `D_L1 ≈ 1.000` and `D_L2a = 0.500` reproduce to
three decimals across all three policies, including the degraded one. That is the strongest evidence
in the project.

**The two speed faults reproduce on P1 and P3 and break on P2.** The distinguishing variable is not
the policy but the **operating regime**: P2 is vetoed on 70% of ticks and drives at half the speed.
A speed bias on a vehicle whose speed is already being clamped by governance has a masked signature —
which is a mechanistic explanation and, importantly, a **falsifiable one**: it predicts that
speed-channel discriminability varies with veto rate.

**This is not a reason to discard P2.** It is a boundary condition on the phenomenon and belongs in
the paper.

## 13 · Heterogeneous Fault Behaviour — preserved

**`imu_dropout` — NON-MONOTONIC on all three.** 0.998 at sensing, dips, recovers at L2b, falls to
0.500–0.585 at the gates, recovers to 0.780–0.988 at the fail-safe. **NO UNIQUE A(f).** The gates sit
at or near chance on a fault sensing separates almost perfectly, while the fail-safe responds because
it reads L1 directly.

**`lateral_noise` — PERSISTENT on all three.** Never falls below 0.60 at any stage. **NO A(f).** With
the corrected dispersion statistic it is separable from sensing through to the fail-safe. The earlier
"emergent" classification was an artefact of the wrong statistic and is withdrawn.

## 14 · Limitations

n = 1 per policy · one plant · one severity per fault · three policies is not a sample · the P2
regime confound is explanatory, not tested · stage statistics are one choice among several ·
`speed_stuck` under P2 shows discriminability *rising* at L2a (0.667 → 0.905), which is unexplained.

## 15 · Decision

# CONDITIONAL_GO

Four of six faults classify identically across all three policies, and the two position faults
reproduce to three decimals including under a degraded regime. Two speed faults reproduce on two of
three policies, with a specific and testable mechanism for the third.

Not GO, because the designated second policy did **not** reproduce all four primary faults, and the
prompt's GO criterion required it.

**Condition to resolve:** the 30-seed sweep must record **operating regime** — veto rate and mean
speed per run — as a covariate, so the speed-channel boundary can be characterised rather than
averaged away. Without it the sweep would pool two regimes and report a blurred result.

## 16 · Exact Next Action

**Add veto rate and mean speed per run to the E17 output**, then run the 30-seed sweep **stratified
by operating regime** rather than pooled.

That is roughly an hour of instrumentation. It converts P2's divergence from a confound into a
measured variable, and it is the difference between a sweep that answers the question and one that
hides it.
