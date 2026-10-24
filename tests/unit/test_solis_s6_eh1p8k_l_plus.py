"""Detection and entity selection for the S6-EH1P8K-L-PLUS (#521)."""

from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.solax_modbus import plugin_solis, plugin_solis_fb00
from custom_components.solax_modbus.const import CONF_READ_DCB, CONF_READ_EPS
from tests.conftest import MockHub, MockModbusResponse


@pytest.mark.parametrize("module", [plugin_solis, plugin_solis_fb00])
@pytest.mark.parametrize("prefix", ["303126", "2051", "303127"])
@pytest.mark.parametrize("read_optional", [False, True])
async def test_single_phase_s6_detection(module: ModuleType, prefix: str, read_optional: bool, mock_hub: MockHub) -> None:
    """Read the exact new prefix, preserve existing detection and optional flags."""
    serial = prefix.ljust(16, "0")
    registers = [int.from_bytes(serial[i : i + 2].encode("ascii"), "big") for i in range(0, 16, 2)]
    mock_hub.configure_read(1, 33004, 8, MockModbusResponse(registers))
    plugin = module.plugin_instance.create_hub_instance()

    read = AsyncMock(wraps=mock_hub.async_read_input_registers)
    with patch.object(mock_hub, "async_read_input_registers", read):
        inverter_type = await plugin.async_determineInverterType(mock_hub, {CONF_READ_EPS: read_optional, CONF_READ_DCB: read_optional})

    expected = 0 if prefix == "303127" else module.HYBRID | module.X1
    if expected and read_optional:
        expected |= module.EPS | module.DCB
    assert inverter_type == expected
    assert mock_hub.seriesnumber == serial
    read.assert_awaited_once_with(unit=1, address=33004, count=8)

    if prefix != "303126":
        return

    sensors = {
        description.key: description
        for description in plugin.SENSOR_TYPES
        if plugin.matchInverterWithMask(inverter_type, description.allowedtypes, serial)
    }
    for mppt in (1, 2):
        assert sensors[f"pv_voltage_{mppt}"].register == 33047 + 2 * mppt
        assert sensors[f"pv_current_{mppt}"].register == 33048 + 2 * mppt
        assert f"pv_power_{mppt}" in sensors
    for mppt in (3, 4):
        assert all(f"pv_{measurement}_{mppt}" not in sensors for measurement in ("voltage", "current", "power"))
    assert sensors["inverter_voltage"].register == 33073
    assert sensors["inverter_current"].register == 33076
    assert all(f"grid_{measurement}_l{phase}" not in sensors for measurement in ("voltage", "current") for phase in (1, 2, 3))
    assert sensors["battery_soc"].register == 33139
