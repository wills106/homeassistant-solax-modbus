
import logging
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntityDescription,
)
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from homeassistant.helpers.entity import EntityCategory
from pymodbus.payload import Endian
from datetime import datetime, timedelta
from dataclasses import dataclass, replace
import pathlib

from homeassistant.const import (
    PERCENTAGE,
    POWER_VOLT_AMPERE_REACTIVE,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
    CONF_SCAN_INTERVAL,
)


# ================================= Definitions for config_flow ==========================================================

DOMAIN = "solax_modbus"
INVERTER_IDENT = "inverter"
DEFAULT_NAME = "SolaX"
DEFAULT_INVERTER_NAME_SUFFIX = "Inverter"
DEFAULT_SCAN_INTERVAL = 15
DEFAULT_PORT = 502
DEFAULT_MODBUS_ADDR = 1
DEFAULT_TCP_TYPE = "tcp"
CONF_TCP_TYPE = "tcp_type"
TMPDATA_EXPIRY   = 120 # seconds before temp entities return to modbus value
CONF_INVERTER_NAME_SUFFIX = "inverter_name_suffix"
CONF_READ_EPS    = "read_eps"
CONF_READ_DCB    = "read_dcb"
CONF_READ_PM    = "read_pm"
CONF_MODBUS_ADDR = "read_modbus_addr"
CONF_INTERFACE   = "interface"
CONF_SERIAL_PORT = "read_serial_port"
CONF_SolaX_HUB   = "solax_hub"
CONF_BAUDRATE    = "baudrate"
CONF_PLUGIN      = "plugin"
CONF_READ_BATTERY = "read_battery"
ATTR_MANUFACTURER = "SolaX Power"
DEFAULT_INTERFACE  = "tcp"
DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_READ_EPS = False
DEFAULT_READ_DCB = False
DEFAULT_READ_PM = False
DEFAULT_BAUDRATE = "19200"
DEFAULT_PLUGIN        = "solax"
DEFAULT_READ_BATTERY = False
PLUGIN_PATH = f"{pathlib.Path(__file__).parent.absolute()}/plugin_*.py"
SLEEPMODE_NONE   = None
SLEEPMODE_ZERO   = 0 # when no communication at all
SLEEPMODE_LAST   = 1 # when no communication at all
SLEEPMODE_LASTAWAKE = 2 # when still responding but register must be ignored when not awake
#keys for config
CONF_SCAN_INTERVAL_MEDIUM = "scan_interval_medium"
CONF_SCAN_INTERVAL_FAST   = "scan_interval_fast"
#values for scan_group attribute
SCAN_GROUP_DEFAULT = CONF_SCAN_INTERVAL             # default scan group, slow; should always work
SCAN_GROUP_MEDIUM  = CONF_SCAN_INTERVAL_MEDIUM      # medium speed scanning (energy, temp, soc...)
SCAN_GROUP_FAST    = CONF_SCAN_INTERVAL_FAST        # fast scanning (power,...)

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
class base_battery_config:
    def __init__(
        self
    ):
        self.battery_sensor_type: list[SelectEntityDescription] | None = None
        self.battery_sensor_name_prefix: str | None = None
        self.battery_sensor_key_prefix: str | None = None

@dataclass
class plugin_base:
    plugin_name: str
    plugin_manufacturer: str
    SENSOR_TYPES: list[SensorEntityDescription]
    BUTTON_TYPES: list[ButtonEntityDescription]
    NUMBER_TYPES: list[NumberEntityDescription]
    SELECT_TYPES: list[SelectEntityDescription]
    BATTERY_CONFIG: base_battery_config | None = None
    block_size: int = 100
    auto_block_ignore_readerror: bool | None = None # if True or False, inserts a ignore_readerror statement for each block
    order16: int | None = None # Endian.BIG or Endian.LITTLE
    order32: int | None = None
    inverter_model: str = None

    def isAwake(self, datadict):
        return True # always awake by default

    def wakeupButton(self):
        return None # no wakeup button

    async def async_determineInverterType(self, hub, configdict):
        return 0

    async def async_determineInverterData(self, hub, configdict):
        return False

    def matchInverterWithMask (self, inverterspec, entitymask, serialnumber = 'not relevant', blacklist = None):
        return False

    def localDataCallback(self, hub): # called when local data is updated or on startup
        return True

    def getModel(self, new_data):
        return None

    def getSoftwareVersion(self, new_data):
        return None

    def getHardwareVersion(self, new_data):
        return None

