# 07 · Data Flow — one tick, end to end

The goal of this section is that you can **mentally simulate a tick**.

Three traces: a healthy tick, a tick where a gate refuses, and the OD-9 tick
where everything reports success and the vehicle leaves the lane.

**[FACT]** unless marked. The pipeline order is read from
`src/astra/runtime/pipeline.py`.

---

## Trace 1 — a healthy tick

### Stage 0 · The tick opens

The clock is **injected** (ADR-0010) — no component reads wall time. At 20 Hz the
tick period is 50 ms.

```
tick = TickId(1247)
```

### Stage 1 · Sensors publish → L1

**Before:** five independent `SensorSample`s, each with a payload and an
observation instant.

```python
SensorSample(modality=IMU,   observed_at=t, payload={"y": 0.031, "v": 12.4, "a": 0.08})
SensorSample(modality=GPS,   observed_at=t, payload={"y": 0.028, ...})
SensorSample(modality=LIDAR, observed_at=t, payload={"y": 0.033, ...})
...
```

**Transformation:** the bus stamps each stream with a **freshness verdict**
against the 50 ms budget.

**After:** a `FusedSensorFrame`, plus a health map:

```
{IMU: HEALTHY, GPS: HEALTHY, LIDAR: HEALTHY, CAMERA: HEALTHY, RADAR: HEALTHY}
```

**Why this transformation is necessary.** It is the **only** point where the
system can judge a sensor without having already trusted it. Everything after
this has been through the filter.

**What could go wrong.** A stream stops → `ABSENT`. A stream lags → `DEGRADED`.
**A stream lies fluently → `HEALTHY`, and this stage cannot tell.**

### Stage 1b · The health map forks

```
frame ──► L2 (the pipeline)
health ──┴──► L8 directly, bypassing everything
```

**This fork is ADR-0024** and it is the single most important arrow in the
system. Everything down the left branch shares a common cause; the right branch
does not.

### Stage 2 · L1 → L2 · the estimate

**Before:** three independent position readings (σ = 0.10, 0.20, 0.06 m).

**Transformation, two steps:**

1. **Fuse the redundant channels by median** (ADR-0033). The median of three
   cancels a liar: with two honest channels, a bias in the third is outvoted.
   *Measured: a 1 m bias in one channel produces a final deviation of 0.0168 m —
   the clean run's figure to four decimals (`E-153`).*
2. **UKF predict/update.** Sigma points through the process model, then corrected
   by the measurement.

**After:**

```
mean       = [px, py, v, ψ, a_lat]        e.g. [153.2, 0.029, 12.41, 0.002, 0.07]
covariance = 5×5 symmetric matrix         the uncertainty
```

**Why necessary.** Nothing downstream can use a raw reading. And the *covariance*
is not decoration — L6 divides by it.

**How errors propagate.** A wrong measurement moves the mean **and shrinks the
covariance**, because the filter treats a consistent reading as informative. That
is exactly the OD-9 mechanism: the filter grows **more** confident as it is lied
to.

### Stage 3 · L2 → L3 · trust

**Before:** the estimate, plus the filter's innovation (measurement minus
prediction).

**Transformation:** classify the context from speed and sensor health; produce
the Trust Index.

**After:** `TrustAssessment(trust_index=0.96, context_class=HIGHWAY_CLEAR, ...)`

**What could go wrong.** A wet-night tick classifies `HIGHWAY_CLEAR` because
`RAIN_NIGHT` is undecidable from the fast state — so it is judged against the
wrong population. Bounded, named, and a blocker on the CARLA rain phase.

### Stage 4 · L3 → L4 · the proposal — **and the SI-5 line**

**Before:** the state estimate and the trust assessment. **Nothing else.**

> The proposer cannot see the previous verdict, the posture, or the calibration
> table. Not by convention — the channel exposes no read method.

**After:** `ProposedCommand(values=(throttle, brake, steer))`.

**What could go wrong.** Anything. **This is the untrusted component**, and the
entire rest of the pipeline exists on the assumption that this output may be
arbitrary.

### Stage 5 · L4 → L5 · what would that actually do?

