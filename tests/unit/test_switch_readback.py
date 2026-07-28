"""Tests for Modbus and local switch state handling."""

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

import custom_components.solax_modbus.switch as switch_platform
from custom_components.solax_modbus.const import (
    CONF_MODBUS_ADDR,
    DOMAIN,
    WRITE_DATA_LOCAL,
    WRITE_MULTISINGLE_MODBUS,
    WRITE_SINGLE_MODBUS,
    BaseModbusSwitchEntityDescription,
)
from custom_components.solax_modbus.switch import SolaXModbusSwitch


class _Plugin:
    def __init__(self, switch_types: list[BaseModbusSwitchEntityDescription]) -> None:
        self.SWITCH_TYPES = switch_types

    def matchInverterWithMask(self, *_args: Any) -> bool:
        return True


def _description(
    key: str,
    sensor_key: str,
    *,
    write_method: int = WRITE_SINGLE_MODBUS,
) -> BaseModbusSwitchEntityDescription:
    return BaseModbusSwitchEntityDescription(
        key=key,
        name=key,
        register=1,
        sensor_key=sensor_key,
        write_method=write_method,
    )


@pytest.mark.asyncio
async def test_only_local_switches_register_persistent_state(monkeypatch: Any) -> None:
    """Do not let Modbus switch readbacks enter the local-data store."""
    modbus_switch = _description("modbus_switch", "modbus_readback")
    local_switch = _description("local_switch", "local_state", write_method=WRITE_DATA_LOCAL)
    provider_modbus_switch = _description("provider_modbus_switch", "provider_modbus_readback")
    provider_local_switch = _description("provider_local_switch", "provider_local_state", write_method=WRITE_DATA_LOCAL)

    hub = SimpleNamespace(
        _invertertype=1,
        _name="SolaX",
        computedSwitches={},
        device_info={},
        entity_dependencies={},
        name="SolaX",
        plugin=_Plugin([modbus_switch, local_switch]),
        seriesnumber="test",
        switchEntities={},
        writeLocals={},
    )

    def _provider(_hub: Any, _hass: Any, _entry: Any) -> tuple[dict[Any, Any], str, list[BaseModbusSwitchEntityDescription]]:
        return {}, "Provider", [provider_modbus_switch, provider_local_switch]

    hass = cast(
        HomeAssistant,
        SimpleNamespace(
            data={
                DOMAIN: {
                    "SolaX": {"hub": hub},
                    "_switch_entity_providers": [_provider],
                }
            }
        ),
    )
    entry = cast(
        ConfigEntry,
        SimpleNamespace(
            data={},
            options={CONF_NAME: "SolaX", CONF_MODBUS_ADDR: 1},
        ),
    )
    added_entities: list[SolaXModbusSwitch] = []

    def _matches_modbus_protocol(_hub: Any, _description: Any) -> bool:
        return True

    monkeypatch.setattr(switch_platform, "matches_modbus_protocol", _matches_modbus_protocol)

    await switch_platform.async_setup_entry(hass, entry, cast(Any, added_entities.extend))

    assert len(added_entities) == 4
    assert hub.writeLocals == {
        "local_state": local_switch,
        "provider_local_state": provider_local_switch,
    }


@pytest.mark.parametrize("data", [{}, {"readback": None}])
def test_missing_switch_readback_is_unknown_without_error(data: dict[str, Any], caplog: Any) -> None:
    """Treat a not-yet-read value as unknown instead of logging an error."""
    description = _description("modbus_switch", "readback")
    hub = SimpleNamespace(data=data, name="SolaX")
    switch = SolaXModbusSwitch("SolaX", hub, 1, cast(Any, {}), description)

    with caplog.at_level(logging.ERROR, logger="custom_components.solax_modbus.switch"):
        assert switch.is_on is None

    assert caplog.records == []


@pytest.mark.parametrize(("raw_value", "expected"), [(0, False), (1, True)])
def test_switch_uses_integer_readback(raw_value: int, expected: bool) -> None:
    """Keep deriving the switch state from a valid Modbus readback."""
    description = _description("modbus_switch", "readback")
    hub = SimpleNamespace(data={"readback": raw_value}, name="SolaX")
    switch = SolaXModbusSwitch("SolaX", hub, 1, cast(Any, {}), description)

    assert switch.is_on is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("write_method", "expected_method"),
    [
        (WRITE_SINGLE_MODBUS, "async_write_register"),
        (WRITE_MULTISINGLE_MODBUS, "async_write_registers_single"),
    ],
)
async def test_switch_respects_configured_write_method(write_method: int, expected_method: str) -> None:
    """Use FC6 by default and FC16 only when the description requests it."""

    def _payload(_bit: int | None, is_on: bool | None, _sensor_key: str | None, _data: dict[str, Any]) -> int:
        return int(bool(is_on))

    description = BaseModbusSwitchEntityDescription(
        key="modbus_switch",
        name="modbus_switch",
        register=0x9E,
        sensor_key="readback",
        value_function=_payload,
        write_method=write_method,
    )
    hub = SimpleNamespace(
        async_write_register=AsyncMock(),
        async_write_registers_single=AsyncMock(),
        data={},
        name="SolaX",
    )
    switch = SolaXModbusSwitch("SolaX", hub, 1, cast(Any, {}), description)

    await switch._write_switch_to_modbus(True)

    expected = getattr(hub, expected_method)
    expected.assert_awaited_once_with(
        unit=1,
        address=0x9E,
        payload=1,
        register_data_type=None,
    )
    other_method = "async_write_registers_single" if expected_method == "async_write_register" else "async_write_register"
    getattr(hub, other_method).assert_not_awaited()
