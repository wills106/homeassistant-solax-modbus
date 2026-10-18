"""SolaX X3-NEO-LV Modbus plugin.

Built from the vendor document:
    "Solax Power Energy Storage Inverter - MODBUS RTU Communication protocols"
    Version: 1.30 (valid for: X3-NEO-LV)

Scope of this file (intentional, see notes below):
  * SENSOR_TYPES: full coverage of section 3.3 (real-time data, function code 0x04)
    plus the most useful read-only diagnostic sensors from section 3.4
    (configuration parameters, function code 0x03 - READ ONLY here).
  * NUMBER_TYPES / SELECT_TYPES / SWITCH_TYPES / BUTTON_TYPES are intentionally
    left EMPTY in this version. Writing to this inverter's holding registers
    (work mode, charge/discharge limits, protection thresholds, ...) is only
    added once we have a verified, working reference example of those entity
    description classes from this same integration codebase (plugin_solax_lv.py
    only ever fills those lists with []). Guessing the field names for writable
    entities risks sending wrong data to real hardware - not done here.

Verified against a real register dump from the target inverter (2026-09-05):
  * 0x0000-0x0002 (input) = 2304/2322/2338 -> GridA/B/CVoltage 230.4/232.2/233.8V
    matches doc exactly.
  * 0x002C-0x002E (input) RTC Lo/Hi byte pairs decode to 2026-09-05 11:36:55,
    which matches the real date/time this file was produced - confirms the
    Lo=first-named-field / Hi=second-named-field byte order from the doc.
  * 32-bit "Total" energy registers (e.g. ConsumEnergyTotal 0x006F-0x0070)
    only make sense with word order "big" (first/lower register = most
    significant word) - NOT "little" as used by the unrelated plugin_solax_lv.py
    GEN2-6 models. This plugin therefore sets order32="big".

If some values still look wrong (e.g. wildly out of range) after installing,
it is likely a small addressing difference between firmware/protocol
revisions the user already flagged as possible ("+/- 1 or 2 registers") -
compare against the live SolaX app and adjust the affected `register=` value.
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.entity import EntityCategory  # type: ignore[attr-defined]  # HA stubs incomplete

from custom_components.solax_modbus.const import (
    REG_HOLDING,
    REG_INPUT,
    REGISTER_S16,
    REGISTER_U16,
    REGISTER_U32,
    SCAN_GROUP_AUTO,
    SCAN_GROUP_FAST,
    SCAN_GROUP_MEDIUM,
    BaseModbusButtonEntityDescription,
    BaseModbusNumberEntityDescription,
    BaseModbusSelectEntityDescription,
    BaseModbusSensorEntityDescription,
    BaseModbusSwitchEntityDescription,
    BaseModbusTimeEntityDescription,
    plugin_base,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Guard for cumulative 32-bit energy counters (e.g. PV Energy Yield Total).
#
# Several Modbus masters talking to one gateway can produce garbled frames that
# still decode as a valid-looking (but absurd) 32-bit counter value. Home
# Assistant would record such a jump as real energy (total_increasing), which
# permanently inflates the Energy dashboard. The guard keeps the last accepted
# value whenever a counter decreases or grows faster than physically possible.
# A new baseline is accepted only after several consecutive, mutually
# consistent reads (so a genuine counter reset, or a bad first read after a
# restart, can never leave the sensor stuck).
# ---------------------------------------------------------------------------
_ALWAYS_AWAKE = True  # set to False to restore the original run_mode based isAwake()
_ENERGY_GUARD_MAX_KW = 40.0  # fastest plausible energy rate; far above the 12 kW inverter
_ENERGY_GUARD_SLACK_KWH = 1.0  # tolerance added on top of the rate-based limit
_ENERGY_GUARD_CONFIRM_READS = 3  # consistent reads needed to adopt a new baseline


def _energy_counter_guard(state: dict[str, Any], key: str, raw: int, scale: float, now: float) -> int:
    """Return the raw counter value to use (the input, or the last accepted one)."""
    entry = state.get(key)
    if entry is None:
        state[key] = {"raw": raw, "t": now, "cand": None, "cand_t": now, "cand_n": 0}
        return raw

    last_raw: int = entry["raw"]
    allowed = (_ENERGY_GUARD_SLACK_KWH + _ENERGY_GUARD_MAX_KW * max(now - entry["t"], 0.0) / 3600.0) / scale
    if last_raw <= raw <= last_raw + allowed:
        entry.update(raw=raw, t=now, cand=None, cand_n=0)
        return raw

    # Suspicious value: decreased, or grew faster than physically possible.
    cand = entry["cand"]
    cand_allowed = (_ENERGY_GUARD_SLACK_KWH + _ENERGY_GUARD_MAX_KW * max(now - entry["cand_t"], 0.0) / 3600.0) / scale
    if cand is not None and cand <= raw <= cand + cand_allowed:
        entry["cand"], entry["cand_t"] = raw, now
        entry["cand_n"] += 1
    else:
        entry["cand"], entry["cand_t"], entry["cand_n"] = raw, now, 1

    if entry["cand_n"] >= _ENERGY_GUARD_CONFIRM_READS:
        _LOGGER.warning("Energy counter %s: adopting new baseline %s after %s consistent reads (was %s)", key, raw, entry["cand_n"], last_raw)
        entry.update(raw=raw, t=now, cand=None, cand_n=0)
        return raw

    if entry["cand_n"] == 1:
        _LOGGER.warning("Energy counter %s: ignoring implausible value %s (last accepted %s)", key, raw, last_raw)
    return last_raw


# =====================================================================================
# This plugin targets exactly one product line (X3-NEO-LV), so unlike
# plugin_solax_lv.py there is no need for the multi-generation GEN/X1/X3/...
# bitmask matching system. All entities simply use the default allowedtypes=0,
# which the framework treats as "always matches" (see matchInverterWithMask below).
# =====================================================================================


@dataclass(kw_only=True, frozen=True)
class SolaxNeoLVButtonEntityDescription(BaseModbusButtonEntityDescription):
    pass


@dataclass(kw_only=True, frozen=True)
class SolaxNeoLVNumberEntityDescription(BaseModbusNumberEntityDescription):
    # BaseModbusNumberEntityDescription defaults register_data_type to None,
    # which left the hub unable to decode the raw register (no error, just an
    # empty/"unknown" entity). All our registers are plain 16-bit values unless
    # overridden per-entry (see the two signed entries in NUMBER_TYPES).
    register_data_type: str = REGISTER_U16


@dataclass(kw_only=True, frozen=True)
class SolaxNeoLVSelectEntityDescription(BaseModbusSelectEntityDescription):
    # Same missing-default issue as Number above.
    register_data_type: str = REGISTER_U16


@dataclass(kw_only=True, frozen=True)
class SolaxNeoLVSensorEntityDescription(BaseModbusSensorEntityDescription):
    register_data_type: str = REGISTER_U16
    register_type: int = REG_INPUT


@dataclass(kw_only=True, frozen=True)
class SolaxNeoLVSwitchEntityDescription(BaseModbusSwitchEntityDescription):
    pass


@dataclass(kw_only=True, frozen=True)
class SolaxNeoLVTimeEntityDescription(BaseModbusTimeEntityDescription):
    pass


# ====================================== small helper value-functions ================


def _byte_lo(initval: int, descr: Any, datadict: dict[str, Any]) -> int:
    """Extract the low byte of a 16-bit register (doc: 'Uint8(Lo)', first-named field)."""
    return int(initval) & 0xFF


def _byte_hi(initval: int, descr: Any, datadict: dict[str, Any]) -> int:
    """Extract the high byte of a 16-bit register (doc: 'Uint8(Hi)', second-named field)."""
    return (int(initval) >> 8) & 0xFF


_BATTERY_STATUS_MAP = {
    0: "Discharge Self-Test",
    1: "Standby",
    2: "Discharge Precharge",
    3: "Charging to Discharging Precharge",
    4: "Discharging",
    5: "Discharging Fault",
    6: "Charging Transition Current Limit",
    7: "Charge Self-Test",
    8: "Charge Precharge",
    9: "Charging",
    10: "Charging Fault",
    11: "Shutdown",
}


def _value_function_battery_status(initval: int, descr: Any, datadict: dict[str, Any]) -> str:
    hi = (int(initval) >> 8) & 0xFF
    return _BATTERY_STATUS_MAP.get(hi, f"Unknown ({hi})")


def _value_function_bms_comm_status(initval: int, descr: Any, datadict: dict[str, Any]) -> str:
    lo = int(initval) & 0xFF
    return {0: "Disconnected", 1: "Connected"}.get(lo, f"Unknown ({lo})")


_RUN_MODE_MAP = {
    0: "WaitMode",
    1: "CheckMode",
    2: "NormalMode",
    3: "FaultMode",
    4: "UpdateMode",
    5: "EPS check mode",
    6: "EPS mode",
    7: "GEN Check",
    8: "GEN Mode",
    9: "IdleMode",
    10: "StandbyMode",
    11: "EPS Wait",
    12: "Force Wakeup",
}

_MACHINE_POWER_TYPE_MAP = {
    1: "5kW",
    2: "8kW",
    3: "10kW",
    4: "12kW",
    5: "15kW",
    6: "20kW",
}

_SAFETY_CODE_MAP = {
    0: "G99",
    1: "VDE4105",
    2: "Ukraine",
    3: "Israel",
    4: "EN50549",
    5: "G98",
    6: "Vietnam",
    7: "IEC61727",
    8: "Poland",
    9: "PAKISTAN",
    10: "C10-11",
    11: "MEAThailand",
    12: "PEAThailand",
    35: "Cyprus",
    63: "User-Define-50Hz",
    64: "User-Define-60Hz",
    65: "Sri Lanka",
    66: "UZBEKISTAN",
    67: "MALAYSIA",
    68: "Lebanon",
    69: "Syria",
    74: "NRS097",
    87: "Armenia",
}

_COUNTRY_TYPE_MAP = {
    0xB5: "Armenia",
    0xAD: "Belgium",
    0xA8: "Bulgaria",
    0xAF: "Cyprus",
    0xAA: "Hungary",
    0xB2: "Iraq",
    0xB0: "Israel",
    0xA5: "Jordan",
    0xB4: "Lebanon",
    0xB1: "Malaysia",
    0xA6: "Myanmar",
    0xF0: "Others",
    0xA0: "Pakistan",
    0xAC: "Philippines",
    0xA7: "Poland",
    0xAB: "SaudiArabia",
    0xA1: "SouthAfrica",
    0xA9: "Sri Lanka",
    0xB6: "Syria",
    0xB3: "Thailand",
    0xA4: "UK",
    0xA2: "Ukraine",
    0xAE: "UZBEKISTAN",
    0xA3: "Vietnam",
}

_ENABLE_DISABLE_MAP = {0xA0: "Disable", 0xA1: "Enable"}
_ON_OFF_MAP = {0xA0: "Off", 0xA1: "On"}
_WORKMODE_MAP = {
    0xA0: "Self Use",
    0xA1: "Back Up Mode",
    0xA2: "Manual",
    0xA3: "Peak Shaving",
    0xA4: "Feed in",
    0xB0: "SUB",
    0xB1: "SBU",
    0xB2: "MKS",
    0xB3: "Force Time Use",
}
_BATTERY_TYPE_MAP = {0xA0: "Lead-acid", 0xA1: "Li-ion", 0xA2: "No Battery"}
_METER_CT_MAP = {
    0xA0: "None",
    0xA1: "CT",
    0xA2: "Meter",
    0xA3: "Meter-WiBr",
    0xA4: "Meter-Dual",
    0xA5: "Meter-Dual-WiBr",
}
_BATTERY_CHARGE_SOURCE_MAP = {
    0xA0: "Only PV",
    0xA1: "Only Grid",
    0xA2: "PV Then Grid",
    0xA3: "PV + Grid",
}
_LANGUAGE_MAP = {0: "English", 1: "Polish"}


def _value_function_error_word(initval: int, descr: Any, datadict: dict[str, Any]) -> int:
    """Raw error-code word; kept as a plain integer bitmask sensor.

    Splitting this into individual named binary_sensors per bit (per section
    3.3.1.2-3.3.1.4 of the doc) can be done later via HA template
    binary_sensors on top of this raw value - keeps this plugin simple and
    avoids guessing an unverified 64-bit register_data_type.
    """
    return int(initval)


# ================================= Sensor Declarations (function code 0x04 / input) ===

SENSOR_TYPES_MAIN: list[SolaxNeoLVSensorEntityDescription] = [
    # ---------------------------------------------------------------------------
    # 3.3.3 Get Inverter-Grid Port Info
    # ---------------------------------------------------------------------------
    SolaxNeoLVSensorEntityDescription(
        name="Grid A Voltage",
        key="grid_a_voltage",
        register=0x0000,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid B Voltage",
        key="grid_b_voltage",
        register=0x0001,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid C Voltage",
        key="grid_c_voltage",
        register=0x0002,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid A Current",
        key="grid_a_current",
        register=0x0003,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid B Current",
        key="grid_b_current",
        register=0x0004,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid C Current",
        key="grid_c_current",
        register=0x0005,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        register=0x0006,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid Power Factor",
        key="grid_power_factor",
        register=0x0007,
        register_data_type=REGISTER_S16,
        scale=0.01,
        rounding=2,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid A Power",
        key="grid_a_power",
        register=0x0008,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid B Power",
        key="grid_b_power",
        register=0x0009,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid C Power",
        key="grid_c_power",
        register=0x000A,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Grid Power Total",
        key="grid_power_total",
        register=0x000B,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ---------------------------------------------------------------------------
    # 3.3.2 Get Inverter-PV Port Info
    # ---------------------------------------------------------------------------
    SolaxNeoLVSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        register=0x000C,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        register=0x000D,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        register=0x000E,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        register=0x000F,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        register=0x0010,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        register=0x0011,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ---------------------------------------------------------------------------
    # 3.3.1 Get Inverter Status
    # ---------------------------------------------------------------------------
    SolaxNeoLVSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x0012,
        scale=_RUN_MODE_MAP,
        icon="mdi:run",
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        register=0x002A,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Radiator Temperature",
        key="radiator_temperature",
        register=0x002B,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="RTC Year/Month",
        key="rtc_year_month",
        register=0x002C,
        scale=lambda v, d, dd: f"20{int(v) & 0xFF:02d}-{(int(v) >> 8) & 0xFF:02d}",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="RTC Day/Hour",
        key="rtc_day_hour",
        register=0x002D,
        scale=lambda v, d, dd: f"{int(v) & 0xFF:02d} {(int(v) >> 8) & 0xFF:02d}h",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="RTC Minute/Second",
        key="rtc_minute_second",
        register=0x002E,
        scale=lambda v, d, dd: f"{int(v) & 0xFF:02d}:{(int(v) >> 8) & 0xFF:02d}",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Machine Power Type",
        key="machine_power_type",
        register=0x0038,
        scale=_MACHINE_POWER_TYPE_MAP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter Error Code Word 0",
        key="inverter_error_code_word0",
        register=0x003C,
        scale=_value_function_error_word,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter Error Code Word 1",
        key="inverter_error_code_word1",
        register=0x003D,
        scale=_value_function_error_word,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter Error Code Word 2",
        key="inverter_error_code_word2",
        register=0x003E,
        scale=_value_function_error_word,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter Error Code Word 3",
        key="inverter_error_code_word3",
        register=0x003F,
        scale=_value_function_error_word,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Manager Error Code Word 0",
        key="manager_error_code_word0",
        register=0x0040,
        scale=_value_function_error_word,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Manager Error Code Word 1",
        key="manager_error_code_word1",
        register=0x0041,
        scale=_value_function_error_word,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
    ),
    SolaxNeoLVSensorEntityDescription(
        name="BMS Error Code Word 0",
        key="bms_error_code_word0",
        register=0x0042,
        scale=_value_function_error_word,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
    ),
    SolaxNeoLVSensorEntityDescription(
        name="BMS Error Code Word 1",
        key="bms_error_code_word1",
        register=0x0043,
        scale=_value_function_error_word,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
    ),
    # ---------------------------------------------------------------------------
    # 3.3.6 Get Inverter-EPS Port Info
    # ---------------------------------------------------------------------------
    SolaxNeoLVSensorEntityDescription(
        name="EPS A Voltage",
        key="eps_a_voltage",
        register=0x0013,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS B Voltage",
        key="eps_b_voltage",
        register=0x0014,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS C Voltage",
        key="eps_c_voltage",
        register=0x0015,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS A Current",
        key="eps_a_current",
        register=0x0016,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS B Current",
        key="eps_b_current",
        register=0x0017,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS C Current",
        key="eps_c_current",
        register=0x0018,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS Frequency",
        key="eps_frequency",
        register=0x0019,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS A Power",
        key="eps_a_power",
        register=0x001A,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS B Power",
        key="eps_b_power",
        register=0x001B,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS C Power",
        key="eps_c_power",
        register=0x001C,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS A Apparent Power",
        key="eps_a_power_s",
        register=0x001D,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS B Apparent Power",
        key="eps_b_power_s",
        register=0x001E,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS C Apparent Power",
        key="eps_c_power_s",
        register=0x001F,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---------------------------------------------------------------------------
    # 3.3.7 Get Inverter-Output Info
    # ---------------------------------------------------------------------------
    SolaxNeoLVSensorEntityDescription(
        name="Inverter A Voltage",
        key="inv_a_voltage",
        register=0x002F,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter B Voltage",
        key="inv_b_voltage",
        register=0x0030,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter C Voltage",
        key="inv_c_voltage",
        register=0x0031,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter A Current",
        key="inv_a_current",
        register=0x0032,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter B Current",
        key="inv_b_current",
        register=0x0033,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter C Current",
        key="inv_c_current",
        register=0x0034,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter Power Total",
        key="inverter_power",
        register=0x0039,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter A Frequency",
        key="inv_a_freq",
        register=0x0098,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter B Frequency",
        key="inv_b_freq",
        register=0x0099,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter C Frequency",
        key="inv_c_freq",
        register=0x009A,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter Power Factor",
        key="inv_power_factor",
        register=0x009B,
        register_data_type=REGISTER_S16,
        scale=0.01,
        rounding=2,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter A Power",
        key="inv_a_power",
        register=0x009C,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter B Power",
        key="inv_b_power",
        register=0x009D,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter C Power",
        key="inv_c_power",
        register=0x009E,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter Reactive Power Total",
        key="inv_reactive_power_total",
        register=0x009F,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter A Apparent Power",
        key="inv_a_apparent_power",
        register=0x00A0,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter B Apparent Power",
        key="inv_b_apparent_power",
        register=0x00A1,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter C Apparent Power",
        key="inv_c_apparent_power",
        register=0x00A2,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---------------------------------------------------------------------------
    # 3.3.8 Get Inverter-Generator Port Info
    # ---------------------------------------------------------------------------
    SolaxNeoLVSensorEntityDescription(
        name="Generator A Voltage",
        key="gen_a_voltage",
        register=0x0035,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator B Voltage",
        key="gen_b_voltage",
        register=0x0036,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator C Voltage",
        key="gen_c_voltage",
        register=0x0037,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator A Current",
        key="gen_a_current",
        register=0x0044,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator B Current",
        key="gen_b_current",
        register=0x0045,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator C Current",
        key="gen_c_current",
        register=0x0046,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator Frequency",
        key="gen_frequency",
        register=0x00A6,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator Power Factor",
        key="gen_power_factor",
        register=0x00A7,
        register_data_type=REGISTER_S16,
        scale=0.01,
        rounding=2,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator A Power",
        key="gen_a_power",
        register=0x00A8,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator B Power",
        key="gen_b_power",
        register=0x00A9,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator C Power",
        key="gen_c_power",
        register=0x00AA,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator Power Total",
        key="gen_power_total",
        register=0x00AB,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Generator Reactive Power Total",
        key="gen_reactive_power_total",
        register=0x00AC,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---------------------------------------------------------------------------
    # 3.3.4 Get Inverter-Battery Port Info
    # ---------------------------------------------------------------------------
    SolaxNeoLVSensorEntityDescription(
        name="Battery Status",
        key="battery_status",
        register=0x0079,
        scale=lambda v, d, dd: f"{_value_function_bms_comm_status(v, d, dd)} / {_value_function_battery_status(v, d, dd)}",
        icon="mdi:battery-sync",
    ),
    SolaxNeoLVSensorEntityDescription(
        name="BMS Battery Voltage",
        key="bms_bat_voltage",
        register=0x007A,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="BMS Battery Current",
        key="bms_bat_current",
        register=0x007B,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="BMS Battery Power",
        key="bms_bat_power",
        register=0x007C,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery SOC",
        key="battery_soc",
        register=0x007D,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Temperature",
        key="battery_temperature",
        register=0x007F,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery NTC Temperature",
        key="battery_ntc_temperature",
        register=0x0080,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Charge Cut-off Voltage",
        key="battery_charge_cut_voltage",
        register=0x0082,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Discharge Cut-off Voltage",
        key="battery_discharge_cut_voltage",
        register=0x0083,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="BMS Charge Max Current",
        key="bms_charge_max_current",
        register=0x0084,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="BMS Discharge Max Current",
        key="bms_discharge_max_current",
        register=0x0085,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Cell Temperature High",
        key="battery_cell_temperature_high",
        register=0x0086,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Cell Temperature Low",
        key="battery_cell_temperature_low",
        register=0x0087,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Health",
        key="battery_health",
        register=0x008A,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:heart-pulse",
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Energy Throughput",
        key="battery_energy_throughput",
        register=0x008B,
        register_data_type=REGISTER_U32,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Voltage (Inverter Sampled)",
        key="bat_voltage_inv",
        register=0x00A3,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Current (Inverter Sampled)",
        key="bat_current_inv",
        register=0x00A4,
        register_data_type=REGISTER_S16,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Power (Inverter Sampled)",
        key="bat_power_inv",
        register=0x00A5,
        register_data_type=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ---------------------------------------------------------------------------
    # 3.3.5 Get Inverter History Data
    # NOTE: word order for these 32-bit "Total" counters is "big" - verified
    # against a real dump (see module docstring). plugin_instance below sets
    # order32="big" as the default for the whole plugin.
    # ---------------------------------------------------------------------------
    SolaxNeoLVSensorEntityDescription(
        name="On-Grid Output Yield Total",
        key="ongrid_output_yield_total",
        register=0x005B,
        register_data_type=REGISTER_U32,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="On-Grid Output Yield Today",
        key="ongrid_output_yield_today",
        register=0x005D,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="On-Grid Input Yield Total",
        key="ongrid_input_yield_total",
        register=0x005E,
        register_data_type=REGISTER_U32,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="On-Grid Input Yield Today",
        key="ongrid_input_yield_today",
        register=0x0060,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Discharge Yield Total",
        key="bat_discharge_yield_total",
        register=0x0061,
        register_data_type=REGISTER_U32,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Charge Yield Total",
        key="bat_charge_yield_total",
        register=0x0063,
        register_data_type=REGISTER_U32,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Discharge Yield Today",
        key="bat_discharge_yield_today",
        register=0x0065,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Battery Charge Yield Today",
        key="bat_charge_yield_today",
        register=0x0066,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="PV Energy Yield Total",
        key="pv_energy_yield_total",
        register=0x0067,
        register_data_type=REGISTER_U32,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="PV Energy Yield Today",
        key="pv_energy_yield_today",
        register=0x0069,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS (Off-Grid) Yield Total",
        key="eps_yield_total",
        register=0x006A,
        register_data_type=REGISTER_U32,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS (Off-Grid) Yield Today",
        key="eps_yield_today",
        register=0x006C,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Feed-in Energy Total",
        key="feedin_energy_total",
        register=0x006D,
        register_data_type=REGISTER_U32,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Consumed Energy Total",
        key="consumed_energy_total",
        register=0x006F,
        register_data_type=REGISTER_U32,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Feed-in Energy Today",
        key="feedin_energy_today",
        register=0x0071,
        register_data_type=REGISTER_U32,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Consumed Energy Today",
        key="consumed_energy_today",
        register=0x0073,
        register_data_type=REGISTER_U32,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    # ---------------------------------------------------------------------------
    # 3.2.1 Get Inverter Firmware Info (function code 0x03 - holding, read only)
    # ---------------------------------------------------------------------------
    SolaxNeoLVSensorEntityDescription(
        name="Inverter Master (DSP) Version",
        key="fw_inverter_master_version",
        register=0x0010,
        register_type=REG_HOLDING,
        scale=0.01,
        rounding=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Inverter Slave (DSP) Version",
        key="fw_inverter_slave_version",
        register=0x0012,
        register_type=REG_HOLDING,
        scale=0.01,
        rounding=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="BMS Master Version",
        key="fw_bms_master_version",
        register=0x0014,
        register_type=REG_HOLDING,
        scale=0.01,
        rounding=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Manager (ARM) Firmware Version",
        key="fw_manager_version",
        register=0x0015,
        register_type=REG_HOLDING,
        scale=0.01,
        rounding=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Hardware Version",
        key="fw_hardware_version",
        register=0x0017,
        register_type=REG_HOLDING,
        scale=0.01,
        rounding=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---------------------------------------------------------------------------
    # 3.4.1 / 3.4.4 - configuration parameters that have NO number/select
    # counterpart (they share a register byte-packed with another value, so no
    # writable entity was created for them - see NUMBER_TYPES/SELECT_TYPES
    # comments below). Every other former "cfg_*" read-only sensor was removed
    # here on purpose: the corresponding number/select entity already reads AND
    # displays the live register value, so keeping a duplicate sensor for the
    # same address only caused UI clutter and the "unknown" state the user hit.
    # ---------------------------------------------------------------------------
    SolaxNeoLVSensorEntityDescription(
        name="ISO Enable",
        key="cfg_iso_enable",
        register=0x0054,
        register_type=REG_HOLDING,
        scale=_byte_lo,
        entity_category=EntityCategory.DIAGNOSTIC,
        internal=True,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Min SOC",
        key="cfg_min_soc",
        register=0x0055,
        register_type=REG_HOLDING,
        scale=_byte_lo,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="EPS Auto Recover SOC",
        key="cfg_eps_auto_recover_soc",
        register=0x0056,
        register_type=REG_HOLDING,
        scale=_byte_hi,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        internal=True,
    ),
    SolaxNeoLVSensorEntityDescription(
        name="Alarm SOC",
        key="cfg_alarm_soc",
        register=0x0057,
        register_type=REG_HOLDING,
        scale=_byte_hi,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        internal=True,
    ),
]

# ================================= Empty lists (see module docstring) ===============


BUTTON_TYPES: Sequence["SolaxNeoLVButtonEntityDescription"] = []
SWITCH_TYPES: Sequence["SolaxNeoLVSwitchEntityDescription"] = []
TIME_TYPES: Sequence["SolaxNeoLVTimeEntityDescription"] = []

# BUTTON_TYPES (0x0049 RestoreFactorySetting, 0x004B ResetErrorLog) and SWITCH_TYPES
# are intentionally left empty: no confirmed working example of those two entity
# description classes was found anywhere in this codebase to copy the exact field
# names from, and RestoreFactorySetting performs a full factory reset (wipes energy
# counters and error logs) - not something to expose on a guess. Binary
# Enable/Disable and On/Off registers are implemented as SELECT entities below
# instead, which matches this repo's own historical convention for such registers.

# =====================================================================================
# Table of Enable/Disable-style register values, reused across several SELECT_TYPES
# =====================================================================================
_EN_DIS = {0xA0: "Disable", 0xA1: "Enable"}
_ON_OFF_SEL = {0xA0: "Off", 0xA1: "On"}
_CHARGE_SOURCE_SEL = {
    0xA0: "Only PV",
    0xA1: "Only Grid",
    0xA2: "PV Then Grid",
    0xA3: "PV + Grid",
}

# =====================================================================================
# NUMBER_TYPES - all writable, whole-register (not byte-packed) numeric parameters
# from section 3.4 of the doc. EEPROM write-limit registers (marked with a Star in
# the doc) are noted per entry; avoid automations that write these on every poll.
# =====================================================================================
NUMBER_TYPES: Sequence["SolaxNeoLVNumberEntityDescription"] = [
    # ---- 3.4.1 Basic Parameters ----
    # NOTE: UserPassward (0x0003) and Newpassword (0x0006) are deliberately NOT
    # exposed as entities, for the same reason neither plugin_solax.py nor
    # plugin_solax_lv.py expose them anywhere in this repo either: they gate the
    # inverter's local lock-code, and there's no good reason to make that
    # read/writable from Home Assistant. If you ever need to change the PIN,
    # do it from the inverter's own screen/app.
    # ---- 3.4.2 Work Mode Parameters ----
    SolaxNeoLVNumberEntityDescription(
        name="Return To Utility Volt",
        key="return_to_utility_volt",
        register=0x0065,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Return To Battery Volt",
        key="return_to_battery_volt",
        register=0x0066,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Return To Utility SOC",
        key="return_to_utility_soc",
        register=0x0067,
        fmt="i",
        native_min_value=10,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Return To Battery SOC",
        key="return_to_battery_soc",
        register=0x0068,
        fmt="i",
        native_min_value=50,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=0,
    ),
    # ---- 3.4.2.1 Self Use Mode (WorkMode = Self Use) ----
    SolaxNeoLVNumberEntityDescription(
        name="Self Use Min SOC",
        key="self_use_min_soc",
        register=0x008D,
        fmt="i",
        native_min_value=2,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=10,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Self Use Min Volt",
        key="self_use_min_vol",
        register=0x008E,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Self Use Charge Upper SOC",
        key="self_use_charge_upper_soc",
        register=0x0090,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=100,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Self Use Charge Upper Volt",
        key="self_use_charge_upper_vol",
        register=0x0091,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    # ---- 3.4.2.2 Back Up Mode ----
    SolaxNeoLVNumberEntityDescription(
        name="Back Up Min SOC",
        key="back_up_min_soc",
        register=0x0092,
        fmt="i",
        native_min_value=30,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=30,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Back Up Min Volt",
        key="back_up_min_vol",
        register=0x0093,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Back Up Charge Upper SOC",
        key="back_up_charge_upper_soc",
        register=0x0094,
        fmt="i",
        native_min_value=30,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=100,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Back Up Charge Upper Volt",
        key="back_up_charge_upper_vol",
        register=0x0095,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    # ---- 3.4.2.3 Manual Mode ----
    SolaxNeoLVNumberEntityDescription(
        name="Manual Mode Battery Charge/Discharge Power",
        key="manual_charge_discharge_power",
        register=0x003D,
        fmt="i",
        register_data_type=REGISTER_S16,
        native_min_value=-30000,
        native_max_value=30000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        initvalue=0,
    ),
    # ---- 3.4.2.4 Peak Shaving Mode (standalone registers only) ----
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Time A Charge Power Limit",
        key="ps_time_a_charge_power_limit",
        register=0x013F,
        fmt="i",
        native_min_value=0,
        native_max_value=60000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Time A Charge Max SOC",
        key="ps_time_a_charge_max_soc",
        register=0x0140,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=100,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Time A Charge Max Volt",
        key="ps_time_a_charge_max_volt",
        register=0x0141,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Time B Peak Limit",
        key="ps_time_b_peak_limit",
        register=0x0144,
        fmt="i",
        native_min_value=0,
        native_max_value=60000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Time B Charge Max SOC",
        key="ps_time_b_charge_max_soc",
        register=0x0146,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=100,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Time B Charge Max Volt",
        key="ps_time_b_charge_max_volt",
        register=0x0147,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Time D Peak Limit",
        key="ps_time_d_peak_limit",
        register=0x014A,
        fmt="i",
        native_min_value=0,
        native_max_value=60000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Time D Charge Max SOC",
        key="ps_time_d_charge_max_soc",
        register=0x014C,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=100,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Time D Charge Max Volt",
        key="ps_time_d_charge_max_volt",
        register=0x014D,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Reserved Charge SOC",
        key="ps_reserved_charge_soc",
        register=0x014E,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Peak Shaving Reserved Charge Volt",
        key="ps_reserved_charge_volt",
        register=0x014F,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    # ---- 3.4.2.5 Force Time Use Mode (standalone registers only) ----
    SolaxNeoLVNumberEntityDescription(
        name="Battery Stop Discharge Volt",
        key="battery_stop_discharge_volt",
        register=0x0078,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Battery Stop Discharge SOC",
        key="battery_stop_discharge_soc",
        register=0x0079,
        fmt="i",
        native_min_value=5,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=10,
    ),
    # ---- 3.4.2.6 Feed-in Mode (standalone registers only) ----
    SolaxNeoLVNumberEntityDescription(
        name="Feedin Charge SOC",
        key="feedin_charge_soc",
        register=0x0152,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Feedin Charge Volt",
        key="feedin_charge_vol",
        register=0x0153,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Feedin Cutoff SOC",
        key="feedin_cutoff_soc",
        register=0x0158,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=0,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Feedin Cutoff Volt",
        key="feedin_cutoff_vol",
        register=0x0159,
        fmt="i",
        scale=0.1,
        native_min_value=400,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
    ),
    # ---- 3.4.4 Battery System Parameters ----
    SolaxNeoLVNumberEntityDescription(
        name="Battery Rated Capacity (Lead-acid)",
        key="battery_rated_cap",
        register=0x003F,
        fmt="i",
        native_min_value=0,
        native_max_value=10000,
        native_step=1,
        native_unit_of_measurement="Ah",
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Max Charge Current (Grid, Pakistan only)",
        key="max_charge_current_grid",
        register=0x0040,
        fmt="i",
        native_min_value=0,
        native_max_value=350,
        native_step=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Battery Max Charge Current",
        key="battery_max_charge_current",
        register=0x005C,
        fmt="i",
        scale=0.1,
        native_min_value=0,
        native_max_value=3500,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Battery Max Discharge Current",
        key="battery_max_discharge_current",
        register=0x005D,
        fmt="i",
        scale=0.1,
        native_min_value=0,
        native_max_value=3500,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Battery Charge Cutoff Volt",
        key="battery_charge_cutoff_volt",
        register=0x005E,
        fmt="i",
        scale=0.1,
        native_min_value=490,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Battery Discharge Cutoff Volt",
        key="battery_discharge_cutoff_volt",
        register=0x005F,
        fmt="i",
        scale=0.1,
        native_min_value=350,
        native_max_value=520,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Battery Charge Max SOC",
        key="battery_charge_max_soc",
        register=0x007E,
        fmt="i",
        native_min_value=80,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=100,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Force Charge SOC",
        key="force_charge_soc",
        register=0x007F,
        fmt="i",
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=2,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Recover SOC",
        key="recover_soc",
        register=0x0080,
        fmt="i",
        native_min_value=5,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        initvalue=30,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Alarm Volt",
        key="alarm_vol",
        register=0x0083,
        fmt="i",
        scale=0.1,
        native_min_value=390,
        native_max_value=530,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Float Charge Volt",
        key="float_vol",
        register=0x0085,
        fmt="i",
        scale=0.1,
        native_min_value=490,
        native_max_value=600,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    # ---- 3.4.7 Grid Port Parameters ----
    SolaxNeoLVNumberEntityDescription(
        name="Grid Voltage 10min Protect",
        key="grid_vol_10min_protect",
        register=0x001F,
        fmt="i",
        scale=0.1,
        native_min_value=1150,
        native_max_value=3120,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Max 1",
        key="vol_protect_max1",
        register=0x0020,
        fmt="i",
        scale=0.1,
        native_min_value=1150,
        native_max_value=3120,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Max 2",
        key="vol_protect_max2",
        register=0x0021,
        fmt="i",
        scale=0.1,
        native_min_value=1150,
        native_max_value=3120,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Max 3",
        key="vol_protect_max3",
        register=0x0022,
        fmt="i",
        scale=0.1,
        native_min_value=1150,
        native_max_value=3120,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Min 1",
        key="vol_protect_min1",
        register=0x0023,
        fmt="i",
        scale=0.1,
        native_min_value=0,
        native_max_value=3120,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Min 2",
        key="vol_protect_min2",
        register=0x0024,
        fmt="i",
        scale=0.1,
        native_min_value=0,
        native_max_value=3120,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Min 3",
        key="vol_protect_min3",
        register=0x0025,
        fmt="i",
        scale=0.1,
        native_min_value=0,
        native_max_value=3120,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Max 1 Time",
        key="vol_protect_max1_time",
        register=0x0026,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Max 2 Time",
        key="vol_protect_max2_time",
        register=0x0027,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Max 3 Time",
        key="vol_protect_max3_time",
        register=0x0028,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Min 1 Time",
        key="vol_protect_min1_time",
        register=0x0029,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Min 2 Time",
        key="vol_protect_min2_time",
        register=0x002A,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Protect Min 3 Time",
        key="vol_protect_min3_time",
        register=0x002B,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Max 1",
        key="freq_protect_max1",
        register=0x002C,
        fmt="i",
        scale=0.01,
        native_min_value=40.0,
        native_max_value=75.0,
        native_step=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Max 2",
        key="freq_protect_max2",
        register=0x002D,
        fmt="i",
        scale=0.01,
        native_min_value=40.0,
        native_max_value=75.0,
        native_step=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Max 3",
        key="freq_protect_max3",
        register=0x002E,
        fmt="i",
        scale=0.01,
        native_min_value=40.0,
        native_max_value=75.0,
        native_step=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Min 1",
        key="freq_protect_min1",
        register=0x002F,
        fmt="i",
        scale=0.01,
        native_min_value=40.0,
        native_max_value=75.0,
        native_step=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Min 2",
        key="freq_protect_min2",
        register=0x0030,
        fmt="i",
        scale=0.01,
        native_min_value=40.0,
        native_max_value=75.0,
        native_step=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Min 3",
        key="freq_protect_min3",
        register=0x0031,
        fmt="i",
        scale=0.01,
        native_min_value=40.0,
        native_max_value=75.0,
        native_step=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Max 1 Time",
        key="freq_protect_max1_time",
        register=0x0032,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Max 2 Time",
        key="freq_protect_max2_time",
        register=0x0033,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Max 3 Time",
        key="freq_protect_max3_time",
        register=0x0034,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Min 1 Time",
        key="freq_protect_min1_time",
        register=0x0035,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Min 2 Time",
        key="freq_protect_min2_time",
        register=0x0036,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Protect Min 3 Time",
        key="freq_protect_min3_time",
        register=0x0037,
        fmt="i",
        native_min_value=1,
        native_max_value=65500,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Recovery Max",
        key="vol_recovery_max",
        register=0x0038,
        fmt="i",
        scale=0.1,
        native_min_value=2300,
        native_max_value=2760,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Vol Recovery Min",
        key="vol_recovery_min",
        register=0x0039,
        fmt="i",
        scale=0.1,
        native_min_value=1150,
        native_max_value=2300,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Recovery Max",
        key="freq_recovery_max",
        register=0x003A,
        fmt="i",
        scale=0.01,
        native_min_value=40.0,
        native_max_value=75.0,
        native_step=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Freq Recovery Min",
        key="freq_recovery_min",
        register=0x003B,
        fmt="i",
        scale=0.01,
        native_min_value=40.0,
        native_max_value=75.0,
        native_step=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Reconnection Time",
        key="reconnection_time",
        register=0x003C,
        fmt="i",
        native_min_value=30,
        native_max_value=1000,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        initvalue=30,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="Export Limit",
        key="export_limit",
        register=0x004D,
        fmt="i",
        scale=10,
        native_min_value=0,
        native_max_value=30000,
        native_step=10,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        initvalue=0,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVNumberEntityDescription(
        name="PF Setting",
        key="pf_setting_pf",
        register=0x004E,
        fmt="i",
        register_data_type=REGISTER_S16,
        scale=0.01,
        native_min_value=0.80,
        native_max_value=1.00,
        native_step=0.01,
        initvalue=1,
        entity_category=EntityCategory.CONFIG,
    ),
]

# =====================================================================================
# SELECT_TYPES - enum-valued and Enable/Disable-style writable registers
# =====================================================================================
SELECT_TYPES: Sequence["SolaxNeoLVSelectEntityDescription"] = [
    SolaxNeoLVSelectEntityDescription(
        name="Language",
        key="sel_language",
        register=0x0004,
        option_dict={0: "English", 1: "Polish"},
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Safety Code",
        key="sel_safety_code",
        register=0x0005,
        option_dict=dict(_SAFETY_CODE_MAP),
        entity_category=EntityCategory.CONFIG,
        icon="mdi:shield-check-outline",
    ),
    SolaxNeoLVSelectEntityDescription(
        name="EPS Enable",
        key="sel_eps_enable",
        register=0x003E,
        option_dict=dict(_EN_DIS),
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVSelectEntityDescription(
        name="System Switch",
        key="sel_system_switch",
        register=0x0048,
        option_dict=dict(_ON_OFF_SEL),
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Phase Sequence Detect",
        key="sel_phase_sequence_detect",
        register=0x0058,
        option_dict=dict(_EN_DIS),
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Country Type",
        key="sel_country_type",
        register=0x00C9,
        option_dict=dict(_COUNTRY_TYPE_MAP),
        entity_category=EntityCategory.CONFIG,
        icon="mdi:earth",
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Work Mode",
        key="sel_work_mode",
        register=0x0047,
        option_dict=dict(_WORKMODE_MAP),
        icon="mdi:cog-outline",
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Battery Charge Source (Pakistan only)",
        key="sel_battery_charge_source",
        register=0x0060,
        option_dict=dict(_BATTERY_CHARGE_SOURCE_MAP),
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Battery Type",
        key="sel_battery_type",
        register=0x005B,
        option_dict=dict(_BATTERY_TYPE_MAP),
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Meter/CT Select",
        key="sel_meter_ct_select",
        register=0x0059,
        option_dict=dict(_METER_CT_MAP),
        entity_category=EntityCategory.CONFIG,
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Charge Source V1 (Force Time Use)",
        key="sel_charge_source_v1",
        register=0x006B,
        option_dict=dict(_CHARGE_SOURCE_SEL),
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Charge Source V2 (Force Time Use)",
        key="sel_charge_source_v2",
        register=0x006E,
        option_dict=dict(_CHARGE_SOURCE_SEL),
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Charge Source V3 (Force Time Use)",
        key="sel_charge_source_v3",
        register=0x0071,
        option_dict=dict(_CHARGE_SOURCE_SEL),
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Self Use Charge From Grid Enable",
        key="sel_self_use_charge_from_grid_en",
        register=0x008F,
        option_dict=dict(_EN_DIS),
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Feedin Selling First Enable",
        key="sel_feedin_selling_first_en",
        register=0x0156,
        option_dict=dict(_EN_DIS),
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Feedin Charge From Grid Enable",
        key="sel_feedin_charge_from_grid_en",
        register=0x0157,
        option_dict=dict(_EN_DIS),
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Peak Shaving Time A Charge From Grid Enable",
        key="sel_ps_time_a_charge_from_grid_en",
        register=0x013E,
        option_dict=dict(_EN_DIS),
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Peak Shaving Time B Charge From Grid Enable",
        key="sel_ps_time_b_charge_from_grid_en",
        register=0x0145,
        option_dict=dict(_EN_DIS),
    ),
    SolaxNeoLVSelectEntityDescription(
        name="Peak Shaving Time D Charge From Grid Enable",
        key="sel_ps_time_d_charge_from_grid_en",
        register=0x014B,
        option_dict=dict(_EN_DIS),
    ),
]


# ============================ plugin declaration =====================================


@dataclass(kw_only=True)
class solax_x3_neo_lv_plugin(plugin_base):
    def validate_register_data(self, descr: Any, value: Any, datadict: dict[str, Any]) -> Any:
        """Hook called by the hub for every decoded register value (before scaling).

        Only cumulative 32-bit energy counters are touched; everything else is
        passed through unchanged. Any unexpected problem falls back to the
        original value, so this can never break reading.
        """
        try:
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and getattr(descr, "register_data_type", None) == REGISTER_U32
                and getattr(descr, "device_class", None) == SensorDeviceClass.ENERGY
                and not getattr(descr, "internal", False)
            ):
                scale = descr.scale if isinstance(descr.scale, (int, float)) and descr.scale > 0 else 0.1
                state = self.__dict__.setdefault("_energy_guard_state", {})
                return _energy_counter_guard(state, descr.key, value, float(scale), time.monotonic())
        except Exception:
            _LOGGER.debug("energy counter guard failed for %s - using raw value", getattr(descr, "key", "?"), exc_info=True)
        return value

    def isAwake(self, datadict: dict[str, Any]) -> bool:
        """Consider the inverter awake whenever it isn't sitting in WaitMode."""
        # Modbus keeps answering with System Switch Off and there is no wake-up button,
        # so don't gate writes on run_mode (avoids "cannot wakeup inverter" warning).
        if _ALWAYS_AWAKE:
            return True
        run_mode = datadict.get("run_mode", None)
        return run_mode is not None and run_mode != "WaitMode"

    def wakeupButton(self) -> str | None:
        # No wake-up button is defined for this plugin (no write entities yet).
        return None

    async def async_determineInverterType(self, hub: Any, configdict: dict[str, Any]) -> int:
        """This plugin targets a single product line, so detection just confirms
        the inverter responds and reads the Machine Power Type register (0x0038,
        input) to build a friendly model string. No serial-number-based
        multi-model matching is needed or attempted.
        """
        _LOGGER.info("%s: initializing SolaX X3-NEO-LV plugin", hub.name)
        self.inverter_model = "X3-NEO-LV"

        try:
            power_type_data = await hub.async_read_input_registers(unit=hub._modbus_addr, address=0x0038, count=1)
            if power_type_data is not None and not power_type_data.isError():
                power_kw = _MACHINE_POWER_TYPE_MAP.get(int(power_type_data.registers[0]))
                if power_kw:
                    self.inverter_model = f"X3-NEO-LV {power_kw}"
        except Exception:
            _LOGGER.debug("%s: could not read Machine Power Type register", hub.name, exc_info=True)

        hub.inverter_model = self.inverter_model
        hub._has_local_inverter_model = True

        # The X3-NEO-LV Modbus RTU protocol (V1.30) does not expose a serial
        # number register anywhere in its documented address ranges (checked
        # both input 0x0000-0x00AC and holding 0x0000-0x0159 against a real
        # register dump - no block decodes as ASCII). Leaving hub.seriesnumber
        # unset shows the framework's generic "still unknown" placeholder, so
        # set an explicit, honest string instead of guessing an address.
        hub.seriesnumber = "not available via Modbus (X3-NEO-LV protocol)"

        # Nonzero so the framework treats this as "device found". Since every
        # entity in this file uses the default allowedtypes=0, this specific
        # value is otherwise unused (see matchInverterWithMask below).
        return 1

    def matchInverterWithMask(
        self, inverterspec: int, entitymask: int, serialnumber: str = "not relevant", blacklist: list[str] | None = None
    ) -> bool:
        # Single supported product line -> every entity always matches.
        return True

    def getSoftwareVersion(self, new_data: dict[str, Any]) -> str | None:
        return None

    def getHardwareVersion(self, new_data: dict[str, Any]) -> str | None:
        return None


