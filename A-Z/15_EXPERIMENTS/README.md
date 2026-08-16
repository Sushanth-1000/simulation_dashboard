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

**Actual.** RCM correctly held `SAFE_EXPLORATION` for 520 ticks — and the OOD
counter climbed 0 → 100 underneath it and **halted the vehicle**.

> One event escalated twice, defeating the architecture's distinguishing claim
> **using its own fail-safe machine**.

**Changed:** ADR-0023 — the OOD counter freezes during exploration.

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
