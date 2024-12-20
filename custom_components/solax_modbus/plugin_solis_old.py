import logging
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

MPPT3 = 0x40000
MPPT4 = 0x80000
MPPT6 = 0x100000
MPPT8 = 0x200000
MPPT10 = 0x400000
ALL_MPPT_GROUP = MPPT3 | MPPT4 | MPPT6 | MPPT8 | MPPT10

ALLDEFAULT = 0  # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3


async def async_read_serialnr(hub, address):
    res = None
    inverter_data = None
    try:
        inverter_data = await hub.async_read_input_registers(unit=hub._modbus_addr, address=address, count=4)
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(8).decode("ascii")
            hub.seriesnumber = res
    except Exception as ex:
        _LOGGER.warning(
            f"{hub.name}: attempt to read serialnumber failed at 0x{address:x} data: {inverter_data}", exc_info=True
        )
    if not res:
        _LOGGER.warning(
            f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed"
        )
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number before potential swap: {res}")
    return res


@dataclass
class SolisModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolisModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolisModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolisModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    """A class that describes Solis Old Modbus sensor entities."""

    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    # order16: int = Endian.BIG
    # order32: int = Endian.BIG
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING


# ================================= Button Declarations ============================================================

BUTTON_TYPES = []
NUMBER_TYPES = []
SELECT_TYPES = []
SENSOR_TYPES: list[SolisModbusSensorEntityDescription] = [
    SolisModbusSensorEntityDescription(
        name="ActivePower",
        key="activepower",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=3005,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Total Power",
        key="pv_total_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=3007,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=HYBRID,
        icon="mdi:solar-power-variant",
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation Total",
        key="power_generation_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=3009,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation This Month",
        key="power_generation_this_month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=3011,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation Last Month",
        key="power_generation_last_month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=3013,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation Today",
        key="power_generation_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=3015,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation Yesterday",
        key="power_generation_yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=3016,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation This Year",
        key="power_generation_this_year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=3017,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation Last Year",
        key="power_generation_last_year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=3019,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=3022,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=3023,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
        icon="mdi:current-dc",
    ),
    SolisModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=3024,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=3025,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
        icon="mdi:current-dc",
    ),
    SolisModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=3026,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=3027,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:current-dc",
    ),
    SolisModbusSensorEntityDescription(
        name="PV Voltage 4",
        key="pv_voltage_4",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=3028,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Current 4",
        key="pv_current_4",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=3029,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:current-dc",
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Voltage",
        key="inverter_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=3034,
        scale=0.1,
        register_type=REG_INPUT,
        rounding=1,
        allowedtypes=HYBRID | X1,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Voltage R",
        key="grid_voltage_r",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=3034,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Voltage S",
        key="grid_voltage_s",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=3035,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Voltage T",
        key="grid_voltage_t",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=3036,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Current",
        key="inverter_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=3037,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X1,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Current R",
        key="grid_current_r",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=3037,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Current S",
        key="grid_current_s",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=3038,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Current T",
        key="grid_current_t",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=3039,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=3042,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Frequency",
        key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        register=3043,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID,
    ),
]

# ============================ plugin declaration =================================================


@dataclass
class solis_old_plugin(plugin_base):

    async def async_determineInverterType(self, hub, configdict):
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber = await async_read_serialnr(hub, 3061, swapbytes=False)
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find serial number, even not for other Inverter")
            seriesnumber = "unknown"

        # derive invertertype from seriiesnumber
        if seriesnumber.startswith("303105"):
            invertertype = HYBRID | X1  # Hybrid Gen5 3kW
        elif seriesnumber.startswith("363105"):
            invertertype = HYBRID | X1  # Hybrid Gen5 3.6kW
        elif seriesnumber.startswith("463105"):
            invertertype = HYBRID | X1  # Hybrid Gen5 4.6kW
        elif seriesnumber.startswith("503105"):
            invertertype = HYBRID | X1  # Hybrid Gen5 5kW
        elif seriesnumber.startswith("603105"):
            invertertype = HYBRID | X1  # Hybrid Gen5 6kW
        elif seriesnumber.startswith("603122"):
            invertertype = HYBRID | X1  # Hybrid Gen5 3.6kW
        elif seriesnumber.startswith("110CA22"):
            invertertype = HYBRID | X3  # Hybrid Gen5 10kW 3Phase

        else:
            invertertype = 0
            _LOGGER.error(f"unrecognized {hub.name} inverter type - serial number : {seriesnumber}")

        if invertertype > 0:
            read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
            read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
            if read_eps:
                invertertype = invertertype | EPS
            if read_dcb:
                invertertype = invertertype | DCB

        return invertertype

    def matchInverterWithMask(self, inverterspec, entitymask, serialnumber="not relevant", blacklist=None):
        # returns true if the entity needs to be created for an inverter
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP) != 0) or (entitymask & ALL_GEN_GROUP == 0)
        xmatch = ((inverterspec & entitymask & ALL_X_GROUP) != 0) or (entitymask & ALL_X_GROUP == 0)
        hybmatch = ((inverterspec & entitymask & ALL_TYPE_GROUP) != 0) or (entitymask & ALL_TYPE_GROUP == 0)
        epsmatch = ((inverterspec & entitymask & ALL_EPS_GROUP) != 0) or (entitymask & ALL_EPS_GROUP == 0)
        dcbmatch = ((inverterspec & entitymask & ALL_DCB_GROUP) != 0) or (entitymask & ALL_DCB_GROUP == 0)
        mpptmatch = ((inverterspec & entitymask & ALL_MPPT_GROUP) != 0) or (entitymask & ALL_MPPT_GROUP == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist:
                if serialnumber.startswith(start):
                    blacklisted = True
        return (genmatch and xmatch and hybmatch and epsmatch and dcbmatch and mpptmatch) and not blacklisted


plugin_instance = solis_old_plugin(
    plugin_name="Solis Old",
    plugin_manufacturer="Ginlog Solis",
    SENSOR_TYPES=SENSOR_TYPES,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=[],
    block_size=48,
    order16=Endian.BIG,
    order32=Endian.BIG,
    auto_block_ignore_readerror=True,
)
