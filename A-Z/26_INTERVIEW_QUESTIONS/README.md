# 26 · Interview questions

Questions someone will ask about this project — in a technical interview, a design
review, or a due-diligence conversation — with the answer that is *true* rather
than the answer that is flattering.

Grouped by what the question is really testing.

**How to use this section:** do not memorise the answers. Memorised answers fail
at the first follow-up, and every question here has an obvious follow-up. Learn
the *reasoning*; the wording will come.

---

## 26.1 · Tier 1 — "Do you understand your own system?"

### Q1 · Walk me through one tick.

A sensor frame arrives. **L1** computes per-modality `StreamHealth` from
freshness and fuses three position channels by median, with a residual monitor
naming any disagreeing channel. **L2** runs a UKF — draw sigma points, propagate,
add process noise, **redraw**, then update — producing a state and a covariance.
**L3** computes trust. **L4**, the only Core-A component, proposes a command.
**L5**, the twin, predicts what that command would do. **L6** scores the proposal
against a per-context conformal corpus, **L7a** checks deterministic bounds,
**L7b** checks physical limits — three verdicts, merged fail-closed. **L8** takes
the health map *directly from L1* and the verdict history and sets a posture plus
a set of withdrawn capabilities. **L9** arbitrates between proposal, fail-safe and
bounded exploration, and is the only thing that touches an actuator. A
`DecisionRecord` is appended.

**The two details to include, because they are what the question is testing:** the
health map **bypasses L2**, and L9 is the **sole** actuation authority.

### Q2 · Why is the health map delivered directly to L8?

Because everything else in the system is downstream of one estimate. When that
estimate is corrupted, everything computed from it agrees — the gates all read the
same state, so they all read the same lie. The health map is computed from
freshness before the filter touches anything, so it is the **only input that is
not downstream of the common cause**.

Measured on 11 August: it cut a frozen-IMU departure from **4.199 m to 0.167 m**,
and halted at tick +40 against a departure beginning at +73 — 1.65 s of margin.

**Have the re-measurement ready, because it is the better answer.** On 16 August
the same fault gives **0.062 m**, and the escalation stops at **LIMP** — ADR-0030's
health-level ceiling caps a `DEGRADED` stream one posture short of HALT. Two ADRs
moved a headline safety number and neither said so. *That* is the interesting
thing to volunteer, and it is a better demonstration of how the project works than
the original figure was.

**Its limit, and say it before you are asked:** it catches a stream going *quiet*.
A stream publishing fresh, well-formed, **wrong** values stays `HEALTHY`.

### Q3 · Why a UKF and not an EKF?

Two reasons. No Jacobian to derive by hand and re-derive whenever the model
changes — and the EKF's linearisation is a first-order approximation whose error
grows with curvature. And the UKF produces the covariance that **L6 divides by**;
a cheaper estimator without one would delete an entire layer.

**Follow-up you should expect:** *"when would you not use a UKF?"* When the
posterior is genuinely **multi-modal** — two plausible positions rather than one
uncertain one. Every Kalman variant assumes unimodality; a particle filter does
not.

### Q4 · Explain conformal prediction as if I have not met it.

You want to say *"this is unusual"* with a guaranteed error rate, without trusting
your model to be right. So you score a corpus of past examples, take the
`⌈(n+1)(1−ε)⌉`-th score as a threshold, and flag anything beyond it. The guarantee
comes from the ranking, not from the model — which is why it survives a model
being wrong.

**The price is one assumption:** the live samples must be exchangeable with the
corpus. Here they are not, and that is OD-8.

### Q5 · Why *Mondrian* conformal prediction?

Because a single global corpus would pool highway and urban driving, and call a
proposal that is normal for neither *mildly unusual for the mixture* — flagging
nothing. A separate corpus per context is what makes "unusual" mean "unusual
**here**".

---

## 26.2 · Tier 2 — "Do you understand why it is built this way?"

### Q6 · You have a trust boundary. What stops someone crossing it?

The compiler. `CommandProposer.propose` receives state and trust; the write side
of the channel, `ProposalWriter`, **exposes no read method**. There is no call to
make, so the violating code cannot be written.

