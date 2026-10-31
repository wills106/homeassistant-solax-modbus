"""Regressions for devices that need a quiet interval between requests."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol

from custom_components.solax_modbus import modbus_transport as transport
from custom_components.solax_modbus.config_flow import TCP_SCHEMA
from custom_components.solax_modbus.core_modbus import configured_core_connection


@pytest.mark.parametrize("milliseconds", [0, 150, 1000])
def test_tcp_spacing_reaches_core_connection(milliseconds: int) -> None:
    options = TCP_SCHEMA({"host": "192.0.2.1", "message_wait_milliseconds": milliseconds})
    settings = configured_core_connection({**options, "interface": "core_tcp"})
    assert settings is not None
    assert settings["message_wait_milliseconds"] == milliseconds


def test_tcp_spacing_defaults_to_zero() -> None:
    options = TCP_SCHEMA({"host": "192.0.2.1"})
    assert options["message_wait_milliseconds"] == 0


@pytest.mark.parametrize("value", [-1, 1001, "invalid"])
def test_tcp_spacing_rejects_invalid_values(value: Any) -> None:
    with pytest.raises(vol.Invalid):
        TCP_SCHEMA({"host": "192.0.2.1", "message_wait_milliseconds": value})


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = SimpleNamespace(now=100.0, waits=[])

    async def sleep(delay: float) -> None:
        state.waits.append(delay)
        state.now += delay

    monkeypatch.setattr(transport, "monotonic", lambda: state.now)
    monkeypatch.setattr(transport, "_sleep", sleep)
    return state


def client() -> Any:
    return SimpleNamespace(
        read_holding_registers=AsyncMock(return_value="holding"),
        read_input_registers=AsyncMock(return_value="input"),
        write_register=AsyncMock(return_value="single"),
        write_registers=AsyncMock(return_value="multiple"),
    )


async def test_reads_and_writes_share_completion_spacing(clock: Any) -> None:
    native = transport.NativeModbusTransport(client(), message_spacing=0.15)
    assert await native.read("holding", 1, 0, 1) == "holding"
    assert clock.waits == []
    # Time already spent outside the transport counts toward the quiet interval.
    clock.now += 0.05
    assert await native.write(1, 0, [1], multiple=False) == "single"
    assert await native.read("input", 1, 0, 1) == "input"
    assert await native.write(1, 0, [1, 2], multiple=True) == "multiple"
    assert clock.waits == pytest.approx([0.10, 0.15, 0.15])


async def test_spacing_starts_after_slow_request_completes(clock: Any) -> None:
    device = client()

    async def slow_read(**kwargs: Any) -> str:
        clock.now += 2
        return "holding"

    device.read_holding_registers.side_effect = slow_read
    native = transport.NativeModbusTransport(device, message_spacing=0.15)
    await native.read("holding", 1, 0, 1)
    await native.write(1, 0, [1], multiple=False)
    assert clock.waits == pytest.approx([0.15])


@pytest.mark.parametrize("error", [TimeoutError, asyncio.CancelledError])
async def test_failed_or_cancelled_request_still_requires_spacing(clock: Any, error: type[BaseException]) -> None:
    device = client()
    device.read_holding_registers.side_effect = error
    native = transport.NativeModbusTransport(device, message_spacing=0.15)
    with pytest.raises(error):
        await native.read("holding", 1, 0, 1)
    await native.write(1, 0, [1], multiple=False)
    assert clock.waits == pytest.approx([0.15])


async def test_zero_spacing_preserves_immediate_requests(clock: Any) -> None:
    native = transport.NativeModbusTransport(client())
    await native.read("holding", 1, 0, 1)
    await native.write(1, 0, [1], multiple=False)
    assert clock.waits == []


async def test_elapsed_quiet_interval_needs_no_sleep(clock: Any) -> None:
    native = transport.NativeModbusTransport(client(), message_spacing=0.15)
    await native.read("holding", 1, 0, 1)
    clock.now += 1
    await native.write(1, 0, [1], multiple=False)
    assert clock.waits == []


async def test_concurrent_read_and_write_cannot_bypass_spacing(clock: Any) -> None:
    device = client()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocking_read(**kwargs: Any) -> str:
        entered.set()
        await release.wait()
        return "holding"

    device.read_holding_registers.side_effect = blocking_read
    native = transport.NativeModbusTransport(device, message_spacing=0.15)
    read = asyncio.create_task(native.read("holding", 1, 0, 1))
    await entered.wait()
    write = asyncio.create_task(native.write(1, 0, [1], multiple=False))
    await asyncio.sleep(0)
    device.write_register.assert_not_awaited()
    release.set()
    read_result, write_result = await asyncio.gather(read, write)
    assert read_result == "holding"
    assert write_result == "single"
    assert clock.waits == pytest.approx([0.15])


async def test_cancel_during_spacing_sends_no_request(clock: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    entered = asyncio.Event()

    async def blocking_sleep(delay: float) -> None:
        entered.set()
        await asyncio.Event().wait()

    device = client()
    native = transport.NativeModbusTransport(device, message_spacing=0.15)
    await native.read("holding", 1, 0, 1)
    monkeypatch.setattr(transport, "_sleep", blocking_sleep)
    write = asyncio.create_task(native.write(1, 0, [1], multiple=False))
    await entered.wait()
    write.cancel()
    with pytest.raises(asyncio.CancelledError):
        await write
    device.write_register.assert_not_awaited()
    # Cancellation releases the lock and does not restart the quiet interval.
    clock.now += 0.15
    assert await native.read("input", 1, 0, 1) == "input"
