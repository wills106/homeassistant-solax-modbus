#!/usr/bin/env python3
"""Smart conversion that excludes locally defined symbols."""

import ast
from pathlib import Path


def get_const_symbols():
    """Get all symbols from const.py."""
    const_file = Path(__file__).parent.parent / "custom_components" / "solax_modbus" / "const.py"
    with open(const_file) as f:
        tree = ast.parse(f.read())

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


def get_locally_defined(tree):
    """Get symbols defined locally in the file."""
    local_defs = set()

    # Top-level definitions
    for node in ast.walk(tree):
        # Function definitions
        if isinstance(node, ast.FunctionDef):
            local_defs.add(node.name)
            # Add function parameters
            for arg in node.args.args:
                local_defs.add(arg.arg)
            for arg in node.args.kwonlyargs:
                local_defs.add(arg.arg)
            if node.args.vararg:
                local_defs.add(node.args.vararg.arg)
            if node.args.kwarg:
                local_defs.add(node.args.kwarg.arg)

        # Class definitions
        elif isinstance(node, ast.ClassDef):
            local_defs.add(node.name)

        # Assignments (constants, variables)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    local_defs.add(target.id)

        # For loops
        elif isinstance(node, ast.For):
            if isinstance(node.target, ast.Name):
                local_defs.add(node.target.id)

        # List/Dict comprehensions
        elif isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
            for generator in node.generators:
                if isinstance(generator.target, ast.Name):
                    local_defs.add(generator.target.id)

    return local_defs


def get_used_names(tree):
    """Get all name references in the file."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
    return names


def analyze_file(filepath, const_symbols):
    """Analyze what symbols file needs from const (excluding local definitions)."""
    with open(filepath) as f:
        content = f.read()
        tree = ast.parse(content)

    used_names = get_used_names(tree)
    local_defs = get_locally_defined(tree)

    # Only consider names that are used but not defined locally
    external_names = used_names - local_defs

    # What's from const
    from_const = sorted(external_names & const_symbols)

    # HA const
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
    from_ha_const = sorted(external_names & ha_const_symbols)

    # Device classes
    has_sensor_device_class = "SensorDeviceClass" in external_names
    has_number_device_class = "NumberDeviceClass" in external_names
    has_sensor_state_class = "SensorStateClass" in external_names
    has_entity_category = "EntityCategory" in external_names

    return {
        "from_const": from_const,
        "from_ha_const": from_ha_const,
        "has_sensor_device_class": has_sensor_device_class,
        "has_number_device_class": has_number_device_class,
        "has_sensor_state_class": has_sensor_state_class,
        "has_entity_category": has_entity_category,
    }


def main():
    """Analyze remaining problem files."""
    const_symbols = get_const_symbols()

    plugin_dir = Path(__file__).parent.parent / "custom_components" / "solax_modbus"

    problem_files = [
        "plugin_growatt.py",
        "plugin_sofar.py",
        "plugin_solax.py",
        "plugin_solax_lv.py",
        "plugin_solinteg.py",
        "plugin_sunway.py",
    ]

    for filename in problem_files:
        filepath = plugin_dir / filename
        analysis = analyze_file(filepath, const_symbols)

        print(f"\n{filename}:")
        print(f"  From const ({len(analysis['from_const'])}): {', '.join(analysis['from_const'][:10])}")
        if len(analysis["from_const"]) > 10:
            print(f"    ... and {len(analysis['from_const']) - 10} more")
        print(f"  From HA ({len(analysis['from_ha_const'])}): {', '.join(analysis['from_ha_const'])}")
        print(
            f"  Device classes: SensorDC={analysis['has_sensor_device_class']}, NumberDC={analysis['has_number_device_class']}, SensorSC={analysis['has_sensor_state_class']}"
        )
        print(f"  EntityCategory: {analysis['has_entity_category']}")


if __name__ == "__main__":
    main()
