import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
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
from homeassistant.helpers.entity import (  # type: ignore[attr-defined]
    EntityCategory,
)

from custom_components.solax_modbus.const import (
    CONF_READ_DATAHUB,
    CONF_READ_EMS,
    CONF_READ_PM,
    DEFAULT_READ_DATAHUB,
    DEFAULT_READ_EMS,
    DEFAULT_READ_PM,
    REG_HOLDING,
    REG_INPUT,
    REGISTER_S16,
    REGISTER_S32,
    REGISTER_STR,
    REGISTER_U16,
    REGISTER_U32,
    REGISTER_WORDS,
    TIME_OPTIONS_SEPARATE_REGISTERS,
    WRITE_MULTI_MODBUS,
    BaseModbusButtonEntityDescription,
    BaseModbusNumberEntityDescription,
    BaseModbusSelectEntityDescription,
    BaseModbusSensorEntityDescription,
    BaseModbusSwitchEntityDescription,
    BaseModbusTimeEntityDescription,
    plugin_base,
    value_function_disable_enable,
    value_function_enable_disable,
    value_function_firmware_decimal_hundredths,
    value_function_separate_registers_time,
)

from .pymodbus_compat import DataType, convert_from_registers

_LOGGER = logging.getLogger(__name__)


""" ============================================================================================
bitmasks  definitions to characterize inverters, ogranized by group
these bitmasks are used in entitydeclarations to determine to which inverters the entity applies
within a group, the bits in an entitydeclaration will be interpreted as OR
between groups, an AND condition is applied, so all gruoups must match.
An empty group (group without active flags) evaluates to True.
example: GEN1 | X1 | X3 | EPS
means:  any charger of type (GEN1 or GEN2) and (X1 or X3)
An entity can be declared multiple times (with different bitmasks) if the parameters are different for each inverter type
"""

GEN = 0x0001  # base generation for MIC, PV, AC
GEN1 = 0x0001  # = EVC in SolaX naming
GEN2 = 0x0002  # = HAC in SolaX naming
GEN3 = 0x0004
GEN4 = 0x0008
ALL_GEN_GROUP = GEN1 | GEN2 | GEN3 | GEN4 | GEN

X1 = 0x0100
X3 = 0x0200
ALL_X_GROUP = X1 | X3

POW4 = 0x0080
POW7 = 0x0010
POW11 = 0x0020
POW22 = 0x0040
ALL_POW_GROUP = POW4 | POW7 | POW11 | POW22

# Feature flags — set dynamically in async_determineInverterType based on device registers
PARALLEL_TYPE = 0x1000  # device reports Is_support_parallel (0x0107) == 0xAA55 and the Parallel Mode option is on
PM_OPTION_TYPE = 0x2000  # the Parallel Mode option is on, regardless of what 0x0107 reports
EMS_TYPE = 0x4000  # the EMS / V2G option is on
DATAHUB_TYPE = 0x8000  # the Datahub option is on
PM = PARALLEL_TYPE
ALL_FEATURE_GROUP = PARALLEL_TYPE | PM_OPTION_TYPE | EMS_TYPE | DATAHUB_TYPE

