"""Select current, minimum or explicit HA without changing the project's lockfile."""

import argparse
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

RELEASE_URL = "https://api.github.com/repos/home-assistant/core/releases/latest"
TEST_PLUGIN_PYPI_URL = "https://pypi.org/pypi/pytest-homeassistant-custom-component/json"
HA_VERSION_PATTERN = r"\d{4}\.\d{1,2}\.\d+(?:(?:b|rc)\d+)?"


def read_url(url: str) -> str:
    """Read official release metadata, authenticating only GitHub API requests."""
    headers = {"User-Agent": "solax-modbus-ci"}
    if url.startswith("https://api.github.com/") and (token := os.environ.get("GITHUB_TOKEN")):
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        # urllib exposes an untyped response; HTTP read() returns bytes.
        return cast(bytes, response.read()).decode("utf-8")


def stable_tag(release: dict[str, Any]) -> str:
    """Reject previews and unexpected tags before constructing URLs or outputs."""
    tag = release.get("tag_name")
    if release.get("draft") or release.get("prerelease") or not isinstance(tag, str) or not re.fullmatch(r"\d{4}\.\d{1,2}\.\d+", tag):
        raise ValueError("Expected a published stable HA Core release")
    return tag


def explicit_tag(tag: str) -> str:
    """Explicit versions may be stable, beta or release candidates, never URLs."""
    if not re.fullmatch(HA_VERSION_PATTERN, tag):
        raise ValueError("Expected an exact HA release version")
    return tag


def plugin_homeassistant_tag() -> tuple[str, str]:
    """'Current' is the exact HA pinned by the newest published test plugin.

    The plugin pins one HA release exactly, so the newest plugin defines the
    newest HA that is actually testable. This avoids an unsatisfiable
    homeassistant==<latest core> request while its plugin is unpublished.
    """
    metadata = cast(dict[str, Any], json.loads(read_url(TEST_PLUGIN_PYPI_URL)))
    pins = [
        match[1]
        for requirement in metadata.get("info", {}).get("requires_dist") or []
        if (match := re.fullmatch(rf"homeassistant==({HA_VERSION_PATTERN})(?:\[[^\]]*\])?(?:;.*)?", str(requirement).strip()))
    ]
    if len(pins) != 1:
        raise ValueError("The newest test plugin must pin exactly one published HA release")
    return pins[0], TEST_PLUGIN_PYPI_URL


def python_version(text: str) -> str:
    """Use the exact interpreter selected by that HA release."""
    version = text.strip()
    if not re.fullmatch(r"3\.\d+\.\d+", version):
        raise ValueError("HA release has no supported exact Python version")
    return version


def legacy_python(text: str) -> str:
    """Select the lowest supported Python series for older HA release tags."""
    requirement = tomllib.loads(text)["project"]["requires-python"]
    match = re.fullmatch(r">=3\.(\d+)\.\d+", requirement)
    if not match:
        raise ValueError("Unsupported legacy HA Python requirement")
    # uv selects the latest patch in this series; record the actual patch in CI.
    return f"3.{match[1]}"


def select_python(tag: str, *, allow_legacy: bool = False) -> tuple[str, str]:
    """Only an absent legacy file permits using the tagged Python requirement."""
    base = f"https://raw.githubusercontent.com/home-assistant/core/{tag}"
    source = f"{base}/.python-version"
    try:
        text = read_url(source)
    except HTTPError as error:
        if not allow_legacy or error.code != 404:
            raise
        source = f"{base}/pyproject.toml"
        return legacy_python(read_url(source)), source
    return python_version(text), source


def environment_requirements(project: dict[str, Any], tag: str) -> list[str]:
    """Keep runtime/test requirements; quality tools use the locked baseline."""
    groups = project["dependency-groups"]
    requirements = list(project["project"]["dependencies"])
    replaced = {"homeassistant", "pytest-homeassistant-custom-component", "pytest-asyncio"}
    for requirement in groups["test"]:
        name = re.split(r"[\[<>=!~;\s]", requirement, maxsplit=1)[0].lower().replace("_", "-")
        if name not in replaced:
            requirements.append(requirement)
    # The plugin pins HA exactly. Resolve it for the selected version rather
    # than installing the latest plugin's potentially different HA dependency.
    return requirements + [f"homeassistant=={tag}", "pytest-homeassistant-custom-component>=0.13.0", "pytest-asyncio"]


def resolve_environment(target: str, ha_version: str, output_dir: Path) -> dict[str, str]:
    """Select and record the same environment for CI and local uv tests."""
    if target not in ("minimum", "current", "version") or bool(ha_version) != (target == "version"):
        raise ValueError("Only target=version requires ha_version")
    output_dir.mkdir(parents=True, exist_ok=True)
    minimum = target == "minimum"
    if target == "version":
        tag, version_source = explicit_tag(ha_version), "--ha-version"
    elif minimum:
        metadata = json.loads(Path("hacs.json").read_text(encoding="utf-8"))
        tag, version_source = stable_tag({"tag_name": metadata.get("homeassistant")}), "hacs.json"
    else:
        tag, version_source = plugin_homeassistant_tag()
    selected_python, source = select_python(tag, allow_legacy=target != "current")
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    selection = {
        "target": target,
        "homeassistant": tag,
        "python": selected_python,
        "version_source": version_source,
        "python_source": source,
    }
    (output_dir / "selection.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    (output_dir / "requirements.in").write_text("\n".join(environment_requirements(project, tag)) + "\n", encoding="utf-8")
    return selection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("current", "minimum", "version"), default="current")
    parser.add_argument("--ha-version", default="")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.ha_version) != (args.target == "version"):
        parser.error("Only --target version requires --ha-version")
    selection = resolve_environment(args.target, args.ha_version, args.output_dir)
    print(json.dumps(selection, indent=2))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"homeassistant={selection['homeassistant']}\npython={selection['python']}\n")


if __name__ == "__main__":
    main()
