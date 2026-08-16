# 04 · Architecture Evolution

**The most valuable section in this folder.**

Section 05 shows you what the architecture *is*. This one shows you why it could
not have been anything else — by walking each version, the problem that broke it,
and the decision that replaced it.

**[INTERPRETATION]** The "versions" below are this folder's framing. The project
does not version its architecture; it writes ADRs. But the ADRs cluster into
distinct architectural states, and naming them makes the evolution legible.
Every *fact* inside each version is sourced.

---

## Version 0 — The documents (before any code)

**Architecture.** Nine layers, described three different ways across a paper, a
prototype plan and status reports.

**Problem discovered.** It did not agree with itself. Figure 1 labelled **three
different components "Layer 6"** **[FACT** — ADR-0001**]**.

**Decision.** Reconcile before implementing. Consolidated `L1`–`L9` with L7 split
into `L7a`/`L7b`; the layer count asserted against the enum by a test.

**→ Version 1.**

---

## Version 1 — Contracts with no logic (29 July)

### Architecture

Ports, contracts, frozen dataclasses, ten separation invariants, a configuration
schema, an audit log — **and nothing that computes**.

### Data flow

None. There is no pipeline yet; there are the *shapes* a pipeline would pass
around.

### Assumptions

- Domain independence will come from ports plus a configured `ActuationSpace` (A-1)
- Safety thresholds have no defensible default (A-4)
- Explainability means decision provenance (A-10)

### Advantages

**The invariants existed before anything could violate them.** SI-5 was designed
into the channel's *type* rather than retrofitted onto a component that already
used the information.

**[INTERPRETATION]** This ordering is why SI-5 and SI-7 are structural today.
Retrofitting them would have meant taking information away from a working
component, which almost never survives contact with a deadline.

### Problem discovered

None yet — but a real one was latent: **nothing had been run**, so every
behavioural claim was an intention.

**→ Version 2.**

---

## Version 2 — Layers arrive (late July – early August)

### Architecture

```
sensors → L1 bus → L2 UKF → L3 trust → L4 proposer
                                          ↓
              L5 twin → L6 gate ┐
                    L7a shield ─┼→ merge → L8 fail-safe → L9 RCM → actuators
                    L7b physical┘
```

### Data flow

A tick: sensors publish → L1 stamps freshness → L2 fuses to a state estimate →
L3 scores trust → L4 proposes → L5 predicts → the three gates judge → verdicts
merge fail-closed → L8 updates posture → L9 issues.

### Assumptions

- The gates fail for structurally unrelated reasons
- A veto is unconditional
- The estimate the gates read is trustworthy ← **this one is doing a lot of
  unexamined work**

### Advantages

Complete, and every invariant mechanically enforced.

### Problem discovered — 5 August, the first long run

**Six defects at once** **[FACT]**. Two mattered architecturally:

**OD-6 — the veto was not unconditional.** Bounded safe exploration was tested
*before* the verdict, so in exploration the proposal was issued **regardless of
what the gates decided** — **99,808 commands per 100,000**.

The root cause was not the ordering. It was that **one condition had two owners**:
*"no profile covers this context"* produced a veto from L6 **and** a narrowed
envelope from L9, and the conflict was resolved by L9 ignoring L6.

**OD-2 — the fail-safe's speed cap applied to no actuator.** Recorded on every
capped tick; 17.2 m/s held *in HALT*. **The evidence log confidently reported a
mechanism that did not exist.**

### Decision — ADR-0016, ADR-0017

- Add **`Verdict.ABSTAIN`**: a gate that *cannot* judge says so, and abstentions
  are dropped before the fail-closed merge. One condition, one owner.
- Test the verdict **before** the exploration branch.
- A jerk veto yields **the largest admissible step in the direction asked for**,
  not zero steering — because zero steering latched a correction that needed ~21
  vetoed ticks to complete.
- Make the speed cap bind **through the projector**, so it reaches an actuator.

### Cost, recorded

The verdict is **no longer binary**; two invariant statements had to be amended;
the audit schema went 1 → 2. And abstention is a licence that must not spread — *a
gate abstaining because it was "uncertain" would be a fail-open mode wearing
ADR-0016 as cover*.

**→ Version 3.**

---

## Version 3 — Verdicts that mean something (5–9 August)

### Architecture

As Version 2, plus a three-valued verdict and a binding speed cap.

### Problem discovered — 9 August, the fault injector's first fault

