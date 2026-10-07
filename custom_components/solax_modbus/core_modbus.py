"""Prepare shared Core Modbus connections and preserve existing YAML hubs."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.reload import async_integration_yaml_config

from .const import (
    CONF_BAUDRATE,
    CONF_CORE_CONNECTION,
    CONF_CORE_HUB,
    CONF_INTERFACE,
    CONF_SERIAL_PORT,
    CONF_TCP_TYPE,
    CONF_TIME_OUT,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DEFAULT_TIME_OUT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
MIGRATION_URL = "https://github.com/wills106/homeassistant-solax-modbus/blob/main/docs/core-modbus-migration.md"


def supports_core_units() -> bool:
    """Require the public API needed to preserve timeout and startup delay."""
    try:
        from homeassistant.components import modbus
        from modbus_connection import ModbusUnit
    except ImportError:
        return False
    return callable(getattr(modbus, "async_get_unit", None)) and all(
        hasattr(ModbusUnit, method) for method in ("require_timeout", "require_connect_delay")
    )


def connection_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Extract connection settings, never YAML entities or unrelated options."""
    transport = str(config["type"])
    if transport not in ("tcp", "udp", "rtuovertcp", "ascii", "serial"):
        raise ValueError(f"Unsupported Core Modbus transport: {transport}")
    settings: dict[str, Any] = {
        "type": transport,
        "port": config["port"],
        "timeout": float(config.get("timeout", DEFAULT_TIME_OUT)),
        "delay": float(config.get("delay", 0)),
        "message_wait_milliseconds": float(config.get("message_wait_milliseconds", 30 if transport == "serial" else 0)),
    }
    if transport == "serial":
        settings.update(
            baudrate=int(config.get("baudrate", 9600)),
            bytesize=int(config.get("bytesize", 8)),
            parity=str(config.get("parity", "N")),
            stopbits=int(config.get("stopbits", 1)),
            method=str(config.get("method", "rtu")),
        )
    else:
        settings["host"] = str(config["host"])
        settings["port"] = int(config["port"])
    return settings


