import logging
from dataclasses import dataclass
from time import time

from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.number import NumberDeviceClass, NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
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
from homeassistant.helpers.entity import EntityCategory

from custom_components.solax_modbus.const import (
    REG_HOLDING,
    REG_INPUT,
    REGISTER_S16,
    REGISTER_S32,
    REGISTER_U16,
    REGISTER_U32,
    REGISTER_WORDS,
    WRITE_MULTI_MODBUS,
    BaseModbusButtonEntityDescription,
    BaseModbusNumberEntityDescription,
    BaseModbusSelectEntityDescription,
    BaseModbusSensorEntityDescription,
    plugin_base,
    value_function_firmware_decimal_hundredths,
    value_function_rtc,
    value_function_sync_rtc,
)

from .pymodbus_compat import DataType, convert_from_registers

_LOGGER = logging.getLogger(__name__)


# Debug helper for EV charger operations
def _debug_charger_setting(hub_name, setting_name, value, register=None, mode=None):
    """Log debug information about charger setting changes"""
    mode_info = f" (current mode: {mode})" if mode else ""
    reg_info = f" at register 0x{register:x}" if register else ""
    _LOGGER.debug(f"{hub_name}: EV Charger {setting_name} set to {value}{reg_info}{mode_info}")


""" ============================================================================================
bitmasks  definitions to characterize inverters, ogranized by group
these bitmasks are used in entitydeclarations to determine to which inverters the entity applies
within a group, the bits in an entitydeclaration will be interpreted as OR
between groups, an AND condition is applied, so all gruoups must match.
An empty group (group without active flags) evaluates to True.
example: GEN3 | GEN4 | X1 | X3 | EPS
means:  any inverter of type (GEN3 or GEN4) and (X1 or X3) and (EPS)
An entity can be declared multiple times (with different bitmasks) if the parameters are different for each inverter type
"""

GEN = 0x0001  # base generation for MIC, PV, AC
GEN1 = 0x0001
GEN2 = 0x0002
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

ALLDEFAULT = 0  # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub, address):
    _LOGGER.debug(f"{hub.name}: Reading serial number from address 0x{address:x}")
    res = None
    try:
        _LOGGER.debug(
            f"{hub.name}: Attempting to read holding registers at 0x{address:x}, count=7, unit={hub._modbus_addr}"
        )
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=7)
        if not inverter_data.isError():
            _LOGGER.debug(f"{hub.name}: Successfully read registers: {inverter_data.registers[0:7]}")
            raw = convert_from_registers(inverter_data.registers[0:7], DataType.STRING, "big")
            _LOGGER.debug(f"{hub.name}: Converted raw data: {raw} (type: {type(raw)})")
            res = raw.decode("ascii", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            hub.seriesnumber = res
            _LOGGER.debug(f"{hub.name}: Decoded serial number: {res}")
        else:
            _LOGGER.debug(f"{hub.name}: Register read returned error: {inverter_data}")
    except Exception as ex:
        _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x}", exc_info=True)
        _LOGGER.debug(f"{hub.name}: Exception type: {type(ex).__name__}, message: {ex}")
    if not res:
        _LOGGER.warning(
            f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed"
        )
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number before potential swap: {res}")
    return res


async def async_read_firmware(hub, address=0x25):
    """Read firmware version from input register.

    Args:
        hub: The modbus hub instance
        address: Register address (default 0x25)

    Returns:
        float: Firmware version (e.g., 7.07) or None on failure
    """
    _LOGGER.debug(f"{hub.name}: Reading firmware version from address 0x{address:x}")
    res = None
    try:
        _LOGGER.debug(
            f"{hub.name}: Attempting to read input registers at 0x{address:x}, count=1, unit={hub._modbus_addr}"
        )
        fw_data = await hub.async_read_input_registers(unit=hub._modbus_addr, address=address, count=1)
        if not fw_data.isError():
            fw_raw = fw_data.registers[0]
            res = fw_raw / 100.0  # Decimal hundredths (e.g., 707 → 7.07)
            _LOGGER.debug(f"{hub.name}: Successfully read firmware: raw={fw_raw}, version={res:.2f}")
        else:
            _LOGGER.debug(f"{hub.name}: Register read returned error: {fw_data}")
    except Exception as ex:
        _LOGGER.warning(f"{hub.name}: attempt to read firmware failed at 0x{address:x}", exc_info=True)
        _LOGGER.debug(f"{hub.name}: Exception type: {type(ex).__name__}, message: {ex}")
    if not res:
        _LOGGER.debug(f"{hub.name}: reading firmware from address 0x{address:x} failed")
    return res