**OD-9.** Everything above assumed the estimate was trustworthy. Under a frozen
IMU: **4.199 m off a 1.75 m lane**, corridor bound reading **0.023 m**, verdict
trace identical to a clean run **[FACT** — `E-46`, `E-48`**]**.

**The architectural discovery:** all three gates read L2's estimate, *and the
proposer closes its loop on the same estimate*. The three "independent" gates
share a common cause, and the fault is not merely undetected but **actively
driven**.

**And no gate could have fixed it.** L9's fallback controller reads the same
corrupted estimate, so a veto substitutes one command computed from a lie for
another.

### Decision — ADR-0024. **The most consequential architectural change after
Version 2.**

A **second counter** in L8, driven by `StreamHealth` — computed by L1 at the
sensor boundary, *before the filter touches anything*.

**Why not a fourth gate.** A fourth gate would read the same estimate and add
nothing. What was needed was not more judgement but **a different vantage
point** — an input upstream of the common cause.

```
        ┌──────────────── the common cause ────────────────┐
sensors ─┴→ L2 estimate → L3, L4, L5, L6, L7a, L7b        │
    │                                                      │
    └──── StreamHealth ────────────────────→ L8 ───────────┘
          (freshness, computed before the filter)
```

**Measured after:** dropout deviation **4.199 m → 0.167 m**, with DEGRADED at +5
ticks, LIMP at +15, HALT at +40 — against a departure that begins at +73. **1.65
seconds of margin.**

### What it explicitly did *not* fix

`StreamHealth` is computed from **staleness**. A stream that publishes fresh,
well-formed, *wrong* values stays `HEALTHY` forever. It closes the worst third of
OD-9 and is honest about the other two.

**→ Version 4.**

---

## Version 4 — Two counters (11 August, morning)

### Architecture

L8 now has **two independent counters**, and the posture is the worse of the two:

| Counter | Question | Rises on |
|---|---|---|
| **OOD counter** | *Is the command being refused?* | A blocking verdict |
| **Integrity counter** | *Can I still believe what I am told?* | Unhealthy sensor streams |

They are reported separately in every snapshot, because *"the gates refused forty
commands"* and *"a sensor was dark for forty ticks"* need different responses and
**one integer cannot say which happened**.

### Problem discovered — three times in one day

**OD-12.** On a platform the twin was never fitted to, RCM correctly held
`SAFE_EXPLORATION` for 520 ticks while the OOD counter climbed 0 → 100 and
**halted the vehicle underneath it**. One event escalated twice — defeating the
architecture's distinguishing claim *using its own fail-safe machine*.
**→ ADR-0023:** the OOD counter **freezes** during bounded exploration.

**Redundancy arrived (ADR-0026) and immediately broke the counter.** One faulted
channel of three HALTed a vehicle driving at **0.042 m** on the other two.
**→ ADR-0027:** the counter rises on a **lost quorum**, not on any bad channel.

**A camera failure HALTed the vehicle exactly as an IMU failure did** — on a
build whose extractor reads the IMU alone. A nuisance stop caused by a component
that was not contributing.
**→ ADR-0028:** the deployment declares which modalities are `critical_modalities`.

**→ Version 5.**

---

## Version 5 — The counter learns to discriminate (15 August)

Three more corrections, and the pattern behind them is the interesting part.

### The diagnosis

**One integer had been answering four different questions:**

| Question | Answered by |
|---|---|
| How bad is this getting? | The counter itself — **always correct** |
| How many channels may fail? | ADR-0027's quorum |
| *Which* sensors matter? | ADR-0028's critical set |
| *What* is broken? | **Nothing. Missing entirely** |

### Decision — ADR-0029. A **second axis**, not a third counter

`failsafe.capabilities` declares what each autonomy function requires; a function
is **withdrawn** while any modality it needs is unhealthy. The two axes compose by
**intersection**, so withdrawal can only ever *subtract* — a set able to *grant*
what the posture forbids would be a fourth gate with veto-override authority,
which SI-3 forbids.

**What this made expressible for the first time:** *lose the camera, stop
offering lane changes, keep driving.* Before it, a camera failure either stopped
the vehicle or did nothing at all.

### Decision — ADR-0030. The health *level* caps how far the posture may go

L1 distinguishes four health values; the machine read **one bit** of them. A
camera arriving **late** stopped the vehicle exactly as one that was **gone**.

