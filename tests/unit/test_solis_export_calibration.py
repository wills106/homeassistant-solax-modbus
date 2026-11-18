"""Verify signed watt readback and writes for Solis export calibration."""

from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import UnitOfPower

from custom_components.solax_modbus import plugin_solis, plugin_solis_fb00
from custom_components.solax_modbus.const import REG_HOLDING, REGISTER_S16
from custom_components.solax_modbus.number import SolaXModbusNumber

from .test_write_pipeline import make_hub


@pytest.mark.parametrize("plugin", [plugin_solis, plugin_solis_fb00], ids=["solis", "solis-fb00"])
async def test_export_calibration_reads_and_writes_signed_watts(plugin: ModuleType) -> None:
    key = "export_calibration"
    number = next(description for description in plugin.NUMBER_TYPES if description.key == key)
    readback = next(description for description in plugin.SENSOR_TYPES if description.key == key)

    assert number.register == readback.register == 43195
    assert number.register_data_type == readback.register_data_type == REGISTER_S16
    assert readback.register_type == REG_HOLDING
    assert number.native_unit_of_measurement == readback.native_unit_of_measurement == UnitOfPower.WATT
    assert not number.entity_registry_enabled_default
    assert not readback.entity_registry_enabled_default

    hub = make_hub()
    hub.plugin = plugin.plugin_instance
    hub.cyclecount = 1
    hub._validate_register_func = None
    hub.tmpdata_expiry = {}
    hub.localsLoaded = True
    hub._transport.write = AsyncMock(return_value=SimpleNamespace(isError=lambda: False))
    entity = SolaXModbusNumber("solis", hub, 1, {}, number)

    assert entity.native_min_value == -32768
    assert entity.native_max_value == 32767
    assert entity.native_step == 1
    assert hub.treat_address(hub.data, [0xFFE2], 0, readback) == 1
    assert entity.native_value == -30

    with patch.object(entity, "async_write_ha_state"):
        await entity.async_set_native_value(-100)

    hub._transport.write.assert_awaited_once_with(1, 43195, [0xFF9C], multiple=False)
    assert hub.treat_address(hub.data, [25], 0, readback) == 1
    assert entity.native_value == 25
