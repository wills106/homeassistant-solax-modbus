#!/usr/bin/env python3
"""Print exact imports needed for each problem file."""

from pathlib import Path

from smart_convert import analyze_file, get_const_symbols


def print_imports_for_file(filename):
    """Print import block for a file."""
    plugin_dir = Path(__file__).parent.parent / "custom_components" / "solax_modbus"
    filepath = plugin_dir / filename
    const_symbols = get_const_symbols()
    analysis = analyze_file(filepath, const_symbols)

    print(f"\n{'=' * 80}")
    print(f"File: {filename}")
    print(f"{'=' * 80}\n")

    # Print const imports
    print("from custom_components.solax_modbus.const import (")
    for sym in analysis["from_const"]:
        print(f"    {sym},")
    print(")")


if __name__ == "__main__":
    files = [
        "plugin_sunway.py",  # Smallest
        "plugin_solinteg.py",
        "plugin_growatt.py",
        "plugin_solax_lv.py",
        "plugin_sofar.py",
        "plugin_solax.py",  # Largest
    ]

    for f in files:
        print_imports_for_file(f)
