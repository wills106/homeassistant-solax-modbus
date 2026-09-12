"""Ensure existing Solis battery energy totals support long-term statistics."""

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy

from custom_components.solax_modbus import plugin_solis
from custom_components.solax_modbus.const import REG_INPUT, REGISTER_U32


@pytest.mark.parametrize(
    ("key", "register"),
    [("total_battery_charge", 33161), ("total_battery_discharge", 33165)],
)
def test_battery_totals_are_energy_dashboard_compatible(key: str, register: int) -> None:
    """Add statistics metadata without changing the existing register mapping."""
    descriptions = [description for description in plugin_solis.SENSOR_TYPES if description.key == key]
    assert len(descriptions) == 1
    description = descriptions[0]
    assert description.device_class == SensorDeviceClass.ENERGY
    assert description.state_class == SensorStateClass.TOTAL_INCREASING
    assert description.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR
    assert description.register == register
    assert description.register_type == REG_INPUT
    assert description.register_data_type == REGISTER_U32
    assert description.scale == 1
    assert description.allowedtypes == plugin_solis.HYBRID
