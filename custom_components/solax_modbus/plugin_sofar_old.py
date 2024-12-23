import logging
import re
from dataclasses import dataclass
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
from custom_components.solax_modbus.const import *

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

GEN = 0x0001  # base generation for MIC, PV, AC
GEN2 = 0x0002
GEN3 = 0x0004
GEN4 = 0x0008
ALL_GEN_GROUP = GEN2 | GEN3 | GEN4 | GEN

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

# ====================== find inverter type and details ===========================================


def remove_special_chars(input_str):
    return re.sub(r"[^A-z0-9 -]", "", input_str)


async def async_read_serialnr(hub, address, swapbytes):
    res = None
    try:
        inverter_data = await hub.async_read_input_registers(unit=hub._modbus_addr, address=address, count=6)
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(12).decode("ascii")
            if swapbytes:
                ba = bytearray(res, "ascii")  # convert to bytearray for swapping
                ba[0::2], ba[1::2] = ba[1::2], ba[0::2]  # swap bytes ourselves - due to bug in Endian.LITTLE ?
                res = str(ba, "ascii")  # convert back to string
            res = remove_special_chars(res)
            hub.seriesnumber = res
    except Exception as ex:
        _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x}", exc_info=True)
    if not res:
        _LOGGER.warning(
            f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed"
        )
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number: {res}, swapped: {swapbytes}")
    return res


# =================================================================================================


@dataclass
class SofarOldModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SofarOldModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SofarOldModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SofarOldModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    """A class that describes Sofar Modbus sensor entities."""

    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    # order16: int = Endian.BIG
    # order32: int = Endian.BIG
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING


# ================================= Button Declarations ============================================================

BUTTON_TYPES = []
NUMBER_TYPES = []
SELECT_TYPES = []

