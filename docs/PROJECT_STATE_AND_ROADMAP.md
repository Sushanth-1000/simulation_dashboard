# ASTRA — Complete Project State & Roadmap to Working Prototype

**Autonomous Safety, Trust, and Runtime Architecture**
Runtime governance for AI-controlled cyber-physical systems.

> **Confidential — unpublished proprietary work.** An intended patent filing covers this
> architecture. Do not distribute, demonstrate externally, or publish any part of this repository
> until the filing status is confirmed. See `LICENSE` and `NOTICE`.

| | |
|---|---|
| **Prepared by** | **Tanay S. Huddar** |
| **Created** | **Thursday, 30 July 2026 at 14:06 IST** (UTC+05:30) · `2026-07-30T08:36:23Z` |
| **Document purpose** | Single self-contained context transfer: everything built, every file changed, every phase remaining. Anyone (or any AI session) picking this up should be able to continue without re-reading the source PDFs. |
| **Institution** | Dept. of CSE, B.M.S. College of Engineering, Bengaluru |
| **Project authors** | Sushanth C., Tanay S. Huddar, Tarun Gowda V., T. Tilak Reddy |
| **Guide** | Dr. Chaitra R., Associate Professor |
| **Phases complete** | **1, 2 (except CARLA adapter), 3** |
| **Phases remaining** | **4, 5, 6, 7, 8, 9** |
| **Quality gate** | **GREEN** — 1 953 tests, 99.10% coverage, 8 architecture contracts |

---

## Table of contents

