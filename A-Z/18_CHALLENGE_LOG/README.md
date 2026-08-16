# 18 · Challenge Log

Every challenge as: **Problem → Root cause → Investigation → Attempts → Failed
attempts → Final solution → Remaining risk.**

**[FACT]** — the `C-` entries are read from `docs/DECISION_LOG.md` Part 4, which
opens: *"These are here because a log of only good decisions is a brochure."*

---

## Part A · The engineering mistakes — the `C-` register

### C-1 · `str.replace("", new)` on a 63 KB file

**Problem.** A branch became unpushable.

**Root cause.** Python's `str.replace` with an **empty** first argument inserts
the replacement **between every character**.

**Cost.** A **210 MB blob**, an unpushable branch **for four days**, and a history
rewrite.

**Final solution.** `make blobsize`, which *scans the filesystem* rather than the
index — so the file is caught before it is ever staged.

**Remaining risk.** Low. **[INTERPRETATION]** The lesson generalises past this
bug: an operation whose degenerate case is catastrophic needs a guard, not care.

---

### C-2 · The plant integrated 2.5× faster than the controller

**Problem.** Policies behaved differently in training and in the pipeline.

**Root cause.** `step_seconds` was **0.02** while the tick period was **0.05** —
and **the docstring said 0.05.**

**Cost.** **Every policy trained before 5 August was invalidated**, and L7b's
jerk bound was being evaluated against a plant moving 2.5× too fast.

**Remaining risk.** The class of defect — a documented constant disagreeing with
the code — is the one this project has hit most often. **[INTERPRETATION]** It is
why so many constants are now asserted against their consumers by a test.

---

### C-3 · A reward term ~500× too small

**Problem.** The trained policy **stopped the vehicle** and collected the
stationary reward.

**Root cause.** `action_rate_weight` was 6.0 against a task reward capping at
2.0, so a step at exactly L7b's jerk limit cost **one part in ten thousand**.

**Failed approach it condemns.** Folding constraints into the reward as
penalties. The constraint had not been weakened — it had effectively **vanished**.

**Final solution.** The Lagrangian dual, where budgets stay legible as budgets.

**Remaining risk.** **[OPEN]** No mechanism checks that a reward term's magnitude
is commensurate with the reward it modifies.

---

### C-4 · Four wrong measurements in a row

**Problem.** ADR-0020's effectiveness measurement went wrong **four consecutive
times**.

**Root cause.** **Tick pairing** — between the command, the plant's truth, and the
sensor reading. Off-by-one in *which* tick's truth pairs with *which* command.

**Cost.** Read the effectiveness **12–18% low**, and *"looked entirely plausible
while doing so."*

**[INTERPRETATION]** The most instructive entry in the register. A measurement
that is obviously broken gets fixed in minutes. One that is quietly 15% off gets
**published**.

**Remaining risk.** Real. Tick pairing is easy to get wrong and hard to see.

---

### C-5 · A context tuned by intuition inverted the result

**Problem.** A signature that *looks like* clear highway sat in permanent
`SAFE_EXPLORATION`.

**Root cause.** Component 2 of the signature is **ego-speed over the legal
limit** — 0.375 against a centroid expecting something else. It was tuned by what
the component *sounded like*.

**Learned.** Read a vector's components from their **definition**, never from
their name.

---

### C-6 · Overstating OD-10 as "22×"

**Problem.** A register row overstated what was broken.

**Root cause.** 22.4× is the **per-channel algebraic bound**; the realised effect
was **1.53× / 1.23× / 1.024×**.

**Final solution.** **The row was corrected rather than quietly amended**, because
*"a register that overstates what is broken loses trust as fast as one that
understates it."*

**[INTERPRETATION]** Worth dwelling on. Overstating a defect feels like caution.
It is not — it spends the same credibility as understating one.

---

### C-7 · `--delete-excluded` wiped the trained artefacts

**Problem.** An rsync destroyed `~/astra/var` — twin, corpus and policy.

**Final solution.** Restored from tracked Windows copies; would have cost a
retrain otherwise. Now named in the environment notes.

**Remaining risk.** Moderate. **[INTERPRETATION]** The artefacts are gitignored by
design, so the only defence is a second copy — which is a convention, not a
mechanism.

---

### C-8 · `None` rendered as `0.0`

**Problem.** A dashboard would have shown **commanded stop** on every healthy
tick.

