
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
#DEFAULT_PLUGIN   = "/config/custom_components/solax_modbus/plugin_solax.py"
DEFAULT_PLUGIN        = "solax"
#PLUGIN_PATH           = "/config/custom_components/solax_modbus/plugin_*.py"
PLUGIN_PATH = f"{pathlib.Path(__file__).parent.absolute()}/plugin_*.py"
SLEEPMODE_NONE   = None
SLEEPMODE_ZERO   = 0 # when no communication at all
SLEEPMODE_LAST   = 1 # when no communication at all
SLEEPMODE_LASTAWAKE = 2 # when still responding but register must be ignored when not awake
STOP_AUTOREPEAT  = "_stop_autorepeat"


# ================================= Definitions for Sennsor Declarations =================================================

REG_HOLDING = 1  # modbus holding register
REG_INPUT   = 2  # modbus input register
#REG_DATA    = 3  # local data storage register, no direct modbus relation
REGISTER_U16 = "uint16"
REGISTER_U32 = "uint32"
REGISTER_S16 = "int16"
REGISTER_S32 = "int32"
REGISTER_ULSB16MSB16 = "ulsb16msb16" # probably same as REGISTER_U32 - suggest to remove later
REGISTER_STR = "string"  # nr of bytes must be specified in wordcount and is 2*wordcount
REGISTER_WORDS = "words" # nr or words must be specified in wordcount
REGISTER_U8L = "int8L"
REGISTER_U8H = "int8H"
WRITE_SINGLE_MODBUS       = 1 # use write_single_modbus command
WRITE_MULTISINGLE_MODBUS  = 2 # use write_mutiple modbus command for single register
WRITE_DATA_LOCAL          = 3 # write only to local data storage (not persistent)
WRITE_MULTI_MODBUS        = 4 # use write_multiple modbus command


_LOGGER = logging.getLogger(__name__)

# ==================================== plugin access ====================================================================




"""
glob_plugin = {}

def setPlugin(instancename, plugin):
    global glob_plugin
    glob_plugin[instancename] = plugin 

def getPlugin(instancename):
    return glob_plugin.get(instancename)

def getPluginName(plugin_path):
    _LOGGER.error(f"get plugin name: path: {plugin_path} name: {plugin_path[len(PLUGIN_PATH)-4:-3]}")
    return plugin_path[len(PLUGIN_PATH)-4:-3]

"""

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
    #order16: int = None # Endian.Big or Endian.Little
    #order32: int = None
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
    blacklist: list = None # None or list of serial number prefixes like
    write_method: int = WRITE_SINGLE_MODBUS # WRITE_SINGLE_MOBUS or WRITE_MULTI_MODBUS or WRITE_DATA_LOCAL
    initvalue: int = None # initial default value for WRITE_DATA_LOCAL entities
    unit: int = None #  optional for WRITE_DATA_LOCAL e.g REGISTER_U16, REGISTER_S32 ...

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

