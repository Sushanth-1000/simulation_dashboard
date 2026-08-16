# ASTRA — Demonstration Plan

**Prepared** 10 August 2026 · **rewritten against a re-verified system**
16 August 2026
**For** a technical audience at a company: engineers, a safety lead, possibly a
research manager. Not a sales meeting.
**Runs on** one laptop, no GPU, no network.
**Length** 16 minutes of driving, 30–40 with questions.

> **Every number in this document was re-measured on 16 August 2026** by running
> the benchmark, not by reading the row it came from. The command for each is in
> [`A-Z/00_START_HERE/REPRODUCE.md`](../A-Z/00_START_HERE/REPRODUCE.md). Six
> figures in the previous version of this plan had been superseded by two ADRs
> and were still being quoted — see §*What changed*.

---

## The one decision that shapes everything below

**Do not open by showing the gates catching a fault. Open by showing what the
governance does that a gate cannot.**

That sentence is the whole strategy, and it survived a full re-verification. Every
instinct says to lead with "watch it catch this", and every instinct is wrong
here, for three reasons:

1. **On the current evidence, the gates are not the strong part.** Two of three
   never object at all across 2,800 ticks of a suite built to break them
   (`E-162`, re-measured today). On one fault the governance measurably *costs*
   you. A demo implying three vigilant gates falls apart at the first informed
   question.
2. **The room contains someone who will test it.** Safety engineers do not watch
   demos, they probe them. The first question after any "watch it catch this" is
   *"what does it miss?"* — and you want the answer to be a document, not a pause.
3. **The honest version is the stronger pitch, and it is now backed by a stronger
   result.** Since the last version of this plan, redundancy landed on the driven
   path and produced the best measurement in the project: **a 1 m sensor lie that
   never reaches the estimator at all.** That is a governance win a gate could
   never deliver, and it is the new opening.

So the argument is: **the governance does things gates cannot, it degrades in
steps instead of stopping, it writes down why — and we can find our own defects.**
The architecture is the subject; the *method* is the product.

---

## The arc, in one table

Each scene earns the next. Do not reorder.

| # | Scene | Time | What it proves | The line that lands |
|:--:|---|:--:|---|---|
| 0 | The nominal drive | 1 min | It runs, and every number is traceable | *"Everything on this screen came out of an audit record. Nothing is drawn."* |
| **1** | **The lie that never arrives** | **3 min** | **A corrupted sensor is outvoted before the estimator sees it** | *"The biased car and the healthy car are the same car, to four decimal places."* |
| 2 | **The tunnel** | 3 min | An unrecognised context narrows the envelope instead of stopping | *"Most runtime assurance halts here. This keeps moving, inside a bound it can defend."* |
| 3 | **The dark sensor** | 4 min | The gates are blind to it — **and something outside them catches it anyway** | *"Every gate is green and will stay green. And yet the vehicle is stopping."* |
| 4 | **Lose a camera, keep driving** | 2 min | Capability withdrawal: a second axis, not a fifth posture | *"It has stopped offering lane changes. It has not stopped driving."* |
| 5 | **The ablation, and where we lose** | 2 min | One gate does the work — and on one fault it is the cost | *"We measured what each gate is worth. On one fault, ours is worth less than nothing."* |
| 6 | The register | 1 min | 21 defects, all self-found, plus a guard that went stale | *"Every one of these was found by us, by instruments we built for the purpose."* |

---

## Scene 0 — The nominal drive

**Do:** start the dashboard. Let it run for thirty seconds without touching it.

```bash
uv run python -m demo.dashboard
```

**Say:**

> Nine layers, twenty ticks a second. The lane deviation you are watching sits
> around three centimetres and stays there — we have run this for a hundred
> thousand ticks and it does not drift, the memory does not grow, and the
> fail-safe never leaves NOMINAL.
>
> Everything on this screen came out of an audit record. Nothing here is drawn.

**Have ready if asked:** `python -m benchmarks.soak -n 100000`, ten pass criteria,
deviation 0.0285 → 0.0287 m across halves, resident set **+0.1 MiB**, per-tick p99
8.599 → 7.757 ms, `PROPOSED` on **99,958** of 100,000 ticks.

