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

- Python **3.14.2+** for current HA checks (Python **3.12** for minimum HA tests)
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
UV_PYTHON=3.14 uv sync --locked --all-groups
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
source of truth for dependency versions. `--locked` fails if the lockfile needs
updating; after an intentional dependency change, run `uv lock` and review the diff.

## Home Assistant compatibility

CI runs the full suite against two explicit environments:

| Purpose | Python | Home Assistant | Test plugin |
| ------- | ------ | -------------- | ----------- |
| Minimum supported | 3.12 | 2025.1.0 | 0.13.201 |
| Current stable | 3.14 | 2026.9.4 | 0.13.367 |

The HA and test-plugin pins in `pyproject.toml` select the corresponding
environment by Python version. Quality checks and quick branch tests use 3.14;
Ruff retains a 3.12 source target to preserve minimum-version compatibility.
Mypy targets 3.14 because it also parses current HA's Python 3.14 source.
Pytest uses asyncio auto mode so the current HA plugin's async autouse fixtures
are handled by pytest-asyncio.

Reproduce both full-suite jobs locally:

```bash
make ci-full PYTHON=3.14
make sync test-all PYTHON=3.12
```

When updating current HA, update its matching test plugin, CI matrix and this
table together, regenerate `uv.lock`, and run both suites. Change the minimum
only when the requirement in `hacs.json` changes. Early Python 3.14 patches
below 3.14.2 are excluded from lock resolution because current HA requires 3.14.2+.

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
5. **Tests** — quick (non-slow) on current HA for branch pushes, comprehensive
   (all tests) on minimum and current HA for pull requests, `main`, schedule,
   and manual dispatch

All checks must pass before a PR can be merged (enforced by branch protection
on `main`).
