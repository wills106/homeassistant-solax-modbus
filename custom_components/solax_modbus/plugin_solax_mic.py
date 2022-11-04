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


def matchInverterWithMask (inverterspec, entitymask, serialnumber = 'not relevant', blacklist = None):
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

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================

def _read_serialnr(hub, address, swapbytes):
    res = None
    try:
        inverter_data = hub.read_holding_registers(unit=hub._modbus_addr, address=address, count=7)
        if not inverter_data.isError(): 
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.Big)
            res = decoder.decode_string(14).decode("ascii")
            if swapbytes: 
                ba = bytearray(res,"ascii") # convert to bytearray for swapping
                ba[0::2], ba[1::2] = ba[1::2], ba[0::2] # swap bytes ourselves - due to bug in Endian.Little ?
                res = str(ba, "ascii") # convert back to string
            hub.seriesnumber = res    
    except Exception as ex: _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x}", exc_info=True)
    if not res: _LOGGER.warning(f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed")
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number: {res}, swapped: {swapbytes}")
    return res

def determineInverterType(hub, configdict):
    global SENSOR_TYPES
    _LOGGER.info(f"{hub.name}: trying to determine inverter type")
    seriesnumber                       = _read_serialnr(hub, 0x0,   swapbytes = False)
    if not seriesnumber:  seriesnumber = _read_serialnr(hub, 0x300, swapbytes = False) # bug in endian.Little decoding?
    if not seriesnumber: 
        _LOGGER.error(f"{hub.name}: cannot find serial number, even not for MIC")
        seriesnumber = "unknown"

    # derive invertertupe from seriiesnumber
    if   seriesnumber.startswith('L30E'):  invertertype = HYBRID | GEN2 | X1 # Gen2 X1 SK-TL 3kW
    elif seriesnumber.startswith('U30E'):  invertertype = HYBRID | GEN2 | X1 # Gen2 X1 SK-SU 3kW
    elif seriesnumber.startswith('L37E'):  invertertype = HYBRID | GEN2 | X1 # Gen2 X1 SK-SU 3.7kW Untested
    elif seriesnumber.startswith('U37E'):  invertertype = HYBRID | GEN2 | X1 # Gen2 X1 SK-SU 3.7kW Untested
    elif seriesnumber.startswith('L50E'):  invertertype = HYBRID | GEN2 | X1 # Gen2 X1 SK-SU 5kW
    elif seriesnumber.startswith('U50E'):  invertertype = HYBRID | GEN2 | X1 # Gen2 X1 SK-SU 5kW
    elif seriesnumber.startswith('H1E'):   invertertype = HYBRID | GEN3 | X1 # Gen3 X1 Early
    elif seriesnumber.startswith('HCC'):   invertertype = HYBRID | GEN3 | X1 # Gen3 X1 Alternative
    elif seriesnumber.startswith('HUE'):   invertertype = HYBRID | GEN3 | X1 # Gen3 X1 Late
    elif seriesnumber.startswith('XRE'):   invertertype = HYBRID | GEN3 | X1 # Gen3 X1 Alternative
    elif seriesnumber.startswith('XAC'):   invertertype = AC | GEN3 | X1 # X1AC
    elif seriesnumber.startswith('XB3'):   invertertype = PV | GEN3 | X1 # X1-Boost G3, should work with other kW raiting assuming they use Hybrid registers
    elif seriesnumber.startswith('XM3'):   invertertype = PV | GEN3 | X1 # X1-Mini G3, should work with other kW raiting assuming they use Hybrid registers
    elif seriesnumber.startswith('H3DE'):  invertertype = HYBRID | GEN3 | X3 # Gen3 X3
    elif seriesnumber.startswith('H3E'):   invertertype = HYBRID | GEN3 | X3 # Gen3 X3
    elif seriesnumber.startswith('H3PE'):  invertertype = HYBRID | GEN3 | X3 # Gen3 X3
    elif seriesnumber.startswith('H3UE'):  invertertype = HYBRID | GEN3 | X3 # Gen3 X3
    elif seriesnumber.startswith('F3D'):   invertertype = AC | GEN3 | X3 # RetroFit
    elif seriesnumber.startswith('F3E'):   invertertype = AC | GEN3 | X3 # RetroFit
    elif seriesnumber.startswith('H43'):   invertertype = HYBRID | GEN4 | X1 # Gen4 X1 3kW / 3.7kW
    elif seriesnumber.startswith('H450'):  invertertype = HYBRID | GEN4 | X1 # Gen4 X1 5.0kW
    elif seriesnumber.startswith('H460'):  invertertype = HYBRID | GEN4 | X1 # Gen4 X1 6kW?
    elif seriesnumber.startswith('H475'):  invertertype = HYBRID | GEN4 | X1 # Gen4 X1 7.5kW
    elif seriesnumber.startswith('PRI'):   invertertype = AC | GEN4 | X1 # RetroFit
    elif seriesnumber.startswith('H34'):   invertertype = HYBRID | GEN4 | X3 # Gen4 X3
    elif seriesnumber.startswith('MC10'):  invertertype = MIC | GEN | X3 # MIC X3 Serial Inverted?
    elif seriesnumber.startswith('MC20'):  invertertype = MIC | GEN | X3 # MIC X3 Serial Inverted?
    elif seriesnumber.startswith('MP15'):  invertertype = MIC | GEN | X3 # MIC X3 MP15 Serial Inverted!
    elif seriesnumber.startswith('MU80'):  invertertype = MIC | GEN | X3 # MIC X3 Serial Inverted?
    # add cases here
    else: 
        invertertype = 0
        _LOGGER.error(f"unrecognized inverter type - serial number : {seriesnumber}")
    read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
    read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
    if read_eps: invertertype = invertertype | EPS 
    if read_dcb: invertertype = invertertype | DCB
    hub.invertertype = invertertype

# =================================================================================================

@dataclass
class SolaXMicModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    # A class that describes SolaX Power MIC Modbus sensor entities.
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice
    order16: int = Endian.Big
    order32: int = Endian.Little
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING

# ================================= Computed sensor value functions  =================================================


def value_function_pv_total_power(initval, descr, datadict):
    return  datadict.get('pv_power_1', 0) + datadict.get('pv_power_2',0)

def value_function_grid_import(initval, descr, datadict):
    val = datadict["feedin_power"]
    if val<0: return abs(val)
    else: return 0

def value_function_grid_export(initval, descr, datadict):
    val = datadict["feedin_power"]
    if val>0: return val
    else: return 0

def value_function_house_load(initval, descr, datadict):
    return datadict['inverter_load'] - datadict['feedin_power']

def value_function_rtc(initval, descr, datadict):
    (rtc_seconds, rtc_minutes, rtc_hours, rtc_days, rtc_months, rtc_years, ) = initval
    val = f"{rtc_days:02}/{rtc_months:02}/{rtc_years:02} {rtc_hours:02}:{rtc_minutes:02}:{rtc_seconds:02}"
    return datetime.strptime(val, '%d/%m/%y %H:%M:%S')

def value_function_gen4time(initval, descr, datadict):
    h = initval % 256
    m = initval >> 8
    return f"{h:02d}:{m:02d}"

def value_function_gen23time(initval, descr, datadict):
    (h,m,) = initval
    return f"{h:02d}:{m:02d}"

BUTTON_TYPES = []
NUMBER_TYPES = []
SELECT_TYPES = []

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES: list[SolaXMicModbusSensorEntityDescription] = [
    SolaXMicModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        register = 0x400,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= MIC,
    ),
    SolaXMicModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        register = 0x401,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= MIC,
    ),
    SolaXMicModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 0x402,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= MIC,
        icon="mdi:current-dc",
    ),
    SolaXMicModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 0x403,
        register_type = REG_INPUT,
        scale = 0.1,
        rounding = 1,
        allowedtypes= MIC,
        icon="mdi:current-dc",
    ),
    SolaXMicModbusSensorEntityDescription(
        name="Measured Power",
        key="measured_power",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        register = 0x40E,
        newblock = True,
        register_type = REG_INPUT,
        allowedtypes= MIC,
    ),
    SolaXMicModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode", # Need add the actual modes!
        register = 0x40F,
        scale = { 0: "Waiting",
                  1: "Checking",
                  2: "Normal Mode",
                  3: "Fault",
                  4: "Permanent Fault Mode", },
        register_type = REG_INPUT,
        allowedtypes= MIC,
        icon="mdi:run",
    ),
    SolaXMicModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        register = 0x414,
        newblock = True,
        register_type = REG_INPUT,
        allowedtypes= MIC,
        icon="mdi:solar-power-variant",
    ),
    SolaXMicModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        register = 0x415,
        register_type = REG_INPUT,
        allowedtypes= MIC,
        icon="mdi:solar-power-variant",
    ),
    SolaXMicModbusSensorEntityDescription(
        name="PV Total Power",
        key="pv_total_power",
        value_function= value_function_pv_total_power,
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes= MIC,
        icon="mdi:solar-power-variant",
    ),
]