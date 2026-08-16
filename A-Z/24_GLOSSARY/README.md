# 24 · Glossary

Every term you will meet, in plain English, with **where it appears** and **why
it exists**. A definition that does not say why the thing exists is a dictionary
entry, not an explanation.

Terms are grouped by what kind of thing they are, not alphabetically — alphabetical
order scatters the concepts that only make sense together. There is an
alphabetical index at the end.

---

## 24.1 · The architecture

### Core-A

The **untrusted** half. It contains the proposer and nothing else with authority.
Core-A may compute anything it likes; it may not act.

*Why it exists:* the project's thesis is that an untrusted component can be
governed. Naming the untrusted half explicitly is what makes "untrusted" a
structural property rather than a description.

### Core-B

The **trusted** half — estimation, uncertainty, the gates, arbitration,
fail-safe, actuation, the record. Everything that decides.

*Why it exists:* if the trust boundary is not a line you can point at in the
package structure, it is not a boundary.

### Layer, L1 … L9

The nine stages a tick passes through. L1 sensing, L2 estimation, L3 trust, L4
proposal *(Core-A)*, L5 twin, L6 statistical gate, L7a deterministic gate, L7b
physical gate, L8 fail-safe, L9 arbitration.

*Why nine and not fewer:* each layer is a distinct **kind** of judgement, and the
architecture's claim is that they fail differently. Merging two would merge their
failure modes.

### Gate

A component that returns a **verdict** on a proposed command. Three exist: L6
(statistical), L7a (deterministic), L7b (physical).

*Why "gate" and not "check":* a check reports; a gate has authority. A gate's
VETO stops the command absolutely (SI-3).

### Verdict

`PASS`, `ABSTAIN`, or `VETO`. Merged across gates by a **fail-closed fold**.

*Why three values and not two:* `ABSTAIN` means *"I cannot judge this"*, which is
different from *"I judge this acceptable"*. Collapsing them would let a gate that
could not evaluate a proposal look like a gate that approved it.

### Fail-closed fold

The merge rule for verdicts. Any `VETO` wins; an **empty** set of verdicts merges
to `VETO`.

*Why the empty case matters:* if no gate reported, something upstream failed.
Treating silence as approval makes a crashed gate indistinguishable from an
approving one.

### Posture

The fail-safe machine's state: `NOMINAL`, `CAUTION`, `DEGRADED`, `HALT`. Driven
by two counters.

*Why four and not two:* a binary "safe / unsafe" response is the thing operators
disable, because it fires too hard too often.

### Capability withdrawal

A **second axis**, orthogonal to posture. Each capability (e.g. *lane change*)
declares the sensor modalities it requires; if any required modality is unhealthy,
that capability is withdrawn while the vehicle keeps driving.

*Why an axis rather than a fifth posture:* it expresses *lose the camera, stop
offering lane changes, keep driving* — which no point on the posture ladder can
say. See ADR-0029.

### Arbitration

L9. Chooses between the proposed command, the fail-safe command, and a bounded
safe exploration command, and is the **only** thing that touches an actuator
(SI-7).

### Bounded safe exploration

What the vehicle does when no certified profile matches its situation: half the
nearest certified speed, a ±15° steering cone, no lane changes — instead of
halting.

*Why it exists:* halting is itself a hazard, and *"others degrade to a halt …
ASTRA is built not to."* It is the project's distinguishing behaviour.

### Separation invariant, SI-1 … SI-10

Ten properties the architecture guarantees, each with a **stated enforcement
kind** — compile-time, construction-time, runtime, or review — and each with a
test asserting *that the enforcement kind is what the document says*.

*Why the second test matters:* SI-6 was documented as `REVIEW`-only for four weeks
after the code had changed. A claim about enforcement can go stale exactly like a
number can.

### Assumption, A-1 … A-10

Things the *system* assumes about the world, each with what breaks if it is wrong.
A-2 timing, A-3 evidence format, A-4 no default thresholds, A-10 explainability
scoped to provenance.

### `DecisionRecord`

One per tick. Frame health, estimate, trust, proposal, prediction, every gate
verdict, posture, arbitration, issued command, config hash — appended as JSONL and
**hash-chained**.

*Why hash-chained:* it makes the log tamper-**evident**. An integrity check tells
you a file is intact; a chain tells you a row was altered *and where*.

---

## 24.2 · The mathematics

### Unscented Kalman Filter (UKF)

The state estimator, L2. Propagates a small set of deterministically chosen
**sigma points** through the non-linear model rather than linearising it.

*Why not an EKF:* an EKF needs a Jacobian derived by hand and re-derived whenever
the model changes, and it is a first-order approximation whose error grows with
curvature.

### Sigma points

`2n+1` points chosen to have the same mean and covariance as the current estimate
(van der Merwe scaled). Propagate the points, then recover a mean and covariance
from where they land.

*The intuition:* it is easier to push a few carefully chosen points through a
non-linear function than to approximate the function.

