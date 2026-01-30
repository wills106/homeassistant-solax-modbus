"""Test that dataclasses imports are complete in plugin files.

This test suite ensures that plugin files that use dataclasses functions
have properly imported them. This prevents runtime NameErrors that unit
tests might not catch.
"""

import ast
import importlib
from pathlib import Path

import pytest


def get_plugin_files():
    """Get all plugin files."""
    plugin_dir = Path(__file__).parent.parent.parent / "custom_components" / "solax_modbus"
    return sorted(plugin_dir.glob("plugin_*.py"))


def check_function_usage(filepath, function_name):
    """Check if a file uses a specific function by analyzing AST."""
    with open(filepath) as f:
        tree = ast.parse(f.read(), filepath)

    for node in ast.walk(tree):
        # Check for direct function calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == function_name:
                return True
            # Check for attribute access (e.g., module.function)
            if isinstance(node.func, ast.Attribute) and node.func.attr == function_name:
                return True

    return False


def check_import_exists(filepath, module, name):
    """Check if a specific name is imported from a module."""
    with open(filepath) as f:
        tree = ast.parse(f.read(), filepath)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == module:
                for alias in node.names:
                    if alias.name == name or alias.name == "*":
                        return True

    return False


@pytest.mark.parametrize("plugin_file", get_plugin_files())
def test_replace_import(plugin_file):
    """Test that files using replace() have imported it from dataclasses.

    Bug: During Phase B star import removal, several files had
    'from dataclasses import dataclass' but used replace() without
    importing it, causing runtime NameError.
    """
    uses_replace = check_function_usage(plugin_file, "replace")
    has_replace_import = check_import_exists(plugin_file, "dataclasses", "replace")

    if uses_replace:
        assert has_replace_import, (
            f"{plugin_file.name} uses replace() but doesn't import it from dataclasses. "
            f"Add 'replace' to: from dataclasses import dataclass, replace"
        )


@pytest.mark.parametrize("plugin_file", get_plugin_files())
def test_dataclass_import(plugin_file):
    """Test that files using @dataclass have imported it.

    This is a sanity check - all plugin files should have dataclass imported.
    """
    with open(plugin_file) as f:
        content = f.read()

    # Check if @dataclass decorator is used
    if "@dataclass" in content:
        has_dataclass_import = check_import_exists(plugin_file, "dataclasses", "dataclass")
        assert has_dataclass_import, f"{plugin_file.name} uses @dataclass but doesn't import it from dataclasses"


def test_replace_usage_files():
    """Document which files actually use replace() for future reference."""
    plugin_dir = Path(__file__).parent.parent.parent / "custom_components" / "solax_modbus"
    files_using_replace = []

    for plugin_file in get_plugin_files():
        if check_function_usage(plugin_file, "replace"):
            files_using_replace.append(plugin_file.name)

    # This test documents the current state and will fail if new files start using replace
    # without proper imports (caught by test_replace_import)
    assert len(files_using_replace) > 0, "Expected some files to use replace()"

    # These are the known files as of Phase B implementation
    known_files = {
        "plugin_Enertech.py",
        "plugin_alphaess.py",
        "plugin_solax.py",
        "plugin_solax_a1j1.py",
        "plugin_solax_lv.py",
        "plugin_solax_mega_forth.py",
        "plugin_srne.py",
    }

    actual_files = set(files_using_replace)

    # If this fails, either:
    # 1. A new file started using replace() - update this test
    # 2. A file stopped using replace() - update this test
    assert actual_files == known_files, (
        f"Files using replace() changed. Added: {actual_files - known_files}, Removed: {known_files - actual_files}"
    )
