# 03 · Timeline

The dated version. Every entry is traceable to an ADR date, an evidence row, a
completion report or a commit.

**How to read it.** Each stage answers the same five questions: *what state was
the project in, what problem existed, what was tried, what happened, what changed
as a result.*

---

## 29 July 2026 — Day 0. Foundation

**[FACT** — fifteen ADRs dated 2026-07-29; `PHASE1_COMPLETION_REPORT.md`.**]**

| | |
|---|---|
| **State** | Nothing implemented. Source documents describing a nine-layer architecture |
| **Problem** | **The documents contradicted each other.** Figure 1 labelled three different components "Layer 6"; three numbering schemes were in circulation |
| **Tried** | Reconciliation before implementation — every contradiction found, recorded, and resolved in `DOCUMENT_RECONCILIATION.md` |
| **Result** | Consolidated `L1`–`L9`, L7 split into a/b. `ASTRA_LAYER_COUNT = 9` asserted against the enum by a test |
| **Changed** | The paper and the implementation now disagree, **and the paper is the one that must change** |

**Also delivered, same day:** ADRs 0001–0015. Contracts, ports, ten separation
invariants, the configuration schema, the audit log, the quality gate. **No layer
logic.**

**Open risk:** RK-1 — CARLA 0.9.14 supports CPython ≤3.8; ADR-0003 floors the
project at 3.12. *As stated, no interpreter satisfies both.*

---

## Late July — Phase 2. Sensing and estimation

**[FACT** — `PHASE2_COMPLETION_REPORT.md`, ADR-0015.**]**

| | |
|---|---|
| **State** | Vocabulary and contracts; nothing that computes |
| **Problem** | RK-1, the highest-rated technical risk |
| **Tried** | Three workarounds were on the table — sidecar, unofficial wheel, lower the floor — **and the premise was checked first** |
| **Result** | **The premise had expired.** CARLA 0.9.16 ships an official `cp312` wheel |
| **Changed** | RK-1 closed at zero cost. A real constraint replaced it: **CARLA has no macOS build** |

**Delivered:** L1 shared sensor bus, L2 dual-rate UKF, the replay spine.

---

## Late July — Phase 3. The deterministic safety spine

**[FACT** — `PHASE3_COMPLETION_REPORT.md`.**]**

**Delivered:** L7a Hard Safety Shield, L8 fail-safe FSM, the one-way Core-A →
Core-B channel. **SI-5 becomes a type error** — the write side exposes no read
method, so a violation does not compile.

---

## Early August — Phase 4. The proposer and the twin

**Delivered:** L4 CMDP proposer (the untrusted AI), L5 physics-informed twin.

**For the first time there is something to govern.**

---

## 5 August 2026 — The first long run. **The hinge.**

**[FACT** — `SOAK_REPORT.md`, `CREDIBILITY_MATRIX.md`, ADRs 0016 and 0017 dated
2026-08-05.**]**

| | |
|---|---|
| **State** | All layers built. Tests green, `mypy --strict` clean, 12 import contracts kept |
| **Problem** | None known |
| **Tried** | Run the whole pipeline for 100,000 ticks and read the numbers |
| **Result** | **Six defects at once** |

| Defect | Measured |
|---|---|
| OD-1 | Lane departure **2,883 m** at tick 100,000; every tick vetoed; FSM latched in HALT |
| OD-2 | Speed cap recorded on every capped tick, **applied to no actuator** — 17.2 m/s held *in HALT* |
| OD-4 | Lateral position dead-reckoned from an unobserved heading; estimator error **2.9 × 10⁶ m** |
| OD-5 | OOD counter unbounded — 1,508 by tick 2,000, still climbing |
| OD-6 | **99,808 of 100,000 commands issued under a blocking verdict** |

**What changed — ADR-0016.** The real defect was upstream of the ordering: *one
condition had two owners*. "No profile covers this context" produced a veto from
L6 **and** a narrowed envelope from L9, and the conflict was resolved by L9
ignoring L6. The fix added `Verdict.ABSTAIN` — a gate that *cannot* judge says so
— and moved the verdict test before the exploration branch.

**What changed — ADR-0017.** A vehicle 1 m off centre needs ~21 ticks to correct,
every one vetoed on jerk, so the correction could never complete. A jerk veto now
yields *the largest admissible step in the direction asked for*, not zero
steering.

**The lesson, recorded permanently:** none of the six was caught by the test
suite, the type checker, or the import contracts.

---

## 6 August 2026

**[FACT** — ADR-0018 dated 6 August; `E-41`.**]**

- **ADR-0018** — the EWC anchor moves on a context change, not on every update.
- **`E-41` / OD-8 opened.** Live non-conformity scores measured at **1.156**,
  *below the corpus minimum of 1.158*. **No wiring had changed.** The corpus
  simply stopped describing the system. Still open today.

---

## 9 August 2026 — Faults, and OD-9

**[FACT** — ADRs 0020, 0021, 0022 dated 9 August; `E-46`, `E-48`, `E-58`.**]**

