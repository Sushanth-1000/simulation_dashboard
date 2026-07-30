# ADR-0003: Python 3.12 floor; the simulator is isolated behind a port

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

The source documents specify Python 3.10 or newer, and CARLA 0.9.14 as the simulator. Reconciliation
finding R-6 records that these are incompatible as stated: CARLA 0.9.14's official Python client
ships for Python 2.7, 3.6, 3.7 and 3.8 only. There is no interpreter that satisfies both
requirements.

Choosing an interpreter version is normally a low-stakes decision. Here it is not, for three
reasons.

**The floor constrains the type system, and the type system is a safety mechanism.** ASTRA is an
interface-heavy architecture: ten layer protocols, seven contract modules, generic sensor payloads.
The features available for expressing those interfaces differ materially between 3.10, 3.11 and
3.12.

**The floor has an expiry date.** Python 3.10 reaches end of life in October 2026, which is before
this project's own horizon. Starting on an interpreter that dies mid-project schedules a migration
nobody has budgeted.

**The floor interacts with the ML stack**, which arrives in Phase 4. PyTorch, Stable-Baselines3 and
FilterPy historically lag new interpreter releases, so the newest interpreter is not automatically
the safest choice.

The simulator question and the interpreter question are the same question, which is why they are
one ADR: if `carla` is importable from the core, the core's interpreter is CARLA's interpreter.

## Decision

**Python 3.12 is the floor**, declared in three places that must agree:

```toml
[project]        requires-python = ">=3.12"
[tool.ruff]      target-version  = "py312"
[tool.mypy]      python_version  = "3.12"
```

**The simulator is isolated behind a port.** No module in `astra` imports `carla`, enforced by the
`simulator-isolation` contract in `.importlinter` and by an independent AST-walking architecture
test. The simulator will be reached through the `SensorSource` protocol and an adapter written in
Phase 2.

### Why 3.12 specifically

- **PEP 695 type parameter syntax.** `class SensorSample[PayloadT]:` and
  `class FusedSensorFrame[PayloadT]:` in `src/astra/contracts/sensing.py` are the mechanism by
  which the core carries sensor data without knowing what it is — which is SI-1's enforcement and
  ADR-0002's domain independence. PEP 695 `type` alias statements are used throughout
  `src/astra/config/schema.py` (`type UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]`).
  Both are 3.12 syntax.
- **`typing.override`.** Used in `kernel/errors.py`, `kernel/identifiers.py`, `kernel/time.py` and
  `observability/logging.py`. Paired with mypy's `explicit-override` error code, it turns "this
  method was meant to override something" into a checked claim rather than a comment. Added in 3.12.
- **Security support to October 2028**, comfortably beyond the project horizon.
- **Broad ML-stack support expected by 2026** across torch, Stable-Baselines3 and FilterPy.

CI runs the full gate on a `["3.12", "3.13"]` matrix with `fail-fast: false`, so a 3.13-specific
problem is visible as a 3.13-specific failure rather than a general one. 3.13 is an early warning,
not a supported floor.

## Alternatives considered

**Python 3.10, as the documents specify.** Rejected. It has no PEP 695 syntax and no
`typing.override`, and it reaches end of life in October 2026 — before this project finishes. Its
only advantage is literal compliance with a document line, and the documents are the authority on
architecture, not on a version number whose implications they did not analyse.

**Python 3.11.** Rejected. It fixes the end-of-life problem but still has no PEP 695. The generic
sensor payload would revert to `TypeVar` plus `Generic[PayloadT]` — more code expressing less, in
the module where the expression matters most.

**Python 3.13 or 3.14 as the floor.** Rejected. Both were bugfix-current at the time of the
decision, and assumption A-6 flags ML-stack version lag as a live Phase 4 risk. Choosing the newest
interpreter would put a hard dependency on the least-supported target at exactly the phase where
the dependency set explodes. Running 3.13 in CI captures most of the forward-compatibility benefit
at none of the risk.

**Pin the whole project to Python 3.8 to match CARLA 0.9.14.** Rejected, decisively. 3.8 is end of
life, has no `StrEnum`, no `Self`, no `match`, no PEP 604 unions in annotations at runtime, and no
modern typing story at all. Accepting it would mean the safety island's type system is constrained
by a simulator that is not part of the delivered system.

**Import `carla` in the sensor layer only.** Rejected for the reasons in ADR-0002: one permitted
import is not a boundary. It would also make the interpreter question architectural rather than
deployment-level, which is the specific outcome this decision exists to avoid.

## Consequences

### Positive

- The generic-payload design that carries SI-1 and NFR5 is expressible in the syntax the language
  actually provides, rather than simulated with `TypeVar`.
- `typing.override` plus `explicit-override` catches a class of refactoring bug — a renamed base
  method leaving an orphaned override — that would otherwise survive to runtime.
- The interpreter is supported for the life of the project, and beyond it.
- R-6 is contained. The three candidate resolutions (newer CARLA, a community-built wheel, or a
  Python 3.8 sidecar bridged to the 3.12 core) are all deployment choices. Nothing in
  `src/astra/` changes under any of them.
- CI's 3.13 job gives an early signal on the interpreter the project will eventually move to.

### Negative / accepted trade-offs

- **The floor is higher than the documents specify**, so the codebase is formally out of compliance
  with a stated requirement. The deviation is deliberate and recorded here, but it is a deviation,
  and anyone auditing requirement traceability will find it.
- **R-6 is deferred, not solved.** Assumption A-8 and risk RK-1 remain open, and RK-1 is rated the
  single most consequential unresolved technical risk in the project. Isolation buys the freedom to
  solve it later; it does not solve it. If route (c) — the Python 3.8 sidecar — turns out to be the
  only option, every simulator-sourced sensor frame crosses an IPC boundary, and that latency is
  charged against the 10 ms budget in assumption A-2.
- **Reverting to 3.11 would be real work.** PEP 695 syntax appears in the sensing contracts and
  throughout the configuration schema; `typing.override` appears in four modules. It is a bounded
  mechanical migration, not a redesign, but it is not free — which means A-6 being wrong has a
  cost, not merely a consequence.
- **3.12 was not universally available in distribution repositories** at the time of the decision.
  uv installs an interpreter, so this is a non-issue on the uv path and a real friction on the
  plain-venv fallback path (see `docs/INSTALL.md` §4).
- **The 3.13 CI job doubles gate wall-clock time** for a signal that is advisory rather than
  blocking-in-principle. It is configured `fail-fast: false` so it cannot mask a 3.12 failure, but
  it does consume CI minutes on every push.
