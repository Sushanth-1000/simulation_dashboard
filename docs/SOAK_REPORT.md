# Soak report — the closed loop over 100,000 ticks

**Run date** 1 August 2026
**Baseline** `833ce4d`, plus the soak harness added for this run
**Host** WSL2 Ubuntu, Linux 6.6.87.2, CPython 3.12.13, CPU only
**Commands** — four runs of 100,000 ticks each, ~4 minutes apiece
```bash
uv run python -m benchmarks.soak --ticks 100000 --window 1000 --output var/soak/learned-100k
uv run python -m benchmarks.soak --ticks 100000 --window 1000 --placeholder --output var/soak/placeholder-100k
uv run python -m benchmarks.soak --ticks 100000 --window 1000 --cold-path open   --output var/soak/coldpath-open
uv run python -m benchmarks.soak --ticks 100000 --window 1000 --cold-path tunnel --output var/soak/coldpath-tunnel
```
**Artefacts** `var/soak/*/{windows.jsonl,summary.json,soak.png}`

This closes Phase 2.1 of [`WORK_PLAN.md`](WORK_PLAN.md). It is the first run in the
project's history longer than 400 ticks.

---

## The verdict

**The loop is not stable, in either configuration, and it fails differently in
each.**

With the cold path dormant — how every run before this one was configured — **the
vehicle leaves the lane at around tick 900 and never returns.** By tick 100,000
it is 2,883 m from the lane centre at 17.2 m/s, every tick vetoed, the fail-safe
machine in HALT. A control run with the deterministic placeholder policy reaches
the same deadlock sooner through a *different* gate, so it is a property of the
loop and not of the learned policy.

With the cold path engaged, the departure disappears and is replaced by the one
behaviour the architecture was built to avoid: **the vehicle comes to a complete
stop at around tick 400 and stays there for the remaining 99,600 ticks.** Along
the way, bounded safe exploration issues the proposer's command on 99.8% of ticks
*while Core-B's aggregate verdict is blocking*.

Both configurations issued a command on all 100,000 ticks. Availability is not
the problem.

### The common cause, found while investigating the second run

**The trained policy does not control speed. It brings the vehicle to a complete
stop inside its own training environment, with no part of ASTRA involved.**

```
reference speed 13.0 m/s, episode 500 steps
accel authority 3.0, brake 8.0
  step    0  v= 10.219  dev=  0.773  cmd=(0.481, 0.498, -0.051)  net=-2.54 m/s^2
  step  100  v=  5.329  dev= -0.051  cmd=(0.516, 0.492, -0.000)  net=-2.39 m/s^2
  step  250  v=  0.000  dev= -0.055  cmd=(0.540, 0.493, +0.001)  net=-2.33 m/s^2
  step  499  v=  0.000  dev= -0.055  cmd=(0.540, 0.493, +0.001)  net=-2.33 m/s^2
```

Its lateral control is real and good — the lane deviation settles at 5 cm and
stays there, and steering responds correctly to lateral error, swinging −0.065 to
+0.063 rad for ±1 m of offset. Its **longitudinal** output is near-constant:
brake sits at 0.49 whatever the state, throttle moves only between 0.43 and 0.54,
and on a plant with 8.0 m/s² of braking against 3.0 m/s² of acceleration *every
command in that range decelerates the vehicle*. At exactly its own target speed,
on the lane centre, it commands −2.5 m/s².

Everything above is downstream of that one fact:

- speed collapses → the OOD counter climbs → HALT → the fallback governs → the
  fallback holds speed but commands zero steering → **lane departure** (F1);
- speed collapses → the runtime context signature leaves every profile's ball,
  because no certified profile covers a slow vehicle → `SAFE_EXPLORATION` →
  the envelope halves throttle → the vehicle can never recover speed → **it
  stops** (F6).

No existing test could have caught it. `test_closed_loop_policy.py` runs 300
ticks — the vehicle has only fallen from 10.2 to about 3 m/s by then — and
asserts lane deviation, veto rates and issuance. **Nothing in the suite asserts
that the vehicle is still moving.** Three tests now do.

