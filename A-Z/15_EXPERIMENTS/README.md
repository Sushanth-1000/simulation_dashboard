# 15 · Experiments

Seventeen benchmarks. Every one of them is a **question**, not a demo — and each
states its question in its first line.

**[FACT]** — the inventory and quoted lines are read from `benchmarks/`.

---

## 15.1 · The inventory

| Benchmark | The question it asks |
|---|---|
| `soak` | *Drive the closed loop for hours and ask whether anything moved* |
| `fault_study` | *What does each gate catch? One injected fault at a time, against a control* |
| `ablation` | *What is each gate worth? Disarm one at a time and re-measure* |
| `comparison` | *ASTRA against raw Core-A, same seed, same fault, side by side* |
| `detectors` | *Candidate answers to OD-9, run with no authority over any verdict* |
| `parity` | *Two candidate answers to a lying sensor, both measured, both refuted* |
| `whiteness` | *Is the innovation sequence white? The fifth candidate against the slow drift* |
| `redundancy` | *Can a second sensor see the lie that four other mechanisms could not?* |
| `effectiveness` | *What would ADR-0020's estimator learn, if anything read it?* |
| `exchangeability` | *Are the live non-conformity scores exchangeable with the corpus that judges them?* |
| `gate_census` | *Which of the three gates actually objects, and to what?* |
| `degradation` | *If this sensor fails, what does the vehicle stop being able to do?* |
| `commissioning` | *What is this vehicle actually certified for? Measure it, do not assume it* |
| `envelope` | *Where is this vehicle repeatedly driving that nothing has certified?* |
| `platform_transfer` | *Does bounded safe exploration survive a platform the twin was never fitted to?* |
| `latency` | *Measure the hot-path latency of the layers that exist* |
| `flake_hunt` | *Run the test suite repeatedly under CPU contention, hunting for flakes* |

**[INTERPRETATION]** Notice how many are phrased as *open* questions rather than
*demonstrations*. `parity`'s first line announces its own refutation. That is the
tell of a measurement culture rather than a demo culture.

---

## 15.2 · The experiments that changed the architecture

### E1 · The 100,000-tick soak — 5 August

**Objective.** Run the complete pipeline for a long time and read the numbers.

**Setup.** All nine layers, clean data, no injected faults, 100,000 ticks.

**Expected.** Nothing in particular. Everything passed.

**Actual.** **Six defects.**

| Metric | Result |
|---|---|
| Lane departure at tick 100,000 | **2,883 m** |
| Commands issued under a blocking verdict | **99,808 / 100,000** |
| Estimator error (lateral) | **2.9 × 10⁶ m** |
| OOD counter at tick 2,000 | 1,508, still climbing |
| Speed held *in HALT* | 17.2 m/s |

**Changed:** ADR-0016 (ABSTAIN, verdict-before-exploration), ADR-0017 (the jerk
veto yields a step), the counter's ceiling, the speed cap bound to an actuator.

**[INTERPRETATION]** The most valuable single experiment the project has run. It
cost nothing to perform and it invalidated more assumptions than everything since.

### E2 · The first injected fault — 9 August

**Objective.** Test the gates against something going wrong on purpose.

**Setup.** `imu_dropout`, 200 ticks, against a clean control on the same seed.

**Expected.** *Some* gate notices.

**Actual — OD-9.** 4.199 m off a 1.75 m lane, corridor bound reading 0.023 m, and
**a verdict trace identical to the control's**.

**Worse on inspection (`E-58`):** the error migrated into an unobserved state —
true heading 0.0686 rad, estimate 0.0017 rad.

**Changed:** ADR-0024, the second counter, and the architecture's most important
arrow.

### E3 · The platform-transfer run

**Objective.** Does bounded safe exploration survive a platform the twin was
never fitted to?

**Actual (`E-83`).** On **two platforms of five** the OOD counter climbed
underneath a correctly-held `SAFE_EXPLORATION` and **halted the vehicle** — weak
acceleration at t398, weak brakes at t404, both ending at 0.00 m/s.

> One event escalated twice, defeating the architecture's distinguishing claim
> **using its own fail-safe machine**.

**Changed:** ADR-0023 — the OOD counter freezes during exploration.

**Re-run 16 August 2026 — the fix holds, and one row deserves attention:**

