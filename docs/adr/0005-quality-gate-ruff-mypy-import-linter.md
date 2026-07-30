# ADR-0005: Ruff + mypy strict + import-linter as a single non-negotiable quality gate

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

The project's stated code-quality bar is: docstrings on every public symbol, full type hints, no
magic values, no duplicated logic, SOLID, Clean Architecture, PEP 8. Objective 1 adds *formally
defined separation invariants between layers*, and the Prototype & Demo Plan is explicit about what
"formally defined" has to mean in practice: *"Verify this with a code-level check (no import, no
shared memory region, no queue), not just a comment."*

Every one of those is a claim about the codebase. A claim about a codebase that nothing checks is
an aspiration, and aspirations decay under deadline pressure — reliably, and fastest in exactly the
week when the pressure is highest and the stakes are highest.

The problem is therefore not choosing good tools. It is deciding what the tools' *authority* is:
whether a failing check is a suggestion a reviewer may weigh, or a wall.

There is a second, narrower problem. An architecture fitness check must exist **before** the code it
constrains. A layering violation discovered after two phases of code have been built on it is a
refactor, not a fix.

## Decision

A **single quality gate**, five steps, run identically by `make check`, by CI, and (as a subset) by
pre-commit. Passing it is a precondition for merging. There is no advisory tier.

| # | Step | Command | Authority |
|---|---|---|---|
| 1 | Format | `ruff format --check .` | Blocking |
| 2 | Lint | `ruff check .` | Blocking |
| 3 | Types | `mypy` (strict) | Blocking |
| 4 | Architecture | `lint-imports` | Blocking |
| 5 | Tests | `pytest --cov=astra` (95% floor) | Blocking |

Ordering is cheapest-and-most-likely-to-fail first, so a broken commit fails in seconds rather than
after the full suite.

**Ruff** replaces flake8 + isort + pydocstyle + pyupgrade + bandit + black: one tool, one
configuration, one pass. Thirty-seven rule families are selected. Four of them are project
requirements made mechanical rather than style preferences — `D` (a docstring on every public
symbol), `ANN` (a type annotation on every signature), `BLE` (no blind except, because a bare
`except` in a safety path hides faults) and `T20` (no `print()` outside the CLI). Exactly two
per-file relaxations exist, for `tests/**` and for `bootstrap/cli.py`.

**mypy `strict`** from commit one, over `src` *and* `tests`, with `warn_unreachable`,
`disallow_any_unimported` and five additional error codes (`redundant-expr`, `possibly-undefined`,
`truthy-bool`, `ignore-without-code`, `explicit-override`). `ignore-without-code` is the one worth
naming: it forbids blanket `# type: ignore`, so every suppression declares which check it waives.

**import-linter** turns the module dependency graph and the separation invariants expressible as
import relationships into build failures. Five contracts are active — `layers`,
`kernel-independence`, `simulator-isolation`, `si-1-sensor-opacity`, `si-10-evidence-non-influence`
— and a sixth (`si-5-one-way-core-channel`) is written and commented out, awaiting the Phase 3/4
modules it names. The contracts live in `.importlinter` rather than `pyproject.toml` because they
are a design artefact and deserve to be reviewed as one.

**pytest** with `pytest-cov` and Hypothesis, `filterwarnings = ["error"]`, `--strict-markers`,
`--strict-config`, and a 95% branch-coverage floor.

**CI runs the five steps individually rather than via `make check`**, so a failure is attributed to
a named check in the GitHub UI instead of to one opaque `make` invocation — but every step names the
identical command a developer runs locally. If the Makefile and the workflow ever disagree about
what "passing" means, the gate has stopped being a gate.

**Pre-commit runs a fast subset**: hygiene hooks, `detect-private-key`, ruff, and — despite being
slow — mypy and import-linter, because a contract violation found after code has been built on it is
a refactor rather than a fix. The test suite runs in CI only. mypy and import-linter run as
`language: system`, from the project's own environment rather than pre-commit's isolated one,
because both need the real dependencies and the real module graph to say anything true.

### One documented trap

`python -m importlinter.cli lint-imports` **exits 0 having checked nothing** — that module has no
`__main__` guard. Only the `lint-imports` console script runs the contracts. This is the worst
possible failure mode in the one job that guards the module dependency graph and SI-1/SI-10: a
silent false pass with a green tick. The Makefile, `.pre-commit-config.yaml` and the CI workflow
each carry a warning comment at the point of invocation, and
`tests/architecture/test_layering.py::test_every_import_linter_contract_holds` runs the contracts
through import-linter's API from inside the test suite as a second line of defence.

