# 2 · Why the problem is hard

Six reasons. Each one independently defeats an obvious fix, and together they
explain why the answer had to be *architectural* rather than a better component.

---

## 2.1 · You cannot test your way out — the coverage problem

The instinct is: test it more.

The arithmetic refuses. Driving is a continuous, high-dimensional space —
weather, light, road geometry, other road users, tyre condition, occlusion — and
the *combinations* are what matter. You cannot enumerate them, and the ones that
kill people are by construction the rare ones.

Industry estimates for demonstrating a fatality rate better than a human's run to
**hundreds of millions of miles**, and would need re-running after every software
change. **[UNVERIFIED** — widely cited in the AV literature; not measured by this
project, quoted here as background rather than as a project claim.**]**

The deeper problem is not cost. It is that **testing establishes behaviour on the
cases you tested**, and the failure mode under discussion is *specifically* the
case you did not think of. Testing is the wrong instrument for unknown unknowns.

**Consequence for the design:** the runtime system must handle a situation
nobody enumerated in advance. That pushes toward *"detect that this is
unfamiliar"* rather than *"have a rule for this"*.

---

## 2.2 · The model cannot tell you it is lost

If a network could reliably say *"this input is unlike my training data, do not
trust me"*, the problem would be much smaller.

It generally cannot. A classifier's softmax output is routinely near-certain on
inputs it has never seen anything like; that is a well-known property of the
architecture rather than a bug. Confidence, as reported by the model, is **not**
a measure of familiarity.

So the *"am I out of my depth?"* question must be answered by something that is
**not the model**, from evidence the model does not control.

**Consequence:** ASTRA's L3 Conformal Trust Module and L6 statistical gate exist
to answer that question from outside — and, crucially, the proposer is
**forbidden from seeing their answer** (SI-5), because anything an optimiser can
observe it can learn to game.

---

## 2.3 · Anything you can see, you can learn to exploit

This one is subtle and it shapes a lot of the architecture.

Suppose you let the proposer see whether it is about to be vetoed. Now it has a
new signal to optimise against. A trained system will learn to produce commands
that *pass the check* — which is not the same as commands that are *safe*, and
may be very nearly its opposite.

This is a general phenomenon: optimising against a proxy corrupts the proxy. It
is why a safety monitor must be **structurally invisible** to the thing it
monitors, not merely ignored by it.

**Consequence:** `SI-5`, enforced as a **type error** — the proposer's channel
exposes no read method, so a violation does not compile **[FACT** —
`ARCHITECTURE.md` §1**]**. It is not a convention anyone can forget.

**The same trap, from the inside.** This project measured it happening to itself.
Feedback loop **FB2** would have trained the digital twin on the proposer's own
commands — the twin exists to be an *independent* prediction of what a command
will do, and training it on the proposer's output makes it agree with the
proposer by construction. Measured in shadow: the non-conformity score fell
**40%** in a context where nothing had changed **[FACT** — `E-39`**]**. FB2 was
never wired.

---

## 2.4 · Redundancy does not help against a common cause

The classical answer to *"what if a component fails?"* is redundancy: run several
and vote.

Redundancy defends against **independent** failures. If three components share an
input, one bad input takes all three simultaneously — and the vote is unanimous
and wrong.

This is not theoretical here. ASTRA has three gates with genuinely different
implementations and different failure vocabularies. All three read L2's state
estimate. Corrupt that estimate and **all three go blind together**, which is
exactly what OD-9 measured **[FACT** — `E-46`, `E-48`**]**.

**Consequence:** the fail-safe machine's sensor-integrity counter reads
`StreamHealth` — computed at the **sensor boundary, before the filter touches
anything**. It is the one input to that machine which is *upstream of the common
cause* **[FACT** — ADR-0024**]**. Not a fourth gate; a different vantage point.

**The general lesson:** when adding a defence, the question is not *"is it
strong?"* but **"does it fail for a different reason than the ones I already
have?"** A strong defence that fails for the same reason adds nothing.

---

## 2.5 · The judge needs a reference, and the reference can go stale

To say *"this proposal is unusual"* you need something to be unusual *relative
to* — a **calibration corpus**, a recorded population of normal behaviour.

Three ways that goes wrong, and this project has measured all three **[FACT** —
`DATA_SPLIT_PROTOCOL.md` §4**]**:

1. **The corpus describes an older system.** Closing feedback loop FB1 changed
   the state estimate, which changed the score, and a corpus built before it drove
   the veto rate from **59.8% to 99.8%** — with no change to the policy.
2. **The corpus was built from the wrong source.** Rebuilding it from the
   deployed proposer rather than a placeholder moved the threshold from **1.18 to
   2.43** — the shipped threshold had been **less than half** what the running
   system routinely produced **[FACT** — `E-20`**]**.
