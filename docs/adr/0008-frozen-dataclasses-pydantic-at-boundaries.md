# ADR-0008: Frozen slotted dataclasses on the hot path; pydantic only at boundaries

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

ASTRA's control loop runs at 20 Hz — a 50 ms period — with a < 10 ms end-to-end software budget.
Within one tick, a sensor frame becomes a state estimate, which becomes a trust assessment and a
proposed command, which becomes a twin prediction, three gate verdicts, an FSM snapshot, an
arbitration decision, an issued command and a decision record. That is dozens of record objects per
tick, each constructed, passed between layers and read several times.

Two separate requirements act on how those records are represented.

**They must be immutable.** L5, L6 and L7 all read the same L2 state estimate. If a record can be
mutated after construction, the third gate may be judging a different value than the first — which
would silently destroy the gate-independence argument that is the system's central claim, without
any symptom a test would catch.

**They must be cheap.** Validation that runs on every hop spends the tick budget re-proving
something already proven.

Meanwhile, a *different* kind of data enters the system: configuration files and calibration
profiles, parsed once at startup from text a human wrote. That data is untrusted, arrives with
typos, and must fail loudly with messages that name the file, the field and the constraint. It has
the opposite cost profile — parsed once, never on the hot path — and the opposite quality
requirement.

Using one mechanism for both means choosing which requirement to fail.

## Decision

**Two data models, split by where the data comes from.**

### On the hot path: frozen, slotted dataclasses

Every record layers exchange — everything in `src/astra/contracts/`, and the value types in
`src/astra/kernel/` — is:

```python
@dataclass(frozen=True, slots=True)
class Instant:
    nanoseconds: int
    timeline: Timeline = Timeline.SYSTEM_MONOTONIC

    def __post_init__(self) -> None:
        # validate here, once
```

- **`frozen=True`** — a downstream layer cannot mutate a record an upstream layer already consumed.
- **`slots=True`** — no per-instance `__dict__`. Smaller objects and faster attribute access,
  measurable at 20 Hz with dozens of records per tick; and a typo'd attribute assignment becomes an
  `AttributeError` rather than a new field nobody reads.
- **Validate once at construction, then trust.** `__post_init__` runs the boundary guards from
  `astra.kernel.validation`; every subsequent hop reads plain attributes.
- Frozen and slotted together give hashability and safe use as dictionary keys, which the
  correlation structures on the audit path rely on.

### At the boundary: pydantic v2

`src/astra/config/` — and only `src/astra/config/` — uses pydantic. Configuration and calibration
profiles are parsed once, at startup, from text a human wrote. That is exactly the boundary
pydantic is for.

```python
class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=False)
```

`extra="forbid"` is load-bearing rather than tidy: a typo in a TOML key becomes a startup error
instead of a silently ignored line. A misspelled safety threshold that is quietly dropped would
leave the system running on a different value than the file appears to specify — the worst failure
mode a configuration file has.

The settings objects are `frozen` too, so a component cannot mutate the operating point mid-run,
and after load they are read as plain attributes: O(1) and allocation-free. The validators never run
again.

**The split is enforced where it matters most.** `.importlinter`'s `kernel-independence` contract
forbids `astra.kernel` from importing `pydantic` or `pydantic_settings`, with
`allow_indirect_imports = False` so a transitive path counts too. Beyond the kernel, the layering
contract keeps `config` above `contracts` and `ports`, which prevents the dependency flowing the
wrong way. A grep of `src/astra/` finds pydantic in exactly two files, both under `config/`.

## Alternatives considered

**pydantic everywhere.** Rejected on cost and on kernel purity. pydantic validates on every model
construction; the hot path constructs many records per tick and needs the guarantee established
once. It would also put a third-party dependency in the kernel, which breaks the property that an
offline evidence-analysis tool, a certification script or the dashboard process can import ASTRA's
vocabulary without installing the pipeline's dependencies (ADR-0011 makes the same argument about
NumPy).

The honest counterpoint: pydantic v2's core is Rust and genuinely fast, and "pydantic everywhere"
would give richer validation errors on the hot path too. The objection is not that it would be slow
in absolute terms; it is that it would be non-zero cost, repeated, for a guarantee already held —
and that it would make the kernel non-portable.

**Frozen dataclasses everywhere, including configuration.** Rejected. Hand-rolled TOML parsing and
coercion is more code with worse error messages, and the error messages are the point at a boundary
where a human wrote the input. "field required" naming `shield.friction_margin` is worth more than
a `KeyError`.

**Plain dictionaries.** Rejected outright. No invariants, no types, no autocomplete, and every
consumer re-deriving what a key means. In an evidence-producing system it is also unserialisable in
any disciplined way.

**`NamedTuple`.** Rejected. Immutable and slotted-equivalent, but it offers no `__post_init__` hook
for validation, and its tuple identity means a record compares equal to an unrelated tuple with the
same values — an ordering and equality hazard in a system that compares verdicts and identifiers.

**`attrs`.** Rejected as a dependency that buys little over stdlib dataclasses for this use.
`slots=True` and `frozen=True` are both in the standard library from 3.10.

**Mutable dataclasses with a "don't mutate" convention.** Rejected. See ADR-0007's argument: a
convention that is not machine-checked is a comment.

## Consequences

### Positive

- Immutability makes the gate-independence argument structurally true rather than procedurally
  hoped for. No layer can mutate a record another layer already judged.
- Validate-once-then-trust keeps the hot path light, which is one of the foundation-level reasons
  assumption A-2's budget is plausible.
- `slots=True` removes a dict per instance. At dozens of records per tick, 20 times a second, that
  is real memory and real attribute-lookup time.
- Hashability comes free, which the audit correlation structures use.
- pydantic's errors at startup name the file, the field and the constraint — which is precisely what
  makes A-4's enforcement usable: loading `certification.toml` lists all fourteen missing safety
  thresholds by name rather than failing on the first one.
- `extra="forbid"` converts a silent config typo into a startup failure.
- The kernel stays third-party-free, enforced by contract.

### Negative / accepted trade-offs

- **Two data models is two things to learn.** A contributor must know which side of the boundary
  they are on and why the answer differs. The rule is simple — pydantic parses text a human wrote,
  dataclasses carry values between layers — but it is a rule, and rules get misapplied.
- **Frozen records are awkward to evolve.** Updating one field means `dataclasses.replace`, which
  allocates a new object. On the hot path that is a real cost the moment a layer wants an
  incrementally-updated record, and it will push designs toward constructing complete records rather
  than building them up — which is the intended discipline but is not always the natural one.
- **`slots=True` breaks some patterns.** No arbitrary attribute assignment, no `__dict__`,
  restrictions on multiple inheritance, and some serialisation and debugging tools handle slotted
  classes less gracefully.
- **Validation in `__post_init__` runs on every construction anyway.** "Validate once" means once
  per record, not once per run — a record reconstructed from a replay log re-validates. That is
  correct behaviour, and it means the saving over pydantic is smaller than the framing suggests.
- **The pydantic boundary is enforced only for the kernel.** `kernel-independence` names pydantic
  explicitly; the rest of the split — that `contracts`, `ports` and `invariants` stay pydantic-free
  — rests on the layering contract and on review. A future `contracts` module could import pydantic
  without breaking any current contract.
- **The two models can drift.** `ShieldSettings` (pydantic) and the contract records that consume
  its values (dataclasses) describe overlapping concepts in different mechanisms. Keeping their
  validation consistent — a range enforced in both places, or in neither — is a manual obligation.