**Do not oversell this scene.** It is the baseline every later claim is a
difference from, and it takes one minute.

---

## Scene 1 — The lie that never arrives

**This is the new opening and it is the strongest thing in the deck.** It is a
table, not an animation. Put it on screen.

```bash
uv run python -m benchmarks.arms
```

| arm | peak estimator error | final \|deviation\| |
|---|--:|--:|
| single channel / clean | 0.1993 m | 0.1034 m |
| single channel / **1 m bias** | **1.1805 m** | **0.8387 m** |
| redundant / clean | 0.1323 m | **0.0168 m** |
| redundant / **1 m bias** | 0.1323 m | **0.0168 m** |

**Say:**

> One position sensor is lying by a full metre — two thirds of a lane width —
> from tick two hundred onward. Read the bottom two rows.
>
> They are the same. Not similar; the same, to four decimal places. Under three
> channels fused by median, the car being lied to and the car being told the
> truth are **indistinguishable**.

**Then the mechanism, because a number without a mechanism is a demo:**

> A mean would have been dragged by that outlier without bound. A median of three
> ignores it entirely — it does not average the lie in, it **outvotes** it.
>
> And it names the liar. With three channels the largest residual identifies
> *which one* disagreed, and the subtraction cancels the truth term exactly — we
> verified that to five times ten to the minus seventeen — so the statistic
> measures sensor disagreement and nothing else. An earlier candidate measured a
> *quantity* instead, so a hard cornering manoeuvre moved it and it reported the
> manoeuvre as a fault.

**Then the limit, unprompted — this is the pattern for the whole demo:**

> Two honest constraints on that.
>
> **One liar, not two.** For Byzantine faults you need `n ≥ 3f+1`. We have three
> channels, so we tolerate **zero** coordinated liars — and it does not merely
> fail there, it **inverts**: two channels agreeing on a lie make the lie the
> median, and the monitor then accuses the honest channel by name, in the
> evidence log. It is in our threat model as T1-prime. Every other entry in that
> model degrades toward silence; this one degrades toward a confident wrong
> accusation.
>
> **And the bound assumes independent compromise.** A shared supplier, a shared
> bus, a shared firmware image — or simply the same fog — breaks the assumption
> before it breaks the arithmetic.

**Why this scene goes first now.** Until 15 August this was the thing we told
audiences we *could not* measure, because the reference plant published one
ground truth to every modality and was structurally incapable of disagreeing with
itself. Fixing that took an ADR and produced the project's best number. **Say
that** — it is a story about method, and method is what you are selling.

---

## Scene 2 — The tunnel

**Do:** press **Tunnel**. Visibility drops to 0.05, complexity to 0.95 — outside
every certified centroid.

**What appears:** context goes `UNCLASSIFIED`, arbitration flips to
`SAFE_EXPLORATION`, the envelope narrows, **and the vehicle keeps driving.**

**Say:**

> No certified profile matches this. Most runtime assurance architectures stop
> here — that is the safe default and it is what a simplex architecture does.
>
> This one narrows the envelope instead: half the nearest certified speed, a
> fifteen-degree steering cone, no lane changes. It is still driving, inside a
> bound it can state.

**Then the objection, before they raise it:**

> The obvious objection is that we have just described *operating outside
> certification*, and that is exactly right — so the question is which hazard you
> prefer. A stopped vehicle in live traffic is not a safe state. And a defence
> that fires too readily gets switched off by operators, at which point it
> protects nothing.
>
> What we did **not** do is weaken the veto. ADR-0023 froze the out-of-distribution
> *counter* during exploration, not the gates. Every gate still vetoes, and every
> veto still stops the command reaching an actuator. SI-3 is exactly as it was.

**The scar behind that ADR — tell it, it is short and it lands:**

> We learned that by changing the car. On a platform the twin was never fitted
> to, the vehicle correctly declared exploration — and the OOD counter climbed
> underneath it and **halted the vehicle anyway**, on two platforms out of five,
> at ticks 398 and 404. One event escalated twice, defeating the architecture's
> distinguishing behaviour using its own fail-safe machine.
>
> Re-run this morning: **no platform halts, every one is still moving.**

