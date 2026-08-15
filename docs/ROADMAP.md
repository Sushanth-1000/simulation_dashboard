# ASTRA — Roadmap

What each phase builds, on what, and what it is not allowed to skip.

> ### Phase markers are stale, 15 August 2026
>
> This document still reads as though Phase 4 were ahead. Phases 1–4 are built,
> Phase 5's statistical gate and Phase 6's arbitration both run, and the work
> since has been closing defects the running system produced rather than adding
> layers. **The phase structure is kept because the *ordering argument* in it is
> still the reason things were built in the order they were** — not as a report
> of where the project is.
>
> For where it actually is, read [`CREDIBILITY_MATRIX.md`](CREDIBILITY_MATRIX.md)
> — one row per claim, with what each does and does not license. For why each
> call went the way it did, [`DECISION_LOG.md`](DECISION_LOG.md).
>
> The one section still ahead of the code is **Phase 9's CARLA drives**, and it
> is the section that matters most: every `[M-syn]` row in the matrix becomes
> `[M-ext]` there or not at all.

Nine phases run from the foundation that exists today to a validated prototype with an evidence
pack. Each phase ends with a **Phase Engineering Completion Report**. No phase starts before the
previous one's `make check` is green — not as a matter of taste, but because every phase's exit
criteria are stated as properties the build can check, and a phase that starts on a red build is
a phase whose own results cannot be attributed.

Two conventions used throughout:

- **Exit criteria** are the conditions under which the phase is finished. They are deliberately
  written as things that can be observed, not as things that can be asserted.
- **Does not compress** names the part of the phase that cannot be shortened by working harder.
  Recording it up front is what stops a deadline being absorbed by the one activity that will
  not absorb it.

Related: [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`SEPARATION_INVARIANTS.md`](SEPARATION_INVARIANTS.md) ·
[`DOCUMENT_RECONCILIATION.md`](DOCUMENT_RECONCILIATION.md) ·
[`ENGINEERING_HANDOFF.md`](ENGINEERING_HANDOFF.md)

---

## Where the Prototype & Demo Plan's modules live in this repository

The Demo Plan proposed a flat prototype layout (`core/`, `feedback/`, `comms/`, …) with no
packaging, tests or configuration. NFR5 requires domain independence, which a flat layout with a
CARLA-coupled core cannot deliver. The resolution (finding R-11) was to keep every proposed
module and re-home it: **nothing is discarded, only the packaging is upgraded.**

| Demo Plan §9 | This repository | Phase |
|---|---|---|
| `core/sensor_bus.py` | `src/astra/layers/l1_sensing/` + `src/astra/adapters/carla/sensors.py` | 2 |
| `core/ukf_dual_rate.py` | `src/astra/layers/l2_estimation/` | 2 |
| `core/trust_module.py` | `src/astra/layers/l3_trust/` (EnbPI + Mondrian) | 5 |
| `core/core_a_agent.py` | `src/astra/layers/l4_proposer/` | 4 |
| `core/pinn_twin.py` | `src/astra/layers/l5_twin/` | 4 |
| `core/icp_gate.py` | `src/astra/layers/l6_statistical_gate/` | 5 |
| `core/hard_safety_shield.py` | `src/astra/layers/l7_shield/` (a = deterministic, b = physical) | 3 / 4 |
| `core/failsafe_fsm.py` | `src/astra/layers/l8_failsafe/` | 3 |
| `core/rcm.py` | `src/astra/layers/l9_rcm/` | 6 |
| `feedback/fb*.py` | `src/astra/feedback/` | 7 |
| `comms/ipc_queues.py` | `src/astra/runtime/channels.py` (one-way enforcement + SI-5 guard) | 3 |
| `calibration_kb/profiles/` | `calibration/profiles/` (repo root) + `ProfileRepository` port | 6 |
| `scenarios/` | `scenarios/` (repo root) | 9 |
| `replay/` | `src/astra/replay/` | 2 |
| `dashboard/` | `apps/dashboard/` (backend + frontend) | 8 |
| `training/` | `training/` (repo root, offline) | 4 |
| `logs/event_log.jsonl` | `var/runs/<run-id>/events.jsonl` via `JsonlAuditSink` | **done** |

The last row is the only one already delivered, and it is delivered under a different path on
purpose: one directory per run makes a run the unit of archival and replay, which a single
shared log file cannot be.

---

## Phase 1 — Foundation · **COMPLETE**

