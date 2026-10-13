"""Build the HA test matrix while preserving branch-push and full-suite triggers."""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any


def build_matrix(environments: list[dict[str, Any]], event: str, ref: str) -> dict[str, list[dict[str, str]]]:
    """Validate every entry and select the environments required by this event."""
    branch_push = event == "push" and ref != "refs/heads/main"
    rows: list[dict[str, str]] = []
    names: set[str] = set()
    for environment in environments:
        name = environment.get("name")
        target = environment.get("target")
        version = environment.get("ha_version", "")
        on_branch = environment.get("branch_push", False)
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", name) or name in names:
            raise ValueError("HA test environment names must be unique safe identifiers")
        if target not in ("minimum", "current", "version") or not isinstance(version, str) or not isinstance(on_branch, bool):
            raise ValueError(f"Invalid HA test environment: {name}")
        if bool(version) != (target == "version"):
            raise ValueError(f"Only target=version requires ha_version: {name}")
        names.add(name)
        if not branch_push or on_branch:
            rows.append({"name": name, "target": target, "ha_version": version, "suite": "quick" if branch_push else "full"})
    if not rows:
        raise ValueError("No HA test environments selected for this event")
    return {"include": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(".github/ha-test-environments.json"))
    args = parser.parse_args()
    matrix = build_matrix(json.loads(args.config.read_text(encoding="utf-8")), os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"])
    encoded = json.dumps(matrix)
    print(encoded)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"matrix={encoded}\n")


if __name__ == "__main__":
    main()
