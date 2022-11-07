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

####
#
# Placeholder for now
#
####

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

def determineInverterType(hub, configdict):
    _LOGGER.info(f"{hub.name}: trying to determine inverter type")
    seriesnumber                       = _read_serialnr(hub, 3061,  swapbytes = False)
    if not seriesnumber: 
        _LOGGER.error(f"{hub.name}: cannot find serial number, even not for other Inverter")
        seriesnumber = "unknown"

    # derive invertertype from seriiesnumber
    if   seriesnumber.startswith('123ABC'):  invertertype = HYBRID | X1 # 
    elif seriesnumber.startswith('ABC123'):  invertertype = HYBRID | X1 # 

    else: 
        invertertype = 0
        _LOGGER.error(f"unrecognized {hub.name} inverter type - serial number : {seriesnumber}")
    read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
    read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
    if read_eps: invertertype = invertertype | EPS 
    if read_dcb: invertertype = invertertype | DCB
    hub.invertertype = invertertype


@dataclass
class SolisOldModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SolisOldModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SolisOldModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SolisOldModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    """A class that describes Solis Old Modbus sensor entities."""
    order16: int = Endian.Big
    order32: int = Endian.Big
    unit: int = REGISTER_U16
    register_type: int= REG_HOLDING

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

# ================================= Button Declarations ============================================================

BUTTON_TYPES = []
NUMBER_TYPES = []
SELECT_TYPES = []
SENSOR_TYPES: list[SolisOldModbusSensorEntityDescription] = []