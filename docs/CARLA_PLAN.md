# ASTRA — The CARLA plan

**Written** 15 August 2026, after the register reached 16 closed / 1 reclassified /
1 partly closed / 3 open and every in-house item was either done or blocked on a
real simulator.

---

## 1 · What CARLA is actually for

One number:

> **Rows at [M-ext]: 0 of 30.**

Every measurement this project has is `[M-syn]` — taken on a plant it also wrote.
The digital twin, the calibration corpus and the trained policy all descend from
the same kinematic bicycle model, so **the generator and the judge agree by
construction.** That is stated at the top of the credibility matrix and it is the
single largest thing a reviewer can hold against the work.

CARLA is not "the next feature". It is the only thing that moves a row from
*"this machinery runs"* to *"this machinery is correct against something we did
not author"*. Nothing else on the backlog can do that, which is why three of the
four remaining register rows are waiting on it.

**What it is not for:** making the numbers better. Several will get worse, and §5
predicts which, in advance, on purpose.

---

## 2 · What has to be built

Four things, and only the first is large.

### 2.1 · The adapter — `src/astra/adapters/carla/`

`.importlinter` has forbidden `carla` anywhere in `astra` since Phase 1, and that
contract **stays**. The adapter is the one place the name may appear, and it is
the reason [ADR-0002](adr/0002-domain-independent-platform-core.md)'s promise
exists at all.

It supplies, against ports that already exist:

| port | what CARLA gives it |
|---|---|
| `SensorSource` | IMU, GNSS, and a lidar/camera-derived lateral position, published per modality with real timestamps |
| `MeasurementExtractor` | the three position channels ADR-0033 fuses by median |
| `IntegrityMonitor` | the same residual monitor, unchanged |
| `CommandProjector` | throttle/brake/steer, real steering effectiveness |
| `ActuationSpace` | the automotive space, which is genuinely correct here |

**[ADR-0034](adr/0034-the-composition-root-accepts-a-platform-instead-of-being-one.md)
is what makes this possible**, and it named the four coordinated things an
adapter must bring: space, projector, policy, and a matching
`twin.control_effectiveness` row. CARLA needs all four and a profile of its own.

### 2.2 · The driver — `training/carla_loop.py`

`drive_closed_loop` **owns its plant**: it constructs `SyntheticDrivingEnv`,
steps it, and reads truth back for the deviation metric. CARLA cannot be dropped
into that — the simulator owns the clock, the tick is `world.tick()`, and ground
truth arrives as an actor transform rather than a state vector.

So this is a **sibling**, not a parameter. It must reproduce three properties or
the evidence is not comparable:

1. **The injected `Clock`** ([ADR-0010](adr/0010-injected-clock.md)) driven from
   CARLA's simulation time, not wall time.
2. **Faults at the sensor boundary, never inside the core**
   ([ADR-0022](adr/0022-faults-are-injected-at-the-sensor-boundary.md)) — the
   same `FaultInjector`, applied to the CARLA payloads.
3. **The same audit sink**, so a CARLA run and a synthetic run produce records a
   single reader can compare.

### 2.3 · A CARLA profile

`config/environments/carla.toml`. Every A-4 threshold declared afresh — they are
operating points and the synthetic ones were tuned against a different plant.
`failsafe.capabilities` and `integrity_ceiling` carry over unchanged; they are
statements about the vehicle, not about the simulator.

### 2.4 · The run guard — and this one is not optional

**Three times on 15 August a number was assembled correctly from an observation
nobody checked was adequate** (E-143, E-145, E-161): a detector measured on a
vehicle that never moved, a file declared missing from a truncated listing, and
`100% inside` reported from one sample.

`make artifacts-check` exists because of the first. **CARLA needs its
equivalent before the first evidence run, not after**: refuse to report from a
drive where the vehicle did not move, where every tick was vetoed, or where the
simulator dropped frames. Cheap, and it is the difference between a finding and
a retraction.

---

## 3 · The order, and why it is not negotiable

[`DATA_SPLIT_PROTOCOL.md`](DATA_SPLIT_PROTOCOL.md) governs, and it splits at
**segment** level, never tick level. The order below is that document applied.

| # | step | produces | must not touch |
|---|---|---|---|
| 1 | Adapter + driver, against a **stationary** actor | the seams work | any metric |
| 2 | **TRAIN** segments | a CARLA-fitted twin | CALIBRATE, TEST |
| 3 | **CALIBRATE** segments | the Mondrian corpus, MMD reference | TEST |
| 4 | Per-class sufficiency check | ≥500 samples per reachable class | TEST |
| 5 | **TEST** — the evidence run | every `[M-ext]` row | — |

**Step 5 happens once.** A TEST set looked at twice is a validation set, and the
protocol says so. Every temptation to "just re-run with a tweak" after seeing the
numbers is the thing that discipline exists to refuse.

**Step 4 is the one people skip.** `RAIN_NIGHT` is already unreachable on the
synthetic classifier — it needs an input the fast state vector does not carry —
and a class with no calibration samples means L6 abstains there permanently.
Better to know before the evidence run than to explain it after.

---

## 4 · The policy question, and the answer that makes this interesting

E-155 found that `train_policy` trains against `SyntheticDrivingEnv` **directly**
— no pipeline, no UKF, no sensor bus. So the proposer has only ever seen ground
truth on a bicycle plant, and in CARLA it meets a different plant *and* an
estimate for the first time.

