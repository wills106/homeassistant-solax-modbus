# Makefile — local CI parity for homeassistant-solax-modbus
#
# Every target mirrors the exact commands run by the GitHub Actions
# workflow (.github/workflows/ci-cd.yml). If `make ci` passes locally,
# the CI pipeline will pass.

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Install dependencies (matching CI) and install pre-commit git hooks
	uv sync --all-groups
	uv run pre-commit install

.PHONY: sync
sync: ## Re-sync dependencies to match uv.lock (fixes local/CI drift)
	uv sync --all-groups

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
test-all: ## Run the full test suite (same as CI 'Test Comprehensive')
	uv run pytest

.PHONY: check
check: ## Fast local gate: lint + mypy + quick tests (no dependency re-sync)
	uv run pre-commit run --all-files --show-diff-on-failure
	uv run mypy custom_components/solax_modbus tests --strict
	uv run pytest -m "not slow"

.PHONY: ci
ci: ## Full CI pipeline locally: sync + lint + mypy + quick tests
	uv sync --all-groups
	uv run pre-commit run --all-files --show-diff-on-failure
	uv run mypy custom_components/solax_modbus tests --strict
	uv run pytest -m "not slow"

.PHONY: ci-full
ci-full: ## Full CI pipeline locally including the comprehensive test suite
	uv sync --all-groups
	uv run pre-commit run --all-files --show-diff-on-failure
	uv run mypy custom_components/solax_modbus tests --strict
	uv run pytest
