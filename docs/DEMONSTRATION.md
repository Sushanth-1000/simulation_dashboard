# ASTRA — Demonstration Plan

**Prepared** 10 August 2026
**For** a technical audience at a company: engineers, a safety lead, possibly a
research manager. Not a sales meeting.
**Runs on** one laptop, no GPU, no network.
**Length** 12 minutes of driving, 20–30 with questions.

---

## The one decision that shapes everything below

**Do not demonstrate that the gates catch faults. They mostly do not, and we
know exactly which ones and why.**

That sentence is the whole strategy. Every instinct says to open with a fault
being caught, and every instinct is wrong here, for three reasons:

1. **It is not true on the current evidence.** Of six injected faults, two put
   the vehicle outside its corridor with a verdict trace *identical* to the
   clean run's (E-46, E-47). A demo implying otherwise is a demo that falls
   apart under the first informed question.
2. **The room contains someone who will test it.** Safety engineers do not
   watch demos, they probe them. The first question after any "watch it catch
   this" is "what does it miss?" — and you want the answer to be a document,
   not a pause.
3. **The honest version is the stronger pitch.** Nobody in that room has ever
   been shown a prototype whose authors built the instrument that found its own
   worst defect, measured it, and put it on screen. That is the differentiator,
   and it is not available to a team that hid it.

So the demonstration's argument is: **we can find things.** The architecture is
the subject; the *method* is the product.

---

## The arc, in one table

Each scene earns the next. Do not reorder.

| # | Scene | Time | What it proves | The line that lands |
|:--:|---|:--:|---|---|
| 0 | The nominal drive | 1 min | The thing runs, and every number is traceable | *"Everything on this screen came out of an audit record. Nothing is drawn."* |
| 1 | **The tunnel** | 3 min | An unrecognised context narrows the envelope instead of stopping | *"Most runtime assurance halts here. This keeps moving, inside a bound it can defend."* |
| 1b | *(within scene 1)* | — | Calibration promotion is staged, not a config reload | *"It found a better profile and is running both in parallel. Nothing switches until the divergence clears."* |
| 2 | **The sensor fault** | 3 min | The gates are blind to it, measured, on screen | *"Watch the two lines separate. Now watch the gate panel. That is our worst open defect and we found it."* |
| 3 | **The recovery** | 2 min | The blindness lasts exactly as long as the lie | *"The instant the sensor tells the truth again, all three gates fire at once."* |
| 4 | **The ablation** | 2 min | One gate does almost all the work | *"We measured what each gate is worth. Two of them are worth less than we assumed."* |
| 5 | The register | 1 min | Eleven defects, all self-found | *"Every one of these was found by us, and five were found this week by instruments we built for the purpose."* |

---

## Scene 0 — The nominal drive

**Do:** start the dashboard. Let it run for thirty seconds without touching it.

```bash
uv run python -m demo.dashboard
```

**Point at, in this order:**

- The three gate panels — L6 statistical, L7b physical, L7a deterministic —
  lit independently, each with its own reason code.
- The **estimate against the truth** on one axis, both inside the ±1.75 m
  corridor, sitting on top of each other.
- The footer.

**Say:**

> Every value on this page except two is copied straight out of that tick's
> decision record — the same record that goes into the audit log. The two
> exceptions are the red line and the true speed: those come from the
> simulator, because no real vehicle knows where it actually is. They are
> labelled, and they are on screen for a reason you will see in a minute.

**Why this scene exists.** It buys the right to be believed in scenes 2 and 3.
An audience that has watched you volunteer *"this number is not something a real
system would have"* will accept the later numbers without arguing.

**Do not say** that the run is stable "over 100,000 ticks" while showing a
400-tick window. That figure is real (E-2) and belongs in the answer to a
question, not in the narration of a different measurement.

---

## Scene 1 — The tunnel, and the thing nothing else does

**This is the architectural argument, and it should come before any fault.**

