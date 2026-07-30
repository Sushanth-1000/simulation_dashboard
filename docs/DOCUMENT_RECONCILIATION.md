# ASTRA — Document Reconciliation

Every contradiction found across the source documents, how it was resolved, and where the
resolution is encoded in code.

Five documents describe ASTRA. They were written at different times for different audiences, and
eleven points of apparent disagreement were found between them — one of which, on inspection,
turns out not to be a conflict at all. Some of the rest are cosmetic; two are architectural; one
is an unresolved technical risk that gates Phase 2.

The standing rule for this project is that **the source documents are the authority and
architecture is not invented** — but where documents conflict, something has to be chosen, and
the choice has to be recorded rather than absorbed silently into the code. This document is that
record. Each finding below states the conflict, the resolution, and the artefact in the
repository where the resolution now lives, so that a future reader who disagrees with a choice
can find every place it took effect.

| Document | Role in the corpus |
|---|---|
| `ASTRA_shortened.pdf` | **Primary technical authority.** Latest and most honest version of the paper |
| `ASTRA_paper 1.pdf` | Earlier draft. **Superseded** on layer numbering and on empirical claims |
| `ASTRA_mp1report.pdf` | **Requirements authority.** The only formal FR1–FR12 / NFR1–NFR8 statements |
| `ASTRA_patent_report_final.pdf` | Patent-oriented restatement, near-identical to the MP-1 report |
| `ASTRA_Prototype_and_Demo_Plan.md` | **Implementation authority.** Per-layer spec, build order, honesty boundaries |

Related: [`ARCHITECTURE.md`](ARCHITECTURE.md) ·
[`SEPARATION_INVARIANTS.md`](SEPARATION_INVARIANTS.md) · [`ROADMAP.md`](ROADMAP.md) ·
[`ENGINEERING_HANDOFF.md`](ENGINEERING_HANDOFF.md)

---

## Summary

