import logging
from dataclasses import dataclass
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
#from .const import BaseModbusSensorEntityDescription
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

GEN            = 0x0001 # base generation for MIC, PV, AC
GEN2           = 0x0002
GEN3           = 0x0004
GEN4           = 0x0008
ALL_GEN_GROUP  = GEN2 | GEN3 | GEN4 | GEN

X1             = 0x0100
X3             = 0x0200
ALL_X_GROUP    = X1 | X3

PV             = 0x0400 # Needs further work on PV Only Inverters
AC             = 0x0800
HYBRID         = 0x1000
MIC            = 0x2000
ALL_TYPE_GROUP = PV | AC | HYBRID | MIC

EPS            = 0x8000
ALL_EPS_GROUP  = EPS

DCB            = 0x10000 # dry contact box - gen4
ALL_DCB_GROUP  = DCB


ALLDEFAULT = 0 # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3 


# ======================= end of bitmask handling code =============================================

# ====================== find inverter type and details ===========================================

def _read_serialnr(hub, address, swapbytes):
    res = None
    try:
        inverter_data = hub.read_input_registers(unit=hub._modbus_addr, address=address, count=4)
        if not inverter_data.isError(): 
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.Big)
            res = decoder.decode_string(8).decode
            if swapbytes: 
                ba = bytearray(res) # convert to bytearray for swapping
                ba[0::2], ba[1::2] = ba[1::2], ba[0::2] # swap bytes ourselves - due to bug in Endian.Little ?
                res = str(ba) # convert back to string
            hub.seriesnumber = res    
    except Exception as ex: _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x}", exc_info=True)
    if not res: _LOGGER.warning(f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed")
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number: {res}, swapped: {swapbytes}")
    #return 'SP1ES2' 
    return res

@dataclass
class SolisModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SolisModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SolisModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SolisModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    """A class that describes Solis Old Modbus sensor entities."""
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice
    #order16: int = Endian.Big
    #order32: int = Endian.Big
    unit: int = REGISTER_U16
    register_type: int= REG_HOLDING

# ================================= Button Declarations ============================================================

BUTTON_TYPES = []
NUMBER_TYPES = []
SELECT_TYPES = []
SENSOR_TYPES: list[SolisModbusSensorEntityDescription] = [
    SolisModbusSensorEntityDescription(
        name = "ActivePower",
        key = "activepower",
        native_unit_of_measurement = ENERGY_KILO_WATT_HOUR,
        device_class = DEVICE_CLASS_ENERGY,
        register = 3005,
        register_type = REG_INPUT,
        unit = REGISTER_U32,
        allowedtypes = HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Total Power",
        key="pv_total_power",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        register = 3007,
        register_type = REG_INPUT,
        unit = REGISTER_U32,
        allowedtypes= HYBRID,
        icon="mdi:solar-power-variant",
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation Total",
        key="power_generation_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        register = 3009,
        register_type = REG_INPUT,
        unit = REGISTER_U32,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation This Month",
        key="power_generation_this_month",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        register = 3011,
        register_type = REG_INPUT,
        unit = REGISTER_U32,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation Last Month",
        key="power_generation_last_month",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        register = 3013,
        register_type = REG_INPUT,
        unit = REGISTER_U32,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation Today",
        key="power_generation_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        register = 3015,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation Yesterday",
        key="power_generation_yesterday",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        register = 3016,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation This Year",
        key="power_generation_this_year",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        register = 3017,
        register_type = REG_INPUT,
        unit = REGISTER_U32,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="Power Generation Last Year",
        key="power_generation_last_year",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        register = 3019,
        register_type = REG_INPUT,
        unit = REGISTER_U32,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        register = 3022,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 3023,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= HYBRID,
        icon="mdi:current-dc",
    ),
    SolisModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        register = 3024,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 3025,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= HYBRID,
        icon="mdi:current-dc",
    ),
    SolisModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        register = 3026,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        entity_registry_enabled_default=False,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 3027,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        entity_registry_enabled_default=False,
        allowedtypes= HYBRID,
        icon="mdi:current-dc",
    ),
    SolisModbusSensorEntityDescription(
        name="PV Voltage 4",
        key="pv_voltage_4",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        register = 3028,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        entity_registry_enabled_default=False,
        allowedtypes= HYBRID,
    ),
    SolisModbusSensorEntityDescription(
        name="PV Current 4",
        key="pv_current_4",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 3029,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        entity_registry_enabled_default=False,
        allowedtypes= HYBRID,
        icon="mdi:current-dc",
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Voltage",
        key="inverter_voltage",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        register = 3034,
        scale = 0.1,
        register_type = REG_INPUT,
        rounding = 1,
        allowedtypes= HYBRID | X1,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Voltage R",
        key="grid_voltage_r",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        register = 3034,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Voltage S",
        key="grid_voltage_s",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        register = 3035,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Voltage T",
        key="grid_voltage_t",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        register = 3036,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Current",
        key="inverter_current",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 3037,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= HYBRID | X1,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Current R",
        key="grid_current_r",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 3037,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Current S",
        key="grid_current_s",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 3038,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Current T",
        key="grid_current_t",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 3039,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID | X3,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
        register = 3042,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = HYBRID,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolisModbusSensorEntityDescription(
        name="Inverter Frequency",
        key="grid_frequency",
        native_unit_of_measurement=FREQUENCY_HERTZ,
        device_class=DEVICE_CLASS_FREQUENCY,
        register = 3043,
        register_type = REG_INPUT,
        scale = 0.01,
        rounding = 2,
        allowedtypes = HYBRID,
    ),
]

