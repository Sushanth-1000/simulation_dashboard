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

**Partly fixed** by redundancy — a *bias* is now outvoted (`E-153`). A slow
**drift** remains hard, because a drift stays close to the median for a long time.

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

### L9 · One gate carries all the veto authority

**Why it exists.** Partly design — bounds should rarely fire — and partly defect
(L6 cannot fire). But the consequence stands: disarming L7b takes the veto count
to **zero on six of seven scenarios**.

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
| L1+L2+L7a+L8 in isolation (`benchmarks/latency.py`) | 0.160 ms | **0.442 ms** | 0.984 ms |
| **The full assembled tick**, 2,000 samples | 2.214 ms | **7.289 ms** | **57.063 ms** |

**The limitation is the last column.** One tick in 2,000 took **57 ms against a
10 ms budget**. A 20 Hz control loop that overruns by 5.7× has missed its slot,
and no mechanism in this system notices — there is no deadline monitor, and a
late tick is indistinguishable from a punctual one in the record.

**Why it exists.** The prototype targets legibility over performance — no NumPy in
the kernel, a Python hot path, a loop instead of a matrix product for
bit-comparability — and CPython gives no timing guarantee at all. The p50 of
2.2 ms is comfortable; the tail is where a soft-real-time language costs you.

**[OPEN]** The outlier is not diagnosed, and there is no deadline monitor.
Adding a simulator round trip in CARLA moves every one of these figures the wrong
way.

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
