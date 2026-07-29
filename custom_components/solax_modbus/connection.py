"""Helpers for identifying configured Modbus connections."""

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT

from .const import (
    CONF_CORE_HUB,
    CONF_INTERFACE,
    CONF_MODBUS_ADDR,
    CONF_SERIAL_PORT,
    DEFAULT_MODBUS_ADDR,
    DEFAULT_PORT,
    DEFAULT_SERIAL_PORT,
    DOMAIN,
)


@dataclass(frozen=True)
class ModbusConnectionIdentity:
    """The configured path to one Modbus device."""

    interface: str
    endpoint: str
    modbus_addr: int
    port: int | None = None


def effective_entry_config(entry: Any) -> dict[str, Any]:
    """Return config entry data with current options taking precedence."""
    data = getattr(entry, "data", {}) or {}
    options = getattr(entry, "options", {}) or {}
    return {**dict(data), **dict(options)}


def configured_entry_name(entry: Any) -> str:
    """Return the user-visible name of a configured inverter."""
    config = effective_entry_config(entry)
    name = config.get(CONF_NAME) or getattr(entry, "title", None) or getattr(entry, "entry_id", "unknown")
    return str(name)


def _configured_interface(config: Mapping[str, Any]) -> str:
    interface = config.get(CONF_INTERFACE)
    if interface:
        return str(interface)
    return "serial" if config.get("read_serial", False) else "tcp"


def _normalized_host(host: Any) -> str:
    value = str(host).strip()
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        return value.rstrip(".").casefold()


def modbus_connection_identity(config: Mapping[str, Any]) -> ModbusConnectionIdentity | None:
    """Build a comparable identity for TCP, serial, or Core Modbus."""
    interface = _configured_interface(config)
    configured_addr = config.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    if configured_addr is None:
        configured_addr = DEFAULT_MODBUS_ADDR
    try:
        modbus_addr = int(configured_addr)
    except (TypeError, ValueError):
        return None

    if interface == "tcp":
        host = config.get(CONF_HOST)
        if not host:
            return None
        try:
            port = int(config.get(CONF_PORT, DEFAULT_PORT))
        except (TypeError, ValueError):
            return None
        return ModbusConnectionIdentity("tcp", _normalized_host(host), modbus_addr, port)

    if interface == "serial":
        serial_port = str(config.get(CONF_SERIAL_PORT, DEFAULT_SERIAL_PORT)).strip()
        if not serial_port:
            return None
        return ModbusConnectionIdentity("serial", serial_port, modbus_addr)

    if interface == "core":
        core_hub = str(config.get(CONF_CORE_HUB, "")).strip()
        if not core_hub:
            return None
        return ModbusConnectionIdentity("core", core_hub, modbus_addr)

    return None


def describe_modbus_connection(identity: ModbusConnectionIdentity) -> str:
    """Return a user-facing description of a Modbus connection."""
    if identity.interface == "tcp":
        host = f"[{identity.endpoint}]" if ":" in identity.endpoint else identity.endpoint
        return f"TCP {host}:{identity.port}, Modbus address {identity.modbus_addr}"
    if identity.interface == "serial":
        return f"serial {identity.endpoint}, Modbus address {identity.modbus_addr}"
    return f'Core Modbus "{identity.endpoint}", Modbus address {identity.modbus_addr}'


def matching_config_entries(
    hass: Any,
    config: Mapping[str, Any],
    *,
    exclude_entry_id: str | None = None,
    active_only: bool = False,
) -> list[Any]:
    """Return integration entries configured for the same Modbus device."""
    identity = modbus_connection_identity(config)
    if identity is None:
        return []

    matches: list[Any] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if getattr(entry, "entry_id", None) == exclude_entry_id:
            continue
        if active_only and (getattr(entry, "disabled_by", None) is not None or getattr(entry, "state", None) is not ConfigEntryState.LOADED):
            continue
        if modbus_connection_identity(effective_entry_config(entry)) == identity:
            matches.append(entry)
    return matches


def format_config_entry_names(entries: list[Any]) -> str:
    """Format inverter config entry names for warnings."""
    names = sorted((configured_entry_name(entry) for entry in entries), key=str.casefold)
    quoted = [f'"{name}"' for name in names]
    if len(quoted) < 2:
        return quoted[0] if quoted else ""
    if len(quoted) == 2:
        return " and ".join(quoted)
    return f"{', '.join(quoted[:-1])}, and {quoted[-1]}"
