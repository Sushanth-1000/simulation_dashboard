# E17 — Position Faults Re-Run: Does the Central Phenomenon Survive?

**1 September 2026** · 720 runs · 30 seeds × 3 policies × 2 conditions × 2 faults × 2 arms
**Raw** `results/E17_POSITION/position_runs.json` · **Analysis** `results/E17_POSITION/analysis.json`

# Answer: NO.

---

## 1 · What changed

`FaultInjector` cannot reach the position channel: `_publish_state` regenerates `y` per channel
from `plant._state[1]` whenever redundant sensing is active, which it is by default since ADR-0033.

Injection was moved to **`RedundantSensing.offset(modality, tick)`** — the per-channel path ADR-0033
intends. Two harness fields were added: `bias` (a constant offset; the field previously supported
only linear drift) and `also_faulted` (more than one lying channel). **No change to `src/astra/`.**
Backward compatibility verified: drift-only behaviour is bit-identical.

Severities are unchanged from `fault_study.py` — **1.0 m bias, 2.0 m final drift** over the same
200-tick window.

## 2 · Two conditions, because they answer different questions

Position is fused as the **median of three readings** (IMU, GPS, LIDAR).

| | lying channels | what the median does | what it tests |
|---|---|---|---|
| **R1** | IMU | rejects the liar | **redundancy** |
| **R2** | IMU + GPS | follows the liars | **absorption** |

Only R2 can test absorption, because only R2 delivers a fault to the estimator. R1 is the control
that separates *"redundancy rejected it"* from *"the fault failed to arrive again"* — without it a
null result would be uninterpretable in exactly the way the original one was.

**Integrity: the fault reached the estimator in 720/720 runs.** The failure mode that invalidated the
original result cannot recur silently here.

## 3 · Result

Median `D_s` across 30 seeds.

### R2 — two lying channels (the absorption test)

| policy | fault | L1 | **L2a** | L2b | L3 | L6 | L7 | L8 |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| P1 | position_bias | 0.978 | **0.796** | 0.923 | 0.796 | 0.900 | 0.913 | **0.968** |
| P1 | position_drift | 0.933 | **0.767** | 0.864 | 0.767 | 0.639 | 0.623 | 0.786 |
| P2 | position_bias | 0.515 | **0.675** | 1.000 | 0.675 | 0.978 | 0.504 | 0.500 |
| P2 | position_drift | 0.508 | **0.655** | 0.971 | 0.656 | 0.930 | 0.501 | 0.500 |
| P3 | position_bias | 0.978 | **0.797** | 0.754 | 0.797 | 0.957 | 0.873 | **0.968** |
| P3 | position_drift | 0.925 | **0.741** | 0.871 | 0.741 | 0.801 | 0.669 | 0.786 |

### Absorption verdict — all 12 cells

| condition | policy | fault | `D_L1` | `D_L2a` [BCa 95 % CI] | absorbed? |
|---|:--:|---|--:|---|:--:|
| R1 | P1 | position_bias | 0.859 | 0.756 [0.738, 0.766] | **NO** |
| R1 | P1 | position_drift | 0.659 | 0.724 [0.711, 0.739] | **NO** |
| R1 | P2 | position_bias | 0.504 | 0.640 [0.611, 0.646] | **NO** |
| R1 | P2 | position_drift | 0.504 | 0.618 [0.592, 0.628] | **NO** |
| R1 | P3 | position_bias | 0.656 | 0.762 [0.749, 0.774] | **NO** |
| R1 | P3 | position_drift | 0.548 | 0.714 [0.701, 0.725] | **NO** |
| R2 | P1 | position_bias | 0.978 | 0.796 [0.782, 0.815] | **NO** |
| R2 | P1 | position_drift | 0.933 | 0.767 [0.756, 0.779] | **NO** |
| R2 | P2 | position_bias | 0.515 | 0.675 [0.654, 0.694] | **NO** |
| R2 | P2 | position_drift | 0.508 | 0.655 [0.644, 0.672] | **NO** |
| R2 | P3 | position_bias | 0.978 | 0.797 [0.789, 0.802] | **NO** |
| R2 | P3 | position_drift | 0.925 | 0.741 [0.735, 0.749] | **NO** |

