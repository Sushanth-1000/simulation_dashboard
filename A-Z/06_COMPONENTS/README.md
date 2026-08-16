# 06 · Components

Each layer answered the same nine ways:

*What is it · Why does it exist · What does it receive · What does it produce ·
How does it work internally · Why this implementation · What alternatives were
considered · Strengths · Weaknesses.*

**Depth note.** The *internals* — equations, update steps, complexity — are in
`08_INTERNAL_MECHANICS/` and `09_ALGORITHMS/`. This section is about **what each
component is for and why it is shaped the way it is**.

---

# L1 · Shared Sensor Bus

**What is it.** The single point where every sensor modality publishes, and where
freshness is judged. `src/astra/layers/l1_sensing/bus.py`.

**Why it exists.** Two reasons, and the second only became clear after OD-9.

1. **Sensor opacity (SI-1).** No layer above L2 may see a raw sensor reading.
   Layers reason about a *state estimate*, not about pixels or accelerations.
2. **It is the only place upstream of the estimator.** After OD-9 this became the
   architecture's most valuable property: everything downstream of L2 shares a
   common cause, and L1 does not.

**Receives.** `SensorSample` per modality — CAMERA, LIDAR, IMU, GPS, RADAR — each
with a payload and an observation timestamp.

**Produces.** A `FusedSensorFrame` carrying per-modality samples, **and a health
verdict per modality**.

**How it works internally.** Freshness against a budget. A reading older than
`staleness_budget_ms` (default 50 ms, from FR1) marks its stream `DEGRADED`; a
stream that stops entirely becomes `ABSENT`.

```
StreamHealth:  HEALTHY  →  DEGRADED  →  FAULTED  →  ABSENT
               fresh       stale        lying       gone
```

**The distinction that matters** **[FACT** — `StreamHealth` docstring**]**:

> `DEGRADED` is the state produced by the 50 ms staleness rule. It is distinct
> from `FAULTED`, which is raised by the innovation monitor: **a stale stream and
> a lying stream demand different responses, and collapsing them loses that
> distinction.**

For three years `FAULTED` was **unreachable** — the contract reserved it for a
lying stream and named a producer that was measured unable to detect one
(`E-105`). It got a real producer only with ADR-0026's residual monitor.

**Strengths.** Upstream of the common cause; cheap; the health signal is
*evidence* rather than a decision.

**Weaknesses.** **Freshness cannot see a lie.** A stream publishing fresh,
well-formed, slowly-wrong values stays `HEALTHY` for ever — which is exactly two
thirds of OD-9, and is why redundancy (ADR-0033) had to exist.

---

# L2 · Dual-Rate Unscented Kalman Filter

**What is it.** The state estimator. Fuses sensor readings into a best estimate
of where the vehicle is and how fast it is going — **with an explicit
uncertainty**.

**Why it exists.** Sensors are noisy and partial. Nothing downstream can reason
about a raw reading; everything needs *"where are we, and how sure are we?"*

**Receives.** A `FusedSensorFrame`. Also — via feedback loop **FB1** — the
command L9 last issued.

**Produces.** `FastStateEstimate`: a mean vector and a **covariance matrix**.

```
fast state x_f = [position_x, position_y, speed, heading, lateral_acceleration]
slow state x_s = [road_friction, tyre_wear, sensor_health_score]
```

**Why dual-rate.** Vehicle *motion* changes in milliseconds; *degradation* — tyre
wear, road friction — changes over minutes. Running both at 20 Hz would waste
computation and produce a badly-conditioned filter.

**Why *unscented* rather than extended.** An EKF linearises the model with a
Jacobian. The UKF instead pushes a set of **sigma points** through the true
non-linear model and reconstructs the mean and covariance from where they land —
more accurate for the same order of cost, and **no Jacobian to derive or get
wrong**.

**Alternatives considered** **[FACT** — ADR-0011, and the FilterPy removal**]**:

- **FilterPy** — used originally, then *removed*. Its final release is 1.4.5 from
  2018 and it is unmaintained; it sat **inside the safety path**, where ISO 26262
  asks for a qualification argument, and *"the upstream is gone"* is a poor
  opening. It dragged in scipy → matplotlib → pillow, none of which `astra`
  imports. The used surface was two classes and a dozen attributes.
- **Reimplemented to match it exactly**, including a choice that is arguably
  worse: the gain is `Pxz @ inv(S)` rather than `solve`, *because replacing a
  library and improving its numerics in the same change makes any difference
  unattributable to either.*

**Strengths.** Uncertainty is explicit and propagates. The covariance widens
automatically when a tick produces no measurement — so L6's gate becomes more
permissive precisely when the state is less certain, which is the mechanism the
paper describes *arising* rather than being special-cased.