**Before pressing anything**, point at the RCM panel. It reads
**`SHADOW_EXECUTION`**, active profile `urban_clear`, trust score **0.717**
against a threshold of 0.70.

**Say:**

> Before the tunnel, look at what RCM is already doing. It has found a
> calibration profile that fits this context better than the active one, and it
> is running both in parallel — shadow execution. Nothing switches until the
> divergence index between them clears. A calibration change on a safety system
> is not a config reload here; it is a staged, measured promotion.

**Do:** press **Enter the tunnel**. It moves the context signature outside every
certified profile in the knowledge base.

**What appears:**

- RCM's arbitration outcome changes from `SHADOW_EXECUTION` to
  **`SAFE_EXPLORATION`**.
- The trust score drops below threshold; **no candidate is admissible at all**.
- The actuation envelope narrows on screen: **speed capped to half the nearest
  certified profile's maximum, steering restricted to a ±15° cone, lane changes
  refused**.
- **The vehicle keeps driving.** Commands continue to issue on every tick.

**Say:**

> The vehicle has just entered a context that no certified calibration profile
> covers. A tunnel — the profile is withheld deliberately, so this path gets
> exercised rather than assumed.
>
> And note what I did *not* do: I did not tell it to explore. I moved the
> context. RCM re-evaluated on its own period, found nothing admissible, and
> chose this. The button changes the world, not the verdict.
>
> Systems in our prior-art table degrade to a stop here, because their
> certified envelope is where their guarantee lives and outside it they have
> nothing to say. This narrows the envelope instead: half speed, a fifteen
> degree steering cone, no lane changes, and every tick of it logged as
> exploration rather than as normal operation. The vehicle keeps moving inside
> a bound the system can defend.

**Then say the limit, unprompted:**

> What this shows is the *mechanism* — the envelope narrows, it widens again on
> the way out, and no tick fails to issue a command. It does not show that the
> vehicle drives *well* in a tunnel. That needs a real simulator and a trained
> policy, and it is Phase 7.

**Why unprompted matters.** Saying the limit before they ask converts a
weakness into a demonstration of calibration. Saying it after they ask converts
it into a concession.

---

## Scene 2 — The sensor fault, and our worst open defect

**Do:** press **IMU dropout**. Then stop talking for about five seconds and let
them watch.

**What appears:**

- The blue estimate line stays flat near the centre.
- The red truth line walks steadily away from it.
- **The gate panel stays green.** All three. `NOMINAL` on every one.
- Fail-safe: `NOMINAL`. OOD counter: 0. No speed cap.
- The truth line crosses the dashed corridor and keeps going.

**Say, once it is unmistakable:**

> Every gate is green. The fail-safe machine is nominal. The audit log for these
> ticks is indistinguishable from the clean run you just watched.
>
> The vehicle is now outside its lane by more than a lane width, and the
> corridor bound — the check we added specifically to catch a lane departure —
> is reading two centimetres.

**Then give the mechanism, because the mechanism is the impressive part:**

> This is not a missing check. The bound exists. It reads the position estimate,
> and the controller closes its loop on the same estimate — so the controller is
> actively driving the corrupted number to the value the monitor considers safe.
> A sensor fault blinds the monitor and the thing it monitors at the same time,
> through the same channel.
>
> We call it OD-9. We found it on the first fault we ever injected, about an hour
> after the injector worked.

**Numbers to have ready** (do not recite them all; use one):

- 200-tick dropout: **4.199 m** off a 1.75 m lane, corridor bound reading
  **0.023 m** (E-46, E-48).
- The error propagates into the *unobserved* state: true heading **0.0686 rad**
  against an estimate of **0.0017** (E-58).
- 600-tick dropout: **35.705 m**, still no attributable veto (E-76).

---

## Scene 3 — The recovery, and the shape of the blindness

**Do:** wait for the fault window to close. Twenty seconds. Say nothing for the
last five.

**What appears, on the exact tick the sensor recovers:**

