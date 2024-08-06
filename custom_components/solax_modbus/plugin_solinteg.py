import logging
from dataclasses import dataclass
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
from custom_components.solax_modbus.const import *

_LOGGER = logging.getLogger(__name__)

"""
  Gabriel C.
  Plugin for Solinteg inverter, using ModbusTCP
  Only basic functionality for now
"""

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
ALL_GEN_GROUP  = GEN2

X1             = 0x0100 #not needed
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

#1 is minimum
MPPT2          = 0x20000
MPPT4          = 0x40000
MPPT_MIN2      = MPPT2 | MPPT4
ALL_MPPT = MPPT2 | MPPT4

#ALLDEFAULT = 0 # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3 
ALLDEFAULT = 0 #HYBRID | AC | ALL_X_GROUP

SCAN_GROUP_MPPT = SCAN_GROUP_MEDIUM

_simple_switch = {0: "off", 1: "on"}
#_simple_switch = {0: False, 1: True}

# ======================= end of bitmask handling code =============================================

# ====================== find inverter type and details ===========================================

async def _read_serialnr(hub, address=10000, count=8, swapbytes=False):
    res = None
    try:
        data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=count)
        if not data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(count*2).decode("ascii")
            if swapbytes:
                ba = bytearray(res,"ascii") # convert to bytearray for swapping
                ba[0::2], ba[1::2] = ba[1::2], ba[0::2] # swap bytes ourselves - due to bug in Endian.Little ?
                res = str(ba, "ascii") # convert back to string
            hub.seriesnumber = res
    except Exception as ex: _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x}", exc_info=True)
    if not res: _LOGGER.warning(f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed")
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number: {res}, swapped: {swapbytes}")
    return res

async def _read_model(hub, address=10008):
    res = None
    try:
        data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=1)
        if not data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(data.registers, byteorder=Endian.BIG)
            res = decoder.decode_16bit_uint()
            hub._invertertype = res
    except Exception as ex: _LOGGER.warning(f"{hub.name}: attempt to read model failed at 0x{address:x}", exc_info=True)
    _LOGGER.info(f"Read {hub.name} 0x{address:x} model: {res}")
    return res

# ====================================== Computed value functions  =================================================

def _bytes_str(b_array):
  return '.'.join(str(x) for x in b_array)

def _model_str(val):
    #there are models 40,41,42, docu not found
    d = {
        30: [
            "MHT-4K-25",
            "MHT-5K-25",
            "MHT-6K-25",
            "MHT-8K-25",
            "MHT-10K-25",
            "MHT-12K-25",
            "MHT-10K-40",
            "MHT-12K-40",
            "MHT-15K-40",
            "MHT-20K-40",
            ],
            
        31: [
            "MHS-3K-30D",
            "MHS-3.6K-30D",
            "MHS-4.2K-30D",
            "MHS-4.6K-30D",
            "MHS-5K-30D",
            "MHS-6K-30D",
            "MHS-7K-30D",
            "MHS-8K-30D",
            "MHS-3K-30S",
            "MHS-3.6K-30S",
            ],
        32: [
            "MHT-25K-100",
            "MHT-30K-100",
            "MHT-36K-100",
            "MHT-40K-100",
            "MHT-50K-100",
            ]
    }
    try:
        bh, bl = val // 256, val % 256
        return d[bh][bl]
    except:
        return "unknown"

def _flag_list(v, flags, empty=""):
    #v int, flags array of bit/string, empty string
    v = format(v, 'b')#[::-1] #optimized, don't reverse each time
    n = len(v)
    ret = []
    for i in range(0, min(n, len(flags))):
        if v[n-i-1] == '1': ret.append(flags[i])

    return empty if not ret else ','.join(ret)

