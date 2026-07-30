# ASTRA — Separation Invariants

The safety argument, invariant by invariant, with the enforcement that exists **in the code as
built**.

Objective 1 of the project is *"a nine-layer pipeline with formally defined separation invariants
between layers."* These are those invariants. The Prototype & Demo Plan is explicit about what
"formally defined" has to mean in practice — *"verify this with a code-level check (no import, no
shared memory region, no queue), not just a comment"* — so every entry below names the artefact
doing the checking, and says plainly where no artefact does.

The authoritative text lives in `src/astra/invariants/catalogue.py` as a frozen tuple of
`SeparationInvariant` values. This document explains each one; the catalogue *is* each one. If
the two ever disagree, the catalogue is right and this document is stale.

---

## How enforcement is classified

`EnforcementKind` in `src/astra/invariants/catalogue.py` distinguishes what is actually checked
from what is merely asserted:

| Kind | Meaning |
|---|---|
| `STATIC` | Enforced at build time — an import contract, or a type that makes the violation unrepresentable. Cannot be violated by a running system. |
| `RUNTIME` | Enforced by a guard that raises when the violation occurs. |
| `TEST` | Enforced by an assertion in the test suite, which fails the build. |
| `REVIEW` | **Not yet mechanically enforced.** Depends on human review. |

`SeparationInvariant.is_mechanically_enforced` returns `False` for exactly `REVIEW`, and
`tests/unit/test_invariants.py::test_mechanical_enforcement_is_false_exactly_for_review_only_invariants`
asserts that correspondence, so an invariant cannot be quietly downgraded and keep claiming a
guarantee.

### Current status

| Invariant | Kind | Mechanically enforced today? |
|---|---|---|
| SI-1 Sensor opacity | `STATIC` | Partially — see §SI-1 |
| SI-2 Single state source | `STATIC` | Partially — see §SI-2 |
| SI-3 Unconditional veto | `RUNTIME` | Yes, fully |
| SI-4 Trust isolation | `STATIC` | Yes, fully |
| SI-5 One-way core channel | `STATIC` | Partially — see §SI-5 |
| SI-6 Veto-rate exclusion | `REVIEW` | **No.** Review-only until Phase 4 |
| SI-7 Sole actuation authority | `RUNTIME` | Yes, fully |
| SI-8 Timing-domain separation | `TEST` | Partially — see §SI-8 |
| SI-9 Independent calibration validation | `STATIC` | Partially — see §SI-9 |
| SI-10 Evidence non-influence | `STATIC` | Yes, at the boundary that exists today |

**Nine of ten are mechanically enforced. SI-6 is not: it is `REVIEW` until Phase 4, and it says
so in the catalogue, in `astra invariants list`, and here.**

Several of the mechanically enforced entries are marked "partially" above. That is not a
weakening of the classification — each is genuinely checked by a machine today — but the scope of
the check is narrower than the scope of the invariant, because the artefact that would complete
it does not exist yet: the layer packages `astra.layers.*` for SI-1, SI-2 and SI-5, a measured
tick for SI-8, and a signing scheme for SI-9. Each section below states its gap and names the
phase that closes it. Reading only the "Kind" column would over-report the guarantee, which is
why the third column exists.

---

## SI-1 — Sensor opacity

**Statement.** No layer above L2 reads a raw sensor payload. L9 may read reliability metadata
only.

**Rationale.** If a downstream layer could re-read the sensors it would become a second,
uncontrolled state source, and the pipeline would no longer have a single auditable notion of
what the world looked like at a tick.

**Consequence if violated.** State provenance becomes ambiguous; two layers can disagree about
the world with no way to say which was right.

**Enforcement as built — `STATIC`.**

1. **The payload is a type parameter.** `SensorSample[PayloadT]` and `FusedSensorFrame[PayloadT]`
   in `src/astra/contracts/sensing.py` are PEP 695 generics. Health, quality, staleness and
   provenance are architectural and concrete; the shape of a LiDAR return is not. A layer written
   against `FusedSensorFrame[object]` — which is exactly what `StateEstimator.update_fast` in
   `src/astra/ports/pipeline.py` declares — has a payload it cannot interpret. The asymmetry
   between metadata and payload is the mechanism.
2. **An import contract.** `.importlinter`'s `si-1-sensor-opacity` contract forbids
   `astra.kernel` and `astra.invariants` from importing `astra.contracts.sensing`.

