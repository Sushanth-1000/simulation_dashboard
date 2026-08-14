# ASTRA — Pending work, by priority

**Prepared** 5 August 2026 · **last revised** 9 August 2026
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

**Current state, 5 August 2026 (evening):** ten layers built, 12 import contracts
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

## P0.0 — Lateral position must be observed — DONE, 5 Aug 2026

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

## ~~P0.4 — The fail-safe machine latches on a startup transient~~ — DONE, 5 Aug 2026

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

## ~~P0.1 — Decide whether bounded safe exploration out-ranks a VETO~~ — DONE, 5 Aug 2026

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

## P0.2 — Break the veto latch — PARTLY DONE, 5 Aug 2026

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

## ~~P1.1 — Match the training step to the tick period~~ — DONE, 5 Aug 2026

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

## ~~P1.2 — Correct the three docstrings that claim speed-cap enforcement~~ — DONE, 5 Aug 2026

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

## ~~P1.3 — Evidence pack~~ — DONE, 5 Aug 2026

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

## ~~P1.4 — Documentation sync~~ — DONE, 5 Aug 2026

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

## ~~P1.5 — Close assumption A-8~~ — DONE, 5 Aug 2026

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

## ~~P2.1 — The `CommandProjector` seam~~ — DONE, 6 Aug 2026

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

## ~~P2.2 — Test-quality gaps~~ (work plan §2.3) — DONE, 6 Aug 2026

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

## ~~P2.3 — Clamp the OOD counter~~ — DONE, 6 Aug 2026

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

## ~~P2.4 — Decide what to do about the unobserved lateral position~~ — DONE, 5 Aug 2026

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

## ~~P2.5 — Understand the saturated Trust Index~~ — DONE, 5 Aug 2026

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

## ~~P2.6 — The closed loop runs with perfect sensors~~ — DONE, 5 Aug 2026

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

## ~~P2.7 — Close OD-9~~ — WIRED, 11 Aug 2026. One third of the defect closed

**The highest-value open defect in the project, and the first one produced by a
fault rather than by a soak or a mechanism review.**

Measured (E-46 – E-48): a 200-tick IMU dropout puts the vehicle **4.199 m off a
1.75 m lane**, 73 ticks outside the corridor, with a veto count and reason codes
**identical to the clean control's** and the fail-safe machine NOMINAL on all
400 ticks. A 2 m slow drift does the same at 2.025 m.

**The cause is not a missing check.** L7a's lateral corridor bound exists and was
added by P2.1a for exactly this hazard. It reads `state.position_y`; the proposer
closes the loop on the same `state.position_y`; so the controller drives the
corrupted estimate to zero and the bound reads **0.023 m** while the vehicle is
4.199 m out. Every Core-B gate reads L2's fast estimate, so this is one common
cause upstream of all three, and it bears directly on D-3.

`shield.py` predicted it in its own docstring — *"this bound is only as good as
the position estimate, and that is not a quibble"* — as a caveat. It is now a
measurement.

### The candidate answers, and why none is chosen yet

| | Idea | For | Against |
|---|---|---|---|
| **A** | **Gate on `StreamHealth`.** L1 already detects the dropout correctly — IMU `DEGRADED` from the second tick. Nothing in Core-B reads it; only L9's context signature weights it | The signal exists, is already computed, already recorded, and costs nothing. Cheapest real improvement available | Catches `DROPOUT` and nothing else. `BIAS`, `DRIFT` and `STUCK_AT` all keep the stream perfectly *fresh* — that is why they were chosen |
| **B** | **Gate on the innovation sequence.** The UKF computes normalised innovations and L3 already reads them for the Trust Index | The principled answer: it is the one quantity that can disagree with the estimate, and it is what a lying stream perturbs | Under a *slow* drift the filter absorbs the fault a little at a time and the innovations may never leave their band. Whether it catches E-47 is **unknown and must be measured** |
| **C** | **Gate on estimate uncertainty**, `trace(P_f)` | Free; already on the record | Almost certainly useless here, and worth writing down so nobody tries it twice: a frozen or biased reading is *self-consistent*, so the filter grows more confident, not less. `P_f` shrinks under exactly the faults that matter |
| **D** | **Require sensor redundancy and cross-check it** | What a real vehicle actually does, and the only one that addresses the general case rather than a fault list | The reference plant publishes one ground truth to all five modalities, so it **cannot express redundancy** and cannot be used to measure this. Belongs in the deployment requirements, and in Phase 7 |

### Measured, 9 August 2026 — the shadow run happened

Latency from the fault opening; **zero false alarms on the control for all three**.

| scenario | departure | health (A) | innovation (B) | trust |
|---|---|---|---|---|
| `imu_dropout` | **4.199 m** | **+5 ticks** | silent | **+5 ticks** |
| `position_drift` | **2.025 m** | silent | silent | silent |
| `position_bias` | 0.931 m | silent | silent | silent |
| `lateral_noise` | 0.140 m | silent | +84 ticks | +10 ticks |
| `speed_stuck` / `speed_bias` | — | silent | silent | silent |

**A works, and better than expected.** It fires at **+5 ticks** against a
departure that begins at **+73** — 3.4 seconds of margin at 20 Hz, from a signal
L1 already computes and records and that no gate reads.

**B is refuted, by measurement rather than by argument.** The innovation
sequence was the principled candidate — the one recorded quantity that can
*disagree* with the estimate — and it is silent on the slow drift. Ramping 2 m
over 200 ticks is 1 cm per tick against a declared sigma of 0.1 m, so every step
sits well inside what the filter expects and the innovation never leaves its
band. It is silent on exactly the fault it was most wanted for.

