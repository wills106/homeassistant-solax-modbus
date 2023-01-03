
import logging
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_TOTAL_INCREASING,
)
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from homeassistant.helpers.entity import EntityCategory
from pymodbus.payload import Endian
from datetime import datetime
from dataclasses import dataclass
import pathlib

from homeassistant.const import (
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_CURRENT,
    DEVICE_CLASS_ENERGY,
    DEVICE_CLASS_FREQUENCY,
    DEVICE_CLASS_POWER,
    DEVICE_CLASS_POWER_FACTOR,
    DEVICE_CLASS_TEMPERATURE,
    DEVICE_CLASS_VOLTAGE,
    ELECTRIC_CURRENT_AMPERE,
    ELECTRIC_CURRENT_MILLIAMPERE,
    ELECTRIC_POTENTIAL_VOLT,
    ENERGY_KILO_WATT_HOUR,
    ENERGY_MEGA_WATT_HOUR,
    ENERGY_WATT_HOUR,
    FREQUENCY_HERTZ,
    PERCENTAGE,
    POWER_KILO_WATT,
    POWER_VOLT_AMPERE,
    POWER_VOLT_AMPERE_REACTIVE,
    POWER_WATT,
    TEMP_CELSIUS,
    TIME_HOURS,
    TIME_MINUTES,
    TIME_SECONDS,
)


# ================================= Definitions for config_flow ==========================================================

DOMAIN = "solax_modbus"
DEFAULT_NAME = "SolaX"
DEFAULT_SCAN_INTERVAL = 15
DEFAULT_PORT = 502
DEFAULT_MODBUS_ADDR = 1
CONF_READ_EPS    = "read_eps"
CONF_READ_DCB    = "read_dcb"
CONF_READ_PM    = "read_pm"
CONF_MODBUS_ADDR = "read_modbus_addr"
CONF_INTERFACE   = "interface"
CONF_SERIAL_PORT = "read_serial_port"
CONF_SolaX_HUB   = "solax_hub"
CONF_BAUDRATE    = "baudrate"
CONF_PLUGIN      = "plugin"
ATTR_MANUFACTURER = "SolaX Power"
DEFAULT_INTERFACE  = "tcp"
DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_READ_EPS = False
DEFAULT_READ_DCB = False
DEFAULT_READ_PM = False
DEFAULT_BAUDRATE = "19200"
DEFAULT_PLUGIN        = "solax"
PLUGIN_PATH = f"{pathlib.Path(__file__).parent.absolute()}/plugin_*.py"
SLEEPMODE_NONE   = None
SLEEPMODE_ZERO   = 0 # when no communication at all
SLEEPMODE_LAST   = 1 # when no communication at all
SLEEPMODE_LASTAWAKE = 2 # when still responding but register must be ignored when not awake


# ================================= Definitions for Sensor Declarations =================================================

REG_HOLDING = 1  # modbus holding register
REG_INPUT   = 2  # modbus input register
REGISTER_U16 = "_uint16"
REGISTER_U32 = "_uint32"
REGISTER_S16 = "_int16"
REGISTER_S32 = "_int32"
REGISTER_ULSB16MSB16 = "_ulsb16msb16" # probably same as REGISTER_U32 - suggest to remove later
REGISTER_STR = "_string"  # nr of bytes must be specified in wordcount and is 2*wordcount
REGISTER_WORDS = "_words" # nr or words must be specified in wordcount
REGISTER_U8L = "_int8L"
REGISTER_U8H = "_int8H"
WRITE_SINGLE_MODBUS       = 1 # use write_single_modbus command
WRITE_MULTISINGLE_MODBUS  = 2 # use write_mutiple modbus command for single register
WRITE_DATA_LOCAL          = 3 # write only to local data storage (not persistent)
WRITE_MULTI_MODBUS        = 4 # use write_multiple modbus command


_LOGGER = logging.getLogger(__name__)



# ==================================== plugin base class ====================================================================

