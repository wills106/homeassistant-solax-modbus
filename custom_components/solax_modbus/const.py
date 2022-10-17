
import logging
from homeassistant.components.sensor import (
    SensorEntityDescription,
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
    FREQUENCY_HERTZ,
    PERCENTAGE,
    POWER_KILO_WATT,
    POWER_VOLT_AMPERE,
    POWER_WATT,
    TEMP_CELSIUS,
    TIME_HOURS,
    TIME_MINUTES,
)


# ================================= Definitions for config_flow ==========================================================

DOMAIN = "solax_modbus"
DEFAULT_NAME = "SolaX"
DEFAULT_SCAN_INTERVAL = 15
DEFAULT_PORT = 502
DEFAULT_MODBUS_ADDR = 1
CONF_READ_EPS    = "read_eps"
CONF_READ_DCB    = "read_dcb"
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
DEFAULT_BAUDRATE = "19200"
DEFAULT_PLUGIN   = "custom_components/solax_modbus/plugin_solax.py"
PLUGIN_PATH      = "custom_components/solax_modbus/plugin_*.py"

# ================================= Definitions for Sennsor Declarations =================================================

REG_HOLDING = 1
REG_INPUT   = 2
REGISTER_U16 = "uint16"
REGISTER_U32 = "uint32"
REGISTER_S16 = "int16"
REGISTER_S32 = "int32"
REGISTER_ULSB16MSB16 = "ulsb16msb16" # probably same as REGISTER_U32 - suggest to remove later
REGISTER_STR = "string"  # nr of bytes must be specified in wordcount and is 2*wordcount
REGISTER_WORDS = "words" # nr or words must be specified in wordcount
REGISTER_U8L = "int8L"
REGISTER_U8H = "int8H"


# ==================================== plugin access ====================================================================

_LOGGER = logging.getLogger(__name__)
glob_plugin = {}

def setPlugin(instancename, plugin):
    global glob_plugin
    glob_plugin[instancename] = plugin 

def getPlugin(instancename):
    return glob_plugin.get(instancename)

def getPluginName(plugin_path):
    return plugin_path[len(PLUGIN_PATH)-4:-3]

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
    register_type: int = None # REGISTER_HOLDING or REGISTER_INPUT
    unit: int = None # e.g. REGISTER_U16
    order16: int = None # Endian.Big or Endian.Little
    order32: int = None
    newblock: bool = False # set to True to start a new modbus read block operation - do not use frequently
    value_function: callable = None #  value = function(initval, descr, datadict)
    wordcount: int = None # only for unit = REGISTER_STR and REGISTER_WORDS

@dataclass
class BaseModbusButtonEntityDescription(ButtonEntityDescription):
    allowedtypes: int = 0 # overload with ALLDEFAULT from plugin  
    register: int = None
    command: int = None
    blacklist: list = None # none or list of serial number prefixes

@dataclass
class BaseModbusSelectEntityDescription(SelectEntityDescription):
    allowedtypes: int = 0 # overload with ALLDEFAULT from plugin
    register: int = None
    option_dict: dict = None
    blacklist: list = None # none or list of serial number prefixes

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