ALLDEFAULT = 0  # should be equivalent to GEN1 | GEN2 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES: list[Any] = []

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub: Any, address: int) -> str | None:
    _LOGGER.debug("%s: Reading serial number from address 0x%x", hub.name, address)
    res = None
    try:
        _LOGGER.debug("%s: Attempting to read holding registers at 0x%x, count=7, unit=%s", hub.name, address, hub._modbus_addr)
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=7)
        if not inverter_data.isError():
            _LOGGER.debug("%s: Successfully read registers: %s", hub.name, inverter_data.registers[0:7])
            raw = convert_from_registers(inverter_data.registers[0:7], DataType.STRING, "big")  # type: ignore[attr-defined]  # Dynamic enum aliasing
            _LOGGER.debug("%s: Converted raw data: %s (type: %s)", hub.name, raw, type(raw))
            res = raw.decode("ascii", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            hub.seriesnumber = res
            _LOGGER.debug("%s: Decoded serial number: %s", hub.name, res)
        else:
            _LOGGER.debug("%s: Register read returned error: %s", hub.name, inverter_data)
    except Exception as ex:
        _LOGGER.warning("%s: attempt to read serialnumber failed at 0x%x", hub.name, address, exc_info=True)
        _LOGGER.debug("%s: Exception type: %s, message: %s", hub.name, type(ex).__name__, ex)
    if not res:
        _LOGGER.warning("%s: reading serial number from address 0x%x failed; other address may succeed", hub.name, address)
    _LOGGER.info("Read %s 0x%x serial number before potential swap: %s", hub.name, address, res)
    return res


async def async_read_firmware(hub: Any, address: int = 0x25) -> float | None:
    """Read firmware version from input register.

    Args:
        hub: The modbus hub instance
        address: Register address (default 0x25)

    Returns:
        float: Firmware version (e.g., 7.07) or None on failure
    """
    _LOGGER.debug("%s: Reading firmware version from address 0x%x", hub.name, address)
    res = None
    try:
        _LOGGER.debug("%s: Attempting to read input registers at 0x%x, count=1, unit=%s", hub.name, address, hub._modbus_addr)
        fw_data = await hub.async_read_input_registers(unit=hub._modbus_addr, address=address, count=1)
        if not fw_data.isError():
            fw_raw = fw_data.registers[0]
            res = fw_raw / 100.0  # Decimal hundredths (e.g., 707 → 7.07)
            _LOGGER.debug("%s: Successfully read firmware: raw=%s, version=%.2f", hub.name, fw_raw, res)
        else:
            _LOGGER.debug("%s: Register read returned error: %s", hub.name, fw_data)
    except Exception as ex:
        _LOGGER.warning("%s: attempt to read firmware failed at 0x%x", hub.name, address, exc_info=True)
        _LOGGER.debug("%s: Exception type: %s, message: %s", hub.name, type(ex).__name__, ex)
    if not res:
        _LOGGER.debug("%s: reading firmware from address 0x%x failed", hub.name, address)
    return res


# =================================================================================================


@dataclass(kw_only=True, frozen=True)
class SolaXEVChargerModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass(kw_only=True, frozen=True)
class SolaXEVChargerModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass(kw_only=True, frozen=True)
class SolaXEVChargerModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass(kw_only=True, frozen=True)
class SolaXEVChargerModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    # order16: int = Endian.BIG
    order32: str | None = None  # optional per-sensor 32-bit word order override
    register_data_type: str = REGISTER_U16
    register_type: int = REG_HOLDING


@dataclass(kw_only=True, frozen=True)
class SolaXEVChargerModbusTimeEntityDescription(BaseModbusTimeEntityDescription):
    allowedtypes: int = ALLDEFAULT


# ====================================== Computed value functions  =================================================


def value_function_closed_is_on(initval: Any, descr: Any, datadict: dict[str, Any]) -> int | None:
    """0x0664 stores 0 = Closed / 1 = Open; the switch shows Closed as on."""
    if initval in (0, 1):
        return 1 - int(initval)
    return None


def value_function_rated_current(initval: Any, descr: Any, datadict: dict[str, Any]) -> float | None:
    """Rated charging current of the charger, derived from its power and phase type.

    Used as the ceiling for the current settings: unlike register 0x64F it never
    moves, whereas 0x64F only holds the rated value while no vehicle is connected
    (SolaX support, ticket 703158) and follows Modbus writes during a session.

    Known model ratings map to their nameplate currents (e.g. the 7.2 kW X1 is a
    32 A unit, which watts/(phases*230) would truncate to 31 A); combinations
    without an established nameplate fall back to the derived value.
    """
    phases = 3 if datadict.get("phase_type") == "Three Phase" else 1
    documented: dict[tuple[str, int], int] = {
        ("4.6 kW", 1): 20,
        ("7 kW", 1): 32,
        ("7.6 kW", 1): 32,
        ("9.6 kW", 1): 40,
        ("11.5 kW", 1): 48,
        ("11 kW", 3): 16,
        ("22 kW", 3): 32,
    }
    amps = documented.get((str(datadict.get("power_rating")), phases))
    if amps is not None:
        return float(amps)
    ratings: dict[str, int] = {
        "4.6 kW": 4600,
        "6 kW": 6000,
        "7 kW": 7200,
        "7.6 kW": 7600,
        "9.6 kW": 9600,
        "11 kW": 11000,
        "11.5 kW": 11500,
        "22 kW": 22000,
    }
    watts = ratings.get(str(datadict.get("power_rating")))
    if watts is None:
        return None
    return round(watts / (phases * 230), 0)


FAULT_BITS: dict[int, str] = {
    0: "Emergency stop",
    1: "Overcurrent",
    2: "Over temperature",
    3: "PE grounding fault",
    4: "Leakage current",
    5: "PE leakage current",
    6: "Overload protection",
    8: "L1 overvoltage",
    9: "L1 undervoltage",
    10: "L2 overvoltage",
    11: "L2 undervoltage",
    12: "L3 overvoltage",
    13: "L3 undervoltage",
    14: "Energy measurement IC fault",
    15: "Meter communication fault",
    16: "Incorrect power rating",
    17: "Control Pilot voltage anomaly",
    18: "Electronic lock fault",
    19: "Meter selection failure",
    20: "Cover opened",
    21: "PEN relay fault",
    22: "Parallel communication failure",
    23: "L1N relay contact sticking",
    24: "L1N relay failure",
    25: "L2L3 relay contact sticking",
    26: "L2L3 relay failure",
    28: "Abnormal metering",
}


def value_function_fault_description(initval: Any, descr: Any, datadict: dict[str, Any]) -> str | None:
    """Human readable view of the fault bitfield (HAC V1.00 Appendix B)."""
    raw = datadict.get("fault_code")
    if raw is None:
        return None
    raw = int(raw)
    if raw == 0:
        return "OK"
    names = [name for bit, name in FAULT_BITS.items() if raw >> bit & 1]
    if not names:
        return f"Unknown fault 0x{raw:08X}"
    if len(names) > 5:
        return ", ".join(names[:5]) + f" (+{len(names) - 5} more)"
    return ", ".join(names)


def value_function_ems_fault_description(initval: Any, descr: Any, datadict: dict[str, Any]) -> str | None:
    """Human readable view of the EMS fault bitfield (same bit map as 0x1E)."""
    raw = datadict.get("ems_fault_code")
    if raw is None:
        return None
    raw = int(raw)
    if raw == 0:
        return "OK"
    names = [name for bit, name in FAULT_BITS.items() if raw >> bit & 1]
    if not names:
        return f"Unknown fault 0x{raw:08X}"
    if len(names) > 5:
        return ", ".join(names[:5]) + f" (+{len(names) - 5} more)"
    return ", ".join(names)


def value_function_rtc_evc(initval: Any, descr: Any, datadict: dict[str, Any]) -> datetime | None:
    """Parse GEN1 RTC block (7 words from 0x61D).

    word[0] = timezone offset in MINUTES (device uses minutes; e.g. UTC+3 → 180,
              negatives as uint16 two's-complement).
    words[1-6] = seconds, minutes, hours, day, month, year (2-digit).

    Attaches the stored timezone directly to the stored time — no UTC assumption,
    no conversion.  Whatever time the device holds is shown as-is with its offset.
    e.g. stored: tz=180, time=11:18  ->  returns 2026-05-01 11:18:00+03:00
    """

    try:
        tz_raw, sec, minute, hour, day, month, year = initval
        tz_minutes = tz_raw if tz_raw <= 32767 else tz_raw - 65536
        tz = timezone(timedelta(minutes=tz_minutes))
        return datetime(2000 + year % 100, month, day, hour, minute, sec, tzinfo=tz)
    except Exception:
        return None


def value_function_charge_start_time(initval: Any, descr: Any, datadict: dict[str, Any]) -> datetime | None:
    """Parse the GEN2 charging-session start timestamp (6 words from 0x31).

    words = seconds, minutes, hours, day, month, year (2-digit), stamped from
    the charger's local clock when the session starts.  All zeros = no session
    recorded yet.
    """

    try:
        sec, minute, hour, day, month, year = initval
        if not any(initval):
            return None
        return datetime(2000 + year % 100, month, day, hour, minute, sec).astimezone()
    except Exception:
        return None


def value_function_sync_rtc_evc(initval: Any, descr: Any, datadict: dict[str, Any]) -> list[tuple[str, int]]:
    """Write current UTC into the RTC base clock (0x61E–0x623).

    Verified on hardware (C311 fw 1.18): the six time words hold a UTC base
    clock and the device itself renders display time = base + 0x61D offset.
    Writing anything but UTC skews the clock by the offset. 0x61D is owned by
    the cloud — it re-asserts the account timezone from the SolaX app within
    a minute — so the sync deliberately leaves it untouched.
    """

    utc_now = datetime.now(UTC)
    return [
        (REGISTER_U16, utc_now.second),
        (REGISTER_U16, utc_now.minute),
        (REGISTER_U16, utc_now.hour),
        (REGISTER_U16, utc_now.day),
        (REGISTER_U16, utc_now.month),
        (REGISTER_U16, utc_now.year % 100),
    ]


# ================================= Button Declarations ============================================================

BUTTON_TYPES = [
    SolaXEVChargerModbusButtonEntityDescription(
        name="Sync RTC",
        key="sync_rtc",
        register=0x61E,
        write_method=WRITE_MULTI_MODBUS,
        icon="mdi:home-clock",
        value_function=value_function_sync_rtc_evc,
        entity_category=EntityCategory.CONFIG,
    ),
]

# ================================= Number Declarations ============================================================

NUMBER_TYPES = [
    ###
    #
    # Data only number types
    #
    ###
    ###
    #
    #  Normal number types
    #
    ###
    SolaXEVChargerModbusNumberEntityDescription(
        name="Overvoltage Limit",
        key="overload_limit",
        register=0x611,
        fmt="i",
        native_min_value=260,
        native_max_value=300,
        native_step=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Undervoltage Limit",
        key="undervoltage_limit",
        register=0x612,
        fmt="i",
        native_min_value=80,
        native_max_value=160,
        native_step=1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Main Breaker Limit",
        key="main_breaker_limit",
        register=0x614,
        fmt="i",
        native_min_value=11,
        native_max_value=300,
        native_step=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Charge Current",
        key="charge_current",
        register=0x628,
        modbus_min=109,
        allowedtypes=GEN1,
        fmt="f",
        native_min_value=6,
        native_max_value=32,
        max_key="rated_current",
        native_step=1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Charge Current",
        key="charge_current",
        register=0x628,
        allowedtypes=GEN2,
        fmt="f",
        native_min_value=6,
        native_max_value=32,
        max_key="rated_current",
        native_step=1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Unbalanced Power",
        key="unbalanced_power",
        register=0x63C,
        modbus_min=111,
        allowedtypes=GEN1 | X1,
        fmt="i",
        native_min_value=1300,
        native_max_value=7200,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Unbalanced Power",
        key="unbalanced_power",
        register=0x63C,
        allowedtypes=GEN2 | X1,
        fmt="i",
        native_min_value=1300,
        native_max_value=7200,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Max Charge Current",
        key="max_charge_current",
        register=0x668,
        fmt="f",
        native_min_value=6,
        native_max_value=32,
        max_key="rated_current",
        native_step=1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Min Charge Current",
        key="min_charge_current",
        register=0x63F,
        modbus_min=112,
        allowedtypes=GEN1,
        fmt="f",
        native_min_value=0,
        native_max_value=32,
        max_key="rated_current",
        native_step=1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Min Charge Current",
        key="min_charge_current",
        register=0x63F,
        allowedtypes=GEN2,
        fmt="f",
        native_min_value=0,
        native_max_value=32,
        max_key="rated_current",
        native_step=1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Modbus Address",
        key="modbus_address",
        register=0x640,
        modbus_min=112,
        allowedtypes=GEN1,
        fmt="i",
        native_min_value=1,
        native_max_value=247,
        native_step=1,
        icon="mdi:identifier",
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Modbus Address",
        key="modbus_address",
        register=0x640,
        allowedtypes=GEN2,
        fmt="i",
        native_min_value=1,
        native_max_value=247,
        native_step=1,
        icon="mdi:identifier",
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Smart Boost Energy",
        key="smart_boost_energy",
        register=0x63A,
        modbus_min=111,
        allowedtypes=GEN1,
        fmt="i",
        native_min_value=0,
        native_max_value=200,
        native_step=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=NumberDeviceClass.ENERGY,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Smart Boost Energy",
        key="smart_boost_energy",
        register=0x63A,
        allowedtypes=GEN2,
        fmt="i",
        native_min_value=0,
        native_max_value=200,
        native_step=1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=NumberDeviceClass.ENERGY,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Max Charge Power",
        key="ems_max_charge_power",
        device_group="ems",
        register=0xA100,
        allowedtypes=GEN2 | EMS_TYPE,
        fmt="i",
        native_min_value=0,
        native_max_value=30000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Max Discharge Power",
        key="ems_max_discharge_power",
        device_group="ems",
        register=0xA101,
        allowedtypes=GEN2 | EMS_TYPE,
        fmt="i",
        native_min_value=0,
        native_max_value=30000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Failsafe Charge Power",
        key="ems_failsafe_charge_power",
        device_group="ems",
        register=0xA102,
        allowedtypes=GEN2 | EMS_TYPE,
        fmt="i",
        native_min_value=0,
        native_max_value=30000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Failsafe Discharge Power",
        key="ems_failsafe_discharge_power",
        device_group="ems",
        register=0xA103,
        allowedtypes=GEN2 | EMS_TYPE,
        fmt="i",
        native_min_value=0,
        native_max_value=30000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        entity_category=EntityCategory.CONFIG,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Failsafe Timeout",
        key="ems_failsafe_timeout",
        device_group="ems",
        register=0xA104,
        allowedtypes=GEN2 | EMS_TYPE,
        fmt="i",
        native_min_value=1,
        native_max_value=600,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.CONFIG,
    ),
]

# ================================= Select Declarations ============================================================

SELECT_TYPES = [
    ###
    #
    #  Data only select types
    #
    ###
    ###
    #
    #  Normal select types
    #
    ###
    SolaXEVChargerModbusSelectEntityDescription(
        name="Meter Setting",
        key="meter_setting",
        register=0x60C,
        option_dict={
            0: "External CT",
            1: "External Meter",
            2: "Inverter",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:meter-electric",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        register=0x60D,
        option_dict={
            0: "Stop",
            1: "Fast",
            2: "ECO",
            3: "Green",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="ECO Gear",
        key="eco_gear",
        register=0x60E,
        option_dict={
            1: "6A",
            2: "10A",
            3: "16A",
            4: "20A",
            5: "25A",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Green Gear",
        key="green_gear",
        register=0x60F,
        option_dict={
            1: "3A",
            2: "6A",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Start Charge Mode",
        key="start_charge_mode",
        register=0x610,
        allowedtypes=GEN2,
        option_dict={
            0: "Plug and Charge",
            1: "Swipe Card to Start",
            2: "App Start",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:lock",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Start Charge Mode",
        key="start_charge_mode",
        register=0x610,
        allowedtypes=GEN1,
        option_dict={
            0: "Plug and Charge",
            1: "Swipe Card to Start",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:lock",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Boost Mode",
        key="boost_mode",
        register=0x613,
        option_dict={
            0: "Normal",
            1: "Timer Boost",
            2: "Smart Boost",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Charge Phase",
        key="charge_phase",
        register=0x625,
        modbus_min=109,
        modbus_max=110,
        option_dict={
            0: "Three Phase",
            1: "L1 Phase",
            2: "L2 Phase",
            3: "L3 Phase",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:dip-switch",
        allowedtypes=GEN1 | X1,
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Charge Phase",
        key="charge_phase",
        register=0x625,
        option_dict={
            0: "Three Phase",
            1: "L1 Phase",
            2: "L2 Phase",
            3: "L3 Phase",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:dip-switch",
        allowedtypes=GEN2 | X1,
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Charge Phase",
        key="charge_phase",
        register=0x63B,
        modbus_min=111,
        option_dict={
            0: "Three Phase",
            1: "L1 Phase",
            2: "L2 Phase",
            3: "L3 Phase",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:dip-switch",
        allowedtypes=GEN1 | X1,
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Control Command",
        key="control_command",
        register=0x627,
        modbus_min=109,
        allowedtypes=GEN1,
        option_dict={
            0: "No Command",
            1: "Available",
            2: "Unavailable",
            3: "Stop Charging",
            4: "Start Charging",
            5: "Reserve",
            6: "Cancel the Reservation",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Control Command",
        key="control_command",
        register=0x627,
        allowedtypes=GEN2,
        option_dict={
            0: "No Command",
            1: "Available",
            2: "Unavailable",
            3: "Stop Charging",
            4: "Start Charging",
            5: "Reserve",
            6: "Cancel the Reservation",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Mode Button",
        key="mode_button",
        register=0x63E,
        modbus_min=112,
        allowedtypes=GEN1,
        option_dict={
            0: "None",
            1: "Short Press",
            2: "Long Press",
        },
        icon="mdi:gesture-tap-button",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Mode Button",
        key="mode_button",
        register=0x63E,
        allowedtypes=GEN2,
        option_dict={
            0: "None",
            1: "Short Press",
            2: "Long Press",
        },
        icon="mdi:gesture-tap-button",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Phase Switching",
        key="ems_phase_switching",
        device_group="ems",
        register=0xA105,
        allowedtypes=GEN2 | EMS_TYPE,
        option_dict={
            0: "Disabled",
            1: "Single-Phase Manual",
            2: "Three-Phase Manual",
            3: "Power-Following Auto",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:sine-wave",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Charge Control",
        key="ems_charge_control",
        device_group="ems",
        register=0xA106,
        allowedtypes=GEN2 | EMS_TYPE,
        option_dict={
            1: "Start Charging",
            2: "Pause Charging",
            3: "Stop Charging",
        },
        icon="mdi:play-pause",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Parallel Charge Mode",
        key="parallel_charge_mode",
        device_group="pm",
        register=0x669,
        allowedtypes=PARALLEL_TYPE,
        option_dict={
            0: "Fast",
            1: "ECO",
            2: "Green",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Auth Priority",
        key="auth_priority",
        register=0x650,
        modbus_min=114,
        allowedtypes=GEN1,
        option_dict={
            0: "Network Priority",
            1: "Local Priority",
            2: "Local Only",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:shield-key",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Auth Priority",
        key="auth_priority",
        register=0x650,
        allowedtypes=GEN2,
        option_dict={
            0: "Network Priority",
            1: "Local Priority",
            2: "Local Only",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:shield-key",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Charge Mode",
        key="charge_mode",
        register=0x641,
        allowedtypes=GEN1,
        modbus_min=114,
        option_dict={
            0: "Fast",
            1: "ECO",
            2: "Green",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Charge Mode",
        key="charge_mode",
        register=0x641,
        allowedtypes=GEN2,
        option_dict={
            0: "Fast",
            1: "ECO",
            2: "Green",
        },
        entity_category=EntityCategory.CONFIG,
        icon="mdi:dip-switch",
    ),
]

# ================================= Time Declarations ==============================================================

TIME_TYPES = [
    SolaXEVChargerModbusTimeEntityDescription(
        name="Timer Boost Start Time",
        key="timer_boost_start_time",
        register=0x634,
        modbus_min=111,
        allowedtypes=GEN1,
        option_dict=TIME_OPTIONS_SEPARATE_REGISTERS,
        wordcount=2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaXEVChargerModbusTimeEntityDescription(
        name="Timer Boost Start Time",
        key="timer_boost_start_time",
        register=0x634,
        allowedtypes=GEN2,
        option_dict=TIME_OPTIONS_SEPARATE_REGISTERS,
        wordcount=2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaXEVChargerModbusTimeEntityDescription(
        name="Timer Boost End Time",
        key="timer_boost_end_time",
        register=0x636,
        modbus_min=111,
        allowedtypes=GEN1,
        option_dict=TIME_OPTIONS_SEPARATE_REGISTERS,
        wordcount=2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaXEVChargerModbusTimeEntityDescription(
        name="Timer Boost End Time",
        key="timer_boost_end_time",
        register=0x636,
        allowedtypes=GEN2,
        option_dict=TIME_OPTIONS_SEPARATE_REGISTERS,
        wordcount=2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaXEVChargerModbusTimeEntityDescription(
        name="Smart Boost End Time",
        key="smart_boost_end_time",
        register=0x638,
        modbus_min=111,
        allowedtypes=GEN1,
        option_dict=TIME_OPTIONS_SEPARATE_REGISTERS,
        wordcount=2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaXEVChargerModbusTimeEntityDescription(
        name="Smart Boost End Time",
        key="smart_boost_end_time",
        register=0x638,
        allowedtypes=GEN2,
        option_dict=TIME_OPTIONS_SEPARATE_REGISTERS,
        wordcount=2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
]

# ================================= Sensor Declarations ============================================================


SENSOR_TYPES_MAIN: list[SolaXEVChargerModbusSensorEntityDescription] = [
    SolaXEVChargerModbusSensorEntityDescription(
        name="Serial Number",
        key="serial_number",
        register=0x600,
        register_data_type=REGISTER_STR,
        order32="big",
        wordcount=7,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:barcode",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="WiFi S/N",
        key="wifi_sn",
        register=0x607,
        register_data_type=REGISTER_STR,
        order32="big",
        wordcount=5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Customized S/N",
        key="customized_sn",
        register=0x629,
        modbus_min=111,
        allowedtypes=GEN1,
        register_data_type=REGISTER_STR,
        order32="big",
        wordcount=11,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:identifier",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Customized S/N",
        key="customized_sn",
        register=0x629,
        allowedtypes=GEN2,
        register_data_type=REGISTER_STR,
        order32="big",
        wordcount=11,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:identifier",
    ),
    ###
    #
    # Holding — internal backing sensors (poll registers for SELECT/NUMBER readback;
    # not registered as HA entities — use the SELECT/NUMBER entities instead)
    #
    ###
    SolaXEVChargerModbusSensorEntityDescription(
        name="Meter Setting",
        key="meter_setting",
        register=0x60C,
        scale={0: "External CT", 1: "External Meter", 2: "Inverter"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        register=0x60D,
        scale={0: "Stop", 1: "Fast", 2: "ECO", 3: "Green"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="ECO Gear",
        key="eco_gear",
        register=0x60E,
        scale={1: "6A", 2: "10A", 3: "16A", 4: "20A", 5: "25A"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Green Gear",
        key="green_gear",
        register=0x60F,
        scale={1: "3A", 2: "6A"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Start Charge Mode",
        key="start_charge_mode",
        register=0x610,
        scale={0: "Plug and Charge", 1: "Swipe Card to Start", 2: "App Start"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Overvoltage Limit",
        key="overload_limit",
        register=0x611,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Undervoltage Limit",
        key="undervoltage_limit",
        register=0x612,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Boost Mode",
        key="boost_mode",
        register=0x613,
        scale={0: "Normal", 1: "Timer Boost", 2: "Smart Boost"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Main Breaker Limit",
        key="main_breaker_limit",
        register=0x614,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Electronic Lock",
        key="electronic_lock",
        register=0x615,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="RFID Card Activation",
        key="rfid_card_activation",
        register=0x616,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="RTC",
        key="rtc",
        register=0x61D,
        register_data_type=REGISTER_WORDS,
        wordcount=7,
        scale=value_function_rtc_evc,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:clock",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Datahub Charge Current",
        key="datahub_charge_current",
        device_group="datahub",
        register=0x624,
        allowedtypes=GEN1 | DATAHUB_TYPE,
        modbus_min=109,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Datahub Charge Current",
        key="datahub_charge_current",
        device_group="datahub",
        register=0x624,
        allowedtypes=GEN2 | DATAHUB_TYPE,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Phase",
        key="charge_phase",
        register=0x625,
        modbus_min=109,
        modbus_max=110,
        scale={0: "Three Phase", 1: "L1 Phase", 2: "L2 Phase", 3: "L3 Phase"},
        allowedtypes=GEN1 | X1,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Phase",
        key="charge_phase",
        register=0x625,
        scale={0: "Three Phase", 1: "L1 Phase", 2: "L2 Phase", 3: "L3 Phase"},
        allowedtypes=GEN2 | X1,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Phase",
        key="charge_phase",
        register=0x63B,
        modbus_min=111,
        scale={0: "Three Phase", 1: "L1 Phase", 2: "L2 Phase", 3: "L3 Phase"},
        allowedtypes=GEN1 | X1,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current",
        key="charge_current",
        register=0x628,
        modbus_min=109,
        allowedtypes=GEN1,
        scale=0.01,
        rounding=2,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current",
        key="charge_current",
        register=0x628,
        allowedtypes=GEN2,
        scale=0.01,
        rounding=2,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Control Command",
        key="control_command",
        register=0x627,
        modbus_min=109,
        allowedtypes=GEN1,
        scale={
            0: "No Command",
            1: "Available",
            2: "Unavailable",
            3: "Stop Charging",
            4: "Start Charging",
            5: "Reserve",
            6: "Cancel the Reservation",
        },
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Control Command",
        key="control_command",
        register=0x627,
        allowedtypes=GEN2,
        scale={
            0: "No Command",
            1: "Available",
            2: "Unavailable",
            3: "Stop Charging",
            4: "Start Charging",
            5: "Reserve",
            6: "Cancel the Reservation",
        },
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Max Charge Current Limit",
        key="max_charge_current_limit",
        register=0x64F,
        modbus_min=114,
        allowedtypes=GEN1,
        scale=0.01,
        rounding=2,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Max Charge Current Limit",
        key="max_charge_current_limit",
        register=0x64F,
        allowedtypes=GEN2,
        scale=0.01,
        rounding=2,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Rated Current",
        key="rated_current",
        register=-1,
        value_function=value_function_rated_current,
        depends_on=["power_rating", "phase_type"],
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Modbus Address",
        key="modbus_address",
        register=0x640,
        modbus_min=112,
        allowedtypes=GEN1,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Modbus Address",
        key="modbus_address",
        register=0x640,
        allowedtypes=GEN2,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Unbalanced Power",
        key="unbalanced_power",
        register=0x63C,
        modbus_min=111,
        allowedtypes=GEN1 | X1,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Unbalanced Power",
        key="unbalanced_power",
        register=0x63C,
        allowedtypes=GEN2 | X1,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Unbalanced Switch",
        key="unbalanced_switch",
        register=0x63D,
        modbus_min=111,
        allowedtypes=GEN1 | X1,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Unbalanced Switch",
        key="unbalanced_switch",
        register=0x63D,
        allowedtypes=GEN2 | X1,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Mode Button",
        key="mode_button",
        register=0x63E,
        modbus_min=112,
        allowedtypes=GEN1,
        scale={0: "None", 1: "Short Press", 2: "Long Press"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Mode Button",
        key="mode_button",
        register=0x63E,
        allowedtypes=GEN2,
        scale={0: "None", 1: "Short Press", 2: "Long Press"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Min Charge Current",
        key="min_charge_current",
        register=0x63F,
        modbus_min=112,
        allowedtypes=GEN1,
        scale=0.01,
        rounding=2,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Min Charge Current",
        key="min_charge_current",
        register=0x63F,
        allowedtypes=GEN2,
        scale=0.01,
        rounding=2,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Mode",
        key="charge_mode",
        register=0x641,
        allowedtypes=GEN1,
        modbus_min=114,
        scale={0: "Fast", 1: "ECO", 2: "Green"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Mode",
        key="charge_mode",
        register=0x641,
        allowedtypes=GEN2,
        scale={0: "Fast", 1: "ECO", 2: "Green"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Datahub Charge Power",
        key="datahub_charge_power",
        device_group="datahub",
        register=0x643,
        newblock=True,
        allowedtypes=GEN1 | DATAHUB_TYPE,
        modbus_min=114,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Datahub Charge Power",
        key="datahub_charge_power",
        device_group="datahub",
        register=0x643,
        newblock=True,
        allowedtypes=GEN2 | DATAHUB_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Green 30s Delay",
        key="green_30s_delay",
        register=0x644,
        allowedtypes=GEN1,
        modbus_min=114,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Green 30s Delay",
        key="green_30s_delay",
        register=0x644,
        allowedtypes=GEN2,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Main Breaker Limit Switch",
        key="main_breaker_limit_switch",
        register=0x664,
        newblock=True,
        allowedtypes=GEN2,
        value_function=value_function_closed_is_on,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Timer Boost Start Time",
        key="timer_boost_start_time",
        register=0x634,
        modbus_min=111,
        allowedtypes=GEN1,
        register_data_type=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_separate_registers_time,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Timer Boost Start Time",
        key="timer_boost_start_time",
        register=0x634,
        allowedtypes=GEN2,
        register_data_type=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_separate_registers_time,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Timer Boost End Time",
        key="timer_boost_end_time",
        register=0x636,
        modbus_min=111,
        allowedtypes=GEN1,
        register_data_type=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_separate_registers_time,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Timer Boost End Time",
        key="timer_boost_end_time",
        register=0x636,
        allowedtypes=GEN2,
        register_data_type=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_separate_registers_time,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Smart Boost End Time",
        key="smart_boost_end_time",
        register=0x638,
        modbus_min=111,
        allowedtypes=GEN1,
        register_data_type=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_separate_registers_time,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Smart Boost End Time",
        key="smart_boost_end_time",
        register=0x638,
        allowedtypes=GEN2,
        register_data_type=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_separate_registers_time,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Smart Boost Energy",
        key="smart_boost_energy",
        register=0x63A,
        modbus_min=111,
        allowedtypes=GEN1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Smart Boost Energy",
        key="smart_boost_energy",
        register=0x63A,
        allowedtypes=GEN2,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        internal=True,
    ),
    ###
    #
    # Input — 0x0100+
    # 0x0100-0x0102: ChargePower L1 (A) / L2 (B) / L3 (C), replacing 0x08-0x0A from firmware V1.12 (protocol V2.8)
    #
    ###
    # ---- 0x0100-0x0102  Phase powers (protocol V2.8+, firmware >= V1.12) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Max Power Charging",
        key="max_power_charging",
        register=0x103,
        register_type=REG_INPUT,
        modbus_min=112,
        allowedtypes=GEN1,
        scale={0: "No", 1: "Yes"},
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:lightning-bolt",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Mode",
        key="charge_mode",
        register=0x104,
        allowedtypes=GEN1,
        register_type=REG_INPUT,
        modbus_min=112,
        scale={0: "Fast", 1: "ECO", 2: "Green"},
        icon="mdi:dip-switch",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Green Mode Start Power",
        key="green_mode_start_power",
        register=0x105,
        register_type=REG_INPUT,
        modbus_min=112,
        allowedtypes=GEN1,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:solar-power",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Auth Priority",
        key="auth_priority",
        register=0x650,
        modbus_min=114,
        allowedtypes=GEN1,
        scale={0: "Network Priority", 1: "Local Priority", 2: "Local Only"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Auth Priority",
        key="auth_priority",
        register=0x650,
        allowedtypes=GEN2,
        scale={0: "Network Priority", 1: "Local Priority", 2: "Local Only"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Parallel Role",
        key="parallel_role",
        device_group="pm",
        register=0x642,
        modbus_min=114,
        allowedtypes=GEN1 | PARALLEL_TYPE,
        scale={0: "Master", 1: "Slave", 2: "Parallel with Gen2"},
        icon="mdi:transit-connection-variant",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Parallel Role",
        key="parallel_role",
        device_group="pm",
        register=0x642,
        allowedtypes=GEN2 | PARALLEL_TYPE,
        scale={0: "Master", 1: "Slave", 2: "Parallel with Gen2"},
        icon="mdi:transit-connection-variant",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Parallel Support",
        key="parallel_support",
        device_group="pm",
        register=0x107,
        register_type=REG_INPUT,
        modbus_min=112,
        allowedtypes=PM_OPTION_TYPE,
        scale={0: "No", 0xAA55: "Yes"},
        icon="mdi:transit-connection-variant",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Allow Charge",
        key="slave_allow_charge",
        device_group="pm",
        register=0x666,
        newblock=True,
        allowedtypes=PARALLEL_TYPE,
        scale={0: "No", 1: "Yes"},
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:ev-station",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Available Current",
        key="slave_available_current",
        device_group="pm",
        register=0x667,
        allowedtypes=PARALLEL_TYPE,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:current-ac",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Max Charge Current",
        key="max_charge_current",
        register=0x668,
        newblock=True,
        scale=0.01,
        rounding=2,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Parallel Charge Mode",
        key="parallel_charge_mode",
        register=0x669,
        allowedtypes=PARALLEL_TYPE,
        scale={0: "Fast", 1: "ECO", 2: "Green"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Error Mask",
        key="parallel_error_mask",
        device_group="pm",
        register=0x66A,
        register_data_type=REGISTER_U32,
        allowedtypes=PARALLEL_TYPE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-decagram-outline",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Count",
        key="slave_count",
        device_group="pm",
        register=0x66C,
        allowedtypes=PARALLEL_TYPE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:counter",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Power Allocation Ratio",
        key="power_allocation_ratio",
        device_group="pm",
        register=0x66D,
        allowedtypes=PARALLEL_TYPE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:scale-balance",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Allocation Master State",
        key="allocation_master_state",
        device_group="pm",
        register=0x66E,
        allowedtypes=PARALLEL_TYPE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:sitemap",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Request Slave Address",
        key="request_slave_address",
        device_group="pm",
        register=0x66F,
        allowedtypes=PARALLEL_TYPE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:map-marker-question-outline",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Reference Power",
        key="datahub_reference_power",
        device_group="datahub",
        register=0x700,
        newblock=True,
        register_data_type=REGISTER_S16,
        allowedtypes=DATAHUB_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Power To EV",
        key="datahub_power_to_ev",
        device_group="datahub",
        register=0x701,
        register_data_type=REGISTER_S32,
        allowedtypes=DATAHUB_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="PV Reference",
        key="datahub_pv_reference",
        device_group="datahub",
        register=0x703,
        allowedtypes=DATAHUB_TYPE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:solar-power",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Feedin Power",
        key="datahub_feedin_power_l1",
        device_group="datahub",
        register=0x704,
        register_data_type=REGISTER_S32,
        allowedtypes=DATAHUB_TYPE | X1,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Feedin Power L1",
        key="datahub_feedin_power_l1",
        device_group="datahub",
        register=0x704,
        register_data_type=REGISTER_S32,
        allowedtypes=DATAHUB_TYPE | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Feedin Power L2",
        key="datahub_feedin_power_l2",
        device_group="datahub",
        register=0x706,
        register_data_type=REGISTER_S32,
        allowedtypes=DATAHUB_TYPE | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Feedin Power L3",
        key="datahub_feedin_power_l3",
        device_group="datahub",
        register=0x708,
        register_data_type=REGISTER_S32,
        allowedtypes=DATAHUB_TYPE | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Off-Grid Charging",
        key="datahub_off_grid",
        device_group="datahub",
        register=0x70A,
        allowedtypes=DATAHUB_TYPE,
        scale={
            0: "Not Off-Grid",
            1: "Off-Grid",
        },
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:transmission-tower-off",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Main Breaker Limit",
        key="datahub_main_breaker_limit",
        device_group="datahub",
        register=0x70B,
        allowedtypes=DATAHUB_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:fuse",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Green Mode 30s Delay",
        key="datahub_green_30s_delay",
        device_group="datahub",
        register=0x70C,
        allowedtypes=DATAHUB_TYPE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:timer-outline",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power Limit",
        key="datahub_charge_power_limit",
        device_group="datahub",
        register=0x70D,
        allowedtypes=DATAHUB_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:speedometer",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Start Time",
        key="charge_start_time",
        register=0x31,
        register_type=REG_INPUT,
        newblock=True,
        allowedtypes=GEN2,
        register_data_type=REGISTER_WORDS,
        wordcount=6,
        scale=value_function_charge_start_time,
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Request Charge",
        key="slave_request_charge",
        device_group="pm",
        register=0x38,
        register_type=REG_INPUT,
        newblock=True,
        allowedtypes=PARALLEL_TYPE,
        scale={0: "No", 1: "Yes"},
        icon="mdi:ev-plug-type2",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Run Mode",
        key="slave_run_mode",
        device_group="pm",
        register=0x39,
        register_type=REG_INPUT,
        allowedtypes=PARALLEL_TYPE,
        scale={
            0: "Available",
            1: "Preparing",
            2: "Charging",
            3: "Finishing",
            4: "Faulted",
            5: "Unavailable",
            6: "Reserved",
            7: "Suspended EV",
            8: "Suspended EVSE",
            9: "Update",
            10: "Card Activation",
            11: "Start Delay",
            12: "Charge Paused",
            13: "Stopping",
            14: "Occupied",
            15: "Waiting for Response",
            16: "Discharging",
            17: "Phase Switching",
        },
        icon="mdi:run",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Current",
        key="slave_current",
        device_group="pm",
        register=0x3A,
        register_type=REG_INPUT,
        allowedtypes=X1 | PARALLEL_TYPE,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Current L1",
        key="slave_current_l1",
        device_group="pm",
        register=0x3A,
        register_type=REG_INPUT,
        allowedtypes=X3 | PARALLEL_TYPE,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Current L2",
        key="slave_current_l2",
        device_group="pm",
        register=0x3B,
        register_type=REG_INPUT,
        allowedtypes=X3 | PARALLEL_TYPE,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Current L3",
        key="slave_current_l3",
        device_group="pm",
        register=0x3C,
        register_type=REG_INPUT,
        allowedtypes=X3 | PARALLEL_TYPE,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Power",
        key="slave_power",
        device_group="pm",
        register=0x3D,
        register_type=REG_INPUT,
        allowedtypes=X1 | PARALLEL_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Power L1",
        key="slave_power_l1",
        device_group="pm",
        register=0x3D,
        register_type=REG_INPUT,
        allowedtypes=X3 | PARALLEL_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Power L2",
        key="slave_power_l2",
        device_group="pm",
        register=0x3E,
        register_type=REG_INPUT,
        allowedtypes=X3 | PARALLEL_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Power L3",
        key="slave_power_l3",
        device_group="pm",
        register=0x3F,
        register_type=REG_INPUT,
        allowedtypes=X3 | PARALLEL_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Power Total",
        key="slave_power_total",
        device_group="pm",
        register=0x40,
        register_type=REG_INPUT,
        allowedtypes=PARALLEL_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Phase Type",
        key="slave_phase_type",
        device_group="pm",
        register=0x41,
        register_type=REG_INPUT,
        allowedtypes=PARALLEL_TYPE,
        scale={0: "Single Phase", 1: "Three Phase"},
        icon="mdi:sine-wave",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Slave Charge Phase",
        key="slave_charge_phase",
        device_group="pm",
        register=0x42,
        register_type=REG_INPUT,
        allowedtypes=PARALLEL_TYPE,
        scale={0: "Three Phase", 1: "L1 Phase", 2: "L2 Phase", 3: "L3 Phase"},
        icon="mdi:cable-data",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Auto Allocation Result",
        key="auto_allocation_result",
        device_group="pm",
        register=0x64,
        register_type=REG_INPUT,
        newblock=True,
        allowedtypes=PARALLEL_TYPE,
        icon="mdi:sitemap-outline",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Request Slave SN",
        key="request_slave_sn",
        device_group="pm",
        register=0x65,
        register_type=REG_INPUT,
        allowedtypes=PARALLEL_TYPE,
        icon="mdi:identifier",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Max Charge Power",
        key="ems_max_charge_power",
        register=0xA100,
        newblock=True,
        allowedtypes=GEN2 | EMS_TYPE,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Max Discharge Power",
        key="ems_max_discharge_power",
        register=0xA101,
        allowedtypes=GEN2 | EMS_TYPE,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Failsafe Charge Power",
        key="ems_failsafe_charge_power",
        register=0xA102,
        allowedtypes=GEN2 | EMS_TYPE,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Failsafe Discharge Power",
        key="ems_failsafe_discharge_power",
        register=0xA103,
        allowedtypes=GEN2 | EMS_TYPE,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Failsafe Timeout",
        key="ems_failsafe_timeout",
        register=0xA104,
        allowedtypes=GEN2 | EMS_TYPE,
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Phase Switching",
        key="ems_phase_switching",
        register=0xA105,
        allowedtypes=GEN2 | EMS_TYPE,
        scale={0: "Disabled", 1: "Single-Phase Manual", 2: "Three-Phase Manual", 3: "Power-Following Auto"},
        internal=True,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Control",
        key="ems_charge_control",
        register=0xA106,
        allowedtypes=GEN2 | EMS_TYPE,
        scale={0: "Invalid", 1: "Start Charging", 2: "Pause Charging", 3: "Stop Charging"},
        internal=True,
    ),
    ###
    #
    # Input
    #
    ###
    # ---- 0x0000–0x0002  Phase voltages L1 (A) / L2 (B) / L3 (C), 0.01V ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage",
        key="charge_voltage",
        register=0x0,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X1,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage L1",
        key="charge_voltage_l1",
        register=0x0,
        register_type=REG_INPUT,
        allowedtypes=X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage L2",
        key="charge_voltage_l2",
        register=0x1,
        register_type=REG_INPUT,
        allowedtypes=X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage L3",
        key="charge_voltage_l3",
        register=0x2,
        register_type=REG_INPUT,
        allowedtypes=X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ---- 0x0003  PE voltage (GEN2 doc: VoltagePE, 0.01V) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge PE Voltage",
        key="charge_pe_voltage",
        register=0x3,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---- 0x0004–0x0006  Phase currents L1 (A) / L2 (B) / L3 (C), 0.01A ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current",
        key="charge_current_measured",
        register=0x4,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=GEN1 | X1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current",
        key="charge_current_measured",
        register=0x4,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=GEN2 | X1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L1",
        key="charge_current_l1",
        register=0x4,
        register_type=REG_INPUT,
        allowedtypes=GEN1 | X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L1",
        key="charge_current_l1",
        register=0x4,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=GEN2 | X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L2",
        key="charge_current_l2",
        register=0x5,
        register_type=REG_INPUT,
        allowedtypes=GEN1 | X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L2",
        key="charge_current_l2",
        register=0x5,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=GEN2 | X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L3",
        key="charge_current_l3",
        register=0x6,
        register_type=REG_INPUT,
        allowedtypes=GEN1 | X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L3",
        key="charge_current_l3",
        register=0x6,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=GEN2 | X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ---- 0x0007  PE current (GEN2 doc: CurrentPE, 0.001A) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge PE Current",
        key="charge_pe_current",
        register=0x7,
        register_type=REG_INPUT,
        rounding=0,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---- 0x0008–0x000A  Phase powers L1 (A) / L2 (B) / L3 (C), 1W ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power",
        key="charge_power",
        register=0x8,
        register_type=REG_INPUT,
        modbus_max=111,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=GEN1 | X1,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power",
        key="charge_power",
        register=0x100,
        register_type=REG_INPUT,
        modbus_min=112,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=GEN1 | X1,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power",
        key="charge_power",
        register=0x8,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=GEN2 | X1,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L1",
        key="charge_power_l1",
        register=0x8,
        register_type=REG_INPUT,
        modbus_max=111,
        allowedtypes=GEN1 | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L1",
        key="charge_power_l1",
        register=0x100,
        register_type=REG_INPUT,
        modbus_min=112,
        allowedtypes=GEN1 | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L1",
        key="charge_power_l1",
        register=0x8,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=GEN2 | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L2",
        key="charge_power_l2",
        register=0x9,
        register_type=REG_INPUT,
        modbus_max=111,
        allowedtypes=GEN1 | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L2",
        key="charge_power_l2",
        register=0x101,
        register_type=REG_INPUT,
        modbus_min=112,
        allowedtypes=GEN1 | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L2",
        key="charge_power_l2",
        register=0x9,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=GEN2 | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L3",
        key="charge_power_l3",
        register=0xA,
        register_type=REG_INPUT,
        modbus_max=111,
        allowedtypes=GEN1 | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L3",
        key="charge_power_l3",
        register=0x102,
        register_type=REG_INPUT,
        modbus_min=112,
        allowedtypes=GEN1 | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L3",
        key="charge_power_l3",
        register=0xA,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=GEN2 | X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ---- 0x000B  Total charge power (GEN2 doc: TotalChargePower, 1W) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power Total",
        key="charge_power_total",
        register=0xB,
        allowedtypes=GEN1,
        register_type=REG_INPUT,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power Total",
        key="charge_power_total",
        register=0xB,
        allowedtypes=GEN2,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ---- 0x000C–0x000E  Phase frequencies L1 (A) / L2 (B) / L3 (C), 0.01Hz ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency",
        key="charge_frequency",
        register=0xC,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X1,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency L1",
        key="charge_frequency_l1",
        register=0xC,
        register_type=REG_INPUT,
        allowedtypes=X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency L2",
        key="charge_frequency_l2",
        register=0xD,
        register_type=REG_INPUT,
        allowedtypes=X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency L3",
        key="charge_frequency_l3",
        register=0xE,
        register_type=REG_INPUT,
        allowedtypes=X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---- 0x000F  Session energy (GEN2 doc: EQ_Single, 0.1kWh) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Added",
        key="charge_added",
        register=0xF,
        register_type=REG_INPUT,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    # ---- 0x0010  Cumulative energy u32 (GEN2 doc: EQ_Total, 0.1kWh) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Added - Cumulative",
        key="charge_added_cum",
        register=0x10,
        register_type=REG_INPUT,
        register_data_type=REGISTER_U32,
        order32="big",
        allowedtypes=GEN1,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Added - Cumulative",
        key="charge_added_cum",
        register=0x10,
        register_type=REG_INPUT,
        register_data_type=REGISTER_U32,
        allowedtypes=GEN2,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Added Total",
        key="charge_added_total",
        register=0x619,
        register_type=REG_HOLDING,
        register_data_type=REGISTER_U32,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    # ---- 0x0012–0x0014  Grid currents L1 (A) / L2 (B) / L3 (C), S16, 0.01A ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current",
        key="grid_current",
        register=0x12,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X1,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current L1",
        key="grid_current_l1",
        register=0x12,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current L2",
        key="grid_current_l2",
        register=0x13,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current L3",
        key="grid_current_l3",
        register=0x14,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=X3,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---- 0x0015–0x0017  Grid powers L1 (A) / L2 (B) / L3 (C), S16, 1W ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power",
        key="grid_power",
        register=0x15,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X1,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power L1",
        key="grid_power_l1",
        register=0x15,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power L2",
        key="grid_power_l2",
        register=0x16,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power L3",
        key="grid_power_l3",
        register=0x17,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        allowedtypes=X3,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---- 0x0018  Total grid power S16 (GEN2 doc: ExternTotalPower, 1W) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power Total",
        key="grid_power_total",
        register=0x18,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ---- 0x0019–0x001C  Not in GEN2 doc; present in GEN1 doc and live on device ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="CC Voltage",
        key="cc_voltage",
        register=0x19,
        register_type=REG_INPUT,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:sine-wave",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="CP Voltage",
        key="cp_voltage",
        register=0x1A,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:sine-wave",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="PWM Duty Cycle",
        key="pwm_duty_cycle",
        register=0x1B,
        register_type=REG_INPUT,
        scale=0.1,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:pulse",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charger Temperature",
        key="charger_temperature",
        register=0x1C,
        register_type=REG_INPUT,
        rounding=0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---- 0x001D  EVSE state (GEN2 doc: EVSE_State, 0–13) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x1D,
        register_type=REG_INPUT,
        modbus_max=111,
        allowedtypes=GEN1,
        scale={
            0: "Available",
            1: "Preparing",
            2: "Charging",
            3: "Finishing",
            4: "Faulted",
            5: "Unavailable",
            6: "Reserved",
            7: "Suspended EV",
            8: "Suspended EVSE",
            9: "Update",
            10: "Card Activation",
            11: "Start Delay",
            12: "Charge Paused",
            13: "Stopping",
            14: "Occupied",
            15: "Waiting for Response",
            16: "Discharging",
            17: "Phase Switching",
        },
        icon="mdi:run",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x106,
        register_type=REG_INPUT,
        modbus_min=112,
        allowedtypes=GEN1,
        scale={
            0: "Available",
            1: "Preparing",
            2: "Charging",
            3: "Finishing",
            4: "Faulted",
            5: "Unavailable",
            6: "Reserved",
            7: "Suspended EV",
            8: "Suspended EVSE",
            9: "Update",
            10: "Card Activation",
            11: "Start Delay",
            12: "Charge Paused",
            13: "Stopping",
            14: "Occupied",
            15: "Waiting for Response",
            16: "Discharging",
            17: "Phase Switching",
        },
        icon="mdi:run",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x1D,
        register_type=REG_INPUT,
        allowedtypes=GEN2,
        scale={
            0: "Available",
            1: "Preparing",
            2: "Charging",
            3: "Finishing",
            4: "Faulted",
            5: "Unavailable",
            6: "Reserved",
            7: "Suspended EV",
            8: "Suspended EVSE",
            9: "Update",
            10: "Card Activation",
            11: "Start Delay",
            12: "Charge Paused",
            13: "Stopping",
            14: "Occupied",
            15: "Waiting for Response",
            16: "Discharging",
            17: "Phase Switching",
        },
        icon="mdi:run",
    ),
    # ---- 0x001E  Fault code u32 (GEN2 doc: FaultCode) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Fault Code",
        key="fault_code",
        register=0x1E,
        register_type=REG_INPUT,
        register_data_type=REGISTER_U32,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Fault Description",
        key="fault_description",
        register=-1,
        value_function=value_function_fault_description,
        depends_on=["fault_code"],
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Serial Number",
        key="ems_serial_number",
        device_group="ems",
        register=0xA000,
        register_type=REG_INPUT,
        newblock=True,
        allowedtypes=GEN2 | EMS_TYPE,
        register_data_type=REGISTER_STR,
        order32="big",
        wordcount=7,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:barcode",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Model ID",
        key="ems_model_id",
        device_group="ems",
        register=0xA007,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        register_data_type=REGISTER_STR,
        order32="big",
        wordcount=8,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:identifier",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Firmware Version",
        key="ems_firmware_version",
        device_group="ems",
        register=0xA00F,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        register_data_type=REGISTER_U16,
        scale=value_function_firmware_decimal_hundredths,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:numeric",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Active Power",
        key="ems_active_power",
        device_group="ems",
        register=0xA010,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X1 | EMS_TYPE,
        register_data_type=REGISTER_S16,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Active Power L1",
        key="ems_active_power_l1",
        device_group="ems",
        register=0xA010,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X3 | EMS_TYPE,
        register_data_type=REGISTER_S16,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Active Power L2",
        key="ems_active_power_l2",
        device_group="ems",
        register=0xA011,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X3 | EMS_TYPE,
        register_data_type=REGISTER_S16,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Active Power L3",
        key="ems_active_power_l3",
        device_group="ems",
        register=0xA012,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X3 | EMS_TYPE,
        register_data_type=REGISTER_S16,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Active Power Total",
        key="ems_active_power_total",
        device_group="ems",
        register=0xA013,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        register_data_type=REGISTER_S16,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Max Allowed Charge Power",
        key="ems_max_allowed_charge_power",
        device_group="ems",
        register=0xA014,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Max Allowed Discharge Power",
        key="ems_max_allowed_discharge_power",
        device_group="ems",
        register=0xA015,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Run Mode",
        key="ems_run_mode",
        device_group="ems",
        register=0xA016,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        scale={
            0: "Available",
            1: "Preparing",
            2: "Charging",
            3: "Finishing",
            4: "Faulted",
            5: "Unavailable",
            6: "Reserved",
            7: "Suspended EV",
            8: "Suspended EVSE",
            9: "Update",
            10: "Card Activation",
            11: "Start Delay",
            12: "Charge Paused",
            13: "Stopping",
            14: "Occupied",
            15: "Waiting for Response",
            16: "Discharging",
            17: "Phase Switching",
        },
        icon="mdi:run",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Plug State",
        key="ems_plug_state",
        device_group="ems",
        register=0xA017,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        scale={
            0: "Not Plugged In",
            1: "Plugged In",
            2: "Charging",
            3: "Invalid Voltage",
            4: "Ventilation Required",
        },
        icon="mdi:ev-plug-type2",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Manufacturer ID",
        key="ems_manufacturer_id",
        device_group="ems",
        register=0xA018,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        register_data_type=REGISTER_STR,
        order32="big",
        wordcount=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:factory",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Voltage",
        key="ems_voltage",
        device_group="ems",
        register=0xA01C,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X1 | EMS_TYPE,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Voltage L1",
        key="ems_voltage_l1",
        device_group="ems",
        register=0xA01C,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X3 | EMS_TYPE,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Voltage L2",
        key="ems_voltage_l2",
        device_group="ems",
        register=0xA01D,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X3 | EMS_TYPE,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Voltage L3",
        key="ems_voltage_l3",
        device_group="ems",
        register=0xA01E,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X3 | EMS_TYPE,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Current",
        key="ems_current",
        device_group="ems",
        register=0xA01F,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X1 | EMS_TYPE,
        register_data_type=REGISTER_S16,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Current L1",
        key="ems_current_l1",
        device_group="ems",
        register=0xA01F,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X3 | EMS_TYPE,
        register_data_type=REGISTER_S16,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Current L2",
        key="ems_current_l2",
        device_group="ems",
        register=0xA020,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X3 | EMS_TYPE,
        register_data_type=REGISTER_S16,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Current L3",
        key="ems_current_l3",
        device_group="ems",
        register=0xA021,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | X3 | EMS_TYPE,
        register_data_type=REGISTER_S16,
        scale=0.01,
        rounding=2,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Min Allowed Charge Power",
        key="ems_min_allowed_charge_power",
        device_group="ems",
        register=0xA022,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Battery Capacity",
        key="ems_battery_capacity",
        device_group="ems",
        register=0xA023,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        icon="mdi:battery-high",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Battery SoC",
        key="ems_battery_soc",
        device_group="ems",
        register=0xA024,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        rounding=0,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charged Energy Total",
        key="ems_charged_energy_total",
        device_group="ems",
        register=0xA025,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        register_data_type=REGISTER_U32,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Temperature",
        key="ems_temperature",
        device_group="ems",
        register=0xA027,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        register_data_type=REGISTER_S16,
        rounding=0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Fault Code",
        key="ems_fault_code",
        device_group="ems",
        register=0xA028,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        register_data_type=REGISTER_U32,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Fault Description",
        key="ems_fault_description",
        device_group="ems",
        register=-1,
        allowedtypes=GEN2 | EMS_TYPE,
        value_function=value_function_ems_fault_description,
        depends_on=["ems_fault_code"],
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charging Phase",
        key="ems_charging_phase",
        device_group="ems",
        register=0xA02A,
        register_type=REG_INPUT,
        allowedtypes=GEN2 | EMS_TYPE,
        scale={0: "Idle", 1: "Single-Phase", 2: "Three-Phase"},
        icon="mdi:sine-wave",
    ),
    # ---- 0x0020  Cable type (GEN2 doc: TypeCase, 0=CaseB, 1=CaseC) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Case Type",
        key="case_type",
        register=0x20,
        register_type=REG_INPUT,
        scale={
            0: "Case B",
            1: "Case C",
        },
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:ev-plug-type2",
    ),
    # ---- 0x0021  Power rating (GEN2 V1.00 mapping, a superset of the GEN1 values) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Power Rating",
        key="power_rating",
        register=0x21,
        register_type=REG_INPUT,
        scale={
            0: "7 kW",
            1: "11 kW",
            2: "22 kW",
            3: "6 kW",
            4: "4.6 kW",
            5: "7.6 kW",
            6: "9.6 kW",
            7: "11.5 kW",
        },
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:lightning-bolt",
    ),
    # ---- 0x0022  Phase count (GEN2 doc: TypePhase, 0=Single, 1=Three) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Phase Type",
        key="phase_type",
        register=0x22,
        register_type=REG_INPUT,
        scale={
            0: "Single Phase",
            1: "Three Phase",
        },
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:sine-wave",
    ),
    # ---- 0x0023  GEN1: TypeCharger (0=Home, 1=OCPP) / GEN2: EVSE_Scene (0=PV,1=Standard,2=OCPP) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charger Type",
        key="model_type",
        register=0x23,
        register_type=REG_INPUT,
        allowedtypes=GEN1,
        scale={
            0: "Home Edition",
            1: "Commercial Edition",
            2: "Integrated Edition",
        },
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Application Scene",
        key="model_type",
        register=0x23,
        register_type=REG_INPUT,
        allowedtypes=GEN2,
        scale={
            0: "Solar Scene",
            1: "Standard Scene",
            2: "OCPP Scene",
        },
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:dip-switch",
    ),
    # ---- 0x0024  Screen fitted (GEN1 doc only; not in GEN2 doc but present on device) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Screen Fitted",
        key="screen_fitted",
        register=0x24,
        register_type=REG_INPUT,
        scale={
            0: "No",
            1: "Yes",
        },
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:monitor",
    ),
    # ---- 0x0025  Firmware version (GEN2 doc: FirmwareVersion) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Firmware Version",
        key="firmware_version",
        register=0x25,
        register_type=REG_INPUT,
        register_data_type=REGISTER_U16,
        scale=value_function_firmware_decimal_hundredths,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:numeric",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Module Version",
        key="module_version",
        register=0x71,
        register_type=REG_INPUT,
        newblock=True,
        allowedtypes=GEN2,
        register_data_type=REGISTER_U16,
        scale=value_function_firmware_decimal_hundredths,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:numeric",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="LCD Version",
        key="lcd_version",
        register=0x73,
        register_type=REG_INPUT,
        newblock=True,
        allowedtypes=GEN2,
        register_data_type=REGISTER_U16,
        scale=value_function_firmware_decimal_hundredths,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:numeric",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Modbus Version",
        key="modbus_version",
        register=0x78,
        register_type=REG_INPUT,
        newblock=True,
        allowedtypes=GEN2,
        register_data_type=REGISTER_U16,
        scale=value_function_firmware_decimal_hundredths,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:numeric",
    ),
    # ---- 0x0026  Network status (0=Offline, 1=Online) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Network Status",
        key="net_connected",
        register=0x26,
        register_type=REG_INPUT,
        scale={
            0: "Not Connected",
            1: "Connected",
        },
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
    ),
    # ---- 0x0027  Signal strength (GEN2 doc: RSSI, 1%) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="WiFi RSSI",
        key="rssi",
        register=0x27,
        register_type=REG_INPUT,
        rounding=0,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi-strength-2",
    ),
    # ---- 0x0028  Active charge phase (GEN2 doc: ChargePhase) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Wiring Phase",
        key="active_charge_phase",
        register=0x28,
        register_type=REG_INPUT,
        scale={
            0: "Three Phase",
            1: "L1 Phase",
            2: "L2 Phase",
            3: "L3 Phase",
        },
        icon="mdi:cable-data",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---- 0x0029  Unbalanced power (GEN2 doc: UnbalancedPower, 1W) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Unbalanced Power Limit",
        key="unbalanced_power_limit",
        register=0x29,
        register_type=REG_INPUT,
        allowedtypes=X1,
        rounding=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:scale-unbalanced",
    ),
    # ---- 0x002A  Unbalanced switch (GEN2 doc: UnbalancedSwitch, 0=Off, 1=On) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Phase Unbalance",
        key="phase_unbalance",
        register=0x2A,
        register_type=REG_INPUT,
        allowedtypes=X1,
        scale={
            0: "Off",
            1: "On",
        },
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:scale-unbalanced",
    ),
    # ---- 0x002B  Charging duration u32 (GEN2 doc: Charging_time, 1s) ----
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charging Duration",
        key="charge_duration",
        register=0x2B,
        register_type=REG_INPUT,
        register_data_type=REGISTER_U32,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
        rounding=0,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        icon="mdi:timer",
    ),
    # ---- 0x002D-0x0030 are second-generation-only: SolaX support confirmed they do
    # not exist on Gen1 chargers and will be removed from the Gen1 protocol document.
    SolaXEVChargerModbusSensorEntityDescription(
        name="Lock State",
        key="lock_state",
        register=0x2D,
        register_type=REG_INPUT,
        allowedtypes=GEN2,
        scale={
            0: "Unlocked",
            1: "Locked",
        },
        icon="mdi:lock",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Main Breaker Limit State",
        key="mainbrk_limit",
        register=0x2E,
        register_type=REG_INPUT,
        allowedtypes=GEN2,
        scale={
            0: "Not Limited",
            1: "Limited, Charging",
            2: "Stopped Charging",
        },
        icon="mdi:car-speed-limiter",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Random Delay State",
        key="delay_state",
        register=0x2F,
        register_type=REG_INPUT,
        allowedtypes=GEN2,
        scale={
            0: "Not in Delay",
            1: "In Random Delay",
        },
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:progress-clock",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Ban State",
        key="ban_state",
        register=0x30,
        register_type=REG_INPUT,
        allowedtypes=GEN2,
        scale={
            0: "Okay",
            1: "Charge Prohibited",
        },
        icon="mdi:hand-back-left",
    ),
]

# ============================ plugin declaration =================================================


@dataclass(kw_only=True)
class solax_ev_charger_plugin(plugin_base):
    '''
    def isAwake(self, datadict: dict[str, Any]) -> bool:
        """ determine if inverter is awake based on polled datadict"""
        return (datadict.get('run_mode', None) == 'Normal Mode')

    def wakeupButton(self) -> str:
        """ in order to wake up  the inverter , press this button """
        return 'battery_awaken'
    '''

    async def async_determineInverterType(self, hub: Any, configdict: dict[str, Any]) -> int:
        _LOGGER.info("%s: trying to determine inverter type", hub.name)
        _LOGGER.debug("%s: Reading serial number to determine inverter type", hub.name)
        seriesnumber = await async_read_serialnr(hub, 0x600)
        _LOGGER.debug("%s: Received serial number: %s", hub.name, seriesnumber)
        if not seriesnumber:
            _LOGGER.error("%s: cannot find serial number for EV Charger", hub.name)
            seriesnumber = "unknown"

        fw_version = await async_read_firmware(hub, 0x25)
        # Version source for modbus_min/modbus_max gating:
        #   GEN1 - firmware version (0x25), the key of the V3.6 version-matching table.
        #   GEN2 - Modbus protocol version (0x78), replaced below once the generation is known.
        hub.modbus_protocol_version = int(round(fw_version * 100)) if fw_version is not None else None

        # derive invertertupe from seriesnumber
        _LOGGER.debug("%s: Determining inverter type from serial number prefix", hub.name)
        invertertype = 0
        self.inverter_model = None
        if seriesnumber.startswith("C107"):
            invertertype = X1 | POW7 | GEN1  # 7kW EV Single Phase Gen1 (X1-GEN1-7kW*)
            self.inverter_model = "X1-EVC-7kW"
            self.hardware_version = "Gen1"
            _LOGGER.debug(
                "%s: Matched C107 - X1 | POW7 | EVC (7kW EV Single Phase Gen1), type=0x%x, model=%s, hw=%s",
                hub.name,
                invertertype,
                self.inverter_model,
                self.hardware_version,
            )
        elif seriesnumber.startswith("C311"):
            # Default to GEN1 for backward compatibility
            _LOGGER.debug("%s: C311 series number detected: %s", hub.name, seriesnumber)
            invertertype = X3 | POW11 | GEN1  # 11kW EV Three Phase Gen1 (X3-GEN1-11kW*)
            self.inverter_model = "X3-EVC-11kW"
            _LOGGER.debug("%s: C311 model set to: %s", hub.name, self.inverter_model)
            self.hardware_version = "Gen1"

            if fw_version is not None and fw_version >= 7.0:
                # Upgrade to GEN2 - has GEN2 firmware
                invertertype = X3 | POW11 | GEN2
                self.hardware_version = "Gen1 (Gen2 FW)"
                _LOGGER.info("%s: C311 detected with HAC firmware v%.2f, enabling HAC features", hub.name, fw_version)

            _LOGGER.debug(
                "%s: Matched C311 - X3 | POW11 | type=0x%x, model=%s, hw=%s", hub.name, invertertype, self.inverter_model, self.hardware_version
            )
        elif seriesnumber.startswith("C322"):
            # Default to GEN1 for backward compatibility
            _LOGGER.debug("%s: C322 series number detected: %s", hub.name, seriesnumber)
            invertertype = X3 | POW22 | GEN1  # 22kW EV Three Phase Gen1 (X3-GEN1-22kW*)
            self.inverter_model = "X3-EVC-22kW"
            _LOGGER.debug("%s: C322 model set to: %s", hub.name, self.inverter_model)
            self.hardware_version = "Gen1"

            if fw_version is not None and fw_version >= 7.0:
                # Upgrade to GEN2 - has GEN2 firmware
                invertertype = X3 | POW22 | GEN2
                self.hardware_version = "Gen1 (Gen2 FW)"
                _LOGGER.info("%s: C322 detected with HAC firmware v%.2f, enabling HAC features", hub.name, fw_version)

            _LOGGER.debug(
                "%s: Matched C322 - X3 | POW22 | type=0x%x, model=%s, hw=%s", hub.name, invertertype, self.inverter_model, self.hardware_version
            )
        elif len(seriesnumber) >= 5 and seriesnumber.startswith("5"):
            model_code = seriesnumber[1:3]
            power_code = seriesnumber[3:5]

            model_map = {
                "02": ("X1-HAC", X1),
                "03": ("X3-HAC", X3),
                "04": ("A1-HAC", X1),
                "05": ("J1-HAC", X1),
                "06": ("X1-HAC-S", X1),
                "07": ("X3-HAC-S", X3),
                "08": ("C1-HAC", X1),
                "09": ("C3-HAC", X3),
            }

            power_map = {
                "04": ("4.6kW", POW4),
                "07": ("7.2kW", POW7),
                "0B": ("11kW", POW11),
                "0M": ("22kW", POW22),
            }

            model_info = model_map.get(model_code)
            power_info = power_map.get(power_code)
            if model_info and power_info:
                model_prefix, phase_mask = model_info
                power_label, power_mask = power_info
                invertertype = phase_mask | power_mask | GEN2
                self.inverter_model = f"{model_prefix} {power_label}"
                self.hardware_version = "Gen2"
                _LOGGER.debug(
                    "%s: Parsed serial codes model=%s power=%s -> type=0x%x, model=%s, hw=%s",
                    hub.name,
                    model_code,
                    power_code,
                    invertertype,
                    self.inverter_model,
                    self.hardware_version,
                )
        # add cases here

        if invertertype == 0:
            _LOGGER.error("unrecognized inverter type - serial number : %s", seriesnumber)
            _LOGGER.debug("%s: No match found for serial number prefix, returning type=0", hub.name)

        # Parallel capability via 0x0107 (Is_support_parallel): 0xAA55 = supported.
        # The parallel entities need both the capability and the Parallel Mode option,
        # the same option that gates the parallel group on the inverter plugins.
        if invertertype & GEN2:
            try:
                version_data = await hub.async_read_input_registers(unit=hub._modbus_addr, address=0x0078, count=1)
                if not version_data.isError() and version_data.registers[0] > 0:
                    hub.modbus_protocol_version = version_data.registers[0]
                    _LOGGER.info("%s: HAC Modbus protocol version %.2f (0x0078) used for version gating", hub.name, version_data.registers[0] / 100)
                else:
                    _LOGGER.info("%s: 0x0078 unavailable, version gating falls back to the firmware version", hub.name)
            except Exception:
                _LOGGER.debug("%s: Could not read 0x0078", hub.name, exc_info=True)

        read_pm = configdict.get(CONF_READ_PM, DEFAULT_READ_PM)
        if read_pm:
            invertertype |= PM_OPTION_TYPE
        if configdict.get(CONF_READ_EMS, DEFAULT_READ_EMS):
            invertertype |= EMS_TYPE
        if configdict.get(CONF_READ_DATAHUB, DEFAULT_READ_DATAHUB):
            invertertype |= DATAHUB_TYPE
        try:
            parallel_data = await hub.async_read_input_registers(unit=hub._modbus_addr, address=0x0107, count=1)
            if not parallel_data.isError():
                val = parallel_data.registers[0]
                if val == 0xAA55 and read_pm:
                    invertertype |= PARALLEL_TYPE
                    _LOGGER.info("%s: parallel operation supported (0x0107=0x%04X) and Parallel Mode option enabled", hub.name, val)
                elif val == 0xAA55:
                    _LOGGER.info("%s: parallel operation supported (0x0107=0x%04X) but the Parallel Mode option is off", hub.name, val)
                else:
                    _LOGGER.debug("%s: parallel operation not supported (0x0107=0x%04X)", hub.name, val)
            else:
                _LOGGER.debug("%s: Could not read 0x0107 for parallel probe (Modbus error)", hub.name)
        except Exception:
            _LOGGER.debug("%s: Could not read parallel support register 0x0107", hub.name, exc_info=True)

        _LOGGER.debug("%s: Final inverter type determination: 0x%x, model=%s", hub.name, invertertype, self.inverter_model)
        return invertertype

    def matchInverterWithMask(
        self,
        inverterspec: Any,
        entitymask: Any,
        serialnumber: str = "not relevant",
        blacklist: list[str] | None = None,
    ) -> bool:
        # returns true if the entity needs to be created for an inverter
        _LOGGER.debug("matchInverterWithMask: inverterspec=0x%x, entitymask=0x%x, serialnumber=%s", inverterspec, entitymask, serialnumber)
        powmatch = ((inverterspec & entitymask & ALL_POW_GROUP) != 0) or (entitymask & ALL_POW_GROUP == 0)
        xmatch = ((inverterspec & entitymask & ALL_X_GROUP) != 0) or (entitymask & ALL_X_GROUP == 0)
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP) != 0) or (entitymask & ALL_GEN_GROUP == 0)
        featurematch = ((inverterspec & entitymask & ALL_FEATURE_GROUP) != 0) or (entitymask & ALL_FEATURE_GROUP == 0)
        _LOGGER.debug("matchInverterWithMask: powmatch=%s, xmatch=%s, genmatch=%s, featurematch=%s", powmatch, xmatch, genmatch, featurematch)
        blacklisted = False
        if blacklist:
            _LOGGER.debug("matchInverterWithMask: Checking blacklist: %s", blacklist)
            for start in blacklist:
                if serialnumber.startswith(start):
                    blacklisted = True
                    _LOGGER.debug("matchInverterWithMask: Serial number %s matches blacklist prefix %s", serialnumber, start)
        result = (xmatch and powmatch and genmatch and featurematch) and not blacklisted
        _LOGGER.debug("matchInverterWithMask: Final result: %s (blacklisted=%s)", result, blacklisted)
        return result

    def getModel(self, new_data: dict[str, Any]) -> str | None:
        return getattr(self, "inverter_model", None)

    def getSoftwareVersion(self, new_data: dict[str, Any]) -> str | None:
        fw = new_data.get("firmware_version")
        return f"ARM v{fw}" if fw is not None else None

    def getHardwareVersion(self, new_data: dict[str, Any]) -> str | None:
        return getattr(self, "hardware_version", None)


plugin_instance = solax_ev_charger_plugin(
    plugin_name="SolaX EV Charger",
    plugin_manufacturer="SolaX Power",
    SENSOR_TYPES=SENSOR_TYPES_MAIN,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=[
        BaseModbusSwitchEntityDescription(
            name="Electronic Lock",
            key="electronic_lock",
            register=0x615,
            sensor_key="electronic_lock",
            value_function=value_function_enable_disable,
            entity_category=EntityCategory.CONFIG,
            icon="mdi:lock",
        ),
        BaseModbusSwitchEntityDescription(
            name="Unbalanced Switch",
            key="unbalanced_switch",
            register=0x63D,
            modbus_min=111,
            allowedtypes=GEN1 | X1,
            sensor_key="unbalanced_switch",
            value_function=value_function_enable_disable,
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
            icon="mdi:scale-unbalanced",
        ),
        BaseModbusSwitchEntityDescription(
            name="Unbalanced Switch",
            key="unbalanced_switch",
            register=0x63D,
            allowedtypes=GEN2 | X1,
            sensor_key="unbalanced_switch",
            value_function=value_function_enable_disable,
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
            icon="mdi:scale-unbalanced",
        ),
        BaseModbusSwitchEntityDescription(
            name="Green 30s Delay",
            key="green_30s_delay",
            register=0x644,
            allowedtypes=GEN1,
            modbus_min=114,
            sensor_key="green_30s_delay",
            value_function=value_function_enable_disable,
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
            icon="mdi:timer-sand",
        ),
        BaseModbusSwitchEntityDescription(
            name="Green 30s Delay",
            key="green_30s_delay",
            register=0x644,
            allowedtypes=GEN2,
            sensor_key="green_30s_delay",
            value_function=value_function_enable_disable,
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
            icon="mdi:timer-sand",
        ),
        BaseModbusSwitchEntityDescription(
            name="Main Breaker Limit Switch",
            key="main_breaker_limit_switch",
            register=0x664,
            allowedtypes=GEN2,
            sensor_key="main_breaker_limit_switch",
            value_function=value_function_disable_enable,
            entity_category=EntityCategory.CONFIG,
            icon="mdi:electric-switch",
        ),
        BaseModbusSwitchEntityDescription(
            name="RFID Card Activation",
            key="rfid_card_activation",
            register=0x616,
            sensor_key="rfid_card_activation",
            value_function=value_function_enable_disable,
            entity_category=EntityCategory.CONFIG,
            icon="mdi:card-account-details",
        ),
    ],
    TIME_TYPES=TIME_TYPES,
    block_size=100,
    # order16=Endian.BIG,
    order32="little",
)
