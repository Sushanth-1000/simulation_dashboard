# E17 — Fault-Injection Integrity Audit

**1 September 2026** · `benchmarks/e17_integrity.py`, `benchmarks/e17_controls.py`
**Raw** `results/E17_INTEGRITY/{integrity.json,controls.json,validation_subset.json}`

The rule this audit enforces: **never trust the injector's output as evidence that a fault
happened.** Measure the signal where each consumer reads it.

---

## 1 · Instrumented boundaries

| # | boundary | how it is captured |
|---|---|---|
| 1 | injector | wrap `FaultInjector.corrupt`, record the returned payload |
| 2 | bus / L1 | read the IMU sample **off the fused frame**, i.e. as published |
| 3 | estimator input | wrap the extractor, record the `Measurement.values` handed to the UKF |
| 4 | downstream | `fast_innovation` and `fast_state.mean[1]` via the tick observer |

Both extractors are patched. `RedundantExtractor` is the default path; `_Extractor` runs under
`single_channel=True`. **Patching only one is how an audit silently measures nothing** — the first
version of this module patched `RedundantExtractor` alone and captured zero samples under
`single_channel=True`.

## 2 · Integrity table — required by §3

Policy P1, seed 20260731, 400 ticks, fault from tick 200. Magnitudes are max absolute
clean-vs-faulted difference over the fault window.

| Fault | Severity | Intended channel | Reaches L1? | Reaches estimator? | Reaches downstream? | Ground-truth bypass? | Verdict |
|---|---|---|:--:|:--:|:--:|:--:|:--:|
| `imu_dropout` | suppress IMU | frame-level (IMU) | **yes** | **yes** | **yes** | no | **VALID** |
| `position_bias` | 1.0 m | `y` | **NO** | **NO** | **NO** | **YES** | **INVALID** |
| `position_drift` | 2.0 m final | `y` | **NO** | **NO** | **NO** | **YES** | **INVALID** |
| `speed_stuck` | hold | `v` | **yes** | **yes** | **yes** | no | **VALID** |
| `speed_bias` | 3.0 m/s | `v` | **yes** | **yes** | **yes** | no | **VALID** |
| `lateral_noise` | sigma ×25 | `a` | **yes** | **yes** | **yes** | no | **VALID** |

Magnitudes:

| fault | injector | L1 | estimator in | innovation | est. state |
|---|--:|--:|--:|--:|--:|
| `imu_dropout` | (absent) | 0.736 | 0.736 | 0.689 | 0.190 |
| **`position_bias`** | **1.500** | **0** | **0** | **0** | **0** |
| **`position_drift`** | **2.231** | **0** | **0** | **0** | **0** |
| `speed_stuck` | 0.215 | 0.215 | 0.215 | 0.093 | 0.010 |
| `speed_bias` | 3.000 | 3.000 | 3.000 | 11.30 | 0.070 |
| `lateral_noise` | 4.953 | 4.953 | 9.772 | 4.323 | 1.230 |

For the four valid faults the injector magnitude **equals** the L1 magnitude — the corruption is
delivered intact. For the two position faults the injector produces 1.5 m and 2.2 m of corruption and
**every consumer sees exactly zero.**

## 3 · Consistency across policies and seeds — §5 verification subset

Three policies × three seeds × six faults = 54 audited fault paths.

| fault | verdicts observed | consistent? |
|---|---|:--:|
| `imu_dropout` | VALID ×9 | yes |
| `position_bias` | **INVALID ×9** | yes |
| `position_drift` | **INVALID ×9** | yes |
| `speed_stuck` | VALID ×9 | yes |
| `speed_bias` | VALID ×9 | yes |
| `lateral_noise` | VALID ×9 | yes |

No NaN, no Inf, no missing logs, no run failures. **The bypass is not policy-specific and not
seed-specific.**

## 4 · Root cause