SENSOR_TYPES: list[SofarOldModbusSensorEntityDescription] = [
    ###
    #
    # Holding Registers
    #
    ###
    # Start of Single Phase
    SofarOldModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x0,
        scale={
            0: "Waiting",
            1: "Checking",
            2: "Normal Mode",
            3: "Fault",
            4: "Permanent Fault Mode",
        },
        allowedtypes=PV,
        icon="mdi:run",
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x6,
        scale=0.1,
        rounding=1,
        allowedtypes=PV,
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x7,
        scale=0.01,
        rounding=2,
        allowedtypes=PV,
        icon="mdi:current-dc",
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Power",
        key="pv_power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xA,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X1,
        icon="mdi:solar-power-variant",
    ),
    SofarOldModbusSensorEntityDescription(
        name="ActivePower",
        key="activepower",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xC,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X1,
    ),
    SofarOldModbusSensorEntityDescription(
        name="ReactivePower",
        key="reactivepower",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0xD,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X1,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        register=0xE,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X1,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Voltage",
        key="voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xF,
        scale=0.1,
        rounding=1,
        allowedtypes=PV | X1,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Current",
        key="current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x10,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X1,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Total Production",
        key="total_production",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x15,
        unit=REGISTER_U32,
        allowedtypes=PV | X1,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Total Time",
        key="total_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        register=0x17,
        unit=REGISTER_U32,
        allowedtypes=PV | X1,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Today Production",
        key="today_production",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x19,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X1,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Today Time",
        key="today_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        register=0x1A,
        allowedtypes=PV | X1,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Inverter Heatsink Temperature ",
        key="inverter_heatsink_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1B,
        unit=REGISTER_S16,
        # entity_registry_enabled_default = False,
        allowedtypes=PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Inverter Inner Temperature ",
        key="inverter_inner_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1C,
        unit=REGISTER_S16,
        # entity_registry_enabled_default = False,
        allowedtypes=PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # End of Single Phase
    #
    # Start of 3Phase PV
    SofarOldModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x8,
        scale=0.1,
        rounding=1,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x9,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
        icon="mdi:current-dc",
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xA,
        scale=0.1,
        rounding=1,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0xB,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
        icon="mdi:current-dc",
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xC,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
        icon="mdi:solar-power-variant",
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xD,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
        icon="mdi:solar-power-variant",
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Power 3",
        key="pv_power_3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xE,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
        icon="mdi:solar-power-variant",
    ),
    SofarOldModbusSensorEntityDescription(
        name="ActivePower",
        key="activepower",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        register=0xF,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="ReactivePower",
        key="reactivepower",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x10,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        register=0x11,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Voltage R",
        key="voltage_r",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x12,
        scale=0.1,
        rounding=1,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Current R",
        key="current_r",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x14,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Voltage S",
        key="voltage_s",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x14,
        scale=0.1,
        rounding=1,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Current S",
        key="current_s",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x15,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Voltage T",
        key="voltage_t",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x16,
        scale=0.1,
        rounding=1,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Current T",
        key="current_t",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x17,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Total Production",
        key="total_production",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        register=0x18,
        unit=REGISTER_U32,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Total Time",
        key="total_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        register=0x1A,
        unit=REGISTER_U32,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Today Production",
        key="today_production",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        register=0x1C,
        scale=0.01,
        rounding=2,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Today Time",
        key="today_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        register=0x1D,
        allowedtypes=PV | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Inverter Heatsink Temperature ",
        key="inverter_heatsink_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1E,
        unit=REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes=PV | X3,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Inverter Inner Temperature ",
        key="inverter_inner_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1F,
        unit=REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes=PV | X3,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Bus Voltage",
        key="bus_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x20,
        scale=0.1,
        rounding=1,
        allowedtypes=PV | X3,
    ),
    # End of 3Phase PV
    #
    # Start of AC
    SofarOldModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x200,
        scale={
            0: "Waiting",
            1: "Checking",
            2: "Normal Mode",
            3: "Checking Discharge",
            4: "Discharge Mode",
            5: "EPS Mode",
            6: "Fault",
            7: "Permanent Fault Mode",
        },
        allowedtypes=AC | HYBRID,
        icon="mdi:run",
    ),
    SofarOldModbusSensorEntityDescription(
        name="Voltage R",
        key="voltage_r",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x206,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Current R",
        key="current_r",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x207,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Voltage S",
        key="voltage_s",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x208,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Current S",
        key="current_s",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x209,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Voltage T",
        key="voltage_t",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x20A,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Current T",
        key="current_t",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x20B,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        register=0x20C,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Battery Power Charge",
        key="battery_power_charge",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x20D,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Battery Input Energy",
        key="battery_input_energy",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_function=value_function_battery_input,
        allowedtypes=AC | HYBRID,
        icon="mdi:battery-arrow-up",
    ),
    SofarOldModbusSensorEntityDescription(
        name="Battery Output Energy",
        key="battery_output_energy",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_function=value_function_battery_output,
        allowedtypes=AC | HYBRID,
        icon="mdi:battery-arrow-down",
    ),
    SofarOldModbusSensorEntityDescription(
        name="Battery Voltage Charge",
        key="battery_voltage_charge",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x20E,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Battery Current Charge",
        key="battery_current_charge",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x20F,
        scale=0.01,
        rounding=2,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID,
        icon="mdi:current-dc",
    ),
    SofarOldModbusSensorEntityDescription(
        name="Battery Capacity",
        key="battery_capacity_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x210,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Battery Temperature",
        key="battery_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x211,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Measured Power",
        key="measured_power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x212,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Import",
        key="grid_import",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_function=value_function_grid_import,
        allowedtypes=AC | HYBRID,
        icon="mdi:home-import-outline",
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Export",
        key="grid_export",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_function=value_function_grid_export,
        allowedtypes=AC | HYBRID,
        icon="mdi:home-export-outline",
    ),
    SofarOldModbusSensorEntityDescription(
        name="House Load",
        key="house_load",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x213,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
    ),
    ####
    #
    # register = 0x214,
    #
    ####
    SofarOldModbusSensorEntityDescription(
        name="Generation Power",
        key="generation_power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x215,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="EPS Voltage",
        key="eps_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x216,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | EPS,
    ),
    SofarOldModbusSensorEntityDescription(
        name="EPS Power",
        key="eps_power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x217,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | EPS,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Generation Today",
        key="generation_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x218,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Export Energy Today",
        key="export_energy_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x219,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
        icon="mdi:home-export-outline",
    ),
    SofarOldModbusSensorEntityDescription(
        name="Import Energy Today",
        key="import_energy_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x21A,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
        icon="mdi:home-import-outline",
    ),
    SofarOldModbusSensorEntityDescription(
        name="Consumption Today",
        key="consumption_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x21B,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
    ),
    #
    SofarOldModbusSensorEntityDescription(
        name="Generation Total",
        key="generation_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x21C,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Export Energy Total",
        key="export_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x21E,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID,
        icon="mdi:home-export-outline",
    ),
    SofarOldModbusSensorEntityDescription(
        name="Import Energy Total",
        key="import_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x220,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID,
        icon="mdi:home-import-outline",
    ),
    SofarOldModbusSensorEntityDescription(
        name="Consumption Total",
        key="consumption_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x222,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Battery Charge Cycle",
        key="battery_charge_cycle",
        register=0x22C,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Voltage R",
        key="grid_voltage_r",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x230,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Current R",
        key="grid_current_r",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x231,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Voltage S",
        key="grid_voltage_s",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x232,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Current S",
        key="grid_current_s",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x233,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Voltage T",
        key="grid_voltage_t",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x234,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Grid Current T",
        key="grid_current_t",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x235,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | X3,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Inverter Inner Temperature ",
        key="inverter_inner_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x238,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Inverter Heatsink Temperature ",
        key="inverter_heatsink_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x239,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Generation Time Today",
        key="generation_time_today",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        register=0x242,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Generation Time Today",
        key="generation_time_today",
        native_unit_of_measurement=UnitOfTime.HOURS,
        register=0x244,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_oltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x250,
        newblock=True,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x251,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x252,
        scale=10,
        allowedtypes=HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_oltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x253,
        newblock=True,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x254,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x255,
        scale=10,
        allowedtypes=HYBRID,
    ),
    SofarOldModbusSensorEntityDescription(
        name="PV Power Total",
        key="pv_power_total",
        value_function=value_function_pv_power_total,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=HYBRID,
        icon="mdi:solar-power-variant",
        sleepmode=SLEEPMODE_ZERO,
    ),
    ###
    #
    # Holding Registers
    #
    ###
    SofarOldModbusSensorEntityDescription(
        name="Serial Number",
        key="serial_number",
        register=0x2002,
        register_type=REG_INPUT,
        unit=REGISTER_STR,
        wordcount=6,
        allowedtypes=ALLDEFAULT,
    ),
    SofarOldModbusSensorEntityDescription(
        name="Battery Minimum Capacity",
        key="battery_minimum_capacity",
        register=0x104D,
        register_type=REG_INPUT,
        allowedtypes=AC,
        icon="mdi:battery-sync",
    ),
]