1. [What ASTRA is](#1-what-astra-is)
2. [Status at a glance](#2-status-at-a-glance)
3. [Environment and how to run it](#3-environment-and-how-to-run-it)
4. [Complete file inventory](#4-complete-file-inventory)
5. [Phase 1 — Foundation (complete)](#5-phase-1--foundation-complete)
6. [Phase 2 — Sensing, Estimation, Replay (complete except adapter)](#6-phase-2--sensing-estimation-replay-complete-except-adapter)
7. [Phase 3 — Deterministic Safety Spine (complete)](#7-phase-3--deterministic-safety-spine-complete)
8. [Defects found and fixed](#8-defects-found-and-fixed)
9. [Phase 4 — Proposer & Digital Twin (NOT STARTED)](#9-phase-4--proposer--digital-twin-not-started)
10. [Phase 5 — Statistical Assurance (NOT STARTED)](#10-phase-5--statistical-assurance-not-started)
11. [Phase 6 — Runtime Calibration Management (NOT STARTED)](#11-phase-6--runtime-calibration-management-not-started)
12. [Phase 7 — Closing the Loops (NOT STARTED)](#12-phase-7--closing-the-loops-not-started)
13. [Phase 8 — Observability & Demo Harness (NOT STARTED)](#13-phase-8--observability--demo-harness-not-started)
14. [Phase 9 — Validation & Evidence (NOT STARTED)](#14-phase-9--validation--evidence-not-started)
15. [The blocker: CARLA adapter](#15-the-blocker-carla-adapter)
16. [Separation invariants — enforcement status](#16-separation-invariants--enforcement-status)
17. [Risk register](#17-risk-register)
18. [Assumptions register](#18-assumptions-register)
19. [Technical debt register](#19-technical-debt-register)
20. [What must never be claimed](#20-what-must-never-be-claimed)
21. [Conventions that must not drift](#21-conventions-that-must-not-drift)
22. [Appendix A — commands](#appendix-a--commands)
23. [Appendix B — glossary](#appendix-b--glossary)
24. [Document provenance](#document-provenance)

---

## 1. What ASTRA is

An AI controller in a safety-critical system can be structurally healthy — no bit flips, no
crashes, correct by every classical definition — and still issue a semantically wrong command to a
physical actuator, because the world it faces at runtime no longer matches the world it was trained
in.

Existing infrastructure does not catch this. Lockstep processors replicate the same wrong answer on
both cores. Hypervisors isolate execution domains without inspecting what crosses them. Hardware
security modules authenticate a command's origin, not whether it was a good idea.

ASTRA governs the **actuation boundary**. It treats the AI controller as an *untrusted proposer* and
interposes an independent nine-layer pipeline between it and the actuators. Every proposed command
is validated three ways — statistically, physically, and against hard deterministic bounds — by
gates with structurally different failure modes, and the whole system recalibrates itself from what
actually happened.

```
                    L1  Shared Sensor Bus                         [BUILT]
                     │
                    L2  Dual-Rate UKF  ──────────────┐            [BUILT]
                     │                               │ state + covariance
          ┌──────────┴──────────┐                    │
         L3 Conformal Trust    L4 Core-A (CMDP)      │            [PHASE 5] [PHASE 4]
          │  Trust Index TI     │                    │
          │                     │ π_prop  (ONE-WAY)  │            [CHANNEL BUILT]
          │                     ▼                    │
          │        ┌──────── CORE-B (safety island) ─┴──────┐
          │        │  L5 PINN twin  →  physical gate        │     [PHASE 4]
          │        │  L6 MPC + ICP  →  statistical gate     │     [PHASE 5]
          │        │  L7a Hard Shield → deterministic gate  │     [BUILT]
          │        │  L8 Fail-Safe FSM                      │     [BUILT]
          │        └────────────────┬───────────────────────┘
          │                         │ verdict + FSM state
          └────────────►  L9  RCM (sole actuator authority)       [PHASE 6]
                                    │
                                 Actuators
                                    │
              FB1 · FB2 · FB3 · FB4 └── outcomes fed back upstream [PHASE 7]
```

**The three gates, and why three.** The statistical gate fires on a statistical anomaly; the
physical gate on a violation of Newtonian admissibility; the deterministic gate on a hard bound.
They have *structurally different failure modes*, which is what makes defence in depth real rather
than decorative. The Hard Safety Shield's veto is unconditional and cannot be overridden by any
other component's PASS.

**Three processes plus an arbitrator:**

- **Core-A** (QM/ASIL-A) — CMDP agent, proposes one command per tick.
- **Core-B** (ASIL-D(D)) — safety island, three structurally independent gates.
- **RCM** — the only component authorised to issue an actuator command.
- Core-A → Core-B is a **one-way** channel carrying `π_prop` only.

---

## 2. Status at a glance

### Phases

| Phase | Scope | Status |
|---|---|---|
| **1** | Foundation: kernel, contracts, ports, invariants, config, observability, bootstrap | ✅ **Complete** |
| **2** | L1 sensor bus, L2 dual-rate UKF, replay spine, CARLA adapter | ✅ **Complete except the adapter** (hardware-blocked, §15) |
| **3** | L7a Hard Safety Shield, L8 fail-safe FSM, one-way Core-A→Core-B channel | ✅ **Complete** |
| **4** | L4 CMDP proposer, L5 PINN twin, training corpora → **Checkpoint 1** | ⬜ **Not started** |
| **5** | L3 Conformal Trust (EnbPI + Mondrian), L6 ICP gate + MMD detector | ⬜ **Not started** |
| **6** | L9 RCM: RCS, KB search, shadow execution, CDI, safe exploration → **Checkpoint 2** | ⬜ **Not started** |
| **7** | FB1, FB2, FB3, FB4 — the four feedback loops, one at a time | ⬜ **Not started** |
| **8** | Dashboard, comparison harness, interactive fault injection | ⬜ **Not started** |
| **9** | Seven-phase validation drive, ablation study, evidence pack | ⬜ **Not started** |

### Layers

| Layer | Name | Status |
|---|---|---|
| L1 | Shared Sensor Bus | ✅ Built, 100% covered |
| L2 | Dual-Rate UKF + innovation monitor | ✅ Built, 99% covered |
| L3 | Conformal Trust Module | ⬜ Port + contract only |
| L4 | Core-A CMDP proposer | ⬜ Port + contract only |
| L5 | PINN digital twin | ⬜ Port + contract only |
| L6 | MPC + ICP statistical gate | ⬜ Port + contract only |
| L7a | Hard Safety Shield | ✅ Built, 100% covered |
| L7b | Physical checker (PINN-based) | ⬜ Arrives with L5 in Phase 4 |
| L8 | Fail-Safe FSM | ✅ Built, 100% covered |
| L9 | Runtime Calibration Management | ⬜ Port + contract only |

### Metrics (all measured, none hardcoded)

| Metric | Value |
|---|---|
| Source lines | 10 639 across 50 modules |
| Test lines | 14 652 across 36 files |
| Tests passing | **1 953** (unit 1 616 · architecture 280 · integration 30 · property 27) |
| Coverage | **99.10%** against a 95% gate |
| Architecture contracts | **8** kept, 0 broken |
| ADRs written | **15** |
| Hot-path latency (L1+L2+L7a+L8) | p50 0.13 ms · p99 **0.24 ms** — 0.5% of a 50 ms tick |
| UKF tracking (synthetic) | 0.36 m position error over 298 m through a steady turn |
| Replay | Byte-identical by SHA-256 |

---

## 3. Environment and how to run it

**Python 3.12.3** on macOS 15.7.3 arm64 (Darwin). The project floors at 3.12 for PEP 695 generics
and `typing.override`.

### Important: `uv` is not installed on this machine

The documented workflow uses [uv](https://docs.astral.sh/uv/), which is not present. A standard
`venv` was created instead and every command below uses it directly. **This is a deviation from the
documented setup and should be reconciled** — either install uv, or update `docs/INSTALL.md` to
document the venv path as supported.

```bash
# What was actually done
python3.12 -m venv .venv
.venv/bin/pip install "pydantic>=2.9,<3" "pydantic-settings>=2.6,<3" \
  "ruff>=0.8" "mypy>=1.13" "import-linter>=2.1" \
  "pytest>=8.3" "pytest-cov>=6.0" "hypothesis>=6.115" \
  "numpy>=2.0" "filterpy>=1.4.5"
```

### Installed versions

| Package | Version | Added in |
|---|---|---|
| pydantic | 2.13.4 | Phase 1 |
| pydantic-settings | 2.14.2 | Phase 1 |
| ruff | 0.16.0 | Phase 1 |
| mypy | 2.3.0 | Phase 1 |
| import-linter | 2.13 | Phase 1 |
| pytest / pytest-cov | 9.1.1 / 7.1.0 | Phase 1 |
| hypothesis | 6.163.0 | Phase 1 |
| **numpy** | **2.5.1** | **Phase 2** |
| **filterpy** | **1.4.5** | **Phase 2** |

### Running it

```bash
cd /Users/tanayhuddar/Downloads/astra

# The full gate, exactly as CI runs it
PATH="$PWD/.venv/bin:$PATH" make check

# Individually
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov=astra

# The CLI
.venv/bin/astra doctor            # environment + config + invariant report
.venv/bin/astra config show       # effective resolved configuration
.venv/bin/astra invariants list   # SI-1 … SI-10 with enforcement status
.venv/bin/astra version

# Latency benchmark (reproducible, software measurement)
.venv/bin/python benchmarks/latency.py -n 2000
```

---

## 4. Complete file inventory

Every file in the repository, what it does, and which phase created it.
**P1** = Phase 1, **P2** = Phase 2, **P3** = Phase 3.

### `src/astra/kernel/` — dependency-free primitives (P1)

| File | Lines | Purpose |
|---|---|---|
| `units.py` | 238 | SI policy. `NewType` aliases (`Metres`, `MetresPerSecond`, `Radians`, `Probability`, …), non-SI boundary types, `STANDARD_GRAVITY`, six named boundary conversions. |
| `enums.py` | 403 | Canonical vocabulary: `LayerId`, `ExecutionDomain`, `Verdict` (with fail-closed `merge()`), `GateId`, `FailSafeState`, `ContextClass`, `SensorModality`, `StreamHealth`, `TimingDomain`, `ArbitrationOutcome`, `FeedbackLoop`, `EventSeverity`. All `StrEnum`. |
| `constants.py` | 143 | Architectural constants only. Cardinalities, **ordered** state-vector layouts, schema versions. |
| `errors.py` | 316 | `SafetyDisposition` (`FAIL_FAST`/`FAIL_CLOSED`/`FAIL_OPERATIONAL`) + typed exception hierarchy. |
| `identifiers.py` | 317 | `RunId` (only random ID), `TickId`, `ProfileId`, `ComponentId`, `EventId` (deterministic). |
| `time.py` | 376 | `Timeline`, `Instant` (integer ns), `Clock` protocol, `SystemClock`, `ManualClock`, `UNIX_EPOCH` **(P2)**, `staleness()`, `is_stale()`. |
| `validation.py` | 258 | Boundary guards, never `assert`. `require_finite`, `require_range`, `require_probability`, `require_non_negative`, `require_positive`, `require_dimension`, `require_non_decreasing`. |
| `matrix.py` | 347 | `SymmetricMatrix` — packed lower triangle, pure-Python Cholesky, no NumPy. |

### `src/astra/contracts/` — the immutable records layers exchange

| File | Lines | Phase | Purpose |
|---|---|---|---|
| `sensing.py` | 217 | P1 | `SensorSample[PayloadT]`, `FusedSensorFrame[PayloadT]`, health/staleness classification. |
| `estimation.py` | 311 | P1 | `FastStateEstimate`, `SlowStateEstimate`, `InnovationRecord`. |
| `actuation.py` | 445 | **P1 (new)** | `ActuationChannel`, `ActuationSpace` (**how NFR5 domain-independence is achieved**), `ControlCommand`, `CommandOrigin`, `ProposedCommand`, `PredictedCommand`, `IssuedCommand` (**enforces SI-7**). |
| `assurance.py` | 262 | **P1 (new)** | `TrustAssessment`, `GateVerdict`, `SafetyVerdict` (**no TI field → SI-4**), `FailSafeSnapshot`. |
| `governance.py` | 395 | **P1 (new)** | `RuntimeContextSignature`, `CalibrationProfile` (**SI-9 quantile monotonicity**), `ProfileFieldHistory`, `ArbitrationDecision`, `is_candidate_admissible`. |
| `audit.py` | 384 | **P1 (new)** | `AuditEvent`, `DecisionRecord` (**the explainability unit**), `ExecutionOutcome`, `JsonValue`. |

### `src/astra/ports/` — Protocol interfaces (P1)

| File | Lines | Purpose |
|---|---|---|
| `pipeline.py` | 502 | One `Protocol` per layer: `SensorSource[PayloadT]`, `StateEstimator[PayloadT]` (**made generic in P3**), `TrustEstimator`, `CommandProposer`, `DynamicsPredictor`, `StatisticalGate`, `PhysicalAdmissibilityChecker`, `DeterministicShield`, `SafetyStateMachine`, `CalibrationArbiter`. |
| `infrastructure.py` | 188 | `EventSink`, `ProfileRepository`, `ActuationSink`, `FeedbackBus`. |

### `src/astra/invariants/` (P1)

| File | Lines | Purpose |
|---|---|---|
| `catalogue.py` | 388 | `SeparationInvariant` record + frozen catalogue SI-1…SI-10; runtime guards for SI-3 and SI-7. Enforcement claims **updated in P3** to match reality. |

### `src/astra/config/` (P1)

| File | Lines | Purpose |
|---|---|---|
| `schema.py` | 480 | pydantic-settings models. **No default for any safety threshold** (A-4). Extended in P2 (`fast_process_noise`, `slow_process_noise`, `yaw_rate_minimum_speed`) and P3 (`assured_clear_distance_m`). |
| `loader.py` | 336 | Layered resolution: packaged defaults → environment TOML → `ASTRA_*` env vars. Frozen after load. Emits the **configuration hash**. |

### `src/astra/observability/` (P1)

| File | Lines | Purpose |
|---|---|---|
| `context.py` | 173 | `contextvars` correlation: current `RunId`, `TickId`, `ComponentId`; `tick_scope()`. |
| `logging.py` | 250 | Structured logging; `QueueHandler` + background writer so **the hot path never blocks on I/O (SI-8)**. |
| `audit.py` | 278 | `JsonlAuditSink` — append-only, one file per run, schema-versioned. **This file is the certification evidence artefact.** |

### `src/astra/layers/` — the pipeline layers

| File | Lines | Phase | Purpose |
|---|---|---|---|
| `l1_sensing/bus.py` | 357 | **P2** | `SharedSensorBus[PayloadT]` — thread-safe fusion, per-modality staleness vs 50 ms, out-of-order rejection, canonical sample ordering, `BusStatistics`. |
| `l2_estimation/measurement.py` | 288 | **P2** | `Measurement` (carries its state **layout**), `MeasurementExtractor` protocol (**the domain-independence seam**), `fast_measurement`, `slow_measurement`. |
| `l2_estimation/models.py` | 117 | **P2** | `fast_transition` (kinematic bicycle), `slow_transition` (random walk). |
| `l2_estimation/filter.py` | 490 | **P2** | `DualRateUKF[PayloadT]` — two FilterPy UKFs, scaled unscented transform, innovation monitor, fail-closed numerics. |
| `l7_shield/shield.py` | 276 | **P3** | `HardSafetyShield` — three O(1) bounds, unconditional veto, stateless, `REASON_CODES`. |
| `l8_failsafe/machine.py` | 239 | **P3** | `FailSafeStateMachine` — four states, OOD counter, hysteresis, **latched HALT**. |

### `src/astra/runtime/` (P3)

| File | Lines | Purpose |
|---|---|---|
| `channels.py` | 270 | `ProposalWriter` / `ProposalReader` **capability pair** (SI-5 by construction), `open_proposal_channel`, `guard_core_a_isolation`, `guard_proposal_origin`. |

### `src/astra/replay/` (P2)

| File | Lines | Purpose |
|---|---|---|
| `tape.py` | 312 | `TapeHeader`, `PayloadCodec` protocol, `IdentityPayloadCodec`, `encode_frame`/`decode_frame`, canonical serialisation. **No wall-clock field, by design.** |
| `recorder.py` | 146 | `StateRecorder` — writes a run's inputs; blocking on purpose (§ Phase 2). |
| `harness.py` | 288 | `ReplayHarness` + `ReplayClock` — re-drives a tape, reusable, tick-range segments. |

### `src/astra/bootstrap/` (P1)

| File | Lines | Purpose |
|---|---|---|
| `composition.py` | 248 | The composition root. Loads+freezes config, builds clock, opens audit sink, verifies the invariant catalogue, returns an immutable `AstraRuntime`. |
| `cli.py` | 385 | `astra doctor`, `astra config show`, `astra invariants list`, `astra version`. The only place `print()` is allowed. |

### Configuration files

| File | Phase | Purpose |
|---|---|---|
| `config/astra.defaults.toml` | P1 | Only non-safety-critical defaults. |
| `config/environments/development.toml` | P1, ext. P2/P3 | Loose bring-up values, all marked provisional. |
| `config/environments/simulation.toml` | P1, ext. P2/P3 | Simulator operating point; slow UKF at 0.1 Hz (finding R-5). |
| `config/environments/certification.toml` | P1, ext. P2/P3 | **Deliberately refuses to load** — every safety threshold commented out. Names all **24** missing fields. |

### Tests

| Directory | Files | Tests | Purpose |
|---|---|---|---|
| `tests/unit/` | 29 | 1 616 | Behaviour of individual modules |
| `tests/architecture/` | 2 | 280 | Fitness tests over the codebase's own structure |
| `tests/integration/` | 2 | 30 | Layers wired together (**both created in P2/P3**) |
| `tests/property/` | 2 | 27 | Hypothesis-driven invariants |

New test files by phase:

- **P2:** `test_l1_sensor_bus.py` (779 lines), `test_l2_filter.py` (1 044), `test_l2_measurement.py` (450), `test_replay.py` (1 158), `tests/integration/test_phase2_pipeline.py`
- **P3:** `test_l7_shield.py` (415), `test_l8_failsafe.py` (582), `test_runtime_channels.py` (290), `tests/integration/test_phase3_safety_spine.py`

### Tooling and other

| File | Phase | Purpose |
|---|---|---|
| `pyproject.toml` | P1, ext. P2/P3 | Single source of truth for build, deps, ruff, mypy, pytest, coverage. P2 added `mypy_path = "stubs"`; P2/P3 added per-file ignores for `benchmarks/` and `stubs/`. |
| `.importlinter` | P1, ext. P2/P3 | **8 architecture contracts.** Grew from 5 → 6 (P2) → 8 (P3). |
| `Makefile` | P1 | `make check` = format + lint + mypy + lint-imports + pytest. |
| `.pre-commit-config.yaml`, `.editorconfig`, `.env.example`, `.gitignore` | P1 | Standard tooling. |
| `.github/workflows/ci.yml` | P1 | Matrix 3.12/3.13, runs the same `make check`. |
| `CHANGELOG.md` | P1 | Change history. |
| `benchmarks/latency.py` | **P2, ext. P3** | Reproducible software latency measurement. Now covers L1, L2, L7a, L8. |
| `stubs/filterpy/*.pyi` | **P2** | Local type stubs. **Also the enumeration a FilterPy safety-case qualification argument starts from.** |

### Documentation

| File | Phase | Purpose |
|---|---|---|
| `README.md` | P1, updated P2/P3 | What ASTRA is, status table, quick start, layout, honesty boundaries. |
| `docs/ARCHITECTURE.md` | P1 | How the system is put together and why. |
| `docs/ROADMAP.md` | P1, updated P2/P3 | What each phase builds. Phases 2 and 3 marked delivered. |
| `docs/SEPARATION_INVARIANTS.md` | P1 | The safety argument, invariant by invariant. |
| `docs/DOCUMENT_RECONCILIATION.md` | P1 | R-1…R-11: every contradiction across the four source documents. |
| `docs/ASSUMPTIONS.md` | P1, updated P2 | A-1…A-10. **A-8 updated with the R-6 resolution.** |
| `docs/CONVENTIONS.md` | P1 | Coding standards this repository enforces. |
| `docs/INSTALL.md`, `docs/DEVELOPMENT.md` | P1 | Setup and workflow. |
| `docs/adr/0001…0014` | P1 | One ADR per significant Phase 1 choice. |
| `docs/adr/0015-carla-interpreter-strategy.md` | **P2** | The R-6 decision. |
| `docs/spikes/R6-carla-interpreter.md` | **P2** | The full spike report, with source URLs and dates. |
| `docs/PHASE1_COMPLETION_REPORT.md` | P1 | |
| `docs/PHASE2_COMPLETION_REPORT.md` | **P2** | |
| `docs/PHASE3_COMPLETION_REPORT.md` | **P3** | |
| `docs/ENGINEERING_HANDOFF.md` | Pre-existing | ⚠️ **STALE** — header still says "Phase 1 ~40% complete". Superseded by this document. |

---

## 5. Phase 1 — Foundation (complete)

**Scope:** the vocabulary, contracts, interfaces, invariants, configuration and evidence machinery
every layer depends on. Deliberately **no layer logic**.

### Why Phase 1 came first

Six arguments, each grounded in the source documents:

1. **Replay tooling must exist before closed-loop integration.** The Demo Plan is explicit: *"Build
   state-recording/replay tooling before this stage, not during it… the difference between debugging
   in hours vs. days."* Replay requires deterministic identifiers, an injected clock, immutable
   records and a schema-versioned event log — every one a Phase 1 decision. Retrofit is a rewrite.
2. **L2 is a single point of common cause and everything reads it.** Before writing a UKF, the
   system needs an unambiguous, unit-typed, dimension-checked representation of "state estimate with
   covariance". Get that wrong and all three gates are wrong together.
3. **NFR8 makes the audit log a certification artefact, not a debug aid.** Evidence is only evidence
   if records are joinable, schema-versioned and complete from tick zero.
4. **Objective 1 is *formally defined* separation invariants.** They must be machine-checked, not
   commented.
5. **The hot-path budget constrains the foundation itself.** < 10 ms at 20 Hz means non-blocking
   logging, frozen O(1) config, no allocation on the nominal error path.
6. **NFR5 demands domain independence.** Only achievable if vehicle-specific vocabulary is confined
   to adapters from the first commit.

### What was delivered

- **Kernel** (8 modules): units with `NewType` SI policy, canonical enums with fail-closed
  `Verdict.merge()`, architectural constants, typed exception hierarchy with safety dispositions,
  deterministic identifiers, injected clock with timeline-tagged instants, boundary guards,
  packed symmetric matrix with pure-Python Cholesky.
- **Contracts** (6 modules): the records layers exchange. `IssuedCommand` makes SI-7 unrepresentable
  to violate; `SafetyVerdict` has no Trust Index field, making SI-4 structural; `CalibrationProfile`
  rejects a non-monotonic quantile table (SI-9).
- **Ports** (2 modules): a `Protocol` per layer, structural so a layer never imports the port it
  satisfies.
- **Invariants**: the SI-1…SI-10 catalogue as executable data, plus runtime guards.
- **Configuration**: layered, validated, startup-frozen, with a configuration hash. **No safety
  threshold has a default** — a missing one is a startup failure (A-4).
- **Observability**: correlation context, non-blocking structured logging, the append-only JSONL
  audit sink.
- **Bootstrap**: the composition root and the CLI.
- **Tooling**: `Makefile`, pre-commit, CI, `.importlinter` with 5 contracts.
- **Documentation**: 14 ADRs, architecture, roadmap, reconciliation, assumptions, conventions.

### Key design decisions (all recorded as ADRs)

| Decision | Chosen | Why |
|---|---|---|
| Python floor | **3.12** | PEP 695 generics, `typing.override`; security support to Oct 2028 |
| Simulator coupling | Behind a **port** | Keeps the interpreter question a deployment detail |
| Units | SI internally; `NewType` aliases | Static safety at **zero** runtime cost (a units library costs 50–100× on arithmetic) |
| Error model | Typed hierarchy carrying `SafetyDisposition` | An exception in a safety path is a statement about what the system may now do |
| Time | Injected `Clock`, integer-ns `Instant` with `Timeline` | Wall clock is non-monotonic; negative staleness reads as "perfectly fresh" |
| Covariance | Packed lower-triangular, no NumPy | Asymmetry becomes **unrepresentable**; kernel stays importable by offline tools |
| Identifiers | Exactly **one** random ID (`RunId`) | Replay must produce byte-comparable event streams |
| Hot-path data | Frozen + `slots=True` dataclasses | Validate once, then trust; no per-instance `__dict__` |
| Boundary data | pydantic v2 | Config parsed once from untrusted text, must fail loudly |

---

## 6. Phase 2 — Sensing, Estimation, Replay (complete except adapter)

### 6.1 The headline: R-6 resolved, and it dissolved

Finding **R-6** — the documents mandate CARLA 0.9.14, whose Python client ships for CPython ≤ 3.8,
while the project floors at 3.12 — was the single most consequential unresolved risk (RK-1). Three
routes had been named and none evaluated.

**None of them is needed.** CARLA **0.9.16**, released 2025-09-16, publishes official
`cp310`/`cp311`/`cp312` wheels to PyPI. Verified directly against `https://pypi.org/pypi/carla/json`
on 2026-07-29:

| Version | Uploaded | Wheel Python tags |
|---|---|---|
| 0.9.14 | 2022-12-24 | `cp27`, `cp37`, `cp38` |
| 0.9.15 | 2023-11-14 | `cp27`, `cp37`, `cp38`, `cp39`, `cp310` |
| **0.9.16** | **2025-09-14** | **`cp310`, `cp311`, `cp312`** |

R-6's premise expired between ADR-0003 being written and today. No sidecar, no IPC hop, no
unofficial binary, and the 10 ms budget is untouched. Recorded in
`docs/adr/0015-carla-interpreter-strategy.md` and `docs/spikes/R6-carla-interpreter.md`.

**A new constraint replaced it.** CARLA has **no macOS build** and its wheels carry no `macosx` tag,
so `pip install carla` fails on Darwin regardless of interpreter. See §15.

### 6.2 L1 — Shared Sensor Bus

`SharedSensorBus[PayloadT]` fuses five modalities into one timestamped frame per tick and classifies
each stream's freshness against the 50 ms budget of FR1.

**Three design decisions carry the weight:**

**The threading model.** Sensor readings arrive on foreign callback threads, not the control thread.
`publish()` is called from any thread and holds a lock for one dictionary comparison and one
assignment; `acquire()` holds it long enough to copy at most five entries. Both critical sections
are negligible against a 50 ms tick. A lock-free design was considered and rejected — it buys
nothing measurable at this scale and costs clarity in a module whose correctness argument is about
ordering.

**A later reading may not be replaced by an earlier one.** Readings can arrive out of order. If the
bus accepted whichever arrived last, a late-arriving old reading would replace a fresh one and the
stream's measured staleness would *travel backwards* — a stale stream would look healthy, which is
exactly the fault FR1 exists to catch. Superseded arrivals are **counted**, not silently dropped.

**Staleness is measured from acquisition, never arrival.** A reading delayed 80 ms in transport is
80 ms stale the instant it appears. Treating it as fresh because it just arrived would hide the
transport fault entirely.

### 6.3 L2 — Dual-Rate UKF

**Why unscented, not extended.** The fast process model is non-linear: heading integrates
`a_lat / v`, position integrates `v` through trigonometric functions of heading. An EKF would
linearise about the current estimate and accumulate that error exactly where the vehicle is turning
hardest. The unscented transform propagates sigma points through the true model — accurate to second
order, no Jacobians to derive and get wrong.

**The process models:**

```
Fast (20 Hz), x_f = [px, py, v, psi, a_lat]:
    px'    = px + v cos(psi) dt
    py'    = py + v sin(psi) dt
    v'     = v                          # Q carries what the model does not know
    psi'   = psi + (a_lat / v) dt       # yaw rate from steady-turn physics
    a_lat' = a_lat

Slow (1 Hz / 0.1 Hz), x_s = [mu_road, delta_tyre, rho_sensor]:
    x' = x                              # random walk; all movement in Q
```

`v' = v` and `a_lat' = a_lat` are honest, not lazy: longitudinal acceleration and lateral jerk are
neither in the state nor measured, so the model cannot predict them. `Q` is where "the model does
not know" belongs. Inflating the state with unobservable derivatives would produce confident
estimates of quantities nothing constrains.

`psi' = psi + (a_lat/v) dt` couples heading to lateral acceleration through actual physics, which is
what lets a lateral-acceleration measurement correct the heading estimate at all. The division is
guarded below a configured speed — at standstill the quotient is unbounded and meaningless.

**The innovation monitor is not a diagnostic.** All three Core-B gates read this filter's output,
which the architecture acknowledges as a genuine common-cause channel. The innovation sequence is
the *one* signal that detects filter divergence from inside L2, because it compares what the sensors
said against what the model expected. Its Mahalanobis distance raises a sensor-fault flag, and the
rolling distribution is the physics-grounded covariate-shift signal L6 will consume.

**The `MeasurementExtractor` seam.** The filter needs numbers; the bus carries payloads. Turning one
into the other requires knowing what a payload *is* — the knowledge the core is forbidden to hold
(NFR5). The adapter supplies the extractor; L2 consumes only `Measurement`, which is plain numbers
plus the state dimensions they observe **and the layout those indices address**.

### 6.4 The replay spine

Built in Phase 2, **not** Phase 7, per the Demo Plan's explicit instruction.

**The tape records inputs, never conclusions.** Replaying inputs reproduces outputs; recording
outputs would only let them be re-read. That distinction is what makes replay a debugging instrument
rather than a log viewer.

**The tape contains no wall-clock reading.** Not a creation timestamp, nothing. Any such field would
differ on every recording and defeat byte-comparison in the one artefact whose entire purpose is
byte-comparison.

**Serialisation is canonical.** Fixed separators, fixed key order, samples emitted in
`SensorModality` declaration order regardless of publish order.

### 6.5 Measured results

**Tracking**, synthetic vehicle at 20 m/s, 120 ticks straight then 180 in a steady 3 m/s² turn with
Gaussian sensor noise:

| Metric | Result |
|---|---|
| Final position error | **0.36 m** after 298 m travelled |
| Heading error | 0.0085 rad |
| Speed error | 0.020 m/s |
| `P_f` positive definite | Every tick |
| Innovation monitor | Quiet; mean Mahalanobis 1.38 |

**Replay:** byte-identical by SHA-256 over a 300-tick run with uneven sensor rates.

**Latency** (software measurement, macOS arm64, CPython 3.12.3):

| Stage | p50 | p99 | budget |
|---|---|---|---|
| L1 acquire (fusion) | 0.003 | 0.004 | 1.0 |
| L2 `update_fast` (UKF) | 0.119 | 0.213 | 1.0 |

### 6.6 The honest qualification

The roadmap's exit criterion says "against **CARLA** ground truth". This was validated against a
**synthetic kinematic vehicle**, because CARLA does not run on the available machine. That is a
weaker claim in a specific way: the synthetic vehicle integrates the same kinematics the filter
models, so it cannot expose a *modelling* error — only an implementation one. The ground-truth
vehicle is deliberately written out separately rather than calling the filter's own transition
function, so a change to the process model surfaces as a tracking error instead of cancelling.
Validation against real simulated dynamics remains outstanding.

---

## 7. Phase 3 — Deterministic Safety Spine (complete)

### 7.1 L7a — Hard Safety Shield

The deterministic gate, and the component with unconditional veto authority.

**Its independence is structural.** It reads the UKF state and the estimated road friction, and
nothing else: not the twin's prediction, not the conformal score, not the Trust Index, not the FSM
state. That absence is the entire point — its bounds fail only if the state estimate itself is
wrong, a failure mode neither the statistical gate (fails when exchangeability is violated) nor the
physical gate (fails on model drift) shares. The method signature enforces most of this: there is no
parameter through which a prediction or a score could arrive.

**The three bounds:**

| Bound | Form | Fails when |
|---|---|---|
| Tyre friction | `\|a_lat\| ≤ margin · μ_road · g` | commanded lateral acceleration exceeds available grip |
| Stopping distance | `d_min + v²/(2·margin·μ·g) ≤ d_avail` | the vehicle cannot stop inside the distance its ODD assures |
| Legal speed | `v ≤ v_legal` | a legal limit is exceeded |

Using the **estimated** `μ_road` from the slow filter rather than a constant is what makes the first
two adaptive, and it is demonstrable: **an identical state estimate and an identical proposal PASS
on dry tarmac and VETO on ice.** A shield with a hard-coded friction figure passes both.

The three are separate because they fail for unrelated reasons. The stopping-distance bound is not a
restatement of the speed limit: on a wet road the legal speed can be perfectly lawful and still
leave the vehicle unable to stop.

**Bounds are evaluated against the state, not the command in isolation.** A steering command is not
unsafe on its own — it is unsafe at 30 m/s on ice and fine at 5 m/s on tarmac. Judging a command
without the state it will act on would be judging a number.

**Fail-closed on a non-finite state.** NaN defeats every comparison rather than failing it, so a NaN
speed would silently satisfy all three bounds. That case raises `SafetyPathError`
(`FAIL_CLOSED`) rather than returning a verdict, because a non-finite state is a filter fault, not
an unsafe manoeuvre, and the evidence should say which.

### 7.2 L8 — Fail-Safe FSM

**Why a counter.** One integer that increments on VETO and decrements on PASS gives three properties
that would otherwise need separate machinery:

- *It distinguishes a glitch from a fault.* One VETO changes nothing; ten crosses a threshold.
- *Recovery is the same mechanism run backwards.* No separate recovery path that could disagree
  with the escalation path.
- *It is auditable.* One integer per snapshot reconstructs the full history.

**HALT is deliberately asymmetric.** Every other transition is reversible on the counter; HALT is
not. A controlled pull-over is not something to reverse because a few ticks passed, and resuming
automatically because a briefly-failed sensor started reporting plausible data again is exactly what
makes a fail-safe untrustworthy. Leaving HALT requires an explicit `reset()`.

**Hysteresis.** De-escalation happens at a *lower* counter value than escalation. Without that gap a
counter sitting on a threshold would oscillate on alternating verdicts, and an oscillating safety
posture is worse than either state it flips between — the speed cap and lane-change permission would
change every tick.

**Only the aggregate verdict is consulted.** *Which* gate vetoed is evidence for the log, not an
input to the escalation policy. Weighting gates differently would give one gate more authority than
another, which SI-3 forbids.

### 7.3 The one-way channel (SI-5)

**Why two types, not one queue.** The obvious implementation is a shared queue with a comment saying
Core-A must only call `put`. A comment does not fail a build.

Instead the channel is a **capability pair** with disjoint methods. Core-A holds a `ProposalWriter`
whose entire public surface is `{send, pending}` — **there is no method through which a verdict, an
FSM state or a calibration table could return.** Core-A cannot read a Core-B artefact not because it
has been told not to, but because the object it holds has no such method. Same technique
`IssuedCommand` uses for SI-7: make the illegal operation *unrepresentable* rather than forbidden.

**Why this matters adversarially, not just tidily.** Core-A is a learned policy trained by
optimisation. Anything it can observe, it can learn to exploit. A proposer that can see the gate can
learn to slip past it, which converts defence in depth into a single adversarial optimisation
problem with the safety monitor as its objective.

**Bounded and non-blocking.** If the queue fills, Core-B has stalled, and a proposal that cannot be
delivered must not block Core-A's tick. `send()` returns `False`; the caller treats it as a tick that
produced no proposal, which produces an empty verdict set, which merges to VETO **through the
ordinary path with nothing special-cased.**

### 7.4 Exit criteria — all four met

| Criterion | Result |
|---|---|
| No PASS can suppress a shield VETO (SI-3) | ✅ Against a *real* shield verdict, in any order; empty set → VETO |
| FSM walks NOMINAL → DEGRADED → LIMP → HALT and back without restart | ✅ Verified; HALT latched through 200 clean ticks |
| Both layers' latency measured | ✅ L7a p99 **0.004 ms**, L8 p99 **0.003 ms** |
| The channel is a real topology, not a convention | ✅ Capability pair + 2 runtime guards |

**Full hot path so far** (L1 + L2 + L7a + L8): p50 0.13 ms, **p99 0.24 ms** — 0.5% of a 50 ms tick.

### 7.5 New architecture contracts

Grew from 6 to **8**:

- **`si-3-shield-independence`** — the shield imports no other gate and no FSM. A shield that could
  read the posture could make its verdict depend on the posture its own verdict produces.
- **`l8-judges-verdicts-only`** — the machine imports no gate implementation, so it cannot weight
  one gate's veto above another's.

---

## 8. Defects found and fixed

Ten across Phases 2 and 3, all found by tests rather than review. The first four are the ones that
mattered.

| # | Defect | Why it was serious |
|---|---|---|
| **1** | **A NaN staleness budget silently disabled FR1.** The guard checked `budget < 0`, which is `False` for NaN, and `staleness > nan` is also `False`. | A reading 1 000 s old classified as `HEALTHY`. **Fail-open in the one rule L1 exists to enforce.** The identical hole existed in `kernel.time.is_stale`. |
| **2** | **A cross-layout measurement silently corrupted the state.** `DualRateUKF._step` read `state_indices` and discarded `layout`. | A slow-state measurement applied to the fast filter drove the speed estimate from 12.0 → 1.099 m/s, and the innovation monitor reported it as an ordinary sensor fault rather than a wiring fault. **Every gate above L2 would have read that state.** |
| **3** | **The reverse direction escaped as a raw `IndexError`** carrying no `SafetyDisposition`. | The caller's single reviewable `except SafetyPathError` — the entire basis of "anything wrong here becomes a VETO" — would not have fired. |
| **4** | **`acquire()` read the clock outside the lock.** | A sample published in the intervening window carried `observed_at` after `fused_at` and was reported with *negative* staleness — manufacturing the future-timestamp fault signal out of ordinary scheduling jitter. |
| 5 | `replay/harness.py` imported `datetime` at runtime | Violated the project's own architecture test that only `kernel/time.py` may. Fixed by exporting `UNIX_EPOCH`. |
| 6 | `ReplayHarness.frames()` was single-use | Its own docstring says the workflow is re-running the same fifty ticks repeatedly; the clock never rewound. |
| 7 | The bus emitted samples in publish order | Two runs over identical inputs produced frames equal in content but not structure, defeating frame-by-frame replay comparison. |
| 8 | `StateEstimator` was not generic in the payload | `FusedSensorFrame` is invariant, so the protocol was only satisfiable by an estimator written against `object` — every estimator except the real ones. |
| 9 | Process noise had no configuration slot | `Q` sets the state estimate all three gates read; it now follows the same A-4 no-default discipline as every other empirical parameter. |
| 10 | `d_avail` had no configuration slot | The stopping-distance bound had nothing to compare against. Added as `assured_clear_distance_m`, a required certified ODD parameter. |

Every one is now pinned by a regression test. The two architecture rules (clock discipline,
`print()` confinement) were verified by injecting a violation, confirming the test fails, and
reverting.

---

## 9. Phase 4 — Proposer & Digital Twin (NOT STARTED)

*Demo Plan Week 1c.* **This is the next phase.**

### Scope

- **`l4_proposer`**: SB3 PPO + `LagrangianConstraintWrapper` (PID dual update). Constraints: lane
  deviation ≤ d_max, |a_long| ≤ a_max, collision rate = 0. **Veto rate excluded from the reward and
  constraint computation (SI-6).**
- **`l5_twin`**: small PyTorch PINN with the physics loss; offline training script.
- **`l7b_physical`**: the PINN-based admissibility checker, formally assigned `GateId.PHYSICAL`
  (finding R-3). Distinct from L7a, which stays independent of it.
- **`training/`**: offline corpora — highway + urban × clear + adverse, ≥ 500 calibration samples
  per context.

### Exit criteria

- **Checkpoint 1 from the Demo Plan** — one real scenario runs end-to-end with **no feedback loops**,
  proving independent gates + deterministic veto + FSM.
- A code-level check confirms Core-A has **no import, no shared memory and no queue** back from
  Core-B. The capability pair already covers the queue; the import contract activates here.
- SI-6 stops being review-only: a test asserts the training signal's field set excludes veto rate.

### What must be done first

**Spike PyTorch + Stable-Baselines3 on Python 3.12** (assumption A-6). This is unverified and is the
same shape of risk R-6 turned out to be. Do it before writing any L4 code — exactly as the R-6 spike
was done before the adapter.

### Contracts to activate

```ini
[importlinter:contract:si-5-one-way-core-channel]
name = SI-5 Core-A cannot import any Core-B module
type = forbidden
source_modules =
    astra.layers.l4_proposer
forbidden_modules =
    astra.layers.l5_twin
    astra.layers.l6_statistical_gate
    astra.layers.l7_shield
    astra.layers.l8_failsafe
allow_indirect_imports = False
```

This contract is already written, commented, in `.importlinter`. Uncomment it once
`astra.layers.l4_proposer` exists.

### Risks

- **A-6 (unverified):** torch/SB3 on 3.12. Would force 3.11; the core is unaffected.
- **Does not compress:** PPO wall-clock training time is GPU-bound, not coding-bound. Start training
  corpora early.
- The PINN twin will be trained on **simulated dynamics, not real vehicle physics** — honesty
  boundary #5.

---

## 10. Phase 5 — Statistical Assurance (NOT STARTED)

*Demo Plan Week 2a.*

### Scope

- **`l3_trust`**: hand-rolled **EnbPI** (MAPIE lacks robust online time-series EnbPI) + Mondrian
  context bucketing over the four `ContextClass` values. `TI = 1 − F̂_k(α_{t+1})`.
- **`l6_statistical_gate`**: `α = |π_prop − π̂| / σ(x)` where `σ(x) = √P_f[control dim]`;
  class-conditional quantiles; CQR for heteroscedasticity; **MMD covariate-shift detector on the
  rolling innovation distribution** → dynamic ε tightening.

### Exit criteria

- EnbPI unit-tested **in isolation on synthetic time series** before integration (the Demo Plan
  explicitly recommends this).
- Per-class coverage ≥ 94.5% over 1 000 steps on synthetic data.
- SI-4 architecture test green (TI absent from `SafetyVerdict` — already structurally true).

### Risks

- **RK-2 (High):** hand-rolling EnbPI correctly is the primary implementation risk in the whole
  project after L9. A subtly wrong implementation gives a silently invalid coverage guarantee.
  Mitigation: build and unit-test in isolation on synthetic series; verify empirical coverage per
  class before integration.
- Conformal prediction's coverage guarantee **assumes exchangeability**, which adversarial
  perturbation violates by construction — honesty boundary #4. That is *why* there is more than one
  gate.

### Already in place

`σ(x)` is available: `FastStateEstimate.variance_of(field)` resolves the index from the canonical
field order, so a reordering cannot silently repoint the normalisation term. The rolling innovation
distribution is already maintained by `DualRateUKF.innovation_history`.

---

## 11. Phase 6 — Runtime Calibration Management (NOT STARTED)

*Demo Plan Week 2b.* **Highest architectural intricacy of any single component.**

### Scope

- **`l9_rcm`**:
  - RCS builder (reliability-weighted, so a degraded sensor lowers its own contribution).
  - Cold-path Mahalanobis KB search.
  - Mandatory gates: expired signature, platform mismatch, critical failure history.
  - `T(c) = w₁·sim + w₂·val + w₃·hist − w₄·risk` scoring.
  - Admissibility `T(c) ≥ τ AND val(c) = 1` as a **hard** gate.
- Shadow execution + **CDI** → commit or rollback.
- **Core-B independent table validation** (signed checksum + quantile monotonicity/range) — SI-9.
- **Bounded safe exploration**: 50% of nearest certified max speed, no lane changes, steering ±15°,
  evidence logged, four exit conditions. **Never halts.**
- **`calibration/profiles/`**: the four seed profiles. **No tunnel profile** — that omission is
  deliberate and is what makes validation Phase 3.5 meaningful.

### Exit criteria

- **Checkpoint 2 from the Demo Plan** — the tunnel scenario works: no admissible profile,
  exploration engages, the vehicle keeps moving.
- Cold path proven never to block a tick (SI-8).

### Already in place

- `RuntimeContextSignature`, `CalibrationProfile`, `ProfileFieldHistory`, `ArbitrationDecision`
  contracts.
- `is_candidate_admissible()` encodes the hard conjunction in one reviewable place.
- `CalibrationProfile` already rejects a non-monotonic quantile table.
- `IssuedCommand` already refuses any issuer that is not L9 (SI-7).
- `ProfileId` binds name and version, so an audit record can never be ambiguous about what was
  active (NFR7).

### Risks

- **RK-4 (Medium):** L9 complexity. Budget the most debugging time here. Building it *after* the
  safety spine (now done) means it can be tested against a working veto path.
- SI-8 needs an actual timing test, which does not exist yet.

---

## 12. Phase 7 — Closing the Loops (NOT STARTED)

*Demo Plan Week 3 — protected slack, does not compress.*

Bring up **one at a time**, confirming stability before adding the next:

| Loop | What it does | Notes |
|---|---|---|
| **FB1** | Applied (not proposed) command re-anchors the UKF | Everything else depends on it. Bring up first. |
| **FB2** | 50-sample buffer → EWC update of the PINN **output layer only**, Fisher-anchored on 200 historical samples | **Explicit catastrophic-forgetting test required: highway accuracy must not degrade after adapting to rain.** |
| **FB3** | Executed outcomes → online Mondrian requantilisation | |
| **FB4** | Executed command → simulator sync | Prototype-only; brought up last, lowest risk. |

### Exit criteria

- Stable closed loop over a long run; no oscillation, drift or feedback overcorrection.
- Every loop demonstrably improves its target metric and degrades it when removed.

### Risks

- **RK-3 (High):** closed-loop emergent dynamics. The Demo Plan's warning applies: bugs here are
  usually not code bugs but emergent dynamics. **The replay harness from Phase 2 is the primary
  debugging instrument** — and it exists, byte-exact, which is precisely why it was built early.
- **RK-5 (Medium):** EWC may fail to prevent catastrophic forgetting in practice. Fisher penalty
  tuning is empirical and does not compress.

---

## 13. Phase 8 — Observability & Demo Harness (NOT STARTED)

*Demo Plan Week 4.*

### Scope

- **`apps/dashboard/backend`**: FastAPI + WebSocket streaming live layer state.
- **`apps/dashboard/frontend`**: React + Recharts rendering the pipeline diagram itself:
  - TI gauge
  - **L6 and L7 shown as separately lit paths** — this is the *visual proof of gate independence*
  - `P_f` visibly widening/narrowing the acceptance band
  - FSM as a lit state diagram
  - RCM's KB search / shadow execution / "SAFE EXPLORATION ENGAGED" banner
  - Event ticker with independent-cause attribution
- **Comparison harness**: two synchronised instances — full ASTRA vs. baseline (raw Core-A) —
  against the identical injected fault. **Highest-impact visual in the demo.**
- **Interactive fault injection** — the audience presses the button. Deliberate credibility move.
- Explainability surface = replay of `DecisionRecord` provenance (per finding R-7).

### Exit criteria

- Every dashboard number traceable to a live record. Nothing scripted.
- Pre-recorded fallback run captured.

### Already in place

`DecisionRecord` is the explainability unit and already ties tick → frame health → state → TI →
proposal → each gate verdict → FSM → arbitration → issued command → config hash. It round-trips to
stable JSON.

---

## 14. Phase 9 — Validation & Evidence (NOT STARTED)

### Scope

- **Seven-phase continuous drive** through CARLA Town04: highway → urban → rain/night →
  **tunnel (3.5)** → sensor fault → adversarial FGSM → recovery. **The vehicle never stops.**
- **Ablation study**: disable FB1/FB2/FB3 individually; run ICP-only without the Shield; disable
  safe exploration and force HALT.
- Metrics against Table VII targets — reported as measurements, with the software/hardware latency
  distinction stated explicitly every time.
- Evidence pack: audit logs, replayable runs, dependency licence inventory, assumption closure.

### The independence evidence

This is where "three structurally independent gates" stops being architecture and becomes evidence:

- **Validation Phase 5 (FGSM camera attack)** is designed so **exactly one** gate fires.
- **Validation Phase 4 (IMU corruption)** is designed so **two** fire, for different reasons.

Those two scenarios *are* the independence evidence. Nothing before Phase 9 can supply it.

### Exit criteria

All claims in the papers are either demonstrated by code that ran, or **explicitly listed as not
demonstrated**. No overclaiming.

---

## 15. The blocker: CARLA adapter

**Status: deferred, not descoped.** This is the one Phase 2 scope item not delivered.

### Why

CARLA has **no macOS build**. Its wheels carry no `macosx` tag, so `pip install carla` fails on
Darwin arm64 regardless of interpreter. The Apple Silicon PR (carla#5086) has been open and unmerged
since January 2022. Docker images are `linux/amd64` only, and a VM is not a substitute for a
GPU-accelerated simulator.

Writing an untestable adapter into a safety-critical repository would violate this project's own
standards more seriously than leaving it absent.

### What is needed

1. A **Linux x86-64 host with an NVIDIA GPU**.
2. CARLA **0.9.16** (not 0.9.14 — see §6.1; and not 0.10.0, which is daylight-only and Town 10 only,
   disqualifying for a project whose covariate-shift work is specified around a rain/highway shift).
3. `pip install carla==0.9.16`.
4. **First task on that machine:** confirm the install and a client-to-server connection actually
   work. A-8 is currently *evidenced* from published wheel metadata, **not verified by a run**.

### What is NOT blocked

L1, L2, the replay spine, L7a, L8 and the channel are all complete and tested against in-process
fakes. Phases 3, 4, 5 and much of 6 need no simulator. The `MeasurementExtractor` protocol is
exactly where the adapter attaches, and `.importlinter` forbids importing `carla` anywhere in the
core — so the adapter is a leaf, not a dependency.

---

## 16. Separation invariants — enforcement status

| ID | Invariant | Enforcement | Status |
|---|---|---|---|
| **SI-1** | **Sensor opacity.** No layer above L2 reads raw sensor payloads. | import-linter + payload generics | 🟡 Contract narrower than the invariant until more layers exist |
| **SI-2** | **Single state source.** All layers obtain state exclusively from L2. | import-linter layering | 🟡 Same |
| **SI-3** | **Unconditional veto.** No PASS can suppress a VETO; an empty verdict set is a VETO. | `Verdict.merge()`, `SafetyVerdict.aggregate`, `guard_verdict_aggregation`, **2 new import contracts** | ✅ **Enforced + proven against a real shield verdict** |
| **SI-4** | **Trust isolation.** TI must not participate in Core-B's verdict. | `SafetyVerdict` has no TI field and no way to acquire one | ✅ **Structural** |
| **SI-5** | **One-way core channel.** Core-A may write `π_prop`; it may read no Core-B artefact. | **Capability pair** (writer has no read method) + `guard_core_a_isolation` + `guard_proposal_origin` | ✅ **Enforced.** Import contract activates in Phase 4 |
| **SI-6** | **Veto-rate exclusion.** Core-B's veto rate must never enter Core-A's reward. | Code review | 🔴 **Review-only until Phase 4** |
| **SI-7** | **Sole actuation authority.** Only L9 may emit a command. | `IssuedCommand` refuses any non-L9 issuer at construction | ✅ **Unrepresentable to violate** |
| **SI-8** | **Timing-domain separation.** Cold-path work must never block a hot-path tick. | Non-blocking audit sink | 🟡 **No timing test yet** (Phase 6) |
| **SI-9** | **Independent calibration validation.** Core-B validates any table before activation. | `require_non_decreasing` in `CalibrationProfile` | 🟡 Monotonicity enforced; **checksum stored but never verified** (Phase 6) |
| **SI-10** | **Evidence non-influence.** Exploration evidence must not modify the live safety argument. | import-linter contract | ✅ Enforced |

**Acknowledged residual weakness, which must always be stated and never hidden:** all three gates
consult the same L2 state estimate. That is a genuine common-cause channel. It is *mitigated* by the
innovation-sequence Mahalanobis monitor and by FB1 — **not eliminated.** As of Phase 3 this is a
*live* channel, not a theoretical one: L7a reads it today, and every gate built from Phase 4 onward
will too.

---

## 17. Risk register

| ID | Risk | Severity | Status |
|---|---|---|---|
| **RK-1** | CARLA vs Python 3.12 incompatibility | ~~High~~ | ✅ **CLOSED** — R-6's premise expired (§6.1) |
| **RK-1b** | **CARLA has no macOS build** | **High (new)** | 🔴 **OPEN** — needs a Linux x86-64 + NVIDIA host (§15) |
| **RK-2** | Hand-rolled EnbPI subtly wrong; coverage guarantee silently invalid | High | ⬜ Phase 5 |
| **RK-3** | Closed-loop emergent dynamics (oscillation, drift, overcorrection) | High | ⬜ Phase 7. **Mitigation already built:** byte-exact replay |
| **RK-4** | L9 RCM complexity | Medium | ⬜ Phase 6. Mitigation in place: a working veto path now exists |
| **RK-5** | EWC fails to prevent catastrophic forgetting | Medium | ⬜ Phase 7 |
| **RK-6** | PPO training wall-clock time | Medium | ⬜ Phase 4. GPU-bound, not coding-bound |
| **RK-7** | Patent disclosure through a public repo or ungated demo | **High (non-technical)** | 🔴 **OPEN** — private repo + proprietary licence in place; **filing status still unconfirmed** |
| **RK-8** | Overclaiming (1.25 µs, "eliminates hallucination", zero-failure) | **High (credibility)** | 🟡 Managed — honesty boundaries in README, every latency figure labelled |
| **RK-9** | Scope creep from the "platform" framing | Medium | 🟡 Managed — phase discipline held through 3 phases |
| **RK-10** | **`uv` is not installed; the documented setup path is unexercised** | **Low (new)** | 🔴 OPEN — see §3 |

---

## 18. Assumptions register

| ID | Assumption | Status |
|---|---|---|
| **A-1** | Domain independence via ports + a configured `ActuationSpace` | 🟡 Holding. Real test is Phase 6: add a non-automotive profile without touching core |
| **A-2** | A 10 ms end-to-end budget at 20 Hz is achievable in CPython | ✅ **Strongly supported** — four layers use 0.24 ms p99, 2.4% of the budget |
| **A-3** | Append-only JSONL is adequate as prototype certification evidence | ⬜ Phase 9 review |
| **A-4** | θ1/θ2/θ3, ε, γ, τ, δ_CDI have **no defensible defaults** | ✅ **Verified** — `certification.toml` refuses to load, naming all **24** missing fields |
| **A-5** | A single random `RunId` is sufficient for byte-comparable replay | ✅ **Verified** for sensor inputs. Must extend to RNG seeding in Phase 4 |
| **A-6** | **Python 3.12 is supported by torch / SB3 / filterpy at Phase 4** | 🟡 **filterpy ✅ verified (1.4.5 runs clean). torch + SB3 UNVERIFIED — spike this first** |
| **A-7** | Repository stays private and proprietary until filing is confirmed | 🔴 Outside engineering. Confirm with the filing agent |
| **A-8** | The CARLA/interpreter incompatibility is resolvable without changing the core | ✅ **RESOLVED via route (a)** — but *evidenced*, not *verified*: nothing has been installed or run |
| **A-9** | "MPC candidate scoring" fits behind the `StatisticalGate` port | ⬜ Clarify with Dr. Chaitra R. before Phase 5 |
| **A-10** | Explainability = decision provenance, not model-internal attribution | 🟡 Realised by `DecisionRecord`. Confirm stakeholders don't expect SHAP/LIME |

---

## 19. Technical debt register

| # | Item | Origin |
|---|---|---|
| 1 | **The UKF has met only synthetic dynamics.** Cannot expose a modelling error, only an implementation one. | P2 |
| 2 | **Process noise `Q` is provisional.** Values labelled as tuning starting points, not tuned values. | P2 |
| 3 | **FilterPy is unmaintained and inside a safety path.** ISO 26262 8-12 asks for qualification. `stubs/filterpy/` enumerates the exact surface depended on — where the argument *starts* — but the argument is not written. | P2 |
| 4 | **`Measurement` restricts observation to selecting state dimensions.** A future sensor needing a genuinely non-linear `h` needs the type extended. | P2 |
| 5 | **`d_avail` is a certified ODD parameter, not a perceived distance.** Catches "too fast for these conditions" but not "too fast for *that* obstacle". Perception-sourced `d_avail` needs a state-vector extension. | P3 |
| 6 | **The FSM hysteresis margin is a module constant, not configuration.** Defensible as a property of the mechanism, but revisit if oscillation is ever observed. | P3 |
| 7 | SI-1/SI-2 import contracts are narrower than the invariants they claim | P1 |
| 8 | SI-6 is review-only until Phase 4 | P1 |
| 9 | SI-8 has no timing test | P1 |
| 10 | SI-9's checksum is stored but never verified | P1 |
| 11 | **`docs/ENGINEERING_HANDOFF.md` is stale** — header says "Phase 1 ~40% complete". Superseded by this document. | Pre-existing |
| 12 | **`uv` is not installed;** the documented setup path is unexercised (§3) | P1/P2 |

---

## 20. What must never be claimed

Carried forward from the Prototype & Demo Plan §8, plus what the current state adds.

1. **The 1.25 µs Core-B intercept latency is an analytical hardware bound, not a measurement.** It
   is an AbsInt aiT WCET figure (500 MHz, 627 cycles) for a hardware implementation. The software
   prototype's real latency must be reported against the software target of < 5 ms, **never** against
   the hardware figure.
2. **False positive/negative targets are < 1%, not zero.** The argument is defence in depth through
   structurally independent gates, never "eliminates hallucination".
3. **The shared UKF state is an acknowledged residual common-cause channel** across all three gates —
   mitigated by the innovation monitor and FB1, **not eliminated**. As of Phase 3 this is live.
4. **Conformal prediction's coverage guarantee assumes exchangeability**, which adversarial
   perturbation violates by construction. That is why there is more than one gate.
5. **The PINN twin will be trained on simulated dynamics, not real vehicle physics.**
6. **Core-B here is Python processes, not fabricated hardware.** FPGA/ASIC is roadmap, not done.

### Added by the current state

7. **ASTRA governs nothing end to end.** L1, L2, L7a and L8 exist. There is no proposer, no twin, no
   statistical gate and no arbitrator — so there is no pipeline, and no false-positive,
   false-negative or veto-rate figure exists.
8. **Every latency figure is a software measurement of four layers**, on one machine, excluding the
   simulator, the audit sink, and L3/L4/L5/L6/L9. A **floor**, not an estimate.
9. **Gate independence is currently a claim about one gate.** With only the deterministic gate built,
   "three structurally independent gates" is architecture, not evidence. The evidence is the Phase 9
   scenarios designed so that exactly one gate fires.
10. **All tracking accuracy is against a synthetic vehicle**, through a filter validated against the
    same synthetic vehicle.
11. **The CARLA 0.9.16 finding rests on published wheel metadata**, not on an install anyone has run.

**Any metric this repository reports must come from code that ran. Nothing is hardcoded to look good
in a demo.**

---

## 21. Conventions that must not drift

- **Absolute imports only.** No relative imports (`TID` rule). No package facade re-exports — import
  from the defining module.
- **Docstring on every public symbol**, Google convention, `Args`/`Returns`/`Raises`.
- **Full type annotations.** `mypy --strict` is a gate, not advice.
- **No magic numbers.** A number is either an architectural constant (`kernel/constants.py`) or
  configuration (`config/`). The test: *would a software engineer or a safety engineer review this
  change?*
- **SI units internally**, always. Non-SI types exist only so non-SI values are visible in a
  signature; they must never appear in a `ports/` signature.
- **Never `assert` for a safety check** — `python -O` deletes it.
- **Never a bare `except`** (`BLE`). Catch `AstraError` or a specific subclass.
- **Never `time.time()`** — use the injected `Clock`.
- **Never `print()`** outside `bootstrap/cli.py` (and `benchmarks/`, which is outside the package).
- **No f-strings in logging calls** (`G`) — the format cost is paid even when filtered out.
- **Fail closed.** Absence of a verdict is a VETO. An empty verdict set is a VETO.
- **Every claim traceable.** A number in a report, a dashboard or a paper must come from a record a
  run produced.

### Phase discipline

Implement only the current phase. Future layers stay as ports and documented placeholders — never as
empty stubs with no purpose. Do not over-engineer and do not under-engineer. Both are failures.

### Deliverable at the end of each phase

A "Phase *n* Engineering Completion Report" covering: files created · architecture established ·
engineering decisions · risks · technical debt · readiness score (/10) · why the project is ready
for the next phase.

---

## Appendix A — commands

```bash
cd /Users/tanayhuddar/Downloads/astra

# The full gate, exactly as CI runs it
PATH="$PWD/.venv/bin:$PATH" make check

# Individually
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov=astra

# Targeted
.venv/bin/pytest tests/unit -q
.venv/bin/pytest tests/integration -q
.venv/bin/pytest tests/architecture -q
.venv/bin/pytest tests/property -q

# CLI
.venv/bin/astra doctor
.venv/bin/astra config show
.venv/bin/astra invariants list
.venv/bin/astra version

# Latency (software measurement — never quote as the 1.25 µs hardware bound)
.venv/bin/python benchmarks/latency.py -n 2000
.venv/bin/python benchmarks/latency.py -e development -n 500
```

---

## Appendix B — glossary

**ASIL** Automotive Safety Integrity Level · **BIST** Built-In Self-Test · **CBF** Control Barrier
Function · **CDI** Calibration Divergence Index · **CMDP** Constrained Markov Decision Process ·
**CQR** Conformalized Quantile Regression · **ECC** Error Correction Code · **EnbPI** Ensemble Batch
Prediction Intervals · **EWC** Elastic Weight Consolidation · **FGSM** Fast Gradient Sign Method ·
**FMEA** Failure Mode and Effects Analysis · **ICP** Inductive Conformal Prediction · **KB**
Calibration Knowledge Base · **MMD** Maximum Mean Discrepancy · **ODD** Operational Design Domain ·
**OOD** Out-of-Distribution · **PINN** Physics-Informed Neural Network · **PPO** Proximal Policy
Optimisation · **RCM** Runtime Calibration Management · **RCS** Runtime Context Signature ·
**SECDED** Single Error Correction, Double Error Detection · **SI-n** Separation Invariant n ·
**SOTIF** Safety Of The Intended Functionality · **TI** Trust Index · **UKF** Unscented Kalman
Filter · **WCET** Worst-Case Execution Time

---

## Immediate next actions, in order

1. **Spike torch + Stable-Baselines3 on Python 3.12** (A-6). Do this before writing L4 code, exactly
   as R-6 was spiked before the adapter. It is the same shape of risk.
2. **Arrange a Linux x86-64 + NVIDIA host.** Unblocks the CARLA adapter, real UKF validation, and
   everything in Phases 6 and 9 that needs a simulator.
3. **Confirm the patent filing status** (RK-7, A-7). This gates any external demo regardless of code
   readiness.
4. **Build Phase 4** — L4 proposer + L5 twin + L7b physical checker → Checkpoint 1.
5. **Reconcile the `uv` deviation** (RK-10) — install uv, or document the venv path in
   `docs/INSTALL.md`.
6. **Delete or clearly mark `docs/ENGINEERING_HANDOFF.md` as superseded** by this document.

### Non-engineering gates before any external demo

From Demo Plan §10 — these block regardless of code readiness:

- [ ] **Provisional patent filing status confirmed**
- [ ] NDA in place for demo attendees
- [ ] Team split confirmed (single builder vs. parallel L2/L7/L8 · L3/L4 · L5/L6 tracks)
- [ ] Baseline system for the side-by-side chosen (raw Core-A vs. lockstep emulation)
- [ ] Final three showcase scenarios confirmed
- [ ] Backup recording scheduled ahead of the first live demo

---

## Document provenance

| | |
|---|---|
| **Prepared by** | Tanay S. Huddar |
| **Created** | Thursday, 30 July 2026 at 14:06:23 IST (UTC+05:30) |
| **ISO 8601 (UTC)** | `2026-07-30T08:36:23Z` |
| **Repository** | `/Users/tanayhuddar/Downloads/astra` |
| **Verified against** | A green quality gate at time of writing |
| **Gate result** | 1 953 tests passed · 99.10% coverage · 8 architecture contracts kept, 0 broken |
| **Toolchain** | CPython 3.12.3 · ruff 0.16.0 · mypy 2.3.0 · pytest 9.1.1 · import-linter 2.13 |
| **Host** | macOS 15.7.3, arm64 (Darwin) |

Every figure in this document was read from the repository or produced by a run at the time of
writing. None is carried over from a document, estimated, or rounded in a flattering direction. Two
counts were corrected during verification: the test-file count (35 → 36) and the number of safety
thresholds `certification.toml` refuses to start without (16 → 17).

---

*End of state document — ASTRA, prepared by Tanay S. Huddar, 30 July 2026, 14:06 IST.*

---

# ADDENDUM — Stage 1 complete: the system runs end to end

**Added** 31 July 2026, continuing from Sushanth C.'s status report
(`docs/1144_2026-07-31_Sushanth_status.md`), which recorded the project at ~55%
with the note: *"The system has never run end to end."*

**It does now.**

## What closed the gap

| Module | Purpose |
|---|---|
| `runtime/pipeline.py` | The tick loop. L1→L2→L3→L4→channel→L5→L6/L7b/L7a→merge→L8→L9→record. |
| `runtime/assembly.py` | The composition root: builds all ten layers, seed profiles, seed calibration. |
| `l3_trust/classifier.py` | `RuleBasedContextClassifier` — the real classifier, previously only a test stub. |
| `l4_proposer/policies.py` | `KinematicPlaceholderPolicy` — **explicitly not** a trained PPO policy. |
| `l9_rcm/fallback.py` | `ProportionalFallbackController` — what drives when a proposal is vetoed. |
| `demo/run_pipeline.py` | A runnable scenario driver. |
| `tests/integration/test_full_pipeline.py` | 9 end-to-end tests. |

`DecisionRecord` gained `prediction` and `twin_weights_digest`, so one tick now
produces one complete evidence row — the Stage 1 exit criterion.

## Measured, after training the twin

```
python training/train_twin.py --out var/twin/synthetic.pt    # held-out RMSE 7.3e-3
python demo/run_pipeline.py --scenario nominal
python demo/run_pipeline.py --scenario ice
```

| Scenario | Gates that fire |
|---|---|
| nominal cruise, dry | none — all PASS |
| hard cornering, dry | PHYSICAL (lateral jerk) |
| **same cornering, ice** | **PHYSICAL + DETERMINISTIC** — the second for an unrelated reason (stopping distance) |
| over the legal limit | DETERMINISTIC only |

The FSM escalates NOMINAL → DEGRADED → LIMP under sustained vetoes and the
vehicle keeps receiving fallback commands throughout.

## Latency: a defect found and fixed

The first end-to-end measurement **missed** the < 10 ms budget at p99 = 12.3 ms.
Profiling located it precisely: `MmdShiftDetector.discrepancy` is `O(n²)` in the
window and the gate computed it **twice per tick** — once through
`effective_epsilon`, once to record as evidence. Six million kernel evaluations
per four hundred ticks.

Memoising it — the discrepancy is a pure function of the retained window, so the
cache is exact rather than approximate — gave:

| | before | after |
|---|---|---|
| p50 | 3.369 ms | **1.782 ms** |
| p99 | 12.305 ms | **1.978 ms** |
| max | 26.805 ms | **2.217 ms** |
| < 10 ms target | **MISSED** | **MET** (4.0% of a 50 ms tick) |

Pinned by three regression tests.

## Gate

**2 316 tests · 98.00% coverage · 12 contracts kept · mypy clean on 126 files.**

## What is still true from Sushanth's "must never be claimed"

Every item stands, and one is now sharper:

**The pipeline runs on `KinematicPlaceholderPolicy`, not a trained PPO policy.**
A deterministic controller cannot hallucinate, drift, or be adversarially
perturbed — the three things every gate downstream exists to catch. So this run
demonstrates that the *plumbing* composes. It demonstrates **nothing** about
whether the gates catch what they exist to catch. No false-positive rate, no
false-negative rate, no veto rate, and no gate-independence claim follows from
it. Those need Stage 4's trained policy and the Phase 9 scenarios.

The twin is trained on synthetic kinematics, so it can expose an implementation
error and never a modelling one. Calibration is seeded from synthetic scores,
not a certification corpus.

## Remaining route

Stages 2–7 of Sushanth's plan are unchanged, minus the part Stage 1 absorbed.
Next: **Stage 2** — generate ≥500 real non-conformity scores per context class
from the trained twin and verify per-class empirical coverage ≥ 94.5%, replacing
the seeded corpus. Then **Stage 3** (Linux + CARLA) and **Stage 4** (PPO).

---

# ADDENDUM — Stage 2 complete: the conformal gate is calibrated

**Added** 31 July 2026. Continues the Stage 1 addendum above.

Sushanth's Stage 2 called for ">=500 non-conformity scores per context class
from the trained twin and the synthetic vehicle" and "per-class empirical
coverage >= 94.5% over 1,000 steps", with the exit: *"conformal quantiles are
finite; L6 stops vetoing everything; RK-2 has measured evidence behind it."*

All three met.

## What was built

| Module | Purpose |
|---|---|
| `l3_trust/corpus.py` | `CalibrationCorpus` — scores plus the provenance to defend them; `coverage_report` |
| `training/generate_calibration.py` | Harvests scores from the real proposer, twin and filter; measures coverage |
| `l3_trust/classifier.py` | Real context classifier (was a test stub) |
| `l9_rcm/fallback.py` | Real fallback controller (was a test stub) |
| `l4_proposer/policies.py` | Placeholder policy, corrected twice — see below |

A corpus records the twin's weights digest, the configuration hash, the seed and
the **score definition**, and `read` refuses a corpus built under a different
definition. A quantile fitted to one score definition says nothing about a gate
computing another, and the mismatch would be invisible in the numbers.

## Measured coverage — the RK-2 evidence

1,000 scores per class, mean over 200 random calibration/validation splits,
epsilon = 0.05:

| class | quantile | coverage | ±sd | worst split | sequential |
|---|---|---|---|---|---|
| HIGHWAY_CLEAR | 1.1699 | **0.9515** | 0.0135 | 0.9100 | 0.9200 |
| URBAN_CLEAR | 1.7406 | **0.9503** | 0.0130 | 0.9180 | 0.9060 |
| DEGRADED_SENSOR | 1.7253 | **0.9498** | 0.0142 | 0.8900 | 0.9500 |

Every class clears the 0.945 floor against 0.950 nominal.

**Coverage is reported twice on purpose.** The shuffled figure is exchangeable
by construction, so it tests the quantile arithmetic — and it is the only thing
the conformal guarantee actually promises. The sequential figure preserves the
autocorrelation a live control loop faces, which the guarantee does *not* cover.
Reporting only the first would conceal honesty boundary #4.

## Three defects found, and what each cost to learn

**1. The coverage measurement was underpowered, not the code wrong.** The first
report showed HIGHWAY_CLEAR at 0.9260 and flagged it below target. Before
changing anything, `conformal_quantile` was Monte-Carlo'd against theory on
uniform, exponential and lognormal draws at three sample sizes: **it matches to
within 0.15 percentage points.** The `+1` in `ceil((n+1)(1-eps))` is right and
the infinite-threshold branch is right.

What was wrong was the measurement. One split at 500 calibration points has a
standard deviation near 1.5 pp, so 0.9260 was an unremarkable 1.6-sigma draw —
and a single split landing at 0.96 would have been an equally meaningless pass.
`coverage_report` now averages 200 splits and prints the spread and the worst
split beside the mean.

**2. The corpus sampled two point speeds.** It could not calibrate a run
cruising anywhere between them, and L6 correctly reported it had no calibration
for the situation. A calibration set has to span the operational design domain
it certifies; the generator now sweeps speeds and lateral accelerations in held
segments, discarding each segment's filter transient.

**3. The placeholder policy was wrong twice, and the physical gate caught both.**

Its steering gain was chosen in command units with no reference to the plant.
Against a control effectiveness of 140 m/s² per radian, a gain of 0.05 commanded
**6.3 m/s² of counter-acceleration** into a vehicle turning at 1.5.

Corrected to scale by the plant gain, it was still wrong in a deeper way: a
damping law proportional to `-lateral` asks a turning vehicle to be at zero one
tick later — about **30 m/s³ against a limit of 8**. It vetoed on every tick of
every turn, and the veto was correct: the gate was not strict, the controller
was asking for something impossible.

The command now names the lateral acceleration the vehicle should have *next*
tick — the current one, walked toward zero by at most one tick's jerk allowance.
Pinned by a parametrised test over eight lateral accelerations.

**These are the gates doing their job.** Two independent controller bugs, found
by the safety architecture rather than by review.

## Stage 2 exit, verified

| scenario | result |
|---|---|
| cruise 15 / 25 / 30 m/s straight | 40/40 PASS, no gate fires |
| ramped turn to 1.5 m/s² | 40/40 PASS, no gate fires |
| ramped turn to 3.0 m/s² | 40/40 PASS, no gate fires |
| over the legal limit | DETERMINISTIC fires |
| hard turn on ice | DETERMINISTIC fires |

L6 no longer vetoes everything, and faults are still caught.

## Gate

**2 450 tests · 98.23% coverage · 12 contracts kept · mypy clean on 131 files.**
The four new modules are at 100%, 98%, 100% and 100%.

## Reproducing it

```bash
python training/train_twin.py --out var/twin/synthetic.pt
python training/generate_calibration.py --out var/calibration/synthetic.json
python demo/run_pipeline.py --scenario nominal
```

The integration tests skip with an explanatory message if either artefact is
absent, so a clean checkout still passes.

## What Stage 2 does not establish

**The corpus is synthetic.** It comes from a twin trained on kinematics from the
same family the UKF assumes, so it can expose an implementation error — a wrong
quantile rank, a broken normalisation, a gate reading the wrong covariance entry
— and it **cannot** establish that coverage holds on real driving. Phase 9's
CARLA drives replace it.

**RAIN_NIGHT is uncalibrated, and cannot be reached at all.** The classifier
decides context from the fast state and the innovation; precipitation and
ambient light are in neither. The nearest proxy, road friction, lives in the
slow state and is not passed to it. Returning RAIN_NIGHT on a heuristic the
signature cannot see would be inventing a classification, so the class is left
uncalibrated and the generator says so in its output. Closing it needs either a
wider classifier input or a weather source from an adapter — both visible
architectural changes. **Recorded as debt, not approximated.**

**Every claim about the policy still stands from Stage 1.** The pipeline runs on
`KinematicPlaceholderPolicy`, which is deterministic and cannot hallucinate,
drift or be adversarially perturbed. No false-positive rate, no false-negative
rate, no veto rate and no gate-independence claim follows from any of this.

## Next

**Stage 3** — Linux + CARLA. Closes RK-1b and converts A-8 from evidenced to
verified. Then **Stage 4**, the PPO policy, which is what finally makes the
gates' numbers mean something.

---

# ADDENDUM — Closing the no-hardware gaps

**Added** 31 July 2026, after Stage 2.

Stage 3 needs a Linux host with an NVIDIA GPU, which is not available. Rather
than write a CARLA adapter that cannot be run, every remaining item on
Sushanth's *Known gaps* and *Immediate next actions* lists that needs no
hardware was completed.

## Gap #9 / action #5 — the flaky concurrency test

**Reproduced first.** Under twelve-way CPU load the L1 concurrency tests did not
produce wrong answers; they produced **no answer at all**. Every
`Barrier.wait()` and `Thread.join()` in the file was unbounded, so a thread
starved by the scheduler left the others waiting indefinitely.

Every rendezvous is now bounded — 30 s at a barrier, 60 s at a join — and a
`_start_and_join` helper asserts that no thread is still alive afterwards.
Verified directly: a thread that never arrives now surfaces as
`BrokenBarrierError` in about two seconds instead of hanging. 20/20 clean runs.

The ceilings are generous on purpose. They can only be reached by a genuine
stall, never by slowness, so this does not trade one flake for another.

## Gap #8 — SI-8 had no timing test

`tests/unit/test_si8_timing.py`, six tests. They assert **decoupling**, not
absolute microseconds — a benchmark that passes on a quiet laptop says nothing
about a loaded one, whereas these comparisons hold whatever the machine is
doing because both sides move together:

- the caller's cost does not track slow disk writes (`fsync_each_record=True`);
- the caller's cost does not grow with the backlog;
- a saturated queue drops rather than blocks, and the drop is counted;
- **structurally**: the thread calling `record_decision` is never the thread
  that touches the file.

One thing the file deliberately does *not* assert is that serialisation is free.
It is not, and it is not meant to be: `_enqueue` renders JSON on the calling
thread so that an unserialisable record fails at its origin instead of vanishing
inside a writer no caller can hear. **My first attempt asserted the wrong thing**
— it obstructed `json.dumps` and failed, which is the sink working as designed.
SI-8 is about keeping *syscalls* off the tick.

## Gap #8 — SI-9's checksum was stored but never computed

The profiles carried `checksum="seed-highway_clear"` — a placeholder string that
nothing verified. SI-9 requires Core-B to validate a table independently before
activation, and monotonicity was only half of that.

`CalibrationProfile` now has `compute_checksum()`, `has_valid_checksum()` and
`with_checksum()`. The digest covers exactly the fields that change what a
profile *authorises* — identity, context, centroid, covariance, quantile table,
coverage, limits, platform, validity window, field history — field-separated by
`\x1f` so that moving a character between fields cannot produce a collision.

`runtime.assembly.verify_profiles` runs before the arbitrator is handed
anything, and it lives in the composition root rather than inside L9 on purpose:
a check inside the component that activates the table would be the proposer
validating its own proposal. Demonstrated — a tampered quantile table is refused
with `InvariantViolationError`.

## Gap #7 — `TrustAssessment` could not say "uncalibrated"

It was encoded as a quantile of `0.0`: correct fail-closed *behaviour*, ambiguous
*record*. A reader could not distinguish "no calibration, reject everything" from
"calibrated, and this class genuinely has a threshold near zero" without
recovering epsilon and comparing the sample count against
`minimum_samples_for`.

`is_calibrated` is now an explicit, **required** field. Required rather than
defaulted because both defaults are wrong: `True` is fail-open, `False` would
quietly mark every hand-built assessment uncalibrated. Adding a key is a minor
change under the audit schema policy, so no version bump was needed. Three tests
pin the distinction, including the case the flag exists for — a calibrated class
whose genuine threshold is zero.

## Gaps #10, #11 / actions #3, #4 — CI and stale counts

The lockfile went stale twice because nothing exercised a from-scratch frozen
install. CI now runs `uv lock --check` before anything else, so a stale lockfile
fails in one line rather than surfacing in a training run.

A second new step installs the package **with no dev groups and no extras** and
imports the kernel and contracts, asserting NumPy and torch are absent from
`sys.modules`. That turns the two independence contracts from an import-linter
rule into a runtime fact — an offline evidence tool must be able to read an audit
archive without the numerical stack. Verified locally before trusting CI with it.

Stale documentation counts corrected. Note the certification field count has
moved again: it is **24**, not the 21 Sushanth measured, because Stage 1 and 2
added `trust.highway_speed_boundary_kmh`, `estimation.fast_process_noise`,
`estimation.slow_process_noise` and `shield.assured_clear_distance_m`.

## Gap #6 (action) — the quantile read by an outside eye

Sushanth asked for "one stats-literate person" to read `l3_trust/quantile.py`.
That was done differently but to the same end: `conformal_quantile` was
Monte-Carlo'd against theory on uniform, exponential and lognormal draws at
three sample sizes, and **matches to within 0.15 percentage points**. The `+1` in
`ceil((n+1)(1-eps))` is right and the infinite-threshold branch is right. A human
statistician's reading is still worth having, but the arithmetic is no longer
unexamined.

## Gate

**2 459 tests · 98.17% coverage · 12 contracts kept · mypy clean on 132 files ·
0 broken doc links.**

## What remains, and what it needs

| Item | Blocker |
|---|---|
| CARLA adapter, real UKF validation | **Linux x86-64 + NVIDIA GPU** |
| Trained PPO policy (Stage 4) | Above, plus GPU wall-clock |
| Feedback loops FB1–FB4 (Stage 5) | Stage 4 |
| Dashboard and comparison harness (Stage 6) | — |
| Validation and evidence pack (Stage 7) | Stages 3–5 |
| SI-6 mechanical enforcement | A trained policy to have a training signal at all |
| RAIN_NIGHT calibration | A classifier input the fast state does not carry |

Everything that could be finished on this machine has been.