**It is fixed, and fixing it did not fix the lane departure.** Two changes were
needed, and a controlled 2×2 at a fixed seed shows both are load-bearing:

| training steps | action-rate penalty over all 3 channels | over steering only |
|---|---|---|
| 98k | stops — return 549, mean \|long. accel\| 1.289 m/s² | stops |
| 786k | **stops** — return 671, 1.289 m/s² | **holds 13.0 m/s** — return 986, 0.158 m/s² |

The action-rate term was documented from the start as being for L7b's *lateral*
jerk limit, and it was being applied to throttle and brake as well. At weight 6.0
against a task reward capping at 2.0, that made a constant longitudinal command
the cheapest behaviour available — and the constant a Gaussian policy starts from
is a normalised action of zero, which maps to half throttle and half brake:
−2.5 m/s². Restricting the term to steering and raising the default budget to
786k timesteps produces a policy that converges on 13.035 m/s and holds the lane
to 0.033 m.

Re-running the soak with it: **the departure is unchanged.** See F1a.

---

## What held

Four properties were measured over 100,000 continuous ticks and all four held.
These are real results and none of them was previously known.

| Property | Result |
|---|---|
| **Availability** | 100,000 of 100,000 ticks issued a command. The architecture's headline claim survives a run 250× longer than any before it |
| **Resident memory** | +0.2 MiB peak growth after the first window. Every rolling structure — the Mondrian buckets, the MMD window, the twin's Fisher history — is genuinely bounded, not merely documented as bounded |
| **Per-tick cost** | p99 4.82 ms → 4.67 ms between halves (×0.97). No growth. p50 ≈ 2.2 ms |
| **Evidence integrity** | 0 audit records dropped by the sink's bounded queue across 100,000 records |

The twin weights digest was constant throughout, as it must be while FB2 is
unwired. Every figure above is reproduced within noise by the placeholder run.

---

## What failed

### F1 — Unbounded lane departure, and no mechanism to recover from it

The failure is not a blow-up. It is a deadlock, and each component in it is
behaving exactly as specified.

| Tick | What is happening |
|---|---|
| 0–200 | The policy proposes throttle ≈ 0.53 with brake ≈ 0.49. Braking authority is 8.0 m/s² against 3.0 m/s² of acceleration authority, so the net command decelerates. Speed falls from 10.3 to 1.0 m/s |
| ~210 | The OOD counter crosses θ₃ = 20. The FSM enters **HALT** and, by design, never leaves — `reset()` is documented as the only exit |
| 200–800 | Most ticks are vetoed `PHYSICAL:PROPOSAL_DIVERGES_FROM_TWIN`. The fallback governs. It holds speed and, by explicit design, commands **zero steering** |
| ~750 | One proposal passes and puts a small heading on the vehicle. Nothing ever takes it off again |
| 800 → ∞ | Every tick is vetoed `PHYSICAL:LATERAL_JERK_EXCEEDS_LIMIT`. The vehicle drives in a straight line at a fixed heading, accelerating toward the fallback's target of half the legal speed limit (16.7 m/s), out of the lane, for ever |

Once the vehicle is outside the lane it is outside the policy's training
distribution, and the corrections it proposes there are physically absurd — at
tick 1,950 it proposes 0.25 rad of steer, which at the plant's steer
effectiveness of 140 is 35 m/s² of lateral acceleration, over 3 g. L7b is
correct to veto it. The fallback is correct to command zero steering — its
docstring argues the case, and the argument is sound. **But between them there
is no controller with both the authority and the permission to bring the vehicle
back**, so the departure is monotone: 7 m at tick 2,000, 267 m at tick 10,000,
2,883 m at tick 100,000.

