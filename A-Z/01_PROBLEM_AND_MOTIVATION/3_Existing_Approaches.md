# 3 · Existing approaches, and exactly where each stops

Nobody arrived at this problem first. The question is not *"has anyone tried to
make AI systems safe?"* — obviously — but **"which existing mechanism catches a
computation that executes perfectly and produces a wrong answer?"**

---

## 3.1 · The three the project explicitly names

`docs/ARCHITECTURE.md` §1 names three and says why each misses **[FACT]**:

### Lockstep processors

**What it is.** Run the identical computation on two (or three) processor cores
in cycle-by-cycle synchrony. Compare the outputs every cycle. Any divergence
means a hardware fault, and the system fails safe.

**What it catches.** Transient hardware faults — cosmic-ray bit flips, a failing
transistor, a marginal clock. Extremely effective, genuinely essential, and used
in essentially every automotive safety controller.

**Where it stops, in the project's own words:**

> Lockstep processors replicate the same wrong answer on both cores.

If the *input* is wrong, or the *model* is extrapolating, both cores compute the
same wrong output and agree perfectly. Lockstep verifies **execution fidelity**.
It has no opinion on whether the thing being executed was a good idea. Against a
semantic failure it is not weak — it is *silent by construction*.

### Hypervisors

**What it is.** A thin layer beneath the operating systems that partitions a
processor so that several software domains of different criticality share
hardware without interfering. A crash in the infotainment domain cannot corrupt
the braking domain.

**What it catches.** Interference. Freedom from interference is a real ISO 26262
requirement and hypervisors deliver it.

**Where it stops:**

> Hypervisors isolate execution domains without inspecting what crosses them.

A hypervisor polices *who may run and what memory they may touch*. When the
autonomy domain sends a steering command through a legitimate channel, that is
exactly what the partitioning permits. The hypervisor's job is to let it through
correctly. It never asks whether the value is sensible.

### Hardware security modules

**What it is.** A tamper-resistant component holding cryptographic keys, used to
sign and verify messages so a receiver knows a command genuinely came from the
authorised sender and was not altered.

**What it catches.** Spoofing, tampering, replay — a real and growing automotive
attack surface.

**Where it stops:**

> Hardware security modules authenticate a command's origin, not whether it was a
> good idea.

A correctly signed command from a genuinely authorised controller that is
extrapolating badly is **valid**. The signature is over the bytes, not the
wisdom. The HSM will faithfully authenticate a command that drives into a wall.

### The pattern

All three answer **"did the computation execute correctly, from the right party,
without interference?"** Every one can answer *yes* while the vehicle leaves the
road, and that is the gap ASTRA aims at.

---

## 3.2 · Approaches from the research literature

**[INTERPRETATION]** — the framing below is this folder's, offered as context.
The project's own comparison is in `docs/PAPER_ADHERENCE.md`, which is narrower
and concerns whether the paper describes the code accurately.

### Formal verification of the network

**Idea.** Prove mathematically that the network satisfies a property for all
inputs in a region.

**Why it does not close this.** It scales poorly against production-sized
networks, and — more fundamentally — it requires a **formal specification of
"safe"**. For image classification you can state *"a small perturbation must not
change the label"*. For driving, nobody has written down what safe means in a
form a prover can consume. You can verify a property you can state.

**Its relationship to ASTRA:** complementary, not competing. ASTRA's position is
explicit **[FACT** — `ARCHITECTURE.md` §1**]**: *"ASTRA does not attempt to make
the learned controller provably safe; that is an open problem."*

### Runtime verification / safety shields

**Idea.** Wrap the controller in a monitor that checks each action against a
hand-written safety specification and substitutes a safe action when violated.

**Why it is close but insufficient alone.** This is genuinely the same family as
ASTRA's L7a. Two limits:

- It is only as good as its specification, and it checks *hard physical bounds*,
  which are the easy half.
- **It reads the state estimate.** If that estimate is corrupted, the shield
  computes its bound from a lie. Measured here: under a frozen IMU, the corridor
  bound read **0.023 m** while the true deviation was **4.199 m** **[FACT** —
  `E-46`**]**.

**What ASTRA adds:** the shield is *one* of three gates, and the fail-safe
machine takes an input that does not pass through the estimator at all.

