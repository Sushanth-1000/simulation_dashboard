# 22 · Limitations

**Every entry answers: why does this limitation exist?** Not a list of
disclaimers — a list of causes, because a limitation you understand the cause of
is one you can reason about.

Ordered by how much they should change your view.

---

## Tier 1 — The ones that govern how everything else should be read

### L1 · Nothing has been measured against an external reference

**[FACT]** `[M-ext]: 0 of 30`.

**Why it exists.** The plant, L2's process model, the twin and the corpus are
**the same kinematic bicycle model**. When the twin predicts the plant accurately,
that is **two implementations of the same equations agreeing** — not evidence
about driving.

**What it invalidates.** Every accuracy claim. No false-positive or
false-negative rate exists anywhere in the project *because none has been
measured*.

**Fixable?** Yes — that is exactly what CARLA is for. And even then, `[M-ext]`
against one simulator, one town, one seed is narrower than it sounds.

### L2 · The conformal guarantee does not currently hold

**[FACT]** `E-159` — 999 live samples against 1,000 calibration samples, **zero
overlap**.

**Why it exists.** Conformal prediction buys its guarantee with **exactly one**
assumption — exchangeability — and the live loop is not exchangeable with the
corpus that judges it.

**Why it is worse than it sounds.** The failure is **silent and flattering**.
Scores sitting *below* the threshold produce a near-zero veto rate, which reads
as *"the proposals are good"*. That is how it survived from 6 to 15 August.

**Fixable in-house?** **No.** The corpus and the live loop are both things this
project wrote; making them agree would be tuning one until it matched the other,
which proves nothing.

### L3 · Two of three gates never object

**[FACT]** `E-162` — across 2,800 ticks of a suite built to break them:
`STATISTICAL` **VETO 0**, `DETERMINISTIC` **VETO 0**, `PHYSICAL` **149**, all on
one reason code. **`ABSTAIN` is zero for all three**, so the silent two are
*judging and finding nothing*.

**Why it exists.** Two different causes.

- **L6** cannot fire — its scores are below the corpus quantile (L2 above).
- **L7a** is a bound, and a bound *should* rarely fire. But **zero across a fault
  suite designed to break it** is different from *rarely*.

**What it invalidates.** The independence claim, D-3. *For an attacker there is
one gate to neutralise, not three.*

**[OPEN]** Whether L7a's thresholds are wrong or its traffic is too easy is
unresolved. CARLA prediction **P3** is the test.

---

## Tier 2 — Structural limits of the design

### L4 · All three gates read one estimate

**Why it exists.** L2 exists precisely so nothing above it handles raw readings
(SI-1, sensor opacity). That is a *good* property — and it makes L2 a **common
cause**.

**Measured:** OD-9. A frozen IMU took the vehicle 4.199 m off a 1.75 m lane with
every gate passing and a verdict trace identical to a clean run's.

**Partly mitigated** by the health map bypassing L2, and by redundancy. **Not
removed** — the gates still share the estimate.

### L5 · A slow, self-consistent lie is undetectable

**[FACT]** `E-107`, after five refuted detectors.

**Why it exists.**

> No rearrangement of downstream quantities creates information that was never
> upstream.

Every quantity on the record is computed from the same measurement. A lie slower
than the sensor noise is, from inside a single chain, **indistinguishable from
truth**.

**Partly fixed** by redundancy — a *bias* is now outvoted (`E-153`, verified
16 August: peak estimator error **1.1805 m → 0.1323 m**). A slow **drift** remains
hard, because a drift stays close to the median for a long time.

**And the fifth detector was re-run on 16 August with a harder result than
recorded.** The whiteness CUSUM does not separate the drift **at all** — the
faulted arm matches the control to every printed digit, where `E-143` had measured 1.03×.
Redundancy now stops the drift reaching the estimator, so there is no innovation
signature left to find. The refutation is stronger and the limitation is
unchanged: nothing sees the drift.

