# 02 · Project History — the narrative

**What this section is.** The story of how ASTRA got from an idea to nine
working layers, told as a sequence of *problems and responses* rather than a list
of features.

**What it is not.** A changelog. `03_TIMELINE/` has the dated version; this one
explains *why each thing happened*.

---

## The shape of the whole history in one paragraph

Four days of foundation work built the vocabulary and the invariants with **no
layer logic at all**. The layers then arrived over about three weeks. The moment
the whole pipeline first ran for a long time, it produced **six defects at once**
— and from that point the project's character changed permanently: it stopped
being a construction project and became a **measurement project**, in which
almost every subsequent change was forced by a number that contradicted a
document.

---

## Act I — Foundation, 29 July 2026

**[FACT** — `PHASE1_COMPLETION_REPORT.md`, and fifteen ADRs all dated
2026-07-29.**]**

### The state

Nothing existed. There were source documents — a paper, a prototype plan, status
reports — describing a nine-layer architecture.

### The first problem was the documents

Before a line of implementation, the source material had to be reconciled, and it
did not agree with itself. The clearest example **[FACT** — ADR-0001**]**:

> The paper's Figure 1 labels **three different components "Layer 6"**.

Three different numbering schemes existed across the documents. `DOCUMENT_RECONCILIATION.md`
exists solely to record every contradiction found and how it was resolved.

**Decision:** adopt a consolidated `L1`–`L9` numbering, splitting L7 into `L7a`
and `L7b` — *"the only numbering in which every layer has exactly one number and
every number has exactly one layer"*. The count is asserted against the enum by a
test, so it cannot drift without the build failing.

**Cost, recorded honestly:** the paper and the implementation now disagree, and
**the paper is the one that must change**.

### What Phase 1 deliberately did not build

Any layer logic. Phase 1 delivered vocabulary, contracts, interfaces, invariants,
configuration and evidence machinery — and nothing that computes.

**[INTERPRETATION]** This is unusual and, on the evidence of what followed, was
correct. The invariants were in place *before* there was anything to violate
them, so the enforcement is structural rather than retrofitted. Retrofitting SI-5
onto a working proposer would have meant asking a component to give up
information it already used.

### The decisions that still shape everything

Of the fifteen ADRs written that day, five still govern daily work:

| ADR | Decision | Why it still matters |
|---|---|---|
| **0012** | Separation invariants as **executable** contracts | An invariant cannot be quietly downgraded and keep claiming a guarantee |
| **0005** | Ruff + mypy strict + import-linter as **one non-negotiable gate** | The gate is the reason large refactors are safe |
| **0008** | Frozen dataclasses on the hot path, pydantic only at boundaries | Validation where humans write text; zero cost where the tick runs |
| **0007** | SI units via `NewType`, converted only at boundaries | A unit mismatch is a **build error** |
| **0013** | Append-only JSONL audit log as the evidence artefact | Every later claim traces to a row in it |

### The risk that dominated

**RK-1**: the source documents mandated CARLA 0.9.14, whose Python client
supported CPython 2.7/3.7/3.8 — while ADR-0003 floored the project at Python
3.12. *As stated, the two requirements admitted no interpreter.*

Three workarounds were on the table and none had been evaluated.

---

## Act II — The layers arrive, late July to early August

**[FACT** — Phase 2 and Phase 3 completion reports.**]**

### Phase 2 — sensing and estimation, and a risk that dissolved

Delivered L1 (the shared sensor bus) and L2 (the dual-rate UKF), plus the replay
spine.

**The headline was RK-1, and the resolution is worth learning from.** It was not
worked around. **The premise expired**: CARLA 0.9.16 ships an official `cp312`
wheel. No sidecar, no unofficial wheel, no lowered floor.

**[INTERPRETATION]** The transferable habit here is *re-examine the premise before
engineering around it*. A version number in a source document was treated as a
fact; checking it dissolved the project's highest-rated risk at zero cost.

A new constraint replaced it and is real: **CARLA has no macOS build.**

### Phase 3 — the deterministic safety spine

Delivered L7a (the Hard Safety Shield), L8 (the fail-safe state machine), and the
one-way Core-A → Core-B channel.

**This is where SI-5 became a type error rather than a rule.** The proposer's
channel exposes no read method, so a violation *does not compile*.

### Phase 4 — the proposer and the twin

L4 (the CMDP proposer — the untrusted AI) and L5 (the physics-informed digital
twin). This is the point at which there was something to govern.

---

## Act III — The first long run, and everything changes

**[FACT** — `SOAK_REPORT.md`, `CREDIBILITY_MATRIX.md`.**]**

### What happened

The complete pipeline was run for a hundred thousand ticks. It had passed every
test, satisfied `mypy --strict`, and kept twelve import contracts.

**It produced six defects at once.**

| Defect | What the long run showed |
|---|---|
| **OD-1** | Lane departure of **2,883 m** at tick 100,000, every tick vetoed, the fail-safe latched in HALT |
| **OD-2** | The fail-safe's speed cap was recorded on every capped tick and **applied to no actuator** — 17.2 m/s held *in HALT* |
| **OD-4** | Lateral position dead-reckoned from an unobserved heading; estimator error reached **2.9 × 10⁶ m** |
| **OD-5** | The OOD counter was unbounded — 1,508 by tick 2,000 and climbing |
| **OD-6** | **99,808 commands per 100,000** issued under a blocking verdict |

