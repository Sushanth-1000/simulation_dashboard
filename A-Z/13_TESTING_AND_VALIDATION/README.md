# 13 · Testing and Validation

**The most important distinction in this folder:**

| Level | Means |
|---|---|
| **PROVEN** | True by construction — a type error, an import contract. Cannot be false while the build passes |
| **DEMONSTRATED** | Measured, on this plant. Reproducible from one command. **Says the machinery runs; not that it is right** |
| **ASSUMED** | Stated, relied upon, **not measured** (`A-1` … `A-10`) |
| **NOT VALIDATED** | Neither measured nor safely assumable. Named so it cannot be mistaken for done |

Almost every mistake a reader can make about this project is putting something in
the wrong row.

---

## 13.1 · What exists

**[FACT** — read from the tree, 15 August 2026.**]**

| | Count |
|---|---|
| Test files | **83** — 69 unit, 7 integration, 4 architecture, 3 property |
| Tests | **3,065** |
| Strict `xfail` | **3** |
| Type checking | `mypy --strict` over **169** files, 0 issues (re-run 16 Aug) |
| Import contracts | **12**, 0 broken |
| Coverage | **97.47%** (re-run 16 Aug), plus an **80% per-file floor** |

### The gate

```bash
make check
```

`blobsize · lockfile · format-check · lint · typecheck · contracts · test ·
coverage-floor` — *"the full quality gate, exactly as CI runs it."*

---

## 13.2 · The categories, and what each can establish

### Unit tests — 69 files

Component behaviour in isolation. `test_unscented.py` checks the sigma-point
maths against analytic expectations; `test_sensor_decay.py` checks the EMA
converges to the duty cycle.

**Can establish:** a function computes what it claims.
**Cannot establish:** that the composition behaves — *every one of the six
defects on 5 August passed the unit tests*.

### Integration tests — 7 files

The assembled pipeline, driven end to end. `test_closed_loop_faults.py` injects
an IMU dropout and asserts the posture escalates while no gate fires.

**Can establish:** components compose; a fault produces the intended response.
**Cannot establish:** behaviour over long horizons.

### Architecture tests — 4 files

Structural claims. `test_domain_independence.py` asserts that
`assemble_pipeline` *accepts* an actuation space, and drives it with a
two-channel differential drive to check the seam is real.

**These are the `[M-code]` rows** — true regardless of plant.

### Property tests — 3 files

Invariants over generated inputs rather than chosen examples.

### Strict `xfail` — the unusual category, and the most informative

**[FACT** — D-16, and `test_domain_independence.py`.**]**

A **strict** `xfail` asserts *"this is currently false, and if it becomes true the
suite fails."*

Three remain, all NFR5 walls — the bicycle process model, the automotive names in
`SLOW_STATE_FIELDS`, and the automotive `ContextClass` values.

**Why this matters.** On 15 August two more (walls 1 and 2) **flipped to
`XPASS`** the moment the parameters existed — reported as *failures*, forcing the
fix to announce itself. A known-false claim held as a passing test would have let
the improvement land silently.

> A strict xfail turns *"we know this is broken"* from a comment into a
> **mechanism**.

---

## 13.3 · What has actually been tested — the honest table

### PROVEN

| Claim | How |
|---|---|
| The proposer cannot read a verdict (SI-5) | Type error — no read method exists |
| Only L9 may construct an `IssuedCommand` (SI-7) | Runtime refusal |
| Any VETO ⇒ VETO; empty ⇒ VETO (SI-3) | `Verdict.merge`, tested |
| `carla` appears nowhere in `astra` | Import contract |
| Every layer number maps to exactly one layer | Asserted against the enum |
| An invariant cannot claim mechanical enforcement while being `REVIEW` | Tested correspondence |

### DEMONSTRATED — on this plant, `[M-syn]`

| Claim | Evidence |
|---|---|
| Lane-keeping to 0.0168 m over 400 ticks | `E-152` |
| A 1 m bias in one channel never reaches the estimator | `E-153` |
| IMU dropout: escalation to LIMP at +15, no departure, 0.062 m | re-measured 16 Aug — supersedes `E-87`/`E-88`'s *HALT at +40 vs departure at +73* |
| Recovery bounded at 91 ticks | Derived from the counter's ceiling |
| FB2 would fall 40% in an unchanging context | `E-39` |
| FB3's veto rate converges to ε exactly | `E-40` |
| Five drift detectors are silent | `E-53`, `E-94`, `E-105`, `E-106`, `E-143` — detectors 1, 2 and 5 re-run 16 Aug and still silent; 5 is now *exactly* silent, at 1.00× |
| Two of three gates never object | `E-162` |
| Live scores do not overlap the corpus | `E-159` |

### ASSUMED — stated, relied upon, unmeasured

| | Assumption | Status |
|---|---|---|
| A-1 | Domain independence via ports | **Partly measured FALSE** — OD-11 |
| A-2 | 10 ms at 20 Hz in CPython | **Measured 16 Aug** — full tick p50 2.2 ms, p99 2.8–10.5 ms across five runs, max 46.9 ms. Met at the median, violated in the tail |
| A-3 | JSONL is adequate evidence | Not stress-tested at scale |
| A-8 | CARLA resolvable without core change | **Untested — the CARLA work is the test** |

