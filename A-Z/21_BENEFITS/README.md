# 21 · Benefits

**Each benefit with the mechanism behind it.** A list of adjectives is worthless;
what matters is *why* each property holds, and *how far* it holds.

Every entry carries its **status**: `PROVEN`, `DEMONSTRATED [M-syn]`, or
`CLAIMED` (structural but unmeasured).

---

## 21.1 · Technical benefits

### B1 · A violation of the trust boundary does not compile — `PROVEN`

**The mechanism.** `CommandProposer.propose` accepts state and trust. The write
side of the channel — `ProposalWriter` — **exposes no read method**. There is no
call to make, so a proposer that wanted a verdict could not be written, let alone
ship.

**Why that matters more than a rule.** Anything an optimiser can observe, it can
learn to exploit. A convention holds until someone is in a hurry; a missing method
holds always.

**How far it holds.** Against *code* that reads a verdict. **Not** against a
compromised process outside the type system — threat T4, and the threat model
says so rather than pretending otherwise.

### B2 · An error becomes a refusal, never a repair — `PROVEN`

**The mechanism.** A covariance that stops being positive definite raises from
Cholesky; the exception is **deliberately uncaught** and converts to a
`SafetyPathError`, which is a **VETO**.

**Why.** *"A filter that quietly repaired its own covariance would return a state
estimate nobody could justify, and the layer above would have no way to know."*

**[INTERPRETATION]** The generalisable idea: **repair destroys the evidence that
something broke.** In a system whose output is an evidence log, that is a worse
outcome than the failure.

### B3 · Absence of judgement is refusal, not permission — `PROVEN`

**The mechanism.** `Verdict.merge` is a fail-closed fold. An **empty** verdict set
merges to `VETO`.

**Why.** If no gate reported, something upstream failed. Treating that as approval
would make a crashed gate indistinguishable from an approving one.

### B4 · A unit mismatch is a build error — `PROVEN`

`NewType` per SI unit, converted **once** at the configuration boundary. A speed
cap in km/h and a speed in m/s are both `float` to a compiler that has not been
told otherwise.

**Limit, stated in its own ADR:** it stops *assignment*, not *arithmetic between
two units*. The remaining gap is real and recorded.

---

## 21.2 · Safety benefits

### B5 · One signal is upstream of the common cause — `DEMONSTRATED [M-syn]`

**The mechanism.** `StreamHealth` is computed by L1 from **freshness, before the
filter touches anything**, and goes **directly to L8** — bypassing L2, L3, the
proposer, the twin and all three gates.

**Why it matters.** Every other quantity in the system is downstream of one
estimate. When that estimate is corrupted, everything computed from it agrees.
This is the only input that does not.

**Measured:** dropout deviation **4.199 m → 0.167 m**; HALT at +40 against a
departure beginning at +73 — **1.65 s of margin**.

**How far it holds.** It catches a stream going **quiet**. A stream publishing
fresh, well-formed, *wrong* values stays `HEALTHY` — one third of OD-9, and the
project says so.

### B6 · A liar is outvoted before it reaches the estimator — `DEMONSTRATED [M-syn]`

**The mechanism.** Three position channels, fused by **median**. A median of three
is unmoved by one arbitrary value — unlike a mean, which an outlier pulls without
bound.

**Measured:** a 1 m bias gives a final deviation of **0.0168 m — the clean run's
figure to four decimals**. The biased arm and the healthy arm are
indistinguishable.

**And it names the liar:** with three channels the largest residual identifies
*which*, and `reading − median` cancels the truth term exactly (verified to
**5e-17**), so it measures disagreement and nothing else.

**How far it holds.** **One** liar. Two coordinated ones invert it (T1′).

### B7 · The response is graduated, on two independent axes — `DEMONSTRATED [M-syn]`

**The mechanism.** Four postures driven by **two** counters — *"is the command
being refused?"* and *"can I believe what I am told?"* — plus a **separate
capability axis** composed by intersection.

**Why two counters.** *"The gates refused forty commands"* and *"a sensor was dark
for forty ticks"* need different responses, and one integer cannot say which.

**Why the second axis.** It makes *lose the camera, stop offering lane changes,
keep driving* expressible. Before ADR-0029 a camera failure either stopped the
vehicle or did nothing at all.

**And recovery is bounded:** the counter's ceiling means the longest walk back to
NOMINAL is **91 ticks = 4.6 s**. Automatic *and* with a stated worst case.

### B8 · The vehicle keeps driving where it safely can — `DEMONSTRATED [M-syn]`

**The mechanism.** When no certified profile matches, L9 declares bounded safe
exploration — half the nearest certified speed, a ±15° steering cone, no lane
changes — instead of halting.

**And veto authority is untouched:** ADR-0023 froze the *counter*, not the gates.
*"Every gate still vetoes and every veto still stops the command reaching an
actuator; SI-3 is exactly as it was."*

