"""Stable-release selection cannot drift to beta HA or locked older versions."""

import json
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

from scripts import resolve_ha_environment
from scripts.resolve_ha_environment import environment_requirements, explicit_tag, legacy_python, python_version, select_python, stable_tag


@pytest.mark.parametrize(
    "release",
    [
        {"tag_name": "2026.10.0b0"},
        {"tag_name": "2026.9.4", "prerelease": True},
        {"tag_name": "2026.9.4", "draft": True},
        {"tag_name": "2026.9.4\npython=3.15.0"},
        {},
    ],
)
def test_reject_non_stable_release(release: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="stable HA"):
        stable_tag(release)


def test_accept_stable_release_and_exact_python() -> None:
    assert stable_tag({"tag_name": "2026.9.4", "prerelease": False, "draft": False}) == "2026.9.4"
    assert python_version("3.14.5\n") == "3.14.5"


@pytest.mark.parametrize("text", ["3.14", "3.15.0b1", "3.14.5\nother=bad", "latest", ""])
def test_reject_invalid_python(text: str) -> None:
    with pytest.raises(ValueError, match="exact Python"):
        python_version(text)


def test_environment_requirements_preserve_project_dependencies_without_old_test_pins() -> None:
    project = {
        "project": {"dependencies": ["pymodbus>=3.8.3"]},
        "dependency-groups": {
            "dev": ["ruff>=0.14.14", "mypy>=1.8.0", "codespell>=2.2.6", "pre-commit>=4.0.0"],
            "test": [
                "pytest>=8.0.0",
                "homeassistant==2025.1.0; python_version < '3.14'",
                "pytest-homeassistant-custom-component==0.13.201",
                "pytest-asyncio<1.0.0",
                "pytest-cov>=4.1.0",
            ],
        },
    }
    requirements = environment_requirements(project, "2026.9.4")
    assert "pymodbus>=3.8.3" in requirements
    assert set(project["dependency-groups"]["dev"]).isdisjoint(requirements)
    assert "pytest>=8.0.0" in requirements
    assert "pytest-cov>=4.1.0" in requirements
    assert [item for item in requirements if item.startswith("homeassistant")] == ["homeassistant==2026.9.4"]
    assert "pytest-homeassistant-custom-component>=0.13.0" in requirements
    assert "pytest-asyncio" in requirements
    assert not any("0.13.201" in item or "<1.0.0" in item for item in requirements)


@pytest.mark.parametrize("requirement, series", [(">=3.12.0", "3.12"), (">=3.13.2", "3.13")])
def test_legacy_python_uses_lowest_supported_series(requirement: str, series: str) -> None:
    assert legacy_python(f'[project]\nrequires-python = "{requirement}"') == series


@pytest.mark.parametrize("requirement", [">=3.12", ">=3.12.0,<3.14", "~=3.12.0", "garbage"])
def test_legacy_python_does_not_guess_unsupported_requirements(requirement: str) -> None:
    with pytest.raises(ValueError, match="Unsupported legacy"):
        legacy_python(f'[project]\nrequires-python = "{requirement}"')


def test_minimum_with_python_file_uses_exact_version(monkeypatch: pytest.MonkeyPatch) -> None:
    def read(url: str) -> str:
        assert url.endswith("/2026.9.4/.python-version")
        return "3.14.5\n"

    monkeypatch.setattr(resolve_ha_environment, "read_url", read)
    assert select_python("2026.9.4", allow_legacy=True) == (
        "3.14.5",
        "https://raw.githubusercontent.com/home-assistant/core/2026.9.4/.python-version",
    )


@pytest.mark.parametrize("minimum, status", [(False, 404), (True, 403), (True, 500)])
def test_python_metadata_errors_are_not_hidden(monkeypatch: pytest.MonkeyPatch, minimum: bool, status: int) -> None:
    def read(url: str) -> str:
        raise HTTPError(url, status, "metadata error", Message(), None)

    monkeypatch.setattr(resolve_ha_environment, "read_url", read)
    with pytest.raises(HTTPError) as error:
        select_python("2025.1.0", allow_legacy=minimum)
    assert error.value.code == status


