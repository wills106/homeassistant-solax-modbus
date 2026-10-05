"""Regression coverage for the staged Core Modbus migration."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components import persistent_notification
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus import core_modbus as core
from custom_components.solax_modbus import modbus_transport as transport
from custom_components.solax_modbus.const import CONF_CORE_CONNECTION, CONF_CORE_HUB, CONF_INTERFACE, REGISTER_U16


@pytest.fixture
def migration(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Use realistic options while keeping YAML loading and HA UI isolated."""
    entry = SimpleNamespace(entry_id="entry", title="SolaX", options={CONF_INTERFACE: "core", CONF_CORE_HUB: "inverter_bus", "name": "SolaX"})

    def update_entry(target: Any, *, options: dict[str, Any]) -> None:
        target.options = options

    state = SimpleNamespace(
        entry=entry,
        hass=SimpleNamespace(data={}, config_entries=SimpleNamespace(async_update_entry=Mock(side_effect=update_entry))),
        loader=AsyncMock(return_value={"modbus": []}),
        running={},
        notify=Mock(),
        dismiss=Mock(),
    )
    monkeypatch.setattr(core, "supports_core_units", lambda: True)
    monkeypatch.setattr(core, "async_integration_yaml_config", state.loader)
    monkeypatch.setattr(core, "_running_yaml_hubs", lambda hass: state.running)
    monkeypatch.setattr(core, "core_connection_params", lambda settings: SimpleNamespace(endpoint=core._physical_endpoint(settings)))
    monkeypatch.setattr(persistent_notification, "async_create", state.notify)
    monkeypatch.setattr(persistent_notification, "async_dismiss", state.dismiss)
    return state


def yaml_hub(**extra: Any) -> dict[str, Any]:
    return {"name": "inverter_bus", "type": "tcp", "host": "192.0.2.1", "port": 502, "timeout": 12, "delay": 1, **extra}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hub",
    [
        yaml_hub(sensors=[{"name": "Existing YAML sensor"}]),
        yaml_hub(type="rtuovertcp", message_wait_milliseconds=75),
        yaml_hub(type="serial", port="/dev/serial/by-id/inverter", baudrate=19200, parity="E", bytesize=7, stopbits=2, method="ascii"),
    ],
)
async def test_existing_yaml_hub_is_saved_but_keeps_its_connection(migration: Any, hub: dict[str, Any]) -> None:
    migration.loader.return_value = {"modbus": [hub]}
    original = hub.copy()

    assert await core.async_prepare_core_connection(migration.hass, migration.entry) == "inverter_bus"

    assert migration.entry.options[CONF_CORE_CONNECTION] == core.connection_settings(hub)
    assert migration.entry.options[CONF_INTERFACE] == "core"
    assert migration.entry.options[CONF_CORE_HUB] == "inverter_bus"
    assert hub == original
    assert "sensors" not in migration.entry.options[CONF_CORE_CONNECTION]
    migration.notify.assert_called_once()
    message = migration.notify.call_args.args[1]
    assert "settings have been saved automatically" in message
    assert "inverter_bus" in message and core.MIGRATION_URL in message
    assert "2027.10" in message


@pytest.mark.asyncio
async def test_notification_is_reused_and_settings_refresh_on_every_start(migration: Any) -> None:
    hub = yaml_hub()
    migration.loader.return_value = {"modbus": [hub]}
    await core.async_prepare_core_connection(migration.hass, migration.entry)
    first_id = migration.notify.call_args.kwargs["notification_id"]
    hub["port"] = 1502
    await core.async_prepare_core_connection(migration.hass, migration.entry)

    assert migration.notify.call_args.kwargs["notification_id"] == first_id
    assert migration.entry.options[CONF_CORE_CONNECTION]["port"] == 1502


@pytest.mark.asyncio
async def test_yaml_removal_after_restart_selects_saved_settings(migration: Any) -> None:
    migration.entry.options[CONF_CORE_CONNECTION] = core.connection_settings(yaml_hub())

    assert await core.async_prepare_core_connection(migration.hass, migration.entry) is None
    migration.dismiss.assert_called_once()
    migration.notify.assert_not_called()
    assert migration.entry.options[CONF_INTERFACE] == "core"


