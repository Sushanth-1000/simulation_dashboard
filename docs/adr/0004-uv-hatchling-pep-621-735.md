# ADR-0004: uv + hatchling + PEP 621/735 for build and dependency management

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

The Prototype & Demo Plan's proposed layout has no packaging at all — a set of directories and an
implicit `python main.py`. That does not survive contact with the requirements this project carries.

Three of those requirements bear directly on tooling.

**Reproducibility is a safety property here, not a convenience.** Assumption A-3 makes the audit
log a certification artefact; a certification artefact produced by an environment nobody can
reconstruct is worth very little. "It worked on my machine" is an acceptable answer in most
projects and not in this one.

**Every dependency must eventually be justified.** ISO 26262 §8-12 covers qualification of software
components. The bar for adding a runtime dependency to the safety pipeline is therefore high, and
the toolchain must make the dependency set visible and auditable rather than incidental.

**Development tooling must not be installable by a downstream consumer.** ruff, mypy and pytest are
not features of ASTRA. If they are reachable through `pip install astra[dev]`, they are part of the
distributed surface.

The project also has a mixed-experience team and a CI job that runs on every commit, so resolution
speed and a single obvious command matter more than marginal per-tool configurability.

## Decision

**uv** for interpreter installation, virtual environments, dependency resolution, the lockfile and
task running. **hatchling** as the PEP 517 build backend. **PEP 621** `[project]` metadata and
**PEP 735** `[dependency-groups]` for development dependencies.

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
requires-python = ">=3.12"
dependencies = ["pydantic>=2.9,<3", "pydantic-settings>=2.6,<3"]

[dependency-groups]
lint = ["ruff>=0.8", "mypy>=1.13", "import-linter>=2.1"]
test = ["pytest>=8.3", "pytest-cov>=6.0", "hypothesis>=6.115"]
dev  = [{ include-group = "lint" }, { include-group = "test" }, "pre-commit>=4.0"]
```

Supporting decisions that come with it:

- **`pyproject.toml` is the single source of truth** for how the project is built, linted,
  type-checked and tested. Every tool in the quality gate is configured there rather than in a
  per-tool dotfile, so a reviewer can audit the entire engineering standard from one artefact. Two
  deliberate exceptions: `.importlinter`, because the architecture contracts are a *design* artefact
  and deserve their own reviewable file, and `.pre-commit-config.yaml`, whose schema pre-commit owns.
- **`src/` layout**, `[tool.hatch.build.targets.wheel] packages = ["src/astra"]`. Mandatory rather
  than stylistic: it makes importing `astra` from the repository root impossible by accident, so the
  test suite always exercises the *installed* package. Without it, a missing entry in the wheel is
  invisible until deployment.
- **Two runtime dependencies only** in Phase 1, both used exclusively at the configuration boundary.
- **No `[project.optional-dependencies]` table.** Empty extras are noise. Later phases add
  `[estimation]`, `[learning]`, `[simulation]`, `[dashboard]` when they have contents.
- **`"Private :: Do Not Upload"`** in the classifiers, as a hard guard against accidental PyPI
  publication of a patent-pending repository (ADR-0014).
- **`uv.lock` is committed**, and CI sets `UV_FROZEN=1` so a stale lockfile fails the build rather
  than being silently regenerated.
- **uv is not load-bearing.** Everything is a standard PEP 517/621 package invoked through standard
  console scripts. The Makefile's `RUN ?= uv run` is the only place the toolchain is named, and
  clearing it (`make check RUN=`) runs the identical gate from any environment on `PATH`.

## Alternatives considered

**Poetry.** Rejected. Historically required Poetry-specific metadata rather than PEP 621, and its
resolver is materially slower — which matters when CI runs the full gate on every commit across two
interpreter versions. Poetry has since moved toward the standards, but the migration history means
tutorials and existing projects are split across two dialects, which is precisely the confusion this
project does not need.

**pip + `requirements.txt`.** Rejected. No lockfile in any meaningful sense (a pinned requirements
file records versions but not hashes or the resolution that produced them), no interpreter
management, and no separation between runtime and development dependencies that a downstream
consumer cannot cross. Reproducibility would rest on discipline.

**conda / mamba.** Rejected. Heavyweight, a second package universe alongside PyPI, and its main
advantage — binary scientific packages — is not needed in Phase 1 and is largely solved by wheels
for the Phase 4 stack.

**setuptools as the build backend.** Rejected. It carries a large legacy surface (`setup.py`,
`setup.cfg`, two decades of behaviour that PEP 621 does not describe). hatchling reads the
`[project]` table verbatim with no second dialect.

**poetry-core as the build backend without Poetry.** Rejected as a needless coupling to another
tool's ecosystem for no gain over hatchling.

**`[project.optional-dependencies.dev]` instead of PEP 735 groups.** Rejected. An extra is part of
the published distribution's metadata: `pip install astra[dev]` would work for a downstream
consumer, which makes the test and lint toolchain part of ASTRA's public surface. Dependency groups
are local to the source tree and cannot be installed from a built wheel — which is exactly the
property wanted.

**Flat layout instead of `src/`.** Rejected. Under a flat layout the tests import the working
directory, not the wheel, and a packaging mistake surfaces at deployment.

## Consequences

### Positive

- One tool covers interpreter, environment, resolution, lockfile and task running. Onboarding is
  `uv sync --all-groups`, and there is no activation step to forget.
- `uv.lock` plus `UV_FROZEN=1` in CI makes the environment reproducible, which is what lets a run's
  evidence be attributed to a specific dependency set.
- PEP 735 groups keep the development toolchain out of the distributed package entirely.
- Fast resolution is not a vanity metric when the gate runs on every commit across two interpreters.
- `pyproject.toml` as the single configuration artefact means the engineering standard is reviewable
  in one file — genuinely useful when the reviewer is not a full-time Python engineer.
- The two-dependency runtime surface is small enough that ISO 26262 §8-12 qualification is a
  tractable conversation rather than an inventory exercise.

### Negative / accepted trade-offs

- **uv is a young tool.** It moves fast, and fast-moving tools have breaking changes. The project's
  exposure is limited by uv not being load-bearing — but "limited" is not "none", and a uv
  regression would still stop the primary documented workflow.
- **uv is another thing to install**, and on locked-down or air-gapped machines it may not be
  installable at all. The venv fallback exists precisely for that, and it is a genuinely worse
  experience: pip resolves fresh, so tool versions drift from what CI runs, and a lint rule added in
  a newer ruff can fail locally and pass in CI or the reverse.
- **Two ways to run the gate is two things to keep working.** `make check` and
  `make check RUN=` must both stay correct, and only the first is exercised by CI. The second is
  documented and manually verified rather than continuously tested — which is how it will break.
- **PEP 735 is recent.** Some tooling does not yet understand `[dependency-groups]`, so an IDE or a
  security scanner may report the development dependencies as absent.
- **The `src/` layout requires the package to be installed** before anything works, which surprises
  people who expect `python -m astra` to run from a fresh clone. That is the intended behaviour and
  it will still generate confused questions.
- **A committed lockfile is a maintenance obligation.** It goes stale, Dependabot-style updates are
  a recurring chore, and `UV_FROZEN=1` guarantees that forgetting to run `uv lock` breaks CI rather
  than being papered over.
