"""Regression coverage for X3 GEN5 third-MPPT detection (#2374, #2420, #2453)."""

from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.plugin_solax import GEN5, HYBRID, MPPT3, SENSOR_TYPES_MAIN, X3, plugin_instance


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prefix", "has_mppt3", "model"),
    [
        ("P35G10", True, "X3-IES-10kW"),
        ("P35G12", True, "X3-IES-12kW"),
        ("P35G15", True, "X3-IES-15kW"),
        ("H35A06", False, "X3-IES-6kW"),
        ("H35A12", False, "X3-IES-12kW"),
        ("P35A10", True, "X3-IES-10kW"),
        ("P35A12", True, "X3-IES-12kW"),
        ("P35A15", True, "X3-IES-15kW"),
        ("P35A06", False, "X3-IES-6kW"),
        ("H35F06", False, "X3-IES-6kW"),
        ("H35F12", False, "X3-IES-12kW"),
        ("H3BF15KB", True, "X3-Ultra-15kW"),
        ("H3BF15L", True, "X3-Ultra-15kW"),
        ("H3BF15", False, "X3-Ultra-15kW"),
        ("H3BC15M", True, "X3-Ultra-15kW"),
        ("H3BC15L", True, "X3-Ultra-15kW"),
        ("H3BC15K", False, "X3-Ultra-15kW"),
        ("H3BC15", False, "X3-Ultra-15kW"),
    ],
)
async def test_x3_gen5_mppt_detection(mock_hub: Any, prefix: str, has_mppt3: bool, model: str) -> None:
    """Enable existing GEN5 PV3 sensors only for the affected model range."""
    plugin = replace(plugin_instance)
    mock_hub.data = {}
    serial_number = prefix + "12345678"
    with (
        patch("custom_components.solax_modbus.plugin_solax.async_read_serialnr", new=AsyncMock(return_value=serial_number)),
        patch("custom_components.solax_modbus.plugin_solax.async_read_inverter_firmware_info", new=AsyncMock()),
    ):
        inverter_type = await plugin.async_determineInverterType(mock_hub, {"read_eps": False, "read_pm": False})

    assert inverter_type == HYBRID | GEN5 | X3 | (MPPT3 if has_mppt3 else 0)
    assert mock_hub.inverter_model == model

    descriptions = {
        description.key: description
        for description in SENSOR_TYPES_MAIN
        if (description.modbus_min is None or description.modbus_min <= 1)
        and (description.modbus_max is None or description.modbus_max >= 1)
        and plugin.matchInverterWithMask(inverter_type, description.allowedtypes, serial_number, description.blacklist)
    }
    for key, register in (("pv_voltage_3", 0x122), ("pv_current_3", 0x123), ("pv_power_3", 0x124)):
        assert (key in descriptions) is has_mppt3
        if has_mppt3:
            assert descriptions[key].register == register
    assert "pv_power_4" not in descriptions

    # Exercise the actual computed sensor with the detected active dependencies.
    hub: Any = object.__new__(SolaXModbusHub)
    hub._name = "test"
    hub.sensorDescriptions = descriptions
    hub.data = {"pv_power_1": 1000, "pv_power_2": 2000}
    if has_mppt3:
        hub.data["pv_power_3"] = 3000
    assert hub.evaluate_computed_sensor(descriptions["pv_power_total"], hub.data, set(hub.data), force=True)
    assert hub.data["pv_power_total"] == (6000 if has_mppt3 else 3000)
