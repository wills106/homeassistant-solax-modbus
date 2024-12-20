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

MPPT3 = 0x40000
MPPT4 = 0x80000
MPPT5 = 0x100000
MPPT6 = 0x200000
MPPT10 = 0x400000
ALL_MPPT_GROUP = MPPT3 | MPPT4 | MPPT5 | MPPT6 | MPPT10

ALLDEFAULT = 0  # should be equivalent to AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub, address):
    res = None
    inverter_data = None
    try:
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=10)
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(20).decode("ascii")
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
class AlphaESSModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class AlphaESSModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class AlphaESSModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class AlphaESSModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
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
    AlphaESSModbusNumberEntityDescription(
        name="Discharge Minimum SOC",
        key="discharge_minimum_soc",
        register=0x850,
        fmt="i",
        native_min_value=10,
        native_max_value=99,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=GEN,
        icon="mdi:battery-sync",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Discharge Start 1 Hours",
        key="discharge_start_1_hours",
        register=0x851,
        fmt="i",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Discharge Stop 1 Hours",
        key="discharge_stop_1_hours",
        register=0x852,
        fmt="i",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Discharge Start 2 Hours",
        key="discharge_start_2_hours",
        register=0x853,
        fmt="i",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Discharge Stop 2 Hours",
        key="discharge_stop_2_hours",
        register=0x854,
        fmt="i",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Charge Target SOC",
        key="charge_target_soc",
        register=0x855,
        fmt="i",
        native_min_value=10,
        native_max_value=99,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=GEN,
        icon="mdi:battery-sync",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Charge Start 1 Hours",
        key="charge_start_1_hours",
        register=0x856,
        fmt="i",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Charge Stop 1 Hours",
        key="charge_stop_1_hours",
        register=0x857,
        fmt="i",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Charge Start 2 Hours",
        key="charge_start_2_hours",
        register=0x858,
        fmt="i",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Charge Stop 2 Hours",
        key="charge_stop_2_hours",
        register=0x859,
        fmt="i",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Discharge Start 1 Mins",
        key="discharge_start_1_mins",
        register=0x85A,
        fmt="i",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Discharge Stop 1 Mins",
        key="discharge_stop_1_mins",
        register=0x85B,
        fmt="i",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Discharge Start 2 Mins",
        key="discharge_start_2_mins",
        register=0x85C,
        fmt="i",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Discharge Stop 2 Mins",
        key="discharge_stop_2_mins",
        register=0x85D,
        fmt="i",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Charge Start 1 Mins",
        key="charge_start_1_mins",
        register=0x85E,
        fmt="i",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Charge Stop 1 Mins",
        key="charge_stop_1_mins",
        register=0x85F,
        fmt="i",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Charge Start 2 Mins",
        key="charge_start_2_mins",
        register=0x860,
        fmt="i",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
    AlphaESSModbusNumberEntityDescription(
        name="Charge Stop 2 Mins",
        key="charge_stop_2_mins",
        register=0x861,
        fmt="i",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=GEN,
        icon="mdi:battery-clock",
    ),
]

# ================================= Select Declarations ============================================================