```bash
uv run python -m benchmarks.platform_transfer
```

**One row on that table deserves your honesty.** `sharp_steer` finishes **53.756 m**
off the lane at LIMP, still driving, and the benchmark counts it as a pass because
its rule tests posture, motion and speed cap — **not lane position**. If they read
the table, get there first: *"that row is either a missing exit criterion or a
platform this vehicle should refuse, and we have not decided which."*

---

## Scene 3 — The dark sensor

**Do:** press **IMU dropout**. Then stop talking for five seconds and let them
watch.

**What appears:**

- The blue estimate line stays flat near the centre; the red truth line separates.
- **The gate panel stays green.** All three. It never moves.
- **The fail-safe panel escalates anyway** — DEGRADED, then LIMP — driven by a
  counter no gate feeds. The vehicle slows and comes to rest.

**Say, while the lines separate and before the posture moves:**

> Watch the two lines, and watch the gate panel while you do, because it is going
> to stay green for the whole of this. The verdict trace for these ticks is
> indistinguishable from the clean run you just watched.

**Then, as the posture moves:**

> And yet the vehicle is stopping. Nothing refused a command. Something else
> noticed.

**Then the mechanism — the impressive part:**

> This is not a missing check. The corridor bound exists; we added it
> specifically to catch a lane departure. It reads the position estimate — and
> the controller closes its loop on the same estimate, so the controller is
> *actively driving the corrupted number toward the value the monitor considers
> safe*. A sensor fault blinds the monitor and the thing it monitors at the same
> time, through the same channel.
>
> We call it OD-9. We found it on the first fault we ever injected, about an hour
> after the injector worked.

**Then the sentence the fix turned on. Slow down — it is the best line in the
deck, and it is a negative result:**

> The obvious fix is a fourth gate that vetoes on sensor health. It does not
> work, and finding out why is the useful part.
>
> When a gate vetoes, the arbitrator falls back to its own controller — and that
> controller reads **the same corrupted estimate**. A veto exchanges one command
> computed from a lie for another command computed from the same lie.
>
> **You cannot veto your way out of a lying sensor.**
>
> What the vehicle needs is not a refusal. It is a change of *posture*, driven by
> something that is not downstream of the filter. There is exactly one such
> signal: the sensor bus reports, at the boundary, before the filter touches
> anything, that a channel has gone quiet. It was being computed every tick and
> read by nothing.

**The numbers. Use two, not all of them.**

| | when we found it (9 Aug) | today |
|---|--:|--:|
| final \|deviation\| under a 200-tick dropout | **4.199 m** | **0.062 m** |
| ticks outside the ±1.75 m corridor | 73 | **0** |
| escalation | none — NOMINAL for all 400 ticks | **DEGRADED +5, LIMP +15** |
| final speed | 12 m/s, still departing | **0.0000 m/s — stopped, in its lane** |
| false alarms on the clean run | — | **zero** |

**Two honest notes on that table, and give them unprompted.**

> The deviation improved twice, and only the first was this mechanism. The health
> counter took it from 4.199 to 0.167 metres in August; **redundancy took it the
> rest of the way**, because three channels outvote one frozen one. Credit where
> it is due.
>
> And it no longer reaches HALT. A `DEGRADED` stream is capped at LIMP by a
> health-level ceiling we added afterwards — the counter still reaches its HALT
> threshold and the ceiling refuses the escalation. The effect is the same here,
> the vehicle stops, but the *deepest response* to a dark sensor is one posture
> shallower than it was, and **nothing in the ADR or the audit schema recorded
> that it had changed.** We found that this morning, re-running our own numbers.

**Then the limit that is still open:**

