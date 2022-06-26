from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntityDescription,
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_TOTAL_INCREASING,
)
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription

from homeassistant.const import (
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_CURRENT,
    DEVICE_CLASS_ENERGY,
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
)


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

GEN_GROUP_BITS = 0x00FF # inverter generation bits
GEN2             = 0x0002
GEN3             = 0x0004
GEN4             = 0x0008
#MIC             = 0x0010 Might be needed if it turns out the MIC uses different registers to the GenX

X13_GROUP_BITS = 0x0300 # X1 or X3 model flags
X1               = 0x0100
X3               = 0x0200

HYB_GROUP_BITS = 0x1C00 # hybrid or AC or PV flags
PV               = 0x0400 # Needs further work on PV Only Inverters
AC               = 0x0800
HYBRID           = 0x1000

EPS_GROUP_BITS = 0x8000  # EPS flag
EPS              = 0x8000


ALLDEFAULT = 0 # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3 


def matchInverterWithMask (inverterspec, entitymask, serialnumber = 'not relevant', blacklist = None):
    # returns true if the entity needs to be created for an inverter
    genmatch = ((inverterspec & entitymask & GEN_GROUP_BITS) != 0) or (entitymask & GEN_GROUP_BITS == 0)
    xmatch   = ((inverterspec & entitymask & X13_GROUP_BITS) != 0) or (entitymask & X13_GROUP_BITS == 0)
    hybmatch = ((inverterspec & entitymask & HYB_GROUP_BITS) != 0) or (entitymask & HYB_GROUP_BITS == 0)
    epsmatch = ((inverterspec & entitymask & EPS_GROUP_BITS) != 0) or (entitymask & EPS_GROUP_BITS == 0)
    blacklisted = False
    if blacklist:
        for start in blacklist: 
            if serialnumber.startswith(start) : blacklisted = True
    return (genmatch and xmatch and hybmatch and epsmatch) and not blacklisted

"""
end of bitmask handling code
==============================================================================================="""


DOMAIN = "solax_modbus"
DEFAULT_NAME = "SolaX"
DEFAULT_SCAN_INTERVAL = 15
DEFAULT_PORT = 502
DEFAULT_MODBUS_ADDR = 1
CONF_READ_EPS    = "read_eps"
CONF_MODBUS_ADDR = "read_modbus_addr"
CONF_SERIAL      = "read_serial"
CONF_SERIAL_PORT = "read_serial_port"
CONF_SolaX_HUB   = "solax_hub"
ATTR_MANUFACTURER = "SolaX Power"
DEFAULT_SERIAL      = False
DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_READ_EPS = False


# ================================= Button Declarations ============================================================

