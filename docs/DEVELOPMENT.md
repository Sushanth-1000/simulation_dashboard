# Development

Day-to-day workflow: the quality gate, how to run parts of it, how to add a layer in a later
phase, and how to debug the checks when they fail.

Environment setup lives in [`INSTALL.md`](INSTALL.md). This document assumes `uv sync --all-groups`
has already run.

---

## The one command

```bash
make check
```

`make check` **is** the quality gate. It runs the same five checks as `.github/workflows/ci.yml`, in
the same order, with the same commands. That equivalence is deliberate and worth protecting: a gate
developers cannot reproduce locally is a gate they learn to ignore. If the Makefile and the CI
workflow ever disagree about what "passing" means, fix it before anything else.

Two deliberate differences, neither of which changes what passes: CI runs the steps as separate
named jobs rather than through `make`, so a failure is attributed to a named check in the GitHub UI
instead of to one opaque `make` invocation; and CI adds `--cov-report=xml` plus a final
`uv run astra doctor` smoke test (`doctor` exits non-zero if the installation could not start a run,
which makes it a genuine test of the composition root). Run `make doctor` locally if you want that
last one.

```bash
make help     # every target, with a one-line description
```

Current status of the gate on `main`: **green** — 1352 tests, 99.10% statement/branch coverage,
ruff, mypy `--strict` and import-linter all clean on Python 3.12.3.

### Running it without uv

`RUN ?= uv run` is the only place the Makefile names the toolchain. Clear it to take the tools from
`PATH` instead:

```bash
PATH=.venv/bin:$PATH make check RUN=
```

See [`INSTALL.md` §4](INSTALL.md#4-fallback-a-plain-virtual-environment) for what this costs you.

---

## The five steps

`check: format-check lint typecheck contracts test`

The ordering is cheapest-and-most-likely-to-fail first, so a broken commit fails in seconds rather
than after the full suite.

| # | Step | Command | What it catches |
|---|---|---|---|
| 1 | Format | `uv run ruff format --check .` | Formatting drift. Fails without rewriting, so CI never mutates the tree |
| 2 | Lint | `uv run ruff check .` | 37 rule families: real errors, security, docstring coverage, annotation coverage, bare excepts, `print()` outside the CLI, f-strings in log calls, relative imports, commented-out code |
| 3 | Types | `uv run mypy` | Strict typing across `src/` **and** `tests/`, plus `redundant-expr`, `possibly-undefined`, `truthy-bool`, `ignore-without-code`, `explicit-override`, `disallow_any_unimported` |
| 4 | Architecture | `uv run lint-imports` | The module dependency graph and the separation invariants expressible as import relationships (SI-1, SI-10, kernel independence, simulator isolation) |
| 5 | Tests | `uv run pytest --cov=astra --cov-report=term-missing` | Behaviour, properties, structural fitness — and the 95% coverage floor |

Individual targets exist for each:

```bash
make format        # rewrite files to the project format
make format-check  # step 1
make lint          # step 2
make typecheck     # step 3
make contracts     # step 4
make test          # step 5, with coverage and the gate
make test-fast     # the suite without coverage — the inner-loop command
make coverage      # HTML report at htmlcov/index.html
make doctor        # astra doctor
make clean         # remove build, cache and coverage artefacts
```

### Step 1 — format

Ruff's formatter, configured with `line-length = 100` and `docstring-code-format = true` (code
blocks inside docstrings are formatted too, so an example that would not run is visible). There is
no black; ruff replaces it.

`make format` rewrites. `make format-check` only reports, which is what the gate and CI run — a CI
job that reformats the tree is a CI job that produces a diff nobody reviewed.

### Step 2 — lint

Ruff with a large `select` list (see `[tool.ruff.lint]` in `pyproject.toml`). Four of those rule
families are not style preferences but project requirements made mechanical:

- **`D`** — a docstring on every public symbol, Google convention.
- **`ANN`** — a type annotation on every signature.
- **`BLE`** — no blind `except`. A bare `except` in a safety path hides faults.
- **`T20`** — no `print()` outside `src/astra/bootstrap/cli.py`.

