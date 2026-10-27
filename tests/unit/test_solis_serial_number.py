"""Regression coverage for missing Solis serial-number responses (#2415)."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.solax_modbus.plugin_solis import async_read_serialnr
from tests.conftest import MockHub, MockModbusResponse


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, MockModbusResponse(error=True)], ids=["no-response", "modbus-error"])
@pytest.mark.parametrize("previous_serial", [None, "6031012345678901"])
async def test_failed_serial_read_has_no_traceback(
    mock_hub: MockHub, caplog: pytest.LogCaptureFixture, response: MockModbusResponse | None, previous_serial: str | None
) -> None:
    """Keep the normal read-failure warning without dereferencing a missing response."""
    mock_hub.seriesnumber = previous_serial
    read = AsyncMock(return_value=response)
    with patch.object(mock_hub, "async_read_input_registers", read):
        assert await async_read_serialnr(mock_hub, 33004, swapbytes=False) is None

    read.assert_awaited_once_with(unit=1, address=33004, count=8)
    assert mock_hub.seriesnumber == previous_serial
    assert "reading serial number from address 0x80ec failed" in caplog.text
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("swapbytes", [False, True])
async def test_successful_serial_read_preserves_byte_order(mock_hub: MockHub, swapbytes: bool) -> None:
    """Continue decoding and storing valid serial numbers in either byte order."""
    serial = "6031012345678901"
    registers = [int.from_bytes(serial[i : i + 2].encode("ascii"), "little" if swapbytes else "big") for i in range(0, len(serial), 2)]
    mock_hub.configure_read(1, 33004, 8, MockModbusResponse(registers))

    assert await async_read_serialnr(mock_hub, 33004, swapbytes=swapbytes) == serial
    assert mock_hub.seriesnumber == serial
