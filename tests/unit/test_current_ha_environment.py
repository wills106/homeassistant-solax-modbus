"""Stable-release selection cannot drift to beta HA or locked older versions."""

from typing import Any

import pytest

from scripts.resolve_current_ha import current_requirements, python_version, stable_tag


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


def test_current_requirements_preserve_project_dependencies_without_old_test_pins() -> None:
    project = {
        "project": {"dependencies": ["pymodbus>=3.8.3"]},
        "dependency-groups": {
            "dev": ["ruff>=0.14.14"],
            "test": [
                "pytest>=8.0.0",
                "homeassistant==2025.1.0; python_version < '3.14'",
                "pytest-homeassistant-custom-component==0.13.201",
                "pytest-asyncio<1.0.0",
                "pytest-cov>=4.1.0",
            ],
        },
    }
    requirements = current_requirements(project, "2026.9.4")
    assert "pymodbus>=3.8.3" in requirements
    assert "ruff>=0.14.14" in requirements
    assert "pytest>=8.0.0" in requirements
    assert "pytest-cov>=4.1.0" in requirements
    assert [item for item in requirements if item.startswith("homeassistant")] == ["homeassistant==2026.9.4"]
    assert "pytest-homeassistant-custom-component>=0.13.0" in requirements
    assert "pytest-asyncio" in requirements
    assert not any("0.13.201" in item or "<1.0.0" in item for item in requirements)
