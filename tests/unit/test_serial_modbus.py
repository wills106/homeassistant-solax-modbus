"""Tests for the SerialX-backed Modbus RTU client."""

from __future__ import annotations

from typing import Any

import pytest
from serialx import Parity, StopBits

from custom_components.solax_modbus import serial_modbus
from custom_components.solax_modbus.serial_modbus import AsyncSerialModbusClient

pytestmark = pytest.mark.asyncio


class FakeUnitClient:
    """Unit-bound tmodbus client used by the adapter tests."""

    def __init__(
        self,
        *,
        holding: list[int] | None = None,
        input_registers: list[int] | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.holding = holding or []
        self.input_registers = input_registers or []
        self.read_error = read_error
        self.calls: list[tuple[Any, ...]] = []

    async def read_holding_registers(self, address: int, count: int) -> list[int]:
        self.calls.append(("read_holding", address, count))
        if self.read_error:
            raise self.read_error
        return self.holding

    async def read_input_registers(self, address: int, count: int) -> list[int]:
        self.calls.append(("read_input", address, count))
        if self.read_error:
            raise self.read_error
        return self.input_registers

    async def write_single_register(self, address: int, value: int) -> None:
        self.calls.append(("write_single", address, value))

    async def write_multiple_registers(self, address: int, values: list[int]) -> None:
        self.calls.append(("write_multiple", address, values))


class FakeClient:
    """Minimal tmodbus client used to verify lifecycle behavior."""

    def __init__(self, unit_client: FakeUnitClient) -> None:
        self.connected = False
        self.unit_client = unit_client
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.unit_ids: list[int] = []

    async def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def for_unit_id(self, unit_id: int) -> FakeUnitClient:
        self.unit_ids.append(unit_id)
        return self.unit_client


def make_client(port: str, *, retries: int = 1) -> AsyncSerialModbusClient:
    """Create the adapter with the existing SolaX serial defaults."""
    return AsyncSerialModbusClient(
        port=port,
        baudrate=9600,
        parity="N",
        stopbits=1,
        bytesize=8,
        timeout=5,
        retries=retries,
    )


@pytest.mark.parametrize(
    "port",
    [
        "/dev/serial/by-id/usb-existing-adapter",
        "esphome-hass://esphome/entry-id?port_name=Inverter%20RS485",
    ],
)
async def test_port_is_passed_unchanged_to_serialx_backend(
    monkeypatch: pytest.MonkeyPatch,
    port: str,
) -> None:
    """Existing local paths and ESPHome proxy URLs use the same transport."""
    fake = FakeClient(FakeUnitClient(holding=[27, 0]))
    factory_calls: list[tuple[str, dict[str, Any]]] = []

    def factory(received_port: str, **kwargs: Any) -> FakeClient:
        factory_calls.append((received_port, kwargs))
        return fake

    monkeypatch.setattr(serial_modbus, "create_async_rtu_client", factory)

    client = make_client(port)
    assert await client.connect()
    response = await client.read_holding_registers(
        address=16,
        count=2,
        device_id=1,
    )

    assert factory_calls == [
        (
            port,
            {
                "unit_id": 1,
                "baudrate": 9600,
                "parity": Parity.NONE,
                "stopbits": StopBits.ONE,
                "timeout": 5,
                "auto_reconnect": False,
                "retry_on_device_busy": False,
                "retry_on_device_failure": False,
            },
        )
    ]
    assert response.registers == [27, 0]
    assert not response.isError()
    assert fake.unit_ids == [1]


async def test_read_retries_once_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new backend preserves the previous retries=1 behavior."""
    clients = [
        FakeClient(FakeUnitClient(read_error=TimeoutError("no response"))),
        FakeClient(FakeUnitClient(input_registers=[2300])),
    ]

    def factory(*args: Any, **kwargs: Any) -> FakeClient:
        return clients.pop(0)

    monkeypatch.setattr(serial_modbus, "create_async_rtu_client", factory)

    client = make_client("/dev/ttyUSB0")
    response = await client.read_input_registers(
        address=0,
        count=1,
        slave=2,
    )

    assert response.registers == [2300]
    assert not clients


async def test_writes_return_compatible_success_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing write validation continues to receive isError responses."""
    unit = FakeUnitClient()
    fake = FakeClient(unit)
    monkeypatch.setattr(
        serial_modbus,
        "create_async_rtu_client",
        lambda *args, **kwargs: fake,
    )

    client = make_client("/dev/ttyUSB0")
    single = await client.write_register(
        address=10,
        value=5,
        device_id=3,
    )
    multiple = await client.write_registers(
        address=20,
        values=[1, 2],
        device_id=3,
    )

    assert not single.isError()
    assert not multiple.isError()
    assert unit.calls == [
        ("write_single", 10, 5),
        ("write_multiple", 20, [1, 2]),
    ]


async def test_close_waits_for_serial_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unload closes SerialX deterministically."""
    fake = FakeClient(FakeUnitClient())
    monkeypatch.setattr(
        serial_modbus,
        "create_async_rtu_client",
        lambda *args, **kwargs: fake,
    )

    client = make_client("/dev/ttyUSB0")
    await client.connect()
    await client.close()

    assert not client.connected
    assert fake.disconnect_calls == 1