> This catches a channel that goes **quiet**. It does not catch a channel that
> lies *fluently* — a constant offset, a slow drift, a value frozen at its last
> good reading. Redundancy now handles the offset. The **slow drift** does not,
> and we have five refuted detectors to prove it: the innovation sequence, the
> innovation gate flag, analytical redundancy, cross-channel consistency, and a
> CUSUM on the residual. All silent.
>
> The reason is structural, and it is the most useful sentence we have produced:
> **no rearrangement of downstream quantities creates information that was never
> upstream.** Every quantity on the record comes from the same measurement.

---

## Scene 4 — Lose a camera, keep driving

**Do:** put the degradation table on screen.

```bash
uv run python -m benchmarks.degradation
```

| sensor | critical | posture | φ | withdrawn |
|---|:--:|---|--:|---|
| CAMERA | yes | HALT | 40 | `lane_change`, `lane_keeping` |
| LIDAR | yes | HALT | 40 | `obstacle_avoidance` |
| IMU | yes | HALT | 40 | `adaptive_cruise` |
| GPS | yes | HALT | 40 | `route_following` |
| RADAR | yes | HALT | 40 | `adaptive_cruise`, `lane_change`, `obstacle_avoidance` |

**Say:**

> This is the degradation concept every functional-safety argument needs: per
> sensor, what its loss withdraws and where the posture lands.
>
> In most projects that is a document maintained by hand beside a state machine
> maintained separately — which is to say, a document that is wrong. **This one
> is a measurement.** It drives the real fail-safe machine once per modality with
> that sensor dark, and prints what happened. The table and the running system
> cannot disagree, because the table *is* the system.

**Then the design point, which is what a safety lead will actually take away:**

> Withdrawal is a **second axis**, not a fifth posture. Posture answers *how bad
> is it*; withdrawal answers *what can I no longer do*. They compose by
> intersection.
>
> That is what lets the vehicle say *lose the camera, stop offering lane changes,
> keep driving*. Before we separated them, a camera failure either stopped the
> vehicle or did nothing at all — there was no sentence in between.

**And the flag worth pointing at:**

> The column to watch is one that is empty today. If a modality is neither
> critical nor required by any capability, this table marks it **INERT** — its
> failure does nothing whatsoever. That is the *"we added a sensor and forgot to
> wire its failure response"* integration bug, it is invisible in the code, and it
> falls straight out of this table.

**If you have a spare minute, this is where predictive maintenance goes:**

> The same health map that protects the vehicle also gives you a per-modality
> decay figure — the duty cycle of a fault, not a count — in every audit row. A
> fleet operator gets *"this camera missed 23% of its frames"* at zero extra
> sensor cost.
>
> And it drives **nothing**, deliberately. A vehicle that stopped for maintenance
> would be a nuisance stop arriving through a different door.

---

## Scene 5 — The ablation, and where we lose

**Do:** the ablation and comparison tables, side by side. Terminal or slide.

```bash
uv run python -m benchmarks.ablation
uv run python -m benchmarks.comparison
```

**First, vetoes per profile:**

| profile | control | `imu_dropout` | `lateral_noise` | others |
|---|--:|--:|--:|--:|
| governed | 1 | 18 | **126** | 1 |
| L6 off | 1 | 18 | 126 | 1 |
| **L7b off** | **0** | **0** | **0** | **0** |
| L7a off | 1 | 18 | 126 | 1 |

**Say:**

> We switch each gate off in turn and re-measure. The physical gate produces
> **every veto this system emits**. Disarm it and the count goes to zero
> everywhere.
>
> And `L6 off` and `L7a off` are identical to governed in **every cell of both
> tables**. Not "nearly". Identical. On this traffic those two gates contribute
> nothing measurable.

**Give the counter-argument yourself, then refuse half of it:**

> The reading to refuse is *"two gates are decorative"*. A bound **should** rarely
> fire, and L7a vetoed once in roughly half a million nominal ticks, so a
> 2,800-tick study finding zero is consistent with that rate rather than evidence
> against it.
>
> The reading to **accept** is about L6. It is not quiet because the proposals are
> good — it is quiet because it **cannot fire**. Its live scores sit entirely
> below the corpus it is judged against, zero overlap, so its exchangeability
> assumption does not hold. That is our top open defect and the veto rate looked
> healthy the entire time it was broken.