### L6 · The twin has no uncertainty

**Why it exists.** The twin produces a **point prediction**. So when L6 computes
`departure = |proposal − prediction|`, a large departure may mean *the proposal is
unusual* **or** *the twin is wrong* — and the score cannot tell them apart.

**Why it will bite in CARLA.** Prediction P2 says the twin will be badly wrong
against a plant with suspension and tyre slip. **Every twin error will present as
a proposer anomaly.**

**[OPEN]** Not quantified anywhere.

### L7 · The proposer is trained on truth and deployed against an estimate

**[FACT]** `E-155` — `train_policy` fits against the bare plant: no pipeline, no
UKF, no sensor bus.

**Why it exists.** Training through the full pipeline would be far slower and
would couple the policy to a filter that was still changing.

**[OPEN]** The cost is **unmeasured**. It is recorded in the evidence log and is
not a register row.

### L8 · Two coordinated liars invert the monitor

**[FACT]** Threat `T1'`. `n ≥ 3f+1` for Byzantine faults; `n = 3`, so **zero**
coordinated liars are tolerated.

**Why it is worse than a gap.** With two compromised channels agreeing, **the
median is the lie**, so the residual monitor flags the **honest** channel, names
it, and writes it to the evidence log.

> Every other entry in the threat model degrades toward silence. This one degrades
> toward **a false positive that looks like a successful detection.**

**And the correlation assumption is optimistic.** The bound assumes *independent*
compromise; a shared supplier, bus, firmware image or simply *the same fog*
breaks it.

### L9 · One gate carries all the veto authority — and on one fault it is the harm

**Why it exists.** Partly design — bounds should rarely fire — and partly defect
(L6 cannot fire). Measured 16 August: disarming L7b takes the veto count to
**zero on all seven scenarios**, while disarming L6 or L7a changes **not one cell**
of the ablation table.

**And the consequence is worse than concentration.** On `lateral_noise`, traced
tick by tick on 16 August:

| | vetoes | final m/s | final \|dev\| | **peak \|dev\|** | ticks outside ±1.75 m |
|---|---|---|---|---|---|
| governed | 125 | 4.214 | 1.3073 m | **1.7179 m** | **0** |
| L7b disarmed | 0 | 6.870 | 0.1384 m | 0.5854 m | 0 |

**The governed vehicle peaked 3.2 cm inside its own corridor bound.** Ungoverned
Core-A on the same fault ends at 0.148 m. **Neither arm ever left the lane** — the
harm is a near-miss and a slower vehicle, not a departure.

**What governs those ticks, measured per tick and per axis.** L7b vetoes
`LATERAL_JERK_EXCEEDS_LIMIT` on **125 of 200** post-fault ticks. Maximum
\|issued − proposed\| by issued-command origin:

| origin | ticks | throttle | brake | steer |
|---|--:|--:|--:|--:|
| `RATE_LIMITED` | 122 | **0.000000** | **0.000000** | 0.011977 |
| `PROPOSED` | 75 | 0.000000 | 0.000000 | 0.000000 |
| `SPEED_CAPPED` | 3 | 0.614747 | 0.791599 | 0.004285 |

**ADR-0017's rate limiter is a steering-axis limiter.** On all 122 ticks it
governs it leaves throttle and brake **bit-identical to the proposal** and moves
steering by at most **11.977 mrad**. The `throttle 0, brake 1.0` substitution
belongs to the **speed cap**, which fires on exactly three ticks — 351, 352, 353:

```
tick 351   origin    SPEED_CAPPED
           proposed  (throttle 0.6147, brake 0.2084, steer 0.0094)
           issued    (throttle 0.0000, brake 1.0000, steer 0.0137)
```