**C was a dead end and is now a measured one**: `fast_innovation` had to be added
to the decision record (schema v2 → v3) before B could be evaluated at all, which
is its own finding — the pipeline computed the signal every tick, fed it to two
consumers, and archived it nowhere (E-54).

**The slow drift remains undetected by anything.** Option D — sensor redundancy
and a cross-check — is the only candidate left for it, and the reference plant
publishes one ground truth to all five modalities, so it **cannot be measured
here**. That is a limitation of the plant, not a gap in the analysis, and it is
where Phase 7 earns its place.

### What follows, and what deliberately does not

**Wire A.** It is cheap, it is measured, it has margin, and it turns the worst
scenario in the study from "no reaction at all" into "3.4 seconds of warning."

**Do not wire it as a veto without a second measurement.** These are six faults
chosen by hand to defeat six named defences, not a population drawn from
anything. A threshold that catches all six is fitted to its own test set --
which is precisely the defect E-41 records for the conformal corpus, and it
would be no more defensible here. The shadow harness stays in front of it, as it
did for FB2 and FB3.

<details><summary>The original entry, kept for the reasoning that led here</summary>

**Measure A and B in shadow against `benchmarks/fault_study.py` before either is
given authority over a verdict.** That is the standing convention this project
adopted after FB2 and FB3 — *no mechanism gets authority until it has run with
none* — and it is exactly the situation the convention was written for: two
plausible detectors, a strong intuition about which one works, and a cheap way
to find out that costs no verdict.

The shadow harness already exists. The fault study already produces the ground
truth. What is missing is a shadow detector and the four-cell table it fills in.

**Also record D in [`ENGAGEMENT_DELIVERABLES.md`](ENGAGEMENT_DELIVERABLES.md)'s
integration assessment** — *what would have to be true before any of this is
deployable* — because it is a genuine precondition on the integrator and not a
thing this repository can close.

**Exit:** a detection table over the six scenarios for whichever of A and B
survives shadow, or a written statement that neither does and D is the only
answer. Both are publishable; the second is more so.
**Estimate:** 2–3 days for the shadow measurement. The wiring depends on what it
says.

</details>

**Exit — met.** The detection table exists (E-51) and **option A is wired**, as
a second counter in L8 rather than as a gate
([ADR-0024](adr/0024-sensor-integrity-is-a-second-counter-not-a-fourth-gate.md)).

**The design turned on a sentence the shadow measurement made unavoidable:
you cannot veto your way out of a lying sensor.** L9's fallback controller reads
the same corrupted estimate, so a fourth gate would have exchanged one command
computed from a lie for another. What the fault needs is not a refusal, it is a
change of *posture* — and L8 already owns converting sustained evidence into a
graduated one.

**Measured after** (`uv run python -m benchmarks.fault_study`):

| | before | after |
|---|--:|--:|
| `imu_dropout` final \|deviation\| | 4.199 m | **0.167 m** |
| escalation | none, NOMINAL all 400 ticks | **DEGRADED +5, LIMP +15, HALT +40** |
| departure begins at | +73 | +73 — the response now precedes it by 1.65 s |
| control false alarms | — | **0**, integrity counter 0 across 400 ticks |
| the other five faults | — | **unchanged to three decimals**, integrity counter 0 |

### Option E, tried and refuted — analytical redundancy, 11 Aug 2026

Since the plant cannot express sensor redundancy, the obvious substitute is a
second estimate the system can build **without any sensor at all**: propagate the
issued commands through the process model. Commands are not measurements — the
system knows what it sent — so the two estimates should share no channel.

**Refuted by measurement** (E-94 – E-96), and the reason is worth more than the
attempt. On a healthy cruising vehicle the parity residual accumulates at
**0.022–0.040 m per tick of window**; the slow drift injects **0.010 m per tick**.
Both scale linearly with the window, so the ratio is constant and **no window
separates them**.

**The two estimates were never independent.** FB1 feeds the issued command into
the filter's *prediction* step, so the filtered estimate and the propagation
share the process model *and* the command input, differing only by the
measurement correction. The residual is not "commands versus sensors" — it is
"how far the measurement pulled the filter", which under a slow drift is exactly
the drift rate.

**Refuted by the feedback loop that exists to fix the very defect it attacked**,
and FB1 is not removable.

**What it points at, unmeasured:** integration is what kills it, so a check that
does *not* integrate survives — compare the **position channel against the
acceleration channel** directly. Under a position drift the IMU honestly reports
a turning vehicle while the position reading says nothing moved. Cross-channel,
no propagation, does not pass through FB1. Not built, not measured.

### Options B', E and F, all tried and all refuted -- 11 Aug 2026

Four candidates have now been measured against the slow drift. **All four are
silent on it**, and the pattern is the finding:

| | candidate | result |
|---|---|---|
| **B** | the innovation sequence | 1 cm/tick against a 0.1 m sigma never leaves the filter's band (E-53) |
| **B'** | the innovation *gate*'s own flag, fed to the integrity counter | fires on tick 0 of **every** arm including the control, and on no fault but the noise burst (E-105). Refuted before it was built |
| **E** | analytical redundancy -- a command-only second estimate | the two estimates were never independent; FB1 couples them, and the residual accumulates 2.2-4.0x faster than the fault (E-94, E-95) |
| **F** | cross-channel consistency, position against acceleration | catches the *bias* at 4.14x and the drift at **0.99x** (E-106) |

**The root is shared.** A self-consistent lie slower than the sensor noise cannot
be distinguished from truth by any function of a single sensor chain: every
quantity on the record is downstream of the same measurement, and no
rearrangement of downstream quantities creates information that was never
upstream (E-107).