@dataclass
class SolaxModbusButtonEntityDescription(ButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice
    register: int = None
    command: int = None
    blacklist: list = None # none or list of serial number prefixees

BUTTON_TYPES = [
    SolaxModbusButtonEntityDescription( name = "Battery Awaken",
        key = "battery_awaken",
        register = 0x56,
        command = 1,
        allowedtypes = ALLDEFAULT,
    ),
    SolaxModbusButtonEntityDescription( name = "Unlock Inverter",
        key = "unlock_inverter",
        register = 0x00,
        command = 2014,
        allowedtypes = ALLDEFAULT,
    ),
    SolaxModbusButtonEntityDescription( name = "Unlock Inverter - Advanced",
        key = "unlock_inverter_advanced",
        register = 0x00,
        command = 6868,
        allowedtypes = ALLDEFAULT,
    ),
]

# ================================= Number Declarations ============================================================

MAX_CURRENTS = [
    ('L30E',  100 ), # Gen2 X1 SK-TL
    ('U30',    50 ), # Gen2 X1 SK-SU
    ('L37E',  100 ), # Gen2 X1 SK-TL
    ('U37',    50 ), # Gen2 X1 SK-SU
    ('L50E',  100 ), # Gen2 X1 SK-TL
    ('U50',    50 ), # Gen2 X1 SK-SU
    ('F3E',    25 ), # RetroFit X3
    ('H3DE',    25 ), # Gen3 X3 might need changing?
    ('H3PE',    25 ), # Gen3 X3 might need changing?
    ('H3UE',    25 ), # Gen3 X3
    ('H437',   30 ), # Gen4 X1 3.7kW
    ('H450',   30 ), # Gen4 X1 5kW
    ('H460',   30 ), # Gen4 X1 6kW
    ('H475',   30 ), # Gen4 X1 7.5kW
    ('H34B',    30 ), # Gen4 X3 B
    ('H34T',    25 ), # Gen4 X3 T
    ### All known Inverters added
]

@dataclass
class SolaxModbusNumberEntityDescription(NumberEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice
    register: int = None
    fmt: str = None
    state: str = None
    max_exceptions: list = None  #  None or dict with structue { 'U50EC' : 40 } 
    blacklist: list = None # None or list of serial number prefixes like 

NUMBER_TYPES = [
    SolaxModbusNumberEntityDescription( name = "Battery Minimum Capacity",
        key = "battery_minimum_capacity",
        register = 0x20,
        fmt = "i",
        min_value = 0,
        max_value = 99,
        step = 1,
        unit_of_measurement = PERCENTAGE,
        state = "battery_capacity_charge",
        allowedtypes = GEN2 | GEN3,
    ),
    SolaxModbusNumberEntityDescription( name = "Battery Minimum Capacity - Grid-tied",
        key = "battery_minimum_capacity_gridtied",
        register = 0xa7,
        fmt = "i",
        min_value = 28,
        max_value = 99,
        step = 1,
        unit_of_measurement = PERCENTAGE,
        state = "battery_minimum_capacity_gridtied",
        allowedtypes = HYBRID | GEN3,
    ),
    SolaxModbusNumberEntityDescription( name = "Battery Charge Max Current", # multiple versions depending on GEN
        key = "battery_charge_max_current",
        register = 0x24,
        fmt = "f",
        min_value = 0,
        max_value = 20, # default (new default, was 50)
        step = 0.1,
        unit_of_measurement = ELECTRIC_CURRENT_AMPERE,
        allowedtypes = GEN2 | GEN3 | GEN4,
        max_exceptions = MAX_CURRENTS,
    ),
    SolaxModbusNumberEntityDescription( name = "Battery Discharge Max Current", 
        key = "battery_discharge_max_current",
        register = 0x25,
        fmt = "f",
        min_value = 0,
        max_value = 20, # universal default
        step = 0.1,
        unit_of_measurement = ELECTRIC_CURRENT_AMPERE,
        allowedtypes = GEN2 | GEN3 | GEN4,
        max_exceptions = MAX_CURRENTS,
    ),
    SolaxModbusNumberEntityDescription( name = "ForceTime Period 1 Max Capacity",
        key ="forcetime_period_1_max_capacity",
        register = 0xA4,
        fmt = "i",
        min_value = 5,
        max_value = 100,
        step = 1,
        unit_of_measurement = PERCENTAGE,
        allowedtypes = GEN3,
    ),
    SolaxModbusNumberEntityDescription( name = "ForceTime Period 2 Max Capacity",
        key = "forcetime_period_2_max_capacity",
        register = 0xA5,
        fmt = "i",
        min_value = 5,
        max_value = 100,
        step = 1,
        unit_of_measurement = PERCENTAGE,
        allowedtypes = GEN3,
    ),
    SolaxModbusNumberEntityDescription( name = "Export Control User Limit",
        key = "export_control_user_limit", 
        register = 0x42,
        fmt = "i",
        min_value = 0,
        max_value = 60000,
        step = 500,
        unit_of_measurement = POWER_WATT,
        allowedtypes = GEN4,
    ),
    SolaxModbusNumberEntityDescription( name = "Selfuse Discharge Min SOC",
        key ="selfuse_discharge_min_soc",
        register = 0x61,
        fmt = "i",
        min_value = 10,
        max_value = 100,
        step = 1,
        unit_of_measurement = PERCENTAGE,
        allowedtypes = GEN4,
    ),
    SolaxModbusNumberEntityDescription( name = "Selfuse Nightcharge Upper SOC",
        key = "selfuse_nightcharge_upper_soc", 
        register = 0x63,
        fmt = "i",
        min_value = 10,
        max_value = 100,
        step = 1,
        unit_of_measurement = PERCENTAGE,
        allowedtypes = GEN4,
    ),
    SolaxModbusNumberEntityDescription( name = "Feedin Nightcharge Upper SOC",
        key = "feedin_nightcharge_upper_soc", 
        register = 0x64,
        fmt = "i",
        min_value = 10,
        max_value = 100,
        step = 1,
        unit_of_measurement = PERCENTAGE,
        allowedtypes = GEN4,
    ),
    SolaxModbusNumberEntityDescription( name = "Feedin Discharge Min SOC",
        key = "feedin_discharge_min_soc",
        register = 0x65,
        fmt = "i",
        min_value = 10,
        max_value = 100,
        step = 1,
        unit_of_measurement = PERCENTAGE,
        allowedtypes = GEN4,
    ),
    SolaxModbusNumberEntityDescription( name = "Backup Nightcharge Upper SOC",
        key = "backup_nightcharge_upper_soc", 
        register = 0x66,
        fmt = "i",
        min_value = 10,
        max_value = 100,
        step = 1,
        unit_of_measurement = PERCENTAGE,
        allowedtypes = GEN4,
    ),
    SolaxModbusNumberEntityDescription( name = "Backup Discharge Min SOC",
        key = "backup_discharge_min_soc",
        register = 0x67,
        fmt = "i",
        min_value = 10,
        max_value = 100,
        step = 1,
        unit_of_measurement = PERCENTAGE,
        allowedtypes = GEN4,
    ),
]

# ================================= Select Declarations ============================================================


TIME_OPTIONS = {
    0: "00:00",
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

@dataclass
class SolaxModbusSelectEntityDescription(SelectEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice
    register: int = None
    options: dict = None
    blacklist: list = None # none or list of serial number prefixes

SELECT_TYPES = [
    SolaxModbusSelectEntityDescription( name = "Charger Use Mode",
        key = "charger_use_mode",
        register = 0x1F,
        options = {
            0: "Self Use Mode",
            1: "Force Time Use",
            2: "Back Up Mode",
            3: "Feedin Priority",
        },
        allowedtypes = GEN2 | GEN3,
    ),
    SolaxModbusSelectEntityDescription( name = "Charger Use Mode",
        key = "charger_use_mode",
        register = 0x1F,
        options = {
                0: "Self Use Mode",
                1: "Feedin Priority",
                2: "Back Up Mode",
                3: "Manual Mode",
            },
        allowedtypes = GEN4, 
    ),
    SolaxModbusSelectEntityDescription( name = "Manual Mode Select",
        key = "manual_mode",
        register = 0x20,
        options = {
                0: "Stop Charge and Discharge",
                1: "Force Charge",
                2: "Force Discharge",
            },
        allowedtypes = GEN4, 
    ),
    SolaxModbusSelectEntityDescription( name = "Allow Grid Charge",
        key = "allow_grid_charge",
        register = 0x40,
        options =  {
                0: "Both Forbidden",
                1: "Period 1 Allowed",
                2: "Period 2 Allowed",
                3: "Both Allowed",
            },
        allowedtypes = GEN2 | GEN3, 
    ),
    SolaxModbusSelectEntityDescription( name = "Charger Start Time 1",
        key = "charger_start_time_1",
        register = 0x26,
        options = TIME_OPTIONS,
        allowedtypes = GEN2 | GEN3, 
    ),
    SolaxModbusSelectEntityDescription( name = "Charger End Time 1",
        key = "charger_end_time_1",
        register = 0x27,
        options = TIME_OPTIONS,
        allowedtypes = GEN2 | GEN3, 
    ),
    SolaxModbusSelectEntityDescription( name = "Charger Start Time 2",
        key = "charger_start_time_2",
        register = 0x2A,
        options = TIME_OPTIONS,
        allowedtypes = GEN2 | GEN3, 
    ),
    SolaxModbusSelectEntityDescription( name = "Charger End Time 2",
        key = "charger_end_time_2",
        register = 0x2B,
        options = TIME_OPTIONS,
        allowedtypes = GEN2 | GEN3, 
    ),
    SolaxModbusSelectEntityDescription( name = "Cloud Control",
        key = "cloud_control",
        register = 0x99,
        options =  {
                0: "Disabled",
                1: "Enabled",
            },
        allowedtypes = AC | HYBRID | GEN3,
    ),
    SolaxModbusSelectEntityDescription( name = "Discharger Start Time 1",
        key = "discharger_start_time_1",
        register = 0x28,
        options = TIME_OPTIONS,
        allowedtypes = GEN2, # Probably remove Gen3 in future, not in Doc's
    ),
    SolaxModbusSelectEntityDescription( name = "Discharger End Time 1",
        key = "discharger_end_time_1",
        register = 0x29,
        options = TIME_OPTIONS,
        allowedtypes = GEN2, # Probably remove Gen3 in future, not in Doc's
    ),
    SolaxModbusSelectEntityDescription( name = "Discharger Start Time 2",
        key = "discharger_start_time_2",
        register = 0x2C,
        options = TIME_OPTIONS,
        allowedtypes = GEN2, # Probably remove Gen3 in future, not in Doc's
    ),
    SolaxModbusSelectEntityDescription( name = "Discharger End Time 2",
        key = "discharger_end_time_2",
        register = 0x2D,
        options = TIME_OPTIONS,
        allowedtypes = GEN2, # Probably remove Gen3 in future, not in Doc's
    ),
    SolaxModbusSelectEntityDescription( name = "Selfuse Night Charge Enable",
        key = "selfuse_nightcharge_enable",
        register = 0x62,
        options =  {
                0: "Disabled",
                1: "Enabled",
            },
        allowedtypes = GEN4, 
    ),
    SolaxModbusSelectEntityDescription( name = "Charge and Discharge Period2 Enable",
        key = "charge_period2_enable",
        register = 0x6C,
        options = {  
                0: "Disabled",
                1: "Enabled",
            },
        allowedtypes = GEN4, 
    ),
    SolaxModbusSelectEntityDescription( name = "Charger Start Time 1",
        key = "charger_start_time_1",
        register = 0x68,
        options = TIME_OPTIONS_GEN4,
        allowedtypes = GEN4, 
    ),
    SolaxModbusSelectEntityDescription( name = "Charger End Time 1",
        key = "charger_end_time_1",
        register = 0x69,
        options = TIME_OPTIONS_GEN4,
        allowedtypes = GEN4, 
    ),
    SolaxModbusSelectEntityDescription( name = "Discharger Start Time 1",
        key = "discharger_start_time_1",
        register = 0x6A,
        options = TIME_OPTIONS_GEN4,
        allowedtypes = GEN4, 
    ),
    SolaxModbusSelectEntityDescription( name = "Discharger End Time 1",
        key = "discharger_end_time_1",
        register = 0x6B,
        options = TIME_OPTIONS_GEN4,
        allowedtypes = GEN4, 
    ), 
    SolaxModbusSelectEntityDescription( name = "Charger Start Time 2",
        key = "charger_start_time_2",
        register = 0x6D,
        options = TIME_OPTIONS_GEN4,
        allowedtypes = GEN4, 
    ),
    SolaxModbusSelectEntityDescription( name = "Charger End Time 2",
        key = "charger_end_time_2",
        register = 0x6E,
        options = TIME_OPTIONS_GEN4,
        allowedtypes = GEN4, 
    ),
    SolaxModbusSelectEntityDescription( name = "Discharger Start Time 2",
        key = "discharger_start_time_2",
        register = 0x6F,
        options = TIME_OPTIONS_GEN4,
        allowedtypes = GEN4,
    ),
    SolaxModbusSelectEntityDescription( name = "Discharger End Time 2",
        key = "discharger_end_time_2",
        register = 0x70,
        options = TIME_OPTIONS_GEN4,
        allowedtypes = GEN4, 
    ),
]


# ================================= Sennsor Declarations ============================================================

@dataclass
class SolaXModbusSensorEntityDescription(SensorEntityDescription):
    """A class that describes SolaX Power Modbus sensor entities."""
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice
    blacklist: list = None # None or list of serial number prefixes



SENSOR_TYPES: list[SolaXModbusSensorEntityDescription] = [ 
    SolaXModbusSensorEntityDescription(
        name="Allow Grid Charge",
        key="allow_grid_charge",
        entity_registry_enabled_default=False,
        allowedtypes= GEN2 | GEN3 #ALLDEFAULT & ~GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Capacity",
        key="battery_capacity_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=DEVICE_CLASS_BATTERY,
        allowedtypes=ALLDEFAULT, 
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Charge Max Current",
        key="battery_charge_max_current",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Current Charge",
        key="battery_current_charge",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Discharge Cut Off Voltage",
        key="battery_discharge_cut_off_voltage",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Discharge Max Current",
        key="battery_discharge_max_current",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Install Capacity",
        key="battery_install_capacity",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        entity_registry_enabled_default=False,
        allowedtypes= GEN3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Minimum Capacity",
        key="battery_minimum_capacity",
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes= GEN2 | GEN3 #ALLDEFAULT & ~GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Minimum Capacity - Grid-tied",
        key="battery_minimum_capacity_gridtied",
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes= HYBRID | GEN3, 
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Package Number",
        key="battery_package_number",
        entity_registry_enabled_default=False,
        allowedtypes= GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Power Charge",
        key="battery_power_charge",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery State of Health",
        key="battery_soh",
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes= GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Type",
        key="battery_type",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Charge Float Voltage",
        key="battery_charge_float_voltage",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Input Energy Total",
        key="input_energy_charge",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Output Energy Total",
        key="output_energy_charge",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Temperature",
        key="battery_temperature",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Voltage Charge",
        key="battery_voltage_charge",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Volt Fault Val",
        key="battery_volt_fault_val",
        entity_registry_enabled_default=False,
        allowedtypes= GEN3 | GEN4,
    ),
    # Gen 3 & Gen4 only
    SolaXModbusSensorEntityDescription(
        name="BMS Charge Max Current",
        key="bms_charge_max_current",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    # Gen3 & Gen4 only, this is a different sensors on Gen2
    SolaXModbusSensorEntityDescription(
        name="BMS Connect State", 
        key="bms_connect_state",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    # Gen3 & Gen4 only
    SolaXModbusSensorEntityDescription(
        name="BMS Discharge Max Current",
        key="bms_discharge_max_current",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Bus Volt",
        key="bus_volt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charger Start Time 1",
        key="charger_start_time_1",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charger End Time 1",
        key="charger_end_time_1",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charger Start Time 2",
        key="charger_start_time_2",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charger End Time 2",
        key="charger_end_time_2",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Import Total",
        key="grid_import_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="DC Fault Val",
        key="dc_fault_val",
        entity_registry_enabled_default=False,
        allowedtypes= GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharger Start Time 1",
        key="discharger_start_time_1",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharger End Time 1",
        key="discharger_end_time_1",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharger Start Time 2",
        key="discharger_start_time_2",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharger End Time 2",
        key="discharger_end_time_2",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Yield",
        key="today_yield",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        allowedtypes= GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Export Control Factory Limit",
        key="export_control_factory_limit",
        native_unit_of_measurement=POWER_WATT,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Export Control User Limit",
        key="export_control_user_limit",
        native_unit_of_measurement=POWER_WATT,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Export Total",
        key="grid_export_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Group Read Test",
        key="group_read_test",
        icon="mdi:solar-power",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power",
        key="feedin_power",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Firmware Version Inverter Master",
        key="firmwareversion_invertermaster",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Firmware Version Manager",
        key="firmwareversion_manager",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Firmware Version Modbus TCP Major",
        key="firmwareversion_modbustcp_major",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Firmware Version Modbus TCP Minor",
        key="firmwareversion_modbustcp_minor",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency",
        key="grid_frequency",
        native_unit_of_measurement=FREQUENCY_HERTZ,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Import",
        key="grid_import",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Export",
        key="grid_export",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="House Load",
        key="house_load",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=ALLDEFAULT,
    ),    
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage",
        key="inverter_voltage",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current",
        key="inverter_current",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Model Number",
        key="inverter_model_number",
        entity_registry_enabled_default=False,
        allowedtypes= GEN3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power",
        key="inverter_load",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Language",
        key="language",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Lock State",
        key="lock_state",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Bootloader Version",
        key="bootloader_version",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Normal Runtime",
        key="normal_runtime",
        native_unit_of_measurement=TIME_HOURS,
        entity_registry_enabled_default=False,
        allowedtypes=GEN3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Overload Fault Val",
        key="overload_fault_val",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes=HYBRID | PV,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes=HYBRID | PV,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=HYBRID | PV,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=HYBRID | PV,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes=HYBRID | PV,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes=HYBRID | PV,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Total Power",
        key="pv_total_power",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes=HYBRID | PV,
    ),
    SolaXModbusSensorEntityDescription(
        name="Registration Code",
        key="registration_code",
        entity_registry_enabled_default=False,
        allowedtypes= GEN2 | GEN3, #ALLDEFAULT & ~GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="RTC",
        key="rtc",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Series Number",
        key="seriesnumber",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Solar Energy",
        key="solar_energy_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        allowedtypes= GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Solar Energy",
        key="today_yield",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        allowedtypes= GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Solar Energy",
        key="solar_energy_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        allowedtypes= GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Solar Energy",
        key="total_yield",
        native_unit_of_measurement=ENERGY_MEGA_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        allowedtypes= GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Yield",
        key="today_s_yield_gen2",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=True,
        allowedtypes= GEN2,
        blacklist=('U50EC',)
    ),
    SolaXModbusSensorEntityDescription(
        name="E Charge Today",
        key="e_charge_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        allowedtypes= GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="E Charge Total",
        key="e_charge_total",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        allowedtypes= GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Time Count Down",
        key="time_count_down",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Rated Power",
        key="inverter_rate_power",
        entity_registry_enabled_default=False,
        allowedtypes=ALLDEFAULT,
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Yield",
        key="total_yield",
        native_unit_of_measurement=ENERGY_MEGA_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        allowedtypes=GEN3 | GEN4,
    ),


    # tranferred from GEN4_SENSOR_TYPES
    SolaXModbusSensorEntityDescription(
        name="Selfuse Night Charge Upper SOC",
        key="selfuse_nightcharge_upper_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=DEVICE_CLASS_BATTERY,
        allowedtypes= GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Selfuse Night Charge Enable",
        key="selfuse_nightcharge_enable",
        allowedtypes = GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charge Period2 Enable",
        key="charge_period2_enable",
        entity_registry_enabled_default=False,
        allowedtypes = GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Selfuse Discharge Min SOC",
        key="selfuse_discharge_min_soc",
        allowedtypes = GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Shadow Fix Function Level",
        key="shadow_fix_enable",
        entity_registry_enabled_default=False,
        allowedtypes = GEN4,
     ),
    SolaXModbusSensorEntityDescription(
        name="Machine Type X1/X3",
        key="machine_type",
        entity_registry_enabled_default=False,
        allowedtypes = GEN4,
     ),
    SolaXModbusSensorEntityDescription(
        name="Manual Mode",
        key="manual_mode",
        allowedtypes = GEN4,
     ),
    SolaXModbusSensorEntityDescription(
        name="Feedin Discharge Min SOC",
        key="feedin_discharge_min_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=DEVICE_CLASS_BATTERY,
        allowedtypes = GEN4,
     ),
    SolaXModbusSensorEntityDescription(
        name="Feedin Night Charge Upper SOC",
        key="feedin_nightcharge_upper_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=DEVICE_CLASS_BATTERY,
        allowedtypes = GEN4,
     ),
    SolaXModbusSensorEntityDescription(
        name="Backup Discharge Min SOC",
        key="backup_discharge_min_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=DEVICE_CLASS_BATTERY,
        allowedtypes = GEN4,
     ),
    SolaXModbusSensorEntityDescription(
        name="Backup Night Charge Upper SOC",
        key="backup_nightcharge_upper_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=DEVICE_CLASS_BATTERY,
        allowedtypes = GEN4,
     ),


     # transferred fromm GEN3_X1_SENSOR_TYPES, some also from GEN3_X3_SENSOR_TYPES

    SolaXModbusSensorEntityDescription(
        name="Backup Charge End",
        key="backup_charge_end",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Backup Charge Start",
        key="backup_charge_start",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Backup Gridcharge",
        key="backup_gridcharge",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Input Energy Today",
        key="input_energy_charge_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        allowedtypes= X1 | X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Output Energy Today",
        key="output_energy_charge_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        allowedtypes= X1 | X3 | GEN3 | GEN4,
    ),
    # cloud_control should be X3 as well?
    SolaXModbusSensorEntityDescription(
        name="Cloud Control",
        key="cloud_control",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | GEN3,
    ),
    SolaXModbusSensorEntityDescription(
        name="CT Meter Setting",
        key="ct_meter_setting",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharge Cut Off Point Different",
        key="disch_cut_off_point_different",
        entity_registry_enabled_default=False,
        allowedtypes= GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharge Cut Off Voltage Grid Mode",
        key="disch_cut_off_voltage_grid_mode",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        entity_registry_enabled_default=False,
        allowedtypes= GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Export Energy",
        key="export_energy_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        allowedtypes= X1 | X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Forcetime Period 1 Maximum Capacity",
        key="forcetime_period_1_max_capacity",
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes= X1 | X3 | GEN3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Forcetime Period 2 Maximum Capacity",
        key="forcetime_period_2_max_capacity",
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes= X1 | X3 | GEN3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Global MPPT Function",
        key="global_mppt_function",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | X3 | GEN3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Import Energy",
        key="import_energy_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        allowedtypes= X1 | X3 | GEN3 | GEN4,
    ),
    # Should be X3 as well?
    SolaXModbusSensorEntityDescription(
        name="Machine Style",
        key="machine_style",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | X3 | GEN3 | GEN4,
    ),
    # Should be X3 as well?
    SolaXModbusSensorEntityDescription(
        name="Meter 1 id",
        key="meter_1_id",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | X3 | GEN3 | GEN4,
    ),
    # Should be X3 as well?
    SolaXModbusSensorEntityDescription(
        name="Meter 2 id",
        key="meter_2_id",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | X3 | GEN3 | GEN4,
    ),
    # Should be X3 as well?
    SolaXModbusSensorEntityDescription(
        name="Meter Function",
        key="meter_function",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Power Control Timeout",
        key="power_control_timeout",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="wAS4777 Power Manager",
        key="was4777_power_manager",
        entity_registry_enabled_default=False,
        allowedtypes= X1 | X3 |  GEN3,
    ),


    # transferred fromm GEN3_X3_SENSOR_TYPES
    SolaXModbusSensorEntityDescription(
        name="Earth Detect X3",
        key="earth_detect_x3",
        allowedtypes = X3 | GEN3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power R",
        key="feedin_power_r",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power S",
        key="feedin_power_s",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power T",
        key="feedin_power_t",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current R",
        key="grid_current_r",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current S",
        key="grid_current_s",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current T",
        key="grid_current_t",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Mode Runtime",
        key="grid_mode_runtime",
        native_unit_of_measurement=TIME_HOURS,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power R",
        key="grid_power_r",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power S",
        key="grid_power_s",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power T",
        key="grid_power_t",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Service X3",
        key="grid_service_x3",
        allowedtypes = X3 | GEN3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage R",
        key="grid_voltage_r",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage S",
        key="grid_voltage_s",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage T",
        key="grid_voltage_t",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes = X3 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Phase Power Balance X3",
        key="phase_power_balance_x3",
        allowedtypes = X3 | GEN3 | GEN4,
    ),

    # transferred from X1_EPS_SENSOR_TYPES

    SolaXModbusSensorEntityDescription(
        name="EPS Auto Restart",
        key="eps_auto_restart",
        allowedtypes = X1 | X3 | GEN2 | GEN3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Current",
        key="eps_current",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes = X1 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Frequency",
        key="eps_frequency",
        native_unit_of_measurement=FREQUENCY_HERTZ,
        allowedtypes = X1 | X3  | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Min Esc SOC",
        key="eps_min_esc_soc",
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes = X1 | X3 | GEN2 | GEN3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Min Esc Voltage",
        key="eps_min_esc_voltage",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        allowedtypes = X1 | X3 | GEN2 | GEN3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Mute",
        key="eps_mute",
        allowedtypes = X1 | X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power",
        key="eps_power",
        native_unit_of_measurement=POWER_VOLT_AMPERE,
        allowedtypes = X1 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Set Frequency",
        key="eps_set_frequency",
        native_unit_of_measurement=FREQUENCY_HERTZ,
        allowedtypes = X1 | X3 | GEN2 | GEN3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Voltage",
        key="eps_voltage",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes = X1 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Yield Today",
        key="eps_yield_today",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=DEVICE_CLASS_ENERGY,
        #state_class=STATE_CLASS_TOTAL_INCREASING,
        allowedtypes = X1 | X3 | GEN3 | GEN4 | EPS,
    ),

    # transferred from X3_EPS_SENSOR_TYPES

    SolaXModbusSensorEntityDescription(
        name="EPS Current R",
        key="eps_current_r",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
        ),
    SolaXModbusSensorEntityDescription(
        name="EPS Current S",
        key="eps_current_s",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Current T",
        key="eps_current_t",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Mode Runtime",
        key="eps_mode_runtime",
        allowedtypes = X3 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power R",
        key="eps_power_r",
        native_unit_of_measurement=POWER_VOLT_AMPERE,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power S",
        key="eps_power_s",
        native_unit_of_measurement=POWER_VOLT_AMPERE,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power T",
        key="eps_power_t",
        native_unit_of_measurement=POWER_VOLT_AMPERE,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power Active R",
        key="eps_power_active_r",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power Active S",
        key="eps_power_active_s",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power Active T",
        key="eps_power_active_t",
        native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Voltage R",
        key="eps_voltage_r",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Voltage S",
        key="eps_voltage_s",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Voltage T",
        key="eps_voltage_t",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        allowedtypes = X3 | GEN2 | GEN3 | GEN4 | EPS,
    ),

]