**[OPEN] — and this is the third explanation of this arm, two of which measurement
has refuted.** The first blamed a latched steering correction; the second said the
lateral bound was being discharged longitudinally, by braking. **The limiter does
not brake at all.** What remains established is the outcome — 1.7179 m peak, speed
falling 12.1821 → 4.2137 m/s, inside the corridor throughout — and *what governs
each tick*. **What causes the deviation is not established.** A steering axis
clipped on 122 of 200 ticks is a candidate again, which is where the first
hypothesis started; three hard speed-cap brakes are another; the policy's own
response to a corrupted lateral signal is a third. None has been measured.

**The design question stands regardless** and belongs in the register: should a
projector prefer the axis the violated bound lives on?

*Corrected 17 August 2026 by a verification pass that read `record.issued.origin`
per tick. The earlier drafts of this entry quoted tick 351 **by name** as the rate
limiter's work; it is one of the three speed-cap ticks. The error came from
picking the largest command substitution in the run and assuming it belonged to
the majority origin.*, undiagnosed, and it belongs in the
register rather than in a limitations list.

### L10 · The process model cannot represent a platform that turns on the spot

**[FACT]** OD-11 wall 3, held as a **strict xfail**.

**Why it exists.** L2's process model derives yaw rate from `a_lat / v` and
refuses below a minimum speed. A differential-drive platform has no such
relationship.

**Why it is the hardest of the four NFR5 walls:** *"unlike walls 1, 2 and 4 it
cannot be fixed by moving a symbol."*

### L11 · `RAIN_NIGHT` is undecidable

Precipitation and ambient light are not in the fast state vector, and the
classifier **refuses to guess** from a friction proxy it cannot see.

**Consequence, bounded and named:** a wet-night tick classifies as
`HIGHWAY_CLEAR` and is judged against a population that does not match it.

**And it is now a blocker on the CARLA demo**, which has a rain/night phase.

---

## Tier 3 — Engineering and operational limits

### L12 · The timing budget is met at the median and missed in the tail

**Corrected 16 August 2026.** An earlier draft of this section said timing was
unmeasured. It is measured, twice over, and the honest limitation is sharper than
the one it replaced.

| Measurement | p50 | p99 | max |
|---|---|---|---|
| L1+L2+L7a+L8 in isolation (`benchmarks/latency.py`) | 0.144–0.170 ms | **0.207–0.245 ms** | 0.474–0.573 ms |
| The full assembled tick, one run of 2,000 | 2.214 ms | 7.289 ms | 57.063 ms |

**Then it was run five times, and again ten times the next day.**

| | p50 | p99 | max | ticks over budget |
|---|---|---|---|---|
| 16 Aug, 5 runs | 2.148–2.246 | 2.768–**10.460** | 7.676–46.958 | **0–31** / 2000 |
| 17 Aug, 10 runs | 2.006–2.392 | 3.322–6.225 | 3.682–55.302 | **0–2** / 2000 |

**The median is solid and the tail is not — including between days.** p50 varies
by under 20% across sixteen runs. p99 spans 2.768–10.460 ms, and the single run
whose p99 exceeded the budget **has not recurred**. Budget violations ran 0–31 on
one day and 0–2 on the next.

**What reproduces is the maximum.** Both days produced individual ticks above
44 ms — 46.958 and 55.302 — so **a tick taking twenty-five times the median is a
repeatable event whose frequency is not.**

**The limitation is that nothing notices.** There is **no deadline monitor** — a
late tick is written to the record identically to a punctual one, so an overrun
is invisible in exactly the evidence log that exists to make behaviour
reconstructible.

*A single run had suggested "one tick in 2,000". Five runs show that figure was
the best of the five, not a typical one.*

**Why it exists.** The prototype targets legibility over performance — no NumPy in
the kernel, a Python hot path, a loop instead of a matrix product for
bit-comparability — and CPython gives no timing guarantee at all. The p50 of
2.2 ms is comfortable; the tail is where a soft-real-time language costs you.