**Then the deviation table, and do not skip it:**

| | governed | L7b disarmed | ungoverned Core-A |
|---|--:|--:|--:|
| `lateral_noise`, final \|dev\| | **1.3073 m** | 0.1384 m | 0.1484 m |
| peak \|dev\| | **1.7179 m** | 0.5854 m | — |
| ticks outside ±1.75 m | 0 | 0 | 0 |

**Say this slowly. It is the most credible thing you will say all meeting:**

> On one of six faults, our governance makes the outcome **worse**. Under a
> lateral-noise burst the governed vehicle peaks three centimetres inside its own
> corridor bound; with our own gate switched off it peaks at half a metre.
>
> We traced it this morning. The gate vetoes on lateral jerk 125 times out of 200,
> the rate limiter substitutes the largest admissible command, and the projector
> realises that as **throttle zero, brake one**. The steering axis moves by four
> milliradians. **The lateral bound is being satisfied longitudinally — by
> braking** — which is geometrically reasonable and leaves the car crawling at
> four metres a second while its deviation grows.
>
> It never leaves the lane. Every component did exactly what it was specified to
> do. And the composition is worse than no governance at all on that fault. It is
> now an open design question: should a projector prefer the axis the violated
> bound actually lives on?

**The engineering note a safety lead will notice:** switching a gate off does not
make it optional. The constructor parameters stay required and the ablation
supplies a subtype that runs and cannot block, so a pipeline with no gate is still
unconstructible. Every ablated record is stamped, so a study can never be mistaken
for a governed run.

---

## Scene 6 — The register

**Do:** put the open-defect register on screen. **21 rows** — sixteen struck
through, one reclassified, one partly closed, three open.

**Say:**

> Twenty-one defects. Every one found by this project; none reported to us.
> They were found by instruments we built for the purpose — a fault injector, a
> shadow harness, an ablation profile, a census that counts which gates ever
> object, and a test written against the textbook rather than against the code it
> was checking.
>
> Several are cases where our own evidence log confidently recorded something
> that had not happened. Those are the ones we care most about, because they are
> invisible to testing by construction.
>
> Nothing on this list was found by the test suite. Three thousand tests,
> ninety-seven percent coverage, and every one of these passed every test that
> existed when it was written. Each is a composition that is correct at every
> layer and wrong as a whole. **That is the case for runtime evidence, and it is
> the reason this architecture exists.**

**If you want one more beat, this is the best single anecdote in the project:**

> We publish retractions. In August a detector appeared to break a long-standing
> conclusion of ours and we withdrew the conclusion — then found the measurement
> had run on a vehicle with every tick vetoed and a speed of zero, the one
> configuration where the mechanism under test cannot operate. We caught it
> because two structurally different proposers produced bit-identical numbers,
> which is not a thing that happens.
>
> The fix was not a note in a document. It was a guard that **refuses to run** in
> that configuration.
>
> And here is the part I like. Yesterday we re-ran everything, and that guard had
> since begun blocking its own benchmark — because a later change gave the
> fail-safe a response that brings the vehicle to rest, and the guard read a
> successful safety stop as a dead loop. It had produced nothing for a day and
> nobody noticed.
>
> **A guard is a claim about what a valid configuration looks like, and claims go
> stale exactly like numbers do.** We pin our audit schema with a test and assert
> every invariant's enforcement kind with a test. Our retraction guards had
> nothing watching them. They do now.

**Then stop.** This is the note to end on.

---

## The scenarios, and what each is for

Every scenario is one button. The observer chooses; nothing is staged.

