"""Run the CI HA compatibility matrix locally with uv, independent of uv.lock."""

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

from scripts.plan_ha_tests import build_matrix
from scripts.resolve_ha_environment import resolve_environment

VERSION_CODE = "import platform; print(platform.python_version())"
INSTALLED_CODE = """import json, platform
from importlib.metadata import version
print(json.dumps({
    "python": platform.python_version(),
    "homeassistant": version("homeassistant"),
    "test_plugin": version("pytest-homeassistant-custom-component"),
}))
"""


def run(command: list[str], *, capture: bool = False) -> str:
    """Fail on command errors; stream install/test output without buffering it."""
    result = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else ""


def verify_versions(versions: dict[str, str], selection: dict[str, str]) -> None:
    """Never substitute another HA or Python when preparing a local environment."""
    expected = selection["python"].split(".")
    if versions["homeassistant"] != selection["homeassistant"] or versions["python"].split(".")[: len(expected)] != expected:
        raise ValueError(f"Installed versions do not match the selected environment: {versions}")


def test_environment(row: dict[str, str], root: Path, suite: str) -> None:
    """Use CI's resolver and uv commands, keeping each HA/Python venv separate."""
    record = root / row["name"] / "record"
    record.mkdir(parents=True, exist_ok=True)
    # A failed new attempt must not leave records suggesting a previous success.
    for filename in ("selection.json", "requirements.in", "requirements.txt", "installed.json", "installed-requirements.txt", "uv-version.txt"):
        (record / filename).unlink(missing_ok=True)
    selection = resolve_environment(row["target"], row["ha_version"], record)
    print(json.dumps(selection, indent=2), flush=True)
    selected_python = selection["python"]
    install = ["uv", "python", "install", "--no-bin", "--no-registry", selected_python]
    if selected_python.count(".") == 1:
        install.append("--upgrade")
    run(install)
    # Ignore active venvs so legacy series always use the newly installed patch.
    interpreter = run(["uv", "python", "find", "--managed-python", "--system", "--no-project", selected_python], capture=True).strip()
    actual_python = run([interpreter, "-c", VERSION_CODE], capture=True).strip()
    env = root / row["name"] / f"ha-{selection['homeassistant']}-py-{actual_python}"
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not env.exists():
        run(["uv", "venv", "--managed-python", "--python", interpreter, str(env)])
    if run([str(python), "-c", VERSION_CODE], capture=True).strip() != actual_python:
        raise ValueError(f"Existing environment uses a different Python: {env}")
    run(
        [
            "uv",
            "pip",
            "compile",
            "--no-config",
            "--python",
            str(python),
            "--upgrade",
            str(record / "requirements.in"),
            "-o",
            str(record / "requirements.txt"),
        ],
        capture=True,
    )
    run(["uv", "pip", "sync", "--no-config", "--python", str(python), str(record / "requirements.txt")])
    # JSON decoding is untyped; the child interpreter emits these version strings.
    versions = cast(dict[str, str], json.loads(run([str(python), "-c", INSTALLED_CODE], capture=True)))
    (record / "installed.json").write_text(json.dumps(versions, indent=2) + "\n", encoding="utf-8")
    verify_versions(versions, selection)
    (record / "installed-requirements.txt").write_text(run(["uv", "pip", "freeze", "--python", str(python)], capture=True), encoding="utf-8")
    (record / "uv-version.txt").write_text(run(["uv", "--version"], capture=True), encoding="utf-8")
    print(f"Running {row['name']} ({suite}); environment record: {record}", flush=True)
    # uv run here would synchronize the project's pinned baseline instead.
    run([str(python), "-m", "pytest", *(["-m", "not slow"] if suite == "quick" else [])])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="all", help="Name from .github/ha-test-environments.json, or all (default)")
    parser.add_argument("--suite", choices=("full", "quick"), default="full")
    args = parser.parse_args()
    # JSON decoding is untyped; the shared CI planner validates every entry.
    environments = cast(list[dict[str, Any]], json.loads(Path(".github/ha-test-environments.json").read_text(encoding="utf-8")))
    rows = build_matrix(environments, "workflow_dispatch", "refs/heads/main")["include"]
    if args.environment != "all":
        rows = [row for row in rows if row["name"] == args.environment]
        if not rows:
            parser.error(f"Unknown HA environment: {args.environment}")
    failed = []
    for row in rows:
        try:
            test_environment(row, Path("tools/ha-tests").resolve(), args.suite)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            print(f"FAILED {row['name']}: {error}", flush=True)
            failed.append(row["name"])
    if failed:
        parser.exit(1, f"Failed HA environments: {', '.join(failed)}\n")


if __name__ == "__main__":
    main()
