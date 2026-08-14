# Architecture Decision Records

An ADR records one significant architectural decision: the situation that forced a choice, the
choice made, the alternatives that were rejected and why, and the consequences — including the ones
that hurt. In this project an ADR is not a summary of what the code does; the code and its module
docstrings already say that. An ADR exists to answer the question a reader will ask in eighteen
months, when the reasoning has left the building: *why is it like this, and what did we give up?*
That is why every record here carries a **Negative / accepted trade-offs** section, and why an
empty one would mean the record is wrong rather than the decision perfect. The first fourteen cover
the decisions taken during Phase 1 (Foundation) and ADR-0015 opens Phase 2; they are **Accepted**
and, unless a later ADR supersedes one, they describe the system as built. Where an ADR's reasoning
is also recorded in the source, the module docstring is named — the reader who opens
`kernel/units.py` should not have to find this directory to understand why `NewType` is there.

## Index

| ADR | Title | Primary source |
|---|---|---|
| [0001](0001-consolidated-layer-numbering.md) | Adopt the consolidated L1–L9 layer numbering | `src/astra/kernel/enums.py` (`LayerId`) |
| [0002](0002-domain-independent-platform-core.md) | Domain-independent platform core with adapters, not a CARLA-coupled prototype | `src/astra/ports/pipeline.py` |
| [0003](0003-python-312-floor-simulator-behind-a-port.md) | Python 3.12 floor; the simulator is isolated behind a port | `pyproject.toml`, `.importlinter` |
| [0004](0004-uv-hatchling-pep-621-735.md) | uv + hatchling + PEP 621/735 for build and dependency management | `pyproject.toml`, `Makefile` |
| [0005](0005-quality-gate-ruff-mypy-import-linter.md) | Ruff + mypy strict + import-linter as a single non-negotiable quality gate | `pyproject.toml`, `Makefile`, `.github/workflows/ci.yml` |
| [0006](0006-typed-exception-hierarchy-no-result-type.md) | Typed exception hierarchy carrying safety dispositions; no `Result` type | `src/astra/kernel/errors.py` |
| [0007](0007-si-units-via-newtype.md) | SI units internally via `NewType`; conversion only at boundaries | `src/astra/kernel/units.py` |
| [0008](0008-frozen-dataclasses-pydantic-at-boundaries.md) | Frozen slotted dataclasses on the hot path; pydantic only at boundaries | `src/astra/contracts/`, `src/astra/config/schema.py` |
| [0009](0009-deterministic-identifiers-one-random-runid.md) | Deterministic identifiers; exactly one random `RunId` | `src/astra/kernel/identifiers.py` |
| [0010](0010-injected-clock.md) | Injected `Clock`; no component reads time directly | `src/astra/kernel/time.py` |
| [0011](0011-packed-symmetric-matrix-no-numpy.md) | Packed lower-triangular `SymmetricMatrix`; no NumPy in the kernel | `src/astra/kernel/matrix.py` |
| [0012](0012-executable-separation-invariants.md) | Separation invariants as executable, machine-checked contracts | `src/astra/invariants/catalogue.py`, `.importlinter` |
| [0013](0013-append-only-jsonl-audit-log.md) | Append-only JSONL audit log as the certification evidence artefact | `src/astra/observability/audit.py`, `src/astra/contracts/audit.py` |
| [0014](0014-proprietary-licence-pending-patent.md) | Proprietary licence while the patent filing is pending | `LICENSE`, `NOTICE` |
| [0015](0015-carla-interpreter-strategy.md) | Target CARLA 0.9.16 on Linux; no sidecar, no unofficial wheel | `.importlinter`, [`../spikes/R6-carla-interpreter.md`](../spikes/R6-carla-interpreter.md) |
| [0016](0016-exploration-may-not-override-a-deterministic-veto.md) | A gate that cannot judge abstains; no path overrides a veto | `src/astra/kernel/enums.py` (`Verdict`), `src/astra/layers/l9_rcm/arbiter.py` |
| [0017](0017-rate-limited-approach-to-a-jerk-vetoed-proposal.md) | A jerk veto yields the largest admissible step, not zero steering | `src/astra/layers/l9_rcm/arbiter.py`, `src/astra/ports/pipeline.py` (`CommandProjector`) |
| [0018](0018-ewc-anchors-on-context-not-on-every-update.md) | The EWC anchor moves on a context change, not on every update | `src/astra/layers/l5_twin/` — **superseded in effect by 0019** |
| [0019](0019-one-twin-head-per-context.md) | One twin output head per context, instead of a consolidation penalty | `src/astra/layers/l5_twin/twin.py` |
| [0020](0020-fb2-estimates-control-effectiveness.md) | FB2 estimates the control effectiveness, rather than regressing on commands | `src/astra/runtime/assembly.py` (`ControlEffectivenessEstimator`), `benchmarks/effectiveness.py` |
| [0021](0021-ablation-neutralises-a-gate-it-never-removes-one.md) | An ablation neutralises a gate; it never removes one | `src/astra/runtime/ablation.py`, `benchmarks/ablation.py` |
| [0022](0022-faults-are-injected-at-the-sensor-boundary.md) | Faults are injected at the sensor boundary, never inside the core | `training/faults.py`, `benchmarks/fault_study.py` |
| [0023](0023-the-ood-counter-freezes-during-bounded-exploration.md) | The OOD counter freezes during bounded exploration, and the envelope's speed cap goes through the projector | `src/astra/layers/l8_failsafe/machine.py`, `src/astra/layers/l9_rcm/arbiter.py`, `benchmarks/platform_transfer.py` |
| [0024](0024-sensor-integrity-is-a-second-counter-not-a-fourth-gate.md) | Sensor integrity is a second counter, not a fourth gate | `src/astra/layers/l8_failsafe/machine.py`, `src/astra/layers/l1_sensing/bus.py` (`StreamHealth`) |
| [0025](0025-the-vehicle-proposes-calibration-work-never-a-calibration.md) | The vehicle proposes calibration *work*, never a calibration | `benchmarks/envelope.py`, `src/astra/contracts/governance.py` (`ArbitrationDecision.signature`) |
| [0026](0026-faulted-gets-a-producer-and-the-counter-needs-a-quorum.md) | `FAULTED` gets a producer, and the counter now needs a quorum | `src/astra/layers/l2_estimation/measurement.py` (`IntegrityMonitor`), `training/redundant.py` |
| [0027](0027-the-integrity-counter-rises-on-a-lost-quorum.md) | The integrity counter rises on a lost quorum, not on any bad channel | `src/astra/layers/l8_failsafe/machine.py`, `src/astra/config/schema.py` |
| [0028](0028-the-deployment-declares-which-sensors-are-critical.md) | The deployment declares which sensors are safety-critical | `src/astra/layers/l8_failsafe/machine.py`, `src/astra/config/schema.py` |
| [0029](0029-capability-withdrawal-is-a-second-axis-not-a-third-counter.md) | Capability withdrawal is a second axis, not a third counter | `src/astra/layers/l8_failsafe/machine.py`, `benchmarks/degradation.py` |

