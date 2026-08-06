# ASTRA — Pending work, by priority

**Prepared** 2 August 2026
**Baseline** `833ce4d` plus the uncommitted soak work
**Companion documents** [`SOAK_REPORT.md`](SOAK_REPORT.md) for the evidence behind
every finding cited here; [`WORK_PLAN.md`](WORK_PLAN.md) for the phase structure
this re-orders.

---

## How to read this

Ordered by **what unblocks the most work per day spent**, not by phase number.
The work plan's phase order was written before the first long run; that run
closed one phase and re-ordered four others.

Estimates are person-days for one engineer at this repository's standard — full
annotations, Google docstrings, a test per behaviour, 95% coverage floor. They
are 2–3× what the same change would cost in an ordinary codebase, deliberately.

| Priority | Meaning |
|---|---|
| **P0** | Blocks Phase 3 and makes Phase 4 meaningless. Nothing downstream is worth doing first |
| **P1** | Cheap, and gets more expensive the longer it waits |
| **P2** | Required for the safety argument. Not blocking |
| **P3** | Unblocked only once P0 is resolved |
| **P4** | Independent. Parallelisable across people |
| **P5** | Hardware-gated. Highest single value in the project |

**Current state, 2 August 2026 (evening):** ten layers built, 12 import contracts
kept, **2,618 tests**, 97.89% coverage, gate green. One of four feedback loops
wired. **The closed loop is stable over 100,000 ticks on all ten soak criteria**,
at a timestep that now matches the control period — lane deviation 0.0331 m, veto
rate 3×10⁻⁵, the proposer driving 99,997 of 100,000 ticks unmodified, the
fail-safe machine never leaving NOMINAL.

**All of P0 is closed. All of P1 is closed except the deferred paper
conversation.** What remains starts at P2.

Roughly **85% built, 15% validated** — the second number moved because the loop
demonstrably runs, not because anything non-self-referential was measured. The
plant, the twin and the corpus still share one set of kinematic equations, so no
false-positive or false-negative rate exists and none can before Phase 7.

---

# P0 — Blocking

## P0.0 — Lateral position must be observed — DONE, 2 Aug 2026

**The finding that subsumes P0.2 and P0.3.** `position_y` was measured by
nothing. The extractor published speed and lateral acceleration only, so the UKF
dead-reckoned lateral position from a heading that is also unobserved.

Measured over 2,000 ticks: the estimate sat at zero while the plant drifted to
**2.07 m off a lane 1.75 m wide**, and the estimator error tracked the true
deviation to three decimals because the estimate never moved. **The veto rate was
0.00 and the Trust Index exactly 1.00 the whole way out.** No gate in Core-B
measures where the vehicle is — L7a bounds speed, lateral acceleration and
friction margin; L7b bounds jerk and twin divergence; L6 scores proposal against
twin. A lane departure is invisible to all three, and the proposer, reading the
same estimate, believed it was centred.

Every failure the soak had reported was downstream of it.

**Fixed** by publishing a lateral-position measurement at σ = 0.1 m — lane
detection from a forward camera is where a real vehicle gets this, and the
`MeasurementExtractor` seam is what it exists for. Corpus regenerated under the
same observability.

**Result, 100,000 ticks:** lane deviation **0.0003 m** and flat, veto rate
**0.00%**, speed held at 13.03 m/s, estimator error 0.0000, memory +0.0 MiB,
p99 latency ×0.91, 100,000 of 100,000 ticks issued. With P0.4 also fixed, **all
ten criteria pass** — the first clean 100,000-tick run in the project.

## ~~P0.2 / P0.3~~ — dissolved by P0.0

Both were mechanisms that made a departure *permanent*. With the departure gone
they no longer occur: the closed loop runs at a 0.00% veto rate, so there is no
latch to break and no statistical veto to answer. ADR-0017's rate limiter still
earns its place — it handles the startup transient, 21 ticks of it — and
ADR-0016 stands on its own merits. **Neither should be re-opened without first
re-establishing that the departure has returned.**

## ~~P0.4 — The fail-safe machine latches on a startup transient~~ — DONE, 2 Aug 2026

**The OOD thresholds were durations wearing counts, and nobody had converted
them.** At 20 Hz, 5 / 12 / 20 is 0.25 s / 0.6 s / **1.0 s** — so the system
declared a terminal, unrecoverable pull-over after one second of sustained
refusal, and a legitimate recovery from 1 m off the lane centre takes about
that long, because L7b permits 0.4 m/s² of lateral acceleration per tick and
ADR-0017 rate-limits the approach across ~21 of them.

Set as durations instead — 0.5 s / 1.5 s / 5.0 s, i.e. **10 / 30 / 100** — with
the reasoning recorded in `simulation.toml` and the duration framing added to
`FailSafeSettings`. Configuration, so a safety engineer's call under convention
5. `development.toml` keeps its deliberately twitchy values and now says why they
do not generalise.

**Result: all ten criteria pass. STABLE over 100,000 ticks**, the first clean run
in the project's history. `PROPOSED` on 99,967 ticks, `RATE_LIMITED` on 21,
`SPEED_CAPPED` on 12, ending in NOMINAL — the machine degraded during startup and
recovered, which is the graduated response doing what its docstring always
claimed.

**Still open from this:** a proposer demanding impossible jerk indefinitely would
be rate-limited indefinitely and take proportionally longer to escalate. L7a
still bounds the achieved state, but sustained rate limiting deserves its own
diagnostic.

<details><summary>Original entry, kept for the reasoning</summary>

The one criterion still failing, and now the only thing between this run and a
clean 100,000 ticks.

The plant resets up to 1 m off the lane centre. The policy corrects, the
correction exceeds L7b's jerk bound for about twenty ticks while ADR-0017's rate
limiter walks it in, and those **21 vetoes push the out-of-distribution counter
past `ood_threshold_halt = 20`**. HALT is terminal by design — `reset()` is its
only exit, because leaving a pull-over is meant to be an engineering decision.

So the machine spends **99,000 of 100,000 ticks in its most severe state**,
reporting a commanded stop of 0.0 m/s, while the vehicle drives perfectly at
13.03 m/s. Both halves are individually defensible; the composition is not.

Three candidate answers:

1. **Raise `ood_threshold_halt`** — cheapest, and it only moves the transient's
   headroom rather than distinguishing a transient from a fault.
2. **Decay the counter, or require the threshold to be crossed by sustained
   rather than cumulative vetoes** — a rate rather than a count. This is the one
   I would take: it is what the counter is *for*, and it makes recovery from
   DEGRADED and LIMP mean what the enum docstring already claims.
3. **Do not count a veto that the rate limiter successfully answered** — the
   tightest fit to this case and the most special-purpose.

Note it also makes F2 concrete: for 99,000 ticks the FSM reported a 0.0 m/s cap
that reached no actuator.

</details>

## ~~P0.1 — Decide whether bounded safe exploration out-ranks a VETO~~ — DONE, 2 Aug 2026

**Resolved by [ADR-0016](adr/0016-exploration-may-not-override-a-deterministic-veto.md).**
A gate with no basis to judge now returns `Verdict.ABSTAIN`; `Verdict.merge`
drops abstentions before applying the fail-closed rule, so a set that is empty
*or entirely abstentions* is still a VETO; and `issue()` tests the verdict before
the exploration envelope. **Commands issued under a blocking verdict: 99,808 per
100,000 ticks → zero.** SI-3 holds with no exception and `issue()` lost a branch.
Costs: the verdict is no longer binary (SI-3 and SI-4 statements amended,
recorded in the ADR), `AUDIT_SCHEMA_VERSION` 1 → 2, and a command an uncalibrated
L6 used to block is now issued when L7a and L7b pass. Gate green: 12 contracts
kept, 2,596 tests, 97.97%.

**It also removed the accident that was masking P0.2** — exploration was the one
path by which a vetoed proposal reached the actuators, and it was holding the
vehicle in its lane. The departure now reasserts in cold-path runs, as the ADR
predicted. Read P0.2 next.

<details><summary>Original entry, kept for the reasoning</summary>

**Finding F6b.** One conversation, and it must come before P0.2 because it
defines the design space that P0.2 chooses from.

