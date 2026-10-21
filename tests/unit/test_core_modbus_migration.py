"""Regression coverage for the staged Core Modbus migration."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components import persistent_notification
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError

from custom_components import solax_modbus as integration
from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus import core_modbus as core
from custom_components.solax_modbus import modbus_transport as transport
from custom_components.solax_modbus.const import CONF_CORE_CONNECTION, CONF_CORE_HUB, CONF_INTERFACE, CONF_MODBUS_ADDR, DOMAIN, REGISTER_U16
from custom_components.solax_modbus.core_modbus import core_connection_params


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


@pytest.mark.parametrize(("version", "expected"), [((2025, 1), False), ((2026, 9), False), ((2026, 10), True), ((2027, 1), True)])
def test_shared_api_requires_ha_2026_10_even_if_newer_library_is_installed(
    monkeypatch: pytest.MonkeyPatch, version: tuple[int, int], expected: bool
) -> None:
    from homeassistant.components import modbus
    from modbus_connection import ModbusUnit

    monkeypatch.setattr(core, "MAJOR_VERSION", version[0])
    monkeypatch.setattr(core, "MINOR_VERSION", version[1])
    monkeypatch.setattr(modbus, "async_get_unit", Mock(), raising=False)
    monkeypatch.setattr(ModbusUnit, "require_timeout", Mock(), raising=False)
    monkeypatch.setattr(ModbusUnit, "require_connect_delay", Mock(), raising=False)
    assert core.supports_core_units() is expected


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
    assert "deprecation warning is expected" in message
    assert "No second connection is opened" in message


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


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["configured", "still_running", "restarted"])
async def test_migration_selects_transport_without_opening_a_second_link(migration: Any, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    """Exercise preparation AND the real hub constructor, not just its return value."""
    legacy = Mock()
    managed = Mock()
    monkeypatch.setattr(integration, "CoreModbusTransport", legacy)
    monkeypatch.setattr(integration, "CoreModbusUnitTransport", managed)
    plugin = SimpleNamespace(plugin_instance=SimpleNamespace(create_hub_instance=Mock()))
    migration.entry.options[CONF_CORE_CONNECTION] = core.connection_settings(yaml_hub())
    if stage == "configured":
        migration.loader.return_value = {"modbus": [yaml_hub()]}
    elif stage == "still_running":
        migration.running["inverter_bus"] = object()

    selected = await core.async_prepare_core_connection(migration.hass, migration.entry)
    hub = SolaXModbusHub(migration.hass, cast(Any, plugin), migration.entry, yaml_hub_name=selected)

    if stage == "restarted":
        legacy.assert_not_called()
        managed.assert_called_once()
        assert hub._transport is managed.return_value
    else:
        managed.assert_not_called()
        legacy.assert_called_once_with(migration.hass, "inverter_bus", "SolaX")
        assert hub._transport is legacy.return_value


@pytest.mark.asyncio
@pytest.mark.parametrize(("interface", "supported"), [("tcp", True), ("tcp", False), ("serial", False)])
async def test_native_connections_remain_on_tcp_or_older_ha(migration: Any, monkeypatch: pytest.MonkeyPatch, interface: str, supported: bool) -> None:
    """TCP is out of scope; older HA must keep its native serial transport."""
    monkeypatch.setattr(core, "supports_core_units", lambda: supported)
    migration.entry.options = {CONF_INTERFACE: interface, "host": "192.0.2.1", "name": "SolaX"}
    managed = Mock()
    legacy = Mock()
    monkeypatch.setattr(integration, "CoreModbusUnitTransport", managed)
    monkeypatch.setattr(integration, "CoreModbusTransport", legacy)
    monkeypatch.setattr(integration, "AsyncModbusTcpClient", Mock())
    monkeypatch.setattr(integration, "AsyncSerialModbusClient", Mock())
    plugin = SimpleNamespace(plugin_instance=SimpleNamespace(create_hub_instance=Mock()))

    selected = await core.async_prepare_core_connection(migration.hass, migration.entry)
    hub = SolaXModbusHub(migration.hass, cast(Any, plugin), migration.entry, yaml_hub_name=selected)

    assert isinstance(hub._transport, transport.NativeModbusTransport)
    managed.assert_not_called()
    legacy.assert_not_called()
    migration.loader.assert_not_called()
    manifest = json.loads((Path(integration.__file__).parent / "manifest.json").read_text())
    assert "modbus" in manifest["dependencies"]


@pytest.mark.asyncio
@pytest.mark.parametrize("port", ["/dev/serial/by-id/inverter", "esphome-hass://entry/Inverter%20RS485", "socket://192.0.2.1:502"])
@pytest.mark.parametrize("legacy_flag", [False, True])
async def test_serial_migrates_in_place_and_uses_only_managed_transport(
    migration: Any, monkeypatch: pytest.MonkeyPatch, port: str, legacy_flag: bool
) -> None:
    """Move native serial settings, including old read_serial entries, without recreating anything."""
    original: dict[str, Any] = {
        "name": "SolaX",
        "read_serial_port": port,
        "baudrate": "19200",
        CONF_MODBUS_ADDR: 2,
        "time_out": 12,
        "scan_interval": 15,
        "plugin": "solax",
        "read_battery": True,
        # Native serial always used 8N1/RTU, even with stale shared options.
        "parity": "E",
        "bytesize": 7,
        "stopbits": 2,
        "method": "ascii",
    }
    if legacy_flag:
        original["read_serial"] = True
    else:
        original[CONF_INTERFACE] = "serial"
    migration.entry.options = original.copy()
    identity = id(migration.entry)
    managed = Mock()
    native = Mock()
    monkeypatch.setattr(integration, "CoreModbusUnitTransport", managed)
    monkeypatch.setattr(integration, "AsyncSerialModbusClient", native)
    plugin = SimpleNamespace(plugin_instance=SimpleNamespace(create_hub_instance=Mock()))

    selected = await core.async_prepare_core_connection(migration.hass, migration.entry)
    hub = SolaXModbusHub(migration.hass, cast(Any, plugin), migration.entry, yaml_hub_name=selected)

    assert id(migration.entry) == identity
    assert migration.entry.entry_id == "entry"
    assert migration.entry.options[CONF_INTERFACE] == "core_serial"
    for key in ("name", "read_serial_port", "baudrate", CONF_MODBUS_ADDR, "time_out", "scan_interval", "plugin", "read_battery"):
        assert migration.entry.options[key] == original[key]
    settings = managed.call_args.args[2]
    assert settings == {
        "type": "serial",
        "port": port,
        "baudrate": 19200,
        "timeout": 12,
        "parity": "N",
        "bytesize": 8,
        "stopbits": 1,
        "method": "rtu",
        "delay": 0,
        "message_wait_milliseconds": 0,
    }
    assert managed.call_args.args[3] == 2
    assert hub._transport is managed.return_value
    native.assert_not_called()
    migration.notify.assert_not_called()
    migration.hass.config_entries.async_update_entry.assert_called_once()

    # Reloads/startups must not repeat the config update.
    assert await core.async_prepare_core_connection(migration.hass, migration.entry) is None
    migration.hass.config_entries.async_update_entry.assert_called_once()


@pytest.mark.asyncio
async def test_serial_migration_preserves_native_defaults(migration: Any) -> None:
    from custom_components.solax_modbus.const import DEFAULT_BAUDRATE, DEFAULT_SERIAL_PORT, DEFAULT_TIME_OUT

    migration.entry.options = {CONF_INTERFACE: "serial", "name": "SolaX"}
    await core.async_prepare_core_connection(migration.hass, migration.entry)
    settings = core.configured_core_connection(migration.entry.options)
    assert settings is not None
    assert settings["port"] == DEFAULT_SERIAL_PORT
    assert settings["baudrate"] == int(DEFAULT_BAUDRATE)
    assert settings["timeout"] == DEFAULT_TIME_OUT


@pytest.mark.asyncio
@pytest.mark.parametrize("still_running", [False, True])
async def test_serial_migration_does_not_commit_or_open_a_link_on_yaml_conflict(migration: Any, still_running: bool) -> None:
    original = {CONF_INTERFACE: "serial", "read_serial_port": "/dev/ttyUSB0"}
    migration.entry.options = original.copy()
    if still_running:
        migration.running["inverter_bus"] = SimpleNamespace(endpoint=("serial", "/dev/ttyUSB0"))
    else:
        migration.loader.return_value = {"modbus": [yaml_hub(type="serial", port="/dev/ttyUSB0")]}

    with pytest.raises(ConfigEntryNotReady, match="inverter_bus"):
        await core.async_prepare_core_connection(migration.hass, migration.entry)

    assert migration.entry.options == original
    migration.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_serial_migration_does_not_commit_if_yaml_cannot_be_checked(migration: Any) -> None:
    original = {CONF_INTERFACE: "serial", "read_serial_port": "/dev/ttyUSB0"}
    migration.entry.options = original.copy()
    migration.loader.side_effect = HomeAssistantError("invalid YAML")
    with pytest.raises(ConfigEntryNotReady, match="Cannot check YAML"):
        await core.async_prepare_core_connection(migration.hass, migration.entry)
    assert migration.entry.options == original
    migration.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_serial_reload_closes_old_connection_before_migrating(migration: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the real entry setup order, including a previously running native hub."""
    migration.entry.options = {CONF_INTERFACE: "serial", "name": "SolaX", "plugin": "solax", "read_serial_port": "/dev/ttyUSB0"}
    migration.entry.data = {}
    migration.entry.async_on_unload = Mock()
    migration.entry.add_update_listener = Mock()
    old = SimpleNamespace(async_stop=AsyncMock(), _platforms_forwarded=False)
    migration.hass.data[DOMAIN] = {"SolaX": {"hub": old}}
    migration.hass.async_add_executor_job = AsyncMock(return_value=object())
    new = SimpleNamespace(_name="SolaX", name="SolaX", async_init=AsyncMock())

    def create_hub(*args: Any, **kwargs: Any) -> Any:
        old.async_stop.assert_awaited_once()
        migration.hass.config_entries.async_update_entry.assert_called_once()
        assert migration.entry.options[CONF_INTERFACE] == "core_serial"
        return new

    factory = Mock(side_effect=create_hub)
    monkeypatch.setattr(integration, "SolaXModbusHub", factory)
    monkeypatch.setattr(integration, "async_cleanup_disabled_devices", AsyncMock())
    assert await integration.async_setup_entry(migration.hass, migration.entry) is True
    factory.assert_called_once()
    new.async_init.assert_awaited_once()
    assert migration.hass.data[DOMAIN]["SolaX"]["hub"] is new