- All three gates flip to **VETO** simultaneously —
  `SCORE_EXCEEDS_CONFORMAL_QUANTILE`, `LATERAL_JERK_EXCEEDS_LIMIT`,
  `LATERAL_OFFSET_EXCEEDS_CORRIDOR`.
- The fail-safe machine escalates **NOMINAL → DEGRADED → LIMP → HALT**.
- Speed cap drops to 0.0, origin becomes `SPEED_CAPPED`, the vehicle brakes to a
  stop.

**Say:**

> That happened on the tick the sensor started telling the truth again. Not one
> tick earlier.
>
> So the blindness lasts exactly as long as the lie. The graduated response
> works precisely as designed — three gates, escalating states, a controlled
> stop. It simply cannot start until the corrupted channel stops being
> corrupted, and by then the vehicle is twenty lane-widths out.

**This is the best thirty seconds of the demonstration.** It shows a working
safety machine and its exact failure condition in one continuous shot, and
neither half is oversold.

---

## Scene 4 — The ablation

**Do:** switch to the ablation table. This is a slide or a terminal, not the
live page.

```bash
uv run python -m benchmarks.ablation
```

**Show:**

| profile | control | `imu_dropout` | `position_bias` | others |
|---|--:|--:|--:|--:|
| governed | 3 | 3 | 12 | 3–4 |
| L6 off | 3 | 3 | **11** | 3–4 |
| **L7b off** | **0** | **0** | **1** | **0** |
| L7a off | 3 | 3 | 12 | 3–4 |

**Say:**

> We switched each gate off in turn and re-measured. L7b — the physical
> admissibility gate — produces essentially every veto this system emits.
> L6 contributes one veto in 2,800 ticks. L7a contributes zero.
>
> The architecture's story is three independent gates. On this traffic, the
> observable behaviour is one gate.

**Immediately give the counter-argument yourself:**

> The reading to refuse is "two gates are decorative". L7a vetoed once in
> roughly half a million nominal ticks — a 2,800-tick study finding zero is
> consistent with that rate, not evidence against it. What this measures is each
> gate's contribution *on these seven scenarios*, and that is the whole claim.

**The engineering point worth making here:** switching a gate off did not mean
making it optional. The constructor parameters stayed required and the ablation
supplies a subtype that runs and cannot block, so a pipeline with no gate is
still unconstructible. Every ablated record is stamped, so a study can never be
mistaken for a governed run. That is ADR-0021, and it is the kind of thing a
safety lead notices.

---

## Scene 5 — The register

**Do:** put `CREDIBILITY_MATRIX.md`'s open-defect register on screen. Eleven
rows.

**Say:**

> Eleven open defects. Every one found by this project, none reported to us.
> Five were found this week, by instruments we built for the purpose — a fault
> injector, a shadow harness, an ablation profile, and a test written against
> the textbook rather than against the code it was checking.
>
> Two of the eleven are cases where our own evidence log confidently recorded
> something that had not happened. Those are the ones we care most about,
> because they are invisible to testing by construction.

**Then stop.** This is the note to end on.

---

## The scenarios, and what each is for

Every scenario is one button. The observer chooses; nothing is staged.

| Scenario | What it does | What it demonstrates | Expected outcome |
|---|---|---|---|
| **Nominal** | Nothing | Baseline. Every later claim is a difference from this | Gates green, ±0.03 m |
| **Certified road** | The starting context — visibility 0.85, traffic 0.7, complexity 0.7 | RCM's *normal* work: a better profile found, both run in parallel | `SHADOW_EXECUTION`, trust **0.717** vs τ 0.70 |
| **Tunnel** | Visibility 0.05, complexity 0.95 — outside every centroid | Bounded safe exploration — **the architectural differentiator** | `SAFE_EXPLORATION`, envelope narrows, vehicle continues |
| **IMU dropout** | The IMU stops publishing for 400 ticks | OD-9. The estimate freezes, truth departs, gates stay green | 4.2 m in 200 ticks; no veto until recovery |
| **Slow drift** | Position ramps 2 m over 400 ticks, 1 cm/tick | The fault no per-tick threshold can see | 2.025 m out; silent on **all three** shadow detectors |
| **Position bias** | Constant 1 m offset | The one fault L6 partly notices | Vetoes 3 → 12; still leaves the corridor |
| **Frozen speed** | Speed channel holds its last value | Fresh, well-formed and wrong — staleness cannot see it | Barely moves the vehicle. **Report as a null** |
| **Noise burst** | Lateral acceleration sigma ×25 | Trust Index responds; the vehicle does not depart | TI 0.96 → 0.61, context flips to `DEGRADED_SENSOR` |

