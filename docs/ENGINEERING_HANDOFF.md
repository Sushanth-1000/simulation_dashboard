# ASTRA — Engineering Handoff & Master Context

**Document purpose:** complete, self-contained context transfer. Anyone (or any AI session)
picking this up should be able to continue the build without re-reading the four source PDFs and
without re-deriving a single architectural decision.

| | |
|---|---|
| **Project** | ASTRA — Autonomous Safety, Trust, and Runtime Architecture |
| **Institution** | Dept. of CSE, B.M.S. College of Engineering, Bengaluru |
| **Authors** | Sushanth C., Tanay S. Huddar, Tarun Gowda V., T. Tilak Reddy |
| **Guide** | Dr. Chaitra R., Associate Professor |
| **Handoff date** | 29 July 2026 |
| **Current phase** | Phase 1 (Foundation) — **~40% complete**, see §9 |
| **Repository state** | `astra/` — kernel complete and passing the full quality gate; contracts in progress |
| **Confidentiality** | Proprietary, unpublished. Patent filing pending. Do not publish. |

---

## Table of contents

1. [Standing instructions for every future session](#1-standing-instructions-for-every-future-session)
2. [Source documents and what each contributes](#2-source-documents-and-what-each-contributes)
3. [Consolidated architecture](#3-consolidated-architecture)
4. [Document reconciliation — contradictions found and resolved](#4-document-reconciliation--contradictions-found-and-resolved)
5. [Separation invariants (the safety argument)](#5-separation-invariants-the-safety-argument)
6. [Dependency graphs](#6-dependency-graphs)
7. [Why Phase 1 is the correct starting point](#7-why-phase-1-is-the-correct-starting-point)
8. [Setup decisions and their rationale](#8-setup-decisions-and-their-rationale)
9. [Current build status — file by file](#9-current-build-status--file-by-file)
10. [Remaining Phase 1 work, in execution order](#10-remaining-phase-1-work-in-execution-order)
11. [Full roadmap: Phase 1 → working prototype](#11-full-roadmap-phase-1--working-prototype)
12. [Assumptions register](#12-assumptions-register)
13. [Risk register](#13-risk-register)
14. [Architecture Decision Records index](#14-architecture-decision-records-index)
15. [Conventions that must not drift](#15-conventions-that-must-not-drift)

---

## 1. Standing instructions for every future session

These are the operating rules the work is being executed under. They are reproduced here so that
behaviour stays identical across sessions.

### Role

Act as an elite engineering team, not a chatbot: Principal AI Software Architect, Senior ML
Engineer, Senior Backend Engineer, Senior Python Engineer, DevOps Engineer, Solution Architect,
Tech Lead, Enterprise Architect, MLOps Engineer, Security Engineer, Technical Documentation
Expert.

Build ASTRA as a **production-grade enterprise software product** — the way a runtime AI safety
platform would be built inside NVIDIA, Tesla, Waymo, DeepMind, OpenAI, Microsoft Research, Bosch,
Qualcomm, Mercedes-Benz, Continental or Siemens. This is not a prototype, not a hackathon
project. Think for a long time before writing any code. Quality is infinitely more important than
speed.

### Non-negotiable rules

- **The four uploaded documents are the source of truth.** Do not invent architecture. Where
  documents overlap, merge intelligently. Where they conflict, state the conflict before
  implementing (see §4).
- **Maintain architectural consistency across sessions.** Every session is a continuation of one
  long-lived enterprise project.
- **Never sacrifice architecture for a shorter response.** If a response approaches the context
  limit, stop at a logical engineering checkpoint, summarise what is complete, and state what
  remains.
- **Explain every engineering decision:** why this, why not the alternative, advantages,
  trade-offs, long-term scalability, enterprise considerations, maintainability, performance
  impact, future compatibility. Teach while building.
- **Before creating a file:** state why it exists, why it is needed, how future phases use it,
  its dependencies, its responsibilities.
- **After creating a file:** state what was created, why, how it works, how it connects to other
  files, what future phases build on it.
- **Validate before moving on:** naming consistency, architecture consistency, dependency
  consistency, no duplicated logic, scalability, maintainability, enterprise readiness.
- **Do not jump ahead.** Implement only the current phase. Future layers stay as ports and
  documented placeholders — never as empty stubs with no purpose.
- **Do not over-engineer and do not under-engineer.** Both are failures.
- **No unbacked claims.** Any metric ASTRA reports must come from code that ran. Nothing is
  hardcoded to look good in a demo.

### Code quality bar

Docstrings on every public symbol · full type hints · comments only where they add information ·
meaningful names · SOLID · Clean Architecture · PEP 8 · no duplicated code · no magic values ·
no unnecessary abstractions · reusable · extensible · modern Python.

### Phase discipline

Only Phase 1 is being built. Explicitly **out of scope until later phases**: runtime monitoring,
explainability outputs, dashboard, APIs, ML, safety engine, policy engine, drift detection,
alerting.

### Deliverable at the end of each phase

A "Phase *n* Engineering Completion Report" covering: files created · architecture established ·
engineering decisions · risks · technical debt · readiness score (/10) · why the project is ready
for the next phase.

---

## 2. Source documents and what each contributes

All four live in the Claude Project **"Major Project - Tanay"**. All four have been read in full.

| Document | Role | Unique content found only here |
|---|---|---|
| `ASTRA_shortened.pdf` | **Primary technical authority.** Latest, most honest version of the paper. | Consolidated L1–L9 numbering; FMEA table (Table V); threat model & 3 adversary classes; per-layer latency table (Table III) with *software* targets; explicit statement that validation is **planned, not executed**; ASIL decomposition + 4 CCF measures |
| `ASTRA_paper 1.pdf` | Earlier draft of the paper. **Superseded** on numbering and on empirical claims. | RCM cold-path flow diagram (Fig. 3); richer prose on shadow execution and safe exploration; the (now-retracted) "21-minute run" and "≈47 evidence tuples" figures |
| `ASTRA_mp1report.pdf` | **Requirements authority.** MP-1 academic report. | FR1–FR12 and NFR1–NFR8 — the only formal requirement statements in the whole corpus; class diagram method signatures; sequence diagram for a nominal tick and for a shield VETO; hardware/software requirement tables; cost estimate |
| `ASTRA_patent_report_final.pdf` | Patent-oriented restatement. Near-identical to the MP-1 report. | Confirms the IP-sensitivity of the work; title variant of the acronym |
| `ASTRA_Prototype_and_Demo_Plan.md` | **Implementation authority.** | Per-layer implementation spec with effort estimates; feedback-loop bring-up order and why; 4-week build plan; demo architecture; **§8 honesty boundaries**; proposed module structure; open items incl. patent-filing gate |

**Project-level objective statement** (from the Claude Project description) maps 1:1 onto the
architecture — it is a product-level restatement, not a different system:

| Project objective | Realised by |
|---|---|
| Monitor AI predictions continuously | L6 ICP gate — Core-B intercepts *every* `π_prop` |
| Detect abnormal operating conditions | L2 innovation monitor + L6 MMD covariate-shift detector + L9 RCS drift |
| Estimate prediction confidence | L3 Conformal Trust Module → Trust Index `TI ∈ [0,1]` |
| Explain every AI decision | NFR8 + per-gate verdict attribution → `DecisionRecord` (see R-7) |
| Validate decisions using configurable safety policies | L7 Hard Safety Shield + versioned calibration profiles |
| Trigger corrective actions during unsafe situations | L8 Fail-Safe FSM + L9 fallback / bounded safe exploration |
| Maintain complete audit logs for compliance | NFR8 + append-only JSONL evidence log |
| Real-time operator visibility | Dashboard (Demo Plan §7.3) — Phase 8 |

---

## 3. Consolidated architecture

### 3.1 The governing idea

The AI controller is an **untrusted proposer**. An independent governance pipeline sits between it
and the actuators. ASTRA does not try to make the AI provably safe (open problem); it governs the
**actuation boundary**.

Three processes plus an arbitrator:

- **Core-A** (QM/ASIL-A) — CMDP agent, proposes one command per tick.
- **Core-B** (ASIL-D(D)) — safety island, three structurally independent gates.
- **RCM** — the only component authorised to issue an actuator command.
- Core-A → Core-B is a **one-way** channel carrying `π_prop` only.

### 3.2 The nine layers

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

### 3.3 Timing domains

| Domain | Work | Software budget |
|---|---|---|
| **Hot path** | L1 → L2 → L3/L4 → L5 → L6 → L7 → L8 → L9 active-table lookup | fast UKF < 1 ms · Trust < 2 ms · Core-A < 3 ms · Core-B intercept < 5 ms · RCM hot < 1 ms · **end-to-end < 10 ms** at 20 Hz |
| **Cold path** | RCM KB search, shadow execution, CDI, evidence logging | ms → s, **must never block a tick (SI-8)** |

> The **1.25 µs** figure is an *analytical hardware WCET bound* (AbsInt aiT, 500 MHz, 627 cycles).
> It is **not** measurable by the Python prototype and must never be reported as one.

### 3.4 The three gates and their distinct failure modes

| Gate | Layer | Fires on | Fails when |
|---|---|---|---|
| `STATISTICAL` | L6 | `α_{t+1} > q̂^{(k)}_{1−ε}` | exchangeability is violated — i.e. under adversarial perturbation |
| `PHYSICAL` | L5 → L7b | predicted next state is not Newtonian-admissible | PINN drift outside EWC's correction capacity |
| `DETERMINISTIC` | L7a | a hard bound is exceeded | only if the UKF state itself is wrong |

Phase 5 of the validation plan (FGSM camera attack) is designed so **exactly one** gate fires.
Phase 4 (IMU corruption) is designed so **two** fire, for different reasons. Those two scenarios
*are* the independence evidence.

---

## 4. Document reconciliation — contradictions found and resolved

| ID | Conflict | Resolution |
|---|---|---|
| **R-1** | Layer numbering: `ASTRA_paper 1.pdf` numbers Core-B stages L4–L6 and RCM as L7; the other three documents use L1–L9. | **Adopt L1–L9.** `paper 1` is the earlier draft and is superseded. Encoded in `LayerId`. |
| **R-2** | `paper 1` reports results as achieved ("21-minute run", "≈47 evidence tuples"); `ASTRA_shortened` states plainly that the prototype and all metrics are **planned, not executed**. | **Nothing is a result until code produces it.** All figures in Tables VI/VII are targets. No metric may ever be hardcoded. This is also Demo Plan honesty boundary #1. |
| **R-3** | Demo Plan says L7 has "no dependency on L5 or L6 outputs"; the papers describe L7 as "combined Hard Safety Shield **and physical recheck**", and the physical recheck uses the PINN prediction. | **Split explicitly.** `L7a` Hard Safety Shield = deterministic, reads *only* UKF state, zero dependency on L5/L6 (preserves unconditional-veto independence). `L7b` Physical Checker = the PINN-based admissibility gate, formally assigned `GateId.PHYSICAL`, depends on L5. Both claims are then simultaneously true. |
| **R-4** | Mondrian class names differ: `paper 1` gives `{HIGHWAY-CLEAR, URBAN-RAIN, SENSOR-DEGRADED}`; Demo Plan and validation plan give the four KB seed profiles `{highway_clear, urban_clear, rain_night, degraded_sensor}`. | **Adopt the four KB seed names**, plus `UNCLASSIFIED` for the tunnel case. Encoded in `ContextClass`. Trust-module classes and KB profiles are one enumeration, as the Demo Plan states they match. |
| **R-5** | Slow UKF rate quoted as 1 Hz and 0.1 Hz in different places. | Not a conflict: 1 Hz deployment, 0.1 Hz prototype. Both are **configuration**, not constants. |
| **R-6** | Documents mandate **Python 3.10+** *and* **CARLA 0.9.14**. CARLA 0.9.14's official Python client ships for Python 2.7/3.6/3.7/3.8 only. **These are incompatible as stated.** | Simulator is isolated behind a port (ADR-0003). Three options, to be decided in Phase 2: (a) upgrade to CARLA 0.9.15+/0.10.x with newer interpreter support; (b) community-built egg/wheel for 3.10+; (c) run the CARLA client as a Python 3.8 sidecar process bridged to the 3.12 core. Core is unaffected either way. **This is the single most consequential unresolved technical risk.** |
| **R-7** | Project description promises "Explain every AI decision"; no XAI layer exists in any paper. | **Explainability in ASTRA = decision provenance**, not SHAP/LIME feature attribution: for each tick, which gate fired, on what evidence, under which calibration profile, at which configuration hash. This is exactly NFR8 plus the Demo Plan's "independent cause" event ticker. Realised by the `DecisionRecord` contract. Model-internal attribution is explicitly **not** claimed. |
| **R-8** | "MPC scoring" inside L6 is named but never specified. | Treated as a sub-stage of L6 behind the same `StatisticalGate` port. Deferred; flagged as a documentation gap to close with the guide. |
| **R-9** | Core-A reads the Trust Index — does that violate Core-A/Core-B isolation? | No. L3 is in the `SHARED` domain, not Core-B. TI is withheld from **Core-B's verdict** (SI-4), and Core-A is blind to **Core-B's outputs** (SI-5). Two different invariants; neither is violated. |
| **R-10** | Patent report title reads "Autonomous Safety **and** Trust Runtime Architecture". | **Adopt "Autonomous Safety, Trust, and Runtime Architecture"** — used by three of four documents. |
| **R-11** | Demo Plan §9 proposes a flat prototype module layout (`core/`, `feedback/`, `comms/`…) with no packaging, tests or config; NFR5 requires domain independence. | Adopt a `src/astra/` package with hexagonal ports. **Every proposed module maps to a new home** (see §11 mapping table) — the architecture is respected, only the packaging is upgraded. Confirmed with the project owner. |

---

## 5. Separation invariants (the safety argument)

Objective 1 of the project is *"a nine-layer pipeline with formally defined separation invariants
between layers."* These are those invariants. Each has an enforcement mechanism; prose alone does
not count.

| ID | Invariant | Enforcement |
|---|---|---|
| **SI-1** | **Sensor opacity.** No layer above L2 reads raw sensor payloads. L9 may read reliability *metadata* only. | import-linter forbidden contract + payload generics |
| **SI-2** | **Single state source.** All layers obtain state exclusively from L2's estimates; no layer re-derives state from sensors. | import-linter + code review |
| **SI-3** | **Unconditional veto.** No PASS from any component can suppress a VETO. Aggregation is fail-closed; an *empty* verdict set is a VETO. | `Verdict.merge()` + unit test |
| **SI-4** | **Trust isolation.** The Trust Index must not participate in Core-B's binary verdict. It flows to L4 (monitoring) and L9 (routing) only. | `SafetyVerdict` has no TI field; architecture test |
| **SI-5** | **One-way core channel.** Core-A may write `π_prop`; it may not read any Core-B artefact (verdict, FSM state, calibration table, quantiles). | import-linter forbidden contract + one-way queue topology + runtime guard |
| **SI-6** | **Veto-rate exclusion.** Core-B's veto rate may be logged as a diagnostic but must never enter Core-A's reward or constraint computation. | code review + Phase 4 test asserting the training signal's field set |
| **SI-7** | **Sole actuation authority.** Only L9 may emit a command to the actuation sink. | `IssuedCommand` records issuer; runtime guard; architecture test |
| **SI-8** | **Timing-domain separation.** Cold-path work must never block a hot-path tick. | non-blocking audit sink; Phase 6 latency test |
| **SI-9** | **Independent calibration validation.** Core-B independently validates any calibration table (signed checksum + quantile monotonicity/range) before activation, even though RCM proposed it. | `require_non_decreasing` + Phase 6 checksum verification |
| **SI-10** | **Evidence non-influence.** Evidence logged during safe exploration must not modify the live safety argument; it feeds only the offline certification pipeline. | separate sink; architecture test forbidding evidence→gate imports |

**Acknowledged residual weakness (must always be stated, never hidden):** all three gates consult
the same L2 state estimate. That is a genuine common-cause channel. It is *mitigated* by the
innovation-sequence Mahalanobis monitor and by FB1 — not eliminated.

---

## 6. Dependency graphs

### 6.1 Layer dependency graph (runtime data flow)

```
L1 ──▶ L2 ──┬──▶ L3 ──┬──▶ L4 ──▶ L5 ──▶ L6 ──▶ L7 ──▶ L8 ──▶ L9 ──▶ actuators
            │         └────────────────────────────────────────────▶ L9  (TI routing)
            ├──▶ L4 (state)
            ├──▶ L5 (state)
            ├──▶ L6 (P_f for σ(x), innovation for MMD)
            ├──▶ L7 (state — and ONLY state)
            └──▶ L9 (RCS inputs)

FB1: L9 ──▶ L2      FB2: outcome ──▶ L5      FB3: outcome ──▶ L3      FB4: L9 ──▶ sim
```

**Critical reading:** L2 is the sole state source (SI-2) and therefore the sole common-cause
channel. It must be correct before anything downstream is trustworthy — this is why the Demo Plan
insists it is tested in isolation against ground truth before any wiring.

### 6.2 Module dependency graph (compile-time, enforced by import-linter)

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

Strictly acyclic and strictly downward. `kernel` has zero dependencies — which is what lets an
offline evidence-analysis tool, a certification script or the dashboard process import ASTRA's
vocabulary without installing NumPy, PyTorch or CARLA.

---

## 7. Why Phase 1 is the correct starting point

Six arguments, each grounded in the source documents rather than in general good practice.

**1. The Demo Plan names closed-loop integration as the highest-risk stage, and says the tooling
must exist *before* it.** Verbatim: *"Build state-recording/replay tooling before this stage, not
during it… the difference between debugging in hours vs. days."* Replay is not a feature that can
be bolted on: it requires deterministic identifiers, an injected clock, immutable records and a
schema-versioned event log. Every one of those is a Phase 1 decision. Retrofit is a rewrite.

**2. L2 is a single point of common cause and everything reads it.** Before writing a UKF, the
system needs an unambiguous, unit-typed, dimension-checked representation of "state estimate with
covariance". Get that wrong and all three gates are wrong together — the exact failure mode the
papers call out as the residual weakness.

**3. NFR8 makes the audit log a certification artefact, not a debug aid.** *"All veto events,
Trust Index values, FSM state transitions, and calibration switches shall be logged with
timestamps for post-hoc analysis and certification evidence."* Evidence is only evidence if the
records are joinable, schema-versioned and complete from tick zero. Logs added later have a hole
at the beginning, exactly where the interesting bugs are.

**4. Objective 1 is *formally defined separation invariants*.** The Demo Plan is explicit that
these must be machine-checked: *"Verify this with a code-level check (no import, no shared memory
region, no queue) not just a comment."* An architecture fitness harness must exist before the code
it constrains, or the first violation is discovered after it has been built on.

**5. The hot-path budget constrains the foundation itself.** < 10 ms end-to-end at 20 Hz means the
logging framework must be non-blocking, the config must be frozen and O(1) at read time, and
error handling must not allocate on the nominal path. These are foundation-layer properties. A
logger chosen in Phase 8 cannot retroactively make Phase 2 fast.

**6. NFR5 demands domain independence.** *"The architecture shall be domain-independent… new
operational contexts through the addition of certified profiles without modification to any other
component."* That is only achievable if the vehicle-specific vocabulary is confined to adapters
from the very first commit. Introducing `tyre_friction` into the core and extracting it later is a
migration, not a refactor.

**Counter-check — what would go wrong if we started at L1/L2 instead?** We would write a UKF
against untyped tuples, discover the unit ambiguity during the Phase 4 gate work, discover the
replay gap during Phase 7 closed-loop debugging (the stage the Demo Plan protects with slack
precisely because it does not compress), and discover the audit gap when assembling evidence.
Phase 1 costs days. Those three discoveries cost weeks each, in the worst week of the schedule.

---

## 8. Setup decisions and their rationale

| Decision | Chosen | Why | Rejected alternatives |
|---|---|---|---|
| **Python floor** | **3.12** | PEP 695 generics (`class SensorSample[PayloadT]`) and `typing.override` are directly useful in an interface-heavy architecture. Security support to Oct 2028 — beyond the project horizon. Broad support across torch / SB3 / filterpy by 2026. | 3.10 (docs' floor, but EOL Oct 2026 — dead before the project ends); 3.11 (no PEP 695); 3.13/3.14 (bugfix-current, but ML-stack lag is a real Phase 4 risk) |
| **Simulator coupling** | Behind a **port**; no `carla` import in core | CARLA 0.9.14's client supports Python ≤3.8 (see R-6). Isolation makes the interpreter question a deployment detail, not an architecture one. Also delivers NFR5. | Pin the whole project to 3.8 (EOL, no modern typing) |
| **Package/dep manager** | **uv** | Single tool for interpreter install, venv, resolution, lockfile and task running. Order-of-magnitude faster resolution matters when CI runs on every commit. PEP 621/735 native. | Poetry (slower, historically non-standard metadata); pip + requirements.txt (no lockfile, no interpreter management); conda (heavyweight) |
| **Build backend** | **hatchling** | PEP 517/621 native, no `setup.py`, reads `pyproject.toml` verbatim. | setuptools (legacy surface); poetry-core (tied to Poetry) |
| **Layout** | **`src/` layout** | Makes it impossible to import `astra` from the repo root by accident, so tests always exercise the installed package. A missing wheel entry fails in CI, not in deployment. | flat layout (the Demo Plan's `core/…`) |
| **Lint + format** | **Ruff** (E,W,F,I,N,D,UP,ANN,S,BLE,B,A,C4,DTZ,T10,EM,ISC,ICN,G,INP,PIE,T20,PT,Q,RSE,RET,SLF,SIM,TID,ARG,PTH,ERA,PL,TRY,PERF,FURB,RUF) | One tool replaces flake8+isort+pydocstyle+pyupgrade+bandit+black. `D` and `ANN` enforce the project's own docstring/type-hint requirement mechanically. `BLE` matters specifically: a bare `except` in a safety path hides faults. | black+flake8+isort+bandit (four configs, four failure modes) |
| **Type checking** | **mypy `strict`** + `explicit-override`, `possibly-undefined`, `ignore-without-code`, `redundant-expr`, `truthy-bool`, `disallow_any_unimported` | Retrofitting strict typing costs ~10× starting with it. The contracts are exactly where a silent type error becomes a safety defect. | pyright (excellent, but mypy's plugin/CI story is more standard in safety-adjacent Python); non-strict mypy (theatre) |
| **Testing** | **pytest** + `pytest-cov` + **Hypothesis**; `filterwarnings = ["error"]`; coverage gate **95%** | A warning in a safety codebase is a defect, not noise. Hypothesis is used for the numeric primitives where hand-written examples systematically miss edge cases (unit round-trips, matrix symmetry, Cholesky). | unittest (verbose); no property tests (misses the class of bug this domain has) |
| **Architecture enforcement** | **import-linter** contracts in `.importlinter` | Turns SI-1/SI-2/SI-5/SI-10 into build failures. Directly answers the Demo Plan's "verify with a code-level check, not a comment". | Review-only (does not scale, does not survive a deadline) |
| **Hot-path data model** | **frozen + `slots=True` dataclasses** | Validate once at construction, then trust. `slots` removes per-instance `__dict__` — measurable at 20 Hz with dozens of records per tick. Immutability means a downstream layer cannot mutate a record another layer already consumed. | pydantic everywhere (validation cost on every hop); plain dicts (no invariants, no types) |
| **Boundary data model** | **pydantic v2** | Config files and calibration profiles are parsed once, from untrusted text, and must fail loudly with good messages. Rust core makes it fast enough. | hand-rolled parsing (more code, worse errors) |
| **Units** | SI internally; `NewType` aliases; conversion only at boundaries | Static unit safety at literally zero runtime cost. The documents mix m/s², km/h, degrees and radians freely — this is a Mars-Climate-Orbiter-shaped risk. | `pint` (50–100× arithmetic cost on a hard real-time path); naming conventions (not machine-checked) |
| **Error model** | Typed exception hierarchy carrying a `SafetyDisposition` (`FAIL_FAST` / `FAIL_CLOSED` / `FAIL_OPERATIONAL`) | An exception in a safety path is a statement about what the system may now do, not just a bug report. Mirrors the FMEA's "crossbar defaults to VETO on missed heartbeat". | `Result`/`Either` (no language support; unwrap noise); untyped exceptions (no policy) |
| **Time** | Injected `Clock` protocol; integer-nanosecond `Instant` carrying its `Timeline` | Wall clock is non-monotonic (NTP, leap smear, VM migration) — a negative staleness reads as "perfectly fresh". Replay and CARLA synchronous mode both need a substitutable timeline. | `time.time()` (three separate defects) |
| **Covariance** | Packed lower-triangular `SymmetricMatrix`, pure-Python Cholesky | Asymmetry becomes unrepresentable rather than checkable. No NumPy in the kernel keeps the vocabulary importable by offline tools. 5×5 Cholesky ≈ 40 flops. | NumPy arrays in records (mutable, unhashable → "frozen" in name only) |
| **Identifiers** | Exactly **one** random ID (`RunId`); everything else derived | Replay must produce byte-comparable event streams; `uuid4()` per event makes a diff meaningless. | UUID per event (breaks replay diffing) |
| **Licence** | **Proprietary, all rights reserved**, private repo | Patent filing pending; the Demo Plan gates external demos on filing status. Public disclosure can prejudice patentability. Relicensing open later is always possible; the reverse is not. *(Confirm with whoever handles the filing — this is not legal advice.)* | Apache-2.0 / MIT (public disclosure + patent grant, premature) |

---

## 9. Current build status — file by file

Repository root: `astra/`. Quality gate status: **`ruff format` ✓ · `ruff check` ✓ · `mypy --strict` ✓** for everything marked ✅.

### ✅ Complete and verified

| File | Purpose |
|---|---|
| `pyproject.toml` | Single source of truth for build, deps (PEP 621 + PEP 735 groups), ruff, mypy, pytest, coverage. Heavily commented with the *why* of each setting. |
| `LICENSE` | Proprietary, all-rights-reserved, with explicit **patent notice** and **safety notice** (not certified; must not be deployed). |
| `NOTICE` | Origin, confidentiality, patent-filing gate, third-party inventory placeholder. |
| `README.md` | What ASTRA is, ASCII pipeline, status table, quick start, layout, doc index, **honesty boundaries** carried verbatim from Demo Plan §8. |
| `src/astra/__init__.py` | Package map + the **no-facade-re-export import convention** + phase status. |
| `src/astra/py.typed` | PEP 561 marker — consumers get the type information. |
| `src/astra/kernel/units.py` | SI policy. `NewType` aliases (`Metres`, `MetresPerSecond`, `Radians`, `Probability`, …), non-SI boundary types (`KilometresPerHour`, `Degrees`, `Milliseconds`), `STANDARD_GRAVITY`, six named boundary conversions. |
| `src/astra/kernel/enums.py` | Canonical vocabulary: `LayerId` (with `.ordinal`, `.execution_domain`), `ExecutionDomain`, `Verdict` (**with fail-closed `merge()`**), `GateId`, `FailSafeState` (`.severity_rank`), `ContextClass`, `SensorModality`, `StreamHealth`, `TimingDomain`, `ArbitrationOutcome`, `FeedbackLoop`, `EventSeverity`. All `StrEnum` for free JSON round-tripping. |
| `src/astra/kernel/constants.py` | Architectural constants **only**, with the constant-vs-config test spelled out. Cardinalities (9 layers, 3 gates, 4 loops, 5 modalities), **ordered** state-vector layouts (`FAST_STATE_FIELDS`, `SLOW_STATE_FIELDS`, `RCS_FIELDS`), schema versions. |
| `src/astra/kernel/errors.py` | `SafetyDisposition` + `AstraError` base with `code`/`disposition`/`severity`/`to_audit_fields()`. Hierarchy: `ConfigurationError`→`SchemaVersionError`; `ContractViolationError`→`RangeViolationError`/`NonFiniteValueError`/`DimensionMismatchError`; `SafetyPathError`→`TimingBudgetExceededError`; `InvariantViolationError`; `AdapterError`. |
| `src/astra/kernel/identifiers.py` | `RunId` (only random ID), `TickId` (ordered, `.next()`), `ProfileId` (`name@vN`, immutable versioning per NFR7), `ComponentId` (**instance discriminator for shadow execution**), `EventId` (deterministic `run:tick:seq`). |
| `src/astra/kernel/time.py` | `Timeline` enum, `Instant` (integer ns + timeline; cross-timeline arithmetic raises), `Clock` protocol, `SystemClock`, `ManualClock` (replay/test), `staleness()`, `is_stale()` (FR1's 50 ms rule). |
| `src/astra/kernel/validation.py` | Boundary guards, never `assert` (removed by `-O`): `require_finite` (NaN is fail-*open* — the reason this exists), `require_range`, `require_probability`, `require_non_negative`, `require_positive`, `require_dimension`, `require_non_decreasing` (**SI-9 quantile monotonicity**). |
| `src/astra/kernel/matrix.py` | `SymmetricMatrix` — packed lower triangle, `from_rows` (tolerant symmetry check), `from_diagonal`, `at`, `diagonal`, `variance_of` (the ICP σ(x) accessor), `to_rows` (NumPy seam), `has_admissible_diagonal` (cheap O(n) hot-path check), `cholesky_factor`, `is_positive_definite` (and *why* PD not PSD: a singular covariance means filter collapse, which would drive σ(x)→0 and unbound the ICP gate). |

### 🟡 Written, not yet verified

| File | Purpose |
|---|---|
| `src/astra/contracts/sensing.py` | `SensorSample[PayloadT]` (PEP 695 generic — metadata is architectural, payload is domain-specific), `FusedSensorFrame[PayloadT]` with tuple storage for true immutability, `health()`, `degraded_modalities()`, `build()`. |
| `src/astra/contracts/estimation.py` | `FastStateEstimate` (named unit-typed accessors `speed`, `heading`, `lateral_acceleration`; `variance_of(field)` resolved from the canonical field order so reordering cannot silently repoint σ(x)), `SlowStateEstimate`, `InnovationRecord`. |

### ⬜ Not started — remaining Phase 1 work

See §10.

---

## 10. Remaining Phase 1 work, in execution order

Each item lists its acceptance criteria. Nothing is "done" until `make check` passes.

### 10.1 Contracts (finish the data model)

| File | Contents | Acceptance |
|---|---|---|
| `contracts/actuation.py` | `ActuationSpace` (channel names + units + bounds — **this is how NFR5 domain-independence is achieved**; the vehicle's throttle/brake/steer space is *configured*, not hardcoded), `ControlCommand` (vector in that space), `CommandOrigin` enum (`PROPOSED`/`FALLBACK_PID`/`SPEED_CAPPED`/`EXPLORATION_BOUNDED`), `ProposedCommand` (L4 output), `PredictedCommand` (L5 `π̂_{t+1}`), `IssuedCommand` (L9 output, records issuer → SI-7) | Bounds validated at construction; issuing component must be L9 |
| `contracts/assurance.py` | `TrustAssessment` (TI, context class, class-conditional quantile, coverage target, calibration sample count), `GateVerdict` (gate, verdict, reason code, evidence map, evaluation duration), `SafetyVerdict` (tuple of gate verdicts + aggregate via `Verdict.merge` + `vetoing_gates`; **must have no TI field → SI-4**), `FailSafeSnapshot` (state, OOD counter, speed cap, lane-change permission, human-intervention request) | Test: adding a PASS to a set containing a shield VETO cannot change the aggregate |
| `contracts/governance.py` | `RuntimeContextSignature` (5-dim, each component a `Probability`, named accessors, `as_vector()`), `CalibrationProfile` (profile id, context class, certified centroid + covariance, `validation_fraction`, field history, max speed, quantile table, coverage level, checksum, certified/expiry, platform), `ArbitrationDecision` (outcome, active/candidate profile, trust score, CDI) | Profile rejects non-monotonic quantile table (SI-9); admissibility helper enforces `T(c) ≥ τ AND val(c) == 1` as a **hard** gate |
| `contracts/audit.py` | `AuditEvent` (event id, severity, kind, payload), `DecisionRecord` (**the explainability unit** — ties tick → frame health → state → TI → proposal → each gate verdict → FSM → arbitration → issued command → config hash), `ExecutionOutcome` (applied command + measured outcome + which loops it feeds) | `DecisionRecord` round-trips to JSON and back byte-identically |

### 10.2 Ports

| File | Contents |
|---|---|
| `ports/pipeline.py` | `Protocol` per layer: `SensorSource`, `StateEstimator`, `TrustEstimator`, `CommandProposer`, `DynamicsPredictor`, `StatisticalGate`, `PhysicalAdmissibilityChecker`, `DeterministicShield`, `SafetyStateMachine`, `CalibrationArbiter` |
| `ports/infrastructure.py` | `EventSink`, `ProfileRepository`, `ActuationSink`, `FeedbackBus`, plus a re-export note for `Clock` |

*Acceptance:* every protocol is `@runtime_checkable` where it is cheap to be; a five-line fake in
`tests/` satisfies each without inheritance; no port signature mentions a non-SI unit type.

### 10.3 Invariants

| File | Contents |
|---|---|
| `invariants/catalogue.py` | `SeparationInvariant` record (id, statement, rationale, consequence, enforcement) and the frozen catalogue SI-1…SI-10; runtime guard helpers for SI-3 and SI-7 |
| `.importlinter` | Contracts: layered `kernel < contracts < ports < {config, observability, invariants} < bootstrap`; forbidden `astra.*` → `carla`; forbidden Core-A modules → Core-B modules (activated in Phase 4) |

### 10.4 Configuration

| File | Contents |
|---|---|
| `config/schema.py` | pydantic-settings models: `AstraSettings` with `schema_version`, `environment`, and nested `SensingSettings` (staleness budget), `EstimationSettings` (fast/slow rates, γ), `TrustSettings` (ε, coverage, ensemble size), `GateSettings` (ε, MMD window), `ShieldSettings` (v_legal, friction margin), `FailSafeSettings` (θ1/θ2/θ3, speed caps), `ArbitrationSettings` (τ, δ_CDI, exploration caps, ±15°), `ObservabilitySettings` (log dir, level, buffer). **No default for any safety threshold** — a missing value must fail at startup rather than silently use an invented number (A-4). |
| `config/loader.py` | Layered resolution: packaged defaults → `config/environments/<env>.toml` → `ASTRA_*` env vars. Frozen after load. Emits a **configuration hash** that goes into every `DecisionRecord`. |
| `config/astra.defaults.toml` | Only non-safety-critical defaults (log levels, paths, rates). |
| `config/environments/{development,simulation,certification}.toml` | Environment operating points. `certification.toml` is the one a safety engineer edits. |

### 10.5 Observability

| File | Contents |
|---|---|
| `observability/context.py` | `contextvars`-based correlation: current `RunId`, `TickId`, `ComponentId`; a `tick_scope()` context manager |
| `observability/logging.py` | Structured logging setup; `QueueHandler` + background writer so **the hot path never blocks on I/O (SI-8)**; JSON formatter; no f-strings in log calls (`G` lint rule) |
| `observability/audit.py` | `JsonlAuditSink` implementing `EventSink`: append-only, one file per run, schema-versioned, `EventId`-ordered, fsync policy configurable. This file *is* the certification evidence artefact. |

### 10.6 Bootstrap

| File | Contents |
|---|---|
| `bootstrap/composition.py` | The composition root. Loads+freezes config, builds clock, opens audit sink, verifies the invariant catalogue, returns an immutable `AstraRuntime` handle. **Assembles only what exists** — no fake layer implementations. |
| `bootstrap/cli.py` | `astra doctor` (environment + config + invariant report), `astra config show`, `astra invariants list`, `astra version`. The only place `print()` is allowed. |
| `src/astra/__main__.py` | `python -m astra` entry point |

### 10.7 Tests

```
tests/conftest.py                     shared fixtures: ManualClock, frozen settings, tmp audit sink
tests/unit/test_units.py              conversions, boundary types
tests/unit/test_enums.py              Verdict.merge fail-closed incl. empty set; layer↔domain map
tests/unit/test_constants.py          cardinalities agree with the enums (fitness)
tests/unit/test_errors.py             disposition per class; to_audit_fields is JSON-safe
tests/unit/test_identifiers.py        validation, ProfileId.parse round-trip, EventId determinism
tests/unit/test_time.py               staleness, cross-timeline raises, ManualClock cannot rewind
tests/unit/test_validation.py         every guard, incl. NaN-defeats-comparison case
tests/unit/test_matrix.py             packing, symmetry tolerance, Cholesky vs known PD/non-PD
tests/unit/test_contracts_*.py        one per contracts module
tests/unit/test_config.py             layering, missing-threshold fails, schema version mismatch
tests/unit/test_audit.py              append-only, ordering, JSON round-trip
tests/unit/test_bootstrap.py          doctor output, invariant verification
tests/property/test_units_props.py    round-trip identities under Hypothesis
tests/property/test_matrix_props.py   symmetry, PD⇔Cholesky, from_rows/to_rows round-trip
tests/architecture/test_layering.py   runs import-linter; asserts kernel has no astra imports
tests/architecture/test_invariants.py SI-3 and SI-7 structural assertions
```

### 10.8 Tooling & CI

`.pre-commit-config.yaml` · `.editorconfig` · `.gitignore` · `.env.example` · `Makefile`
(`make check` = format-check + lint + mypy + lint-imports + pytest) ·
`.github/workflows/ci.yml` (matrix 3.12/3.13; uv cache; the same `make check`) · `CHANGELOG.md`

### 10.9 Documentation

`docs/ARCHITECTURE.md` · `docs/ROADMAP.md` · `docs/CONVENTIONS.md` · `docs/INSTALL.md` ·
`docs/DEVELOPMENT.md` · `docs/ASSUMPTIONS.md` · `docs/DOCUMENT_RECONCILIATION.md` ·
`docs/SEPARATION_INVARIANTS.md` · `docs/PHASE1_COMPLETION_REPORT.md` · `docs/adr/0001…0014`

---

## 11. Full roadmap: Phase 1 → working prototype

### 11.1 Mapping the Demo Plan's module layout to this repository

Nothing in the Demo Plan is discarded — only re-homed.

| Demo Plan §9 | This repository |
|---|---|
| `core/sensor_bus.py` | `src/astra/layers/l1_sensing/` + `src/astra/adapters/carla/sensors.py` |
| `core/ukf_dual_rate.py` | `src/astra/layers/l2_estimation/` |
| `core/trust_module.py` | `src/astra/layers/l3_trust/` (EnbPI + Mondrian) |
| `core/core_a_agent.py` | `src/astra/layers/l4_proposer/` |
| `core/pinn_twin.py` | `src/astra/layers/l5_twin/` |
| `core/icp_gate.py` | `src/astra/layers/l6_statistical_gate/` |
| `core/hard_safety_shield.py` | `src/astra/layers/l7_shield/` (a = deterministic, b = physical) |
| `core/failsafe_fsm.py` | `src/astra/layers/l8_failsafe/` |
| `core/rcm.py` | `src/astra/layers/l9_rcm/` |
| `feedback/fb*.py` | `src/astra/feedback/` |
| `comms/ipc_queues.py` | `src/astra/runtime/channels.py` (one-way enforcement + SI-5 guard) |
| `calibration_kb/profiles/` | `calibration/profiles/` (repo root) + `ProfileRepository` port |
| `scenarios/` | `scenarios/` (repo root) |
| `replay/` | `src/astra/replay/` |
| `dashboard/` | `apps/dashboard/` (backend + frontend) |
| `training/` | `training/` (repo root, offline) |
| `logs/event_log.jsonl` | `var/runs/<run-id>/events.jsonl` via `JsonlAuditSink` |

### 11.2 Phase plan

Each phase ends with a **Phase Engineering Completion Report**. No phase starts before the previous
one's `make check` is green.

---

**PHASE 1 — Foundation** *(current; Demo Plan: pre-Week 1)*

Scope: everything in §9 and §10. No layer logic.
**Exit criteria:** `make check` green · coverage ≥ 95% · `astra doctor` reports a healthy runtime ·
SI-1…SI-10 catalogued with at least static enforcement in place for SI-1, SI-2, SI-5, SI-10 ·
all 14 ADRs written.

---

**PHASE 2 — Sensing, State Estimation & the Replay Spine** *(Demo Plan Week 1a)*

- `l1_sensing`: fusion, per-modality staleness (FR1), health classification.
- `l2_estimation`: `DualRateUKF` over two FilterPy UKFs — `update_fast(z)`, `update_slow()`,
  `get_state_and_covariance()`, `get_innovation()`. Julier–Uhlmann scaled unscented transform.
- Innovation monitor: Mahalanobis spike → sensor-fault flag; rolling distribution retained for L6.
- `adapters/carla`: sensor ingestion, synchronous-mode clock (`Timeline.SIMULATED`).
- **`replay/`: `StateRecorder` + `ReplayHarness`** — built *now*, not in Phase 7, per the Demo Plan.
- **Resolve R-6** (CARLA ↔ interpreter). This is the gating decision of the phase.

**Exit criteria:** UKF validated **in isolation against CARLA ground truth** before anything
downstream is wired — the Demo Plan is explicit about this. Recorded run replays to a
byte-identical event stream. Fast-filter latency < 1 ms measured.

*Risk:* highest-effort layer after L9; correctness here dominates everything downstream.

---

**PHASE 3 — Deterministic Safety Spine** *(Demo Plan Week 1b)*

- `l7_shield` (L7a): three O(1) bounds from UKF state only — `a_lat ≤ μg`, `d_stop ≤ d_avail`,
  `v ≤ v_legal`. **No dependency on L5 or L6.**
- `l8_failsafe`: four-state FSM, OOD counter with bidirectional recovery, speed caps.
- `runtime/channels.py`: one-way Core-A→Core-B queue with the SI-5 runtime guard.

**Exit criteria:** a unit test proving **no PASS from any component can suppress a shield VETO**
(SI-3, and the Demo Plan asks for exactly this test) · FSM walks NOMINAL→DEGRADED→LIMP→HALT and
back without restart · both layers' latency measured.

*Why this early:* it is the lowest-effort, highest-assurance part of the safety argument, and it
gives every later phase a working veto path to test against.

---

**PHASE 4 — Proposer & Digital Twin (minimal)** *(Demo Plan Week 1c)*

- `l4_proposer`: SB3 PPO + `LagrangianConstraintWrapper` (PID dual update). Constraints: lane
  deviation ≤ d_max, |a_long| ≤ a_max, collision rate = 0. **Veto rate excluded (SI-6).**
- `l5_twin`: small PyTorch PINN with the physics loss; offline training script.
- `training/`: offline corpora — highway + urban × clear + adverse, ≥ 500 calibration samples per
  context.

**Exit criteria:** **Checkpoint 1 from the Demo Plan** — one real scenario runs end-to-end with no
feedback loops, proving independent gates + deterministic veto + FSM.
A code-level check confirms Core-A has no import, no shared memory and no queue back from Core-B.

*Does not compress:* PPO wall-clock training time is GPU-bound.

---

**PHASE 5 — Statistical Assurance** *(Demo Plan Week 2a)*

- `l3_trust`: hand-rolled **EnbPI** (MAPIE lacks robust online time-series EnbPI) + Mondrian
  context bucketing over the four `ContextClass` values. `TI = 1 − F̂_k(α_{t+1})`.
- `l6_statistical_gate`: `α = |π_prop − π̂|/σ(x)`, `σ(x) = √P_f[control dim]`; class-conditional
  quantiles; CQR for heteroscedasticity; **MMD covariate-shift detector on the rolling innovation
  distribution** → dynamic ε tightening.

**Exit criteria:** EnbPI unit-tested **in isolation on synthetic time series** before integration
(Demo Plan explicitly recommends this) · per-class coverage ≥ 94.5% over 1 000 steps on synthetic
data · SI-4 architecture test green (TI absent from `SafetyVerdict`).

*Primary implementation risk in the whole project after L9: hand-rolling EnbPI correctly.*

---

**PHASE 6 — Runtime Calibration Management** *(Demo Plan Week 2b)*

- `l9_rcm`: RCS builder (reliability-weighted, so a degraded sensor lowers its own contribution);
  cold-path Mahalanobis KB search; mandatory gates (expired signature, platform mismatch, critical
  failure history); `T(c)` scoring; admissibility `T(c) ≥ τ AND val(c) = 1` as a **hard** gate.
- Shadow execution + **CDI** → commit or rollback.
- **Core-B independent table validation** (signed checksum + quantile monotonicity/range) — SI-9.
- **Bounded safe exploration**: 50% of nearest certified max speed, no lane changes, steering
  ±15°, evidence logged, four exit conditions.
- `calibration/profiles/`: the four seed profiles. **No tunnel profile** — that omission is
  deliberate and is what makes Phase 3.5 of the validation plan meaningful.

**Exit criteria:** **Checkpoint 2 from the Demo Plan** — the tunnel scenario works: no admissible
profile, exploration engages, vehicle keeps moving. Cold path proven never to block a tick (SI-8).

*Highest architectural intricacy of any single component; budget the most debugging time here.*

---

**PHASE 7 — Closing the Loops** *(Demo Plan Week 3 — protected slack, does not compress)*

Bring up **one at a time**, confirming stability before adding the next:

1. **FB1** — applied (not proposed) command re-anchors the UKF. Everything else depends on it.
2. **FB2** — 50-sample buffer → EWC update of the PINN **output layer only**, Fisher-anchored on
   200 historical samples. **Explicit catastrophic-forgetting test: highway accuracy must not
   degrade after adapting to rain.**
3. **FB3** — executed outcomes → online Mondrian requantilisation.
4. **FB4** — executed command → simulator sync. Prototype-only; brought up last, lowest risk.

**Exit criteria:** stable closed loop over a long run; no oscillation, drift or feedback
overcorrection; every loop demonstrably improves its target metric and degrades it when removed.

*The Demo Plan's warning applies: bugs here are usually not code bugs but emergent dynamics. The
replay harness from Phase 2 is the primary debugging instrument.*

---

**PHASE 8 — Observability, Demo Harness & Explainability Surface** *(Demo Plan Week 4)*

- `apps/dashboard/backend`: FastAPI + WebSocket streaming live layer state.
- `apps/dashboard/frontend`: React + Recharts rendering the pipeline diagram itself — TI gauge;
  **L6 and L7 shown as separately lit paths** (this is the visual proof of gate independence);
  P_f visibly widening/narrowing the acceptance band; FSM as a lit state diagram; RCM's KB search /
  shadow execution / "SAFE EXPLORATION ENGAGED" banner; event ticker with independent-cause
  attribution.
- **Comparison harness**: two synchronised instances — full ASTRA vs. baseline (raw Core-A) —
  against the identical injected fault. Highest-impact visual in the demo.
- **Interactive fault injection** — the audience presses the button. Deliberate credibility move.
- Explainability surface = replay of `DecisionRecord` provenance (per R-7).

**Exit criteria:** every dashboard number traceable to a live record; nothing scripted; pre-recorded
fallback run captured.

---

**PHASE 9 — Validation & Evidence**

- Seven-phase continuous drive through CARLA Town04: highway → urban → rain/night → **tunnel
  (3.5)** → sensor fault → adversarial FGSM → recovery. Vehicle never stops.
- **Ablation study**: disable FB1/FB2/FB3 individually; run ICP-only without the Shield; disable
  safe exploration and force HALT.
- Metrics against Table VII targets — reported as measurements, with the software/hardware latency
  distinction stated explicitly every time.
- Evidence pack: audit logs, replayable runs, dependency licence inventory, assumption closure.

**Exit criteria:** all claims in the papers are either demonstrated by code that ran, or explicitly
listed as not demonstrated. No overclaiming.

### 11.3 Gating items outside engineering

From Demo Plan §10 — these block the external demo regardless of code readiness:

- [ ] **Provisional patent filing status** — gate before any external/company-facing demo
- [ ] NDA in place for demo attendees
- [ ] Team split confirmed (single builder vs. parallel L2/L7/L8 · L3/L4 · L5/L6 tracks)
- [ ] Baseline system for the side-by-side chosen (raw Core-A vs. lockstep emulation)
- [ ] Final three showcase scenarios confirmed
- [ ] Backup recording scheduled ahead of the first live demo

---

## 12. Assumptions register

| ID | Assumption | Impact if wrong | Verify by |
|---|---|---|---|
| **A-1** | Domain independence is achieved by ports + a configured `ActuationSpace`; all vehicle specifics live in adapters and configuration. | NFR5 unmet; non-automotive claims in the paper unsupported. | Phase 6: add a non-automotive profile without touching core. |
| **A-2** | A 10 ms end-to-end budget at 20 Hz (50 ms period) is achievable in CPython with non-blocking audit I/O. | Architecture holds; only the numbers move. Report honestly. | Phase 2 measurement. |
| **A-3** | Append-only JSONL, one file per run, is adequate as certification evidence at prototype stage. | May need a database or signed log for real certification. | Phase 9 evidence review. |
| **A-4** | θ1/θ2/θ3, ε, γ, τ, δ_CDI have **no defensible defaults** and must be required configuration. | If defaults were shipped, a run could silently use invented safety thresholds. | Phase 1 test: missing threshold ⇒ startup failure. |
| **A-5** | Determinism (single random `RunId`) is sufficient for byte-comparable replay. | Replay diffing is weakened; PPO/PINN seeding must also be controlled. | Phase 2 replay test; extend to RNG seeding in Phase 4. |
| **A-6** | Python 3.12 is supported by torch / SB3 / filterpy at Phase 4. | Would force 3.11. Core is unaffected. | Phase 4 dependency spike — **do this early**. |
| **A-7** | Repository stays private and proprietary until the filing is confirmed. | Potential loss of patent rights in some jurisdictions. | Confirm with the filing agent. |
| **A-8** | CARLA/interpreter incompatibility (R-6) is resolvable by one of three routes without changing the core. | Could force a sidecar process and an IPC hop, adding latency. | Phase 2 spike — **do this first**. |
| **A-9** | "MPC candidate scoring" in L6 can be treated as a sub-stage behind the `StatisticalGate` port. | May need its own port and layer number. | Clarify with Dr. Chaitra R. |
| **A-10** | Explainability = decision provenance, not model-internal attribution (R-7). | If stakeholders expect SHAP/LIME, a new layer is needed. | Confirm with the project owner. |

---

## 13. Risk register

| ID | Risk | Severity | Mitigation |
|---|---|---|---|
| **RK-1** | CARLA 0.9.14 vs Python 3.10+ incompatibility (R-6) | **High** | Simulator behind a port; resolve in Phase 2 before any adapter code is written |
| **RK-2** | Hand-rolled EnbPI is subtly wrong; coverage guarantee silently invalid | **High** | Build and unit-test in isolation on synthetic series (Demo Plan's own recommendation); verify empirical coverage per class before integration |
| **RK-3** | Closed-loop emergent dynamics (oscillation, drift, overcorrection) | **High** | Replay harness built in Phase 2, not Phase 7; loops brought up one at a time; Week 3 slack protected |
| **RK-4** | L9 RCM complexity — the most intricate single component | Medium | Build after the safety spine exists so it can be tested against a working veto path |
| **RK-5** | EWC fails to prevent catastrophic forgetting in practice | Medium | Explicit before/after cross-context accuracy test; Fisher penalty tuning is empirical and does not compress |
| **RK-6** | PPO training wall-clock time | Medium | GPU-bound, not coding-bound; start training corpora early, in parallel with Phase 3 |
| **RK-7** | Patent disclosure through a public repo or an ungated demo | **High** (non-technical) | Private repo, proprietary licence, NDA before demos, filing gate in Demo Plan §10 |
| **RK-8** | Overclaiming in the demo (1.25 µs, "eliminates hallucination", zero-failure) | **High** (credibility) | Honesty boundaries reproduced in `README.md`; every latency claim labelled hardware-analytical or software-measured |
| **RK-9** | Scope creep from the "platform" framing into features no document specifies | Medium | Phase discipline; every new component must trace to a document line or an ADR |

---

## 14. Architecture Decision Records index

To be written into `docs/adr/`. Each follows: Context · Decision · Alternatives considered ·
Consequences · Status.

| ADR | Title |
|---|---|
| 0001 | Adopt the consolidated L1–L9 layer numbering |
| 0002 | Domain-independent platform core with adapters, not a CARLA-coupled prototype |
| 0003 | Python 3.12 floor; the simulator is isolated behind a port |
| 0004 | uv + hatchling + PEP 621/735 for build and dependency management |
| 0005 | Ruff + mypy strict + import-linter as a single non-negotiable quality gate |
| 0006 | Typed exception hierarchy carrying safety dispositions; no `Result` type |
| 0007 | SI units internally via `NewType`; conversion only at boundaries |
| 0008 | Frozen slotted dataclasses on the hot path; pydantic only at boundaries |
| 0009 | Deterministic identifiers; exactly one random `RunId` |
| 0010 | Injected `Clock`; no component reads time directly |
| 0011 | Packed lower-triangular `SymmetricMatrix`; no NumPy in the kernel |
| 0012 | Separation invariants as executable, machine-checked contracts |
| 0013 | Append-only JSONL audit log as the certification evidence artefact |
| 0014 | Proprietary licence while the patent filing is pending |

---

## 15. Conventions that must not drift

- **Absolute imports only.** No relative imports (`TID` rule). No package facade re-exports —
  import from the defining module.
- **Docstring on every public symbol**, Google convention, `Args`/`Returns`/`Raises`.
- **Full type annotations.** `mypy --strict` is a gate, not advice.
- **No magic numbers.** A number is either an architectural constant (`kernel/constants.py`) or
  configuration (`config/`). The test: *would a software engineer or a safety engineer review this
  change?*
- **SI units internally**, always. Non-SI types exist only so that non-SI values are visible in a
  signature; they must never appear in a `ports/` signature.
- **Never `assert` for a safety check** — `python -O` deletes it.
- **Never a bare `except`** (`BLE`). Catch `AstraError` or a specific subclass.
- **Never `time.time()`** — use the injected `Clock`.
- **Never `print()`** outside `bootstrap/cli.py`.
- **No f-strings in logging calls** (`G`) — the format cost is paid even when the record is
  filtered out.
- **Fail closed.** Absence of a verdict is a VETO. An empty verdict set is a VETO.
- **Every claim traceable.** A number in a report, a dashboard or a paper must come from a record
  that a run produced.

---

## Appendix A — quick commands

```bash
uv sync --all-groups            # install everything
uv run astra doctor             # environment + config + invariant report
uv run astra config show        # effective resolved configuration
uv run astra invariants list    # SI-1 … SI-10 with enforcement status

make check                      # the full gate, exactly as CI runs it
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run lint-imports
uv run pytest --cov=astra
```

## Appendix B — glossary

**ASIL** Automotive Safety Integrity Level · **BIST** Built-In Self-Test · **CBF** Control Barrier
Function · **CDI** Calibration Divergence Index · **CMDP** Constrained Markov Decision Process ·
**CQR** Conformalized Quantile Regression · **ECC** Error Correction Code · **EnbPI** Ensemble
Batch Prediction Intervals · **EWC** Elastic Weight Consolidation · **FGSM** Fast Gradient Sign
Method · **FMEA** Failure Mode and Effects Analysis · **ICP** Inductive Conformal Prediction ·
**KB** Calibration Knowledge Base · **MMD** Maximum Mean Discrepancy · **OOD** Out-of-Distribution ·
**PINN** Physics-Informed Neural Network · **PPO** Proximal Policy Optimisation · **RCM** Runtime
Calibration Management · **RCS** Runtime Context Signature · **SECDED** Single Error Correction,
Double Error Detection · **SI-n** Separation Invariant n · **SOTIF** Safety Of The Intended
Functionality · **TI** Trust Index · **UKF** Unscented Kalman Filter · **WCET** Worst-Case
Execution Time

---

*End of handoff. The source code referenced in §9 travels with this document as `astra-phase1-wip.zip`.*