@pytest.mark.asyncio
@pytest.mark.parametrize("port", ["/dev/serial/by-id/inverter", "esphome-hass://entry/Inverter%20RS485"])
async def test_migrated_serial_uses_real_ha_pool_and_preserves_io_settings(migration: Any, monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    """Keep the real HA getter, unit backend and hub; replace only hardware I/O."""
    from homeassistant.const import MAJOR_VERSION, MINOR_VERSION

    if (MAJOR_VERSION, MINOR_VERSION) < (2026, 10):
        pytest.skip("Home Assistant's complete Modbus unit API is not available")
    from modbus_connection import tmodbus as backend
    from serialx import Parity, StopBits

    monkeypatch.setattr(core, "core_connection_params", core_connection_params)
    unit_client = SimpleNamespace(read_input_registers=AsyncMock(return_value=[12]), write_single_register=AsyncMock())
    client = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(), for_unit_id=Mock(return_value=unit_client))
    factory = Mock(return_value=client)
    monkeypatch.setattr(backend, "create_async_rtu_client", factory)
    migration.entry.options = {
        CONF_INTERFACE: "serial",
        "name": "SolaX",
        "read_serial_port": port,
        "baudrate": "9600",
        "time_out": 11,
        CONF_MODBUS_ADDR: 2,
    }
    releases: list[Any] = []
    migration.entry.async_on_unload = Mock(side_effect=releases.append)
    plugin = SimpleNamespace(plugin_instance=SimpleNamespace(create_hub_instance=Mock()))

    await core.async_prepare_core_connection(migration.hass, migration.entry)
    hub = SolaXModbusHub(migration.hass, cast(Any, plugin), migration.entry)
    assert isinstance(hub._transport, transport.CoreModbusUnitTransport)
    factory.assert_not_called()

    response = await hub.async_read_input_registers(2, 150, 1)
    assert response.registers == [12]
    await hub.async_lowlevel_write_register(2, 30, 7, register_data_type=REGISTER_U16)
    factory.assert_called_once()
    assert factory.call_args.args == (port,)
    for key, expected in {"baudrate": 9600, "timeout": 11, "bytesize": 8, "parity": Parity.NONE, "stopbits": StopBits.ONE}.items():
        assert factory.call_args.kwargs[key] == expected
    client.for_unit_id.assert_called_once_with(2)
    unit_client.read_input_registers.assert_awaited_once_with(150, 1)
    unit_client.write_single_register.assert_awaited_once_with(30, 7)

    await hub._transport.close()
    client.disconnect.assert_not_awaited()
    await releases[0]()
    client.disconnect.assert_awaited_once()


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (yaml_hub(host="Inverter.LOCAL."), yaml_hub(host="inverter.local")),
        (yaml_hub(host="2001:0DB8:0:0:0:0:0:1"), yaml_hub(host="2001:db8::1")),
        (yaml_hub(), yaml_hub(type="rtuovertcp")),
        (yaml_hub(type="ascii"), yaml_hub(type="serial", port="socket://192.0.2.1:502")),
        (yaml_hub(host="inverter.local"), yaml_hub(type="serial", port="socket://INVERTER.local.:502")),
        (yaml_hub(host="2001:db8::1"), yaml_hub(type="serial", port="socket://[2001:0DB8:0:0:0:0:0:1]:502")),
    ],
)
def test_equivalent_yaml_endpoints_share_conflict_key(first: dict[str, Any], second: dict[str, Any]) -> None:
    assert core._physical_endpoint(core.connection_settings(first)) == core._physical_endpoint(core.connection_settings(second))


