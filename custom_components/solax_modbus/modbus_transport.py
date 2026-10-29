"""Transport adapters for native and Home Assistant Core Modbus access."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any, Protocol, TypeVar
from weakref import ReferenceType, ref

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .core_modbus import core_connection_params
from .pymodbus_compat import ADDR_KW
from .serial_modbus import SerialModbusResponse

_LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")
MAX_RECOVERY_BACKOFF = 600.0

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


class CoreModbusUnitError(Exception):
    """A failure reported by Home Assistant's shared Modbus unit."""


class CoreModbusBackoff(CoreModbusUnitError):
    """A read was deferred, not attempted, while a failed connection recovers."""


def _get_core_unit(hass: HomeAssistant, entry: ConfigEntry, params: Any, unit: int) -> Any:
    """Request a unit; Core owns the link and releases it on entry unload."""
    from homeassistant.components import modbus

    getter = getattr(modbus, "async_get_unit", None)
    if getter is None:
        raise HomeAssistantError("Home Assistant's Modbus unit API is not available")
    return getter(hass, entry, params, unit)


class CoreModbusUnitTransport:
    """Public unit API adapter with lazy connection and Core-owned reconnects."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        settings: dict[str, Any],
        unit: int,
        *,
        unit_getter: Callable[[HomeAssistant, ConfigEntry, Any, int], Any] = _get_core_unit,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._params = core_connection_params(settings)
        self._settings = settings
        self._default_unit = unit
        self._unit_getter = unit_getter
        self._units: dict[int, Any] = {}
        self._closed = False
        self._request_lock = asyncio.Lock()
        self._backoff_delay = 0.0
        self._retry_at = 0.0
        self._unit(unit)

    @property
    def backoff_remaining(self) -> float:
        """Return the remaining cooldown without sleeping or holding a lock."""
        return max(0.0, self._retry_at - monotonic())

    @property
    def recovering(self) -> bool:
        """Keep recovery probes independent of the hub's sleep slowdown."""
        return self._backoff_delay > 0

    def _defer_recovery(self) -> None:
        self._backoff_delay = min(self._backoff_delay + float(self._settings["timeout"]), MAX_RECOVERY_BACKOFF)
        self._retry_at = monotonic() + self._backoff_delay
        _LOGGER.warning(
            "%s: read recovery paused for %.1f seconds (maximum 600 seconds); writes remain available", self.endpoint, self._backoff_delay
        )

    def _recovery_succeeded(self) -> None:
        if self.recovering:
            _LOGGER.warning("%s: Modbus replies restored; clearing read recovery backoff", self.endpoint)
        self._backoff_delay = 0.0
        self._retry_at = 0.0

    async def _request(self, client: Any, label: str, operation: Callable[[], Awaitable[_T]], *, read: bool) -> _T:
        """Retry one transport failure via HA; only reads enter a cooldown."""
        from modbus_connection.exceptions import ModbusConnectionError, ModbusError, ModbusTimeoutError

        async with self._request_lock:
            if self._closed:
                raise CoreModbusBackoff("Modbus transport is closed")
            if read and (remaining := self.backoff_remaining):
                raise CoreModbusBackoff(f"Connection recovery deferred for another {remaining:.1f} seconds")
            try:
                result = await operation()
            except (ModbusTimeoutError, ModbusConnectionError) as err:
                reason = "timed out" if isinstance(err, ModbusTimeoutError) else "lost or failed to establish its connection"
                _LOGGER.warning(
                    "%s: %s %s (configured timeout %.1fs); resetting the connection and retrying once: %s",
                    self.endpoint,
                    label,
                    reason,
                    self._settings["timeout"],
                    err,
                )
                if not read:
                    _LOGGER.warning(
                        "%s: %s may already have been applied despite the missing acknowledgement; repeating it once", self.endpoint, label
                    )
                try:
                    await client.disconnect()
                except (ModbusError, OSError, TimeoutError) as reset_error:
                    _LOGGER.warning("%s: connection reset for %s failed; no retry was sent: %s", self.endpoint, label, reset_error)
                    if read:
                        self._defer_recovery()
                    uncertainty = " The write may already have been applied." if not read else ""
                    raise CoreModbusUnitError(f"Connection reset for {label} failed; no retry was sent: {reset_error}.{uncertainty}") from reset_error
                if self._closed:
                    raise CoreModbusBackoff("Modbus transport closed during recovery") from err
                try:
                    # Unit I/O reconnects lazily and preserves the configured
                    # timeout, startup delay, spacing and other unit handles.
                    result = await operation()
                except (ModbusError, OSError, TimeoutError) as retry_error:
                    _LOGGER.warning("%s: reconnect or repeated %s failed; giving up this request: %s", self.endpoint, label, retry_error)
                    if read:
                        if isinstance(retry_error, (ModbusConnectionError, ModbusTimeoutError, OSError, TimeoutError)):
                            self._defer_recovery()
                        else:
                            # An explicit reply is not a stalled connection. Leave
                            # register errors available to the existing bisect path.
                            self._recovery_succeeded()
                    uncertainty = " The write may already have been applied." if not read else ""
                    raise CoreModbusUnitError(f"{label} failed after reconnect and one retry: {retry_error}.{uncertainty}") from retry_error
                _LOGGER.warning("%s: repeated %s succeeded after reconnect", self.endpoint, label)
            except (ModbusError, OSError, TimeoutError) as err:
                if isinstance(err, (OSError, TimeoutError)):
                    _LOGGER.warning("%s: %s could not connect or lost its connection: %s", self.endpoint, label, err)
                    if read:
                        self._defer_recovery()
                elif read:
                    self._recovery_succeeded()
                raise CoreModbusUnitError(str(err)) from err
            if read:
                self._recovery_succeeded()
            return result

    def _unit(self, unit_id: int) -> Any:
        if not 0 <= unit_id <= 255:
            raise HomeAssistantError(f"Invalid Modbus unit ID {unit_id}: expected 0 to 255")
        if unit_id not in self._units:
            unit = self._unit_getter(self._hass, self._entry, self._params, unit_id)
            unit.require_timeout(self._settings["timeout"])
            unit.require_connect_delay(self._settings["delay"])
            unit.set_message_spacing(self._settings["message_wait_milliseconds"] / 1000)
            self._units[unit_id] = unit
        return self._units[unit_id]

    @property
    def endpoint(self) -> str:
        return ":".join(str(part) for part in self._params.endpoint)

    def is_connected(self) -> bool:
        return not self._closed and any(unit.connected for unit in self._units.values())

    async def connect(self) -> bool:
        self._closed = False
        self._unit(self._default_unit)
        # Acquiring a unit does not open the link. The next I/O connects it.
        return True

    async def close(self) -> None:
        # Never disconnect a link shared with other integrations. A reconnect
        # retains our unit handles; actual teardown belongs to Core on unload.
        self._closed = True

    async def read(self, register_type: str, unit: int, address: int, count: int) -> SerialModbusResponse | None:
        if self._closed:
            return None
        client = self._unit(unit)
        operation = client.read_input_registers if register_type == "input" else client.read_holding_registers
        registers = await self._request(
            client, f"read {register_type} unit={unit} address=0x{address:x} count={count}", lambda: operation(address, count), read=True
        )
        return SerialModbusResponse(registers)

    async def write(self, unit: int, address: int, values: list[int], *, multiple: bool) -> SerialModbusResponse | None:
        if self._closed:
            return None
        client = self._unit(unit)
        values = list(values)  # Preserve the exact payload across a possible retry.

        async def operation() -> None:
            if multiple:
                await client.write_registers(address, values)
            else:
                await client.write_register(address, values[0])

        await self._request(client, f"write unit={unit} address=0x{address:x} count={len(values)}", operation, read=False)
        # The public API confirms successful writes by returning without error.
        return SerialModbusResponse([])


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