### `P` — the state covariance

How uncertain the filter is, and **in which directions**. A `5×5` symmetric
matrix, stored packed.

*Why it matters beyond the filter:* **L6 divides by it.** A cheaper estimator
without a covariance would delete an entire layer.

### `Q` — process noise

How much the filter believes the *model* is wrong per step.

### `R` — measurement noise

How much the filter believes the *sensor* is wrong.

### `S` — the innovation covariance

`S = H·P·Hᵀ + R`. The expected spread of the difference between what was measured
and what was predicted.

*Why it was wrong, and why fixing it hurt:* `S` did not carry `H·Q·Hᵀ`, so it was
too small — the filter was **over-confident**. Correcting it made the Kalman gain
smaller, the filter slower to trust each measurement, and lane deviation worse
(0.0122 m → 0.1218 m). Correctness cost performance; ADR-0033 then repaid it.

### Mahalanobis distance

A distance measured in units of the distribution's own spread — *"how many sigma
away"*, accounting for the fact that some directions are more uncertain than
others.

*Why it is the right distance here:* a 1 m error in a direction the filter knows
well is alarming; the same error where it is uncertain is not.

### Cholesky decomposition

Factorising a covariance to draw sigma points. **Raises** if the matrix stops
being positive definite.

*Why the raise is deliberately uncaught:* it converts to a `SafetyPathError`,
which is a VETO. *"A filter that quietly repaired its own covariance would return
a state estimate nobody could justify."*

### Conformal prediction

A way to get a coverage guarantee **without trusting your model**. Score a
calibration corpus, take a quantile, and anything scoring beyond it is flagged —
with a guaranteed error rate, under one assumption.

### Mondrian (class-conditional) ICP

Conformal prediction with a **separate corpus per context** (highway, urban, …).

*Why per-context:* a single global corpus would compare highway against urban and
call both mildly unusual, flagging neither.

### Exchangeability

The one assumption conformal prediction buys its guarantee with: the live samples
must be drawn from the same distribution as the calibration samples.

*Its status here:* **violated**. OD-8 — 999 live samples against 1,000
calibration samples, zero overlap. This is the project's most consequential open
defect.

### Non-conformity score

`departure / sigma` — how far the proposal is from the twin's prediction, divided
by the filter's own uncertainty in lateral acceleration.

### Quantile index

`⌈(n+1)(1−ε)⌉`. If that index exceeds the corpus size, the threshold is
**infinite** — meaning *this corpus is too small to support this confidence
level*, so the gate abstains rather than inventing a bound.

### Byzantine bound, `n ≥ 3f+1`

To tolerate `f` **lying** (as opposed to merely absent) components you need at
least `3f+1` of them. With `n = 3`, `f = 0` — three channels tolerate one *crash*
and **zero coordinated liars**.

### Median fusion

Three position channels reduced by taking the middle value.

*Why median and not mean:* a mean is pulled by an outlier without bound; a median
of three ignores one arbitrary value entirely.

### Residual monitor

`reading − median` per channel. The largest residual names the disagreeing
channel.

*The property that made it work:* the subtraction **cancels the truth term
exactly** (verified to 5e-17), so it measures *disagreement* and nothing else.
The earlier cross-channel candidate measured a *quantity*, so a large legitimate
manoeuvre moved it and it reported the manoeuvre as a fault.

### PINN — physics-informed neural network

The twin, L5. A learned model with a physics term in its loss.

*Why physics-informed:* it keeps the model honest where training data is thin.
Its limitation is that it produces a **point prediction with no uncertainty**.

### Constrained PPO

The proposer's training method. Constraints stay as **budgets** rather than being
folded into the reward as weights.

*Why it matters:* C-3 is the measured failure of the alternative — a jerk-limit
weight of 6.0 against a task reward capping at 2.0 made the constraint cost one
part in ten thousand, and the policy stopped the vehicle.

### EMA — exponential moving average

Used for **sensor decay**: a per-modality average that converges to the *duty
cycle* of a fault. `α = 2/(window+1)`.

*Why a duty cycle and not a count:* a count grows forever and tells you how long
the vehicle has been driving; a duty cycle tells you *what fraction of frames this
sensor is missing*, which is what a maintenance decision needs.

---

## 24.3 · The project's own vocabulary

### Credibility marker

How every claim in `CREDIBILITY_MATRIX.md` is qualified:

| Marker | Meaning |
|---|---|
| `[M-ext]` | Measured against an **external** reference. **Currently 0 of 30** |
| `[M-syn]` | Measured in this project's own synthetic environment |
| `[M-code]` | A property of the code, verified by inspection or a test |
| `[E]` | Argued from evidence, not directly measured |
| `[NOT DONE]` | Claimed somewhere and not built |

*Why this vocabulary exists:* it makes the difference between *"we measured it"*
and *"we measured it against something independent"* impossible to blur.

