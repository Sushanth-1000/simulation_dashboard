# ADR-0006: Typed exception hierarchy carrying safety dispositions; no `Result` type

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

In ordinary application code an exception's job is to tell a developer what went wrong. In a
safety-governed system it has a second job, and the second one is more important: it must tell the
*runtime* what the system is now permitted to do.

An exception raised while the ICP gate is scoring a proposed command is not merely a bug report. It
is a statement that the command has not been validated, and therefore must not be issued. An
exception raised while writing a diagnostic log line is a different kind of statement entirely: the
pipeline can continue, and the incident should be recorded. Treating those two the same way — as
"an error" — is how a logging failure becomes a vetoed command, or worse, how a validation failure
becomes an issued one.

The hardware FMEA in the source documents already encodes the correct policy for the important
case: on a missed Core-B heartbeat, the crossbar defaults to VETO. The software error model has to
express the same idea, and it has to express it in a form that survives a developer who is not
thinking about safety at the moment they write a `try` block.

Two error-handling styles were on the table: exceptions, or a `Result`/`Either` return type.

## Decision

A **typed exception hierarchy** rooted at `AstraError`, in which every class carries a
`SafetyDisposition` as a `ClassVar` declaring what the runtime does when it escapes.

```python
@unique
class SafetyDisposition(StrEnum):
    FAIL_FAST = "FAIL_FAST"  # refuse to start, or terminate the run
    FAIL_CLOSED = "FAIL_CLOSED"  # treat the command as VETOed; notify the FSM
    FAIL_OPERATIONAL = "FAIL_OPERATIONAL"  # record and continue
```

- **`FAIL_FAST`** — the system cannot start, or cannot continue, in a defensible state.
  Configuration and invariant violations. Refusing to start is safe; starting with an unverified
  configuration is not.
- **`FAIL_CLOSED`** — the safety pipeline could not complete its judgement. The command under
  inspection is treated as VETOed and the fail-safe FSM sees a VETO event. This is the software
  mirror of the FMEA's crossbar behaviour.
- **`FAIL_OPERATIONAL`** — the failure is outside the safety argument: a dashboard websocket
  dropping, an offline evidence file failing to write. Only failures that *provably cannot influence
  a command* carry this disposition.

Each class also carries a stable, greppable `code` that appears verbatim in audit records, and an
`EventSeverity`:

| Class | Code | Disposition | Severity |
|---|---|---|---|
| `AstraError` | `ASTRA-000` | `FAIL_FAST` | `SAFETY_CRITICAL` |
| `ConfigurationError` | `ASTRA-CFG-001` | `FAIL_FAST` | `SAFETY_CRITICAL` |
| ↳ `SchemaVersionError` | `ASTRA-CFG-002` | `FAIL_FAST` | `SAFETY_CRITICAL` |
| `ContractViolationError` | `ASTRA-CTR-001` | `FAIL_CLOSED` | `SAFETY_RELEVANT` |
| ↳ `RangeViolationError` | `ASTRA-CTR-002` | `FAIL_CLOSED` | `SAFETY_RELEVANT` |
| ↳ `NonFiniteValueError` | `ASTRA-CTR-003` | `FAIL_CLOSED` | `SAFETY_RELEVANT` |
| ↳ `DimensionMismatchError` | `ASTRA-CTR-004` | `FAIL_CLOSED` | `SAFETY_RELEVANT` |
| `SafetyPathError` | `ASTRA-SAF-001` | `FAIL_CLOSED` | `SAFETY_RELEVANT` |
| ↳ `TimingBudgetExceededError` | `ASTRA-SAF-002` | `FAIL_CLOSED` | `SAFETY_CRITICAL` |
| `InvariantViolationError` | `ASTRA-INV-001` | `FAIL_FAST` | `SAFETY_CRITICAL` |
| `AdapterError` | `ASTRA-ADP-001` | `FAIL_OPERATIONAL` | `WARNING` |

Codes are never reused for a different meaning, because they appear in the evidence archive.

Two of these assignments carry an argument worth reading in the source.
`ContractViolationError` is `FAIL_CLOSED` rather than `FAIL_FAST`: a single malformed sensor frame
should degrade the current tick to a VETO and be counted by the fail-safe FSM, not abort a moving
vehicle's control loop — sustained violations reach HALT through the ordinary OOD-counter path,
which is the graduated response the architecture exists to provide. `InvariantViolationError` is
the opposite: if Core-A has obtained a reference to a Core-B verdict, or a component other than
RCM has issued a command, the safety argument no longer describes the running system and no
graduated response is meaningful. The run stops.

`AdapterError` defaults to `FAIL_OPERATIONAL` because most adapters — the dashboard stream, the
evidence writer — sit outside the safety argument. Adapters that *are* inside it (a sensor source,
the actuation sink) must subclass and override the disposition to `FAIL_CLOSED`.