SELECT_TYPES = [
    AlphaESSModbusSelectEntityDescription(
        name="System Mode",
        key="system_mode",
        register=0x805,
        option_dict={
            0: "AC Mode",
            1: "DC Mode",
            2: "Hybrid Mode",
        },
        allowedtypes=GEN,
        icon="mdi:dip-switch",
    ),
    AlphaESSModbusSelectEntityDescription(
        name="3Phase Unbalance Mode",
        key="3phase_unbalance_mode",
        register=0x811,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=GEN | X3,
        icon="mdi:dip-switch",
    ),
    AlphaESSModbusSelectEntityDescription(
        name="Time Preiod Control",
        key="time_preiod_control",
        register=0x84F,
        option_dict={
            0: "Disabled",
            1: "Charge - Enabled",
            2: "Discharge - Enabled",
            3: "Both - Enabled",
        },
        allowedtypes=GEN,
        icon="mdi:dip-switch",
    ),
]

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES_MAIN: list[AlphaESSModbusSensorEntityDescription] = [
    #####
    #
    # Holding Registers
    #
    #####
    AlphaESSModbusSensorEntityDescription(
        name="Grid Voltage",
        key="grid_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x14,
        allowedtypes=GEN | X1,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Grid Voltage L1",
        key="grid_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x14,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Grid Voltage L2",
        key="grid_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x15,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Grid Voltage L3",
        key="grid_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x16,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Grid Current",
        key="grid_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x17,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X1,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Grid Current L1",
        key="grid_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x17,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Grid Current L2",
        key="grid_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x18,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Grid Current L3",
        key="grid_current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x19,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1A,
        scale=0.01,
        rounding=2,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Active Power Energy",
        key="active_power_energy",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x21,
        unit=REGISTER_S32,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Reactive Power",
        key="reactive_power",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x29,
        unit=REGISTER_S32,
        allowedtypes=MAX | GEN2,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Battery Voltage",
        key="battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x100,
        scale=0.1,
        unit=REGISTER_S16,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Battery Current",
        key="battery_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x101,
        scale=0.1,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | GEN2,
        icon="mdi:current-dc",
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Battery SOC",
        key="battery_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x102,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Battery Capacity",
        key="battery_capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        register=0x119,
        scale=0.1,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Battery Input Energy",
        key="battery_input_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-arrow-up",
        register=0x120,
        unit=REGISTER_U32,
        scale=0.1,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Battery Output Energy",
        key="battery_output_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-arrow-down",
        register=0x122,
        unit=REGISTER_U32,
        scale=0.1,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Voltage",
        key="inverter_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x400,
        allowedtypes=GEN | X1,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Voltage L1",
        key="inverter_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x400,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Voltage L2",
        key="inverter_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x401,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Voltage L3",
        key="inverter_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x402,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Current",
        key="inverter_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x403,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X1,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Current L1",
        key="inverter_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x403,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Current L2",
        key="inverter_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x404,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Current L3",
        key="inverter_current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x405,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Power L1",
        key="inverter_power_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x406,
        unit=REGISTER_S32,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Power L2",
        key="inverter_power_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x408,
        unit=REGISTER_S32,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Power L3",
        key="inverter_power_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x40A,
        unit=REGISTER_S32,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Power",
        key="inverter_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x40C,
        unit=REGISTER_S32,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Voltage",
        key="eps_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x40E,
        allowedtypes=GEN | X1,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Voltage L1",
        key="eps_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x40E,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Voltage L2",
        key="eps_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x40F,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Voltage L3",
        key="eps_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x410,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Current",
        key="eps_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x411,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X1,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Current L1",
        key="eps_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x411,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Current L2",
        key="eps_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x412,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Current L3",
        key="eps_current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x413,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Power L1",
        key="eps_power_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x414,
        unit=REGISTER_S32,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Power L2",
        key="eps_power_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x416,
        unit=REGISTER_S32,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Power L3",
        key="eps_power_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x418,
        unit=REGISTER_S32,
        allowedtypes=GEN | X3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="EPS Power",
        key="eps_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x41A,
        unit=REGISTER_S32,
        allowedtypes=GEN | EPS,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Frequency",
        key="inverter_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x41C,
        scale=0.01,
        rounding=2,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x41D,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x41E,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN,
        icon="mdi:current-dc",
    ),
    AlphaESSModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x41F,
        unit=REGISTER_S32,
        allowedtypes=GEN,
        icon="mdi:solar-power-variant",
    ),
    AlphaESSModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x421,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x422,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN,
        icon="mdi:current-dc",
    ),
    AlphaESSModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x423,
        unit=REGISTER_S32,
        allowedtypes=GEN,
        icon="mdi:solar-power-variant",
    ),
    AlphaESSModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x425,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | MPPT3,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x426,
        scale=0.1,
        rounding=1,
        allowedtypes=GEN | MPPT3,
        icon="mdi:current-dc",
    ),
    AlphaESSModbusSensorEntityDescription(
        name="PV Power 3",
        key="pv_power_3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x427,
        unit=REGISTER_S32,
        allowedtypes=GEN | MPPT3,
        icon="mdi:solar-power-variant",
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x435,
        scale=0.1,
        allowedtypes=GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x440,
        scale={
            0: "Waiting",
            1: "Online",
            2: "UPS Mode",
            3: "Bypass Mode",
            4: "Fault Mode",
            5: "DC Mode",
            6: "Self Test Mode",
            7: "Check Mode",
            8: "Update Master",
            9: "Update Slave",
            10: "Update ARM",
        },
        allowedtypes=GEN,
        icon="mdi:run",
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Software Master Version",
        key="software_master_version",
        register=0x640,
        unit=REGISTER_STR,
        wordcount=5,
        allowedtypes=GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    AlphaESSModbusSensorEntityDescription(
        name="Software Slave Version",
        key="software_slave_version",
        register=0x645,
        unit=REGISTER_STR,
        wordcount=8,
        allowedtypes=GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    AlphaESSModbusSensorEntityDescription(
        key="system_mode",
        register=0x805,
        scale={
            0: "AC Mode",
            1: "DC Mode",
            2: "Hybrid Mode",
        },
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="3phase_unbalanced_mode",
        register=0x811,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=GEN | X3,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="time_preiod_control",
        register=0x84F,
        scale={
            0: "Disabled",
            1: "Charge - Enabled",
            2: "Discharge - Enabled",
            3: "Both - Enabled",
        },
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="discharge_minimum_soc",
        register=0x850,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="discharge_start_1_hours",
        register=0x851,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="discharge_stop_1_hours",
        register=0x852,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="discharge_start_2_hours",
        register=0x853,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="discharge_stop_2_hours",
        register=0x854,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="charge_target_soc",
        register=0x855,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="charge_start_1_hours",
        register=0x856,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="charge_stop_1_hours",
        register=0x857,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="charge_start_2_hours",
        register=0x858,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="charge_stop_2_hours",
        register=0x859,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="discharge_start_1_mins",
        register=0x85A,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="discharge_stop_1_mins",
        register=0x85B,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="discharge_start_2_mins",
        register=0x85C,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="discharge_stop_2_mins",
        register=0x85D,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="charge_start_1_mins",
        register=0x85E,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="charge_stop_1_mins",
        register=0x85F,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="charge_start_2_mins",
        register=0x860,
        allowedtypes=GEN,
        internal=True,
    ),
    AlphaESSModbusSensorEntityDescription(
        key="charge_stop_2_mins",
        register=0x861,
        allowedtypes=GEN,
        internal=True,
    ),
]

# ============================ plugin declaration =================================================


@dataclass
class alphaess_plugin(plugin_base):

    async def async_determineInverterType(self, hub, configdict):
        # global SENSOR_TYPES
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber = await async_read_serialnr(hub, 0x64A)
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find any serial number(s)")
            seriesnumber = "unknown"

        # derive invertertupe from seriiesnumber
        if seriesnumber.startswith("XYZ"):
            invertertype = GEN  # Unknown AlphaESS
            self.inverter_model = "Unknown"
        elif seriesnumber.startswith("ZYX"):
            invertertype = MAX | GEN2 | MPPT5  # Unknown AlphaESS
            self.inverter_model = "Unknown"
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


plugin_instance = alphaess_plugin(
    plugin_name="AlphaESS",
    plugin_manufacturer="Alpha ESS Co., Ltd.",
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
