"""Tests for duplicate inverter connection identification."""

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT

from custom_components.solax_modbus.connection import (
    matching_config_entries,
    modbus_connection_identity,
)
from custom_components.solax_modbus.const import (
    CONF_BAUDRATE,
    CONF_CORE_HUB,
    CONF_INTERFACE,
    CONF_MODBUS_ADDR,
    CONF_SERIAL_PORT,
    CONF_TCP_TYPE,
    DOMAIN,
)


class _ConfigEntries:
    def __init__(self, entries: list[Any]) -> None:
        self._entries = entries

    def async_entries(self, domain: str) -> list[Any]:
        assert domain == DOMAIN
        return self._entries


def _entry(entry_id: str, name: str, config: dict[str, Any], *, active: bool = True) -> Any:
    return SimpleNamespace(
        entry_id=entry_id,
        title=name,
        data={},
        options={CONF_NAME: name, **config},
        disabled_by=None if active else "user",
        state=ConfigEntryState.LOADED,
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            {CONF_INTERFACE: "tcp", CONF_HOST: "INVERTER.local.", CONF_PORT: 502, CONF_MODBUS_ADDR: 1, CONF_TCP_TYPE: "tcp"},
            {CONF_INTERFACE: "tcp", CONF_HOST: "inverter.local", CONF_PORT: 502, CONF_MODBUS_ADDR: 1, CONF_TCP_TYPE: "rtu"},
        ),
        (
            {CONF_INTERFACE: "serial", CONF_SERIAL_PORT: "/dev/ttyUSB0", CONF_MODBUS_ADDR: 2, CONF_BAUDRATE: "9600"},
            {CONF_INTERFACE: "serial", CONF_SERIAL_PORT: "/dev/ttyUSB0", CONF_MODBUS_ADDR: 2, CONF_BAUDRATE: "19200"},
        ),
        (
            {CONF_INTERFACE: "core", CONF_CORE_HUB: "inverter_bus", CONF_MODBUS_ADDR: 3},
            {CONF_INTERFACE: "core", CONF_CORE_HUB: "inverter_bus", CONF_MODBUS_ADDR: 3},
        ),
    ],
)
def test_connection_identity_matches_same_modbus_device(first: dict[str, Any], second: dict[str, Any]) -> None:
    """Treat connection settings that target the same device as duplicates."""
    assert modbus_connection_identity(first) == modbus_connection_identity(second)


@pytest.mark.parametrize(
    "config",
    [
        {CONF_INTERFACE: "tcp", CONF_HOST: "192.0.2.10", CONF_PORT: 502, CONF_MODBUS_ADDR: 1},
        {CONF_INTERFACE: "serial", CONF_SERIAL_PORT: "/dev/ttyUSB0", CONF_MODBUS_ADDR: 1},
        {CONF_INTERFACE: "core", CONF_CORE_HUB: "inverter_bus", CONF_MODBUS_ADDR: 1},
    ],
)
def test_connection_identity_distinguishes_modbus_addresses(config: dict[str, Any]) -> None:
    """Allow multiple inverters behind one TCP, serial, or Core Modbus connection."""
    other = {**config, CONF_MODBUS_ADDR: 2}

    assert modbus_connection_identity(config) != modbus_connection_identity(other)


def test_legacy_none_modbus_address_uses_default() -> None:
    """Match legacy entries that the runtime treats as Modbus address 1."""
    legacy = {CONF_INTERFACE: "tcp", CONF_HOST: "192.0.2.10", CONF_PORT: 502, CONF_MODBUS_ADDR: None}
    current = {CONF_INTERFACE: "tcp", CONF_HOST: "192.0.2.10", CONF_PORT: 502, CONF_MODBUS_ADDR: 1}

    assert modbus_connection_identity(legacy) == modbus_connection_identity(current)


def test_matching_entries_can_include_disabled_entries_for_setup_warning() -> None:
    """Warn in setup even when the existing duplicate is currently disabled."""
    config = {CONF_INTERFACE: "tcp", CONF_HOST: "192.0.2.10", CONF_PORT: 502, CONF_MODBUS_ADDR: 1}
    disabled = _entry("existing", "Existing inverter", config, active=False)
    hass = SimpleNamespace(config_entries=_ConfigEntries([disabled]))

    assert matching_config_entries(hass, config) == [disabled]
    assert matching_config_entries(hass, config, active_only=True) == []


def test_matching_entries_excludes_entry_being_edited() -> None:
    """Do not treat an options flow entry as its own duplicate."""
    config = {CONF_INTERFACE: "serial", CONF_SERIAL_PORT: "/dev/ttyUSB0", CONF_MODBUS_ADDR: 1}
    current = _entry("current", "Current inverter", config)
    duplicate = _entry("duplicate", "Duplicate inverter", config)
    hass = SimpleNamespace(config_entries=_ConfigEntries([current, duplicate]))

    assert matching_config_entries(hass, config, exclude_entry_id="current") == [duplicate]
