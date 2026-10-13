"""Warn about an outdated locked quality baseline without changing dependencies."""

import json
import os
import platform
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from scripts.resolve_ha_environment import RELEASE_URL, python_version, read_url, select_python, stable_tag


def version_parts(value: str) -> tuple[int, ...]:
    """Compare numeric release components, including two-digit months/patches."""
    return tuple(int(part) for part in value.split("."))


def baseline_warnings(baseline: dict[str, str], current: dict[str, str]) -> list[str]:
    """Review HA drift and Python compatibility without requiring patch equality."""
    warnings = []
    if version_parts(current["homeassistant"]) > version_parts(baseline["homeassistant"]):
        warnings.append(
            f"New stable HA {current['homeassistant']}; locked quality baseline uses HA {baseline['homeassistant']}. "
            "Review the HA/test-plugin pins in pyproject.toml and regenerate and validate uv.lock."
        )
    running = version_parts(baseline["python"])
    selected = version_parts(current["python"])
    if running[:2] != selected[:2] or running < selected:
        warnings.append(
            f"Current HA selects Python {current['python']}; quality checks run on Python {baseline['python']}. "
            "Review Python settings in CI, Makefile and pyproject.toml, then validate the baseline."
        )
    expected_series = ".".join(current["python"].split(".")[:2])
    if baseline["mypy_python"] != expected_series:
        warnings.append(
            f"Current HA uses Python {expected_series}; mypy targets Python {baseline['mypy_python']}. "
            "Review tool.mypy.python_version in pyproject.toml. Keep Ruff's source target aligned with minimum HA support."
        )
    return warnings


def report(summary: str, warnings: list[str]) -> None:
    """Expose advisory annotations and a job summary; also work outside CI."""
    for message in warnings:
        # GitHub workflow commands require escaping multiline message data.
        escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::warning title=HA quality baseline::{escaped}")
    print(summary)
    if output := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(summary + "\n")


def main() -> None:
    try:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        baseline = {
            "homeassistant": stable_tag({"tag_name": version("homeassistant")}),
            "python": python_version(platform.python_version()),
            "mypy_python": str(project["tool"]["mypy"]["python_version"]),
        }
        tag = stable_tag(json.loads(read_url(RELEASE_URL)))
        selected_python, _ = select_python(tag)
        current = {"homeassistant": tag, "python": selected_python}
        warnings = baseline_warnings(baseline, current)
    except (OSError, ValueError, KeyError, PackageNotFoundError) as error:
        # This is advisory; missing metadata must not fail code quality checks.
        message = f"Baseline freshness could not be checked ({type(error).__name__}). No dependency versions were changed; retry the check."
        report(f"### HA quality baseline\n\n{message}", [message])
        return
    summary = (
        "### HA quality baseline\n\n"
        "| Component | Locked quality environment | Current stable HA |\n"
        "| --- | --- | --- |\n"
        f"| Home Assistant | {baseline['homeassistant']} | {current['homeassistant']} |\n"
        f"| Python runtime | {baseline['python']} | {current['python']} |\n"
        f"| Mypy Python target | {baseline['mypy_python']} | {'.'.join(current['python'].split('.')[:2])} |\n\n"
    )
    if warnings:
        summary += "Baseline review recommended:\n\n" + "\n".join(f"- {message}" for message in warnings)
    else:
        summary += "No baseline update indicated by current HA/Python metadata."
    report(summary, warnings)


if __name__ == "__main__":
    main()
