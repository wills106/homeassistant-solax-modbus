import logging
from dataclasses import dataclass
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
from custom_components.solax_modbus.const import *
from time import time

_LOGGER = logging.getLogger(__name__)

""" ============================================================================================
bitmasks  definitions to characterize inverters, ogranized by group
these bitmasks are used in entitydeclarations to determine to which inverters the entity applies
within a group, the bits in an entitydeclaration will be interpreted as OR
between groups, an AND condition is applied, so all gruoups must match.
An empty group (group without active flags) evaluates to True.
example: GEN3 | GEN4 | X1 | X3 | EPS
means:  any inverter of tyoe (GEN3 or GEN4) and (X1 or X3) and (EPS)
An entity can be declared multiple times (with different bitmasks) if the parameters are different for each inverter type
"""

A1 = 0x0001  # base generation for MIC, PV, AC
J1 = 0x0002
GEN3 = 0x0004
GEN4 = 0x0008
ALL_GEN_GROUP = A1 | J1 | GEN3 | GEN4

X1 = 0x0100
X3 = 0x0200
ALL_X_GROUP = X1 | X3

PV = 0x0400  # Needs further work on PV Only Inverters
AC = 0x0800
HYBRID = 0x1000
MIC = 0x2000
ALL_TYPE_GROUP = PV | AC | HYBRID | MIC

EPS = 0x8000
ALL_EPS_GROUP = EPS

DCB = 0x10000  # dry contact box - gen4
ALL_DCB_GROUP = DCB

PM = 0x20000
ALL_PM_GROUP = PM

ALLDEFAULT = 0  # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub, address):
    res = None
    try:
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=7)
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(14).decode("ascii")
            hub.seriesnumber = res
    except Exception as ex:
        _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x}", exc_info=True)
    if not res:
        _LOGGER.warning(
            f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed"
        )
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number before potential swap: {res}")
    return res


# =================================================================================================


@dataclass
class SolaxA1J1ModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaxA1J1ModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaxA1J1ModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaXA1J1ModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    # order16: int = Endian.BIG
    # order32: int = Endian.LITTLE
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING


# ====================================== Computed value functions  =================================================


def value_function_remotecontrol_recompute(initval, descr, datadict):
    power_control = datadict.get("remotecontrol_power_control", "Disabled")
    set_type = datadict.get("remotecontrol_set_type", "Set")  # other options did not work
    target = datadict.get("remotecontrol_active_power", 0)
    reactive_power = datadict.get("remotecontrol_reactive_power", 0)
    rc_duration = datadict.get("remotecontrol_duration", 20)
    ap_up = datadict.get("active_power_upper", 0)
    ap_lo = datadict.get("active_power_lower", 0)
    reap_up = datadict.get("reactive_power_upper", 0)
    reap_lo = datadict.get("reactive_power_lower", 0)
    import_limit = datadict.get("remotecontrol_import_limit", 20000)
    meas = datadict.get("measured_power", 0)
    pv = datadict.get("pv_power_total", 0)
    houseload_nett = datadict.get("inverter_power", 0) - meas
    houseload_brut = pv - datadict.get("battery_power_charge", 0) - meas
    if power_control == "Enabled Power Control":
        ap_target = target
    elif power_control == "Enabled Grid Control":  # alternative computation for Power Control
        if target < 0:
            ap_target = target - houseload_nett  # subtract house load
        else:
            ap_target = target - houseload_brut
        power_control = "Enabled Power Control"
    elif power_control == "Enabled Self Use":  # alternative computation for Power Control
        ap_target = 0 - houseload_nett  # subtract house load
        power_control = "Enabled Power Control"
    elif power_control == "Enabled Battery Control":  # alternative computation for Power Control
        ap_target = target - pv  # subtract house load and pv
        power_control = "Enabled Power Control"
    elif power_control == "Enabled Feedin Priority":  # alternative computation for Power Control
        if pv > houseload_nett:
            ap_target = 0 - pv + (houseload_brut - houseload_nett) * 1.20  # 0 - pv + (houseload_brut - houseload_nett)
        else:
            ap_target = 0 - houseload_nett
        power_control = "Enabled Power Control"
    elif power_control == "Enabled No Discharge":  # alternative computation for Power Control
        if pv <= houseload_nett:
            ap_target = 0 - pv + (houseload_brut - houseload_nett)  # 0 - pv + (houseload_brut - houseload_nett)
        else:
            ap_target = 0 - houseload_nett
        power_control = "Enabled Power Control"
    elif power_control == "Disabled":
        ap_target = target
        autorepeat_duration = 10  # or zero - stop autorepeat since it makes no sense when disabled
    old_ap_target = ap_target
    ap_target = min(ap_target, import_limit - houseload_brut)
    # _LOGGER.warning(f"peak shaving: old_ap_target:{old_ap_target} new ap_target:{ap_target} max: {import_limit-houseload} min:{-export_limit-houseload}")
    if old_ap_target != ap_target:
        _LOGGER.debug(
            f"peak shaving: old_ap_target:{old_ap_target} new ap_target:{ap_target} max: {import_limit-houseload_brut}"
        )
    res = [
        (
            "remotecontrol_power_control",
            power_control,
        ),
        (
            "remotecontrol_set_type",
            set_type,
        ),
        (
            "remotecontrol_active_power",
            max(min(ap_up, ap_target), ap_lo),
        ),
        (
            "remotecontrol_reactive_power",
            max(min(reap_up, reactive_power), reap_lo),
        ),
        (
            "remotecontrol_duration",
            rc_duration,
        ),
    ]
    if power_control == "Disabled":
        autorepeat_stop(datadict, descr.key)
    _LOGGER.debug(f"Evaluated remotecontrol_trigger: corrected/clamped values: {res}")
    return res