| platform | exploring | vetoes | final m/s | final \|dev\| | posture |
|---|---|---|---|---|---|
| calibrated | 60 | 3 | 12.30 | 0.036 m | NOMINAL |
| weak acceleration | 540 | 306 | 0.83 | 0.057 m | NOMINAL |
| weak brakes | 600 | 3 | 16.69 | 0.095 m | NOMINAL |
| worn tyres | 60 | 2 | 12.26 | 0.002 m | NOMINAL |
| **sharp steer** | 560 | 586 | 5.25 | **53.756 m** | **LIMP** |

**No platform HALTs. Every one still moves.** That is what ADR-0023 bought, and it
reproduces.

**But `sharp_steer` ends 53.756 m off the lane** — thirty lane-widths — at LIMP,
still driving, and the benchmark's own pass rule counts it as a pass because the
rule tests *posture, motion and speed cap* and **not lane position**. **[OPEN]**
That is either a missing exit criterion or a platform this vehicle should refuse.

*A previous draft of this entry said "held `SAFE_EXPLORATION` for 520 ticks while
the OOD counter climbed 0 → 100". 520 is `E-85`'s **post-fix** exploration count
for weak acceleration, not a pre-fix failure figure; the two were conflated.
Today that count is 540.*

### E4 · The shadow runs — FB2 and FB3

**Objective.** Measure two specified feedback loops **before wiring them**.

**Actual.**

- **FB2** — the twin's non-conformity score fell **40%** in a context where
  nothing changed, while the live score stayed flat to four decimal places
  (`E-39`).
- **FB3** — the veto rate converged to `significance_epsilon` **exactly**, because
  ε of any distribution lies above its own 1−ε quantile (`E-40`).

**Changed:** neither was wired. **Both measurements kept as the evidence for not
wiring them.**

### E5 · The gate census — 15 August

**Objective.** Which gate is actually load-bearing?

**Setup.** 2,800 ticks — the clean arm plus all six faults, a suite built to
break the gates.

**Actual.**

```
STATISTICAL     PASS 2800   VETO 0     ABSTAIN 0
PHYSICAL        PASS 2651   VETO 149   ABSTAIN 0
DETERMINISTIC   PASS 2800   VETO 0     ABSTAIN 0
```

All 149 on one reason code. **ABSTAIN zero everywhere**, so the silent two are
*judging and finding nothing*, not declining.

**Consequence:** bears directly on D-3, the independence claim, and forced a
rewrite of the paper's contribution 2.

---

### E6 · The ablation and the comparison — first run 16 August 2026

Two benchmarks this folder listed in its inventory and had never actually
executed. Both produced results that change what the folder says.

**The ablation — disarm one gate at a time.** Vetoes, then final deviation:

| profile | control | imu_dropout | position_bias | position_drift | speed_stuck | speed_bias | lateral_noise |
|---|---|---|---|---|---|---|---|
| governed | 1 | 18 | 1 | 1 | 1 | 1 | **126** |
| L6 off | 1 | 18 | 1 | 1 | 1 | 1 | 126 |
| **L7b off** | **0** | **0** | **0** | **0** | **0** | **0** | **0** |
| L7a off | 1 | 18 | 1 | 1 | 1 | 1 | 126 |

| profile | control | imu_dropout | lateral_noise |
|---|---|---|---|
| governed | 0.017 m | 0.062 m | **1.307 m** |
| **L7b off** | 0.017 m | 0.061 m | **0.138 m** |

**Disarming L7b makes the vehicle nearly ten times better on `lateral_noise`** —
1.307 m against 0.138 m. The physical gate issues 126 vetoes on that arm, and the
vetoes are what put the vehicle 1.3 m off the lane.

**[INTERPRETATION]** This is the sharpest single result in the folder, and it cuts
against the architecture. On one fault the governance is not merely inert — it is
**the cause of the departure**. The likely mechanism is ADR-0017's rate limiter:
a noisy lateral channel produces jerk vetoes, each veto yields the largest
admissible step rather than the demanded one, and the correction never completes.
That is the OD-17 latch shape reappearing on a fault it was not tested against.
**[OPEN]** — not diagnosed, and it deserves an ADR.

**Also worth stating:** `L6 off` and `L7a off` are **bit-identical to governed in
every cell**. Two of three gates contribute nothing measurable, which is E-162
seen from the other direction.

**The comparison — ASTRA against raw Core-A**, same seed, same fault:

| scenario | ASTRA | Core-A raw |
|---|---|---|
| control | 0.017 m | 0.055 m |
| `imu_dropout` | **0.062 m** | 1.707 m |
| `position_bias` | **0.017 m** | 0.960 m |
| `position_drift` | **0.017 m** | 2.001 m |
| `speed_bias` | **0.059 m** | 0.126 m |
| **`lateral_noise`** | **1.307 m** | **0.148 m** |

