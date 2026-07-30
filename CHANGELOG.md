# Changelog

All notable changes to ASTRA are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Two versions in this project are **not** the package version and change on their
own schedule; both are called out explicitly whenever they move, because both
determine whether an archived artefact can still be read:

- the **configuration schema version**, which a configuration file must declare;
- the **audit schema version**, stamped on every evidence record.

---

## [Unreleased]

### Added — Phase 1, Foundation

The vocabulary, contracts, interfaces, invariants, configuration and evidence
machinery every later phase depends on. Deliberately contains **no layer
logic**: L1–L9, the four feedback loops, the simulator adapter and the dashboard
are all later phases.

**Kernel** — dependency-free primitives, importable without NumPy, PyTorch or a
simulator.
- SI unit policy via `NewType` aliases, with the six named boundary conversions
  as the only places a unit system is crossed.
- `LayerId`, `ExecutionDomain`, `Verdict`, `GateId`, `FailSafeState`,
  `ContextClass`, `SensorModality`, `StreamHealth`, `TimingDomain`,
  `ArbitrationOutcome`, `FeedbackLoop`, `EventSeverity` — one spelling per
  concept, so the audit log is queryable.
- `Verdict.merge` with fail-closed aggregation: an empty verdict set is a VETO.
- Typed exception hierarchy carrying a `SafetyDisposition`
  (`FAIL_FAST` / `FAIL_CLOSED` / `FAIL_OPERATIONAL`).
- Deterministic identifiers — exactly one random ID (`RunId`); everything else
  derived, so a replayed run produces a byte-comparable event stream.
- Injected `Clock` protocol with timeline-tagged integer-nanosecond `Instant`;
  cross-timeline arithmetic raises rather than returning a meaningless number.
- Boundary guards that never use `assert` (which `python -O` removes), including
  `require_non_decreasing` for quantile monotonicity.
- `SymmetricMatrix` — packed lower triangle, so asymmetry is unrepresentable;
  pure-Python Cholesky.

**Contracts** — the immutable records layers exchange.
- Sensing, estimation, actuation, assurance, governance and audit records, all
  frozen slotted dataclasses validating once at construction.
- `ActuationSpace` makes the command space *configured* rather than hardcoded,
  which is how domain independence (NFR5) is achieved.
- `DecisionRecord` — the explainability unit: decision provenance, not
  model-internal attribution.

**Ports** — a `Protocol` per layer plus the infrastructure ports. Structural, so
an adapter never imports an ASTRA base class.

**Invariants** — SI-1 … SI-10 as data, with an `EnforcementKind` that
distinguishes mechanically checked from review-only, and runtime guards for SI-3
and SI-7. Nine of ten are mechanically enforced; SI-6 rests on review until
Phase 4, and says so.

**Configuration** — layered defaults → environment file → `ASTRA_*`, validated,
frozen at startup, hashed into every decision record. **No safety threshold has
a default**; `config/environments/certification.toml` ships incomplete on
purpose, so the failure is demonstrable rather than merely documented.

**Observability** — `contextvars` correlation, non-blocking structured logging,
and an append-only JSONL audit sink whose queue is bounded and whose drops are
counted rather than silent.

**Bootstrap** — the composition root and the `astra` CLI
(`doctor`, `config show`, `invariants list`, `version`).

**Quality gate** — ruff, mypy `--strict`, import-linter contracts and pytest
with a 95% coverage floor, wired identically into `make check`, pre-commit and
CI.

### Notes

- Configuration schema version: **1** (initial).
- Audit schema version: **1** (initial).
- `python -m importlinter.cli` exits 0 without checking anything — that module
  has no `__main__` guard. Every invocation in this repository uses the
  `lint-imports` console script, and the architecture test asserts the
  contract summary appears in the output so a no-op runner cannot pass.