**The honest gap.** That import contract is *narrower than the invariant*. It states that the
kernel and the invariant catalogue must remain valid without any notion of a sensor — which is
true and worth enforcing — but it does not yet forbid L3…L9 from importing the sensing
contracts, because `astra.layers.*` does not exist. The contract's `source_modules` list grows to
name each layer above L2 as those packages land in Phases 2–6. Until then, SI-1's coverage of
the layers themselves rests on the generic payload and on review.

---

## SI-2 — Single state source

**Statement.** Every layer obtains state exclusively from L2's estimates; no layer re-derives
state from sensors.

**Rationale.** One state source is what makes the three gates' inputs comparable and the audit
record joinable. It is also, acknowledged openly, the system's single common-cause channel.

**Consequence if violated.** Gate independence is weakened in an undocumented way: gates would
differ because their *inputs* differed, not because their *failure modes* differ — which is a
different and much weaker property than the one the architecture claims.

**Enforcement as built — `STATIC`.**

1. **`StateEstimator` is the only port that returns a state estimate.** In
   `src/astra/ports/pipeline.py`, `update_fast` and `update_slow` are the sole methods returning
   `FastStateEstimate` / `SlowStateEstimate`; every other port takes them as parameters. A layer
   cannot obtain an estimate except by being handed one.
2. **The layering contract** in `.importlinter` keeps `contracts` below `ports`, so no port can
   reach around the estimator into a lower-level construction path.

**The honest gap.** Same shape as SI-1. Nothing today can import `astra.contracts.sensing` and
build its own filter, because nothing today is a layer. The enforceable statement grows with the
layer packages in Phase 2.

**This invariant is the reason the residual weakness in §"Residual common-cause weakness" below
exists.** It is not an accident of the design; it is the price of the design, paid deliberately.

---

## SI-3 — Unconditional veto

**Statement.** No PASS from any component can suppress a VETO. Aggregation is fail-closed, and an
empty verdict set is a VETO.

**Rationale.** The Hard Safety Shield's authority is only meaningful if it is unconditional. A
vote, a weighted score or a majority would each be a mechanism by which one gate cancels another.

**Consequence if violated.** The deterministic safety bound becomes advisory, and the strongest
claim in the safety argument is void.

**Enforcement as built — `RUNTIME`, and fully.** Three layers of it:

1. **`Verdict.merge`** in `src/astra/kernel/enums.py` is the executable form. It returns `PASS`
   only if the input is non-empty and every element is `PASS`; otherwise `VETO`. `merge(())` is
   `VETO` — a command that no gate inspected has not been cleared, it has been missed. This
   mirrors the FMEA mitigation for a silent Core-B crash, where the crossbar defaults to VETO on
   a missed heartbeat.
2. **`SafetyVerdict.aggregate`** in `src/astra/contracts/assurance.py` is a *property* computed
   through `Verdict.merge`. There is no constructor argument for the aggregate and no field to
   override it, so a contradictory aggregate has nowhere to live.
   `tests/architecture/test_invariants.py::test_the_safety_verdict_carries_only_the_tick_and_the_gate_verdicts`
   asserts the field set is exactly `{tick, gate_verdicts}`, which is what stops an escape hatch
   being added later.
3. **`guard_verdict_aggregation`** in `src/astra/invariants/catalogue.py` re-derives the merge
   from the components and raises `InvariantViolationError` if the supplied aggregate disagrees.
   Under correct operation it never fires. That is the point: if it ever does, something computed
   an aggregate by a path other than `Verdict.merge`, and the property can no longer be assumed.

Tested in `tests/unit/test_enums.py`, `tests/unit/test_contracts_assurance.py`,
`tests/unit/test_invariants.py` and `tests/architecture/test_invariants.py`, including the
property that a single VETO survives any number of PASSes.

---

## SI-4 — Trust isolation

**Statement.** The Trust Index must not participate in Core-B's binary verdict. It flows to L4 for
monitoring and L9 for routing only.

**Rationale.** A gate that consulted a confidence score would fail whenever the score was wrong,
coupling three supposedly independent gates to one estimator.

**Consequence if violated.** Gate independence is lost; a single miscalibrated estimator can pass
a bad command.

**Enforcement as built — `STATIC`, and fully.**

1. **`SafetyVerdict` has no trust field and no way to acquire one.** Two fields, `tick` and
   `gate_verdicts`, both asserted.