_op_flags = [
    "WorkMode Abn.",
    "Emergency Stop",
    "DC Abn.",
    "Mains Abn.",
    "OffGrid Dis.",
    "Batt. Abn.",
    "Cmd Stop",
    "Soc Lowerand No PV",
    "","","","","","","","", #8x unused
    "Cmd PowerLimit",
    "OverFreq PowerLimit",
    "OverTemp PowerLimit",
    "OverCurr PowerLimit",
    "Reactive PowerLimit",
    "Feed in Grid PowerLimit",
    "Slow Loading",
    "OverVolt PowerLimit",
    "System PowerLim",
    ]

def _fw_str(wa, *a):
    ba = [b for w in wa for b in w.to_bytes(2)]
    return f"V{_bytes_str(ba[0:4])}-{_bytes_str(ba[4:8])}"

def _fn_mppt_mask(v, descr, dd):
    mask = dd.get("mppt_mask", 0)
    return "off" if v == 0 or mask == 0 else "on" if v & mask == mask else _flag_list(v, dd["mppt_list"], "unknown")

def value_function_house_load(initval, descr, datadict):
    return ( datadict.get('inverter_load', 0) - datadict.get('measured_power', 0) + datadict.get('meter_2_measured_power', 0) )

# =================================================================================================

#gc: set defaults; not all classes have all fields...
@dataclass
class SolintegModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    def __init__(self, **kwargs):
        kwargs.setdefault("allowedtypes",ALLDEFAULT)
        #kwargs.setdefault("register_type",REG_HOLDING)
        #kwargs.setdefault("write_method",WRITE_SINGLE_MODBUS)
        super().__init__( **kwargs)

@dataclass
class SolintegModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    def __init__(self, **kwargs):
        kwargs.setdefault("allowedtypes",ALLDEFAULT)
        #kwargs.setdefault("sleepmode",SLEEPMODE_LASTAWAKE)
        #kwargs.setdefault("register_type",REG_HOLDING)
        kwargs.setdefault("unit",REGISTER_U16)
        super().__init__( **kwargs)

@dataclass
class SolintegModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    def __init__(self, **kwargs):
        kwargs.setdefault("allowedtypes",ALLDEFAULT)
        #kwargs.setdefault("sleepmode",SLEEPMODE_LASTAWAKE)
        #kwargs.setdefault("register_type",REG_HOLDING)
        #kwargs.setdefault("write_method",WRITE_SINGLE_MODBUS)
        kwargs.setdefault("unit",REGISTER_U16)
        super().__init__( **kwargs)

    @property
    def should_poll(self) -> bool:
        return True

@dataclass
class SolintegModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    """A class that describes Solinteg Modbus sensor entities."""
    def __init__(self, **kwargs):
        #_LOGGER.warning("sensor init")
        kwargs.setdefault("allowedtypes",ALLDEFAULT)
        kwargs.setdefault("sleepmode",SLEEPMODE_LASTAWAKE)
        kwargs.setdefault("register_type",REG_HOLDING)
        kwargs.setdefault("unit",REGISTER_U16)
        super().__init__( **kwargs)

# ================================= Button Declarations ============================================================

BUTTON_TYPES = [
    #on off commands, reg 25008
    SolintegModbusButtonEntityDescription( 
        name = "Stop Soft(Backup on)",
        key = "control_cmd_stop",
        register = 25008,
        icon = "mdi:stop",
        command = 0x100,
    ),
    SolintegModbusButtonEntityDescription( 
        name = "Stop Full",
        key = "control_cmd_stop_full",
        register = 25008,
        icon = "mdi:alert-box",
        command = 0x404,
    ),
    SolintegModbusButtonEntityDescription( 
        name = "Start",
        key = "control_cmd_start",
        register = 25008,
        icon = "mdi:play",
        command = 0x101,
    ),
    SolintegModbusButtonEntityDescription( 
        name = "Restart",
        key = "control_cmd_restart",
        register = 25009,
        icon = "mdi:restart",
        command = 1,
    ),
]

# ================================= Number Declarations ============================================================

