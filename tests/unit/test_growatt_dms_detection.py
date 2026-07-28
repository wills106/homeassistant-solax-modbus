from typing import Any

import pytest

from custom_components.solax_modbus.plugin_growatt import (
    GEN4,
    HYBRID,
    MPPT3,
    X3,
)
from custom_components.solax_modbus.plugin_growatt import (
    plugin_instance as growatt_plugin,
)


@pytest.mark.asyncio
async def test_dms_serial_detects_mod_8000_tl3_hu(mock_hub: Any) -> None:
    serial_number = "DMS8G1E00M"
    serial_registers = [int.from_bytes(serial_number[index : index + 2].encode(), byteorder="big") for index in range(0, len(serial_number), 2)]
    firmware = b"DO1.0ZBDC\x00"
    firmware_registers = [int.from_bytes(firmware[index : index + 2], byteorder="big") for index in range(0, len(firmware), 2)]
    mock_hub.configure_read(
        1,
        3001,
        5,
        type(
            "MockResponse",
            (),
            {
                "registers": serial_registers,
                "isError": lambda self: False,
            },
        )(),
    )
    mock_hub.configure_read(
        1,
        9,
        5,
        type(
            "MockResponse",
            (),
            {
                "registers": firmware_registers,
                "isError": lambda self: False,
            },
        )(),
    )

    inverter_type = await growatt_plugin.async_determineInverterType(
        mock_hub,
        {"read_eps": False, "read_dcb": False},
    )

    assert inverter_type == HYBRID | GEN4 | X3 | MPPT3
    assert mock_hub.seriesnumber == serial_number