2. **No gate port accepts a `TrustAssessment`.** `StatisticalGate.evaluate`,
   `PhysicalAdmissibilityChecker.evaluate` and `DeterministicShield.evaluate` in
   `src/astra/ports/pipeline.py` take proposals, predictions and state — never trust.
   `tests/architecture/test_invariants.py` renders each gate protocol's type annotations and
   asserts that neither the type name nor any parameter whose name mentions trust appears.
3. **The positive half is asserted too.** The same test module checks that `TrustAssessment`
   *does* reach `CommandProposer.propose` (L4) and `CalibrationArbiter.issue` (L9), so the
   invariant cannot be satisfied by simply deleting the Trust Index from the system.

This invariant and SI-5 are what resolve the apparent Core-A/Core-B isolation conflict recorded
as finding R-9: L3 sits in the `SHARED` domain, Core-A may read the Trust Index, Core-B may not
use it in a verdict, and Core-A still cannot see anything Core-B produced. Two invariants,
neither violated.

---

## SI-5 — One-way core channel

**Statement.** Core-A may write `π_prop` to Core-B; it may not read any Core-B artefact —
verdict, FSM state, calibration table or quantile.

**Rationale.** The proposer is untrusted and is trained by optimisation. Anything it can observe,
it can learn to exploit; a proposer that can see the gate can learn to slip past it.

**Consequence if violated.** The learned policy can adapt to the safety monitor, which converts
defence in depth into a single adversarial optimisation problem.

**Enforcement as built — `STATIC`.**

1. **The port signature.** `CommandProposer.propose` in `src/astra/ports/pipeline.py` takes
   `tick`, `state` and `trust`, and returns a `ProposedCommand`. There is no parameter for a
   `SafetyVerdict`, a `FailSafeSnapshot`, a `CalibrationProfile` or a quantile. The one-way
   channel is expressed in the type, not in the wiring — which matters because wiring is
   changed far more casually than a signature.
2. **Provenance is checked.** `ProposedCommand.__post_init__` in
   `src/astra/contracts/actuation.py` raises `ContractViolationError` unless its `source`
   component's layer is `L4_CORE_A_CMDP`, so a Core-B layer cannot manufacture a proposal and
   have the evidence log misrepresent the trust boundary.

**The honest gap.** The catalogue's mechanism string names an "import-linter forbidden contract",
and that contract is **present but commented out** in `.importlinter`. It names
`astra.layers.l4_proposer` as the source and `l5_twin`, `l6_statistical_gate`, `l7_shield` and
`l8_failsafe` as forbidden — modules that do not exist, so import-linter would fail on unknown
modules if it were active. It was written now and commented rather than omitted and forgotten;
activating it is deleting the comment markers, which becomes possible in **Phase 4**, when
`l4_proposer` and `l5_twin` land. `l7_shield` and `l8_failsafe` arrive earlier, in Phase 3, along
with the one-way queue topology and its runtime guard.

---

## SI-6 — Veto-rate exclusion

**Statement.** Core-B's veto rate may be logged as a diagnostic but must never enter Core-A's
reward or constraint computation.

**Rationale.** Rewarding a low veto rate trains the proposer to avoid *detection* rather than to
be *safe*. The two are indistinguishable to the optimiser and opposite in effect.

**Consequence if violated.** The proposer optimises against its own safety monitor.

**Enforcement as built — `REVIEW`. This invariant is not mechanically enforced.**

There is no code today that could enforce it, because there is no reward computation to inspect:
Core-A arrives in Phase 4. `CommandProposer.propose` accepting no Core-B artefact is *related* —
it means veto statistics cannot reach the proposer through the inference path — but SI-6 is
about the **training signal**, which is a different code path entirely and one that does not
exist yet. Claiming the port signature enforces SI-6 would be exactly the kind of overstatement
the catalogue's `EnforcementKind` was introduced to prevent.

The catalogue records the mechanism as *"Phase 4: test asserting the training signal's field set
excludes veto statistics"*. Until that test exists and the entry is upgraded to
`EnforcementKind.TEST`, the honest statement is: **one of the ten separation invariants rests on
human review.** Upgrading it is a named Phase 4 exit criterion in [`ROADMAP.md`](ROADMAP.md).

---

## SI-7 — Sole actuation authority

**Statement.** Only L9 may emit a command to the actuation sink.

**Rationale.** A single issuer is what makes the actuation boundary a boundary. With two, no
record could say which component moved the vehicle.

**Consequence if violated.** The governance pipeline can be bypassed entirely; the architecture's
central claim no longer describes the running system.