| Scenario | What it does | What it demonstrates | Expected outcome, today |
|---|---|---|---|
| **Nominal** | Nothing | Baseline. Every later claim is a difference from this | Gates green, ~0.017 m |
| **Tunnel** | Visibility 0.05, complexity 0.95 — outside every centroid | Bounded safe exploration — **the architectural differentiator** | `SAFE_EXPLORATION`, envelope narrows, vehicle continues |
| **IMU dropout** | The IMU stops publishing | OD-9. Gates stay green; the posture escalates from outside them | 0.062 m, DEGRADED +5, LIMP +15, comes to rest |
| **Position bias** | Constant 1 m offset on one channel | **Redundancy outvoting a liar** | Indistinguishable from clean — 0.0168 m |
| **Slow drift** | Position ramps 2 m over 400 ticks | The fault no per-tick threshold can see | 0.017 m — outvoted; **the detectors are still silent** |
| **Frozen speed** | Speed channel holds its last value | Fresh, well-formed and wrong | 0.024 m. **Report as a null** |
| **Speed bias** | +3 m/s on the speed channel | L7a's speed bound | 0.059 m. **Report as a null** |
| **Noise burst** | Lateral acceleration sigma ×25 | **Where governance costs us** | 1.307 m, 126 vetoes — worse than ungoverned |

**Three of these are nulls or losses, and show them anyway.** Frozen speed and
the speed bias did not stress what they were chosen to stress; the noise burst
stresses us. A demonstration that only shows what worked is a demonstration that
has been curated, and an audience that spots the curation discounts everything
else.

---

## What must never be claimed

Print this. Read it before the meeting. Each line has cost this project a
retraction or a register row.

| Never say | Because |
|---|---|
| "false-positive rate" or "false-negative rate" of any gate | The plant, twin and corpus share one set of equations. **No such rate exists** and none can before an external plant |
| "the gates are independent" | All three read L2's estimate; OD-9 is a measured common cause. And two of three never object |
| "three layers of defence" | Measured: **one**. Disarming L7b takes every veto to zero |
| "1.25 µs intercept latency" | An analytical bound for hardware that does not exist. Never quotable as measured |
| "real-time" or "meets a 10 ms budget" | p50 is 2.2 ms; **p99 has reached 10.46 ms and a single tick 61 ms**, on an idle host, with no deadline monitor |
| "ASIL-D" | A design target. An ASIL is the outcome of an assessed safety case |
| "validated on real driving" | **`[M-ext]: 0 of 30`.** The UKF has met only synthetic dynamics |
| "domain-independent" without qualification | Partly violated. Say *"the gates are; the process model is not"* |
| "tamper-proof evidence log" | Tamper-**evident**. Tail truncation and a consistent whole-file rewrite are both undetectable |
| "it detects sensor faults" | It detects a channel going **quiet**, and outvotes one that lies. A slow drift defeats both |

**The false-positive rate has a specific trap.** Two different numbers exist and
conflating them is the fastest way to lose the room:

- **Per tick**, the gate vetoes **ε** by construction — because ε of any
  distribution lies above its own 1−ε quantile.
- **Per intervention**, at the design point: **0.008% of ticks outside NOMINAL.**

**Both are quotable together and neither is quotable alone.** And both are
`[M-syn]` — measured on a plant we wrote.

---

## The questions they will ask

**"What's your false-positive rate?"**
> Two numbers and I have to give you both or neither — per tick it is epsilon by
> construction, per intervention it is 0.008% of ticks. Both measured on a plant
> we wrote, which is why neither is the number you actually want. That one needs
> an external environment and it is the next piece of work.

**"How often do your gates fire?"**
> One of three does all of it. The statistical gate cannot currently fire — its
> exchangeability precondition is violated — and the deterministic gate is a
> bound that should rarely fire, though zero across a fault suite is more than
> *rarely* and we have not explained it. Both are open register rows.

**"Is it real-time?"**
> No, and I would not claim it. Median tick is 2.2 milliseconds against a
> ten-millisecond budget; the ninety-ninth percentile has touched 10.46 and a
> single tick reached 61. On an idle machine, in CPython, with no deadline
> monitor — a late tick is written to the record identically to a punctual one.
> It is characterised, not guaranteed.

**"What would it take to put this in a vehicle?"**
> More than validation, and I would rather list it than wave at it. A real-time
> execution environment — this is CPython. A process or hardware boundary; ours
> is a type boundary, which stops code and not a compromised process. Byzantine
> tolerance above zero, which needs a fourth dissimilar channel. Certification
> artefacts. And an actuation path with real faults in it — every fault we inject
> is at the sensor end.

