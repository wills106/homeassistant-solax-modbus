import pytest

from custom_components.solax_modbus.const import REG_HOLDING, REG_INPUT, REGISTER_U16, REGISTER_U32
from custom_components.solax_modbus.plugin_growatt import (
    SENSOR_TYPES,
    SERIAL_PREFIX_TYPES,
    GrowattModbusSensorEntityDescription,
    plugin_instance,
)


def _matching_module1_descriptions(serial_number: str) -> dict[str, GrowattModbusSensorEntityDescription]:
    inverter_type = SERIAL_PREFIX_TYPES[serial_number[:3]]
    descriptions: dict[str, GrowattModbusSensorEntityDescription] = {}
    for description in SENSOR_TYPES:
        if not description.key.startswith("bms_1_module_1_") or not plugin_instance.matchInverterWithMask(
            inverter_type, description.allowedtypes, serial_number, description.blacklist
        ):
            continue
        assert description.key not in descriptions, f"duplicate matching description for {serial_number}: {description.key}"
        descriptions[description.key] = description
    return descriptions


@pytest.mark.parametrize("serial_number", ["DLP1234567", "TSS0F4L1234"])
def test_apx_bms1_module1_uses_input_registers(serial_number: str) -> None:
    expected_input_registers = {
        "bms_1_module_1_status": 5080,
        "bms_1_module_1_soh": 5082,
        "bms_1_module_1_volt": 5083,
        "bms_1_module_1_combined_current": 5084,
        "bms_1_module_1_combined_power": 5085,
        "bms_1_module_1_toe": 5087,
        "bms_1_module_1_max_cell_temp": 5090,
        "bms_1_module_1_min_cell_temp": 5091,
        "bms_1_module_1_warning_text": 5098,
        "bms_1_module_1_charge_cycles": 5108,
    }
    descriptions = _matching_module1_descriptions(serial_number)

    for key, register in expected_input_registers.items():
        description = descriptions[key]
        assert description.register == register
        assert description.register_type == REG_INPUT


@pytest.mark.parametrize("serial_number", ["JCM0D12345", "TTS1234567", "DKS1234567"])
def test_other_models_bms1_module1_keep_holding_registers(serial_number: str) -> None:
    expected_holding_registers = {
        "bms_1_module_1_status": 5880,
        "bms_1_module_1_soh": 5882,
        "bms_1_module_1_volt": 5883,
        "bms_1_module_1_combined_current": 5884,
        "bms_1_module_1_combined_power": 5885,
        "bms_1_module_1_toe": 5887,
        "bms_1_module_1_max_cell_temp": 5890,
        "bms_1_module_1_min_cell_temp": 5891,
        "bms_1_module_1_warning_text": 5898,
        "bms_1_module_1_charge_cycles": 5908,
    }
    descriptions = _matching_module1_descriptions(serial_number)

    for key, register in expected_holding_registers.items():
        description = descriptions[key]
        assert description.register == register
        assert description.register_type == REG_HOLDING


@pytest.mark.parametrize("prefix", list(SERIAL_PREFIX_TYPES))
def test_bms1_aggregate_registers_are_scoped_to_tss(prefix: str) -> None:
    expected = {
        "bms_1_soc": (4058 if prefix == "TSS" else 5777, REGISTER_U16, 1),
        "bms_1_soh": (4065 if prefix == "TSS" else 5778, REGISTER_U16, 1),
        "bms_1_toe": (4025 if prefix == "TSS" else 5769, REGISTER_U32 if prefix == "TSS" else REGISTER_U16, 0.1),
    }
    inverter_type = SERIAL_PREFIX_TYPES[prefix]
    for key, (register, data_type, scale) in expected.items():
        candidates = [description for description in SENSOR_TYPES if description.key == key]
        original = next(description for description in candidates if description.register in (5769, 5777, 5778))
        was_supported = plugin_instance.matchInverterWithMask(inverter_type, original.allowedtypes)
        matching = [
            description
            for description in candidates
            if plugin_instance.matchInverterWithMask(inverter_type, description.allowedtypes, prefix + "0F4L1234", description.blacklist)
        ]
        assert len(matching) == int(was_supported)
        if not was_supported:
            continue
        description = matching[0]
        assert description.register == register
        assert description.register_type == REG_INPUT
        assert description.register_data_type == data_type
        assert description.scale == scale
        assert description.name == original.name
        assert description.state_class == original.state_class
        assert description.entity_registry_enabled_default == original.entity_registry_enabled_default