**Enforcement as built — `RUNTIME`, and fully.** Three complementary mechanisms:

1. **`IssuedCommand.__post_init__`** in `src/astra/contracts/actuation.py` raises
   `InvariantViolationError`, naming SI-7 and the offending layer, unless the issuer's layer is
   `L9_RCM`. It additionally refuses any command that is not admissible in its own actuation
   space — an out-of-bounds command must never reach an actuator, whatever produced it. Together
   these make "something other than the arbitrator issued something inadmissible" an
   unconstructable state rather than a bug to be found in review.
2. **`guard_actuation_authority`** in `src/astra/invariants/catalogue.py` performs the same check
   *before* a record is built, for the call sites that decide first and construct later — an
   adapter about to write to a bus, a harness checking a wiring change. The duplication is
   deliberate: an invariant enforced in only one place is enforced until someone adds a second
   place.
3. **The type of the boundary.** `ActuationSink.apply` in `src/astra/ports/infrastructure.py`
   accepts only an `IssuedCommand`, so authority is carried to the edge of the process by the
   type system rather than by convention.

`tests/architecture/test_invariants.py` parametrises over every non-L9 member of `LayerId` and
asserts each is refused, and separately asserts that exactly one layer in the enumeration has
actuation authority — so adding a tenth layer with issuing rights fails the build.

---

## SI-8 — Timing-domain separation

**Statement.** Cold-path work must never block a hot-path tick.

**Rationale.** The knowledge-base search and evidence writing are unbounded in time. A tick that
waits for either is late, and a late verdict about a vehicle that has already moved is not a
verdict.

**Consequence if violated.** The end-to-end latency budget is violated, and control degrades
under exactly the load that matters.

**Enforcement as built — `TEST`.**

1. **The port contract states it.** `EventSink.emit` and `EventSink.record_decision` in
   `src/astra/ports/infrastructure.py` are documented "**must not block**", with the reason
   (SI-8, the 10 ms budget) given where an implementer will read it. `flush` is documented as
   blocking and therefore never called from within a tick.
2. **The implementation honours it.** `JsonlAuditSink` in `src/astra/observability/audit.py`
   serialises on the calling thread — cheap, CPU-bound, and detects an unserialisable record at
   its origin — then `put_nowait`s onto a bounded queue. Every syscall in the class happens on a
   background daemon thread. Diagnostic logging does the same thing with a `QueueHandler` and a
   `QueueListener` in `src/astra/observability/logging.py`.
3. **The bound is a design choice, and overflow is counted.** An unbounded queue converts a
   stalled disk into unbounded memory growth, which on a real-time system is the worse failure.
   `JsonlAuditSink.dropped_records` is non-zero if any record was lost, so a run's evidence can
   be reported as incomplete rather than being silently incomplete.
   `tests/unit/test_audit.py::test_a_record_that_cannot_be_queued_is_counted_rather_than_silently_discarded`
   drives `emit` against a queue that is already at its bound and nothing is draining, and
   asserts that every call returned and that each overflow was counted;
   `test_the_records_that_did_fit_are_still_written_when_others_were_dropped` asserts the
   surviving records still reach the file.

**The honest gap.** What exists today proves the sink does not block *on a full queue*. It does
not measure tick latency, because there is no tick. The catalogue's mechanism string names a
**Phase 6 latency test** as the completion of this enforcement, and it is a Phase 6 exit
criterion.

---

## SI-9 — Independent calibration validation

**Statement.** Core-B independently validates any calibration table — signed checksum plus
quantile monotonicity and range — before activation, even though RCM proposed it.

**Rationale.** A table that is not monotonic can map a *higher* non-conformity score to a *lower*
rejection threshold. That is the precise shape a calibration-poisoning attack takes, and the
component that proposes a table cannot be the only one that checks it.

**Consequence if violated.** The statistical gate can be silently disabled by a corrupt or
hostile calibration table.

**Enforcement as built — `STATIC`.**

1. **Monotonicity is checked at construction.** `CalibrationProfile.__post_init__` in
   `src/astra/contracts/governance.py` runs `require_non_decreasing` from
   `src/astra/kernel/validation.py` over the quantile table and re-binds the validated tuple. A
   profile carrying a non-monotonic quantile table cannot be constructed at all, so the
   poisoning shape this invariant targets is unrepresentable rather than merely forbidden.
