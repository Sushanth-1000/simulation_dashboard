# ADR-0010: Injected `Clock`; no component reads time directly

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

Calling `time.time()` is the obvious way to find out what time it is, and in ASTRA it is wrong three
separate times over.

**Correctness.** FR1 requires the sensor bus to flag any stream whose staleness exceeds 50 ms.
Staleness is a *duration*, and durations must be measured on a monotonic timeline. The wall clock is
not monotonic: an NTP correction, a leap-second smear or a VM migration can move it backwards. When
it does, a staleness computation returns a negative number, and a negative staleness reads as
"perfectly fresh" — a stale sensor stream passing its freshness check because the clock moved. That
is a fail-open mode in the first layer of the pipeline. Using the wall clock to time a control loop
is a latent fault, not a style preference.

**Replay.** The Prototype & Demo Plan requires tooling that can freeze and replay a specific tick
range with one feedback loop's weights held constant, and states that building it during closed-loop
integration rather than before is the difference between debugging in hours and in days. Replay is
impossible if components read a global clock: the recorded timeline has to be substitutable for the
live one, and a global read cannot be substituted.

**Simulation.** CARLA in synchronous mode advances simulated time in fixed steps that do not track
wall-clock time. A pipeline that measures its own latency against the wall clock while the simulator
advances on its own timeline is measuring two different things and comparing them — and this system's
central claim is *about* latency.

Any one of the three would justify the decision. Together they make it non-optional.

## Decision

**Every component that needs the time receives a `Clock` through its constructor. No component reads
a global clock.**

`src/astra/kernel/time.py` provides:

- **`Clock`** — a structural `Protocol` with a `timeline` property, `now() -> Instant`, and
  `wall_clock() -> datetime` for human-readable audit records only, never for arithmetic.
- **`SystemClock`** — reads the host's monotonic counter. The default for live operation.
- **`ManualClock`** — advances only when advanced explicitly. Used by tests and by replay.
- **`Instant`** — a frozen slotted dataclass holding **integer nanoseconds** and the `Timeline` it
  was measured against.
- **`Timeline`** — `SYSTEM_MONOTONIC`, `SIMULATED`, `MANUAL`.
- **`staleness()` and `is_stale()`** — the duration helpers FR1's rule is expressed with.

Two properties of `Instant` are decisions in their own right.

**Integer nanoseconds, not a float of seconds.** A float64 holding seconds-since-boot loses
sub-microsecond resolution after a few days of uptime, and this system reports latencies whose
targets are stated in microseconds and milliseconds. Integers do not drift.

**The timeline is part of the value.** Subtracting instants from different timelines raises rather
than returning a number. The alternative — bare floats — makes "simulated tick time minus wall-clock
arrival time" a perfectly valid expression that produces a meaningless duration. Given that this
system's central claim is about latency and staleness, that class of defect is worth one integer
comparison to prevent.

**`bootstrap/composition.py` is the only module permitted to construct a concrete clock.** The
startup order puts the clock third — after configuration is frozen and after the invariant catalogue
is verified — so that every subsequent timestamp comes from one substitutable source.

`tests/conftest.py` supplies a `ManualClock` fixture. A safety codebase whose tests depend on
wall-clock time produces flaky results, and a flaky safety test trains the team to re-run rather
than to investigate.

## Alternatives considered

**`time.time()` directly.** Rejected on all three counts above. It is not monotonic, not
substitutable and not simulator-aware.

**`time.monotonic()` directly, as a global call.** Rejected. It fixes the correctness objection —
`monotonic()` genuinely is monotonic — and neither of the other two. A component that calls
`time.monotonic()` cannot be replayed and cannot be driven by simulated time. This is the
alternative that looks adequate and is not, which is why it is worth naming explicitly: monotonicity
was never the only requirement.