**The control run makes this a property of the loop.** Driven by the
deterministic `KinematicPlaceholderPolicy` instead, the same run departs the lane
sooner and through a different gate — `STATISTICAL:SCORE_EXCEEDS_CONFORMAL_QUANTILE`
(L6) on 100% of ticks from tick 1,000, rather than L7b's jerk limit. It settles
at exactly 19.46 m/s, the fallback's speed target, and departs linearly to 712 m
by tick 90,000. Two different proposers, two different gates, one shape:

| | Learned policy | Placeholder |
|---|---|---|
| Veto reason, steady state | `PHYSICAL:LATERAL_JERK_EXCEEDS_LIMIT` | `STATISTICAL:SCORE_EXCEEDS_CONFORMAL_QUANTILE` |
| 100% veto from | tick ~1,000 | tick ~1,000 |
| Steady speed | 17.2 m/s | 19.5 m/s |
| Deviation at tick 90,000 | 2,619 m | 712 m |

**This run had the cold path dormant** — `drive_closed_loop` passed
`cold_path=None`, so `arbitration` is absent from all 100,000 decision records
and bounded safe exploration never engaged. That was the obvious next experiment
and it is now F6 below: engaging it removes this failure and substitutes another.

### F1a — The mechanism is a latch, and no proposer can escape it

Re-run with the speed-holding policy, the departure is identical. The first
window now looks healthy — 36% veto rate, 639 of 1,000 ticks issued as
`PROPOSED`, the vehicle holding 13.6 m/s, and one
`DETERMINISTIC:LATERAL_ACCELERATION_EXCEEDS_FRICTION` from L7a, its only veto in
half a million ticks. Then the OOD counter crosses θ₃, the FSM reaches HALT, and
from tick 1,000 onward it is 100% `PHYSICAL:LATERAL_JERK_EXCEEDS_LIMIT` and
`FALLBACK_PID` for ever, departing at a constant 17.17 m/s — the fallback's
speed, not the policy's.

The latch, stated exactly:

1. The fallback commands **zero steering** by design, so the plant's lateral
   acceleration goes to zero and stays there.
2. L7b's jerk bound is `|a_proposed − a_current| / dt ≤ 8.0 m/s³`, and
   `a_current` is read from the state estimate — which now reflects the
   *fallback's* behaviour, not the proposer's.
3. At `dt = 0.05 s`, the largest lateral acceleration admissible from rest is
   therefore **0.4 m/s²**. The vehicle is by now far off-lane, so every useful
   correction exceeds it.
4. The proposal is vetoed, the fallback governs again, and step 1 re-establishes
   the condition that made the veto inevitable.

**The escape path is closed by construction.** Leaving the latch requires
ramping lateral acceleration in ≤0.4 m/s² steps, but a proposal only moves
`a_current` if it is *executed*, and it is not executed while vetoed. No
proposer, however well trained, can climb a ramp it is never allowed to stand on.

Three policies confirm it is not a policy-quality problem — the original stopping
one, the speed-holding one (36% initial veto rate), and one trained with an
explicit jerk penalty (97%) all reach the same terminal state.

The design question this poses is sharp and worth an ADR: **while the fallback is
governing, L7b judges the proposer against a state the proposer did not create.**
The jerk it measures is that of a transition from the fallback's trajectory to
the proposer's — a transition the vehicle would never actually make.

Two things were tried and are recorded so they are not tried again:

- **An explicit jerk term in the training objective**, charging
  `w × max(0, jerk − 8.0)/8.0` per step from the plant's own lateral
  acceleration. At `w = 1.0` it swamps a task reward that caps at 2.0 and
  training collapses (return 63, collision rate 1.0). At `w = 0.1` training is
  healthy (return 897, deviation 0.114 m) and the closed loop is *worse* — 97%
  veto in the first thousand ticks against 36% without it. Reverted.
- The existing `action_rate_weight` proxy, quantified: at the gate's boundary a
  permitted step is a normalised action change of 0.0057, which the term charges
  `6.0 × 0.0057² = 2×10⁻⁴` against a centring reward of 1.0. **It is inert with
  respect to the bound it was introduced to approximate** — the same shape of
  finding as the EWC λ already recorded in the work plan.

