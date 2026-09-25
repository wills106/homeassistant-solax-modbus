"""Exercise battery follow-up callbacks, including persistent device metadata."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.solax_modbus import device_registry_lookup, sensor
from custom_components.solax_modbus.const import CONF_READ_BATTERY, DOMAIN, INVERTER_IDENT
from custom_components.solax_modbus.plugin_sofar import battery_config


@pytest.mark.asyncio
@pytest.mark.parametrize("modern_registry", [True, False], ids=["scoped-registry", "legacy-registry"])
@pytest.mark.parametrize("selection", [0, 0x0100, None], ids=["valid-pack", "wrong-pack", "unreadable-selection"])
async def test_pack_metadata_updated_only_after_validation(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, selection: int | None, modern_registry: bool
) -> None:
    """Keep device IDs, repair stale serials once, and preserve failed snapshots' metadata."""
    config = battery_config(
        number_strings=1,
        number_cels_in_parallel=2,
        battery_sensor_key_prefix="battery_{batt-nr}_{pack-nr}_",
    )
    devices = {f"battery_1_{i}": SimpleNamespace(id=f"pack-device-{i}", serial_number=f"OLD-{i}") for i in (1, 2)}
    devices[INVERTER_IDENT] = SimpleNamespace(id="inverter-device")

    def get_device_by_identifier(identifier: tuple[str, str, str], config_entry_id: str) -> SimpleNamespace | None:
        assert config_entry_id == "entry"
        assert identifier[:2] == (DOMAIN, "Sofar")
        return devices.get(identifier[2])

    def get_device(*, identifiers: set[tuple[str, str, str]]) -> SimpleNamespace | None:
        assert len(identifiers) == 1
        return get_device_by_identifier(next(iter(identifiers)), "entry")

    def update_device(device_id: str, **changes: Any) -> None:
        device = next(device for device in devices.values() if device.id == device_id)
        for key, value in changes.items():
            setattr(device, key, value)

    registry = SimpleNamespace(async_update_device=Mock(side_effect=update_device))
    if modern_registry:
        registry.async_get_device_by_identifier = Mock(side_effect=get_device_by_identifier)
    else:
        registry.async_get_device = Mock(side_effect=get_device)
    monkeypatch.setattr(dr, "async_get", lambda hass: registry)
    monkeypatch.setattr(device_registry_lookup, "supports_via_device_id", lambda: modern_registry)
    callbacks: list[Any] = []
    entity_to_list = Mock(side_effect=lambda *args: callbacks.append(args[-1]))
    monkeypatch.setattr(sensor, "entityToList", entity_to_list)
    monkeypatch.setattr(sensor, "entityToListSingle", Mock())

    async def select(hub: Any, batt_nr: int, pack_nr: int) -> bool:
        config.selected_batt_nr = batt_nr
        config.selected_batt_pack_nr = pack_nr
        return True

    monkeypatch.setattr(config, "select_battery", select)
    monkeypatch.setattr(config, "get_batt_pack_model", AsyncMock(return_value="BTS"))
    monkeypatch.setattr(config, "get_batt_pack_sw_version", AsyncMock(return_value="V1"))
    response = None if selection is None else SimpleNamespace(registers=[selection], isError=lambda: False)
    hub = SimpleNamespace(
        name="Sofar",
        _modbus_addr=1,
        device_info={},
        rebuild_blocks=Mock(),
        plugin=SimpleNamespace(BATTERY_CONFIG=config, SENSOR_TYPES=[], ENERGY_DASHBOARD_MAPPING=None, plugin_manufacturer="Sofar"),
        async_read_holding_registers=AsyncMock(return_value=response),
    )
    hass = cast(HomeAssistant, SimpleNamespace(data={DOMAIN: {"Sofar": {"hub": hub}}}))
    entry = cast(ConfigEntry, SimpleNamespace(data={}, options={"name": "Sofar", CONF_READ_BATTERY: True}, entry_id="entry"))
    assert await sensor.async_setup_entry(hass, entry, Mock())
    assert config.batt_pack_serials == {0: {0: "OLD-1", 1: "OLD-2"}}
    for call in entity_to_list.call_args_list[1:]:
        device_info = call.args[5]
        if modern_registry:
            assert device_info["via_device_id"] == "inverter-device"
            assert "via_device" not in device_info
        else:
            assert device_info["via_device"] == (DOMAIN, "Sofar", INVERTER_IDENT)
            assert "via_device_id" not in device_info

    follow_up = callbacks[1]
    for _ in range(2):
        assert await follow_up({}, {"battery_1_1_pack_serial_number": "NEW-1"}) is (selection == 0)

    if selection == 0:
        assert devices["battery_1_1"].serial_number == "NEW-1"
        assert config.batt_pack_serials[0][0] == "NEW-1"
        assert caplog.text.count("serial number changed from 'OLD-1' to 'NEW-1'") == 1
        registry.async_update_device.assert_called_with("pack-device-1", sw_version="V1", model="BTS", serial_number="NEW-1")
        # On the next integration setup, the registry supplies the corrected reference.
        config.batt_pack_serials.clear()
        assert await sensor.async_setup_entry(hass, entry, Mock())
        assert config.batt_pack_serials[0][0] == "NEW-1"
    else:
        registry.async_update_device.assert_not_called()
        assert devices["battery_1_1"].serial_number == "OLD-1"
        assert config.batt_pack_serials[0][0] == "OLD-1"
        assert "serial number changed" not in caplog.text
    assert devices["battery_1_2"].serial_number == "OLD-2"