@dataclass
class plugin_base:
    plugin_name: str
    SENSOR_TYPES: list[SensorEntityDescription]
    BUTTON_TYPES: list[ButtonEntityDescription]
    NUMBER_TYPES: list[NumberEntityDescription]
    SELECT_TYPES: list[SelectEntityDescription]
    block_size: int = 100
    order16: int = None # Endian.Big or Endian.Little
    order32: int = None

    def isAwake(self, datadict): 
        return True # always awake by default

    def wakeupButton(self):
        return None # no wakeup button

    def determineInverterType(self, hub, configdict): 
        return 0

    def matchInverterWithMask (self, inverterspec, entitymask, serialnumber = 'not relevant', blacklist = None):
        return False

# =================================== base class for sensor entity descriptions =========================================

@dataclass
class BaseModbusSensorEntityDescription(SensorEntityDescription):
    """ base class for modbus sensor declarations """
    allowedtypes: int = 0 # overload with ALLDEFAULT from plugin
    scale: float = 1 # can be float, dictionary or callable function(initval, descr, datadict)
    read_scale_exceptions: list = None # additional scaling when reading from modbus
    blacklist: list = None
    register: int = -1 # initialize with invalid register
    rounding: int = 1
    register_type: int = None # REGISTER_HOLDING or REGISTER_INPUT or REG_DATA
    unit: int = None # e.g. REGISTER_U16
    newblock: bool = False # set to True to start a new modbus read block operation - do not use frequently
    value_function: callable = None #  value = function(initval, descr, datadict)
    wordcount: int = None # only for unit = REGISTER_STR and REGISTER_WORDS
    sleepmode: int = SLEEPMODE_LAST # or SLEEPMODE_ZERO or SLEEPMODE_NONE

@dataclass
class BaseModbusButtonEntityDescription(ButtonEntityDescription):
    allowedtypes: int = 0 # overload with ALLDEFAULT from plugin  
    register: int = None
    command: int = None
    blacklist: list = None # none or list of serial number prefixes
    write_method: int = WRITE_SINGLE_MODBUS # WRITE_SINGLE_MOBUS or WRITE_MULTI_MODBUS or WRITE_DATA_LOCAL
    value_function: callable = None #  value = function(initval, descr, datadict)
    autorepeat: str = None  # if not None: name of entity that contains autorepeat duration in seconds

@dataclass
class BaseModbusSelectEntityDescription(SelectEntityDescription):
    allowedtypes: int = 0 # overload with ALLDEFAULT from plugin
    register: int = None
    option_dict: dict = None
    reverse_option_dict: dict = None # autocomputed
    blacklist: list = None # none or list of serial number prefixes
    write_method: int = WRITE_SINGLE_MODBUS # WRITE_SINGLE_MOBUS or WRITE_MULTI_MODBUS or WRITE_DATA_LOCAL
    initvalue: int = None # initial default value for WRITE_DATA_LOCAL entities
    unit: int = None #  optional for WRITE_DATA_LOCAL e.g REGISTER_U16, REGISTER_S32 ...

@dataclass
class BaseModbusNumberEntityDescription(NumberEntityDescription):
    allowedtypes: int = 0 # overload with ALLDEFAULT from plugin
    register: int = None
    read_scale_exceptions: list = None
    fmt: str = None
    scale: float = 1 
    state: str = None
    max_exceptions: list = None   #  None or list with structue [ ('U50EC' , 40,) ]
    min_exceptions_minus: list = None # same structure as max_exceptions, values are applied with a minus
    blacklist: list = None # None or list of serial number prefixes like
    write_method: int = WRITE_SINGLE_MODBUS # WRITE_SINGLE_MOBUS or WRITE_MULTI_MODBUS or WRITE_DATA_LOCAL
    initvalue: int = None # initial default value for WRITE_DATA_LOCAL entities
    unit: int = None #  optional for WRITE_DATA_LOCAL e.g REGISTER_U16, REGISTER_S32 ...


# ========================= autorepeat aux functions to be used on hub.data dictionary ===============================