def value_function_remotecontrol_autorepeat_remaining(initval, descr, datadict):
    return autorepeat_remaining(datadict, "remotecontrol_trigger", time())


# for testing prevent_update only
# def value_function_test_prevent(initval, descr, datadict):
#    _LOGGER.warning(f"succeeded test prevent_update - datadict: {datadict['dummy_timed_charge_start_h']}")
#    return  None


# ================================= Button Declarations ============================================================

BUTTON_TYPES = []

# ================================= Number Declarations ============================================================

NUMBER_TYPES = []

# ================================= Select Declarations ============================================================

SELECT_TYPES = []

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES_MAIN: list[SolaXA1J1ModbusSensorEntityDescription] = [
    ###
    #
    # Holding
    #
    ###
    SolaXA1J1ModbusSensorEntityDescription(
        name="Series Number",
        key="seriesnumber",
        register=0x00,
        unit=REGISTER_STR,
        wordcount=7,
        allowedtypes=ALL_GEN_GROUP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:information",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Firmware Version Inverter Master",
        key="firmware_version_inverter_master",
        entity_registry_enabled_default=False,
        register=0x23,
        allowedtypes=J1,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Firmware Version Manager",
        key="firmware_version_manager",
        register=0x24,
        allowedtypes=J1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:information",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Firmware Version Manager Bootloader",
        key="firmware_version_manager_bootloader",
        register=0x25,
        allowedtypes=J1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:information",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Firmware Version Modbus",
        key="firmware_version_modbustcp",
        register=0x26,
        allowedtypes=J1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:information",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="RTC",
        key="rtc",
        register=0x27,
        unit=REGISTER_WORDS,
        wordcount=6,
        scale=value_function_rtc,
        allowedtypes=J1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:clock",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        register=0x2D,
        scale={
            0: "Economic Mode",
            1: "Green Mode",
            2: "Ease Use Mode",
            3: "Manual Mode",
        },
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Charger Start Time 1",
        key="charger_start_time_1",
        register=0x2E,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:battery-clock",
        scale=value_function_gen4time,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Charger Stop Time 1",
        key="charger_stop_time_1",
        register=0x2F,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:battery-clock",
        scale=value_function_gen4time,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Charger Start Time 2",
        key="charger_start_time_2",
        register=0x30,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:battery-clock",
        scale=value_function_gen4time,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Charger Stop Time 2",
        key="charger_stop_time_2",
        register=0x31,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:battery-clock",
        scale=value_function_gen4time,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="ForceCharge SOC - Economic",
        key="forcharge_soc_economic",
        native_unit_of_measurement=PERCENTAGE,
        register=0x33,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:battery-sync",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Discharger Start Time 1",
        key="discharger_start_time_1",
        register=0x34,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:battery-clock",
        scale=value_function_gen4time,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Discharger Stop Time 1",
        key="discharger_stop_time_1",
        register=0x35,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:battery-clock",
        scale=value_function_gen4time,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Discharger Start Time 2",
        key="discharger_start_time_2",
        register=0x36,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:battery-clock",
        scale=value_function_gen4time,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Discharger Stop Time 2",
        key="discharger_stop_time_2",
        register=0x37,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:battery-clock",
        scale=value_function_gen4time,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="ForceCharge SOC - Green",
        key="forcharge_soc_green",
        native_unit_of_measurement=PERCENTAGE,
        register=0x33,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:battery-sync",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Mute",
        key="eps_mute",
        register=0x52,
        scale={
            0: "Off",
            1: "On",
        },
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Language",
        key="language",
        register=0x53,
        scale={
            0: "Nihongo",
            1: "Chūgokugo",
        },
        allowedtypes=J1 | EPS,
        entity_registry_enabled_default=False,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Manual Mode",
        key="manual_mode",
        register=0x5A,
        scale={
            0: "Stop Charge and Discharge",
            1: "Force Charge",
            2: "Force Discharge",
        },
        allowedtypes=J1,
        entity_registry_enabled_default=False,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Power Factor Mode",
        key="power_factor_mode",
        register=0x5B,
        scale={0: "Off", 1: "Over Excited", 2: "Under Excited", 3: "Fix Q"},
        allowedtypes=J1,
        entity_registry_enabled_default=False,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Set Frequency",
        key="eps_set_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x67,
        scale={
            0: "50",
            1: "60",
        },
        allowedtypes=J1,
        entity_registry_enabled_default=False,
    ),
    ###
    #
    # Input
    #
    ###
    SolaXA1J1ModbusSensorEntityDescription(
        name="Inverter Voltage L1",
        key="inverter_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x0,
        register_type=REG_INPUT,
        rounding=1,
        scale=0.1,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Inverter Current L1",
        key="inverter_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1,
        register_type=REG_INPUT,
        rounding=1,
        scale=0.1,
        unit=REGISTER_S16,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Inverter Power L1",
        key="inverter_power_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Inverter Voltage L2",
        key="inverter_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x3,
        scale=0.1,
        register_type=REG_INPUT,
        rounding=1,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Inverter Current L2",
        key="inverter_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x4,
        register_type=REG_INPUT,
        rounding=1,
        scale=0.1,
        unit=REGISTER_S16,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Inverter Power L2",
        key="inverter_power_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x5,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Inverter Frequency L1",
        key="inverter_frequency_l1",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x6,
        register_type=REG_INPUT,
        rounding=2,
        scale=0.01,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Measured Power L1",
        key="measured_power_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x7,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Measured Power L2",
        key="measured_power_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x8,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x9,
        register_type=REG_INPUT,
        rounding=1,
        scale=0.1,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0xA,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1,
        icon="mdi:current-dc",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xB,
        register_type=REG_INPUT,
        allowedtypes=J1,
        icon="mdi:solar-power-variant",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xC,
        register_type=REG_INPUT,
        rounding=1,
        scale=0.1,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0xD,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1,
        icon="mdi:current-dc",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xE,
        register_type=REG_INPUT,
        allowedtypes=J1,
        icon="mdi:solar-power-variant",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xF,
        register_type=REG_INPUT,
        rounding=1,
        scale=0.1,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x10,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1,
        icon="mdi:current-dc",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="PV Power 3",
        key="pv_power_3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x11,
        register_type=REG_INPUT,
        allowedtypes=J1,
        icon="mdi:solar-power-variant",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Battery Voltage",
        key="battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x12,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Battery Current",
        key="battery_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x13,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_S16,
        allowedtypes=J1,
        icon="mdi:current-dc",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Battery Power",
        key="battery_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x14,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Battery Temperature",
        key="battery_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x16,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=J1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Battery Capacity",
        key="battery_capacity_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x17,
        register_type=REG_INPUT,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1A,
        register_type=REG_INPUT,
        allowedtypes=J1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Voltage L1",
        key="eps_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x1D,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Current L1",
        key="eps_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1E,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_S16,
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Power Active L1",
        key="eps_power_active_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1F,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Power L1",
        key="eps_power_l1",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x20,
        register_type=REG_INPUT,
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Voltage L2",
        key="eps_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x21,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Current L2",
        key="eps_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x22,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_S16,
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Power Active L2",
        key="eps_power_active_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x23,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Power L2",
        key="eps_power_l2",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x24,
        register_type=REG_INPUT,
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Frequency L1",
        key="eps_frequency_l1",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x25,
        register_type=REG_INPUT,
        rounding=2,
        scale=0.01,
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Today's Yield",
        key="today_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x2B,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Total Yield",
        key="total_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x2C,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:solar-power",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Total E Charge",
        key="total_e_charge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x2E,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:solar-power",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Today's E Charge",
        key="today_e_charge",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x30,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:solar-power",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Today's Battery Output Energy",
        key="today_battery_output_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x31,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1,
        icon="mdi:battery-arrow-down",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Total Battery Output Energy",
        key="total_battery_output_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x32,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,
        allowedtypes=J1,
        icon="mdi:battery-arrow-down",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Total Battery Input Energy",
        key="total_battery_input_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x34,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,
        allowedtypes=J1,
        icon="mdi:battery-arrow-ip",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Today's Battery Input Energy",
        key="today_battery_inpput_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x36,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1,
        icon="mdi:battery-arrow-up",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Today's EPS Yield",
        key="today_eps_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x37,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1 | EPS,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Total EPS Yield",
        key="total_eps_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x38,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,
        allowedtypes=J1 | EPS,
        entity_registry_enabled_default=False,
        icon="mdi:solar-power",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Total Solar Energy",
        key="total_solar_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x3A,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:solar-power",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Today's Solar Energy",
        key="today_solar_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x3C,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Today's Grid Export",
        key="today_grid_export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x3E,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,
        allowedtypes=J1,
        icon="mdi:home-export-outline",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Total Grid Export",
        key="total_grid_export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x40,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:home-export-outline",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Today's Grid Import",
        key="today_grid_import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x42,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,
        allowedtypes=J1,
        icon="mdi:home-import-outline",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Total Grid Import",
        key="total_grid_import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x44,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,
        allowedtypes=J1,
        entity_registry_enabled_default=False,
        icon="mdi:home-import-outline",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Grid Mode Runtime",
        key="grid_mode_runtime",
        native_unit_of_measurement=UnitOfTime.HOURS,
        register=0x46,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        allowedtypes=J1,
        icon="mdi:timer",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Mode Runtime",
        key="eps_mode_runtime",
        native_unit_of_measurement=UnitOfTime.HOURS,
        register=0x48,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=J1,
        icon="mdi:timer",
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="Inverter Frequency L2",
        key="inverter_frequency_l2",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x7E,
        register_type=REG_INPUT,
        rounding=2,
        scale=0.01,
        allowedtypes=J1,
    ),
    SolaXA1J1ModbusSensorEntityDescription(
        name="EPS Frequency L2",
        key="eps_frequency_l2",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x7F,
        register_type=REG_INPUT,
        rounding=2,
        scale=0.01,
        allowedtypes=J1 | EPS,
    ),
]