### Uncertainty quantification

**Idea.** Have the model report calibrated uncertainty — Bayesian networks,
ensembles, Monte-Carlo dropout, conformal prediction — and act cautiously when it
is high.

**Where it stops.** Two things.

- Most methods report uncertainty *the model computes about itself*, which
  returns to §2.2: the model is the wrong witness.
- **Conformal prediction** is the interesting exception: it gives a
  distribution-free guarantee that does not depend on the model being
  well-specified. ASTRA uses it (L3, L6).
- But conformal buys that guarantee with **exactly one assumption —
  exchangeability** — and this project has measured that assumption **violated,
  in-house, on synthetic data**: zero overlap between live and calibration
  scores (`OD-8`, `E-159`). The guarantee is not wrong; the precondition is not met.

**[OPEN]** whether exchangeability can be maintained in a closed loop at all is
not settled by this project, and is arguably a research question rather than an
engineering one.

### Simplex / fallback architectures

**Idea.** A high-performance untrusted controller and a simple verified one, with
a decision module switching between them.

**Why this is the closest ancestor.** ASTRA is recognisably in this family, and
the untrusted/trusted split is the same idea.

**What ASTRA adds** **[INTERPRETATION]**:

- **Three gates with different failure modes**, not one switching rule
- A **digital twin** predicting what the command will do, so the check is on the
  *consequence* rather than the command
- A **graduated posture** (NOMINAL → DEGRADED → LIMP → HALT) rather than a
  binary switch, because binary switching is the over-firing failure of §2.6
- **Bounded safe exploration** — the vehicle keeps driving outside its certified
  envelope under a narrowed envelope, instead of halting
- **Ten mechanically-enforced separation invariants** making the "untrusted"
  claim structural rather than intentional

---

## 3.3 · The honest comparison

**[INTERPRETATION].** ASTRA is not a new idea in the sense of a new mechanism.
Every ingredient exists: shields, conformal prediction, digital twins, simplex
architectures, fail-safe state machines.

The claims worth making are about **composition and discipline**:

1. The ingredients are assembled so their **failure modes differ**, and the
   project measures whether that holds rather than asserting it — and has
   published that it currently does *not* hold as strongly as claimed (`OD-9`,
   `E-162`).
2. The separation properties are **mechanically enforced** — a violation of SI-5
   or SI-7 does not compile or does not construct. Not review, not convention.
3. The evidence discipline is unusual: every number reproducible from one
   command, every claim carrying what it does *not* license, and retractions
   published rather than quietly fixed.

**What is not claimed:** that this is the only such architecture, that it
eliminates the failure mode, or that any of it has been shown to work outside a
simulator this project wrote.

---

## 3.4 · You should know this before moving on

**The core distinction**

| Mechanism | Question it answers | Silent on |
|---|---|---|
| Lockstep | Did the computation execute correctly? | Whether the answer was sensible |
| Hypervisor | Is this domain allowed to run and touch this memory? | The content of what it sends |
| HSM | Did this really come from the authorised sender? | Whether the sender was right |
| Formal verification | Does this property hold for all inputs in a region? | Properties nobody can formalise |
| Runtime shield | Does this action violate a stated bound? | Bounds computed from a corrupted estimate |
| Uncertainty quantification | How confident should we be? | Cases where the model is its own witness — or exchangeability fails |

**Questions you should be able to answer**

1. Why do two lockstepped cores not catch a semantically wrong command?
2. What exactly does an HSM's signature cover, and what does it not?
3. Why is formal verification of the controller not a substitute here?
4. What does conformal prediction buy, and what single assumption does it buy it
   with? Is that assumption currently satisfied here?
5. Name three things ASTRA adds over a classical simplex architecture.

**Misconception to avoid**

> *"This is a replacement for existing safety mechanisms."*
>
> It is not, and treating it as one would be dangerous. Lockstep, hypervisors and
> HSMs address failure modes ASTRA does nothing about. ASTRA is an **additional**
> layer for a failure mode they do not cover. A vehicle needs both.

---

**Next:** [`4_Original_Goals_And_Constraints.md`](4_Original_Goals_And_Constraints.md)