def autorepeat_set(datadict, entitykey, value):
    datadict['_repeatUntil'][entitykey] = value

def autorepeat_stop(datadict, entitykey):
    datadict['_repeatUntil'][entitykey] = 0

def autorepeat_remaining(datadict, entitykey, timestamp):
    remaining = datadict['_repeatUntil'].get(entitykey,0) - timestamp
    return int(remaining) if remaining >0 else 0

# ================================= Computed sensor value functions  =================================================

def value_function_pv_power_total(initval, descr, datadict):
    return  datadict.get('pv_power_1', 0) + datadict.get('pv_power_2',0) + datadict.get('pv_power_3',0)

def value_function_battery_output(initval, descr, datadict):
    val = datadict["battery_power_charge"]
    if val<0: return abs(val)
    else: return 0

def value_function_battery_input(initval, descr, datadict):
    val = datadict["battery_power_charge"]
    if val>0: return val
    else: return 0

def value_function_battery_output_solis(initval, descr, datadict):
    inout = datadict["battery_charge_direction"]
    val = datadict["battery_power"]
    if inout == 1: return abs(val)
    else: return 0

def value_function_battery_input_solis(initval, descr, datadict):
    inout = datadict["battery_charge_direction"]
    val = datadict["battery_power"]
    if inout == 0: return val
    else: return 0

def value_function_grid_import(initval, descr, datadict):
    val = datadict["measured_power"]
    if val<0: return abs(val)
    else: return 0

def value_function_grid_export(initval, descr, datadict):
    val = datadict["measured_power"]
    if val>0: return val
    else: return 0

def value_function_house_load(initval, descr, datadict):
    return (   datadict.get('pv_power_1', 0) +  datadict.get('pv_power_2', 0) + datadict.get('pv_power_3', 0)
             - datadict['battery_power_charge'] 
             - datadict['measured_power'] )

def value_function_house_load_alt(initval, descr, datadict):
    return ( datadict['inverter_load'] - datadict['measured_power'] )

def value_function_rtc(initval, descr, datadict):
    try:
        (rtc_seconds, rtc_minutes, rtc_hours, rtc_days, rtc_months, rtc_years, ) = initval
        val = f"{rtc_days:02}/{rtc_months:02}/{rtc_years:02} {rtc_hours:02}:{rtc_minutes:02}:{rtc_seconds:02}"
        return datetime.strptime(val, '%d/%m/%y %H:%M:%S')
    except: pass
    
def value_function_gen4time(initval, descr, datadict):
    h = initval % 256
    m = initval >> 8
    return f"{h:02d}:{m:02d}"

def value_function_gen23time(initval, descr, datadict):
    (h,m,) = initval
    return f"{h:02d}:{m:02d}"

def value_function_sofartime(initval, descr, datadict):
    m = initval % 256
    h = initval >> 8
    return f"{h:02d}:{m:02d}"

def value_function_firmware(initval, descr, datadict):
    m = initval % 256
    h = initval >> 8
    return f"{h}.{m:02d}"

# ================================= Computed Time Values =================================================

TIME_OPTIONS = { }
TIME_OPTIONS_GEN4 = { }
for h in range(0,24):
    for m in range(0, 60, 15):
        TIME_OPTIONS[m*256+h] = f"{h:02}:{m:02}" 
        TIME_OPTIONS_GEN4[h*256+m] = f"{h:02}:{m:02}" 
        if (h, m,) == (0,  0,): # add extra entry 00:01
            TIME_OPTIONS[1*256+h] = f"{h:02}:{m+1:02}"  
            TIME_OPTIONS_GEN4[h*256+1] = f"{h:02}:{m+1:02}" 
        if (h, m,) == (23, 45,): # add extra entry 23:59
            TIME_OPTIONS[(m+14)*256+h] = f"{h:02}:{m+14:02}"
            TIME_OPTIONS_GEN4[h*256+m+14] = f"{h:02}:{m+14:02}" 