**Absorbed at L2a: 0 of 12.** Every CI sits far above the 0.60 threshold. Not one cell is close.

## 4 · Interpretation

**The original `D_L2a = 0.500` was the artefact, entirely.** With a fault that actually arrives,
position-fault evidence **survives** estimation: `D_L2a` = 0.618–0.797. There is no collapse.

Two further observations, both from valid data:

**Discriminability sometimes rises after estimation.** Under R1, `D_L1` is 0.504–0.859 while
`D_L2a` is 0.618–0.762 — *higher*. The median rejects the lying channel at the sensor level, so the
raw reading looks close to clean, but the estimator still registers the inter-channel disagreement.
**The estimator is more sensitive to a lying channel than the fused sensor value is.** That inverts
the assumed direction of information flow and is worth a designed experiment.

**The fail-safe responds strongly on P1 and P3** — `D_L8` = 0.968 for `position_bias`, 0.786 for
`position_drift`. On P2 it sits at 0.500. That is ASTRA behaving as intended on two of three
policies, on a fault whose delivery is verified.

## 5 · L6 headroom on the corrected faults

| condition | policy | fault | shift | headroom | ratio | fires? |
|---|:--:|---|--:|--:|--:|:--:|
| R2 | P1 | position_bias | 0.6885 | 1.7115 | 0.402 | no |
| R2 | P3 | position_bias | 0.8371 | 2.0134 | 0.416 | no |
| R2 | **P2** | position_bias | 0.6913 | **0.1721** | **17.59** | yes |
| R2 | **P2** | position_drift | 0.6053 | **0.1724** | **5.40** | yes |

The same OD-8 split as every other fault: **unreachable on P1 and P3, permanently tripped on P2.**
Independent confirmation on a new fault class — the calibration defect is not fault-specific.

## 6 · Consequence for C1

# C1: NOT SUPPORTED as a general claim

| fault | injection | absorbed at L2a? |
|---|:--:|---|
| `speed_stuck` | valid | **YES — P1, well-posed 30/30, the only clean case** |
| `speed_bias` | valid | at L2a but 0/30 well-posed — L6 statistic recovers |
| `imu_dropout` | valid | no — non-monotonic |
| `lateral_noise` | valid | no — persistent |
| `position_bias` | **valid (corrected)** | **NO — 0.675–0.797** |
| `position_drift` | **valid (corrected)** | **NO — 0.655–0.767** |

**One fault of six, on one policy of three, shows a clean well-posed absorption point.**

The defensible claim is no longer *"faults are absorbed at the estimator."* It is:

> **Fault observability is strongly heterogeneous across fault types. A single absorption point is
> ill-posed for five of six faults. One fault-policy combination shows a stable, well-posed
> absorption at the estimator; the others weaken, recover, oscillate, persist, or survive intact.**

That is a smaller claim than the project started with, and it is the one the data supports.

## 7 · What this does to the paper

**The heterogeneity is now the finding**, not a caveat attached to an absorption result. That is
defensible, novel-ish, and reproducible at n = 30 — but it is a different paper from the one v18
drafts, and it needs the monitor-placement consequence (H7) to be more than a descriptive taxonomy.

**Honest position:** the project's headline claim has not survived correction. What has survived is
a well-audited method, a reproducible heterogeneity result, one clean absorption case, and two
architecture-level findings (POSITION_Y inertness, OD-8 miscalibration in both directions). That is
a real contribution and a weaker one than was hoped.

## 8 · Reassessment of gating

**H7 becomes more important, not less.** Without absorption as the headline, monitor placement is
the contribution that could carry a paper. But it remains blocked by OD-8: two policies cannot fire
the gate, one fires constantly.

**OD-8 is now the top priority.** It blocks H7; it is confirmed across every fault including this
new class; and it is a concrete, well-characterised, fixable defect.