| | |
|---|---|
| **State** | Pipeline running well on clean data |
| **Problem** | Nothing had ever gone *wrong* on purpose |
| **Tried** | Build a fault injector (ADR-0022: faults at the **sensor boundary**, never inside the core) and run it |
| **Result** | **OD-9 on the first fault it ever ran** |

**Measured:** a 200-tick IMU dropout put the vehicle **4.199 m off a 1.75 m
lane** — 73 ticks outside the corridor — with the corridor bound reading
**0.023 m** and a verdict trace **identical to the clean control's**.

**And worse than first recorded:** the fault does not stay in the channel it
entered. A frozen position reading is maximally self-consistent, so the filter
grows *confident* in it and pushes the inconsistency into the one state nothing
observes. True heading reached **0.0686 rad** while the estimate reported
**0.0017 rad** (`E-58`).

**Also this day — ADR-0020 and ADR-0021.**

- FB2 refused: *"do not wire as originally specified"*.
- Ablation defined as *neutralising* a gate, never removing one.

---

## 10 August 2026

- **OD-10 filed** — the innovation covariance omits `H·Q·Hᵀ`. Filed quoting the
  algebraic per-channel bound of **22.4×**; measured the same day at **1.53× /
  1.23× / 1.024×**, and the row was **corrected rather than quietly amended**
  (`C-6`).
- **Audit schema 5** — every record carries `previous_digest`, making the
  evidence log a hash chain.

---

## 11 August 2026 — Six ADRs in one day

**[FACT** — ADRs 0023–0028 all dated 2026-08-11.**]**

The busiest day in the project's history, and every one was forced by a
measurement.

| ADR | Forced by |
|---|---|
| **0023** | OD-12: on a platform the twin was never fitted to, the OOD counter climbed 0→100 and **halted the vehicle** while L9 correctly held a safe-exploration envelope underneath it — one event escalated twice |
| **0024** | OD-9. A **second counter**, driven by sensor freshness — the one input upstream of the common cause. Dropout deviation 4.199 m → **0.167 m** |
| **0025** | The vehicle proposes calibration *work*, never a calibration |
| **0026** | `FAULTED` gets a producer for the first time in the project's life; redundancy built |
| **0027** | One faulted channel of three HALTed a vehicle driving at 0.042 m on the other two — the counter needed a **quorum** |
| **0028** | A camera failure HALTed the vehicle exactly as an IMU failure did, on a build whose extractor reads the IMU alone. **A nuisance stop caused by a component that was not contributing** |

**Also:** OD-16 (a counter argued for and never written to the log) and OD-17
(`astra explain` shipped at **10.3% coverage** with a green gate) — both found by
*using* the tools rather than testing them.

---

## 15 August 2026 — The last in-house day

**[FACT** — ADRs 0029–0034; `E-129` – `E-164`.**]**

Six ADRs, audit schema 8 → 10, and the register from 18 rows to 21.

| What | Result |
|---|---|
| **ADR-0029** | Capability withdrawal — a *second axis*. One integer had been answering both *"how bad is this?"* and *"what is broken?"* |
| **ADR-0030** | Four health levels existed and the machine acted on two — a camera arriving **late** stopped the vehicle exactly as one that was **gone** |
| **ADR-0031** | The integrity counter moves ±1, so **any duty cycle at or below 50% nets to zero**. A camera dark on alternate frames for a full minute held NOMINAL with the counter at **1** |
| **ADR-0032** | `S` was short by exactly `H·Q·Hᵀ`. Fixing it cost control quality — deviation 0.0122 m → 0.1218 m — and **would not drive at all** until the corpus was regenerated |
| **ADR-0033** | Five modalities carried **one sensor**. Making redundancy the driven path improved the clean run **six-fold** and made a 1 m bias **never reach the estimator** |
| **ADR-0034** | The composition root accepts a platform instead of being one |

**Three claims were retracted the same day** — the stationary-vehicle detector,
the missing-file assertion, and `100% inside` from one sample. All three had been
assembled correctly from an observation nobody checked was adequate.

**And two open rows were shown to explain each other:** the statistical gate's
zero veto rate is not evidence the proposals were sound — it is **OD-8 seen from
the gate's side** (`E-162`, `E-164`).

---

## Where the line is now

Everything in-house is done or deliberately deferred. **Zero rows at `[M-ext]`.**
The next move is CARLA.

---

## You should know this before moving on

**Five dates worth memorising**

| Date | What |
|---|---|
| **29 Jul** | Foundation. Invariants before there was anything to violate them |
| **5 Aug** | The first long run. **Six defects at once.** The project's character changes |
| **9 Aug** | The fault injector's first fault finds OD-9 |
| **11 Aug** | Six ADRs — the sensor-integrity counter is born and corrected twice |
| **15 Aug** | Six more ADRs, three retractions, and the in-house work runs out |

**Questions you should be able to answer**

1. What did 5 August demonstrate about the relationship between a green test
   suite and a working system?
2. Why did the fault injector find OD-9 on its *first* fault?
3. Why did the sensor-integrity counter need correcting five times in five days?
4. What made 15 August's three retractions the *same* mistake in three costumes?

---

**Next:** `04_ARCHITECTURE_EVOLUTION/` — the same story told as *architecture*.