**[OPEN]** The outlier is not diagnosed, and there is no deadline monitor.
Adding a simulator round trip in CARLA moves every one of these figures the wrong
way.

**And every figure above was measured on an idle machine.** `flake_hunt` puts the
same box under `stress-ng` with 32 workers and the full test suite slows by
**2.6× on 16 August** (91 s → 238.8 s) and **3.5× on 17 August** (78.2 s →
276.2 s). Nothing here establishes what the tick tail does under contention, and a
control loop shares its host with whatever else is running.

### L13 · The archive cannot say which filter produced a row

**Why it exists.** ADR-0032 changed the innovation covariance. That is a **code**
change, so neither the audit schema nor the config hash records it.

**Consequence:** a reader pooling a pre- and post-15-August archive has **nothing
in the record to warn them**. Recorded as the ADR's sharpest negative; unfixed.

### L14 · The evidence pack is not reproducible from a clean checkout

`var/` is gitignored by design, so a fresh clone has **no** twin, corpus or
policy — while every `[M-syn]` row is measured through all three.

**Mitigated** by `make artifacts` and `make artifacts-check`; **not removed** —
regeneration takes time and the policy is the long pole.

### L15 · Everything runs in one process, on one machine

No process boundary between Core-A and Core-B. SI-5 is a **type** boundary, which
protects against code that reads a verdict and **not** against a compromised
process (threat T4) — *"if reached, nothing in this architecture helps, and this
document says so rather than pretending otherwise."*

---

## Tier 4 — Limits of scope

| | Limit | Why |
|---|---|---|
| **L16** | No hardware, ever | Prototype scope |
| **L17** | One domain | CARLA is automotive; wall 4's rename needs a *warehouse*, not a better car |
| **L18** | No certification artefacts | ISO 26262 work item, not built |
| **L19** | Linux only | CARLA has **no macOS build** — the constraint that replaced RK-1 |
| **L20** | The paper and the code disagree in seven places | Six are specified but unapplied — the paper is not in this repository |

---

## 22.5 · The pattern behind the limitations

**[INTERPRETATION]** Three families:

**1 · One estimate, many readers.** L4, L5, L6, L9's fallback. The architecture's
central structural weakness, and the one it has done most to mitigate without
removing.

**2 · The judge and the judged share an origin.** L1, L2, and every `[M-syn]`
row. The plant, twin, corpus and process model are one model — so agreement is
not evidence.

**3 · Silent failure.** L2, L3, L12. A stale corpus vetoes nothing. A gate that
cannot fire looks well-behaved. **The most dangerous limitations here are the ones
that produce reassuring numbers**, which is exactly why the project's guards are
all of the form *refuse to report from a configuration where the measurement is
meaningless*.

---

## 22.6 · You should know this before moving on

**The three that should change your view most:** no external validation · the
conformal guarantee not currently holding · two of three gates silent.

**Questions you should be able to answer**

1. Why can OD-8 not be fixed in-house?
2. Why does a *zero* veto rate tell you nothing reassuring?
3. Why is a twin with no uncertainty a problem specifically for CARLA?
4. Why is wall 3 harder than the other three NFR5 walls?
5. What do L2, L3 and L12 have in common as *kinds* of limitation?

**Misconception to avoid**

> *"So it does not work."*
>
> That is as wrong as *"it works."* What is **PROVEN** is structural and holds on
> any plant. What is **DEMONSTRATED** holds on a plant this project wrote. What is
> **NOT VALIDATED** is everything about external accuracy. The useful sentence is
> *"here is exactly what has been shown, and here is exactly what has not"* — and
> the project's own documents are unusually good at supplying it.

---

**Next:** pass 8 — `24_GLOSSARY`, `25_FAQ`, `26_INTERVIEW_QUESTIONS`,
`27_RESEARCH_QUESTIONS`, `28_CURRENT_STATUS`, `29_REMAINING_WORK`.