# =====================================================================================
# Internal "mirror" sensors that make number/select entities actually show a value.
#
# The hub's block-read planner (splitInBlocks in __init__.py) only ever builds its
# Modbus read plan from SENSOR_TYPES - it accesses `descr.register_type` directly,
# a field that simply does not exist on the Number/Select description classes. In
# other words: a number/select entity's own `register` is used ONLY for writing:
# nothing ever polls it for reading. To show the live value, its `key` must also
# exist as a SENSOR_TYPES entry that IS polled - marked `internal=True` so it is
# never created as a visible HA entity (see should_register_be_loaded() and the
# `internal` field docstring in const.py: "internal sensors are used for reading
# data only; used for computed, selects, etc").
#
# Generated automatically from NUMBER_TYPES/SELECT_TYPES so the mirror can never
# drift out of sync with the writable entity it backs.
# =====================================================================================


def _build_internal_mirror_sensors() -> list[SolaxNeoLVSensorEntityDescription]:
    mirrors: list[SolaxNeoLVSensorEntityDescription] = []
    seen_keys: set[str] = set()
    for n in NUMBER_TYPES:
        if n.key in seen_keys:
            continue
        if n.register is None:
            continue
        seen_keys.add(n.key)
        mirrors.append(
            SolaxNeoLVSensorEntityDescription(
                name=f"{n.name} (internal)",
                key=n.key,
                register=n.register,
                register_type=REG_HOLDING,
                register_data_type=n.register_data_type,
                scale=n.scale,
                internal=True,
            )
        )
    for s in SELECT_TYPES:
        if s.key in seen_keys:
            continue
        if s.register is None:
            continue
        seen_keys.add(s.key)
        mirrors.append(
            SolaxNeoLVSensorEntityDescription(
                name=f"{s.name} (internal)",
                key=s.key,
                register=s.register,
                register_type=REG_HOLDING,
                register_data_type=REGISTER_U16,
                # No scale here on purpose: SolaXModbusSelect.current_option looks up
                # the RAW register integer in option_dict (e.g. 0xA0/0xA1), so this
                # mirror must store the unscaled value.
                internal=True,
            )
        )
    return mirrors


SENSOR_TYPES_MAIN.extend(_build_internal_mirror_sensors())


plugin_instance = solax_x3_neo_lv_plugin(
    plugin_name="SolaX",
    plugin_manufacturer="SolaX Power",
    SENSOR_TYPES=SENSOR_TYPES_MAIN,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=SWITCH_TYPES,
    TIME_TYPES=TIME_TYPES,
    block_size=100,
    order32="big",  # verified against real register dump - see module docstring
    auto_block_ignore_readerror=True,
    default_holding_scangroup=SCAN_GROUP_MEDIUM,
    default_input_scangroup=SCAN_GROUP_AUTO,
    auto_default_scangroup=SCAN_GROUP_FAST,
    auto_slow_scangroup=SCAN_GROUP_MEDIUM,
)