## Alternatives considered

**black + flake8 + isort + pydocstyle + bandit.** Rejected. Four to five tools, four to five
configuration files, four to five failure modes, and version-skew problems between them. Ruff's
single configuration is worth more than marginal per-tool tuning — especially for a project that
will be reviewed by people who are not full-time Python engineers.

**pyright instead of mypy.** Rejected, and not because pyright is worse; it is excellent and often
faster. mypy's plugin and CI story is more standard in safety-adjacent Python, and pydantic's mypy
integration is the more travelled path. This is a close call that could reasonably be revisited.

**Non-strict mypy, tightened later.** Rejected as theatre. Non-strict mypy reports what it can prove
without `Any`, which in a partly-annotated codebase is very little, and it produces a green tick
that means almost nothing. Retrofitting strict typing costs roughly an order of magnitude more than
starting with it, and `astra.contracts` is exactly where a silent type error becomes a safety defect.

**Review-only enforcement of the layering.** Rejected. It does not scale past a few modules and it
does not survive a deadline — the two conditions under which it would matter. It also fails the Demo
Plan's explicit requirement for a code-level check.

**A custom AST-walking script instead of import-linter.** Rejected as the primary mechanism: a
bespoke tool is code nobody else maintains and nobody else has debugged. It is used as a
*secondary* mechanism — `tests/architecture/test_layering.py` walks the AST directly and catches
things the import graph does not, such as a relative import inside the kernel or a `print()` outside
the CLI.

**An advisory tier — warnings that do not block.** Rejected. A warning nobody must act on is a
warning nobody acts on, and a gate with an advisory tier trains the team to read the tier label
rather than the finding.

**100% coverage.** Rejected. Chasing the last few percent produces tests written to reach lines
rather than to establish behaviour, and it makes `# pragma: no cover` a routine tool rather than a
documented exception. 95% with branch coverage on, plus a narrow `exclude_lines` list, leaves room
for genuinely unreachable defensive branches. Actual coverage is 99.10%.

## Consequences

### Positive

- The project's stated quality bar is mechanically true rather than aspirational. Docstring coverage
  and annotation coverage are not audited; they are enforced.
- SI-1, SI-10, kernel purity and simulator isolation are build failures, which is what Objective 1's
  "formally defined" requires and what the Demo Plan explicitly asked for.
- The architecture fitness harness exists before the code it constrains, so the first violation
  fails at the moment it is introduced.
- `make check` green implies CI green. That equivalence is the reason developers run the gate at
  all.
- Current state: **1352 tests, 99.10% coverage, all five steps green** on Python 3.12.3.
- `filterwarnings = ["error"]` turns a dependency's `DeprecationWarning` into the earliest possible
  signal that an upgrade is due, rather than noise nobody reads.

### Negative / accepted trade-offs

- **The gate is slow enough to notice**, and it will get slower as the suite grows. `make test-fast`
  exists for the inner loop, but the full gate is a real interruption. Pre-commit's inclusion of
  mypy and import-linter is a deliberate choice to pay some of that cost at commit time.
- **Strict typing costs velocity on genuinely dynamic code.** The kernel already carries
  `# type: ignore[redundant-expr]` on deliberate `isinstance` guards that mypy proves unreachable
  under the annotations — guards kept because the values arrive from adapters and persisted records,
  where an annotation is a claim rather than a guarantee. Every such case is friction between a
  correct runtime check and a correct static analysis.
- **Thirty-seven rule families produce false positives.** Four ruff rules are globally ignored (`D203`,
  `D213`, `ISC001`, `PLR0913`) and two per-file exemptions exist. Each is a judgement call, and each
  is a place where the gate was loosened. `PLR0913` in particular is disabled because safety records
  legitimately carry many fields — defensible, but it does mean argument-count sprawl goes unchecked.
- **Tool-version drift is real.** A newer ruff adds rules. On the plain-venv fallback path, pip
  resolves fresh and can produce a local tool newer than the one CI runs, so the two disagree. CI is
  authoritative, which means a developer can be blocked by a failure they cannot reproduce.
- **A blocking gate creates pressure to weaken it** rather than to fix the finding. The
  `per-file-ignores` table and the `ignore` list are where that pressure lands, and neither is
  itself protected by anything but review.
- **The `python -m importlinter.cli` trap is mitigated, not eliminated.** Three comments and one
  test stand between the project and a silent disabling of architecture enforcement. Someone
  optimising a slow CI step could still remove all four.
