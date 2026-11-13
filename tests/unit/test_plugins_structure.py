import importlib
import pathlib
from typing import Any

import pytest

from custom_components.solax_modbus.const import plugin_base

# Find all plugin files
PLUGIN_DIR = pathlib.Path(__file__).parent.parent.parent / "custom_components" / "solax_modbus"
PLUGIN_FILES = [f.name[:-3] for f in PLUGIN_DIR.glob("plugin_*.py") if f.is_file() and not f.name.startswith("__")]


def get_plugin(plugin_module_name: str) -> plugin_base:
    # Import the module dynamically
    module = importlib.import_module(f"custom_components.solax_modbus.{plugin_module_name}")

    # Module must have a plugin instance entry.
    assert hasattr(module, "plugin_instance"), f"{plugin_module_name} missing 'plugin_instance'"
    plugin = module.plugin_instance

    # Must inherit from the correct base
    assert isinstance(plugin, plugin_base), f"{plugin_module_name} plugin_instance must inherit from plugin_base"

    return plugin


@pytest.mark.parametrize("plugin_module_name", PLUGIN_FILES)
def test_plugin_structure(plugin_module_name: str) -> None:
    """Verify that each plugin module has the required structure."""

    # Get the plugin for this module name, ensuring it is valid
    plugin = get_plugin(plugin_module_name)

    # Verify plugin can create an instance
    runtime_plugin = plugin.create_hub_instance()
    assert runtime_plugin is not plugin, f"{plugin_module_name} must create a separate runtime plugin per hub"

    # Verify attributes
    assert plugin.plugin_name, f"{plugin_module_name} missing plugin_name"
    assert isinstance(plugin.SENSOR_TYPES, list), f"{plugin_module_name} SENSOR_TYPES must be a list"
    for collection_name in ("SENSOR_TYPES", "BUTTON_TYPES", "NUMBER_TYPES", "SELECT_TYPES", "SWITCH_TYPES", "TIME_TYPES"):
        assert getattr(runtime_plugin, collection_name) is not getattr(plugin, collection_name), (
            f"{plugin_module_name} runtime plugin must not share {collection_name} with its template"
        )

    # Verify Entity Integrity (basic check)
    all_entities: list[Any] = (
        list(plugin.SENSOR_TYPES) + list(plugin.BUTTON_TYPES) + list(plugin.NUMBER_TYPES) + list(plugin.SELECT_TYPES) + list(plugin.SWITCH_TYPES)
    )

    for entity in all_entities:
        # Verify key exists and is string
        assert entity.key, f"Entity in {plugin_module_name} missing key"
        assert isinstance(entity.key, str), f"Entity key in {plugin_module_name} must be string"

        # Verify allowedtypes is an integer (bitmask)
        assert isinstance(entity.allowedtypes, int), f"Entity '{entity.key}' allowedtypes must be int in {plugin_module_name}"


@pytest.mark.parametrize("plugin_module_name", PLUGIN_FILES)
def test_external_source_types_present_and_valid(plugin_module_name: str) -> None:
    # Find all sensors with external overrides and check that both the key names
    # are valid, and they exist in external source types.

    # Find all sensors for the plugin, and get any external overrides.
    plugin = get_plugin(plugin_module_name)
    required_overrides = [
        getattr(descr, "external_override", "") for descr in plugin.SENSOR_TYPES if getattr(descr, "external_override", None) is not None
    ]

    # All external overrides must start with "external_"
    assert all([key.startswith("external_") for key in required_overrides])
    # And they must exist in EXTERNAL_SOURCE_TYPES
    assert set([key.removeprefix("external_") for key in required_overrides]).issubset(plugin.EXTERNAL_SOURCE_TYPES.keys())
