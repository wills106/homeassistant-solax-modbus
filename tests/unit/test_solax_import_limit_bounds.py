"""Import limits describe the mains connection, not the inverter rating."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from custom_components.solax_modbus.const import REGISTER_INT_RANGES, REGISTER_S32
from custom_components.solax_modbus.number import SolaXModbusNumber, _native_value_bounds
from custom_components.solax_modbus.plugin_solax import NUMBER_TYPES, plugin_instance


def make_hub(parallel_setting: str, config_max_export: float | None) -> Any:
    """Build real number entities to exercise the callback and derived bounds."""
    hub = SimpleNamespace(
        data={"parallel_setting": parallel_setting},
        inverterPowerKw=24,
        seriesnumber="H34A12",
        numberEntities={},
        sensorEntities={},
        localsUpdated=False,
    )
    for key in ("remotecontrol_import_limit", "remotecontrol_active_power", "export_control_user_limit"):
        description = next(item for item in NUMBER_TYPES if item.key == key)
        hub.numberEntities[key] = SolaXModbusNumber("SolaX", hub, 1, {}, description)
    if config_max_export is not None:
        hub.numberEntities["config_max_export"] = SimpleNamespace(enabled=True)
        hub.data["config_max_export"] = config_max_export
    return hub


def test_import_limit_uses_existing_signed_32_bit_bounds() -> None:
    description = next(item for item in NUMBER_TYPES if item.key == "remotecontrol_import_limit")

    assert description.native_min_value == 0
    assert description.native_max_value is None
    assert description.register_data_type == REGISTER_S32
    assert _native_value_bounds(description) == (0, REGISTER_INT_RANGES[REGISTER_S32][1])


@pytest.mark.parametrize("parallel_setting", ["Free", "Master", "Slave"])
@pytest.mark.parametrize("config_max_export", [None, 26000])
def test_import_limit_is_not_overridden_by_inverter_or_export_limits(parallel_setting: str, config_max_export: float | None) -> None:
    hub = make_hub(parallel_setting, config_max_export)
    number = hub.numberEntities["remotecontrol_import_limit"]
    hub.data["remotecontrol_import_limit"] = 72000

    for system_power_kw in (24, 36):
        hub.inverterPowerKw = system_power_kw
        plugin_instance.localDataCallback(hub)
        assert number.native_min_value == 0
        assert number.native_max_value == REGISTER_INT_RANGES[REGISTER_S32][1]
        assert number.entity_description.native_max_value is None
        assert number.native_value == 72000


@pytest.mark.parametrize("parallel_setting", ["Free", "Master", "Slave"])
def test_other_power_limits_keep_their_existing_behavior(parallel_setting: str) -> None:
    hub = make_hub(parallel_setting, 26000)

    plugin_instance.localDataCallback(hub)

    active_power = hub.numberEntities["remotecontrol_active_power"]
    assert active_power.native_max_value == (24000 if parallel_setting == "Master" else 26000)
    if parallel_setting == "Master":
        assert active_power.native_min_value == -24000
    assert hub.numberEntities["export_control_user_limit"].native_max_value == 26000


@pytest.mark.asyncio
async def test_large_import_limit_is_stored_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    hub = make_hub("Master", 26000)
    number = hub.numberEntities["remotecontrol_import_limit"]
    monkeypatch.setattr(number, "async_write_ha_state", Mock())
    plugin_instance.localDataCallback(hub)

    assert number.native_min_value <= 72000 <= number.native_max_value
    await number.async_set_native_value(72000)

    assert hub.data["remotecontrol_import_limit"] == 72000
    assert number.native_value == 72000
    assert hub.localsUpdated is True
