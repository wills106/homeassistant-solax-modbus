"""Tests for shared native and Home Assistant Core Modbus transports."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from pymodbus.exceptions import ConnectionException, ModbusIOException

from custom_components.solax_modbus import SolaXModbusHub, block
from custom_components.solax_modbus.const import REGISTER_U16
from custom_components.solax_modbus.modbus_transport import (
    CORE_CALL_TYPE_REGISTER_HOLDING,
    CORE_CALL_TYPE_REGISTER_INPUT,
    CORE_CALL_TYPE_WRITE_REGISTER,
    CORE_CALL_TYPE_WRITE_REGISTERS,
    CoreModbusTransport,
    NativeModbusTransport,
)
from custom_components.solax_modbus.pymodbus_compat import ADDR_KW


class FakeNativeClient:
    """Minimal pymodbus client for native transport contract tests."""

    def __init__(self, *, connected: bool = False, read_error: Exception | None = None, write_error: Exception | None = None) -> None:
        self.connected = connected
        self.comm_params = SimpleNamespace(host="192.0.2.1", port=502)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.close_calls = 0
        self.read_error = read_error
        self.write_error = write_error

    async def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.close_calls += 1
        self.connected = False

    async def read_holding_registers(self, **kwargs: Any) -> Any:
        self.calls.append(("read_holding", kwargs))
        if self.read_error is not None:
            raise self.read_error
        return SimpleNamespace(isError=lambda: False)

    async def read_input_registers(self, **kwargs: Any) -> Any:
        self.calls.append(("read_input", kwargs))
        if self.read_error is not None:
            raise self.read_error
        return SimpleNamespace(isError=lambda: False)

    async def write_register(self, **kwargs: Any) -> Any:
        self.calls.append(("write_register", kwargs))
        if self.write_error is not None:
            raise self.write_error
        return SimpleNamespace(isError=lambda: False)

    async def write_registers(self, **kwargs: Any) -> Any:
        self.calls.append(("write_registers", kwargs))
        if self.write_error is not None:
            raise self.write_error
        return SimpleNamespace(isError=lambda: False)


class FakeCoreHub:
    """Minimal Core Modbus hub exposing its supported call interface."""

    def __init__(self, responses: list[Any] | None = None, *, connected: bool = True, config_delay: int = 0) -> None:
        self._client = SimpleNamespace(connected=connected)
        self.config_delay = config_delay
        self._responses = list(responses or [])
        self.calls: list[tuple[int, int, int | list[int], str]] = []

    async def async_pb_call(self, unit: int, address: int, value: int | list[int], call_type: str) -> Any:
        self.calls.append((unit, address, value, call_type))
        if self._responses:
            return self._responses.pop(0)
        return SimpleNamespace(isError=lambda: False)


def make_modbus_io_exception(message: str) -> ModbusIOException:
    """Create a pymodbus I/O exception despite its untyped constructor."""
    return ModbusIOException(message)  # type: ignore[no-untyped-call]


def make_connection_exception(message: str) -> ConnectionException:
    """Create a pymodbus connection exception despite its untyped constructor."""
    return ConnectionException(message)  # type: ignore[no-untyped-call]


def make_core_transport(core_hub: FakeCoreHub) -> CoreModbusTransport:
    """Create a Core transport backed by a test hub."""
    return CoreModbusTransport(
        cast(Any, object()),
        "core",
        "test",
        hub_getter=lambda hass, name: core_hub,
        reconnect_delay=0,
    )


def make_quarantine_hub(core_hub: FakeCoreHub) -> Any:
    """Build the minimal integration hub state needed by quarantine probes."""
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._transport = make_core_transport(core_hub)
    hub._name = "test"
    hub._stopping = False
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub._modbus_addr = 1
    hub._time_out = 15
    hub.bisect_max_depth = 10
    hub.bad_regs = {"holding": set(), "input": set()}
    hub.initial_groups = {}
    hub.groups = {}
    hub.blocks_changed = False
    hub._comm_last_quarantined_register = None
    hub._comm_last_recovered_register = None
    hub._ensure_quarantine_recheck_task = Mock()
    hub._update_communication_data = Mock()
    hub._publish_communication_diagnostics = Mock()
    return hub


def make_native_hub(client: FakeNativeClient) -> Any:
    """Build the minimal integration hub state needed by native I/O tests."""
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._transport = NativeModbusTransport(client)
    hub._name = "test"
    hub._stopping = False
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub.plugin = SimpleNamespace(order32="big")
    return hub


@pytest.mark.asyncio
async def test_native_transport_implements_shared_read_write_contract() -> None:
    client = FakeNativeClient()
    transport = NativeModbusTransport(client)

    assert await transport.connect() is True
    assert transport.is_connected() is True
    assert transport.endpoint == "192.0.2.1:502"

    await transport.read("holding", unit=1, address=10, count=2)
    await transport.read("input", unit=2, address=20, count=3)
    await transport.write(unit=3, address=30, values=[7], multiple=False)
    await transport.write(unit=4, address=40, values=[8, 9], multiple=True)

    assert client.calls == [
        ("read_holding", {"address": 10, "count": 2, ADDR_KW: 1}),
        ("read_input", {"address": 20, "count": 3, ADDR_KW: 2}),
        ("write_register", {"address": 30, "value": 7, ADDR_KW: 3}),
        ("write_registers", {"address": 40, "values": [8, 9], ADDR_KW: 4}),
    ]

    await transport.close()
    assert transport.is_connected() is False


@pytest.mark.asyncio
async def test_read_timeout_leaves_connected_native_transport_open() -> None:
    client = FakeNativeClient(connected=True, read_error=make_modbus_io_exception("no response"))
    hub = make_native_hub(client)

    response = await hub.async_read_holding_registers(unit=1, address=9, count=5)

    assert response is None
    assert client.connected is True
    assert client.close_calls == 0


@pytest.mark.asyncio
async def test_read_connection_error_resets_native_transport() -> None:
    client = FakeNativeClient(connected=True, read_error=make_connection_exception("connection lost"))
    hub = make_native_hub(client)

    response = await hub.async_read_holding_registers(unit=1, address=9, count=5)

    assert response is None
    assert client.connected is False
    assert client.close_calls == 1


@pytest.mark.asyncio
async def test_write_timeout_leaves_connected_native_transport_open() -> None:
    client = FakeNativeClient(connected=True, write_error=make_modbus_io_exception("no response"))
    hub = make_native_hub(client)

    with pytest.raises(HomeAssistantError, match="single-register write failed"):
        await hub.async_lowlevel_write_register(unit=1, address=9, payload=1, register_data_type=REGISTER_U16)

    assert client.connected is True
    assert client.close_calls == 0


@pytest.mark.asyncio
async def test_write_connection_error_resets_native_transport() -> None:
    client = FakeNativeClient(connected=True, write_error=make_connection_exception("connection lost"))
    hub = make_native_hub(client)

    with pytest.raises(HomeAssistantError, match="single-register write failed"):
        await hub.async_lowlevel_write_register(unit=1, address=9, payload=1, register_data_type=REGISTER_U16)

    assert client.connected is False
    assert client.close_calls == 1


@pytest.mark.asyncio
async def test_core_transport_delegates_reads_and_writes_to_core_hub() -> None:
    core_hub = FakeCoreHub()
    transport = make_core_transport(core_hub)

    await transport.read("holding", unit=1, address=10, count=2)
    await transport.read("input", unit=2, address=20, count=3)
    await transport.write(unit=3, address=30, values=[7], multiple=False)
    await transport.write(unit=4, address=40, values=[8, 9], multiple=True)

    assert core_hub.calls == [
        (1, 10, 2, CORE_CALL_TYPE_REGISTER_HOLDING),
        (2, 20, 3, CORE_CALL_TYPE_REGISTER_INPUT),
        (3, 30, 7, CORE_CALL_TYPE_WRITE_REGISTER),
        (4, 40, [8, 9], CORE_CALL_TYPE_WRITE_REGISTERS),
    ]


def test_core_transport_uses_real_core_connection_state() -> None:
    core_hub = FakeCoreHub(connected=True)
    transport = make_core_transport(core_hub)

    assert transport.is_connected() is True

    core_hub.config_delay = 5
    assert transport.is_connected() is False

    core_hub.config_delay = 0
    core_hub._client.connected = False
    assert transport.is_connected() is False


@pytest.mark.asyncio
async def test_core_transport_close_does_not_close_shared_client() -> None:
    core_hub = FakeCoreHub()
    transport = make_core_transport(core_hub)

    assert transport.is_connected() is True
    await transport.close()

    assert core_hub._client.connected is True
    assert transport.is_connected() is False


@pytest.mark.asyncio
async def test_runtime_quarantine_operates_through_core_transport() -> None:
    success = SimpleNamespace(isError=lambda: False)
    core_hub = FakeCoreHub([None, None, success])
    hub = make_quarantine_hub(core_hub)
    hub._confirm_bad_register = AsyncMock(return_value=True)
    failing_block = block(start=10, end=12, descriptions={}, regs=[10, 11])

    await hub._runtime_bisect_block(failing_block, "holding", "holding:10-12")

    assert hub.bad_regs["holding"] == {10}
    assert core_hub.calls == [
        (1, 10, 2, CORE_CALL_TYPE_REGISTER_HOLDING),
        (1, 10, 1, CORE_CALL_TYPE_REGISTER_HOLDING),
        (1, 11, 1, CORE_CALL_TYPE_REGISTER_HOLDING),
    ]
    hub._ensure_quarantine_recheck_task.assert_called_once_with()
    hub._update_communication_data.assert_called_once_with()
    hub._publish_communication_diagnostics.assert_called_once_with()


@pytest.mark.asyncio
async def test_quarantined_register_is_rechecked_through_core_transport() -> None:
    core_hub = FakeCoreHub()
    hub = make_quarantine_hub(core_hub)
    hub.bad_regs["holding"].add(10)

    await hub._recheck_quarantined_register("holding", 10)

    assert hub.bad_regs["holding"] == set()
    assert hub.blocks_changed is True
    assert hub._comm_last_recovered_register == "holding 0xa"
    assert core_hub.calls == [(1, 10, 1, CORE_CALL_TYPE_REGISTER_HOLDING)]