### NOT VALIDATED

- **Any behaviour on a plant this project did not write.** `[M-ext]: 0 of 30`
- **False-positive and false-negative rates.** No number exists, deliberately
- **The gates' efficacy** — five of ten rows are `[NOT DONE]`
- **The train/serve skew** — the proposer trains on truth, runs on an estimate
  (`E-155`). **[OPEN]**
- **Timing under load.** The tick is measured; what is *not* measured is the
  cause of the tail, and there is **no deadline monitor** — a late tick is
  recorded identically to a punctual one

---

## 13.4 · Fault injection — the scenario suite

**[FACT** — `benchmarks/fault_study.py`; ADR-0022: faults at the **sensor
boundary**, never inside the core.**]**

| Scenario | Defeats |
|---|---|
| `imu_dropout` | The 50 ms staleness rule — the one defence built for exactly this |
| `position_bias` | The innovation sequence: fresh, well-formed and confidently wrong |
| `position_drift` | **Any per-tick threshold** — no single step is anomalous |
| `speed_stuck` | Staleness from the other side: the reading never goes stale |
| `speed_bias` | L7a's speed bound, which reads the estimate the fault has captured |
| `lateral_noise` | The Trust Index, which reads normalised innovations |

**Each scenario declares what it is meant to defeat** — a field exists for it, so
*"a study cannot accrete faults for variety and report coverage it does not
have."*

**[INTERPRETATION]** This is the best-designed part of the test apparatus. Each
fault is aimed at a *specific defence*, which converts the suite from *"we tried
some things"* into *"here is what each defence is worth."*

---

## 13.5 · Testing techniques the project invented for itself

### The shadow harness

Run a mechanism **with no authority** and compare it against the live one. FB2,
FB3 and the effectiveness estimator were all measured this way *before* any
wiring decision.

> **No mechanism gets authority until it has run with none.**

This is why two feedback loops were refused with numbers rather than opinions.

### Ablation that neutralises, never removes

**[FACT** — ADR-0021.**]** An ablation **neutralises** a gate; it never removes
one. A removed gate changes the pipeline's shape; a neutralised one leaves every
other path identical, so the difference is attributable.

And the audit record carries an `ablation` field **per tick**, because *"a v3
reader sees an ablated run's records as a governed run's — every other field is
identical by construction. That is what an ablation is."*

### The artefact guard

**[FACT** — `tools/check_artifacts.py`.**]** Presence is not the check; **driving
is**. It runs a short closed loop and refuses if every tick was vetoed or the
vehicle never left rest.

> An artefact that loads and yields a car that never moves is **worse than a
> missing one**: a missing one raises, and this one produces numbers.

It caught a real regression **within hours of existing** — ADR-0032's corrected
filter put 400 of 400 ticks into a veto until the corpus was regenerated.

### The version pin that fires

The audit schema version is **pinned by a test**, and has fired **seven times** —
each forcing a schema change to be a deliberate decision.

---

## 13.6 · What testing has repeatedly failed to catch

**[FACT** — `CREDIBILITY_MATRIX.md`.**]**

> Not one of these was caught by the test suite, `mypy --strict`, or the 12
> import contracts.

| Found by | Examples |
|---|---|
| **Running a long time** | OD-1, OD-2, OD-4, OD-5, OD-6 — all six on 5 August |
| **Injecting a fault deliberately** | OD-9, on the first fault ever run |
| **Running a mechanism in shadow** | FB2, FB3, the effectiveness estimator |
| **Using a tool** rather than testing it | OD-14, OD-16 — found by the explainer |
| **A customer-style question** | OD-16, OD-17, OD-18, OD-19 — four in one week |

**And the shape that testing is worst at — inversions.** OD-2 and FB2 both had
the evidence log confidently recording something that had not happened. *Those are
invisible to testing by construction, because the system reports success.*

---

## 13.7 · You should know this before moving on

**The four levels:** PROVEN · DEMONSTRATED · ASSUMED · NOT VALIDATED. Put every
claim in one before believing it.

**Questions you should be able to answer**

1. What is a *strict* xfail, and what did it do on 15 August that a comment could
   not?
2. Why does an ablation **neutralise** rather than remove?
3. Why is *"presence is not the check, driving is"* the right rule for artefacts?
4. Which claims are PROVEN, and why are they the only ones true regardless of
   plant?
5. What kind of defect is testing structurally worst at finding, and why?

**Misconception to avoid**

> *"3,065 tests and 97.47% coverage means it is well tested."*
>
> The project's own evidence contradicts that reading. A green suite of that size
> coexisted with a vehicle **2,883 m off its lane**, a speed cap applied to no
> actuator, and **99,808 of 100,000 commands issued under a blocking verdict**.
> Coverage measures *how much code ran*, not *whether the system works*. The suite
> is necessary and it has never once been sufficient.

---

**Next:** `14_SIMULATION/`.