*Demo Plan: pre-Week 1.*

### Delivered

Everything the pipeline depends on, and no layer logic whatsoever.

| Package | Contents |
|---|---|
| `src/astra/kernel/` | `units` (SI `NewType` policy + six boundary conversions), `enums` (twelve enumerations, including `Verdict` with its fail-closed `merge`), `constants` (cardinalities, state-vector layouts, schema versions), `errors` (typed hierarchy carrying `SafetyDisposition`), `identifiers` (one random ID; everything else derived), `time` (`Timeline`, `Instant`, `Clock`, `SystemClock`, `ManualClock`, staleness), `validation` (guards that are never `assert`), `matrix` (`SymmetricMatrix`, packed lower triangle, pure-Python Cholesky) |
| `src/astra/contracts/` | `sensing`, `estimation`, `actuation`, `assurance`, `governance`, `audit` — frozen slotted dataclasses that validate once at construction |
| `src/astra/ports/` | `pipeline` — ten layer protocols; `infrastructure` — `EventSink`, `ProfileRepository`, `ActuationSink`, `FeedbackBus` |
| `src/astra/invariants/` | `catalogue.py` — SI-1…SI-10 as data with an `EnforcementKind`, plus runtime guards for SI-3 and SI-7 |
| `src/astra/config/` | `schema.py`, `loader.py`, `config/astra.defaults.toml`, `config/environments/{development,simulation,certification}.toml` |
| `src/astra/observability/` | `context.py` (contextvars correlation), `logging.py` (queue-backed structured logging), `audit.py` (`JsonlAuditSink`) |
| `src/astra/bootstrap/` | `composition.py` (the composition root), `cli.py` (`doctor`, `config show`, `invariants list`, `version`) |
| Tooling | `.importlinter`, `Makefile`, `.github/workflows/ci.yml` (3.12 + 3.13 matrix), `.pre-commit-config.yaml`, `.editorconfig`, `.env.example`, `CHANGELOG.md` |
| Tests | `tests/unit/` (22 modules), `tests/property/` (Hypothesis over units and matrices), `tests/architecture/` (layering + the statically enforced invariants) |

**Gate status on this tree:** 1352 tests passing · 99% statement coverage against a 95% floor ·
`ruff format --check`, `ruff check`, `mypy --strict` and `lint-imports` green. These are counts
over the Phase 1 code; they say nothing about pipeline behaviour, because there is no pipeline.

### Exit criteria — status

| Criterion | Status |
|---|---|
| `make check` green | Met |
| Coverage ≥ 95% | Met (99%) |
| `astra doctor` reports a healthy runtime | Met |
| SI-1…SI-10 catalogued, with at least static enforcement for SI-1, SI-2, SI-5, SI-10 | Met, with the scope caveats recorded in [`SEPARATION_INVARIANTS.md`](SEPARATION_INVARIANTS.md) |
| All 14 ADRs written | **Not met.** `docs/adr/` is empty; the decisions are currently carried by module docstrings and [`ARCHITECTURE.md`](ARCHITECTURE.md) |

The ADR gap is the single outstanding Phase 1 item. It is documentation debt, not architectural
debt — every decision the ADRs would record has been made and implemented — but it is recorded
here rather than quietly reclassified, because the exit criteria were written before the work,
not after it.

### Risks carried forward

- The import contracts for SI-1 and SI-5 are necessarily narrower than the invariants they
  enforce, because the modules they will constrain do not exist yet. Widening them is Phase 3/4
  work and is called out per-invariant in [`SEPARATION_INVARIANTS.md`](SEPARATION_INVARIANTS.md).
- SI-6 is review-only until Phase 4.
- Finding **R-6** (CARLA versus the Python 3.12 floor) was unresolved at the close of Phase 1 and
  was resolved by the Phase 2 spike. See [`adr/0015-carla-interpreter-strategy.md`](adr/0015-carla-interpreter-strategy.md).

---

## Phase 2 — Sensing, State Estimation & the Replay Spine

*Demo Plan Week 1a.* Builds on: `contracts/sensing`, `contracts/estimation`, `kernel/matrix`,
`kernel/time`, the `SensorSource` and `StateEstimator` ports.

### Scope

- `l1_sensing`: multi-modality fusion, per-modality staleness against FR1's 50 ms budget, health
  classification into `HEALTHY` / `DEGRADED` / `FAULTED` / `ABSENT`.