**Root cause.** A snapshot's `speed_cap` of `None` — meaning *"no cap applies"* —
rendered as `0.0`, which means *"stop"*.

**Caught by** running the dashboard, **not by a test** — every fixture had set a
cap.

**[INTERPRETATION]** A whole class of defect lives here: a *sentinel* and a
*value* that render identically. The fixtures were all realistic and all wrong in
the same direction.

---

### C-9 · Two integration tests asserted a defect

**Problem.** Fixing a defect **broke two passing tests**.

**Root cause.** They pinned the broken behaviour — correctly. One said so in its
own comment: *"pinned so that a future change which fixes it fails here and has
to say so."*

**Final solution.** Rewritten to assert the new truth, keeping the still-broken
half pinned.

**[INTERPRETATION]** This is the system working. A test that pins a known defect
**must** fail when the defect is fixed, or the fix lands silently.

---

### C-10 · An integration rig published one modality of five

**Problem.** Two tests failed on a change that was working correctly.

**Root cause.** The rig published a single sensor modality. **Harmless while
nothing read stream health** — and *"a vehicle with four dead sensors"* once L8
did.

**Learned.** A test fixture encodes assumptions about the world, and those
assumptions **expire** when the code learns to read something new.

---

### C-11 · A forensic tool shipped with no tests, gate green

**Problem.** `astra explain` — a module a safety case would lean on — shipped at
**10.3% coverage** in a pushed commit.

**Root cause.** The 95% gate is an **aggregate**. 94 uncovered statements against
several thousand move it by less than a tenth of a point.

**Final solution.** A per-file floor at 80% (D-18), and 29 tests.

**The uncomfortable part.** The aggregate was **always true**. What it never
licensed was a statement about any *particular* module — *"same shape as OD-2 and
OD-7, with the novelty that the check was the quality gate."*

---

## Part B · The categories the brief asks about

| Category | Representative challenge |
|---|---|
| **Algorithmic** | Five drift detectors, all refuted by one shared cause (`E-107`) |
| **Mathematical** | The conformal index `⌈(n+1)(1−ε)⌉`, and the infinite-threshold case |
| **Integration** | C-10 — a rig whose assumptions expired |
| **Accuracy** | C-4 — 12–18% low, and plausible |
| **Stability** | OD-5's unbounded counter, 1,508 by tick 2,000 |
| **Safety** | OD-6 — 99,808 commands issued under a blocking verdict |
| **Simulation** | The four-way bicycle-model coincidence |
| **Data** | OD-8 — exchangeability violated in-house |
| **Environment** | The quality gate runs **only in WSL2**; the Windows host is blocked by Smart App Control |
| **Testing** | Every major defect found by running, not testing |
| **Validation** | `[M-ext]: 0 of 30` |
| **Hardware** | CARLA has **no macOS build** — the constraint that replaced RK-1 |

---

## Part C · The three retractions, as a challenge

**Problem.** Three numbers published on 15 August had to be withdrawn.

**Root cause — identical in all three.** A conclusion **assembled correctly from
an observation nobody checked was adequate.**

| | Claimed | Actually measured |
|---|---|---|
| `E-143` | A detector separates a drift 7.35× | A vehicle with **400/400 ticks vetoed, speed zero** |
| `E-145` | An artefact is missing | An `ls` truncated **one line above it** |
| `E-161` | 100% inside | **One** sample |

**Investigation.** The first was caught by noticing two *different* proposers
produced **bit-identical numbers** — impossible if the proposer mattered.

**Final solution — mechanisms, not resolutions.**

| | Guard |
|---|---|
| E-143 | `StationaryVehicleError` — *a benchmark measuring a closed-loop property must refuse to run when the loop is open* |
| E-145 | `make artifacts-check` — *presence is not the check; driving is* |
| E-161 | A minimum-sample guard — *a fraction from n=1 is not a weaker measurement, it is a different kind of thing* |

**Remaining risk. [OPEN] and real.** Three guards cover three specific shapes.
The **general** failure — a valid computation in an invalid configuration — has
no general defence.

### And one of the three guards has since gone wrong — measured 16 August 2026

**`benchmarks.whiteness` cannot be run at all.** With the trained policy named
explicitly it raises `StationaryVehicleError` and produces nothing.