**Evidence.** Over 100,000 ticks with the cold path engaged, 99,808 ticks
(99.8%) had a blocking aggregate verdict *and* issued the proposer's command.
[`arbiter.py:258`](../src/astra/layers/l9_rcm/arbiter.py:258) tests the
exploration envelope **before**
[`arbiter.py:262`](../src/astra/layers/l9_rcm/arbiter.py:262) tests the verdict:

```python
if self._exploration_space is not None:  # 258 — wins
    return self._build(
        tick, self._clamp(proposal.command.values), CommandOrigin.EXPLORATION_BOUNDED
    )
if verdict.is_blocking:  # 262 — never reached in exploration
    return self._build(tick, self._fallback_values(tick), CommandOrigin.FALLBACK_PID)
```

`exploration.py`'s module docstring opens with *"The answer here is not to relax
the gates. It is to shrink the envelope."* As ordered, the envelope **replaces**
the gates.

**Strictly, SI-3 is not violated** — it governs verdict *aggregation*, and the
aggregate verdict is still a VETO. It is issuance that ignores it. But the
property a reader would assume — a vetoed command is not sent to the actuators —
does not hold.

**The two defensible answers.**

1. *The ordering is correct.* In exploration no profile matches, so the gates are
   scoring against a calibration that does not describe the situation, and the
   envelope is the safety argument. Then: say so in `exploration.py`, in
   `arbiter.issue`'s docstring, and in the README sentence *"Every proposed
   command is validated three ways"* — which is currently false for the shipped
   configuration.
2. *The ordering is wrong.* A VETO is unconditional; exploration narrows what may
   be proposed, not whether a veto binds. Then: swap the branches, and accept
   that P0.2 gets harder — exploration stops being an escape from the latch.

**Exit:** an ADR recording the decision; code and all three docstrings agreeing;
a test asserting whichever property was chosen.
**Estimate:** 1–2 days including the ADR.
**Blocks:** P0.2.

</details>

## P0.2 — Break the veto latch — PARTLY DONE, 2 Aug 2026

**The jerk latch is broken by [ADR-0017](adr/0017-rate-limited-approach-to-a-jerk-vetoed-proposal.md).**
A proposal refused solely because it changed lateral acceleration too fast now
yields the largest step that bound permits, in the direction asked for, projected
through the new `CommandProjector` seam. The veto is not overridden — the
proposal is not issued; a different command is, admissible under the refusing
bound by construction. Verified by unit tests including convergence over repeated
ticks, and live: 347 `RATE_LIMITED` ticks in a 20,000-tick soak.

**It did not stop the departure, because there are two latches.** From tick
~2,000 the statistical and physical gates veto on *every* tick simultaneously
(2,000 and 2,000 in a 2,000-tick window), and any non-rate objection correctly
cancels the ratchet. Two things follow, both open:

- **P0.3 (new).** Once the vehicle is outside the region the corpus covers, L6
  vetoes every correction that would bring it back — the same shape of latch at a
  different gate. No bounded approach answers a statistical objection. Widening
  the eligible reason set would be ADR-0016 undone by the back door; it needs its
  own decision.
- **The two gates are not firing independently.** L6 scores
  `dist(proposed, twin_predicted) / sigma`; L7b's divergence term is
  `|implied − twin_implied|`. Both measure proposal-against-twin. This is the
  documented common-cause weakness appearing in a measurement rather than a
  caveat, and it bears on the "three structurally independent gates" claim.

<details><summary>Original entry, kept for the reasoning</summary>

**Finding F1a. This is the finding.** It blocks all three remaining feedback
loops and makes the Phase 4 ablation meaningless — ablating a latched system
measures the latch.

**The mechanism, exactly.**

1. `ProportionalFallbackController.command()`
   ([`fallback.py:154`](../src/astra/layers/l9_rcm/fallback.py:154)) returns the
   speed effort on its own channel and **zero on every other**, by explicit
   design. The plant's lateral acceleration goes to zero and stays there.
2. L7b's bound is `|a_proposed − a_current| / dt ≤ 8.0 m/s³`
   ([`checker.py:179`](../src/astra/layers/l7b_physical/checker.py:179)), and
   `a_current` is read from the state estimate
   ([`checker.py:174`](../src/astra/layers/l7b_physical/checker.py:174)) — which
   now reflects the **fallback's** behaviour, not the proposer's.
3. At `dt = 0.05 s`, the largest lateral acceleration admissible from rest is
   therefore **0.4 m/s²**. The vehicle is by then far off-lane and every useful
   correction exceeds it.
4. The proposal is vetoed, the fallback governs again, and step 1 re-establishes
   the condition that made the veto inevitable.

**The escape path is closed by construction.** Leaving requires ramping lateral
acceleration in ≤0.4 m/s² steps, but a proposal only moves `a_current` if it is
**executed**, and it is not executed while vetoed. No proposer, however well
trained, can climb a ramp it is never allowed to stand on.

**Confirmed across three policies** — the original stopping checkpoint, the
speed-holding one (36% initial veto rate), and one trained with an explicit jerk
penalty (97%). All reach the identical terminal state: 100% veto on
`PHYSICAL:LATERAL_JERK_EXCEEDS_LIMIT`, FSM in HALT, `FALLBACK_PID` governing,
unbounded lane departure at the fallback's speed.

**The design question, stated sharply:** while the fallback is governing, L7b
judges the proposer against a state the proposer did not create. The jerk it
measures is that of a transition from the fallback's trajectory to the
proposer's — a transition the vehicle would never actually make.

**Three non-equivalent options.**

| Option | Days | Consequence |
|---|---|---|
| **A. Give the fallback lateral authority** so `a_current` reflects an attempt to hold the lane rather than an absence of steering | 4–8 | Most honest, most work. The fallback stops being "the boring one" and needs its own safety argument. It also requires knowing which channel steers — the `CommandProjector` seam of P2.1 |
| **B. Compare the proposal against the proposer's own previous proposal** rather than the achieved state | 2–4 | Changes what the gate means. L7b stops being a check on what the *vehicle* would experience and becomes a check on proposer smoothness. The gate-independence argument must be re-made |
| **C. A ratcheted single-tick exception** — a vetoed proposal within some multiple of the bound may be issued once, to let the ramp start | 1–2 | Smallest and most dangerous. A deliberate hole in an unconditional veto, and it will be the first thing an assessor finds |

**Do not tune the proposer.** It has been measured and it does not work:

- An explicit jerk term in the training objective, charging
  `w × max(0, jerk − 8.0)/8.0` per step from the plant's own lateral
  acceleration, was tried at two weights. At `w = 1.0` it swamps a task reward
  capping at 2.0 and training collapses (return 63, collision rate 1.0). At
  `w = 0.1` training is healthy (return 897, deviation 0.114 m) and the closed
  loop is **worse** — 97% veto in the first thousand ticks against 36% without.
  Reverted; the reasoning is preserved in `EnvironmentSpec.action_rate_weight`.
- The existing `action_rate_weight` proxy is **inert** with respect to the bound:
  at the gate's boundary a permitted step is a normalised action change of
  0.0057, which the term charges `6.0 × 0.0057² = 2×10⁻⁴` against a centring
  reward of 1.0. The same shape of finding as the EWC λ already on record.

**Exit:** an ADR selecting an option with its reasoning; the fix implemented; a
100k soak in which the vehicle is still in its lane at the end; the
`lane deviation does not drift` criterion passing in `benchmarks/soak.py`.
**Estimate:** 1 day for the ADR, then 1–8 days depending on the option.
**Blocked by:** P0.1. **Blocks:** P3 entirely.

</details>

# P1 — Cheap now, expensive later

## ~~P1.1 — Match the training step to the tick period~~ — DONE, 2 Aug 2026

Corrected to 0.05. **The cascade was smaller than feared:** the twin is
self-labelling from kinematics and takes no timestep, and the corpus generator
drives its own sweep at the pipeline rate, so only the plant and the policy were
affected.

