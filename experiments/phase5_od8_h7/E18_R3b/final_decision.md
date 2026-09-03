# E18-R3b — Final Decision

**3 September 2026** · 180 faulted runs × 3,400 ticks · frozen v3 threshold (P1 = 3.7024), no recalibration
**Criterion frozen in `preregistration.md` before execution.** Per-tick series stored.

---

# VERDICT: PASS on the criterion — MECHANISM REFUTED AND REPLACED

**4 of 6 faults reach ≥ 90 % detection at n = 3200.** The frozen bar was ≥ 4 of 6.

**But the pre-registered explanation for why is wrong**, and the real mechanism is more interesting
than the one it replaces.

---

## 1 · Result

| fault | detection n=200 | detection n=3200 |
|---|--:|--:|
| `position_bias` | 100 % | **100 %** |
| `position_drift` | 100 % | **100 %** |
| `lateral_noise` | 87 % | **100 %** |
| `imu_dropout` | 0 % | **100 %** |
| `speed_bias` | 0 % | 50 % |
| `speed_stuck` | 3 % | 10 % |

## 2 · The pre-registered red flag fired, and investigating it produced the finding

`preregistration.md` §4 stated, before any run:

> **If `speed_stuck` or `imu_dropout` reaches ≥ 90 % detection, that is a red flag, not a win.**

`imu_dropout` reached 100 %. Its E18 score shift was **−0.0069** — 0.71 σ *away* from the alarm
region. A monitor that alarms on high scores should become *less* likely to fire, not certain to.

**The flag was correct to fire, and the investigation it forced is the result of this experiment.**

## 3 · What the per-tick series shows

The fault window is **ticks 200–399 only**. `_build_injector` derives `last` from `TICKS = 400`, a
module constant in `e18_evaluate.py` that R3b imports unchanged. So at n = 3200 the evaluation window
holds 200 ticks of fault and 3,000 ticks of **post-fault operation** — the fault is 6 % of the
window, and detection should have been *diluted*.

Mean non-conformity score by phase, threshold **3.7024**:

| fault | pre 0–199 | **during fault 200–399** | 400–999 | 1000–1999 | 2000–3399 |
|---|--:|--:|--:|--:|--:|
| `position_bias` | 3.6871 | 4.3764 | 4.6791 | 4.6795 | 4.6976 |
| `position_drift` | 3.6871 | 4.0033 | 4.6642 | 4.8145 | 4.9394 |
| `lateral_noise` | 3.6871 | 3.7909 | 4.0785 | 4.0489 | 4.0548 |
| **`imu_dropout`** | 3.6871 | **3.6790** | **4.1092** | 4.0268 | 4.0332 |
| `speed_bias` | 3.6871 | 3.6846 | 3.6917 | 3.6892 | 3.6889 |
| `speed_stuck` | 3.6871 | 3.6885 | 3.6883 | 3.6888 | 3.6888 |

Fraction of ticks above threshold:

| fault | during fault | 400–999 | 1000–1999 | 2000–3399 |
|---|--:|--:|--:|--:|
| **`imu_dropout`** | **0.004** | **0.991** | 0.692 | 0.596 |
| `position_bias` | 0.873 | 1.000 | 1.000 | 1.000 |
| `lateral_noise` | 0.406 | 0.893 | 0.496 | 0.439 |

# The fault is invisible while it is happening and glaringly visible after it stops.

During the dropout, `imu_dropout`'s mean score sits **below** the threshold and alarms on 0.4 % of
ticks — **less often than clean operation**. The moment the sensor returns, the score jumps and
alarms on 99.1 % of ticks, staying elevated for thousands of ticks afterwards.

## 4 · The mechanism, and what it refutes

**Refuted:** the pre-registered hypothesis that a longer window improves detection by resolving a
persistent shift with more statistical power. The fault does not last longer, and its own 200 ticks
are the *least* informative part of the window.

**Supported instead:** the conformal score responds to the **aftermath** of a fault far more than to
the fault itself. The estimator's state is corrupted while the sensor misbehaves; the twin then
disagrees with that corrupted state long after the sensor recovers. **What the longer window buys is
not statistical power — it is coverage of the recovery transient.**

This also gives the alarm-suppression finding a mechanism and a time course. Suppression is not a
property of the fault in general; it is a property of the fault **while active**. The same fault is
strongly detectable once it stops.

## 5 · Safety implication — the sharpest thing here

**While the IMU is dropping out, the monitor reports the vehicle as healthier than normal.**

0.4 % alarm rate during the fault, against ~5 % clean. An operator watching this monitor sees quieter
than usual output at exactly the moment a sensor has failed. Detection arrives only after the
hazard has passed.

A monitor that is suppressed during the event and confident afterwards is worse than one that simply
misses it, because its silence is read as evidence of health. **This is now a measured time course,
not an anecdote.**

## 6 · Consequences for the proposed contributions

**The window-sizing rule (ASTRA 2.0 §8 / C2) needs rewriting.** Sizing from effective sample size is
the wrong theory for detection. The right rule is: **size the window to include the post-fault
recovery transient.** That is a different, more specific, and more useful design rule — but it is a
new claim needing its own validation, not a confirmation of the old one.

**R3's clean-data result is unaffected.** It measured clean runs only; no fault, no aftermath.

## 7 · What is NOT licensed

- `speed_bias` (50 %) and `speed_stuck` (10 %) remain undetectable. Their scores are flat in every
  phase — no fault signature, no aftermath. Consistent with shifts of 0.34 σ and 0.05 σ.
- Detection latency is **not** measured meaningfully here. A fault detected at tick 450 was
  undetected throughout its own duration. Reporting "detected" without the phase breakdown would be
  actively misleading.
- Nothing about P2 or P3. Nothing about severities other than `medium`. `[M-syn]` throughout.

## 8 · Next

1. **Re-run with fault duration matched to the window** — hold the fault active for the whole
   evaluation window and compare. That separates "aftermath detection" from "sustained-fault
   detection" and is the experiment that turns §4 from an inference into a result.
2. **Measure phase-resolved detection as the primary metric**, not window-aggregate detection.
3. Phase 2 (monitorability) — still nearly free, and `M` now needs a phase-aware definition.
