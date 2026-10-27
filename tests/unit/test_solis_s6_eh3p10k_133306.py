"""Detection and entity selection for the S6-EH3P10K-H-EU (#521)."""

from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.solax_modbus import plugin_solis, plugin_solis_fb00
from custom_components.solax_modbus.const import CONF_READ_DCB, CONF_READ_EPS
from tests.conftest import MockHub, MockModbusResponse


@pytest.mark.parametrize("module", [plugin_solis, plugin_solis_fb00])
@pytest.mark.parametrize("prefix", ["103306", "133306", "133307"])
@pytest.mark.parametrize("read_optional", [False, True])
async def test_three_phase_s6_detection(module: ModuleType, prefix: str, read_optional: bool, mock_hub: MockHub) -> None:
    """Keep the original prefix and give the tested alias the same four-MPPT profile."""
    serial = prefix.ljust(16, "0")
    registers = [int.from_bytes(serial[i : i + 2].encode("ascii"), "big") for i in range(0, 16, 2)]
    mock_hub.configure_read(1, 33004, 8, MockModbusResponse(registers))
    plugin = module.plugin_instance.create_hub_instance()

    read = AsyncMock(wraps=mock_hub.async_read_input_registers)
    with patch.object(mock_hub, "async_read_input_registers", read):
        inverter_type = await plugin.async_determineInverterType(mock_hub, {CONF_READ_EPS: read_optional, CONF_READ_DCB: read_optional})

    expected = 0 if prefix == "133307" else module.HYBRID | module.X3 | module.MPPT4
    if expected and read_optional:
        expected |= module.EPS | module.DCB
    assert inverter_type == expected
    assert mock_hub.seriesnumber == serial
    read.assert_awaited_once_with(unit=1, address=33004, count=8)

    if not expected:
        return

    sensors = {
        description.key: description
        for description in plugin.SENSOR_TYPES
        if plugin.matchInverterWithMask(inverter_type, description.allowedtypes, serial)
    }
    for mppt in (1, 2, 3, 4):
        assert sensors[f"pv_voltage_{mppt}"].register == 33047 + 2 * mppt
        assert sensors[f"pv_current_{mppt}"].register == 33048 + 2 * mppt
        assert f"pv_power_{mppt}" in sensors
    for phase in (1, 2, 3):
        assert sensors[f"grid_voltage_l{phase}"].register == 33072 + phase
        assert sensors[f"grid_current_l{phase}"].register == 33075 + phase
    assert "inverter_voltage" not in sensors
    assert "inverter_current" not in sensors
    assert sensors["battery_soc"].register == 33139