**Two of these are nulls, and show them anyway.** Frozen speed and the speed
bias did not stress what they were chosen to stress (E-50). A demonstration that
only shows the scenarios that worked is a demonstration that has been curated,
and an audience that spots the curation discounts everything else.

---

## What must never be claimed

Print this. Read it before the meeting. These are not hedges — each is a row in
`EVIDENCE.md`'s *Not demonstrated* section, and each has cost this project a
retraction already.

| Never say | Because |
|---|---|
| "false-positive rate" or "false-negative rate" of any gate | **N-1.** The plant, twin and corpus share one set of equations. No such rate exists and none can before Phase 7 |
| "the gates are independent" | **N-2.** All three read L2's estimate. OD-9 is a measured common cause |
| "1.25 µs intercept latency" | **N-3.** An analytical bound for hardware that does not exist. Never quotable as measured |
| "ASIL-D" | **N-4.** A design target. An ASIL is the outcome of an assessed safety case |
| "validated on real driving" | **N-5, N-11.** The UKF has met only synthetic dynamics |
| "domain-independent" without qualification | **A-1 is PARTLY VIOLATED.** Say "the gates are; the composition root and process model are not" (E-72–E-75) |
| "the Mahalanobis distance is X" | **OD-10.** The innovation covariance omits `H Q Hᵀ`. It is not a Mahalanobis distance |
| "tamper-proof evidence log" | Tamper-**evident**. Tail truncation and a consistent whole-file rewrite are both undetectable |

**The false-positive rate has a specific trap.** Two different numbers exist and
conflating them is the fastest way to lose the room:

- **Per tick**, the gate vetoes **ε** — 5% at the shipped significance level, and
  always will, because ε of any distribution lies above its own 1−ε quantile.
- **Per intervention**, measured at the design point: **0.008% of ticks outside
  NOMINAL** — two episodes in 83 minutes, both self-recovering (E-42).

**Both are quotable together and neither is quotable alone.** And both are
`[M-syn]`.

---

## The questions they will ask

Ordered by likelihood. The answer to every one already exists; the job is to
know where.

**"What's your false-positive rate?"**
> Two numbers, and I have to give you both or neither. Per tick it is epsilon,
> five percent, by construction — that is the conformal guarantee working. Per
> intervention it is 0.008%. But both are on synthetic data where the plant and
> the judge share equations, so neither is a rate you should plan against. The
> number you want needs real logs, and that is exactly what we would want from a
> collaboration.

**"So the gates didn't catch it. What use is the system?"**
> On that fault, none — and we would rather you heard that from us. What the
> system did was produce a record complete enough that we could find the defect,
> localise it to a shared input, and measure a fix that gives 3.4 seconds of
> warning. That is the capability we are offering: not gates that catch
> everything, but a runtime whose evidence is good enough to find out what they
> miss.

**"Why should we believe your numbers?"**
> Every one has a command next to it that reproduces it on a clean checkout,
> and three published numbers have been retracted after they turned out to be
> artefacts. The retractions are still in the document, with their corrections.

**"How long to get this on our platform?"**
> Honestly: the gates would take an adapter. The composition root and the
> process model are automotive today and we have measured exactly where — four
> walls, three of them a refactor and one a migration. We tested that this week
> with a warehouse AGV rather than assuming it.

