#
# ASTRA — developer task runner
#
# `make check` is the quality gate. It runs exactly what CI runs, in the same
# order, so a green local run means a green pipeline. That equivalence is the
# whole point: a gate developers cannot reproduce locally is a gate they learn
# to ignore.
#
# Ordering is deliberate — cheapest and most-likely-to-fail first, so a broken
# commit fails in seconds rather than after the full test suite.
#
# One CI step is deliberately *not* in `check`: `verify-install`, which builds a
# throwaway virtualenv. It is tens of seconds, and a gate that slow is a gate
# people stop running. That is a real gap in the equivalence claimed above, so
# it is named here rather than left for someone to discover: run it before
# pushing, and always after touching dependencies or the package layout.
#

# uv is the project's declared toolchain (ADR-0004): `uv run <tool>` resolves
# the tool from the locked environment without anything needing to be activated.
#
# Where uv is unavailable, activate an environment that already has the
# development dependencies and clear RUN so the tools are taken from PATH:
#
#     source .venv/bin/activate && make check RUN=
#     # or, without activating:
#     PATH=.venv/bin:$PATH make check RUN=
#
RUN ?= uv run
PYTHON ?= $(RUN) python

# Where `verify-install` builds its throwaway environment. Outside the tree so
# that a half-built one cannot be collected by pytest or type-checked by mypy.
BARE_VENV ?= /tmp/astra-bare

# Mirrors the CI step of the same name. Kept as one variable rather than inline
# so the recipe stays readable and the assertions stay quotable.
define BARE_IMPORT_CHECK
import sys
import astra.kernel.matrix, astra.kernel.units, astra.kernel.enums
import astra.contracts.audit, astra.contracts.governance
assert 'numpy' not in sys.modules, 'the kernel or contracts pulled in NumPy'
assert 'torch' not in sys.modules, 'the kernel or contracts pulled in torch'
print('kernel and contracts import cleanly without the numerical stack')
endef
export BARE_IMPORT_CHECK

.DEFAULT_GOAL := help
.PHONY: help install format format-check lint typecheck contracts test test-fast coverage check clean doctor lockfile verify-install

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create the environment and install everything
	uv sync --all-groups --all-extras

format: ## Rewrite files to the project's format
	$(RUN) ruff format .

format-check: ## Verify formatting without rewriting
	$(RUN) ruff format --check .

lint: ## Static lint
	$(RUN) ruff check .

typecheck: ## Strict type checking
	$(RUN) mypy

contracts: ## Architecture fitness contracts (import-linter)
	@# NOTE: invoke the console script, never `python -m importlinter.cli`.
	@# That module has no __main__ guard, so `python -m` exits 0 having checked
	@# nothing — a silent false pass in the one job that guards the module
	@# dependency graph and SI-1/SI-10.
	$(RUN) lint-imports

lockfile: ## Verify uv.lock is current with pyproject.toml
	@# The lockfile went stale twice, and both times a *training run* found it
	@# rather than the gate -- because this check lived only in CI, which is to
	@# say it ran after the commit that broke it. It costs well under a second,
	@# so it goes first.
	@#
	@# Skipped rather than failed where uv is absent, because `make check RUN=`
	@# is a documented path for environments without it. Saying so out loud
	@# matters: a check that can quietly not run is worse than no check.
	@if command -v uv >/dev/null 2>&1; then \
		uv lock --check; \
	else \
		echo "  uv.lock NOT VERIFIED - uv is not on PATH"; \
	fi

verify-install: ## From-scratch frozen install of what a consumer actually gets
	@# Deliberately not part of `check`: it builds a virtualenv, which is tens of
	@# seconds, and a gate that slow is a gate people stop running. Run it before
	@# pushing, and after touching dependencies or the package layout.
	@#
	@# `--no-deps` plus only pydantic: this installs *no* numerical stack, so a
	@# stray `import numpy` anywhere under kernel/ or contracts/ fails here as an
	@# ImportError. That is the enforcement behind the claim that an offline
	@# evidence tool can read an audit archive without NumPy or torch -- which
	@# import-linter cannot check, because it is a property of the installed
	@# distribution rather than of the source graph.
	uv venv --python 3.12 $(BARE_VENV)
	VIRTUAL_ENV=$(BARE_VENV) uv pip install --no-deps .
	VIRTUAL_ENV=$(BARE_VENV) uv pip install pydantic pydantic-settings
	$(BARE_VENV)/bin/python -c "$$BARE_IMPORT_CHECK"
	@rm -rf $(BARE_VENV)
	@echo ""
	@echo "  frozen install: OK"

test: ## Run the test suite with coverage and the 95% gate
	$(RUN) pytest --cov=astra --cov-report=term-missing

test-fast: ## Run the test suite without coverage
	$(RUN) pytest -q

coverage: ## Write an HTML coverage report to htmlcov/
	$(RUN) pytest --cov=astra --cov-report=html --cov-report=term
	@echo "report: htmlcov/index.html"

doctor: ## Report on this installation, as `astra doctor` does
	$(RUN) astra doctor

check: lockfile format-check lint typecheck contracts test ## The full quality gate, exactly as CI runs it
	@echo ""
	@echo "  quality gate: PASSED"

clean: ## Remove build, cache and coverage artefacts
	rm -rf build dist htmlcov .coverage .coverage.* .mypy_cache .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -not -path './.venv/*' -prune -exec rm -rf {} +