**A module-level clock with a patch point for tests** (`astra.time.now()`, monkeypatched in the
suite). Rejected. It makes replay a global mutation, which means two components cannot run on
different timelines in the same process — precisely what shadow execution and the Core-A/Core-B
split will need. It also makes the dependency invisible: nothing in a component's signature says it
reads time.

**Bare floats for instants, with the timeline as a naming convention.** Rejected under the same
reasoning as ADR-0007: a convention that is not machine-checked is a comment.

**A datetime-based `Instant`.** Rejected. `datetime` carries calendar semantics ASTRA does not need,
costs more per operation, and reintroduces the wall-clock non-monotonicity through the back door.
`Instant` does provide a wall-clock rendering for human-facing evidence, but the arithmetic is on
integer nanoseconds. Ruff's `DTZ` rules are on project-wide, so any `datetime` that does appear
carries a timezone.

## Consequences

### Positive

- Staleness is measured on a monotonic timeline, so FR1's 50 ms rule cannot be defeated by an NTP
  correction. The fail-open mode is removed rather than mitigated.
- Replay is possible: substitute a recorded timeline for the live one and every component follows.
  This is a precondition for the Phase 2 replay harness, which the Demo Plan wants built before
  closed-loop integration rather than during it.
- CARLA synchronous mode is supported by construction — `Timeline.SIMULATED` exists, and mixing it
  with wall-clock instants raises.
- Deterministic tests. No sleeps, no tolerance windows, no "flaky on CI" category.
- The clock is a visible dependency: a component that needs time says so in its constructor, which
  a reviewer can see.
- Integer nanoseconds keep sub-microsecond resolution indefinitely, which matters for a project that
  reports latency figures.
- It is the necessary companion to ADR-0009: deterministic identifiers with a hidden wall-clock read
  in the middle would not be deterministic.

### Negative / accepted trade-offs

- **Every component that needs the time grows a constructor parameter.** The clock threads through
  the composition root to nearly everything, and that plumbing is real: it makes constructors longer
  and makes "just log a timestamp here" a change to a signature rather than a one-line addition.
- **Nothing mechanically forbids `time.time()` today.** `astra.kernel.time` imports `time`
  legitimately, so no blanket lint ban is possible. The convention rests on review plus
  composition-root discipline — a layer that wanted the wall clock would have to import `time`
  itself, visible in a diff but only if someone looks.
  **Known gap:** the `Clock` protocol's own docstring states that *"the architecture test suite
  enforces this by forbidding imports of `time` and `datetime` outside this module and the adapters
  that implement it."* **No such test exists in `tests/architecture/`.** The property currently
  holds — `src/astra/kernel/time.py` is the only module in `src/astra/` that imports either — but
  it holds by discipline, not by enforcement, and the docstring overstates what is checked. Either
  the test should be written or the docstring corrected; leaving a claimed enforcement unbacked is
  the same defect class this project's honesty rules forbid elsewhere.
- **The timeline check is a runtime error, not a static one.** All three `Timeline` values inhabit
  the same `Instant` type, so mixing them type-checks and raises at runtime. A phantom type
  parameter (`Instant[SimulatedT]`) would have caught it statically at the cost of substantially
  more type machinery on a value used everywhere. That trade was taken toward simplicity; it means
  the class of defect this decision exists to prevent is caught one step later than it could be.
- **`Instant`'s epoch is unspecified.** Only differences between instants on the same timeline are
  meaningful, and an absolute `Instant` value means nothing on its own. Anyone reading a raw
  nanosecond count out of a record and expecting a date will be wrong.
- **`ManualClock` makes it easy to write tests that could not happen.** A test can advance time
  backwards conceptually, or construct interleavings a real clock never produces, and a passing test
  under an impossible timeline proves less than it appears to.
- **The clock is a shared dependency of every layer**, which makes it — like the L2 state estimate —
  a common-cause channel. A defective clock implementation is wrong everywhere at once. It is small
  and heavily tested, but the property is worth stating rather than assuming away.
