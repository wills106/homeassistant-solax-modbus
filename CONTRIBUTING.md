# Contributing to SolaX Modbus

Thank you for contributing! This document explains how to set up your
development environment and — most importantly — how to make sure your
changes pass the same checks that run in CI **before** you open a pull
request.

> **Why this matters:** the CI pipeline runs mypy in *strict* mode, ruff
> linting/formatting, codespell, HACS and hassfest validation, and the full
> test suite. A single missing type annotation (e.g. `no-untyped-def`) will
> fail the build. Running the checks locally first saves everyone time.

## Prerequisites

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/) — the package manager used by this project
- `make` (for the convenience targets below)

## Setup

```bash
git clone <repo-url>
cd homeassistant-solax-modbus

# Install all dependencies (dev + test groups) exactly as CI does,
# and install the pre-commit git hooks so checks run on every commit.
make setup
```

`make setup` is equivalent to:

```bash
uv sync --all-groups
uv run pre-commit install
```

The `pre-commit install` step registers a git hook that runs codespell, mypy,
ruff and ruff-format automatically on every `git commit`, blocking the commit
if any check fails.

## Before pushing / opening a PR

Run the full CI pipeline locally. If this passes, CI will pass:

```bash
make ci
```

For faster iteration while developing (skips the dependency re-sync):

```bash
make check
```

### Individual targets

| Command        | What it does                                                        |
| -------------- | ------------------------------------------------------------------- |
| `make sync`    | Re-sync dependencies to match `uv.lock` (fixes local/CI drift)      |
| `make lint`    | Run all pre-commit checks (codespell, mypy, ruff, ruff format)      |
| `make mypy`    | Run mypy in strict mode                                             |
| `make format`  | Auto-fix lint issues and format code with ruff                      |
| `make test`    | Run the quick test suite (`pytest -m "not slow"`)                   |
| `make test-all`| Run the full test suite                                             |
| `make check`   | lint + mypy + quick tests (fast local gate)                         |
| `make ci`      | Full CI pipeline: sync + lint + mypy + quick tests                  |
| `make ci-full` | Full CI pipeline including the comprehensive test suite             |

## Keeping your environment in sync with CI

The most common cause of "works in CI but not locally" (or vice versa) is a
drifted local environment. If you ever see unexpected mypy or import errors,
re-sync first:

```bash
make sync
```

This reinstalls the exact pinned versions from `uv.lock`, which is the single
source of truth for dependency versions.

## Code style

- **mypy strict mode** is enforced — every function needs full type
  annotations (parameters *and* return type). See
  [`pyproject.toml`](pyproject.toml) for the exact configuration.
- **ruff** handles linting and formatting (line length 150, double quotes).
  Run `make format` to auto-fix most issues.
- Follow the existing patterns in the codebase, especially for typed mocks in
  tests (e.g. `def handler(identifiers: Any = None) -> Any:`).

## Pull request checklist

- [ ] `make ci` passes locally
- [ ] New/changed behaviour is covered by tests
- [ ] No new mypy errors (strict mode)
- [ ] Code follows existing patterns and style
- [ ] Changes are minimal and focused

## CI pipeline overview

The GitHub Actions workflow (`.github/workflows/ci-cd.yml`) runs:

1. **Code Quality** — pre-commit (codespell, mypy, ruff, ruff format)
2. **Type Check** — mypy strict mode
3. **HACS Validation** — HACS action
4. **Hassfest Validation** — Home Assistant validation
5. **Tests** — quick (non-slow) on branch pushes, comprehensive (all tests)
   on pull requests, `main`, and schedule

All checks must pass before a PR can be merged (enforced by branch protection
on `main`).