**"Is it real-time?"**
> No, and it is not close. It is Python, the full tick is about 9 ms p99 against
> a 50 ms period, and there is no hard guarantee anywhere. The architecture is
> the deliverable; a deployable implementation is a different project.

**"What happens if someone attacks it?"**
> There is a threat model as of this week. The short version: we defend
> thoroughly against a proposer that is wrong and not at all against a platform
> that is compromised, and the second is the larger surface. The evidence log is
> tamper-evident since yesterday; artefact digests are recorded but not verified
> at load, which is the next thing to fix.

**"Did you build this or did a tool?"**
> Answer honestly. The evidence is reproducible either way, and the register of
> self-found defects is the thing that is hard to fake.

---

## Fallback plan

**Capture the recording before the meeting. Every time.**

```bash
uv run python -m demo.dashboard --ticks 3000 --record var/demo/fallback.jsonl
uv run python -m demo.dashboard --replay var/demo/fallback.jsonl
```

A replay streams recorded frames at the captured rate. The page cannot tell the
difference; the fault buttons refuse with 409, because the faults in a recording
already happened. **A recording is exactly the frames the live run produced**, so
it is as traceable to decision records as the run that made it — say so, and the
fallback costs you interactivity rather than credibility.

**If the laptop dies entirely**, the ablation and comparison tables are static
and carry scenes 4 and 5 unaided.

---

## Pre-flight, the morning of

```bash
make check                                   # 2,849 tests + 5 strict xfail
uv run python -m benchmarks.fault_study      # reproduces E-46 .. E-50
uv run python -m demo.dashboard --ticks 3000 --record var/demo/fallback.jsonl
```

- [ ] Gate green, and know the number by heart
- [ ] Fallback recording captured **today**
- [ ] `--rate 1.0` — real time. The harness runs 5× faster than the vehicle and
      an unpaced demo shows the fault arriving and leaving before anyone finds it
- [ ] Browser at 1440 px or wider, or the layout stacks
- [ ] `CREDIBILITY_MATRIX.md` and `THREAT_MODEL.md` open in tabs
- [ ] **Know that HALT is terminal.** `reset()` is its only exit by design, so
      once scene 3 stops the vehicle, restart the server before scene 4

---

## The closing line

If you take one sentence into the room, take this one:

> **We built the instrument that found our own worst defect, and we are showing
> you the defect.**

Everything else in this document is in service of making that sentence land as
confidence rather than as an apology.


---

## Appendix — the numbers behind the context tuning

Recorded because getting this wrong once cost an afternoon and would have made
scene 1 meaningless.

The Runtime Context Signature has five components: visibility, **ego speed
normalised by the legal limit**, traffic dynamicity, sensor reliability, road
complexity. Three arrive from the cold-path context; two are computed from the
vehicle's own state.

The trap is the second one. This policy cruises at about **12.5 m/s** against a
**33.3 m/s** limit — 0.375. `HIGHWAY_CLEAR`'s centroid wants **0.8**. So a
context that *looks* like clear highway on the three supplied components still
misses on the fourth, and the first attempt at a "certified" baseline sat in
permanent `SAFE_EXPLORATION` — which would have destroyed the contrast the
tunnel scene depends on, while looking like the tunnel scene working.

Measured, 200 ticks each:

| context | supplied `(vis, traffic, complexity)` | outcome |
|---|---|---|
| urban-matched | `(0.85, 0.7, 0.7)` | `SAFE_EXPLORATION` ×80 → **`SHADOW_EXECUTION`** ×120, trust 0.717 |
| clear-highway-looking | `(0.90, 0.3, 0.2)` | `SAFE_EXPLORATION` throughout |
| tunnel | `(0.05, 0.7, 0.95)` | `SAFE_EXPLORATION` throughout |

The first eighty ticks of the matched case are exploration too, and that is
correct rather than a defect: the vehicle starts from rest, so its ego-speed
component does not match anything until it is up to speed. **If an audience
notices the run opens in exploration, say that** — it is the signature tracking
a real change in the vehicle's state, which is the mechanism working.