**Weaknesses.**

- **It is the common cause.** Every gate reads it (OD-9).
- **It absorbs a self-consistent lie.** A frozen reading is maximally consistent,
  so the filter grows *confident* in it and pushes the inconsistency into an
  unobserved state — true heading 0.0686 rad while the estimate reported 0.0017
  (`E-58`).
- **The process model is a bicycle model** — it derives yaw rate from `a_lat / v`
  and refuses below a minimum speed, so a platform that turns on the spot cannot
  be estimated at all. This is **OD-11 wall 3**, still open, and *"unlike the
  other walls it cannot be fixed by moving a symbol."*

---

# L3 · Conformal Trust Module

**What is it.** Produces the **Trust Index** — *how familiar is this situation?*
— and classifies the situation into a **context class**.

**Why it exists.** §2.2 of the problem section: the model cannot self-report. The
*"am I out of my depth?"* question must be answered by something that is not the
model, from evidence the model does not control.

**Receives.** The state estimate and the filter's innovation.

**Produces.** A `TrustAssessment` — Trust Index, context class, the
class-conditional quantile, whether that class is calibrated.

**Context classes** **[FACT** — `ContextClass`**]**: `HIGHWAY_CLEAR`,
`URBAN_CLEAR`, `RAIN_NIGHT`, `DEGRADED_SENSOR`, `UNCLASSIFIED`.

**Why "Mondrian".** A single global calibration would compare highway driving
against urban driving and call both slightly unusual. **Mondrian
class-conditional** conformal prediction keeps a separate calibration population
per class, so a proposal is compared against *situations like this one*.

**A gap stated honestly in the code** **[FACT** — `classifier.py` docstring**]**:

> `RAIN_NIGHT` is **not decidable here**. Precipitation and ambient light are not
> in the fast state vector; the nearest proxy is road friction, which lives in
> the *slow* state and is not passed to this method. Returning `RAIN_NIGHT` on a
> friction heuristic the signature cannot see **would be inventing a
> classification**.

The consequence is bounded and named: a wet-night tick classifies as
`HIGHWAY_CLEAR`, is compared against a population that does not match it, and
that shows up as *degraded empirical coverage* rather than as a silent error.

**[INTERPRETATION]** This is a good example of the project's habit: the honest
failure was chosen over the convenient guess, and the cost was written down. It
is also now a **blocker on the CARLA demo**, which has a rain/night phase.

**Weaknesses.** A rule, not a model — cheap and inspectable, but it only knows
what the fast state carries. And the whole thing is downstream of L2.

---

# L4 · CMDP Proposer — **the untrusted AI**

**What is it.** The learned controller. Proposes a command each tick.

**Why it exists.** It is the thing being governed. Without it there is nothing to
govern.

**Receives.** The state estimate and the trust assessment. **And nothing else** —
`CommandProposer.propose` accepts state and trust and **no verdict, no fail-safe
state, no calibration table** (SI-5).

**Produces.** A `ProposedCommand`. Never an `IssuedCommand` — it cannot construct
one; the type refuses (SI-7).

**Why CMDP.** A *constrained* Markov decision process: maximise task reward
subject to explicit cost budgets — lane deviation, longitudinal acceleration,
collision rate — enforced by a Lagrangian dual rather than folded into the
reward. Constraints stay legible instead of disappearing into a weighted sum.

**How it is trained** **[FACT** — `train_policy.py`**]**: PPO against
`SyntheticDrivingEnv`, 48 rounds × 16,384 steps.

**The weakness worth knowing** **[FACT** — `E-155`**]**:

> `train_policy` trains against the bare plant — **no pipeline, no UKF, no sensor
> bus**. The proposer has only ever seen *ground truth*, and at deployment it
> reads an *estimate*.

**[OPEN]** What that train/serve skew costs has never been measured. It is
recorded in the evidence log and is **not** currently a register row.

**[INTERPRETATION]** This is also the reason the CARLA plan leads with the
*transferred* policy rather than a retrained one: a proposer that transfers badly
is precisely the case the architecture exists for.

---

# L5 · Physics-Informed Digital Twin

**What is it.** A learned model that predicts *what a command will actually do* —
`(state, command) → next state`.

**Why it exists.** It converts the question from *"does this command look
reasonable?"* to **"is the consequence of this command reasonable?"** — which is
a much better question, and it gives L6 and L7b something to compare against.

**Receives.** The state estimate, the proposed command, and the **context class**.

**Produces.** A `PredictedCommand` — the twin's one-step prediction.