**Transformation:** the twin predicts the next state, using the **output head for
this context class** (ADR-0019).

**After:** `PredictedCommand` — the twin's one-step prediction.

**Why necessary.** It changes the question from *"does this command look
sensible?"* to **"is the consequence sensible?"**

### Stage 6 · The three gates — in parallel, on the same inputs

```
                    ┌─► L6  score vs calibrated population   → PASS
proposal+prediction ─┼─► L7a hard bounds                     → PASS
                    └─► L7b jerk, divergence from twin       → PASS
```

**L6 internally:**

```
departure = |proposal − prediction|   in the control dimension
sigma     = sqrt(P_f[lateral_acceleration])
score     = departure / sigma
verdict   = VETO if score > quantile(context, 1−ε) else PASS
```

**Note what the normalisation does:** when the filter is uncertain, σ is large,
the score is small, and the gate is **more permissive**. The gate relaxes exactly
when the state is least trustworthy — arising from the arithmetic.

**After:** three `GateVerdict`s, each with a reason code.

### Stage 7 · Merge — fail-closed

```
Verdict.merge([PASS, PASS, PASS])   → PASS
Verdict.merge([PASS, VETO, PASS])   → VETO      any veto wins
Verdict.merge([])                    → VETO      absence is refusal
ABSTAIN dropped before the fold
```

### Stage 8 · L8 · posture

**Two counters update independently:**

```
verdict not blocking → ood_counter  = max(0, ood − 1)          → 0
all critical healthy → integrity    = max(0, integrity − 1)    → 0
posture = worse(band(ood), band(integrity))                    → NOMINAL
capabilities withdrawn = {}                                     (nothing unhealthy)
```

### Stage 9 · L9 · issue

**Transformation:** apply the posture's speed cap through the projector, then
construct the `IssuedCommand` — the only place in the system where that type can
be built.

**After:** actuator values reach the vehicle. **~10 ms budget, 50 ms available.**

### Stage 10 · The record

One `DecisionRecord` written as JSONL, carrying **everything above**, chained to
the previous record's digest.

### Stage 11 · Feedback — FB1

The issued command is fed back to L2, so the *next* prediction propagates from
what was actually commanded rather than assuming the last estimate persists.

**Deliberately a prediction input, not a state assignment** — writing the
commanded value into `x` would make the estimate agree with the command *by
construction*, destroying the innovation the whole system uses to detect that the
vehicle is not doing what it was told. *The filter would report perfect health
precisely when the actuator had failed.*

---

## Trace 2 — a gate refuses

Diverges at **Stage 6**. Suppose the proposal implies a lateral jerk above the
limit.

```
L7b → VETO, reason LATERAL_JERK_EXCEEDS_LIMIT
merge([PASS, PASS, VETO]) → VETO
```

**Stage 8:** `ood_counter += 1`. Ten consecutive such ticks reach the DEGRADED
threshold. One does nothing — *that is what the counter is for.*

**Stage 9 — and this is ADR-0017:** L9 does **not** issue zero steering. It
issues **the largest step the jerk bound permits, in the direction asked for**.

**Why that matters.** Zero steering *latched*: a vehicle 1 m off centre needs
~21 ticks to correct, every one vetoed on jerk, so the correction could never
complete and the vehicle sat off-centre for ever, refusing to fix itself.

**A veto is a refusal of *this* command, not an instruction to do nothing.**

---

## Trace 3 — the OD-9 tick, where everything reports success

**[FACT** — `E-46`, `E-48`, `E-58`.**]** The most important trace here.

**Stage 1.** The IMU is frozen — same value, every tick, at full rate,
well-formed.

```
health = {IMU: HEALTHY, ...}      ← freshness cannot see this
```

**Stage 2.** The filter fuses a reading that is **maximally self-consistent**.
Because it agrees with itself perfectly, the innovation is small and the filter
becomes **more confident**: the covariance *shrinks*.

```
estimate: py = 0.02      truth: py = 4.199
```

**And the error goes somewhere invisible.** The inconsistency is pushed into
heading, which nothing observes: true 0.0686 rad, estimate 0.0017 rad.

**Stage 3.** Trust reads a small innovation and a tight covariance → high trust.