`AstraError` being the root also gives the `BLE` lint rule something to protect: catching
`AstraError` catches exactly the failures ASTRA understands and models, and leaves genuine
programming errors (`TypeError`, `AttributeError`) to propagate, where they belong.

**Deliberately not included in Phase 1:** any fail-closed decorator or guard context manager. The
policy is data; the machinery that applies it belongs with the pipeline it guards, which arrives in
Phase 2. Building the mechanism now would mean building it against an imagined caller — a
placeholder that later integration code gets written against, which is the failure mode the phase
discipline exists to prevent.

## Alternatives considered

**A `Result`/`Either` return type.** Rejected, and this was the closest call in the error model.
The case for it is real: an explicit return type makes the failure path visible at every call site
and impossible to forget, which is exactly the property a safety system wants. Three arguments
against it won.

First, Python has no syntactic support. No `?` operator, no `do` notation, no pattern-matching
ergonomics for it. Every call site grows an explicit unwrap, and the resulting code is harder for a
mixed-experience team to read *correctly* — and correctness of reading is the whole point.

Second, the typed-disposition approach gets the same core property. The failure mode is part of the
contract, declared on the type and documented in the `Raises:` section that ruff's `D` rules
require.

Third, the hot-path cost is nil in the nominal case. Python pays for an exception only when one is
raised; a `Result` allocates a wrapper on every call, including every successful one, on a path with
a < 10 ms end-to-end budget at 20 Hz.

**Untyped exceptions — just `raise ValueError`.** Rejected. It provides no policy at all. A caller
cannot distinguish "this command was not validated" from "the log file is full" without reading the
raising code, which means the distinction lives in a human's head rather than in the type.

**Error codes as return values, C-style.** Rejected. Silently ignorable, and the ignore is
invisible in review.

**A single `AstraError` with a disposition passed at the raise site**, rather than a hierarchy.
Rejected. It makes the disposition a per-call decision rather than a property of the failure kind,
so the same condition can carry different dispositions in different modules — and the one that gets
it wrong is the one written at 2 a.m.

## Consequences

### Positive

- The failure policy is attached to the type, so `except SafetyPathError` is a statement about what
  the system may now do, not just about what went wrong.
- `AstraError` as the root makes `except AstraError` a precise catch, which is what lets `BLE`
  forbid blind excepts without making error handling impossible.
- Stable codes make the audit log greppable and the evidence archive joinable across runs.
- Nominal-path cost is zero. No wrapper allocation, no unwrap noise.
- The three-disposition model maps directly onto the hardware FMEA, so the software and hardware
  safety arguments use the same vocabulary.
- `ConfigurationError` carrying `FAIL_FAST` is what makes A-4's enforcement work: a missing safety
  threshold stops the run rather than degrading it.

### Negative / accepted trade-offs

- **An exception is invisible in a signature.** This is the `Result` type's genuine advantage and
  the real cost of this decision. Nothing in `def score(...) -> float:` says it can raise
  `NonFiniteValueError`. The mitigation is convention — a `Raises:` section in every docstring,
  enforced for presence by `D` but *not* for accuracy by anything. A function that grows a new raise
  and does not update its docstring will pass the gate.
- **Nothing forces a caller to handle it.** An unhandled `SafetyPathError` propagates to whatever
  catches first. Until the Phase 2 guard machinery exists, "the disposition is honoured" is a
  statement about code that has not been written yet.
- **The disposition is advisory in Phase 1.** It is data on a class. No code reads it and acts on
  it, because the pipeline it would guard does not exist. This is a deliberate deferral, but it
  means the property is currently documented rather than operative.
- **The disposition is a property of the class, so one class cannot mean two things.**
  `ContractViolationError` is `FAIL_CLOSED` because the common case is a malformed frame mid-run —
  but the *same* class is raised by `SymmetricMatrix.__post_init__` and by `RunId.__post_init__`
  during startup and during test construction, where `FAIL_FAST` would be the honest answer. The
  model resolves this by where the error is caught rather than by what it is, which is a seam worth
  revisiting when the Phase 2 guard machinery is built.
- **`AdapterError`'s override requirement is a convention with a promised check.** Its docstring
  states that adapters inside the safety path must subclass and set `FAIL_CLOSED`, and that the
  architecture suite verifies it. No adapter exists yet, so that check is a commitment rather than a
  running test — and it is exactly the kind of commitment that quietly does not get honoured.
- **Exception hierarchies invite over-refinement.** Eleven classes today is defensible; the pressure
  in later phases will be to add one per failure mode, at which point the hierarchy stops being a
  policy and becomes a catalogue.
- **Python's traceback machinery allocates.** In a genuinely worst-case tick where an exception *is*
  raised, the cost is real and unbudgeted. The bet is that the exceptional path is rare enough for
  the nominal-path saving to dominate — a bet that assumption A-2's measurement will eventually test.
