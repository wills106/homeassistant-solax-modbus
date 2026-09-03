"""Regression tests for config-entry-scoped device registry lookups."""

import ast
from pathlib import Path


def test_sensor_device_lookups_are_scoped_to_config_entry() -> None:
    """Prefer the scoped API while retaining compatibility with older HA."""
    sensor_tree = ast.parse(Path("custom_components/solax_modbus/sensor.py").read_text())
    helper = next(node for node in sensor_tree.body if isinstance(node, ast.FunctionDef) and node.name == "_get_device_by_identifier")
    helper_calls = [node for node in ast.walk(helper) if isinstance(node, ast.Call)]

    deprecated_calls = [
        call
        for call in ast.walk(sensor_tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "async_get_device"
    ]
    assert len(deprecated_calls) == 1
    assert deprecated_calls[0] in helper_calls

    scoped_lookup_checks = [
        call
        for call in helper_calls
        if isinstance(call.func, ast.Name)
        and call.func.id == "getattr"
        and len(call.args) >= 2
        and isinstance(call.args[1], ast.Constant)
        and call.args[1].value == "async_get_device_by_identifier"
    ]
    assert len(scoped_lookup_checks) == 1

    identifier_calls = [
        call
        for call in ast.walk(sensor_tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_get_device_by_identifier"
    ]
    assert identifier_calls

    for call in identifier_calls:
        assert len(call.args) == 3
        config_entry_id = call.args[2]
        assert isinstance(config_entry_id, ast.Attribute)
        assert isinstance(config_entry_id.value, ast.Name)
        assert config_entry_id.value.id == "entry"
        assert config_entry_id.attr == "entry_id"
