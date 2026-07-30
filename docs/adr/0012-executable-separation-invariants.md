# ADR-0012: Separation invariants as executable, machine-checked contracts

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

Objective 1 of this project is *"a nine-layer pipeline with formally defined separation invariants
between layers."* Ten such invariants exist, SI-1 through SI-10, and together they **are** the
safety argument. The claim that three gates fail in structurally independent ways rests on SI-5
(Core-A cannot read Core-B) and SI-4 (the Trust Index does not participate in Core-B's verdict).
The claim that a veto is unconditional rests on SI-3. The claim that only one component can move
the vehicle rests on SI-7.

The Prototype & Demo Plan is unambiguous about what "formally defined" must mean in practice:
*"Verify this with a code-level check (no import, no shared memory region, no queue), not just a
comment."*

The reason for that insistence is not pedantry. An invariant asserted in a design document has three
failure modes, and all three are quiet. It can be violated by code written a year later by someone
who never read the document. It can be *believed* to be enforced when it is not, which is worse than
knowing it is unenforced. And it can erode gradually — one reasonable-looking exception at a time,
each defensible in isolation, until the argument no longer describes the system.

An architecture fitness harness must therefore exist **before** the code it constrains. A violation
discovered after two phases have been built on it is a refactor, not a fix.

## Decision

**Make the invariants a data structure, and check each one by the strongest mechanism available.**

### The catalogue is code

`src/astra/invariants/catalogue.py` defines `SeparationInvariant` as a frozen slotted dataclass —
identifier, title, statement, rationale, consequence, enforcement kind, enforcement description —
and `SEPARATION_INVARIANTS` as the populated catalogue of all ten.

That buys three things prose cannot. The CLI can print it, so an assessor sees the safety argument
and its enforcement status without reading source (`astra invariants list`). The composition root
verifies it at startup, so a malformed or depopulated safety argument stops the run before anything
moves. And the architecture tests assert properties *of the catalogue itself* — that every invariant
has an enforcement mechanism, that none has been silently downgraded — which is what stops the
argument eroding under deadline pressure.

### Enforcement is graded, and the grade is honest

```python
class EnforcementKind(StrEnum):
    STATIC = "STATIC"  # build time: an import contract, or an unrepresentable state
    RUNTIME = "RUNTIME"  # a guard that raises when the violation occurs
    TEST = "TEST"  # an assertion in the suite, which fails the build
    REVIEW = "REVIEW"  # not yet mechanically enforced. Named honestly
```

`REVIEW` is the important member. An invariant marked `REVIEW` is one the codebase does **not**
mechanically enforce, and it says so rather than implying a guarantee it cannot make. Several
invariants are review-only because the components they constrain do not exist yet; each names the
phase that upgrades it. Overstating enforcement would be exactly the kind of unbacked claim the
project's honesty boundaries forbid.

Current state, as `astra invariants list` reports it: **10 declared, 9 mechanically enforced, 1
resting on review only (SI-6).**

| | Invariant | Kind | Mechanism |
|---|---|---|---|
| SI-1 | Sensor opacity | `STATIC` | import-linter forbidden contract; payload behind a type parameter |
| SI-2 | Single state source | `STATIC` | import-linter layering; `StateEstimator` is the only port returning an estimate |
| SI-3 | Unconditional veto | `RUNTIME` | `Verdict.merge`; `SafetyVerdict.aggregate`; `guard_verdict_aggregation` |
| SI-4 | Trust isolation | `STATIC` | `SafetyVerdict` has no trust field; no gate port accepts a `TrustAssessment` |
| SI-5 | One-way core channel | `STATIC` | import-linter contract; `CommandProposer.propose` accepts no Core-B type |
| SI-6 | Veto-rate exclusion | `REVIEW` | Phase 4: test asserting the training signal's field set |
| SI-7 | Sole actuation authority | `RUNTIME` | `IssuedCommand` rejects a non-L9 issuer; `guard_actuation_authority` |
| SI-8 | Timing-domain separation | `TEST` | non-blocking `EventSink`; queue-based audit writer; Phase 6 latency test |
| SI-9 | Independent calibration validation | `STATIC` | `require_non_decreasing` in `CalibrationProfile`; Phase 6 checksum verification |
| SI-10 | Evidence non-influence | `STATIC` | import-linter contract forbidding evidence → gate imports |

### Three enforcement layers, chosen by what each can express

**Import contracts** (`.importlinter`) for anything expressible as an import relationship: the
layering, kernel purity, simulator isolation, SI-1 and SI-10. Five contracts are active. A sixth,
`si-5-one-way-core-channel`, is written and commented out because it names layer modules arriving in
Phases 3 and 4 and import-linter fails on unknown modules — written down rather than
omitted-and-forgotten, activated by deleting the comment markers.

**Types that make the illegal state unrepresentable**, wherever possible. `SafetyVerdict` simply has
no field for the Trust Index, so SI-4 is not a rule about what to pass but a fact about what exists.
`SensorSample[PayloadT]` means a layer that cannot name the payload type cannot read it, which is
SI-1.

**Runtime guards**, for the two invariants whose violation is catastrophic and whose trigger is
dynamic: `guard_verdict_aggregation` (SI-3) and `guard_actuation_authority` (SI-7). Everything else
is caught before the program runs; these two cannot be.

**Architecture tests** as a second, independent check. `tests/architecture/` walks the AST directly
and catches things the import graph does not — a relative import inside the kernel, a `print()`
outside the CLI, a non-SI unit type in a port signature, and the SI-3/SI-4/SI-7 properties above.
`test_every_import_linter_contract_holds` also runs the contracts through import-linter's API from
inside the suite, which is what stops the `python -m importlinter.cli` false pass (ADR-0005) from
silently disabling architecture enforcement.

## Alternatives considered

**Document the invariants and enforce them in code review.** Rejected. It is the status quo the
Demo Plan explicitly rules out, it does not scale past a few modules, and it does not survive a
deadline — the two conditions under which it would matter.

**A bespoke AST-walking script as the primary mechanism.** Rejected as primary: it is code nobody
else maintains and nobody else has debugged, in the position of guarding the safety argument. It is
used as the *secondary* mechanism, where its ability to see things the import graph cannot is worth
the maintenance.

**Runtime guards for everything.** Rejected. A guard that fires at runtime fires *after* the
violating code has shipped, and on a hot path it costs a check per tick. Static enforcement fails at
build time, for free. Runtime guards are used only where static enforcement is impossible.

**Formal verification — TLA+, Alloy, a model checker.** Rejected for Phase 1 as disproportionate.
It would produce a stronger argument about a model, and the gap between the model and the Python
would then need its own argument. The invariants that matter most here are structural (who imports
whom, who can construct what), and those are exactly the ones a fitness harness checks directly on
the real code.

**Mark everything `STATIC` and sort it out later.** Rejected on honesty grounds. An invariant
claimed as enforced and not enforced is worse than one honestly marked `REVIEW`, because the first
stops anyone from looking.

## Consequences

### Positive

- Objective 1's "formally defined" is mechanically true. The invariants fail builds.
- The catalogue is inspectable by a safety assessor without reading source, via
  `astra invariants list --verbose`, complete with each invariant's rationale and the consequence of
  violating it.
- The composition root refuses to start on a malformed safety argument, so a depopulated catalogue
  cannot silently accompany a run.
- Enforcement status is honest and visible. SI-6's `REVIEW` marker is a standing, printed admission
  rather than a footnote.
- The fitness harness exists before the layers it constrains, so the first violation fails at the
  moment it is introduced rather than two phases later.
- Two independent mechanisms (import-linter and the AST tests) cover the layering, so a failure of
  one is caught by the other.

### Negative / accepted trade-offs

- **The catalogue can lie, and nothing can tell.** `EnforcementKind` is a field a human sets.
  Marking SI-6 `STATIC` today would pass every check in the repository. The architecture tests assert
  that each invariant *has* an enforcement mechanism, not that the mechanism *works* — that is a
  structural limit, not an oversight, and it means the honesty of the safety argument ultimately
  rests on review.
- **Only three invariants are enforced by import relationships**, which is the strongest and
  cheapest mechanism. The rest lean on tests, guards and types — all real, all weaker in different
  ways.
- **SI-5's contract is inactive.** The most consequential structural invariant in the architecture —
  the one-way Core-A/Core-B channel — is currently enforced by a port signature and by the fact that
  neither core exists. Its import contract is commented out, and a commented contract is a contract
  that can be forgotten. It is written into `.importlinter` precisely so the reminder is adjacent to
  the enforcement, but nothing fails if Phase 3 lands without uncommenting it.
- **Runtime guards cost something on the hot path**, and SI-3's guard sits on the verdict
  aggregation that runs every tick. Small, but non-zero, and on the path with the tightest budget.
- **The invariants are duplicated in three places** — the catalogue, `.importlinter`, and the
  architecture tests — and nothing keeps the three in sync. Changing an invariant's meaning requires
  finding all three, and forgetting one leaves a contradiction that no check detects.
- **Import contracts constrain imports, not behaviour.** SI-5 says Core-A may not *read* a Core-B
  artefact. A forbidden-import contract prevents the compile-time route; it says nothing about a
  shared memory region, a file, or a value passed in through the composition root. The Demo Plan's
  own phrasing — *"no import, no shared memory region, no queue"* — names three channels, and Phase 1
  mechanically covers one.
