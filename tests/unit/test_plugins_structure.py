import importlib
import pathlib

import pytest

from custom_components.solax_modbus.const import plugin_base

# Find all plugin files
PLUGIN_DIR = pathlib.Path(__file__).parent.parent.parent / "custom_components" / "solax_modbus"
PLUGIN_FILES = [f.name[:-3] for f in PLUGIN_DIR.glob("plugin_*.py") if f.is_file() and not f.name.startswith("__")]


@pytest.mark.parametrize("plugin_module_name", PLUGIN_FILES)
def test_plugin_structure(plugin_module_name):
    """Verify that each plugin module has the required structure."""

    # Import the module dynamically
    module = importlib.import_module(f"custom_components.solax_modbus.{plugin_module_name}")

    # 1. Verify plugin_instance exists
    assert hasattr(module, "plugin_instance"), f"{plugin_module_name} missing 'plugin_instance'"

    plugin = module.plugin_instance

    # 2. Verify inheritance
    assert isinstance(plugin, plugin_base), f"{plugin_module_name} plugin_instance must inherit from plugin_base"

    # 3. Verify attributes
    assert plugin.plugin_name, f"{plugin_module_name} missing plugin_name"
    assert isinstance(plugin.SENSOR_TYPES, list), f"{plugin_module_name} SENSOR_TYPES must be a list"

    # 4. Verify Entity Integrity (basic check)
    all_entities = plugin.SENSOR_TYPES + plugin.BUTTON_TYPES + plugin.NUMBER_TYPES + plugin.SELECT_TYPES + plugin.SWITCH_TYPES

    for entity in all_entities:
        # Verify key exists and is string
        assert entity.key, f"Entity in {plugin_module_name} missing key"
        assert isinstance(entity.key, str), f"Entity key in {plugin_module_name} must be string"

        # Verify allowedtypes is an integer (bitmask)
        assert isinstance(entity.allowedtypes, int), f"Entity '{entity.key}' allowedtypes must be int in {plugin_module_name}"
