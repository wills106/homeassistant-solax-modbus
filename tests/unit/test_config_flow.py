"""Tests for the SolaX Modbus config flow."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from homeassistant.const import CONF_NAME
from homeassistant.helpers.schema_config_entry_flow import SchemaCommonFlowHandler, SchemaFlowError

from custom_components.solax_modbus.config_flow import (
    CONFIG_FLOW,
    _duplicate_inverter_schema,
    _validate_base,
)
from custom_components.solax_modbus.const import (
    CONF_INTERFACE,
    CONF_MODBUS_ADDR,
    CONF_PLUGIN,
    DEFAULT_PLUGIN,
    DOMAIN,
)


class _ConfigEntries:
    def __init__(self, entries: list[Any]) -> None:
        self._entries = entries

    def async_entries(self, domain: str) -> list[Any]:
        assert domain == DOMAIN
        return self._entries


class _FlowParent:
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