- `l2_estimation`: `DualRateUKF` over two FilterPy UKFs — `update_fast(z)`, `update_slow()`,
  `get_state_and_covariance()`, `get_innovation()`. Julier–Uhlmann scaled unscented transform.
- The **innovation monitor**: Mahalanobis spike → sensor-fault flag, with the rolling
  distribution retained for L6's covariate-shift detector.
- `adapters/carla`: sensor ingestion and a synchronous-mode clock on `Timeline.SIMULATED`.
- **`replay/`: `StateRecorder` + `ReplayHarness`** — built *now*, not in Phase 7.
- **Resolve R-6.** Done, and it dissolved rather than needing a workaround: CARLA 0.9.16 publishes
  an official CPython 3.12 wheel, so the incompatibility the finding describes no longer exists.
  See [`adr/0015-carla-interpreter-strategy.md`](adr/0015-carla-interpreter-strategy.md).

### Exit criteria

- The UKF is validated **in isolation against ground truth before anything downstream is
  wired**. The Demo Plan is explicit about this and it is not negotiable: L2 is the sole state
  source and therefore the sole common-cause channel, so a wrong filter makes all three gates
  wrong together.
- A recorded run replays to a byte-identical event stream.
- Fast-filter latency measured (target < 1 ms), and reported as a software measurement.

### Risks

- **RK-1 — closed.** R-6's premise expired: CARLA 0.9.16 (2025-09-16) ships an official `cp312`
  wheel, so no sidecar, no IPC hop and no unofficial binary is required, and the latency budget is
  untouched. **A new constraint replaces it, and it is a real one:** CARLA has no macOS build and
  no macOS wheel, so simulator work needs a Linux x86-64 machine with an NVIDIA GPU. That does not
  block L1, L2 or the replay spine, which are developed and tested against in-process fakes — but
  it does mean the adapter cannot be exercised on an Apple-Silicon development machine at all.
- **Nothing has been run against a real simulator.** The interpreter finding rests on CARLA's
  published wheel metadata, not on an install. A-8 should be treated as evidenced, not closed,
  until `pip install carla==0.9.16` and a client connection have actually succeeded on Linux.
- Correctness here dominates everything downstream. This is the highest-effort layer after L9.
- **A-5** — determinism from a single random `RunId` — is first tested here, and must be
  extended to RNG seeding in Phase 4.

### Does not compress

Filter tuning against ground truth. Process- and measurement-noise covariances are found
empirically, and the search is not shortened by additional engineers.

---

## Phase 3 — Deterministic Safety Spine — **DELIVERED**

*Demo Plan Week 1b.* Builds on: `DeterministicShield` and `SafetyStateMachine` ports,
`ShieldSettings`, `FailSafeSettings`, `Verdict.merge`, `guard_verdict_aggregation`.

### Scope

- `l7_shield` (L7a): three O(1) bounds computed from the UKF state alone — `a_lat ≤ μg`,
  `d_stop ≤ d_avail`, `v ≤ v_legal`. **No dependency on L5 or L6.**
- `l8_failsafe`: the four-state FSM with an OOD counter that increments on VETO and decrements on
  PASS, giving bidirectional recovery without a restart; speed caps per state.
- `runtime/channels.py`: the one-way Core-A → Core-B queue, with the SI-5 runtime guard.

### Exit criteria

- A unit test proving **no PASS from any component can suppress a shield VETO** (SI-3). The
  aggregation half of this already exists in `tests/architecture/test_invariants.py`; this phase
  extends it to a real shield producing a real verdict.
- The FSM walks NOMINAL → DEGRADED → LIMP → HALT and back without a restart.
- Both layers' latency measured.
- The one-way channel exists as a queue with a runtime guard, not as a convention. (The
  *import* contract for SI-5 cannot be activated until Phase 4, because it names
  `astra.layers.l4_proposer` as its source module.)

### Result

All four exit criteria met. See
[`PHASE3_COMPLETION_REPORT.md`](PHASE3_COMPLETION_REPORT.md).

- The unsuppressable veto holds against a *real* shield verdict, not a hand-built one: two PASSes
  plus a shield VETO aggregates to VETO, in any order, and an empty verdict set is a VETO.
- The FSM walks NOMINAL → DEGRADED → LIMP and back to NOMINAL driven only by verdicts, with no
  restart and no `reset()`. HALT is deliberately **latched** — 200 clean ticks do not leave it.
