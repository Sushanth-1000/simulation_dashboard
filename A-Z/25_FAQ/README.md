# 25 · Frequently asked questions

The questions people actually ask, in the order they usually ask them. Answers
are short where the honest answer is short.

---

## 25.1 · What is it?

### Q1 · In one sentence, what is ASTRA?

A nine-layer **runtime governance** system that sits between an AI controller and
an actuator, judges every command before it is issued, degrades in graduated steps
rather than halting, and writes an evidence record for every decision.

### Q2 · Does it make the AI safe?

**No, and the project explicitly disclaims that.** It makes the *system*
governable. The AI stays exactly as untrustworthy as it was; what changes is that
nothing it proposes reaches an actuator without passing three gates, and that
every decision is on the record.

### Q3 · How is this different from just adding safety checks?

Three things a check does not have.

- **Authority that cannot be bypassed.** A VETO stops the command absolutely
  (SI-3), and the proposer has no way to see, let alone influence, a verdict —
  the read method does not exist.
- **A graduated response.** Four postures plus a capability axis, rather than
  *stop / do not stop*.
- **An evidence record.** One row per tick, hash-chained, sufficient to
  reconstruct why the vehicle did what it did.

### Q4 · Is it a self-driving car?

No. It is the **governance layer** a self-driving stack would sit inside. The
vehicle in the simulation exists to give the governance something to govern.

---

## 25.2 · Does it work?

### Q5 · Does it work?

**That is the wrong question, and the project's own documents say so.** Split it:

- What is **PROVEN** — structural properties that hold on any plant: a trust
  boundary that does not compile if violated, an error that becomes a refusal
  rather than a repair, an empty verdict set that merges to VETO.
- What is **DEMONSTRATED** — measured, but on a plant this project wrote: a frozen
  sensor's departure cut from 4.199 m to 0.167 m, a 1 m sensor bias that never
  reaches the estimator.
- What is **NOT VALIDATED** — everything about external accuracy. `[M-ext]: 0 of
  30`.

### Q6 · Why does it matter that the plant is your own simulator?

Because the plant, the estimator's process model, the twin and the calibration
corpus are **the same kinematic bicycle model**. When the twin predicts the plant
accurately, that is two implementations of the same equations agreeing — it is not
evidence about driving.

### Q7 · What is the single biggest problem right now?

**OD-8.** The statistical gate's conformal guarantee requires exchangeability
between the calibration corpus and the live loop, and there is **zero overlap**
between them — 999 live samples against 1,000 calibration samples.

### Q8 · Why is that worse than it sounds?

Because the failure is **silent and flattering**. Live scores sit *below* the
threshold, so the veto rate is near zero, which reads as *"the proposals are
good."* That is how it survived from 6 to 15 August without anyone noticing.

### Q9 · Can you not just fix it?

**Not honestly, in-house.** The corpus and the live loop are both things this
project wrote. Making them agree would mean tuning one until it matched the other,
which proves nothing. It needs an environment the project did not author — which
is what CARLA is for.

### Q10 · How many of the three gates actually fire?

**One.** Across 2,800 ticks of a suite built to break them: physical 149 vetoes,
statistical **0**, deterministic **0** — and `ABSTAIN` is zero for all three, so
the silent two are judging and finding nothing. The statistical gate cannot fire
because of OD-8; the deterministic gate's zero is `[OPEN]`.

---

## 25.3 · Design questions

### Q11 · Why nine layers? Is that not over-engineered?

Each layer is a distinct **kind** of judgement, and the architecture's claim is
that they fail differently. Merging two merges their failure modes. That said —
see Q10 — the measured independence of the three gates is currently much weaker
than the design intends, and that is recorded as a defect rather than argued away.

### Q12 · Why does the proposer have no way to read a verdict?

Anything an optimiser can observe, it can learn to exploit. A *convention* not to
read the verdict holds until someone is in a hurry. A **missing method** holds
always — the violating code does not compile.

### Q13 · Why does an error become a refusal instead of being repaired?

Because repair destroys the evidence that something broke, and this is a system
whose output is an evidence log. A filter that quietly restored its own covariance
would return a state estimate nobody could justify, and the layer above would have
no way to know.

### Q14 · Why keep driving instead of stopping when something is wrong?

Two reasons, and both are practical rather than ideological.

- A stopped vehicle in traffic is a hazard, not a safe state.
- A defence that fires too readily gets **disabled by operators**, at which point
  it protects nothing.

So when no certified profile matches, the vehicle explores under a narrowed
envelope: half the nearest certified speed, ±15° steering, no lane changes. Every
gate still vetoes and every veto still stops the command — ADR-0023 froze the
*counter*, not the gates.