TIME_OPTIONS = {
    0: "00:00",
    256: "00:01",
    3840: "00:15",
    7680: "00:30",
    11520: "00:45",
    1: "01:00",
    3841: "01:15",
    7681: "01:30",
    11521: "01:45",
    2: "02:00",
    3842: "02:15",
    7682: "02:30",
    11522: "02:45",
    3: "03:00",
    3843: "03:15",
    7683: "03:30",
    11523: "03:45",
    4: "04:00",
    3844: "04:15",
    7684: "04:30",
    11524: "04:45",
    5: "05:00",
    3845: "05:15",
    7685: "05:30",
    11525: "05:45",
    6: "06:00",
    3846: "06:15",
    7686: "06:30",
    11526: "06:45",
    7: "07:00",
    3847: "07:15",
    7687: "07:30",
    11527: "07:45",
    8: "08:00",
    3848: "08:15",
    7688: "08:30",
    11528: "08:45",
    9: "09:00",
    3849: "09:15",
    7689: "09:30",
    11529: "09:45",
    10: "10:00",
    3850: "10:15",
    7690: "10:30",
    11530: "10:45",
    11: "11:00",
    3851: "11:15",
    7691: "11:30",
    11531: "11:45",
    12: "12:00",
    3852: "12:15",
    7692: "12:30",
    11532: "12:45",
    13: "13:00",
    3853: "13:15",
    7693: "13:30",
    11533: "13:45",
    14: "14:00",
    3854: "14:15",
    7694: "14:30",
    11534: "14:45",
    15: "15:00",
    3855: "15:15",
    7695: "15:30",
    11535: "15:45",
    16: "16:00",
    3856: "16:15",
    7696: "16:30",
    11536: "16:45",
    17: "17:00",
    3857: "17:15",
    7697: "17:30",
    11537: "17:45",
    18: "18:00",
    3858: "18:15",
    7698: "18:30",
    11538: "18:45",
    19: "19:00",
    3859: "19:15",
    7699: "19:30",
    11539: "19:45",
    20: "20:00",
    3860: "20:15",
    7700: "20:30",
    11540: "20:45",
    21: "21:00",
    3861: "21:15",
    7701: "21:30",
    11541: "21:45",
    22: "22:00",
    3862: "22:15",
    7702: "22:30",
    11542: "22:45",
    23: "23:00",
    3863: "23:15",
    7703: "23:30",
    11543: "23:45", 
    15127: "23:59", # default value for Gen4 discharger_end_time_1 , maybe not a default for Gen2,Gen3
}

TIME_OPTIONS_GEN4 = { 
    0: "00:00",
    1: "00:01",
    15: "00:15",
    30: "00:30",
    45: "00:45",
    256: "01:00",
    271: "01:15",
    286: "01:30",
    301: "01:45",
    512: "02:00",
    527: "02:15",
    542: "02:30",
    557: "02:45",
    768: "03:00",
    783: "03:15",
    798: "03:30",
    813: "03:45",
    1024: "04:00",
    1039: "04:15",
    1054: "04:30",
    1069: "04:45",
    1280: "05:00",
    1295: "05:15",
    1310: "05:30",
    1325: "05:45",
    1536: "06:00",
    1551: "06:15",
    1566: "06:30",
    1581: "06:45",
    1792: "07:00",
    1807: "07:15",
    1822: "07:30",
    1837: "07:45",
    2048: "08:00",
    2063: "08:15",
    2078: "08:30",
    2093: "08:45",
    2304: "09:00",
    2319: "09:15",
    2334: "09:30",
    2349: "09:45",
    2560: "10:00",
    2575: "10:15",
    2590: "10:30",
    2605: "10:45",
    2816: "11:00",
    2831: "11:15",
    2846: "11:30",
    2861: "11:45",
    3072: "12:00",
    3087: "12:15",
    3132: "12:30",
    3117: "12:45",
    3328: "13:00",
    3343: "13:15",
    3358: "13:30",
    3373: "13:45",
    3584: "14:00",
    3599: "14:15",
    3614: "14:30",
    3629: "14:45",
    3840: "15:00",
    3855: "15:15",
    3870: "15:30",
    3885: "15:45",
    4096: "16:00",
    4111: "16:15",
    4126: "16:30",
    4141: "16:45",
    4352: "17:00",
    4367: "17:15",
    4382: "17:30",
    4397: "17:45",
    4608: "18:00",
    4623: "18:15",
    4638: "18:30",
    4653: "18:45",
    4864: "19:00",
    4879: "19:15",
    4894: "19:30",
    4909: "19:45",
    5120: "20:00",
    5135: "20:15",
    5150: "20:30",
    5165: "20:45",
    5376: "21:00",
    5391: "21:15",
    5406: "21:30",
    5421: "21:45",
    5632: "22:00",
    5647: "22:15",
    5662: "22:30",
    5677: "22:45",
    5888: "23:00",
    5903: "23:15",
    5918: "23:30",
    5933: "23:45",
    5947: "23:59", # default value for discharger_end_time1
}