### F1b — The training plant integrates 2.5× faster than the pipeline ticks

`EnvironmentSpec.step_seconds = 0.02`, and its docstring reads *"Integration
step. Matched to the pipeline's fast rate."* The pipeline's fast rate is
`fast_rate_hz = 20.0`, i.e. **0.05 s**. They have never matched.

`drive_closed_loop` steps the plant once per tick and advances the clock by
`1/fast_rate_hz`, so every run through this harness advances 0.02 s of vehicle
motion per 0.05 s of pipeline time. Consequences worth stating:

- Every "simulated time" figure in this report is 2.5× optimistic: 100,000 ticks
  is 5,000 s of pipeline time and 2,000 s of plant motion.
- The policy learns a rate of change per 0.02 s step and is judged by a gate
  computing jerk over 0.05 s, which makes the gate 2.5× *more* permissive than
  training — so this is not a cause of the vetoes, but it does mean no measured
  jerk figure means what it appears to.
- The UKF's process model, the twin and the corpus all assume the pipeline
  period.

Fixing it means regenerating the twin, the corpus and the policy (trap 9), which
is why it is recorded here rather than done.

### F2 — HALT does not halt, because the fail-safe speed cap is never applied

**Resolved 2 August 2026 by P2.1.** The cap is now projected onto the issued
command across the `CommandProjector` seam, applied last and after whatever
governed the tick, so it binds on the blocked path too. Above the cap, throttle
goes to zero and the brake goes full on; `SPEED_CAPPED` is recorded only when the
projection actually changed the vector. Pinned by
`test_the_command_issued_in_halt_actually_brakes` in
[`test_full_pipeline.py`](../tests/integration/test_full_pipeline.py), which
drives the assembled pipeline into HALT and asserts the deceleration. The
decision record is in [`PENDING.md`](PENDING.md) under P2.1. The finding below
stands as written — it is what the 1 August run showed.

`FailSafeStateMachine.speed_cap` returns `MetresPerSecond(0.0)` in HALT, and its
docstring is explicit about why: *"a controlled pull-over is a commanded stop,
and reporting 'no cap' there would invert the meaning."*

The vehicle accelerated from 1.0 to 17.2 m/s while in HALT and held that speed
for 99,000 ticks.

The cap reaches no command. In [`arbiter.py:262`](../src/astra/layers/l9_rcm/arbiter.py:262):

```python
if verdict.is_blocking:
    return self._build(tick, self._fallback_values(tick), CommandOrigin.FALLBACK_PID)
if failsafe.speed_cap is not None:
    return self._build(tick, self._clamp(proposal.command.values), CommandOrigin.SPEED_CAPPED)
```

Two separate gaps:

- A **blocked** tick returns before the cap branch is reached. Every tick after
  ~800 was blocked, so the cap was never even consulted.
- The cap branch itself calls `self._clamp`, which confines the vector to the
  actuation space's channel bounds — **the identical call the uncapped
  `PROPOSED` branch makes**. `failsafe.speed_cap` is not read. A command
  recorded as `SPEED_CAPPED` is bit-identical to the one that would have been
  recorded as `PROPOSED`.

The repository's own test is honestly named —
`test_a_fail_safe_cap_is_recorded_in_the_origin` — and asserts recording, not
enforcement. Three docstrings claim more than that:

- `CommandOrigin.SPEED_CAPPED`: *"A command clamped to a fail-safe speed cap by the L8 state machine."*
- `FailSafeState.LIMP`: *"Hard speed cap; lane changes excluded."*
- `FailSafeState.HALT`: *"Controlled pull-over."*

**This is a design question, not a typo.** A speed cap is in m/s; the actuation
space is throttle, brake and steer. Converting one into the other requires
knowing which channel brakes and how hard — exactly the platform knowledge NFR5
keeps out of the core, and exactly the `CommandProjector` seam that
[`WORK_PLAN.md`](WORK_PLAN.md) §6.3 already identifies for the L7a scope
question. The two should be decided together.