**So option D -- redundancy and a cross-check -- is not the convenient answer,
it is the only one**, and this is now an argument rather than an assertion.

### Option D, measured -- and it was never a Phase 7 blocker

*"Unmeasurable here, because the plant publishes one ground truth to all five
modalities"* was written into three refutations. It was true and it was **half
the story**: two facts made it true and **both live in the test harness**, not
in the architecture (OD-15, E-108). `FusedSensorFrame` already carries
per-modality samples and `MeasurementExtractor` is an injectable port, so
**nothing in `src/` changed** to run this.

Three dissimilar position channels, the drift injected into **one**, residual
against the median (E-109 - E-112):

| arm | IMU | GPS | LIDAR |
|---|--:|--:|--:|
| control | 0.8x | 1.1x | 1.3x |
| drift on IMU | **5.3x** | 1.1x | 2.4x |
| drift on GPS | 0.7x | **4.4x** | 1.5x |

**The faulted channel is identified, not merely detected** -- with three channels
the largest residual names the liar. Detected at **+41** and **+28 ticks**
against a departure that begins at +73.

Two honest caveats. The good channels are perturbed too -- LIDAR reaches 2.4x
under an IMU fault, because with three channels the median itself moves -- so
**the margin to quote is 2.2x over the next channel, not 5.3x over the control**.
And the pipeline is still *driven* by one channel: redundancy is measured beside
the vehicle rather than by it. Wiring it needs its own decision record.

**What Phase 7 is still for**, unchanged: real sensor models with real failure
modes, real imagery for the adversarial scenario, and a plant this project did
not author, so the numbers stop being self-referential.

**Two thirds of OD-9 remain open and the register says so.** `StreamHealth` is
computed from staleness, so `BIAS`, `DRIFT` and `STUCK_AT` — which keep the
stream perfectly fresh — are invisible to it, and **no gate sees the fault even
now**. Option D, sensor redundancy with a cross-check, is still the only
candidate for the general case and still cannot be measured on a plant that
publishes one ground truth to all five modalities. Phase 7.

---

# P3 — Unblocked only after P0

## P3.1 — FB2, PINN online adaptation (work plan §3.1) — PART DONE, 6 Aug 2026

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

The acceptance region is a quantile calibrated offline, and the scores slide down
beneath it, so an anomaly must be correspondingly larger to cross.

**Corrected on re-measurement, 6 Aug.** This entry first cited a quantile of
**2.43**, taken from E-20. That is not what the shipped corpus holds: reading
`var/calibration/synthetic.json` directly gives HIGHWAY_CLEAR p95 = **1.179**
over 1,000 samples, spanning only 1.158–1.189. So the true figures are headroom
**×1.02 today against ×1.69 under FB2** — an anomaly would need to sit 69% above
the twin's prediction to trip the gate, against 2% now.

The direction is unchanged and the conclusion is unchanged. What changed is that
**the margin today is far thinner than the original framing implied**, not wider:
the live score 1.156 sits *below* the corpus minimum of 1.158, and the whole
calibration distribution spans 0.03. That is its own finding and it is not FB2's
doing — see P3.2.

**Conclusion: do not wire FB2 as it stands.** That needs no action to implement — it is the status quo — and it
now rests on measurement rather than on reading the code.

**6. P3.1c — what FB2 should do instead. DECIDED, [ADR-0020](adr/0020-fb2-estimates-control-effectiveness.md); estimator built, shadowed 9 Aug, and NOT wired — the specified placement is blind (E-63).**

FB2 estimates the control effectiveness `B` from measured response rather than
regressing a network onto proposer commands. The target becomes measured physics,
so drift toward the proposer is impossible rather than penalised — the ADR-0019
move, one level up — and the twin's weights stop changing during a run at all.

Evidence, and it carries a hard condition: `a_lat / steer` recovers the configured
B = 140.0 to **0.000%** with σ = 0, **provided saturated samples are excluded**.
Admitting them reads 116.0, **17.1% low**, and low is the dangerous direction —
an underestimated B shrinks the departure the score is computed from (E-43). The
first probe made exactly that mistake by driving ±0.05 steer into a plant that
saturates at 0.0214, and it is recorded because the same error in production
would be silent.

**The estimator itself is now built and tested** — `ControlEffectivenessEstimator`
in the adapter, 18 tests, including the saturation control that computes what a
naive estimator *would* have returned from exactly the samples the real one
rejects.

### Shadowed 9 August 2026, and the placement was wrong

| scenario | true `B` | from the **estimate** | from the **raw reading** |
|---|--:|--:|--:|
| control | 140.0 | **140.000** | 137.843 |
| `lateral_noise` | 140.0 | 140.000 | 140.000 |
| **platform `B`=112** | **112.0** | **140.000** | **111.341** |
| **platform `B`=168** | **168.0** | **140.000** | **165.140** |

**Fed the filtered estimate — where the ADR places it — the estimator returns
the configured value on every platform it is shown**, exactly, on vehicles whose
true `B` is 20% away in either direction (E-63). The UKF's process model already
assumes `B`, so its lateral-acceleration estimate is that assumption propagated;
an estimator reading it measures the configuration and calls it a measurement.
Wired that way the loop would report *"the platform has not changed"* for any
platform — the fifth mechanism in this register that fails by looking fine.

Fed the **raw measured response** it tracks: 111.3 against 112, 165.1 against 168
(E-64). And the risk the shadow run was written to look for did not appear —
**no injected fault moves it materially**, the widest deviation being 0.4% and
the 25×-sigma noise burst leaving it exactly at 140.000, because the estimate is
a median (E-65).

**Still open, and this is why it is still not wired:**

