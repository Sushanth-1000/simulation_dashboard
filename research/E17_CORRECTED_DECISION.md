# E17 Corrected Decision

**Run** 31 August 2026 · same seed, same policy, same faults, same metric as the first E17 run.
**Only the L1 statistic changed.**

---

## 1 · Previous Measurement Problem

The first run used *count of non-HEALTHY modalities* as `T_L1` for every scenario. That is the
**health verdict**, not the raw observation.

`BIAS`, `DRIFT`, `STUCK_AT` and `NOISE_BURST` all keep the stream perfectly fresh by construction —
the scenario definitions in `benchmarks/fault_study.py` say so explicitly. So the health count was
identically zero in both arms and AUC returned 0.500 **by construction, not by measurement**. Five of
six `A(f)` values were artefacts.

Confirmed by inspection: `TickSample` exposed only `measured_lateral_acceleration_mps2`. No raw
position or speed channel existed, so a correct L1 was not computable without instrumentation.

---

## 2 · Exact Correction

`T_L1` is now the **raw measured value on the channel the fault corrupts**, after noise and after
injection, before fusion and before the filter — mirroring `FaultChannel` in `training/faults.py`:

| Scenario | Channel | `T_L1` |
|---|---|---|
| position_bias, position_drift | POSITION_Y | `measured_position_m` |
| speed_stuck, speed_bias | SPEED | `measured_speed_mps` |
| lateral_noise | LATERAL_ACCELERATION | `measured_lateral_acceleration_mps2` |
| imu_dropout | frame-level | health count — **correct here**: a dropout suppresses the reading, so absence *is* the observable |

---

## 3 · Implementation Changes

**`training/closed_loop.py` — instrumentation only, 4 edits.** `_publish_state` already returned the
full payload (`y`, `v`, `a`) after fault corruption; the caller extracted `published["a"]` and
discarded the rest. Two fields added to `TickSample` and populated from values already computed.

**No change to `src/`. No change to ASTRA behaviour.** Verified: integration suite is 82 passed /
2 failed before and after, the same two pre-existing guard-threshold failures.

**`benchmarks/discriminability.py`** — L1 resolved per scenario from a channel map.

---

## 4 · Corrected n = 1 Results

| scenario | L1 | L2a | L2b | L3 | L6 | L7 | L8 | A(f) |
|---|--:|--:|--:|--:|--:|--:|--:|:--:|
| imu_dropout | 0.998 | 0.675 | 0.931 | 0.676 | — | **0.505** | 0.988 | L7 |
| position_bias | **1.000** | **0.500** | 0.500 | 0.500 | — | 0.500 | 0.500 | **L2a** |
| position_drift | **0.970** | **0.500** | 0.500 | 0.500 | — | 0.500 | 0.500 | **L2a** |
| speed_stuck | **0.927** | 0.564 | 0.512 | 0.562 | — | 0.500 | 0.500 | **L2a** |
| speed_bias | **1.000** | 0.508 | 0.692 | 0.504 | — | 0.500 | 0.500 | **L2a** |
| lateral_noise | 0.504 | **0.982** | 0.906 | 0.981 | — | 0.833 | 0.870 | L1 |

---

## 5 · Old vs Corrected

| Scenario | Old L1 | New L1 | Old A(f) | New A(f) | Prior conclusion |
|---|--:|--:|:--:|:--:|---|
| position_bias | 0.500 | **1.000** | L1 | **L2a** | **INVALIDATED** |
| position_drift | 0.500 | **0.970** | L1 | **L2a** | **INVALIDATED** |
| speed_stuck | 0.500 | **0.927** | L1 | **L2a** | **INVALIDATED** |
| speed_bias | 0.500 | **1.000** | L1 | **L2a** | **INVALIDATED** |
| lateral_noise | 0.500 | 0.504 | L1 | L1 | UNCHANGED |
| imu_dropout | 0.998 | 0.998 | L7 | L7 | VALID |

Downstream stages L2a–L8 are **byte-identical** across both runs, as they must be — only L1 changed.

**The previous NO-GO was caused entirely by the measurement defect.** Four of six rows reverse.

---

## 6 · Fault-by-Fault Behaviour *(exploratory at n = 1)*

**ABSORBED — 4 of 6.** `position_bias` (1.000 → 0.500), `position_drift` (0.970 → 0.500),
`speed_bias` (1.000 → 0.508), `speed_stuck` (0.927 → 0.564). Near-perfect separation at the raw
sensing boundary, at or near chance immediately after estimation, and flat through every downstream
stage. **All four share `A(f) = L2a`.**

**NON-MONOTONIC — `imu_dropout`.** 0.998 at L1, 0.675 at L2a, recovers to 0.931 at L2b, **0.505 at
the gates**, 0.988 at the fail-safe. The gates are at chance on a fault sensing separates almost
perfectly; the fail-safe responds because it reads L1 directly rather than through the estimator.

