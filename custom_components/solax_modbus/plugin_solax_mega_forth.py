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
example: GEN3 | GEN4 | GEN5 | X1 | X3 | EPS
means:  any inverter of tyoe (GEN3 or GEN4 | GEN5) and (X1 or X3) and (EPS)
An entity can be declared multiple times (with different bitmasks) if the parameters are different for each inverter type
"""

GEN = 0x0001  # base generation for MIC, PV, AC
GEN2 = 0x0002
GEN3 = 0x0004
GEN4 = 0x0008
GEN5 = 0x0010
ALL_GEN_GROUP = GEN2 | GEN3 | GEN4 | GEN5 | GEN

X1 = 0x0100
X3 = 0x0200
ALL_X_GROUP = X1 | X3

PV = 0x0400  # Needs further work on PV Only Inverters
AC = 0x0800
HYBRID = 0x1000
MIC = 0x2000
MAX = 0x4000
ALL_TYPE_GROUP = PV | AC | HYBRID | MIC | MAX

EPS = 0x8000
ALL_EPS_GROUP = EPS

DCB = 0x10000  # dry contact box - gen4
ALL_DCB_GROUP = DCB

PM = 0x20000
ALL_PM_GROUP = PM

MPPT5 = 0x40000
MPPT6 = 0x80000
MPPT9 = 0x100000
MPPT12 = 0x200000
MPPT14 = 0x400000
ALL_MPPT_GROUP = MPPT5 | MPPT6 | MPPT9 | MPPT12 | MPPT14

ALLDEFAULT = 0  # should be equivalent to AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub, address):
    res = None
    inverter_data = None
    try:
        inverter_data = await hub.async_read_input_registers(unit=hub._modbus_addr, address=address, count=8)
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(16).decode("ascii")
            hub.seriesnumber = res
    except Exception as ex:
        _LOGGER.warning(
            f"{hub.name}: attempt to read serialnumber failed at 0x{address:x} data: {inverter_data}", exc_info=True
        )
    if not res:
        _LOGGER.warning(
            f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed"
        )
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number: {res}")
    return res


# =================================================================================================


@dataclass
class SolaxModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaxModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaxModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaXModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING


# ====================================== Computed value functions  =================================================

# ================================= Button Declarations ============================================================

BUTTON_TYPES = []

# ================================= Number Declarations ============================================================

MAX_CURRENTS = []

MAX_EXPORT = []

EXPORT_LIMIT_SCALE_EXCEPTIONS = []

NUMBER_TYPES = [
    SolaxModbusNumberEntityDescription(
        name="Active Power",
        key="active_power_control",
        register=0x2304,
        fmt="i",
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        scale=0.1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=MAX | GEN2,
    ),
    SolaxModbusNumberEntityDescription(
        name="Reactive Power",
        key="reactive_power_control",
        register=0x2305,
        fmt="i",
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        scale=0.1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=MAX | GEN2,
    ),
]

# ================================= Select Declarations ============================================================

SELECT_TYPES = []

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES_MAIN: list[SolaXModbusSensorEntityDescription] = [
    #####
    #
    # X3 MEGA G2
    #
    #
    #####
    #
    # Input Registers
    #
    #####
    SolaXModbusSensorEntityDescription(
        name="Model Type",
        key="model_type",
        register=0x12,
        register_type=REG_INPUT,
        unit=REGISTER_STR,
        wordcount=8,
        allowedtypes=MAX | GEN2,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="Software Version",
        key="software_version",
        register=0x22,
        register_type=REG_INPUT,
        unit=REGISTER_STR,
        wordcount=8,
        allowedtypes=MAX | GEN2,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Voltage L1",
        key="grid_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x100,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Voltage L2",
        key="grid_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x101,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Voltage L3",
        key="grid_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x102,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L1",
        key="inverter_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x103,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L2",
        key="inverter_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x104,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L3",
        key="inverter_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x105,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x106,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L1",
        key="inverter_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x180,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L2",
        key="inverter_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x181,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L3",
        key="inverter_current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x182,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Active Power Energy",
        key="active_power_energy",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x183,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Reactive Power",
        key="reactive_power",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x185,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Apparent Power",
        key="apparent_power",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x187,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Energy",
        key="today_s_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x189,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Energy",
        key="total_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x18A,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Power Factor",
        key="power_factor",
        native_unit_of_measurement=None,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x18F,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.001,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x202,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        allowedtypes=MAX | GEN2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x28B,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x28C,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x28D,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 1 Temperature",
        key="mppt_1_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x28F,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x292,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x293,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x294,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 2 Temperature",
        key="mppt_2_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x296,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x299,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x29A,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 3",
        key="pv_power_3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x29B,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 3 Temperature",
        key="mppt_3_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x29D,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 4",
        key="pv_voltage_4",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x2A0,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 4",
        key="pv_current_4",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x2A1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 4",
        key="pv_power_4",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2A2,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 4 Temperature",
        key="mppt_4_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2A4,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 5",
        key="pv_voltage_5",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x2A7,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9 | MPPT6 | MPPT5,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 5",
        key="pv_current_5",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x2A8,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9 | MPPT6 | MPPT5,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 5",
        key="pv_power_5",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2A9,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9 | MPPT6 | MPPT5,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 5 Temperature",
        key="mppt_5_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2AB,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9 | MPPT6 | MPPT5,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 6",
        key="pv_voltage_6",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x2AE,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9 | MPPT6,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 6",
        key="pv_current_6",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x2AF,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9 | MPPT6,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 6",
        key="pv_power_6",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2B0,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9 | MPPT6,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 6 Temperature",
        key="mppt_6_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2B2,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9 | MPPT6,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 7",
        key="pv_voltage_7",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x2B5,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 7",
        key="pv_current_7",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x2B6,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 7",
        key="pv_power_7",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2B7,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 7 Temperature",
        key="mppt_7_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2B9,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 8",
        key="pv_voltage_8",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x2BC,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 8",
        key="pv_current_8",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x2BD,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 8",
        key="pv_power_8",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2BE,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 8 Temperature",
        key="mppt_8_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2C0,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 9",
        key="pv_voltage_9",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x2C3,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 9",
        key="pv_current_9",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x2C4,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 9",
        key="pv_power_9",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2C5,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 9 Temperature",
        key="mppt_9_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2C7,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2 | MPPT12 | MPPT9,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 10",
        key="pv_voltage_10",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x2CA,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 10",
        key="pv_current_10",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x2CB,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 10",
        key="pv_power_10",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2CC,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2 | MPPT12,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 10 Temperature",
        key="mppt_10_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2CE,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2 | MPPT12,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 11",
        key="pv_voltage_11",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x2D1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 11",
        key="pv_current_11",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x2D2,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 11",
        key="pv_power_11",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2D3,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2 | MPPT12,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 11 Temperature",
        key="mppt_11_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2D5,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2 | MPPT12,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 12",
        key="pv_voltage_12",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x2D8,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 12",
        key="pv_current_12",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x2D9,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX | GEN2 | MPPT12,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 12",
        key="pv_power_12",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2DA,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2 | MPPT12,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT 12 Temperature",
        key="mppt_12_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2DC,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=MAX | GEN2 | MPPT12,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    #####
    #
    # Holding Registers
    #
    #####
    SolaXModbusSensorEntityDescription(
        key="active_power_control",
        register=0x2304,
        scale=0.1,
        allowedtypes=MAX | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="reactive_power_control",
        register=0x2305,
        scale=0.1,
        allowedtypes=MAX | GEN2,
        internal=True,
    ),
]

# ============================ plugin declaration =================================================


@dataclass
class solax_mega_forth_plugin(plugin_base):

    async def async_determineInverterType(self, hub, configdict):
        # global SENSOR_TYPES
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber = await async_read_serialnr(hub, 0x32)
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find any serial number(s)")
            seriesnumber = "unknown"

        # derive invertertupe from seriiesnumber
        if seriesnumber.startswith("X3G04"):
            invertertype = MAX | GEN2  # MAX G2
            self.inverter_model = "X3 - MEGA 40kW - G2"
        elif seriesnumber.startswith("X3G05"):
            invertertype = MAX | GEN2 | MPPT5  # MAX MEGA G2
            self.inverter_model = "X3- MEGA 50kW - G2"
        elif seriesnumber.startswith("X3G06"):
            invertertype = MAX | GEN2 | MPPT6  # MAX MEGA G2
            self.inverter_model = "X3- MEGA 60kW - G2"
        elif seriesnumber.startswith("X3G075"):
            invertertype = MAX | GEN2 | MPPT9  # MAX FORTH G2
            self.inverter_model = "X3- FORTH 75kW - G2"
        elif seriesnumber.startswith("X3G08"):
            invertertype = MAX | GEN2 | MPPT9  # MAX FORTH G2
            self.inverter_model = "X3- FORTH 80kW - G2"
        elif seriesnumber.startswith("X3G01"):
            invertertype = MAX | GEN2 | MPPT9  # MAX FORTH G2
            self.inverter_model = "X3- FORTH 100kW - G2"
        elif seriesnumber.startswith("X3G011"):
            invertertype = MAX | GEN2 | MPPT9  # MAX FORTH G2
            self.inverter_model = "X3- FORTH 110kW - G2"
        elif seriesnumber.startswith("X3G012"):
            invertertype = MAX | GEN2 | MPPT12  # MAX FORTH G2
            self.inverter_model = "X3- FORTH 120kW - G2"
        elif seriesnumber.startswith("X3G0125"):
            invertertype = MAX | GEN2 | MPPT12  # MAX FORTH G2
            self.inverter_model = "X3- FORTH 125kW - G2"
        elif seriesnumber.startswith("X3G013"):
            invertertype = MAX | GEN2 | MPPT12  # MAX FORTH G2
            self.inverter_model = "X3- FORTH 136kW - G2"
        elif seriesnumber.startswith("X3G015"):
            invertertype = MAX | GEN2 | MPPT12  # MAX FORTH G2
            self.inverter_model = "X3- FORTH 150kW - G2"
        elif seriesnumber.startswith("MAXMEG_G2"):
            invertertype = MAX | GEN2  # MAX MEGA G2
            self.inverter_model = "X3-MAX MEGA - G2"
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

        return invertertype

    def matchInverterWithMask(self, inverterspec, entitymask, serialnumber="not relevant", blacklist=None):
        # returns true if the entity needs to be created for an inverter
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP) != 0) or (entitymask & ALL_GEN_GROUP == 0)
        xmatch = ((inverterspec & entitymask & ALL_X_GROUP) != 0) or (entitymask & ALL_X_GROUP == 0)
        hybmatch = ((inverterspec & entitymask & ALL_TYPE_GROUP) != 0) or (entitymask & ALL_TYPE_GROUP == 0)
        epsmatch = ((inverterspec & entitymask & ALL_EPS_GROUP) != 0) or (entitymask & ALL_EPS_GROUP == 0)
        dcbmatch = ((inverterspec & entitymask & ALL_DCB_GROUP) != 0) or (entitymask & ALL_DCB_GROUP == 0)
        mpptmatch = ((inverterspec & entitymask & ALL_MPPT_GROUP) != 0) or (entitymask & ALL_MPPT_GROUP == 0)
        pmmatch = ((inverterspec & entitymask & ALL_PM_GROUP) != 0) or (entitymask & ALL_PM_GROUP == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist:
                if serialnumber.startswith(start):
                    blacklisted = True
        return (
            genmatch and xmatch and hybmatch and epsmatch and dcbmatch and mpptmatch and pmmatch
        ) and not blacklisted

    def getSoftwareVersion(self, new_data):
        return new_data.get("software_version", None)

    def getHardwareVersion(self, new_data):
        return new_data.get("hardware_version", None)

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
                    "generator_max_charge",
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


plugin_instance = solax_mega_forth_plugin(
    plugin_name="SolaX",
    plugin_manufacturer="SolaX Power",
    SENSOR_TYPES=SENSOR_TYPES_MAIN,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=[],
    block_size=100,
    order16=Endian.BIG,
    order32=Endian.BIG,
    auto_block_ignore_readerror=True,
)
