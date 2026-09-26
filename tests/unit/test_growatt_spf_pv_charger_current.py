import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfElectricCurrent

from custom_components.solax_modbus.const import REG_INPUT, REGISTER_U16
from custom_components.solax_modbus.plugin_growatt import (
    FIRMWARE_PREFIX_TYPES,
    SENSOR_TYPES,
    SERIAL_PREFIX_TYPES,
    SPF,
    SPF_SINGLE_MPPT_SERIAL_PREFIXES,
    plugin_instance,
)


@pytest.mark.parametrize("prefix,inverter_type", list(SERIAL_PREFIX_TYPES.items()) + list(FIRMWARE_PREFIX_TYPES.items()))
@pytest.mark.parametrize("channel", [1, 2])
def test_pv_charger_current_names_are_scoped_to_spf(prefix: str, inverter_type: int, channel: int) -> None:
    descriptions = [
        description
        for description in SENSOR_TYPES
        if description.key == f"pv_current_{channel}"
        and plugin_instance.matchInverterWithMask(inverter_type, description.allowedtypes, prefix, description.blacklist)
    ]
    if inverter_type & SPF:
        if channel == 2 and prefix in SPF_SINGLE_MPPT_SERIAL_PREFIXES:
            assert descriptions == []
            return
        assert len(descriptions) == 1
        description = descriptions[0]
        assert description.name == f"PV Charger Current {channel}"
        assert description.register == 6 + channel
        assert description.register_type == REG_INPUT
        assert description.register_data_type == REGISTER_U16
        assert description.scale == 0.1
        assert description.rounding == 1
        assert description.native_unit_of_measurement == UnitOfElectricCurrent.AMPERE
        assert description.device_class == SensorDeviceClass.CURRENT
    else:
        for description in descriptions:
            assert description.name == f"PV Current {channel}"