**Stage 4.** The proposer sees a vehicle at 0.02 m — nicely centred — and proposes
commands to *stay there*. **It is correcting toward a lie**, and every correction
moves the real vehicle further out.

**Stages 6–7.** All three gates read the same estimate.

```
L7a  corridor deviation 0.023 m  → PASS
L6   score small, σ tight        → PASS
L7b  jerk fine, twin agrees      → PASS
merge → PASS
```

**L7a's own source says why:** *"This bound is only as good as the position
estimate, and that is not a quibble."*

**Stage 8, before ADR-0024.** OOD counter falls (verdicts are clean). Posture
**NOMINAL**, all 400 ticks.

**Stage 9.** The command is issued. The vehicle drives further out of the lane.

### The four properties that make this the project's defining measurement

1. **Nothing was broken.** Every component behaved correctly given its inputs.
2. **Every check passed**, and the verdict trace was **identical to a clean run's**.
3. **The fault was actively driven** — the proposer's corrections made it worse.
4. **A veto could not have helped.** L9's fallback reads the same estimate.

### What Stage 1b changed

With ADR-0024, the health map forks *before* the filter. A dropout (a *quiet*
failure) marks the stream `ABSENT`, the integrity counter climbs, and the posture
escalates **with no gate involved at all**:

```
DEGRADED at +5 ticks · LIMP at +15 · HALT at +40      (11 Aug, E-87/E-88)
departure begins at +73
```

**1.65 seconds of margin**, and deviation **4.199 m → 0.167 m**.

**Re-measured 16 August 2026**, the same fault on today's system:

```
DEGRADED at +5 ticks · LIMP at +15 · HALT never       (counter still reaches 40)
no departure at all — final deviation 0.062 m
```

ADR-0030's health-level ceiling maps `DEGRADED → LIMP`, so the counter reaches its
HALT threshold and the escalation is refused; ADR-0033's redundancy is why the
departure no longer develops.

**But note precisely what was fixed.** ADR-0024 catches the stream going *quiet*.
A stream that keeps publishing fresh, well-formed, slowly-wrong values still
reads `HEALTHY` — which is why ADR-0033's **redundancy** had to follow, and why
that one closes the *bias* case (`E-153`) while a slow drift remains hard.

---

## Where uncertainty enters and how it moves

| Stage | Uncertainty | What happens to it |
|---|---|---|
| L1 | Sensor noise, per modality | Recorded as σ per channel |
| L2 predict | Process noise `Q` | **Added** — the covariance grows |
| L2 update | Measurement noise `R` | **Reduced** — a reading shrinks it |
| L2 no measurement | — | Grows unopposed. Deliberate: the right response to a tick where every sensor was absent |
| L6 | The covariance **is the denominator** | Wide covariance ⇒ permissive gate |

**The failure mode to remember:** a self-consistent lie makes the covariance
shrink, which makes the gate *stricter in appearance* while the estimate is
*further from truth*. Confidence and correctness move in opposite directions.

---

## You should know this before moving on

**The eleven stages**

`sensors → L1 health → (fork) → L2 estimate → L3 trust → ═SI-5═ → L4 proposal →
L5 prediction → 3 gates → merge → L8 posture → L9 issue → record → FB1`

**Questions you should be able to answer**

1. Which arrow bypasses L2, and what would be true without it?
2. Why does dividing by σ make the gate permissive when the state is uncertain —
   and is that right?
3. In Trace 3, at which stage could the fault first have been caught, and by what?
4. Why does a jerk veto issue a *reduced* command rather than none?
5. Why is FB1 a prediction input rather than a state assignment?

**Misconception to avoid**

> *"If all three gates pass, the command is safe."*
>
> Trace 3 is a counter-example that was **measured**, not imagined. All three
> passed on every one of 400 ticks while the vehicle left its lane by 4.199 m.
> The gates were correct about the estimate they were given. Correctness given a
> wrong input is not safety.

---

**Next:** pass 4 — `10_MATHEMATICS/`, `09_ALGORITHMS/`, `08_INTERNAL_MECHANICS/`,
`23_RUNTIME_BEHAVIOR/`.