@pytest.mark.asyncio
@pytest.mark.parametrize("still_running", [False, True])
@pytest.mark.parametrize(
    "other",
    [
        yaml_hub(host="INVERTER.local."),
        yaml_hub(type="serial", port="socket://INVERTER.local.:502"),
    ],
)
async def test_new_connection_rejects_normalized_yaml_conflicts(migration: Any, other: dict[str, Any], still_running: bool) -> None:
    migration.entry.options = {CONF_INTERFACE: "core_tcp", "host": "inverter.local", "port": 502}
    if still_running:
        # Use the endpoint shape published by HA, before our normalization.
        endpoint = ("serial", other["port"]) if other["type"] == "serial" else ("tcp", other["host"], other["port"])
        migration.running["inverter_bus"] = SimpleNamespace(endpoint=endpoint)
    else:
        migration.loader.return_value = {"modbus": [other]}

    with pytest.raises(ConfigEntryNotReady, match="inverter_bus"):
        await core.async_prepare_core_connection(migration.hass, migration.entry)


def test_endpoint_comparison_does_not_guess_dns_or_serial_aliases() -> None:
    assert core._physical_endpoint(core.connection_settings(yaml_hub(host="inverter.local"))) != core._physical_endpoint(
        core.connection_settings(yaml_hub())
    )
    assert core._physical_endpoint(core.connection_settings(yaml_hub(type="serial", port="/dev/ttyUSB0"))) != core._physical_endpoint(
        core.connection_settings(yaml_hub(type="serial", port="/dev/serial/by-id/inverter"))
    )
    assert core._physical_endpoint(core.connection_settings(yaml_hub(type="udp"))) != core._physical_endpoint(core.connection_settings(yaml_hub()))


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