**Why this is a safety benefit and not a convenience.** A defence that halts too
readily gets disabled by operators, and a stopped vehicle in traffic is a hazard.

---

## 21.3 · Research and evidence benefits

### B9 · Every decision is reconstructible — `PROVEN`

**The mechanism.** One `DecisionRecord` per tick carrying frame health, estimate,
trust, proposal, prediction, **every** gate verdict, posture, arbitration, issued
command and config hash — as append-only JSONL, **hash-chained** so the log is
tamper-*evident* rather than merely integrity-checked.

**Why it is scoped as provenance.** A-10: the question answered is *"why did the
vehicle do that, on what evidence, under which calibration"* — **without
model-internal attribution**, which is contested and hard to defend.

### B10 · A refutation is a deliverable — `DEMONSTRATED`

**The mechanism.** The shadow harness: run a mechanism with **no authority** and
compare it against the live one. *"No mechanism gets authority until it has run
with none."*

**What it bought:** FB2 and FB3 were **refused with numbers** rather than
opinions, before either could affect a run. Five drift detectors were refuted the
same way, and the shared cause is now an argument for redundancy.

**[INTERPRETATION]** This is the project's most transferable contribution — more
so than the architecture. It converts *"we think this would be bad"* into *"here
is the measurement."*

### B11 · A known-false claim is held by a mechanism — `PROVEN`

**The mechanism.** Strict `xfail`. A claim documented as false **fails the suite
if it becomes true**.

**Measured:** two flipped to `XPASS` on 15 August, were reported as **failures**,
and forced the fix to announce itself. A comment would have let it land silently.

### B12 · The documents cannot drift from the code — `PROVEN`

Three mechanisms, each from a scar:

| Mechanism | The scar |
|---|---|
| Enforcement kind asserted by a test | SI-6 documented as `REVIEW`-only for **four weeks** after the code changed |
| Schema version **pinned** by a test | Fired **seven times**, each forcing a schema change to be deliberate |
| Per-file coverage floor | `astra explain` shipped at **10.3%** with a green aggregate gate |

---

## 21.4 · Deployment and cost benefits — `CLAIMED`

### B13 · Predictive maintenance falls out of the safety monitor

**The mechanism.** Sensor decay — a per-modality exponential average converging to
the **duty cycle** of a fault — is computed from the *same* health map that
protects the vehicle, and reported per modality in every audit row.

**Why it is worth something commercially.** A fleet operator gets *"this camera
missed 23% of its frames"* at **zero extra sensor cost**, derived from a safety
mechanism rather than bolted beside one. And a schema-10 archive can be mined for
wear **retrospectively**.

**And it drives nothing** — deliberately. A vehicle that stopped for maintenance
would be the nuisance stop ADR-0028 removed, through another door.

### B14 · The degradation table is a measurement, not a document

`benchmarks/degradation.py` **drives the real fail-safe machine** once per
modality and prints what happened. A safety case's degradation concept and the
running system **cannot drift apart**, because the document is a measurement of
the system.

It also flags an **inert** modality — one whose loss does nothing at all — which
is the *"we added a sensor and forgot to wire its failure response"* integration
bug, made visible.

---

## 21.5 · What is *not* a benefit

**[INTERPRETATION]** Worth stating plainly, because a benefits section invites
over-reading:

- **Not** *"the AI is made safe"* — explicitly disclaimed.
- **Not** *"three independent chances to catch a problem"* — measured, two of
  three never object.
- **Not** *"validated"* — `[M-ext]: 0 of 30`.
- **Not** *"a false-negative rate below 1%"* — that is a **target**, and the
  project quotes no rate because none has been measured.

---

## 21.6 · You should know this before moving on

**The four strongest benefits**, by evidence quality:

1. **B1/B2/B3 — `PROVEN`.** Structural, true regardless of plant
2. **B5 — the signal upstream of the common cause.** The single most valuable
   architectural idea here
3. **B6 — a liar outvoted.** The most striking measurement: 0.8387 m → 0.0168 m
4. **B10 — refutation as a deliverable.** The most transferable practice

**Questions you should be able to answer**

1. Why is *"no read method"* stronger than *"do not read the verdict"*?
2. Why does the health map bypass L2, and what would be true without it?
3. Why does an error become a refusal rather than a repair?
4. Why does sensor decay deliberately drive nothing?
5. Which benefits are `PROVEN` and why are those the only ones true regardless of
   plant?

**Misconception to avoid**

> *"These benefits mean the system is ready."*
>
> The `PROVEN` ones are structural and will hold on any plant. The
> `DEMONSTRATED` ones hold **on a plant this project wrote**. Nothing here has
> been shown against an external reference, and the strongest benefits in the
> safety column are exactly the ones CARLA is meant to test.

---

**Next:** `22_LIMITATIONS/`.
