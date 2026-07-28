from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfElectricPotential
from homeassistant.helpers.entity import EntityCategory  # type: ignore[attr-defined]

from custom_components.solax_modbus.const import REGISTER_U16, WRITE_SINGLE_MODBUS
from custom_components.solax_modbus.number import _scale_native_value_to_register
from custom_components.solax_modbus.plugin_growatt import (
    GEN3,
    GEN4,
    HYBRID,
    NUMBER_TYPES,
    PV,
    SENSOR_TYPES,
    X1,
    plugin_instance,
)


def test_growatt_pv_startup_voltage_descriptions() -> None:
    number = next(description for description in NUMBER_TYPES if description.key == "pv_startup_voltage")
    sensor = next(description for description in SENSOR_TYPES if description.key == "pv_startup_voltage")

    assert number.register == sensor.register == 17
    assert number.register_data_type == sensor.register_data_type == REGISTER_U16
    assert number.scale == sensor.scale == 0.1
    assert number.allowedtypes == sensor.allowedtypes == HYBRID | GEN3
    assert number.native_unit_of_measurement == sensor.native_unit_of_measurement == UnitOfElectricPotential.VOLT
    assert number.device_class == NumberDeviceClass.VOLTAGE
    assert sensor.device_class == SensorDeviceClass.VOLTAGE

    assert number.native_min_value == 0
    assert number.native_max_value == 1000
    assert number.native_step == 0.1
    assert number.write_method == WRITE_SINGLE_MODBUS
    assert number.entity_category == EntityCategory.CONFIG
    assert number.entity_registry_enabled_default is True

    assert _scale_native_value_to_register(150.0, number.scale, number.read_scale) == 1500
    assert plugin_instance.matchInverterWithMask(HYBRID | GEN3 | X1, number.allowedtypes)
    assert not plugin_instance.matchInverterWithMask(PV | GEN3 | X1, number.allowedtypes)
    assert not plugin_instance.matchInverterWithMask(HYBRID | GEN4 | X1, number.allowedtypes)
