"""Tests for duplicate inverter warnings during polling."""

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, call

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL

import custom_components.solax_modbus as solax_modbus
from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.const import CONF_INTERFACE, CONF_MODBUS_ADDR, DOMAIN, PollOutcome
from custom_components.solax_modbus.sensor import SolaXModbusSensor


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


def _hub(entries: list[Any], current: Any, config: dict[str, Any]) -> SolaXModbusHub:
    hub = object.__new__(SolaXModbusHub)
    object.__setattr__(hub, "_hass", SimpleNamespace(config_entries=_ConfigEntries(entries)))
    hub.config = config
    hub.entry = current
    return hub


def test_warning_is_logged_on_every_slow_poll(caplog: Any) -> None:
    """Keep warning while two active configurations poll the same inverter."""
    config = {
        CONF_INTERFACE: "tcp",
        CONF_HOST: "192.0.2.10",
        CONF_PORT: 502,
        CONF_MODBUS_ADDR: 1,
        CONF_SCAN_INTERVAL: 15,
    }
    first = _entry("01", "Primary inverter", config)
    second = _entry("02", "Test inverter", config)
    hub = _hub([first, second], first, config)

    with caplog.at_level(logging.WARNING, logger="custom_components.solax_modbus"):
        hub._warn_duplicate_inverter_configuration(15)
        hub._warn_duplicate_inverter_configuration(15)

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert all('"Primary inverter" and "Test inverter"' in message for message in messages)
    assert all("TCP 192.0.2.10:502, Modbus address 1" in message for message in messages)


def test_only_one_duplicate_configuration_logs(caplog: Any) -> None:
    """Avoid duplicate warnings from both active inverter configurations."""
    config = {
        CONF_INTERFACE: "tcp",
        CONF_HOST: "192.0.2.10",
        CONF_PORT: 502,
        CONF_MODBUS_ADDR: 1,
        CONF_SCAN_INTERVAL: 15,
    }
    first = _entry("01", "Primary inverter", config)
    second = _entry("02", "Test inverter", config)
    hub = _hub([first, second], second, config)

    with caplog.at_level(logging.WARNING, logger="custom_components.solax_modbus"):
        hub._warn_duplicate_inverter_configuration(15)

    assert caplog.records == []


def test_fast_poll_and_inactive_duplicate_do_not_log(caplog: Any) -> None:
    """Only warn on slow polls when both inverter configurations are active."""
    config = {
        CONF_INTERFACE: "tcp",
        CONF_HOST: "192.0.2.10",
        CONF_PORT: 502,
        CONF_MODBUS_ADDR: 1,
        CONF_SCAN_INTERVAL: 15,
    }
    first = _entry("01", "Primary inverter", config)
    inactive = _entry("02", "Inactive inverter", config, active=False)
    hub = _hub([first, inactive], first, config)

    with caplog.at_level(logging.WARNING, logger="custom_components.solax_modbus"):
        hub._warn_duplicate_inverter_configuration(5)
        hub._warn_duplicate_inverter_configuration(15)

    assert caplog.records == []


@pytest.mark.asyncio
async def test_scheduled_poll_checks_warning_on_every_cycle(monkeypatch: Any) -> None:
    """Call duplicate detection for each invocation of the slow poll callback."""
    scheduled: dict[str, Any] = {}

    def _track_interval(_hass: Any, callback: Any, _interval: Any) -> Any:
        scheduled["callback"] = callback
        return Mock()

    monkeypatch.setattr(solax_modbus, "async_track_time_interval", _track_interval)

    hub = object.__new__(SolaXModbusHub)
    object.__setattr__(hub, "_hass", SimpleNamespace())
    hub._name = "SolaX"
    hub.groups = {}
    hub.cyclecount = 0
    hub.slowdown = 1
    hub.blocks_changed = False
    monkeypatch.setattr(hub, "scan_group", Mock(return_value=15))
    monkeypatch.setattr(hub, "device_group_key", Mock(return_value="inverter"))
    warn_duplicate = Mock()
    monkeypatch.setattr(hub, "_warn_duplicate_inverter_configuration", warn_duplicate)
    monkeypatch.setattr(hub, "_record_poll_cycle", Mock())

    async def _refresh_data(_interval_group: Any, _now: Any, *, cycle_id: int) -> tuple[PollOutcome, int]:
        assert cycle_id > 0
        return PollOutcome.SUCCESS, 0

    monkeypatch.setattr(hub, "async_refresh_modbus_data", _refresh_data)
    sensor = cast(
        SolaXModbusSensor,
        SimpleNamespace(
            entity_description=SimpleNamespace(key="test_sensor"),
            device_info={},
            _attr_available=True,
        ),
    )

    await hub.async_add_solax_modbus_sensor(sensor)
    await scheduled["callback"]()
    await scheduled["callback"]()

    assert warn_duplicate.call_args_list == [call(15), call(15)]