**And note why a ceiling was right here having been rejected one record earlier:**
a ceiling says *how far*, and *which sensor* is not a question about how far — but
`StreamHealth` **is** a severity. Mapping one severity onto another invents no
number.

### Decision — ADR-0031. Decay measures what the counter cancels

The counter moves +1 unhealthy, −1 healthy, so **any duty cycle at or below 50%
nets to zero**. Measured: a camera dark on *alternate frames* for a full minute
held **NOMINAL** with the counter peaking at **1**.

The counter is not wrong — it answers *"am I in trouble now?"* and the answer is
no. It is **memoryless by design**, which is what makes recovery bounded. So the
fix was not to change it but to **measure the quantity it cancels out**: a
per-modality exponential average that converges to exactly the duty cycle.

**And it drives nothing.** A decaying sensor is a *service* condition; a vehicle
that stopped for maintenance would be ADR-0028's nuisance stop through a
different door.

**→ Version 6.**

---

## Version 6 — Current (15 August, afternoon)

Two changes to what the pipeline is *made of*, rather than to how it decides.

### ADR-0032 — the estimator was over-confident

`update` observed sigma points whose spread was the covariance **before** process
noise was added, so `S = H(P−Q)Hᵀ + R` — short by exactly `H·Q·Hᵀ`. **Every
Mahalanobis distance the filter ever reported was inflated.**

Fixing it **cost control quality** (deviation 0.0122 m → 0.1218 m: a correct
filter trusts each measurement less) and **would not drive at all** until the
corpus was regenerated — 400 of 400 ticks vetoed, caught by a guard added hours
earlier.

### ADR-0033 — five modalities carried one sensor

`_publish_state` computed **one** payload and published it byte-identical to all
five modalities; the extractor read the IMU alone. *Every cross-check that could
catch a lying channel had nothing to check against.*

Making three independent channels the **driven** path:

| | clean run | 1 m bias in one channel |
|---|---|---|
| single channel | 0.1034 m | **0.8387 m** |
| redundant | **0.0168 m** | **0.0168 m** |

The biased arm becomes **indistinguishable from the healthy one** — the median
outvotes the liar. And it more than repays ADR-0032's cost: *the honest fix for a
filter that must trust each measurement less is better measurements.*

### ADR-0034 — the composition root accepts a platform instead of being one

`space` and `projector` become injectable. Writing an honest test for it found
**three couplings nobody had named**, including a placeholder policy that indexes
a steering channel into the space.

---

## The through-line

Read the versions together and one pattern dominates:

> **Almost every architectural change was forced by a measurement that
> contradicted a document, and the fix was usually to give a component a *narrower*
> job rather than a smarter one.**

- ABSTAIN — a gate stops pretending it can judge when it cannot
- The integrity counter — a machine stops inferring sensor health from verdicts
- The capability axis — one integer stops answering two questions
- Decay — the counter keeps its memorylessness and something else carries memory
- ADR-0034 — the composition root stops *being* a platform and starts *accepting*
  one

**[INTERPRETATION]** The recurring error is **one mechanism answering two
questions**, and the recurring fix is **separating them**. If you learn one thing
from this section, learn to look for that shape.

---

## You should know this before moving on

**The six versions**

| V | State | Killed by |
|---|---|---|
| 1 | Contracts, no logic | Nothing had been run |
| 2 | All nine layers | **OD-6** — the veto was not unconditional |
| 3 | Three-valued verdicts | **OD-9** — the gates share a common cause |
| 4 | Two counters | The counter could not say *which*, *how many*, or *what kind* |
| 5 | A discriminating counter, plus a capability axis | The estimator was over-confident; redundancy was not driven |
| 6 | **Current** | — |

**Questions you should be able to answer**

1. Why was OD-9 fixed with a counter reading sensor freshness rather than a
   fourth gate?
2. What does it mean that ABSTAIN gave *"one condition one owner"*?
3. Why is a per-*health-level* ceiling acceptable when a per-*modality* one was
   rejected?
4. Why does sensor decay deliberately drive nothing?
5. What single recurring error shape explains ADR-0016, 0024, 0029 and 0031?

**Misconception to avoid**

> *"The architecture was designed and then implemented."*
>
> Versions 1 and 2 were. Everything after was **forced by measurement**. The
> current design contains at least six things nobody would have thought to
> specify — and each exists because a number contradicted a document.

---

**Next:** `05_CURRENT_ARCHITECTURE/`, which will now read as a set of answers
rather than a set of boxes.