| ID | Conflict, in one line | Status |
|---|---|---|
| [R-1](#r-1--layer-numbering) | Layer numbering: the consolidated L1–L9 versus an earlier draft's L4–L7 | Resolved |
| [R-2](#r-2--results-reported-as-achieved-versus-planned) | Results reported as achieved versus stated as planned | Resolved |
| [R-3](#r-3--l7s-dependency-on-l5) | L7 has "no dependency on L5/L6" versus L7 "includes a physical recheck" | Resolved — architectural |
| [R-4](#r-4--mondrian-class-names) | Two incompatible sets of context-class names | Resolved |
| [R-5](#r-5--slow-ukf-rate) | Slow UKF rate quoted as 1 Hz and as 0.1 Hz | Not a conflict |
| [R-6](#r-6--carla-versus-the-python-floor) | **CARLA 0.9.14 requires Python ≤ 3.8; the project floors at 3.12** | **UNRESOLVED — Phase 2** |
| [R-7](#r-7--explain-every-ai-decision) | "Explain every AI decision" promised; no XAI layer exists | Resolved — scoping |
| [R-8](#r-8--mpc-scoring-inside-l6) | "MPC scoring" inside L6 is named but never specified | Deferred |
| [R-9](#r-9--core-a-reads-the-trust-index) | Core-A reads the Trust Index — does that break core isolation? | Resolved — no conflict |
| [R-10](#r-10--the-acronym) | Two expansions of the ASTRA acronym | Resolved |
| [R-11](#r-11--module-layout) | Flat prototype module layout versus NFR5 domain independence | Resolved — architectural |

**One finding is unresolved: [R-6](#r-6--carla-versus-the-python-floor).** It is the single most
consequential open technical risk in the project.

---

## R-1 — Layer numbering

**Conflict.** `ASTRA_paper 1.pdf` numbers Core-B's internal stages L4–L6 and calls RCM L7. The
other three documents use a consolidated L1–L9 in which L4 is the Core-A proposer and L9 is RCM.
The same label therefore denotes different components depending on which document is open.

**Why it matters.** Layer identity appears in every audit record. A `LayerId` that means two
things makes the evidence archive unqueryable, and a safety assessor cannot join records across
runs.

**Resolution.** **Adopt L1–L9.** `ASTRA_paper 1.pdf` is the earlier draft and is superseded on
this point by the shortened paper, the MP-1 report and the Demo Plan — three of four documents,
including both authorities.

**Encoded in code.**

- `LayerId` in `src/astra/kernel/enums.py` — nine members, `L1_SENSOR_BUS` … `L9_RCM`, with a
  class docstring that names the superseded scheme and points back to this finding by number.
- `LayerId.ordinal` derives the number from the member name, so the numbering cannot drift from
  the identifier.
- `ASTRA_LAYER_COUNT = 9` in `src/astra/kernel/constants.py`, asserted against the enumeration by
  `tests/unit/test_constants.py`. Adding a tenth layer without updating the architecture
  documentation fails the build.

---

## R-2 — Results reported as achieved versus planned

**Conflict.** `ASTRA_paper 1.pdf` reports figures as achieved results — a "21-minute run",
"≈47 evidence tuples". `ASTRA_shortened.pdf` states plainly that the prototype and all of its
metrics are **planned, not executed**.

**Why it matters.** This is not a technical disagreement, it is a credibility one, and it is the
kind that is fatal in front of an assessor. It is also Demo Plan honesty boundary #1.

**Resolution.** **Nothing is a result until code produces it.** Every figure in the papers'
Tables VI/VII is a target. No metric may ever be hardcoded to look good. The retracted figures
from the earlier draft are not carried forward anywhere.

**Encoded in code.**

- `src/astra/kernel/constants.py` contains **no thresholds at all**, and its module docstring
  explains why: θ1/θ2/θ3, ε, γ, τ and δ_CDI have no defensible defaults because the documents
  never assign them values, and they can only be fixed empirically.
- `src/astra/config/schema.py` gives **no default to any safety threshold**. A missing one is a
  startup failure, raised as `ConfigurationError` by `load_settings`, whose message names
  assumption A-4 explicitly.
- `config/environments/certification.toml` ships with every threshold **commented out**, so
  loading it fails by design. The test suite exercises that failure.
- `config/environments/development.toml` carries a banner declaring its values PROVISIONAL, NOT
  CERTIFIED, NOT EVIDENCE, and the `config_hash` stamped on every `DecisionRecord` is what makes
  a run under that file distinguishable from a certified one.
- `TrustAssessment.calibration_sample_count` in `src/astra/contracts/assurance.py` exists so that
  a reviewer can see when a quantile was backed by too few samples to mean anything.
- The honesty boundaries are reproduced verbatim in `README.md` and in
  [`ARCHITECTURE.md`](ARCHITECTURE.md) §10.

Every number in this repository's own documentation follows the same rule. The 1352 tests and
99% coverage are counts a command produced; the < 10 ms end-to-end budget is a *target*; and the
1.25 µs Core-B intercept figure is an **analytical hardware WCET bound**, never a measurement.

---

## R-3 — L7's dependency on L5

**Conflict.** The Demo Plan states that L7 has *"no dependency on L5 or L6 outputs"* — which is
what makes its veto structurally independent. The papers describe L7 as a *"combined Hard Safety
Shield **and physical recheck**"*, and the physical recheck uses the PINN's prediction, which is
an L5 output. Both statements cannot be true of one component.

**Why it matters.** This is the load-bearing claim of the whole architecture. If the
deterministic shield reads the twin's prediction, then PINN drift is a common failure mode across
two of the three gates, and the independence argument in
[`ARCHITECTURE.md`](ARCHITECTURE.md) §4 collapses.

**Resolution.** **Split L7 explicitly into two gates with different inputs.**

- **L7a — Hard Safety Shield.** Deterministic. Reads *only* the UKF state and the slow
  degradation estimate. Zero dependency on L5 or L6. Carries `GateId.DETERMINISTIC` and
  unconditional veto authority.
- **L7b — Physical Admissibility Checker.** The PINN-based gate. Formally assigned
  `GateId.PHYSICAL`. Depends on L5 by design, because Newtonian admissibility of a *predicted*
  next state is what it evaluates.

With the split, both source statements are simultaneously true.

**Encoded in code.** The split lives in `src/astra/ports/pipeline.py` as two protocols whose
signatures differ in exactly the way the argument requires:

| Protocol | Parameters | Cannot see |
|---|---|---|
| `DeterministicShield` (L7a) | `tick`, `proposal`, `state`, `degradation` | The twin's prediction, the conformal score, the Trust Index |
| `PhysicalAdmissibilityChecker` (L7b) | `tick`, `proposal`, `prediction`, `state` | — (depends on L5 by design) |

Also encoded in `GateId` in `src/astra/kernel/enums.py`, whose members document themselves as
`L6`, `L5/L7b` and `L7a` respectively, and whose class docstring states that the independence
claim is a claim about *failure modes* rather than about code paths merely being separate files.

**A nuance worth stating.** `LayerId` has a single `L7_HARD_SAFETY_SHIELD` member; there is no
`L7A` and no `L7B`. The split is expressed in the ports and in `GateId`, not in the layer
enumeration. That is deliberate — a failure mode is a property of a gate, not of a layer number —
but it does mean a reader looking for "L7a" in `LayerId` will not find it. The a/b labels appear
in the port docstrings and in the `GateId` member documentation.

---

## R-4 — Mondrian class names

**Conflict.** `ASTRA_paper 1.pdf` gives the Trust Module's Mondrian conditioning classes as
`{HIGHWAY-CLEAR, URBAN-RAIN, SENSOR-DEGRADED}`. The Demo Plan and the validation plan give the
Calibration Knowledge Base's four seed profiles as
`{highway_clear, urban_clear, rain_night, degraded_sensor}`. Three classes versus four, with
different names and different spellings.

**Why it matters.** A concept that serialises three different ways cannot be queried in an audit
log, and the Demo Plan states that the trust classes and the KB profiles *match* — so they must
be one enumeration or the match is unverifiable.

**Resolution.** **Adopt the four KB seed names**, plus an explicit `UNCLASSIFIED` for the case
where no certified class applies. Trust-module classes and knowledge-base profiles are modelled
as one enumeration, because the Demo Plan says they are the same set.

**Encoded in code.** `ContextClass` in `src/astra/kernel/enums.py`:
`HIGHWAY_CLEAR`, `URBAN_CLEAR`, `RAIN_NIGHT`, `DEGRADED_SENSOR`, `UNCLASSIFIED`, with
`is_certified` returning `False` for exactly the last one.

The class docstring records why there is no tunnel class: the validation plan deliberately
withholds a tunnel profile so that Phase 3.5 exercises the bounded safe-exploration path, and
`UNCLASSIFIED` is what the classifier returns there. `ProfileRepository.for_context` in
`src/astra/ports/infrastructure.py` documents an empty result as the *expected* outcome for an
uncertified context — it triggers exploration, not an error.

---

## R-5 — Slow UKF rate

**Conflict.** The slow filter's rate is quoted as 1 Hz in some places and 0.1 Hz in others.

**Resolution.** **Not a conflict.** 1 Hz is the deployment rate; 0.1 Hz is the prototype rate. A
simulated run is too short for a 1 Hz filter to accumulate meaningful degradation-parameter
estimates. Both are **configuration**, not constants.

**Encoded in code.** `EstimationSettings.slow_rate_hz` in `src/astra/config/schema.py`, whose
field documentation names this finding. The default of 1.0 Hz is in
`config/astra.defaults.toml` with a comment citing R-5, and `config/environments/simulation.toml`
overrides it, also citing R-5. The rate is deliberately *not* in
`src/astra/kernel/constants.py`: by that module's own stated test, a value that legitimately
differs between the deployment and prototype operating points is configuration, and only values
that cannot change without changing the architecture belong in source.

---

## R-6 — CARLA versus the Python floor

> ### **UNRESOLVED. This is the single most consequential open technical risk in the project.**
> Scheduled for decision in **Phase 2**, and it should be attempted first in that phase.

**Conflict.** The source documents mandate **Python 3.10+** *and* **CARLA 0.9.14**. CARLA
0.9.14's official Python client ships for Python 2.7 / 3.6 / 3.7 / 3.8 only. As stated, the two
requirements are incompatible — no interpreter satisfies both. This project's floor is 3.12,
chosen for PEP 695 generics and `typing.override` and for a security-support horizon beyond the
project's, which widens rather than narrows the gap.

**Why it matters.** It is the only finding whose resolution could change a non-functional
property of the running system. If the answer turns out to be a sidecar process, every sensor
frame crosses an IPC boundary, and that hop is charged against a 10 ms end-to-end budget at
20 Hz. The other two routes cost nothing at runtime. Recorded as risk **RK-1 (High)** and
assumption **A-8**.

**Options, to be decided in Phase 2.**

| Route | What it costs |
|---|---|
| (a) Upgrade to CARLA 0.9.15+ / 0.10.x with newer interpreter support | Scenario and API differences; the least invasive if it works |
| (b) A community-built egg or wheel for 3.10+ | Unofficial artefact in a safety-adjacent toolchain; a supply-chain question |
| (c) Run the CARLA client as a Python 3.8 sidecar bridged to the 3.12 core | An IPC hop on the hot path, charged against the latency budget |

**Why the core is unaffected either way — and this is the point of the mitigation.** The
simulator is isolated behind a port (ADR-0003, NFR5), so which route is chosen is a *deployment*
detail rather than an architectural one.

**Encoded in code.**

- `.importlinter`'s `simulator-isolation` contract forbids **the whole of `astra`** from importing
  `carla`, with a comment naming this finding. The eventual adapter is the single permitted
  exception and will be added as an explicit exclusion when it exists.
- `tests/architecture/test_layering.py::test_no_module_in_the_core_imports_the_simulator_client`
  parses every source file's AST and asserts the same thing independently of import-linter.
- `src/astra/ports/pipeline.py` uses structural `Protocol` types rather than abstract base
  classes, so an adapter implements `SensorSource` without importing anything from ASTRA. Its
  module docstring states that this is what makes R-6 a deployment detail.
- `Timeline.SIMULATED` in `src/astra/kernel/time.py` and the injected `Clock` mean the
  simulator's clock is substitutable without any layer knowing.

**What "resolved" will look like.** A Phase 2 decision record naming the chosen route, a measured
answer to whether route (c)'s IPC hop fits inside the budget if (c) is chosen, and the
`simulator-isolation` contract updated with the adapter's exclusion. Until then, nothing in this
repository imports a simulator, and the architecture does not depend on which answer wins.

---

## R-7 — "Explain every AI decision"

**Conflict.** The project's own objective statement promises to *"explain every AI decision"*. No
explainability layer — no SHAP, no LIME, no attention attribution — exists in any of the papers.
Nothing in the nine-layer architecture produces feature attributions.

**Why it matters.** If stakeholders expect model-internal attribution and receive decision
provenance, the deliverable does not meet the promise, however good it is. The gap has to be
closed by scoping the claim, not by quietly redefining it.

**Resolution.** **Explainability in ASTRA is decision provenance, not feature attribution.** For
each tick: which gate fired, on what evidence, under which calibration profile, at which
configuration hash. That is exactly NFR8, plus the Demo Plan's "independent cause" event ticker.
**Model-internal attribution is explicitly not claimed**, anywhere.

**Encoded in code.** `DecisionRecord` in `src/astra/contracts/audit.py` is the explainability
unit, and its module docstring names this finding. For one tick it ties together:

```
run · tick · config_hash
  → frame_health (per modality)
  → fast_state (mean + covariance)
  → trust (TI, context class, quantile, coverage, sample count)
  → proposal (command, origin, source, admissibility)
  → prediction_admissible
  → safety_verdict (aggregate, vetoing gates, every gate verdict with its evidence)
  → failsafe (state, OOD counter, speed cap, permissions)
  → arbitration (outcome, active/candidate profile, T(c), CDI)
  → issued (command, origin, issuer, instant)
```

Supporting mechanisms:

- `GateVerdict` carries a stable `reason_code` and an ordered `evidence` tuple of named numeric
  quantities, so the log records *why* a gate decided rather than only *what* it decided.
- `CommandOrigin` in `src/astra/contracts/actuation.py` — `PROPOSED`, `FALLBACK_PID`,
  `SPEED_CAPPED`, `EXPLORATION_BOUNDED` — answers "why did the vehicle do that" categorically,
  and its docstring names this finding as the reason it exists.
- Optional stages render as `null` rather than being omitted, so a tick that ended early is
  visibly a tick that ended early, and the evidence archive is a rectangle rather than a ragged
  join.

**Open item.** Assumption **A-10** records that this scoping must be confirmed with the project
owner. If stakeholders do expect SHAP/LIME, a new layer is needed and this resolution does not
hold.

---

## R-8 — "MPC scoring" inside L6

**Conflict.** L6 is described as an "MPC scoring + ICP gate", and `LayerId.L6_MPC_ICP_GATE`
carries that name — but no document specifies what the MPC stage does, what it consumes, or what
it produces.

**Resolution.** **Deferred, and flagged as a documentation gap rather than filled in by
invention.** MPC candidate scoring is treated as a sub-stage of L6 behind the same
`StatisticalGate` port, so it needs no separate port, no separate layer number and no separate
verdict. It is not implemented in Phase 1 and it is not specified here, because specifying it
would be inventing architecture.

**Encoded in code.** `LayerId.L6_MPC_ICP_GATE` preserves the name from the documents, and
`StatisticalGate` in `src/astra/ports/pipeline.py` is the single port for the layer. The port's
`evaluate` returns one `GateVerdict` tagged `GateId.STATISTICAL`, which is compatible with an
internal scoring stage and would not be compatible with a second independent gate.

**Open item.** Assumption **A-9**: if MPC scoring turns out to need its own port and layer number,
the deferral is wrong and the enumeration changes. To be clarified with the project guide.

---

## R-9 — Core-A reads the Trust Index

**Conflict.** Core-A (L4) consumes the Trust Index. Core-A and Core-B are supposed to be
isolated. On its face this looks like a breach of that isolation.

**Resolution.** **No conflict. Two different invariants, neither violated.** L3, the Trust
Module, is in the `SHARED` execution domain — not in Core-B. So:

- The Trust Index is withheld from **Core-B's verdict** (SI-4). It is monitoring and routing
  information, never a gate input.
- Core-A is blind to **Core-B's outputs** (SI-5). It sees no verdict, no FSM state, no
  calibration table, no quantile and no veto rate.

Core-A reading a `SHARED`-domain signal breaches neither statement.

**Encoded in code.**

- `_LAYER_DOMAIN` in `src/astra/kernel/enums.py` maps `L3_CONFORMAL_TRUST → SHARED`, and
  `LayerId.execution_domain` exposes it as a total function.
- SI-4: `SafetyVerdict` has no trust field, and no gate port accepts a `TrustAssessment`.
  `tests/architecture/test_invariants.py` asserts both, *and* asserts the positive half — that
  `TrustAssessment` does reach `CommandProposer.propose` and `CalibrationArbiter.issue` — so the
  invariant cannot be satisfied by deleting the Trust Index from the system.
- SI-5: `CommandProposer.propose` takes `tick`, `state` and `trust`, and nothing from Core-B.

Full treatment in [`SEPARATION_INVARIANTS.md`](SEPARATION_INVARIANTS.md), §SI-4 and §SI-5.

---

## R-10 — The acronym

**Conflict.** The patent report expands ASTRA as "Autonomous Safety **and** Trust Runtime
Architecture". The other three documents use "Autonomous Safety, Trust, and Runtime
Architecture".

**Resolution.** **Adopt "Autonomous Safety, Trust, and Runtime Architecture"** — three of four
documents, including both authorities.

**Encoded in code.** The module docstring of `src/astra/__init__.py`, the subtitle of
`README.md`, and `pyproject.toml`'s `description` field — which is the string that reaches any
built artefact's metadata.

Trivial as conflicts go, but the project name appears on every artefact that leaves the
repository, and an inconsistent one on a patent filing is not trivial.

---

## R-11 — Module layout

**Conflict.** Demo Plan §9 proposes a flat prototype layout — `core/`, `feedback/`, `comms/`,
`logs/` — with no packaging, no test tree and no configuration. NFR5 requires domain
independence: *"the architecture shall be domain-independent… new operational contexts through
the addition of certified profiles without modification to any other component."* A flat layout
whose `core/` imports a simulator client cannot deliver that.

**Resolution.** **Adopt a `src/astra/` package with hexagonal ports. Every proposed module maps
to a new home; the architecture is respected and only the packaging is upgraded.** Confirmed with
the project owner. The full mapping table is in [`ROADMAP.md`](ROADMAP.md).

**Encoded in code.**

- The `src/` layout itself, which makes it impossible to import `astra` from the repository root
  by accident, so tests always exercise the installed package and a missing wheel entry fails in
  CI rather than in deployment.
- `.importlinter`'s `layers` contract fixes the dependency graph
  `kernel < contracts < ports < {config, observability, invariants} < bootstrap`, and
  `tests/architecture/test_layering.py` runs it as part of the test suite.
- The hexagonal boundary is real, not nominal: `src/astra/ports/` holds ten pipeline protocols
  and four infrastructure ports, and `ActuationSpace` in `src/astra/contracts/actuation.py` is
  what turns the vehicle's command space from hardcoded constants into configured data — which
  is how NFR5 is actually achieved rather than merely claimed.
- One Demo Plan path is deliberately *not* preserved: `logs/event_log.jsonl` becomes
  `var/runs/<run-id>/events.jsonl` via `JsonlAuditSink`, because one directory per run makes a
  run the unit of archival and replay, which a single shared log file cannot be.

Assumption **A-1** records that this is how domain independence is achieved, and names its own
falsification test: in Phase 6, add a non-automotive profile without touching the core.
