"""Baseline drift is advisory and does not confuse newer patches with incompatibility."""

import json
from pathlib import Path
from urllib.error import URLError

import pytest

from scripts import check_ha_baseline
from scripts.resolve_ha_environment import RELEASE_URL


@pytest.mark.parametrize(
    "ha, python, mypy, warning_count",
    [
        ("2026.9.4", "3.14.5", "3.14", 0),
        ("2026.9.4", "3.14.7", "3.14", 0),
        ("2026.9.4", "3.14.4", "3.14", 1),
        ("2026.9.3", "3.14.7", "3.14", 1),
        ("2026.9.10", "3.14.10", "3.14", 0),
        ("2026.9.4", "3.13.9", "3.13", 2),
        ("2026.9.4", "3.14.7", "3.13", 1),
    ],
)
def test_baseline_comparison(ha: str, python: str, mypy: str, warning_count: int) -> None:
    baseline = {"homeassistant": ha, "python": python, "mypy_python": mypy}
    current = {"homeassistant": "2026.9.4", "python": "3.14.5"}
    assert len(check_ha_baseline.baseline_warnings(baseline, current)) == warning_count


def test_new_ha_python_series_warns_about_runtime_and_mypy() -> None:
    baseline = {"homeassistant": "2026.9.4", "python": "3.14.7", "mypy_python": "3.14"}
    warnings = check_ha_baseline.baseline_warnings(baseline, {"homeassistant": "2026.10.0", "python": "3.15.1"})
    assert len(warnings) == 3
    assert "New stable HA 2026.10.0" in warnings[0]
    assert "Python 3.15.1" in warnings[1]
    assert "mypy targets Python 3.14" in warnings[2]


@pytest.mark.parametrize("lookup", ["current", "newer", "network-error", "prerelease"])
def test_advisory_cli_writes_summary_and_never_exits_on_drift_or_metadata_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], lookup: str
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(check_ha_baseline, "version", lambda name: "2026.9.4")
    monkeypatch.setattr("scripts.check_ha_baseline.platform.python_version", lambda: "3.14.7")

    def read(url: str) -> str:
        assert url == RELEASE_URL
        if lookup == "network-error":
            raise URLError("offline\n::error::untrusted detail")
        tag = {"current": "2026.9.4", "newer": "2026.10.0", "prerelease": "2026.10.0b0"}[lookup]
        return json.dumps({"tag_name": tag})

    monkeypatch.setattr(check_ha_baseline, "read_url", read)
    monkeypatch.setattr(check_ha_baseline, "select_python", lambda tag: ("3.14.5", "metadata"))
    check_ha_baseline.main()
    text = summary.read_text()
    output = capsys.readouterr().out
    assert "HA quality baseline" in text
    assert ("::warning title=HA quality baseline::" in output) == (lookup != "current")
    if lookup in ("network-error", "prerelease"):
        assert "could not be checked" in text
        assert "::error::" not in output
    else:
        assert "2026.9.4" in text
        assert "3.14.7" in text
        assert "No baseline update" in text if lookup == "current" else "Baseline review recommended" in text


def test_annotation_message_cannot_inject_workflow_commands(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    check_ha_baseline.report("summary", ["failure 10%\r\n::error::injected"])
    output = capsys.readouterr().out
    assert "10%25%0D%0A::error::injected" in output
    assert "\n::error::" not in output
