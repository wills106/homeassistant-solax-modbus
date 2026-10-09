"""Local compatibility tests use selected interpreters and preserve matrix failures."""

import json
import subprocess
from pathlib import Path

import pytest

from scripts import run_ha_tests


@pytest.mark.parametrize(
    "actual, selected, valid",
    [("3.12.15", "3.12", True), ("3.14.5", "3.14.5", True), ("3.14.7", "3.14.5", False), ("3.14.5", "3.12", False)],
)
def test_verify_python_series_or_exact_patch(actual: str, selected: str, valid: bool) -> None:
    installed = {"python": actual, "homeassistant": "2026.9.4"}
    selection = {"python": selected, "homeassistant": "2026.9.4"}
    if valid:
        run_ha_tests.verify_versions(installed, selection)
    else:
        with pytest.raises(ValueError, match="do not match"):
            run_ha_tests.verify_versions(installed, selection)


def test_verify_rejects_wrong_ha() -> None:
    with pytest.raises(ValueError, match="do not match"):
        run_ha_tests.verify_versions({"python": "3.14.5", "homeassistant": "2026.9.3"}, {"python": "3.14.5", "homeassistant": "2026.9.4"})


@pytest.mark.parametrize("failure", [None, "compile", "version"])
def test_local_run_uses_isolated_python_and_stops_before_tests_on_setup_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str | None
) -> None:
    commands: list[list[str]] = []
    selection = {"python": "3.12", "homeassistant": "2025.1.0"}

    def resolve(target: str, version: str, record: Path) -> dict[str, str]:
        assert (target, version) == ("minimum", "")
        (record / "requirements.in").write_text("homeassistant==2025.1.0\n")
        return selection

    def run(command: list[str], *, capture: bool = False) -> str:
        commands.append(command)
        if command[:3] == ["uv", "python", "find"]:
            return "/managed/python\n"
        if command[-1] == run_ha_tests.VERSION_CODE:
            return "3.12.15\n"
        if command[:3] == ["uv", "pip", "compile"] and failure == "compile":
            raise subprocess.CalledProcessError(1, command)
        if command[-1] == run_ha_tests.INSTALLED_CODE:
            return json.dumps({"python": "3.12.15", "homeassistant": "2025.2.0" if failure == "version" else "2025.1.0", "test_plugin": "0.13.201"})
        return ""

    monkeypatch.setattr(run_ha_tests, "resolve_environment", resolve)
    monkeypatch.setattr(run_ha_tests, "run", run)
    row = {"name": "minimum", "target": "minimum", "ha_version": ""}
    if failure:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            run_ha_tests.test_environment(row, tmp_path, "quick")
        assert not any("pytest" in command for command in commands)
    else:
        run_ha_tests.test_environment(row, tmp_path, "quick")
        test_command = commands[-1]
        assert test_command[1:] == ["-m", "pytest", "-m", "not slow"]
        assert Path(test_command[0]).is_relative_to(tmp_path / "minimum/ha-2025.1.0-py-3.12.15")
        recorded = json.loads((tmp_path / "minimum/record/installed.json").read_text())
        assert recorded == {"python": "3.12.15", "homeassistant": "2025.1.0", "test_plugin": "0.13.201"}
    assert not any(command[:2] in (["uv", "run"], ["uv", "sync"]) for command in commands)


@pytest.mark.parametrize("failure", [None, "minimum"])
def test_local_matrix_runs_every_entry_and_reports_failures(monkeypatch: pytest.MonkeyPatch, failure: str | None) -> None:
    tested: list[str] = []
    monkeypatch.setattr("sys.argv", ["run_ha_tests.py"])

    def test_environment(row: dict[str, str], root: Path, suite: str) -> None:
        tested.append(row["name"])
        assert suite == "full"
        if row["name"] == failure:
            raise subprocess.CalledProcessError(1, ["pytest"])

    monkeypatch.setattr(run_ha_tests, "test_environment", test_environment)
    if failure:
        with pytest.raises(SystemExit) as error:
            run_ha_tests.main()
        assert error.value.code == 1
    else:
        run_ha_tests.main()
    assert tested == ["minimum", "current"]


def test_local_cli_rejects_unknown_environment_before_installing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["run_ha_tests.py", "--environment", "../escape"])

    def test_environment(row: dict[str, str], root: Path, suite: str) -> None:
        pytest.fail("An unknown environment must not be installed")

    monkeypatch.setattr(run_ha_tests, "test_environment", test_environment)
    with pytest.raises(SystemExit) as error:
        run_ha_tests.main()
    assert error.value.code == 2
