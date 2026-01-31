#!/usr/bin/env python3
"""Batch convert remaining plugin files from star imports to explicit imports."""

import ast
from pathlib import Path


def get_all_const_symbols():
    """Get all symbols defined in const.py."""
    const_file = Path(__file__).parent.parent / "custom_components" / "solax_modbus" / "const.py"
    with open(const_file) as f:
        content = f.read()
        tree = ast.parse(content)

    symbols = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            symbols.add(node.name)
        elif isinstance(node, ast.FunctionDef):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)

    return symbols


def analyze_plugin_file(filepath):
    """Analyze what a plugin file actually uses."""
    with open(filepath) as f:
        content = f.read()
        tree = ast.parse(content)

    # Collect all Name nodes (symbol references)
    used_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_names.add(node.id)

    return used_names, content


def convert_plugin_file(filepath, const_symbols):
    """Convert a single plugin file."""
    used_names, content = analyze_plugin_file(filepath)

    # Determine what's needed from const
    from_const = sorted(used_names & const_symbols)

    # HA const imports
    ha_const_symbols = {
        "PERCENTAGE",
        "DEGREE",
        "UnitOfPower",
        "UnitOfElectricCurrent",
        "UnitOfElectricPotential",
        "UnitOfEnergy",
        "UnitOfTime",
        "UnitOfTemperature",
        "UnitOfFrequency",
        "UnitOfReactivePower",
        "UnitOfApparentPower",
    }
    from_ha_const = sorted(used_names & ha_const_symbols)

    # Build new imports
    new_imports = []
    new_imports.append("import logging")
    new_imports.append("from dataclasses import dataclass")

    # Check if time is used
    if "time" in used_names:
        new_imports.append("from time import time")

    new_imports.append("")

    # HA component imports
    new_imports.append("from homeassistant.components.button import ButtonEntityDescription")

    # Number imports with conditional NumberDeviceClass
    if "NumberDeviceClass" in used_names:
        new_imports.append("from homeassistant.components.number import NumberDeviceClass, NumberEntityDescription")
    else:
        new_imports.append("from homeassistant.components.number import NumberEntityDescription")

    new_imports.append("from homeassistant.components.select import SelectEntityDescription")

    # Sensor imports with conditional device classes
    if "SensorDeviceClass" in used_names or "SensorStateClass" in used_names:
        parts = []
        if "SensorDeviceClass" in used_names:
            parts.append("SensorDeviceClass")
        if "SensorStateClass" in used_names:
            parts.append("SensorStateClass")
        new_imports.append(f"from homeassistant.components.sensor import {', '.join(parts)}")

    # Switch imports if needed
    if "SwitchEntityDescription" in used_names:
        new_imports.append("from homeassistant.components.switch import SwitchEntityDescription")

    # HA const imports
    if from_ha_const:
        new_imports.append("from homeassistant.const import (")
        for sym in from_ha_const:
            new_imports.append(f"    {sym},")
        new_imports.append(")")

    # Entity category
    if "EntityCategory" in used_names:
        new_imports.append("from homeassistant.helpers.entity import EntityCategory")

    new_imports.append("")

    # Local const imports
    if from_const:
        new_imports.append("from custom_components.solax_modbus.const import (")
        for sym in from_const:
            new_imports.append(f"    {sym},")
        new_imports.append(")")

    new_imports.append("")
    new_imports.append("from .pymodbus_compat import DataType, convert_from_registers")

    # Find where to insert (after star import line)
    lines = content.split("\n")
    insert_at = 0
    for i, line in enumerate(lines):
        if "from custom_components.solax_modbus.const import *" in line:
            # Find next non-blank, non-import line
            for j in range(i + 1, len(lines)):
                stripped = lines[j].strip()
                if stripped and not stripped.startswith("from ") and not stripped.startswith("import "):
                    insert_at = j
                    break
            break

    # Rebuild file
    before = lines[:insert_at]
    # Remove old imports
    before = [
        line
        for line in before
        if not (
            line.strip().startswith("import logging")
            or line.strip().startswith("from dataclasses")
            or line.strip().startswith("from time import")
            or line.strip().startswith("from homeassistant.")
            or line.strip().startswith("from .pymodbus_compat")
            or "from custom_components.solax_modbus.const import *" in line
        )
        or line.strip() == ""
    ]

    after = lines[insert_at:]

    # Combine
    new_content = "\n".join(new_imports) + "\n\n" + "\n".join(after)

    # Write back
    with open(filepath, "w") as f:
        f.write(new_content)

    print(f"✅ {filepath.name}: {len(from_const)} const symbols, {len(from_ha_const)} HA symbols")
    return True


def main():
    """Convert all remaining plugin files."""
    const_symbols = get_all_const_symbols()
    print(f"Found {len(const_symbols)} symbols in const.py\n")

    plugin_dir = Path(__file__).parent.parent / "custom_components" / "solax_modbus"

    # Files to process (already have star imports)
    files_to_process = [
        "plugin_Enertech.py",
        "plugin_alphaess.py",
        "plugin_solax_a1j1.py",
        "plugin_swatten.py",
        "plugin_sofar_old.py",
        "plugin_solax_mega_forth.py",
        "plugin_solinteg.py",
        "plugin_solis_fb00.py",
        "plugin_solis.py",
        "plugin_sunway.py",
        "plugin_growatt.py",
        "plugin_solax_lv.py",
        "plugin_sofar.py",
        "plugin_solax.py",
    ]

    for filename in files_to_process:
        filepath = plugin_dir / filename
        if filepath.exists():
            try:
                convert_plugin_file(filepath, const_symbols)
            except Exception as e:
                print(f"❌ {filename}: {e}")
                return False

    print(f"\n✅ Successfully converted {len(files_to_process)} files!")
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
