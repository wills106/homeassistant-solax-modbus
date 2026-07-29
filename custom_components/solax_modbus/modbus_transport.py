"""Transport adapters for native and Home Assistant Core Modbus access."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any, Protocol
from weakref import ReferenceType, ref

from homeassistant.core import HomeAssistant

from .pymodbus_compat import ADDR_KW

_LOGGER = logging.getLogger(__name__)

CORE_CALL_TYPE_REGISTER_HOLDING = "holding"
CORE_CALL_TYPE_REGISTER_INPUT = "input"
CORE_CALL_TYPE_WRITE_REGISTER = "write_register"
CORE_CALL_TYPE_WRITE_REGISTERS = "write_registers"


def _get_core_hub(hass: HomeAssistant, name: str) -> Any | None:
    """Resolve the optional Core Modbus hub without coupling native startup to it."""
    try:
        from homeassistant.components.modbus import get_hub
    except ImportError:
        return None
    try:
        return get_hub(hass, name)
    except KeyError:
        return None


class ModbusTransport(Protocol):
    """Common interface used by polling, writes and register quarantine."""

    @property
    def endpoint(self) -> str:
        """Return a human-readable transport endpoint."""

    def is_connected(self) -> bool:
        """Return whether the underlying transport is ready."""

    async def connect(self) -> bool:
        """Connect or attach to the underlying transport."""

    async def close(self) -> None:
        """Release the underlying transport."""

    async def read(self, register_type: str, unit: int, address: int, count: int) -> Any:
        """Read holding or input registers."""

    async def write(self, unit: int, address: int, values: list[int], *, multiple: bool) -> Any:
        """Write one or more registers."""


class NativeModbusTransport:
    """Transport backed by a pymodbus client owned by this integration."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @property
    def endpoint(self) -> str:
        params = getattr(self._client, "comm_params", None)
        host = getattr(params, "host", "")
        port = getattr(params, "port", "")
        return f"{host}:{port}" if host or port else "native Modbus"

    def is_connected(self) -> bool:
        return bool(getattr(self._client, "connected", False))

    async def connect(self) -> bool:
        if self.is_connected():
            return True
        connect = getattr(self._client, "connect", None)
        if connect is None:
            return False
        await connect()
        return self.is_connected()

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def read(self, register_type: str, unit: int, address: int, count: int) -> Any:
        kwargs = {ADDR_KW: unit} if unit is not None else {}
        if register_type == "input":
            return await self._client.read_input_registers(address=address, count=count, **kwargs)
        return await self._client.read_holding_registers(address=address, count=count, **kwargs)

    async def write(self, unit: int, address: int, values: list[int], *, multiple: bool) -> Any:
        kwargs = {ADDR_KW: unit} if unit is not None else {}
        if multiple:
            return await self._client.write_registers(address=address, values=values, **kwargs)
        return await self._client.write_register(address=address, value=values[0], **kwargs)


class CoreModbusTransport:
    """Transport delegated to a Home Assistant Core Modbus hub."""

    def __init__(
        self,
        hass: HomeAssistant,
        core_hub_name: str,
        owner_name: str,
        *,
        hub_getter: Callable[[HomeAssistant, str], Any] = _get_core_hub,
        reconnect_delay: float = 10,
    ) -> None:
        self._hass = hass
        self._core_hub_name = core_hub_name
        self._owner_name = owner_name
        self._hub_getter = hub_getter
        self._reconnect_delay = reconnect_delay
        self._hub_ref: ReferenceType[Any] | None = None
        self._closed = False

    def _hub_closed(self, reference: ReferenceType[Any]) -> None:
        if reference is self._hub_ref:
            self._hub_ref = None

    def _resolve_hub(self) -> Any | None:
        if self._closed:
            return None
        hub = self._hub_ref() if self._hub_ref is not None else None
        if hub is not None:
            return hub
        try:
            hub = self._hub_getter(self._hass, self._core_hub_name)
        except KeyError:
            return None
        if hub is not None:
            self._hub_ref = ref(hub, self._hub_closed)
        return hub

    @staticmethod
    def _config_delay(hub: Any) -> Any:
        return getattr(hub, "config_delay", getattr(hub, "_config_delay", 0))

    @classmethod
    def _hub_is_connected(cls, hub: Any) -> bool:
        client = getattr(hub, "_client", None)
        return bool(client and getattr(client, "connected", False) and not cls._config_delay(hub))

    @property
    def endpoint(self) -> str:
        hub = self._resolve_hub()
        params = getattr(hub, "_pb_params", {}) if hub is not None else {}
        host = params.get("host", "")
        port = params.get("port", "")
        return f"{host}:{port}" if host or port else f"Core Modbus hub '{self._core_hub_name}'"

    def is_connected(self) -> bool:
        hub = self._resolve_hub()
        return bool(hub and self._hub_is_connected(hub))

    async def connect(self) -> bool:
        self._closed = False
        hub = self._resolve_hub()
        if hub is None:
            _LOGGER.warning("CoreModbusHub '%s' not available", self._core_hub_name)
            return False
        if self._hub_is_connected(hub):
            return True

        await asyncio.sleep(self._reconnect_delay)
        hub = self._resolve_hub()
        if hub is not None and self._hub_is_connected(hub):
            return True

        reason = " during its configured startup delay" if hub is not None and self._config_delay(hub) else ""
        _LOGGER.warning("%s: Core Modbus hub '%s' is not ready%s", self._owner_name, self._core_hub_name, reason)
        return False

    async def close(self) -> None:
        # The Core hub owns the shared client. Only release our reference.
        self._closed = True
        self._hub_ref = None

    async def read(self, register_type: str, unit: int, address: int, count: int) -> Any:
        hub = self._resolve_hub()
        if hub is None or not self._hub_is_connected(hub):
            return None
        call_type = CORE_CALL_TYPE_REGISTER_INPUT if register_type == "input" else CORE_CALL_TYPE_REGISTER_HOLDING
        return await hub.async_pb_call(unit, address, count, call_type)

    async def write(self, unit: int, address: int, values: list[int], *, multiple: bool) -> Any:
        hub = self._resolve_hub()
        if hub is None or not self._hub_is_connected(hub):
            return None
        call_type = CORE_CALL_TYPE_WRITE_REGISTERS if multiple else CORE_CALL_TYPE_WRITE_REGISTER
        value: int | list[int] = values if multiple else values[0]
        return await hub.async_pb_call(unit, address, value, call_type)


class UnavailableModbusTransport:
    """Inert transport used for an invalid interface configuration."""

    def __init__(self, interface: str) -> None:
        self._interface = interface

    @property
    def endpoint(self) -> str:
        return f"unsupported interface '{self._interface}'"

    def is_connected(self) -> bool:
        return False

    async def connect(self) -> bool:
        return False

    async def close(self) -> None:
        return

    async def read(self, register_type: str, unit: int, address: int, count: int) -> None:
        return None

    async def write(self, unit: int, address: int, values: list[int], *, multiple: bool) -> None:
        return None
