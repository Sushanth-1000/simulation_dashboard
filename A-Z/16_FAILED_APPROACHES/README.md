# 16 · What Did Not Work

**This section exists so you do not repeat any of it.**

Each entry: *what it was · why it looked right · how it was tested · what
happened · why it failed · what was learned · what replaced it.*

---

## F1 · EnbPI — the paper's stated first contribution

**What.** Ensemble batch prediction intervals: an ensemble of bootstrap models
producing conformal intervals.

**Why it looked right.** It is the paper's headline method, and the configuration
schema carried `ensemble_size: PositiveInt = 10` to match.

**What happened.** **No ensemble was ever built.** L3 and L6 both run Mondrian
class-conditional ICP — a different method with a different guarantee — and the
field was **read by nothing**: not the trust module, not the gate, not the corpus
generator.

**Why it failed.** It was never attempted. The config field made it *look*
present.

**Learned.** A configuration field nothing reads is **worse than a missing one**:
it reads as a knob a deployment can turn, appears in every rendered profile, and
tells a reviewer the ensemble exists.

**Replaced by.** Nothing — the claim was withdrawn. `ensemble_size` was **deleted**
on 15 August, and `extra="forbid"` now makes a profile still declaring it fail at
startup — *the right loudness for a withdrawn claim*.

---

## F2 · Elastic weight consolidation for the twin

**What.** ADR-0018 — a penalty term discouraging movement of weights important to
earlier contexts, so the twin does not forget one context while learning another.

**Why it looked right.** The standard answer to catastrophic forgetting, with a
literature behind it.

**What happened.** Superseded in effect by **ADR-0019**: one output head per
context class.

**Why it lost.** Per-context heads make forgetting **structurally impossible**
rather than **penalised**. A penalty is a pressure that can be outweighed; a
separate head cannot be overwritten by another context's gradient.

**Learned.** **[INTERPRETATION]** The recurring move in this project: prefer a
structure that cannot express the failure over a term that discourages it. The
same instinct produced SI-5 as a type error and ADR-0029's intersection.

**Kept:** the EWC measurements are **still in the evidence log**, footnoted as
historical, *because a table that silently dropped the measurements behind its
own changes would be a worse record than one carrying a footnote.*

---

## F3 · FB2 — twin adaptation from the proposer's commands

**What.** Continuously adapt the twin from observed `(state, command)` pairs.

**Why it looked right.** A twin that tracks the platform stays accurate as the
vehicle wears.

**How tested.** In **shadow** — run with no authority, compared against the live
score.

**What happened.** The non-conformity score fell **40%** in a context where
nothing changed, while the live score stayed flat to four decimal places
(`E-39`).

**Why it failed.** Its only training labels are the **proposer's own commands**.
The twin exists to be an *independent* prediction of what a command will do;
training it on the proposer's output makes it agree with the proposer **by
construction**. The gate's departure term shrinks toward zero, and the gate stops
discriminating.

**The twin's own module docstring named this as the way to disarm the statistical
gate — before it was measured.**

**Replaced by.** ADR-0020 proposed estimating the *control effectiveness*
instead… and **that was refuted too** (F4).

---

## F4 · ADR-0020's effectiveness estimator, as originally placed

**What.** Estimate the platform's steering effectiveness `B` from measured
response, instead of adapting the twin.

**Why it looked right.** It learns a *platform constant* rather than a policy —
seemingly immune to F3's circularity.

**What happened, as recorded (`E-63`).** Fed the **filtered estimate**, it returns
**140.000 on every platform** — including plants whose true `B` is **112.0** and
**168.0**.

