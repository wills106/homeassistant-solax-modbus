"""Test that import structure follows Phase B standards.

This test suite ensures that imports are organized according to the
conventions established during Phase B refactoring.
"""

import ast
from pathlib import Path

import pytest


def get_plugin_files():
    """Get all plugin files."""
    plugin_dir = Path(__file__).parent.parent.parent / "custom_components" / "solax_modbus"
    return sorted(plugin_dir.glob("plugin_*.py"))


def get_import_sections(filepath):
    """Extract import sections from a file."""
    with open(filepath) as f:
        lines = f.readlines()

    imports = {
        "stdlib": [],
        "homeassistant": [],
        "local": [],
    }

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            continue

        # Stdlib imports
        if stripped.startswith("import ") and not stripped.startswith("import homeassistant"):
            if "from " not in stripped:
                imports["stdlib"].append((i, stripped))

        # From stdlib imports
        if (
            stripped.startswith("from ")
            and not stripped.startswith("from homeassistant")
            and not stripped.startswith("from custom_components")
            and not stripped.startswith("from .")
        ):
            imports["stdlib"].append((i, stripped))

        # Home Assistant imports
        if "homeassistant" in stripped and (stripped.startswith("from ") or stripped.startswith("import ")):
            imports["homeassistant"].append((i, stripped))

        # Local imports
        if stripped.startswith("from custom_components") or stripped.startswith("from ."):
            imports["local"].append((i, stripped))

        # Stop at first non-import statement (after docstring)
        if stripped and not stripped.startswith(("import ", "from ", "#", '"""', "'''")) and i > 10:
            break

    return imports


@pytest.mark.parametrize("plugin_file", get_plugin_files())
def test_import_order(plugin_file):
    """Test that imports follow standard order: stdlib → HA → local.

    Phase B established this import structure:
    1. Standard library imports
    2. Home Assistant imports
    3. Local imports (custom_components)

    This order is enforced by Ruff's import sorting.
    """
    imports = get_import_sections(plugin_file)

    # Get line numbers of each section
    stdlib_lines = [line_no for line_no, _ in imports["stdlib"]]
    ha_lines = [line_no for line_no, _ in imports["homeassistant"]]
    local_lines = [line_no for line_no, _ in imports["local"]]

    # Check that sections are in order (allowing for docstrings and blank lines)
    if stdlib_lines and ha_lines:
        assert max(stdlib_lines) < min(ha_lines), f"{plugin_file.name}: stdlib imports should come before HA imports"

    if ha_lines and local_lines:
        assert max(ha_lines) < min(local_lines), f"{plugin_file.name}: HA imports should come before local imports"

    if stdlib_lines and local_lines:
        assert max(stdlib_lines) < min(local_lines), f"{plugin_file.name}: stdlib imports should come before local imports"


@pytest.mark.parametrize("plugin_file", get_plugin_files())
def test_const_import_explicit(plugin_file):
    """Test that const imports are explicit, not star imports.

    This is the core of Phase B: replacing 'from const import *'
    with explicit imports.
    """
    with open(plugin_file) as f:
        tree = ast.parse(f.read(), plugin_file)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "const" in node.module:
                for alias in node.names:
                    assert alias.name != "*", f"{plugin_file.name} line {node.lineno}: Found 'from {node.module} import *' - must be explicit"


@pytest.mark.parametrize("plugin_file", get_plugin_files())
def test_has_local_const_import(plugin_file):
    """Test that plugin files import from their local const module.

    All plugin files should import from custom_components.solax_modbus.const
    since that's where shared entity descriptions and constants live.
    """
    with open(plugin_file) as f:
        tree = ast.parse(f.read(), plugin_file)

    has_const_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "custom_components.solax_modbus.const" in node.module:
                has_const_import = True
                break

    assert has_const_import, (
        f"{plugin_file.name} doesn't import from custom_components.solax_modbus.const. "
        "Plugin files should import base classes and constants from const.py"
    )


def test_no_parenthesized_imports_without_reason():
    """Test that multi-line imports use parentheses consistently.

    Ruff formats multi-line imports with parentheses. This test
    ensures the format is consistent across all files.
    """
    plugin_files = get_plugin_files()

    for plugin_file in plugin_files:
        with open(plugin_file) as f:
            content = f.read()

        # Check that we don't have the old backslash continuation style
        assert "\\" not in content.split('"""')[0], (
            f"{plugin_file.name} uses backslash line continuation in imports. Use parentheses for multi-line imports instead."
        )


@pytest.mark.parametrize("plugin_file", get_plugin_files())
def test_unit_of_reactive_power_from_const_only(plugin_file):
    """Test that UnitOfReactivePower is only imported from const.py, not homeassistant.const.

    CRITICAL REGRESSION TEST:
    The const.py module has a backwards-compatibility fallback for UnitOfReactivePower
    that supports older Home Assistant versions. If plugins import UnitOfReactivePower
    directly from homeassistant.const, they will crash on older HA versions where
    this constant doesn't exist.

    Pattern in const.py:
        try:
            from homeassistant.const import UnitOfReactivePower
        except ImportError:
            class UnitOfReactivePower(StrEnum):  # fallback
                VOLT_AMPERE_REACTIVE = POWER_VOLT_AMPERE_REACTIVE

    Plugins must import UnitOfReactivePower from custom_components.solax_modbus.const
    to benefit from this fallback mechanism.
    """
    with open(plugin_file) as f:
        tree = ast.parse(f.read(), plugin_file)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # Check imports from homeassistant.const
            if node.module and node.module == "homeassistant.const":
                for alias in node.names:
                    assert alias.name != "UnitOfReactivePower", (
                        f"{plugin_file.name} line {node.lineno}: "
                        f"UnitOfReactivePower must be imported from "
                        f"custom_components.solax_modbus.const (has backwards-compat fallback), "
                        f"not directly from homeassistant.const"
                    )