**"What's the weakest part?"**
> All three gates read one estimate. That is by design — nothing above L2 touches
> raw readings — and it makes L2 a common cause. We measured it: a frozen IMU took
> the vehicle four metres off a lane with every gate passing and a verdict trace
> identical to a clean run's.

**"How do I know your numbers are right?"**
> You do not, on my word. Every one is a row with the command that reproduces it,
> a number lives in exactly one place so it cannot go stale in a second document,
> and several are marked withdrawn with the reason. We re-ran the whole set on the
> sixteenth and corrected twelve figures, two of which were corrections to
> corrections we had made that morning.

---

## Fallback plan

**If the dashboard will not start** — every scene has a terminal command. The
benchmarks are the source of the numbers anyway; the dashboard is a view of them.

**If a benchmark refuses to run** — read the refusal aloud. `make artifacts-check`
saying *"the vehicle does not drive"* is the guard working, and explaining it is a
better story than the demo you had planned. That is genuinely true and not a
consolation.

**If the vehicle stops and you did not expect it** — check the artefacts first.
`var/` is gitignored and a stale corpus can put every tick into a veto. This has
happened; it is `E-148`, and `make artifacts-check` exists because of it.

**If someone asks something you cannot answer** — say so, write it down, and send
the answer. The register is full of things found by someone asking an awkward
question; treating one as an attack is the only way to lose a room that is
otherwise on your side.

---

## Pre-flight, the morning of

```bash
make artifacts-check     # must say the vehicle DRIVES
make check               # gate green
uv run python -m benchmarks.arms          # scene 1
uv run python -m benchmarks.degradation   # scene 4
uv run python -m benchmarks.ablation      # scene 5
```

Order matters for the first one: the corpus is generated *through* the twin and
the policy is trained against both, so a mismatched set loads cleanly and measures
nothing.

Have open in tabs: the register, `EVIDENCE.md`, and
[`A-Z/00_START_HERE/REPRODUCE.md`](../A-Z/00_START_HERE/REPRODUCE.md) so any
number on screen can be re-run in front of them. **Offer that.** Almost nobody
can, and the offer alone changes how the rest is heard.

---

## The closing line

> What we have built is a governance layer that keeps an untrusted controller
> inside an envelope it can state, degrades in steps instead of stopping, and
> writes down why — and an apparatus that finds our own defects faster than a
> reviewer can.
>
> What we have **not** done is validate any of it against an environment we did
> not write ourselves. Zero of thirty claims are external. That is the next piece
> of work, we know exactly what it will cost us, and we have written down what we
> expect it to break before running it.

---

## What changed since the 10 August plan

Recorded so this document does not become the thing it warns about.

| Was | Is | Why |
|---|---|---|
| Dropout deviation **4.199 → 0.167 m** | **0.062 m** | ADR-0033 put redundancy on the driven path |
| Dropout escalates to **HALT at +40** | **LIMP at +15; HALT never** | ADR-0030's health-level ceiling caps a `DEGRADED` stream |
| `position_bias` 0.931 m, `position_drift` 2.025 m | **both 0.017 m** | Outvoted before reaching the estimator |
| Redundancy *"we cannot measure that here — that is Phase 7"* | **Scene 1, the strongest result in the deck** | ADR-0033 |
| Ablation: governed 3 / L6 off 3 / L7b off 0 | **1 / 1 / 0**, and L6 and L7a now identical to governed in every cell | Re-measured |
| Register: **13 rows** | **21 rows** | Six weeks of finding things |
| `OD-10`, the innovation covariance | **Closed** by ADR-0032 | The sigma points are redrawn after process noise |
| Latency: not discussed | **Named, with the tail** | Measured on 16 August; the earlier plan quoted no figure and the A-Z folder wrongly said none existed |

**Two ADRs moved a headline safety number and nothing announced it.** Re-run
[`A-Z/00_START_HERE/VERIFY_PROMPT.md`](../A-Z/00_START_HERE/VERIFY_PROMPT.md)
before any demo that follows a code change.
