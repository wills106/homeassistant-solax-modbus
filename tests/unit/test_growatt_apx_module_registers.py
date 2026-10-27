from unittest.mock import AsyncMock, call, patch

import pytest

from custom_components.solax_modbus.const import CONF_READ_DCB, CONF_READ_EPS, REG_HOLDING, REG_INPUT, REGISTER_U16, REGISTER_U32
from custom_components.solax_modbus.plugin_growatt import (
    APX_BMS_INPUT,
    FIRMWARE_PREFIX_TYPES,
    GEN4,
    HYBRID,
    SENSOR_TYPES,
    SERIAL_PREFIX_TYPES,
    X1,
    GrowattModbusSensorEntityDescription,
    plugin_instance,
)
from tests.conftest import MockHub, MockModbusResponse


def _matching_module1_descriptions(serial_number: str) -> dict[str, GrowattModbusSensorEntityDescription]:
    prefix = serial_number[:3]
    inverter_type = SERIAL_PREFIX_TYPES.get(prefix, FIRMWARE_PREFIX_TYPES.get(prefix, 0))
    descriptions: dict[str, GrowattModbusSensorEntityDescription] = {}
    for description in SENSOR_TYPES:
        if not description.key.startswith("bms_1_module_1_") or not plugin_instance.matchInverterWithMask(
            inverter_type, description.allowedtypes, serial_number, description.blacklist
        ):
            continue
        assert description.key not in descriptions, f"duplicate matching description for {serial_number}: {description.key}"
        descriptions[description.key] = description
    return descriptions


@pytest.mark.parametrize("serial_number", ["DLP1234567", "TSS0F4L1234", "AL1.0Z1234"])
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


@pytest.mark.parametrize("serial_number", ["JCM0D12345", "TTS1234567", "DKS1234567", "ABJ1234567", "SKL1234567", "XVM1234567"])
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


@pytest.mark.parametrize("prefix", [*SERIAL_PREFIX_TYPES, "AL1"])
def test_bms1_aggregate_registers_are_scoped_to_tss(prefix: str) -> None:
    expected = {
        "bms_1_soc": (4058 if prefix == "TSS" else 5777, REGISTER_U16, 1),
        "bms_1_soh": (4065 if prefix == "TSS" else 5778, REGISTER_U16, 1),
        "bms_1_toe": (4025 if prefix == "TSS" else 5769, REGISTER_U32 if prefix == "TSS" else REGISTER_U16, 0.1),
    }
    inverter_type = SERIAL_PREFIX_TYPES.get(prefix, FIRMWARE_PREFIX_TYPES.get(prefix, 0))
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


@pytest.mark.asyncio
async def test_al1_firmware_fallback_selects_module1_input_layout(mock_hub: MockHub) -> None:
    """AL1 is detected via firmware register 9, not a recognized serial prefix."""
    firmware = "AL1.0Z1234"
    registers = [int.from_bytes(firmware[i : i + 2].encode("ascii"), "big") for i in range(0, 10, 2)]
    mock_hub.configure_read(1, 9, 5, MockModbusResponse(registers))
    read = AsyncMock(wraps=mock_hub.async_read_holding_registers)
    with patch.object(mock_hub, "async_read_holding_registers", read):
        inverter_type = await plugin_instance.create_hub_instance().async_determineInverterType(
            mock_hub, {CONF_READ_EPS: False, CONF_READ_DCB: False}
        )

    assert inverter_type == HYBRID | GEN4 | X1 | APX_BMS_INPUT
    assert mock_hub.seriesnumber == firmware
    assert read.await_args_list == [call(unit=1, address=address, count=5) for address in (3001, 209, 23, 9)]
    descriptions = _matching_module1_descriptions(firmware)
    assert descriptions["bms_1_module_1_soc"].depends_on == ["register_5081"]
    for key, register in (("register_5081", 5081), ("bms_1_module_2_status", 5120), ("bms_1_module_2_volt", 5123)):
        matching = [
            description
            for description in SENSOR_TYPES
            if description.key == key
            and plugin_instance.matchInverterWithMask(inverter_type, description.allowedtypes, firmware, description.blacklist)
        ]
        assert len(matching) == 1
        assert matching[0].register == register
        assert matching[0].register_type == REG_INPUT