### Why this is the hinge of the whole project

Read OD-6 again. Bounded safe exploration was being tested *before* the verdict,
so in exploration the proposal was issued **regardless of what the gates
decided** — and at the shipped operating point, exploration was engaged almost
always.

**The single strongest claim in the safety argument — that a veto is
unconditional — was false in practice, and every test passed.**

And OD-2 has the same shape from the other side: the speed cap was faithfully
*recorded* on every tick and applied to nothing. The evidence log confidently
reported a safety mechanism working that did not exist.

### The lesson the project drew, and never let go of

**[FACT** — `CREDIBILITY_MATRIX.md`**]**:

> Not one of these was caught by the test suite, `mypy --strict`, or the 12
> import contracts. Every one was caught by **running the system for a long time
> and reading the numbers**.

Two of them — OD-2 and later FB2 — were **inversions**: the evidence log
confidently recorded something that had not happened. Those are invisible to
testing *by construction*, because the system reports success.

> **This is why the credibility matrix exists**, and why every later claim in the
> project carries a column saying what it does *not* license.

---

## Act IV — The measurement era, August 2026

From here the project's mode changed. The pattern repeats so consistently it is
worth naming:

```
run something for a long time, or ask it an awkward question
   → get a number that contradicts a document
      → work out which is wrong
         → usually the document
            → write an ADR, fix it, re-measure, keep the old number
```

### Four sub-plots worth knowing

**1 · Two feedback loops were built, measured, and refused.**

FB2 would have trained the twin on the proposer's own commands — destroying the
independence that is the twin's entire purpose. Measured in shadow: the score
fell **40%** in a context where nothing changed (`E-39`). FB3 would have
requantilised on scores the system generates itself; its veto rate converges to
`significance_epsilon` **exactly**, because ε of any distribution lies above its
own 1−ε quantile (`E-40`) — the gate stops being a detector and becomes a
fixed-rate sampler.

**Neither was ever wired.** Both measurements are kept as the evidence *for* not
wiring them.

**2 · OD-9 — the common-cause failure.**

Covered in `01_PROBLEM_AND_MOTIVATION`. The fix (ADR-0024) is a second counter
driven by sensor *freshness*, computed upstream of the estimator — deliberately
**not** a fourth gate, because a fourth reader of the same estimate adds nothing.

**3 · Five corrections to one mechanism in five days.**

The sensor-integrity counter was changed by ADR-0024, then 0027, then 0028, then
0029, then 0030 — each time because a customer-style question exposed an
assumption that had quietly rested on there being only one sensor. *Which* sensor
failed, *how many* may fail, *what kind* of failure, and *which functions* it
carries were four different questions, and the original single integer had been
answering all of them.

**4 · A claim was retracted and un-retracted in four hours.**

15 August: a fifth detector appeared to break a long-standing conclusion
(`E-107`), and it was retracted. The measurement had run on a vehicle with
**400 of 400 ticks vetoed and a final speed of zero** — a configuration in which
the mechanism under test cannot operate. Re-run properly, the conclusion stood
and was *strengthened* (`E-143`).

> **And there is a sequel, found and fixed on 16 August.** The guard written that
> day had begun **blocking the benchmark entirely**: it refused the `imu_dropout`
> arm because the fail-safe correctly brings the vehicle to 0.0000 m/s, which the
> guard read as *"the loop never closed"*. It now counts the ticks on which the
> loop actually was closed, and `E-107` still stands — more firmly, since the
> drift arm is now identical to the control to every printed digit. See §18.
>
> **A guard is a claim about what a valid configuration looks like, and claims go
> stale exactly like numbers do.** This project pins its schema with a test and
> asserts each invariant's enforcement kind with a test; its retraction guards had
> nothing watching them.

**[INTERPRETATION]** This is the episode that best characterises the project.
The error was caught by noticing that two different proposers produced
bit-identical numbers — which is impossible if the proposer matters — rather than
by any test.

---

## Act V — Where it stands

**[FACT]** as of 15 August 2026: 21 defects, 16 closed, 1 reclassified, 1 partly
closed, 3 open. 34 ADRs. 3,047 tests. 164 evidence rows.

Everything that can be done in-house is done. The three open rows all want a
simulator this project did not write, and **`CARLA_PLAN.md`** is the plan for
getting there.

---

## You should know this before moving on

**The five acts**

1. Foundation with no layer logic — invariants before there was anything to
   violate them
2. Layers arrive; the dominant risk dissolves on re-examination
3. **The first long run produces six defects and changes the project's character**
4. The measurement era — refutations, retractions, five corrections to one line
5. In-house work exhausted; CARLA is the only remaining move

**Questions you should be able to answer**

1. Why did Phase 1 deliberately build no layer logic, and why did that turn out
   to be right?
2. What is an *inversion*, why is it invisible to testing, and which two defects
   were of that kind?
3. What did the first long run demonstrate about the relationship between a green
   test suite and a working system?
4. Why were FB2 and FB3 built at all, if they were never going to be wired?
5. Why was OD-9 fixed with a counter rather than a fourth gate?

**Misconception to avoid**

> *"The defects mean the project is in poor shape."*
>
> The opposite reading is better supported. Every one was **self-found**, and the
> comparison that matters is not *"how many defects does this project have"* but
> *"how many does it know about"*. A project with a green suite and no register
> has the same defects and no list.

---

**Next:** `03_TIMELINE/` for the dated version.