**EMERGENT — `lateral_noise`.** 0.504 at L1, 0.982 at L2a. Discriminability appears downstream.
**Caveat in §8.**

---

## 7 · Absorption-Point Behaviour

`A(f) = L2a` for all four absorbed faults — a **consistent** absorption point across two different
fault kinds (bias, drift, stuck-at) on two different channels (position, speed).

`A(f)` is **not well-posed** for the other two and is not forced:

- `imu_dropout` crosses the threshold at L7 but recovers at L8 → **NO UNIQUE A(f)**, the curve is
  non-monotonic.
- `lateral_noise` starts below the threshold and rises → **NO UNIQUE A(f)**, "absorption" is the
  wrong frame for an emergent fault.

---

## 8 · Measurement Validity

**Resolved:** L1 now measures the raw observable for every fault.

**Outstanding — one specific issue.** `lateral_noise` is a **variance** fault: `NOISE_BURST` adds
zero-mean Gaussian noise. AUC on raw values detects a **location** shift, not a **dispersion** change,
so `D_L1 = 0.504` may be a property of the statistic rather than of the signal. The correct `T_L1`
for a variance fault is a windowed dispersion measure. **This affects one of six faults and does not
touch the four-fault absorbed result.**

**Also outstanding:** `live_score` is `None` throughout, so L6 was never measured — consistent with
OD-8, but it means the profile has a hole at the conformal gate.

---

## 9 · Scientific Interpretation

Four faults are **perfectly or near-perfectly separable at the raw sensing boundary** and fall to
chance at the first post-estimation statistic, remaining there through every downstream monitor. The
effect is large (0.93–1.00 → 0.50–0.56), consistent across two fault kinds and two channels, and
lands at the same stage each time.

**Stated within the evidence:** *the evaluated downstream representations do not retain discriminative
evidence of these faults.* Not "information is destroyed" — this experiment measures discriminability
under specific statistics, not information content.

---

## 10 · Limitations

n = 1 · one policy · one plant · no CIs reported in the table (single seed) · L6 unmeasured ·
`lateral_noise` L1 statistic mis-specified for a variance fault · stage statistics are one choice
among several, and a different choice could move `D_s`.

---

## 11 · C1 Assessment

| Criterion | Finding |
|---|---|
| **Magnitude** | Large. 1.000 → 0.500 is the maximum possible collapse |
| **Consistency** | 4 of 6 faults, two kinds, two channels, same `A(f) = L2a` |
| **Structural meaning** | The collapse lands exactly at the estimator, which is the transformation the hypothesis names — not at an arbitrary stage |
| **Measurement validity** | L1 corrected and verified; one residual issue confined to one fault |
| **Non-monotonic behaviour** | Present and retained: `imu_dropout` recovers, `lateral_noise` emerges |

**C1: PARTIALLY SUPPORTED at n = 1.** The stage-dependent collapse is real, large and consistent for
the absorbed class. It is *not* universal — two faults behave differently, and that heterogeneity is
a finding rather than noise.

---

## 12 · Decision

# GO_TO_30_SEEDS

Four faults show the predicted pattern with the largest effect the metric can express, at a
consistent absorption point, after a verified measurement correction. That is sufficient to justify
the compute.

Not GO on C1 itself — one seed cannot establish reproducibility. The decision is to **scale the
measurement**, not to accept the claim.

---

## 13 · Conditions for the Next Stage

1. Fix the `lateral_noise` L1 statistic to a windowed dispersion measure **before** the sweep.
2. Determine why `live_score` is `None` so L6 enters the profile, or record the hole explicitly.
3. Report bootstrap CIs per cell; at 30 seeds the unit is the seed, not the tick.
4. Re-run the corrected n = 1 on the **second policy** first — if `A(f) = L2a` does not hold there,
   stop before the full sweep.

---

## 14 · Dataset Readiness

comma2k19 remains **CONDITIONAL GO**, four conditions outstanding (timestamp precision, storage,
calibration, drive identity). **Not started** — correct, since the phenomenon it would externally
validate is only now established at n = 1.

---

## 15 · CARLA Status

**Not started.** Correct. CARLA remains downstream of the 30-seed evidence and H7.

---

## 16 · Exact Next Action

**Re-run the corrected n = 1 profile against the second policy checkpoint** (`var/policy/long.pt` or
another regenerated policy), comparing `A(f)` per fault.

Ten minutes. If the four absorbed faults again land at `A(f) = L2a`, the phenomenon is
policy-independent and the 30-seed sweep is justified. If they do not, the sweep would measure a
property of one policy and must not be run.
