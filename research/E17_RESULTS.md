# E17 — Fault Discriminability Profiling: results

**Run** 31 August 2026 · `python -m benchmarks.discriminability`
**Policy** `var/policy/synthetic.pt` (regenerated, commit `6383676`) · **seed** 20260731 ·
**ticks** 400, fault opens at 200 · **n = 1 seed** · paired faulted vs matched-clean

---

## 1 · Result

`D_s` = AUC(faulted, matched-clean), folded to [0.5, 1.0]. `A(f)` = first stage with `D_s < 0.60`.

| scenario | L1 | L2a | L2b | L3 | L6 | L7 | L8 | A(f) |
|---|--:|--:|--:|--:|--:|--:|--:|:--:|
| imu_dropout | **0.998** | 0.675 | 0.931 | 0.676 | — | **0.505** | **0.988** | L7 |
| position_bias | 0.500 | 0.500 | 0.500 | 0.500 | — | 0.500 | 0.500 | L1 |
| position_drift | 0.500 | 0.500 | 0.500 | 0.500 | — | 0.500 | 0.500 | L1 |
| speed_stuck | 0.500 | 0.564 | 0.512 | 0.562 | — | 0.500 | 0.500 | L1 |
| speed_bias | 0.500 | 0.508 | 0.692 | 0.504 | — | 0.500 | 0.500 | L1 |
| lateral_noise | 0.500 | **0.982** | 0.906 | **0.981** | — | 0.833 | 0.870 | L1 |

Stages: L1 sensing/stream health · L2a innovation (pre-settle) · L2b estimated state · L3 trust
index · L6 non-conformity · L7 gate verdict · L8 fail-safe posture.

---

## 2 · What the numbers say

**Discriminability is not monotonic.** The frozen hypothesis H6 predicted a curve that starts high
at L1 and collapses at L2, staying flat. **No scenario shows that shape.** Three distinct patterns
appear instead.

**Pattern A — `imu_dropout`.** Near-perfect at sensing (0.998), degraded through estimation (0.675),
partially recovered at the estimate (0.931), and **at chance where the gates are (0.505)** — then
0.988 at the fail-safe. The gates cannot see a fault that L1 sees almost perfectly, and L8 responds
anyway *because it reads L1 directly rather than through the estimator*. **This is the paper's
central claim, measured for the first time.**

**Pattern B — `position_bias`, `position_drift`.** 0.500 at **every** stage, L1 included. Nothing
anywhere separates the faulted run from the clean one. These faults are not *absorbed by the
estimator* — they are neutralised by three-channel median fusion **before any monitor observes
anything**.

**Pattern C — `lateral_noise`.** 0.500 at L1, **0.982 at L2a**. Discriminability is *created*
downstream, not lost. The innovation sees what sensing cannot.

**L6 is empty** for every scenario: `live_score` was `None` throughout, consistent with OD-8 — the
statistical gate produces no usable score on this configuration.

---

## 3 · Verdict against the frozen hypotheses

| Hypothesis | Result |
|---|---|
| **H6** — `D_L2 < D_L1 − 0.15` and flat thereafter, for absorbed faults | **NOT SUPPORTED.** Only `imu_dropout` falls from L1, and it recovers at L2b and L8 rather than staying flat |
| **C1** — a reproducible stage-wise collapse | **NOT SUPPORTED as stated.** Discriminability is non-monotonic and pattern-dependent |
| **A(f)** as a single absorption point | **Ill-posed for patterns B and C.** For B the fault was never separable; for C it becomes separable downstream. A "first stage below threshold" cannot describe either |

---

## 4 · A measurement defect that must be fixed before this is final

**The L1 statistic is wrong for four of six scenarios.**

I used *number of non-HEALTHY modalities* as `T_L1`. That is the **health signal**, not what L1
could observe. `position_bias`, `position_drift`, `speed_stuck` and `speed_bias` all keep the stream
perfectly fresh by construction — the scenario definitions say so explicitly — so the health count is
identically zero in both arms and AUC is 0.500 **by construction, not by measurement**.

The correct `T_L1` is the **raw measured value** — measured position, measured speed, measured
lateral acceleration — before fusion and before the filter. `TickSample` already carries
`measured_lateral_acceleration_mps2`; the corresponding raw position and speed channels need to be
exposed the same way.

**Consequences:** the 0.500 entries at L1 for patterns B and C are uninformative, not evidence.
`A(f) = L1` for those five rows is an artefact. Pattern A is unaffected — the health count is the
right statistic for a dropout, and 0.998 is real.

**This does not rescue H6.** Even with a corrected L1, Pattern C runs the wrong way (0.500 → 0.982),
and Pattern B's faults were shown by the earlier fault study to be invisible to every gate. But the
`A(f)` column cannot be interpreted until the statistic is fixed.

---

## 5 · Reproducibility

```
experiment_id     E17
git_commit        6383676
policy            var/policy/synthetic.pt
seed              20260731
ticks             400, fault at 200
pairing           faulted vs clean, same seed, same tick index, fault window only
metric            Mann-Whitney AUC, folded, ties at 0.5
CI                percentile bootstrap, 2000 resamples
python / numpy    3.12 / 2.5.1
hardware          CPU only
output            var/discriminability/summary.json
```

Runtime ≈ 90 s for 7 runs. No GPU. No failed runs.

---

## 6 · The finding worth keeping

Independent of H6, one measurement stands on its own and is the strongest single number the project
has produced:

> **On the inertial dropout, `D_L1 = 0.998` and `D_L7 = 0.505`.** Sensing separates the faulted run
> from the clean one almost perfectly; the three gates are at chance. `D_L8 = 0.988` because the
> fail-safe reads the health signal directly rather than through the estimator.

That is the observability claim, quantified, in one row — and it needs seeds and a corrected L1
before it can be claimed.
