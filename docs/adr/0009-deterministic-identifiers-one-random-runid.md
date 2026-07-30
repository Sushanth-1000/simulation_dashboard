# ADR-0009: Deterministic identifiers; exactly one random `RunId`

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

Two requirements meet on the question of how ASTRA names things.

**NFR8 requires joinable evidence.** *"All veto events, Trust Index values, FSM state transitions,
and calibration switches shall be logged with timestamps for post-hoc analysis and certification
evidence."* That requirement is only satisfiable if the records can be *joined*: the Trust Index at
tick 4200 has to be provably the one that informed the arbitration at tick 4200. Bare strings and
integers cannot express that relationship, and the first time a run identifier is passed where a
profile identifier is expected, the evidence archive is quietly corrupt — quietly, because both are
strings and nothing complains.

**The Prototype & Demo Plan requires replay.** It calls for tooling that can freeze and replay a
specific tick range with one feedback loop's weights held constant, and states plainly that building
it during closed-loop integration rather than before is *"the difference between debugging in hours
vs. days."* Closed-loop integration is named as the highest-risk stage of the whole project.

Replay is only useful if a replayed run produces *comparable* records. If any identifier derives
from `uuid4()` or a wall-clock reading, every record differs on every replay and a diff between the
original run and its reproduction is pure noise — which means the tooling exists but answers no
question.

## Decision

**Exactly one identifier in the system is random. Every other identifier is a pure function of run,
tick and sequence.**

The types live in `src/astra/kernel/identifiers.py`, each a frozen slotted dataclass that validates
its shape at construction:

| Type | Derivation |
|---|---|
| `RunId` | **The only random one.** `RunId.generate()` produces `run-<16 hex chars>` from `uuid4()`. A replay supplies the original run's identifier explicitly, so replayed records carry the identity of the run being reproduced |
| `TickId` | A monotonically increasing control-loop tick number, `ORIGIN = 0`. The primary correlation key of the whole system |
| `EventId` | Derived from run, tick and sequence |
| `ComponentId` | Derived from layer plus an instance discriminator |
| `ProfileId` | Named calibration profile plus version |

`RunId` is a lower-case slug of 3–64 `[a-z0-9_-]` characters, validated by regex — so a run
identifier is safe as a directory name, safe in a log line and safe in a filename, which matters
because the evidence sink creates one directory per run.

`TickId` is `order=True` so `tick_a < tick_b` reads naturally, and is deliberately **not** a bare
`int`: comparing a tick against an OOD counter or a profile version would otherwise type-check, and
both of those are also small monotonic integers.

Two runs of the same inputs then produce byte-comparable event streams.

The decision has a companion that makes it work: the clock is injected (ADR-0010), so no timestamp
is a hidden source of variation either. A deterministic identifier scheme with a wall-clock read in
the middle of a record is not deterministic.

`tests/conftest.py` is built on the same principle — a `ManualClock` that only moves when a test
moves it, a fixed run identifier, and configuration fixtures that never read `ASTRA_*` environment
variables. A safety codebase whose test suite depends on wall-clock time, random identifiers or the
ambient environment produces flaky results, and a flaky safety test is worse than an absent one: it
trains the team to re-run rather than to investigate.

## Alternatives considered

**A UUID per event.** The obvious default, and rejected precisely because it is the default. It
guarantees global uniqueness and destroys replay diffing: every record differs between a run and its
reproduction, so `diff` reports everything and therefore nothing. Uniqueness was never the problem —
records are already unique within a run by `(run, tick, sequence)`, and across runs by `RunId`.

**Timestamp-derived identifiers.** Rejected for the same reason plus one more: they would embed a
wall-clock read into every identifier, which conflicts with ADR-0010 and reintroduces exactly the
non-monotonicity that decision exists to avoid.

**Bare `str` and `int` identifiers.** Rejected. Nothing prevents passing a `RunId` where a
`ProfileId` is expected, or comparing a `TickId` to an OOD counter. Both are silent, both corrupt
evidence, and neither produces a symptom until someone tries to use the archive.

**A global monotonic counter for every artefact.** Rejected. It requires shared mutable state
across process boundaries — and Core-A and Core-B are separate processes with a deliberately
one-way channel between them (SI-5). A shared counter would be a back-channel.

**Fully deterministic `RunId` too — derive it from the configuration hash and a scenario name.**
Rejected, though it is tempting. Two genuinely distinct runs of the same scenario under the same
configuration would then collide, and the evidence archive would silently overlay one run on
another. Randomness at exactly one point buys distinguishability of runs while costing nothing in
replay, because a replay supplies the identifier rather than generating one.

## Consequences

### Positive

- A replayed run produces a byte-comparable event stream, so a diff between the original and its
  reproduction is signal rather than noise. That is what makes the replay harness worth building in
  Phase 2 rather than Phase 7.
- Records are joinable by construction: every artefact produced during a tick carries the same
  `TickId`, which is what lets the dashboard show a coherent snapshot and the replay harness address
  a range.
- Typed identifiers make a whole class of evidence corruption a build failure rather than a silent
  archive defect.
- `RunId`'s validated slug shape means it is safe as a directory name, which the one-directory-per-
  run evidence layout depends on.
- The test suite is deterministic by design, which removes the "just re-run it" habit before it
  forms.
- Exactly one randomness source means exactly one thing to control for in a replay — a small,
  auditable surface.

### Negative / accepted trade-offs

- **Determinism is a property of the whole system, and only part of it is under this decision's
  control.** A single random `RunId` is necessary for byte-comparable replay; it is not sufficient.
  Known remaining sources: PPO's policy sampling and PyTorch's RNG in Phase 4 (anticipated by
  assumption A-5), set iteration order in any code that grows a set, and floating-point
  non-associativity if anything is ever parallelised. Only the first is written down.
- **Nothing enforces it.** No lint rule forbids `uuid4()` in a future layer, and no test asserts
  that a replayed run diffs clean — because no replay harness exists yet. Until Phase 2, this is a
  convention with a good rationale, not a checked property.
- **Derived identifiers are not globally unique.** `EventId` for `(run, tick, sequence)` is unique
  within a run only. Merging evidence from multiple runs requires carrying the `RunId` alongside,
  which every consumer must remember to do.
- **Correlation depends on the tick being correct.** If a component reads or records the wrong
  `TickId`, the join silently produces a coherent-looking but wrong picture — worse than a missing
  record, because it looks complete.
- **Wrapper types add ceremony.** `TickId(4200)` rather than `4200`, and unwrapping at every
  arithmetic use. This is the same trade as ADR-0007's `NewType` aliases, paid in a different
  currency: here the wrapper is a real object, so there is an allocation, not just a static claim.
- **A validated slug is a constraint someone will hit.** A replay tool that wants to name a run
  after a scenario file will discover that uppercase letters, dots and slashes are rejected.
