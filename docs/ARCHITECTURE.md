# ASTRA — Architecture

How the system is put together, and why it is put together that way.

This document describes the architecture the repository implements and the architecture the
repository is *shaped for*. Those are not the same thing, and the difference is stated
explicitly wherever it matters: Phase 1 delivers the vocabulary, the contracts, the interfaces,
the invariants, the configuration and the evidence machinery. It delivers **no layer logic at
all**. What each later phase adds is in [`ROADMAP.md`](ROADMAP.md).

Related documents:

| Document | Answers |
|---|---|
| [`SEPARATION_INVARIANTS.md`](SEPARATION_INVARIANTS.md) | The safety argument, invariant by invariant, with its enforcement in code |
| [`DOCUMENT_RECONCILIATION.md`](DOCUMENT_RECONCILIATION.md) | Every contradiction found across the source documents and how it was resolved |
| [`ROADMAP.md`](ROADMAP.md) | What each future phase builds, and on what |
| [`ENGINEERING_HANDOFF.md`](ENGINEERING_HANDOFF.md) | The master context document this architecture was consolidated from |

---

## 1. The governing idea

An AI controller in a safety-critical system can be structurally healthy — no bit flips, no
crashes, correct by every classical definition — and still issue a semantically wrong command to
a physical actuator, because the world it faces at runtime no longer matches the world it was
trained in.

The existing infrastructure does not address this failure mode. Lockstep processors replicate
the same wrong answer on both cores. Hypervisors isolate execution domains without inspecting
what crosses them. Hardware security modules authenticate a command's origin, not whether it was
a good idea.

ASTRA does not attempt to make the learned controller provably safe; that is an open problem.
It takes a narrower and tractable position:

> **The AI controller is an untrusted proposer. An independent governance pipeline sits between
> it and the actuators, and governs the actuation boundary.**

Three consequences follow directly, and they shape every decision in the codebase.

1. **The proposer must not be able to observe its own judge.** Anything an optimiser can see, it
   can learn to exploit. This is separation invariant SI-5, and it is why
   `CommandProposer.propose` in `src/astra/ports/pipeline.py` accepts state and trust and
   nothing else — no verdict, no fail-safe state, no calibration table.
2. **A single component must own the actuation boundary**, or the boundary is not a boundary.
   This is SI-7, and it is why `IssuedCommand` in `src/astra/contracts/actuation.py` refuses
   construction by any component whose layer is not `L9_RCM`.
3. **A veto must be unconditional**, or the strongest claim in the safety argument is advisory.
   This is SI-3, and it is why `Verdict.merge` in `src/astra/kernel/enums.py` is a fail-closed
   fold and not a vote, a weighted score or a majority — and why an *empty* verdict set merges
   to `VETO`.