MAX_CURRENTS = [
    ('110C',  25 ), # 10kW HV
]

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
    SolintegModbusNumberEntityDescription(
        name = "Battery SOC Min On Grid",
        key = "battery_soc_min_ongrid",
        register = 52503,
        fmt = "i",
        native_min_value = 5,
        native_max_value = 50,
        native_step = 1,
        mode="box",
        scale = 0.1,
        native_unit_of_measurement = PERCENTAGE,
        entity_category = EntityCategory.CONFIG,
        allowedtypes = HYBRID,
        icon = "mdi:battery-charging-low",
    ),
    SolintegModbusNumberEntityDescription(
        name = "Battery SOC Min Off Grid",
        key = "battery_soc_min_offgrid",
        register = 52505,
        fmt = "i",
        native_min_value = 5,
        native_max_value = 50,
        native_step = 1,
        mode="box",
        scale = 0.1,
        native_unit_of_measurement = PERCENTAGE,
        entity_category = EntityCategory.CONFIG,
        allowedtypes = HYBRID,
        icon = "mdi:battery-charging-low",
    ),
    SolintegModbusNumberEntityDescription(
        name = "Battery Charge Current Limit",
        key = "battery_charge_current_limit",
        register = 52601,
        fmt = "i",
        native_min_value = 0,
        native_max_value = 50,
        native_step = 1,
        mode="box",
        scale = 0.1,
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        entity_category = EntityCategory.CONFIG,
        allowedtypes = HYBRID,
        icon = "mdi:battery-charging-low",
    ),
    SolintegModbusNumberEntityDescription(
        name = "Battery Discharge Current Limit",
        key = "battery_discharge_current_limit",
        register = 52603,
        fmt = "i",
        native_min_value = 0,
        native_max_value = 50,
        native_step = 1,
        mode="box",
        scale = 0.1,
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        entity_category = EntityCategory.CONFIG,
        allowedtypes = HYBRID,
        icon = "mdi:battery-charging-low",
    ),
    SolintegModbusNumberEntityDescription(
        name = "Export Limit",
        key = "export_limit_value",
        register = 25103,
        fmt = "i",
        native_min_value = -100,
        native_max_value = 100,
        native_step = 1,
        unit = REGISTER_S16,
        mode="box",
        scale = 0.1,
        native_unit_of_measurement = PERCENTAGE,
        entity_category = EntityCategory.CONFIG,
        allowedtypes = HYBRID,
        icon = "mdi:export",
    ),
]

# ================================= Select Declarations ============================================================
          
SELECT_TYPES = [
    SolintegModbusSelectEntityDescription(
        name = "Working Mode",
        key = "working_mode",
        register = 50000,
        option_dict =  {
            257: "General",
            258: "Economic",
            259: "UPS",
            512: "Off-Grid Mode"
        },
        entity_category = EntityCategory.CONFIG,
        allowedtypes = HYBRID,
        icon = "mdi:dip-switch",
    ),
    SolintegModbusSelectEntityDescription(
        name = "UPS Function",
        key = "ups_function",
        register = 50001,
        option_dict = _simple_switch,
        entity_category = EntityCategory.CONFIG,
        allowedtypes = HYBRID,
        icon = "mdi:power-plug-battery-outline",
    ),
    SolintegModbusSelectEntityDescription(
        name = "Grid Unbalanced Output",
        key = "grid_unbalanced_output",
        register = 50006,
        option_dict = _simple_switch,
        entity_category = EntityCategory.CONFIG,
        allowedtypes = HYBRID,
        icon = "mdi:scale-unbalanced",
    ),
    SolintegModbusSelectEntityDescription(
        name = "Export Limit Switch",
        key = "export_limit_switch",
        register = 25100,
        option_dict = _simple_switch,
        entity_category = EntityCategory.CONFIG,
        icon = "mdi:export",
    ),
    SolintegModbusSelectEntityDescription(
        name = "Battery SOC Protection On Grid",
        key = "battery_soc_prot_ongrid",
        register = 52502,
        option_dict = _simple_switch,
        entity_category = EntityCategory.CONFIG,
        allowedtypes = HYBRID,
        icon = "mdi:dip-switch",
    ),
    SolintegModbusSelectEntityDescription(
        name = "Battery SOC Protection Off Grid",
        key = "battery_soc_prot_offgrid",
        register = 52504,
        option_dict = _simple_switch,
        entity_category = EntityCategory.CONFIG,
        allowedtypes = HYBRID,
        icon = "mdi:dip-switch",
    ),
    SolintegModbusSelectEntityDescription(
        name = "Shadow Scan",
        key = "shadow_scan",
        register = 25020,
        option_dict = {0: "off", 0x7fff: "on"},
        entity_category = EntityCategory.CONFIG,
        icon = "mdi:box-shadow",
    ),
]

