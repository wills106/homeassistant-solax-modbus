from homeassistant.components.number import NumberDeviceClass
from homeassistant.const import EntityCategory, UnitOfElectricCurrent

from custom_components.solax_modbus.const import WRITE_SINGLE_MODBUS
from custom_components.solax_modbus.plugin_growatt import NUMBER_TYPES, SPF, plugin_instance


def test_spf_max_ac_charge_current_number() -> None:
    descriptions = [description for description in NUMBER_TYPES if description.key == "max_ac_charge_current"]

    assert len(descriptions) == 1
    description = descriptions[0]
    assert description.register == 38
    assert description.native_min_value == 0
    assert description.native_max_value == 100
    assert description.native_step == 1
    assert description.native_unit_of_measurement == UnitOfElectricCurrent.AMPERE
    assert description.device_class == NumberDeviceClass.CURRENT
    assert description.entity_category == EntityCategory.CONFIG
    assert description.write_method == WRITE_SINGLE_MODBUS
    assert plugin_instance.matchInverterWithMask(SPF, description.allowedtypes)