**Why "physics-informed".** The loss includes a term penalising violation of the
kinematic relations, so the network is pulled toward physically-consistent
predictions rather than merely fitting the data.

**The architectural decision worth knowing — ADR-0019.** One **output head per
context class**, rather than one network plus a consolidation penalty.

The original design (ADR-0018) used **elastic weight consolidation** — a penalty
term that discourages moving weights important to earlier tasks. It was
*superseded in effect*: per-context heads make forgetting **structurally
impossible** rather than penalised. The measurements behind EWC are kept in the
evidence log with a footnote, *because a table that silently dropped the
measurements behind its own changes would be a worse record than one carrying a
footnote.*

**Weaknesses.**

- **It was trained on the same bicycle model as everything else.** Twin, corpus
  and policy all descend from one plant — the generator and the judge agree by
  construction.
- **[FACT** — CARLA plan prediction P2**]** it is expected to be *badly wrong*
  against CARLA, which has suspension, tyre slip and drivetrain lag the bicycle
  model does not.
- **FB2, which would have kept it current, was refused** — its only training
  labels were the proposer's commands, so the twin would have regressed onto the
  thing it exists to be independent of. Measured: the score fell **40%** in a
  context where nothing changed (`E-39`).

---

# L6 · Statistical Gate (Inductive Conformal Prediction)

**What is it.** Scores the proposal against the twin's prediction and asks
whether that score is unusual **for this context class**.

**Receives.** The proposal, the twin's prediction, the state covariance, the
context class, and the calibration corpus.

**Produces.** A `GateVerdict` — PASS, VETO or ABSTAIN.

**How it works internally.** A **non-conformity score**: how far the proposal
departs from the prediction, normalised by the filter's own uncertainty in the
control dimension.

```
score = departure / sigma        where sigma = sqrt(P_f[lateral_acceleration])
```

Then: **is this score above the 1−ε quantile of the calibration population for
this class?** If yes, VETO.

**The normalisation is the elegant part.** Dividing by the filter's own σ means
the gate automatically becomes **more permissive when the state is less certain**
— the mechanism the paper describes, arising from the arithmetic rather than
being special-cased.

**Why conformal prediction.** It gives a **distribution-free** coverage
guarantee: it does not require the model to be well-specified. That is unusual
and valuable — most uncertainty methods are only as good as their model.

**And what it costs** **[FACT** — `exchangeability.py`, `OD-8`**]**: the
guarantee is bought with **exactly one assumption — exchangeability** — and this
project has measured it **violated**: 999 live samples against 1,000 calibration
samples, **zero overlap** (`E-159`).

> The gate still emits verdicts. **They do not mean what the theory says.**

**Weaknesses.** Depends entirely on a corpus that can go stale three different
ways (all three measured — see `02_PROJECT_HISTORY`). Currently vetoes **nothing**
(`E-162`), and that silence is OD-8 seen from the gate's side.

---

# L7a · Hard Safety Shield

**What is it.** The bounds check. Speed, lateral acceleration against available
friction, stopping distance, lane corridor.

**Why it exists.** Some things are wrong regardless of what any model or
population says. A shield does not need a corpus and cannot go stale.

**Reason codes** **[FACT** — read from `shield.py`**]**:
`LATERAL_ACCELERATION_EXCEEDS_FRICTION`, `LATERAL_OFFSET_EXCEEDS_CORRIDOR`,
`STOPPING_DISTANCE_EXCEEDS_ASSURED_CLEAR`, `SPEED_EXCEEDS_LEGAL_LIMIT`,
`STATE_NOT_FINITE`.

**Strengths.** Simple, inspectable, no learned component, no calibration.
Precisely the kind of thing a safety assessor can read and agree with.

**Weaknesses — and this is the important entry.**

**It reads the state estimate.** Its own source says so: *"This bound is only as
good as the position estimate, and that is not a quibble."* Under a frozen IMU it
reported a corridor deviation of **0.023 m** while the true figure was **4.199 m**.

**And it almost never fires.** One veto in roughly 500,000 nominal ticks (`N-9`),
and **zero across 2,800 ticks of the fault suite** (`E-162`). It **PASSes** every
tick — it is judging, and finding nothing.

**[OPEN]** Whether that means its thresholds are wrong or its traffic is too easy
is unresolved. CARLA prediction **P3** says it should finally fire in real
driving; if it does not, that is a finding about the gate rather than the road.

---

# L7b · Physical Admissibility Gate

**What is it.** Bounds the *change*: lateral jerk, and divergence from the twin.

**Why it exists.** L7a asks *"is this state legal?"*. L7b asks **"is this
transition physically admissible?"** — a comfort and controllability question
L7a's absolute bounds cannot express.

