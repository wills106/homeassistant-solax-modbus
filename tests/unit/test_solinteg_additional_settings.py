"""Tests for additional Solinteg configuration settings."""

from homeassistant.const import PERCENTAGE, UnitOfPower

from custom_components.solax_modbus.const import REGISTER_U16
from custom_components.solax_modbus.plugin_solinteg import NUMBER_TYPES, SELECT_TYPES, SENSOR_TYPES

NUMBER_SETTINGS = {
    "peak_shaving_max_grid_import_power": (50016, UnitOfPower.KILO_WATT, 200, 0.1),
    "peak_shaving_minimum_soc": (50017, PERCENTAGE, 100, 1),
    "peak_shaving_battery_max_grid_charge": (50018, UnitOfPower.KILO_WATT, 200, 0.1),
    "maximum_battery_charge_power": (50020, UnitOfPower.KILO_WATT, 200, 0.1),
    "maximum_battery_discharge_power": (50021, UnitOfPower.KILO_WATT, 200, 0.1),
}

SELECT_SETTINGS = {
    "battery_soc_reset": 21001,
    "peak_shaving_switch": 50022,
}


def test_additional_number_settings_use_u16_tenths() -> None:
    descriptions = {description.key: description for description in NUMBER_TYPES if description.key in NUMBER_SETTINGS}

    assert descriptions.keys() == NUMBER_SETTINGS.keys()
    for key, (register, unit, maximum, step) in NUMBER_SETTINGS.items():
        description = descriptions[key]
        assert description.register == register
        assert description.register_data_type == REGISTER_U16
        assert description.scale == 0.1
        assert description.native_step == step
        assert description.native_min_value == 0
        assert description.native_max_value == maximum
        assert description.native_unit_of_measurement == unit


def test_additional_switch_settings_use_off_on_options() -> None:
    descriptions = {description.key: description for description in SELECT_TYPES if description.key in SELECT_SETTINGS}

    assert descriptions.keys() == SELECT_SETTINGS.keys()
    for key, register in SELECT_SETTINGS.items():
        description = descriptions[key]
        assert description.register == register
        assert description.register_data_type == REGISTER_U16
        assert description.option_dict == {0: "off", 1: "on"}


def test_additional_settings_have_internal_readback_sensors() -> None:
    expected = NUMBER_SETTINGS.keys() | SELECT_SETTINGS.keys()
    descriptions = {description.key: description for description in SENSOR_TYPES if description.key in expected}

    assert descriptions.keys() == expected
    assert {key: description.register for key, description in descriptions.items()} == {
        **{key: register for key, (register, _unit, _maximum, _step) in NUMBER_SETTINGS.items()},
        **SELECT_SETTINGS,
    }
    assert all(description.internal for description in descriptions.values())