- the **~1.5% low bias** on the raw reading is unexplained, small, consistent,
  and in the direction the ADR itself names as dangerous;
- six hand-chosen faults are not a population;
- **`B` is constant within every run measured so far.** A platform whose
  effectiveness changes *mid-run* is the case this loop exists for, and nothing
  has tested it.

Also still open, unchanged: sample starvation (only 387 of 4,000 wide-steer
samples survived the filter), noise on a real platform where σ will not be zero,
and the port change to let L5 read a live estimate without reaching into the
adapter.

**Estimate:** 2–3 days — explain the bias, build a plant whose `B` moves
mid-run, re-shadow, then the port change.

**6-original. P3.1c — what FB2 should do instead.**

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

## P3.2 — FB3, online Mondrian requantilisation (work plan §3.2) — BLOCKED by a defect

`ConformalTrustModule.recalibrate()` exists and is tested. It must not be wired
as it stands, and the reason is the same shape as P3.1b's, which is what makes it
worth stating carefully.

### The defect

Since P2.5, L3 and L6 hold **two different distributions**, because sharing one
pinned the Trust Index to 2 distinct values across 4,001 ticks (E-18):

| | distribution | typical range |
|---|---|---|
| L3 Trust Index | filter innovation, `mahalanobis_innovation_magnitude` | 0.518–7.497 clear, 7.549–154.8 degraded |
| L6 gate | non-conformity score, `\|π_prop − π̂\| / σ` | 1.155–1.191 |

`assess()` honours that split — `trust = 1 − cdf(innovation_dist, innovation)`.

**`recalibrate()` does not.** It observes its argument into that same innovation
distribution, and both the port and the implementation document that argument as
*"the realised score for the executed command"* — L6's score. Wiring FB3 as
specified would therefore pour gate-scale values into the innovation
distribution, **re-merging exactly the two statistics P2.5 separated**, through a
different door. The Trust Index would stop meaning "how unusual is this
innovation" and become a mixture statistic, silently.

Dormant today: `recalibrate` has no callers. That is the only reason it is not a
P0.

### What to decide, and it is a real fork

1. **FB3 feeds L6's score into L6's calibration** — a *third* wiring, since the
   gate's `MondrianCalibration` is a separate object from L3's. This is what
   "online Mondrian requantilisation" most naturally means: the gate's own
   quantile tracks the scores the deployed proposer actually produces. E-20 says
   that matters — regenerating the corpus from the deployed policy moved the
   HIGHWAY_CLEAR quantile 1.18 → 2.43.
2. **FB3 feeds innovations into L3's calibration** — keeps the current object
   graph and makes the parameter name the defect. Smaller change, and arguably
   what the code already is.
3. **Both, as two separate loops**, since they are two distributions and there is
   no reason one call should serve both.

I would take **1**, and rename `recalibrate`'s parameter to say which statistic
it takes. But it changes which object L3 hands the update to, so it wants the
decision written down rather than inferred from a parameter name — which is how
this got here.

### The pattern, which is now worth naming

Three feedback loops, three outcomes:

- **FB1** — wired, works.
- **FB2** — dormant, and would have disarmed the statistical gate (D-6/OD-7).
- **FB3** — dormant, and would have corrupted the Trust Index.

Every unwired loop in this repository has carried a latent defect that appears
only at the moment it is wired. **FB4 has not been examined and should be assumed
to carry one too.** Nothing about a loop being tested in isolation says anything
about what it does to the system it is connected to; that is what the shadow
harness is for, and it should be the default for FB3 and FB4 exactly as it was
for FB2.

### Measured, 6 August 2026 (`var/soak/p32-fb3`)

Fixed as above — each layer requantilises its own statistic — then run in shadow
over 100,000 ticks, thresholded against by nothing.

| | value |
|---|---|
| live quantile | **1.1720**, flat |
| FB3's quantile | **1.1575**, reached within 2 windows, min/max 1.1573/1.1626 |
| veto rate today | **0.089%** |
| veto rate FB3 would give | **5.02%**, steady |

**FB3 is dynamically well behaved.** Unlike FB2 it converges almost immediately
and does not drift for the remaining 98,000 ticks. Whatever is wrong with it is
not instability.

**What is wrong with it is that 5.02% is ε.** `significance_epsilon = 0.05`, and
conformal prediction's guarantee is that ε of *exchangeable* samples exceed the
1−ε quantile. Calibrate on the distribution you are then tested against and the
veto rate goes to ε **by construction, whether or not anything is wrong**. The
gate stops being a detector and becomes a fixed-rate sampler firing once a second
at 20 Hz.

That is the same class of defect as FB2's and the mirror image of it: FB2 made
the gate insensitive by moving the reference toward the proposal; FB3 makes it
fire at a constant rate independent of the evidence. Both destroy the gate's
meaning without breaking anything that would show up as an error.

### Two findings that are not about FB3 at all

**1. Today's 0.089% veto rate is an artefact of non-exchangeability.** The live
scores sit at **1.156**, *below* the corpus minimum of **1.158**; the whole
calibration distribution spans 0.03. The gate is quiet because the calibration
set does not match what the vehicle produces — which is exactly the exchangeability
assumption conformal prediction rests on, already violated. E-12's 94.9–95.1%
coverage is real but was measured on shuffled splits *of the corpus*, which are
exchangeable by construction; it does not transfer to the live loop.

