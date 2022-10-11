

from homeassistant.components.sensor import (
    SensorEntityDescription,
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_TOTAL_INCREASING,
)

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
    DEVICE_CLASS_TEMPERATURE,
    DEVICE_CLASS_VOLTAGE,
    ELECTRIC_CURRENT_AMPERE,
    ELECTRIC_CURRENT_MILLIAMPERE,
    ELECTRIC_POTENTIAL_VOLT,
    ENERGY_KILO_WATT_HOUR,
    ENERGY_MEGA_WATT_HOUR,
    FREQUENCY_HERTZ,
    PERCENTAGE,
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
ATTR_MANUFACTURER = "SolaX Power"
DEFAULT_INTERFACE  = "tcp"
DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_READ_EPS = False
DEFAULT_READ_DCB = False
DEFAULT_BAUDRATE = "19200"



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
REGISTER_U8L = "int8"


# ==================================== plugin access ====================================================================

glob_plugin = None

def setPlugin(plugin):
    global glob_plugin 
    glob_plugin = plugin 

def getPlugin():
    return glob_plugin



# =================================== base class for sensor entity descriptions =========================================

@dataclass
class BaseModbusSensorEntityDescription(SensorEntityDescription):
    """ base class for modbus sensor declarations """
    allowedtypes: int = 0 # overload with ALLDEFAULT from plugin
    scale: float = 1 # can be float, dictionary or callable function(initval, descr, datadict)
    scale_exceptions: list = None
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