- Measured, software: **L7a p99 0.004 ms, L8 p99 0.006 ms.** The whole hot path built so far
  (L1 + L2 + L7a + L8) is p99 0.25 ms, about 0.5% of a 50 ms tick.
- The one-way channel is a **capability pair**, not a queue with a convention: Core-A holds a
  `ProposalWriter` whose only methods are `send` and `pending`, so there is no method through
  which a verdict could return. Two runtime guards cover the paths the type system cannot see.

Two import contracts became enforceable and were added, taking the total from 6 to 8:
`si-3-shield-independence` (the shield imports no other gate and no FSM) and
`l8-judges-verdicts-only` (the machine imports no gate, so it cannot weight one gate's veto above
another's).

### Risks

Low, by construction, and that held. The one real risk remains that the shield's bounds are
configured too permissively during bring-up and never revisited — which `certification.toml`
refusing to load is designed to catch at the one moment it matters.

**One limitation is worth stating plainly.** The `d_stop ≤ d_avail` bound compares against a
*certified ODD parameter*, not a perceived distance. The fast state vector carries no
distance-to-obstacle, and SI-1 and SI-2 forbid the shield from re-reading the sensors to find
one. Sourcing `d_avail` from perception would require extending the state vector — a visible
architectural change, recorded as Phase 3 debt rather than quietly approximated.

### Why this early

It is the lowest-effort, highest-assurance part of the safety argument, and it gives every later
phase a working veto path to test against. A statistical gate built before any veto path exists
has nothing to be integrated with.

---

## Phase 4 — Proposer & Digital Twin (minimal)

*Demo Plan Week 1c.* Builds on: `CommandProposer`, `DynamicsPredictor`,
`PhysicalAdmissibilityChecker`, `ProposedCommand`, `PredictedCommand`.

### Scope

- `l4_proposer`: SB3 PPO with a `LagrangianConstraintWrapper` (PID dual update). Constraints:
  lane deviation ≤ d_max, |a_long| ≤ a_max, collision rate = 0. **Veto rate excluded (SI-6).**
- `l5_twin`: a small PyTorch PINN with the physics loss, plus an offline training script.
- `l7_shield` (L7b): the PINN-based physical admissibility checker, tagged `GateId.PHYSICAL`.
  *(The source documents do not assign L7b to a phase explicitly. It is placed here because it
  depends on L5, which lands in this phase, and because this phase's exit criterion speaks of
  independent gates in the plural while L6 does not arrive until Phase 5.)*
- `training/`: offline corpora — highway + urban × clear + adverse, ≥ 500 calibration samples per
  context.

### Exit criteria

- **Checkpoint 1 from the Demo Plan.** One real scenario runs end to end with no feedback loops,
  demonstrating independent gates, a deterministic veto and the FSM.
- A **code-level check** confirms Core-A has no import, no shared memory region and no queue back
  from Core-B. Prose does not satisfy this criterion.
- **SI-6 is upgraded from `REVIEW` to `TEST`**: a test asserts the training signal's field set
  excludes veto statistics, and the catalogue entry in
  `src/astra/invariants/catalogue.py` is updated to match. Until that lands, the catalogue must
  continue to say `REVIEW`.

### Risks

- **A-6** — Python 3.12 support across torch / SB3 / filterpy — is verified here. The dependency
  spike should be run early, not at integration time. Failure forces 3.11; the core is
  unaffected.
- **RK-5:** EWC's ability to prevent catastrophic forgetting is an empirical question, and the
  answer is not known until Phase 7 exercises it.

### Does not compress

PPO wall-clock training time. It is GPU-bound, not coding-bound, so the corpora should be started
in parallel with Phase 3 rather than at the start of Phase 4.

---

## Phase 5 — Statistical Assurance

*Demo Plan Week 2a.* Builds on: `TrustEstimator`, `StatisticalGate`, `TrustAssessment`,
`GateSettings`, `TrustSettings`, `SymmetricMatrix.variance_of`.

### Scope

- `l3_trust`: a hand-rolled **EnbPI** (MAPIE lacks a robust online time-series EnbPI) with
  Mondrian context bucketing over the four certified `ContextClass` values.
  `TI = 1 − F̂_k(α_{t+1})`.
- `l6_statistical_gate`: `α = |π_prop − π̂| / σ(x)` with `σ(x) = √P_f[control dim]`;
  class-conditional quantiles; CQR for heteroscedasticity; an **MMD covariate-shift detector over
  the rolling innovation distribution**, tightening ε dynamically when it fires.

### Exit criteria

- EnbPI unit-tested **in isolation on synthetic time series** before integration. The Demo Plan
  recommends this explicitly and the reason is that a subtly wrong conformal predictor produces
  plausible numbers indefinitely.
- Per-class empirical coverage ≥ 94.5% over 1 000 steps on synthetic data.
- The SI-4 architecture test stays green: no `TrustAssessment` reaches any gate.

### Risks

**RK-2 (High).** Hand-rolling EnbPI correctly is the primary implementation risk in the project
after L9. A coverage guarantee that is silently invalid is worse than no guarantee, because
downstream components will act on it. Mitigation is empirical coverage verification per class
*before* integration, not after.

### Does not compress

Calibration-sample collection. ≥ 500 residuals per context class is a data-volume requirement,
and the quantile from fewer samples is not merely noisier — it is not yet meaningful.
`TrustAssessment.calibration_sample_count` exists so a reviewer can see when that was the case.

---

## Phase 6 — Runtime Calibration Management

*Demo Plan Week 2b.* Builds on: `CalibrationArbiter`, `ProfileRepository`,
`RuntimeContextSignature`, `CalibrationProfile`, `ArbitrationDecision`,
`is_candidate_admissible`, `IssuedCommand`.

### Scope

- `l9_rcm`: the RCS builder (reliability-weighted, so a degraded sensor lowers its own
  contribution); the cold-path Mahalanobis knowledge-base search; the mandatory gates (expired
  signature, platform mismatch, critical-failure history); `T(c)` scoring; and admissibility
  `T(c) ≥ τ AND val(c) = 1` as a **hard** gate — the predicate already exists as
  `is_candidate_admissible`.
- Shadow execution plus the **Calibration Divergence Index** → commit or rollback.
- **Core-B's independent table validation** — signed checksum plus quantile monotonicity and
  range (SI-9). The monotonicity half already runs in `CalibrationProfile`; the checksum half
  lands here.
- **Bounded safe exploration**: 50% of the nearest certified maximum speed, no lane changes,
  steering ±15°, evidence logged, four exit conditions. The vehicle never halts.
- `calibration/profiles/`: the four seed profiles. **No tunnel profile.** That omission is
  deliberate and is what makes Phase 3.5 of the validation plan meaningful.

### Exit criteria

- **Checkpoint 2 from the Demo Plan.** The tunnel scenario works: no admissible profile is found,
  exploration engages, and the vehicle keeps moving.
- The cold path is proven never to block a tick (SI-8), which upgrades SI-8's enforcement from
  the queue-overflow test that exists today to a measured latency test.

### Risks

**RK-4 (Medium).** L9 has the highest architectural intricacy of any single component: two timing
domains, a staged switch with rollback, five arbitration outcomes and an exploration mode with
its own envelope. Budget the most debugging time here. It is built after the safety spine
precisely so that it can be tested against a working veto path.

### Does not compress

Profile certification. Each of the four seed profiles needs a certified centroid, covariance and
quantile table derived from a corpus — and `CalibrationProfile` refuses to construct without a
checksum, a platform and a non-decreasing table, so a half-certified profile cannot be smuggled
in to unblock the schedule.

---

## Phase 7 — Closing the Loops

*Demo Plan Week 3 — protected slack.* Builds on: `FeedbackBus`, `ExecutionOutcome`,
`FeedbackLoop`, `TrustEstimator.recalibrate`, `DynamicsPredictor.adapt`, and the replay harness
from Phase 2.

### Scope

Loops are brought up **one at a time**, confirming stability before the next is added. The order
is the declaration order of `FeedbackLoop` and it is not arbitrary.

1. **FB1** — the *applied* command, not the proposed one, re-anchors the UKF. Everything else
   depends on it.
2. **FB2** — a 50-sample buffer drives an EWC update of the PINN's **output layer only**,
   Fisher-anchored on 200 historical samples. Requires an **explicit catastrophic-forgetting
   test: highway accuracy must not degrade after adapting to rain.**
3. **FB3** — executed outcomes drive online Mondrian requantilisation.
4. **FB4** — executed command → simulator sync. Prototype-only, lowest risk, brought up last.

### Exit criteria

- A stable closed loop over a long run: no oscillation, no drift, no feedback overcorrection.
- Every loop demonstrably improves its target metric, **and degrades it when removed**. The second
  half is what distinguishes a loop that works from a loop that is merely present.

### Risks

**RK-3 (High).** Bugs here are usually not code bugs but emergent dynamics, and emergent dynamics
are not found by reading code. The replay harness built in Phase 2 is the primary debugging
instrument, which is the entire reason it is built five phases early.

### Does not compress

**This phase, in its entirety.** The Demo Plan protects Week 3 with slack specifically because
closed-loop integration is the stage that does not compress, and the slack must not be spent
covering an overrun in an earlier phase.

---

## Phase 8 — Observability, Demo Harness & Explainability Surface

*Demo Plan Week 4.* Builds on: `DecisionRecord`, `JsonlAuditSink`, the correlation context.

### Scope

- `apps/dashboard/backend`: FastAPI + WebSocket streaming live layer state.
- `apps/dashboard/frontend`: React + Recharts rendering the pipeline diagram itself — the Trust
  Index gauge; **L6 and L7 as separately lit paths**, which is the visual proof of gate
  independence; `P_f` visibly widening and narrowing the acceptance band; the FSM as a lit state
  diagram; RCM's knowledge-base search, shadow execution and a "SAFE EXPLORATION ENGAGED" banner;
  an event ticker with independent-cause attribution.
- A **comparison harness**: two synchronised instances — full ASTRA versus a baseline raw Core-A
  — against the identical injected fault. The highest-impact visual in the demo.
- **Interactive fault injection**, driven by the audience. A deliberate credibility move: a demo
  the audience triggers cannot have been scripted.
- The explainability surface is replay of `DecisionRecord` provenance, per finding R-7. Not
  SHAP, not LIME, and not claimed to be.

### Exit criteria

- Every number on the dashboard is traceable to a live record. Nothing scripted.
- A pre-recorded fallback run is captured before the first live demo.

### Risks

Scope creep (**RK-9**). A dashboard is the easiest place in the project to build features no
document specifies. Every panel must trace to a document line or an ADR.

### Does not compress

Nothing structurally — but the pre-recorded fallback must be captured *before* it is needed, and
that scheduling item is easy to lose.

---

## Phase 9 — Validation & Evidence

Builds on: everything.

### Scope

- A **seven-phase continuous drive** through CARLA Town04: highway → urban → rain/night →
  **tunnel (3.5)** → sensor fault → adversarial FGSM → recovery. The vehicle never stops.
- An **ablation study**: disable FB1/FB2/FB3 individually; run the ICP gate alone without the
  shield; disable safe exploration and force a HALT.
- Metrics against the Table VII targets, **reported as measurements**, with the
  software/hardware latency distinction stated explicitly every single time.
- An evidence pack: audit logs, replayable runs, a dependency licence inventory, and closure of
  every assumption in the register.

### Exit criteria

Every claim in the papers is either demonstrated by code that ran, or **explicitly listed as not
demonstrated**. The second list is a deliverable, not a failure.

### Risks

**RK-8 (High, credibility).** The failure mode here is not technical, it is rhetorical:
reporting the 1.25 µs hardware bound as a measurement, or "eliminates hallucination", or a
zero-failure claim. The honesty boundaries in [`ARCHITECTURE.md`](ARCHITECTURE.md) §10 and in
`README.md` exist to make that a reviewable error rather than an easy slip.

### Does not compress

Scenario debugging. The seven-phase drive is a single continuous run, so a failure in phase 6 of
the drive costs a full re-run to reproduce.

---

## Gating items outside engineering

From Demo Plan §10. These block an external demo regardless of how ready the code is, and none of
them is an engineering task.

- [ ] **Provisional patent filing status** — gates any external or company-facing demo. The
      repository is proprietary and private for this reason (assumption A-7); public disclosure
      can prejudice patentability in some jurisdictions.
- [ ] NDA in place for demo attendees.
- [ ] Team split confirmed — single builder, or parallel L2/L7/L8 · L3/L4 · L5/L6 tracks.
- [ ] Baseline system for the side-by-side chosen: raw Core-A, or lockstep emulation.
- [ ] Final three showcase scenarios confirmed.
- [ ] Backup recording scheduled ahead of the first live demo.

Two further items are open questions for the project guide rather than checkboxes, and both are
carried in the assumptions register: **A-9**, whether "MPC candidate scoring" inside L6 can
remain a sub-stage behind the `StatisticalGate` port or needs its own port and layer number
(finding R-8); and **A-10**, whether stakeholders expecting "explain every AI decision" will
accept decision provenance rather than model-internal attribution (finding R-7).