@pytest.mark.asyncio
async def test_real_core_pool_opens_lazily_and_releases_only_the_last_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise HA's public getter and real unit backend without opening a socket."""
    if not core.supports_core_units():
        pytest.skip("Home Assistant's complete Modbus unit API is not available")
    from modbus_connection import tmodbus as backend

    unit_client = SimpleNamespace(read_holding_registers=AsyncMock(return_value=[7, 8]))
    client = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(), for_unit_id=Mock(return_value=unit_client))
    factory = Mock(return_value=client)
    monkeypatch.setattr(backend, "create_async_tcp_client", factory)
    hass = cast(Any, SimpleNamespace(data={}))
    first_releases: list[Any] = []
    second_releases: list[Any] = []
    first_entry = cast(Any, SimpleNamespace(entry_id="first", async_on_unload=Mock(side_effect=first_releases.append)))
    second_entry = cast(Any, SimpleNamespace(entry_id="second", async_on_unload=Mock(side_effect=second_releases.append)))
    settings = core.connection_settings(yaml_hub(delay=0, message_wait_milliseconds=0))
    first = transport.CoreModbusUnitTransport(hass, first_entry, settings, 1)
    second = transport.CoreModbusUnitTransport(hass, second_entry, settings, 2)

    assert await first.connect() is True
    assert first.is_connected() is False
    factory.assert_not_called()
    first_response = await first.read("holding", 1, 10, 2)
    assert first_response is not None and first_response.registers == [7, 8]
    factory.assert_called_once()
    assert factory.call_args.kwargs["timeout"] == 12
    client.connect.assert_awaited_once()
    assert second.is_connected() is True

    # Adapter close and releasing the first entry must not disconnect the bus.
    await first.close()
    await first_releases[0]()
    client.disconnect.assert_not_awaited()
    second_response = await second.read("holding", 2, 20, 2)
    assert second_response is not None and second_response.registers == [7, 8]
    factory.assert_called_once()
    client.for_unit_id.assert_any_call(1)
    client.for_unit_id.assert_any_call(2)

    await second.close()
    await second_releases[0]()
    client.disconnect.assert_awaited_once()
    assert second.is_connected() is False