def configured_core_connection(config: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve saved YAML settings or the settings entered in the new flow."""
    interface = config.get(CONF_INTERFACE)
    if interface == "core":
        saved = config.get(CONF_CORE_CONNECTION)
        return connection_settings(saved) if isinstance(saved, dict) else None
    if interface == "core_tcp":
        return connection_settings(
            {
                "type": {"rtu": "rtuovertcp", "ascii": "ascii"}.get(str(config.get(CONF_TCP_TYPE, "tcp")), "tcp"),
                "host": config[CONF_HOST],
                "port": config.get(CONF_PORT, DEFAULT_PORT),
                "timeout": config.get(CONF_TIME_OUT, DEFAULT_TIME_OUT),
            }
        )
    if interface == "core_serial":
        return connection_settings(
            {
                "type": "serial",
                "port": config[CONF_SERIAL_PORT],
                "baudrate": int(config.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
                "bytesize": config.get("bytesize", 8),
                "parity": config.get("parity", "N"),
                "stopbits": config.get("stopbits", 1),
                "method": config.get("method", "rtu"),
                "timeout": config.get(CONF_TIME_OUT, DEFAULT_TIME_OUT),
            }
        )
    return None


def core_connection_params(settings: dict[str, Any]) -> Any:
    """Build the parameter object for Home Assistant's shared connection pool."""
    from modbus_connection import ModbusSerialParams, ModbusTcpParams, ModbusUdpParams

    transport = settings["type"]
    if transport == "serial":
        return ModbusSerialParams(
            device=settings["port"],
            baudrate=settings["baudrate"],
            bytesize=settings["bytesize"],
            parity=settings["parity"],
            stopbits=settings["stopbits"],
            framer=settings["method"],
        )
    host, port = settings["host"], settings["port"]
    if transport in ("rtuovertcp", "ascii"):
        # Serial framing over a socket also shares with equivalent serial URLs.
        host = f"[{host}]" if ":" in host else host
        return ModbusSerialParams(device=f"socket://{host}:{port}", baudrate=115200, framer="ascii" if transport == "ascii" else "rtu")
    if transport == "udp":
        return ModbusUdpParams(host=host, port=port)
    return ModbusTcpParams(host=host, port=port)


def _running_yaml_hubs(hass: HomeAssistant) -> dict[str, Any]:
    """Inspect presence only; never take ownership of Core's YAML clients."""
    from homeassistant.components.modbus import const

    return dict(hass.data.get(getattr(const, "DATA_MODBUS_HUBS", "modbus"), {}))


def _physical_endpoint(settings: dict[str, Any]) -> tuple[Any, ...]:
    """Detect competing links even when their framing differs."""
    if settings["type"] != "serial":
        return ("udp" if settings["type"] == "udp" else "tcp", settings["host"].casefold(), settings["port"])
    device = settings["port"]
    if device.startswith("socket://"):
        parsed = urlsplit(device)
        return ("tcp", (parsed.hostname or "").casefold(), parsed.port)
    return ("serial", device)


def _notification_id(entry: ConfigEntry) -> str:
    return f"{DOMAIN}_core_modbus_migration_{entry.entry_id}"


def _notify_migration(hass: HomeAssistant, entry: ConfigEntry, hub_name: str, *, saved: bool) -> None:
    name = entry.options.get(CONF_NAME, entry.title)
    if saved:
        action = (
            "The connection settings have been saved automatically. If this YAML hub is used only by this integration, "
            "back up your configuration, remove that hub from YAML and restart Home Assistant. "
            "The integration will then use the new connection automatically. Do not delete and re-add the integration."
        )
    else:
        action = (
            "The connection settings could not be saved. Keep the YAML hub configured. "
            "Check the integration log and follow the migration guide before changing your configuration."
        )
    persistent_notification.async_create(
        hass,
        f"**{name}** still uses the YAML Modbus hub **{hub_name}**. "
        "The API used to access this hub will be removed in Home Assistant **2027.10**.\n\n"
        f"{action}\n\n"
        "If other Modbus entities or integrations use this hub, keep it until they have also been migrated. "
        "Your current connection continues to work.\n\n"
        f"[Open the migration guide]({MIGRATION_URL})",
        title="SolaX Inverter Modbus: update your Core Modbus connection",
        notification_id=_notification_id(entry),
    )


async def async_prepare_core_connection(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Return a YAML hub to keep using, or None to use the new unit API.

    YAML is read through HA's loader (including packages and includes), never
    edited. A still-running hub prevents a second connection after a file edit.
    """
    config = dict(entry.options)
    interface = config.get(CONF_INTERFACE)
    if interface not in ("core", "core_tcp", "core_serial"):
        persistent_notification.async_dismiss(hass, _notification_id(entry))
        return None
    if not supports_core_units():
        if interface == "core":
            return str(config.get(CONF_CORE_HUB, ""))
        raise ConfigEntryNotReady("This connection requires Home Assistant's Modbus unit API with timeout and startup-delay support")

    try:
        yaml_config = await async_integration_yaml_config(hass, "modbus", raise_on_failure=True)
    except (HomeAssistantError, OSError, ValueError) as err:
        raise ConfigEntryNotReady(f"Cannot check YAML Modbus hubs safely: {err}") from err
    yaml_hubs = yaml_config.get("modbus", [])
    running = _running_yaml_hubs(hass)
    hub_name = str(config.get(CONF_CORE_HUB, "")) if interface == "core" else ""
    selected = next((hub for hub in yaml_hubs if hub.get("name") == hub_name), None)
    settings: dict[str, Any] | None

    if selected is not None:
        try:
            settings = connection_settings(selected)
            core_connection_params(settings)  # Validate before advertising saved settings.
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("%s: cannot save Core hub '%s' connection settings: %s", config.get(CONF_NAME), hub_name, err)
            _notify_migration(hass, entry, hub_name, saved=False)
            return hub_name
        if settings != config.get(CONF_CORE_CONNECTION):
            config[CONF_CORE_CONNECTION] = settings
            hass.config_entries.async_update_entry(entry, options=config)
        _notify_migration(hass, entry, hub_name, saved=True)
        return hub_name

    if hub_name in running:
        # The file was edited but the old client has not been stopped by HA yet.
        _notify_migration(hass, entry, hub_name, saved=bool(config.get(CONF_CORE_CONNECTION)))
        return hub_name

    settings = configured_core_connection(config)
    if settings is None:
        raise ConfigEntryNotReady("No saved Core Modbus settings. Restore the YAML hub and restart Home Assistant to copy them first.")
    endpoint = _physical_endpoint(settings)
    for other in yaml_hubs:
        if _physical_endpoint(connection_settings(other)) != endpoint:
            continue
        other_name = str(other["name"])
        if interface == "core":
            _notify_migration(hass, entry, other_name, saved=True)
            return other_name
        raise ConfigEntryNotReady(
            f"YAML Modbus hub '{other_name}' already uses this endpoint. Follow {MIGRATION_URL} before opening a new connection."
        )
    for other_name, hub in running.items():
        if getattr(hub, "endpoint", None) == endpoint:
            if interface == "core":
                _notify_migration(hass, entry, other_name, saved=True)
                return other_name
            raise ConfigEntryNotReady(f"YAML Modbus hub '{other_name}' is still running on this endpoint. Restart Home Assistant after removing it.")

    persistent_notification.async_dismiss(hass, _notification_id(entry))
    return None
