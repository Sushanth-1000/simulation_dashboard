# 1 · The real-world problem

---

## 1.1 · Start with the thing in the world

A car drives itself. Somewhere inside it, a piece of software decides —
twenty times a second — how much to steer, how much to accelerate, how hard to
brake. That software is increasingly a **neural network**: a function whose
behaviour was *learned from examples* rather than written down by an engineer.

You do not need to know how neural networks work to follow this. You need one
property:

> **Nobody wrote the rules. The rules were fitted to data, and nobody can read
> them back out.**

An engineer wrote the *training procedure*. The behaviour that came out is a few
million numbers. There is no line of code saying *"if a pedestrian steps out,
brake"*. There is a function that, on the examples it was shown, happened to
brake.

---

## 1.2 · Two completely different ways this can fail

This distinction is the entire foundation. Everything else in the project is
downstream of it.

### Failure type 1 — the computer breaks

A cosmic ray flips a bit in memory. A capacitor fails. A pointer runs off the end
of an array. A processor overheats and miscalculates.

The computation **did not execute correctly**.

Engineering has spent fifty years on this and is genuinely good at it. Run the
computation on two processors and compare the answers. Add error-correcting
memory. Add watchdog timers. Certify the process. This is what standards like
**ISO 26262** — the automotive functional-safety standard — are largely about.

### Failure type 2 — the computer works perfectly and is wrong

Every transistor behaves. No bit flips. The memory is intact. The code executes
exactly as written, the network runs exactly as trained, and the answer it
produces is **a bad idea**.

The computation **executed perfectly and produced a wrong answer**.

The project's own words for this **[FACT** — `docs/ARCHITECTURE.md` §1**]**:

> An AI controller in a safety-critical system can be **structurally healthy** —
> no bit flips, no crashes, correct by every classical definition — and still
> issue a **semantically wrong** command to a physical actuator, because the
> world it faces at runtime no longer matches the world it was trained in.

**ASTRA is about failure type 2 only.** It does not help with type 1, and does
not claim to. Type 1 already has an industry.

---

## 1.3 · Why "the world no longer matches" is the crux

A learned controller is, at bottom, an **interpolator**. It saw examples; it
learned a function that fits them; it works well *inside the region those
examples covered*.

Ask it about a situation outside that region and it does not know it is outside.
It has no representation of *"I have not seen this"*. It produces an output with
exactly the same confidence and exactly the same mechanism as always, because
producing an output is all it does.

This is called **distribution shift**, or being **out-of-distribution** (OOD).

> **Definition — out-of-distribution.** The inputs at runtime are drawn from a
> different statistical population than the inputs used in training. The model
> continues to produce outputs; those outputs are extrapolation, and extrapolation
> from a fitted function carries no guarantee whatsoever.

Concretely, a controller trained on daylight highway driving in California and
deployed into fog in Yorkshire is being asked to extrapolate. It will. It will
not say so.

**The dangerous property is not that it is wrong. It is that it is *confidently*
wrong, and cannot report the difference.**

---

## 1.4 · A worked example — the one this project actually measured

This is not hypothetical. It is `OD-9`, measured on 9 August 2026 **[FACT** —
`E-46`, `E-48`**]**.

**Setup.** A simulated vehicle drives down a lane 1.75 m wide on either side of
centre. An IMU — the sensor reporting where the vehicle is laterally — is made to
**freeze**: it keeps reporting, at full rate, perfectly well-formed values. It
simply reports the *same* value, over and over. Nothing is broken. Nothing is
noisy. The reading is just no longer true.

**What the system did.**

1. The state estimator fused the frozen reading and concluded the vehicle was at
   the position the IMU claimed.
2. The AI proposer read that estimate, saw a vehicle nicely centred, and proposed
   commands consistent with staying there.
3. The safety gates read **the same estimate**, saw the same nicely-centred
   vehicle, and agreed the commands were fine.
4. The vehicle drifted out of its lane.

**The numbers.** The vehicle ended **4.199 m** off the centre of a lane whose
half-width is 1.75 m — comfortably outside — while the safety gate responsible
for the lane corridor reported a deviation of **0.023 m**. The full sequence of
verdicts was **identical to a clean run's**.

**Nothing objected. Nothing was broken. Everything reported success.**

### Why this example is worth memorising

It has a property that makes it far worse than "a sensor failed":

> **The proposer closes its control loop on the same corrupted estimate the gates
> use to judge it.**

