# E17 — Validation Report

**1 September 2026** · audit of the completed 30-seed sweep against fault-injection integrity
**Companions** `E17_FAULT_INTEGRITY.md` · `E17_FAILURES_AND_INVALID_RUNS.md` · `E17_INVALIDATION.md`
**Artifacts** `results/E17_FINAL/*.csv` · `results/E17_INTEGRITY/*.json`

---

## 1 · Repository audit — what E17 actually runs

| question | answer, from the code |
|---|---|
| **what runs** | `benchmarks/discriminability.py` drives `training/closed_loop.drive_closed_loop`, clean and faulted arms per scenario, 400 ticks, fault from tick 200 |
| **faults implemented** | **6 scenarios** in `benchmarks/fault_study.py` — not the 13 in `ASTRA_RESEARCH_FREEZE.md`, which is a plan |
| **severities implemented** | **one per fault**, hardcoded: bias 1.0 m, drift 2.0 m final, speed bias 3.0 m/s, noise ×25, stuck/dropout unparameterised. **There is no severity sweep.** `FaultSpec.magnitude` exists but scenarios fix it |
| **policies implemented** | 5 checkpoints in `var/policy/`; 3 usable — `synthetic` (P1), `long` (P2), `jerkscaled` (P3). `dt002`/`dt005` not exercised |
| **fault taxonomy** | `FaultKind` = {BIAS, DRIFT, STUCK_AT, NOISE_BURST, DROPOUT} × `FaultChannel` = {`y`, `v`, `a`} |
| **pipeline** | sensor bus → L1 health → L2 dual-rate UKF → L3 trust → L4 policy → L5 twin → L6 conformal → L7 deterministic/physical → L8 fail-safe → L9 arbitration |
| **seeds** | `20260731 + i`, i = 0…29; injector draws from an offset seed so a clean run is bit-identical to a faulted one outside the window |
| **stage statistics** | L1 raw channel (per-scenario), L2a innovation Mahalanobis, L2b estimated lateral, L3 trust index, L6 conformal non-conformity, L7 veto flag, L8 posture ordinal |

## 2 · Metric audit — §4

`D_s(f) = AUC(T_s | faulted, T_s | matched-clean)`, folded to `[0.5, 1.0]`. **0.5 is chance-level
discriminability, not "50 % accuracy".** The fold means direction is discarded and only separation is
measured; 0.5 is the floor, which is why hitting it exactly is a degeneracy signal rather than a
result.

| fault type | statistic used | appropriate? | why |
|---|---|:--:|---|
| BIAS (`position_bias`, `speed_bias`) | raw channel value | **yes** | location shift; AUC on values is location-sensitive |
| DRIFT (`position_drift`) | raw channel value | **yes** | monotone location shift within the window |
| STUCK_AT (`speed_stuck`) | raw channel value | **partly** | a held value differs in *location* only by luck; the theoretically correct statistic is temporal variability. **Flagged as a limitation**, not changed — changing it now would be changing a metric after seeing results |
| NOISE_BURST (`lateral_noise`) | **rolling std, window 10** | **yes** | zero-mean noise moves dispersion, not location. Corrected 31 Aug; window fixed at 10 to match `PATIENCE` in `training/redundant.py`, a pre-existing constant |
| DROPOUT (`imu_dropout`) | stream-health count | **yes** | absence is the observable |

**One metric is theoretically imperfect (`speed_stuck`) and is reported as such rather than
silently swapped.** Its D_L1 is nonetheless high (0.96–0.99), so the fault is empirically separable
at sensing; the concern is that a variability statistic would likely be *higher* still.

## 3 · Fault-injection integrity — §2, §3

Full detail in `E17_FAULT_INTEGRITY.md`. Summary:

| Fault | Reaches L1? | Reaches estimator? | Ground-truth bypass? | Verdict |
|---|:--:|:--:|:--:|:--:|
| `imu_dropout` | yes | yes | no | **VALID** |
| **`position_bias`** | **NO** | **NO** | **YES** | **INVALID** |
| **`position_drift`** | **NO** | **NO** | **YES** | **INVALID** |
| `speed_stuck` | yes | yes | no | **VALID** |
| `speed_bias` | yes | yes | no | **VALID** |
| `lateral_noise` | yes | yes | no | **VALID** |

Consistent across 3 policies × 3 seeds. Root cause: ADR-0033 redundant sensing regenerates the
position channel from `plant._state[1]`. Established causally by Control C.

## 4 · Absorption analysis — §9, on valid faults only

**The distinction §9 demands — genuine absorption vs implementation artifact — is the whole finding.**

| fault | policy | `A(f)` modal | well-posed | mechanism |
|---|:--:|:--:|:--:|---|
| **`speed_stuck`** | **P1** | **L2a 100 %** | **30/30** | **genuine estimator absorption** |
| `speed_stuck` | P3 | L2a 100 % | 8/30 | absorbed at L2a, **recovered at L6** (0.630) |
| `speed_stuck` | P2 | L2b 57 % | 4/30 | unstable — degraded regime |
| `speed_bias` | P1, P3 | L2a 100 % | **0/30** | absorbed at L2a, **strongly recovered at L6** (0.629–0.963) |
| `speed_bias` | P2 | L2a 40 % | 7/30 | unstable |
| `imu_dropout` | all | L7/L2b, 37–60 % | 0–17/30 | **non-monotonic** — no `A(f)` |
| `lateral_noise` | P1, P3 | none | 3–5/30 | **persistent** — never absorbed |
| ~~`position_bias`/`drift`~~ | — | — | — | **implementation artifact — fault never arrived** |