What ASTRA claims is defence in depth through gates with structurally different failure modes.
It does not claim to eliminate hallucination, and it does not claim zero false negatives; the
target is < 1%, and it is a target rather than a measurement. See
[Honesty boundaries](#10-honesty-boundaries).

---

## 2. The four execution domains

The pipeline is partitioned into four isolation domains. In the software prototype these are
processes; in the production target they are separate silicon with different integrity levels.
The mapping from layer to domain is not documentation — it is a total function in code,
`LayerId.execution_domain` in `src/astra/kernel/enums.py`, backed by the `_LAYER_DOMAIN` table.

| Domain | Layers | Integrity target | Role |
|---|---|---|---|
| `SHARED` | L1, L2, L3 | — | Sensor bus, state estimation, trust estimation. Read by both cores. |
| `CORE_A` | L4 | QM / ASIL-A | The untrusted proposer. Learned, optimising, replaceable. |
| `CORE_B` | L5, L6, L7, L8 | ASIL-D(D) | The safety island. Three gates plus the fail-safe machine. |
| `ARBITRATOR` | L9 | — | Runtime Calibration Management. The sole issuer of actuator commands. |

The `CORE_A → CORE_B` boundary is **asymmetric and unidirectional**. Core-A may write one
proposed command per tick into Core-B; it may read nothing back — not a verdict, not a fail-safe
state, not a calibration table, not a quantile, and specifically not Core-B's veto rate (SI-6).
In the software prototype this is a one-way queue, delivered in Phase 3. In the production
target it is an AXI4-Lite bridge. Phase 1 expresses it in the port signatures, which is the part
of the enforcement that does not depend on the transport.

L3 (the Trust Module) sits in `SHARED`, not in Core-B. That placement is deliberate and it is
the resolution of an apparent conflict: Core-A reads the Trust Index, which looks like a breach
of Core-A/Core-B isolation but is not, because the Trust Index never enters Core-B's verdict
(SI-4) and Core-A still cannot see anything Core-B produced (SI-5). Two invariants, neither
violated. This is finding R-9 in [`DOCUMENT_RECONCILIATION.md`](DOCUMENT_RECONCILIATION.md).

---

## 3. The nine layers

```
CARLA / plant
     │ raw sensors
     ▼
┌──────────────────────────────────────────────────────────────┐
│ L1  Shared Sensor Bus                                        │  SHARED
│     camera+LiDAR+IMU+GPS+radar → fused, timestamped          │
│     staleness > 50 ms ⇒ DEGRADED                             │
└──────────────────────────────────────────────────────────────┘
     ▼
┌──────────────────────────────────────────────────────────────┐
│ L2  Dual-Rate UKF                            ★ most critical │  SHARED
│     fast 20 Hz : x_f = [px,py,v,ψ,a_lat] → (x̂_f, P_f)        │
│     slow 1 Hz (0.1 Hz proto) : x_s = [μ_road,δ_tyre,ρ_sensor]│
│     innovation ν_t → sensor-fault flag + covariate-shift sig  │
└──────────────────────────────────────────────────────────────┘
     │ (x̂_f, P_f)                          │ P_f  ─────────────┐
     ├───────────────┬──────────────────────┘                  │
     ▼               ▼                                          │
┌─────────────┐  ┌──────────────────────┐                      │
│ L3 Conformal│  │ L4 Core-A (CMDP)     │  CORE_A              │
│    Trust    │  │  PPO + PID-Lagrangian│                      │
│  EnbPI +    │─▶│  proposes π_prop     │                      │
│  Mondrian   │TI└──────────────────────┘                      │
│  → TI∈[0,1] │             │ π_prop  (ONE-WAY, SI-5)          │
└─────────────┘             ▼                                   │
   │            ┌───────────────────────────────────────┐      │
   │            │ CORE-B — safety island       ASIL-D(D)│      │
   │            │  L5 PINN twin + EWC  → π̂_{t+1}        │      │
   │            │  L6 MPC scoring + ICP gate ◀──────────┼──────┘
   │            │      α = |π_prop − π̂|/σ(x), σ=√P_f[·] │
   │            │      MMD covariate shift ⇒ tighten ε   │
   │            │  L7a Hard Safety Shield  (a_lat≤μg,   │
   │            │       d_stop≤d_avail, v≤v_legal)      │
   │            │  L7b Physical checker (PINN-based)    │
   │            │  L8 Fail-Safe FSM                     │
   │            │      NOMINAL→DEGRADED→LIMP→HALT       │
   │            └───────────────────────────────────────┘
   │ TI                        │ verdict + FSM state
   └────────────┬──────────────┘
                ▼
┌──────────────────────────────────────────────────────────────┐
│ L9  RCM — final arbitrator                        ARBITRATOR │
│     RCS r = [ρ_vis, v_ego, ρ_dyn, ρ_sensor, ρ_road]          │
│     KB search (Mahalanobis) → mandatory gates → T(c) scoring │
│     T(c) = w₁sim + w₂val + w₃hist − w₄risk ;  admissible iff  │
│              T(c) ≥ τ AND val(c) = 1                          │
│     shadow execution monitored by CDI → commit / rollback     │
│     no admissible candidate ⇒ BOUNDED SAFE EXPLORATION        │
│         (50% of nearest certified max speed, no lane changes, │
│          steering ±15°, evidence logged, never halts)         │
└──────────────────────────────────────────────────────────────┘
                ▼ final command  (SI-7: only L9 may issue)
             Actuators
                │
   FB1 ─────────┴──▶ L2   applied command re-anchors the filter
   FB2 ────────────▶ L5   measured outcome → EWC output-layer update
   FB3 ────────────▶ L3   executed outcome → Mondrian requantilisation
   FB4 ────────────▶ sim  executed command → simulator sync (proto only)
```

### 3.1 Layer by layer, and what Phase 1 contains for each

Every layer is expressed as a `Protocol` in `src/astra/ports/pipeline.py` — ten protocols for
nine layers, because L7 splits into two gates — and the records each consumes and produces are
frozen dataclasses in `src/astra/contracts/`. Nothing in the table's "Phase 1 delivers" column is
an implementation; it is a shape.

| Layer | `LayerId` member | Port | Phase 1 delivers | Implemented in |
|---|---|---|---|---|
| L1 Shared sensor bus | `L1_SENSOR_BUS` | `SensorSource[PayloadT]` | `SensorSample`, `FusedSensorFrame` with per-modality health and the 50 ms staleness rule | Phase 2 |
| L2 Dual-rate UKF | `L2_DUAL_RATE_UKF` | `StateEstimator` | `FastStateEstimate`, `SlowStateEstimate`, `InnovationRecord`, `SymmetricMatrix` | Phase 2 |
| L3 Conformal trust | `L3_CONFORMAL_TRUST` | `TrustEstimator` | `TrustAssessment` | Phase 5 |
| L4 Core-A proposer | `L4_CORE_A_CMDP` | `CommandProposer` | `ProposedCommand`, `ActuationSpace`, `ControlCommand` | Phase 4 |
| L5 PINN twin | `L5_PINN_TWIN` | `DynamicsPredictor` | `PredictedCommand` | Phase 4 |
| L6 Statistical gate | `L6_MPC_ICP_GATE` | `StatisticalGate` | `GateVerdict` tagged `GateId.STATISTICAL` | Phase 5 |
| L7a Hard Safety Shield | `L7_HARD_SAFETY_SHIELD` | `DeterministicShield` | `GateVerdict` tagged `GateId.DETERMINISTIC`; `ShieldSettings` | Phase 3 |
| L7b Physical checker | `L7_HARD_SAFETY_SHIELD` | `PhysicalAdmissibilityChecker` | `GateVerdict` tagged `GateId.PHYSICAL` | Phase 4 |
| L8 Fail-safe FSM | `L8_FAILSAFE_FSM` | `SafetyStateMachine` | `FailSafeState`, `FailSafeSnapshot`, `FailSafeSettings` | Phase 3 |
| L9 RCM | `L9_RCM` | `CalibrationArbiter` | `RuntimeContextSignature`, `CalibrationProfile`, `ArbitrationDecision`, `IssuedCommand` | Phase 6 |

> **A note on L7a and L7b.** `LayerId` has a single `L7_HARD_SAFETY_SHIELD` member; the a/b split
> lives in the *ports*, as two protocols with different inputs, not in the layer enumeration. That
> is intentional. The split exists to make two different failure modes visible, and a failure mode
> is a property of a gate, not of a layer number. `GateId` carries the distinction —
> `GateId.DETERMINISTIC` documents itself as L7a and `GateId.PHYSICAL` as L5/L7b — and the two
> ports differ in exactly the way the argument requires: `DeterministicShield.evaluate` takes the
> proposal, the fast state and the slow degradation estimate, while
> `PhysicalAdmissibilityChecker.evaluate` also takes the twin's `PredictedCommand`. See finding
> R-3.

### 3.2 The four feedback loops

`FeedbackLoop` in `src/astra/kernel/enums.py` enumerates them, and the declaration order is
load-bearing: the roadmap requires them brought up one at a time in this order, because FB1's
correctness is a precondition for the other three.

| Loop | Path | What it corrects |
|---|---|---|
| FB1 | L9 → L2 | The **applied** command, not the proposed one, re-anchors the filter |
| FB2 | outcome → L5 | EWC update of the twin's output layer only, Fisher-anchored |
| FB3 | outcome → L3 | Online Mondrian requantilisation of the trust distribution |
| FB4 | L9 → simulator | Prototype-only synchronisation; `is_deployment_relevant` is `False` |

`ExecutionOutcome` in `src/astra/contracts/audit.py` carries a `frozenset[FeedbackLoop]` naming
which loops an outcome feeds, and `FeedbackBus.publish` in `src/astra/ports/infrastructure.py`
routes on it. Routing through a bus rather than by direct inter-layer calls is what makes
"disable FB2 and re-run" — the Phase 9 ablation study — a configuration change rather than a
code change, and it keeps L5 from importing L9 in order to receive its own feedback.

---

## 4. The three gates, and the independence argument

The architecture's central technical claim is not that there are three checks. It is that the
three checks **fail for structurally unrelated reasons**. Three checks that fail together are
one check with extra latency.

| Gate | `GateId` | Layer | Fires on | Fails when |
|---|---|---|---|---|
| Statistical | `STATISTICAL` | L6 | `α_{t+1} > q̂^{(k)}_{1−ε}` where `α = \|π_prop − π̂\| / σ(x)` | Exchangeability is violated — which adversarial perturbation does by construction |
| Physical | `PHYSICAL` | L5 → L7b | The predicted next state is not Newtonian-admissible | PINN drift beyond what elastic weight consolidation can correct |
| Deterministic | `DETERMINISTIC` | L7a | A hard bound is exceeded: `a_lat ≤ μg`, `d_stop ≤ d_avail`, `v ≤ v_legal` | Only if the UKF state estimate itself is wrong |

Read the **Fails when** column downward: a conformal coverage guarantee, a learned physics model
and a closed-form inequality do not degrade under the same conditions. Read the **Fires on**
column downward: an adversarial camera perturbation defeats the exchangeability assumption
without touching Newtonian mechanics or the arithmetic of a stopping-distance bound.

Three properties in the code carry this argument:

- **`CORE_B_GATE_COUNT = 3` in `src/astra/kernel/constants.py` is documented as load-bearing.**
  Adding a fourth gate that shares a failure mode with an existing one would weaken the argument
  while appearing to strengthen it.
- **The shield's port cannot see the other gates.** `DeterministicShield.evaluate` has no
  parameter for a `PredictedCommand`, no parameter for a conformal score and no parameter for a
  `TrustAssessment`. Its independence is a property of the signature, not of a convention.
- **No gate port accepts a `TrustAssessment` at all** (SI-4). An architecture test in
  `tests/architecture/test_invariants.py` renders each gate protocol's annotations and asserts
  the type name does not appear.

The evidence for independence is not this document. It is Phase 5 and Phase 9 of the validation
plan: the FGSM camera-attack scenario is constructed so that **exactly one** gate fires, and the
IMU-corruption scenario so that **two** fire for different reasons. Until those scenarios have
run, independence is a design argument and is described as one.

### 4.1 Aggregation is fail-closed, and there is only one path to it

`SafetyVerdict` in `src/astra/contracts/assurance.py` has two fields — `tick` and
`gate_verdicts` — and no constructor argument for the aggregate. `SafetyVerdict.aggregate` is a
property computed through `Verdict.merge`, so a contradictory aggregate has nowhere to live. The
architecture test `test_the_safety_verdict_carries_only_the_tick_and_the_gate_verdicts` asserts
the field set exactly, which is what stops the escape hatch being added later.

`Verdict.merge(())` returns `VETO`. A command that no gate inspected has not been cleared; it
has been missed. This mirrors the FMEA mitigation for a silent Core-B crash, where the hardware
crossbar defaults to VETO on a missed heartbeat.

`guard_verdict_aggregation` in `src/astra/invariants/catalogue.py` re-derives the merge and
raises `InvariantViolationError` on disagreement. Under correct operation it never fires — which
is precisely its purpose: if it ever does, something computed an aggregate by a path other than
`Verdict.merge`, and the unconditional-veto property can no longer be assumed.

---

## 5. The two timing domains

`TimingDomain` in `src/astra/kernel/enums.py` names them, and any component added in a later
phase must declare which one it runs in. The declaration is what makes an accidental blocking
call on the hot path reviewable.

| Domain | Work | Software budget |
|---|---|---|
| `HOT_PATH` | L1 → L2 → L3/L4 → L5 → L6 → L7 → L8 → L9 active-table lookup | fast UKF < 1 ms · trust < 2 ms · Core-A < 3 ms · Core-B intercept < 5 ms · RCM hot < 1 ms · **end-to-end < 10 ms** at 20 Hz |
| `COLD_PATH` | RCM knowledge-base search, shadow execution, CDI, evidence writing | milliseconds to seconds; **must never block a tick (SI-8)** |

Every figure in that table is a **target**, not a measurement. Nothing in this repository has
measured a latency, because nothing in this repository executes a tick.

> **The 1.25 µs figure.** It appears in the source papers as a Core-B intercept latency and it is
> an **analytical hardware WCET bound** (AbsInt aiT, 500 MHz, 627 cycles) for a hardware
> implementation that does not exist. It is not measurable by a Python prototype and must never
> be reported as a measurement. The software prototype's real latency will be in the low
> milliseconds and must be reported against the < 5 ms software target.

The split is visible in three places in the Phase 1 code:

1. **`CalibrationArbiter` has two methods, not one.** `issue` is hot-path and is an active-table
   lookup; `arbitrate` is cold-path and runs the Mahalanobis search, the mandatory gates, `T(c)`
   scoring and shadow execution. Splitting them across two methods makes the split impossible to
   lose in an implementation.
2. **`EventSink.emit` is documented as non-blocking**, and `JsonlAuditSink` in
   `src/astra/observability/audit.py` implements that with a bounded `queue.Queue` and a daemon
   writer thread. Every syscall in that class happens on the background thread.
3. **Diagnostic logging uses a `QueueHandler` + `QueueListener`** in
   `src/astra/observability/logging.py`, for the same reason: a `FileHandler` on a busy disk
   blocks, and a blocking call inside a 50 ms tick violates the budget.

The bounded queue is a deliberate trade. An unbounded queue converts a stalled disk into
unbounded memory growth, which on a real-time system is the worse failure. Overflow is therefore
**counted** in `JsonlAuditSink.dropped_records` rather than silently absorbed: a run whose
evidence has a gap must be reportable as incomplete, because only an archive that admits a gap
can be assessed honestly.

---

## 6. The module dependency graph

```
                      bootstrap
                          │
        ┌─────────────┬───┴────┬──────────────┐
        ▼             ▼        ▼              ▼
     config    observability  invariants   (future) layers / adapters
        │             │        │              │
        └─────────────┴───┬────┴──────────────┘
                          ▼
                       ports
                          │
                          ▼
                      contracts
                          │
                          ▼
                       kernel          ← imports nothing from astra, nothing 3rd-party
```

This is a `layers` contract in `.importlinter`, so a violation is a red build rather than a
review comment. `tests/architecture/test_layering.py` runs `lint-imports` as a subprocess and
asserts `0 broken` appears in its output, so the contracts are also part of the test suite.

**Why strictly acyclic.** A cycle between `contracts` and `ports` would mean neither can be
understood, tested or replaced without the other, and the substitutability that every roadmap
exit criterion depends on ("layer X validated in isolation before it is wired to anything")
would be unavailable.

**Why strictly downward.** The payoff is concrete rather than aesthetic: because `kernel`
imports nothing from `astra` and nothing third-party, an offline evidence-analysis tool, a
certification script or the dashboard process can import ASTRA's vocabulary and contracts
without installing NumPy, PyTorch or a simulator.

Two mechanisms guard that property, and it is worth being precise about how much each one
actually covers. `test_no_kernel_module_imports_anything_from_astra_outside_the_kernel` parses
every kernel module's AST and asserts no import reaches outside `astra.kernel` — that half is
complete. The `kernel-independence` contract in `.importlinter` is titled "The kernel imports no
third-party package" but its `forbidden_modules` list names only `pydantic` and
`pydantic_settings`, because import-linter's `forbidden` contracts enumerate targets rather than
inverting an allow-list. The third-party half is therefore enforced against the two packages most
likely to creep down from the configuration boundary, and rests on review for everything else —
including NumPy, which becomes a project dependency in Phase 2 and is the realistic future
offender.

**Why `config`, `observability` and `invariants` are siblings and not a stack.** They are
independent concerns that happen to sit at the same level: configuration does not need the audit
sink, the audit sink does not need the invariant catalogue, and the catalogue does not need
either. Ordering them would invent a dependency and make each harder to test alone. Only
`bootstrap` sees all three, because assembly is the one activity that legitimately needs
everything.

**Where the future layers attach.** `astra.layers.*` and `astra.adapters.*` enter as siblings of
`config`/`observability`/`invariants`: above `ports`, below `bootstrap`. They may depend on
contracts and ports; nothing may depend on them except `bootstrap`. That is what keeps the CARLA
adapter from being reachable from the safety island.

### 6.1 The import convention

Sub-packages deliberately do not re-export their contents. Every import names the defining
module — `from astra.kernel.units import Metres`, never `from astra.kernel import Metres`. Two
reasons: the dependency graph stays precise enough for the import contracts to mean something (a
facade re-export makes every module in a package look like a dependency of every consumer), and
a reader can locate any symbol from its import line alone. Relative imports are banned outright
by ruff's `TID` rules and asserted against in the architecture tests.

---

## 7. A section per package: why it exists, and why not the obvious alternative

### `src/astra/kernel/` — the vocabulary

Units, enumerations, architectural constants, the typed error hierarchy, identifiers, time and
the symmetric matrix. Imported by everything, imports nothing.

**Why a kernel at all, rather than putting these next to the code that uses them?** Because
across the four source documents the same concept appears under several spellings —
`Nominal`/`NOMINAL`, `highway_clear`/`HIGHWAY-CLEAR`, `PASS`/`pass`. In a system whose primary
evidence artefact is an audit log, a concept that serialises three different ways is a concept
that cannot be queried, and therefore cannot be certification evidence. `enums.py` fixes one
spelling per term, and every later phase imports it rather than declaring a string literal.

**Why `StrEnum` and not `Enum` or `IntEnum`?** `StrEnum` members *are* strings, so `json.dumps`
emits `"VETO"` with no custom encoder — and a forgotten encoder on the audit path is a crash in
the one place a crash is least acceptable. `IntEnum` serialises to `2`, which is unreadable in an
evidence log and silently comparable to unrelated integers. The accepted trade-off is that
`Verdict.VETO == "VETO"` is `True`; mypy still rejects passing a bare `str` where a `Verdict` is
declared.

**Why `NewType` aliases for units and not `pint`?** The documents mix m/s², km/h, degrees and
radians freely. That is a Mars-Climate-Orbiter-shaped risk, and it is a static one: `Metres` and
`MetresPerSecond` are distinct to mypy and identical to CPython, so unit safety costs literally
zero at runtime. `pint` imposes a 50–100× arithmetic cost, which is not payable on a hard
real-time path. Non-SI aliases (`KilometresPerHour`, `Degrees`, `Milliseconds`) exist so that a
human-facing value is *visible* in a signature, and an architecture test asserts none of them
ever appears in a `ports/` signature.

**Why an injected `Clock` and never `time.time()`?** Three separate defects in one call. The
wall clock is non-monotonic (NTP correction, leap smear, VM migration), so a negative staleness
reads as "perfectly fresh" — exactly inverting FR1's 50 ms rule. Replay needs a substitutable
timeline. CARLA's synchronous mode has its own. `Instant` carries integer nanoseconds *and* its
`Timeline`, and cross-timeline arithmetic raises rather than returning a plausible-looking
number.

**Why exactly one random identifier?** Replay must produce byte-comparable event streams. A
`uuid4()` per event makes a diff between a recorded run and its replay meaningless. `RunId` is
the only random identifier in the system; `TickId` is ordered, `EventId` is the deterministic
triple `run:tick:sequence`, and `ProfileId` is `name@vN`.

**Why a hand-written `SymmetricMatrix` instead of NumPy?** Two reasons, and the second is the
stronger. First, storing the packed lower triangle makes asymmetry *unrepresentable* rather than
checkable — 15 stored numbers instead of 25 for the 5×5 fast covariance. Second, a NumPy array
is mutable and unhashable, so embedding one in a frozen record would make that record frozen in
name only, and importing NumPy into the kernel would destroy the offline-importability property
above. `to_rows()` is the interoperability seam; Phase 2's UKF converts at its own boundary.
`is_positive_definite` deliberately tests definiteness and not semi-definiteness: a singular
covariance asserts that some direction of the state is known exactly, which for a filter
tracking a physical vehicle means collapse, and a collapsed filter would drive `σ(x)` to zero and
with it unbound the ICP acceptance band.

**Why a typed exception hierarchy carrying a `SafetyDisposition`?** An exception on a safety path
is a statement about what the system may now do, not just a bug report. `AstraError` carries
`FAIL_FAST` / `FAIL_CLOSED` / `FAIL_OPERATIONAL` as a class variable, so a caller can act on the
disposition without pattern-matching on the type. `Result`/`Either` was rejected: Python has no
language support, and the unwrap noise would be everywhere. Untyped exceptions were rejected
because they carry no policy.

**Why guards and never `assert`?** `python -O` deletes `assert`. A safety check that disappears
under an optimisation flag is not a safety check. `require_finite` exists specifically because
NaN defeats comparison: `NaN > threshold` is `False`, so a NaN passes a naive bounds check —
the failure is fail-*open*, which is the one direction this architecture cannot tolerate.

### `src/astra/contracts/` — the records layers exchange

Frozen, slotted dataclasses that validate once at construction and are then trusted.

**Why frozen `slots=True` dataclasses rather than pydantic everywhere?** Validation cost is paid
on every hop with pydantic, and at 20 Hz with dozens of records per tick that is a real budget
item. `slots=True` removes the per-instance `__dict__`. Immutability means a downstream layer
cannot mutate a record another layer has already consumed — which in a pipeline whose whole
premise is that one component judges another's output is not a stylistic preference. Plain
dicts were rejected: no invariants, no types, no way to make an illegal state unrepresentable.

**Why is `ActuationSpace` a value rather than a set of constants?** This is how NFR5 domain
independence is actually achieved. "Throttle in [0, 1], brake in [0, 1], steer in [−0.5, 0.5]
rad" is a fact about *one* platform. Lifting it into a configured value means the pipeline
reasons about "a command in the actuation space" and asks the space whether a vector is
admissible; it never names a channel. A different platform supplies a different space without a
line of core code changing.

**Why several command types rather than one?** Because provenance is safety-relevant. A command
proposed by the untrusted agent, a command predicted by the twin, and the single command L9 is
authorised to issue are three different things with three different trust levels. Collapsing
them into one type would make SI-7 unenforceable; keeping them separate means `IssuedCommand` is
the only one that records an issuer, and it checks it.

**Why does `ControlCommand` *not* reject an out-of-bounds vector?** Because a command the
untrusted proposer offers may violate a bound — detecting exactly that is the shield's job — and
a type that could not represent an inadmissible proposal would make the violation it exists to
catch unrepresentable. Admissibility is a question asked of a command (`is_admissible()`), not a
precondition of building one. `IssuedCommand`, at the far end of the pipeline, *does* enforce it.

**Why does `DecisionRecord` have optional fields?** A tick can end early: a fail-closed VETO can
be reached before a proposal is scored. An absent field means "this stage did not run this
tick", which is itself evidence. `to_payload` renders absent stages as `null` rather than
omitting them, so every record from a run has the same key set and the evidence archive is a
rectangle rather than a ragged join.

### `src/astra/ports/` — the interfaces

Ten pipeline protocols and four infrastructure ports.

**Why do ports exist before any layer does?** Three payoffs. The dependency graph is fixed now,
so the architecture contracts have something concrete to constrain — a port added after its
implementation is a *description* of what was built, whereas a port added before is a *decision*
about what may be built. Substitutability is the testing strategy, and every roadmap exit
criterion is of the form "layer X validated in isolation", which requires X's collaborators to
be replaceable by five-line fakes. And the unit policy is enforced at the boundary, where an
architecture test can see it.

**Why `Protocol` and not an abstract base class?** Structural typing keeps the dependency arrow
pointing inward. An adapter implementing `SensorSource` does not import an ASTRA base class, so
the CARLA adapter never inherits from the core and the core never learns that CARLA exists. That
is what makes the R-6 interpreter problem a deployment detail rather than an architectural one.

**Why `@runtime_checkable` at all, if `isinstance` on a Protocol only checks method presence?**
Because that is exactly what the composition root wants: a wiring sanity check, cheap, that
catches "you passed the wrong object" without pretending to be a substitute for type checking.
The limitation is documented in the module rather than discovered later.

**Why is `Clock` in `kernel/time.py` and not here?** Because `Instant` and `staleness()` are
defined in terms of it, and the kernel may not import upward. `ports/infrastructure.py` names it
in prose so that module still reads as the complete inventory of injected infrastructure.

**Why does `ProfileRepository` have no `save`?** Certification produces profiles offline. A
pipeline that could write its own calibration could also poison it. Profiles are immutable and
versioned (NFR7), so there is no update and no delete either: a change is a new version, and
retirement is a lookup that stops returning it.

### `src/astra/invariants/` — the safety argument as data

`SeparationInvariant` records SI-1…SI-10 with identifier, title, statement, rationale,
consequence, enforcement kind and mechanism; plus runtime guards for SI-3 and SI-7.

**Why is the safety argument a data structure rather than a document?** Prose in a design
document cannot fail a build. As a value, the catalogue can be printed by
`astra invariants list`, so an assessor can read the argument and its enforcement status without
reading the source; verified at startup by `verify_invariant_catalogue`, so a depopulated or
malformed argument stops the run; and asserted *about* by the architecture tests, which is what
stops the argument eroding under deadline pressure.

**Why `EnforcementKind.REVIEW` exists.** It distinguishes what is actually checked from what is
merely asserted. An invariant marked `REVIEW` is one the codebase does not mechanically enforce,
and it says so rather than implying a guarantee it cannot make. Exactly one invariant is
review-only today — SI-6 — and
`test_mechanical_enforcement_is_false_exactly_for_review_only_invariants` keeps that visible.
Full detail in [`SEPARATION_INVARIANTS.md`](SEPARATION_INVARIANTS.md).

**Why only two runtime guards?** Most invariants are enforced statically — by an import contract
or by a type that makes the illegal state unrepresentable. Two need a dynamic check as well, and
they are the two whose violation is catastrophic and whose trigger is dynamic: verdict
aggregation and actuation authority. `guard_actuation_authority` duplicates a check
`IssuedCommand` already performs, deliberately, because it serves the call sites that decide
*before* building a record — and an invariant enforced in only one place is enforced until
somebody adds a second place.

### `src/astra/config/` — the operating point

pydantic-settings models, layered TOML resolution, a configuration hash.

**Why pydantic here when the hot path uses frozen dataclasses?** Configuration is parsed once, at
startup, from text a human wrote. That is exactly the boundary pydantic is for: rich validation
and error messages that name the file, the field and the constraint. The hot path never touches
these validators again — settings are frozen after load and read as plain attributes.

**Why does no safety threshold have a default?** This is the single most important property of
the package. The source documents never assign numeric values to θ1/θ2/θ3, ε, γ, τ or δ_CDI, and
that is not an oversight: those values can only be fixed empirically once the pipeline runs.
Shipping a plausible-looking default would let a run proceed under a threshold nobody chose and
nobody reviewed, and the resulting number would then appear in a report as though it meant
something. A missing safety threshold is therefore a startup failure.
`config/environments/certification.toml` ships with every threshold **commented out**, so
loading it fails by design — and the test suite exercises that failure.

**Why `extra="forbid"`?** A typo in a TOML key would otherwise be silently ignored, leaving the
system running on a different value than the file appears to specify. For a safety threshold
that is the worst available failure mode.

**Why a *deep* merge and not a shallow one?** An environment file that sets one threshold in a
section must inherit the rest of that section. Shallow merging would mean a file touching one
field silently discarded every sibling default — a quiet way to lose a safety-relevant value.

**Why a configuration hash?** Without it a number in a report is unattributable: two runs can
produce different verdicts from identical code because one ran with a tighter ε, and nothing in
the evidence would say so. `config_hash` is computed over the resolved settings in canonical
form, so it changes if and only if an operating point changed, and it is stamped on every
`DecisionRecord`.

### `src/astra/observability/` — correlation, diagnostics, evidence

**Why is audit logging a different system from diagnostic logging?** Because they answer
different questions. `EventSeverity` deliberately does not reuse the `logging` module's levels: a
component that must be silent in the console may still be emitting `SAFETY_CRITICAL` audit
records. Conflating "this is worth printing" with "this changed the safety state of the vehicle"
would put a certification artefact behind a log-level filter.

**Why `contextvars` and not a global or a thread-local?** A module-level global breaks the moment
RCM's shadow execution runs the active and candidate calibration tables concurrently — both are
in the same tick, both emit records, and one global cannot represent two component identities.
Thread-locals handle threads but not the async boundaries a dashboard backend introduces.
`contextvars` handles both, and its tokens make scope exit exact.

**Why JSONL, one file per run?** Append-only means a written record is never rewritten, which is
the tamper-evidence property a certification archive needs at prototype stage. One file per run
makes a run the unit of archival and replay. Line-delimited JSON means a partially written file
is still readable up to the last complete line — which matters precisely when a run ended
abnormally, the case whose evidence is most interesting. Assumption A-3 records that this is
adequate at prototype stage and may need a signed log or a database for real certification.

### `src/astra/bootstrap/` — the composition root and the CLI

**Why a composition root?** Every layer depends on abstractions and none constructs a concrete
one. If they did, the CARLA adapter would be reachable from the safety island, the audit sink
could not be swapped for a test double, and replay would be impossible because a layer could
read the real clock. Concentrating construction in one module means a review of *one* file
establishes what the running system is made of.

**Why does `AstraRuntime` contain no layers?** Because none exist. A placeholder L2 returning
zeros would be worse than an absent one: integration code would be written against behaviour no
real filter will have, and the mismatch would surface during closed-loop integration — the stage
the roadmap protects with slack precisely because it does not compress.

**Why is the startup order what it is?** It is chosen, not incidental. Configuration first and
frozen, because nothing may run under an unvalidated operating point. Invariant catalogue next,
because there is no point starting machinery whose constraints are malformed. Clock third, so
every subsequent timestamp comes from one substitutable source. Audit sink last, because it is
the only step that touches the filesystem and the only one that starts a thread — anything
failing before that point fails without leaving a partial evidence directory behind.

**Why is `bootstrap/cli.py` the only module allowed to `print()`?** Because a `print` anywhere
else is unstructured output that bypasses the correlation context and the audit schema.
`test_print_is_called_nowhere_except_the_command_line_interface` walks every source file's AST
and asserts it.

---

## 8. What Phase 1 contains, precisely

**Delivered.**

- `src/astra/kernel/` — `units`, `enums`, `constants`, `errors`, `identifiers`, `time`,
  `validation`, `matrix`.
- `src/astra/contracts/` — `sensing`, `estimation`, `actuation`, `assurance`, `governance`,
  `audit`.
- `src/astra/ports/` — `pipeline` (ten layer protocols), `infrastructure` (four ports).
- `src/astra/invariants/catalogue.py` — SI-1…SI-10 as data, plus the SI-3 and SI-7 runtime
  guards.
- `src/astra/config/` — `schema`, `loader`, and `config/astra.defaults.toml` plus three
  environment files.
- `src/astra/observability/` — `context`, `logging`, `audit`.
- `src/astra/bootstrap/` — `composition`, `cli`; `python -m astra` entry point.
- `tests/{unit,property,architecture}/`, `.importlinter`, `Makefile`,
  `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `CHANGELOG.md`.

**Quality gate, as run on this tree.** 1352 tests passing, 99% statement coverage against a 95%
floor, `ruff format --check`, `ruff check`, `mypy --strict` and `lint-imports` all green. Those
are counts and coverage of the Phase 1 code; they are not a claim about pipeline behaviour,
because there is no pipeline yet.

**Deliberately absent.**

- Every one of L1–L9. No UKF, no PPO agent, no PINN, no conformal predictor, no shield bounds,
  no FSM transitions, no knowledge-base search.
- All four feedback loops.
- The CARLA adapter, the replay harness, the dashboard, the training corpora, the calibration
  profiles.
- Any latency measurement, any coverage measurement, any false-positive rate.

**Known Phase 1 documentation debt.** The fourteen Architecture Decision Records listed in
§14 of [`ENGINEERING_HANDOFF.md`](ENGINEERING_HANDOFF.md) are not yet written; `docs/adr/` is
empty. Their content is currently carried by the module docstrings and by this document. That is
the last outstanding Phase 1 exit item and it is tracked in [`ROADMAP.md`](ROADMAP.md).

---

## 9. The acknowledged residual weakness

**All three gates read the same L2 state estimate. That is a genuine common-cause channel.**

The independence argument in §4 is an argument about *decision procedures*: a conformal
threshold, a learned physics model and a closed-form inequality fail under unrelated conditions.
It is not an argument about *inputs*. Every gate obtains state from the same dual-rate UKF,
because SI-2 requires exactly one state source — and SI-2 exists for good reasons (comparable
gate inputs, a joinable audit record, no ambiguity about what the world looked like at a tick).
The cost of that decision is that a sufficiently wrong `x̂_f` makes all three gates wrong
together.

This is stated rather than argued away. Two mitigations exist, and neither eliminates it:

1. **The innovation-sequence Mahalanobis monitor.** L2 tracks the innovation `ν_t` and raises a
   sensor-fault flag when its Mahalanobis distance exceeds γ. `InnovationRecord` in
   `src/astra/contracts/estimation.py` carries the residual, the distance and the flag, and its
   docstring names this weakness as the reason the record exists. The monitor detects a filter
   that has begun to disagree with its measurements; it does not detect a filter that is
   confidently and consistently wrong.
2. **FB1.** The **applied** command, not the proposed one, re-anchors the filter. That closes the
   gap between what the controller asked for and what the vehicle did, which is the largest
   single source of the drift that would otherwise accumulate. It does not help if the
   measurements themselves are corrupt.

Two further structural choices reduce the blast radius without touching the root cause. The
Runtime Context Signature's `sensor_reliability` component is reliability-weighted upstream, so a
degraded sensor lowers its own contribution rather than silently dominating the signature. And
`SymmetricMatrix.is_positive_definite` treats a singular covariance as a fault, so a collapsed
filter is reported rather than being allowed to drive `σ(x)` to zero and unbound the ICP gate.

Eliminating the common cause would require a second, independently derived state estimate — a
different filter over a different sensor subset — which is a substantial architectural addition
and is not in any phase of the current roadmap. Until it is, this weakness stands, and it must
be stated in any presentation of the safety argument.

---

## 10. Honesty boundaries

Carried forward from the Prototype & Demo Plan because they constrain what this codebase may
claim.

1. The **1.25 µs Core-B intercept latency is an analytical hardware bound**, not a measurement.
   The software prototype's latency will be in the low milliseconds and must be reported against
   the < 5 ms software target.
2. False positive/negative targets are **< 1%, not zero**. The argument is defence in depth
   through structurally independent gates, never "eliminates hallucination".
3. The **shared UKF state is an acknowledged residual common-cause channel** across all three
   gates — mitigated, not eliminated (§9).
4. Conformal prediction's coverage guarantee **assumes exchangeability**, which adversarial
   perturbation violates by construction. That is why there is more than one gate.
5. The PINN twin will be trained on **simulated dynamics**, not real vehicle physics.
6. Core-B here is **Python processes, not fabricated hardware**. FPGA/ASIC is roadmap, not done.

Any metric this repository reports must come from code that ran. Nothing is hardcoded to look
good in a demo.
