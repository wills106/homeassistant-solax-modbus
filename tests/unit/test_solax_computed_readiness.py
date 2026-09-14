"""Regression coverage for the SolaX startup-zero sensor set."""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.plugin_solax import SENSOR_TYPES_MAIN


def _computed_description(key: str) -> Any:
    return next(description for description in SENSOR_TYPES_MAIN if description.key == key and description.register < 0)


def _hub_with_data(data: dict[str, Any]) -> Any:
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "test"
    hub.data = data
    hub.sensorDescriptions = {key: SimpleNamespace() for key in data}
    return hub


@pytest.mark.parametrize(
    "key",
    [
        "bms_max_charge",
        "battery_voltage_cell_difference",
        "house_load",
        "remaining_battery_capacity",
    ],
)
def test_affected_solax_sensor_stays_unknown_without_inputs(key: str) -> None:
    hub = _hub_with_data({})
    description = _computed_description(key)

    assert hub.evaluate_computed_sensor(description, hub.data, force=True) is False
    assert key not in hub.data


@pytest.mark.parametrize(
    ("key", "data", "expected"),
    [
        ("bms_max_charge", {"battery_voltage_charge": 230, "bms_charge_max_current": 20}, 4600),
        ("battery_voltage_cell_difference", {"cell_voltage_high": 3.5, "cell_voltage_low": 3.4}, 0.1),
        ("house_load", {"inverter_power": 2500, "measured_power": 1000}, 1500),
        (
            "remaining_battery_capacity",
            {"bms_battery_capacity": 23040, "bms_2_battery_capacity": 0, "chargeable_battery_capacity": 8755},
            14285,
        ),
    ],
)
def test_affected_solax_sensor_computes_after_inputs_are_ready(key: str, data: dict[str, Any], expected: float) -> None:
    hub = _hub_with_data(data)
    description = _computed_description(key)

    assert hub.evaluate_computed_sensor(description, hub.data, set(data), force=True) is True
    assert hub.data[key] == pytest.approx(expected)
