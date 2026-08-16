# 27 · Open research questions

Questions nobody in this project can currently answer — separated from
**engineering work** (section 29), which is *known how, not yet done*.

Each entry says why it is open, what would answer it, and how hard that is.

**A note on the distinction, because it matters.** *"Build a CARLA adapter"* is
engineering: the path is known and the difficulty is effort. *"How do you
calibrate a conformal predictor for a closed loop that changes its own input
distribution?"* is research: nobody knows, and effort alone does not close it.

---

## 27.1 · Tier 1 — Questions the project is currently blocked on

### R1 · How do you calibrate a conformal predictor inside a closed loop?

**Why it is open.** Conformal prediction assumes exchangeability. A closed loop
**changes its own input distribution** — the controller acts, the state moves, the
next sample is a consequence of the last decision. That is nearly the definition of
non-exchangeable.

**What has been tried and refuted here.** FB3, online requantilisation. Measured:
the veto rate converges to ε **regardless of whether anything is actually wrong**.
The mechanism that would fix staleness destroys the property it was fixing.

**What would answer it.** Adaptive conformal methods with a time-varying `ε`, or a
weighted-exchangeability formulation. Both exist in the literature; neither has
been applied here.

**Difficulty:** genuine research. **This is the project's hardest open question**,
and OD-8 is its symptom.

### R2 · Should the twin carry uncertainty, and what changes if it does?

**Why it is open.** The twin gives a **point prediction**. So `departure =
|proposal − prediction|` cannot distinguish *the proposal is unusual* from *the
twin is wrong*.

**Why it becomes urgent in CARLA.** Prediction P2 says the twin will be badly
wrong against a plant with suspension and tyre slip. Every twin error will present
as a proposer anomaly.

**What would answer it.** A twin with a predictive distribution — an ensemble,
MC-dropout, or a Bayesian last layer — and a non-conformity score that divides by
the *combined* uncertainty rather than the filter's alone.

**The complication that makes it research rather than engineering:** the score's
denominator currently means one specific thing, `√P_f[lateral_acceleration]`. If
the denominator becomes a sum of two uncertainties, **the corpus is no longer
comparable across the change** — and the archive has no field that records which
scoring rule produced a row (see L13).

**Difficulty:** hard. Unquantified anywhere.

### R3 · Are the three gates independent, and if not, what would make them so?

**Why it is open.** Measured: two of three never object across 2,800 ticks of a
suite built to break them. One cause is known (L6 cannot fire — R1). The
deterministic gate's zero is **not** explained.

**The deeper version of the question:** all three read **one estimate**. Even if
all three fired, would their errors be independent? A common-cause failure in L2
produces three *agreeing* gates, which is what OD-9 demonstrated.

**What would answer the shallow version:** CARLA prediction P3. What would answer
the deep version is a gate that does **not** read L2's estimate — and it is not
obvious what such a gate could judge.

**Difficulty:** the shallow half is a measurement; the deep half is architecture
research.

---

## 27.2 · Tier 2 — Questions about generality

### R4 · Is the core genuinely domain-independent?

**Why it is open.** ADR-0002 claims a domain-independent platform core, and NFR5
tests it with four "walls" — places where an automotive assumption is baked in.
Two were fixed by moving a symbol. **Wall 3 was not**, and is held as a strict
xfail.

**Wall 3:** L2's process model derives yaw rate from `a_lat / v` and refuses below
a minimum speed. A differential-drive platform turns on the spot, so there is no
such relationship. *"Unlike walls 1, 2 and 4 it cannot be fixed by moving a
symbol."*

**Wall 4** — the rename — needs a genuine **second domain**, not a better car.
CARLA is automotive; a warehouse robot is the test.

**What would answer it.** Either a process model abstract enough for both
kinematics — which risks being abstract enough for neither — or an admission that
the *core* is domain-independent and the *estimator* is not, with a documented
seam between them.

**Difficulty:** wall 3 is a modelling problem with a real design fork. Deferred by
explicit decision.

### R5 · How do you classify an environmental context you cannot observe?

**Why it is open.** `RAIN_NIGHT` is undecidable: precipitation and ambient light
are not in the fast state vector, and the classifier **refuses to guess** from a
friction proxy it cannot see.

**The consequence, which is bounded and named:** a wet-night tick classifies as
`HIGHWAY_CLEAR` and is judged against a population that does not match it.

**Why it is not merely engineering.** Adding a rain sensor answers it for rain and
not for the general case — *"which contexts must be **observable** for
class-conditional calibration to be sound, and what do you do about the ones that
are not?"* A Mondrian scheme is only as good as its taxonomy, and a taxonomy with
an unobservable class silently mixes populations.

**Difficulty:** the CARLA-specific instance is a decision (`§0b`, a blocker). The
general question is open.

### R6 · What is the right consequence model for a safety gate?

**Why it is open.** The PINN generalises where an analytical model would not, and
its physics term keeps it honest where data is thin. But an **analytical** model
would be far more explainable, and this is a vehicle whose dynamics are well
understood.