### Q15 · Why three sensor channels and not two, or five?

Three is the minimum that lets you **identify** the disagreeing one. With two you
know something is wrong; with three the largest residual names it. Five would
tolerate one Byzantine liar (`n ≥ 3f+1`) — three tolerates **zero**, which is
threat T1′ and is recorded as such.

### Q16 · Why a median rather than a weighted average?

A mean is pulled by an outlier **without bound**. A median of three ignores one
arbitrary value entirely. Measured: a 1 m bias gives a final deviation of 0.0168 m
— the clean run's figure to four decimals.

### Q17 · Why is there no default for any safety threshold?

A-4. A default is an **unreviewed claim wearing the appearance of a decision**. A
missing threshold is a startup failure, and so is a typo in one
(`extra="forbid"`). The cost is that `certification.toml` ships with every value
commented out and the system will not start without a complete profile.

### Q18 · Why does sensor decay not trigger anything?

Deliberately. A vehicle that stopped for maintenance would be the nuisance stop
ADR-0028 removed, arriving through a different door. Decay is **reported** — per
modality, in every audit row — so a fleet operator can act on it. The vehicle does
not act on it.

---

## 25.4 · Evidence and honesty

### Q19 · Why does the project maintain a list of its own defects?

Because a project with a green suite and no register has the **same** defects and
no list. The trade is understood and stated: it reads as a project with many
problems, and a casual reviewer will misread it. It is the trade the project's
credibility rests on.

### Q20 · Have you ever published a wrong number?

**Yes, several times, and the retractions are on the record.**

The clearest: a 7.35× whiteness improvement, measured correctly from a vehicle
that had **every one of 400 ticks vetoed and a speed of zero**. Caught because two
different proposers gave bit-identical results. Fixed by making the measurement
refuse to run from a stationary vehicle at all.

Also: a `100% inside` figure computed from **one** sample, and a claim that an
artefact was missing that came from an `ls` truncated one line above it.

### Q21 · What did you change so those cannot recur?

Each retraction produced a **guard**, not a note. `StationaryVehicleError`. A
minimum-live-samples floor of 30. `make artifacts-check` that does not merely
check presence but **drives** the artefacts. The pattern is consistent: *refuse to
report from a configuration where the measurement would be meaningless.*

### Q22 · What does `[M-ext]: 0 of 30` mean?

Thirty claims in the credibility matrix, and **none** of them has been measured
against an external reference. It is the single number that most governs how
everything else in the project should be read.

---

## 25.5 · Practical questions

### Q23 · Can I run it?

Yes, on Linux. `make check` runs the quality gate; `make artifacts` regenerates
the twin, corpus and policy. Note that `var/` is gitignored by design, so a fresh
clone has **no** artefacts and every `[M-syn]` measurement runs through all three —
regeneration is required first, and the policy is the long pole.

### Q24 · Why Linux only?

CARLA has **no macOS build**. That constraint is what replaced the original
platform assumption.

### Q25 · How fast is it?

**Unknown.** A-2 *assumes* 10 ms per tick at 20 Hz is achievable in CPython. No
end-to-end latency measurement appears in the evidence pack. The prototype
deliberately favours legibility over speed — no NumPy in the kernel, and in one
place a loop instead of a matrix product because bit-comparability mattered more.

### Q26 · How big is it?

Thirty-four ADRs, ten separation invariants, ten assumptions, thirty claims in the
credibility matrix, twenty-one register rows, and a suite of 3,042 tests plus 3
strict xfails under mypy strict across 166 files at 97.6% coverage with a per-file
floor.

### Q27 · What happens next?

CARLA. In order: commit `partition.json` before any measurement, decide what to do
about `RAIN_NIGHT`, then build the adapter. The point is to get a plant the
project did **not** write — which is the only thing that can move `[M-ext]` off
zero, and the only honest way to close OD-8.

---

## 25.6 · The questions people should ask more often

**[INTERPRETATION]** Three that separate a serious reviewer from a casual one:

1. *"Your veto rate is near zero — is that because the proposals are good, or
   because the gate cannot fire?"* This is exactly OD-8, and it took the project
   nine days to ask it of itself.
2. *"Which of your numbers were measured against something you did not write?"*
   The answer is none, and everything follows from that.
3. *"What would falsify this?"* Every refused mechanism here — FB2, FB3,
   self-calibration — was refused for making a guarantee unfalsifiable.

---

**Next:** `26_INTERVIEW_QUESTIONS/`.