**2. ~~`significance_epsilon = 0.05` contradicts D-1's "false-positive rate < 1%".~~
RESOLVED — it was a units error in D-1, not a defect.** Measured at the design point over
100,000 ticks: **4.97% of ticks vetoed, 0.008% outside NOMINAL** — two episodes in 83 minutes,
2 and 6 ticks, both self-recovering, LIMP and HALT never reached (E-42). A veto runs the
fallback for one tick; θ₁ = 10 sustained refusals are needed to degrade the posture, and
independent 5% events do not cluster that way. Per-tick is ε by construction; per-intervention
is what a fleet pays for; they differ by ~600×. **ε stays at 0.05** — lowering it would have
raised the threshold, bought D-1 with D-2, and made the rare context classes uncertifiable at
n ≥ 99. Original text follows.

**2-original. `significance_epsilon = 0.05` contradicts D-1's "false-positive rate < 1%".**
A correctly functioning conformal gate at ε = 0.05 vetoes 5% of nominal
exchangeable traffic. The two cannot both be true, and FB3's shadow is what made
it unavoidable: it is the first time the gate has been asked to run at its own
design point. Either ε drops to ≤ 0.01, or D-1 is restated, or D-1 is a claim
about something other than the conformal rate. **This is a decision for the
safety argument, not a tuning change**, and it belongs with the credibility
matrix.

**Exit:** FB3's mechanism is fixed and measured; it is *not* wired, and should not
be until finding 2 is settled — the veto rate it produces is a direct consequence
of ε, so choosing ε is choosing FB3's behaviour.
**Estimate:** the ε decision, then 1 day to wire and re-soak.

## ~~P3.3 — FB4, plant synchronisation~~ — ALREADY WIRED, 8 Aug 2026

**My prediction was wrong and it is worth recording as such.** After FB2 and FB3
both turned out to be broken, I said FB4 should be assumed to carry a latent
defect too. It does not, and it is not even unwired: `training/closed_loop.py`
steps the plant with whatever L9 issued —

> *Close the loop: whatever L9 actually issued is what the plant applies. A veto
> therefore changes the vehicle's trajectory, which is the whole point and what
> an open-loop harness cannot show.*

It lives in the harness rather than in `src/` because FB4 is the one loop with
**no deployment counterpart** — `FeedbackLoop.FB4_SIMULATOR_SYNC.is_deployment_relevant`
is `False`. A simulator sync belongs in the simulator's driver, not in the
runtime. So it is both wired and in the right place.

That also means **every soak in this project measured ASTRA driving, not the
proposer driving.** Worth stating explicitly, because had it been otherwise every
closed-loop number since the first run would have been meaningless.

### One real defect, in the branch that never runs

The `else` arm — what the plant gets when the pipeline issued *nothing* — read
`[0.0, 1.0, 0.0]`. That is the plant's **normalised** action space, where
`v = lower + (action + 1) / 2 × (upper − lower)`, so on a channel bounded `[0, 1]`
an action of `0.0` is **half throttle**. The branch that exists for "the pipeline
failed to issue a command" was commanding half throttle and full brake together.

Unreachable in everything measured — 0 ticks of 100,000 issued nothing (E-3) —
which is exactly why nothing caught it, and no less wrong for that. Now
`[-1.0, 1.0, 0.0]`, with a test that decodes the constant through the plant's own
bounds rather than asserting the literal.

### The four loops, closed out

| | state | if wired |
|---|---|---|
| FB1 | wired | works |
| FB2 | dormant | would disarm the statistical gate (E-39) |
| FB3 | dormant | drives the veto rate to ε by construction (E-40) |
| FB4 | **wired, in the harness** | works; one unreachable branch fixed |

The pattern I named after FB3 — *every unwired loop carries a latent defect* —
survives, but it should be stated more precisely: **the two loops that feed a
gate's own inputs were both broken; the two that feed state estimation and the
plant were not.** That is a sharper claim and a more useful one, because it says
where to look next rather than merely that something will be wrong.

## ~~P3.4 — Ablation study (work plan §4.1)~~ — DONE, 9 Aug 2026

**The entry's premise does not hold, and that is the first finding.** It said
*"the `None` paths were preserved deliberately for this"*. Checked against the
code: **one of the six ablations has a `None` path.**

| Ablation | Disable path today | Status |
|---|---|---|
| **FB1 off** | `control_effectiveness: Sequence[float] \| None` on the pipeline | **Ready.** The only one |
| L6 off | `statistical_gate: IcpStatisticalGate` — **required parameter** | Needs building |
| L7a off | `shield: HardSafetyShield` — **required parameter** | Needs building |
| L9 exploration off | Driven by `ArbitrationOutcome.SAFE_EXPLORATION`, not by a switch | Needs building |
| FB2 off | — | **Vacuous.** See below |
| FB3 off | — | **Vacuous.** See below |

### Two of the six are already answered, and better than an ablation could

FB2 and FB3 have never been wired. "FB2 off" *is* the shipped configuration, so
ablating it measures nothing — the comparison it wants is against FB2 **on**,
which is the direction that was never available.

That comparison exists, and it is stronger than an ablation because it changed no
verdict: both loops were run **in shadow**, adapting real state, read by nothing.

- **FB2 on** would collapse the non-conformity score **40%** in a context where
  nothing changed, while the live score stayed flat to four decimal places
  (E-39). Its labels are the proposer's own commands (E-38).
- **FB3 on** would drive the veto rate to **5.02%** — ε exactly, because ε of any
  distribution lies above its own 1−ε quantile (E-40).

Those rows belong in the ablation table as measured results. They should not be
re-derived by switching off something that was never on.

### What building the remaining three actually costs

Each is a change to the safety spine, not a flag. `statistical_gate` and `shield`
are required constructor parameters because a pipeline that silently ran without
a gate would be the single most dangerous defect this codebase could carry — the
requirement is load-bearing, and removing it needs care that "make it optional"
does not convey.

