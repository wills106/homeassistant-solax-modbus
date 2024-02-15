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

GEN            = 0x0001 # base generation for MIC, PV, AC
GEN2           = 0x0002
GEN3           = 0x0004
GEN4           = 0x0008
SPF            = 0x0010
ALL_GEN_GROUP  = GEN2 | GEN3 | GEN4 | GEN | SPF

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

MPPT3          = 0x40000
MPPT4          = 0x80000
MPPT6          = 0x100000
MPPT8          = 0x200000
MPPT10         = 0x400000
ALL_MPPT_GROUP = MPPT3 | MPPT4 | MPPT6 | MPPT8 | MPPT10

ALLDEFAULT = 0 # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================

def _read_serialnr(hub, address):
    res = None
    try:
        inverter_data = hub.read_input_registers(unit=hub._modbus_addr, address=address, count=8)
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(16).decode("ascii")
            hub.seriesnumber = res
    except Exception as ex: _LOGGER.warning(f"{hub.name}: attempt to read firmware failed at 0x{address:x}", exc_info=True)
    if not res: _LOGGER.warning(f"{hub.name}: reading firmware number from address 0x{address:x} failed; other address may succeed")
    _LOGGER.info(f"Read {hub.name} 0x{address:x} firmware number before potential swap: {res}")
    return res

# =================================================================================================

@dataclass
class SwattenModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SwattenModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SwattenModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SwattenModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    """A class that describes Swatten Modbus sensor entities."""
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice
    order16: int = Endian.BIG
    order32: int = Endian.BIG
    unit: int = REGISTER_U16
    register_type: int= REG_HOLDING

# ====================================== Computed value functions  =================================================

def value_function_timingmode(initval, descr, datadict):
    return  [ ('timed_charge_start_h', datadict.get('timed_charge_start_h', 0), ),
              ('timed_charge_start_m', datadict.get('timed_charge_start_m', 0), ),
              ('timed_charge_end_h', datadict.get('timed_charge_end_h', 0), ),
              ('timed_charge_end_m', datadict.get('timed_charge_end_m', 0), ),
              ('timed_discharge_start_h', datadict.get('timed_discharge_start_h', 0), ),
              ('timed_discharge_start_m', datadict.get('timed_discharge_start_m', 0), ),
              ('timed_discharge_end_h', datadict.get('timed_discharge_end_h', 0), ),
              ('timed_discharge_end_m', datadict.get('timed_discharge_end_m', 0), ),
            ]

def value_function_today_solar_energy(initval, descr, datadict):
    return  datadict.get('today_pv1_solar_energy', 0) + datadict.get('today_pv2_solar_energy',0) + datadict.get('today_pv3_solar_energy',0) + datadict.get('today_pv4_solar_energy',0)

def value_function_combined_battery_power(initval, descr, datadict):
    return  datadict.get('battery_charge_power', 0) - datadict.get('battery_discharge_power',0) 

# ================================= Button Declarations ============================================================

