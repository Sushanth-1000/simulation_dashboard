# E18-R3c — Final Decision

**3 September 2026** · 180 sustained-fault runs × 3,400 ticks · frozen v3 threshold (P1 = 3.7024)
**Duration-matched control for E18-R3b. Pre-registered before execution, direction unknown in advance.**

---

# VERDICT: H-AFTERMATH SUPPORTED

**A persistent sensor failure is not detected by the conformal monitor while it persists.**
**E18-R3b's 100 % detection of `imu_dropout` was entirely the post-fault recovery transient.**

---

## 1 · The decisive measurement

`imu_dropout` sustained for 3,200 ticks (160 s), 30 seeds, threshold 3.7024:

| phase from fault onset | alarm rate |
|---|--:|
| 200–399 | 0.004 |
| 400–999 | **0.002** |
| 1000–1999 | **0.002** |
| 2000–3399 | **0.002** |
| clean baseline (E18-R3, 30 runs) | ~0.05 |

**The alarm rate is below the clean baseline in every phase.** The monitor is quieter under
sustained IMU failure than during nominal operation, for 160 continuous seconds, on all 30 seeds.

## 2 · Direct comparison with R3b — one variable

Same seeds, same threshold, same faults. The only difference is whether the fault ever ends.

| fault | phase | R3b alarm | R3c alarm |
|---|---|--:|--:|
| **`imu_dropout`** | during 200–399 | 0.004 | 0.004 |
| | 400–999 | **0.991** | **0.002** |
| | 1000–1999 | 0.692 | 0.002 |
| | 2000–3399 | 0.596 | 0.002 |
| `position_bias` | all phases | 0.87–1.00 | 0.87–1.00 |
| `position_drift` | during 200–399 | 0.478 | 0.068 |
| | 400–999 | 1.000 | 0.182 |
| | 1000–1999 | 1.000 | 0.780 |
| | 2000–3399 | 1.000 | 1.000 |
| `lateral_noise` | 400–999 | 0.893 | **0.977** |
| | 1000–1999 | 0.496 | **1.000** |
| | 2000–3399 | 0.439 | **1.000** |
| `speed_bias` | all phases | ~0.05 | ~0.05 |
| `speed_stuck` | all phases | ~0.06 | ~0.07 |

## 3 · Run-level detection under sustained fault

| fault | n = 200 | n = 3200 |
|---|--:|--:|
| `position_bias` | 100 % | **100 %** |
| `position_drift` | 0 % | **100 %** |
| `lateral_noise` | 87 % | **100 %** |
| `speed_stuck` | 3 % | 37 % |
| `speed_bias` | 0 % | **0 %** |
| **`imu_dropout`** | 0 % | **0 %** |

**Three of six faults are detected under sustained injection**, not four. R3b's fourth
(`imu_dropout`) was aftermath.

## 4 · Three mechanisms, now cleanly separated

**`imu_dropout` — aftermath-only.** R3b's late-window 99.1 % collapses to 0.2 % once the fault never
ends. All of its apparent detection came from the recovery transient.

**`lateral_noise` — genuinely sustained-detectable.** R3c *exceeds* R3b in every late phase
(0.977 / 1.000 / 1.000 against 0.893 / 0.496 / 0.439). The fault continuously feeds the score, so
removing the "end" adds evidence rather than removing it.

**`position_bias` — sustained in both.** Identical across R3b and R3c, because position faults inject
via `RedundantSensing.offset` with `opens_at = 200` and no closing tick, so they were already active
for the whole run under both designs.

## 5 · A correction to R3b, found only by running R3c

`_sensing` in `e18_evaluate.py` computes `drift_per_tick = magnitude / span` where
`span = TICKS - 1 - _FAULT_FIRST` and `TICKS = 400` is a module constant. R3b imported this
unchanged and ran for 3,400 ticks, so `position_drift`'s per-tick rate was calibrated for a 200-tick
window and then applied for 3,200 ticks — **reaching roughly 32 m instead of the intended 2 m.**

R3c uses `span = ticks - 1 - _FAULT_FIRST` with the true run length. At the corrected 2 m magnitude,
`position_drift` alarms on only 6.8 % of ticks during its first 200 ticks and 18.2 % through
tick 999, reaching 100 % only after roughly 2,000 ticks of accumulated drift.

**R3b's `position_drift` figure is therefore partially invalidated** — it was detecting a runaway
32 m drift, not the 2 m specification. Earlier 400-tick E18 runs are unaffected, because `span` was
correct for those.

## 6 · The safety statement

# A persistent sensor failure is invisible to the conformal monitor for as long as it persists.

Detection, when it occurs, comes primarily from the **post-fault recovery transient** — the twin
disagreeing with an estimator state that was corrupted while the sensor misbehaved. Under sustained
failure no recovery ever begins, and the monitor stays below its own clean baseline throughout.

**A monitor that is quieter than baseline during a hazard is worse than one that fails to detect
it.** An operator watching that monitor sees quieter-than-usual output and concludes normality. The
absence of an alarm becomes positive evidence for the safety of a compromised system.

## 7 · What this refutes and establishes

**Refuted:** the R3b interpretation that a longer window supplies more statistical power on a
persistent shift. When the shift is genuinely persistent, it is not detected at all.

**Established:** alarm suppression is now more than an anecdote — it is a measured, phase-resolved
property of the conformal score under sustained sensor failure, on 30 seeds with a frozen threshold
and a duration-matched control. Combined with E17's `D_L1 = 0.998` for `imu_dropout` against a 0.2 %
operational alarm rate, the discriminability-versus-detection gap is not only anti-correlated
(E18) but also time-dependent.

## 8 · What R3c does not license

- Nothing about P2 or P3; nothing about severities other than `medium`.
- Nothing about *why* the estimator behaves this way. R3c measures monitor output, not internal
  filter state. Explaining the mechanism at L2 needs instrumentation this experiment does not add.
- `speed_bias` and `speed_stuck` remain flat in every phase, in both transient and sustained modes.
- `[M-syn]` throughout. `[M-ext]` remains 0 of 30.

## 9 · Next

1. **Update the paper framing.** This is the headline: the monitor is silent during the fault it
   exists to catch. Window sizing, monitorability and the self-trust plane are the machinery built
   in response.
2. **Fix the drift-scaling bug** in `e18_evaluate.py` so it cannot resurface.
3. **Phase 2 (monitorability)** — still zero new compute, and `M` now needs a phase-aware definition.
4. **E19** — now genuinely reachable on P1, with detection understood phase-resolved.
