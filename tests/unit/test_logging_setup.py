"""Test that logging is properly set up in all plugin files.

This test suite ensures that plugin files that use logging have properly
initialized the logger. This prevents runtime NameErrors when logging
functions are called.
"""

import ast
import importlib
from pathlib import Path

import pytest


def get_plugin_files():
    """Get all plugin files."""
    plugin_dir = Path(__file__).parent.parent.parent / "custom_components" / "solax_modbus"
    return sorted(plugin_dir.glob("plugin_*.py"))


def check_logger_usage(filepath):
    """Check if a file uses _LOGGER by analyzing AST."""
    with open(filepath) as f:
        tree = ast.parse(f.read(), filepath)

    for node in ast.walk(tree):
        # Check for _LOGGER.method() calls
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "_LOGGER":
                return True

    return False


def check_logger_definition(filepath):
    """Check if _LOGGER is defined in the file."""
    with open(filepath) as f:
        content = f.read()

    # Look for the standard logger definition
    return "_LOGGER = logging.getLogger(__name__)" in content


@pytest.mark.parametrize("plugin_file", get_plugin_files())
def test_logger_defined(plugin_file):
    """Test that files using _LOGGER have defined it.

    Bug: During Phase B import reorganization, plugin_solax.py lost
    its _LOGGER definition line, causing runtime NameError when
    logging methods were called.
    """
    uses_logger = check_logger_usage(plugin_file)
    has_logger_definition = check_logger_definition(plugin_file)

    if uses_logger:
        assert has_logger_definition, (
            f"{plugin_file.name} uses _LOGGER but doesn't define it. Add: _LOGGER = logging.getLogger(__name__)"
        )


@pytest.mark.parametrize("plugin_file", get_plugin_files())
def test_logging_import(plugin_file):
    """Test that files defining _LOGGER have imported logging module."""
    has_logger_definition = check_logger_definition(plugin_file)

    if has_logger_definition:
        with open(plugin_file) as f:
            tree = ast.parse(f.read(), plugin_file)

        # Check for 'import logging'
        has_logging_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "logging":
                        has_logging_import = True
                        break

        assert has_logging_import, f"{plugin_file.name} defines _LOGGER but doesn't import logging module"


def test_all_plugins_use_logger():
    """Verify that all plugin files use logging (sanity check)."""
    plugin_files = get_plugin_files()
    files_without_logger = []

    for plugin_file in plugin_files:
        if not check_logger_usage(plugin_file):
            files_without_logger.append(plugin_file.name)

    # All plugin files should use logging for consistency
    assert len(files_without_logger) == 0, f"These plugin files don't use _LOGGER (unexpected): {files_without_logger}"