# =================================== base class for sensor entity descriptions =========================================

@dataclass
class BaseModbusSensorEntityDescription(SensorEntityDescription):
    """ base class for modbus sensor declarations """
    allowedtypes: int = 0 # overload with ALLDEFAULT from plugin
    scale: float = 1 # can be float, dictionary or callable function(initval, descr, datadict)
    read_scale_exceptions: list = None # additional scaling when reading from modbus
    read_scale: float = 1
    blacklist: list = None
    register: int = -1 # initialize with invalid register
    rounding: int = 1
    register_type: int = None # REGISTER_HOLDING or REGISTER_INPUT or REG_DATA
    unit: int = None # e.g. REGISTER_U16
    scan_group: int = None # <=0 -> default group
    internal: bool = False # internal sensors are used for reading data only; used for computed, selects, etc
    newblock: bool = False # set to True to start a new modbus read block operation - do not use frequently
    #prevent_update: bool = False # if set to True, value will not be re-read/updated with each polling cycle; only when read value changes
    value_function: callable = None #  value = function(initval, descr, datadict)
    wordcount: int = None # only for unit = REGISTER_STR and REGISTER_WORDS
    sleepmode: int = SLEEPMODE_LAST # or SLEEPMODE_ZERO or SLEEPMODE_NONE
    ignore_readerror: bool = False # if not False, ignore read errors for this block and return this static value
                                   # A failing block read will be accepted as valid block if the first entity of the block contains a non-False ignore_readerror attribute.
                                   # The other entitties of the block can also have an ignore_readerror attribute that determines the value returned upon failure
                                   # so typically this attribute can be set to None or "Unknown" or any other value
                                   # This only works if the first entity of a block contains this attribute
                                   # When simply set to True, no initial value will be returned, but the block will be considered valid
    value_series: int = None # if not None, the value is part of a series of values with similar properties
                             # The name and key must contain a placeholder {} that is replaced by the preceding number

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
    read_scale: float = 1
    fmt: str = None
    scale: float = 1
    state: str = None
    max_exceptions: list = None   #  None or list with structue [ ('U50EC' , 40,) ]
    min_exceptions_minus: list = None # same structure as max_exceptions, values are applied with a minus
    blacklist: list = None # None or list of serial number prefixes like
    write_method: int = WRITE_SINGLE_MODBUS # WRITE_SINGLE_MOBUS or WRITE_MULTI_MODBUS or WRITE_DATA_LOCAL
    initvalue: int = None # initial default value for WRITE_DATA_LOCAL entities
    unit: int = None #  optional for WRITE_DATA_LOCAL e.g REGISTER_U16, REGISTER_S32 ...
    prevent_update: bool = False # if set to True, value will not be re-read/updated with each polling cycle; only when read value changes


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
    val = datadict.get('battery_power_charge', 0)
    if val<0: return abs(val)
    else: return 0

def value_function_battery_input(initval, descr, datadict):
    val = datadict.get('battery_power_charge', 0)
    if val>0: return val
    else: return 0

def value_function_battery_output_solis(initval, descr, datadict):
    inout = datadict.get('battery_charge_direction', 0)
    val = datadict.get('battery_power', 0)
    if inout == 1: return abs(val)
    else: return 0