`training/closed_loop.py:742` — `drive_closed_loop` resolves sensing through `_resolved_sensing`,
which returns `RedundantSensing.build(...)` **by default**. Redundancy is the driven path since
**ADR-0033, 15 August 2026**.

`training/closed_loop.py:365-374` — for every modality in `redundant.sigmas`:

```python
published = {**payload, "y": float(state[1]) + redundant.draw(modality) + redundant.offset(modality, tick)}
```

`y` is rebuilt from `state[1]`, the plant's **ground truth**, discarding the corrupted value. Only
`y`; `v` and `a` pass through from `**payload` intact. `RedundantExtractor` then takes the median
across IMU/GPS/LIDAR — all three regenerated from truth.

**This is a harness defect, not an ASTRA defect.** Real redundancy *should* out-vote a lying channel,
which is what ADR-0033 exists for. `FaultInjector` corrupts the shared pre-publish payload, upstream
of the per-channel regeneration, so **no channel ever lies** and there is nothing to out-vote. The
correct injection point for a position fault post-ADR-0033 is `redundant.offset(modality, tick)`,
which is per-channel and already exists.

## 5 · Negative controls — §10

| control | expectation | result | verdict |
|---|---|---|:--:|
| **A** fault on an unconsumed channel (`position_bias`, redundancy ON) | no downstream effect | L1 1.000, every stage from L2a = 0.500 | **as expected** |
| **B** fault on the consumed channel (`speed_bias`) | measurable downstream effect | L1 1.000 → L2a 0.508, L2b 0.692, L6 0.695 | **as expected** |
| **C** bypass disabled (`single_channel=True`) | position fault propagates | see below | **BYPASS CONFIRMED** |
| **D** clean vs clean, different seeds | no systematic fault evidence | max stage 0.565 (L6), rest ≤ 0.527 | **as expected** |

**Control C, the load-bearing one.** Same fault, same seed, same policy; only the sensing path differs:

| fault | redundancy | injector | L1 | estimator in | innovation |
|---|:--:|--:|--:|--:|--:|
| `position_bias` | **ON** | 1.500 | **0** | **0** | **0** |
| `position_bias` | **OFF** | 1.000 | **1.000** | **3.180** | **2.046** |
| `position_drift` | **ON** | 2.231 | **0** | **0** | **0** |
| `position_drift` | **OFF** | 0.102 | **0.102** | **0.533** | **0.037** |

Disabling the regeneration restores propagation completely. **The diagnosis is established causally,
not by argument.**

### 5.1 · A correction to this control

The first version of Control C compared **end-to-end `D_s`** with redundancy on and off, and returned
*"BYPASS NOT CONFIRMED"*. That verdict was wrong, and the reason matters:

With redundancy OFF, `D_L1` for `position_bias` is **0.513** — near chance — even though the signal
carries a full 1.0 m bias. **The vehicle steers to null the bias**, so true lateral position moves to
≈ −1.0 m and the measured reading returns to ≈ 0, indistinguishable from clean.

**Closed-loop compensation destroys sensor-level discriminability for bias faults.** That is a real
phenomenon and a genuinely interesting one — but it is *not* what `D_s` was being read as. It also
means **`D_s` is not a valid integrity test**: only the delivered signal answers whether a fault
arrived. Control C was rewritten to measure boundary magnitudes.

## 6 · Consequence for the 30-seed sweep

| fault | 30-seed data | status |
|---|---|---|
| `position_bias`, `position_drift` | present | **EXCLUDED — contaminated** |
| `imu_dropout`, `speed_stuck`, `speed_bias`, `lateral_noise` | present | **retained — integrity-verified** |

The four valid faults were not re-run. Their integrity is verified at the delivered signal across 9
(policy, seed) combinations, the sweep completed with 0 failures, and re-running would reproduce
identical numbers from identical seeds. **Contaminated rows are retained in the CSVs and flagged
`INVALID`, not deleted** — an audit that erases its contaminated rows cannot be checked.