2. **Range and structure are checked with it.** The centroid must be `RCS_DIMENSION`-dimensional
   with every component in [0, 1]; the covariance must match that dimension; coverage level and
   validation fraction must be probabilities; max speed must be non-negative; the checksum and
   platform must be non-empty; and the certification dates must be timezone-aware with expiry
   strictly after certification.
3. **The hard admissibility rule is written once.** `is_candidate_admissible` encodes
   `T(c) ≥ τ AND val(c) == 1` as a conjunction with no scoring escape hatch: validity is a veto,
   not a weight, so no trust score however high rescues a candidate that failed validation.

**The honest gap.** The **checksum is stored and required to be non-empty; it is not verified.**
Verification requires a signing scheme and a key, and it lands with L9 in Phase 6. Today SI-9's
monotonicity half is enforced by construction and its cryptographic half is not. Independence in
the strict sense — a *Core-B* component re-validating a table that *L9* proposed — also requires
both components to exist, which is Phase 6.

---

## SI-10 — Evidence non-influence

**Statement.** Evidence logged during safe exploration must not modify the live safety argument;
it feeds only the offline certification pipeline.

**Rationale.** Exploration evidence is uncertified by definition. Letting it widen a live
acceptance band would let the system certify itself from its own unreviewed behaviour.

**Consequence if violated.** The system can bootstrap its way out of its certified envelope
without human review.

**Enforcement as built — `STATIC`.** `.importlinter`'s `si-10-evidence-non-influence` contract
forbids `astra.contracts` and `astra.ports` from importing `astra.observability`. The gates are
written against the contracts and the ports; the evidence machinery is `astra.observability`. So
a gate cannot reach the evidence side of the boundary even transitively, and the direction of
the arrow is enforced rather than described.

This is the invariant whose Phase 1 enforcement is closest to complete, because both sides of
the boundary it constrains already exist. When bounded safe exploration lands in Phase 6, the
contract extends to name the exploration evidence modules explicitly, but the structural
statement does not change.

Note that the layering contract already implies part of this — `observability` sits *above*
`ports` — so the forbidden contract is partly redundant. It is kept because redundancy in a
safety argument is a feature: if the layering were ever relaxed, this contract would still fail.

---

## Residual common-cause weakness

**All three gates consult the same L2 state estimate. That is a genuine common-cause channel, and
it is not eliminated by any invariant in this document.**

It follows directly from SI-2. One state source is what makes the gates' inputs comparable and
the audit record joinable; the price is that a sufficiently wrong `x̂_f` makes the statistical
gate, the physical gate and the deterministic shield wrong *together*, which is precisely the
correlated failure the three-gate architecture exists to avoid elsewhere.

Two mitigations exist. Neither is a fix.

1. **The innovation-sequence Mahalanobis monitor.** L2 raises a sensor-fault flag when the
   innovation's Mahalanobis distance exceeds γ. `InnovationRecord` in
   `src/astra/contracts/estimation.py` carries the residual, the distance and the flag. The
   monitor detects a filter that has begun to *disagree with its measurements*. It does not
   detect a filter that is confidently and consistently wrong.
2. **FB1.** The **applied** command, not the proposed one, re-anchors the filter, closing the gap
   between what the controller asked for and what the vehicle actually did. It does not help if
   the measurements themselves are corrupt.

Two structural choices reduce the blast radius without touching the root cause: the Runtime
Context Signature's `sensor_reliability` component is reliability-weighted upstream, so a
degraded sensor lowers its own contribution rather than dominating the signature; and
`SymmetricMatrix.is_positive_definite` in `src/astra/kernel/matrix.py` treats a singular
covariance as a fault rather than as certainty, so a collapsed filter is reported instead of
being allowed to drive `σ(x)` to zero and unbound the ICP acceptance band.

Removing the common cause would require a second, independently derived state estimate over a
different sensor subset. That is a substantial architectural addition and it is in no phase of
[`ROADMAP.md`](ROADMAP.md). Until it is, **this weakness must be stated in any presentation of
the safety argument, including any that is otherwise favourable.**

---

## Verifying this document against the code

```bash
uv run astra invariants list        # the catalogue, with enforcement status per entry
uv run lint-imports                 # the architecture fitness contracts in .importlinter
uv run pytest tests/architecture    # the invariants expressible as properties of the code
uv run pytest tests/unit/test_invariants.py
```

`astra invariants list` reads the same tuple this document describes, so it is the authoritative
answer to "what does the running system actually claim to enforce".
