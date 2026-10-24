"""Automatic native TCP migration without changing the inverter or its entities."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components import persistent_notification
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError

from custom_components import solax_modbus as integration
from custom_components.solax_modbus import core_modbus as core
from custom_components.solax_modbus import modbus_transport as transport
from custom_components.solax_modbus.const import (
    CONF_INTERFACE,
    CONF_MODBUS_ADDR,
    CONF_TCP_TYPE,
    DEFAULT_PORT,
    DEFAULT_TIME_OUT,
    DOMAIN,
    REGISTER_U16,
)


@pytest.fixture
def tcp_migration(monkeypatch: pytest.MonkeyPatch) -> Any:
    entry = SimpleNamespace(
        entry_id="inverter-entry",
        title="SolaX",
        data={},
        options={
            CONF_INTERFACE: "tcp",
            "name": "SolaX",
            "plugin": "solax",
            "host": "192.0.2.1",
            "port": 1502,
            "time_out": 11,
            CONF_MODBUS_ADDR: 2,
            "scan_interval": 15,
            "read_battery": True,
        },
    )

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
    monkeypatch.setattr(persistent_notification, "async_create", state.notify)
    monkeypatch.setattr(persistent_notification, "async_dismiss", state.dismiss)
    return state


@pytest.mark.parametrize(("version", "supported"), [((2025, 1), False), ((2026, 9), False), ((2026, 10), True), ((2027, 1), True)])
def test_managed_tcp_requires_ha_2026_10_even_with_newer_libraries(
    monkeypatch: pytest.MonkeyPatch, version: tuple[int, int], supported: bool
) -> None:
    from homeassistant.components import modbus
    from modbus_connection import ModbusUnit

    monkeypatch.setattr(core, "MAJOR_VERSION", version[0])
    monkeypatch.setattr(core, "MINOR_VERSION", version[1])
    monkeypatch.setattr(modbus, "async_get_unit", Mock(), raising=False)
    monkeypatch.setattr(ModbusUnit, "require_timeout", Mock(), raising=False)
    monkeypatch.setattr(ModbusUnit, "require_connect_delay", Mock(), raising=False)
    assert core.supports_core_units() is supported


@pytest.mark.asyncio
@pytest.mark.parametrize(("framing", "transport_type"), [("tcp", "tcp"), ("rtu", "rtuovertcp"), ("ascii", "ascii")])
@pytest.mark.parametrize("legacy_flag", [False, True])
async def test_tcp_migrates_in_place_preserving_all_three_framings(
    tcp_migration: Any, monkeypatch: pytest.MonkeyPatch, framing: str, transport_type: str, legacy_flag: bool
) -> None:
    state = tcp_migration
    state.entry.options[CONF_TCP_TYPE] = framing
    if legacy_flag:
        state.entry.options.pop(CONF_INTERFACE)
        state.entry.options["read_serial"] = False
    original = state.entry.options.copy()
    managed = Mock()
    native = Mock()
    monkeypatch.setattr(integration, "CoreModbusUnitTransport", managed)
    monkeypatch.setattr(integration, "AsyncModbusTcpClient", native)
    plugin = SimpleNamespace(plugin_instance=SimpleNamespace(create_hub_instance=Mock()))

    selected = await core.async_prepare_core_connection(state.hass, state.entry)
    hub = integration.SolaXModbusHub(state.hass, cast(Any, plugin), state.entry, yaml_hub_name=selected)

    assert state.entry.entry_id == "inverter-entry"
    assert state.entry.options == {**original, CONF_INTERFACE: "core_tcp"}
    managed.assert_called_once_with(
        state.hass,
        state.entry,
        {"type": transport_type, "host": "192.0.2.1", "port": 1502, "timeout": 11, "delay": 0, "message_wait_milliseconds": 0},
        2,
    )
    assert hub._transport is managed.return_value
    native.assert_not_called()
    state.notify.assert_not_called()
    state.hass.config_entries.async_update_entry.assert_called_once()

    assert await core.async_prepare_core_connection(state.hass, state.entry) is None
    state.hass.config_entries.async_update_entry.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("framing", [None, "tcp", "unknown"])
async def test_tcp_migration_preserves_native_defaults(tcp_migration: Any, framing: str | None) -> None:
    state = tcp_migration
    state.entry.options = {"host": "192.0.2.1"}
    if framing is not None:
        state.entry.options[CONF_TCP_TYPE] = framing
    await core.async_prepare_core_connection(state.hass, state.entry)
    settings = core.configured_core_connection(state.entry.options)
    assert settings is not None
    assert settings["type"] == "tcp"
    assert settings["port"] == DEFAULT_PORT
    assert settings["timeout"] == DEFAULT_TIME_OUT


@pytest.mark.asyncio
@pytest.mark.parametrize("still_running", [False, True])
async def test_tcp_migration_does_not_commit_when_yaml_occupies_endpoint(tcp_migration: Any, still_running: bool) -> None:
    state = tcp_migration
    original = state.entry.options.copy()
    if still_running:
        state.running["inverter_bus"] = SimpleNamespace(endpoint=("tcp", "192.0.2.1", 1502))
    else:
        state.loader.return_value = {"modbus": [{"name": "inverter_bus", "type": "tcp", "host": "192.0.2.1", "port": 1502}]}
    with pytest.raises(ConfigEntryNotReady, match="inverter_bus"):
        await core.async_prepare_core_connection(state.hass, state.entry)
    assert state.entry.options == original
    state.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_tcp_migration_does_not_commit_when_yaml_is_invalid(tcp_migration: Any) -> None:
    state = tcp_migration
    original = state.entry.options.copy()
    state.loader.side_effect = HomeAssistantError("invalid YAML")
    with pytest.raises(ConfigEntryNotReady, match="Cannot check YAML"):
        await core.async_prepare_core_connection(state.hass, state.entry)
    assert state.entry.options == original
    state.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_tcp_reload_stops_native_client_before_migration(tcp_migration: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tcp_migration
    state.entry.async_on_unload = Mock()
    state.entry.add_update_listener = Mock()
    old = SimpleNamespace(async_stop=AsyncMock(), _platforms_forwarded=False)
    state.hass.data[DOMAIN] = {"SolaX": {"hub": old}}
    state.hass.async_add_executor_job = AsyncMock(return_value=object())
    new = SimpleNamespace(_name="SolaX", name="SolaX", async_init=AsyncMock())

    def create_hub(*args: Any, **kwargs: Any) -> Any:
        old.async_stop.assert_awaited_once()
        state.hass.config_entries.async_update_entry.assert_called_once()
        assert state.entry.options[CONF_INTERFACE] == "core_tcp"
        return new

    factory = Mock(side_effect=create_hub)
    monkeypatch.setattr(integration, "SolaXModbusHub", factory)
    monkeypatch.setattr(integration, "async_cleanup_disabled_devices", AsyncMock())
    assert await integration.async_setup_entry(state.hass, state.entry) is True
    factory.assert_called_once()
    new.async_init.assert_awaited_once()
    assert state.hass.data[DOMAIN]["SolaX"]["hub"] is new


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("framing", "factory_name"), [("tcp", "create_async_tcp_client"), ("rtu", "create_async_rtu_client"), ("ascii", "create_async_ascii_client")]
)
async def test_migrated_tcp_real_ha_pool_reads_writes_and_reconnects(
    tcp_migration: Any, monkeypatch: pytest.MonkeyPatch, framing: str, factory_name: str
) -> None:
    """Exercise the real pool and backend, replacing only the hardware client."""
    if (MAJOR_VERSION, MINOR_VERSION) < (2026, 10):
        pytest.skip("Home Assistant's complete Modbus unit API is not available")
    from modbus_connection import tmodbus as backend
    from tmodbus.exceptions import ModbusConnectionError

    state = tcp_migration
    state.entry.options[CONF_TCP_TYPE] = framing
    unit_client = SimpleNamespace(
        read_input_registers=AsyncMock(return_value=[12]),
        read_holding_registers=AsyncMock(return_value=[13]),
        write_single_register=AsyncMock(),
        write_multiple_registers=AsyncMock(),
    )
    client = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(), for_unit_id=Mock(return_value=unit_client))
    factory = Mock(return_value=client)
    monkeypatch.setattr(backend, factory_name, factory)
    releases: list[Any] = []
    state.entry.async_on_unload = Mock(side_effect=releases.append)
    plugin = SimpleNamespace(plugin_instance=SimpleNamespace(create_hub_instance=Mock()))

    await core.async_prepare_core_connection(state.hass, state.entry)
    hub = integration.SolaXModbusHub(state.hass, cast(Any, plugin), state.entry)
    assert isinstance(hub._transport, transport.CoreModbusUnitTransport)
    factory.assert_not_called()
    assert (await hub.async_read_input_registers(2, 150, 1)).registers == [12]
    assert (await hub.async_read_holding_registers(2, 10, 1)).registers == [13]
    await hub.async_lowlevel_write_register(2, 30, 7, register_data_type=REGISTER_U16)
    await hub._transport.write(2, 40, [8, 9], multiple=True)
    unit_client.write_single_register.assert_awaited_once_with(30, 7)
    unit_client.write_multiple_registers.assert_awaited_once_with(40, [8, 9])
    assert factory.call_args.kwargs["timeout"] == 11
    if framing == "tcp":
        assert factory.call_args.args == ("192.0.2.1", 1502)
    else:
        assert factory.call_args.args == ("socket://192.0.2.1:1502",)

    # A timeout is reported without us tearing down a shared, connected link.
    unit_client.read_input_registers.side_effect = TimeoutError("no response")
    assert await hub.async_read_input_registers(2, 150, 1) is None
    client.disconnect.assert_not_awaited()
    unit_client.read_input_registers.side_effect = None
    assert (await hub.async_read_input_registers(2, 150, 1)).registers == [12]
    factory.assert_called_once()

    # Simulate a transport-reported loss; HA opens a new client on the next I/O.
    def lose_link(*args: Any) -> None:
        factory.call_args.kwargs["on_connection_lost"](ConnectionResetError("lost link"))
        raise ModbusConnectionError("lost link")

    unit_client.read_input_registers.side_effect = lose_link
    assert await hub.async_read_input_registers(2, 150, 1) is None
    unit_client.read_input_registers.side_effect = None
    assert (await hub.async_read_input_registers(2, 150, 1)).registers == [12]
    assert factory.call_count == 2

    await hub._transport.close()
    await releases[0]()
    client.disconnect.assert_awaited()
