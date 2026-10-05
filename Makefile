# Makefile — local CI parity for homeassistant-solax-modbus
#
# Locked quality/baseline checks and dynamic HA compatibility tests.
# HACS and hassfest validation also run in GitHub Actions.

.DEFAULT_GOAL := help

# Run quality checks on the locked baseline's Python.
PYTHON ?= 3.14
export UV_PYTHON := $(PYTHON)
HA_ENVIRONMENT ?= all
HA_SUITE ?= full

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Install dependencies (matching CI) and install pre-commit git hooks
	uv sync --locked --all-groups
	uv run pre-commit install

.PHONY: sync
sync: ## Re-sync dependencies to match uv.lock (fixes local/CI drift)
	uv sync --locked --all-groups

.PHONY: lint
lint: ## Run pre-commit checks (codespell, mypy, ruff, ruff format) on all files
	uv run pre-commit run --all-files --show-diff-on-failure

.PHONY: mypy
mypy: ## Run mypy in strict mode (same as CI)
	uv run mypy custom_components/solax_modbus tests --strict

.PHONY: format
format: ## Auto-fix lint issues and format code (ruff)
	uv run ruff check --fix custom_components/solax_modbus tests
	uv run ruff format custom_components/solax_modbus tests

.PHONY: test
test: ## Run the quick test suite (non-slow tests, same as CI 'Test Quick')
	uv run pytest -m "not slow"

.PHONY: test-all
test-all: ## Run the full test suite on the locked baseline
	uv run pytest

.PHONY: check
check: ## Fast local gate: lint + mypy + quick tests (no dependency re-sync)
	uv run pre-commit run --all-files --show-diff-on-failure
	uv run pytest -m "not slow"

.PHONY: ci
ci: ## Locked baseline checks: sync + lint + mypy + quick tests
	uv sync --locked --all-groups
	uv run pre-commit run --all-files --show-diff-on-failure
	uv run pytest -m "not slow"

.PHONY: ci-full
ci-full: ## Locked baseline checks including the full test suite
	uv sync --locked --all-groups
	uv run pre-commit run --all-files --show-diff-on-failure
	uv run pytest

.PHONY: test-ha
test-ha: ## Dynamic CI HA matrix (HA_ENVIRONMENT=all/minimum/current, HA_SUITE=full/quick)
	uv run --no-project --python 3.12 -m scripts.run_ha_tests --environment $(HA_ENVIRONMENT) --suite $(HA_SUITE)
