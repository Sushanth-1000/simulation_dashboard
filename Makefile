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

.DEFAULT_GOAL := help
.PHONY: help install format format-check lint typecheck contracts test test-fast coverage check clean doctor

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

test: ## Run the test suite with coverage and the 95% gate
	$(RUN) pytest --cov=astra --cov-report=term-missing

test-fast: ## Run the test suite without coverage
	$(RUN) pytest -q

coverage: ## Write an HTML coverage report to htmlcov/
	$(RUN) pytest --cov=astra --cov-report=html --cov-report=term
	@echo "report: htmlcov/index.html"

doctor: ## Report on this installation, as `astra doctor` does
	$(RUN) astra doctor

check: format-check lint typecheck contracts test ## The full quality gate, exactly as CI runs it
	@echo ""
	@echo "  quality gate: PASSED"

clean: ## Remove build, cache and coverage artefacts
	rm -rf build dist htmlcov .coverage .coverage.* .mypy_cache .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -not -path './.venv/*' -prune -exec rm -rf {} +