## Format

Every record follows the same structure, and new ones must:

```markdown
# ADR-000N: Title

- **Status:** Proposed | Accepted | Superseded by ADR-000M
- **Date:** YYYY-MM-DD
- **Phase:** N (Name)

## Context
## Decision
## Alternatives considered
## Consequences
### Positive
### Negative / accepted trade-offs
```

## Writing a new one

Number sequentially; the number is permanent. Use a short kebab-case slug in the filename
(`0015-something-specific.md`) and add a row to the index above.

Write one when a decision has a *rejected alternative worth recording* — when a future reader could
reasonably ask "why not X?" and the answer took thought. Do not write one for a decision with no
alternative; that is just how the thing works, and it belongs in a module docstring.

Never edit an accepted ADR to reflect a changed decision. Write a new record and mark the old one
**Superseded by ADR-000M**. The value of this directory is that it shows what was believed at the
time, including where that turned out to be wrong.

## Related

- [`../DECISION_LOG.md`](../DECISION_LOG.md) — the index across all of these: one row per decision, the
  alternatives weighed, and what each choice gave up. Read it before reading the records themselves
- [`../CONVENTIONS.md`](../CONVENTIONS.md) — the coding standards these decisions produced, and how
  each is enforced
- [`../ASSUMPTIONS.md`](../ASSUMPTIONS.md) — A-1 … A-10, what breaks if each is wrong, and their
  status
- [`../DEVELOPMENT.md`](../DEVELOPMENT.md) — the quality gate that makes several of these decisions
  mechanical