Until then, the honest statement is: **the FSM's speed cap is recorded in the
evidence and does not constrain any actuator.**

### F3 — L7a never fires, in either run, and the Trust Index carries no information

Across 200,000 ticks over the two runs, with the vehicle kilometres outside its
lane at 17–19 m/s in HALT, **the Hard Safety Shield (L7a) never vetoed once.**

That is explicable and is not a bug: L7a bounds speed, lateral acceleration and
friction margin, none of which was violated, and it has no notion of lane
position. It is recorded because it is the concrete form of the L7a scope
question in [`WORK_PLAN.md`](WORK_PLAN.md) §6.3 — a state monitor cannot object
to a vehicle whose *state* is unremarkable and whose *position* is 2.9 km wrong.

Separately, the **Trust Index read exactly 1.00 in every window after the first
in both runs** — including the placeholder run, where L6 was simultaneously
vetoing 100% of ticks on the conformal quantile. A signal pinned at its maximum
for 99,000 consecutive ticks carries no information, and one that reads "maximally
typical" while its own gate rejects every proposal is worth understanding before
FB3 wires online requantilisation into it.

### F4 — The state estimate for lateral position is fiction

`mean_estimator_error_m` — the gap between the UKF's `position_y` and the plant's
truth — reached 2.9 × 10⁶ metres in the learned run. In the placeholder run it
tracked the true deviation almost exactly (199.87 m against 199.87 m), meaning
the estimate stayed pinned near zero while the vehicle left: the same defect,
seen from the other side.

This is arithmetically unsurprising: the extractor in `training/closed_loop.py`
publishes only `speed` and `lateral_acceleration`, so `position_y` is never
observed and is dead-reckoned from an unobserved heading. Nothing in the current
wiring consumes it — the fallback reads only speed — so it caused none of the
above. It is recorded because L6 scores against the **full** state estimate and
its covariance, and because a component added later that reads estimated lateral
position would be reading a number wrong by kilometres, with no indication in
the record that it was.

### F5 — The OOD counter is unbounded

It reached 1,508 by tick 2,000 and kept climbing. There is no ceiling. In HALT
this is harmless because HALT is terminal, but the counter is written into every
`FailSafeSnapshot`, and the enum's claim that recovery is *"bidirectional and
automatic without a restart"* holds only for excursions short enough that the
counter can be walked back down.

### F6 — With the cold path engaged, the vehicle stops instead

`benchmarks/soak.py --cold-path {open,tunnel}` builds a `ColdPathContext` and
turns L9's knowledge base on. `open` uses the signature components the demo and
the tunnel test call open road; `tunnel` uses the ones they call a tunnel, a
context no seed profile covers.

**The two runs are numerically identical**, which is the first result: the
context made no difference at all.

| | Cold path off | Cold path on (either context) |
|---|---|---|
| Lane deviation at tick 100,000 | 2,883 m and rising | 0.328 m, unchanging |
| Speed, steady state | 17.2 m/s | **0.000 m/s from ~tick 400** |
| Veto rate | 100% | 100% |
| What governed | `FALLBACK_PID` | `EXPLORATION_BOUNDED`, 99,999 of 100,000 ticks |
| Arbitration outcome | none ran | `SAFE_EXPLORATION`, 100,000 of 100,000 |

Three findings sit inside that table.

**F6a — Exploration engages permanently, because a decelerating vehicle leaves
every profile's ball and no profile covers a slow one.** `SAFE_EXPLORATION` was
the outcome of all 100,000 arbitrations in *both* contexts, with no candidate
named.

The knowledge base itself is working. With
`SearchWeights(similarity=0.4, validation=0.3, history=0.2, risk=0.1)`, seed
covariances of `0.05·I` and τ = 0.70, the fixed terms contribute 0.468 for a
valid in-class profile, so admissibility needs a Mahalanobis distance below 0.72
— a real but not unreasonable ball, and `highway_clear` sits inside it whenever
the vehicle is actually driving at highway speed:

| Signature (open-road components) | Best candidate | Distance | `T(c)` | Admissible at τ = 0.70 |
|---|---|---|---|---|
| Exactly the highway centroid | `highway_clear` | 0.000 | 0.868 | yes |
| `test_tunnel_scenario.py`'s constant 0.78 × limit | `highway_clear` | 0.155 | 0.814 | **yes** |
| At the legal limit | `highway_clear` | 0.903 | 0.678 | no |
| The plant's reference speed, 13.0 m/s | `highway_clear` | 1.838 | 0.608 | no |
| Cruising at 10.3 m/s | `highway_clear` | 2.203 | 0.592 | no |
| Stopped | `highway_clear` | 3.580 | 0.555 | no |

The second row is why `test_a_drive_that_never_enters_the_tunnel_never_explores`
passes: that test drives a mock vehicle at a *constant* 0.78 × the legal limit,
which is 0.155 Mahalanobis units from the highway centroid. The tunnel scenario
is sound and its control test is doing its job.

The soak differs in one respect that turns out to be decisive: its vehicle is
**decelerating**. `ego_speed` is one of the five signature components, so as the
speed falls the signature walks out of the highway ball (1.84 units at the
plant's own reference speed, 3.58 when stopped) and there is no profile for a
slow vehicle to fall into. Declaring an *urban* context instead — which matches
the plant's 13 m/s far better — produces five `SHADOW_EXECUTION` arbitrations
and five `PROPOSED` commands before the vehicle slows out of that ball too.

So this is not a threshold that needs lowering. It is the common cause above,
seen from the knowledge base's side.

**F6b — In exploration, a vetoed proposal is issued.** 99,808 of the 100,000
ticks (99.8%) had a blocking aggregate verdict *and* issued the proposal, because
[`arbiter.py:257`](../src/astra/layers/l9_rcm/arbiter.py:257) tests the
exploration envelope **before** it tests the verdict:

```python
if self._exploration_space is not None:
    return self._build(tick, self._clamp(...), CommandOrigin.EXPLORATION_BOUNDED)
if verdict.is_blocking:
    return self._build(tick, self._fallback_values(tick), CommandOrigin.FALLBACK_PID)
```

The exploration module's own docstring opens with *"The answer here is not to
relax the gates. It is to shrink the envelope."* As ordered, the envelope
**replaces** the gates rather than narrowing what they permit.

Strictly, SI-3 is not violated: it governs verdict *aggregation*, and the
aggregate verdict is still a VETO — it is issuance that ignores it. But combined
with F6a, the practical consequence is that the three structurally independent
gates have no authority over the actuators in almost every context. The soak
counts these ticks and does not gate on them, because whether that ordering is
correct is a design decision, not a measurement.

**F6c — The stop is three reasonable decisions composing badly.** None of the
following is wrong on its own:

- the exploration envelope halves the throttle channel's upper bound;
- it deliberately leaves braking at **full** authority, because *"taking away its
  ability to stop would make the safety envelope less safe"*;
- the proposer emits throttle ≈ 0.54 with brake ≈ 0.49.

On a plant with 8.0 m/s² of braking against 3.0 m/s² of acceleration, the clamped
command `(0.5, 0.493, 0.0)` is a net deceleration of 2.45 m/s². The vehicle
decelerates to rest, the state stops changing, the proposer keeps emitting the
same command, and the system sits still for 99,600 ticks — a stable fixed point
of exactly the kind the exploration module's first paragraph rejects: *"Every
runtime-assurance system in the survey degrades to a stop… useless on a
motorway."*

**The instrument was wrong too.** The first cold-path run reported `STABLE`: a
stopped vehicle has no lane drift, no veto-rate movement and flat memory, so
every criterion passed it. A ninth criterion — *the vehicle is still moving at
the end* — has been added, with two tests, one of which is the control that
distinguishes a transient crawl from a halt. The runs above are scored with it.

---

## What this run does not license

- **No gate accuracy figure.** The plant, the twin and the calibration corpus
  descend from one set of kinematic equations. There is still no false-positive
  or false-negative rate and there cannot be one before Phase 7.
- **No claim that bounded safe exploration cannot work.** What F6 measures is
  bounded safe exploration *at the shipped simulation operating point*, where it
  is engaged permanently because no profile is reachable (F6a). Whether it
  behaves as intended when it engages only in the contexts it was meant for is
  untested, and cannot be tested until τ, the search weights or the seed
  covariances are re-tuned.
- **No claim that any of this is a coding error.** Every behaviour above follows
  from code that does what its docstring says locally. What the run measures is
  what those decisions compose into over 100,000 ticks, which is the one thing
  no unit test was ever going to show.
- **No claim that the learned policy is at fault.** It was trained on 500-step
  episodes with resets, and nothing in its training required holding a lane for
  100,000 continuous steps — but the placeholder, which learned nothing, fails
  the same way sooner. The proposer is not the variable.
- **The latency figures are software, on WSL2, under CPython.** They are not the
  1.25 µs analytical hardware bound and must never be quoted as it.

---

## Reproducing it

```bash
uv run python -m benchmarks.soak --ticks 100000 --window 1000
```

Two-minute versions that reach the same two verdicts:

```bash
uv run python -m benchmarks.soak --ticks 2000 --window 200 --output var/soak/smoke
uv run python -m benchmarks.soak --ticks 2000 --window 200 --cold-path open --output var/soak/smoke-cold
```

The harness exits non-zero when a criterion fails, writes one JSON row per
window to `windows.jsonl` as the run proceeds, and holds its own memory flat so
that the resident-set series describes the pipeline rather than the measurement.
Its criteria and their thresholds are in the module docstring; oscillation is
reported as a direction-change count and deliberately not gated, because no
threshold for it has been earned by a measurement yet.

---

## What follows from this

In the order the findings warrant, not the order the plan had.

The policy is now fixed and the suite asserts it, so the list below is what
remains. Item 1 is the only architectural one.

1. **Break the veto latch** (F1a). This is the finding, and it wants an ADR
   rather than a patch. The options are not equivalent:
   - give the fallback lateral authority, so `a_current` reflects an attempt to
     hold the lane rather than an absence of steering;
   - compare the proposal against the *proposer's own* previous proposal rather
     than the achieved state, so the gate measures the jerk of a trajectory the
     vehicle would actually follow;
   - allow a ratcheted exception — a vetoed proposal within some multiple of the
     bound may be issued once, to let the ramp start.

   The first is the most honest and the most work. The second changes what the
   gate means. The third is the smallest and the most dangerous. Tuning the
   proposer is *not* on this list: it has been measured and it does not work.
2. **Decide whether exploration out-ranks a VETO** (F6b). Independent of
   everything else: 99.8% of ticks issued a proposal under a blocking verdict.
   One conversation, and until it is had, *"every proposed command is validated
   three ways"* is not true of the configuration this repository ships.
   Whichever way it goes, the exploration docstring and the ordering in
   `issue()` have to be made to agree.
3. **Settle the speed-cap question** (F2) with the L7a scope question from §6.3,
   since both need the same `CommandProjector` seam. Until then, correct the
   three docstrings that claim an enforcement that does not exist.
4. **Match the training step to the tick period** (F1b), then regenerate the
   twin, the corpus and the policy in that order. Cheap to do, expensive to do
   *later*, and every measurement taken before it is off by 2.5× in time.
5. **Then** Phase 3's feedback loops.

**None of the findings depended on the broken policy** except the specific
numbers. F1/F1a, F2 (the speed cap reaches no actuator), F3 (L7a fired once in
half a million ticks), F4 (`position_y` is dead-reckoned and unobserved), F5 (the
OOD counter is unbounded), F6a and F6b all reproduce with a policy that drives.
