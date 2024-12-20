import logging
import asyncio
from dataclasses import dataclass
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
from custom_components.solax_modbus.const import *

_LOGGER = logging.getLogger(__name__)

""" ============================================================================================
bitmasks  definitions to characterize inverters, organized by group
these bitmasks are used in entity declarations to determine to which inverters the entity applies
within a group, the bits in an entity declaration will be interpreted as OR
between groups, an AND condition is applied, so all gruoups must match.
An empty group (group without active flags) evaluates to True.
example: GEN3 | GEN4 | X1 | X3 | EPS
means:  any inverter of tyoe (GEN3 or GEN4) and (X1 or X3) and (EPS)
An entity can be declared multiple times (with different bitmasks) if the parameters are different for each inverter type
"""

GEN = 0x0001  # base generation for MIC, PV, AC
GEN2 = 0x0002
GEN3 = 0x0004
GEN4 = 0x0008
ALL_GEN_GROUP = GEN2 | GEN3 | GEN4 | GEN

X1 = 0x0100
X3 = 0x0200
ALL_X_GROUP = X1 | X3

PV = 0x0400  # Needs further work on PV Only Inverters
AC = 0x0800
HYBRID = 0x1000
MIC = 0x2000
ALL_TYPE_GROUP = PV | AC | HYBRID | MIC

EPS = 0x8000
ALL_EPS_GROUP = EPS

DCB = 0x10000  # dry contact box - gen4
ALL_DCB_GROUP = DCB

PM = 0x20000
ALL_PM_GROUP = PM

MPPT3 = 0x40000
MPPT4 = 0x80000
MPPT6 = 0x100000
MPPT8 = 0x200000
MPPT10 = 0x400000
ALL_MPPT_GROUP = MPPT3 | MPPT4 | MPPT6 | MPPT8 | MPPT10

BAT_BTS = 0x1000000

ALLDEFAULT = 0  # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3

# ======================= end of bitmask handling code =============================================

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub, address, swapbytes):
    res = None
    try:
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=7)
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(14).decode("ascii")
            if swapbytes:
                ba = bytearray(res, "ascii")  # convert to bytearray for swapping
                ba[0::2], ba[1::2] = ba[1::2], ba[0::2]  # swap bytes ourselves - due to bug in Endian.LITTLE ?
                res = str(ba, "ascii")  # convert back to string
            hub.seriesnumber = res
    except Exception as ex:
        _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x}", exc_info=True)
    if not res:
        _LOGGER.warning(
            f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed"
        )
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number: {res}, swapped: {swapbytes}")
    # return 'SP1ES2'
    return res


# =================================================================================================


@dataclass
class SofarModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    # write_method = WRITE_MULTISINGLE_MODBUS


@dataclass
class SofarModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    # write_method = WRITE_MULTISINGLE_MODBUS


@dataclass
class SofarModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    # write_method = WRITE_MULTISINGLE_MODBUS


@dataclass
class SofarModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    """A class that describes Sofar Modbus sensor entities."""

    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    # order16: int = Endian.BIG
    # order32: int = Endian.BIG
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING


# ====================================== Computed value functions  =================================================


def value_function_passivemode(initval, descr, datadict):
    return [
        (REGISTER_S32, datadict.get("passive_mode_grid_power", 0)),
        (REGISTER_S32, datadict.get("passive_mode_battery_power_min", 0)),
        (REGISTER_S32, datadict.get("passive_mode_battery_power_max", 0)),
    ]


def value_function_passive_timeout(initval, descr, datadict):
    return [
        (
            "passive_mode_timeout",
            datadict.get("passive_mode_timeout", datadict.get("passive_mode_timeout")),
        ),
        (
            "passive_mode_timeout_action",
            datadict.get("passive_mode_timeout_action", datadict.get("passive_mode_timeout_action")),
        ),
    ]


def value_function_refluxcontrol(initval, descr, datadict):
    return [
        (
            "feedin_limitation_mode",
            datadict.get("feedin_limitation_mode", datadict.get("feedin_limitation_mode")),
        ),
        (
            "feedin_max_power",
            int(datadict.get("feedin_max_power", 0)) / 100,
        ),
    ]


# TIMING AND TOU DISABLED AS THESE ARE NOT WORKING
# def value_function_timingmode(initval, descr, datadict):
#     return  [ ('timing_id', datadict.get('timing_id', 0), ),
#               ('timing_charge', datadict.get('timing_charge', datadict.get('ro_timing_charge')), ),
#               ('timing_charge_start_time', datadict.get('timing_charge_start_time', datadict.get('ro_timing_charge_start_time')), ),
#               ('timing_charge_end_time', datadict.get('timing_charge_end_time', datadict.get('ro_timing_charge_end_time')), ),
#               ('timing_discharge_start_time', datadict.get('timing_discharge_start_time', datadict.get('ro_timing_discharge_start_time')), ),
#               ('timing_discharge_end_time', datadict.get('timing_discharge_end_time', datadict.get('ro_timing_discharge_end_time')), ),
#               ('timing_charge_power', datadict.get('timing_charge_power', 0), ),
#               ('timing_discharge_power', datadict.get('timing_discharge_power', 0), ),
#             ]

# def value_function_toumode(initval, descr, datadict):
#     return  [ ('tou_id', datadict.get('tou_id', 0), ),
#               ('tou_control', datadict.get('tou_control', datadict.get('ro_tou_control')), ),
#               ('tou_charge_start_time', datadict.get('tou_charge_start_time', datadict.get('ro_tou_charge_start_time')), ),
#               ('tou_charge_end_time', datadict.get('tou_charge_end_time', datadict.get('ro_tou_charge_end_time')), ),
#               ('tou_target_soc', datadict.get('tou_target_soc', datadict.get('tou_target_soc')), ),
#               ('tou_charge_power', datadict.get('tou_charge_power', 0), ),
#             ]


def value_function_sync_rtc_ymd_sofar(initval, descr, datadict):
    now = datetime.now()
    return [
        (
            REGISTER_U16,
            now.year % 100,
        ),
        (
            REGISTER_U16,
            now.month,
        ),
        (
            REGISTER_U16,
            now.day,
        ),
        (
            REGISTER_U16,
            now.hour,
        ),
        (
            REGISTER_U16,
            now.minute,
        ),
        (
            REGISTER_U16,
            now.second,
        ),
        (
            REGISTER_U16,
            1,
        ),
    ]


# ================================= Button Declarations ============================================================

BUTTON_TYPES = [
    SofarModbusButtonEntityDescription(
        name="Passive: Update Battery Charge/Discharge",
        key="passive_mode_battery_charge_discharge",
        register=0x1187,
        allowedtypes=HYBRID,
        write_method=WRITE_MULTI_MODBUS,
        value_function=value_function_passivemode,
    ),
    SofarModbusButtonEntityDescription(
        name="Passive: Update Timeout",
        key="passive_mode_update_timeout",
        register=0x1184,
        allowedtypes=HYBRID,
        write_method=WRITE_MULTI_MODBUS,
        value_function=value_function_passive_timeout,
    ),
    # Unlikely to work as Sofar requires writing 7 registers, where the last needs to have the constant value of '1' during a write operation.
    SofarModbusButtonEntityDescription(
        name="Update System Time",
        key="sync_rtc",
        register=0x1004,
        allowedtypes=HYBRID | PV,
        write_method=WRITE_MULTI_MODBUS,
        icon="mdi:home-clock",
        value_function=value_function_sync_rtc_ymd_sofar,
    ),
    SofarModbusButtonEntityDescription(
        name="FeedIn: Update",
        key="feedin_limitation_mode",
        register=0x1023,
        allowedtypes=HYBRID,
        write_method=WRITE_MULTI_MODBUS,
        value_function=value_function_refluxcontrol,
    ),
    # TIMING AND TOU DISABLED AS THESE ARE NOT WORKING
    # SofarModbusButtonEntityDescription(
    #     name = "Timing: Control",
    #     key = "timing_control",
    #     register = 0x111F,
    #     command = 1,
    #     allowedtypes = HYBRID,
    #     icon = "mdi:battery-clock",
    # ),
    # # Unlikely to work. Current value function writes just 8 registers, but according to doc 15 registers need to be written (0x1111 - 0x111F)
    # SofarModbusButtonEntityDescription(
    #     name = "TOU: Update Charge/Discharge Times",
    #     key = "update_charge_discharge_times",
    #     register = 0x1111,
    #     allowedtypes = HYBRID,
    #     write_method = WRITE_MULTI_MODBUS,
    #     icon = "mdi:battery-clock",
    #     value_function = value_function_timingmode,
    # ),
    # #Unlikely to work. According to doc starting at 0x1120 16 registers from 0x1120 to 0x112F must be written. But integration just writes 6 registers
    # SofarModbusButtonEntityDescription(
    #     name = "TOU: Update Charge Times",
    #     key = "update_tou_charge_times",
    #     register = 0x1120,
    #     allowedtypes = HYBRID,
    #     write_method = WRITE_MULTI_MODBUS,
    #     icon = "mdi:battery-clock",
    #     value_function = value_function_toumode,
    # ),
]

# ================================= Number Declarations ============================================================

