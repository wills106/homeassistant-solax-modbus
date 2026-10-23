"""Tests for the SolaX Modbus config flow."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowHandler
from homeassistant.helpers.schema_config_entry_flow import SchemaCommonFlowHandler, SchemaFlowError

from custom_components.solax_modbus import config_flow
from custom_components.solax_modbus.config_flow import (
    CONFIG_FLOW,
    CONFIG_SCHEMA,
    CORE_SERIAL_SCHEMA,
    INTERFACES,
    LEGACY_INTERFACE,
    SERIAL_SCHEMA,
    TCP_SCHEMA,
    _duplicate_inverter_schema,
    _next_step_modbus,
    _option_schema,
    _validate_base,
    _validate_interface,
)
from custom_components.solax_modbus.const import (
    CONF_INTERFACE,
    CONF_MODBUS_ADDR,
    CONF_PLUGIN,
    DEFAULT_PLUGIN,
    DOMAIN,
)
from custom_components.solax_modbus.core_modbus import supports_core_units


class _ConfigEntries:
    def __init__(self, entries: list[Any]) -> None:
        self._entries = entries

    def async_entries(self, domain: str) -> list[Any]:
        assert domain == DOMAIN
        return self._entries


class _FlowParent:
    add_suggested_values_to_schema = FlowHandler.add_suggested_values_to_schema
    show_advanced_options = False

    def __init__(self, entries: list[Any]) -> None:
        self.hass = SimpleNamespace(config_entries=_ConfigEntries(entries))

    def async_show_form(self, **kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    def async_create_entry(self, *, data: dict[str, Any]) -> dict[str, Any]:
        return {"type": "create_entry", "data": data}


def _handler_with_entries(
    entries: list[Any],
    *,
    options: dict[str, Any] | None = None,
    current_entry: Any = None,
) -> SchemaCommonFlowHandler:
    hass = SimpleNamespace(config_entries=_ConfigEntries(entries))
    parent_handler = SimpleNamespace(hass=hass)
    if current_entry is not None:
        parent_handler.config_entry = current_entry
    return cast(
        SchemaCommonFlowHandler,
        SimpleNamespace(parent_handler=parent_handler, options=options or {}),
    )


def _base_input(name: str) -> dict[str, Any]:
    return {
        CONF_NAME: name,
        CONF_INTERFACE: "tcp",
        CONF_MODBUS_ADDR: 1,
        CONF_PLUGIN: DEFAULT_PLUGIN,
    }


def test_interface_selector_has_one_tcp_choice_and_a_valid_default() -> None:
    interface = "core_tcp" if supports_core_units() else "tcp"
    assert [item for item in INTERFACES if item["value"] in ("tcp", "core_tcp")] == [{"value": interface, "label": "TCP / Ethernet"}]
    marker = next(key for key in CONFIG_SCHEMA.schema if key.schema == CONF_INTERFACE)
    assert marker.default() == interface


@pytest.mark.asyncio
async def test_tcp_choice_routes_new_setups_to_version_appropriate_backend() -> None:
    interface = next(item["value"] for item in INTERFACES if item["label"] == "TCP / Ethernet")
    handler = SchemaCommonFlowHandler(cast(Any, _FlowParent([])), CONFIG_FLOW, {})
    result = await handler.async_step("user", {**_base_input("SolaX"), CONF_INTERFACE: interface})
    assert result["type"] == "form"
    assert result["step_id"] == interface
    schema = result["data_schema"]
    assert schema is not None
    assert set(schema.schema) == set(TCP_SCHEMA.schema)


def test_interface_selector_has_one_serial_choice() -> None:
    serial = [item for item in INTERFACES if item["value"] in ("serial", "core_serial")]
    assert serial == [{"value": "core_serial" if supports_core_units() else "serial", "label": "Serial"}]


@pytest.mark.asyncio
async def test_serial_choice_routes_new_setups_to_version_appropriate_backend() -> None:
    interface = next(item["value"] for item in INTERFACES if item["label"] == "Serial")
    parent = _FlowParent([])
    handler = SchemaCommonFlowHandler(cast(Any, parent), CONFIG_FLOW, {})
    result = await handler.async_step("user", {**_base_input("SolaX"), CONF_INTERFACE: interface})
    assert result["type"] == "form"
    assert result["step_id"] == interface
    schema = result["data_schema"]
    assert schema is not None
    expected = CORE_SERIAL_SCHEMA if supports_core_units() else SERIAL_SCHEMA
    assert set(schema.schema) == set(expected.schema)


def test_legacy_interface_is_not_offered_to_new_connections() -> None:
    interface = next(value for key, value in CONFIG_SCHEMA.schema.items() if key.schema == CONF_INTERFACE)
    assert all(item["value"] != "core" for item in interface.config["options"])


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted_interface", ["core", "tcp", "core_tcp", "serial", "core_serial"])
@pytest.mark.parametrize("legacy_data", [False, True])
async def test_only_existing_legacy_entries_can_keep_the_legacy_interface(
    monkeypatch: pytest.MonkeyPatch, persisted_interface: str, legacy_data: bool
) -> None:
    monkeypatch.setattr(config_flow, "_plugin_supports_device_group", lambda *args: True)
    monkeypatch.setattr(config_flow, "_plugin_supports_energy_dashboard", lambda *args: True)
    monkeypatch.setattr(config_flow, "_plugin_uses_feature_flag", lambda *args: True)
    saved = {CONF_INTERFACE: persisted_interface}
    entry = SimpleNamespace(entry_id="existing", options={} if legacy_data else saved, data=saved if legacy_data else {})
    # An uncommitted candidate value must not grant access to legacy mode.
    handler = _handler_with_entries([entry], options={CONF_INTERFACE: "core"}, current_entry=entry)
    schema = await _option_schema(handler)
    interface = next(value for key, value in schema.schema.items() if key.schema == CONF_INTERFACE)
    legacy = [item for item in interface.config["options"] if item["value"] == "core"]
    assert legacy == ([LEGACY_INTERFACE] if persisted_interface == "core" else [])
    assert "2027.10" in LEGACY_INTERFACE["label"]

    if persisted_interface == "core":
        assert await _validate_interface(handler, {CONF_INTERFACE: "core"}) == {CONF_INTERFACE: "core"}
    else:
        with pytest.raises(SchemaFlowError, match="legacy_hub_unavailable"):
            await _validate_interface(handler, {CONF_INTERFACE: "core"})
    assert entry.options == ({} if legacy_data else saved)


@pytest.mark.asyncio
async def test_new_flow_cannot_submit_a_hidden_legacy_interface() -> None:
    with pytest.raises(SchemaFlowError, match="legacy_hub_unavailable"):
        await _validate_base(_handler_with_entries([]), {**_base_input("SolaX"), CONF_INTERFACE: "core"})


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted_interface", ["core", "tcp"])
async def test_options_flow_only_retains_already_selected_legacy_interface(persisted_interface: str) -> None:
    entry = SimpleNamespace(entry_id="existing", options={CONF_INTERFACE: persisted_interface}, data={})
    parent = SimpleNamespace(
        hass=SimpleNamespace(config_entries=_ConfigEntries([entry])),
        config_entry=entry,
        show_advanced_options=False,
        async_show_form=lambda **kwargs: {"type": "form", **kwargs},
        add_suggested_values_to_schema=lambda schema, values: schema,
    )
    handler = SchemaCommonFlowHandler(cast(Any, parent), config_flow.OPTIONS_FLOW, {CONF_INTERFACE: persisted_interface})
    result = await handler.async_step("init", {CONF_INTERFACE: "core"})
    assert result["type"] == "form"
    if persisted_interface == "core":
        assert result["step_id"] == "core"
        assert handler.options[CONF_INTERFACE] == "core"
    else:
        assert result["step_id"] == "init"
        assert result["errors"] == {"base": "legacy_hub_unavailable"}
        assert handler.options[CONF_INTERFACE] == "tcp"


def test_legacy_warning_texts_explain_the_api_deadline() -> None:
    root = Path(config_flow.__file__).parent
    for path in (root / "strings.json", root / "translations" / "en.json"):
        strings = json.loads(path.read_text())
        for section in ("config", "options"):
            description = strings[section]["step"]["core"]["description"]
            assert "2027.10" in description and "access API" in description
            assert "Core Modbus migration guide" in description
            assert "http://" not in description and "https://" not in description
            assert "legacy_hub_unavailable" in strings[section]["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("interface", ["serial", "core_serial", "tcp", "core_tcp", "core"])
async def test_saved_interface_values_keep_their_flow_routes(interface: str) -> None:
    assert await _next_step_modbus({CONF_INTERFACE: interface}) == interface


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_name", ["SolaX", " solax ", "SOLAX"])
async def test_validate_base_rejects_duplicate_hub_name(existing_name: str) -> None:
    """Reject names that identify an already configured hub."""
    entry = SimpleNamespace(options={CONF_NAME: existing_name}, data={})

    with pytest.raises(SchemaFlowError, match="name_already_used"):
        await _validate_base(_handler_with_entries([entry]), _base_input("SolaX"))


@pytest.mark.asyncio
async def test_validate_base_checks_legacy_entry_data() -> None:
    """Reject a duplicate name stored in legacy config entry data."""
    entry = SimpleNamespace(options={}, data={CONF_NAME: "SolaX"})

    with pytest.raises(SchemaFlowError, match="name_already_used"):
        await _validate_base(_handler_with_entries([entry]), _base_input("SolaX"))


@pytest.mark.asyncio
async def test_validate_base_allows_unique_hub_name() -> None:
    """Allow a hub name that is not already configured."""
    entry = SimpleNamespace(options={CONF_NAME: "SolaX Garage"}, data={})
    user_input = _base_input("SolaX Loft")

    result = await _validate_base(_handler_with_entries([entry]), user_input)

    assert result == user_input


@pytest.mark.asyncio
async def test_validate_base_preserves_default_name_handling_for_other_plugins() -> None:
    """Keep suggesting the plugin name when a non-SolaX plugin uses the default."""
    entry = SimpleNamespace(options={CONF_NAME: "SolaX"}, data={})
    user_input = _base_input("SolaX")
    user_input[CONF_PLUGIN] = "growatt"

    with pytest.raises(SchemaFlowError, match="name_already_used"):
        await _validate_base(_handler_with_entries([entry]), user_input)

    assert user_input[CONF_NAME] == "growatt"


@pytest.mark.asyncio
async def test_duplicate_connection_shows_confirmation() -> None:
    """Show the same non-blocking warning during initial setup."""
    connection = {
        CONF_NAME: "SolaX Test",
        CONF_INTERFACE: "tcp",
        "host": "192.0.2.10",
        "port": 502,
        CONF_MODBUS_ADDR: 1,
    }
    existing = SimpleNamespace(
        entry_id="existing",
        title="SolaX Existing",
        options={**connection, CONF_NAME: "SolaX Existing"},
        data={},
    )
    handler = _handler_with_entries([existing], options=connection)

    schema = await _duplicate_inverter_schema(handler)

    assert schema is not None
    assert schema.schema == {}


@pytest.mark.asyncio
async def test_options_flow_excludes_only_the_entry_being_edited() -> None:
    """Warn on save when another matching inverter config exists."""
    connection = {
        CONF_NAME: "SolaX Existing",
        CONF_INTERFACE: "serial",
        "read_serial_port": "/dev/ttyUSB0",
        CONF_MODBUS_ADDR: 1,
    }
    current = SimpleNamespace(entry_id="current", title="SolaX Existing", options=connection, data={})
    duplicate = SimpleNamespace(
        entry_id="duplicate",
        title="SolaX Test",
        options={**connection, CONF_NAME: "SolaX Test"},
        data={},
    )

    current_only = _handler_with_entries([current], options=connection, current_entry=current)
    with_duplicate = _handler_with_entries([current, duplicate], options=connection, current_entry=current)

    assert await _duplicate_inverter_schema(current_only) is None
    assert await _duplicate_inverter_schema(with_duplicate) is not None


@pytest.mark.asyncio
async def test_duplicate_warning_step_allows_save_after_confirmation() -> None:
    """Show the warning once, then complete the flow after an empty submit."""
    connection = {
        CONF_NAME: "SolaX Test",
        CONF_INTERFACE: "tcp",
        "host": "192.0.2.10",
        "port": 502,
        CONF_MODBUS_ADDR: 1,
    }
    existing = SimpleNamespace(
        entry_id="existing",
        title="SolaX Existing",
        options={**connection, CONF_NAME: "SolaX Existing"},
        data={},
    )
    parent = _FlowParent([existing])
    handler = SchemaCommonFlowHandler(cast(Any, parent), CONFIG_FLOW, connection)

    warning = await handler.async_step("duplicate_inverter")

    assert warning["type"] == "form"
    assert warning["step_id"] == "duplicate_inverter"
    data_schema = warning["data_schema"]
    assert data_schema is not None
    assert data_schema.schema == {}

    result = await handler.async_step("duplicate_inverter", {})

    assert result == {"type": "create_entry", "data": connection}


@pytest.mark.asyncio
async def test_duplicate_warning_step_is_skipped_for_unique_connection() -> None:
    """Complete the flow immediately when no other inverter connection matches."""
    connection = {
        CONF_NAME: "SolaX",
        CONF_INTERFACE: "core",
        "read_core_hub": "inverter_bus",
        CONF_MODBUS_ADDR: 1,
    }
    handler = SchemaCommonFlowHandler(cast(Any, _FlowParent([])), CONFIG_FLOW, connection)

    result = await handler.async_step("duplicate_inverter")

    assert result == {"type": "create_entry", "data": connection}
