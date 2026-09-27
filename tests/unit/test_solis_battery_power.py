"""Check Solis charge/discharge power without inventing missing input values."""

from types import ModuleType
from typing import Any, cast

import pytest

from custom_components import solax_modbus
from custom_components.solax_modbus import SolaXModbusHub, plugin_solis, plugin_solis_fb00


@pytest.mark.parametrize("plugin", [plugin_solis, plugin_solis_fb00], ids=["solis", "solis-fb00"])
@pytest.mark.parametrize(
    ("data", "charge", "discharge"),
    [
        ({"battery_charge_direction": 0, "battery_power": 1482}, 1482, 0),
        ({"battery_charge_direction": 1, "battery_power": 2181}, 0, 2181),
        ({"battery_charge_direction": 1, "battery_power": -542}, 0, 542),
        ({"battery_charge_direction": 0, "battery_power": 0}, 0, 0),
        ({"battery_charge_direction": 1, "battery_power": 0}, 0, 0),
        ({"battery_power": 1482}, None, None),
        ({"battery_charge_direction": None, "battery_power": 1482}, None, None),
        ({"battery_charge_direction": 2, "battery_power": 1482}, None, None),
        ({"battery_charge_direction": 0}, None, None),
        ({"battery_charge_direction": 1}, None, None),
        ({"battery_charge_direction": 0, "battery_power": None}, None, None),
        ({"battery_charge_direction": 1, "battery_power": None}, None, None),
        ({}, None, None),
    ],
)
def test_battery_power_requires_known_inputs(plugin: ModuleType, data: dict[str, Any], charge: int | None, discharge: int | None) -> None:
    """Missing direction must not label discharge as charging or fabricate zero."""
    descriptions = {description.key: description for description in plugin.SENSOR_TYPES}
    for key, expected in (("battery_input_energy", charge), ("battery_output_energy", discharge)):
        description = descriptions[key]
        assert description.value_function(0, description, data) == expected


@pytest.mark.parametrize("plugin", [plugin_solis, plugin_solis_fb00], ids=["solis", "solis-fb00"])
def test_battery_direction_is_polled_as_a_dependency(plugin: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Disabled raw entities remain polled when the derived battery sensors are enabled."""
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "Solis"
    hub._hass = None
    hub.plugin = plugin.plugin_instance
    hub.sensorDescriptions = {description.key: description for description in plugin.SENSOR_TYPES}
    hub.selectEntities = {}
    hub.numberEntities = {}
    hub.switchEntities = {}
    hub.sensorEntities = {}
    hub.bad_regs = {"holding": set(), "input": set()}
    derived = {"battery_input_energy", "battery_output_energy"}
    hub.entity_dependencies = {}
    for key in derived:
        for dependency in hub.sensorDescriptions[key].depends_on:
            hub.entity_dependencies.setdefault(dependency, []).append(key)
    monkeypatch.setattr(solax_modbus, "should_register_be_loaded", lambda hass, hub, description: description.key in derived)
    raw = {hub.sensorDescriptions[key].register: hub.sensorDescriptions[key] for key in ("battery_charge_direction", "battery_power")}
    blocks = hub.splitInBlocks(raw)
    assert {register for block in blocks for register in block.regs} == set(raw)

    # A fresh power sample alone must not be combined with an old charging direction.
    hub.computedSensors = {key: hub.sensorDescriptions[key] for key in derived}
    data = {"battery_charge_direction": 0, "battery_power": 2181, "battery_input_energy": 100, "battery_output_energy": 0}
    fresh = {"battery_power"}
    assert hub._compute_poll_sensors(data, fresh) == set()
    assert data["battery_input_energy"] == 100
    data["battery_charge_direction"] = 1
    fresh.add("battery_charge_direction")
    assert hub._compute_poll_sensors(data, fresh) == derived
    assert data["battery_input_energy"] == 0
    assert data["battery_output_energy"] == 2181