**`E-56`'s headline — *"on one fault ASTRA is worse"* — is still true, and it has
moved to a different fault.** In August it was `imu_dropout`, where ASTRA is now
**27× better**. Today it is `lateral_noise`, where ASTRA is **8.8× worse**.

**[INTERPRETATION]** The claim survived; every number under it changed. A reader
who had only the sentence would believe something true about the system and
nothing accurate about it.

---

## 15.3 · The measurement discipline

Four rules visible across every benchmark:

**1 · Always a control arm.** The fault study runs a clean arm on the same seed.
Without it, *"the vehicle deviated 4.199 m"* is not a finding — you cannot tell
it from normal behaviour.

**2 · Predict before you measure.** The CARLA plan writes down six falsifiable
predictions *before* running. **[INTERPRETATION]** This is what separates a
measurement from a search for a favourable number.

**3 · Sweep the free parameter.** `whiteness` reports separation across nine
slack values, because *"a detector that only works at a slack chosen after seeing
the fault is not a detector"*.

**4 · Report what the measurement does not license.** `exchangeability` prints,
even when it passes, that agreement between corpus and live loop is *agreement
between two things this project wrote*.

---

## 15.4 · Three experiments that went wrong, and how

**[FACT** — the `C-` register in `DECISION_LOG.md` Part 4.**]**

### C-4 · Four wrong measurements in a row

ADR-0020's effectiveness measurement went wrong **four consecutive times**, all
on **tick pairing** between the command, the plant's truth and the sensor
reading. It read the effectiveness **12–18% low** and *"looked entirely plausible
while doing so"*.

**[INTERPRETATION]** Plausibility is the enemy. A measurement that is obviously
broken gets fixed; one that is quietly 15% off gets published.

### C-5 · A context tuned by intuition inverted the result

A cold-path signature that *looks* like clear highway sat in permanent
`SAFE_EXPLORATION`, because component 2 is ego-speed **over legal limit** — 0.375
against a centroid expecting something else.

**Lesson:** a signature vector's components must be read from their definition,
not from what they sound like.

### C-6 · Overstating a defect

OD-10 was filed quoting **22×** — the *per-channel algebraic bound* — when the
realised effect was **1.53× / 1.23× / 1.024×**.

**The row was corrected rather than quietly amended**, because *"a register that
overstates what is broken loses trust as fast as one that understates it."*

---

## 15.5 · The three retractions of 15 August

All three are the **same mistake in three costumes**: a number assembled
correctly from an observation nobody checked was adequate.

| | What was claimed | What was actually measured |
|---|---|---|
| `E-143` | A detector separates a drift **7.35×**, refuting `E-107` | A vehicle with **400 of 400 ticks vetoed and a final speed of zero** — the closed loop was open, so the mechanism under test could not operate |
| `E-145` | An artefact file is missing | An `ls` of three directories piped through `head -20`, where the cut landed **one line above it** |
| `E-161` | **100% inside** for a context | **One** sample, printed beside a genuine 0% from 999, in the same column |

**How the first was caught:** two *different* proposers produced **bit-identical
numbers** — impossible if the proposer mattered. Not by a test.

**What each produced:** `StationaryVehicleError`, `make artifacts-check`, and a
minimum-sample guard. Each turns *"remember to check"* into a mechanism.

**[INTERPRETATION]** Three in one day is not a bad day; it is what happens when a
project measures aggressively enough to make mistakes at that rate — and catches
them because it distrusts convenient results.

---

## 15.6 · You should know this before moving on

**The five architecture-changing experiments:** the soak, the first fault, the
platform transfer, the shadow runs, the gate census.

**Questions you should be able to answer**

1. Why is a control arm on the same seed non-negotiable?
2. Why does `whiteness` sweep its slack rather than quote one value?
3. Why were FB2 and FB3 *built* if they were never going to be wired?
4. What do the three retractions have in common, and what mechanism now guards
   each?
5. Why is a measurement that is *quietly* 15% wrong more dangerous than one that
   is obviously broken?

**Misconception to avoid**

> *"The benchmarks demonstrate that ASTRA works."*
>
> Most of them demonstrate the opposite of something. `parity` announces its own
> refutation in its first line; `gate_census` shows two of three gates never
> firing; `exchangeability` shows the conformal precondition violated. They are
> **instruments**, not demos — and the project's strongest results are the
> refutations.

---

**Next:** `16_FAILED_APPROACHES/`.
