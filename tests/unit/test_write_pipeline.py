"""Tests for validated and atomic Modbus writes."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from pymodbus.pdu import ExceptionResponse

from custom_components.solax_modbus import PendingWrite, SolaXCoreModbusHub, SolaXModbusHub
from custom_components.solax_modbus.const import REGISTER_S16, REGISTER_U16
from custom_components.solax_modbus.switch import SolaXModbusSwitch


class FakeClient:
    """Minimal pymodbus client used by write tests."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.write_register_calls = 0
        self.write_registers_calls = 0

    async def write_register(self, **kwargs: object) -> object:
        self.write_register_calls += 1
        return self.response

    async def write_registers(self, **kwargs: object) -> object:
        self.write_registers_calls += 1
        return self.response


def make_hub(client: FakeClient | None = None) -> Any:
    """Build the minimal hub state required by the write helpers."""
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "test"
    hub.plugin = SimpleNamespace(order32="big")
    hub.data = {}
    hub.writeLocals = {}
    hub._client = client
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub._stopping = False
    hub._check_connection = AsyncMock(return_value=True)
    return hub


def test_validate_write_response_rejects_modbus_exception_response() -> None:
    hub = make_hub()
    response = ExceptionResponse(function_code=6, exception_code=2)

    with pytest.raises(HomeAssistantError, match="was rejected"):
        hub._validate_write_response(response, unit=1, address=36, operation="test write")


def test_encode_multi_write_payload_is_all_or_nothing() -> None:
    hub = make_hub()

    with pytest.raises(HomeAssistantError, match="cannot encode"):
        hub._encode_multi_write_payload(
            [
                (REGISTER_U16, 7),
                ("_unsupported", 8),
                (REGISTER_S16, 9),
            ]
        )


@pytest.mark.asyncio
async def test_multi_write_does_not_send_partially_encoded_payload() -> None:
    client = FakeClient(SimpleNamespace(isError=lambda: False))
    hub = make_hub(client)

    with pytest.raises(HomeAssistantError, match="cannot encode"):
        await hub.async_write_registers_multi(
            unit=1,
            address=100,
            payload=[
                (REGISTER_U16, 7),
                ("_unsupported", 8),
            ],
        )

    assert client.write_registers_calls == 0


@pytest.mark.asyncio
async def test_single_write_rejects_error_response() -> None:
    client = FakeClient(ExceptionResponse(function_code=6, exception_code=2))
    hub = make_hub(client)

    with pytest.raises(HomeAssistantError, match="was rejected"):
        await hub.async_lowlevel_write_register(
            unit=1,
            address=36,
            payload=10,
            register_data_type=REGISTER_U16,
        )


@pytest.mark.asyncio
async def test_sleeping_write_queues_full_request_without_reporting_success() -> None:
    hub = make_hub()
    hub.plugin.isAwake = Mock(return_value=False)
    hub.writequeue = {}
    hub.wakeupButton = SimpleNamespace(register=1, command=1)
    hub._modbus_addr = 1
    hub.async_lowlevel_write_register = AsyncMock(
        side_effect=[
            HomeAssistantError("write rejected"),
            SimpleNamespace(isError=lambda: False),
        ]
    )

    with pytest.raises(HomeAssistantError, match="queued for retry"):
        await hub.async_write_register(
            unit=2,
            address=36,
            payload=40000,
            register_data_type=REGISTER_U16,
        )

    assert hub.writequeue[(2, 36)] == PendingWrite(
        unit=2,
        address=36,
        payload=40000,
        register_data_type=REGISTER_U16,
    )


@pytest.mark.asyncio
async def test_core_multi_write_uses_core_client_and_validates_response() -> None:
    response = SimpleNamespace(isError=lambda: False)
    core_client = FakeClient(response)
    core_hub = SimpleNamespace(
        _client=core_client,
        _lock=asyncio.Lock(),
        _config_delay=False,
    )
    hub = cast(Any, object.__new__(SolaXCoreModbusHub))
    hub._name = "test"
    hub.plugin = SimpleNamespace(order32="big")
    hub.data = {}
    hub.writeLocals = {}
    hub._client = SimpleNamespace()
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub._stopping = False
    hub._check_connection = AsyncMock(return_value=core_hub)

    result = await hub.async_write_registers_multi(
        unit=1,
        address=100,
        payload=[(REGISTER_U16, 7), (REGISTER_S16, -2)],
    )

    assert result is response
    assert core_client.write_registers_calls == 1


@pytest.mark.asyncio
async def test_switch_does_not_publish_rejected_state() -> None:
    switch = cast(Any, object.__new__(SolaXModbusSwitch))
    switch._attr_is_on = False
    switch._last_command_time = None
    switch._write_switch_to_modbus = AsyncMock(side_effect=HomeAssistantError("write rejected"))
    switch.async_write_ha_state = Mock()

    with pytest.raises(HomeAssistantError, match="write rejected"):
        await switch._async_set_state(True)

    assert switch._attr_is_on is False
    assert switch._last_command_time is None
    switch.async_write_ha_state.assert_not_called()