The shape that keeps the guarantee: an explicit `AblationProfile` naming which
layers are disabled, refused outright by any environment other than
`development`, and stamped into every `DecisionRecord` so a run measured under an
ablation can never be mistaken for a governed one. That is more work than the
entry implies and it is the right amount, because the failure mode of getting it
wrong is a certification artefact describing a system that was not running.

### Measured, 9 August 2026

ADR-0021 implemented and the study run: four profiles x seven scenarios, 2,800
ticks each, same seed. Vetoes per run:

| profile | control | `imu_dropout` | `position_bias` | others |
|---|---|---|---|---|
| governed | 3 | 3 | 12 | 3–4 |
| L6 off | 3 | 3 | **11** | 3–4 |
| **L7b off** | **0** | **0** | **1** | **0** |
| L7a off | 3 | 3 | 12 | 3–4 |

**L7b produces essentially every veto in this system.** Disarming it takes the
count to zero on six of seven scenarios. **L6 contributes one veto in 2,800
ticks. L7a contributes zero, everywhere.** Disarming any single gate moves the
vehicle by at most **5 mm** (E-59, E-60).

**The reading to refuse:** *"L7a is worthless."* It vetoed once in roughly
500,000 nominal ticks (N-9), so a 2,800-tick study finding zero is consistent
with its known rate rather than evidence against it. What this measures is each
gate's contribution **on these seven scenarios**, and that is the whole claim.

**The positive control matters as much as the table.** Disarmed gates still run
and still write a verdict: `ablated_passes` is **0 of 2,800 in every governed
row and 2,800 of 2,800 in every disarmed row** (E-61). A study that silently
failed to ablate would report zeroes everywhere and look otherwise identical.

**One correction to ADR-0021, made on first contact.** The environment guard
originally admitted `development` alone. That would have measured every ablated
run at that environment's deliberately twitchy operating point — OOD thresholds
of 3/6/10 against simulation's 10/30/100 — so each run would have differed from
its control in the disarmed gate *and* in a tenfold tighter escalation. Two
variables, one measurement. The guard now admits `development` and `simulation`,
and still refuses `certification`, which is the environment the rule exists for.

**Exit met:** a table quantifying each layer's contribution, with FB2 and FB3
supplied from the shadow measurements rather than re-derived.
**Estimate:** 4–6 days, revised up from 3–5 — the entry costed six ablations
against `None` paths that mostly do not exist.
**Unblocked:** the note *"meaningless before P0.2"* no longer applies. P0.2 was
dissolved by P0.0, the loop runs at a 0.1% veto rate, and an ablation now
measures the layer rather than the latch.

## ~~P3.5 — Comparison harness (work plan §4.2)~~ — DONE, 9 Aug 2026

The single most persuasive artefact available, and it needs no GPU. Two
synchronised instances — full ASTRA and raw Core-A — driven from the same seed
against the same injected fault, side by side. One keeps moving; one does not.

`drive_closed_loop` is the substrate and `benchmarks/soak.py` already supplies
the instrumentation, the window aggregation and the criteria. ~~What is missing
is fault injection~~ — **fault injection landed 9 August** (P4.2, ADR-0022), and
`benchmarks/fault_study.py` is already half of this: same seed, same policy, one
injected fault, a clean control beside it.

What is still missing is the **other instance** — raw Core-A driven in lockstep
against the same fault, with no gates at all. The fault study compares ASTRA
against ASTRA; this compares ASTRA against no ASTRA.

**The exit criterion needs restating in light of E-46, and this is not a
softening.** The planned result was *"one keeps moving; one does not."* Under an
injected sensor fault the measured result is that **both** keep moving and both
leave the corridor, because the gates read the estimate the fault corrupted
(OD-9). A comparison harness that only reported the flattering scenario would be
a demo rather than a measurement. Build it to report whichever way each fault
falls, and expect a mixed table.

**Exit — met, 9 August 2026.** [`benchmarks/comparison.py`](../benchmarks/comparison.py)
produces the two-column result per fault. The table is mixed, as expected, and
on one row it is inverted:

| scenario | ASTRA | Core-A raw |
|---|---|---|
| control | **0.009 m** / 0 ticks out | 0.055 m / 0 |
| `imu_dropout` | **4.199 m / 73 ticks out** | **1.707 m / 0** |
| `position_drift` | 2.025 m / 34 | 2.001 m / 27 |
| `position_bias` | 0.931 m / 0 | 0.960 m / **5** |

**The dropout row is the finding, and it sharpens OD-9 rather than contradicting
it.** A frozen position reading is maximally self-consistent, so the filter grows
confident in it, and keeping *"y is not changing"* consistent with the motion
model forces the conclusion that the vehicle is not turning. True heading reaches
0.0686 rad while the estimate reports 0.0017 rad — a fortyfold understatement of
the one state nothing observes (E-58). The fault propagates out of the channel it
entered, and proposer and gates alike then read the result.

**Read it narrowly.** The baseline avoids this only because it is handed a true
heading no sensor publishes, so it is not realisable; on the control run that
same generosity leaves it worse than ASTRA. The row measures the filter's
failure mode under a frozen sensor, not a case for removing the filter.

**Still open:** the third arm — gates removed, UKF kept — which is P3.4's
ablation and is what would attribute the difference to a layer.
**Estimate:** met. The ablation is costed under P3.4.

---

# P4 — Parallelisable across people

## ~~P4.1 — Dashboard (work plan §5.1)~~ — DONE, 10 Aug 2026

FastAPI + WebSocket backend, React + Recharts frontend, rendering the pipeline
diagram itself: Trust Index gauge; **L6 and L7 as separately lit paths** — the
visual proof of gate independence; `P_f` visibly widening and narrowing the
acceptance band; the FSM as a lit state diagram; RCM's knowledge-base search,
shadow execution and a **"SAFE EXPLORATION ENGAGED"** banner; an event ticker
with independent-cause attribution.

