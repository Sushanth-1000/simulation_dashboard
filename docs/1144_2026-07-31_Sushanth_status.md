# ASTRA — Status and Route to a Working Prototype

> ## ⚠ SUPERSEDED — do not cite
>
> Superseded on 31 July 2026 by [`2030_2026-07-31_Tanay_S_status.md`](2030_2026-07-31_Tanay_S_status.md),
> and its measurements superseded again on 2 August 2026 by
> [`SOAK_REPORT.md`](SOAK_REPORT.md) and [`EVIDENCE.md`](EVIDENCE.md).
>
> Every closed-loop figure in this document was taken before four defects were
> found that invalidate them: lateral position was observed by no sensor, the
> training plant integrated 2.5× faster than the control period, the calibration
> corpus was harvested from a different proposer than the one deployed, and the
> trained policy brought the vehicle to a stop inside its own environment.
>
> Kept for the reasoning and the history. **For current numbers use
> [`EVIDENCE.md`](EVIDENCE.md); for current work use [`PENDING.md`](PENDING.md).**

**Prepared** Friday, 31 July 2026, 11:44 IST (UTC+05:30) · `2026-07-31T06:14Z`
**Author** Sushanth C.
**Branch** `phase4-l5-twin-l7b-physical` · 7 commits ahead of `main`
**Institution** Dept. of CSE, B.M.S. College of Engineering, Bengaluru
**Team** Sushanth C., Tanay S. Huddar, Tarun Gowda V., T. Tilak Reddy
**Guide** Dr. Chaitra R.

> **Confidential — unpublished proprietary work.** Do not distribute or demonstrate
> externally until the patent filing status is confirmed. See `LICENSE` and `NOTICE`.

---

## 0. The one-paragraph version

Every one of ASTRA's nine layers now exists, is individually tested, and passes a
quality gate of 2,284 tests at 98.89% coverage with twelve machine-checked
architecture contracts and `mypy --strict` clean across 120 files. **The system
has never run end to end.** Not one command has passed from the proposer,
through all three gates, to an issued actuator command. That gap — ten tested
components with nothing composing them — is the honest distance between
"architecture complete" and "prototype complete", and closing it is the single
highest-value task remaining.

**Completion: approximately 55%.**

---

## 1. Measured state

Every figure below was read from the repository or produced by a run today.
None is estimated or rounded favourably.

| Metric | Value |
|---|---|
| Source | **71 modules · 14,584 lines** |
| Tests | **49 files · 2,284 tests** |
| Coverage | **98.89%** against a 95% gate |
| Architecture contracts | **12** kept, 0 broken |
| Type checking | `mypy --strict` clean on **120** files |
| Lint | `ruff` format + check clean, ~30 rule families |
| Certification fields deliberately absent | **21** |
| Layer packages | **10 of 10** |

### Quality gate, verified on Linux / CPython 3.12

```
ruff format --check     125+ files formatted
ruff check              All checks passed!
mypy --strict           Success: no issues found in 120 source files
lint-imports            Contracts: 12 kept, 0 broken.
pytest --cov=astra      2284 passed  ·  coverage 98.89%
astra doctor            OK  this installation can start a run.
```

**Important environment note.** Smart App Control on the development Windows host
blocks the unsigned native extensions used by `torch`, `mypy` and `grimp`. The
full gate is therefore **only runnable under Linux** (WSL2 today, native Ubuntu
required later for CARLA). This is not a preference — it is a hard constraint.

---

## 2. The framework as built

### 2.1 Pipeline

```
        L1  Shared Sensor Bus                                    [BUILT]
         │
        L2  Dual-Rate UKF ──────────────────┐                    [BUILT]
         │                                  │ state + covariance
   ┌─────┴─────┐                            │
  L3 Conformal  L4 Core-A (CMDP)            │              [BUILT] [BUILT*]
   │  Trust TI   │                          │
   │             │ π_prop  (ONE-WAY)        │
   │             ▼                          │
   │   ┌──────── CORE-B (safety island) ────┴────┐
   │   │  L5  PINN twin                          │          [BUILT + TRAINED*]
   │   │  L6  ICP gate      → statistical gate   │          [BUILT]
   │   │  L7a Hard Shield   → deterministic gate │          [BUILT]
   │   │  L7b Physical      → physical gate      │          [BUILT]
   │   │  L8  Fail-Safe FSM                      │          [BUILT]
   │   └──────────────┬──────────────────────────┘
   │                  │ verdict + FSM state
   └────────►  L9  RCM (sole actuator authority)            [BUILT]
                      │
                   Actuators
                      │
     FB1 · FB2 · FB3 · FB4 └── outcomes fed back upstream   [NOT WIRED]
```