> **This no longer reproduces, 16 August 2026.** Run twice, identically, `python
> -m benchmarks.effectiveness` now reads **117.929** from the estimate on the
> `B = 112` platform and **164.443** on the `B = 168` platform. The configured
> control value is 140.0 and the estimator is no longer returning it.
>
> **[INTERPRETATION]** The most likely cause is ADR-0032. The estimator was
> reading its own input back because the UKF's lateral-acceleration estimate was
> the `B` assumption propagated; redrawing the sigma points after the process
> noise changed how much of the *measurement* survives into that estimate, so the
> estimate now carries platform information it previously did not.
>
> **What this does and does not overturn.** The *conclusion* — do not feed FB2
> from the filtered estimate — still stands on the structural argument, and
> ADR-0020's status line refuses the original design outright. But the **headline
> evidence for it is gone**, and a refutation whose measurement no longer
> reproduces is not a refutation you can put in front of an assessor. `E-63`
> needs re-deriving or withdrawing. **[OPEN]**

**Why it failed. Structurally, not by tuning.** The UKF's process model *already
assumes* `B`, so its lateral-acceleration estimate is **that assumption
propagated**. The estimator was reading its own input back.

**Partial rescue, as recorded (`E-64`).** Fed the **raw measured response**
instead, it tracks the platform to within 1.7% — 111.341 against 112.0, 165.140
against 168.0.

> **Re-measured 16 August 2026:** **114.986** against 112.0 (**2.7% high**) and
> **167.702** against 168.0 (**0.18% low**). The rescue still works and the error
> is no longer symmetric — *"within 1.7%"* is now *"within 2.7%"*, and the sign
> has flipped on the low platform. Same cause as above.
But the residual runs **~1.5% low**, unexplained, *in the direction ADR-0020
names as dangerous*: an underestimated `B` shrinks the departure the score is
computed from.

**Status.** Defined in `assembly.py`, instantiated **only in a shadow benchmark**.
**Not wired.**

**Learned.** *"Independent"* must be checked against the whole chain. An estimator
downstream of an assumption cannot measure that assumption.

---

## F5 · FB3 — online requantilisation

**What.** Continuously update the conformal quantile from scores observed at
runtime.

**Why it looked right.** It keeps the corpus current — and OD-8 is precisely the
corpus going stale. It looks like the fix.

**What happened.** The veto rate converges to `significance_epsilon` **exactly**
(`E-40`).

**Why it failed — and this one is beautiful.** ε of *any* distribution lies above
its own 1−ε quantile. So requantilising on your own scores makes the gate fire at
exactly ε **regardless of whether anything is wrong**.

> **The gate stops being a detector and becomes a fixed-rate sampler.**

**Learned.** A calibration reference must come from **outside** the loop it
judges. Self-calibration is not adaptive; it is a tautology with a threshold.

**Replaced by.** Nothing yet. **OD-8 remains open**, and the honest fix is
CARLA-generated calibration under a data-split protocol — *outside* the loop.

---

## F6 · Five detectors for the slow drift

The single most instructive cluster in the project.

| # | Detector | Result |
|---|---|---|
| 1 | Innovation sequence **magnitude** | 1 cm/tick against σ = 0.1 m never leaves the band (`E-53`) |
| 2 | Innovation gate flag, γ = 7.5 | Fires on **tick 0 of every arm including the control** and nothing else (`E-105`) |
| 3 | **Analytical redundancy** from commands | Residual **2.2×–4.0× larger than the fault** (`E-94`) |
| 4 | Cross-channel consistency | Bias 4.14×; **drift 0.99×** (`E-106`) |
| 5 | Innovation **whiteness** / CUSUM | **1.03×** at every slack (`E-143`) — **not regenerable today**, the benchmark refuses (§18) |

**A note on how far these five can be trusted, 16 August 2026.** Detectors 1 and 2
were re-run inside `fault_study` and the innovation signal is **silent on all
seven arms**, which is rows 1 and 2 confirmed. Row 5 **cannot be re-run at all**.
Rows 3 and 4 were not re-executed in this pass.

### Why #3 failed is worth its own paragraph

It propagated a second estimate from the **issued commands alone**, never
corrected by a sensor — apparently independent.

**It was not.** FB1 feeds the command into the filter's *prediction* step, so the
two estimates share the same process model **and the same command input**; they
differ only by the measurement correction. The "parity residual" was therefore
*"how far the measurement pulled the filter"* — **which under a slow drift is
exactly the drift rate** (`E-95`).