**Correcting it exposed what the error had been hiding.** With the plant at 0.02
and L7b computing jerk over 0.05, the gate was 2.5× more permissive than
configured and the policy's steering fitted inside the slack. Corrected, the same
policy was vetoed on 99.7% of ticks and parked 3.14 m outside its lane. The
proposer had never been trained against the bound it is judged by, and the
previous stable run depended on the mismatch.

That retires ADR-0017's *"do not tune the proposer"* conclusion, which was
measured under the error. The fix was not a new objective term — one was tried
and failed — but the **existing** one at a derived scale. Lateral acceleration is
linear in steering, so a penalty on squared change in normalised steer already
*is* a penalty on squared change in lateral acceleration. At 6.0, a step at
exactly L7b's limit cost 2×10⁻⁴ against a maximum per-step reward of 2.0. Set so
that step costs 5% of the reward instead: `0.05 / 3.265e-5` = **1531**.

Peak lateral jerk across three retrains: **150 → 60 → 16.7 m/s³**.

**Result: all ten criteria pass over 100,000 ticks at the corrected timestep.**
`PROPOSED` on 99,997 ticks, `RATE_LIMITED` on 3, the fail-safe machine never
leaving NOMINAL, lane deviation 0.0331 m, veto rate 0.00%. Better than the run it
replaced, *and* the figures now mean what they say. Corpus regenerated from the
deployed policy afterwards, per trap 9.

<details><summary>Original entry, kept for the reasoning</summary>

**Finding F1b.** `EnvironmentSpec.step_seconds = 0.02`, and its docstring reads
*"Integration step. Matched to the pipeline's fast rate."* The pipeline's rate is
`fast_rate_hz = 20.0` — **0.05 s**. They have never matched.

`drive_closed_loop` steps the plant once per tick and advances the clock by
`1/fast_rate_hz`, so every run advances 0.02 s of vehicle motion per 0.05 s of
pipeline time.

**Consequences.**

- Every "simulated time" figure on record is 2.5× optimistic. The 100,000-tick
  soak is 5,000 s of pipeline time and 2,000 s of plant motion.
- The policy learns a rate of change per 0.02 s and is judged by a gate computing
  jerk over 0.05 s — which makes the gate 2.5× *more* permissive than training,
  so this is not a cause of the vetoes, but no jerk figure means what it appears
  to.
- The UKF process model, the twin and the corpus all assume the pipeline period.

**Why now:** the fix cascades — twin, then corpus, then policy, in that order
(trap 9) — and every artefact produced before it must be regenerated anyway. Doing
it after Phase 3 means regenerating three feedback loops' worth of evidence too.

**Files:** `training/environment.py`, then `train_twin.py`,
`generate_calibration.py`, `train_policy.py`.
**Exit:** `step_seconds == 1 / fast_rate_hz` asserted by a test; twin, corpus and
policy regenerated; the soak matrix re-run; per-class coverage back in the
94.9–95.1% band.
**Estimate:** 2–3 days including regeneration and re-validation.

</details>

## ~~P1.2 — Correct the three docstrings that claim speed-cap enforcement~~ — DONE, 2 Aug 2026

`CommandOrigin.SPEED_CAPPED`, `FailSafeState.LIMP` and `FailSafeState.HALT` now
say what the code does, with `FailSafeSnapshot.speed_cap` marked *reported, not
enforced* and a pointer to P2.1 for the enforcement question. The README's *"every
proposed command is validated three ways"* was corrected at the same time.

<details><summary>Original entry</summary>

## P1.2 — Correct the three docstrings that claim speed-cap enforcement

The documentation half of finding F2, separable from the implementation half
(P2.1) and worth an hour on its own.

`FailSafeStateMachine.speed_cap` returns `MetresPerSecond(0.0)` in HALT. The
vehicle accelerated from 1.0 to 17.2 m/s while in HALT and held it for 99,000
ticks. The cap reaches no command:

- a **blocked** tick returns at [`arbiter.py:262`](../src/astra/layers/l9_rcm/arbiter.py:262),
  before the cap branch at line 264 is reached;
- the cap branch itself calls `self._clamp`, which confines the vector to the
  actuation space's channel bounds — **the identical call the uncapped
  `PROPOSED` branch makes**. `failsafe.speed_cap` is never read.

The repository's own test is honestly named
(`test_a_fail_safe_cap_is_recorded_in_the_origin`) and asserts recording. Three
docstrings claim more:

| Symbol | Claim |
|---|---|
| `CommandOrigin.SPEED_CAPPED` | *"A command clamped to a fail-safe speed cap by the L8 state machine."* |
| `FailSafeState.LIMP` | *"Hard speed cap; lane changes excluded."* |
| `FailSafeState.HALT` | *"Controlled pull-over."* |

**Exit:** each docstring states what the code does, with a pointer to P2.1 for
the enforcement question.
**Estimate:** 0.5 days.

</details>

## ~~P1.3 — Evidence pack~~ — DONE, 2 Aug 2026

[`EVIDENCE.md`](EVIDENCE.md): 17 measured rows, 3 controlled comparisons, 12
things explicitly not demonstrated. Every row carries the command that
reproduces it. Building it found four stale claims, which is what it is for.

<details><summary>Original entry</summary>

## P1.3 — Evidence pack (work plan §2.2)

Now higher value than when the plan was written: there are four 100,000-tick
runs, a controlled 2×2 training comparison and seven findings to capture while
the context is fresh.

**Do:** build `docs/EVIDENCE.md` as a living table — one row per claim the
project makes, with the run that produced it, the command to reproduce, and the
date. Add a section for claims explicitly **not** demonstrated, which is now a
long and well-evidenced list.

**Exit:** every number in `README.md` and both status documents traces to a row.
**Estimate:** 1–2 days.

</details>

## ~~P1.4 — Documentation sync~~ — DONE, 2 Aug 2026

README's test count, the "1.98 ms full ten-layer tick" figure and the 400-tick
closed-loop numbers all corrected. `PROJECT_STATE_AND_ROADMAP.md` summary row
updated with a banner saying to read the rest as history — its per-phase figures
are correct for the phase they describe. `1144_..._Sushanth_status.md` marked
SUPERSEDED, naming the four defects that invalidate its figures.

<details><summary>Original entry</summary>

## P1.4 — Documentation sync (work plan §1.3)

`docs/PROJECT_STATE_AND_ROADMAP.md` reports counts that have moved. Mark
`docs/1144_2026-07-31_Sushanth_status.md` as superseded by the 20:30 ledger.

**Exit:** contract count, certification-field count and layer statuses match
reality.
**Estimate:** 0.5–1 day.

</details>

## ~~P1.5 — Close assumption A-8~~ — DONE, 2 Aug 2026

`carla==0.9.16` installs and imports on **CPython 3.12.13**/Linux, as a single
package with no dependency tree, exposing every symbol the adapter design needs.
A `Client` constructs and `get_server_version()` raises `RuntimeError` with no
server listening — the correct failure, and confirmation the client is live
rather than inert. Run in a throwaway venv so nothing reached the project
environment or the lockfile.

**The interpreter risk is closed** — no sidecar, no IPC hop, no unofficial
binary, and the 10 ms budget is untouched. What remains is the *connection* half,
which needs a running simulator and therefore the Linux GPU host of P5: a
hardware dependency, not a compatibility one. Recorded as E-17 and in
[`ASSUMPTIONS.md`](ASSUMPTIONS.md) A-8.

<details><summary>Original entry</summary>

## P1.5 — Close assumption A-8 (work plan §7.1)

Ten minutes, no GPU, no hardware. Unverified since Phase 2 and the entire CARLA
adapter design rests on it.

```bash
pip install carla==0.9.16
python -c "import carla; c = carla.Client('localhost', 2000); c.set_timeout(10.0); print(c.get_server_version())"
```

The install half runs on Colab free. **Do the install half now**; the connect
half waits for P5.
**Estimate:** 0.5 days.

</details>

## P1.6 — The paper's validation section (work plan §1.1) — *deferred by instruction*

**The only calendar-critical item in the project, and the only one that gets
harder purely by waiting.** §5 of the submitted survey describes a 21-minute
CARLA drive across seven phases with specific observations (47 evidence tuples,
gates firing in a stated order). None of it was run.