@pytest.fixture
def unit_transport(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Use the unit protocol, without a socket or an HA Core connection."""
    # Test the documented exception hierarchy, not an invented backend contract.
    from modbus_connection.exceptions import ModbusError

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


@pytest.mark.asyncio
async def test_unit_adapter_lazy_lifecycle_and_hub_availability(unit_transport: Any) -> None:
    state = unit_transport
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._transport = state.transport
    hub._name = "SolaX"
    hub._stopping = False
    hub.slowdown = 1
    assert await hub.is_online() is False
    assert await hub._check_connection() is True
    assert await hub.is_online() is False  # Acquired, but not connected yet.
    state.unit.connected = True  # Successful first I/O opens the real link.
    await state.transport.read("holding", 1, 10, 2)
    assert await hub.is_online() is True
    state.unit.read_holding_registers.side_effect = state.error("rejected read")
    with pytest.raises(transport.CoreModbusUnitError):
        await state.transport.read("holding", 1, 10, 2)
    assert await hub.is_online() is True  # A rejected request need not lose the link.
    state.unit.connected = False
    assert await hub.is_online() is False
    await state.transport.close()
    assert await hub.is_online() is False
    assert await hub._check_connection() is True
    state.unit.read_holding_registers.side_effect = None
    state.unit.connected = True
    await state.transport.read("holding", 1, 10, 2)
    assert await hub.is_online() is True
    state.getter.assert_called_once()
    state.unit.disconnect.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["read_holding_registers", "write_register", "write_registers"])
@pytest.mark.parametrize("error_name", ["ModbusConnectionError", "ModbusTimeoutError", "ModbusProtocolError", "ModbusExceptionError", "OSError"])
async def test_public_unit_errors_are_translated(unit_transport: Any, operation: str, error_name: str) -> None:
    from modbus_connection import exceptions

    if error_name == "ModbusExceptionError":
        error: Exception = exceptions.ModbusExceptionError(2)
    elif error_name == "OSError":
        error = ConnectionRefusedError("connection refused")
    else:
        error = getattr(exceptions, error_name)("test failure")
    state = unit_transport
    getattr(state.unit, operation).side_effect = error
    with pytest.raises(transport.CoreModbusUnitError) as caught:
        if operation == "read_holding_registers":
            await state.transport.read("holding", 1, 10, 2)
        else:
            await state.transport.write(1, 10, [7, 8], multiple=operation == "write_registers")
    assert caught.value.__cause__ is error


@pytest.mark.asyncio
async def test_unit_acquisition_conflicts_are_not_hidden(unit_transport: Any) -> None:
    state = unit_transport
    state.getter.side_effect = HomeAssistantError("already in use with different link settings")
    with pytest.raises(HomeAssistantError, match="different link settings"):
        await state.transport.read("holding", 2, 10, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("unit_id", [-1, 256])
async def test_invalid_unit_ids_fail_before_acquisition(unit_transport: Any, unit_id: int) -> None:
    # The fixture already acquired its valid default unit; isolate this request.
    unit_transport.getter.reset_mock()
    with pytest.raises(HomeAssistantError, match="Invalid Modbus unit ID"):
        await unit_transport.transport.read("holding", unit_id, 10, 2)
    unit_transport.getter.assert_not_called()
