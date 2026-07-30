# ADR-0013: Append-only JSONL audit log as the certification evidence artefact

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

NFR8 states: *"All veto events, Trust Index values, FSM state transitions, and calibration switches
shall be logged with timestamps for post-hoc analysis and certification evidence."*

That sentence makes the log a **certification artefact, not a debugging aid**, and the two have
almost nothing in common. A debug log may be sampled, may be rotated away, may start when someone
turns it on, and may be reformatted between releases. An evidence archive must be complete from tick
zero, joinable across record types, schema-versioned so an old archive stays readable, and it must
survive an abnormal termination — because the run that crashed is the run whose evidence is most
interesting.

Two requirements sit in direct tension.

**Durable evidence means file I/O.** **SI-8 forbids cold-path work from blocking a hot-path tick.**
A `write()` inside a 50 ms tick with a < 10 ms end-to-end budget is exactly the blocking syscall
that breaks the budget — and on a stalled disk it does not merely slow the tick, it stops it.

There is also a timing argument for building this in Phase 1 rather than later. Evidence is only
evidence if the records are joinable, schema-versioned and complete from the first tick. A log added
in Phase 6 has a hole at the beginning, exactly where the interesting bugs are.

## Decision

**An append-only, line-delimited JSON file, one per run, written by a background thread behind a
bounded queue.**

### The format

`events.jsonl`, one JSON object per line, inside a per-run directory.

- **Append-only** — a written record is never rewritten, which gives the tamper-evidence property a
  certification archive needs at prototype stage.
- **One file per run** — a run becomes the unit of archival and of replay, and the run directory is
  named by the `RunId` slug (ADR-0009).
- **Line-delimited** — a partially written file is still readable up to the last complete line.
  That matters precisely when a run ended abnormally.
- **JSON, not a binary format** — a human safety assessor is one of the consumers, and `StrEnum`
  members serialise as `"VETO"` with no custom encoder (see `astra.kernel.enums`).

### The records

Three types, in `src/astra/contracts/audit.py`, each carrying `AUDIT_SCHEMA_VERSION`:

- **`AuditEvent`** — the atomic entry. Its payload is validated to be JSON-serialisable **at
  construction**, so an event that could not become evidence fails when it is built, not when the
  log is written.
- **`DecisionRecord`** — the explainability unit (reconciliation finding R-7). For one tick it ties
  together frame health, the state estimate, the Trust Index, the proposal, the twin's prediction,
  every gate verdict, the FSM snapshot, the arbitration decision, the issued command, and the
  configuration hash under which all of it happened. It answers *"why did the vehicle do that, on
  what evidence, under which calibration"* without any model-internal attribution.
- **`ExecutionOutcome`** — closes the loop: the command actually applied, what was measured
  afterwards, and which feedback loops that outcome feeds.

**Round-trip guarantee.** `DecisionRecord.to_json` produces a payload built from ordered
dictionaries of JSON scalars only — no sets, no mappings with non-string keys — so parsing a line
and re-serialising it yields byte-identical output. The guarantee holds by construction rather than
by hope, which is what makes replay diffing (ADR-0009) meaningful at the evidence level.

### The writer

`JsonlAuditSink` in `src/astra/observability/audit.py`. `emit()` appends to an in-memory queue and
returns; a background writer thread drains it and performs every syscall. The hot path pays a queue
append.

**The queue is bounded.** An unbounded queue turns a stalled disk into unbounded memory growth,
which on a real-time system is a worse failure than losing records. Overflow is therefore **counted
and reported**: `JsonlAuditSink.dropped_records` is non-zero if any record was lost, and the run's
evidence is then *known* to be incomplete. An evidence archive that is silently incomplete is worse
than one that admits a gap, because only the second can be assessed honestly.

`fsync_each_record` is configurable — `false` in development, `true` in simulation and certification,
where a crashed run must not lose the ticks that preceded it. The background writer means it never
blocks a tick either way.

**Diagnostic logging is a separate system.** `astra.observability.logging` produces what an engineer
reads while debugging; the audit sink produces evidence. `EventSeverity` deliberately does not reuse
the `logging` module's levels, so a component silent in the console may still be emitting
`SAFETY_CRITICAL` audit records.