**[INTERPRETATION]** For a *safety case*, an analytical twin might be the better
engineering choice. The learned one buys generality the prototype has not yet
needed — and pays in explainability, which is the currency a safety assessor
actually spends.

**What would answer it:** running both against CARLA and comparing prediction
error *and* the resulting gate behaviour. Neither has been done.

---

## 27.3 · Tier 3 — Questions about the adversary

### R7 · Can a slow, self-consistent lie ever be caught from inside one chain?

**The finding, after five refuted detectors:**

> No rearrangement of downstream quantities creates information that was never
> upstream.

**Why it is open.** Redundancy fixed the *bias* case — one liar is outvoted. A slow
**drift** stays close to the median for a long time, so the residual stays small
for a long time.

**What would answer it.** A characterisation: given `n` channels, noise `σ`, and a
detection window `w`, what is the **fastest drift that goes undetected**? That is a
tractable statistical question and nobody here has posed it formally.

**Difficulty:** moderate, and unusually well-posed for a research question. Worth
doing.

### R8 · What does correlated compromise do to the Byzantine bound?

**Why it is open.** `n ≥ 3f+1` assumes **independent** compromise. A shared
supplier, a shared bus, a shared firmware image — or simply **the same fog** —
breaks that assumption, and the bound says nothing about what happens next.

**Why it is worse here than usual.** The failure is not degradation to silence. It
is **inversion**: the median becomes the lie and the monitor names the honest
channel. A correlated environmental effect on two of three channels produces a
confident, specific, **wrong** accusation in the evidence log.

**What would answer it.** A fault model with correlation, and a redundancy scheme
whose failure is silence rather than inversion.

### R9 · What can be said about a compromised process?

**Why it is open.** SI-5 is a **type** boundary. It stops code that reads a
verdict; it does not stop a process that reads memory. Threat T4 is stated and
explicitly out of scope: *"if reached, nothing in this architecture helps."*

**What would answer it** is not research so much as a different system — process
isolation, an enclave, or a hardware boundary. Worth stating because the
architecture's strongest structural guarantee has exactly one assumption
underneath it, and it is this.

---

## 27.4 · Tier 4 — Questions about the method itself

### R10 · How do you validate a governance layer at all?

**[INTERPRETATION]** The deepest question here.

A governance layer's job is to prevent things. Preventing things produces
**absence of evidence**. A run with zero vetoes is consistent with *"the governance
is working"*, *"the proposer is well-behaved"* and *"the gates cannot fire"* — and
the project has now been all three at different times without being able to tell
from the output.

**What partially answers it.** Fault injection — manufacture the event, check the
response. That is what the fault study does, and it is why the degradation table
drives the real machine.

**What it does not answer.** The false-positive side. You can manufacture faults;
you cannot manufacture *"all the normal driving that should not have been
vetoed"* — that requires an external distribution, which is the whole argument for
CARLA.

### R11 · Is *provenance* enough explainability for an assessor?

A-10 scopes explainability to **decision provenance** — *"why did the vehicle do
that, on what evidence, under which calibration"* — deliberately excluding
model-internal attribution.

**[INTERPRETATION]** Good scoping: model-internal attribution is contested and
hard to defend. But whether an assessor **accepts** it is an empirical question
about assessors, not about the system, and nobody in this project has asked one.

### R12 · Does the honesty premium exist?

The project bets that a register of 21 self-found defects makes it *more*
credible, not less. The counter-case is real: a comparable project with a green
suite and no register has the same defects, no list, and **looks better**.

**[INTERPRETATION]** Unfalsifiable from inside the project. It is a bet on the
reader.

---

## 27.5 · Ranked by what to do first

| | Question | Why this order |
|---|---|---|
| **1** | **R1** — conformal in a closed loop | Blocks the statistical gate entirely; everything downstream of OD-8 waits on it |
| **2** | **R2** — uncertainty on the twin | Becomes urgent the moment CARLA starts, per prediction P2 |
| **3** | **R3** — gate independence | The shallow half is one measurement, and it tests the central claim |
| **4** | **R7** — the fastest undetectable drift | Unusually well-posed, tractable, and closes a five-detector dead end properly |
| **5** | **R5** — unobservable contexts | Has a concrete blocker attached (`RAIN_NIGHT`) |

**Not on this list, deliberately:** R4 wall 3 and R6. Both are real, both are
deferred by explicit decision, and neither blocks CARLA.

---

## 27.6 · You should know this before moving on

**Questions you should be able to answer**

1. Why is *"just recalibrate the corpus online"* not the answer to OD-8?
2. Why does a twin with no uncertainty become a *bigger* problem in CARLA than in
   simulation?
3. Why can a governance layer's success not be read off a zero veto rate?
4. Why does wall 3 resist the fix that worked for walls 1 and 2?
5. Which failure mode here degrades toward a **confident wrong accusation** rather
   than toward silence?

**Misconception to avoid**

> *"These are things the project has not got round to."*
>
> Some are. R1, R2, R7, R8 and R10 are not — they are questions with no known
> answer, and the project's contribution to several of them is a **refutation**:
> here is a thing that looks like it would work, and here is the measurement
> showing it does not.

---

**Next:** `28_CURRENT_STATUS/`.
