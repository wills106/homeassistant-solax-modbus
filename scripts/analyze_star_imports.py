#!/usr/bin/env python3
"""Analyze symbol usage in plugin files to prepare for star import elimination."""

import ast
from pathlib import Path


def get_const_exports():
    """Extract symbols exported from const.py."""
    const_file = Path(__file__).parent.parent / "custom_components" / "solax_modbus" / "const.py"
    with open(const_file) as f:
        tree = ast.parse(f.read())

    exports = set()
    for node in ast.walk(tree):
        # Class definitions
        if isinstance(node, ast.ClassDef):
            exports.add(node.name)
        # Top-level assignments
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    exports.add(target.id)

    return exports


def analyze_file(filepath, const_exports):
    """Analyze a single file for symbol usage."""
    with open(filepath) as f:
        content = f.read()
        tree = ast.parse(content, filepath)

    # Check if file has star import from const
    has_star_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "const" in node.module:
                if any(alias.name == "*" for alias in node.names):
                    has_star_import = True
                    break

    if not has_star_import:
        return None

    # Collect all name references
    name_refs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name_refs.add(node.id)

    # Categorize symbols
    from_const = name_refs & const_exports

    # Known HA symbols (partial list, extend as needed)
    ha_symbols = {
        "EntityCategory",
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
        "SensorDeviceClass",
        "NumberDeviceClass",
        "SensorStateClass",
        "ButtonEntityDescription",
        "NumberEntityDescription",
        "SelectEntityDescription",
        "SensorEntityDescription",
        "SwitchEntityDescription",
    }
    from_ha = name_refs & ha_symbols

    return {
        "file": filepath.name,
        "from_const": sorted(from_const),
        "from_ha": sorted(from_ha),
        "total_refs": len(name_refs),
    }


def main():
    """Analyze all plugin files."""
    plugin_dir = Path(__file__).parent.parent / "custom_components" / "solax_modbus"
    const_exports = get_const_exports()

    print(f"Found {len(const_exports)} symbols in const.py\n")

    results = []
    for plugin_file in sorted(plugin_dir.glob("plugin_*.py")):
        result = analyze_file(plugin_file, const_exports)
        if result:
            results.append(result)

    # Print summary
    print(f"Files with star imports: {len(results)}\n")
    print("=" * 80)

    for result in sorted(results, key=lambda x: len(x["from_const"])):
        print(f"\n{result['file']}")
        print(f"  Symbols from const: {len(result['from_const'])}")
        print(f"  HA symbols: {len(result['from_ha'])}")

        if len(result["from_const"]) <= 30:
            print(f"  From const: {', '.join(result['from_const'][:10])}")
            if len(result["from_const"]) > 10:
                print(f"              ... and {len(result['from_const']) - 10} more")

        if result["from_ha"]:
            print(f"  From HA: {', '.join(result['from_ha'])}")

    print("\n" + "=" * 80)
    print(f"\nTotal files to process: {len(results)}")
    print(f"Smallest: {min(results, key=lambda x: len(x['from_const']))['file']}")
    print(f"Largest: {max(results, key=lambda x: len(x['from_const']))['file']}")


if __name__ == "__main__":
    main()