`per-file-ignores` relaxes exactly two places: `tests/**` (asserts, magic numbers in assertions,
private-member inspection, and no docstring requirement — a test's name is its documentation) and
`cli.py` (`T20`). Adding a third entry to that table is a decision, not a fix; it deserves a
sentence of justification in the diff.

`uv run ruff check --fix .` fixes what is mechanically fixable. Review the result — `--fix` is not
always right about intent.

### Step 3 — type check

```toml
[tool.mypy]
strict = true
files = ["src", "tests"]
```

Strict from commit one, because retrofitting strict typing costs roughly an order of magnitude more
than starting with it, and `astra.contracts` is precisely where a silent type error becomes a
safety defect.

Tests are type-checked too. The single relaxation is `disallow_untyped_defs = false` for `tests.*`,
which keeps test bodies readable while still checking every signature they call.

Two idioms you will meet in the kernel and should not "clean up":

```python
if not isinstance(self.nanoseconds, int) or isinstance(  # type: ignore[redundant-expr]
    self.nanoseconds, bool
):
```

The annotation says `int`, so mypy proves the check redundant and `redundant-expr` flags it. It is
kept anyway, with a narrow, coded ignore and a comment, because instants and covariances are
reconstructed from adapter data and persisted records where the annotation is a *claim about* the
value, not a guarantee. A guard that only runs when the types are already correct guards nothing.

Blanket `# type: ignore` is rejected by `ignore-without-code`. Every ignore names its rule.

### Step 4 — architecture fitness contracts

`.importlinter` holds the contracts. They are in their own file rather than in `pyproject.toml`
because they are a *design* artefact and deserve to be reviewed as one. Five contracts are active:

| Contract | Statement |
|---|---|
| `layers` | `bootstrap` → (`config` \| `observability` \| `invariants`) → `ports` → `contracts` → `kernel`. Strictly acyclic, strictly downward |
| `kernel-independence` | Nothing under `astra.kernel` imports a third-party package |
| `simulator-isolation` | Nothing anywhere in `astra` imports `carla` |
| `si-1-sensor-opacity` | Neither `astra.kernel` nor `astra.invariants` imports `astra.contracts.sensing` |
| `si-10-evidence-non-influence` | Neither `astra.contracts` nor `astra.ports` imports `astra.observability` |

A sixth, `si-5-one-way-core-channel`, is present but commented out: it names layer modules
(`astra.layers.l4_proposer` and the Core-B modules) that arrive in Phases 3 and 4, and
import-linter fails on unknown modules. It is written down rather than omitted-and-forgotten;
activating it is deleting the comment markers.

#### The import-linter gotcha — read this one

```bash
# WRONG. Exits 0 having checked NOTHING.
python -m importlinter.cli lint-imports

# RIGHT. Actually runs the contracts.
lint-imports
```

`importlinter.cli` has no `__main__` guard. Running it with `python -m` imports the module, defines
the click command, reaches the end of the file and exits 0 — silently, with no output. It looks
exactly like a pass.

This is the worst possible failure mode in the one job that guards the module dependency graph and
SI-1/SI-10. A developer who "fixed" a slow CI step by switching to `python -m` would have disabled
architecture enforcement entirely while leaving a green tick in the UI. Reproduce it yourself once,
so you recognise it:

```bash
$ uv run python -m importlinter.cli lint-imports
$ echo $?
0                    # no banner, no contract list, no "Contracts: 5 kept"
```

A real run prints the import-linter banner, `Analyzed N files, M dependencies.`, one line per
contract, and a `Contracts: 5 kept, 0 broken.` summary. **If you do not see that summary, nothing
was checked.**

The Makefile, `.pre-commit-config.yaml` and `.github/workflows/ci.yml` each carry a comment saying
so at the point of invocation. Keep those comments when you edit those files.

As a second line of defence, `tests/architecture/test_layering.py::test_every_import_linter_contract_holds`
runs the contracts through import-linter's API from inside the test suite, so a mis-invoked
`lint-imports` step is still caught by step 5.

### Step 5 — tests

```bash
uv run pytest --cov=astra --cov-report=term-missing
```

Three suites, three jobs:

| Directory | Marker | Purpose |
|---|---|---|
| `tests/unit/` | — | Behaviour of individual modules |
| `tests/property/` | `property` | Hypothesis-driven invariants over the numeric primitives — unit round-trips, matrix symmetry, Cholesky |
| `tests/architecture/` | `architecture` | Fitness tests over the codebase's own structure |

Markers are declared in `pyproject.toml` and `--strict-markers` is on, so a typo in a marker name
is an error rather than a silently unregistered mark. Applied file-wide via
`pytestmark = pytest.mark.architecture` / `pytest.mark.property`.

Running a subset:

```bash
uv run pytest -m architecture              # structural fitness only
uv run pytest -m property                  # Hypothesis only
uv run pytest -m "not property"            # skip the slow ones during an inner loop
uv run pytest tests/unit/test_matrix.py    # one file
uv run pytest -k "cholesky or symmetry"    # by name substring
uv run pytest -x --lf                      # stop at the first failure; rerun last-failed
uv run pytest -q --no-header -p no:cacheprovider   # minimal output
```

The architecture suite is worth knowing by name, because it enforces conventions that no linter
can express:

- `test_no_kernel_module_imports_anything_from_astra_outside_the_kernel`
- `test_no_kernel_module_uses_a_relative_import`
- `test_no_module_in_the_core_imports_the_simulator_client`
- `test_print_is_called_nowhere_except_the_command_line_interface`
- `test_no_non_si_unit_type_appears_in_a_port_signature` — SI units at every interface (ADR-0007)
- `test_the_safety_verdict_has_no_field_whose_name_mentions_trust` — SI-4
- `test_no_layer_other_than_l9_can_construct_an_issued_command` — SI-7
- `test_an_empty_verdict_set_is_a_veto_because_an_uninspected_command_is_not_a_cleared_one` — SI-3

Two pytest settings that will bite you if you do not know about them:

- **`filterwarnings = ["error"]`.** A warning in a safety codebase is a defect, not noise. A
  `DeprecationWarning` from a dependency fails the suite, on purpose — it is the earliest possible
  signal that an upgrade is due.
- **`--import-mode=importlib`** with the `src/` layout. Tests always exercise the *installed*
  package, never a stray copy in the working directory.

#### The coverage gate

```toml
[tool.coverage.report]
fail_under = 95
```

Branch coverage is on. Phase 1 is pure foundation — there is no reason for a line to be untested,
and the gate sits at 95 rather than 100 only to leave room for defensive branches that cannot be
reached without patching the interpreter. Actual coverage is **99.10%**.

`exclude_lines` omits `pragma: no cover`, `if TYPE_CHECKING:`, `raise NotImplementedError`,
`@overload` and `Protocol` class bodies. Reaching for `# pragma: no cover` is allowed and should
carry a comment saying why the line is unreachable. Reaching for it to make a number go up is not.

```bash
make coverage    # HTML report; open htmlcov/index.html
```

---

## Pre-commit

```bash
uv run pre-commit install
```

The hooks are a deliberately chosen *subset* of `make check`: the checks with the best
defects-caught-per-second, plus two slow ones that earn their place.

| Hook | Why |
|---|---|
| `check-added-large-files`, `check-merge-conflict`, `check-toml`, `check-yaml`, `end-of-file-fixer`, `trailing-whitespace`, `mixed-line-ending` | Cheap hygiene |
| `detect-private-key` | A private, patent-pending repository must never grow a committed credential |
| `ruff --fix`, `ruff-format` | Steps 1 and 2 |
| `mypy` (local, `language: system`) | Step 3 |
| `lint-imports` (local, `language: system`) | Step 4 |

The test suite is **not** a pre-commit hook. It runs in CI.

mypy and import-linter run as `language: system` — from the project's own environment rather than
pre-commit's isolated one — because both need the real dependencies and the real module graph to
say anything true. A mypy running against an empty environment reports missing imports, not type
errors.

Both are included despite being slow, because a contract violation discovered after code has been
built on it is a refactor, not a fix.

```bash
uv run pre-commit run --all-files    # run the hooks over the whole tree
git commit --no-verify               # skip them; use sparingly, CI will still fail
```

---

## Adding a new layer (Phase 2 onward)

Phase 1 ships no layer logic on purpose. When L1 or L2 arrives, the order below is not a style
preference — each step makes the next one checkable.

**1. Port first.** Define or confirm the `Protocol` in `src/astra/ports/pipeline.py`. The signature
is a decision about what the layer may see, and the separation invariants live in it: `CommandProposer`
(L4, Core-A) takes state and trust and returns a proposal — it is handed no verdict, no FSM state
and no calibration table, so SI-5 is expressed in the type rather than only in the wiring. No
non-SI unit type may appear here; an architecture test enforces that.

**2. Contracts next.** Add or extend the immutable records the layer exchanges, under
`src/astra/contracts/`. Frozen, `slots=True` dataclasses that validate in `__post_init__` and are
trusted thereafter. If the record needs a numeric guarantee, express it with the existing guards in
`astra.kernel.validation` (`require_finite`, `require_range`, `require_probability`,
`require_dimension`, `require_non_decreasing`) rather than a new one-off check.

**3. Implementation.** New package `src/astra/layers/lN_<name>/`. It imports contracts, ports and
kernel; it does not import a sibling layer, and it constructs nothing concrete — clock, event sink
and repositories arrive as constructor arguments from the composition root.

**4. Tests before wiring.** Every exit criterion in the roadmap is of the form "layer X validated in
isolation before it is wired to anything". The ports are structural protocols, so a five-line fake
in `tests/` satisfies a collaborator with no inheritance and no registration. Add property tests
for anything numeric; that is where hand-written examples systematically miss edge cases.

**5. Wire it in the composition root.** `src/astra/bootstrap/composition.py` is the only module
permitted to name a concrete implementation. Respect the startup order — configuration frozen
first, invariant catalogue verified second, clock third, audit sink last (it is the only step that
touches the filesystem and starts a thread, so anything failing earlier leaves no partial evidence
directory).

**6. Add the import-linter contract, and only then commit.** Whatever the new layer must *not*
reach, write as a `forbidden` contract in `.importlinter`. When the Core-A/Core-B modules land,
uncomment `si-5-one-way-core-channel`. A layer whose isolation is enforced only by review is a
layer whose isolation will not survive a deadline.

**7. Update the invariant catalogue.** If the new code upgrades an invariant's enforcement — SI-6
moves from `REVIEW` to `TEST` when Phase 4's training-signal test exists — change its
`EnforcementKind` in `src/astra/invariants/catalogue.py`. `astra invariants list` must keep telling
the truth.

**8. Write the ADR** if the layer involved a decision with a rejected alternative. See
[`adr/README.md`](adr/README.md).

---

## Debugging a failing architecture contract

When `lint-imports` reports a broken contract it prints the offending import chains. Work through
them in this order.

**1. Read the chain, not just the verdict.** Output looks like:

```
Module layering is acyclic and downward BROKEN

astra.contracts.audit is not allowed to import astra.observability.audit:

-   astra.contracts.audit -> astra.observability.audit (l. 42)
```

The line number is the import statement to look at.

**2. Ask which direction is wrong.** Almost every layering break is one of three things:

- A **type-only import** that should be under `if TYPE_CHECKING:`. This is the most common cause
  and the easiest fix. The kernel and contracts modules use it heavily — `astra.kernel.errors`
  imports `LayerId` that way. Runtime imports are what the contract constrains; annotations are not
  a dependency if they never execute. Add `from __future__ import annotations` (already the house
  style) and move the import.
- A **misplaced module**. The dependency is genuine, and the module is in the wrong package. If
  `contracts` needs something from `observability`, the thing it needs probably belongs in
  `kernel`.
- An **inverted dependency**. The high-level module is being imported by the low-level one. The fix
  is a port: define a `Protocol` in `ports/`, depend on that, and let the composition root supply
  the concrete implementation. This is the fix that keeps `JsonlAuditSink` satisfying `EventSink`
  structurally without inheriting from it.

**3. Do not "fix" it by loosening the contract.** Editing `.importlinter` to permit the import is
occasionally correct and usually not. The contracts encode SI-1, SI-5 and SI-10; weakening one
weakens the safety argument. If the contract really is wrong, that is an ADR, not a one-line diff.

**4. `allow_indirect_imports = False`** on the `kernel-independence` and (future) SI-5 contracts
means a transitive path counts. `kernel → contracts → pydantic` breaks the contract even though no
kernel module names pydantic. The chain output shows the full path.

**5. Reproduce in isolation.** `lint-imports` accepts a single contract by name:

```bash
uv run lint-imports --contract kernel-independence
uv run lint-imports --verbose          # show the graph-building detail
rm -rf .import_linter_cache            # if results look stale
```

**6. If `lint-imports` passes but the architecture test fails**, or vice versa, believe the test.
`tests/architecture/test_layering.py` walks the AST directly and catches things the import graph
does not — a relative import inside the kernel, a `print()` outside the CLI, a `carla` import in a
docstring example.

---

## Conventions: mechanical vs. reviewed

The full list, with rationale, is in [`CONVENTIONS.md`](CONVENTIONS.md). What matters for workflow
is knowing which ones the build will catch for you and which ones it will not.

### Enforced mechanically — the build fails

| Convention | Enforced by |
|---|---|
| Absolute imports only | ruff `TID` (`ban-relative-imports = "all"`) + architecture test |
| Docstring on every public symbol | ruff `D`, Google convention |
| Full type annotations | ruff `ANN` + `mypy --strict` |
| No bare `except` | ruff `BLE` |
| No `print()` outside `cli.py` | ruff `T20` + architecture test |
| No f-strings in logging calls | ruff `G` |
| No naive datetimes | ruff `DTZ` |
| No commented-out code | ruff `ERA` |
| `pathlib` over `os.path` | ruff `PTH` |
| No private-member access across objects | ruff `SLF` |
| Module layering, kernel purity, simulator isolation | import-linter |
| SI units at every port signature | architecture test |
| SI-3 fail-closed aggregation, SI-4, SI-7 | architecture tests + runtime guards |
| 95% coverage | pytest-cov `fail_under` |
| Warnings are errors | pytest `filterwarnings` |

### Enforced by review — nothing will stop you

| Convention | Why it cannot be mechanised |
|---|---|
| **No package facade re-exports.** Import from the defining module | A `__init__.py` re-export is valid Python and valid to every tool |
| **No magic numbers.** A number is an architectural constant (`kernel/constants.py`) or configuration (`config/`) | A linter cannot tell 9 (layer count) from 9.0 (a Mahalanobis gate). The test is: *would a software engineer or a safety engineer review this change?* Software engineer means constant; safety engineer means configuration |
| **Never `assert` for a safety check** | `python -O` deletes it. ruff's `S101` is off in `tests/**` where assert is the point, and a safety-path assert in `src/` reads identically to a legitimate one |
| **Never `time.time()`** — use the injected `Clock` | `astra.kernel.time` imports `time` legitimately, so no blanket ban is possible |
| **Fail closed.** Absence of a verdict is a VETO | Enforced for `Verdict.merge` by test; for new aggregation code, only by review |
| **Every claim traceable.** A number in a report, dashboard or paper comes from a record a run produced | This is the honesty rule. No tool checks it. It is the one that matters most |
| **`EnforcementKind` honesty.** An invariant marked `STATIC` must actually be statically enforced | The catalogue is data; only a human can tell whether it is lying |

---

## Practical inner loop

```bash
make test-fast                # fast feedback while writing
make lint typecheck           # before you think you are done
make check                    # before you push
```

If `make check` is green, CI will be green — that equivalence is the point of the whole
arrangement, and it is worth a bug report when it stops holding.