Correction, withdrawal and revised submission are routine *before* a reviewer
attempts to reproduce the work, and difficult after. Raise it with Dr. Chaitra as
supervising author.

Also pending from §1.2, independent of the above: Table 1's unmarked `1.25 µs`
(an analytical AbsInt aiT budget for RTL that does not exist, sitting in a WCRT
column beside measured figures), Table 1's `D(D)` presented as an awarded ASIL,
the layer numbering conflict (§4.5.2 calls the ICP gate "Layer 5", Figure 1 calls
it "Layer 6", three components are labelled "Layer 6"),
`\cite{altman1999}` attached to PPO instead of Schulman,
`\cite{kirkpatrick2017}` doing double duty for EWC and the PINN, and two uncited
references.

**Status: deferred at your instruction.** Listed because deferring it is a
decision with a cost, and the cost accrues on a calendar rather than a backlog.
**Estimate:** 0.5 days to prepare; the conversation is not dev time.

---

# P2 — Required for the safety argument

## ~~P2.1 — The `CommandProjector` seam~~ — DONE, 2 Aug 2026

Both halves closed. Finding F2 — *the fail-safe speed cap is recorded and never
enforced* — is fixed, and the exit criterion the original entry named, *"a test
that a command issued in HALT decelerates the vehicle"*, now exists and passes.

### What F2 actually was

Every layer was individually correct and the composition was not. L8 computed a
cap, wrote it into the evidence and reported it to L9. L9 wrote `SPEED_CAPPED`
into the issued command's origin. **Nobody ever changed a number in the command
vector.** A 100,000-tick run sat in HALT — a commanded stop — holding 17.2 m/s,
and every audit row agreed it had been capped. A label had been standing in for
an actuation for the entire life of the pipeline.

### Decisions taken

**Decision 1 — how a cap in m/s becomes a command in throttle/brake/steer.**

