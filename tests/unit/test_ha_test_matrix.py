"""The shared matrix preserves triggers and cannot silently omit every test."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from scripts import plan_ha_tests
from scripts.plan_ha_tests import build_matrix


def environments() -> list[dict[str, Any]]:
    # JSON decoding is untyped; build_matrix validates each configured entry.
    return cast(list[dict[str, Any]], json.loads(Path(".github/ha-test-environments.json").read_text()))


@pytest.mark.parametrize(
    "event, ref",
    [("push", "refs/heads/main"), ("pull_request", "refs/pull/1/merge"), ("workflow_dispatch", "refs/heads/topic"), ("schedule", "refs/heads/main")],
)
def test_full_triggers_select_minimum_and_current(event: str, ref: str) -> None:
    rows = build_matrix(environments(), event, ref)["include"]
    assert [row["target"] for row in rows] == ["minimum", "current"]
    assert all(row["suite"] == "full" for row in rows)


def test_branch_push_only_selects_current_quick_tests() -> None:
    rows = build_matrix(environments(), "push", "refs/heads/topic")["include"]
    assert [(row["target"], row["suite"]) for row in rows] == [("current", "quick")]


def test_additional_beta_uses_same_matrix_and_controls_branch_pushes() -> None:
    targets = environments() + [{"name": "beta", "target": "version", "ha_version": "2026.10.0b0", "branch_push": False}]
    full = build_matrix(targets, "workflow_dispatch", "refs/heads/topic")["include"]
    assert full[-1] == {"name": "beta", "target": "version", "ha_version": "2026.10.0b0", "suite": "full"}
    assert len(build_matrix(targets, "push", "refs/heads/topic")["include"]) == 1
    targets[-1]["branch_push"] = True
    assert build_matrix(targets, "push", "refs/heads/topic")["include"][-1]["suite"] == "quick"


@pytest.mark.parametrize(
    "targets",
    [
        [],
        [{"name": "minimum", "target": "minimum", "branch_push": False}],
        [{"name": "../escape", "target": "current"}],
        [{"name": "current", "target": "current"}, {"name": "current", "target": "minimum"}],
        [{"name": "beta", "target": "version"}],
        [{"name": "current", "target": "current", "ha_version": "2026.9.4"}],
        [{"name": "current", "target": "current", "branch_push": "false"}],
        [{"name": "unknown", "target": "guess"}],
    ],
)
def test_invalid_or_empty_matrix_fails(targets: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        build_matrix(targets, "push", "refs/heads/topic")


def test_matrix_cli_writes_github_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/1/merge")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr("sys.argv", ["plan_ha_tests.py"])
    plan_ha_tests.main()
    matrix = json.loads(output.read_text().removeprefix("matrix="))
    assert {row["name"] for row in matrix["include"]} == {"minimum", "current"}