# ================================= Sensor Declarations ============================================================

SENSOR_TYPES: list[SolintegModbusSensorEntityDescription] = [ 
    SolintegModbusSensorEntityDescription(
        name = "Firmware",
        key = "firmware",
        register = 10011,
        #both values
        #unit = REGISTER_U32,
        unit = REGISTER_WORDS,
        wordcount = 4,
        scale = _fw_str, #v is array of words
        entity_category = EntityCategory.DIAGNOSTIC,
        icon = "mdi:information",
    ),

    SolintegModbusSensorEntityDescription(
        name = "Inverter Status",
        key = "inverter_status",
        entity_category = EntityCategory.DIAGNOSTIC,
        register = 10105,
        scan_group = SCAN_GROUP_MEDIUM,
        scale = {  
            0: "Waiting",
            1: "Self checking",
            2: "On Grid generating",
            3: "Fault",
            4: "Firmware upgrade",
            5: "Off Grid generating",
        },
    ),
    SolintegModbusSensorEntityDescription(
        name = "Inverter Operation Flags",
        key = "operation_flags",
        entity_category = EntityCategory.DIAGNOSTIC,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 10110,
        unit = REGISTER_U32,
        scale = lambda v, *a: _flag_list(v, _op_flags, "ok"),
    ),

    SolintegModbusSensorEntityDescription(
        name = "Energy Generation Total",
        key = "energy_generation_total",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        icon = "mdi:solar-power",
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31112,
        scale = 0.1,
        unit = REGISTER_U32,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Energy AC Generation Total",
        key = "energy_ac_generation_total",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        icon = "mdi:solar-power",
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 11020,
        scale = 0.1,
        unit = REGISTER_U32,
    ),

    SolintegModbusSensorEntityDescription(
        name = "Energy Generation Today",
        key = "energy_generation_today",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        icon = "mdi:solar-power",
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31005,
        scale = 0.1,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Energy AC Generation Today",
        key = "energy_ac_generation_today",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        icon = "mdi:solar-power",
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 11018,
        unit = REGISTER_U32,
        scale = 0.1,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Inverter Temperature",
        key = "inverter_temperature",
        native_unit_of_measurement = UnitOfTemperature.CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 11032,
        scale = 0.1,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Voltage 1",
        key = "pv_voltage_1",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 11038,
        #ignore_readerror = True,
        scale = 0.1,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:current-dc",
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Current 1",
        key = "pv_current_1",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 11039,
        scale = 0.1,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:current-dc",
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Power 1",
        key = "pv_power_1",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        register = 11062,
        #scale = 0.001,
        unit = REGISTER_U32,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:solar-power-variant",
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Voltage 2",
        key = "pv_voltage_2",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        allowedtypes = MPPT_MIN2,
        register = 11040,
        scale = 0.1,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:current-dc",
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Current 2",
        key = "pv_current_2",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        allowedtypes = MPPT_MIN2,
        register = 11041,
        scale = 0.1,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:current-dc",
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Power 2",
        key = "pv_power_2",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        allowedtypes = MPPT_MIN2,
        register = 11064,
        unit = REGISTER_U32,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:solar-power-variant",
    ),

    SolintegModbusSensorEntityDescription(
        name = "PV Voltage 3",
        key = "pv_voltage_3",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        allowedtypes = MPPT4,
        register = 11042,
        scale = 0.1,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:current-dc",
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Current 3",
        key = "pv_current_3",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        allowedtypes = MPPT4,
        register = 11043,
        scale = 0.1,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:current-dc",
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Power 3",
        key = "pv_power_3",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        allowedtypes = MPPT4,
        register = 11066,
        unit = REGISTER_U32,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:solar-power-variant",
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Voltage 4",
        key = "pv_voltage_4",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        allowedtypes = MPPT4,
        register = 11044,
        scale = 0.1,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:current-dc",
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Current 4",
        key = "pv_current_4",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        allowedtypes = MPPT4,
        register = 11045,
        scale = 0.1,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:current-dc",
    ),
    SolintegModbusSensorEntityDescription(
        name = "PV Power 4",
        key = "pv_power_4",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        allowedtypes = MPPT4,
        register = 11068,
        unit = REGISTER_U32,
        scan_group = SCAN_GROUP_MPPT,
        icon = "mdi:solar-power-variant",
    ),

    SolintegModbusSensorEntityDescription(
        name = "PV Power Total",
        key = "pv_power_total",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        register = 11028,
        unit = REGISTER_U32,
        scan_group = SCAN_GROUP_FAST,
        icon = "mdi:solar-power-variant",
    ),
    SolintegModbusSensorEntityDescription(
        name = "Inverter Current L1",
        key = "grid_current_l1",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 11010,
        scale = 0.1,
        allowedtypes = X1 | X3,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Inverter Current L2",
        key = "grid_current_l2",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 11012,
        scale = 0.1,
        allowedtypes = X3,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Inverter Current L3",
        key = "grid_current_l3",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 11014,
        scale = 0.1,
        allowedtypes = X3,
    ),
    SolintegModbusSensorEntityDescription(
        name = "AC Power",
        key = "inverter_load",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        scan_group = SCAN_GROUP_FAST,
        register = 11016,
        unit = REGISTER_S32,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Inverter Frequency",
        key = "grid_frequency",
        native_unit_of_measurement = UnitOfFrequency.HERTZ,
        device_class = SensorDeviceClass.FREQUENCY,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 11015,
        scale = 0.01,
        rounding = 2,
    ),
    # SolintegModbusSensorEntityDescription(
        # name = "Meter Total Energy",
        # key = "meter_total_activepower",
        # native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        # device_class = SensorDeviceClass.ENERGY,
        # register = 33126,
        # unit = REGISTER_U32,
        # scale = 0.01,
        # rounding = 2,
        # allowedtypes = HYBRID,
    # ),

    SolintegModbusSensorEntityDescription(
        name = "Battery Voltage",
        key = "battery_voltage",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 30254,
        scale = 0.1,
        allowedtypes = HYBRID,
        icon = "mdi:current-dc",
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Current",
        key = "battery_current",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 30255,
        unit = REGISTER_S16,
        scale = 0.1,
        allowedtypes = HYBRID,
        icon = "mdi:current-dc",
        scan_group = SCAN_GROUP_MEDIUM,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Charge Direction",
        key = "battery_charge_direction",
        #register = 30256, not needed, take sign from power
        #scale = {0: "discharging", 1: "charging"},
        value_function = lambda v, d, dd: ["discharge", "charge"][dd.get("battery_power",0) <= 0] ,
        entity_registry_enabled_default = False,
        allowedtypes = HYBRID,
        scan_group = SCAN_GROUP_MEDIUM,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery SOC",
        key = "battery_soc",
        native_unit_of_measurement = PERCENTAGE,
        device_class = SensorDeviceClass.BATTERY,
        register = 33000,
        scale = 0.01,
        allowedtypes = HYBRID,
        scan_group = SCAN_GROUP_MEDIUM,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery SOH",
        key = "battery_soh",
        native_unit_of_measurement = PERCENTAGE,
        register = 33001,
        scale = 0.01,
        allowedtypes = HYBRID,
        icon = "mdi:battery-heart",
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Temperature",
        key = "battery_temperature",
        native_unit_of_measurement = UnitOfTemperature.CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 33003,
        scale = 0.1,
        allowedtypes = HYBRID,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),

    SolintegModbusSensorEntityDescription(
        name = "Battery Firmware",
        key = "battery_firmware",
        register = 32003, 
        #unit = REGISTER_U16,
        scale = lambda v, *a: _bytes_str(v.to_bytes(2)),
        allowedtypes = HYBRID,
        icon = "mdi:information",
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Rated Capacity",
        key = "battery_rated_capacity",
        native_unit_of_measurement = UnitOfEnergy.WATT_HOUR,
        register = 32007, #working, from fw V27.52.3.0
        unit = REGISTER_U32,
        allowedtypes = HYBRID,
        icon = "mdi:battery",
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Bat. Min Cell Voltage",
        key = "battery_min_cell_voltage",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        register = 33015,
        scale = 0.001,
        allowedtypes = HYBRID,
        icon = "mdi:battery-heart",
        entity_registry_enabled_default = False,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Bat. Min Cell Voltage ID",
        key = "battery_min_cell_voltage_id",
        register = 33014,
        allowedtypes = HYBRID,
        entity_registry_enabled_default = False,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Bat. Max Cell Voltage",
        key = "battery_max_cell_voltage",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        register = 33013,
        scale = 0.001,
        allowedtypes = HYBRID,
        icon = "mdi:battery-heart",
        entity_registry_enabled_default = False,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Bat. Max Cell Voltage ID",
        key = "battery_max_cell_voltage_id",
        register = 33012,
        allowedtypes = HYBRID,
        entity_registry_enabled_default = False,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Charge Limit",
        key = "battery_charge_limit",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 33021, #32005 or *33021
        scale = 0.1,
        allowedtypes = HYBRID,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Discharge Limit",
        key = "battery_discharge_limit",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 33023, #32006 or *33023
        scale = 0.1,
        allowedtypes = HYBRID,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Power",
        key = "battery_power",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        register = 30258,
        unit = REGISTER_S32,
        scan_group = SCAN_GROUP_FAST,
        allowedtypes = HYBRID,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Charge Total",
        key = "battery_charge_total",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31108,
        scale = 0.1,
        unit = REGISTER_U32,
        allowedtypes = HYBRID,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Charge Today",
        key = "battery_charge_today",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31003,
        scale = 0.1,
        allowedtypes = HYBRID,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Discharge Total",
        key = "battery_discharge_total",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31110,
        scale = 0.1,
        unit = REGISTER_U32,
        allowedtypes = HYBRID,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Battery Discharge Today",
        key = "battery_discharge_today",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31004,
        scale = 0.1,
        allowedtypes = HYBRID,
    ),
    
    SolintegModbusSensorEntityDescription(
        name = "Backup Power",
        key = "backup_power",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        register = 30230,
        unit = REGISTER_S32,
        scan_group = SCAN_GROUP_MEDIUM,
        allowedtypes = HYBRID | ALL_EPS_GROUP,
    ),

    SolintegModbusSensorEntityDescription(
        name = "Grid Import Total",
        key = "grid_import_total",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31104,   #same as 11004??
        scale = 0.1,
        unit = REGISTER_U32,
        icon = "mdi:home-import-outline",
    ),
    SolintegModbusSensorEntityDescription(
        name = "Grid Import Today",
        key = "grid_import_today",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31001,
        scale = 0.1,
        icon = "mdi:home-import-outline",
    ),
    SolintegModbusSensorEntityDescription(
        name = "Grid Export Total",
        key = "grid_export_total",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31102,   #same as 11002??
        scale = 0.1,
        unit = REGISTER_U32,
        icon = "mdi:home-export-outline",
    ),
    SolintegModbusSensorEntityDescription(
        name = "Grid Export Today",
        key = "grid_export_today",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31000,
        scale = 0.1,
        icon = "mdi:home-export-outline",
    ),
    SolintegModbusSensorEntityDescription(
        name = "House Energy Total",
        key = "house_energy_total",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31114,
        scale = 0.1,
        unit = REGISTER_U32,
        icon = "mdi:home",
    ),
    SolintegModbusSensorEntityDescription(
        name = "House Energy Today",
        key = "house_energy_today",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 31006,
        scale = 0.1,
        icon = "mdi:home",
    ),
    SolintegModbusSensorEntityDescription(
        name = "Meter Active Power L1",
        key = "measured_power_l1",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 10994,
        unit = REGISTER_S32,
        entity_registry_enabled_default = False,
        allowedtypes = X1 | X3,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Meter Active Power L2",
        key = "measured_power_l2",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 10996,
        unit = REGISTER_S32,
        entity_registry_enabled_default = False,
        allowedtypes = X3,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Meter Active Power L3",
        key = "measured_power_l3",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        scan_group = SCAN_GROUP_MEDIUM,
        register = 10998,
        unit = REGISTER_S32,
        entity_registry_enabled_default = False,
        allowedtypes = X3,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Meter Active Power",
        key = "measured_power",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        register = 11000,
        unit = REGISTER_S32,
        scan_group = SCAN_GROUP_FAST,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Meter Grid Import Total",
        key = "meter_grid_import_total",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 11004,   #0?
        unit = REGISTER_U32,
        scale = 0.01,
        entity_registry_enabled_default = False,
        icon = "mdi:home-import-outline",
    ),
    SolintegModbusSensorEntityDescription(
        name = "Meter Grid Export Total",
        key = "meter_grid_export_total",
        native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR,
        device_class = SensorDeviceClass.ENERGY,
        state_class = SensorStateClass.TOTAL_INCREASING,
        register = 11002,   #0?
        unit = REGISTER_U32,
        scale = 0.01,
        entity_registry_enabled_default = False,
        icon = "mdi:home-export-outline",
    ),
    SolintegModbusSensorEntityDescription(
        name = "House Load",
        key = "house_load",
        value_function = value_function_house_load,
        scan_group = SCAN_GROUP_FAST,
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        icon = "mdi:home",
    ),

    #internal sensors are only used for polling values for selects, etc
    #no need for name, etc
    SolintegModbusSensorEntityDescription(
        key = "working_mode",
        register = 50000,
        scale =  {
            257: "General",
            258: "Economic",
            259: "UPS",
            512: "Off-Grid Mode"
        },
        internal = True,
        #allowedtypes = HYBRID,
    ),
    SolintegModbusSensorEntityDescription(
        key = "grid_unbalanced_output",
        register = 50006,
        scale = _simple_switch,
        internal = True,
    ),
    SolintegModbusSensorEntityDescription(
        name = "Shadow Scan",
        key = "shadow_scan",
        register = 25020,
        scale = _fn_mppt_mask,
        entity_registry_enabled_default = False,
        #internal = True, #leave visible for debugging
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SolintegModbusSensorEntityDescription(
        key = "export_limit_switch",
        register = 25100,
        scale = _simple_switch,
        internal = True,
    ),
    SolintegModbusSensorEntityDescription(
        key = "export_limit_value",
        register = 25103,
        unit = REGISTER_S16,
        scale = 0.1,
        internal = True,
    ),

    SolintegModbusSensorEntityDescription(
        key = "ups_function",
        register = 50001,
        scale =  _simple_switch,
        allowedtypes = HYBRID,
        internal = True,
    ),
    SolintegModbusSensorEntityDescription(
        key = "battery_soc_min_ongrid",
        register = 52503,
        scale = 0.1,
        internal = True,
        allowedtypes = HYBRID,
    ),
    SolintegModbusSensorEntityDescription(
        key = "battery_soc_min_offgrid",
        register = 52505,
        scale = 0.1,
        internal = True,
        allowedtypes = HYBRID,
    ),
    SolintegModbusSensorEntityDescription(
        key = "battery_charge_current_limit",
        register = 52601,
        scale = 0.1,
        internal = True,
        allowedtypes = HYBRID,
    ),
    SolintegModbusSensorEntityDescription(
        key = "battery_discharge_current_limit",
        register = 52603,
        scale = 0.1,
        internal = True,
        allowedtypes = HYBRID,
    ),
    SolintegModbusSensorEntityDescription(
        key = "battery_soc_prot_ongrid",
        register = 52502,
        scale = _simple_switch,
        internal = True,
    ),
    SolintegModbusSensorEntityDescription(
        key = "battery_soc_prot_offgrid",
        register = 52504,
        scale = _simple_switch,
        internal = True,
        allowedtypes = HYBRID,
    ),
]



# ============================ plugin declaration =================================================

@dataclass
class solinteg_plugin(plugin_base):

    """
    def isAwake(self, datadict):
        return (datadict.get('run_mode', None) == 'Normal Mode')

    """


    async def async_determineInverterType(self, hub, configdict):
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber  = await _read_serialnr(hub)
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find serial number, even not for other Inverter")
            seriesnumber = "unknown"

        model = await _read_model(hub)
        self.inverter_model = _model_str(model) #as string
        bh, bl = model // 256, model % 256

        invertertype = 0
        if bh in [30,31,32]:
            invertertype = invertertype | HYBRID

        if bh in [30,32, 40,42]:
            invertertype = invertertype | X3

        if bh == 30 and bl in [0, 1]:
            mppt = 1
        elif bh == 32:
            mppt = 4
            invertertype = invertertype | MPPT4
        else : #bh == 31, other 30...
            mppt = 2
            invertertype = invertertype | MPPT2
        
        if invertertype > 0:
            #prepare mppt list
            #hub.data["mppt_count"] = mppt
            hub.data["mppt_mask"] = 2**mppt - 1 #mask
            hub.data["mppt_list"] = []
            sel_dd = {0: "off", 0x7fff: "on"} #dict uses 16 bit signed!?, 0xffff not possible
            for i in range(mppt):
                mx = f"mppt{i+1}"
                hub.data["mppt_list"].append(mx)
                sel_dd[2**i] = mx
            #set the options
            for sel in self.SELECT_TYPES:
                if sel.key == "shadow_scan":
                    sel.option_dict.clear()
                    sel.option_dict.update(sel_dd)
                    break

            read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
            read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
            if read_eps: invertertype = invertertype | EPS 
            if read_dcb: invertertype = invertertype | DCB

            _LOGGER.info(f"{hub.name}: inverter type: x{invertertype:x}, mppt count={mppt}")
        
        return invertertype

    def matchInverterWithMask (self, inverterspec, entitymask, serialnumber = 'not relevant', blacklist = None):
        # returns true if the entity needs to be created for an inverter
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP)  != 0) or (entitymask & ALL_GEN_GROUP  == 0)
        xmatch   = ((inverterspec & entitymask & ALL_X_GROUP)    != 0) or (entitymask & ALL_X_GROUP    == 0)
        hybmatch = ((inverterspec & entitymask & ALL_TYPE_GROUP) != 0) or (entitymask & ALL_TYPE_GROUP == 0)
        epsmatch = ((inverterspec & entitymask & ALL_EPS_GROUP)  != 0) or (entitymask & ALL_EPS_GROUP  == 0)
        dcbmatch = ((inverterspec & entitymask & ALL_DCB_GROUP)  != 0) or (entitymask & ALL_DCB_GROUP  == 0)
        mpptmatch= ((inverterspec & entitymask & ALL_MPPT)       != 0) or (entitymask & ALL_MPPT == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist: 
                if serialnumber.startswith(start) : return False
        return (genmatch and xmatch and hybmatch and epsmatch and dcbmatch and mpptmatch)


plugin_instance = solinteg_plugin(
    plugin_name = 'solinteg',
    plugin_manufacturer = 'Gabriel C.',
    SENSOR_TYPES = SENSOR_TYPES,
    NUMBER_TYPES = NUMBER_TYPES,
    BUTTON_TYPES = BUTTON_TYPES,
    SELECT_TYPES = SELECT_TYPES, 
    block_size = 120,
    order16 = Endian.BIG,
    order32 = Endian.BIG,
    #auto_block_ignore_readerror = True
    )
