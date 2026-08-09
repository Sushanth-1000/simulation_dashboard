# Assumptions register

Where the four ASTRA source documents were silent, a decision still had to be made. Each such
decision is recorded here as an assumption: what was assumed, what breaks if it turns out to be
wrong, how to find out, and what its status is now that Phase 1 is complete.

An assumption is not a risk. A risk is something that might go wrong; an assumption is something
the architecture currently *depends on being true* and has not yet proved. The distinction matters
because an unproved assumption that nobody wrote down becomes, after a few months, an unexamined
belief.

**Status vocabulary**

| Status | Meaning |
|---|---|
| **ENFORCED** | The assumption has been converted into a mechanism. It cannot be violated silently |
| **HOLDING** | Consistent with everything built so far; not yet independently verified |
| **OPEN** | Not yet testable. The phase that tests it has not started |
| **EXTERNAL** | Resolution is not an engineering activity — it needs a person outside the codebase |

---

## Register

| ID | Assumption | Status after Phase 1 |
|---|---|---|
| [A-1](#a-1--domain-independence-comes-from-ports-plus-a-configured-actuationspace) | Domain independence via ports + configured `ActuationSpace` | HOLDING |
| [A-2](#a-2--a-10-ms-end-to-end-budget-at-20-hz-is-achievable-in-cpython) | 10 ms end-to-end at 20 Hz is achievable in CPython | OPEN |
| [A-3](#a-3--append-only-jsonl-one-file-per-run-is-adequate-prototype-evidence) | Append-only JSONL is adequate prototype evidence | HOLDING |
| [A-4](#a-4--safety-thresholds-have-no-defensible-default) | Safety thresholds have no defensible default | **ENFORCED** |
| [A-5](#a-5--a-single-random-runid-is-sufficient-for-byte-comparable-replay) | One random `RunId` suffices for byte-comparable replay | HOLDING (partial) |
| [A-6](#a-6--python-312-is-supported-by-the-ml-stack-at-phase-4) | Python 3.12 is supported by the ML stack at Phase 4 | OPEN — early warning active |
| [A-7](#a-7--the-repository-stays-private-until-the-filing-is-confirmed) | The repository stays private until the filing is confirmed | EXTERNAL |
| [A-8](#a-8--the-carlainterpreter-incompatibility-is-resolvable-without-changing-the-core) | CARLA/interpreter incompatibility is resolvable without core changes | **RESOLVED** — install verified on CPython 3.12, 5 Aug 2026 |
| [A-9](#a-9--mpc-candidate-scoring-fits-behind-the-statisticalgate-port) | MPC candidate scoring fits behind the `StatisticalGate` port | EXTERNAL |
| [A-10](#a-10--explainability-means-decision-provenance-not-model-internal-attribution) | Explainability means decision provenance, not model-internal attribution | EXTERNAL |

---

## A-1 — Domain independence comes from ports plus a configured `ActuationSpace`

**Assumption.** Domain independence is achieved by hexagonal ports plus a configured
`ActuationSpace`; every vehicle-specific concept lives in an adapter or in configuration, never in
the core.

**Impact if wrong.** NFR5 is unmet, and the paper's claim that the architecture generalises beyond
automotive is unsupported. Extracting vehicle vocabulary from a core that has absorbed it is a
migration, not a refactor — which is precisely why the assumption was made at Phase 1 rather than
tested later.

**How to verify.** Phase 6: add a non-automotive calibration profile and adapter — a drone or an
industrial robot arm — and confirm no module under `src/astra/` outside the adapter changes.

**Status after Phase 1: HOLDING.** Consistent with everything built. Every layer interface in
`src/astra/ports/pipeline.py` is a structural `Protocol`, so an adapter satisfies it without
importing an ASTRA base class and the core never learns the adapter exists. `ActuationChannel` and
`ActuationSpace` in `src/astra/contracts/actuation.py` describe an actuation space as configured
data rather than as fixed vehicle controls. The `simulator-isolation` contract in `.importlinter`
proves the negative for one concrete domain: nothing anywhere in `astra` imports `carla`.

What is *not* yet proved is the positive: no non-automotive profile has been built. The core does
still carry automotive vocabulary in places a reviewer should note — `road_friction_coefficient`,
`tyre_wear_index` in `SLOW_STATE_FIELDS`, `legal_speed_limit_kmh` in `ShieldSettings`. Those are
defensible as the *configured* domain rather than a hardcoded one, but the argument is currently
made in prose, not by a second working profile.

---

## A-2 — A 10 ms end-to-end budget at 20 Hz is achievable in CPython

**Assumption.** The hot-path budget — fast UKF < 1 ms, Trust < 2 ms, Core-A < 3 ms, Core-B
intercept < 5 ms, RCM hot < 1 ms, **< 10 ms end-to-end** within a 50 ms tick — is achievable in
CPython with non-blocking audit I/O.

**Impact if wrong.** The architecture survives; only the numbers move. This is a reporting problem,
not a redesign: the layer decomposition, the gate independence and the invariants are unaffected by
the pipeline being slower than hoped. It must be reported honestly against the software target,
never against the hardware bound.

**How to verify.** Phase 2 measurement, once L1 and L2 exist and a tick can actually be timed.

**Status after Phase 1: OPEN.** Nothing has been measured, because there is no pipeline to measure.
Phase 1's contribution is to remove the foundation-level reasons the budget would be missed:

- The audit sink is a bounded queue plus a background writer thread, so `emit` costs a queue append
  and every syscall happens off the tick (SI-8).
- Diagnostic logging attaches only a `QueueHandler`; a `QueueListener` on a background thread owns
  every handler that performs I/O.
- Configuration is frozen after load and read as plain attributes — O(1), allocation-free.
- Contract records are frozen, slotted dataclasses that validate once at construction, so no hop
  re-validates.
- No units library on the hot path: `NewType` is erased at runtime (ADR-0007).

**Standing honesty obligation.** The **1.25 µs Core-B intercept figure is an analytical hardware
WCET bound** (AbsInt aiT, 500 MHz, 627 cycles). It is not measurable by a Python prototype and must
never be presented as a measurement. Every latency claim carries its label: hardware-analytical or
software-measured.

---

## A-3 — Append-only JSONL, one file per run, is adequate prototype evidence

**Assumption.** An append-only JSONL file per run is adequate as certification evidence at
prototype stage.

**Impact if wrong.** Real certification may require a database, a cryptographically signed log, or
both. The migration is contained — the `EventSink` port is the seam — but the evidence already
gathered would have to be re-attested.

**How to verify.** Phase 9 evidence review, against whatever the certification body actually asks
for.

**Status after Phase 1: HOLDING.** Implemented and exercised. `src/astra/observability/audit.py`
provides `JsonlAuditSink`; the record types are in `src/astra/contracts/audit.py` (`AuditEvent`,
`DecisionRecord`, `ExecutionOutcome`), each schema-versioned via `AUDIT_SCHEMA_VERSION`.

Three properties are already true, and they are the ones the assumption rests on. An `AuditEvent`
validates that its payload is JSON-serialisable *at construction*, so an event that could not
become evidence fails when it is built rather than when the log is written. `DecisionRecord.to_json`
is built from ordered dictionaries of JSON scalars only, so parse-and-re-serialise is
byte-identical — the round-trip guarantee holds by construction. And queue overflow is *counted*:
`JsonlAuditSink.dropped_records` is non-zero if any record was lost, so an incomplete evidence
archive announces itself. An archive that is silently incomplete is worse than one that admits a
gap, because only the second can be assessed honestly.

What remains unproved is adequacy as *certification* evidence, which is not an engineering question
and cannot be settled inside the repository. There is no signing, no tamper-proofing beyond
append-only, and no external attestation. `certification.toml` sets `fsync_each_record = true`
so evidence survives an abnormal termination.

---

## A-4 — Safety thresholds have no defensible default

**Assumption.** `θ1`, `θ2`, `θ3`, `ε`, `γ`, `τ`, `δ_CDI` and the Hard Safety Shield's bounds have
**no defensible default** and must be required configuration.

**Impact if wrong** — that is, if defaults had been shipped. A run could silently proceed under
invented safety thresholds, and the numbers it produced would enter a report carrying the authority
of a configured system. This is the failure mode the project's honesty boundaries exist to prevent,
and it is undetectable after the fact unless the configuration is part of the evidence.

**How to verify.** Phase 1 test: a missing threshold must cause a startup failure.

### Status after Phase 1: ENFORCED — mechanically, not by convention

This assumption is no longer an assumption in the ordinary sense. It has been converted into a
mechanism that cannot be bypassed silently, in three places that reinforce each other.

**1. The schema declares them required.** In `src/astra/config/schema.py`, each safety threshold is
a field with no default:

```python
class EstimationSettings(_Section):
    fast_rate_hz: PositiveFloat = 20.0  # defaulted — operational
    slow_rate_hz: PositiveFloat = 1.0  # defaulted — operational
    innovation_gate_gamma: PositiveFloat  # NO DEFAULT — safety threshold


class GateSettings(_Section):
    significance_epsilon: UnitInterval  # NO DEFAULT
    mmd_window: PositiveInt = 100  # defaulted — operational
    mmd_threshold: NonNegativeFloat  # NO DEFAULT
```

The same pattern holds for `TrustSettings.coverage_level`, all three fields of `ShieldSettings`
(`legal_speed_limit_kmh`, `friction_margin`, `minimum_stopping_distance_m` — *"a shield running on
invented bounds is worse than no shield: it produces PASS verdicts that carry the authority of a
deterministic check"*), the five `FailSafeSettings` fields, and
`ArbitrationSettings.trust_threshold_tau` / `divergence_limit_delta`.

Two further guards sit alongside. Every section is `frozen=True, extra="forbid"`, so a typo in a
TOML key is a startup error instead of a silently ignored line — a misspelled threshold that is
quietly dropped would leave the system running on a value the file does not specify. And
`FailSafeSettings` validates `θ1 < θ2 < θ3` strictly, because out-of-order thresholds would make a
state unreachable and silently remove a step from the graduated response.

**2. The packaged defaults omit them.** `config/astra.defaults.toml` contains no `ε`, no `γ`, no
`τ`, no `δ_CDI`, no `θ` and no shield bound. Each absence is marked in the file itself
(`# innovation_gate_gamma: intentionally absent — safety threshold (A-4)`), so the omission reads
as a decision rather than an oversight. The file's own test for what may be defaulted: *"if this
value were wrong, would the consequence be an inconvenience or an unsound safety claim?"*

`staleness_budget_ms = 50.0` is the one boundary case, and it is defended: 50 ms is stated
explicitly in FR1 as a requirement, rather than left to be determined empirically.

**3. `certification.toml` ships incomplete, and loading it fails.** Every threshold in
`config/environments/certification.toml` is commented out, under a banner reading
`THIS FILE IS INCOMPLETE BY DESIGN. LOADING IT WILL FAIL UNTIL A SAFETY ENGINEER SUPPLIES THE
VALUES BELOW.` The behaviour is verifiable in one command:

```console
$ uv run astra config show --environment certification
configuration could not be resolved: [ASTRA-CFG-001] configuration for environment
'certification' is invalid; a required safety threshold may be missing (see assumption A-4)
  - estimation.innovation_gate_gamma: Field required
  - trust.coverage_level: Field required
  - gate.significance_epsilon: Field required
  - gate.mmd_threshold: Field required
  - shield.legal_speed_limit_kmh: Field required
  - shield.friction_margin: Field required
  - shield.minimum_stopping_distance_m: Field required
  - failsafe.ood_threshold_degraded: Field required
  - failsafe.ood_threshold_limp: Field required
  - failsafe.ood_threshold_halt: Field required
  - failsafe.degraded_speed_cap_kmh: Field required
  - failsafe.limp_speed_cap_kmh: Field required
  - arbitration.trust_threshold_tau: Field required
  - arbitration.divergence_limit_delta: Field required
$ echo $?
1
```

Fourteen required fields, every one of them a safety threshold, every one of them named.
`ConfigurationError` carries `SafetyDisposition.FAIL_FAST`, so the run does not start — and the
behaviour is exercised by the test suite rather than merely documented.

`development.toml` and `simulation.toml` do carry values, and both open with a banner —
`PROVISIONAL VALUES. NOT CERTIFIED. NOT EVIDENCE.` — stating that no number produced under them may
be reported as a result. The configuration hash stamped on every decision record is the mechanism
that keeps a development number distinguishable from a certified one after the fact.

**Verify these claims yourself:** read `src/astra/config/schema.py` (the field declarations),
`config/astra.defaults.toml` (the omissions) and `config/environments/certification.toml` (the
commented-out block), then run the command above.

**What is still assumed.** Only the underlying judgement: that these particular parameters cannot
be given defensible defaults from the literature. The source documents assign them no values, and
the reasoning is that they can only be fixed empirically once the pipeline runs against real
scenarios. That judgement is now load-bearing in the opposite direction — a certification run
cannot start until a safety engineer supplies them *and* records, per the file's instructions, the
value chosen, the runs or analysis it came from, and who approved it.

---

## A-5 — A single random `RunId` is sufficient for byte-comparable replay

**Assumption.** Determinism through exactly one random identifier — `RunId`, generated once per run
and injectable for replay — is sufficient to make replayed runs byte-comparable.

**Impact if wrong.** Replay diffing is weakened. If it turns out insufficient, PPO and PINN seeding
must also be brought under control, which is additional work in Phase 4 rather than a redesign.

**How to verify.** Phase 2 replay test on the L1/L2 path; extend to RNG seeding in Phase 4.

**Status after Phase 1: HOLDING, partially.** The identifier discipline is built and enforced by
construction. `src/astra/kernel/identifiers.py` makes `RunId.generate()` the only non-deterministic
identifier in the system; `TickId`, `EventId`, `ComponentId` and `ProfileId` are pure functions of
run, tick and sequence. The clock is injected, so no timestamp is a hidden source of variation
either (ADR-0010), and `tests/conftest.py` is built on `ManualClock` and a fixed run identifier for
the same reason.

The unverified half is that this is *sufficient*. No replay harness exists yet — it is Phase 2
work — so nothing has been diffed. Known future sources of non-determinism that a single `RunId`
does not address: PPO's policy sampling and PyTorch's RNG (Phase 4), dictionary iteration order in
any code that grows a set, and floating-point non-associativity if any computation is ever
parallelised. The first is explicitly anticipated by the assumption's own text; the other two are
not, and should be watched.

---

## A-6 — Python 3.12 is supported by the ML stack at Phase 4

**Assumption.** PyTorch, Stable-Baselines3 and FilterPy support Python 3.12 by the time Phase 4
starts.

**Impact if wrong.** The project drops to 3.11, which costs PEP 695 generics and `typing.override`
— a syntax migration in the contracts and ports, not an architectural change. The core is
otherwise unaffected.

**How to verify.** A Phase 4 dependency spike — **do this early**, before the code that would have
to be rewritten exists.

**Status after Phase 1: OPEN, with an early-warning mechanism running.** No ML dependency is
installed, so nothing is confirmed. What Phase 1 added is a tripwire: `.github/workflows/ci.yml`
runs the full quality gate on a `["3.12", "3.13"]` matrix with `fail-fast: false`, so a
version-specific problem is visible as a version-specific failure rather than a general one.

The floor itself is committed in three places (`requires-python = ">=3.12"`,
`target-version = "py312"`, `python_version = "3.12"`) and used non-trivially: PEP 695 type
parameters in `SensorSample[PayloadT]` and `FusedSensorFrame[PayloadT]`, PEP 695 `type` alias
statements throughout the configuration schema, and `typing.override` in the kernel and
observability packages. Reverting to 3.11 is bounded but not free.

The spike is still owed. It is one `uv add --dry-run torch stable-baselines3 filterpy` away.

---

## A-7 — The repository stays private until the filing is confirmed

**Assumption.** The repository remains private and proprietary until the patent filing status is
confirmed.

**Impact if wrong.** Public disclosure before filing can prejudice patentability in jurisdictions
without a grace period. This is not recoverable by engineering.

**How to verify.** Confirm with whoever handles the filing.

**Status after Phase 1: EXTERNAL — unresolved, with the engineering side done.** Everything the
repository can do about it, it does: `LICENSE` is all-rights-reserved with an explicit patent
notice; `NOTICE` carries the confidentiality statement; `README.md` opens with a
do-not-distribute banner; `pyproject.toml` carries `"Private :: Do Not Upload"` as a hard guard
against accidental PyPI publication; and `detect-private-key` runs on every commit. There is no
`[project.urls]` pointing at a public package index.

None of that resolves the assumption. It needs a person, not a commit. Until then: no external
demo, no publication, no public repository. See [ADR-0014](adr/0014-proprietary-licence-pending-patent.md).

---

## A-8 — The CARLA/interpreter incompatibility is resolvable without changing the core

**Assumption.** Reconciliation finding R-6 — the documents mandate Python 3.10+ *and* CARLA 0.9.14,
whose official Python client ships for 2.7/3.6/3.7/3.8 only — is resolvable by one of three routes
without changing the core: (a) upgrade to CARLA 0.9.15+/0.10.x with newer interpreter support;
(b) a community-built egg or wheel for 3.10+; (c) run the CARLA client as a Python 3.8 sidecar
bridged to the 3.12 core.

**Impact if wrong.** Route (c) becomes mandatory, adding an IPC hop and its latency to every tick
that touches the simulator. That eats into the 10 ms budget (A-2) and complicates the timing
argument, but does not change the architecture.

**How to verify.** Phase 2 spike — **do this first**, before any adapter code is written. This is
the single most consequential unresolved technical risk in the project (risk RK-1).

**Status after the Phase 2 spike: RESOLVED via route (a), but only partly evidenced.**

The assumption held, and more cheaply than any of its three routes anticipated: the incompatibility
itself expired. CARLA **0.9.16**, released 2025-09-16 — after ADR-0003 was written — publishes
official `cp310`/`cp311`/`cp312` wheels to PyPI. Verified against
`https://pypi.org/pypi/carla/json` on 2026-07-29: `0.9.14` carries `cp27`/`cp37`/`cp38` only,
`0.9.16` carries `cp310`/`cp311`/`cp312`. No sidecar, no IPC hop, no unofficial binary, and the
10 ms budget is untouched. Recorded in
[`adr/0015-carla-interpreter-strategy.md`](adr/0015-carla-interpreter-strategy.md).

**Update, 5 August 2026 — the install half is now verified.** Run on WSL2 Ubuntu into a throwaway
CPython 3.12.13 environment, deliberately isolated so nothing reaches the project venv or the
lockfile:

```bash
uv venv --python 3.12 ~/carlacheck
uv pip install --python ~/carlacheck/bin/python carla==0.9.16
~/carlacheck/bin/python -c "import carla; carla.Client('localhost', 2000)"
```

`carla==0.9.16` resolved and installed as a single package with no dependency tree, imported
cleanly, and exposes every symbol the adapter design needs: `Client`, `World`, `Vehicle`, `Sensor`,
`Transform`, `Location`, `Rotation`, `VehicleControl`, `WorldSettings`. A `Client` constructs and
`get_server_version()` raises `RuntimeError` with no server listening — which is the correct
failure and confirms the client is live rather than inert.

**So the interpreter risk is closed.** No sidecar, no IPC hop, no unofficial binary. What remains
unverified is the *connection* half, which needs a running simulator and therefore the Linux GPU
host of Phase 7 — a hardware dependency, not a compatibility one.

**One thing still stops this being fully "closed".**

*A new constraint replaced the old one.* CARLA has no macOS build and its wheels carry no `macosx`
tag, so `pip install carla` fails on Darwin regardless of interpreter. Simulator work needs a Linux
x86-64 host with an NVIDIA GPU. This does not block L1, L2 or the replay spine — all three are
developed and tested against in-process fakes — but it does mean the adapter cannot be exercised at
all on an Apple-Silicon development machine, which makes "build against fakes first" a requirement
rather than a preference.

**What Phase 1 guaranteed, and still does.**
What Phase 1 guarantees is that whichever route is taken, the blast radius is one adapter: the
`simulator-isolation` contract in `.importlinter` forbids *any* module in `astra` from importing
`carla`, with an architecture test (`test_no_module_in_the_core_imports_the_simulator_client`)
walking the AST as a second check. The `SensorSource` port in `src/astra/ports/pipeline.py` is a
structural `Protocol`, so the adapter implements it without the core learning that CARLA exists.

The contract file notes that the eventual adapter will be the single permitted exception, added to
the contract's exclusions when it is written.

---

## A-9 — MPC candidate scoring fits behind the `StatisticalGate` port

**Assumption.** The "MPC candidate scoring" that the documents name inside L6 but never specify can
be treated as a sub-stage behind the same `StatisticalGate` port as the ICP gate.

**Impact if wrong.** It needs its own port and possibly its own layer number, which changes the
consolidated L1–L9 numbering that ADR-0001 fixed and that `LayerId` encodes.

**How to verify.** Clarify with Dr. Chaitra R. This is reconciliation finding R-8, flagged as a
documentation gap in the source corpus rather than a design choice.

**Status after Phase 1: EXTERNAL — unresolved, cost of being wrong currently low.** The
`StatisticalGate` port exists and L6 is a single layer in `LayerId`. Because no L6 logic has been
written, changing the decision today costs an enum member and a port; after Phase 4 it would cost
a refactor of the gate itself and every record that references its layer identifier. Worth
resolving before Phase 4 starts.

---

## A-10 — Explainability means decision provenance, not model-internal attribution

**Assumption.** The project-level objective "explain every AI decision" is satisfied by *decision
provenance* — for each tick, which gate fired, on what evidence, under which calibration profile,
at which configuration hash — and not by SHAP/LIME-style feature attribution. This is
reconciliation finding R-7: no XAI layer appears in any of the four source documents.

**Impact if wrong.** If stakeholders expect model-internal attribution, a new layer is needed, with
its own port, its own contracts and its own place in the pipeline.

**How to verify.** Confirm with the project owner.

**Status after Phase 1: EXTERNAL — unresolved, but the provenance half is built.**
`DecisionRecord` in `src/astra/contracts/audit.py` is the explainability unit: for one tick it ties
together frame health, the state estimate, the Trust Index, the proposal, the twin's prediction,
every gate verdict, the fail-safe FSM snapshot, the arbitration decision, the issued command and
the configuration hash under which all of it happened. That answers *"why did the vehicle do that,
on what evidence, under which calibration"* without any model-internal attribution, and it directly
satisfies NFR8.

Model-internal attribution is explicitly **not** claimed anywhere in the codebase or the
documentation, which is the correct posture until the expectation is confirmed. If it is later
required, `DecisionRecord` is the right place to hang it and the schema version is the mechanism
for evolving it.

---

## Reviewing this register

An assumption's status is only useful if it is maintained. Two rules:

1. **When a phase closes, re-read this file.** Any assumption whose verification step belonged to
   that phase is either resolved or has slipped; both need saying.
2. **Promote before you rely.** If new code depends on an assumption being true, either verify it
   or record in the ADR that the dependency was taken knowingly. Silently building on an OPEN
   assumption is how an unproved belief becomes load-bearing.

Related: [`CONVENTIONS.md`](CONVENTIONS.md) for the standards these assumptions interact with, and
[`adr/`](adr/) for the decisions taken under them.