`*` L4 is scaffolded — proposer, constraint machinery and training-signal
discipline exist; the PPO policy does not. L5 is trained on synthetic dynamics
only.

### 2.2 Layer inventory

| Layer | Module | State |
|---|---|---|
| L1 | `l1_sensing/bus.py` | Built, 100% covered |
| L2 | `l2_estimation/` | Built, 99% covered |
| L3 | `l3_trust/` — `quantile`, `mondrian`, `trust` | **Built, 100% covered** |
| L4 | `l4_proposer/` — `proposer`, `constraints`, `signal` | **Built** (policy absent) |
| L5 | `l5_twin/` — `network`, `twin` | **Built + trained** |
| L6 | `l6_statistical_gate/` — `gate`, `mmd` | **Built** |
| L7a | `l7_shield/shield.py` | Built, 100% covered |
| L7b | `l7b_physical/checker.py` | **Built, 100% covered** |
| L8 | `l8_failsafe/machine.py` | Built, 100% covered |
| L9 | `l9_rcm/` — `arbiter`, `knowledge_base`, `shadow`, `exploration` | **Built, 100% covered** |

### 2.3 Separation invariants

| ID | Invariant | Enforcement |
|---|---|---|
| SI-1 | Sensor opacity | import-linter + payload generics |
| SI-2 | Single state source | import-linter layering |
| SI-3 | Unconditional veto | `Verdict.merge` + **4** import contracts |
| SI-4 | Trust isolation | Structural — no gate accepts a `TrustAssessment`; **new contract** |
| SI-5 | One-way core channel | Capability pair + runtime guards + **contract now active** |
| SI-6 | Veto-rate exclusion | **Now mechanical** — closed field set, asserted by test |
| SI-7 | Sole actuation authority | `IssuedCommand` refuses a non-L9 issuer |
| SI-8 | Timing-domain separation | Hot/cold split in L9; timing test still absent |
| SI-9 | Independent calibration validation | Monotonicity enforced; **checksum still unverified** |
| SI-10 | Evidence non-influence | import-linter contract |

**SI-6 and SI-5 changed status this session.** SI-6 was the one invariant of ten
enforced by code review alone; it is now a frozen five-field record asserted
against a permitted set, with a substring tripwire behind it. SI-5's import
contract had been commented out since Phase 1 because it named a module that did
not exist; `l4_proposer` now exists and the contract is live.

---

## 3. What was built this session, and what it cost to learn

Seven commits. Each entry below records a defect found *while building*, because
those are the parts worth carrying forward.

| Commit | Content |
|---|---|
| `c00f54a` | Declared `numpy`/`filterpy`; L4, L5, L7b |
| `25d77d9` | L3's conformal core, verified in isolation |
| `5b78f18` | L3's `TrustEstimator` |
| `04530cc` | L6, completing all three gates |
| `7876d57` | L9 cold path — KB search, scoring, exploration |
| `04cfad2` | L9 hot path — `issue()`, shadow execution, CDI |
| `49b77c7` | Twin training, checkpoints, weights digest |

### Defects found and fixed

1. **`numpy` and `filterpy` were undeclared.** Imported by L2, present in no
   manifest. A frozen install produced 39 mypy errors and three test-collection
   failures. The "green gate" was green only where those had been hand-installed.
2. **FilterPy's docstrings break the suite non-deterministically.** Invalid escape
   sequences raise `SyntaxWarning`, which `filterwarnings = ["error"]` promotes to
   a `SyntaxError`. Whether it fires depends on whether the installer
   byte-compiled: pip does, `uv sync` does not. A gate whose result depends on the
   installer is not a gate.