@pytest.mark.asyncio
async def test_file_removal_without_restart_keeps_the_running_hub(migration: Any) -> None:
    migration.entry.options[CONF_CORE_CONNECTION] = core.connection_settings(yaml_hub())
    migration.running["inverter_bus"] = object()

    assert await core.async_prepare_core_connection(migration.hass, migration.entry) == "inverter_bus"
    migration.notify.assert_called_once()
    migration.dismiss.assert_not_called()


@pytest.mark.asyncio
async def test_another_yaml_hub_on_same_endpoint_prevents_second_connection(migration: Any) -> None:
    migration.entry.options[CONF_CORE_CONNECTION] = core.connection_settings(yaml_hub())
    migration.loader.return_value = {"modbus": [yaml_hub(name="other_user")]}

    assert await core.async_prepare_core_connection(migration.hass, migration.entry) == "other_user"
    assert "other_user" in migration.notify.call_args.args[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("yaml_running", [False, True])
async def test_new_core_connection_rejects_competing_yaml_client(migration: Any, yaml_running: bool) -> None:
    migration.entry.options = {CONF_INTERFACE: "core_tcp", "host": "192.0.2.1", "port": 502, "tcp_type": "rtu"}
    if yaml_running:
        migration.running["inverter_bus"] = SimpleNamespace(endpoint=("tcp", "192.0.2.1", 502))
    else:
        migration.loader.return_value = {"modbus": [yaml_hub()]}

    with pytest.raises(ConfigEntryNotReady, match="inverter_bus"):
        await core.async_prepare_core_connection(migration.hass, migration.entry)


@pytest.mark.asyncio
async def test_missing_saved_settings_cannot_silently_start_a_default_connection(migration: Any) -> None:
    with pytest.raises(ConfigEntryNotReady, match="Restore the YAML hub"):
        await core.async_prepare_core_connection(migration.hass, migration.entry)


@pytest.mark.asyncio
async def test_yaml_read_failure_does_not_mean_hub_was_removed(migration: Any) -> None:
    migration.entry.options[CONF_CORE_CONNECTION] = core.connection_settings(yaml_hub())
    migration.loader.side_effect = HomeAssistantError("invalid YAML")

    with pytest.raises(ConfigEntryNotReady, match="Cannot check YAML"):
        await core.async_prepare_core_connection(migration.hass, migration.entry)
    migration.dismiss.assert_not_called()


@pytest.mark.asyncio
async def test_unsupported_settings_keep_existing_hub_and_do_not_claim_success(migration: Any) -> None:
    migration.loader.return_value = {"modbus": [yaml_hub(type="unknown")]}

    assert await core.async_prepare_core_connection(migration.hass, migration.entry) == "inverter_bus"
    assert "could not be saved" in migration.notify.call_args.args[1]
    assert CONF_CORE_CONNECTION not in migration.entry.options


@pytest.mark.asyncio
async def test_older_ha_keeps_legacy_connection(migration: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "supports_core_units", lambda: False)

    assert await core.async_prepare_core_connection(migration.hass, migration.entry) == "inverter_bus"
    migration.loader.assert_not_called()
    migration.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_native_connection_does_not_read_or_change_yaml(migration: Any) -> None:
    migration.entry.options = {CONF_INTERFACE: "tcp", "host": "192.0.2.1"}

    assert await core.async_prepare_core_connection(migration.hass, migration.entry) is None
    migration.loader.assert_not_called()
    migration.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"type": "tcp", "host": "192.0.2.1", "port": 502}, ("tcp", "192.0.2.1", 502)),
        ({"type": "udp", "host": "192.0.2.1", "port": 502}, ("udp", "192.0.2.1", 502)),
        ({"type": "rtuovertcp", "host": "2001:db8::1", "port": 502}, ("serial", "socket://[2001:db8::1]:502")),
        ({"type": "serial", "port": "esphome-hass://entry/RS485", "baudrate": 19200}, ("serial", "esphome-hass://entry/RS485")),
    ],
)
def test_real_library_connection_parameters(config: dict[str, Any], expected: tuple[Any, ...]) -> None:
    pytest.importorskip("modbus_connection")
    assert core.core_connection_params(core.connection_settings(config)).endpoint == expected


