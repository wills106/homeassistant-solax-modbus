"""The Sofar IV scan command requires FC16, even for its single register."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from pymodbus.pdu import ExceptionResponse

from custom_components.solax_modbus import SolaXModbusHub, plugin_sofar
from custom_components.solax_modbus.button import SolaXModbusButton
from custom_components.solax_modbus.const import DOMAIN, WRITE_MULTISINGLE_MODBUS
from custom_components.solax_modbus.modbus_transport import NativeModbusTransport
from custom_components.solax_modbus.pymodbus_compat import ADDR_KW


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_iv_curve_scan_writes_one_register_with_fc16(rejected: bool) -> None:
    description = next(description for description in plugin_sofar.BUTTON_TYPES if description.key == "IV_curve_scan")
    assert description.write_method == WRITE_MULTISINGLE_MODBUS
    assert description.register == 0x1027
    assert description.command == 1

    response = ExceptionResponse(function_code=16, exception_code=2) if rejected else SimpleNamespace(isError=lambda: False)
    client = SimpleNamespace(connected=True, write_register=AsyncMock(), write_registers=AsyncMock(return_value=response))
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "Sofar"
    hub.plugin = SimpleNamespace(order32="big")
    hub._transport = NativeModbusTransport(client)
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub._stopping = False
    button = SolaXModbusButton("Sofar", hub, 1, DeviceInfo(identifiers={(DOMAIN, "test")}), description)

    if rejected:
        with pytest.raises(HomeAssistantError, match="was rejected"):
            await button.async_press()
    else:
        await button.async_press()

    client.write_registers.assert_awaited_once_with(address=0x1027, values=[1], **{ADDR_KW: 1})
    client.write_register.assert_not_awaited()
    assert button.unique_id == "Sofar_IV_curve_scan"