3. **Nothing changed at all, and it went stale anyway.** On 6 August the live
   scores sat at **1.156**, *below the corpus minimum of 1.158*. No wiring moved.
   The corpus simply stopped describing the system **[FACT** — `E-41`, `OD-8`**]**.

The third is the nastiest, and it is still open. Re-measured on 15 August after
rebuilding everything the score depends on: **999 live samples against 1,000
calibration samples, zero overlap** **[FACT** — `E-159`**]**.

**And it is silent.** A gate whose scores sit *below* its threshold vetoes almost
nothing and looks perfectly healthy. The veto rate was 0.089% and that number was
**the mismatch, not discrimination** — which is how the defect survived unnoticed.

---

## 2.6 · A defence that fires too often is not a defence

Symmetric to the above, and easy to forget.

A monitor that stops the vehicle at the slightest anomaly is safe in the trivial
sense and useless in practice. Nobody ships it; if they do, operators disable it.

The project has an explicit position **[FACT** — ADR-0023 and the thesis it
states**]**:

> Others degrade to a halt when they leave their certified envelope; ASTRA is
> built not to.

And it has measured itself violating it. On a platform the digital twin was never
fitted to, the out-of-distribution counter climbed 0 → 100 and **halted the
vehicle**, while the arbitration layer was correctly holding a narrowed
safe-exploration envelope underneath it — one event escalated twice, defeating
the architecture's distinguishing claim using its own fail-safe machine **[FACT**
— `OD-12`**]**.

**Consequence:** *availability is a safety property too*. Almost every threshold
in the system is a trade between "stop too readily" and "notice too late", and
the project's convention is that such values carry **no default** and must be
declared by a deployment (`A-4`).

---

## 2.7 · And the meta-problem: you have to know what you have actually shown

Running late, but it belongs here, because it is the reason this project's
documents look the way they do.

It is easy to produce a number that is arithmetically correct and means nothing.
The measurement runs, the figure is plausible, the conclusion follows — and the
configuration it was taken in made the whole thing vacuous.

Three examples from **one day**, 15 August 2026 **[FACT]**:

- A detector was measured on a vehicle with **400 of 400 ticks vetoed and a final
  speed of zero**. It reported 7.35× separation and a correct prior conclusion was
  retracted on the strength of it. The mechanism being tested *is* the closed
  loop; the loop was open (`E-143`).
- A file was declared missing from an `ls` of three directories piped through
  `head -20`, where the cut landed one line above it (`E-145`).
- `100% inside` was reported from **one** sample, in the same column as a genuine
  `0.0%` from 999 (`E-161`).

**All three were assembled correctly from an observation nobody checked was
adequate.** All three were caught by distrusting a convenient result, and all
three are now guarded mechanically rather than remembered.

**Consequence for you as a reader:** when this folder reports a number, look at
what it was measured *in*, not just what it says.

---

## 2.8 · You should know this before moving on

**The six reasons, compressed**

| # | Difficulty | What it forces |
|---|---|---|
| 1 | Cannot test the space | Runtime detection of the unfamiliar, not enumerated rules |
| 2 | The model cannot self-report | An external judge, invisible to the proposer |
| 3 | Observable checks get gamed | SI-5 as a *type* error; FB2 refused on measurement |
| 4 | Redundancy fails to a common cause | A signal upstream of the shared input |
| 5 | The reference goes stale | Regeneration discipline, and OD-8 still open |
| 6 | Over-firing is also failure | Availability as a safety property; no default thresholds |

**Questions you should be able to answer**

1. Why is "test it more" not a solution — and what *kind* of problem is testing
   the wrong instrument for?
2. Why must the safety monitor be invisible to the proposer rather than merely
   ignored by it? Give the measured example.
3. Why does adding a fourth gate reading the same estimate add nothing?
4. Give three distinct ways a calibration corpus can stop describing the system.
   Which is still unresolved?
5. Why is a system that halts too readily a *safety* failure and not just an
   annoyance?

**Misconception to avoid**

> *"Surely you just need a better anomaly detector."*
>
> This project built four separate detectors for one fault and measured all four
> as silent — the innovation sequence, the innovation gate's flag, analytical
> redundancy, and cross-channel consistency (`E-53`, `E-105`, `E-94`, `E-106`).
> The root cause is shared: **a self-consistent lie slower than the sensor noise
> cannot be distinguished from truth by any function of a single sensor chain**
> (`E-107`). The answer was not a cleverer detector; it was **a second sensor**.

---

**Next:** [`3_Existing_Approaches.md`](3_Existing_Approaches.md)