**Why that matters more than a rule:** anything an optimiser can observe, it can
learn to exploit, and a convention holds until someone is in a hurry.

**Its limit:** it protects against *code* that reads a verdict. It does not
protect against a compromised process — threat T4 — and there is no process
boundary here at all. Everything runs in one process on one machine.

### Q7 · Your covariance goes non-positive-definite. What happens?

Cholesky raises, the exception is **deliberately uncaught**, it converts to a
`SafetyPathError`, and that is a VETO.

**Why not repair it?** Because repair destroys the evidence that something broke,
in a system whose output is an evidence log. A filter that quietly restored its
own covariance would return a state estimate nobody could justify and the layer
above would have no way to know.

### Q8 · No gate reports. What is the verdict?

**VETO.** `Verdict.merge` is a fail-closed fold and an empty set merges to VETO.
If nothing reported, something upstream failed — treating that as approval would
make a crashed gate indistinguishable from an approving one.

### Q9 · Why not just halt when you are outside the certified envelope?

Because halting is itself a hazard — a stopped vehicle in traffic is not a safe
state — and because a defence that fires too readily gets **disabled by
operators**, at which point it protects nothing. So the vehicle explores under a
narrowed envelope: half the nearest certified speed, ±15° steering, no lane
changes.

**Pre-empt the obvious objection:** the veto authority is untouched. ADR-0023
froze the OOD *counter*, not the gates. Every gate still vetoes and every veto
still stops the command.

### Q10 · Why is capability withdrawal a separate axis instead of another posture?

Because *lose the camera, stop offering lane changes, keep driving* is not a point
on a severity ladder. Before ADR-0029 a camera failure either stopped the vehicle
or did nothing at all. Two axes compose by intersection; one ladder cannot express
it.

### Q11 · You added redundancy. Did that make the system safer?

**Mostly, and in one specific way less safe — say both halves.**

Safer: a 1 m bias in one channel never reaches the estimator (0.8387 m → 0.0168 m,
indistinguishable from clean), and the residual **names** the liar because
`reading − median` cancels the truth term exactly.

Less safe: threat T1′. With `n = 3`, `n ≥ 3f+1` gives `f = 0`, so **two coordinated
liars invert the monitor** — the median becomes the lie and the monitor flags the
**honest** channel by name. Every other entry in the threat model degrades toward
silence; this one degrades toward a false positive that looks like a successful
detection.

And silencing one channel is now a two-second denial of service that did not exist
before.

---

## 26.3 · Tier 3 — "Are you honest about it?"

**These are the questions that decide the conversation.** An interviewer who asks
them is testing judgement, not knowledge, and the flattering answer loses.

### Q12 · What is your veto rate?

Near zero on the statistical gate — **and that is a defect, not a result**. The
live scores sit below the corpus quantile because the two are not exchangeable
(OD-8, zero overlap between 999 live and 1,000 calibration samples). A low veto
rate reads as *"the proposals are good"*; here it means the gate cannot fire.

### Q13 · How do you know the system works?

I do not, in the sense you mean. What I know splits three ways: some properties
are **structural** and hold on any plant — the trust boundary, the fail-closed
merge, the refusal-not-repair rule. Some are **measured on a plant this project
wrote**, which is weaker than it sounds because the plant, the process model, the
twin and the corpus are the same bicycle model. And external accuracy is
**unmeasured**: `[M-ext]: 0 of 30`.

### Q14 · What is the weakest part of the design?

**All three gates read one estimate.** L2 exists so that nothing above it handles
raw readings, which is a good property — and it makes L2 a common cause. Measured
in OD-9: a frozen IMU took the vehicle 4.199 m off a 1.75 m lane with every gate
passing and a verdict trace **identical to a clean run's**.

Partly mitigated by the health map and by redundancy. Not removed.

### Q15 · Tell me about something you got wrong.

I published a 7.35× improvement in residual whiteness. The measurement was
correct; the vehicle it was measured on had **every one of 400 ticks vetoed and a
speed of zero**, because I had invented a default artefact path that did not
exist and the run silently fell back to a placeholder proposer.

