"""Regression coverage for the Gen2 Discharge Start 2 readback (#2379)."""

from datetime import time
from typing import Any, cast
from unittest.mock import patch

import pytest
from homeassistant.helpers.device_registry import DeviceInfo

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.const import DOMAIN, REGISTER_WORDS
from custom_components.solax_modbus.plugin_solax import GEN2, GEN4, GEN5, GEN6, HYBRID, SENSOR_TYPES_MAIN, TIME_TYPES, X1, plugin_instance
from custom_components.solax_modbus.time import SolaXModbusTimeEntity


@pytest.mark.parametrize(("hour", "minute"), [(0, 0), (6, 30), (23, 59)])
def test_gen2_discharge_start_2_reads_into_time_entity(hour: int, minute: int) -> None:
    """Decode the real two-register readback into the existing time entity."""
    inverter_type = HYBRID | GEN2 | X1
    readback = next(item for item in SENSOR_TYPES_MAIN if item.register == 0x9E and item.allowedtypes == HYBRID | GEN2)
    control = next(item for item in TIME_TYPES if item.key == "discharge_start_2" and item.allowedtypes == HYBRID | GEN2)
    assert plugin_instance.matchInverterWithMask(inverter_type, readback.allowedtypes)
    assert readback.key == control.key
    assert readback.internal
    assert readback.register_data_type == REGISTER_WORDS
    assert readback.wordcount == 2
    assert control.register == 0x2C

    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "test"
    hub.plugin = plugin_instance
    hub.data = {}
    hub.cyclecount = 1
    hub._validate_register_func = None
    hub.tmpdata_expiry = {}
    hub.localsLoaded = True
    assert hub.treat_address(hub.data, [hour, minute], 0, readback) == 2
    assert hub.data[control.key] == f"{hour:02d}:{minute:02d}"

    entity = SolaXModbusTimeEntity("test", hub, 1, DeviceInfo(identifiers={(DOMAIN, "test")}), control)
    with patch.object(entity, "async_write_ha_state"):
        entity.modbus_data_updated()
    assert entity.native_value == time(hour, minute)
    assert entity.unique_id == "test_discharge_start_2"


@pytest.mark.parametrize("generation", [GEN4, GEN5, GEN6])
def test_newer_discharge_start_2_readback_is_unchanged(generation: int) -> None:
    inverter_type = HYBRID | generation | X1
    readbacks = [
        item
        for item in SENSOR_TYPES_MAIN
        if item.key == "discharge_start_2" and plugin_instance.matchInverterWithMask(inverter_type, item.allowedtypes)
    ]
    assert len(readbacks) == 1
    assert readbacks[0].register == 0x9E
    assert readbacks[0].register_data_type != REGISTER_WORDS
