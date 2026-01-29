"""Test that all modules can be imported."""

import importlib
import pkgutil

import pytest

from custom_components import solax_modbus


def get_all_modules():
    """Get all modules in the custom component."""
    modules = []
    path = solax_modbus.__path__
    prefix = solax_modbus.__name__ + "."

    for _, name, _ in pkgutil.walk_packages(path, prefix):
        modules.append(name)

    return modules


@pytest.mark.parametrize("module_name", get_all_modules())
def test_module_import(module_name):
    """Test that the module can be imported."""
    importlib.import_module(module_name)