# ============================ plugin declaration =================================================


@dataclass
class solax_a1j1_plugin(plugin_base):

    def isAwake(self, datadict):
        """determine if inverter is awake based on polled datadict"""
        return datadict.get("run_mode", None) == "Normal Mode"

    def wakeupButton(self):
        """in order to wake up  the inverter , press this button"""
        return "battery_awaken"

    async def async_determineInverterType(self, hub, configdict):
        # global SENSOR_TYPES
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber = await async_read_serialnr(hub, 0x0)
        if not seriesnumber:
            seriesnumber = await async_read_serialnr(hub, 0x300)  # bug in Endian.LITTLE decoding?
            if seriesnumber and not seriesnumber.startswith(("M", "X")):
                ba = bytearray(seriesnumber, "ascii")  # convert to bytearray for swapping
                ba[0::2], ba[1::2] = ba[1::2], ba[0::2]  # swap bytes ourselves - due to bug in Endian.LITTLE ?
                res = str(ba, "ascii")  # convert back to string
                seriesnumber = res
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find serial number, even not for MIC")
            seriesnumber = "unknown"

        # derive invertertupe from seriiesnumber
        if seriesnumber.startswith("J1"):
            invertertype = HYBRID | J1  # J1 Hybrid - Unknown Serial
        elif seriesnumber.startswith("A1"):
            invertertype = HYBRID | A1  # A1 Hybrid - Unknown Serial
        # add cases here
        else:
            invertertype = 0
            _LOGGER.error(f"unrecognized inverter type - serial number : {seriesnumber}")

        if invertertype > 0:
            read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
            read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
            read_pm = configdict.get(CONF_READ_PM, DEFAULT_READ_PM)
            if read_eps:
                invertertype = invertertype | EPS
            if read_dcb:
                invertertype = invertertype | DCB
            if read_pm:
                invertertype = invertertype | PM

            if invertertype & MIC:
                self.SENSOR_TYPES = SENSOR_TYPES_MIC
            # else: self.SENSOR_TYPES = SENSOR_TYPES_MAIN

        return invertertype

    def matchInverterWithMask(self, inverterspec, entitymask, serialnumber="not relevant", blacklist=None):
        # returns true if the entity needs to be created for an inverter
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP) != 0) or (entitymask & ALL_GEN_GROUP == 0)
        xmatch = ((inverterspec & entitymask & ALL_X_GROUP) != 0) or (entitymask & ALL_X_GROUP == 0)
        hybmatch = ((inverterspec & entitymask & ALL_TYPE_GROUP) != 0) or (entitymask & ALL_TYPE_GROUP == 0)
        epsmatch = ((inverterspec & entitymask & ALL_EPS_GROUP) != 0) or (entitymask & ALL_EPS_GROUP == 0)
        dcbmatch = ((inverterspec & entitymask & ALL_DCB_GROUP) != 0) or (entitymask & ALL_DCB_GROUP == 0)
        pmmatch = ((inverterspec & entitymask & ALL_PM_GROUP) != 0) or (entitymask & ALL_PM_GROUP == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist:
                if serialnumber.startswith(start):
                    blacklisted = True
        return (genmatch and xmatch and hybmatch and epsmatch and dcbmatch and pmmatch) and not blacklisted

    def localDataCallback(self, hub):
        # adapt the read scales for export_control_user_limit if exception is configured
        # only called after initial polling cycle and subsequent modifications to local data
        _LOGGER.info(f"local data update callback")

        config_scale_entity = hub.numberEntities.get("config_export_control_limit_readscale")
        if config_scale_entity and config_scale_entity.enabled:
            new_read_scale = hub.data.get("config_export_control_limit_readscale")
            if new_read_scale != None:
                _LOGGER.info(
                    f"local data update callback for read_scale: {new_read_scale} enabled: {config_scale_entity.enabled}"
                )
                number_entity = hub.numberEntities.get("export_control_user_limit")
                sensor_entity = hub.sensorEntities.get("export_control_user_limit")
                if number_entity:
                    number_entity.entity_description = replace(
                        number_entity.entity_description,
                        read_scale=new_read_scale,
                    )
                if sensor_entity:
                    sensor_entity.entity_description = replace(
                        sensor_entity.entity_description,
                        read_scale=new_read_scale,
                    )

        config_maxexport_entity = hub.numberEntities.get("config_max_export")
        if config_maxexport_entity and config_maxexport_entity.enabled:
            new_max_export = hub.data.get("config_max_export")
            if new_max_export != None:
                for key in [
                    "remotecontrol_active_power",
                    "remotecontrol_import_limit",
                    "export_control_user_limit",
                    "external_generation_max_charge",
                ]:
                    number_entity = hub.numberEntities.get(key)
                    if number_entity:
                        number_entity._attr_native_max_value = new_max_export
                        # update description also, not sure whether needed or not
                        number_entity.entity_description = replace(
                            number_entity.entity_description,
                            native_max_value=new_max_export,
                        )
                        _LOGGER.info(f"local data update callback for entity: {key} new limit: {new_max_export}")


plugin_instance = solax_a1j1_plugin(
    plugin_name="SolaX A1-J1",
    plugin_manufacturer="SolaX Power",
    SENSOR_TYPES=SENSOR_TYPES_MAIN,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=[],
    block_size=100,
    order16=Endian.BIG,
    order32=Endian.LITTLE,
    auto_block_ignore_readerror=True,
)