NUMBER_TYPES = [
    ###
    #
    # Data only number types
    #
    ###
    SofarModbusNumberEntityDescription(
        name="Passive: Desired Grid Power",
        key="passive_mode_grid_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        unit=REGISTER_S32,
        fmt="i",
        native_max_value=20000,
        native_min_value=-20000,
        native_step=10,
        initvalue=0,
        allowedtypes=HYBRID,
        prevent_update=True,
        write_method=WRITE_DATA_LOCAL,
        icon="mdi:transmission-tower",
    ),
    SofarModbusNumberEntityDescription(
        name="Passive: Minimum Battery Power",
        key="passive_mode_battery_power_min",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        unit=REGISTER_S32,
        fmt="i",
        native_max_value=20000,
        native_min_value=-20000,
        native_step=100,
        initvalue=0,
        allowedtypes=HYBRID,
        prevent_update=True,
        write_method=WRITE_DATA_LOCAL,
        icon="mdi:battery-arrow-down",
    ),
    SofarModbusNumberEntityDescription(
        name="Passive: Maximum Battery Power",
        key="passive_mode_battery_power_max",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        unit=REGISTER_S32,
        fmt="i",
        native_max_value=20000,
        native_min_value=-20000,
        native_step=100,
        initvalue=0,
        allowedtypes=HYBRID,
        prevent_update=True,
        write_method=WRITE_DATA_LOCAL,
        icon="mdi:battery-arrow-up",
    ),
    SofarModbusNumberEntityDescription(
        name="FeedIn: Maximum Power",
        key="feedin_max_power",
        unit=REGISTER_U16,
        fmt="i",
        native_min_value=0,
        native_max_value=20000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        allowedtypes=HYBRID,
        prevent_update=True,
        write_method=WRITE_DATA_LOCAL,
        icon="mdi:battery-sync",
    ),
    # TIMING AND TOU DISABLED AS THESE ARE NOT WORKING
    # SofarModbusNumberEntityDescription(
    #     name = "Timing: Charge Power",
    #     key = "timing_charge_power",
    #     allowedtypes = HYBRID,
    #     native_min_value = 0,
    #     native_max_value = 6000,
    #     native_step = 100,
    #     native_unit_of_measurement = UnitOfPower.WATT,
    #     initvalue = 0,
    #     prevent_update = True,
    #     unit = REGISTER_U32,
    #     write_method = WRITE_DATA_LOCAL,
    # ),
    # SofarModbusNumberEntityDescription(
    #     name = "Timing: Discharge Power",
    #     key = "timing_discharge_power",
    #     allowedtypes = HYBRID,
    #     native_min_value = 0,
    #     native_max_value = 6000,
    #     native_step = 100,
    #     native_unit_of_measurement = UnitOfPower.WATT,
    #     initvalue = 0,
    #     prevent_update = True,
    #     unit = REGISTER_U32,
    #     write_method = WRITE_DATA_LOCAL,
    # ),
    # SofarModbusNumberEntityDescription(
    #     name = "Timing: ID",
    #     key = "timing_id",
    #     allowedtypes = HYBRID,
    #     native_min_value = 0,
    #     native_max_value = 4,
    #     initvalue = 0,
    #     prevent_update = True,
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    # ),
    # SofarModbusNumberEntityDescription(
    #     name = "TOU: ID",
    #     key = "tou_id",
    #     allowedtypes = HYBRID,
    #     native_min_value = 0,
    #     native_max_value = 4,
    #     initvalue = 0,
    #     prevent_update = True,
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    # ),
    # SofarModbusNumberEntityDescription(
    #     name = "TOU: Target SOC",
    #     key = "tou_target_soc",
    #     allowedtypes = HYBRID,
    #     native_min_value = 30,
    #     native_max_value = 100,
    #     native_unit_of_measurement = PERCENTAGE,
    #     initvalue = 0,
    #     prevent_update = True,
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    # ),
    # SofarModbusNumberEntityDescription(
    #     name = "TOU: Charge Power",
    #     key = "tou_charge_power",
    #     allowedtypes = HYBRID,
    #     native_min_value = 0,
    #     native_max_value = 6000,
    #     native_step = 100,
    #     native_unit_of_measurement = UnitOfPower.WATT,
    #     initvalue = 0,
    #     prevent_update = True,
    #     unit = REGISTER_U32,
    #     write_method = WRITE_DATA_LOCAL,
    # ),
    ###
    #
    #  Normal number types
    #
    ###
    SofarModbusNumberEntityDescription(
        name="Parallel Address",
        key="parallel_address",
        register=0x1037,
        fmt="i",
        native_min_value=0,
        native_max_value=10,
        native_step=1,
        allowedtypes=HYBRID | PV | X3 | PM,
        write_method=WRITE_MULTISINGLE_MODBUS,
        entity_category=EntityCategory.CONFIG,
    ),
]

# ================================= Select Declarations ============================================================

SELECT_TYPES = [
    ###
    #
    #  Data only select types
    #
    ###
    SofarModbusSelectEntityDescription(
        name="FeedIn: Limitation Mode",
        key="feedin_limitation_mode",
        unit=REGISTER_U16,
        option_dict={
            0: "Disabled",
            1: "Enabled - Feed-in limitation",
            2: "Enabled - 3-phase limit",
        },
        allowedtypes=HYBRID,
        write_method=WRITE_DATA_LOCAL,
    ),
    # TIMING AND TOU DISABLED AS THESE ARE NOT WORKING
    # SofarModbusSelectEntityDescription(
    #     name = "Timing: Charge",
    #     key = "timing_charge",
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    #     option_dict =  {
    #             0: "Enabled - Charging & Discharging",
    #             1: "Enabled - Charging ",
    #             2: "Enabled - Discharging",
    #             3: "Disabled",
    #         },
    #     allowedtypes = HYBRID,
    # ),
    # SofarModbusSelectEntityDescription(
    #     name = "Timing: Charge Start Time",
    #     key = "timing_charge_start_time",
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    #     option_dict = TIME_OPTIONS_GEN4,
    #     allowedtypes = HYBRID,
    #     entity_category = EntityCategory.CONFIG,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSelectEntityDescription(
    #     name = "Timing: Charge End Time",
    #     key = "timing_charge_end_time",
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    #     option_dict = TIME_OPTIONS_GEN4,
    #     allowedtypes = HYBRID,
    #     entity_category = EntityCategory.CONFIG,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSelectEntityDescription(
    #     name = "Timing: Discharge Start Time",
    #     key = "timing_discharge_start_time",
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    #     option_dict = TIME_OPTIONS_GEN4,
    #     allowedtypes = HYBRID,
    #     entity_category = EntityCategory.CONFIG,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSelectEntityDescription(
    #     name = "Timing: Discharge End Time",
    #     key = "timing_discharge_end_time",
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    #     option_dict = TIME_OPTIONS_GEN4,
    #     allowedtypes = HYBRID,
    #     entity_category = EntityCategory.CONFIG,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSelectEntityDescription(
    #     name = "TOU: Control",
    #     key = "tou_control",
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    #     option_dict =  {
    #             0: "Enabled - Charging & Discharging",
    #             1: "Enabled - Charging ",
    #             2: "Enabled - Discharging",
    #             3: "Disabled",
    #         },
    #     allowedtypes = HYBRID,
    # ),
    # SofarModbusSelectEntityDescription(
    #     name = "TOU: Charge Start Time",
    #     key = "tou_charge_start_time",
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    #     option_dict = TIME_OPTIONS_GEN4,
    #     allowedtypes = HYBRID,
    #     entity_category = EntityCategory.CONFIG,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSelectEntityDescription(
    #     name = "TOU: Charge End Time",
    #     key = "tou_charge_end_time",
    #     unit = REGISTER_U16,
    #     write_method = WRITE_DATA_LOCAL,
    #     option_dict = TIME_OPTIONS_GEN4,
    #     allowedtypes = HYBRID,
    #     entity_category = EntityCategory.CONFIG,
    #     icon = "mdi:battery-clock",
    # ),
    SofarModbusSelectEntityDescription(
        name="Passive: Timeout",
        key="passive_mode_timeout",
        unit=REGISTER_U16,
        write_method=WRITE_DATA_LOCAL,
        option_dict={
            0: "Disabled",
            300: "5 Minutes",
            600: "10 Minutes",
            900: "15 Minutes",
            1800: "30 Minutes",
            3600: "60 Minutes",
            5400: "90 Minutes",
            7200: "2 Hours",
            10800: "3 Hours",
            14400: "4 Hours",
            18000: "5 Hours",
            21600: "6 Hours",
        },
        allowedtypes=HYBRID,
        icon="mdi:timer",
    ),
    SofarModbusSelectEntityDescription(
        name="Passive: Timeout Action",
        key="passive_mode_timeout_action",
        unit=REGISTER_U16,
        write_method=WRITE_DATA_LOCAL,
        option_dict={
            0: "Force Standby",
            1: "Return to Previous Mode",
        },
        allowedtypes=HYBRID,
        icon="mdi:timer-cog",
    ),
    ###
    #
    #  Normal select types
    #
    ###
    SofarModbusSelectEntityDescription(
        name="EPS Control",
        key="eps_control",
        register=0x1029,
        option_dict={
            0: "Turn Off",
            1: "Turn On, Prohibit Cold Start",
            2: "Turn On, Enable Cold Start",
        },
        allowedtypes=HYBRID | X3 | EPS,
        write_method=WRITE_MULTISINGLE_MODBUS,
    ),
    # Does not work. 0x1035, 0x1036, and 0x1037 have to be written in one single chunk
    # SofarModbusSelectEntityDescription(
    #     name = "Parallel Control",
    #     key = "parallel_control",
    #     register = 0x1035,
    #     option_dict =  {
    #             0: "Disabled",
    #             1: "Enabled",
    #         },
    #     allowedtypes = HYBRID | PV | X3 | PM,
    #     write_method = WRITE_MULTISINGLE_MODBUS,
    # ),
    # SofarModbusSelectEntityDescription(
    #     name = "Parallel Master-Salve",
    #     key = "parallel_masterslave",
    #     register = 0x1036,
    #     option_dict =  {
    #             0: "Slave",
    #             1: "Master",
    #         },
    #     allowedtypes = HYBRID | PV | X3 | PM,
    #     write_method = WRITE_MULTISINGLE_MODBUS,
    # ),
    SofarModbusSelectEntityDescription(
        name="Remote Switch On Off",
        key="remote_switch_on_off",
        register=0x1104,
        option_dict={
            0: "Off",
            1: "On",
        },
        allowedtypes=HYBRID,
        write_method=WRITE_MULTISINGLE_MODBUS,
    ),
    SofarModbusSelectEntityDescription(
        name="Energy Storage Mode",
        key="charger_use_mode",
        register=0x1110,
        option_dict={
            0: "Self Use",
            1: "Time of Use",
            2: "Timing Mode",
            3: "Passive Mode",
            4: "Peak Cut Mode",
            5: "Off-grid Mode",
        },
        allowedtypes=HYBRID,
        write_method=WRITE_MULTISINGLE_MODBUS,
        icon="mdi:battery-charging-60",
    ),
    # Timing Charge Start
    # Timing Charge End
    # Timing Discharge Start
    # Timing Discharge End
    # TOU Charge Start
    # TOU Charge End
]


