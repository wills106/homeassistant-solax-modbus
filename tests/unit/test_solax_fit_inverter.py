"""Unit tests for the X1-FIT (PRI serial prefix) inverter type.

Covers the Copilot PR review concern about correct entity matching
for FIT inverters, which use FIT = AC | HYBRID as a semantic alias.
"""

from collections.abc import Sequence
from typing import Any, cast

import pytest

from custom_components.solax_modbus.plugin_solax import (
    AC,
    FIT,
    GEN3,
    GEN4,
    HYBRID,
    X1,
    X3,
    SolaXModbusSensorEntityDescription,
)
from custom_components.solax_modbus.plugin_solax import (
    plugin_instance as solax_plugin,
)

# Representative serial number for a real X1-FIT GEN3 device
PRI_SERIAL = "PRI502H9168435"

# FIT inverterspec as the plugin sets it for PRI devices
FIT_INVERTER = FIT | GEN3 | X1

# PV input sensor keys that FIT must NOT expose (no DC MPPT hardware)
PV_SENSOR_KEYS = {
    "pv_voltage_1",
    "pv_voltage_2",
    "pv_current_1",
    "pv_current_2",
    "pv_power_1",
    "pv_power_2",
    "pv_power_total",
}

# Typed view of SENSOR_TYPES so mypy can resolve allowedtypes/blacklist attributes
# (plugin_base declares SENSOR_TYPES as Sequence[SensorEntityDescription], the HA
# base class, which does not carry these extra fields)
SOLAX_SENSOR_TYPES: Sequence[SolaXModbusSensorEntityDescription] = cast(Sequence[SolaXModbusSensorEntityDescription], solax_plugin.SENSOR_TYPES)


# ---------------------------------------------------------------------------
# 1. Type constant sanity
# ---------------------------------------------------------------------------


def test_fit_constant_combines_ac_and_hybrid() -> None:
    """FIT must be the bitwise OR of AC and HYBRID — nothing more, nothing less."""
    assert FIT == AC | HYBRID, f"Expected FIT=={AC | HYBRID:#06x}, got {FIT:#06x}"


def test_fit_has_ac_bit() -> None:
    assert FIT & AC != 0, "FIT must include the AC bit"


def test_fit_has_hybrid_bit() -> None:
    assert FIT & HYBRID != 0, "FIT must include the HYBRID bit"


# ---------------------------------------------------------------------------
# 2. matchInverterWithMask — FIT inverter matching
# ---------------------------------------------------------------------------


def test_fit_matches_hybrid_entity() -> None:
    """A bare allowedtypes=HYBRID entity matches a FIT inverter (HYBRID bit is set)."""
    assert solax_plugin.matchInverterWithMask(FIT_INVERTER, HYBRID) is True


def test_fit_matches_ac_entity() -> None:
    """A bare allowedtypes=AC entity matches a FIT inverter (AC bit is set)."""
    assert solax_plugin.matchInverterWithMask(FIT_INVERTER, AC) is True


def test_fit_matches_hybrid_gen3_entity() -> None:
    """FIT matches HYBRID|GEN3 entities — the core battery/yield register set."""
    assert solax_plugin.matchInverterWithMask(FIT_INVERTER, HYBRID | GEN3) is True


def test_fit_does_not_match_hybrid_gen4_entity() -> None:
    """FIT is GEN3 only; it must not pick up HYBRID|GEN4 entities."""
    assert solax_plugin.matchInverterWithMask(FIT_INVERTER, HYBRID | GEN4) is False


def test_fit_does_not_match_x3_entity() -> None:
    """FIT is a single-phase (X1) device; must not match X3-only entities."""
    assert solax_plugin.matchInverterWithMask(FIT_INVERTER, HYBRID | GEN3 | X3) is False


# ---------------------------------------------------------------------------
# 3. Blacklist — PV sensors excluded for PRI serial
# ---------------------------------------------------------------------------


def test_pv_entity_blocked_by_blacklist_for_pri() -> None:
    """Bare HYBRID PV entities must NOT match when serial starts with PRI."""
    # Without blacklist it would normally match (HYBRID bit is set on FIT)
    assert solax_plugin.matchInverterWithMask(FIT_INVERTER, HYBRID) is True

    # With the blacklist applied, PRI serial must be excluded
    assert solax_plugin.matchInverterWithMask(FIT_INVERTER, HYBRID, PRI_SERIAL, ["PRI"]) is False, (
        "PV entities must be blocked for PRI serial numbers via blacklist"
    )


def test_blacklist_does_not_affect_non_pri_serial() -> None:
    """The blacklist has no effect on regular HYBRID (non-FIT) inverters."""
    hybrid_gen4_x3 = HYBRID | GEN4 | X3
    assert solax_plugin.matchInverterWithMask(hybrid_gen4_x3, HYBRID, "H34T10H1234567", ["PRI"]) is True, (
        "Non-PRI serials must not be blocked by the PRI blacklist"
    )


# ---------------------------------------------------------------------------
# 4. Existing inverter types unaffected by FIT alias
# ---------------------------------------------------------------------------


def test_pure_ac_inverter_still_matches_ac_entities() -> None:
    """Adding FIT must not break matching for genuine AC inverters."""
    ac_inverter = AC | GEN3 | X1
    assert solax_plugin.matchInverterWithMask(ac_inverter, AC | GEN3) is True


