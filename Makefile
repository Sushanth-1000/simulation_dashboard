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
.PHONY: help install format format-check lint typecheck contracts test test-fast coverage check clean doctor lockfile verify-install artifacts artifacts-check

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

blobsize: ## Refuse any file large enough to make the branch unpushable
	@# GitHub rejects any blob over 100 MB, and it rejects it at *push* time --
	@# by which point the offending commit is history and only a rewrite gets it
	@# out. That happened here: a `str.replace` accident on 6 August 2026 blew
	@# docs/PENDING.md from 63 KB to 210 MB, the file was repaired two commits
	@# later, and the branch was silently unpushable for four days because the
	@# blob stayed in history. Removing it took a filter-branch over forty
	@# commits and moved twenty-six hashes.
	@#
	@# Scanned from the *filesystem*, not from `git ls-files`. The first version
	@# of this target used git, which meant it passed vacuously wherever the
	@# tree is not a git repository -- and the tree rsynced into WSL, which is
	@# where this gate actually runs, is exactly that. It reported success
	@# having checked nothing, which is the same silent false pass the
	@# `contracts` target above carries a warning about.
	@#
	@# The ceiling is 5 MB, far below GitHub's, because nothing here has any
	@# business being larger: the biggest tracked file is uv.lock at 0.31 MB.
	@# A limit set just under the one that bites gives no warning; this one
	@# complains while the mistake is still a working-tree change.
	@bad=$$(find . -type f -size +5M 		-not -path './.git/*' -not -path './.venv/*' 		-not -path '*/__pycache__/*' -not -path './.mypy_cache/*' 		-not -path './.pytest_cache/*' -not -path './.ruff_cache/*' 		-not -path './htmlcov/*' -not -path './var/soak/*' 		-not -path './var/faults/*' -not -path './var/ablation/*' 		-not -path './var/comparison/*' -not -path './var/effectiveness/*' 		-not -path './var/flake/*' 2>/dev/null); 	if [ -n "$$bad" ]; then 		echo "files over 5 MB -- committing one puts it in history for ever:"; 		for f in $$bad; do ls -lh "$$f" | awk '{print "  " $$5 "	" $$NF}'; done; 		exit 1; 	fi

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

coverage-floor: ## Refuse any single module far below the aggregate gate
	@# The 95% gate is an AGGREGATE, so a new module can ship at 10% and pass,
	@# carried by everything around it. That happened on 11 August 2026:
	@# `astra explain` landed with no tests at all, at 10.3%, and the gate was
	@# green -- the aggregate moved by less than a tenth of a point. See
	@# tools/coverage_floor.py for why the floor sits well below the gate.
	$(RUN) pytest --cov=astra --cov-report=json:.coverage.json -q > /dev/null
	$(RUN) python tools/coverage_floor.py .coverage.json


artifacts-check: ## Refuse an evidence run whose artefacts are absent or do not drive
	@# Presence is not the check -- DRIVING is. On 15 August a benchmark fell
	@# back to a policy that left the vehicle stationary with every tick vetoed,
	@# and published a retraction of a correct finding off the result (E-143,
	@# E-144). A missing artefact raises; a non-driving one produces numbers.
	$(RUN) python -m tools.check_artifacts

artifacts: ## Regenerate the twin, the calibration corpus and the policy, in order
	@# ORDER IS LOAD-BEARING. The corpus is generated *through* the twin and the
	@# policy is trained against both, so running these out of order produces a
	@# mismatched set that loads cleanly and measures nothing.
	@#
	@# This is the command that did not exist until 15 August 2026. The steps
	@# lived only in a status document from 31 July and nothing regenerated or
	@# verified them. `var/` is gitignored by design, so a CLEAN CHECKOUT has no
	@# artefacts at all while every [M-syn] row is measured through all three.
	@#
	@# The policy is the long pole -- 48 rounds x 16,384 steps. Expect this to
	@# run for hours, and run it before you need it rather than during a demo.
	@# All three as `-m`. `training` is deliberately not installed, so it
	@# resolves only from the repo root on sys.path -- which `-m` provides and a
	@# script path does not. Running them by path fails with ModuleNotFoundError.
	$(RUN) python -m training.train_twin
	$(RUN) python -m training.generate_calibration
	$(RUN) python -m training.train_policy
	@$(MAKE) --no-print-directory artifacts-check

check: blobsize lockfile format-check lint typecheck contracts test coverage-floor ## The full quality gate, exactly as CI runs it
	@echo ""
	@echo "  quality gate: PASSED"

clean: ## Remove build, cache and coverage artefacts
	rm -rf build dist htmlcov .coverage .coverage.* .mypy_cache .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -not -path './.venv/*' -prune -exec rm -rf {} +
