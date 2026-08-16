# 12 · Safety and Reliability

The distinction this section exists to make:

> **"The system works"** — it produces correct outputs on the cases tried.
>
> **"The system can be trusted to work safely"** — there is an *argument*, backed
> by *evidence*, that it behaves acceptably including on cases nobody tried.

ASTRA is much closer to the first than the second, and its own documents say so.

---

## 12.1 · The safety objectives

**[INTERPRETATION]** — assembled from `ARCHITECTURE.md` and
`SEPARATION_INVARIANTS.md`; the project does not state them as a numbered list.

1. **No proposed command reaches an actuator unexamined.**
2. **The examination cannot be learned around** by the thing being examined.
3. **A refusal is unconditional** — nothing overrides it.
4. **A failure produces a bounded, declared posture**, not an undefined state.
5. **Every decision is reconstructible** from evidence afterwards.
6. **The vehicle keeps driving where it safely can** — halting is itself a hazard.

Objective 6 is the one people forget, and the project is explicit: *"others
degrade to a halt when they leave their certified envelope; ASTRA is built not
to."*

---

## 12.2 · The ten separation invariants

**[FACT** — `SEPARATION_INVARIANTS.md`, read from the file.**]**

| Invariant | Enforcement | Fully enforced? |
|---|---|---|
| SI-1 Sensor opacity | `STATIC` | Partially |
| SI-2 Single state source | `STATIC` | Partially |
| **SI-3 Unconditional veto** | `RUNTIME` | **Yes, fully** |
| SI-4 Trust isolation | `STATIC` | **Yes, fully** |
| SI-5 One-way core channel | `STATIC` | Partially |
| SI-6 Veto-rate exclusion | `TEST` | **Yes** — upgraded from `REVIEW` when Core-A arrived |
| **SI-7 Sole actuation authority** | `RUNTIME` | **Yes, fully** |
| SI-8 Timing-domain separation | `TEST` | Partially |
| SI-9 Independent calibration validation | `STATIC` | Partially |
| SI-10 Evidence non-influence | `STATIC` | Yes, at the boundary that exists today |

**All ten are mechanically enforced.** None is left to review.

### Why "mechanically enforced" is the load-bearing phrase