**Rule:** every number on screen must trace to a live `DecisionRecord`. Nothing
scripted, nothing interpolated.

### Built, 10 August 2026 — [`demo/dashboard.py`](../demo/dashboard.py)

Live: the three gates lit separately with their reason codes, Trust Index, the
fail-safe state and OOD counter, the issued command and its origin, the
quantile, stream health, an event ticker — and the trace that matters, **the
estimate against the truth on one axis with the ±1.75 m corridor drawn**.

**The rule is structural, not a promise.** `Frame` is a pure projection of one
`TickSample`, and every field is asserted against the specific record attribute
it claims to come from (E-78). `test_every_field_is_declared_as_record_or_simulator`
fails if a field is added without declaring which of the two it is, which is
exactly how the distinction would otherwise erode.

**Exactly three fields are simulator-sourced** — `truth_y`, `truth_speed`,
`fault_active` — and they are on screen for a reason worth stating: **OD-9 is
invisible without them.** A page showing only what the system knows renders E-46
as a completely nominal run.

**Two deviations from this entry, both deliberate.**

*No React, no Recharts, no FastAPI, no WebSockets, no build step, and no new
dependency at all.* Server-Sent Events over `http.server` and one static HTML
page. P4.3 removed FilterPy because an unmaintained dependency inside a safety
repository is a qualification argument nobody wants to write, and it dragged
scipy, matplotlib and pillow behind it; adding a Node toolchain to that
repository for a *demo* would contradict the discipline that makes the rest
credible. Telemetry is one-way, which is what SSE is for.

*It took a day, not ten.* The entry costed a front-end project. What was
actually needed was a projection with tests and a page that draws two lines.

**It found something.** See P4.2.

**Estimate:** met.

## ~~P4.2 — Interactive fault injection (work plan §5.2)~~ — DONE, 10 Aug 2026

**The injection machinery exists.** [`training/faults.py`](../training/faults.py)
provides five sensor-fault kinds with recorded ground truth, verified by 27 unit
tests and 9 integration tests including a mutation test that fails on a no-op
injector; [`benchmarks/fault_study.py`](../benchmarks/fault_study.py) runs each
one against a clean control. Placement and the reasoning behind it are
[ADR-0022](adr/0022-faults-are-injected-at-the-sensor-boundary.md).

What remains is the front end: let an audience press the button — a demo where
the observer chooses the fault cannot be staged. **Capture a pre-recorded
fallback run before any live demonstration.**

**A note for whoever builds the demo.** As of 9 August the honest demonstration
is not *"watch the gates catch it."* It is E-46: watch a sensor fault put the
vehicle two and a half lane widths out of its corridor while every gate reports
NOMINAL, then watch the same run with the fault closed. That is a better
demonstration than the one originally planned, and it is the one the evidence
supports. **Do not build a demo that requires OD-9 to be fixed first** — build
the one that shows it, and show the fix when there is one.

### Done, 10 August 2026

Five buttons — dropout, position bias, position drift, speed frozen, lateral
noise — each arming a 400-tick window from the current tick on the running
injector. The observer chooses; nothing is staged. An unknown fault is refused
with 400 rather than silently arming nothing, because a button that appears to
work and does not is worse than no button.

**The fallback run this entry asked for by name exists.** `--record` writes
every frame to JSONL while driving; `--replay` streams one back at the captured
rate with the buttons refused (409 — the faults in a recording already
happened). A recording is exactly the frames the live run produced, so a replay
is as traceable to `DecisionRecord`s as the run that made it. `var/demo/` holds
a 1,200-frame capture with a dropout armed at t468.

### And it found something the fault study had missed

Every study so far ran its fault to the end of the run. The demo arms a window
that **closes**, and what happens at the closing tick is the finding (E-76):

| dropout | vetoes | first veto | fail-safe | final \|dev\| |
|---|--:|---|---|--:|
| persists to the end | **3** (startup only) | **never** | NOMINAL ×800 | **35.705 m** |
| closes at t600 | 203 | **t600, exactly** | → DEGRADED → LIMP → **HALT** | 21.847 m |

**The blindness lasts exactly as long as the lie.** While the sensor keeps
lying nothing fires and the departure grows without bound — 4.199 m over 200
ticks, 35.705 m over 600. The instant it recovers, all three gates fire and the
graduated response works exactly as designed. It simply cannot start until the
corrupted channel stops being corrupted.

**Estimate:** met.

## ~~P4.3 — Replace FilterPy (work plan §6.1)~~ — DONE, 10 Aug 2026

Last released **2018**, unmaintained, inside the safety path, and it drags
`scipy`, `matplotlib` and `pillow` into a dependency tree that ISO 26262 §8-12
will require a qualification argument for — one per package. `stubs/filterpy/`
already enumerates the exact surface depended on, and it is small.

**Exit met, 10 August 2026.** `filterpy` is gone from `pyproject.toml`, and so
are `scipy`, `matplotlib` and `pillow` — the tree it pulled in behind it, none of
which `src/astra/` ever imported. `stubs/` is deleted with it: the UKF is
first-party and strictly typed, so there is no untyped surface left to declare.

The replacement is `astra.layers.l2_estimation.unscented`, ~250 lines, and it
**matches FilterPy's algorithm rather than improving it** — including computing
the gain as `Pxz @ inv(S)` where `solve` would be better conditioned. Replacing
a library and improving its numerics in one change makes any difference
unattributable to either, and this filter's outputs are what the evidence pack
rests on. The `solve` change is a separate one, and now a measurable one.

