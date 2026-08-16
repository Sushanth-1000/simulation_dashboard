# 17 · Decision Log

**This is a guide to `docs/DECISION_LOG.md`, not a replacement.** That document
is authoritative and holds every decision with its full alternative set. This
section picks the **fifteen you must know**, explains *why each mattered*, and
teaches the shapes so you can recognise the next one.

Each entry: *decision · problem · options · chosen · why · advantages ·
disadvantages · evidence · what would reopen it.*

---

## The four decisions that shape everything

### D1 · Separation invariants as executable contracts — ADR-0012

| | |
|---|---|
| **Problem** | A safety argument written in prose drifts from the code |
| **Options** | (a) Document and review against them — **rejected**; (b) assert in tests only — partly taken; (c) a catalogue where each invariant declares its own enforcement kind, with a test asserting the correspondence |
| **Chosen** | (c) |
| **Why** | `is_mechanically_enforced` returns `False` for exactly `REVIEW`, and a test asserts that correspondence — so **an invariant cannot be quietly downgraded and keep claiming a guarantee** |
| **Evidence** | Option (a) is not hypothetical: *"this is what 'SI-6 is REVIEW-only' meant, and it stayed wrong in a document for four weeks after the code changed"* |
| **Gave up** | **Nothing checks that the ten are the *right* ten** |
| **Would reopen it** | An invariant that cannot be expressed mechanically at all |

**[INTERPRETATION]** The most load-bearing decision in the project. Everything
else in the safety argument rests on the claims about enforcement being checkable.

### D2 · The one-way channel as a type error — ADR-0012, SI-5

| | |
|---|---|
| **Problem** | A compromised or merely optimising Core-A must not read a verdict |
| **Options** | (a) A process boundary — out of scope for a Python prototype; (b) convention plus review — see D1; (c) a capability pair where `ProposalWriter` exposes **no read method** |
| **Why** | **A violation does not compile.** Twelve import contracts back it at module level |
| **Gave up** | It protects against *code* that reads a verdict, not a compromised process outside the type system |

### D3 · A gate that cannot judge abstains — ADR-0016

**The decision that fixed the worst defect in the project's history.**

| | |
|---|---|
| **Problem** | **99,808 commands per 100,000 issued under a blocking verdict.** Exploration was tested *before* the verdict |
| **Options** | (a) Keep the ordering and document it — rejected: it makes the deterministic gate's authority conditional on a state the gate cannot observe. (b) Swap the branches, no abstention — **strictly safer, and it deletes bounded safe exploration**, because an uncalibrated L6 vetoes every tick. *Kept on record as the honest fallback.* (c) Override only the statistical veto — buys the same behaviour for a fifth of the effort and pays with a permanent exception to the unconditional veto. (d) A per-gate override list in configuration — **rejected on sight**: it turns *"which gate may be overruled"* into a value a deployment can edit. (e) Add `ABSTAIN`, drop abstentions before the fail-closed merge, test the verdict first |
| **Why** | **The real defect was upstream of the ordering: one condition had two owners.** *"No profile covers this context"* produced a veto from L6 **and** a narrowed envelope from L9, and the conflict was resolved by L9 ignoring L6. Abstention gives the condition **one owner** |
| **Gave up** | The verdict is **no longer binary**; two invariant statements had to be amended; audit schema 1→2. And *"abstention is a licence that must not spread — a gate abstaining because it was 'uncertain' would be a fail-open mode wearing this record as cover"* |

**[INTERPRETATION]** Study option (b). Recording *the strictly safer option you
did not take, and why* is rare and is what makes this log trustworthy.

### D4 · Sensor integrity is a second counter, not a fourth gate — ADR-0024

| | |
|---|---|
| **Problem** | OD-9: all three gates read L2's estimate; a sensor fault blinds them together, and **the proposer drives the corrupted value toward what the gates consider safe** |
| **Options** | A fourth gate; a better detector; **a second counter reading a signal upstream of the estimator** |
| **Why** | A fourth gate reads the same estimate and **adds nothing**. What was needed was not more judgement but **a different vantage point** |
| **Evidence** | Dropout deviation **4.199 m → 0.167 m**, HALT at +40 against departure at +73 — **1.65 s of margin** |
| **Gave up** | It catches a stream going *quiet*. **A fresh, well-formed, wrong stream stays HEALTHY for ever** — honest about closing one third of OD-9 |

---

## The corrections — five to one mechanism in five days

Worth reading as a sequence, because the *pattern* is the lesson.

| ADR | Forced by | Fix |
|---|---|---|
| **0024** | OD-9 | A second counter |
| **0027** | One faulted channel of three HALTed a vehicle driving at 0.042 m on the other two | Rise on a **lost quorum**, not any bad channel |
| **0028** | A camera failure HALTed exactly as an IMU failure did, on a build reading the IMU alone | The deployment declares `critical_modalities` |
| **0029** | *Lose the camera, stop offering lane changes, keep driving* was **unrepresentable** | A **second axis** — capability withdrawal |
| **0030** | A camera arriving **late** stopped the vehicle exactly as one that was **gone** | The health *level* caps how far the posture may go |
| **0031** | A camera dark on **alternate frames** for a minute held NOMINAL, counter at 1 | **Decay** — measure the duty cycle the counter cancels |