# =================================================================================================


@dataclass
class SolaXEVChargerModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaXEVChargerModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaXEVChargerModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaXEVChargerModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    # order16: int = Endian.BIG
    order32: str | None = None  # optional per-sensor 32-bit word order override
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING


# ====================================== Computed value functions  =================================================

# ================================= Button Declarations ============================================================

BUTTON_TYPES = [
    SolaXEVChargerModbusButtonEntityDescription(
        name="Sync RTC",
        key="sync_rtc",
        register=0x61E,
        write_method=WRITE_MULTI_MODBUS,
        icon="mdi:home-clock",
        value_function=value_function_sync_rtc,
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
        name="Datahub Charge Current",
        key="datahub_charge_current",
        register=0x624,
        allowedtypes=GEN1,  # GEN1 only - not available on GEN2
        fmt="f",
        native_min_value=6,
        native_max_value=32,
        native_step=0.1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Charge Current",
        key="charge_current",
        register=0x628,
        fmt="f",
        native_min_value=6,
        native_max_value=32,
        native_step=0.1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Max Charge Current",
        key="max_charge_current",
        register=0x668,
        allowedtypes=GEN2,
        fmt="f",
        native_min_value=6,
        native_max_value=32,
        native_step=0.1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
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
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
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
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Start Charge Mode",
        key="start_charge_mode",
        register=0x610,
        allowedtypes=GEN2,
        option_dict={
            0: "Plug & Charge",
            1: "RFID to Charge",
            2: "App start",
        },
        icon="mdi:lock",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Start Charge Mode",
        key="start_charge_mode",
        register=0x610,
        allowedtypes=GEN1,
        option_dict={
            0: "Plug & Charge",
            1: "RFID to Charge",
        },
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
        name="Device Lock",
        key="device_lock",
        register=0x615,
        option_dict={
            0: "Unlock",
            1: "Lock",
        },
        icon="mdi:lock",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="RFID Program",
        key="rfid_program",
        register=0x616,
        option_dict={
            1: "Program New",
            0: "Program Off",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="EVSE Scene",
        key="evse_scene",
        register=0x61C,
        allowedtypes=GEN2,
        option_dict={
            0: "PV mode",
            1: "Standard mode",
            2: "OCPP mode",
        },
        icon="mdi:dip-switch",
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
        icon="mdi:dip-switch",
        allowedtypes=X3,
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Control Command",
        key="control_command",
        register=0x627,
        option_dict={
            1: "Available",
            2: "Unavailable",
            3: "Stop charging",
            4: "Start Charging",
            5: "Reserve",
            6: "Cancel Reservation",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="EVSE Mode",
        key="evse_mode",
        register=0x669,
        allowedtypes=GEN2,
        option_dict={
            0: "Fast",
            1: "ECO",
            2: "Green",
        },
        icon="mdi:dip-switch",
    ),
]

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES_MAIN: list[SolaXEVChargerModbusSensorEntityDescription] = [
    ###
    #
    # Holding
    #
    ###
    SolaXEVChargerModbusSensorEntityDescription(
        name="Meter Setting",
        key="meter_setting",
        register=0x60C,
        scale={
            0: "External CT",
            1: "External Meter",
            2: "Inverter",
        },
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:meter-electric",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        register=0x60D,
        scale={
            0: "Stop",
            1: "Fast",
            2: "ECO",
            3: "Green",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="ECO Gear",
        key="eco_gear",
        register=0x60E,
        scale={
            1: "6A",
            2: "10A",
            3: "16A",
            4: "20A",
            5: "25A",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Green Gear",
        key="green_gear",
        register=0x60F,
        scale={
            1: "3A",
            2: "6A",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Boost Mode",
        key="boost_mode",
        register=0x613,
        scale={
            0: "Normal",
            1: "Timer Boost",
            2: "Smart Boost",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Device Lock",
        key="device_lock",
        register=0x615,
        scale={
            0: "Unlock",
            1: "Lock",
        },
        entity_registry_enabled_default=False,
        icon="mdi:lock",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="RFID Program",
        key="rfid_program",
        register=0x616,
        scale={
            1: "Program New",
            0: "Program Off",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="EVSE Scene",
        key="evse_scene",
        register=0x61C,
        allowedtypes=GEN2,
        scale={
            0: "PV mode",
            1: "Standard mode",
            2: "OCPP mode",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="RTC",
        key="rtc",
        register=0x61E,
        unit=REGISTER_WORDS,
        wordcount=6,
        scale=value_function_rtc,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:clock",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Datahub Charge Current",
        key="datahub_charge_current",
        register=0x624,
        allowedtypes=GEN1,  # GEN1 only - not available on GEN2
        scale=0.01,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Phase",
        key="charge_phase",
        register=0x625,
        scale={
            0: "Three Phase",
            1: "L1 Phase",
            2: "L2 Phase",
            3: "L3 Phase",
        },
        allowedtypes=X3,
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current",
        key="charge_current",
        register=0x628,
        scale=0.01,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Control Command",
        key="control_command",
        register=0x627,
        scale={
            1: "Available",
            2: "Unavailable",
            3: "Stop charging",
            4: "Start Charging",
            5: "Reserve",
            6: "Cancel the Reservation",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="EVSE Mode",
        key="evse_mode",
        register=0x669,
        allowedtypes=GEN2,
        scale={
            0: "Fast",
            1: "ECO",
            2: "Green",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    ###
    #
    # Input
    #
    ###
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage",
        key="charge_voltage",
        register=0x0,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        allowedtypes=X1,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage L1",
        key="charge_voltage_l1",
        register=0x0,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage L2",
        key="charge_voltage_l2",
        register=0x1,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage L3",
        key="charge_voltage_l3",
        register=0x2,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge PE Voltage",
        key="charge_pe_voltage",
        register=0x3,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current",
        key="charge_current",
        register=0x4,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X1,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L1",
        key="charge_current_l1",
        register=0x4,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L2",
        key="charge_current_l2",
        register=0x5,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L3",
        key="charge_current_l3",
        register=0x6,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge PE Current",
        key="charge_pe_current",
        register=0x7,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power",
        key="charge_power",
        register=0x8,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X1,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L1",
        key="charge_power_l1",
        register=0x8,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L2",
        key="charge_power_l2",
        register=0x9,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L3",
        key="charge_power_l3",
        register=0xA,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power Total",
        key="charge_power_total",
        register=0xB,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency",
        key="charge_frequency",
        register=0xC,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        allowedtypes=X1,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency L1",
        key="charge_frequency_l1",
        register=0xC,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency L2",
        key="charge_frequency_l2",
        register=0xD,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency L3",
        key="charge_frequency_l3",
        register=0xE,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
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
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Added - Cumulative",
        key="charge_added_cum",
        register=0x10,
        register_type=REG_INPUT,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        allowedtypes=GEN2,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Added Total",
        key="charge_added_total",
        register=0x619,
        register_type=REG_HOLDING,
        unit=REGISTER_U32,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        allowedtypes=(GEN1 | GEN2),  # Works on all charger types (GEN1 and GEN2)
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current",
        key="grid_current",
        register=0x12,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X1,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current L1",
        key="grid_current_l1",
        register=0x12,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current L2",
        key="grid_current_l2",
        register=0x13,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current L3",
        key="grid_current_l3",
        register=0x14,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power",
        key="grid_power",
        register=0x15,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X1,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power L1",
        key="grid_power_l1",
        register=0x15,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power L2",
        key="grid_power_l2",
        register=0x16,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power L3",
        key="grid_power_l3",
        register=0x17,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power Total",
        key="grid_power_total",
        register=0x18,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charger Temperature",
        key="charger_temperature",
        register=0x1C,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x1D,
        scale={
            0: "Available",
            1: "Preparing",
            2: "Charging",
            3: "Finishing",
            4: "Fault Mode",
            5: "Unavailable",
            6: "Reserved",
            7: "Suspended EV",
            8: "Suspended EVSE",
            9: "Update",
            10: "RFID Activation",
            # 11-13 perhaps only seen in Gen2 EVC or in newer firmwares
            11: "Start delay",
            12: "Charge paused",
            13: "Stopping",
        },
        register_type=REG_INPUT,
        icon="mdi:run",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Fault code",
        key="fault_code",
        register=0x1E,
        register_type=REG_INPUT,
        icon="mdi:alert",
        allowedtypes=GEN2,
        unit=REGISTER_S32,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Firmware version",
        key="firmware_version",
        register=0x25,
        register_type=REG_INPUT,
        icon="mdi:numeric",
        allowedtypes=GEN2,
        unit=REGISTER_U16,
        scale=value_function_firmware_decimal_hundredths,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Network connected",
        key="net_connected",
        register=0x26,
        scale={
            0: "Not connected",
            1: "Connected",
        },
        register_type=REG_INPUT,
        icon="mdi:run",
        allowedtypes=GEN2,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="RSSI",
        key="rssi",
        register=0x27,
        register_type=REG_INPUT,
        icon="mdi:numeric",
        allowedtypes=GEN2,
        unit=REGISTER_S16,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charging duration",
        key="charge_duration",
        register=0x2B,
        register_type=REG_INPUT,
        icon="mdi:numeric",
        allowedtypes=GEN2,
        # Per SolaX docs 32-bit values are little-endian, but this register
        # is verifyably flipped on GEN2 devices, so override word order here.
        unit=REGISTER_S32,
        order32="big",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfTime.SECONDS,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Lock state",
        key="lock_state",
        register=0x2D,
        scale={
            0: "Unlocked",
            1: "Locked",
        },
        register_type=REG_INPUT,
        icon="mdi:lock",
        allowedtypes=GEN2,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Main breaker limit",
        key="mainbrk_limit",
        register=0x2E,
        scale={
            0: "Not limited",
            1: "Limited, charging",
            2: "Stopped charging",
        },
        register_type=REG_INPUT,
        icon="mdi:car-speed-limiter",
        allowedtypes=GEN2,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Random delay state",
        key="delay_state",
        register=0x2F,
        scale={
            0: "Not in delay",
            1: "In random delay",
        },
        register_type=REG_INPUT,
        icon="mdi:progess-clock",
        allowedtypes=GEN2,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Ban state",
        key="ban_state",
        register=0x30,
        scale={
            0: "Okay",
            1: "Charge prohibited",
        },
        register_type=REG_INPUT,
        icon="mdi:hand-back-left",
        allowedtypes=GEN2,
    ),
]

# ============================ plugin declaration =================================================


@dataclass
class solax_ev_charger_plugin(plugin_base):
    '''
    def isAwake(self, datadict):
        """ determine if inverter is awake based on polled datadict"""
        return (datadict.get('run_mode', None) == 'Normal Mode')

    def wakeupButton(self):
        """ in order to wake up  the inverter , press this button """
        return 'battery_awaken'
    '''

    async def async_determineInverterType(self, hub, configdict):
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        _LOGGER.debug(f"{hub.name}: Reading serial number to determine inverter type")
        seriesnumber = await async_read_serialnr(hub, 0x600)
        _LOGGER.debug(f"{hub.name}: Received serial number: {seriesnumber}")
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find serial number for EV Charger")
            seriesnumber = "unknown"

        # derive invertertupe from seriesnumber
        _LOGGER.debug(f"{hub.name}: Determining inverter type from serial number prefix")
        invertertype = 0
        self.inverter_model = None
        if seriesnumber.startswith("C107"):
            invertertype = X1 | POW7 | GEN1  # 7kW EV Single Phase Gen1 (X1-EVC-7kW*)
            self.inverter_model = "X1-EVC-7kW"
            self.hardware_version = "Gen1"
            _LOGGER.debug(
                f"{hub.name}: Matched C107 - X1 | POW7 | GEN1 (7kW EV Single Phase Gen1), type=0x{invertertype:x}, model={self.inverter_model}, hw={self.hardware_version}"
            )
        elif seriesnumber.startswith("C311"):
            # Default to GEN1 for backward compatibility
            _LOGGER.debug(f"{hub.name}: C311 series number detected: {seriesnumber}")
            invertertype = X3 | POW11 | GEN1  # 11kW EV Three Phase Gen1 (X3-EVC-11kW*)
            self.inverter_model = "X3-EVC-11kW"
            _LOGGER.debug(f"{hub.name}: C311 model set to: {self.inverter_model}")
            self.hardware_version = "Gen1"

            # Try to detect GEN2 firmware for hybrid hardware
            fw_version = await async_read_firmware(hub, 0x25)
            if fw_version is not None and fw_version >= 7.0:
                # Upgrade to GEN2 - has GEN2 firmware
                invertertype = X3 | POW11 | GEN2
                self.hardware_version = "Gen1 (GEN2 FW)"
                _LOGGER.info(f"{hub.name}: C311 detected with GEN2 firmware v{fw_version:.2f}, enabling GEN2 features")

            _LOGGER.debug(
                f"{hub.name}: Matched C311 - X3 | POW11 | type=0x{invertertype:x}, model={self.inverter_model}, hw={self.hardware_version}"
            )
        elif seriesnumber.startswith("C322"):
            # Default to GEN1 for backward compatibility
            _LOGGER.debug(f"{hub.name}: C322 series number detected: {seriesnumber}")
            invertertype = X3 | POW22 | GEN1  # 22kW EV Three Phase Gen1 (X3-EVC-22kW*)
            self.inverter_model = "X3-EVC-22kW"
            _LOGGER.debug(f"{hub.name}: C322 model set to: {self.inverter_model}")
            self.hardware_version = "Gen1"

            # Try to detect GEN2 firmware for hybrid hardware
            fw_version = await async_read_firmware(hub, 0x25)
            if fw_version is not None and fw_version >= 7.0:
                # Upgrade to GEN2 - has GEN2 firmware
                invertertype = X3 | POW22 | GEN2
                self.hardware_version = "Gen1 (GEN2 FW)"
                _LOGGER.info(f"{hub.name}: C322 detected with GEN2 firmware v{fw_version:.2f}, enabling GEN2 features")

            _LOGGER.debug(
                f"{hub.name}: Matched C322 - X3 | POW22 | type=0x{invertertype:x}, model={self.inverter_model}, hw={self.hardware_version}"
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
                    f"{hub.name}: Parsed serial codes model={model_code} power={power_code} -> "
                    f"type=0x{invertertype:x}, model={self.inverter_model}, hw={self.hardware_version}"
                )
        # add cases here

        if invertertype == 0:
            _LOGGER.error(f"unrecognized inverter type - serial number : {seriesnumber}")
            _LOGGER.debug(f"{hub.name}: No match found for serial number prefix, returning type=0")
        _LOGGER.debug(
            f"{hub.name}: Final inverter type determination: 0x{invertertype:x}, model={self.inverter_model}"
        )
        return invertertype

    def matchInverterWithMask(self, inverterspec, entitymask, serialnumber="not relevant", blacklist=None):
        # returns true if the entity needs to be created for an inverter
        _LOGGER.debug(
            f"matchInverterWithMask: inverterspec=0x{inverterspec:x}, entitymask=0x{entitymask:x}, serialnumber={serialnumber}"
        )
        powmatch = ((inverterspec & entitymask & ALL_POW_GROUP) != 0) or (entitymask & ALL_POW_GROUP == 0)
        xmatch = ((inverterspec & entitymask & ALL_X_GROUP) != 0) or (entitymask & ALL_X_GROUP == 0)
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP) != 0) or (entitymask & ALL_GEN_GROUP == 0)
        _LOGGER.debug(f"matchInverterWithMask: powmatch={powmatch}, xmatch={xmatch}, genmatch={genmatch}")
        blacklisted = False
        if blacklist:
            _LOGGER.debug(f"matchInverterWithMask: Checking blacklist: {blacklist}")
            for start in blacklist:
                if serialnumber.startswith(start):
                    blacklisted = True
                    _LOGGER.debug(
                        f"matchInverterWithMask: Serial number {serialnumber} matches blacklist prefix {start}"
                    )
        result = (xmatch and powmatch and genmatch) and not blacklisted
        _LOGGER.debug(f"matchInverterWithMask: Final result: {result} (blacklisted={blacklisted})")
        return result

    def getModel(self, new_data):
        return getattr(self, "inverter_model", None)

    def getSoftwareVersion(self, new_data):
        fw = new_data.get("firmware_version")
        return f"ARM v{fw}" if fw is not None else None

    def getHardwareVersion(self, new_data):
        return getattr(self, "hardware_version", None)


plugin_instance = solax_ev_charger_plugin(
    plugin_name="SolaX EV Charger",
    plugin_manufacturer="SolaX Power",
    SENSOR_TYPES=SENSOR_TYPES_MAIN,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=[],
    block_size=100,
    # order16=Endian.BIG,
    order32="little",
)