def test_minimum_cli_reads_hacs_and_records_legacy_python(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hacs.json").write_text(json.dumps({"homeassistant": "2025.2.1"}))
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n[dependency-groups]\ndev = []\ntest = []")
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr("sys.argv", ["resolve_ha_environment.py", "--target", "minimum", "--output-dir", "record"])

    def read(url: str) -> str:
        assert "/2025.2.1/" in url  # The local HACS requirement is authoritative.
        if url.endswith("/.python-version"):
            raise HTTPError(url, 404, "missing legacy file", Message(), None)
        assert url.endswith("/pyproject.toml")
        return '[project]\nrequires-python = ">=3.13.2"'

    monkeypatch.setattr(resolve_ha_environment, "read_url", read)
    resolve_ha_environment.main()
    selection = json.loads((tmp_path / "record/selection.json").read_text())
    assert selection["homeassistant"] == "2025.2.1"
    assert selection["python"] == "3.13"
    assert selection["version_source"] == "hacs.json"
    assert selection["python_source"].endswith("/2025.2.1/pyproject.toml")
    assert "homeassistant==2025.2.1" in (tmp_path / "record/requirements.in").read_text().splitlines()
    assert output.read_text() == "homeassistant=2025.2.1\npython=3.13\n"


@pytest.mark.parametrize("minimum", [None, "", "2025.1.0b0", "2025.1.0\npython=3.14"])
def test_invalid_hacs_minimum_does_not_select_current(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, minimum: str | None) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "hacs.json").write_text(json.dumps({"homeassistant": minimum}))
    monkeypatch.setattr("sys.argv", ["resolve_ha_environment.py", "--target", "minimum", "--output-dir", "record"])

    def read(url: str) -> str:
        pytest.fail(f"Invalid HACS metadata must fail before requesting {url}")

    monkeypatch.setattr(resolve_ha_environment, "read_url", read)
    with pytest.raises(ValueError, match="stable HA"):
        resolve_ha_environment.main()


@pytest.mark.parametrize("tag", ["2026.9.4", "2026.10.0b0", "2026.10.0rc1"])
def test_explicit_cli_pins_only_requested_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tag: str) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n[dependency-groups]\ndev = []\ntest = []")
    monkeypatch.setattr("sys.argv", ["resolve_ha_environment.py", "--target", "version", "--ha-version", tag, "--output-dir", "record"])

    def read(url: str) -> str:
        assert url == f"https://raw.githubusercontent.com/home-assistant/core/{tag}/.python-version"
        return "3.14.5\n"

    monkeypatch.setattr(resolve_ha_environment, "read_url", read)
    resolve_ha_environment.main()
    selection = json.loads((tmp_path / "record/selection.json").read_text())
    assert selection["homeassistant"] == tag
    assert selection["version_source"] == "--ha-version"
    assert f"homeassistant=={tag}" in (tmp_path / "record/requirements.in").read_text().splitlines()


@pytest.mark.parametrize("tag", ["latest", "2026.10.0dev1", "2026.10.0b0\npython=3.15", "https://example.com", ""])
def test_explicit_versions_reject_aliases_and_injection(tag: str) -> None:
    with pytest.raises(ValueError, match="exact HA release"):
        explicit_tag(tag)


@pytest.mark.parametrize("arguments", [["--target", "version"], ["--target", "current", "--ha-version", "2026.10.0b0"]])
def test_cli_rejects_ambiguous_version_selection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, arguments: list[str]) -> None:
    monkeypatch.setattr("sys.argv", ["resolve_ha_environment.py", *arguments, "--output-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        resolve_ha_environment.main()
    assert error.value.code == 2