**[FACT** — ADR-0012, and the decision log's own account.**]**

> `is_mechanically_enforced` returns `False` for exactly `REVIEW`, and a test
> asserts that correspondence — so an invariant **cannot be quietly downgraded
> and keep claiming a guarantee**.

And the project has a scar that justifies it: SI-6 was documented as
`REVIEW`-only, and *"it stayed wrong in a document for four weeks after the code
changed."*

**[INTERPRETATION]** The important idea is not that ten invariants exist. It is
that the *claim about how each is enforced* is itself checked by a test. A safety
document that can drift from the code is a liability rather than an asset.

### The honest gaps

The document names what does not exist yet: layer packages for SI-1/2/5, a
**measured** tick for SI-8, and a signing scheme for SI-9. Each section states
its own gap rather than claiming completeness.

---

## 12.3 · Failure modes and what addresses each

| Failure | Detected by | Mitigation | Residual risk |
|---|---|---|---|
| Sensor **stops** | L1 freshness → `ABSENT` | Integrity counter escalates in 2.0 s | None significant |
| Sensor **lags** | L1 freshness → `DEGRADED` | Ceiling caps escalation (ADR-0030) | Threshold choice is a judgement |
| Sensor **lies** (bias) | Median fusion residual | Outvoted; **never reaches the estimator** (`E-153`) | **Only with ≥3 channels** |
| Sensor **drifts slowly** | **Nothing** | — | **OPEN.** Five detectors refuted (`E-107`) |
| Sensor **fails intermittently** | Decay (reports only) | — | Reported, **drives nothing** |
| **Two sensors lie together** | **Nothing — worse than nothing** | — | **The monitor blames the honest channel** (`T1'`) |
| Proposal violates a bound | L7a | Veto → fallback | Fallback reads the same estimate |
| Proposal is statistically odd | L6 | Veto | **Currently vetoes nothing** (OD-8) |
| Transition inadmissible | L7b | Veto → largest admissible step | Carries all veto authority alone |
| Filter numerically breaks | Cholesky raises | → `SafetyPathError` → **VETO** | None |
| Sustained refusal | OOD counter | Graduated posture | Frozen during exploration by design |
| Context uncalibrated | L3 / L6 | **ABSTAIN**, then bounded exploration | Depends on classification being right |

**The two rows to remember are the empty ones:** *slow drift* and *two coordinated
liars*. Both are `[OPEN]`, both are stated in the project's own documents, and the
second is the worst shape in the threat model.

---

## 12.4 · The threat model

**[FACT** — `THREAT_MODEL.md`.**]**

| | Adversary | Realistic? |
|---|---|---|
| **T0** | **Wrong proposer** — emits arbitrary commands | Yes. **This is the design case, not an attack** |
| **T1** | Perturbs **one** sensor channel | Yes — GPS spoofing, adversarial patches, a compromised sensor ECU, CAN injection |
| **T1'** | Perturbs **f of n** channels, consistently | Yes, and **more so since 15 August**, because redundancy became the driven path |
| **T2** | Replaces a file before start-up — corpus, twin, config | Yes, wherever the filesystem or supply chain is reachable |
| **T3** | Writes to the audit log after the fact | Yes, and **the quietest of the four** |
| **T4** | Runs code **inside Core-B** | If reached, nothing in this architecture helps, **and this document says so rather than pretending otherwise** |

### T1' — the worst entry, and it is new

**[FACT** — `THREAT_MODEL.md` §5.1b, written 15 August.**]**

Median fusion tolerates `f` faults with `n ≥ 2f+1` for crash faults and
**`n ≥ 3f+1` for Byzantine** ones. `n = 3`, so:

| Adversary | Tolerated |
|---|---|
| One channel crashes or drifts randomly | 1 |
| One channel lies coherently | 1 |
| **Two channels lie coherently and agree** | **0** |

**And it is an inversion, not a gap.** With two compromised channels agreeing,
**the median is the lie** — so the residual monitor flags the **honest** channel,
names it, and writes it to the evidence log.

> Every other entry in the threat model degrades toward **silence**. This one
> degrades toward **a false positive that looks like a successful detection.**

**The defence created the surface.** ADR-0033 made redundancy the driven path
that morning; the adversary it enables was written down the same day.

**Also cheaper on availability:** `tolerated_faults = 0` in every shipped profile,
so silencing **one** channel is a **two-second denial of service** that did not
exist when the vehicle drove from a single sensor.

**[FACT]** Not measured. The bound is arithmetic and the inversion is read off
the monitor's own rule — both are arguments, and *this document's own standard is
that an argument is weaker than a measurement.*

### T1-B — where the veto authority actually sits

**[FACT** — `E-59`, `E-162`.**]** Disarming L7b takes the veto count to **zero on
six of seven scenarios**. On the current baseline: `STATISTICAL` 0,
`DETERMINISTIC` 0, `PHYSICAL` **149** — all on one reason code.

> For an attacker: **there is one gate to neutralise, not three** — and one of the
> other two is already neutralised by a defect.

---

## 12.5 · Fail-safe behaviour

**Graduated, not binary:**

```
NOMINAL → DEGRADED → LIMP → HALT
                              ╳ terminal
```

**Why HALT latches.** *"Resuming automatically because the sensor that failed
briefly reported plausible data again is precisely the behaviour that makes a
fail-safe untrustworthy."* Leaving it requires an explicit external act.

**Why everything else recovers automatically — and boundedly.** The counter is
capped, so the longest walk back to NOMINAL is **91 ticks = 4.6 s**. Recovery is
automatic *and* has a stated worst case.

**Two counters, one ladder,** because *"the gates refused forty commands"* and *"a
sensor was dark for forty ticks"* need different responses and one integer cannot
say which.

**Plus a second axis** — capability withdrawal — so a vehicle can be `NOMINAL`
with lane changes withdrawn. Composed by **intersection**, so it can only
subtract.

---

## 12.6 · Redundancy and fault tolerance

| Level | Present? |
|---|---|
| **Sensor redundancy** | **Yes** since ADR-0033 — three position channels, deliberately unequal noise |
| **Gate redundancy** | Structurally yes, **measurably no** — two of three never object |
| **Estimator redundancy** | **No.** One filter. It is the common cause |
| **Actuation redundancy** | **No.** One L9, by design (SI-7) |
| **Compute redundancy** | Out of scope — that is lockstep's job |

**The unequal-noise decision is worth understanding**: *"identical sigmas model
identical sensors, and identical sensors share a failure mode … a vehicle
carrying three copies of one part has one part."*

---

## 12.7 · Works vs. can be trusted

| | Status |
|---|---|
| **Structural properties** | **Strong.** `[M-code]`, true regardless of plant. Ten invariants, twelve contracts, strict typing |
| **Behavioural properties** | **Demonstrated on our own plant.** `[M-syn]` — shows the machinery runs |
| **Efficacy properties** | **Largely `[NOT DONE]`.** Five of ten gate-efficacy rows |
| **External validation** | **Zero.** `[M-ext]: 0 of 30` |

**And the number that is absent is the tell** **[FACT** —
`CREDIBILITY_MATRIX.md`**]**:

> No false-positive or false-negative rate appears anywhere in this document,
> because **none has been measured** and none can be until a row reaches
> `[M-ext]`.

**[INTERPRETATION]** A prototype with no error rates is not a weak prototype; a
prototype that *quotes* error rates it has not measured is. The absence here is a
discipline, not an omission.

---

## 12.8 · You should know this before moving on

**The three things to carry**

1. **All ten invariants are mechanically enforced**, and the *claim about
   enforcement* is itself tested
2. **Two failure modes have no mitigation**: slow drift, and two coordinated
   liars — the second **inverts** and blames the honest sensor
3. **`[M-ext]: 0 of 30`.** The safety argument's structure is strong; its evidence
   is entirely in-house

**Questions you should be able to answer**

1. Why is *"mechanically enforced"* a stronger claim than *"documented"* — and
   what four-week failure justified it?
2. Why is T1′ worse than having no redundancy at all?
3. Why does HALT latch when every other transition recovers automatically?
4. Why does the credibility matrix quote **no** false-positive rate?
5. If you were attacking this system, which single gate would you target and why?

**Misconception to avoid**

> *"Three gates plus a fail-safe machine plus redundancy means defence in depth."*
>
> Defence in depth requires the layers to fail for **different reasons**. Measured:
> all three gates read one estimate (OD-9), two never fire (`E-162`), and the
> redundancy that fixes the third case **creates** a new adversary that inverts
> the monitor (`T1'`). The architecture is *shaped* for depth. How much depth it
> delivers is the weakest column in the matrix, and the project says so.

---

**Next:** `13_TESTING_AND_VALIDATION/`.