3. **The EWC penalty was a no-op.** Anchoring on current parameters makes
   `(θ − θ_anchor)` zero in both value and gradient — the term cost time and
   constrained nothing.
4. **`adapt()` crashed on infinite input** — the finiteness guard ran *after*
   `math.sin`, which raises rather than returning NaN.
5. **Twin adaptation diverged to ±10²³.** The physics gradient scales with control
   effectiveness. Now norm-clipped, with a rollback if an update produces
   non-finite weights — a twin holding NaN predicts NaN, which the gate reads as
   **PASS**.
6. **`uv.lock` went stale a second time**, for the `learning` extra. Caught by the
   training run, not the test suite: nothing exercises a from-scratch frozen
   install.

### Traps documented so they are not re-introduced

- **"Tighten ε" is backwards as written.** The acceptance region is
  `{score ≤ q_{1−ε}}`, so a *smaller* ε widens it. Implementing the paper's phrase
  literally would make the gate **more permissive** exactly when covariate shift
  is detected — and nothing would raise, because coverage would still hold at the
  weaker level. The setting is `shift_epsilon_multiplier`, constrained `≥ 1`.
- **The conformal quantile has two classic errors**, both now tested: omitting the
  `+1` in `⌈(n+1)(1−ε)⌉` (under-covers), and returning `max(scores)` when no finite
  threshold exists (converts "not enough data to promise anything" into a
  rejection made on an authority that does not exist).
- **A magnitude bound in L7b would silently merge two gates.** Both its bounds are
  therefore rate limits. A test asserts a command L7a passes and L7b vetoes.

---

## 4. Known gaps — stated, not hidden

| # | Gap | Consequence |
|---|---|---|
| 1 | **No integration.** Nothing composes the ten layers; no tick loop exists | The system has never run |
| 2 | No PPO policy | L4 cannot propose |
| 3 | No calibration corpora | Conformal quantiles are infinite; L6 vetoes everything as `CONTEXT_NOT_CALIBRATED` |
| 4 | CARLA never installed or run | A-8 is evidenced from wheel metadata, not verified |
| 5 | Twin trained on synthetic kinematics only | Can expose an implementation error, never a modelling one |
| 6 | Feedback loops not wired | FB2/FB3 mechanisms exist inside L5/L3; nothing connects them |
| 7 | `TrustAssessment` cannot express "uncalibrated" | Encoded fail-closed as `0.0`; needs an explicit field before the evidence pack |
| 8 | SI-8 has no timing test; SI-9's checksum is stored but unverified | Two invariants partially enforced |
| 9 | One flaky concurrency test | Failed twice under load; passed 25/25 in isolation |
| 10 | No frozen-install smoke check | Let the lockfile go stale twice |
| 11 | Docs report 8 contracts / 17 certification fields | Actual: **12** and **21** |

### What must never be claimed

Carried forward and still binding:

1. The **1.25 µs figure is an analytical hardware bound**, not a measurement. No
   software prototype can produce it — it describes an RTL implementation of the
   ICP engine that does not exist, and excludes L1, L2, L3, L4, L5 and L9.
2. **ASIL-D(D) is a design target**, not an awarded rating. An ASIL is the outcome
   of an assessed safety case.
3. **Every gate figure is a unit-test result**, not a pipeline result. No
   false-positive, false-negative or veto-rate number exists, because no pipeline
   has run.
4. **All twin and filter accuracy is against synthetic dynamics.**
5. **Gate independence is architecture, not evidence**, until the Phase 9
   scenarios designed so that exactly one gate fires have been run.

---

## 5. Route to a working prototype

Ordered by dependency. Items 1–2 need no new hardware.

### Stage 1 — Integration (no hardware) · ~1 week

Build the composition root that constructs all ten layers and a tick loop that
runs them: acquire → estimate → assess trust → propose → gate ×3 → aggregate →
FSM → issue → record. Extend `DecisionRecord` so one tick produces one complete
evidence row.

