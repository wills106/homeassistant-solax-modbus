"""Select stable HA and its Python without changing the project's lockfile."""

import argparse
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen

RELEASE_URL = "https://api.github.com/repos/home-assistant/core/releases/latest"


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


def python_version(text: str) -> str:
    """Use the exact interpreter selected by that HA release."""
    version = text.strip()
    if not re.fullmatch(r"3\.\d+\.\d+", version):
        raise ValueError("HA release has no supported exact Python version")
    return version


def current_requirements(project: dict[str, Any], tag: str) -> list[str]:
    """Keep project requirements but let the plugin select compatible test tools."""
    groups = project["dependency-groups"]
    requirements = list(project["project"]["dependencies"]) + list(groups["dev"])
    replaced = {"homeassistant", "pytest-homeassistant-custom-component", "pytest-asyncio"}
    for requirement in groups["test"]:
        name = re.split(r"[\[<>=!~;\s]", requirement, maxsplit=1)[0].lower().replace("_", "-")
        if name not in replaced:
            requirements.append(requirement)
    # The plugin pins HA exactly. The resolver must find a plugin for this stable
    # release, rather than installing the latest plugin's beta HA dependency.
    return requirements + [f"homeassistant=={tag}", "pytest-homeassistant-custom-component>=0.13.0", "pytest-asyncio"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tag = stable_tag(json.loads(read_url(RELEASE_URL)))
    source = f"https://raw.githubusercontent.com/home-assistant/core/{tag}/.python-version"
    selected_python = python_version(read_url(source))
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    selection = {"homeassistant": tag, "python": selected_python, "release_url": RELEASE_URL, "python_source": source}
    (args.output_dir / "selection.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "requirements.in").write_text("\n".join(current_requirements(project, tag)) + "\n", encoding="utf-8")
    print(json.dumps(selection, indent=2))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"homeassistant={tag}\npython={selected_python}\n")


if __name__ == "__main__":
    main()