**The cause is not the one the message states.** The guard fires on
`final_speed_mps <= 1e-6`, and the arm that trips it is `imu_dropout`, where the
run is:

```
arm             vetoed   final m/s   final |dev|
control              1     12.0907        0.0168   ok
imu_dropout         18      0.0000        0.0620   REFUSES
lateral_noise      126      4.2137        1.3073   ok
```

The vehicle **drove, detected the fault, and was brought to a stop by its own
fail-safe.** That is the mechanism working. The guard reads the stop as *"the
loop was never closed"* and refuses.

**[INTERPRETATION] The guard cannot distinguish a policy that never drove from a
safety response that correctly stopped the vehicle** — and the second became
possible only after ADR-0024 and ADR-0030 gave the fail-safe a stopping response
to a dark sensor. A guard written against one failure was invalidated by a later
feature, and nothing caught it because **nobody re-ran the benchmark.**

**The consequence for the evidence pack: `E-143` is not reproducible today.** It
is cited in this folder as one of the five refuted drift detectors, and it cannot
currently be regenerated. **[OPEN]** — the guard needs to test *whether the loop
closed*, not *whether the vehicle is moving at the end*.

**The generalisable lesson, and it is sharper than the original one.** A guard is
a claim about what a valid configuration looks like, and **claims go stale
exactly like numbers do.** This project pins its schema version with a test and
asserts each invariant's enforcement kind with a test — and its three retraction
guards were asserted by nothing that would notice them becoming wrong.

### Fixed the same day

The guard now asks the question it always meant to ask. It counts the ticks on
which **the loop was actually closed** — a command reached the actuators *and*
the vehicle was moving — and raises only when that count is zero. An arm with
some live ticks but fewer than 30 is **reported as thin** rather than quoted or
refused, which is `E-161`'s shape applied to a second benchmark.

**Five tests now assert the rule**, including the one that would have caught this:
*liveness is per tick, so a correct safety stop keeps its earlier ticks.*

**Re-run, the benchmark produces a result again — and it is the same conclusion:**

| arm | live ticks | lateral-acceleration CUSUM | alarm |
|---|---|---|---|
| control | 200 | 3.75 | — |
| **`position_drift`** | **200** | **3.75** | **—** |
| `imu_dropout` | **41** | 77.63 | +2 |
| `lateral_noise` | 200 | 888.92 | +1 |

**`position_drift` does not alarm. E-107 stands.** And the arm is now
**identical to the control on every component, to every digit the report prints** — because ADR-0033's
redundancy outvotes the drift before it reaches the estimator, so the separation
`E-143` recorded as 1.03× is now exactly **1.00×**. The refutation got stronger,
and `E-143`'s number needs updating rather than its conclusion.

`imu_dropout` reports **41 live ticks** of 200 — the fail-safe stopping the
vehicle, now visible in the table instead of killing the run.

---

## The pattern across everything

**[INTERPRETATION]** Reading all fourteen together, one shape dominates:

> **Almost every challenge here is something being quietly wrong while looking
> right.** A docstring that disagreed with a constant. A measurement 15% low and
> plausible. A sentinel rendering as a value. An aggregate that was true and
> licensed nothing. A detector measured where its mechanism could not operate.

Loud failures were cheap; every expensive one was **plausible**.

Which is why the mechanisms that came out of them are all of one kind: they do
not make the system better, they make a **specific class of plausible-looking
wrongness impossible to publish**.

---

## You should know this before moving on

**Questions you should be able to answer**

1. Why is a measurement that is *quietly* 15% wrong worse than one obviously
   broken?
2. Why did fixing a defect **break two passing tests**, and why was that correct?
3. Why does overstating a defect cost the same credibility as understating one?
4. What do all three of the 15-August retractions share, and why does no general
   defence exist?
5. Why did a 95% coverage gate fail to catch a module at 10.3%?

**Misconception to avoid**

> *"A challenge log this long suggests a troubled project."*
>
> Compare like with like. The relevant comparison is not *"how many mistakes did
> this project make"* — every project makes these — but **"how many did it find,
> write down, and build a guard for."** Fourteen entries, each with a mechanism
> attached, is a project that is looking. The alternative is the same mistakes,
> unlisted.

---

**Next:** pass 7 — `19_TRADEOFFS`, `20_ALTERNATIVES`, `21_BENEFITS`,
`22_LIMITATIONS`.