### Evidence row, `E-n`

One measurement, in `docs/EVIDENCE.md`, with the command that reproduces it. **A
number lives in exactly one place**; everything else cites it.

*Why:* a figure repeated in two documents means one of them is stale. That has
happened, and the convention exists because of it.

### Open defect, `OD-n`

A self-found defect in the register. Twenty-one rows: 16 closed, 1 reclassified,
1 partly closed, 3 open.

### Challenge, `C-n`

An entry in the challenge log — a thing that went wrong during development, and
what was decided about it.

### ADR

Architecture Decision Record. Thirty-four of them, each carrying the alternatives
and what they cost.

### Shadow harness

Running a mechanism with **no authority** and comparing it against the live one.
*"No mechanism gets authority until it has run with none."*

*What it bought:* FB2 and FB3 were refused **with numbers**, before either could
affect a run.

### Strict `xfail`

A test that documents a known-false claim and **fails the suite if the claim
becomes true**.

*Why strict:* two flipped to `XPASS` on 15 August, were reported as failures, and
forced the fix to announce itself. A comment would have let it land silently.

### Feedback loop, FB1 … FB4

FB1 wired (prediction input, **not** a state assignment). FB2 twin adaptation —
measured and **refused**. FB3 corpus self-calibration — measured and **refused**.
FB4 unbuilt.

*Why two were refused:* both would have made a guarantee unfalsifiable. FB3's
veto rate converges to ε *regardless of whether anything is wrong*.

### Ablation

Neutralising a gate to see what it was contributing. ADR-0021: an ablation
**neutralises** a gate, it never **removes** one — so the record still shows the
gate reporting.

### Health map

`StreamHealth` per modality, computed by L1 from **freshness**, before the filter
touches anything, and delivered **directly to L8**.

*Why it is the single most valuable signal in the system:* everything else is
downstream of one estimate, so when that estimate is corrupted, everything
computed from it agrees. This is the only input that does not.

### Sensor decay

Per-modality EMA of unhealthiness, reported in every audit row. **Drives
nothing** — deliberately. A vehicle that stopped for maintenance would be the
nuisance stop ADR-0028 removed, through another door.

### Health-level ceiling

A high-water mark: the worst observed health level caps how far the posture may
escalate *back down*. See ADR-0030.

### `partition.json`

The committed record of which scenarios/seeds belong to train, calibration and
test. Committed **before** any CARLA measurement, so the split cannot be chosen
after seeing results.

---

## 24.4 · Acronyms, quickly

| | |
|---|---|
| **ADR** | Architecture Decision Record |
| **CARLA** | The open-source driving simulator the project is moving to |
| **EKF / UKF** | Extended / Unscented Kalman Filter |
| **EMA** | Exponential moving average |
| **EnbPI** | Ensemble batch prediction intervals — the paper's claimed method; **withdrawn**, no ensemble was built |
| **EWC** | Elastic weight consolidation — anchors the twin against forgetting (ADR-0018) |
| **FSM** | Finite state machine — the fail-safe machine, L8 |
| **ICP** | Inductive conformal prediction |
| **JSONL** | One JSON object per line — the audit format |
| **MPC** | Model predictive control — a considered alternative to the learned proposer |
| **OOD** | Out of distribution |
| **PINN** | Physics-informed neural network |
| **PPO** | Proximal policy optimisation |
| **SI** | Both *Système international* (units) **and** *separation invariant*. Context distinguishes them; the units sense appears as "SI units", the invariant sense as "SI-n" |

---

## 24.5 · Alphabetical index

A-n · Ablation · ADR · Arbitration · Assumption · Bounded safe exploration ·
Byzantine bound · C-n · Capability withdrawal · CARLA · Cholesky · Conformal
prediction · Constrained PPO · Core-A · Core-B · Credibility marker ·
`DecisionRecord` · E-n · EKF · EMA · EnbPI · EWC · Exchangeability · Fail-closed
fold · Feedback loop · FSM · Gate · Health-level ceiling · Health map · ICP ·
JSONL · Layer · Mahalanobis distance · Median fusion · Mondrian ICP ·
Non-conformity score · OD-n · OOD · `P` · `partition.json` · PINN · Posture · PPO
· `Q` · Quantile index · `R` · Residual monitor · `S` · Sensor decay · Separation
invariant · Shadow harness · Sigma points · Strict xfail · UKF · Verdict

---

## 24.6 · The five terms to learn first

If you only take five away:

1. **Core-A / Core-B** — the trust boundary the whole design is built around
2. **Verdict and the fail-closed fold** — silence is refusal, not permission
3. **Exchangeability** — the assumption the statistical gate rests on, and the one
   currently violated
4. **The health map** — the only signal upstream of the common cause
5. **`[M-ext]` vs `[M-syn]`** — the difference between measured and *independently*
   measured, which governs how every number here should be read

---

**Next:** `25_FAQ/`.