So the fault is not merely undetected — it is **actively driven**. The proposer
sees an error between where it thinks it is and where it wants to be, and issues
commands to correct it. Those commands move the *real* vehicle away from the
lane, because the estimate is wrong. And the gates, reading the same estimate,
see the error shrinking and approve.

**The system converges confidently on the wrong answer.** Each component behaves
correctly given its inputs. The failure is in the *structure*: a shared input
that everybody trusted.

That single measurement is the source of more of the current design than any
other. It appears again in nearly every later section.

---

## 1.5 · Why you cannot just veto your way out

The obvious response: *"add a check that catches it"*.

The project tried, and the conclusion is stated as **[FACT** — the module
docstring of `src/astra/layers/l8_failsafe/machine.py`**]**:

> **You cannot veto your way out of a lying sensor.**

Here is why. Suppose a gate *had* objected. What happens on a veto? The
proposal is refused and a **fallback controller** issues a safe command instead.

But the fallback controller reads **the same corrupted estimate**. So refusing
the proposal substitutes one command computed from a lie for another command
computed from the same lie. The veto changes which wrong number reaches the
actuator. It does not make the number right.

**The information required to detect the fault was never in the signal any gate
could see.** No rearrangement of downstream components creates information that
was not upstream. The fix had to come from somewhere the corruption had not
reached — sensor **freshness**, computed at the boundary before the filter
touches anything.

This is the shape of the hardest problems in the project: not *"we did not check
carefully enough"* but *"the check was structurally incapable of seeing it"*.

---

## 1.6 · Why this matters commercially, not just intellectually

A manufacturer cannot ship a system they cannot argue about.

Functional-safety certification asks: *what are the hazards, what mechanisms
address each, and what evidence supports the mechanism?* For classical software
this is laborious but tractable. For a learned controller, the honest answer to
*"why did it do that?"* is **"a few million numbers"** — which is not an argument
anyone can assess.

Two responses exist. The industry mostly takes the first:

1. **Make the network itself provably safe.** An open research problem. Formal
   verification of large networks does not scale, and "provably safe" requires a
   specification of *safe* that nobody has written for driving.
2. **Do not try.** Treat the network as untrusted, and make the *thing between it
   and the actuators* the object of the safety argument.

**ASTRA takes the second** and says so plainly **[FACT** — `ARCHITECTURE.md`
§1**]**:

> ASTRA does not attempt to make the learned controller provably safe; that is an
> open problem.

The bet is that a small, inspectable, conventionally-engineered governor is
something you *can* build a safety case for — even when the thing it governs is
not.

---

## 1.7 · You should know this before moving on

**Concepts you must have**

| Concept | The short version |
|---|---|
| **Structural vs semantic failure** | The computer breaking vs the computer working perfectly and being wrong |
| **Distribution shift / OOD** | Runtime inputs from a different population than training inputs |
| **Confident extrapolation** | A model outputs with unchanged confidence outside its training region, and cannot report that it is outside |
| **Common-cause failure** | Independent-looking components sharing one input, so one fault disables all of them at once |
| **Untrusted proposer** | Treat the AI's output as a *suggestion* to be judged, never as a command |

**Terminology**

- **IMU** — inertial measurement unit; reports acceleration and rotation
- **Actuator** — the thing that physically acts: throttle, brake, steering
- **ISO 26262** — the automotive functional-safety standard
- **Veto** — an unconditional refusal of a proposed command
- **Fallback controller** — the simple, non-learned controller used when a
  proposal is refused

**Questions you should be able to answer**

1. What is the difference between a structural and a semantic failure, and which
   does ASTRA address?
2. In the OD-9 example, what exactly was broken? *(Careful: nothing was broken.)*
3. Why did adding a veto not fix OD-9?
4. What does "the proposer closes its loop on the same estimate the gates read"
   mean, and why is it dangerous?
5. Why does a manufacturer care about explainability at all?

**Misconceptions to avoid**

> *"The AI made a mistake."*
> It did not, in any useful sense. It produced the correct output for the input
> it was given. The input was wrong and nothing told it so.

> *"More redundancy would fix it."*
> Redundancy fixes *independent* failures. OD-9 is a **common-cause** failure —
> three redundant gates reading one estimate fail together. Adding a fourth
> reader of the same estimate adds nothing. This is measured, not argued.

---

**Next:** [`2_Why_It_Is_Hard.md`](2_Why_It_Is_Hard.md)
