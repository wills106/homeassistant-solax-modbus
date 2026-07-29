"""Tests for Solis current number register limits."""

from types import ModuleType

import pytest

from custom_components.solax_modbus import plugin_solis, plugin_solis_fb00
from custom_components.solax_modbus.const import REGISTER_U16, REGISTER_U16_MAX
from custom_components.solax_modbus.number import _scale_native_value_to_register

SOLIS_CURRENT_KEYS = {
    "battery_chargedischarge_current",
    "battery_charge_current",
    "battery_discharge_current",
    "timed_charge_current",
    "timed_discharge_current",
}
SOLIS_FB00_CURRENT_KEYS = {
    "battery_chargedischarge_current",
    "battery_charge_current",
    "battery_discharge_current",
    *(f"timed_{direction}_current{suffix}" for direction in ("charge", "discharge") for suffix in ("", "_2", "_3", "_4", "_5", "_6")),
}


@pytest.mark.parametrize(
    ("plugin", "expected_keys"),
    [
        (plugin_solis, SOLIS_CURRENT_KEYS),
        (plugin_solis_fb00, SOLIS_FB00_CURRENT_KEYS),
    ],
)
def test_solis_current_numbers_use_full_u16_native_range(plugin: ModuleType, expected_keys: set[str]) -> None:
    descriptions = {description.key: description for description in plugin.NUMBER_TYPES if description.key in expected_keys}

    assert descriptions.keys() == expected_keys
    for description in descriptions.values():
        assert description.register_data_type == REGISTER_U16
        assert description.scale == 0.1
        assert description.native_min_value == 0
        assert description.native_max_value == REGISTER_U16_MAX * description.scale
        assert (
            _scale_native_value_to_register(
                description.native_max_value,
                description.scale,
                description.read_scale,
            )
            == REGISTER_U16_MAX
        )
        assert description.max_exceptions is None