### SI-10: evidence does not influence the safety argument

The `si-10-evidence-non-influence` contract in `.importlinter` forbids `astra.contracts` and
`astra.ports` from importing `astra.observability`. Evidence gathered during bounded safe
exploration feeds the offline certification pipeline; it must not reach a gate.

## Alternatives considered

**Synchronous writes on the hot path.** Rejected. It violates SI-8 by construction, and it makes
disk latency a control-loop latency. A stalled writer would stall the vehicle.

**An unbounded queue.** Rejected. It trades a bounded, *reported* loss of records for an unbounded,
unreported growth in memory — which on a real-time system ends in an OOM kill that loses everything,
including the records that would have explained it.

**A relational database (SQLite or Postgres).** Rejected for prototype stage. It adds a dependency
that must be qualified under ISO 26262 §8-12, it makes a run's evidence a query rather than a file
(harder to archive, harder to hand to an assessor), and a partially written database after a crash
is much less readable than a truncated text file. Assumption A-3 records that real certification may
require exactly this, and the `EventSink` port is the seam that would contain the migration.

**A binary format — Protocol Buffers, Avro, Parquet.** Rejected. Smaller and faster, and unreadable
without tooling. A safety assessor with `less` and `jq` is a design constraint, not an afterthought.
Parquet's columnar layout is also a poor fit for an append-per-tick write pattern.

**A cryptographically signed or hash-chained log.** Not rejected on merit — deferred. It is the
right answer for real certification and would give genuine tamper-evidence rather than the weak
append-only property. It is not built in Phase 1 because the key-management question (who signs,
with what key, verified by whom) is not an engineering decision the repository can make alone.

**Structured logging through the standard `logging` module as the evidence path.** Rejected. Level
filtering, handler configuration and formatter changes are all things that can silently alter what
ends up in an evidence archive. Evidence needs a path with no filtering in it.

## Consequences

### Positive

- SI-8 is satisfied: `emit()` is a queue append, and every syscall happens off the tick.
- NFR8's completeness requirement is achievable, because the machinery exists from tick zero rather
  than being retrofitted.
- A partially written file after a crash is still readable up to the last complete line — the case
  that matters most.
- Record loss is visible. `dropped_records` makes an incomplete archive announce itself.
- Payload serialisability is validated at construction, so an unloggable event fails where it is
  built rather than deep in the writer.
- The round-trip guarantee makes evidence-level replay diffing meaningful.
- Zero new dependencies: `json`, `queue`, `threading`, `pathlib`.
- Readable by `jq`, `grep`, pandas or a human, on any machine, with nothing installed.

### Negative / accepted trade-offs

- **"Append-only" is a convention of this writer, not a property of the filesystem.** Anyone with
  write access can edit `events.jsonl` with a text editor and leave no trace. Calling it
  tamper-*evident* is generous; it is tamper-*inconvenient*. Real tamper-evidence needs hash chaining
  or signing, and that is deferred.
- **Records can be dropped.** A bounded queue is a deliberate choice to lose records rather than
  memory, but a dropped record is a hole in certification evidence. The hole is counted; it is still
  a hole.
- **JSONL is verbose.** Every line repeats its keys. At 20 Hz with a full `DecisionRecord` per tick,
  a long run produces a large file, and no compression or rotation is implemented — a rotation
  scheme would conflict with one-file-per-run.
- **A background thread is a thread.** Shutdown ordering matters (`_WRITER_JOIN_TIMEOUT_S` is 5.0
  seconds; a writer that has not drained by then is abandoned, and whatever remained in the queue is
  lost). Failing to close the sink loses records, which is why it is a context manager. In CPython
  the GIL also means the writer contends with the control loop, which is a real if small cost.
- **A-3 is unresolved.** Adequacy as *certification* evidence is not an engineering question and
  cannot be settled inside this repository. Phase 9's evidence review may return a requirement for a
  signed log or a database.
- **`fsync_each_record = true` in the certification environment is slow**, and slow on the writer
  thread means the bounded queue drains slower, which makes overflow more likely under load — the
  durability setting and the completeness property pull against each other, and no measurement of
  that interaction exists yet.