def value_function_battery_input_solis(initval, descr, datadict):
    inout = datadict.get('battery_charge_direction', 0)
    val = datadict.get('battery_power', 0)
    if inout == 0: return val
    else: return 0

def value_function_grid_import(initval, descr, datadict):
    val = datadict.get('measured_power', 0)
    if val<0: return abs(val)
    else: return 0

def value_function_grid_export(initval, descr, datadict):
    val = datadict.get('measured_power', 0)
    if val>0: return val
    else: return 0

def value_function_house_load(initval, descr, datadict):
    return ( datadict.get('inverter_load', 0) - datadict.get('measured_power', 0) + datadict.get('meter_2_measured_power', 0) )

def value_function_house_load_alt(initval, descr, datadict):
    return (   datadict.get('pv_power_1', 0) +  datadict.get('pv_power_2', 0) + datadict.get('pv_power_3', 0)
             - datadict.get('battery_power_charge', 0)
             - datadict.get('measured_power', 0)
             + datadict.get('meter_2_measured_power', 0) )

def value_function_sync_rtc(initval, descr, datadict):
    now = datetime.now()
    return [ (REGISTER_U16, now.second, ),
             (REGISTER_U16, now.minute, ),
             (REGISTER_U16, now.hour, ),
             (REGISTER_U16, now.day, ),
             (REGISTER_U16, now.month, ),
             (REGISTER_U16, now.year % 100, ),
           ]

def value_function_sync_rtc_ymd(initval, descr, datadict):
    offset = datadict.get('sync_rtc_offset', 0)
    if isinstance(offset, float) or isinstance(offset, int):
        now = datetime.now() + timedelta(seconds=offset)
    else:
        now = datetime.now()

    return [ (REGISTER_U16, now.year % 100, ),
             (REGISTER_U16, now.month, ),
             (REGISTER_U16, now.day, ),
             (REGISTER_U16, now.hour, ),
             (REGISTER_U16, now.minute, ),
             (REGISTER_U16, now.second, ),
           ]

def value_function_rtc(initval, descr, datadict):
    try:
        (rtc_seconds, rtc_minutes, rtc_hours, rtc_days, rtc_months, rtc_years, ) = initval
        val = f"{rtc_days:02}/{rtc_months:02}/{rtc_years:02} {rtc_hours:02}:{rtc_minutes:02}:{rtc_seconds:02}"
        return datetime.strptime(val, '%d/%m/%y %H:%M:%S') # ok since sensor.py has been adapted
    except: pass

def value_function_rtc_ymd(initval, descr, datadict):
    try:
        (rtc_years, rtc_months, rtc_days, rtc_hours, rtc_minutes, rtc_seconds, ) = initval
        val = f"{rtc_days:02}/{rtc_months:02}/{rtc_years:02} {rtc_hours:02}:{rtc_minutes:02}:{rtc_seconds:02}"
        return datetime.strptime(val, '%d/%m/%y %H:%M:%S') # ok since sensor.py has been adapted
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

def value_function_2byte_timestamp(initval, descr, datadict):
    # Real-time data timestamp
    # Bit0-5: second, range 0-59
    # Bit6-11: minute, range 0-59
    # Bit12-16: hour, range 0-23
    # Bit17-21: day, range 1-31
    # Bit22-25: month, range 1-12
    # Bit26-31: year, range 0-63 (from the year 2000)"
    try:
        second = initval & 0b111111
        initval = initval >> 6
        minute = initval & 0b111111
        initval = initval >> 6
        hour = initval & 0b11111
        initval = initval >> 5
        day = initval & 0b11111
        initval = initval >> 5
        month = initval & 0b1111
        initval = initval >> 4
        year = initval & 0b111111
        val = f"{day:02}/{month:02}/{year:02} {hour:02}:{minute:02}:{second:02}"
        return datetime.strptime(val, '%d/%m/%y %H:%M:%S')
    except:   # noqa: E722
        pass

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