@dataclass
class sofar_old_plugin(plugin_base):
    """
    def isAwake(self, datadict):
        return (datadict.get('run_mode', None) == 'Normal Mode')

    def wakeupButton(self):
        return 'battery_awaken'
    """

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

    async def async_determineInverterType(self, hub, configdict):
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber = await async_read_serialnr(hub, 0x2002, swapbytes=False)
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find serial number, even not for other Inverter")
            seriesnumber = "unknown"

        # derive invertertype from seriiesnumber
        if seriesnumber.startswith("SA1"):
            invertertype = PV | X1  # Older Might be single
        elif seriesnumber.startswith("SA3"):
            invertertype = PV | X1  # Older Might be single
        elif seriesnumber.startswith("SB1"):
            invertertype = PV | X1  # Older Might be single
        elif seriesnumber.startswith("ZA3"):
            invertertype = PV | X1  # Older Might be single
        elif seriesnumber.startswith("SC1"):
            invertertype = PV | X3  # Older Probably 3phase
        elif seriesnumber.startswith("SD1"):
            invertertype = PV | X3  # Older Probably 3phase
        elif seriesnumber.startswith("SF4"):
            invertertype = PV | X3  # Older Probably 3phase
        elif seriesnumber.startswith("SH1"):
            invertertype = PV | X3  # Older Probably 3phase
        elif seriesnumber.startswith("SJ2"):
            invertertype = PV | X3  # Older Probably 3phase
        elif seriesnumber.startswith("SL1"):
            invertertype = PV | X3  # Older Probably 3phase
        elif seriesnumber.startswith("SM1"):
            invertertype = PV  # Not sure if 1 or 3phase?
        elif seriesnumber.startswith("SE1E"):
            invertertype = HYBRID | X1  # 3kW HYDxxxxES
        elif seriesnumber.startswith("SM1E"):
            invertertype = HYBRID | X1  # 3kW HYDxxxxES
        elif seriesnumber.startswith("ZE1E"):
            invertertype = HYBRID | X1  # 3kW HYDxxxxES
        elif seriesnumber.startswith("ZM1E"):
            invertertype = HYBRID | X1  # 3.6kW HYDxxxxES
        # elif seriesnumber.startswith('S??'):  invertertype = AC | HYBRID # Storage Inverter 1 or 3phase?

        else:
            invertertype = 0
            _LOGGER.error(f"unrecognized {hub.name} inverter type - serial number : {seriesnumber}")

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


plugin_instance = sofar_old_plugin(
    plugin_name="Sofar Old",
    plugin_manufacturer="Sofar Solar",
    SENSOR_TYPES=SENSOR_TYPES,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=[],
    block_size=100,
    order16=Endian.BIG,
    order32=Endian.BIG,
    auto_block_ignore_readerror=True,
)