I caught it because two structurally different proposers produced **bit-identical**
numbers, which is not something that happens.

The fix was not a note. It was `StationaryVehicleError` — the benchmark now
**refuses to report** from a stationary vehicle. That is the pattern for all three
retractions that week: the guard, not the correction.

### Q16 · What would change your mind about the architecture?

CARLA giving a false-positive rate that makes the system unusable — vetoes on
normal driving, from a twin that cannot model suspension and tyre slip and whose
errors present as proposer anomalies because the twin carries **no uncertainty**.
That is prediction P2 in the CARLA plan, written down before the measurement
specifically so it cannot be rationalised after.

### Q17 · Why should I believe your numbers?

You should not, on my word. Each one is a row in `EVIDENCE.md` with the command
that reproduces it, and a number lives in exactly one place so it cannot go stale
in a second document. The claims are marked with what kind of evidence backs them
and **what they do not license**. And several are marked withdrawn, with the reason.

**The correct level of belief:** the `[M-syn]` numbers are real measurements of a
real system, in an environment I wrote. That is worth something and it is not
worth external validation.

---

## 26.4 · Tier 4 — "Would you be useful to us?"

### Q18 · What is the most transferable thing here?

**[INTERPRETATION]** Not the architecture — the **shadow harness**. Run a
mechanism with no authority, measure it against the live one, and let the
measurement decide. *"No mechanism gets authority until it has run with none."*

It converted *"we think online self-calibration would be bad"* into *"here is the
measurement"* — FB3's veto rate converges to ε regardless of whether anything is
wrong. Two feedback loops were refused that way before either could affect a run,
and five drift detectors were refuted the same way.

### Q19 · What would you do differently?

Two things.

Build **one external environment early**, even a bad one. Every structural weakness
in this project traces to the judge and the judged sharing an origin, and nine
months of internal measurement did not surface OD-8 — a five-minute distribution
comparison did.

And measure **latency** from day one. A-2 has been an assumption for the whole
project, and a timing budget you never measure is a claim you will discover is
false at the worst moment.

### Q20 · This is a prototype. Why is it interesting to a company?

Three things a company can use before anything is validated.

- **Mechanisms that stop documents drifting from code** — an invariant's
  *enforcement kind* asserted by a test, a schema version pinned by a test that has
  fired seven times, a per-file coverage floor that exists because a module shipped
  at 10.3% behind a green aggregate gate.
- **A degradation table that is a measurement, not a document** — it drives the
  real fail-safe machine once per modality and prints what happened, so a safety
  case and the running system cannot drift apart. It also flags an **inert**
  modality, which is the *"we added a sensor and forgot to wire its failure
  response"* bug made visible.
- **Predictive maintenance for free** — sensor decay is computed from the same
  health map that protects the vehicle, so a fleet gets *"this camera missed 23% of
  its frames"* at zero extra sensor cost, and a schema-10 archive can be mined for
  wear retrospectively.

### Q21 · What is it *not* an alternative to?

**Lockstep redundancy.** They are orthogonal: lockstep catches *structural*
failure — a bit flip, a stuck core — and catches semantic failure not at all.
ASTRA catches semantic failure and structural failure not at all. A vehicle needs
both, and lockstep is shipping in production vehicles today while this is a
prototype with zero external validation.

---

## 26.5 · The three questions to prepare hardest

**[INTERPRETATION]**

1. **Q12 — "what is your veto rate?"** Because the honest answer is a confession,
   and the temptation to give the flattering one is strongest exactly here.
2. **Q14 — "what is the weakest part?"** Because a candidate who names a real
   structural weakness and its measurement is immediately more credible than one
   who names a small one.
3. **Q15 — "what did you get wrong?"** Because the *fix* is the answer. Anyone can
   confess an error; the signal is whether it produced a guard.

**The failure mode to avoid**

> Over-claiming. Every number here is defensible **if** it is stated with its
> scope. The same number stated without its scope is a claim that will not survive
> the first follow-up, and losing credibility on one number costs you the other
> twenty-nine.

---

**Next:** `27_RESEARCH_QUESTIONS/`.
