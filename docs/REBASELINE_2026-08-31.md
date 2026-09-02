# Re-baseline — 31 August 2026

**Why this document exists.** The committed policy `var/policy/synthetic.pt` was committed on
**9 August** with the message *"Commit the corpus and policy the measurements were actually taken
with."* It predates ADR-0030, ADR-0032 and ADR-0033. Measured on 31 August it does not drive:
`make artifacts-check` reported *"every one of 200 ticks was vetoed and the final speed is 0.0300 m/s"*,
and all five checkpoints in `var/policy/` failed identically. Five integration tests failed with it.

Artefacts were regenerated with `make artifacts` (twin → corpus → policy, in order). The check now
reports *"twin, corpus and policy present; the vehicle drives"*, and the suite is **3,063 passed,
2 failed**.

**Every `[M-syn]` figure below was re-measured through the regenerated artefacts.** The policy is a
different policy from the one that produced the published numbers, so this is a *re-measurement*,
not a reproduction. Where a figure moved, both values are given.

---

## 1 · The finding that governs how the rest is read

Two classes of result emerged, and the credibility matrix currently has no marker that distinguishes
them.

**Class A — reproduced on an independently trained policy.** Structural, and did not depend on which
policy was in the loop.

**Class B — moved substantially.** Every absolute deviation, every veto count, and the entire
shadow-detector table.

This is the first direct evidence in the project for why single-seed figures cannot carry an
architectural claim. It is also the answer to the referee's n=1 objection: not an argument, a
measurement.

---

## 2 · Class A — reproduced

| Finding | 9 Aug artefacts (published) | 31 Aug artefacts | Status |
|---|---|---|---|
| Common-cause blind spot: faults whose veto count equals the control's | 4 of 6 (1 veto each) | **4 of 6 (2 vetoes each)** | reproduced |
| Steps outside NOMINAL, `imu_dropout` | 195 | **195** | reproduced exactly |
| Health escalation, `imu_dropout` | DEGRADED +5, LIMP +15 | **DEGRADED +5, LIMP +15** | reproduced exactly |
| HALT reached on `imu_dropout` | no (peak phi 40) | **no (peak phi 40)** | reproduced |
| Gates that never object | 2 of 3, 0 abstentions | **2 of 3, 0 abstentions** | reproduced |
| Ablation: L6 off ≡ governed in every cell | yes | **yes** | reproduced |
| Ablation: L7a off ≡ governed in every cell | yes | **yes** | reproduced |
| Ablation: L7b off zeroes every veto | yes | **yes** | reproduced |
| Redundancy: peak estimator error, single / 1 m bias | 1.1805 m | **1.1655 m** | reproduced, 1.3% |
| Redundancy: peak estimator error, redundant / 1 m bias | 0.1323 m | **0.1338 m** | reproduced, 1.1% |
| Redundancy: the two redundant arms indistinguishable to 4 dp | yes | **yes** | reproduced |
| OD-8: live scores outside the corpus, `URBAN_CLEAR` | 0.0% inside | **0.0% inside** | reproduced |
| Command issued on every tick, both arms | yes | **yes** | reproduced |

**Proposed marker.** The matrix has `[M-ext]`, `[M-syn]`, `[M-code]`, `[E]`, `[NOT DONE]`, and no way
to record *"re-measured through independently regenerated artefacts and held."* Rows in this table
warrant something stronger than `[M-syn]` and weaker than `[M-ext]`. Suggest **`[M-syn×2]`**.

---

## 3 · Class B — moved

### 3.1 · Fault study, governed

| scenario | published final \|dev\| | **31 Aug** | published vetoes | **31 Aug** |
|---|---|---|---|---|
| control | 0.017 m | **0.142 m** | 1 | **2** |
| imu_dropout | 0.062 m | **0.089 m** | 18 | **85** |
| position_bias | 0.017 m | **0.142 m** | 1 | **2** |
| position_drift | 0.017 m | **0.142 m** | 1 | **2** |
| speed_stuck | 0.024 m | **0.130 m** | 1 | **2** |
| speed_bias | 0.059 m | **0.108 m** | 1 | **2** |
| lateral_noise | 1.307 m | **0.235 m** | 126 | **147** |

### 3.2 · Governed against ungoverned — the headline changes

| scenario | ASTRA | Core-A raw | ticks outside corridor (raw) |
|---|---|---|---|
| control | 0.142 m | 0.110 m | 0 |
| imu_dropout | **0.089 m** | **0.163 m** | 0 |
| position_bias | **0.142 m** | **0.896 m** | 0 |
| position_drift | **0.142 m** | **1.807 m** | **8** |
| speed_stuck | 0.130 m | 0.111 m | 0 |
| speed_bias | 0.108 m | 0.076 m | 0 |
| lateral_noise | 0.235 m | 0.169 m | 0 |

**Three consequences, and none is cosmetic.**

The published `imu_dropout` comparison was **0.062 m against 1.707 m**, a 27-fold improvement and the
paper's single most-quoted figure. It is now **0.089 m against 0.163 m** — less than twofold. The
27× claim does not survive re-measurement.

**`position_drift` is the only row where the ungoverned vehicle leaves the corridor**, for 8 ticks.
Governance prevents a corridor departure there. That is now the clearest single-scenario case for the
architecture, and it was not the scenario the paper led with.

**ASTRA is worse than raw Core-A on four of seven rows** — control, `speed_stuck`, `speed_bias` and
`lateral_noise`. The published table showed it better on six of seven. The honest summary is now:
governance helps on the three sensor-corruption faults and costs a little on the rest.

### 3.3 · Gate census

