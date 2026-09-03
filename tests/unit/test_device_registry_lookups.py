"""Regression tests for config-entry-scoped device registry lookups."""

import ast
from pathlib import Path


def test_sensor_device_lookups_are_scoped_to_config_entry() -> None:
    """Use the modern device registry API with the owning config entry."""
    sensor_tree = ast.parse(Path("custom_components/solax_modbus/sensor.py").read_text())
    calls = [node for node in ast.walk(sensor_tree) if isinstance(node, ast.Call)]

    deprecated_calls = [call for call in calls if isinstance(call.func, ast.Attribute) and call.func.attr == "async_get_device"]
    assert not deprecated_calls

    identifier_calls = [call for call in calls if isinstance(call.func, ast.Attribute) and call.func.attr == "async_get_device_by_identifier"]
    assert identifier_calls

    for call in identifier_calls:
        assert len(call.args) == 2
        config_entry_id = call.args[1]
        assert isinstance(config_entry_id, ast.Attribute)
        assert isinstance(config_entry_id.value, ast.Name)
        assert config_entry_id.value.id == "entry"
        assert config_entry_id.attr == "entry_id"
