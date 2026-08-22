from custom_components.solax_modbus.const import REG_HOLDING, REG_INPUT
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


def test_dlp_bms1_module1_uses_apx_input_registers() -> None:
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
    descriptions = _matching_module1_descriptions("DLP1234567")

    for key, register in expected_input_registers.items():
        description = descriptions[key]
        assert description.register == register
        assert description.register_type == REG_INPUT


def test_jcm_bms1_module1_keeps_holding_registers() -> None:
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
    descriptions = _matching_module1_descriptions("JCM0D12345")

    for key, register in expected_holding_registers.items():
        description = descriptions[key]
        assert description.register == register
        assert description.register_type == REG_HOLDING
