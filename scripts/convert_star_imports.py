#!/usr/bin/env python3
"""Convert star imports to explicit imports in plugin files."""

import ast
import sys
from pathlib import Path


def get_const_exports():
    """Extract symbols exported from const.py."""
    const_file = Path(__file__).parent.parent / "custom_components" / "solax_modbus" / "const.py"
    with open(const_file) as f:
        tree = ast.parse(f.read())

    exports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            exports.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    exports.add(target.id)

    return exports


def analyze_file(filepath, const_exports):
    """Analyze a file and collect needed imports."""
    with open(filepath) as f:
        content = f.read()
        tree = ast.parse(content, filepath)

    # Collect all name references
    name_refs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name_refs.add(node.id)

    # HA const symbols
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
    from_ha_const = sorted(name_refs & ha_const_symbols)

    # Device classes
    device_classes = {"SensorDeviceClass", "NumberDeviceClass", "SensorStateClass"}
    has_device_classes = bool(name_refs & device_classes)

    # Entity category
    has_entity_category = "EntityCategory" in name_refs

    # Symbols from const
    from_const = sorted(name_refs & const_exports)

    return {
        "from_const": from_const,
        "from_ha_const": from_ha_const,
        "has_device_classes": has_device_classes,
        "has_entity_category": has_entity_category,
    }


def convert_file(filepath):
    """Convert a file from star import to explicit imports."""
    const_exports = get_const_exports()
    analysis = analyze_file(filepath, const_exports)

    with open(filepath) as f:
        content = f.read()

    # Build new import block
    import_lines = []
    import_lines.append("import logging")
    import_lines.append("from dataclasses import dataclass")
    import_lines.append("from time import time")
    import_lines.append("")

    # HA component imports (keep existing pattern)
    import_lines.append("from homeassistant.components.button import ButtonEntityDescription")
    import_lines.append("from homeassistant.components.number import NumberEntityDescription")
    if analysis["has_device_classes"]:
        import_lines[-1] = "from homeassistant.components.number import NumberDeviceClass, NumberEntityDescription"
    import_lines.append("from homeassistant.components.select import SelectEntityDescription")
    if analysis["has_device_classes"]:
        import_lines.append("from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass")

    # HA const imports
    if analysis["from_ha_const"]:
        import_lines.append("from homeassistant.const import (")
        for symbol in analysis["from_ha_const"]:
            import_lines.append(f"    {symbol},")
        import_lines.append(")")

    # Entity category
    if analysis["has_entity_category"]:
        import_lines.append("from homeassistant.helpers.entity import EntityCategory")

    import_lines.append("")

    # Local const imports
    if analysis["from_const"]:
        import_lines.append("from custom_components.solax_modbus.const import (")
        for symbol in analysis["from_const"]:
            import_lines.append(f"    {symbol},")
        import_lines.append(")")

    import_lines.append("")
    import_lines.append("from .pymodbus_compat import DataType, convert_from_registers")

    new_import_block = "\n".join(import_lines)

    # Replace old import block (up to first non-import line)
    # Find where imports end
    lines = content.split("\n")
    import_end = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not (
            stripped.startswith("import ")
            or stripped.startswith("from ")
            or stripped.startswith("#")
            or line.startswith(" ")  # continuation
            or stripped == ""
        ):
            import_end = i
            break

    # Rebuild file
    rest_of_file = "\n".join(lines[import_end:])
    new_content = new_import_block + "\n\n" + rest_of_file

    with open(filepath, "w") as f:
        f.write(new_content)

    print(f"✅ Converted {filepath.name}")
    print(f"   Symbols from const: {len(analysis['from_const'])}")
    print(f"   Symbols from HA: {len(analysis['from_ha_const'])}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert_star_imports.py <plugin_file>")
        sys.exit(1)

    filepath = Path(sys.argv[1])
    if not filepath.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)

    convert_file(filepath)