def test_pure_hybrid_inverter_still_matches_hybrid_entities() -> None:
    """Adding FIT must not break matching for genuine HYBRID inverters."""
    hybrid_inverter = HYBRID | GEN3 | X1
    assert solax_plugin.matchInverterWithMask(hybrid_inverter, HYBRID | GEN3) is True


def test_pure_ac_inverter_does_not_match_hybrid_entity() -> None:
    """A genuine AC-only inverter (not FIT) must not match HYBRID entities."""
    ac_inverter = AC | GEN3 | X1  # No HYBRID bit — this is a real XAC, not FIT
    assert solax_plugin.matchInverterWithMask(ac_inverter, HYBRID) is False


# ---------------------------------------------------------------------------
# 5. SENSOR_TYPES audit — all PV entities must have PRI blacklist
# ---------------------------------------------------------------------------


def test_all_pv_sensors_blacklist_pri() -> None:
    """Every bare allowedtypes=HYBRID PV sensor must carry blacklist=['PRI'].

    SENSOR_TYPES contains multiple entries per key for different inverter
    generations (e.g. pv_voltage_1 appears with HYBRID, HYBRID|GEN3|GEN4,
    PV|GEN3|GEN4, etc.).  Only the entries with bare allowedtypes=HYBRID
    (no GEN qualifier, no PV type bit) can be incorrectly matched by the
    FIT=AC|HYBRID alias, so those are the ones that need the blacklist.

    This is the key regression guard: if a new bare allowedtypes=HYBRID PV
    entity is added without a blacklist, this test will catch it.
    """
    missing: list[str] = []
    for sensor in SOLAX_SENSOR_TYPES:
        if sensor.key in PV_SENSOR_KEYS and sensor.allowedtypes == HYBRID:
            if sensor.blacklist is None or "PRI" not in sensor.blacklist:
                missing.append(sensor.key)

    assert not missing, f"PV sensor(s) missing blacklist=['PRI'] (FIT has no DC PV inputs): {missing}"


def test_all_pv_sensor_keys_present_in_sensor_types() -> None:
    """Confirm we found all 7 expected PV sensor entities in SENSOR_TYPES."""
    found = {s.key for s in SOLAX_SENSOR_TYPES if s.key in PV_SENSOR_KEYS}
    assert found == PV_SENSOR_KEYS, f"Expected PV sensor keys {PV_SENSOR_KEYS}, found {found}"


# ---------------------------------------------------------------------------
# 6. End-to-end entity matching for a PRI inverter
# ---------------------------------------------------------------------------


def test_pv_sensors_do_not_match_pri_inverter() -> None:
    """PV sensors must not match the FIT inverter when serial starts with PRI."""
    mismatched: list[str] = []
    for sensor in SOLAX_SENSOR_TYPES:
        if sensor.key in PV_SENSOR_KEYS:
            if solax_plugin.matchInverterWithMask(FIT_INVERTER, sensor.allowedtypes, PRI_SERIAL, sensor.blacklist):
                mismatched.append(sensor.key)

    assert not mismatched, f"PV sensor(s) incorrectly matching PRI inverter: {mismatched}"


def test_battery_sensors_match_pri_inverter() -> None:
    """Core battery sensors (HYBRID|GEN3/GEN4) must match the FIT inverter."""
    battery_keys = {
        "battery_capacity",
        "battery_power_charge",
        "battery_voltage_charge",
        "battery_current_charge",
    }
    matched = set()
    for sensor in SOLAX_SENSOR_TYPES:
        if sensor.key in battery_keys:
            if solax_plugin.matchInverterWithMask(FIT_INVERTER, sensor.allowedtypes, PRI_SERIAL, sensor.blacklist):
                matched.add(sensor.key)

    assert matched == battery_keys, f"Battery sensors should match FIT inverter. Missing: {battery_keys - matched}"


# ---------------------------------------------------------------------------
# 7. Serial number detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_determine_inverter_type_pri_serial(mock_hub: Any) -> None:
    """PRI serial prefix must be classified as FIT | GEN3 | X1.

    Registers encode "PRI502H9168435" as 7 big-endian 16-bit values:
      P(0x50) R(0x52) → 0x5052
      I(0x49) 5(0x35) → 0x4935
      0(0x30) 2(0x32) → 0x3032
      H(0x48) 9(0x39) → 0x4839
      1(0x31) 6(0x36) → 0x3136
      8(0x38) 4(0x34) → 0x3834
      3(0x33) 5(0x35) → 0x3335
    """
    mock_registers = [0x5052, 0x4935, 0x3032, 0x4839, 0x3136, 0x3834, 0x3335]
    mock_hub.configure_read(
        1,
        0,
        7,
        type("MockResponse", (), {"registers": mock_registers, "isError": lambda self: False})(),
    )

    config: dict[str, Any] = {"read_eps": False, "read_dcb": False}
    inverter_type = await solax_plugin.async_determineInverterType(mock_hub, config)

    expected = FIT | GEN3 | X1
    assert inverter_type == expected, f"PRI serial should map to FIT|GEN3|X1 ({expected:#06x}), got {inverter_type:#06x}"
