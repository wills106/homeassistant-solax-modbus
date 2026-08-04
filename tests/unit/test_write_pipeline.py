"""Tests for validated and atomic Modbus writes."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from pymodbus.pdu import ExceptionResponse

from custom_components.solax_modbus import (
    PendingWrite,
    RegisterEncodingError,
    SolaXCoreModbusHub,
    SolaXModbusHub,
    plugin_growatt,
)
from custom_components.solax_modbus.const import REGISTER_S16, REGISTER_S32, REGISTER_U16, REGISTER_U32
from custom_components.solax_modbus.modbus_transport import CoreModbusTransport, NativeModbusTransport
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
    hub._transport = NativeModbusTransport(client)
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


def test_multi_write_rejects_descriptor_without_register_type() -> None:
    hub = make_hub()
    hub.writeLocals["missing_type"] = SimpleNamespace(
        reverse_option_dict=None,
        scale=1,
        register_data_type=None,
    )

    with pytest.raises(HomeAssistantError, match="unsupported register data type"):
        hub._encode_multi_write_payload([("missing_type", 7)])


@pytest.mark.parametrize(
    ("register_data_type", "minimum", "maximum"),
    [
        (REGISTER_U16, 0, 65535),
        (REGISTER_S16, -32768, 32767),
        (REGISTER_U32, 0, 4294967295),
        (REGISTER_S32, -2147483648, 2147483647),
    ],
)
def test_encode_write_value_accepts_integer_register_boundaries(
    register_data_type: str,
    minimum: int,
    maximum: int,
) -> None:
    hub = make_hub()

    assert len(hub._encode_write_value(minimum, register_data_type, single_register=False)) in (1, 2)
    assert len(hub._encode_write_value(maximum, register_data_type, single_register=False)) in (1, 2)


@pytest.mark.parametrize(
    ("register_data_type", "value"),
    [
        (REGISTER_U16, -1),
        (REGISTER_U16, 65536),
        (REGISTER_S16, -32769),
        (REGISTER_S16, 32768),
        (REGISTER_U32, -1),
        (REGISTER_U32, 4294967296),
        (REGISTER_S32, -2147483649),
        (REGISTER_S32, 2147483648),
    ],
)
def test_encode_write_value_rejects_values_outside_integer_register_range(register_data_type: str, value: int) -> None:
    hub = make_hub()

    with pytest.raises(RegisterEncodingError, match="outside"):
        hub._encode_write_value(value, register_data_type, single_register=False)


def test_legacy_unspecified_single_register_type_remains_signed_16_bit() -> None:
    hub = make_hub()

    assert hub._encode_write_value(32767, None, single_register=True) == [32767]
    with pytest.raises(RegisterEncodingError, match="outside"):
        hub._encode_write_value(32768, None, single_register=True)


def test_growatt_vpp_allow_ac_charging_uses_supported_u16_write() -> None:
    description = next(description for description in plugin_growatt.SELECT_TYPES if description.key == "vpp_allow_ac_charging")
    hub = make_hub()

    assert description.register == 30410
    assert description.register_data_type == REGISTER_U16
    assert hub._encode_write_value(0, description.register_data_type, single_register=True) == [0]
    assert hub._encode_write_value(1, description.register_data_type, single_register=True) == [1]


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
async def test_single_write_rejects_multi_register_type_before_transport() -> None:
    client = FakeClient(SimpleNamespace(isError=lambda: False))
    hub = make_hub(client)

    with pytest.raises(RegisterEncodingError, match="requires 2 registers"):
        await hub.async_lowlevel_write_register(
            unit=1,
            address=36,
            payload=65536,
            register_data_type=REGISTER_U32,
        )

    assert client.write_register_calls == 0
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
async def test_sleeping_write_does_not_queue_unencodable_value() -> None:
    client = FakeClient(SimpleNamespace(isError=lambda: False))
    hub = make_hub(client)
    hub.plugin.isAwake = Mock(return_value=False)
    hub.writequeue = {}
    hub.wakeupButton = SimpleNamespace(register=1, command=1)
    hub._modbus_addr = 1

    with pytest.raises(RegisterEncodingError, match="outside"):
        await hub.async_write_register(
            unit=2,
            address=36,
            payload=65536,
            register_data_type=REGISTER_U16,
        )

    assert hub.writequeue == {}
    assert client.write_register_calls == 0
    assert client.write_registers_calls == 0


@pytest.mark.asyncio
async def test_core_multi_write_uses_core_client_and_validates_response() -> None:
    response = SimpleNamespace(isError=lambda: False)

    class FakeCoreHub:
        def __init__(self) -> None:
            self._client = SimpleNamespace(connected=True)
            self.config_delay = 0
            self.calls: list[tuple[int, int, int | list[int], str]] = []

        async def async_pb_call(self, unit: int, address: int, value: int | list[int], call_type: str) -> object:
            self.calls.append((unit, address, value, call_type))
            return response

    core_hub = FakeCoreHub()
    hub = cast(Any, object.__new__(SolaXCoreModbusHub))
    hub._name = "test"
    hub.plugin = SimpleNamespace(order32="big")
    hub.data = {}
    hub.writeLocals = {}
    hub._transport = CoreModbusTransport(
        cast(Any, object()),
        "core",
        "test",
        hub_getter=lambda hass, name: core_hub,
        reconnect_delay=0,
    )
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub._stopping = False
    hub._check_connection = AsyncMock(return_value=True)

    result = await hub.async_write_registers_multi(
        unit=1,
        address=100,
        payload=[(REGISTER_U16, 7), (REGISTER_S16, -2)],
    )

    assert result is response
    assert core_hub.calls == [(1, 100, [7, 65534], "write_registers")]


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
