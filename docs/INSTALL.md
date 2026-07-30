# Installation

Setting up an environment that can run ASTRA's quality gate. Phase 1 needs an interpreter, a
package manager and about two hundred megabytes of disk. It does not need a simulator, a GPU or
any part of the ML stack — see [What Phase 1 does *not* require](#what-phase-1-does-not-require).

---

## 1. Requirements

| | |
|---|---|
| **Python** | 3.12 or newer (3.12 is the declared floor; CI also runs 3.13) |
| **Package manager** | [uv](https://docs.astral.sh/uv/) — the declared toolchain (ADR-0004) |
| **Operating system** | Any that CPython 3.12 supports. Developed on macOS/arm64 and Linux/x86-64; CI runs `ubuntu-latest` |
| **Disk** | ~200 MB for the interpreter, the virtual environment and the tool caches |
| **Network** | Needed once, to resolve and download dependencies |

Phase 1's runtime dependency set is two packages — `pydantic` and `pydantic-settings` — and both
are used only at the configuration boundary. Everything else in the environment is development
tooling.

### Why the Python 3.12 floor

The source documents specify Python 3.10+. That floor was raised deliberately, and the reasoning
is recorded in [ADR-0003](adr/0003-python-312-floor-simulator-behind-a-port.md):

- **PEP 695 type parameter syntax.** ASTRA is an interface-heavy architecture whose central
  abstraction is a generic sensor payload — `class SensorSample[PayloadT]` — and whose
  configuration schema uses `type` alias statements (`type UnitInterval = Annotated[float, ...]`
  in `src/astra/config/schema.py`). Both are 3.12 syntax. On 3.11 they require the older
  `TypeVar` plus `Generic` spelling, which is more code saying less.
- **`typing.override`.** Used throughout the kernel (`errors.py`, `identifiers.py`,
  `time.py`). Combined with mypy's `explicit-override` error code, it turns "this method was meant
  to override something" from a comment into a checked claim. Available from 3.12.
- **Security support to October 2028.** Python 3.10 reaches end of life in October 2026, which is
  before this project's own horizon. Starting on an interpreter that dies mid-project is a
  scheduled migration nobody budgeted for.

3.13 and 3.14 were not chosen as the floor because the ML stack this project acquires in Phase 4
(PyTorch, Stable-Baselines3, FilterPy) historically lags new interpreter releases. That is
assumption A-6 in [`ASSUMPTIONS.md`](ASSUMPTIONS.md), and CI runs a 3.13 job specifically as an
early warning.

---

## 2. Install uv

uv provides the interpreter, the virtual environment, dependency resolution, the lockfile and the
task runner in one binary. Pick whichever of these fits your machine:

```bash
# macOS / Linux — standalone installer
curl -LsSf https://astral.sh/uv/install.sh | sh

# macOS — Homebrew
brew install uv

# Windows — PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Any platform, if you already have a Python
pipx install uv
```

Confirm it is on your `PATH`:

```bash
uv --version
```

If the shell cannot find `uv` after installation, open a new shell — the installer appends to your
profile, and the current session does not re-read it.

---

## 3. Install the project

```bash
git clone <repository-url> astra
cd astra
uv sync --all-groups --all-extras
```

`uv sync --all-groups --all-extras` does four things:

1. Reads `requires-python = ">=3.12"` from `pyproject.toml` and downloads a matching interpreter if
   the machine has none.
2. Creates `.venv/` in the repository root.
3. Installs the locked dependency set from `uv.lock` — the two runtime packages, every
   [PEP 735](https://peps.python.org/pep-0735/) dependency group (`lint`, `test`, `dev`), and every
   extra (`estimation`).
4. Installs `astra` itself in editable mode, which is what makes the `astra` console script and the
   `src/` layout work together.

**Both flags matter, for different reasons.**

`--all-groups` installs the development tooling. Without it you get the runtime dependencies only,
and every tool in the quality gate is missing.

`--all-extras` installs NumPy and FilterPy. Without it the install still succeeds — and then `mypy`
reports dozens of errors and `pytest` cannot collect `tests/unit/test_l2_filter.py`,
`tests/integration/test_phase2_pipeline.py` or `tests/integration/test_phase3_safety_spine.py`,
because `astra.layers.l2_estimation.filter` imports NumPy. Those dependencies sit in the
`[estimation]` extra rather than in `dependencies` so that the kernel and contracts stay importable
without the numerical stack, which is the property the `kernel-independence` and
`contracts-independence` architecture contracts exist to defend.

You do **not** need to activate the environment. `uv run <command>` resolves the command from the
locked environment:

```bash
uv run astra doctor
uv run pytest
```

Activating still works if you prefer it (`source .venv/bin/activate`), but every command in this
documentation is written in the `uv run` form because it is the one that cannot pick up the wrong
interpreter.

### Optional: install the pre-commit hooks

```bash
uv run pre-commit install
```

This is not required to build or test, but it moves most gate failures from CI to your commit.
See [`DEVELOPMENT.md`](DEVELOPMENT.md#pre-commit).

---

## 4. Fallback: a plain virtual environment

uv is the declared toolchain, but nothing in the codebase depends on it — the project is a standard
PEP 517/621 package and every tool is a normal console script. Where uv cannot be installed (a
locked-down machine, an air-gapped build box, a corporate proxy that blocks the installer), a plain
virtual environment works:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[estimation]"
.venv/bin/python -m pip install \
    ruff mypy import-linter \
    pytest pytest-cov hypothesis \
    pre-commit
```

The `[estimation]` extra is not optional in practice: it carries NumPy and FilterPy, without which
the estimation layer will not import and three test modules cannot be collected.

Then run the gate with `RUN` cleared, so the Makefile takes each tool from `PATH` instead of
prefixing it with `uv run`:

```bash
PATH=.venv/bin:$PATH make check RUN=
# or, having activated:
source .venv/bin/activate && make check RUN=
```

The Makefile documents both paths in its header, and `RUN ?= uv run` is the only place the
toolchain choice appears.

**What you lose by taking this path**, stated plainly:

| | uv | plain venv |
|---|---|---|
| Dependency versions | Pinned by `uv.lock` | Resolved by pip at install time — you may get newer tools than CI runs |
| Interpreter | Installed and pinned by uv | Whatever `python3.12` is on the machine |
| Reproducibility against CI | Exact | Approximate |

The practical consequence is that a lint rule added in a newer ruff release can fail locally and
pass in CI, or the reverse. Treat CI as authoritative when the two disagree, and pin the tool
versions in your pip install line if the drift becomes annoying.

---

## 5. Verify the installation

```bash
uv run astra doctor
```

`astra doctor` is a genuine smoke test of the composition root, not a printout: it loads and
validates the configuration, verifies the separation-invariant catalogue, checks that the evidence
directory is writable, and **exits non-zero if anything would prevent a run**. CI runs it for
exactly that reason.

A healthy installation reports, in sections: the interpreter and platform; the architecture
cardinalities (9 layers, 3 Core-B gates, 4 feedback loops, the config and audit schema versions);
the invariant catalogue with its enforcement counts; the resolved environment, its configuration
hash and the files it came from; whether the evidence directory is writable; and a final
`OK  this installation can start a run.`

Two more commands worth running once, to see what the system thinks it is:

```bash
uv run astra config show      # the effective, fully-resolved configuration and its hash
uv run astra invariants list  # SI-1 … SI-10 with honest enforcement status
```

`astra invariants list` prints one invariant marked `[REVIEW]` — SI-6, veto-rate exclusion. That is
correct and deliberate: the component it constrains (Core-A's training signal) does not exist until
Phase 4, and the catalogue reports what is actually enforced rather than what is intended.

Finally, run the gate itself:

```bash
make check
```

Expect: format check, lint, type check, architecture contracts and the test suite, in that order,
ending in `quality gate: PASSED`.

---

## 6. Configuration

ASTRA resolves configuration from three layers, lowest precedence first:

1. `config/astra.defaults.toml` — packaged defaults. **Non-safety values only.**
2. `config/environments/<environment>.toml` — the operating point. One of `development`,
   `simulation`, `certification`.
3. `ASTRA_*` environment variables, nested with a double underscore
   (`ASTRA_GATE__SIGNIFICANCE_EPSILON=0.05`).

The default environment is `development`. Select another with `ASTRA_ENVIRONMENT`, or per command
with `--environment`:

```bash
uv run astra config show --environment simulation
```

Copy `.env.example` to `.env` for local overrides. `.env` is gitignored and must stay that way.

### The `certification` environment fails to load — on purpose

```bash
uv run astra config show --environment certification
```

raises `ConfigurationError [ASTRA-CFG-001]`. This is not a broken installation. Every safety
threshold in `config/environments/certification.toml` is commented out rather than pre-filled,
because those parameters have no defensible default (assumption A-4). A certification run must not
be able to proceed under numbers nobody chose and nobody signed off. See
[`ASSUMPTIONS.md`](ASSUMPTIONS.md#a-4--safety-thresholds-have-no-defensible-default).

`development` and `simulation` both load, and both carry a banner at the top of the file stating
that their values are provisional and that nothing produced under them may be reported as a result.

---

## 7. What Phase 1 does *not* require

Phase 1 is foundation: kernel vocabulary, layer contracts, ports, the separation-invariant
catalogue, configuration, audit logging, the composition root and the quality gate. It contains no
layer logic at all. Consequently none of the following is needed, and none of it is installed:

| Not needed | Arrives in |
|---|---|
| CARLA or any other simulator | Phase 2, behind an adapter — the core never imports it (ADR-0003) |
| A GPU, CUDA or any accelerator | Phase 4, for PPO training |
| PyTorch, Stable-Baselines3 | Phase 3/4 (`[learning]` extra) |
| NumPy, FilterPy | Phase 2 (`[estimation]` extra) — and never inside `src/astra/kernel/` (ADR-0011) |
| FastAPI, uvicorn, a browser | Phase 8, the dashboard (`[dashboard]` extra) |
| A database or message broker | Not planned. Evidence is append-only JSONL (ADR-0013) |

The kernel's dependency-free property is enforced, not merely intended: the
`kernel-independence` contract in `.importlinter` fails the build if anything under
`src/astra/kernel/` imports a third-party package. That is what lets an offline evidence-analysis
tool or a certification script import ASTRA's vocabulary without installing the numerical stack.

---

## 8. Troubleshooting

**`uv: command not found` after installing uv**
The installer appends to your shell profile; the running shell has already read it. Open a new
shell, or `source ~/.bashrc` / `~/.zshrc`.

**`error: The lockfile is not up to date` / `UV_FROZEN` failures**
CI sets `UV_FROZEN=1` so a stale lockfile fails rather than being silently regenerated. Locally,
run `uv lock` after changing dependencies in `pyproject.toml`, and commit the resulting `uv.lock`.

**`ModuleNotFoundError: No module named 'astra'`**
Either the environment was created without installing the project (`uv sync` installs it; a bare
`pip install -r` does not), or you are running a system Python instead of the environment's. The
`src/` layout makes this fail loudly by design — `astra` is not importable from the repository root
unless it is installed. Check with `uv run python -c "import astra; print(astra.__file__)"`.

**`astra: command not found`**
The console script comes from installing the project itself. Re-run
`uv sync --all-groups --all-extras`, or in the venv fallback `pip install -e ".[estimation]"`.

**`ruff` or `mypy` not found**
The dependency groups were not installed. `uv sync --all-groups --all-extras` — the `--all-groups`
flag is what pulls in `lint`, `test` and `dev`.

**`ModuleNotFoundError: No module named 'numpy'`, or mypy reporting dozens of
`no-any-unimported` errors**
The `estimation` extra was not installed. Re-run `uv sync --all-groups --all-extras`; the
`--all-extras` flag is what pulls in NumPy and FilterPy. The symptom is three test modules failing
to collect (`test_l2_filter.py`, `test_phase2_pipeline.py`, `test_phase3_safety_spine.py`) rather
than a failure at install time, because the estimation layer's dependencies deliberately sit outside
`dependencies` — see §3.

**`lint-imports` cannot find the `astra` package**
import-linter builds a real module graph by importing the root package named in `.importlinter`, so
`astra` must be installed and importable. Same fix as `ModuleNotFoundError` above.

**`python -m importlinter.cli lint-imports` prints nothing and exits 0**
It checked nothing. That module has no `__main__` guard. Always invoke the `lint-imports` console
script. This is the single most dangerous false pass in the toolchain and is documented at length
in [`DEVELOPMENT.md`](DEVELOPMENT.md#the-import-linter-gotcha-read-this-one).

**`astra doctor` reports the evidence directory is not writable**
The directory comes from `observability.log_directory`, `var/runs` by default, resolved relative to
the working directory. Either run from the repository root or set
`ASTRA_OBSERVABILITY__LOG_DIRECTORY` to a path you can write.

**A test fails with `filterwarnings: error`**
Not a test-harness problem. `pyproject.toml` sets `filterwarnings = ["error"]` because a warning in
a safety codebase is a defect, not noise. Read the warning and fix its cause; do not add an ignore
without recording why.

**Coverage fails at 95% but all tests pass**
`fail_under = 95` is part of the gate. Add the missing tests, or — if the line genuinely cannot be
reached without patching the interpreter — mark it `# pragma: no cover` with a comment saying why.

**Everything passes locally, CI fails (or the reverse)**
Most likely tool-version drift from the plain-venv fallback (§4). Compare `uv run ruff --version`
against the version CI resolved, and prefer the locked environment for anything you intend to push.