| gate | published | **31 Aug** |
|---|---|---|
| STATISTICAL | 2800 PASS / 0 VETO / 0 ABSTAIN | **2800 / 0 / 0** |
| PHYSICAL | 2651 / **149** / 0 | **2558 / 242 / 0** |
| DETERMINISTIC | 2800 / 0 / 0 | **2800 / 0 / 0** |

Single reason code, `LATERAL_JERK_EXCEEDS_LIMIT`, on all 242. The **149** figure appears throughout
the manuscript and must be replaced.

### 3.4 · OD-8, exchangeability — the finding holds, the numbers move

| | published | **31 Aug** |
|---|---|---|
| `URBAN_CLEAR` corpus | 3.8758 – 5.4312 | **3.8776 – 5.4380** |
| `URBAN_CLEAR` live | 3.3648 – 3.4083 | **3.6133 – 3.7364** |
| overlap | zero | **0.0%, NO OVERLAP** |

The corpus reproduces to four significant figures. The live range moved. **OD-8 STANDS.**

### 3.5 · Shadow detectors — the published table is wrong

Measured, all seven arms:

| scenario | health | innovation | trust |
|---|---|---|---|
| control | silent | silent | **FALSE ALARM** |
| imu_dropout | **+5 ticks** | silent | **+6 ticks** |
| position_bias | silent | silent | +55 ticks |
| position_drift | silent | silent | **+55 ticks** |
| speed_stuck | silent | silent | +55 ticks |
| speed_bias | silent | silent | +55 ticks |
| lateral_noise | silent | silent | +4 ticks |

Against the published table: innovation was reported firing at +84 on `lateral_noise` — it is
**silent on all seven arms**. Trust was reported as `none` on `position_drift` — it fires at **+55**.
False alarms on control were reported as **0** for all three signals — trust raises a **FALSE ALARM
on the clean control**.

**The correction runs in the architecture's favour.** Stream health fires on exactly the one fault it
can observe, at +5, and is silent on the other six with no false alarm. The trust index fires on
every arm including the clean one. The published table showed a tie at +5; the measurement shows a
specific upstream signal against an indiscriminate downstream one, with health first by one tick.

### 3.6 · Ablation — a published result reverses

Final \|deviation\|, metres:

| profile | control | imu_dropout | position_bias | position_drift | speed_stuck | speed_bias | lateral_noise |
|---|---|---|---|---|---|---|---|
| governed | 0.142 | 0.089 | 0.142 | 0.142 | 0.130 | 0.108 | **0.235** |
| L6 off | 0.142 | 0.089 | 0.142 | 0.142 | 0.130 | 0.108 | 0.235 |
| L7b off | 0.142 | **0.105** | 0.142 | 0.142 | 0.130 | 0.108 | **0.719** |
| L7a off | 0.142 | 0.089 | 0.142 | 0.142 | 0.130 | 0.108 | 0.235 |

The published result was that disarming L7b **improves** `lateral_noise`, 1.307 m → 0.138 m. It was
the strongest single piece of evidence against the architecture. **Re-measured, disarming L7b makes
it worse: 0.235 m → 0.719 m.** The physical gate is now load-bearing on that scenario rather than
harmful on it.

Taken with §3.1, the lateral-noise degradation shrinks from 8.8× to 1.4× and the mechanism that was
blamed for it now helps. **The published negative result is more likely an artefact of the 9 August
policy than a property of the architecture.** It should not be removed from the manuscript on this
evidence alone — one policy replacing another is still n=1 — but it can no longer be reported as
established.

---

## 4 · What must change in the manuscript

| Claim | Action |
|---|---|
| 27× improvement on `imu_dropout` (0.062 vs 1.707) | **Replace.** Now 0.089 vs 0.163 |
| 149 physical vetoes | **Replace** with 242 |
| Every figure in Tables 3, 5, 6 | **Re-measure** |
| Table 4, shadow detectors | **Rewrite.** Three of its cells are wrong; the correction strengthens the thesis |
| "Better on every fault except lateral noise" | **Replace.** Worse on four of seven |
| Lateral-noise degradation as an established finding | **Downgrade** to unresolved and policy-dependent |
| Disarming L7b improves lateral noise | **Withdraw.** Reverses on re-measurement |
| OD-8 exchangeability violation | **Keep**, update the live range |
| Redundancy 1.1805 → 0.1323 | **Keep**, update to 1.1655 → 0.1338 |
| Common-cause blind spot | **Keep and strengthen** — reproduced on a new policy |

---

## 5 · Outstanding

- Two integration tests still fail — `test_not_one_gate_fires_while_it_happens` (control produces a
  veto at tick 239) and `test_the_posture_escalates_on_sensor_health_rather_than_on_a_verdict`
  (asserts 15 < 10). Both are guard thresholds baselined to the 9 August policy and need
  re-baselining, not repair.
- `import-linter` is absent from the environment, so `test_layering.py` **skipped**. The "twelve
  contracts, 0 broken" claim is currently unverified.
- Soak (100,000 ticks), per-modality degradation and latency were not re-run.
- Nothing here moves any row to `[M-ext]`. That remains 0 of 30.

---

## 6 · Reproduce this document

```bash
py -3.12 -m venv .venv
.venv/Scripts/pip install -e ".[estimation,learning]" pytest hypothesis
.venv/Scripts/python -m tools.check_artifacts      # must say "the vehicle drives"
.venv/Scripts/python -m benchmarks.fault_study
.venv/Scripts/python -m benchmarks.comparison
.venv/Scripts/python -m benchmarks.ablation
.venv/Scripts/python -m benchmarks.gate_census
.venv/Scripts/python -m benchmarks.exchangeability
.venv/Scripts/python -m benchmarks.arms
```

If `check_artifacts` refuses, run `make artifacts` first. Note that doing so trains a **new** policy,
and §1 is the reason the figures will move again.
