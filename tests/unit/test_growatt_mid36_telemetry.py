"""MID 36KTL3-X Protocol II telemetry through the production decoder."""

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import UnitOfApparentPower

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.plugin_growatt import (
    GEN2,
    GEN3,
    GEN4,
    HYBRID,
    MID_GEN2_TELEMETRY,
    MPPT3,
    MPPT4,
    MPPT8,
    PV,
    SENSOR_TYPES,
    X1,
    X3,
    plugin_instance,
)

MID = GEN2 | PV | X3 | MPPT4


def matching(spec: int = MID) -> list[Any]:
    return [d for d in SENSOR_TYPES if plugin_instance.matchInverterWithMask(spec, d.allowedtypes, "DM1", d.blacklist)]


def decode(description: Any, registers: list[int]) -> Any:
    """Exercise real word order, signedness, validation and scale callbacks."""
    hub: Any = SimpleNamespace(
        plugin=plugin_instance,
        cyclecount=100,
        _name="mid-test",
        _validate_register_func=None,
        inverterPowerKw=36,
        tmpdata_expiry={},
        localsLoaded=True,
    )
    data: dict[str, Any] = {}
    SolaXModbusHub.treat_address(hub, data, registers, 0, description)
    return data[description.key]


@pytest.mark.parametrize(
    ("key", "words", "expected"),
    [
        ("mid_operating_status", [1], "Normal"),
        ("mid_operating_status", [2], "Unknown (2)"),
        ("mid_derating_reason", [0], "No derating"),
        ("mid_derating_reason", [6], "Inverter temperature"),
        ("mid_derating_reason", [8], "Unknown (8)"),
        ("mid_line_voltage_l1_l2", [4116], 411.6),
        ("mid_output_power_limit_readback", [5, 32320], 36000.0),
        ("mid_string_1_current", [24], 2.4),
        ("mid_string_1_current", [65526], -1.0),
        ("mid_string_6_current", [0], 0.0),
        ("mid_string_disconnected_mask", [160], 160),
    ],
)
def test_mid_decode(key: str, words: list[int], expected: Any) -> None:
    assert decode(next(d for d in MID_GEN2_TELEMETRY if d.key == key), words) == expected


@pytest.mark.parametrize("spec", [GEN2 | PV | X3, MID, GEN2 | PV | X3 | MPPT8, GEN3 | HYBRID | X3, GEN4 | HYBRID | X3])
def test_single_temperature_definition(spec: int) -> None:
    descriptions = [d for d in matching(spec) if d.key == "inverter_temperature"]
    assert len(descriptions) == 1
    assert descriptions[0].register == (3093 if spec & GEN4 else 93)
    assert decode(descriptions[0], [672]) == 67.2


def test_no_duplicate_keys_for_mid() -> None:
    keys = [d.key for d in matching()]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("spec", [GEN2 | PV | X3 | MPPT3, GEN2 | PV | X1 | MPPT4, GEN4 | PV | X3 | MPPT4, GEN2 | HYBRID | X3 | MPPT4])
def test_diagnostics_do_not_leak_to_other_maps(spec: int) -> None:
    assert not any(plugin_instance.matchInverterWithMask(spec, d.allowedtypes) for d in MID_GEN2_TELEMETRY)


def test_four_mppts_are_separate_from_total() -> None:
    descriptions = {d.key: d for d in matching()}
    assert [descriptions[f"pv_power_{i}"].register for i in range(1, 5)] == [5, 9, 13, 17]
    powers = [6822, 4324, 68113, 28630]
    decoded = [decode(descriptions[f"pv_power_{i}"], [value >> 16, value & 65535]) for i, value in enumerate(powers, 1)]
    assert sum(decoded) == pytest.approx(decode(descriptions["pv_power_total"], [1, 42353]))
    assert descriptions["grid_power_l1"].native_unit_of_measurement == UnitOfApparentPower.VOLT_AMPERE


def test_energy_counters_keep_protocol_scaling_and_identity() -> None:
    descriptions = {d.key: d for d in matching()}
    for i in range(1, 5):
        daily = descriptions[f"today_s_pv{i}_solar_energy"]
        lifetime = descriptions[f"total_pv{i}_solar_energy"]
        assert daily.register == 59 + (i - 1) * 4
        assert lifetime.register == 61 + (i - 1) * 4
        assert daily.state_class == lifetime.state_class == SensorStateClass.TOTAL_INCREASING
        assert decode(daily, [0, 112]) == 11.2
    # Preserve discrepant device counters; never invent a calibration factor.
    assert decode(descriptions["today_s_power_generation"], [0, 169]) == 16.9
    assert decode(descriptions["total_solar_energy"], [8, 59198]) == 58348.6