**Exit:** one command travels the full pipeline and appears in the audit log with
its configuration hash and twin weights digest. This is the moment the project
stops being ten components and starts being a system.

### Stage 2 — Calibration corpora (no hardware) · ~3 days

Generate ≥500 non-conformity scores per context class from the trained twin and
the synthetic vehicle. Seed the four `CalibrationProfile`s. Verify per-class
empirical coverage ≥94.5% over 1,000 steps.

**Exit:** conformal quantiles are finite; L6 stops vetoing everything; RK-2 has
measured evidence behind it.

### Stage 3 — Linux + CARLA · ~1 week

Dual-boot Ubuntu 22.04 on the RTX 3050 host. `pip install carla==0.9.16`, verify a
client-to-server connection, write the adapter at the `MeasurementExtractor` seam.

**Exit:** closes **RK-1b** and converts A-8 from evidenced to verified. Unblocks
real UKF validation and everything in Phases 6 and 9.

### Stage 4 — PPO training · ~3–4 weeks (GPU wall-clock)

Train the CMDP policy under the Lagrangian wrapper against CARLA. Constraints C1–C3
with veto rate excluded — now enforced by test, not review.

**Exit:** **Checkpoint 1** — one real scenario end to end with no feedback loops.

### Stage 5 — Feedback loops · ~2–3 weeks

One at a time. **FB1 first** — everything depends on it, and it is the mitigation
for the acknowledged shared-state common-cause channel. FB2 requires the
catastrophic-forgetting test written *before* the loop. Then FB3, then FB4.

**Exit:** stable closed loop; each loop demonstrably improves its metric and
degrades it when removed.

### Stage 6 — Dashboard and comparison harness · ~2 weeks

Optional for the engineering, decisive for the demo. Two synchronised instances —
full ASTRA versus raw Core-A — against the identical injected fault, with
interactive fault injection.

### Stage 7 — Validation and evidence · ~2 weeks

The seven-phase Town04 drive, the ablation study, and the evidence pack: one entry
per claim, each pointing at the run that produced it, plus an explicit list of
claims **not** demonstrated.

**Realistic total: 10–12 weeks with four people parallelised; 14–18 solo.**

---

## 6. What would actually impress

Three things carry more weight than a longer feature list.

**The tunnel scenario.** Every system in the prior-art table degrades to a halt.
ASTRA is built not to: no admissible profile, exploration engages at half the
nearest certified speed inside a ±15° cone, and the vehicle keeps moving while
logging evidence that never touches the live safety argument. That is the
differentiator, and the code for it exists today.

**The side-by-side.** Full ASTRA against raw Core-A, same injected fault, same
seed, running simultaneously. One keeps going; one does not. No slide competes
with that.

**The honesty ledger.** A reviewer who finds one overclaim discounts everything
else. A paper that states plainly which claims are demonstrated, which are
targets, and which are structurally undemonstrable earns trust that a clean sweep
of unqualified results does not. This project already has the machinery —
`certification.toml` refuses to start on 21 missing thresholds, the invariant
catalogue records enforcement honestly, and every latency figure is labelled.
**Use it, and apply it to the paper as rigorously as to the code.**

---

## 7. Immediate next actions

1. **Confirm the paper's validation section with Dr. Chaitra.** §5 of the
   submitted survey describes a 21-minute CARLA drive that has not been run.
   This is the only time-critical item and it is not an engineering one.
2. **Build the integration layer** (Stage 1). Highest engineering value; needs
   nothing external.
3. **Add a `uv sync --frozen` smoke check to CI.** Two lockfile defects reached
   commits because nothing exercised a from-scratch install.
4. **Update the roadmap document** — 8 → 12 contracts, 17 → 21 certification
   fields, and the layer statuses above.
5. **Make the flaky concurrency test deterministic** before Phase 7 begins.
6. **Have one stats-literate person read `l3_trust/quantile.py`.** It is the one
   place where being subtly wrong is both easy and invisible, and an outside
   reader is worth more there than anywhere else in the codebase.

---

*Prepared by Sushanth C., 31 July 2026, 11:44 IST. Every figure was read from the
repository or produced by a run at the time of writing.*