@pytest.fixture
def unit_transport(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Use the unit protocol, without a socket or an HA Core connection."""
    # The API adapter does not depend on a particular library installation in CI.
    import sys
    from types import ModuleType

    class ModbusError(Exception):
        pass

    exceptions = ModuleType("modbus_connection.exceptions")
    exceptions.ModbusError = ModbusError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "modbus_connection.exceptions", exceptions)
    monkeypatch.setattr(transport, "core_connection_params", lambda settings: SimpleNamespace(endpoint=("tcp", "192.0.2.1", 502)))
    unit = SimpleNamespace(
        connected=False,
        require_timeout=Mock(),
        require_connect_delay=Mock(),
        set_message_spacing=Mock(),
        read_holding_registers=AsyncMock(return_value=[7, 8]),
        read_input_registers=AsyncMock(return_value=[9]),
        write_register=AsyncMock(),
        write_registers=AsyncMock(),
        disconnect=AsyncMock(),
    )
    getter = Mock(return_value=unit)
    result = transport.CoreModbusUnitTransport(
        cast(Any, object()), cast(Any, object()), core.connection_settings(yaml_hub(message_wait_milliseconds=50)), 1, unit_getter=getter
    )
    return SimpleNamespace(transport=result, unit=unit, getter=getter, error=ModbusError)


@pytest.mark.asyncio
async def test_unit_adapter_connects_on_first_request_and_preserves_settings(unit_transport: Any) -> None:
    state = unit_transport
    assert state.transport.is_connected() is False
    assert await state.transport.connect() is True
    assert state.transport.is_connected() is False
    response = await state.transport.read("holding", 1, 10, 2)
    assert response.registers == [7, 8] and response.isError() is False
    state.unit.require_timeout.assert_called_once_with(12)
    state.unit.require_connect_delay.assert_called_once_with(1)
    state.unit.set_message_spacing.assert_called_once_with(0.05)
    state.unit.read_holding_registers.assert_awaited_once_with(10, 2)
    state.getter.assert_called_once()


@pytest.mark.asyncio
async def test_unit_adapter_preserves_fc03_fc04_fc06_and_fc16(unit_transport: Any) -> None:
    state = unit_transport
    await state.transport.read("input", 1, 20, 1)
    single = await state.transport.write(1, 30, [7], multiple=False)
    multiple = await state.transport.write(1, 40, [8, 9], multiple=True)
    assert single.isError() is False and multiple.isError() is False
    state.unit.read_input_registers.assert_awaited_once_with(20, 1)
    state.unit.write_register.assert_awaited_once_with(30, 7)
    state.unit.write_registers.assert_awaited_once_with(40, [8, 9])


@pytest.mark.asyncio
async def test_unit_adapter_never_disconnects_shared_link_or_reacquires_on_reconnect(unit_transport: Any) -> None:
    state = unit_transport
    state.unit.connected = True
    assert state.transport.is_connected() is True
    await state.transport.close()
    assert state.transport.is_connected() is False
    assert await state.transport.read("holding", 1, 10, 1) is None
    await state.transport.connect()
    assert state.transport.is_connected() is True
    state.unit.disconnect.assert_not_awaited()
    state.getter.assert_called_once()


@pytest.mark.asyncio
async def test_hub_allows_lazy_first_read_and_handles_rejected_writes(unit_transport: Any) -> None:
    import asyncio

    state = unit_transport
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._transport = state.transport
    hub._name = "SolaX"
    hub._stopping = False
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub.plugin = SimpleNamespace(order32="big")

    assert (await hub.async_read_holding_registers(1, 10, 2)).registers == [7, 8]
    state.unit.write_register.side_effect = state.error("illegal address")
    with pytest.raises(HomeAssistantError, match="illegal address"):
        await hub.async_lowlevel_write_register(1, 30, 7, register_data_type=REGISTER_U16)
    state.unit.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_unit_adapter_timeout_reaches_hub_without_closing_connected_bus(unit_transport: Any) -> None:
    import asyncio

    state = unit_transport
    state.unit.connected = True
    state.unit.read_holding_registers.side_effect = state.error("timeout")
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._transport = state.transport
    hub._name = "SolaX"
    hub._stopping = False
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()

    assert await hub.async_read_holding_registers(1, 10, 1) is None
    assert state.transport.is_connected() is True
    state.unit.disconnect.assert_not_awaited()