# ================================= Sensor Declarations ============================================================

SENSOR_TYPES: list[SofarModbusSensorEntityDescription] = [
    ###
    #
    # Real-time Data Area
    #
    ###
    SofarModbusSensorEntityDescription(
        name="System State",
        key="system_state",
        register=0x404,
        newblock=True,
        scale={
            0: "Waiting",
            1: "Checking",
            2: "Grid-connected",
            3: "Emergency Power Supply",
            4: "Recoverable fault",
            5: "Permanent fault",
            6: "Upgrading",
            7: "Self-Charging",
        },
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 1",
        key="fault_1",
        register=0x405,
        scale={
            0: "No error",
            1: "ID01 Grid Over Voltage Protection",
            2: "ID02 Grid Under Voltage Protection",
            4: "ID03 Grid Over Frequency Protection",
            8: "ID04 Grid Under Frequency Protection",
            16: "ID05 Leakage current fault",
            32: "ID06 High penetration error",
            64: "ID07 Low penetration error",
            128: "ID08 Islanding error",
            256: "ID09 Grid voltage transient value overvoltage 1",
            512: "ID10 Grid voltage transient value overvoltage 2",
            1024: "ID11 Grid line voltage error",
            2048: "ID12 Inverter voltage error",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 2",
        key="fault_2",
        register=0x406,
        scale={
            0: "No error",
            1: "ID17 Grid current sampling error",
            2: "ID18 Grid current DC component sampling error (AC side)",
            4: "ID19 Grid voltage sampling error (DC side)",
            8: "ID20 Grid voltage sampling error (AC side)",
            16: "ID21 Leakage current sampling error (DC side)",
            32: "ID22 Leakage current sampling error (AC side)",
            64: "ID23 Load voltage DC component sampling error",
            128: "ID24 DC input current sampling error",
            256: "ID25 DC component sampling error of grid current (DC side)",
            512: "ID26 DC input branch current sampling error",
            4096: "ID29 Leakage current consistency error",
            8192: "ID30 Grid voltage consistency error",
            16384: "ID31 DCI consistency error",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 3",
        key="fault_3",
        register=0x407,
        scale={
            0: "No error",
            1: "ID033 SPI communication error (DC side)",
            2: "ID034 SPI communication error (AC side)",
            4: "ID035 Chip error (DC side)",
            8: "ID036 Chip error (AC side)",
            16: "ID037 Auxiliary power error",
            32: "ID038 Inverter soft start failure",
            256: "ID041 Relay detection failure",
            512: "ID042 Low insulation impedance",
            1024: "ID043 Grounding error",
            2048: "ID044 Input mode setting error",
            4096: "ID045 ID045 CT error",
            8192: "ID046 Input reversal error",
            16384: "ID047 Parallel error",
            32768: "ID048 Serial number error",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 4",
        key="fault_4",
        register=0x408,
        scale={
            0: "No error",
            1: "ID049 Battery temperature protection",
            2: "ID050 Heat sink 1 temperature protection",
            4: "ID051 Heater 2 temperature protection",
            8: "ID052 Heater 3 temperature protection",
            16: "ID053 Heatsink 4 temperature protection",
            32: "ID054 Heatsink 5 temperature protection",
            64: "ID055 Radiator 6 temperature protection",
            256: "ID057 Ambient temperature 1 protection",
            512: "ID058 Ambient temperature 2 protection",
            1024: "ID059 Module 1 temperature protection",
            2048: "ID060 Module 2 temperature protection",
            4096: "ID061 Module 3 temperature protection",
            8192: "ID062 Module temperature difference is too large",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 5",
        key="fault_5",
        register=0x409,
        scale={
            0: "No error",
            1: "ID065 Bus voltage RMS unbalance",
            2: "ID066 Bus voltage transient value unbalance",
            4: "ID067 Undervoltage of busbar during grid connection",
            8: "ID068 Bus bar low voltage",
            16: "ID069 PV overvoltage",
            32: "ID070 Battery over-voltage",
            64: "ID071 LLCBus overvoltage protection",
            128: "ID072 Inverter bus voltage RMS software overvoltage",
            256: "ID073 Inverter bus voltage transient value software overvoltage",
            512: "ID074 Flying Cross Capacitor Overvoltage Protection",
            1024: "ID075 Flying Cross capacitor undervoltage protection",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 6",
        key="fault_6",
        register=0x040A,
        scale={
            0: "No error",
            1: "ID081 Battery overcurrent software protection",
            2: "ID082 Dci overcurrent protection",
            4: "ID083 Output transient current protection",
            8: "ID084 BuckBoost software overcurrent",
            16: "ID085 Output RMS current protection",
            32: "ID086 PV instantaneous current overcurrent software protection",
            64: "ID087 PV parallel uneven current",
            128: "ID088 Output current unbalance",
            256: "ID089 PV software overcurrent protection",
            512: "ID090 Balanced circuit overcurrent protection",
            1024: "ID091 Resonance protection",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 7",
        key="fault_7",
        register=0x040B,
        scale={
            0: "No error",
            1: "ID097 LLC bus hardware overvoltage",
            2: "ID098 Inverter bus hardware overvoltage",
            4: "ID099 BuckBoost hardware overcurrent",
            8: "ID100 Battery hardware overcurrent",
            16: "ID101",
            32: "ID102 PV hardware overcurrent",
            64: "ID103 AC output hardware overcurrent",
            256: "ID105 Power meter error",
            512: "ID106 Serial number model error",
            8192: "ID110 Overload protection 1",
            16384: "ID111 Overload protection 2",
            32768: "ID112 Overload protection 3",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 8",
        key="fault_8",
        register=0x040C,
        scale={
            0: "No error",
            1: "ID113 Overtemperature derating",
            2: "ID114 Frequency down load",
            4: "ID115 Frequency loading",
            8: "ID116 Voltage down load",
            16: "ID117 Voltage loading",
            256: "ID121 Lightning protection failure (DC)",
            512: "ID122 Lightning protection failure (AC)",
            2048: "ID124 Battery low voltage protection",
            4096: "ID125 Battery low voltage shutdown",
            8192: "ID126 Battery low voltage pre-alarm",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 9",
        key="fault_9",
        register=0x040D,
        scale={
            0: "No error",
            1: "ID129 Output hardware overcurrent permanent fault",
            2: "ID130 Bus overvoltage permanent fault",
            4: "ID131 Bus hardware over-voltage permanent fault",
            8: "ID132 PV uneven flow permanent fault",
            16: "ID133 Battery overcurrent permanent fault in EPS mode",
            32: "ID134 Output transient overcurrent permanent fault",
            64: "ID135 Output current unbalance permanent fault",
            256: "ID137 Input mode setting error permanent fault",
            512: "ID138 Input overcurrent permanent fault",
            1024: "ID139 Input hardware overcurrent permanent fault",
            2048: "ID140 Relay permanent fault",
            4096: "ID141 Bus unbalance permanent fault",
            8192: "ID142 Lightning protection permanent fault - DC side",
            16384: "ID143 Lightning protection permanent fault - AC side",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 10",
        key="fault_10",
        register=0x040E,
        scale={
            0: "No error",
            1: "ID145 USB fault",
            2: "ID146 WIFI fault",
            4: "ID147 Bluetooth fault",
            8: "ID148 RTC clock fault",
            16: "ID149 Communication board EEPROM error",
            32: "ID150 Communication board FLASH error",
            128: "ID152 Safety regulation version error",
            256: "ID153 SCI communication error (DC side)",
            512: "ID154 SCI communication error (AC side)",
            1024: "ID155 SCI communication error (convergence board side)",
            2048: "ID156 Software version inconsistency",
            4096: "ID157 Lithium battery 1 communication error",
            8192: "ID158 Li-ion battery 2 communication error",
            16384: "ID159 Lithium battery 3 communication error",
            32768: "ID160 Lithium battery 4 communication failure",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 11",
        key="fault_11",
        register=0x040F,
        scale={
            0: "No error",
            1: "ID161 Forced shutdown",
            2: "ID162 Remote shutdown",
            4: "ID163 Drms0 shutdown",
            16: "ID165 Remote down load",
            32: "ID166 Logic interface down load",
            64: "ID167 Anti-Reverse Flow Downgrade",
            256: "ID169 Fan 1 failure",
            512: "ID170 Fan 2 failure",
            1024: "ID171 Fan 3 failure",
            2048: "ID172 Fan 4 failure",
            4096: "ID173 Fan 5 failure",
            8192: "ID174 Fan 6 failure",
            16384: "ID175 Fan 7 fault",
            32768: "ID176 Meter communication failure",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Fault 12",
        key="fault_12",
        register=0x0410,
        scale={
            0: "No error",
            1: "ID177 BMS over-voltage alarm",
            2: "ID178 BMS undervoltage alarm",
            4: "ID179 BMS high temperature alarm",
            8: "ID180 BMS low temperature alarm",
            16: "ID181 BMS charge/discharge overload alarm",
            32: "ID182 BMS short circuit alarm",
            64: "ID183 BMS version inconsistency",
            128: "ID184 BMS CAN version inconsistency",
            256: "ID185 BMS CAN version is too low",
            4096: "ID189 Arc device communication failure",
            8192: "ID190 DC arc alarm fault",
            16384: "ID191 PID repair failed",
            32768: "ID192 PLC module heartbeat loss",
        },
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Waiting Time",
        key="waiting_time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        register=0x417,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Inverter Temperature 1",
        key="inverter_temperature_1",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x418,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Inverter Temperature 2",
        key="inverter_temperature_2",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x419,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Heatsink Temperature 1",
        key="heatsink_temperature_1",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x41A,
        # newblock = True,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Heatsink Temperature 2",
        key="heatsink_temperature_2",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x41B,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Module Temperature 1",
        key="module_temperature_1",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x420,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Module Temperature 2",
        key="module_temperature_2",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x421,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="System Time",
        key="rtc",
        register=0x42C,
        unit=REGISTER_WORDS,
        wordcount=6,
        scale=value_function_rtc_ymd,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:clock",
    ),
    SofarModbusSensorEntityDescription(
        name="Serial Number",
        key="serial_number",
        register=0x445,
        newblock=True,
        unit=REGISTER_STR,
        wordcount=7,
        entity_category=EntityCategory.DIAGNOSTIC,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Hardware Version",
        key="hardware_version",
        register=0x44D,
        unit=REGISTER_STR,
        wordcount=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Software Version",
        key="software_version",
        register=0x44F,
        unit=REGISTER_STR,
        wordcount=12,
        entity_category=EntityCategory.DIAGNOSTIC,
        allowedtypes=HYBRID | PV,
    ),
    ###
    #
    # On Grid Output
    #
    ###
    SofarModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        register=0x484,
        newblock=True,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power Output Total",
        key="active_power_output_total",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x485,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Reactive Power Output Total",
        key="reactive Power_output_total",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x486,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Apparent Power Output Total",
        key="apparent_power_output_total",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x487,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power PCC Total",
        key="active_power_pcc_total",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x488,
        unit=REGISTER_S16,
        scan_group=SCAN_GROUP_FAST,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Reactive Power PCC Total",
        key="reactive Power_pcc_total",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x489,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Apparent Power PCC Total",
        key="apparent_power_pcc_total",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x48A,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Voltage L1",
        key="voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x48D,
        scan_group=SCAN_GROUP_FAST,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output L1",
        key="current_output_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x48E,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power Output L1",
        key="active_power_output_l1",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x48F,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Reactive Power Output L1",
        key="reactive Power_output_l1",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x490,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Power Factor Output L1",
        key="power_factor_output_l1",
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x491,
        unit=REGISTER_S16,
        scale=0.001,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current PCC L1",
        key="current_pcc_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x492,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power PCC L1",
        key="active_power_pcc_l1",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x493,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Reactive Power PCC L1",
        key="reactive Power_pcc_l1",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x494,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Power Factor PCC L1",
        key="power_factor_pcc_l1",
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x495,
        unit=REGISTER_S16,
        scale=0.001,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Voltage L2",
        key="voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x498,
        scan_group=SCAN_GROUP_FAST,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output L2",
        key="current_output_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x499,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power Output L2",
        key="active_power_output_l2",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x49A,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Reactive Power Output L2",
        key="reactive Power_output_l2",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x49B,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Power Factor Output L2",
        key="power_factor_output_l2",
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x49C,
        unit=REGISTER_S16,
        scale=0.001,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current PCC L2",
        key="current_pcc_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x49D,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power PCC L2",
        key="active_power_pcc_l2",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x49E,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Reactive Power PCC L2",
        key="reactive Power_pcc_l2",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x49F,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Power Factor PCC L2",
        key="power_factor_pcc_l2",
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x4A0,
        unit=REGISTER_S16,
        scale=0.001,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Voltage L3",
        key="voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x4A3,
        scan_group=SCAN_GROUP_FAST,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output L3",
        key="current_output_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x4A4,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power Output L3",
        key="active_power_output_l3",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x4A5,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Reactive Power Output L3",
        key="reactive Power_output_l3",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x4A6,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Power Factor Output L3",
        key="power_factor_output_l3",
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x4A7,
        unit=REGISTER_S16,
        scale=0.001,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current PCC L3",
        key="current_pcc_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x4A8,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power PCC L3",
        key="active_power_pcc_l3",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x4A9,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Reactive Power PCC L3",
        key="reactive Power_pcc_l3",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x4AA,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Power Factor PCC L3",
        key="power_factor_pcc_l3",
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x4AB,
        unit=REGISTER_S16,
        scale=0.001,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power PV Ext",
        key="active_power_pv_ext",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x4AE,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power Load Sys",
        key="active_power_load_sys",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x4AF,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Voltage Phase L1N",
        key="voltage_phase_l1n",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x4B0,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output L1N",
        key="current_output_l1n",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x4B1,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power Output L1N",
        key="active_power_output_l1n",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x4B2,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current PCC L1N",
        key="current_pcc_l1n",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x4B3,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power PCC L1N",
        key="active_power_pcc_l1n",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x4B4,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Voltage Phase L2N",
        key="voltage_phase_l2n",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x4B5,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output L2N",
        key="current_output_l2n",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x4B6,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power Output L2N",
        key="active_power_output_l2n",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x4B7,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Current PCC L2N",
        key="current_pcc_l2n",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x4B8,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Active Power PCC L2N",
        key="active_power_pcc_l2n",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x4B9,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Voltage Line L1",
        key="voltage_line_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x4BA,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Voltage Line L2",
        key="voltage_line_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x4BB,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Voltage Line L3",
        key="voltage_line_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x4BC,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
    ),
    ###
    #
    # Off Grid Output (0x0500-0x057F)
    #
    ###
    SofarModbusSensorEntityDescription(
        name="Active Power Off-Grid Total",
        key="active_power_offgrid_total",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x504,
        # newblock = True,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Reactive Power Off-Grid Total",
        key="reactive Power_offgrid_total",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x505,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Apparent Power Off-Grid Total",
        key="apparent_power_offgrid_total",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x506,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Frequency",
        key="offgrid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        register=0x507,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Voltage L1",
        key="offgrid_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x50A,
        scan_group=SCAN_GROUP_FAST,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Current Output L1",
        key="offgrid_current_output_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x50B,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Active Power Output L1",
        key="offgrid_active_power_output_l1",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x50C,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Reactive Power Output L1",
        key="offgrid_reactive Power_output_l1",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x50D,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Apparent Power Output L1",
        key="offgrid_apparent_power_output_l1",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x50E,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid LoadPeakRatio L1",
        key="offgrid_loadpeakratio_l1",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x50F,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Voltage L2",
        key="offgrid_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x512,
        scan_group=SCAN_GROUP_FAST,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Current Output L2",
        key="offgrid_current_output_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x513,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Active Power Output L2",
        key="offgrid_active_power_output_l2",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x514,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Reactive Power Output L2",
        key="offgrid_reactive Power_output_l2",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x515,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Apparent Power Output L2",
        key="offgrid_apparent_power_output_l2",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x516,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid LoadPeakRatio L2",
        key="offgrid_loadpeakratio_l2",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x517,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Voltage L3",
        key="offgrid_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x51A,
        scan_group=SCAN_GROUP_FAST,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Current Output L3",
        key="offgrid_current_output_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x51B,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Active Power Output L3",
        key="offgrid_active_power_output_l3",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x51C,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Reactive Power Output L3",
        key="offgrid_reactive Power_output_l3",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        register=0x51D,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Apparent Power Output L3",
        key="offgrid_apparent_power_output_l3",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x51E,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid LoadPeakRatio L3",
        key="offgrid_loadpeakratio_l3",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x51F,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Voltage Output L1N",
        key="offgrid_voltage_output_l1n",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x522,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Current Output L1N",
        key="offgrid_current_output_l1n",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x523,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Active Power Output L1N",
        key="offgrid_active_power_output_l1n",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x524,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Voltage Output L2N",
        key="offgrid_voltage_output_l2n",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x525,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Current Output L2N",
        key="offgrid_current_output_l2n",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x526,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Off-Grid Active Power Output L2N",
        key="offgrid_active_power_output_l2n",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x527,
        newblock=True,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    ###
    #
    # PV Input (0x0580-0x05FF)
    #
    ###
    SofarModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x584,
        newblock=True,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x585,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x586,
        scan_group=SCAN_GROUP_FAST,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x587,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x588,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x589,
        scan_group=SCAN_GROUP_FAST,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x58A,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV | GEN | ALL_MPPT_GROUP,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x58B,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | ALL_MPPT_GROUP,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power 3",
        key="pv_power_3",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x58C,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | ALL_MPPT_GROUP,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Voltage 4",
        key="pv_voltage_4",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x58D,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV | GEN | MPPT4 | MPPT6 | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Current 4",
        key="pv_current_4",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x58E,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT4 | MPPT6 | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power 4",
        key="pv_power_4",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x58F,
        newblock=True,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT4 | MPPT6 | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Voltage 5",
        key="pv_voltage_5",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x590,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV | GEN | MPPT6 | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Current 5",
        key="pv_current_5",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x591,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT6 | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power 5",
        key="pv_power_5",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x592,
        newblock=True,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT6 | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Voltage 6",
        key="pv_voltage_6",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x593,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV | GEN | MPPT6 | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Current 6",
        key="pv_current_6",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x594,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT6 | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power 6",
        key="pv_power_6",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x594,
        newblock=True,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT6 | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Voltage 7",
        key="pv_voltage_7",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x596,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV | GEN | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Current 7",
        key="pv_current_7",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x597,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power 7",
        key="pv_power_7",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x598,
        newblock=True,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Voltage 8",
        key="pv_voltage_8",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x599,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV | GEN | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Current 8",
        key="pv_current_8",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x59A,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power 8",
        key="pv_power_8",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x59B,
        newblock=True,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT8 | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Voltage 9",
        key="pv_voltage_9",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x59C,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV | GEN | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Current 9",
        key="pv_current_9",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x59D,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power 9",
        key="pv_power_9",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x59E,
        newblock=True,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Voltage 10",
        key="pv_voltage_10",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x59F,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV | GEN | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Current 10",
        key="pv_current_10",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x5A0,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power 10",
        key="pv_power_10",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x5A1,
        newblock=True,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV | GEN | MPPT10,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power Total",
        key="pv_power_total",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x5C4,
        newblock=True,
        scale=0.1,
        rounding=1,
        # entity_registry_enabled_default =  False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="PV Power Total",
        key="pv_power_total",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x5C4,
        newblock=True,
        scale=0.01,
        rounding=2,
        # entity_registry_enabled_default =  False,
        allowedtypes=PV | GEN,
    ),
    ###
    #
    # Battery Input (0x0600-0x067F)
    #
    ###
    SofarModbusSensorEntityDescription(
        name="Battery Voltage 1",
        key="battery_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x604,
        newblock=True,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Current 1",
        key="battery_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x605,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Power 1",
        key="battery_power_1",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x606,
        unit=REGISTER_S16,
        scan_group=SCAN_GROUP_FAST,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 1",
        key="battery_temperature_1",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x607,
        unit=REGISTER_S16,
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 1",
        key="battery_capacity_1",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # device_class = SensorDeviceClass.BATTERY,
        register=0x608,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 1",
        key="battery_state_of_health_1",
        register=0x609,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=HYBRID,
        icon="mdi:battery-heart",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 1",
        key="battery_charge_cycle_1",
        state_class=SensorStateClass.MEASUREMENT,
        register=0x60A,
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Voltage 2",
        key="battery_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x60B,
        newblock=True,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Current 2",
        key="battery_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x60C,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Power 2",
        key="battery_power_2",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x60D,
        unit=REGISTER_S16,
        scan_group=SCAN_GROUP_FAST,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 2",
        key="battery_temperature_2",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x60E,
        unit=REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 2",
        key="battery_capacity_2",
        native_unit_of_measurement=PERCENTAGE,
        # device_class = SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x60F,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 2",
        key="battery_state_of_health_2",
        register=0x610,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-heart",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 2",
        key="battery_charge_cycle_2",
        state_class=SensorStateClass.MEASUREMENT,
        register=0x611,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Voltage 3",
        key="battery_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x612,
        newblock=True,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Current 3",
        key="battery_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x613,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Power 3",
        key="battery_power_3",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x614,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 3",
        key="battery_temperature_3",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x615,
        unit=REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 3",
        key="battery_capacity_3",
        native_unit_of_measurement=PERCENTAGE,
        # device_class = SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x616,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 3",
        key="battery_state_of_health_3",
        register=0x617,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        icon="mdi:battery-heart",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 3",
        key="battery_charge_cycle_3",
        state_class=SensorStateClass.MEASUREMENT,
        register=0x618,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Voltage 4",
        key="battery_voltage_4",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x619,
        newblock=True,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Current 4",
        key="battery_current_4",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x61A,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Power 4",
        key="battery_power_4",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x61B,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 4",
        key="battery_temperature_4",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x61C,
        unit=REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 4",
        key="battery_capacity_4",
        native_unit_of_measurement=PERCENTAGE,
        # device_class = SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x61D,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 4",
        key="battery_state_of_health_4",
        register=0x61E,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        icon="mdi:battery-heart",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 4",
        key="battery_charge_cycle_4",
        state_class=SensorStateClass.MEASUREMENT,
        register=0x61F,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Voltage 5",
        key="battery_voltage_5",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x620,
        newblock=True,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Current 5",
        key="battery_current_5",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x621,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Power 5",
        key="battery_power_5",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x622,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 5",
        key="battery_temperature_5",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x623,
        unit=REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 5",
        key="battery_capacity_5",
        native_unit_of_measurement=PERCENTAGE,
        # device_class = SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x624,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 5",
        key="battery_state_of_health_5",
        register=0x625,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        icon="mdi:battery-heart",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 5",
        key="battery_charge_cycle_5",
        state_class=SensorStateClass.MEASUREMENT,
        register=0x626,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Voltage 6",
        key="battery_voltage_6",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x627,
        newblock=True,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Current 6",
        key="battery_current_6",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x628,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Power 6",
        key="battery_power_6",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x629,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 6",
        key="battery_temperature_6",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x62A,
        unit=REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 6",
        key="battery_capacity_6",
        native_unit_of_measurement=PERCENTAGE,
        # device_class = SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x62B,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 6",
        key="battery_state_of_health_6",
        register=0x62C,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        icon="mdi:battery-heart",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 6",
        key="battery_charge_cycle_6",
        state_class=SensorStateClass.MEASUREMENT,
        register=0x62D,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Voltage 7",
        key="battery_voltage_7",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x62E,
        newblock=True,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Current 7",
        key="battery_current_7",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x62F,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Power 7",
        key="battery_power_7",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x630,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 7",
        key="battery_temperature_7",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x631,
        unit=REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 7",
        key="battery_capacity_7",
        native_unit_of_measurement=PERCENTAGE,
        # device_class = SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x632,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 7",
        key="battery_state_of_health_7",
        register=0x633,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        icon="mdi:battery-heart",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 7",
        key="battery_charge_cycle_7",
        state_class=SensorStateClass.MEASUREMENT,
        register=0x634,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Voltage 8",
        key="battery_voltage_8",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x635,
        newblock=True,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Current 8",
        key="battery_current_8",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x636,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Power 8",
        key="battery_power_8",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x637,
        unit=REGISTER_S16,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Temperature 8",
        key="battery_temperature_8",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x638,
        unit=REGISTER_S16,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity 8",
        key="battery_capacity_8",
        native_unit_of_measurement=PERCENTAGE,
        # device_class = SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x639,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health 8",
        key="battery_state_of_health_8",
        register=0x63A,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        icon="mdi:battery-heart",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Charge Cycle 8",
        key="battery_charge_cycle_8",
        state_class=SensorStateClass.MEASUREMENT,
        register=0x63B,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Power Total",
        key="battery_power_total",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x667,
        newblock=True,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Capacity Total",
        key="battery_capacity_total",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x668,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery State of Health Total",
        key="battery_state_of_health_total",
        register=0x669,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=HYBRID,
        icon="mdi:battery-heart",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ###
    #
    # Electric Power (0x0680-0x06BF)
    #
    ###
    SofarModbusSensorEntityDescription(
        name="Solar Generation Today",
        key="solar_generation_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x684,
        newblock=True,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Solar Generation Total",
        key="solar_generation_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x686,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Load Consumption Today",
        key="load_consumption_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x688,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Load Consumption Total",
        key="load_consumption_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x68A,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
    ),
    SofarModbusSensorEntityDescription(
        name="Import Energy Today",
        key="import_energy_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x68C,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
        icon="mdi:home-import-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="Import Energy Total",
        key="import_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x68E,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
        icon="mdi:home-import-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="Export Energy Today",
        key="export_energy_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x690,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID | PV,
        icon="mdi:home-export-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="Export Energy Total",
        key="export_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x692,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | PV,
        icon="mdi:home-export-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Input Energy Today",
        key="battery_input_energy_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x694,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID,
        icon="mdi:battery-arrow-up",
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Input Energy Total",
        key="battery_input_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x696,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
        icon="mdi:battery-arrow-up",
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Output Energy Today",
        key="battery_output_energy_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x698,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=HYBRID,
        icon="mdi:battery-arrow-down",
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Output Energy Total",
        key="battery_output_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x69A,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
        icon="mdi:battery-arrow-down",
    ),
    ###
    #
    # Basic Parameter Configuration (0x1000-0x10FF)
    #
    ###
    SofarModbusSensorEntityDescription(
        name="FeedIn: Limitation Mode",
        key="feedin_limitation_mode",
        register=0x1023,
        scale={0: "Disabled", 1: "Enabled - Feed-in limitation", 2: "Enabled - 3-phase limit"},
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="FeedIn: Maximum Power",
        key="feedin_max_power",
        register=0x1024,
        scale=100,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="EPS Control",
        key="eps_control",
        register=0x1029,
        newblock=True,
        scale={
            0: "Turn Off",
            1: "Turn On, Prohibit Cold Start",
            2: "Turn On, Enable Cold Start",
        },
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | X3 | EPS,
    ),
    SofarModbusSensorEntityDescription(
        name="Battery Active Control",
        key="battery_active_control",
        register=0x102B,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Parallel Control",
        key="parallel_control",
        register=0x1035,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=HYBRID | PV | X3 | PM,
    ),
    SofarModbusSensorEntityDescription(
        name="Parallel Master-Salve",
        key="parallel_masterslave",
        register=0x1036,
        scale={
            0: "Slave",
            1: "Master",
        },
        allowedtypes=HYBRID | PV | X3 | PM,
    ),
    SofarModbusSensorEntityDescription(
        name="Parallel Address",
        key="parallel_address",
        register=0x1037,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | PV | X3 | PM,
    ),
    ###
    #
    # Battery Configuration (0x1044-0x105A)
    # Read-only for now. On write all 23 registers would need to be set in one chunk.
    #
    ###
    SofarModbusSensorEntityDescription(
        name="BatConfig: ID",
        key="bat_config_id",
        register=0x1044,
        newblock=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Address 1",
        key="bat_config_address_1",
        register=0x1045,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Protocol",
        key="bat_config_protocol",
        register=0x1046,
        scale={
            0: "First Flight built-in BMS/Default",
            1: "Pie Energy protocol/PYLON",
            2: "First Flight protocol/GENERAL",
            3: "AMASS",
            4: "LG",
            5: "AlphaESS",
            6: "CATL",
            7: "WECO",
            8: "Fronus",
            9: "EMS",
            10: "Nilar",
            11: "BTS 5K",
            11: "Move for",
        },
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Overvoltage Protection",
        key="bat_config_overvoltage_protection",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        register=0x1047,
        scale=0.1,
        rounding=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Charging Voltage",
        key="bat_config_charging_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        register=0x1048,
        scale=0.1,
        rounding=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Undervoltage Protection",
        key="bat_config_undervoltage_protection",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        register=0x1049,
        scale=0.1,
        rounding=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Minimum Discharge Voltage",
        key="bat_config_minimum_discharge_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        register=0x104A,
        scale=0.1,
        rounding=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Maximum Charge Current Limit",
        key="bat_config_maximum_charge_current_limit",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        register=0x104B,
        scale=0.01,
        rounding=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Maximum Discharge Current Limit",
        key="bat_config_maximum_discharge_current_limit",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        register=0x104C,
        scale=0.01,
        rounding=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Depth of Discharge",
        key="bat_config_depth_of_discharge",
        native_unit_of_measurement=PERCENTAGE,
        register=0x104D,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: End of Discharge",
        key="bat_config_end_of_discharge",
        native_unit_of_measurement=PERCENTAGE,
        register=0x104E,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Capacity",
        key="bat_config_capacity",
        native_unit_of_measurement="Ah",
        register=0x104F,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Rated Battery Voltage",
        key="bat_config_rated_battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        register=0x1050,
        scale=0.1,
        rounding=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Cell Type",
        key="bat_config_cell_type",
        register=0x1051,
        scale={
            0: "Lead acid",
            1: "Lithium iron phosphate",
            2: "Ternary",
            3: "Lithium titanate",
            4: "AGM",
            5: "Gel",
            6: "Flooded",
        },
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: EPS Buffer",
        key="bat_config_eps_buffer",
        native_unit_of_measurement=PERCENTAGE,
        register=0x1052,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    # 0x1053 BatConfig_Control skipped for now. Only useful when writing
    SofarModbusSensorEntityDescription(
        name="BatConfig: Address 2",
        key="bat_config_address_2",
        register=0x1054,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Address 3",
        key="bat_config_address_3",
        register=0x1055,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Address 4",
        key="bat_config_address_4",
        register=0x1056,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Lead Acid Battery Temperature Compensation Factor",
        key="bat_config_tempco",
        native_unit_of_measurement="mV/Cell",
        register=0x1057,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Lead Acid Battery Recovery Buffer",
        key="bat_config_rated_battery_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        register=0x1058,
        scale=0.1,
        rounding=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    SofarModbusSensorEntityDescription(
        name="BatConfig: Lead Acid Battery Float Voltage",
        key="bat_config_voltage_float",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        register=0x105A,
        scale=0.1,
        rounding=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        icon="mdi:battery-check-outline",
    ),
    ###
    #
    # Remote Control (0x1100-0x12FF)
    #
    ###
    SofarModbusSensorEntityDescription(
        name="Remote Switch On Off",
        key="remote_switch_on_off",
        register=0x1104,
        newblock=True,
        scale={
            0: "Off",
            1: "On",
        },
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    SofarModbusSensorEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        register=0x1110,
        scale={
            0: "Self Use",
            1: "Time of Use",
            2: "Timing Mode",
            3: "Passive Mode",
            4: "Peak Cut Mode",
            5: "Off-grid Mode",
        },
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
    ),
    # TIMING AND TOU DISABLED AS THESE ARE NOT WORKING
    # SofarModbusSensorEntityDescription(
    #     name = "Timing: ID",
    #     key = "ro_timing_id",
    #     register = 0x1111,
    #     scale = { 0: "0",
    #               1: "1",
    #               2: "2",
    #               3: "3",
    #               65531: "FFFB",
    #               65532: "FFFC",
    #               65533: "FFFD",
    #               65534: "FFFE",
    #               65535: "FFFF", },
    #     #entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "Timing: Charge",
    #     key = "ro_timing_charge",
    #     register = 0x1112,
    #     scale = { 0: "Enabled - Charging & Discharging",
    #               1: "Enabled - Charging",
    #               2: "Enabled - Discharging",
    #               4: "Disabled", },
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "Timing: Charge Start Time",
    #     key = "ro_timing_charge_start_time",
    #     register = 0x1113,
    #     scale = value_function_sofartime,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "Timing: Charge End Time",
    #     key = "ro_timing_charge_end_time",
    #     register = 0x1114,
    #     scale = value_function_sofartime,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "Timing: Discharge Start Time",
    #     key = "ro_timing_discharge_start_time",
    #     register = 0x1115,
    #     scale = value_function_sofartime,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "Timing: Discharge End Time",
    #     key = "ro_timing_discharge_end_time",
    #     register = 0x1116,
    #     scale = value_function_sofartime,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "Timing: Charge Power",
    #     key = "timing_charge_power",
    #     native_unit_of_measurement = UnitOfPower.WATT,
    #     device_class = SensorDeviceClass.POWER,
    #     register = 0x1117,
    #     unit = REGISTER_U32,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "Timing: Discharge Power",
    #     key = "timing_discharge_power",
    #     native_unit_of_measurement = UnitOfPower.WATT,
    #     device_class = SensorDeviceClass.POWER,
    #     register = 0x1119,
    #     unit = REGISTER_U32,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "Timing: Control",
    #     key = "timeing_control",
    #     register = 0x111F,
    #     scale = { 0: "0",
    #               1: "1",
    #               2: "2",
    #               3: "3",
    #               65531: "FFFB",
    #               65532: "FFFC",
    #               65533: "FFFD",
    #               65534: "FFFE",
    #               65535: "FFFF", },
    #     #entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "TOU: ID",
    #     key = "tou_id",
    #     register = 0x1120,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "TOU: Control",
    #     key = "ro_tou_control",
    #     register = 0x1121,
    #     scale = { 0: "Disabled",
    #               1: "Enabled", },
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "TOU: Charge Start Time",
    #     key = "ro_tou_charge_start_time",
    #     register = 0x1122,
    #     scale = value_function_sofartime,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "TOU: Charge End Time",
    #     key = "ro_tou_charge_end_time",
    #     register = 0x1123,
    #     scale = value_function_sofartime,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    #     icon = "mdi:battery-clock",
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "TOU: Target SOC",
    #     key = "tou_target_soc",
    #     register = 0x1124,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "TOU Charge Power",
    #     key = "tou_charge_power",
    #     native_unit_of_measurement = UnitOfPower.WATT,
    #     device_class = SensorDeviceClass.POWER,
    #     register = 0x1125,
    #     unit = REGISTER_U32,
    #     entity_registry_enabled_default =  False,
    #     allowedtypes = HYBRID,
    # ),
    SofarModbusSensorEntityDescription(
        name="Update System Time Operation Result",
        key="sync_rtc_result",
        register=0x100A,
        scale={
            0: "Successful",
            1: "Operation in progress",
            2: "Enabled - Discharging",
            4: "Disabled",
            65531: "Operation failed, controller refused to respond",
            65532: "Operation failed, no response from the controller",
            65533: "Operation failed, current function disabled",
            65534: "Operation failed, parameter access failed",
            65535: "Operation failed, input parameters incorrect",
        },
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="RO: Passive: Timeout",
        key="ro_passive_mode_timeout",
        register=0x1184,
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Passive: Timeout Action",
        key="ro_passive_mode_timeout_action",
        register=0x1185,
        scale={
            0: "Force Standby",
            1: "Return to Previous Mode",
        },
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Passive: Desired Grid Power",
        key="passive_mode_grid_power",
        unit=REGISTER_S32,
        entity_registry_enabled_default=False,
        register=0x1187,
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Passive: Minimum Battery Power",
        key="passive_mode_battery_power_min",
        unit=REGISTER_S32,
        register=0x1189,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SofarModbusSensorEntityDescription(
        name="Passive: Maximum Battery Power",
        key="passive_mode_battery_power_max",
        unit=REGISTER_S32,
        register=0x118B,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]


BATTERY_SENSOR_TYPES: list[SofarModbusSensorEntityDescription] = [
    # SofarModbusSensorEntityDescription(
    #     name = "total voltage",
    #     key = "total_voltage",
    #     native_unit_of_measurement = UnitOfElectricPotential.VOLT,
    #     device_class = SensorDeviceClass.VOLTAGE,
    #     register = 0x900F,
    #     scale = 0.1,
    #     rounding = 1,
    #     allowedtypes = BAT_BTS,
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "total current",
    #     key = "total_current",
    #     native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
    #     device_class = SensorDeviceClass.CURRENT,
    #     register = 0x9010,
    #     unit = REGISTER_S16,
    #     scale = 0.1,
    #     rounding = 1,
    #     allowedtypes = BAT_BTS,
    # ),
    # SofarModbusSensorEntityDescription(
    #     name = "BMS Manufacture Name",
    #     key = "bms_manufacture_name",
    #     register = 0x9007,
    #     newblock = True,
    #     unit = REGISTER_STR,
    #     wordcount=4,
    #     entity_category = EntityCategory.DIAGNOSTIC,
    #     allowedtypes = BAT_BTS,
    # ),
    SofarModbusSensorEntityDescription(
        name="BMS Version",
        key="bms_version",
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        register=0x900B,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Realtime Capacity",
        key="realtime_capacity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x900E,
        scale=0.1,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Total Voltage",
        key="total_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x900F,
        scale=0.1,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Total Current",
        key="total_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x9010,
        unit=REGISTER_S16,
        scale=0.1,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="SOC",
        key="soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x9012,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="SOH",
        key="soh",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x9013,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Pack ID",
        key="pack_id",
        newblock=True,
        register=0x9044,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Pack Time",
        key="pack_time",
        register=0x9045,
        unit=REGISTER_S32,
        wordcount=1,
        scale=value_function_2byte_timestamp,
        entity_category=EntityCategory.DIAGNOSTIC,
        allowedtypes=BAT_BTS,
        icon="mdi:clock",
    ),
    SofarModbusSensorEntityDescription(
        name="Pack Serial Number",
        key="pack_serial_number",
        register=0x9048,
        newblock=True,
        unit=REGISTER_STR,
        wordcount=9,
        entity_category=EntityCategory.DIAGNOSTIC,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="cell {} voltage",
        key="cell_{}_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x9051,
        scale=0.001,
        rounding=3,
        allowedtypes=BAT_BTS,
        value_series=16,
    ),
    SofarModbusSensorEntityDescription(
        name="cell min voltage",
        key="cell_min_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x9069,
        scale=0.001,
        rounding=3,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="cell max voltage",
        key="cell_max_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x906A,
        scale=0.001,
        rounding=3,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Pack Temperature {}",
        key="pack_temperature_{}",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x906B,
        unit=REGISTER_S16,
        scale=0.1,
        allowedtypes=BAT_BTS,
        value_series=4,
    ),
    SofarModbusSensorEntityDescription(
        name="Pack Temperature MOS",
        key="pack_temperature_mos",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x906F,
        unit=REGISTER_S16,
        scale=0.1,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Pack Temperature Env",
        key="pack_temperature_env",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x9070,
        unit=REGISTER_S16,
        scale=0.1,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Pack Current",
        key="pack_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x9071,
        unit=REGISTER_S16,
        scale=0.1,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Pack remaining capacity",
        key="pack_remaining_capacity",
        native_unit_of_measurement="Ah",
        register=0x9072,
        scale=0.1,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Pack Full charge capacity",
        key="pack_full_charge_capacity",
        native_unit_of_measurement="Ah",
        register=0x9073,
        scale=0.1,
        allowedtypes=BAT_BTS,
    ),
    SofarModbusSensorEntityDescription(
        name="Pack Cycles",
        key="pack_cycles",
        register=0x9074,
        entity_category=EntityCategory.DIAGNOSTIC,
        allowedtypes=BAT_BTS,
    ),
    # SofarModbusSensorEntityDescription(
    #     name = "Pack SOC",
    #     key = "pack_soc",
    #     native_unit_of_measurement = PERCENTAGE,
    #     device_class = SensorDeviceClass.BATTERY,
    #     register = 0x907A,
    #     allowedtypes = BAT_BTS,
    # ),
]


@dataclass
class battery_config(base_battery_config):
    def __init__(self):
        self.battery_sensor_type = BATTERY_SENSOR_TYPES
        self.battery_sensor_name_prefix = "Battery {batt-nr}/{pack-nr} "
        self.battery_sensor_key_prefix = "battery_{batt-nr}_{pack-nr}_"

    bapack_number_address = 0x900D
    bms_inquire_address = 0x9020
    bms_check_address = 0x9044
    batt_pack_serial_address = 0x9048
    batt_pack_serial_len = 9
    batt_pack_model_address = 0x9007
    batt_pack_model_len = 4

    number_cels_in_parallel: int = None  # number of battery pack cells in parallel
    number_strings: int = None  # number of strings of all battery packs
    batt_pack_serials = {}
    selected_batt_nr: int = None
    selected_batt_pack_nr: int = None

    async def init_batt_pack(self, hub, serial_number):
        if not self.batt_pack_serials.__contains__(self.selected_batt_nr):
            self.batt_pack_serials[self.selected_batt_nr] = {}
        self.batt_pack_serials[self.selected_batt_nr][self.selected_batt_pack_nr] = serial_number

    async def get_batt_pack_quantity(self, hub):
        if self.number_cels_in_parallel == None:
            await self._determine_bat_quantitys(hub)
        return self.number_cels_in_parallel

    async def get_batt_quantity(self, hub):
        if self.number_strings == None:
            await self._determine_bat_quantitys(hub)
        return self.number_strings

    async def select_battery(self, hub, batt_nr: int, batt_pack_nr: int):
        faulty_nr = 0
        payload = faulty_nr << 12 | batt_pack_nr << 8 | batt_nr
        _LOGGER.debug(f"select batt-nr: {batt_nr} batt-pack: {batt_pack_nr} {hex(payload)}")
        await hub.async_write_registers_single(
            unit=hub._modbus_addr, address=self.bms_inquire_address, payload=payload
        )
        await asyncio.sleep(0.3)
        self.selected_batt_nr = batt_nr
        self.selected_batt_pack_nr = batt_pack_nr
        return True

    async def get_batt_pack_serial(self, hub, batt_nr: int, batt_pack_nr: int):
        if not self.batt_pack_serials.__contains__(batt_nr):
            return None
        if not self.batt_pack_serials[batt_nr].__contains__(batt_pack_nr):
            return None
        return self.batt_pack_serials[batt_nr][batt_pack_nr]

    async def get_batt_pack_model(self, hub):
        try:
            inverter_data = await hub.async_read_holding_registers(
                unit=hub._modbus_addr, address=self.batt_pack_model_address, count=self.batt_pack_model_len
            )
            if not inverter_data.isError():
                decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
                serial = str(decoder.decode_string(self.batt_pack_model_len * 2).decode("ascii"))
                return serial
        except:
            _LOGGER.warn(f"Cannot read batt pack serial")
            return None

    async def get_batt_pack_sw_version(self, hub, new_data, key_prefix):
        sw_version_key = key_prefix + "bms_version"
        if not new_data.__contains__(sw_version_key):
            _LOGGER.info(f"batt pack software version not received {sw_version_key}")
            return None
        return f"BMS: V{new_data[sw_version_key]}"

    async def check_battery_on_start(self, hub, old_data, key_prefix, batt_nr: int, batt_pack_nr: int):
        if not self.batt_pack_serials.__contains__(batt_nr):
            return False
        if not self.batt_pack_serials[batt_nr].__contains__(batt_pack_nr):
            return False

        faulty_nr = 0
        payload = faulty_nr << 12 | batt_pack_nr << 8 | batt_nr
        for retry in range(0, 10):
            inverter_data = await hub.async_read_holding_registers(
                unit=hub._modbus_addr, address=self.bms_check_address, count=1
            )
            if not inverter_data.isError():
                decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
                readed = decoder.decode_16bit_uint()
                ok = readed == payload
                if not ok:
                    await asyncio.sleep(0.3)
                else:
                    return True

            else:
                _LOGGER.error(f"can't read batt check register")
                return False

    async def check_battery_on_end(self, hub, old_data, new_data, key_prefix, batt_nr: int, batt_pack_nr: int):
        # inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=0x9045, count=2)
        # if not inverter_data.isError():
        #     decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
        #     batt_time = value_function_2byte_timestamp(decoder.decode_32bit_uint(), None, None)
        #     _LOGGER.info(f"batt time: {batt_time}")

        faulty_nr = 0
        compare_value = faulty_nr << 12 | batt_pack_nr << 8 | batt_nr
        inverter_data = await hub.async_read_holding_registers(
            unit=hub._modbus_addr, address=self.bms_check_address, count=1
        )
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            new_value = decoder.decode_16bit_uint()
            _LOGGER.debug(f"check_battery_on_end: {hex(new_value)} {hex(compare_value)}")
            if new_value == compare_value:
                serial_key = key_prefix + "pack_serial_number"
                if not new_data.__contains__(serial_key):
                    _LOGGER.info(f"batt pack serial not received {serial_key}")
                    return False
                serial = new_data[serial_key]
                _LOGGER.debug(f"batt pack serial: {serial}")
                return serial == self.batt_pack_serials[batt_nr][batt_pack_nr]
            else:
                return False

        return False

    async def _determine_bat_quantitys(self, hub):
        res = None
        try:
            inverter_data = await hub.async_read_holding_registers(
                unit=hub._modbus_addr, address=self.bapack_number_address, count=1
            )
            if not inverter_data.isError():
                decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
                self.number_cels_in_parallel = decoder.decode_8bit_int()
                self.number_strings = decoder.decode_8bit_int()
        except Exception as ex:
            _LOGGER.warning(f"{hub.name}: attempt to read BaPack number failed at 0x{address:x}", exc_info=True)

    async def init_batt_pack_serials(self, hub):
        retry = 0
        while retry < 5:
            retry = retry + 1
            for batt_nr in range(self.number_strings):
                if not self.batt_pack_serials.__contains__(batt_nr):
                    self.batt_pack_serials[batt_nr] = {}

                for batt_pack_nr in range(self.number_cels_in_parallel):
                    await self.select_battery(hub, batt_nr, batt_pack_nr)
                    serial = await self._determinate_batt_pack_serial(hub)
                    if self.batt_pack_serials[batt_nr].__contains__(batt_pack_nr):
                        if self.batt_pack_serials[batt_nr][batt_pack_nr] != serial:
                            retry = retry - 1
                    self.batt_pack_serials[batt_nr][batt_pack_nr] = serial

        _LOGGER.info(f"serials {self.batt_pack_serials}")

    async def _determinate_batt_pack_serial(self, hub):
        inverter_data = await hub.async_read_holding_registers(
            unit=hub._modbus_addr, address=self.batt_pack_serial_address, count=self.batt_pack_serial_len
        )
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            serial = str(decoder.decode_string(self.batt_pack_serial_len * 2).decode("ascii"))
            return serial


# ============================ plugin declaration =================================================


@dataclass
class sofar_plugin(plugin_base):
    """
    def isAwake(self, datadict):
        return (datadict.get('run_mode', None) == 'Normal Mode')

    def wakeupButton(self):
        return 'battery_awaken'
    """

    async def async_determineInverterType(self, hub, configdict):
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber = await async_read_serialnr(hub, 0x445, swapbytes=False)
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find serial number, even not for other Inverter")
            seriesnumber = "unknown"

        # derive invertertype from seriiesnumber
        if seriesnumber.startswith("SP1ES120N6"):
            invertertype = HYBRID | X3  # HYD20KTL-3P no PV
            self.inverter_model = "HYD20KTL-3P"
        elif seriesnumber.startswith("SP1"):
            invertertype = HYBRID | X3 | GEN | BAT_BTS  # HYDxxKTL-3P
            self.inverter_model = "HYDxxKTL-3P"
        elif seriesnumber.startswith("SP2"):
            invertertype = HYBRID | X3 | GEN | BAT_BTS  # HYDxxKTL-3P 2nd type
            self.inverter_model = f"HYD{seriesnumber[6:8]}KTL-3P 2nd"
        elif seriesnumber.startswith("ZP1"):
            invertertype = HYBRID | X3 | GEN  # Azzurro HYDxx ZSS
            self.inverter_model = "HYDxx ZSS"
        elif seriesnumber.startswith("ZP2"):
            invertertype = HYBRID | X3 | GEN  # Azzurro HYDxx ZSS
            self.inverter_model = "HYDxx ZSS"
        elif seriesnumber.startswith("SM2E"):
            invertertype = HYBRID | X1 | GEN  # HYDxxxxES, Not actually X3, needs changing
            self.inverter_model = "HYDxxxxES"
        elif seriesnumber.startswith("ZM2E"):
            invertertype = HYBRID | X1 | GEN  # HYDxxxxKTL ZCS HP, Single Phase
            self.inverter_model = "HYDxxxxKTL ZCS HP"
        elif seriesnumber.startswith("SH3E"):
            invertertype = PV | X1 | GEN  # 4.6 KTLM-G3
            self.inverter_model = "4.6 KTLM-G3"
        elif seriesnumber.startswith("SS2E"):
            invertertype = PV | X3 | GEN  # 4.4 KTLX-G3
            self.inverter_model = "4.4 KTLX-G3"
        elif seriesnumber.startswith("ZS2E"):
            invertertype = PV | X3 | GEN  # 12 Azzurro KTL-V3
            self.inverter_model = "12 Azzurro KTL-V3"
        elif seriesnumber.startswith("SQ1ES1"):
            invertertype = PV | X3 | GEN | MPPT10  # 100kW KTLX-G4
            self.inverter_model = "100kW KTLX-G4"
        elif seriesnumber.startswith("SA1"):
            invertertype = PV | X1  # Older Might be single
        elif seriesnumber.startswith("SB1"):
            invertertype = PV | X1  # Older Might be single
        elif seriesnumber.startswith("SC1"):
            invertertype = PV | X3  # Older Probably 3phase
        elif seriesnumber.startswith("SD1"):
            invertertype = PV | X3  # Older Probably 3phase
        elif seriesnumber.startswith("SF4"):
            invertertype = PV | X3  # Older Probably 3phase
        elif seriesnumber.startswith("SH1"):
            invertertype = HYBRID | X3 | GEN | BAT_BTS  # HYD5...8KTL-3P
            self.inverter_model = "HYD5...8KTL-3P"
        elif seriesnumber.startswith("SL1"):
            invertertype = PV | X3  # Older Probably 3phase
        elif seriesnumber.startswith("SJ2"):
            invertertype = PV | X3  # Older Probably 3phase
        # elif seriesnumber.startswith('SM1E'):  plugin_sofar_old
        # elif seriesnumber.startswith('ZM1E'):  plugin_sofar_old

        else:
            invertertype = 0
            _LOGGER.error(f"unrecognized {hub.name} inverter type - serial number : {seriesnumber}")

        if invertertype > 0:
            read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
            read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
            read_pm = configdict.get(CONF_READ_PM, DEFAULT_READ_PM)
            if read_eps:
                invertertype = invertertype | EPS
            if read_dcb:
                invertertype = invertertype | DCB
            if read_pm:
                invertertype = invertertype | PM

        return invertertype

    def matchInverterWithMask(self, inverterspec, entitymask, serialnumber="not relevant", blacklist=None):
        # returns true if the entity needs to be created for an inverter
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP) != 0) or (entitymask & ALL_GEN_GROUP == 0)
        xmatch = ((inverterspec & entitymask & ALL_X_GROUP) != 0) or (entitymask & ALL_X_GROUP == 0)
        hybmatch = ((inverterspec & entitymask & ALL_TYPE_GROUP) != 0) or (entitymask & ALL_TYPE_GROUP == 0)
        epsmatch = ((inverterspec & entitymask & ALL_EPS_GROUP) != 0) or (entitymask & ALL_EPS_GROUP == 0)
        dcbmatch = ((inverterspec & entitymask & ALL_DCB_GROUP) != 0) or (entitymask & ALL_DCB_GROUP == 0)
        pmmatch = ((inverterspec & entitymask & ALL_PM_GROUP) != 0) or (entitymask & ALL_PM_GROUP == 0)
        mpptmatch = ((inverterspec & entitymask & ALL_MPPT_GROUP) != 0) or (entitymask & ALL_MPPT_GROUP == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist:
                if serialnumber.startswith(start):
                    blacklisted = True
        return (
            genmatch and xmatch and hybmatch and epsmatch and dcbmatch and pmmatch and mpptmatch
        ) and not blacklisted

    def getSoftwareVersion(self, new_data):
        return new_data.get("software_version", None)

    def getHardwareVersion(self, new_data):
        return new_data.get("hardware_version", None)


plugin_instance = sofar_plugin(
    plugin_name="Sofar",
    plugin_manufacturer="Sofar Solar",
    SENSOR_TYPES=SENSOR_TYPES,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=[],
    BATTERY_CONFIG=battery_config(),
    block_size=100,
    order16=Endian.BIG,
    order32=Endian.BIG,
    auto_block_ignore_readerror=True,
)