**[INTERPRETATION]** A near-perfect example of an independence claim that is false
for a reason two layers away from where you are looking.

### The shared root

**[FACT** — `E-107`.**]**

> A self-consistent lie slower than the sensor noise **cannot be distinguished
> from truth by any function of a single sensor chain.** Every quantity on the
> record is downstream of the same measurement, and **no rearrangement of
> downstream quantities creates information that was never upstream.**

**Replaced by.** ADR-0033 — **a second sensor**. Not a cleverer statistic.

**Learned.** Five refutations with one shared cause is a stronger result than any
one detector working. It converts *"we could not find a detector"* into **"no
such detector exists in this class"** — and *that* is an argument for redundancy
rather than a confession of failure.

---

## F7 · Detector #5's false success — the near-miss

Worth separating, because it nearly reversed a correct conclusion.

**What happened.** The whiteness detector initially reported **7.35×** separation,
and `E-107` was **retracted**.

**Why it was wrong.** The run used a policy path that did not exist, fell back to
a placeholder proposer, and measured a vehicle with **400 of 400 ticks vetoed and
a final speed of zero**.

**Why that invalidates it.** `E-107`'s mechanism *is* the proposer closing the
loop on a corrupted estimate and driving the vehicle toward it. **With every
command vetoed and the vehicle stationary, that feedback does not exist**, so the
innovation keeps a persistent bias a closed loop would absorb.

> **The false signal was the mechanism's absence.**

**Re-run correctly:** 1.03× at every slack. The retraction was withdrawn and
`E-107` came back **stronger**, because the episode also demonstrates *why* — the
bias appears exactly when the loop opens and vanishes when it closes.

**How it was caught.** Two different proposers produced **bit-identical**
numbers. Impossible if the proposer mattered.

**Replaced by.** `StationaryVehicleError` — *a benchmark that measures a
closed-loop property must refuse to run when the loop is open.*

---

## F8 · Two smaller ones worth knowing

### Zero steering on a jerk veto

The original behaviour. It **latched**: a vehicle 1 m off centre needs ~21 ticks
to correct, every one vetoed on jerk, so the correction could never complete.

**Learned:** *a veto is a refusal of this command, not an instruction to do
nothing.* Replaced by ADR-0017's largest-admissible-step.

### Penalties instead of constraints in the reward

`action_rate_weight` at 6.0 against a task reward capping at 2.0 made a step at
exactly L7b's jerk limit cost **one part in ten thousand** (`C-3`).

**Result:** a policy that **stopped the vehicle** and collected the stationary
reward. Replaced by the Lagrangian dual, where budgets stay legible as budgets.

---

## 16.9 · The patterns

**[INTERPRETATION]** Five failures, five shapes worth recognising:

| Pattern | Instances |
|---|---|
| **Training a judge on the thing it judges** | FB2, FB3, F4 |
| **An independence claim false two layers away** | F4, the parity residual |
| **A penalty where a structure was needed** | EWC, reward penalties |
| **A measurement valid in the wrong configuration** | F7, and all three 15-August retractions |
| **A config field that makes a claim the code does not** | `ensemble_size` |

**The most transferable one is the first.** Three separate mechanisms were
refused for the same reason: *the reference must come from outside the loop it
judges*. If you propose a fourth adaptive mechanism here, that is the question to
answer first.

---

## You should know this before moving on

**Questions you should be able to answer**

1. Why does training the twin on the proposer's commands destroy the gate?
2. Why does FB3's veto rate converge to ε **regardless of whether anything is
   wrong**?
3. Why was the command-based parity residual not independent?
4. What do all five drift detectors share, and what does that *prove*?
5. Why was the whiteness detector's 7.35× meaningless — and how was it caught?

**Misconception to avoid**

> *"These were mistakes that wasted effort."*
>
> Every one is now **evidence**. FB2's and FB3's measurements are the argument for
> not wiring them; the five refutations are the argument for redundancy. A
> refutation you can cite is worth more than a mechanism you cannot defend — and
> all of them cost a shadow run, not a production incident.

---

**Next:** `17_DECISION_LOG/`.
