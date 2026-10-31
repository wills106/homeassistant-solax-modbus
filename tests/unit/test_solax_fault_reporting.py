"""Model-specific fault words must stay useful and safe for HA automations."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from pytest_homeassistant_custom_component.common import async_test_home_assistant

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.const import (
    DOMAIN,
    REG_INPUT,
    REGISTER_U16,
    REGISTER_U32,
    SLEEPMODE_NONE,
    BaseModbusSensorEntityDescription,
    matches_modbus_protocol,
)
from custom_components.solax_modbus.plugin_solax import (
    AC,
    GEN2,
    GEN3,
    GEN4,
    GEN5,
    GEN6,
    HYBRID,
    MAX,
    MIC,
    SENSOR_TYPES_MAIN,
    X1,
    X3,
    SolaXModbusSensorEntityDescription,
    plugin_instance,
)
from custom_components.solax_modbus.sensor import SolaXModbusSensor

PROFILES = [(GEN3, X1, 0), (GEN3, X3, 0), (GEN4, X1, 2), (GEN4, X3, 2), (GEN4, X3, 100)]


def _descriptions(inverter_type: int, version: int | None) -> list[SolaXModbusSensorEntityDescription]:
    hub = SimpleNamespace(modbus_protocol_version=version, data={})
    return [
        description
        for description in SENSOR_TYPES_MAIN
        if description.fault_bits is not None
        and plugin_instance.matchInverterWithMask(inverter_type, description.allowedtypes)
        and matches_modbus_protocol(hub, description)
    ]


def _hub() -> Any:
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "test"
    hub.plugin = plugin_instance
    hub.data = {}
    hub.cyclecount = 1
    hub._validate_register_func = None
    hub.tmpdata_expiry = {}
    hub.localsLoaded = True
    return hub


def _sensor(hub: Any, description: BaseModbusSensorEntityDescription) -> SolaXModbusSensor:
    return SolaXModbusSensor("test", hub, DeviceInfo(identifiers={(DOMAIN, "test")}), description)


@pytest.mark.parametrize(("generation", "phases", "version"), PROFILES + [(GEN4, X1, 99), (GEN4, X3, 99), (GEN4, X3, 102)])
def test_supported_profiles_have_exactly_two_diagnostic_sensors(generation: int, phases: int, version: int) -> None:
    descriptions = _descriptions(HYBRID | generation | phases, version)
    assert [description.key for description in descriptions] == ["inverter_errors", "manager_errors"]
    assert [description.register for description in descriptions] == [0x40, 0x43]
    assert [description.register_data_type for description in descriptions] == [REGISTER_U32, REGISTER_U16]
    for description in descriptions:
        assert description.register_type == REG_INPUT
        assert description.sleepmode == SLEEPMODE_NONE
        assert description.entity_category == EntityCategory.DIAGNOSTIC
        assert description.native_unit_of_measurement is None
        assert description.state_class is None
        assert description.scale == 1
        assert description.rounding == 0
        assert description.ignore_readerror is False


@pytest.mark.parametrize(
    ("inverter_type", "version"),
    [
        (HYBRID | GEN2 | X1, 2),
        (HYBRID | GEN4 | X1, 100),
        (HYBRID | GEN4 | X1, 102),
        (HYBRID | GEN4 | X1, None),
        (HYBRID | GEN4 | X3, None),
        (HYBRID | GEN4 | X3, 0),
        (HYBRID | GEN5 | X1, 100),
        (HYBRID | GEN5 | X3, 100),
        (HYBRID | GEN6 | X1, 100),
        (HYBRID | GEN6 | X3, 100),
        (AC | GEN4 | X1, 2),
        (MIC | GEN3 | X1, 2),
        (MIC | GEN4 | X3, 100),
        (MAX, 100),
    ],
)
def test_undocumented_profiles_do_not_inherit_fault_tables(inverter_type: int, version: int | None) -> None:
    assert _descriptions(inverter_type, version) == []


@pytest.mark.parametrize(("generation", "phases", "version"), PROFILES)
def test_fault_words_decode_all_bits_and_preserve_numeric_hub_data(generation: int, phases: int, version: int) -> None:
    hub = _hub()
    for description in _descriptions(HYBRID | generation | phases, version):
        sensor = _sensor(hub, description)
        width = 32 if description.register_data_type == REGISTER_U32 else 16
        assert sensor.device_class is None  # Not an enum: fault combinations are unbounded.
        assert sensor.should_poll is False
        for bit in range(width):
            value = 1 << bit
            words = [value & 0xFFFF, value >> 16] if width == 32 else [value]
            assert hub.treat_address(hub.data, words, 0, description) == width // 16
            assert hub.data[description.key] == value
            assert isinstance(hub.data[description.key], int)
            assert sensor.native_value == "1 active fault"
            assert sensor.extra_state_attributes["raw_value"] == value
            assert description.fault_bits is not None
            assert sensor.extra_state_attributes["active_errors"] == [description.fault_bits.get(bit, f"Unknown bit {bit}")]

        hub.treat_address(hub.data, [0xFFFF] * (width // 16), 0, description)
        assert sensor.native_value == f"{width} active faults"
        assert len(sensor.extra_state_attributes["active_errors"]) == width
        hub.treat_address(hub.data, [0] * (width // 16), 0, description)
        assert sensor.native_value == "Normal"
        assert sensor.extra_state_attributes["raw_value"] == 0
        assert sensor.extra_state_attributes["active_errors"] == []


@pytest.mark.parametrize(
    ("generation", "phases", "version", "key", "bit", "expected"),
    [
        (GEN3, X1, 0, "inverter_errors", 23, "BMS Lost"),
        (GEN3, X3, 0, "inverter_errors", 23, "Parallel Fault"),
        (GEN3, X1, 0, "inverter_errors", 21, "Unknown bit 21"),
        (GEN3, X3, 0, "inverter_errors", 21, "Phase Angle Fault"),
        (GEN4, X1, 2, "inverter_errors", 23, "BMS Lost"),
        (GEN4, X3, 2, "inverter_errors", 18, "BMS Lost"),
        (GEN4, X1, 2, "inverter_errors", 9, "Unknown bit 9"),
        (GEN4, X3, 2, "inverter_errors", 9, "DCV OCP Fault"),
        (GEN4, X1, 2, "inverter_errors", 15, "Missed CT Fault"),
        (GEN4, X3, 2, "inverter_errors", 15, "Off-grid Overload"),
        (GEN4, X3, 2, "inverter_errors", 16, "Overload"),
        (GEN4, X3, 100, "inverter_errors", 16, "Arc Fault"),
        (GEN3, X3, 0, "manager_errors", 3, "DSP Version Fault"),
        (GEN4, X3, 2, "manager_errors", 3, "Unknown bit 3"),
        (GEN4, X3, 100, "manager_errors", 3, "DataHub Comms Error"),
        (GEN4, X3, 2, "manager_errors", 11, "Fan 2 Fault"),
        (GEN4, X3, 100, "manager_errors", 11, "Arc Hardware Fault"),
        (GEN4, X3, 100, "manager_errors", 14, "Fan 2 Fault"),
    ],
)
def test_protocol_and_model_specific_labels(generation: int, phases: int, version: int, key: str, bit: int, expected: str) -> None:
    description = next(item for item in _descriptions(HYBRID | generation | phases, version) if item.key == key)
    hub = _hub()
    hub.data[key] = 1 << bit
    assert _sensor(hub, description).extra_state_attributes["active_errors"] == [expected]


@pytest.mark.parametrize("value", [None, -1, 12.0, "12", [], False, True])
def test_missing_or_invalid_fault_word_never_reports_normal(value: Any) -> None:
    hub = _hub()
    description = _descriptions(HYBRID | GEN4 | X3, 100)[0]
    sensor = _sensor(hub, description)
    assert sensor.native_value is None
    hub.data[description.key] = value
    assert sensor.native_value is None
    assert sensor.extra_state_attributes["raw_value"] is None
    assert sensor.extra_state_attributes["active_errors"] is None


@pytest.mark.asyncio
async def test_ha_publishes_multiple_faults_attribute_only_changes_and_recovery() -> None:
    hub = _hub()
    description = _descriptions(HYBRID | GEN4 | X3, 100)[0]
    sensor = _sensor(hub, description)
    sensor.entity_id = "sensor.test_inverter_errors"
    async with async_test_home_assistant() as hass:
        try:
            sensor.hass = hass
            for value, state, errors in [
                (None, "unknown", None),
                (0, "Normal", []),
                (12, "2 active faults", ["Grid Volt Fault", "Grid Freq Fault"]),
                (4, "1 active fault", ["Grid Volt Fault"]),
                (8, "1 active fault", ["Grid Freq Fault"]),
                (None, "unknown", None),
                (0, "Normal", []),
            ]:
                hub.data[description.key] = value
                sensor.modbus_data_updated()
                published = hass.states.get(sensor.entity_id)
                assert published is not None
                assert published.state == state
                assert published.attributes["raw_value"] == value
                assert published.attributes["active_errors"] == errors
                assert published.attributes["ed_mapping_present"] is False
        finally:
            await hass.async_stop(force=True)


def test_sensors_without_fault_metadata_are_unchanged() -> None:
    hub = _hub()
    description = BaseModbusSensorEntityDescription(key="power", native_unit_of_measurement="W")
    hub.data[description.key] = 123.5
    sensor = _sensor(hub, description)
    assert sensor.native_value == 123.5
    assert "raw_value" not in sensor.extra_state_attributes
    assert "active_errors" not in sensor.extra_state_attributes
