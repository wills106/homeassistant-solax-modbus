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

- Python **3.14.2+** for the locked tooling baseline (Python **3.12** for minimum HA tests)
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

Run the locked quality/baseline checks and the dynamic HA compatibility matrix:

```bash
make ci
make test-ha
```

HACS and hassfest validation run separately in GitHub Actions.

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
| `make ci`      | Locked baseline: sync + lint + mypy + quick tests                    |
| `make ci-full` | Locked baseline checks including the full test suite                  |
| `make test-ha` | Dynamic full HA matrix; select with `HA_ENVIRONMENT=minimum/current` |

## Keeping your environment in sync with CI

The most common cause of "works in CI but not locally" (or vice versa) is a
drifted local environment. If you ever see unexpected mypy or import errors,
re-sync first:

```bash
make sync
```

This reinstalls the exact pinned versions from `uv.lock`, which is the single
source of truth for locked baseline dependency versions. `--locked` fails if the lockfile needs
updating; after an intentional dependency change, run `uv lock` and review the diff.

## Home Assistant compatibility

CI runs the full suite against the minimum supported HA and the latest stable HA:

| Purpose | Python | Home Assistant | Test plugin |
| ------- | ------ | -------------- | ----------- |
| Minimum supported | From that HA tag's metadata | `hacs.json.homeassistant` | Resolved to match that exact HA |
| Current stable | From that HA release's `.python-version` | Latest published stable Core release | Resolved to match that exact HA |
| Locked tooling baseline | 3.14 | 2026.9.4 | 0.13.367 |

The HA and test-plugin pins in `pyproject.toml` retain local locked environments;
CI compatibility jobs resolve their HA independently. Quality checks and baseline quick tests use 3.14;
Ruff retains a 3.12 source target to preserve minimum-version compatibility.
Mypy targets 3.14 because it also parses current HA's Python 3.14 source.
Pytest uses asyncio auto mode so the current HA plugin's async autouse fixtures
are handled by pytest-asyncio.

After installing the locked quality environment, CI checks its installed HA and
Python against the latest stable Core release using the shared metadata resolver.
The advisory step emits warning annotations and a job summary when a newer HA is
available, the Python series differs, the runtime patch is older than HA's selected
patch, or mypy targets a different Python series. A newer runtime patch in the same
series is accepted. Metadata lookup failures also produce a warning; this step
does not block CI or update dependencies automatically. Review the HA/test-plugin
pins, Python settings and `uv.lock` in a separate, validated baseline update.

Run the same advisory check locally after `make sync`:

```bash
uv run --locked python -m scripts.check_ha_baseline
```

Run the same dynamically selected environments locally from the repository root
(Linux or WSL, matching the CI runner), without requiring `make`:

```bash
# Both minimum and current, with the full suite (default)
uv run --no-project --python 3.12 -m scripts.run_ha_tests

# One environment, or non-slow tests for faster iteration
uv run --no-project --python 3.12 -m scripts.run_ha_tests --environment minimum
uv run --no-project --python 3.12 -m scripts.run_ha_tests --environment current --suite quick

# Equivalent make shortcuts
make test-ha
make test-ha HA_ENVIRONMENT=minimum
make test-ha HA_ENVIRONMENT=current HA_SUITE=quick
```

The launcher uses only the standard library. Its Python 3.12 is just for running
the resolver; uv installs each selected HA's own Python for the tests. It reads
the same JSON environment list and calls the same resolver as CI, so changing
the HACS minimum or adding a named version also changes these local tests.
All configured environments run by default, even if an earlier one fails; any
failure produces a nonzero exit status. `--suite quick` selects non-slow tests
for the requested environments; it does not filter by the CI branch-push rules.

Environments and records are stored under the ignored `tools/ha-tests/<name>/`
directory. Venvs are separated by exact HA and actual Python version, and reused
on subsequent runs. Release metadata and dependencies are resolved afresh on
every run. The `record/` directory contains selection, requirements, installed
versions and uv version, like the CI artifacts. The project's `.venv` and
`uv.lock` are not synchronized by this command. Regular `uv sync`, `uv run pytest`
and `make ci` retain the pinned baseline.

Reproduce the locked local environments (the 3.12 environment is a historical
minimum baseline, not automatically updated from HACS):

```bash
make ci-full PYTHON=3.14
make sync test-all PYTHON=3.12
```

The shared `Test HA` matrix is declared in `.github/ha-test-environments.json`.
`scripts/plan_ha_tests.py` selects its entries and suite for the event. Each entry
uses the same workflow steps for Python, dependency resolution, verification,
tests and artifacts. `fail-fast: false` lets every selected environment finish;
all selected entries must succeed for the final CI gate to pass.

The `minimum` entry reads the exact `homeassistant` version from
`hacs.json` using `scripts/resolve_ha_environment.py --target minimum`. It uses that
tag's `.python-version` if present. Older tags without that file use the lowest
Python series from the tagged `pyproject.toml`'s `requires-python`, with the latest
available patch selected by uv. Only a 404 for the missing legacy file allows
this alternative; other metadata errors fail the job. A missing or invalid HACS
minimum also fails, without silently choosing a different HA version.
The compatible test plugin and dependencies are resolved into a separate
environment, without changing `uv.lock`. The existing full-suite triggers remain:
PRs, `main`, schedules and manual dispatch.

The `current` entry resolves the latest non-preview GitHub Core release at
the start of every run using `scripts/resolve_ha_environment.py --target current`. It uses the exact
Python from that release's `.python-version`, pins that HA, and lets uv resolve
a matching test plugin and compatible project/test dependencies from PyPI.
It uses a separate environment and requirements file; `uv.lock` is not changed.
A missing compatible plugin or unavailable release/Python metadata fails the job
explicitly, without substituting an older HA. Branch pushes run non-slow tests;
PRs, `main`, schedules and manual dispatch run the full suite.

Add another version by adding an entry to the JSON list, for example:

```json
{
  "name": "beta",
  "target": "version",
  "ha_version": "2026.10.0b0",
  "branch_push": false
}
```

`target: version` accepts an exact stable, beta or release-candidate version and
never substitutes another release. Python and the matching test plugin are still
resolved automatically. `branch_push: false` includes it only in full-suite events;
`true` also includes it in non-slow branch-push tests. The beta entry above is an
example, not enabled by default. Minimum/current selection continues to reject betas.

The compatibility jobs upload `minimum-ha-environment` or `current-ha-environment`, including selected and
installed versions, uv version, resolved requirements and installed package pins.
To reproduce a run, download its artifact, use the Python in `installed.json`,
and run (from the repository root, using the downloaded requirements path):

```bash
uv venv --python <recorded-python-version> tools/current-ha-env
uv pip sync --python tools/current-ha-env/bin/python <artifact>/requirements.txt
tools/current-ha-env/bin/python -m pytest
```

The existing daily schedule detects new stable HA releases automatically. The
locked tooling baseline can be updated separately when desired. Change the minimum
in `hacs.json`; the minimum CI environment follows automatically. Early Python 3.14 patches below 3.14.2 remain excluded
from project lock resolution because the tooling baseline requires 3.14.2+.

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
- [ ] `make test-ha` passes against the selected HA compatibility environments
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
5. **Baseline quick tests** — non-slow tests on the locked baseline for branch pushes
6. **HA test matrix** — the same test job for all selected environments: current
   non-slow tests on branch pushes; minimum/current full tests for PRs, `main`,
   schedule and manual dispatch; additional versions configured in the JSON list

All checks must pass before a PR can be merged (enforced by branch protection
on `main`).