BUTTON_TYPES = [
    SwattenModbusButtonEntityDescription(
        name = "Sync RTC",
        key = "sync_rtc",
        register = 4050,
        allowedtypes = ALL_GEN_GROUP,
        write_method = WRITE_MULTI_MODBUS,
        icon = "mdi:home-clock",
        value_function = value_function_sync_rtc_ymd,
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
    
]

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES: list[SwattenModbusSensorEntityDescription] = [
    SwattenModbusSensorEntityDescription(
        name = "RTC",
        key = "rtc",
        register = 4050,
        unit = REGISTER_WORDS,
        wordcount = 6,
        scale = value_function_rtc_ymd,
        allowedtypes = ALL_GEN_GROUP,
        #entity_registry_enabled_default = False,
        entity_category = EntityCategory.DIAGNOSTIC,
        icon = "mdi:clock",
    ),
    ###
    #
    # Input registers
    #
    ###
    SwattenModbusSensorEntityDescription(
        name = "Phase",
        key = "phase",
        register = 4052,
        register_type = REG_INPUT,
        allowedtypes = ALL_GEN_GROUP,
        #entity_registry_enabled_default = False,
        entity_category = EntityCategory.DIAGNOSTIC,
        icon = "mdi:clock",
    ),
    SwattenModbusSensorEntityDescription(
        name = "PV Voltage 1",
        key = "pv_voltage_1",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 4061,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
    ),
    SwattenModbusSensorEntityDescription(
        name = "PV Current 1",
        key = "pv_current_1",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 4062,
        #register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
        icon = "mdi:current-dc",
    ),
    SwattenModbusSensorEntityDescription(
        name = "PV Voltage 2",
        key = "pv_voltage_2",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 4063,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
    ),
    SwattenModbusSensorEntityDescription(
        name = "PV Current 2",
        key = "pv_current_2",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 4064,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
        icon = "mdi:current-dc",
    ),
    SwattenModbusSensorEntityDescription(
        name = "PV Power Total",
        key = "pv_power_total",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        register = 4067,
        #register_type = REG_INPUT,
        unit = REGISTER_U32,
        #scale = 0.1,
        #rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
        icon = "mdi:solar-power-variant",
    ),
    SwattenModbusSensorEntityDescription(
        name = "Grid Voltage",
        key = "inverter_voltage",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 4069,
        scale = 0.1,
        register_type = REG_INPUT,
        rounding = 1,
        allowedtypes = GEN | X1,
    ),
    SwattenModbusSensorEntityDescription(
        name = "Grid Voltage L1",
        key = "grid_voltage_l1",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 4069,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
    ),
    SwattenModbusSensorEntityDescription(
        name = "Grid Voltage L2",
        key = "grid_voltage_l2",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 4070,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
    ),
    SwattenModbusSensorEntityDescription(
        name = "Grid Voltage L3",
        key = "grid_voltage_l3",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 4071,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
    ),
    SwattenModbusSensorEntityDescription(
        name = "Grid Current",
        key = "grid_current",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 4072,
        register_type = REG_INPUT,
        #unit = REGISTER_S16,
        scale = 0.1,
        rounding = 1,
        allowedtypes = GEN | X1,
    ),
    SwattenModbusSensorEntityDescription(
        name = "Grid Current L1",
        key = "grid_current_l1",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 4072,
        register_type = REG_INPUT,
        #unit = REGISTER_S16,
        scale = 0.1,
        rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
    ),
    SwattenModbusSensorEntityDescription(
        name = "Grid Current L2",
        key = "grid_current_l2",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 4073,
        register_type = REG_INPUT,
        #unit = REGISTER_S16,
        scale = 0.1,
        rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
    ),
    SwattenModbusSensorEntityDescription(
        name = "Grid Current L3",
        key = "grid_current_l3",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 4074,
        register_type = REG_INPUT,
        #unit = REGISTER_S16,
        scale = 0.1,
        rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
    ),
    SwattenModbusSensorEntityDescription(
        name = "Total Output Power",
        key = "total_output_power",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        register = 4081,
        register_type = REG_INPUT,
        unit = REGISTER_U32,
        #scale = 0.1,
        #rounding = 1,
        allowedtypes = ALL_GEN_GROUP,
        icon = "mdi:solar-power-variant",
    ),
    SwattenModbusSensorEntityDescription(
        name = "Grid Frequency",
        key = "grid_frequency",
        native_unit_of_measurement = UnitOfFrequency.HERTZ,
        device_class = SensorDeviceClass.FREQUENCY,
        register = 4198,
        register_type = REG_INPUT,
        scale = 0.01,
        rounding = 2,
        allowedtypes = ALL_GEN_GROUP,
    ),
    SwattenModbusSensorEntityDescription(
        name = "Model Type",
        key = "model_type",
        register = 5809,
        unit = REGISTER_STR,
        wordcount=8,
        register_type = REG_INPUT,
        allowedtypes = ALL_GEN_GROUP,
        #entity_registry_enabled_default = False,
        entity_category = EntityCategory.DIAGNOSTIC,
        icon = "mdi:information",
    ),   
]

# ============================ plugin declaration =================================================

@dataclass
class swatten_plugin(plugin_base):

    def determineInverterType(self, hub, configdict):
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber                       = _read_serialnr(hub, 5809)
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find equipment model")
            seriesnumber = "unknown"

        # derive invertertype from seriiesnumber
        if seriesnumber.startswith('123'):  invertertype = PV | GEN | X1 # PV ?
        elif seriesnumber.startswith('321'):  invertertype = HYBRID | GEN | X1 # Hybrid ?

        else:
            invertertype = 0
            _LOGGER.error(f"unrecognized {hub.name} model type : {seriesnumber}")
        read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
        read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
        if read_eps: invertertype = invertertype | EPS
        if read_dcb: invertertype = invertertype | DCB
        return invertertype

    def matchInverterWithMask (self, inverterspec, entitymask, serialnumber = 'not relevant', blacklist = None):
        # returns true if the entity needs to be created for an inverter
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP)  != 0) or (entitymask & ALL_GEN_GROUP  == 0)
        xmatch   = ((inverterspec & entitymask & ALL_X_GROUP)    != 0) or (entitymask & ALL_X_GROUP    == 0)
        hybmatch = ((inverterspec & entitymask & ALL_TYPE_GROUP) != 0) or (entitymask & ALL_TYPE_GROUP == 0)
        epsmatch = ((inverterspec & entitymask & ALL_EPS_GROUP)  != 0) or (entitymask & ALL_EPS_GROUP  == 0)
        dcbmatch = ((inverterspec & entitymask & ALL_DCB_GROUP)  != 0) or (entitymask & ALL_DCB_GROUP  == 0)
        mpptmatch = ((inverterspec & entitymask & ALL_MPPT_GROUP)  != 0) or (entitymask & ALL_MPPT_GROUP  == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist:
                if serialnumber.startswith(start) : blacklisted = True
        return (genmatch and xmatch and hybmatch and epsmatch and dcbmatch and mpptmatch) and not blacklisted

plugin_instance = swatten_plugin(
    plugin_name = 'Swatten',
    plugin_manufacturer = 'Sieyuan Watten Technology',
    SENSOR_TYPES = SENSOR_TYPES,
    NUMBER_TYPES = NUMBER_TYPES,
    BUTTON_TYPES = BUTTON_TYPES,
    SELECT_TYPES = SELECT_TYPES,
    block_size = 100,
    order16 = Endian.BIG,
    order32 = Endian.BIG,
    )