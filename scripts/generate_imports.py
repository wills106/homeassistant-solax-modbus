#!/usr/bin/env python3
"""Generate explicit import statements for a plugin file."""

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
    """Analyze a file and generate import statements."""
    with open(filepath) as f:
        content = f.read()
        tree = ast.parse(content, filepath)

    # Collect all name references
    name_refs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name_refs.add(node.id)

    # Symbols from const
    from_const = sorted(name_refs & const_exports)

    # Known HA symbols from homeassistant.const
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

    # Device classes from components
    device_classes = {
        "SensorDeviceClass",
        "NumberDeviceClass",
        "SensorStateClass",
    }
    from_device_classes = sorted(name_refs & device_classes)

    # Entity category
    has_entity_category = "EntityCategory" in name_refs

    return {
        "from_const": from_const,
        "from_ha_const": from_ha_const,
        "from_device_classes": from_device_classes,
        "has_entity_category": has_entity_category,
    }


def generate_import_block(analysis):
    """Generate the import block to add."""
    lines = []

    # Home Assistant const imports
    if analysis["from_ha_const"]:
        lines.append("from homeassistant.const import (")
        for symbol in analysis["from_ha_const"]:
            lines.append(f"    {symbol},")
        lines.append(")")

    # Entity category
    if analysis["has_entity_category"]:
        lines.append("from homeassistant.helpers.entity import EntityCategory")

    # Device classes (they're already imported explicitly in most files)
    # Skip these as they're typically already present

    # Local const imports
    if analysis["from_const"]:
        lines.append("from custom_components.solax_modbus.const import (")
        for symbol in analysis["from_const"]:
            lines.append(f"    {symbol},")
        lines.append(")")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_imports.py <plugin_file>")
        sys.exit(1)

    filepath = Path(sys.argv[1])
    if not filepath.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)

    const_exports = get_const_exports()
    analysis = analyze_file(filepath, const_exports)

    print(f"Import block for {filepath.name}:")
    print("=" * 80)
    print(generate_import_block(analysis))
    print("=" * 80)
    print(f"\nSymbols from const: {len(analysis['from_const'])}")
    print(f"Symbols from HA: {len(analysis['from_ha_const'])}")


if __name__ == "__main__":
    main()
