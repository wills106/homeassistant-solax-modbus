"""SerialX-backed Modbus RTU client compatibility layer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, TypeVar

from serialx import Parity, StopBits
from tmodbus import AsyncModbusClient, create_async_rtu_client
from tmodbus.exceptions import (
    ModbusConnectionError as TModbusConnectionError,
)
from tmodbus.exceptions import TModbusError

_PLACEHOLDER_UNIT_ID = 1

_T = TypeVar("_T")


class SerialModbusError(Exception):
    """Error raised by the SerialX-backed Modbus client."""


@dataclass(slots=True)
class SerialModbusResponse:
    """Pymodbus-compatible successful response used by the existing hub."""

    registers: list[int]

    def isError(self) -> bool:
        """Return False because transport and Modbus errors raise exceptions."""
        return False


class AsyncSerialModbusClient:
    """Expose the small client surface used by SolaX over tmodbus and SerialX."""

    def __init__(
        self,
        *,
        port: str,
        baudrate: int,
        parity: str,
        stopbits: int,
        bytesize: int,
        timeout: float,
        retries: int,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._parity = Parity(parity)
        self._stopbits = StopBits(stopbits)
        if bytesize != 8:
            raise ValueError("Modbus RTU requires 8 data bits")
        self._timeout = timeout
        self._retries = max(0, retries)
        self._client: AsyncModbusClient | None = None
        self._unit_clients: dict[int, AsyncModbusClient] = {}

        # Keep the diagnostics/logging attributes consumed by SolaXModbusHub.
        self.comm_params = SimpleNamespace(host=port, port=baudrate)

    @property
    def connected(self) -> bool:
        """Return whether the serial transport is connected."""
        return bool(self._client and self._client.connected)

    def _new_client(self) -> AsyncModbusClient:
        """Create a Modbus RTU client whose byte transport is SerialX."""
        # tmodbus 0.4.1 forwards timeout at runtime but omits it from SerialXOptions.
        return create_async_rtu_client(  # type: ignore[call-arg]
            self._port,
            unit_id=_PLACEHOLDER_UNIT_ID,
            baudrate=self._baudrate,
            parity=self._parity,
            stopbits=self._stopbits,
            timeout=self._timeout,
            auto_reconnect=False,
            retry_on_device_busy=False,
            retry_on_device_failure=False,
        )

    async def connect(self) -> bool:
        """Connect to the configured local port or SerialX URL."""
        if self.connected:
            return True

        await self.close()
        client = self._new_client()
        try:
            await client.connect()
        except (OSError, TimeoutError, TModbusError) as err:
            try:
                await client.disconnect()
            except (OSError, TModbusError):
                pass
            raise SerialModbusError(f"Unable to open serial Modbus port {self._port}") from err

        self._client = client
        return self.connected

    async def close(self) -> None:
        """Close the serial transport and discard unit-bound clients."""
        client = self._client
        self._client = None
        self._unit_clients.clear()
        if client is None:
            return
        try:
            await client.disconnect()
        except (OSError, TModbusError):
            pass

    def _client_for_unit(self, unit_id: int) -> AsyncModbusClient:
        """Return a client bound to one Modbus unit."""
        if self._client is None:
            raise SerialModbusError("Serial Modbus client is not connected")
        if unit_id not in self._unit_clients:
            self._unit_clients[unit_id] = self._client.for_unit_id(unit_id)
        return self._unit_clients[unit_id]

    @staticmethod
    def _unit_id(kwargs: dict[str, Any]) -> int:
        """Extract the unit id accepted by supported pymodbus versions."""
        unit_id = kwargs.pop("device_id", kwargs.pop("slave", None))
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected serial Modbus arguments: {unexpected}")
        if unit_id is None:
            raise TypeError("Serial Modbus unit id is required")
        return int(unit_id)

    async def _execute(
        self,
        unit_id: int,
        operation: Callable[[AsyncModbusClient], Awaitable[_T]],
    ) -> _T:
        """Execute one request and preserve the previous single-retry behavior."""
        for attempt in range(self._retries + 1):
            if not self.connected:
                await self.connect()
            try:
                return await operation(self._client_for_unit(unit_id))
            except (OSError, TimeoutError, TModbusConnectionError) as err:
                await self.close()
                if attempt >= self._retries:
                    raise SerialModbusError(str(err)) from err
            except TModbusError as err:
                raise SerialModbusError(str(err)) from err

        raise SerialModbusError("Serial Modbus request failed")

    async def read_holding_registers(
        self,
        *,
        address: int,
        count: int,
        **kwargs: Any,
    ) -> SerialModbusResponse:
        """Read holding registers."""
        unit_id = self._unit_id(kwargs)
        registers = await self._execute(
            unit_id,
            lambda client: client.read_holding_registers(address, count),
        )
        return SerialModbusResponse(list(registers))

    async def read_input_registers(
        self,
        *,
        address: int,
        count: int,
        **kwargs: Any,
    ) -> SerialModbusResponse:
        """Read input registers."""
        unit_id = self._unit_id(kwargs)
        registers = await self._execute(
            unit_id,
            lambda client: client.read_input_registers(address, count),
        )
        return SerialModbusResponse(list(registers))

    async def write_register(
        self,
        *,
        address: int,
        value: int,
        **kwargs: Any,
    ) -> SerialModbusResponse:
        """Write one holding register."""
        unit_id = self._unit_id(kwargs)
        await self._execute(
            unit_id,
            lambda client: client.write_single_register(address, value),
        )
        return SerialModbusResponse([])

    async def write_registers(
        self,
        *,
        address: int,
        values: list[int],
        **kwargs: Any,
    ) -> SerialModbusResponse:
        """Write multiple holding registers."""
        unit_id = self._unit_id(kwargs)
        await self._execute(
            unit_id,
            lambda client: client.write_multiple_registers(address, values),
        )
        return SerialModbusResponse([])