**Accuracy unchanged, and measured rather than asserted.** The fault study, the
detector table and the comparison harness all reproduce **every** recorded
figure exactly (E-68). Against FilterPy directly the agreement is 6e-10 on the
state over 2,000 steps, with sigma points and weights bit-identical; the
residual is SciPy's upper-triangular Cholesky against NumPy's lower-triangular
one and cannot be removed without keeping SciPy (E-69).

### It found something, which is the part worth reading

Writing the test that checks the replacement against the **textbook Kalman
filter** — rather than against the library — turned up **OD-10**. The update
reuses the sigma points `predict` pushed through `fx`, whose spread carries no
process noise, so the innovation covariance is short by exactly `H Q Hᵀ`. At the
simulation operating point that is not a rounding matter: `Q` diag is
**0.02 / 0.05 / 0.3** against `R` diag **0.01 / 0.0001 / 0.0016**, inflating the
Mahalanobis distance by **1.73×, 22.4× and 13.7×** across the three observed
channels (E-70).

It is **inherited, not introduced** — the behaviour is FilterPy's and has been in
every number this project ever recorded. It is also, for now, harmless in
verdict terms: the corpus was calibrated on the same inflated statistic, so
calibration and runtime are self-consistent. What it invalidates is the *name*.
The recorded `fast_innovation` is not a Mahalanobis distance, so it may not be
compared against a chi-squared expectation, against a distance computed
elsewhere, or across a change to `Q`.

**Also surfaced:** `benchmarks/soak.py` imported matplotlib and never declared
it. The import resolved by accident for as long as FilterPy pulled scipy, which
pulled matplotlib. It is now a declared benchmark-group dependency — a hidden
dependency becoming visible, not a new one appearing.

**Estimate:** met.

## ~~P4.4 — Test domain independence for real (work plan §6.2, assumption A-1)~~ — DONE, 10 Aug 2026

NFR5 is asserted, structurally defended, and never tested. Add a genuinely
non-automotive profile — a warehouse AGV, a two-channel differential-drive robot
— and get it through the pipeline **without touching `src/astra/` outside
adapters**.

**Exit met, 10 August 2026, and it was the second outcome.**
[`training/warehouse.py`](../training/warehouse.py) is a differential-drive AGV —
two wheels in rad/s, no throttle, no brake, no steering angle, turning on the
spot. Driven at the pipeline, it meets four walls (E-72 – E-75, **OD-11**):

| | wall | kind |
|---|---|---|
| 1 | `assemble_pipeline` has 14 parameters and **none accepts an actuation space** | refactor |
| 2 | The command projector is equally fixed, and divides by a *steering effectiveness* | refactor |
| 3 | **L2's process model is a bicycle model** — propagates `0.000000` heading change for a platform pivoting at zero speed | **migration** |
| 4 | `astra.kernel` names road friction, tyre wear, highways, rain | refactor |

**The claim holds for the gates and fails for the plumbing.** L3, L6, L7a and
L7b took the AGV unchanged, because every input they read is a number with a
unit. What is automotive is the composition root, the process model and the
vocabulary.

**A-1's own "impact if wrong" called it**: *"Extracting vehicle vocabulary from a
core that has absorbed it is a migration, not a refactor."* Walls 1, 2 and 4 are
the refactor. Wall 3 is the migration.

Every wall is pinned as a **strict xfail**, so closing one turns the suite red
and forces the evidence row to be rewritten rather than quietly outgrown.

**Not fixed here, deliberately** — the same discipline as OD-9 and ADR-0020.
Walls 1, 2 and 4 are perhaps 2 days; wall 3 means making the process model an
injected strategy, which touches the layer every gate reads and needs its own
measurement that the automotive numbers are unchanged.
**Estimate:** met for the test. **3–5 days** for walls 1, 2 and 4; wall 3 is
its own item.

## ~~P4.5 — Security threat model (work plan §6.4)~~ — DONE, 10 Aug 2026

[`THREAT_MODEL.md`](THREAT_MODEL.md) is written. It enumerates seven assets, the
two trust boundaries — one enforced as a type error, one assumed entirely — and
five adversary tiers, and it states the asymmetry plainly: **ASTRA defends
thoroughly against a proposer that is wrong and not at all against a platform
that is compromised**, which is the larger surface because everything the first
defence relies on lives there.

Three of this session's *safety* findings turned out to be security findings:

- **OD-9 is an attack primitive.** An adversary who can influence one sensor
  channel has a measured path to a 4.199 m lane departure that produces clean
  evidence the whole way (§5.1).
- **Veto authority is concentrated.** Disarming L7b removes essentially all of
  it, so an attacker choosing one target has an obvious one (§5.2, E-59).
- **Recorded provenance is not verified integrity.** Corpus, twin and
  configuration digests are written into the evidence and checked against
  nothing at load, so substituting the corpus yields a run that faithfully
  records the attacker's digest (§5.3).

**The model's cheapest item is also now done.** The evidence log is a hash chain
— each record carrying the digest of the serialised line before it — so
alteration, deletion, insertion and reordering are all detected (E-66). **N-10
is closed.** Two limits are asserted as tests rather than left in prose: tail
truncation and a consistent whole-file rewrite are both undetectable by chaining
alone (E-67), and closing either needs signing, which needs key management.

**Still open**, and now itemised rather than lumped under "no security posture":
verify artefact digests at load against a manifest; wire the stream-health gate
(P2.7); require sensor redundancy; and a platform security argument, which is
not this project's work and without which §5.6 is void.

**Estimate:** met.

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
| P2 | 9–15 | Includes P2.7, added 9 August after the fault study found OD-9 |
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