| Option | Benefit | Drawback | |
|---|---|---|---|
| **A. Extend `CommandProjector` with `with_speed_cap(values, *, current_speed, cap)`, implemented by the automotive adapter** | The one existing seam already carries platform knowledge out of the core; L9 keeps saying "cap the speed" and stays ignorant of which channel brakes. NFR5 survives untouched | Grows a port that was introduced for something else (ADR-0017's rate limiter) | **chosen** |
| B. Let L9 index the brake channel directly | Fewest lines | L9 becomes a road-vehicle component. NFR5's domain-independence claim dies in the one layer that has actuation authority (SI-7) | rejected |
| C. Have L8 emit a command rather than a cap | The layer that decides the posture also expresses it | Breaks SI-7 outright: L8 gains actuation authority, and the invariant that L9 is the *sole* issuer is the load-bearing one | rejected |

**Decision 2 — full braking or proportional.** Full. Proportional needs a gain, a
gain is a tuning parameter, and a tuning parameter in the fail-safe path is a
thing that can be set wrong. The FSM has already decided the situation warrants
a cap; the response does not need to be gentle, it needs to be right.

**Decision 3 — brake, or merely withdraw throttle.** Brake. Withdrawing throttle
is *coasting*, and this plant has no drag, so a coasting vehicle in HALT never
stops — which is precisely the 17.2 m/s observed. Pinned by
`test_the_cap_brakes_rather_than_merely_coasting`.

**Decision 4 — where in `issue()` the cap applies.**

| Option | Benefit | Drawback | |
|---|---|---|---|
| **A. Restructure into `_govern()` then `_speed_capped()`, applying the cap *last* to whatever governed** | The cap binds on every path — proposed, rate-limited, fallback, exploring. Nothing can route around it | Requires threading `FastStateEstimate` through `issue()` and its port | **chosen** |
| B. Plumb the cap into the fallback's `target_speed` | Reuses the controller already there | Amends the fallback's written contract that *"it does not take the FSM posture"* — for no gain, since A reaches the same vehicles without touching it | rejected |
| C. Leave it as a fourth branch beside the others | Smallest diff | Unreachable in HALT: blocked ticks return the fallback first, so the branch that mattered most would never run. This *is* the original bug | rejected |

**Decision 5 — when to claim `SPEED_CAPPED`.** Only when the projection actually
changed the vector. A cap the vehicle is already within changes nothing, and an
origin that says otherwise is the same class of defect as F2 itself: evidence
describing an intervention that did not occur.

### Tests

Fourteen in a new `tests/unit/test_command_projector.py` — the adapter had *no*
direct tests, having been added with ADR-0017 and exercised only through a stub.
Five in `test_l9_arbiter.py` for the arbiter's side, including the cap binding on
blocked and exploring ticks. Three in `test_full_pipeline.py` for the wiring,
which is where the defect actually lived: a sustained refusal walks the posture
to HALT, the issued command brakes, and a nominal drive labels nothing capped.

### Results

Gate green — 2,639 passed, 97.95 % coverage, ruff + mypy --strict +
import-linter clean. A 100,000-tick soak still passes all ten criteria
(`var/soak/p21b-100k`): deviation 0.0290 → 0.0298 m, p99 ×0.59, RSS +0.2 MiB.

**Honest limitation:** the soak does not exercise this path. Its FSM stays in
NOMINAL for all 100,000 ticks, so there is never a cap to enforce — which is the
correct outcome for a healthy drive, and the reason the integration test provokes
HALT deliberately rather than waiting for one. Enforcement under a *fault* rather
than a deliberate provocation stays open until P4.2's fault injection.

### The L7a half, decided earlier the same day

The shield gained a fourth bound, `|position_y| <= corridor_half_width`, after
six options were compared. It stays *reactive* — a predictive L7a would share
`control_effectiveness` with L7b, so one wrong platform constant would fail both
gates together, and its independence comes precisely from depending on nothing
but measured state and configured bounds. A corridor rather than a lane, so NFR5
survives.

Pinned limitation: the bound reads the *estimate*, so it refuses a departure the
filter knows about and is blind to one it does not. Had it existed before lateral
position was observable it would have passed every tick.

<details><summary>Original entry</summary>

## P2.1 — The `CommandProjector` seam: speed-cap enforcement and the L7a scope question

Finding F2's implementation half and work plan §6.3, which need the same seam and
should be decided together.

**Why they are one problem.** A speed cap is in m/s; the actuation space is
throttle, brake and steer. Converting one into the other requires knowing which
channel brakes and how hard — exactly the platform knowledge NFR5 keeps out of
the core. The same is true of L7a: `shield.py:166` is
`del proposal  # attribution only; the bounds read the state`, so the Hard Safety
Shield does not evaluate the command it is given. It is a state monitor, not a
command gate.

**Finding F3 is the evidence.** Across ~500,000 ticks, with the vehicle
kilometres outside its lane at 17 m/s in HALT, **L7a vetoed once.** A state
monitor cannot object to a vehicle whose *state* is unremarkable and whose
*position* is 2.9 km wrong.

**Two defensible answers for L7a**, from the work plan, now with evidence behind
them:

1. **Reactive by design**, with predictive admissibility owned by L7b. Then fix
   the docstring at line 146 (which claims the proposal is "carried into the
   verdict for attribution" — `GateVerdict` has no field for it) and the README
   sentence *"Every proposed command is validated three ways."*
2. **It should be predictive.** Then it needs its own crude projection — **not
   the PINN**, which would collapse its independence from L5 and L7b — plus the
   `CommandProjector` seam supplied by the adapter.

**Exit:** an ADR covering both; the seam defined in `astra.ports`; a test that a
command issued in HALT decelerates the vehicle.
**Estimate:** 3–5 days.

</details>

## ~~P2.2 — Test-quality gaps~~ (work plan §2.3) — DONE, 2 Aug 2026

### The frozen-install half — done

Both checks already existed **in CI**, which is another way of saying they ran
*after* the commit that broke them. That is the whole defect: the lockfile went
stale twice and a training run found it both times. So the work was not writing
checks, it was moving them to where the mistake is made.

**Decision 1 — what goes in `make check`.**

| Option | Benefit | Drawback | |
|---|---|---|---|
| **A. `uv lock --check` in `check`; the venv build as a separate `verify-install`** | The lockfile check costs under a second and is the one that caught the historical defects, so it belongs in the gate. The venv build is tens of seconds and belongs where a developer can choose to pay for it | The Makefile's stated principle — *"exactly what CI runs, in the same order"* — is now not quite true | **chosen** |
| B. Both in `check` | Keeps the equivalence claim honest | Roughly doubles gate time for a check that only changes when dependencies do. A gate that slow is a gate people stop running, and then neither check runs | rejected |
| C. Neither in `check`; document them | No cost | Exactly the status quo that let two defects through | rejected |
| D. A pre-commit hook | Runs whether or not anyone remembers | New tooling the repo does not have, for one check that fits in the gate it already has | rejected |

Option A's drawback is real and was not left implicit — the Makefile header now
names `verify-install` as the one CI step `check` deliberately skips, and says
when to run it. A divergence that is written down is a decision; one that is not
is a trap.

**Decision 2 — what `make lockfile` does where `uv` is absent.** Prints
`uv.lock NOT VERIFIED` and continues, rather than failing. `make check RUN=` is a
documented path for environments without `uv` — it is how the gate runs on this
project's WSL2 box — and breaking it to add a check would trade a real capability
for a nominal one. Saying so out loud is the part that matters: a check that can
quietly not run is worse than no check.

**Verified, not assumed.** `make lockfile` resolves 83 packages and passes.
`make verify-install` builds a bare venv with pydantic and nothing else and
imports the kernel and contracts. Adding `import numpy` to
`src/astra/kernel/units.py` makes it fail with `ModuleNotFoundError` and
`make: *** Error 1` — so the target detects the defect it claims to, which is
the only thing that distinguishes a check from a decoration.

### The `stress-ng` half — done

**Result: 220 runs, 220 passes, no hangs.** Twenty full-suite runs (28.9 min of
CPU, 76.8–100.2 s each) and two hundred runs of the threaded tests alone
(10.1 min, 2.0–4.8 s each), under `stress-ng --cpu 32` on a 16-core box.
Artefact: `var/flake/p22-campaign/summary.json`.

**Decision 1 — a shell loop, or a committed harness.** A harness,
`benchmarks/flake_hunt.py`. EVIDENCE.md's own rule is that a row needs a command
that reproduces it on a clean checkout, and *"I ran a for-loop once"* does not
survive contact with the next person who asks.

**Decision 2 — two outcomes or three.** Three: pass, fail, and **hang**. This is
the design point and not a detail. The defect the campaign is about *hung* rather
than failed, so a harness with only pass/fail would either block forever on the
very outcome it was built to detect, or report it as a failure and send the next
reader hunting for an assertion that does not exist. Each run gets a wall-clock
timeout; a kill is recorded as its own outcome with the partial output kept.

**Decision 3 — how many runs, and of what.**

| Option | Benefit | Drawback | |
|---|---|---|---|
| **A. 20 full-suite runs *and* 200 of the threaded tests alone** | The broad pass catches a flake anywhere, which nothing had ever looked for; the focused pass buys ten times the statistical power on the actual risk, for a third of the time. 39 min total | Two numbers to report instead of one | **chosen** |
| B. 20 full-suite runs only, as the original entry asked | Simplest | Twenty samples of a race that fires rarely is weak evidence, and 90 % of each run is spent on tests with no threads in them | rejected |
| C. 200 full-suite runs | Uniformly strong | ~5 hours, for coverage that options A already concentrates where it matters | rejected |

**Decision 4 — what happens when `stress-ng` is missing.** Falls back to a
Python spinner and *says so* in the output and the summary JSON. The spinner is
genuinely weaker — one interpreter per worker, and the GIL makes it less hostile
than a native busy-loop. But *"stress-ng is not installed"* must never silently
become *"the campaign ran unloaded and everything passed"*, which is the shape of
every green result that means nothing.

**The harness has its own tests.** `tests/unit/test_flake_hunt.py`, ten of them,
including one that hands the harness a test which really does sleep for ten
minutes and asserts it comes back `hang` — not `fail` — with the child dead and a
log written. A campaign that reports "no hangs" is worth precisely as much as its
ability to see one.

### Honest reading of the result

Two hundred and twenty clean runs is **absence of evidence, not evidence of
absence** — the harness prints that line itself rather than leaving it to the
reader. The original hang was observed at 12-way load; this ran at 32-way on 16
cores, so the contention was harder, and the suite ran 1.5–2× slower than
unloaded, which confirms the load was real rather than nominal. What it does not
establish is a rate: a race with a per-run probability of 1 % would survive 220
runs about one time in nine.

**Estimate:** 1.5–2 days.

## ~~P2.3 — Clamp the OOD counter~~ — DONE, 2 Aug 2026

Finding F5. The counter now lives in `[0, ood_threshold_halt]`.

### One thing the original entry got wrong

It said the recovery claim *"holds only for excursions short enough that the
counter can be walked back down"*. That was already false, and finding out why is
what made the ceiling the obvious choice: **outside HALT the counter could never
exceed `ood_threshold_halt`, because reaching it is what enters HALT**, and
`_next_state` returns before consulting the counter thereafter. So recovery was
always bounded. What was unbounded was the *number written into every audit row*,
which is a real defect but a different one — evidence hygiene, not safety.

### Decisions taken

**Where to put the ceiling.**

| Option | Benefit | Drawback | |
|---|---|---|---|
| **A. `min(ood_threshold_halt, counter + 1)`** | The only non-arbitrary bound available: no value above it can change any decision, so the clamp discards exactly the information nothing consumes. One `min`, no new state, no new constant | Loses "how long have we been in HALT" as a side-effect of the counter | **chosen** |
| B. Clamp at a multiple — 2×, 10× | Keeps some of that duration signal | The multiple is a magic number with no consumer, and a constant nobody can justify is a constant nobody can maintain | rejected |
| C. Freeze the counter on entering HALT | Same outcome, arguably more explicit | Needs a branch on state inside the counter arithmetic. A is the same invariant expressed as a bound, and bounds are easier to test than branches | rejected |
| D. Correct the docstring, leave the counter | No behaviour change | Leaves a field in a safety-evidence record growing without limit and meaning nothing above 100 | rejected |

**On option A's drawback:** duration in HALT is not actually lost. The snapshot
carries the tick and the entry tick is in the log, so it is a subtraction —
pinned by `test_time_spent_in_halt_is_still_recoverable_from_the_snapshot`.
Reading it off the counter would be one field answering two questions, which is
how an evidence log becomes ambiguous.

**What the ceiling buys that the original entry did not ask for.** It turns the
module's promise of automatic recovery into a *bounded* one that can be written
down: at most `ood_threshold_halt - ood_threshold_degraded + hysteresis`
consecutive clean ticks — 91 at the simulation profile, 4.6 s at 20 Hz. That is
now in the module docstring and pinned by
`test_recovery_is_bounded_in_duration_and_not_merely_automatic`, which computes
the bound from the thresholds rather than hardcoding it.

### Verification

Deleting the `min` fails exactly the two tests that name the ceiling and no
others — the mutation check, because a test that would pass without the fix is
not evidence of the fix. Gate green: 2,643 passed, 97.95 %.

## ~~P2.4 — Decide what to do about the unobserved lateral position~~ — DONE, 2 Aug 2026

Resolved by P0.0: lateral position is now measured at sigma = 0.1 m and the
estimator error fell from 2.9e6 m to 0.0000. This entry originally offered
"publish a measurement" or "mark it structurally unobservable and assert nothing
reads it" as alternatives; the first was taken.

<details><summary>Original entry</summary>

## P2.4 — Decide what to do about the unobserved lateral position

**Finding F4.** `mean_estimator_error_m` — the gap between the UKF's `position_y`
and the plant's truth — reached 2.9×10⁶ m. The extractor in
`training/closed_loop.py` publishes only `speed` and `lateral_acceleration`, so
`position_y` is never observed and is dead-reckoned from an unobserved heading.

Nothing in the current wiring consumes it — the fallback reads only speed — so it
caused none of the above. It matters because **L6 scores against the full state
estimate and its covariance**, and because any component added later that reads
estimated lateral position would be reading a number wrong by kilometres with no
indication in the record.

**Options:** publish a position measurement from the plant; or mark `position_y`
as structurally unobservable in this configuration and assert that no consumer
reads it.
**Estimate:** 1–2 days.

</details>

## ~~P2.5 — Understand the saturated Trust Index~~ — DONE, 2 Aug 2026

**Root cause: the Trust Index measured one statistic and was calibrated against
another.** L3 scores the filter's innovation magnitude — it must, because it runs
at tick line 334, before L4 proposes at 422, so no proposal exists for it to
score. L6 scores `dist(proposal, twin) / sigma`. Both queried **one**
`MondrianCalibration`.

The scales were never comparable. Measured in the regenerated corpus:

| | gate scores | innovations |
|---|---|---|
| HIGHWAY_CLEAR | 1.158 – 1.189 | 0.518 – 7.497 |
| DEGRADED_SENSOR | 1.155 – 1.191 | 7.549 – **154.8** |

So `1 - cdf(innovation)` against a CDF of gate scores pinned to one end. The
Trust Index took **exactly two distinct values across 4,001 consecutive ticks**.

### Decisions taken

**Decision: give L3 its own calibration over the statistic it measures.** Corpus
schema 1 → 2, adding an `innovations` score set harvested alongside; assembly
builds two `MondrianCalibration` instances.

| Option | Benefit | Drawback | Verdict |
|---|---|---|---|
| **Separate calibration (chosen)** | CDF is over the quantity being measured; TI becomes a real index; tick ordering and the proposer's TI input untouched; SI-4 unaffected | Corpus schema change; generator harvests twice; two distributions where a comment argued for one | **Taken** |
| Make L3 use L6's score | Perfect agreement between TI and gate | **Impossible** — no proposal exists at L3's point in the tick | Rejected |
| Move the TI after L6 | Would let both use one score | Breaks `propose(trust=trust)` — the proposer consumes the TI. Large architectural change for a calibration bug | Rejected |
| Report it honestly as a binary flag | Zero machinery; immediately honest | Deletes a graded signal L9 routing and the paper both rely on | Rejected |
| Do nothing | — | A "Trust Index" with 2 values in 4,001 ticks, feeding L4 monitoring and L9 routing, about to have FB3 wired into it | Rejected |

The old sharing comment reasoned that "two independently-maintained copies would
drift apart". Sound, and the premise was false: these are two *distributions*,
not two copies, and a TI that disagrees with the gate is now informative rather
than a symptom.

**Result:** 2 distinct values → 5, range 0.358–1.000. Better, and **still
saturated at 1.0 for ~99.9% of nominal ticks** — for a new and defensible reason,
which is the next item.

## ~~P2.6 — The closed loop runs with perfect sensors~~ — DONE, 2 Aug 2026

Two mismatches, both fixed:

1. `training/closed_loop.py` published the plant's **exact state** as sensor
   readings while declaring σ = 0.01 / 0.04 / 0.1 to the filter.
2. The corpus generator injected `gauss(0, 0.08)` on speed and `0.12` on lateral
   acceleration while declaring **those same** 0.01 / 0.04 — an eightfold and
   threefold underestimate, which makes the UKF over-trust its measurements and
   inflates every normalised innovation.

The sigmas now live in one place, `training/closed_loop.py`, imported by the
generator, because the number has to be true of two things at once — the noise
injected and the sigma declared — and two literals drift. Noise is drawn from a
source seeded off the run seed, so reproducibility holds.

### Decisions taken

| Option | Benefit | Drawback | Verdict |
|---|---|---|---|
| **Inject at the declared sigmas, one shared constant (chosen)** | Filter's `R` matches reality; innovations properly scaled; realistic sensor model; single source of truth | Corpus regenerated again; all baselines re-measured | **Taken** |
| Inject at the corpus's 0.08 / 0.12, leave declared sigmas | Matches the corpus exactly, cheapest | Preserves the mis-tuning in both places — a filter told the wrong noise level is simply wrong | Rejected |
| Standardise on 0.08 / 0.12 as declared *and* injected | Also self-consistent | Pessimistic for wheel-encoder speed and IMU lateral acceleration; 0.01 / 0.04 are the physically realistic figures | Rejected |
| Leave it noiseless | No churn | A UKF exists to reject measurement noise and L1's staleness machinery exists for imperfect streams; neither had ever been exercised by a closed-loop run | Rejected |

### Results

**The Trust Index became an index.** Distinct values across 8,001 ticks:
**2 → 5 → 90**. Mean 0.960, p05 0.902, p50 0.964, p95 1.000 — graded resolution
in nominal driving, where before it was pinned at 1.0.

**The loop is still stable, and now that means something.** All ten criteria
pass over 100,000 ticks *with noisy sensors*: `PROPOSED` on 99,911 ticks,
`RATE_LIMITED` on 89, lane deviation 0.0290 → 0.0298 m, fail-safe machine never
leaving NOMINAL, resident set +0.1 MiB, p99 ×0.81.

N-4a is retired from the evidence pack's *not demonstrated* list.

<details><summary>Original entry</summary>

## P2.6 — The closed loop runs with perfect sensors



Found while closing P2.5. `training/closed_loop.py` publishes the plant's **exact
state** as sensor readings while declaring σ = 0.01 / 0.04 / 0.1 to the filter.
The corpus is harvested with `gauss(0, 0.08)` on speed, `0.12` on lateral
acceleration and `0.1` on position.

So the filter is told its measurements are noisy and receives perfect ones. Its
innovations sit near zero, which is why the Trust Index still reads 1.0 in
nominal driving even against a matched distribution.

**This is larger than the Trust Index.** Every soak measurement on record ran
with perfect sensors — including "stable over 100,000 ticks". A UKF exists to
reject measurement noise, L1's staleness and health machinery exists to handle
imperfect streams, and neither has been exercised by the closed loop.

**Recommended:** publish measurements at the same noise the corpus is harvested
with, then re-run the matrix. Expect it to be harder; if the loop is still stable
that result means considerably more than the current one, and if it is not, that
is the finding.

**Estimate:** 1 day including re-running the baselines.
**Note:** this invalidates no *conclusion* reached today — the defects found were
all structural — but it does put an asterisk on every stability figure until it
is done.

</details>

<details><summary>Original P2.5 entry</summary>

## P2.5 — Understand the saturated Trust Index before wiring FB3

The Trust Index read **exactly 1.00 in every window after the first**, in all
four 100k runs — including the placeholder run, where L6 was simultaneously
vetoing 100% of ticks on the conformal quantile. A signal pinned at its maximum
for 99,000 consecutive ticks carries no information, and one that reads
"maximally typical" while its own gate rejects every proposal needs explaining
before FB3 wires online requantilisation into it.

**Estimate:** 1–2 days.

---

</details>

# P3 — Unblocked only after P0

## P3.1 — FB2, PINN online adaptation (work plan §3.1) — PART DONE, 2 Aug 2026

**Done:** the catastrophic-forgetting test, and the anchoring defect it found.
**Still open:** wiring FB2 into the tick loop, and P3.1a below.

### What the forgetting test found

The entry said to write it first. That was right, and it overturned the entry's
own diagnosis. Three findings, in increasing order of importance.

**1. λ=150 was not weak, it was bit-for-bit inert.** At λ=0 and λ=150, forgetting
after 4,000 samples of a second context was 0.038972 and 0.038951 — identical to
four decimals. The entry guessed the penalty started to bite around λ≈10¹²; a
sweep over ten orders of magnitude found one useful *decade*, at 10⁶, with a
cliff at 3×10⁶ where the penalty makes the twin worse at **both** contexts.

**2. The cause was the anchor, not the number.** `_consolidate` re-anchored after
every buffer flush, so the penalty resisted the last fifty samples' movement and
permitted unlimited total drift. A step-size limiter wearing EWC's name. Fixed by
ADR-0018: the anchor now moves on a `ContextClass` change and is held within one,
which makes EWC's task boundary the same partition L3 and L9 already use. The
response is then monotone from 10² to 10⁸ with no cliff, and λ is set to **10⁴**
— chosen mid-range for robustness, so being wrong by an order of magnitude either
way still leaves a working penalty.

Rescaling the penalty, the other option the entry offered, was **measured and
rejected**: normalising the Fisher by its mean shifts the window without widening
it and cuts the best available protection from 0.084 to 0.309 of unregularised.

**3. P3.1a — the penalty was a brake, not a consolidator. RESOLVED by
[ADR-0019](adr/0019-one-twin-head-per-context.md).** Across λ from 0 to 10⁵ the
ratio of forgetting to adaptation was constant to three significant figures. That
could not have been otherwise: EWC protects an old task by holding the parameters
*that task* depends on, which needs the two tasks to use partially disjoint
subspaces, and FB2 adapted a single 16×2 readout that both contexts used in full.

Replaced with **one output head per `ContextClass`**. Forgetting is now
structurally impossible rather than penalised, and the test asserts *exact*
equality. `ewc_lambda`, `fisher_sample_count` and the Fisher machinery are
deleted — one fewer empirical safety number, and coverage went **up** to 98.13%.
The second reason it was worth doing: the ICP score was comparing a
context-blind `π̂` against a per-context quantile, and now is not.

It also uncovered a live defect in `training/train_twin.py`, which fitted one
head and left the rest at random initialisation — caught by the forgetting test
refusing to agree that the offline twin knew the highway.

**4. FB2 is slow.** Unregularised, 4,000 samples — 200 s at 20 Hz — closed 21% of
a large context change; at λ=10⁴, 1.7%. SGD at 10⁻³ with gradients clipped to
norm 1 moves parameters by at most 10⁻³ per step, ten steps per fifty samples.

**5. P3.1b — FB2 would disarm the statistical gate. MEASURED, and it is why FB2
must not be wired in its current form.**

`twin.py`'s module docstring states the property:

> *If the twin were trained until it predicted Core-A's policy accurately, every
> non-conformity score would be small, the statistical gate would stop firing,
> and the system would look healthy while having disarmed one of its three
> gates. The twin is trained against physics, not against the proposer.*

Offline training honours that — `train_twin.py` labels each state with
`steer = lateral / gain`, the inverse of `B·π = a_lat`, with the proposer playing
no part. **`_consolidate` does not.** Its data term is `MSE(predicted, applied)`,
and `applied` is the issued command — the proposal on 99.9% of ticks. FB2's only
source of labels is the component the twin exists to be independent of.

Run in shadow over 100,000 ticks in one unchanging context
(`var/soak/p31b-scores`), with both scores computed by `non_conformity_score`
extracted from the gate rather than reimplemented beside it:

| window | 0 | 20 | 50 | 80 | 99 |
|---|---|---|---|---|---|
| twin divergence | 0.0094 | 0.0607 | 0.1367 | 0.2006 | 0.2360 |
| score, live twin | 1.1564 | 1.1560 | 1.1559 | 1.1559 | 1.1560 |
| score, shadow twin | 1.1534 | 1.0376 | 0.8896 | 0.7652 | 0.6962 |
| ratio | 0.997 | 0.898 | 0.770 | 0.662 | **0.602** |

**The live score is flat to four decimal places. The shadow's falls 40%,
monotonically, and is still falling at the end.** Same run, same ticks, same
state estimates — the only difference is which twin the score is computed
against, so the collapse is FB2's doing and nothing else's.

The acceptance region is a quantile calibrated offline (2.43 for HIGHWAY_CLEAR).
The scores slide down beneath it, so an anomaly must be correspondingly larger to
cross: headroom to a veto goes from ×2.1 to ×3.5. **Conclusion: do not wire FB2
as it stands.** That needs no action to implement — it is the status quo — and it
now rests on measurement rather than on reading the code.

**6. P3.1c — what FB2 should do instead. OPEN, wants an ADR.**

Working the candidates through turned up a better answer than any of them.

1. *Label FB2 from physics rather than from the command.* Does not work as
   stated: the physically-consistent command satisfies `B·π = a_lat`, and `B` is
   **configured**, so labelling from a fixed `B` reproduces `train_twin.py`'s
   corpus exactly and FB2 learns nothing.
2. *Raise `physics_weight` on the online path.* A tuning answer to a structural
   problem. This phase has shown twice where those end up.
3. *Do not wire FB2 at all.* Correct today; gives up a quarter of the design
   permanently.

**Where the first option points: FB2 should estimate the control effectiveness,
not regress a network onto commands.** What "the vehicle's response changed"
*means* — tyre wear, load shift, a wet road — is that the true `B` has moved, and
that is observable from exactly the pairs FB2 already receives: command a
steering value, observe the lateral acceleration it produced, and the ratio is
the effective `B`. A few-parameter estimate rather than a retraining; it cannot
drift toward the proposer because the proposer's output is not its target; and it
feeds the physics residual the whole twin is anchored on.

Cost: a different mechanism from the roadmap's, and `B` is platform configuration
(NFR5), so where the estimate lives needs care — plausibly the adapter, not the
layer.

### Decisions taken

| Decision | Options | Chosen, and why |
|---|---|---|
| Test design | absolute error bound / **controlled comparison at λ vs λ=0** | The comparison. A bound gets chosen until it passes and then measures the choice; RK-5 already says EWC *may* fail, so the question is whether the penalty does anything, not whether the error is small |
| Where the experiment starts | random init / **offline-trained twin** | FB2 trains only the output layer on a frozen hidden layer. From random weights, 2,400 samples moved the parameters 0.14 and converged at 0.094 error — measuring something the mechanism was never for. Each trial now pre-trains with Adam over both layers, as `train_twin.py` does |
| Anchoring | see ADR-0018 | Context change, not buffer flush |
| λ | least-forgetting (10⁸) / **mid-range (10⁴)** | With the anchor fixed, more λ is monotonically more retention, so there is no optimum to find. 10⁴ is picked for robustness — the property the old value most conspicuously lacked |
| The unfixed part | quietly document / **strict xfail** | A defect recorded in prose gets read once. One recorded as a failing-when-fixed test gets read by CI forever |

### Still to do

- **P3.1c**: decide what FB2 becomes. Its own ADR.
- `adapt()` still has **no callers** in `src/` outside the shadow, and should not
  gain one until P3.1c lands.
- Then: corpus regenerated; per-class coverage back in the 94.9–95.1% band; a
  soak with whatever FB2 turns into.

**Estimate remaining:** 3–4 days.

## P3.2 — FB3, online Mondrian requantilisation (work plan §3.2)

`ConformalTrustModule.recalibrate()` exists and is tested. Wire executed outcomes
into it from the tick loop.

**Design point already settled — do not "fix" it.** `recalibrate()` deliberately
ignores `was_correct` when deciding whether to record a score. Filtering the
calibration set to outcomes that went well biases the quantile downward and
produces a guarantee about a distribution the vehicle does not drive in.

**Exit:** quantiles track a deliberately shifted synthetic distribution; coverage
holds per class through the shift; corpus regenerated; soak repeated.
**Estimate:** 2–3 days.
**Blocked by:** P2.5.

## P3.3 — FB4, plant synchronisation (work plan §3.3)

Return the executed command to the synthetic plant so its internal state reflects
what happened rather than what was planned. Lowest risk of the four; bring up
last. Prototype-only; no counterpart in a real vehicle.

**Exit:** all four loops running together through a long soak without
oscillation.
**Estimate:** 1–2 days.

**Bring the loops up one at a time**, confirming stability before adding the
next. The roadmap is explicit that this does not compress.

## P3.4 — Ablation study (work plan §4.1)

Disable each layer in turn and measure. The `None` paths were preserved
deliberately for this.

| Ablation | Question it answers |
|---|---|
| FB1 off | How fast does the state estimate drift under veto? |
| FB2 off | How far does the twin drift as conditions change? |
| FB3 off | How stale do the quantiles get? |
| L6 off | What does the statistical gate catch that the others do not? |
| L7a off | What does the deterministic shield catch alone? |
| L9 exploration disabled | Confirm the system halts — the behaviour ASTRA exists to avoid |

**Exit:** a table quantifying each layer's contribution. Converts *"we built nine
layers"* into *"here is what each layer is worth"*.
**Estimate:** 3–5 days.
**Note:** meaningless before P0.2. An ablation of a latched system measures the
latch.

## P3.5 — Comparison harness (work plan §4.2)

The single most persuasive artefact available, and it needs no GPU. Two
synchronised instances — full ASTRA and raw Core-A — driven from the same seed
against the same injected fault, side by side. One keeps moving; one does not.

`drive_closed_loop` is the substrate and `benchmarks/soak.py` already supplies
the instrumentation, the window aggregation and the criteria. What is missing is
fault injection (IMU corruption, sensor dropout, an unseen distribution shift)
and lockstep execution of two instances.

**Exit:** a reproducible script producing a two-column result and a recorded run.
**Estimate:** 3–5 days.

---

# P4 — Parallelisable across people

## P4.1 — Dashboard (work plan §5.1)

FastAPI + WebSocket backend, React + Recharts frontend, rendering the pipeline
diagram itself: Trust Index gauge; **L6 and L7 as separately lit paths** — the
visual proof of gate independence; `P_f` visibly widening and narrowing the
acceptance band; the FSM as a lit state diagram; RCM's knowledge-base search,
shadow execution and a **"SAFE EXPLORATION ENGAGED"** banner; an event ticker
with independent-cause attribution.

**Rule:** every number on screen must trace to a live `DecisionRecord`. Nothing
scripted, nothing interpolated.

**Estimate:** 10–15 days. This is a front-end project, not a task.

## P4.2 — Interactive fault injection (work plan §5.2)

Let an audience press the button — a demo where the observer chooses the fault
cannot be staged. **Capture a pre-recorded fallback run before any live
demonstration.**
**Estimate:** 2–4 days. **Depends on:** P3.5 for the injection machinery.

## P4.3 — Replace FilterPy (work plan §6.1)

Last released **2018**, unmaintained, inside the safety path, and it drags
`scipy`, `matplotlib` and `pillow` into a dependency tree that ISO 26262 §8-12
will require a qualification argument for — one per package. `stubs/filterpy/`
already enumerates the exact surface depended on, and it is small.

**Exit:** `filterpy` gone from `pyproject.toml`; UKF tracking accuracy unchanged
against the existing synthetic validation.
**Estimate:** 3–5 days.

## P4.4 — Test domain independence for real (work plan §6.2, assumption A-1)

NFR5 is asserted, structurally defended, and never tested. Add a genuinely
non-automotive profile — a warehouse AGV, a two-channel differential-drive robot
— and get it through the pipeline **without touching `src/astra/` outside
adapters**.

**Exit:** either the claim is validated, or it is revealed to be
automotive-shaped. Both are valuable; the second is more so.
**Estimate:** 4–6 days.

## P4.5 — Security threat model (work plan §6.4)

Currently **nothing exists**: no threat model, no signed artefacts, no key
management. The evidence log is integrity-checked but **not tamper-evident**.
Write down the asymmetry: the architecture assumes an untrusted *proposer* on a
*trusted platform*, and the second half has never been examined.

Pure design work, no compute. Blocks every industrial conversation.
**Estimate:** 3–5 days.

## P4.6 — Make the data-split protocol enforceable, *with* the ingestion code

[`DATA_SPLIT_PROTOCOL.md`](DATA_SPLIT_PROTOCOL.md) is written and it is right.
Nothing enforces it. There is no manifest recording which segment went to TRAIN,
CALIBRATE or TEST, no test that the three are disjoint, and nothing stopping
`generate_calibration.py` reading a segment the twin was fitted on.

That is the same defect class as OD-2 and OD-7 in the credibility matrix — a
document asserting a property no code checks — and the protocol's own warning is
why it matters more here than usual: violating it *"does not fail loudly. It just
stops being true."* Once a corpus is built from an overlapping split, every D-row
resting on it is worthless and nothing anywhere raises.

**Deliberately not done yet, and this is a decision rather than an omission.**
There is no external-data ingestion code in the repository at all — nothing reads
a segment. Enforcement written today would wrap a pipeline that does not exist,
against a dataset layout nobody here has seen, and would very likely be the wrong
shape. Building unused abstractions is a thing this codebase's standards call out.

**Binding exit criterion, so this cannot quietly not happen:** the split manifest
and a segment-level disjointness test land **in the same change** as the first
ingestion script, or the ingestion script does not land. Reviewer's rule, not a
suggestion.

**Estimate:** 0.5 days, on top of whatever the ingestion costs.

---

# P5 — Hardware-gated, and the highest single value in the project

Everything above is unblocked. This phase is last in *sequence* only — it is the
only work producing **non-self-referential** validation. Until it runs, no
false-positive or false-negative rate exists and none can.

| Item | Detail | Days |
|---|---|---|
| **P5.1** Obtain a Linux GPU host | DigitalOcean Student Pack credit ($200, ≈55 h at H100 rates), Azure for Students ($100, quota request usually needed), dual-boot the RTX 3050 6 GB laptop (₹0 — save the BitLocker key first, check Intel RST storage mode), or the college GPU lab. **Cost discipline:** set up on a $6/month CPU droplet, snapshot, spin GPU only for runs, destroy after. Billing alerts at $50/$150 — a forgotten droplet overnight is $27 | 1–2 |
| **P5.2** CARLA adapter | Attaches at the `MeasurementExtractor` seam; `.importlinter` already forbids `import carla` in the core. Run `./CarlaUE4.sh -RenderOffScreen -quality-level=Low` — necessary on 6 GB VRAM and cleaner for latency either way. **If you run at Low, say so in the paper**: the FGSM scenario depends on camera imagery. Closes RK-1b; retires the technical-debt item that the UKF has met only synthetic dynamics | 5–8 |
| **P5.3** Retrain against CARLA | Twin, calibration corpora and PPO policy all regenerate against real simulated dynamics. **The step that produces the first numbers the paper can honestly report as gate accuracy.** Do not run CARLA and PPO training on the same GPU — 6 GB will not hold both. Sequence: rollout → save → stop CARLA → train → restart | 3–5 |
| **P5.4** Seven-phase validation drive | Town04: highway → urban → rain/night → **tunnel** → sensor fault → adversarial FGSM → recovery. The vehicle never stops. **The independence evidence lives here and nowhere else** — Phase 5 (FGSM) is designed so exactly one gate fires; Phase 4 (IMU corruption) so two fire for different reasons. **Report what happens, not what was predicted.** If two gates fire under FGSM, or none do, that is the finding | 3–5 |

---

## Effort summary

| Priority | Days | Notes |
|---|---|---|
| P0 | 2–10 | Range driven entirely by which option P0.2 takes |
| P1 | 5–8 | |
| P2 | 7–12 | |
| P3 | 13–21 | Strictly sequential; does not compress |
| P4 | 22–35 | Genuinely parallel across 2–3 people |
| P5 | 12–20 | Plus unknown findings cost |
| **Total** | **61–106** | Before contingency |

**With contingency: 80–140 person-days.** One engineer full-time ≈ **4–7 months**;
two or three with P4 split off ≈ **3–4.5 months**, because the critical path runs
P0 → P3 → P5 and none of that parallelises.

**The three things that could break the estimate.** P0.2 is unbounded until the
ADR is written. P5.3–P5.4 produce the first honest gate-accuracy numbers and
nobody knows what they are — if the false-positive rate lands above the paper's
<1% claim, that is a re-tune and a re-run of everything above it. And P5 cannot
start without hardware.

---

## Housekeeping

- **Nothing is committed.** Five modified files, four untracked — two of which
  (`docs/CREDIBILITY_MATRIX.md`, `docs/DATA_SPLIT_PROTOCOL.md`) are not mine and
  have been left alone.
- `var/policy/long.pt` is a duplicate of the installed `var/policy/synthetic.pt`.
  Delete once the checkpoint is accepted.
- ~1.1 GB of soak audit logs under `var/` (gitignored).
- The nine traps in [`WORK_PLAN.md`](WORK_PLAN.md) still apply, in particular:
  regenerate `uv.lock` on the machine you commit from; run `make check` in WSL,
  not on the Windows host; **regenerate the calibration corpus after closing any
  feedback loop**.