# ============================ plugin declaration =================================================

@dataclass
class solis_old_plugin(plugin_base):
    
    """
    def isAwake(self, datadict):
        return (datadict.get('run_mode', None) == 'Normal Mode')

    def wakeupButton(self):
        return 'battery_awaken'
    """

    def determineInverterType(self, hub, configdict):
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber                       = _read_serialnr(hub, 3061,  swapbytes = False)
        if not seriesnumber: 
            _LOGGER.error(f"{hub.name}: cannot find serial number, even not for other Inverter")
            seriesnumber = "unknown"

        # derive invertertype from seriiesnumber
        if   seriesnumber.startswith('303105'):  invertertype = HYBRID | X1 # Hybrid Gen5 3kW
        elif seriesnumber.startswith('363105'):  invertertype = HYBRID | X1 # Hybrid Gen5 3.6kW
        elif seriesnumber.startswith('463105'):  invertertype = HYBRID | X1 # Hybrid Gen5 4.6kW
        elif seriesnumber.startswith('503105'):  invertertype = HYBRID | X1 # Hybrid Gen5 5kW
        elif seriesnumber.startswith('603105'):  invertertype = HYBRID | X1 # Hybrid Gen5 6kW
        elif seriesnumber.startswith('603122'):  invertertype = HYBRID | X1 # Hybrid Gen5 3.6kW
        elif seriesnumber.startswith('110CA22'):  invertertype = HYBRID | X3 # Hybrid Gen5 10kW 3Phase 

        else: 
            invertertype = 0
            _LOGGER.error(f"unrecognized {hub.name} inverter type - serial number : {seriesnumber}")
        read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
        read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
        if read_eps: invertertype = invertertype | EPS 
        if read_dcb: invertertype = invertertype | DCB
        #hub.invertertype = invertertype
        return invertertype

    def matchInverterWithMask (self, inverterspec, entitymask, serialnumber = 'not relevant', blacklist = None):
        # returns true if the entity needs to be created for an inverter
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP)  != 0) or (entitymask & ALL_GEN_GROUP  == 0)
        xmatch   = ((inverterspec & entitymask & ALL_X_GROUP)    != 0) or (entitymask & ALL_X_GROUP    == 0)
        hybmatch = ((inverterspec & entitymask & ALL_TYPE_GROUP) != 0) or (entitymask & ALL_TYPE_GROUP == 0)
        epsmatch = ((inverterspec & entitymask & ALL_EPS_GROUP)  != 0) or (entitymask & ALL_EPS_GROUP  == 0)
        dcbmatch = ((inverterspec & entitymask & ALL_DCB_GROUP)  != 0) or (entitymask & ALL_DCB_GROUP  == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist: 
                if serialnumber.startswith(start) : blacklisted = True
        return (genmatch and xmatch and hybmatch and epsmatch and dcbmatch) and not blacklisted

plugin_instance = solis_old_plugin(
    plugin_name = 'solis_old', 
    SENSOR_TYPES = SENSOR_TYPES,
    NUMBER_TYPES = NUMBER_TYPES,
    BUTTON_TYPES = BUTTON_TYPES,
    SELECT_TYPES = SELECT_TYPES, 
    block_size = 48,
    order16 = Endian.Big,
    order32 = Endian.Big,
    )
