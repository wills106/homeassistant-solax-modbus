"""SolaX plugin audit for electrical phase naming."""

import ast
import pathlib
import re
from collections.abc import Iterable

PLUGIN_DIR = pathlib.Path(__file__).parents[2] / "custom_components" / "solax_modbus"

SOLAX_PLUGIN_FILES = {
    "plugin_solax.py",
    "plugin_solax_a1j1.py",
    "plugin_solax_ev_charger.py",
    "plugin_solax_lv.py",
    "plugin_solax_mega_forth.py",
}

NON_L123_PHASE_NAME_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bPhase [ABC]\b",
        r"\b[ABC] Phase\b",
        r"\bGrid Phase [ABC]\b",
        r"\bBackup A\b",
        r"\b(?:Grid |Inverter |Output |Load )?(?:Voltage|Current|Power|Frequency) [ABC]\b",
        r"\b(?:Grid |Inverter |Output |Load )?(?:Voltage|Current) [RSTYB]\b",
    )
)

NON_L123_PHASE_KEY_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?:^|_)phase_[abc](?:_|$)",
        r"(?:^|_)(?:voltage|current|power|frequency)_[abc](?:_|$)",
        r"(?:^|_)[abc]_(?:voltage|current|power|frequency)(?:_|$)",
        r"^backup_a_(?:voltage|current|power)$",
        r"^(?:grid_)?(?:voltage|current)_[rst]$",
        r"^grid_phase_[abc]_(?:voltage|current|power)$",
    )
)


def _plugin_entity_literals(plugin_names: set[str]) -> Iterable[tuple[str, str | None, str | None]]:
    for plugin_path in sorted(PLUGIN_DIR.glob("plugin_*.py")):
        if plugin_path.name not in plugin_names:
            continue

        tree = ast.parse(plugin_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            values: dict[str, str | None] = {"name": None, "key": None}
            for keyword in node.keywords:
                if keyword.arg not in values:
                    continue
                try:
                    value = ast.literal_eval(keyword.value)
                except ValueError:
                    continue
                if isinstance(value, str):
                    values[keyword.arg] = value

            if values["name"] is not None or values["key"] is not None:
                yield plugin_path.name, values["name"], values["key"]


def test_solax_plugin_phase_names_use_l1_l2_l3() -> None:
    """SolaX electrical phase names should not expose A/B/C or R/S/T/Y/B labels."""

    offenders = [
        (plugin, key, name)
        for plugin, name, key in _plugin_entity_literals(SOLAX_PLUGIN_FILES)
        if name is not None and any(pattern.search(name) for pattern in NON_L123_PHASE_NAME_PATTERNS)
    ]

    assert offenders == []


def test_solax_plugin_phase_keys_use_l1_l2_l3_for_new_entities() -> None:
    """SolaX phase keys should stay on L1/L2/L3 naming, unless migrated explicitly."""

    offenders = [
        (plugin, key)
        for plugin, _name, key in _plugin_entity_literals(SOLAX_PLUGIN_FILES)
        if key is not None and any(pattern.search(key) for pattern in NON_L123_PHASE_KEY_PATTERNS)
    ]

    assert offenders == []