### The diagnosis that explains all six

**One integer was answering four different questions:**

| Question | Answered by |
|---|---|
| How bad is this getting? | The counter — **always correct** |
| How many channels may fail? | 0027's quorum |
| *Which* sensors matter? | 0028's critical set |
| *What* is broken? | **0029's second axis — was missing entirely** |
| Is this sensor *dying*? | **0031's decay — was missing entirely** |

**[INTERPRETATION]** If you learn one shape from this log, learn this one: **one
mechanism answering two questions**. Its fix is always *separate them*, and the
fix is always *narrower*, never *smarter*.

### And one correction that is itself instructive — ADR-0030 vs ADR-0029

ADR-0029 **rejected** a per-*modality* severity ceiling. ADR-0030 **adopted** a
per-*health-level* one, one record later. Not a contradiction:

> A ceiling says *how far*. **Modality identity is not a question about how far** —
> asking how severe a camera is compared to an IMU has no defensible answer.
> **`StreamHealth` *is* a severity** — literally how far past the staleness budget
> a stream has fallen. Mapping one severity onto another invents no number.

---

## Decisions about how the project works

### D5 · No mechanism gets authority until it has run with none

The rule behind every shadow measurement. FB2, FB3 and the effectiveness
estimator were all measured **before** any wiring decision — and all three were
refused **with numbers**.

### D6 · Retract, do not refresh

When a claim turns out wrong, it is retracted **visibly** rather than quietly
updated. `E-107`'s retraction and un-retraction both survive in the log; the EWC
measurements survive footnoted.

> A table that silently dropped the measurements behind its own changes would be a
> worse record than one carrying a footnote.

### D7 · Cite `EVIDENCE.md`, never restate it

A number lives in exactly one place. A figure repeated in two documents will be
stale in one of them — *"which is precisely what this reconciliation had to
repair."*

### D8 · Strict xfail for a claim that is false

A known-false claim is held as a **strict** `xfail`, so fixing it **fails the
suite** and forces the fix to announce itself. Two flipped on 15 August and were
reported as failures. Exactly the point.

### D9 · A per-file coverage floor far below the aggregate

| | |
|---|---|
| **Problem** | `astra explain` shipped at **10.3%** coverage with a green gate — 94 uncovered statements against several thousand move a 95% *aggregate* by less than a tenth of a point |
| **Options** | Rely on review — *"this repository has filed four separate defects that review did not catch"*; raise the aggregate — *"the arithmetic that hid a 10% module hides it just as well at 97%"*; a floor at the aggregate value — *"would fail three healthy files today and be switched off within a week"*; **a floor far below** |
| **Why** | Its job is to catch a module with **no** tests, not to chase the last branches. At 80% it passes every file today **and fails the defect that motivated it** |
| **The uncomfortable part** | A-7 had cited the aggregate since Phase 1 and **the aggregate was always true**. What it never licensed was a statement about any *particular* module — *"same shape as OD-2 and OD-7, with the novelty that the check was the quality gate"* |

---

## The decision that was wrong, and is recorded as wrong

### D-12h's uncomfortable entry

I recommended **deferring capability withdrawal** behind OD-15, on the grounds
that four of five modalities feed nothing, so a dependency map would be fiction.

**Wrong, and the ADR records it as a rejected alternative with the reasoning that
made it wrong:**

> The map states what the vehicle **may do** when a sensor is unhealthy, not what
> the estimator reads. Camera health is real today — L1 computes it from
> freshness, per stream, whether or not anyone consumes the payload.

**[INTERPRETATION]** A decision log containing only good decisions is a brochure.
This one contains a recommendation that was wrong, the reason it was wrong, and
what it delayed.

---

## You should know this before moving on

**The four foundational decisions:** executable invariants · the type-error
channel · ABSTAIN · the second counter.

**The shape to recognise:** *one mechanism answering two questions* — and its fix
is always **separate them**, never *make it cleverer*.

**Questions you should be able to answer**

1. Why is *"an invariant cannot be quietly downgraded"* the load-bearing property
   of D1, and what four-week failure justified it?
2. What was the strictly safer option ADR-0016 rejected, and why?
3. Why did OD-9 need a *counter* rather than a fourth gate?
4. Why is a per-health-level ceiling acceptable when a per-modality one was not?
5. Why does a per-file coverage floor sit far *below* the aggregate gate?

**Misconception to avoid**

> *"The decision log records what was decided."*
>
> It records **what was rejected and what each choice cost**. The *"Gave up"*
> column is the point — an entry with an empty one is *"a decision that has not
> been thought about hard enough."* Read that column first.

---

**Next:** `18_CHALLENGE_LOG/`.