It will drive badly. There are two responses, and picking the wrong one throws
away the whole point.

**Retrain in CARLA.** Best driving, and it quietly destroys the thesis: a
proposer fitted to the test plant is no longer untrusted, and the governance has
nothing left to govern.

**Transfer the synthetic policy.** Core-A is genuinely out of distribution — and
***that is precisely the case this architecture exists for***. ASTRA's claim is
not "our proposer is good". It is *"an untrusted proposer can be governed"*. A
policy that transfers badly is not an embarrassment in the demo; **it is the
demo.**

**Run both, and lead with the transferred one.** The retrained arm is the control
that says how much of the degradation was the plant and how much was governance.
This is exactly the shape of `benchmarks/platform_transfer.py` and ADR-0023's
bounded-exploration argument, one level up.

---

## 5 · What will break — predicted before running

The project's standing method is to predict, then measure, and keep the
refutations. These are falsifiable and dated.

| # | prediction | why | what it would mean if wrong |
|---|---|---|---|
| P1 | **OD-8 gets worse, not better.** L6's live scores land outside the CARLA corpus | The synthetic corpus is from another plant entirely; even a CARLA corpus faces a policy that transfers badly | Exchangeability is more robust than in-house measurement suggested |
| P2 | **The twin is badly wrong.** Non-conformity scores rise sharply | The PINN learned bicycle kinematics; CARLA has suspension, tyre slip, drivetrain lag | The bicycle model is a better approximation than assumed |
| P3 | **L7a finally fires.** The corridor bound is reachable in real driving | It vetoed once in ~500,000 synthetic ticks (OD-3, E-162) because nothing ever left the corridor | L7a's thresholds are wrong, not its traffic |
| P4 | **The gate census inverts.** L6 stops being silent and starts vetoing constantly | Its silence today is OD-8 — scores below the corpus. Out-of-distribution driving moves them the other way | The gate is insensitive rather than mis-calibrated |
| P5 | **Wall 3 does not bite.** The bicycle process model is adequate | CARLA drives a car; the model is wrong for a warehouse AGV, not for this | A road vehicle needs more than a bicycle model, which is a real finding |
| P6 | **The fail-safe halts more often** | Real sensors are noisier and drop frames; `integrity_tolerated_faults = 0` in every profile | The integrity thresholds transfer, which would be a genuine result |

**P3 and P4 are the ones worth caring about.** Today two of three gates judge
every tick and never object (E-162). If CARLA makes them object, the
three-gate independence claim gets its first real support. If it does not, the
paper's contribution 2 needs rewriting further than §4 item 5 already says.

---

## 6 · Risks

**RK-8 (High, credibility) — the roadmap already names it, and it is rhetorical
rather than technical.** The failure mode is presenting CARLA numbers as though
they validated the architecture when they validate a prototype on one simulator,
in one town, on one seed. The mitigation is the same discipline that has held all
along: every row keeps its marker, `[M-ext]` means *this simulator*, and no
false-positive or false-negative rate is quoted until one has actually been
measured.

**The demo can fail closed.** If the transferred policy is bad enough that every
tick is vetoed, the vehicle stops and there is nothing to show. Mitigated by the
§2.4 guard, by running the retrained arm as a control, and by ADR-0023's bounded
exploration — which exists exactly to keep a vehicle moving outside its certified
envelope.

**CARLA is Linux-only and heavy.** ADR-0015 settled the interpreter question
(0.9.16 ships `cp312`), and the practical constraint stands: this runs in WSL2
where the quality gate already runs, and it will not run on the Windows host.

**One town is one town.** Town04 gives highway, urban and tunnel. It does not
give a different vehicle, a different sensor suite, or weather beyond CARLA's
model. `[M-ext]` earned here is narrower than it sounds and the matrix should say
so in the row, not in a footnote.

---

## 7 · Exit criteria

1. The adapter satisfies its ports with **no change to `src/astra/`** beyond what
   ADR-0034 already made injectable. If the core has to change, NFR5 was weaker
   than believed and that is the finding.
2. `lint-imports` still passes: `carla` appears nowhere outside `adapters/`.
3. TRAIN / CALIBRATE / TEST are disjoint **segments**, recorded in the run
   manifest, and TEST was run once.
4. The seven-phase continuous drive completes without the vehicle stopping —
   or it stops and the reason is in the audit log, named, with the posture that
   produced it.
5. Every P1–P6 prediction above is marked **confirmed or refuted**, with numbers,
   and the refutations are kept.
6. The register's `[M-syn]` rows carry a second column: what the same measurement
   said in CARLA.

---

## 8 · What this plan deliberately does not do

**OD-11 wall 4** (rename `ContextClass` and `SLOW_STATE_FIELDS`) — still deferred.
It needs a second *domain*, and CARLA is the same domain. Doing it now would cost
a regeneration and prove nothing.

**OD-11 wall 3** (the bicycle process model) — P5 predicts it will not bite in
CARLA. If P5 is right, wall 3 stays open honestly, as a claim about warehouse
AGVs that no automotive result can settle.

**A second real platform.** The adapter proves the seam takes *a* platform. It
does not prove domain independence, and §7 item 1 is the strongest claim
available from this work.