**Reason codes:** `LATERAL_JERK_EXCEEDS_LIMIT`, `PROPOSAL_DIVERGES_FROM_TWIN`,
`INPUT_NOT_FINITE`.

**The decision worth knowing — ADR-0017.** A jerk veto originally issued **zero
steering**. That latched: a vehicle 1 m off centre needs ~21 ticks to correct,
every one vetoed on jerk, so the correction could never complete. It now yields
**the largest admissible step in the direction asked for**.

**[INTERPRETATION]** This is the clearest single example of *"a defence that
fires too often is not a defence"*. The gate was behaving exactly as specified
and the specification made the vehicle undriveable.

**Strengths.** In practice it does **all** the veto work — 149 of 149 (`E-162`).

**Weaknesses.** That is also the concern: one gate carrying all the authority on
**one reason code** is a single target for an adversary (threat `T1-B`).

---

# L8 · Fail-Safe State Machine

Covered structurally in `05_CURRENT_ARCHITECTURE` §5.5. The component notes:

**Why a *counter* and not a flag** — one integer gives three properties at once:
it distinguishes a glitch from a fault, recovery is **the same mechanism run
backwards**, and it is auditable as one number per snapshot.

**Why HALT is different.** Every other transition is symmetric; HALT is entered
on the counter but **never left on it**. *"Resuming automatically because the
sensor that failed briefly reported plausible data again is precisely the
behaviour that makes a fail-safe untrustworthy."* Leaving HALT requires an
explicit external `reset`.

**Bounded recovery.** The counter is capped at the HALT threshold, which puts a
*duration* on recovery: the longest walk back to NOMINAL is 91 consecutive clean
ticks — **4.6 seconds at 20 Hz**. Recovery is automatic *and bounded*.

**The most-corrected component in the project** — five ADRs in five days
(0024, 0027, 0028, 0029, 0030) plus decay (0031). Each because the original was
written when there was **one sensor**, and every assumption resting on that had
to be found one at a time.

---

# L9 · Runtime Calibration Manager

**What is it.** The actuation authority, the arbitrator, and the fallback.

**Three jobs.**

1. **Issue.** The only component that may construct an `IssuedCommand` (SI-7).
   It applies the posture's speed cap through a `CommandProjector` so the cap
   binds on an actuator — OD-2 was that cap being *recorded* and applied to
   nothing.
2. **Fall back.** When a proposal is refused, a proportional controller supplies
   a command. **Note the OD-9 caveat:** the fallback reads the same estimate, so
   it does not rescue a corrupted one.
3. **Arbitrate calibration.** Five outcomes: `CONTINUE`, `SHADOW_EXECUTION`,
   `SWITCH_COMMITTED`, `ROLLBACK`, `SAFE_EXPLORATION`.

**Bounded safe exploration** is the architecture's distinguishing behaviour. When
no certified profile matches the context, the vehicle **keeps driving** inside a
narrowed envelope — half the nearest certified speed, a ±15° steering cone, no
lane changes — instead of halting.

**And its veto authority is untouched.** ADR-0023 froze the *OOD counter* during
exploration, not the gates: *"every gate still vetoes and every veto still stops
the command reaching an actuator; SI-3 is exactly as it was."*

**The vehicle proposes calibration *work*, never a calibration** (ADR-0025) — it
can say *"this context is uncovered, someone should calibrate it"*; it cannot
calibrate itself. Self-calibration would let the system widen its own thresholds,
which is the OD-7/FB3 failure shape from another direction.

---

## You should know this before moving on

**Each layer's single most important weakness**

| Layer | The thing to remember |
|---|---|
| L1 | Freshness **cannot see a lie** |
| L2 | It **is** the common cause; absorbs self-consistent lies; bicycle model |
| L3 | `RAIN_NIGHT` is undecidable — honestly refused rather than guessed |
| L4 | Trained on **ground truth**, deployed against an **estimate** |
| L5 | Same plant as everything else; FB2 refused |
| L6 | Exchangeability **violated**; currently vetoes nothing |
| L7a | Reads the estimate; fires essentially never |
| L7b | Does **all** the veto work, on one reason code |
| L8 | Corrected five times in five days |
| L9 | The fallback reads the same estimate a veto was meant to escape |

**Questions you should be able to answer**

1. Why was FilterPy removed, and why was the replacement made *deliberately no
   better*?
2. Why does L5 have one output head per context instead of one network?
3. What single assumption does L6's guarantee rest on, and is it satisfied?
4. Why did a jerk veto issuing zero steering make the vehicle undriveable?
5. Why can L9's fallback controller not rescue a corrupted estimate?

---

**Next:** `07_DATA_FLOW/` — one tick, traced end to end.