**`speed_stuck` on P1 is the one valid, stable, well-posed absorption result in the study:**
`D_L1` 0.9625 → `D_L2a` 0.5629, 30/30 seeds, sd 0.0077.

### 4.1 · Why discriminability collapses — mechanisms distinguished

- **Estimator fusion** — `speed_stuck` P1: the UKF's speed channel corrects a held reading toward the
  predicted trajectory. Genuine.
- **Conformal recovery** — `speed_bias`: L2a 0.513 → **L6 0.963**. The information was *not*
  destroyed at L2a; a downstream statistic recovers it. This forbids the phrase "information is
  destroyed" anywhere in the write-up. The correct framing is *"the evaluated representation does not
  retain discriminative evidence."*
- **Closed-loop compensation** — new, from Control C: with redundancy off, a 1.0 m position bias
  drives `D_L1` to **0.513** because the vehicle steers to null it. **Absorption can happen at the
  plant, before any ASTRA layer.**
- **Ground-truth regeneration** — the position faults. Pure artifact.

## 5 · The detection-without-response gap

`speed_bias`, P3: `L1 1.000 → L2a 0.513 → L3 0.508 → ` **`L6 0.963`** ` → L7 0.500 → L8 0.500`.
P2 reaches **L6 = 0.994**.

The conformal gate separates faulted from clean at near-perfect accuracy; the deterministic gate and
the fail-safe posture sit at chance. **ASTRA detects this fault and does not act on it.** On a
channel whose integrity is verified. This is the strongest surviving finding in the study.

## 6 · Claim classification — §12

### VALIDATED

1. **`FaultChannel.POSITION_Y` is inert against the driven sensing path** and has been since
   ADR-0033. Demonstrated at the delivered signal, consistent over 9 (policy, seed) pairs,
   established causally by Control C.
2. **`speed_stuck` is absorbed at L2a on P1** — `D` 0.9625 → 0.5629, `A(f) = L2a` well-posed on 30/30
   seeds, sd 0.0077.
3. **A detection-without-response gap exists at L6 → L7/L8** for `speed_bias`, on all three policies.
4. **Fault propagation is heterogeneous.** Four valid faults, four distinct behaviours: absorbed,
   absorbed-then-recovered, non-monotonic, persistent. A single `A(f)` is ill-posed for three of four.
5. **`A(f)` modal agreement overstates stability.** `speed_bias` on P1/P3 shows 100 % modal agreement
   with **0/30** well-posed seeds.
6. **The metric does not manufacture evidence** (Control D: max 0.565 on clean data).

### PARTIALLY VALIDATED

7. **`speed_stuck` absorbs at L2a on P3** — modal 100 %, but only 8/30 well-posed because L6 recovers.
8. **Closed-loop compensation destroys sensor-level discriminability for bias faults** — observed
   once, in Control C, n = 1. A real mechanism, not yet a measured result.

### INVALIDATED

9. ~~"Position faults are absorbed at the estimator, policy-independently."~~ The faults never
   reached the estimator. **C1 as previously stated is NOT ESTABLISHED.**
10. ~~"All 18 falsification checks negative."~~ Sound checks, contaminated data.
11. ~~H-regime.~~ Withdrawn earlier as a Simpson's paradox — within P2, `speed_bias` ρ = **+0.836**
    against a pooled −0.341. That withdrawal stands and is independent of this audit.

### NOT TESTED

12. Position-fault absorption **with a correctly injected fault**. Requires per-channel injection via
    `redundant.offset`. **Not tested is not failed.**
13. Any severity other than the single hardcoded value per fault.
14. The 7 unbuilt faults of the planned 13.
15. Whether the L6 → L7 gap is a wiring defect or intended.
16. Anything outside the synthetic plant. **`[M-ext]` remains 0 of 30.**

## 7 · Readiness verdict — §13

# E17 NEEDS MINOR FIXES

**Why not READY:** two of six faults do not reach the intended pipeline. §13 requires *every*
reported fault to reach it.

**Why not MAJOR or INVALID:** the cause is identified, demonstrated causally, and confined to one
channel. Four faults are integrity-verified with complete, reproducible 30-seed data and 0 failures.
Metrics are audited, seeds reproducible, configuration documented, contaminated runs flagged rather
than deleted, and the surviving conclusions follow from the measurements.

**The minor fix:** inject position faults through `redundant.offset(modality, tick)` — per-channel,
already present, and the path ADR-0033 intends. That makes the *better* experiment possible for the
first time: **one channel lying while two stay honest**, which is what redundancy is for. Roughly a
day, then re-run two faults — not the whole sweep.
