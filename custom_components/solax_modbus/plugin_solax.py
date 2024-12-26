import logging
from dataclasses import dataclass
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
from custom_components.solax_modbus.const import *
from time import time

_LOGGER = logging.getLogger(__name__)

""" ============================================================================================
bitmasks  definitions to characterize inverters, ogranized by group
these bitmasks are used in entitydeclarations to determine to which inverters the entity applies
within a group, the bits in an entitydeclaration will be interpreted as OR
between groups, an AND condition is applied, so all gruoups must match.
An empty group (group without active flags) evaluates to True.
example: GEN3 | GEN4 | GEN5 | X1 | X3 | EPS
means:  any inverter of tyoe (GEN3 or GEN4 | GEN5) and (X1 or X3) and (EPS)
An entity can be declared multiple times (with different bitmasks) if the parameters are different for each inverter type
"""

GEN = 0x0001  # base generation for MIC, PV, AC
GEN2 = 0x0002
GEN3 = 0x0004
GEN4 = 0x0008
GEN5 = 0x0010
ALL_GEN_GROUP = GEN2 | GEN3 | GEN4 | GEN5 | GEN

X1 = 0x0100
X3 = 0x0200
ALL_X_GROUP = X1 | X3

PV = 0x0400  # Needs further work on PV Only Inverters
AC = 0x0800
HYBRID = 0x1000
MIC = 0x2000
MAX = 0x4000
ALL_TYPE_GROUP = PV | AC | HYBRID | MIC | MAX

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

ALLDEFAULT = 0  # should be equivalent to AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub, address):
    res = None
    inverter_data = None
    try:
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=7)
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(14).decode("ascii")
            if address == 0x300:
                if res and not res.startswith(("M", "X")):
                    ba = bytearray(res, "ascii")  # convert to bytearray for swapping
                    ba[0::2], ba[1::2] = ba[1::2], ba[0::2]  # swap bytes ourselves - due to bug in Endian.LITTLE ?
                    res = str(ba, "ascii")  # convert back to string
                    hub.seriesnumber = res
            hub.seriesnumber = res
    except Exception as ex:
        _LOGGER.warning(
            f"{hub.name}: attempt to read serialnumber failed at 0x{address:x} data: {inverter_data}", exc_info=True
        )
    if not res:
        _LOGGER.warning(
            f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed"
        )
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number: {res}")
    return res


# =================================================================================================


@dataclass
class SolaxModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaxModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaxModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaXModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING


# ====================================== Computed value functions  =================================================


def value_function_remotecontrol_recompute(initval, descr, datadict):
    power_control = datadict.get("remotecontrol_power_control", "Disabled")
    set_type = datadict.get("remotecontrol_set_type", "Set")  # other options did not work
    target = datadict.get("remotecontrol_active_power", 0)
    reactive_power = datadict.get("remotecontrol_reactive_power", 0)
    rc_duration = datadict.get("remotecontrol_duration", 20)
    ap_up = datadict.get("active_power_upper", 0)
    ap_lo = datadict.get("active_power_lower", 0)
    reap_up = datadict.get("reactive_power_upper", 0)
    reap_lo = datadict.get("reactive_power_lower", 0)
    import_limit = datadict.get("remotecontrol_import_limit", 20000)
    meas = datadict.get("measured_power", 0)
    pv = datadict.get("pv_power_total", 0)
    houseload_nett = datadict.get("inverter_power", 0) - meas
    houseload_brut = pv - datadict.get("battery_power_charge", 0) - meas
    # Current SoC for capacity related calculations like Battery Hold/No Discharge
    battery_capacity = datadict.get("battery_capacity", 0)

    if power_control == "Enabled Power Control":
        ap_target = target
    elif power_control == "Enabled Grid Control":  # alternative computation for Power Control
        if target < 0:
            ap_target = target - houseload_nett  # subtract house load
        else:
            ap_target = target - houseload_brut
        power_control = "Enabled Power Control"
    elif power_control == "Enabled Self Use":  # alternative computation for Power Control
        ap_target = 0 - houseload_nett  # subtract house load
        power_control = "Enabled Power Control"
    elif power_control == "Enabled Battery Control":  # alternative computation for Power Control
        ap_target = target - pv  # subtract house load and pv
        power_control = "Enabled Power Control"
    elif power_control == "Enabled Feedin Priority":  # alternative computation for Power Control
        if pv > houseload_nett:
            ap_target = 0 - pv + (houseload_brut - houseload_nett) * 1.20  # 0 - pv + (houseload_brut - houseload_nett)
        else:
            ap_target = 0 - houseload_nett
        power_control = "Enabled Power Control"
    elif power_control == "Enabled No Discharge":  # alternative computation for Power Control
        # Only hold battery level at below 98% SoC to avoid PV from shutting down when full
        if battery_capacity < 98:
            if pv <= houseload_nett:
                ap_target = 0 - pv + (houseload_brut - houseload_nett)  # 0 - pv + (houseload_brut - houseload_nett)
            else:
                ap_target = 0 - houseload_nett
            power_control = "Enabled Power Control"
        else:
            ap_target = 0
            power_control == "Disabled"
    elif power_control == "Disabled":
        ap_target = target
        autorepeat_duration = 10  # or zero - stop autorepeat since it makes no sense when disabled
    old_ap_target = ap_target
    ap_target = min(ap_target, import_limit - houseload_brut)
    # _LOGGER.warning(f"peak shaving: old_ap_target:{old_ap_target} new ap_target:{ap_target} max: {import_limit-houseload} min:{-export_limit-houseload}")
    if old_ap_target != ap_target:
        _LOGGER.debug(
            f"peak shaving: old_ap_target:{old_ap_target} new ap_target:{ap_target} max: {import_limit-houseload_brut}"
        )
    res = [
        (
            "remotecontrol_power_control",
            power_control,
        ),
        (
            "remotecontrol_set_type",
            set_type,
        ),
        (
            "remotecontrol_active_power",
            ap_target,
        ),  # correct issues #488 , #492  used to be : max(min(ap_up, ap_target),   ap_lo), ),
        (
            "remotecontrol_reactive_power",
            max(min(reap_up, reactive_power), reap_lo),
        ),
        (
            "remotecontrol_duration",
            rc_duration,
        ),
    ]
    if power_control == "Disabled":
        autorepeat_stop(datadict, descr.key)
    _LOGGER.debug(f"Evaluated remotecontrol_trigger: corrected/clamped values: {res}")
    return res


def value_function_byteswapserial(initval, descr, datadict):
    if initval and not initval.startswith(("M", "X")):
        preswap = initval
        swapped = ""
        for pos in range(0, len(preswap), 2):
            swapped += preswap[pos + 1] + preswap[pos]
        return swapped
    return initval


def valuefunction_firmware_g3(initval, descr, datadict):
    return f"3.{initval}"


def valuefunction_firmware_g4(initval, descr, datadict):
    return f"1.{initval}"


def value_function_remotecontrol_autorepeat_remaining(initval, descr, datadict):
    return autorepeat_remaining(datadict, "remotecontrol_trigger", time())


def value_function_battery_power_charge(initval, descr, datadict):
    return datadict.get("battery_1_power_charge", 0) + datadict.get("battery_2_power_charge", 0)


def value_function_hardware_version_g1(initval, descr, datadict):
    return f"Gen1"


def value_function_hardware_version_g2(initval, descr, datadict):
    return f"Gen2"


def value_function_hardware_version_g3(initval, descr, datadict):
    return f"Gen3"


def value_function_hardware_version_g4(initval, descr, datadict):
    return f"Gen4"


def value_function_hardware_version_g5(initval, descr, datadict):
    return f"Gen5"


def value_function_house_load(initval, descr, datadict):
    return (
        datadict.get("inverter_power", 0)
        - datadict.get("measured_power", 0)
        + datadict.get("meter_2_measured_power", 0)
    )


def value_function_house_load_alt(initval, descr, datadict):
    return (
        datadict.get("pv_power_1", 0)
        + datadict.get("pv_power_2", 0)
        + datadict.get("pv_power_3", 0)
        - datadict.get("battery_power_charge", 0)
        - datadict.get("measured_power", 0)
        + datadict.get("meter_2_measured_power", 0)
    )


def value_function_software_version_g2(initval, descr, datadict):
    return f"DSP v2.{datadict.get('firmware_dsp')} ARM v2.{datadict.get('firmware_arm')}"


def value_function_software_version_g3(initval, descr, datadict):
    return f"DSP v3.{datadict.get('firmware_dsp')} ARM v3.{datadict.get('firmware_arm')}"


def value_function_software_version_g4(initval, descr, datadict):
    return f"DSP v1.{datadict.get('firmware_dsp')} ARM v1.{datadict.get('firmware_arm')}"


def value_function_software_version_g5(initval, descr, datadict):
    return (
        f"DSP {datadict.get('firmware_dsp')} ARM {datadict.get('firmware_arm_major')}.{datadict.get('firmware_arm')}"
    )


def value_function_software_version_air_g3(initval, descr, datadict):
    return f"DSP v2.{datadict.get('firmware_dsp')} ARM v1.{datadict.get('firmware_arm')}"


def value_function_software_version_air_g4(initval, descr, datadict):
    return f"DSP {datadict.get('firmware_dsp')} ARM {datadict.get('firmware_arm')}"


def value_function_battery_voltage_cell_difference(initval, descr, datadict):
    return datadict.get("cell_voltage_high", 0) - datadict.get("cell_voltage_low", 0)


# ================================= Button Declarations ============================================================

BUTTON_TYPES = [
    SolaxModbusButtonEntityDescription(
        name="Sync RTC",
        key="sync_rtc",
        register=0x00,
        allowedtypes=AC | HYBRID,
        write_method=WRITE_MULTI_MODBUS,
        icon="mdi:home-clock",
        value_function=value_function_sync_rtc,
    ),
    SolaxModbusButtonEntityDescription(
        name="Remotecontrol Trigger",
        key="remotecontrol_trigger",
        register=0x7C,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        write_method=WRITE_MULTI_MODBUS,
        icon="mdi:battery-clock",
        value_function=value_function_remotecontrol_recompute,
        autorepeat="remotecontrol_autorepeat_duration",
    ),
    SolaxModbusButtonEntityDescription(
        name="System On",
        key="system_on",
        register=0x1C,
        command=1,
        allowedtypes=AC | HYBRID,
        icon="mdi:power-on",
    ),
    SolaxModbusButtonEntityDescription(
        name="System Off",
        key="system_off",
        register=0x1C,
        command=0,
        allowedtypes=AC | HYBRID,
        icon="mdi:power-off",
    ),
    SolaxModbusButtonEntityDescription(
        name="Battery Awaken",
        key="battery_awaken",
        register=0x56,
        command=1,
        allowedtypes=AC | HYBRID,
        entity_registry_enabled_default=False,
        icon="mdi:battery-alert-variant",
    ),
    SolaxModbusButtonEntityDescription(
        name="Grid Export",
        key="grid_export",
        register=0x51,
        icon="mdi:home-export-outline",
        command=1,
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.CONFIG,
    ),
    #####
    #
    # Air Boost Mini MIC
    #
    #####
    SolaxModbusButtonEntityDescription(
        name="Sync RTC",
        key="sync_rtc",
        register=0x1015,
        allowedtypes=MIC,
        write_method=WRITE_MULTI_MODBUS,
        icon="mdi:home-clock",
        value_function=value_function_sync_rtc,
    ),
]

# ================================= Number Declarations ============================================================

MAX_CURRENTS = [
    ("L30E", 100),  # Gen2 X1 SK-TL
    ("U30", 50),  # Gen2 X1 SK-SU
    ("L37E", 100),  # Gen2 X1 SK-TL
    ("U37", 50),  # Gen2 X1 SK-SU
    ("L50E", 100),  # Gen2 X1 SK-TL
    ("U50", 50),  # Gen2 X1 SK-SU
    ("F3D", 35),  # RetroFit X3
    ("F3E", 25),  # RetroFit X3
    ("H3DE", 25),  # Gen3 X3 might need changing?
    ("H3E", 25),  # Gen3 X3
    ("H3LE", 25),  # Gen3 X3
    ("H3PE", 25),  # Gen3 X3 might need changing?
    ("H3UE", 25),  # Gen3 X3
    ("H43", 30),  # Gen4 X1 3 / 3.7kW
    ("H450", 30),  # Gen4 X1 5kW
    ("H449", 30),  # Gen4 X1 5kW
    ("H460", 30),  # Gen4 X1 6kW
    ("H475", 30),  # Gen4 X1 7.5kW
    ("PRE", 30),  # Gen4 X1 RetroFit
    ("PRI", 30),  # Gen4 X1 RetroFit
    ("H55", 50),  # Gen5 X1-IES
    ("H56", 50),  # Gen5 X1-IES
    ("H58", 50),  # Gen5 X1-IES
    ("F34", 30),  # Gen4 X3 RetroFit
    ("H31", 30),  # Gen4 X3 TIGO
    ("H34A", 30),  # Gen4 X3 A
    ("H34B", 30),  # Gen4 X3 B
    ("H34C", 30),  # Gen4 X3 C
    ("H34T", 25),  # Gen4 X3 T
    ("H35A", 50),  # Gen5 X3-IES A
    ("H3BC", 60),  # Gen5 X3 Ultra C
    ("H3BD", 60),  # Gen5 X3 Ultra D
    ("H3BF", 60),  # Gen5 X3 Ultra F
    ### All known Inverters added
]

MAX_EXPORT = [
    ("L30E", 3000),  # Gen2 X1 SK-TL
    ("U30", 3000),  # Gen2 X1 SK-SU
    ("L37E", 3700),  # Gen2 X1 SK-TL
    ("U37", 3700),  # Gen2 X1 SK-SU
    ("L50E", 4600),  # Gen2 X1 SK-TL
    ("U50", 4600),  # Gen2 X1 SK-SU
    ("H1E30", 5000),  # Gen3 X1
    ("H1E37", 5000),  # Gen3 X1
    ("H1E46", 6000),  # Gen3 X1
    ("H1E5", 6000),  # Gen3 X1
    ("H1I30", 5000),  # Gen3 X1
    ("H1I37", 5000),  # Gen3 X1
    ("H1I46", 6000),  # Gen3 X1
    ("H1I5", 6000),  # Gen3 X1
    ("HCC30", 5000),  # Gen3 X1
    ("HCC37", 5000),  # Gen3 X1
    ("HCC46", 6000),  # Gen3 X1
    ("HCC5", 6000),  # Gen3 X1
    ("HUE30", 5000),  # Gen3 X1
    ("HUE37", 5000),  # Gen3 X1
    ("HUE46", 6000),  # Gen3 X1
    ("HUE5", 6000),  # Gen3 X1
    ("XRE30", 5000),  # Gen3 X1
    ("XRE37", 5000),  # Gen3 X1
    ("XRE46", 6000),  # Gen3 X1
    ("XRE5", 6000),  # Gen3 X1
    ("F3D6", 9000),  # RetroFit X3
    ("F3D8", 12000),  # RetroFit X3
    ("F3D10", 15000),  # RetroFit X3
    ("F3D15", 16500),  # RetroFit X3
    ("F3E6", 9000),  # RetroFit X3
    ("F3E8", 12000),  # RetroFit X3
    ("F3E10", 15000),  # RetroFit X3
    ("F3E15", 16500),  # RetroFit X3
    ("H3DE05", 10000),  # Gen3 X3
    ("H3DE06", 12000),  # Gen3 X3
    ("H3DE08", 14000),  # Gen3 X3
    ("H3DE10", 15000),  # Gen3 X3
    ("H3E05", 10000),  # Gen3 X3
    ("H3E06", 12000),  # Gen3 X3
    ("H3E08", 14000),  # Gen3 X3
    ("H3E10", 15000),  # Gen3 X3
    ("H3LE05", 10000),  # Gen3 X3
    ("H3LE06", 12000),  # Gen3 X3
    ("H3LE08", 14000),  # Gen3 X3
    ("H3LE10", 15000),  # Gen3 X3
    ("H3PE05", 10000),  # Gen3 X3
    ("H3PE06", 12000),  # Gen3 X3
    ("H3PE08", 14000),  # Gen3 X3
    ("H3PE10", 15000),  # Gen3 X3
    ("H3UE05", 10000),  # Gen3 X3
    ("H3UE06", 12000),  # Gen3 X3
    ("H3UE08", 14000),  # Gen3 X3
    ("H3UE10", 15000),  # Gen3 X3
    ("H310", 15000),  # Gen4 X3 TIGO
    ("H312", 15000),  # Gen4 X3 TIGO
    ("H315", 16500),  # Gen4 X3 TIGO
    ("H430", 6300),  # Gen4 X1 3kW?
    ("H437", 7300),  # Gen4 X1 3.7kW
    ("H449", 9200),  # Gen4 X1 5kW
    ("H450", 9200),  # Gen4 X1 5kW
    ("H460", 9200),  # Gen4 X1 6kW
    ("H475", 9200),  # Gen4 X1 7.5kW
    ("PRE5", 9200),  # Gen4 X1 RetroFit 5kW
    ("PRI5", 9200),  # Gen4 X1 RetroFit 5kW
    ("F34", 10000),  # Gen4 X3 RetroFit
    ("H34A05", 7500),  # Gen4 X3 A
    ("H34A06", 6000),  # Gen4 X3 A
    ("H34A08", 12000),  # Gen4 X3 A
    ("H34A10", 15000),  # Gen4 X3 A
    ("H34A12", 15000),  # Gen4 X3 A
    ("H34A15", 16500),  # Gen4 X3 A
    ("H34B05", 7500),  # Gen4 X3 B
    ("H34B08", 12000),  # Gen4 X3 B
    ("H34B10", 15000),  # Gen4 X3 B
    ("H34B12", 15000),  # Gen4 X3 B
    ("H34B15", 16500),  # Gen4 X3 B
    ("H34C05", 7500),  # Gen4 X3 C
    ("H34C08", 12000),  # Gen4 X3 C
    ("H34C10", 15000),  # Gen4 X3 C
    ("H34C12", 15000),  # Gen4 X3 C
    ("H34C15", 16500),  # Gen4 X3 C
    ("H34T05", 7500),  # Gen4 X3 T
    ("H34T08", 12000),  # Gen4 X3 T
    ("H34T10", 15000),  # Gen4 X3 T
    ("H34T12", 15000),  # Gen4 X3 T
    ("H34T15", 16500),  # Gen4 X3 T
    ("H35A04", 4000),  # Gen5 X3-IES A
    ("H35A05", 5000),  # Gen5 X3-IES A
    ("H35A06", 6000),  # Gen5 X3-IES A
    ("H35A08", 8000),  # Gen5 X3-IES A
    ("H35A10", 10000),  # Gen5 X3-IES A
    ("H35A12", 12000),  # Gen5 X3-IES A
    ("H35A15", 15000),  # Gen5 X3-IES A
    ("H3BC15", 15000),  # Gen5 X3 Ultra C
    ("H3BC19", 19999),  # Gen5 X3 Ultra C
    ("H3BC20", 20000),  # Gen5 X3 Ultra C
    ("H3BC25", 25000),  # Gen5 X3 Ultra C
    ("H3BC30", 30000),  # Gen5 X3 Ultra C
    ("H3BD15", 15000),  # Gen5 X3 Ultra D
    ("H3BD19", 19999),  # Gen5 X3 Ultra D
    ("H3BD20", 20000),  # Gen5 X3 Ultra D
    ("H3BD25", 25000),  # Gen5 X3 Ultra D
    ("H3BD30", 30000),  # Gen5 X3 Ultra D
    ("H3BF15", 15000),  # Gen5 X3 Ultra F
    ("H3BF19", 19999),  # Gen5 X3 Ultra F
    ("H3BF20", 20000),  # Gen5 X3 Ultra F
    ("H3BF25", 25000),  # Gen5 X3 Ultra F
    ("H3BF30", 30000),  # Gen5 X3 Ultra F
    ### All known Inverters added
]

EXPORT_LIMIT_SCALE_EXCEPTIONS = [
    ("H4", 10),  # assuming all Gen4s
    ("H34", 10),  # assuming all Gen4s
    ("H3UE", 10),  # Issue #339, 922
    ("H4372A", 1),  # Issue #857
    ("H4502A", 1),  # Issue #857
    ("H4502T", 1),  # Issue #418
    ("H4602A", 1),  # Issue #882
    ("H3BD", 10),  # X3-Ultra
    ("H4752A", 1),
    ("H3BC", 10),
    ("H34B10H", 10),  # need return @jansidlo ,
    #    ('H1E', 10 ), # more specific entry comes last and wins
]

NUMBER_TYPES = [
    ###
    #
    # Data only number types
    #
    ###
    SolaxModbusNumberEntityDescription(
        name="Remotecontrol Active Power",
        key="remotecontrol_active_power",
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        native_min_value=-6000,
        native_max_value=30000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        initvalue=0,
        min_exceptions_minus=MAX_EXPORT,  # negative
        unit=REGISTER_S32,
        write_method=WRITE_DATA_LOCAL,
    ),
    SolaxModbusNumberEntityDescription(
        name="Remotecontrol Reactive Power",
        key="remotecontrol_reactive_power",
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        native_min_value=-4000,
        native_max_value=4000,
        native_step=100,
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=NumberDeviceClass.REACTIVE_POWER,
        initvalue=0,
        write_method=WRITE_DATA_LOCAL,
    ),
    SolaxModbusNumberEntityDescription(
        name="Remotecontrol Duration",
        key="remotecontrol_duration",
        unit=REGISTER_U16,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:home-clock",
        initvalue=20,  # seconds
        native_min_value=10,
        native_max_value=360,
        native_step=1,
        fmt="i",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        write_method=WRITE_DATA_LOCAL,
    ),
    SolaxModbusNumberEntityDescription(
        name="Remotecontrol Autorepeat Duration",
        key="remotecontrol_autorepeat_duration",
        unit=REGISTER_U16,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:home-clock",
        initvalue=0,  # seconds -
        native_min_value=0,
        native_max_value=28800,
        native_step=600,
        fmt="i",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        write_method=WRITE_DATA_LOCAL,
    ),
    SolaxModbusNumberEntityDescription(
        name="Remotecontrol Import Limit",
        key="remotecontrol_import_limit",
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        native_min_value=0,
        native_max_value=30000,  # overwritten by MAX_EXPORT
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        initvalue=20000,  # will be reduced to MAX
        unit=REGISTER_S32,
        write_method=WRITE_DATA_LOCAL,
    ),
    SolaxModbusNumberEntityDescription(
        name="Config Export Control Limit Readscale",
        key="config_export_control_limit_readscale",
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        native_min_value=0.1,
        native_max_value=10.0,
        native_step=0.1,
        entity_category=EntityCategory.DIAGNOSTIC,
        initvalue=1,
        entity_registry_enabled_default=False,
        write_method=WRITE_DATA_LOCAL,
    ),
    SolaxModbusNumberEntityDescription(
        name="Config Max Export",
        key="config_max_export",
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        native_min_value=600,
        native_max_value=60000,
        entity_category=EntityCategory.DIAGNOSTIC,
        initvalue=15000,
        native_step=200,
        entity_registry_enabled_default=False,
        write_method=WRITE_DATA_LOCAL,
    ),
    ###
    #
    #  Normal number types
    #
    ###
    SolaxModbusNumberEntityDescription(
        name="Backup Charge End Hours",
        key="backup_charge_end_h",
        register=0x97,
        fmt="i",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-clock",
    ),
    SolaxModbusNumberEntityDescription(
        name="Backup Charge End Minutes",
        key="backup_charge_end_m",
        register=0x98,
        fmt="i",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-clock",
    ),
    SolaxModbusNumberEntityDescription(
        name="Backup Charge Start Hours",
        key="backup_charge_start_h",
        register=0x95,
        fmt="i",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-clock",
    ),
    SolaxModbusNumberEntityDescription(
        name="Backup Charge Start Minutes",
        key="backup_charge_start_m",
        register=0x96,
        fmt="i",
        native_min_value=0,
        native_max_value=59,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-clock",
    ),
    SolaxModbusNumberEntityDescription(
        name="Backup Discharge Min SOC",
        key="backup_discharge_min_soc",
        register=0x67,
        fmt="i",
        native_min_value=15,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:battery-charging-low",
    ),
    SolaxModbusNumberEntityDescription(
        name="Backup Nightcharge Upper SOC",
        key="backup_nightcharge_upper_soc",
        register=0x66,
        fmt="i",
        native_min_value=30,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:battery-charging-high",
    ),
    SolaxModbusNumberEntityDescription(
        name="Battery Minimum Capacity",
        key="battery_minimum_capacity",
        register=0x20,
        fmt="i",
        native_min_value=10,
        native_max_value=99,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        state="battery_minimum_capacity",
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        icon="mdi:battery-sync",
    ),
    SolaxModbusNumberEntityDescription(
        name="Battery Minimum Capacity - Grid-tied",
        key="battery_minimum_capacity_gridtied",
        register=0xA7,
        fmt="i",
        native_min_value=10,
        native_max_value=99,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        state="battery_minimum_capacity_gridtied",
        allowedtypes=HYBRID | GEN3,
        icon="mdi:battery-sync",
    ),
    SolaxModbusNumberEntityDescription(
        name="Battery Charge Max Current",  # multiple versions depending on GEN
        key="battery_charge_max_current",
        register=0x24,
        fmt="f",
        native_min_value=0,
        native_max_value=20,  # default (new default, was 50)
        native_step=0.1,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        max_exceptions=MAX_CURRENTS,
        icon="mdi:current-dc",
    ),
    SolaxModbusNumberEntityDescription(
        name="Battery Charge Max Current",  # multiple versions depending on GEN
        key="battery_charge_max_current",
        register=0x24,
        fmt="f",
        native_min_value=0,
        native_max_value=20,  # default (new default, was 50)
        native_step=0.1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        allowedtypes=HYBRID | GEN2,
        max_exceptions=MAX_CURRENTS,
        icon="mdi:current-dc",
    ),
    SolaxModbusNumberEntityDescription(
        name="Battery Discharge Max Current",
        key="battery_discharge_max_current",
        register=0x25,
        fmt="f",
        scale=0.1,
        native_min_value=0,
        native_max_value=20,  # universal default
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        max_exceptions=MAX_CURRENTS,
        icon="mdi:current-dc",
    ),
    SolaxModbusNumberEntityDescription(
        name="Battery Discharge Max Current",
        key="battery_discharge_max_current",
        register=0x25,
        fmt="f",
        scale=0.01,
        native_min_value=0,
        native_max_value=20,  # universal default
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        allowedtypes=HYBRID | GEN2,
        max_exceptions=MAX_CURRENTS,
        icon="mdi:current-dc",
    ),
    SolaxModbusNumberEntityDescription(
        name="Consume Off Power",
        key="consume_off_power",
        register=0xB9,
        fmt="i",
        native_min_value=0,
        native_max_value=8000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=AC | HYBRID | GEN4,
    ),
    SolaxModbusNumberEntityDescription(
        name="Export Control User Limit",
        key="export_control_user_limit",
        register=0x42,
        fmt="i",
        native_min_value=0,
        native_max_value=2500,
        scale=1,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        read_scale_exceptions=EXPORT_LIMIT_SCALE_EXCEPTIONS,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        max_exceptions=MAX_EXPORT,
        icon="mdi:home-export-outline",
    ),
    SolaxModbusNumberEntityDescription(
        name="Generator Max Charge",
        key="generator_max_charge",
        register=0xC8,
        fmt="i",
        native_min_value=0,
        native_max_value=2500,
        scale=1,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        read_scale_exceptions=EXPORT_LIMIT_SCALE_EXCEPTIONS,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
        max_exceptions=MAX_EXPORT,
    ),
    SolaxModbusNumberEntityDescription(
        name="Feedin Discharge Min SOC",
        key="feedin_discharge_min_soc",
        register=0x65,
        fmt="i",
        native_min_value=10,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:battery-charging-low",
    ),
    SolaxModbusNumberEntityDescription(
        name="Feedin Nightcharge Upper SOC",
        key="feedin_nightcharge_upper_soc",
        register=0x64,
        fmt="i",
        native_min_value=10,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:battery-charging-high",
    ),
    SolaxModbusNumberEntityDescription(
        name="Main Breaker Current Limit",
        key="main_breaker_current_limit",
        register=0x71,
        fmt="i",
        native_min_value=10,
        native_max_value=250,
        native_step=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaxModbusNumberEntityDescription(
        name="Feedin On Power",
        key="feedin_on_power",
        register=0xB7,
        fmt="i",
        native_min_value=0,
        native_max_value=8000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=AC | HYBRID | GEN4,
    ),
    SolaxModbusNumberEntityDescription(
        name="ForceTime Period 1 Max Capacity",
        key="forcetime_period_1_max_capacity",
        register=0xA4,
        fmt="i",
        native_min_value=5,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN3,
        icon="mdi:battery-sync",
    ),
    SolaxModbusNumberEntityDescription(
        name="ForceTime Period 2 Max Capacity",
        key="forcetime_period_2_max_capacity",
        register=0xA5,
        fmt="i",
        native_min_value=5,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN3,
        icon="mdi:battery-sync",
    ),
    SolaxModbusNumberEntityDescription(
        name="Grid Export Limit",
        key="grid_export_limit",
        register=0x52,
        fmt="i",
        native_min_value=-6000,
        native_max_value=6000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=AC | HYBRID | GEN3,
        icon="mdi:home-export-outline",
    ),
    SolaxModbusNumberEntityDescription(
        name="Grid Export Limit",
        key="grid_export_limit",
        register=0x51,
        fmt="i",
        native_min_value=-5000,
        native_max_value=0,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=HYBRID | GEN2,
        icon="mdi:home-export-outline",
    ),
    SolaxModbusNumberEntityDescription(
        name="Maximum Per Day On",
        key="maximum_per_day_on",
        register=0xBC,
        fmt="i",
        native_min_value=5,
        native_max_value=1200,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
    ),
    SolaxModbusNumberEntityDescription(
        name="Minimum Per On Signal",
        key="minimum_per_on_signal",
        register=0xBB,
        fmt="i",
        native_min_value=5,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
    ),
    SolaxModbusNumberEntityDescription(
        name="Selfuse Backup SOC",
        key="selfuse_backup_soc",
        register=0xC5,
        fmt="i",
        native_min_value=10,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:battery-sync",
    ),
    SolaxModbusNumberEntityDescription(
        name="Selfuse Discharge Min SOC",
        key="selfuse_discharge_min_soc",
        register=0x61,
        fmt="i",
        native_min_value=10,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:battery-charging-low",
    ),
    SolaxModbusNumberEntityDescription(
        name="Selfuse Nightcharge Upper SOC",
        key="selfuse_nightcharge_upper_soc",
        register=0x63,
        fmt="i",
        native_min_value=10,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:battery-charging-high",
    ),
    SolaxModbusNumberEntityDescription(
        name="Switch Off SOC",
        key="switch_off_soc",
        register=0xBA,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
    ),
    SolaxModbusNumberEntityDescription(
        name="Switch On SOC",
        key="switch_on_soc",
        register=0xB8,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
    ),
    SolaxModbusNumberEntityDescription(
        name="Battery Charge Upper SOC",
        key="battery_charge_upper_soc",
        register=0xE0,
        fmt="i",
        native_min_value=10,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:battery-charging-high",
    ),
    SolaxModbusNumberEntityDescription(
        name="Generator Switch On SOC",
        key="generator_switch_on_soc",
        register=0xE4,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=HYBRID | GEN4 | GEN5 | DCB,
    ),
    SolaxModbusNumberEntityDescription(
        name="Generator Switch Off SOC",
        key="generator_switch_off_soc",
        register=0xE5,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=HYBRID | GEN4 | GEN5 | DCB,
    ),
    SolaxModbusNumberEntityDescription(
        name="PeakShaving Discharge Limit 1",
        key="peakshaving_discharge_limit_1",
        register=0xEE,
        fmt="i",
        native_min_value=0,
        native_max_value=15000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=HYBRID | GEN4 | GEN5,
    ),
    SolaxModbusNumberEntityDescription(
        name="PeakShaving Discharge Limit 2",
        key="peakshaving_discharge_limit_2",
        register=0xEF,
        fmt="i",
        native_min_value=0,
        native_max_value=15000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=HYBRID | GEN4 | GEN5,
    ),
    SolaxModbusNumberEntityDescription(
        name="PeakShaving Charge Limit",
        key="peakshaving_charge_limit",
        register=0xF1,
        fmt="i",
        native_min_value=0,
        native_max_value=7500,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=HYBRID | GEN4 | GEN5 | X1,
    ),
    SolaxModbusNumberEntityDescription(
        name="PeakShaving Charge Limit",
        key="peakshaving_charge_limit",
        register=0xF1,
        fmt="i",
        native_min_value=0,
        native_max_value=15000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=HYBRID | GEN4 | GEN5 | X3,
    ),
    SolaxModbusNumberEntityDescription(
        name="PeakShaving Max SOC",
        key="peakshaving_max_soc",
        register=0xF2,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=HYBRID | GEN4 | GEN5,
        icon="mdi:battery-charging-high",
    ),
    SolaxModbusNumberEntityDescription(
        name="PeakShaving Reserved SOC",
        key="peakshaving_reserved_soc",
        register=0xF3,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=HYBRID | GEN4 | GEN5,
    ),
    SolaxModbusNumberEntityDescription(
        name="Generator Charge SOC",
        key="generator_charge_soc",
        register=0x10A,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=HYBRID | GEN4 | DCB,
    ),
    SolaxModbusNumberEntityDescription(
        name="Generator Charge SOC",
        key="generator_charge_soc",
        register=0x10D,
        fmt="i",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=HYBRID | GEN5 | DCB,
    ),
    #####
    #
    # MIC
    #
    #####
    SolaxModbusNumberEntityDescription(
        name="Active Power Limit",
        key="active_power_limit",
        register=0x638,
        fmt="i",
        native_min_value=0,
        native_max_value=30000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=MIC | GEN2 | X3,
    ),
    SolaxModbusNumberEntityDescription(
        name="Export Power Limit",
        key="export_power_limit",
        register=0x65C,
        fmt="i",
        native_min_value=0,
        native_max_value=30000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=MIC | GEN2 | X3,
    ),
    SolaxModbusNumberEntityDescription(
        name="Active Power Limit",
        key="active_power_limit",
        register=0x669,
        fmt="i",
        native_min_value=0,
        native_max_value=30000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        allowedtypes=MIC | GEN4,
    ),
]

# ================================= Select Declarations ============================================================

SELECT_TYPES = [
    ###
    #
    #  Data only select types
    #
    ###
    SolaxModbusSelectEntityDescription(
        name="Remotecontrol Power Control",
        key="remotecontrol_power_control",
        unit=REGISTER_U16,
        write_method=WRITE_DATA_LOCAL,
        option_dict={
            0: "Disabled",
            1: "Enabled Power Control",  # battery charge level in absense of PV
            11: "Enabled Grid Control",  # computed variation of Power Control, grid import level in absense of PV
            12: "Enabled Battery Control",  # computed variation of Power Control, battery import without of PV
            110: "Enabled Self Use",  # variation of Grid Control with fixed target 0
            120: "Enabled Feedin Priority",  # variation of Battery Control with fixed target 0
            130: "Enabled No Discharge",  # missing HL from grid
            # 2: "Enabled Quantity Control",
            # 3: "Enabled SOC Target Control",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        initvalue="Disabled",
        icon="mdi:transmission-tower",
    ),
    SolaxModbusSelectEntityDescription(
        name="Remotecontrol Set Type",
        key="remotecontrol_set_type",
        unit=REGISTER_U16,
        write_method=WRITE_DATA_LOCAL,
        option_dict={
            1: "Set",
            2: "Update",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        initvalue="Set",
        icon="mdi:transmission-tower",
    ),
    ###
    #
    #  Normal select types
    #
    ###
    SolaxModbusSelectEntityDescription(
        name="Lock State",
        key="lock_state",
        register=0x0,
        option_dict={
            0: "Locked",
            2014: "Unlocked",
            6868: "Unlocked - Advanced",
        },
        allowedtypes=AC | HYBRID,
        icon="mdi:lock-question",
    ),
    SolaxModbusSelectEntityDescription(
        name="Allow Grid Charge",
        key="allow_grid_charge",
        register=0x40,
        option_dict={
            0: "Both Forbidden",
            1: "Period 1 Allowed",
            2: "Period 2 Allowed",
            3: "Both Allowed",
        },
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        icon="mdi:transmission-tower",
    ),
    SolaxModbusSelectEntityDescription(
        name="Backup Grid Charge",
        key="backup_gridcharge",
        register=0x94,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN3,
        icon="mdi:transmission-tower",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charge and Discharge Period2 Enable",
        key="charge_and_discharge_period2_enable",
        register=0x6C,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-clock",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger End Time 1",
        key="charger_end_time_1",
        register=0x27,
        option_dict=TIME_OPTIONS,
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger End Time 1",
        key="charger_end_time_1",
        register=0x69,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger End Time 2",
        key="charger_end_time_2",
        register=0x2B,
        option_dict=TIME_OPTIONS,
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger End Time 2",
        key="charger_end_time_2",
        register=0x6E,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger Start Time 1",
        key="charger_start_time_1",
        register=0x26,
        option_dict=TIME_OPTIONS,
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger Start Time 1",
        key="charger_start_time_1",
        register=0x68,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger Start Time 2",
        key="charger_start_time_2",
        register=0x2A,
        option_dict=TIME_OPTIONS,
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger Start Time 2",
        key="charger_start_time_2",
        register=0x6D,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        register=0x1F,
        option_dict={
            0: "Self Use Mode",
            1: "Force Time Use",
            2: "Back Up Mode",
        },
        allowedtypes=HYBRID | GEN2,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        register=0x1F,
        option_dict={
            0: "Self Use Mode",
            1: "Force Time Use",
            2: "Back Up Mode",
            3: "Feedin Priority",
        },
        allowedtypes=AC | HYBRID | GEN3,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        register=0x1F,
        option_dict={
            0: "Self Use Mode",
            1: "Feedin Priority",
            2: "Back Up Mode",
            3: "Manual Mode",
            4: "PeakShaving",
            5: "Smart Schedule",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Cloud Control",
        key="cloud_control",
        register=0x99,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        icon="mdi:cloud",
    ),
    SolaxModbusSelectEntityDescription(
        name="Discharge Cut Off Point Different",
        key="discharge_cut_off_point_different",
        register=0xA6,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Meter 1 Direction",
        key="meter_1_direction",
        register=0xAB,
        option_dict={
            0: "Positive",
            1: "Negative",
        },
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        icon="mdi:meter-electric",
    ),
    SolaxModbusSelectEntityDescription(
        name="Meter 2 Direction",
        key="meter_2_direction",
        register=0xAC,
        option_dict={
            0: "Positive",
            1: "Negative",
        },
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        icon="mdi:meter-electric",
    ),
    SolaxModbusSelectEntityDescription(
        name="Device Lock",
        key="device_lock",
        register=0xB5,
        option_dict={
            0: "Unlock",
            1: "Lock",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:lock",
    ),
    SolaxModbusSelectEntityDescription(
        name="Discharger End Time 1",
        key="discharger_end_time_1",
        register=0x29,
        option_dict=TIME_OPTIONS,
        allowedtypes=HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="Discharger End Time 1",
        key="discharger_end_time_1",
        register=0x6B,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="Discharger End Time 2",
        key="discharger_end_time_2",
        register=0x2D,
        option_dict=TIME_OPTIONS,
        allowedtypes=HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="Discharger End Time 2",
        key="discharger_end_time_2",
        register=0x70,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="Discharger Start Time 1",
        key="discharger_start_time_1",
        register=0x28,
        option_dict=TIME_OPTIONS,
        allowedtypes=HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="Discharger Start Time 1",
        key="discharger_start_time_1",
        register=0x6A,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="Discharger Start Time 2",
        key="discharger_start_time_2",
        register=0x2C,
        option_dict=TIME_OPTIONS,
        allowedtypes=HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="Discharger Start Time 2",
        key="discharger_start_time_2",
        register=0x6F,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="HotStandBy",
        key="hotstandby",
        register=0x99,
        option_dict={
            0: "Enabled",
            1: "Disabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Extend BMS Setting",
        key="extend_bms_setting",
        register=0x9A,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Export Duration",
        key="export_duration",
        register=0x9F,
        option_dict={
            4: "Default",
            900: "15 Minutes",
            1800: "30 Minutes",
            3600: "60 Minutes",
            5400: "90 Minutes",
            7200: "120 Minutes",
        },
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:home-export-outline",
    ),
    SolaxModbusSelectEntityDescription(
        name="Dry Contact Mode",
        key="dry_contact_mode",
        register=0xC3,
        option_dict={
            0: "Load Management",
            1: "Generator Control",
        },
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Control",
        key="generator_control",
        register=0xC7,
        option_dict={
            0: "Disabled",
            1: "ATS Control",
            2: "Dry Contact",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Battery Heating",
        key="battery_heating",
        register=0xCF,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:heating-coil",
    ),
    SolaxModbusSelectEntityDescription(
        name="Battery Heating Start Time 1",
        key="battery_heating_start_time_1",
        register=0xD0,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="Battery Heating End Time 1",
        key="battery_heating_end_time_1",
        register=0xD1,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="Battery Heating Start Time 2",
        key="battery_heating_start_time_2",
        register=0xD2,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="Battery Heating End Time 2",
        key="battery_heating_end_time_2",
        register=0xD3,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="Battery to EV Charger",
        key="battery_to_ev_charger",
        register=0xE1,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Start Method",
        key="generator_start_method",
        register=0xE3,
        option_dict={
            0: "Reference SOC",
            1: "Immediately",
        },
        allowedtypes=HYBRID | GEN4 | GEN5 | DCB,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Start Time 1",
        key="generator_start_time_1",
        register=0xE8,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | GEN5 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Stop Time 1",
        key="generator_stop_time_1",
        register=0xE9,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | GEN5 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="PeakShaving Discharge Start Time 1",
        key="peakshaving_discharge_start_time_1",
        register=0xEA,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="PeakShaving Discharge Stop Time 1",
        key="peakshaving_discharge_stop_time_1",
        register=0xEB,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="PeakShaving Discharge Start Time 2",
        key="peakshaving_discharge_start_time_2",
        register=0xEC,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaxModbusSelectEntityDescription(
        name="MPPT",
        key="mppt",
        register=0x48,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="PeakShaving Discharge Stop Time 2",
        key="peakshaving_discharge_stop_time_2",
        register=0xED,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaxModbusSelectEntityDescription(
        name="PeakShaving Charge from Grid",
        key="peakshaving_charge_from_grid",
        register=0xF0,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Shadow Fix Function Level PV3 (GMPPT)",
        key="shadow_fix3_enable",
        register=0xFC,
        option_dict={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=HYBRID | GEN5 | MPPT3,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="CT Cycle Detection",
        key="ct_cycle_detection",
        register=0xFD,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="EPS Mode without Battery",
        key="eps_mode_without_battery",
        register=0xFE,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | EPS,
        icon="mdi:dip-switch",
    ),
    #####
    #
    # Gen4 Generator Block
    #
    #####
    SolaxModbusSelectEntityDescription(
        name="Generator Charge Start Time 1",
        key="generator_charge_start_time_1",
        register=0x100,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Charge Stop Time 1",
        key="generator_charge_stop_time_1",
        register=0x101,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Discharge Start Time 1",
        key="generator_discharge_start_time_1",
        register=0x102,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Discharge Stop Time 1",
        key="generator_discharge_stop_time_1",
        register=0x103,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Time 2",
        key="generator_time_2",
        register=0x104,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=HYBRID | GEN4 | DCB,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Charge Start Time 2",
        key="generator_charge_start_time_2",
        register=0x105,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Charge Stop Time 2",
        key="generator_charge_stop_time_2",
        register=0x106,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Discharge Start Time 2",
        key="generator_discharge_start_time_2",
        register=0x107,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Discharge Stop Time 2",
        key="generator_discharge_stop_time_2",
        register=0x108,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Charge",
        key="generator_charge",
        register=0x109,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=HYBRID | GEN4 | DCB,
        icon="mdi:dip-switch",
    ),
    #####
    #
    # Gen5 Generator Block
    #
    #####
    SolaxModbusSelectEntityDescription(
        name="Generator Charge Start Time 1",
        key="generator_charge_start_time_1",
        register=0x103,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN5 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Charge Stop Time 1",
        key="generator_charge_stop_time_1",
        register=0x104,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN5 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Discharge Start Time 1",
        key="generator_discharge_start_time_1",
        register=0x105,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN5 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Discharge Stop Time 1",
        key="generator_discharge_stop_time_1",
        register=0x106,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN5 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Time 2",
        key="generator_time_2",
        register=0x107,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=HYBRID | GEN5 | DCB,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Charge Start Time 2",
        key="generator_charge_start_time_2",
        register=0x108,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN5 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Charge Stop Time 2",
        key="generator_charge_stop_time_2",
        register=0x109,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN5 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Discharge Start Time 2",
        key="generator_discharge_start_time_2",
        register=0x10A,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN5 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Discharge Stop Time 2",
        key="generator_discharge_stop_time_2",
        register=0x10B,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=HYBRID | GEN5 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:generator-stationary",
    ),
    SolaxModbusSelectEntityDescription(
        name="Generator Charge",
        key="generator_charge",
        register=0x10C,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=HYBRID | GEN5 | DCB,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Lease Mode",
        key="lease_mode",
        register=0xB4,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Manual Mode Select",
        key="manual_mode_select",
        register=0x20,
        option_dict={
            0: "Stop Charge and Discharge",
            1: "Force Charge",
            2: "Force Discharge",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Manual Mode Control",
        key="manual_mode_control",
        register=0xB6,
        option_dict={
            0: "Off",
            1: "On",
        },
        allowedtypes=AC | HYBRID | GEN4,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Parallel Setting",
        key="parallel_setting",
        register=0xC6,
        option_dict={
            0: "Free",
            1: "Master",
            2: "Slave",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Pgrid Bias",
        key="pgrid_bias",
        register=0x8D,
        option_dict={
            0: "Disabled",
            1: "Grid",
            2: "Inverter",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Shadow Fix Function Level PV2 (GMPPT)",
        key="shadow_fix_function_level_pv2_gmppt",
        register=0x98,
        option_dict={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Shadow Fix Function Level PV1 (GMPPT)",
        key="shadow_fix_function_level_pv1_gmppt",
        register=0x9C,
        option_dict={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Phase Power Balance X3",
        key="phase_power_balance_x3",
        register=0x9E,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Schedule",
        key="schedule",
        register=0xBD,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Selfuse Mode Backup",
        key="selfuse_mode_backup",
        register=0xC4,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Selfuse Night Charge Enable",
        key="selfuse_night_charge_enable",
        register=0x62,
        option_dict={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Work End Time 1",
        key="work_end_time_1",
        register=0xBF,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:home-clock",
    ),
    SolaxModbusSelectEntityDescription(
        name="Work End Time 2",
        key="work_end_time_2",
        register=0xC1,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:home-clock",
    ),
    SolaxModbusSelectEntityDescription(
        name="Work Mode",
        key="work_mode",
        register=0xC2,
        option_dict={
            0: "Disabled",
            1: "Manual",
            2: "Smart Save",
        },
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Work Start Time 1",
        key="work_start_time_1",
        register=0xBE,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:home-clock",
    ),
    SolaxModbusSelectEntityDescription(
        name="Work Start Time 2",
        key="work_start_time_2",
        register=0xC0,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:home-clock",
    ),
    #####
    #
    # MIC
    #
    #####
    SolaxModbusSelectEntityDescription(
        name="Lock State",
        key="lock_state",
        register=0x600,
        option_dict={
            0: "Locked",
            2014: "Unlocked",
            6868: "Unlocked - Advanced",
        },
        allowedtypes=MIC | GEN2 | GEN4,
        icon="mdi:lock-question",
    ),
    SolaxModbusSelectEntityDescription(
        name="MPPT Scan Mode PV1",
        key="mppt_scan_mode_pv1",
        register=0x601,
        option_dict={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=MIC | GEN4,
        icon="mdi:dip-switch",
    ),
    # SolaxModbusSelectEntityDescription(
    #    name = "MPPT",
    #    key = "mppt",
    #    register = 0x602,
    #    option_dict =  {
    #            0: "Enabled",
    #            1: "Disabled",
    #        },
    #    allowedtypes = HYBRID | GEN4,
    #    icon = "mdi:dip-switch",
    # ),
    SolaxModbusSelectEntityDescription(
        name="Q Curve",
        key="q-curve",
        register=0x62F,
        option_dict={
            0: "Off",
            1: "Over Excited",
            2: "Under Excited",
            3: "PF(p)",
            4: "Q(u)",
            5: "FixQPower",
        },
        allowedtypes=MIC | GEN4,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="Q Curve",
        key="q-curve",
        register=0x640,
        option_dict={
            0: "Off",
            1: "Over Excited",
            2: "Under Excited",
            3: "PF(p)",
            4: "Q(u)",
            5: "FixQPower",
        },
        allowedtypes=MIC | GEN2 | X3,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="MPPT Scan Mode PV2",
        key="mppt_scan_mode_pv2",
        register=0x6A6,
        option_dict={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=MIC | GEN4,
        icon="mdi:dip-switch",
    ),
    SolaxModbusSelectEntityDescription(
        name="MPPT Scan Mode PV3",
        key="mppt_scan_mode_pv3",
        register=0x6A7,
        option_dict={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=MIC | GEN4 | MPPT3,
        icon="mdi:dip-switch",
    ),
]

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES_MAIN: list[SolaXModbusSensorEntityDescription] = [
    #####
    #
    # Holding
    #
    #####
    SolaXModbusSensorEntityDescription(
        name="MateBox enabled",
        key="matebox_enabled",
        register=0x1E,
        scale={
            0: "disabled",
            1: "enabled",
        },
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN4 | GEN5,
        icon="mdi:dip-switch",
    ),
    SolaXModbusSensorEntityDescription(
        name="Safety code",
        key="safety_code",
        register=0x1D,
        scale={
            0: "VDE0126",
            1: "VDE4105",
            2: "AS 4777_2020_A",
            3: "G98/1",
            4: "C10/11",
            5: "TOR",
            6: "EN50438_NL",
            7: "Denmark2019_W",
            8: "CEB",
            9: "CEI021",
            10: "NRS097_2_1",
            11: "VDE0126_Gr_Is",
            12: "UTE_C15_712",
            13: "IEC61727",
            14: "G99/1",
            15: "VDE0126_Gr_Co",
            16: "Guyana",
            17: "C15_712_is_50",
            18: "C15_712_is_60",
            19: "New Zealand",
            20: "RD1699",
            21: "Chile",
            22: "EN50438_Ireland",
            23: "Philippines",
            24: "Czech PPDS_2020",
            25: "Czech_50438",
            26: "EN50549_EU",
            27: "Denmark2019_E",
            28: "RD1699_Island",
            29: "EN50549_Poland",
            30: "MEA_Thailand",
            31: "PEA_Thailand",
            32: "ACEA",
            33: "AS 4777_2020_B",
            34: "AS 4777_2020_C",
            35: "User Define",
            36: "EN50549_Romania",
        },
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN4 | GEN5 | X1,
        icon="mdi:dip-switch",
    ),
    SolaXModbusSensorEntityDescription(
        name="Safety code",
        key="safety_code",
        register=0x1D,
        scale={
            0: "VDE0126",
            1: "VDE4105",
            2: "AS 4777_2020_A",
            3: "G98/1",
            4: "C10/11",
            5: "TOR",
            6: "EN50438_NL",
            7: "Denmark2019_W",
            8: "CEB",
            9: "CEI021",
            10: "NRS097_2_1",
            11: "VDE0126_Gr_Is",
            12: "UTE_C15_712",
            13: "IEC61727",
            14: "G99/1",
            15: "VDE0126_Gr_Co",
            16: "Guyana",
            17: "C15_712_is_50",
            18: "C15_712_is_60",
            19: "New Zealand",
            20: "RD1699",
            21: "Chile",
            22: "Israel",
            23: "Czech_PPDS_2020",
            24: "RD1699_Island",
            25: "EN50549_Poland",
            26: "EN50438_Portugal",
            27: "PEA",
            28: "MEA",
            29: "EN50549_Sweden",
            30: "Philippines",
            31: "EN50438_Slovenia",
            32: "Denmark2019_E",
            33: "EN50549_EU",
            34: "AS 4777_2020_B",
            35: "AS 4777_2020_C",
            36: "User-Defined",
            37: "EN50549_Romania",
            38: "CEI016",
            39: "ACEA",
            40: "Chile2021 MT_R",
            41: "Chile2021 MT_U",
            42: "Czech_2022_2",
            43: "G98/NI-1",
            44: "G99/NI-1",
            45: "G99/NI_Type B",
            46: "CQC",
            47: "LA_3P_380",
            48: "LA_3P_220",
        },
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN4 | GEN5 | X3,
        icon="mdi:dip-switch",
    ),
    SolaXModbusSensorEntityDescription(
        key="firmware_dsp",
        register=0x7D,
        allowedtypes=AC | HYBRID,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter DSP hardware version",
        key="firmware_DSP_hardware_version",
        entity_registry_enabled_default=False,
        register=0x7E,
        allowedtypes=AC | HYBRID | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter DSP firmware major version",
        key="firmware_DSP_major_version",
        entity_registry_enabled_default=False,
        register=0x7F,
        allowedtypes=AC | HYBRID | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        key="firmware_arm_major",
        register=0x80,
        allowedtypes=AC | HYBRID | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Firmware Version Modbus TCP Major",
        key="firmwareversion_modbustcp_major",
        entity_registry_enabled_default=False,
        register=0x81,
        allowedtypes=AC | HYBRID | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="Firmware Version Modbus TCP Minor",
        key="firmwareversion_modbustcp_minor",
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN5,
        register=0x82,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        key="firmware_arm",
        register=0x83,
        allowedtypes=AC | HYBRID,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Bootloader Version",
        key="bootloader_version",
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN5,
        register=0x84,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="RTC",
        key="rtc",
        register=0x85,
        unit=REGISTER_WORDS,
        wordcount=6,
        scale=value_function_rtc,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:clock",
    ),
    SolaXModbusSensorEntityDescription(
        key="charger_use_mode",
        register=0x8B,
        scale={
            0: "Self Use Mode",
            1: "Force Time Use",
            2: "Back Up Mode",
            3: "Feedin Priority",
        },
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="charger_use_mode",
        register=0x8B,
        scale={
            0: "Self Use Mode",
            1: "Feedin Priority",
            2: "Back Up Mode",
            3: "Manual Mode",
            4: "PeakShaving",
            5: "Smart Schedule",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_minimum_capacity",
        register=0x8C,
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="manual_mode_select",
        register=0x8C,
        scale={
            0: "Stop Charge and Discharge",
            1: "Force Charge",
            2: "Force Discharge",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Type",
        key="battery_type",
        register=0x8D,
        scale={
            0: "Lead Acid",
            1: "Lithium",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:battery-unknown",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Charge Float Voltage",
        key="battery_charge_float_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x8E,
        scale=0.01,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Charge Float Voltage",
        key="battery_charge_float_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x8E,
        scale=0.1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Discharge Cut Off Voltage",
        key="battery_discharge_cut_off_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x8F,
        scale=0.01,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Discharge Cut Off Voltage",
        key="battery_discharge_cut_off_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x8F,
        scale=0.1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_charge_max_current",
        register=0x90,
        scale=0.01,
        allowedtypes=HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_charge_max_current",
        register=0x90,
        scale=0.1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_discharge_max_current",
        register=0x91,
        scale=0.01,
        allowedtypes=HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_discharge_max_current",
        register=0x91,
        scale=0.1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="charger_start_time_1",
        register=0x92,
        unit=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_gen23time,
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="selfuse_discharge_min_soc",
        register=0x93,
        unit=REGISTER_U8H,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="selfuse_night_charge_enable",
        register=0x93,
        unit=REGISTER_U8L,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="charger_end_time_1",
        register=0x94,
        unit=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_gen23time,
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="selfuse_nightcharge_upper_soc",
        register=0x94,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="feedin_nightcharge_upper_soc",
        register=0x95,
        unit=REGISTER_U8H,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="feedin_discharge_min_soc",
        register=0x95,
        unit=REGISTER_U8L,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="discharger_start_time_1",
        register=0x96,
        unit=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_gen23time,
        allowedtypes=HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="backup_nightcharge_upper_soc",
        register=0x96,
        unit=REGISTER_U8H,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="backup_discharge_min_soc",
        register=0x96,
        unit=REGISTER_U8L,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="charger_start_time_1",
        register=0x97,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="discharger_end_time_1",
        register=0x98,
        unit=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_gen23time,
        allowedtypes=HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="charger_end_time_1",
        register=0x98,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="discharger_start_time_1",
        register=0x99,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="charger_start_time_2",
        register=0x9A,
        unit=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_gen23time,
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="discharger_end_time_1",
        register=0x9A,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="charge_and_discharge_period2_enable",
        register=0x9B,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="charger_end_time_2",
        register=0x9C,
        unit=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_gen23time,
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="charger_start_time_2",
        register=0x9C,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="charger_end_time_2",
        register=0x9D,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="discharger_start_time_2",
        register=0x9E,
        unit=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_gen23time,
        allowedtypes=HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="discharger_start_time_2",
        register=0x9E,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="discharger_end_time_2",
        register=0x9F,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="discharger_end_time_2",
        register=0xA0,
        unit=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_gen23time,
        allowedtypes=HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="hotstandby",
        register=0xA1,
        scale={
            0: "Enabled",
            1: "Disabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="extend_bms_setting",
        register=0xA2,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_heating",
        register=0xA3,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_heating_start_time_1",
        register=0xA4,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_heating_end_time_1",
        register=0xA5,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_heating_start_time_2",
        register=0xA6,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_heating_end_time_2",
        register=0xA7,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Registration Code Pocket",
        key="registration_code_pocket",
        register=0xAA,
        unit=REGISTER_STR,
        wordcount=5,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="Registration Code Lan",
        key="registration_code_lan",
        register=0xAF,
        unit=REGISTER_STR,
        wordcount=5,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        key="pgrid_bias",
        register=0xB2,
        scale={
            0: "Disabled",
            1: "Grid",
            2: "Inverter",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="allow_grid_charge",
        register=0xB4,
        scale={
            0: "Both Forbidden",
            1: "Period 1 Allowed",
            2: "Period 2 Allowed",
            3: "Both Allowed",
        },
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Export Control Factory Limit",
        key="export_control_factory_limit",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0xB5,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        key="export_control_user_limit",
        register=0xB6,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        read_scale_exceptions=EXPORT_LIMIT_SCALE_EXCEPTIONS,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Mute",
        key="eps_mute",
        register=0xB7,
        scale={
            0: "Off",
            1: "On",
        },
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | EPS,
        icon="mdi:volume-mute",
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Set Frequency",
        key="eps_set_frequency",
        register=0xB8,
        scale={
            0: "50Hz",
            1: "60Hz",
        },
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Min SOC",
        key="eps_min_soc",
        native_unit_of_measurement=PERCENTAGE,
        register=0xB8,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS frequency",
        key="eps_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xB9,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Language",
        key="language",
        register=0xBB,
        scale={
            0: "English",
            1: "Deutsche",
            2: "Francais",
            3: "Polskie",
            4: "Espanol",
            5: "Portugues",
            6: "Italiano",
            7: "Ukrainian",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        icon="mdi:translate-variant",
    ),
    SolaXModbusSensorEntityDescription(
        key="mppt",
        register=0xBC,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Main Breaker Current Limit",
        key="main_breaker_current_limit",
        register=0xD7,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Install Capacity",
        key="battery_install_capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        entity_registry_enabled_default=False,
        register=0xE8,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:battery-sync",
        blacklist=("XRE",),
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Model Number",
        key="inverter_model_number",
        register=0xE9,
        unit=REGISTER_STR,
        wordcount=10,
        allowedtypes=AC | HYBRID | GEN3,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
        blacklist=("XRE",),
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Service",
        key="grid_service",
        register=0xFC,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=HYBRID | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        key="backup_gridcharge",
        register=0xFD,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Backup Charge Start",
        key="backup_charge_start",
        register=0xFE,
        unit=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_gen23time,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3,
        icon="mdi:clock-start",
    ),
    SolaXModbusSensorEntityDescription(
        name="Backup Charge End",
        key="backup_charge_end",
        register=0x100,
        unit=REGISTER_WORDS,
        wordcount=2,
        scale=value_function_gen23time,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3,
        icon="mdi:clock-end",
    ),
    SolaXModbusSensorEntityDescription(
        name="wAS4777 Power Manager",
        key="was4777_power_manager",
        register=0x102,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="DRM Function Enable",
        key="drm_function_enable",
        register=0x102,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        key="cloud_control",
        register=0x103,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="CT Type",
        key="ct_type",
        register=0x103,
        scale={
            0: "100A",
            1: "200A",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Global MPPT Function",
        key="global_mppt_function",
        register=0x104,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN3,
        icon="mdi:sun-compass",
    ),
    SolaXModbusSensorEntityDescription(
        key="shadow_fix_function_level_pv1_gmppt",
        register=0x104,
        scale={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Service X3",
        key="grid_service_x3",
        register=0x105,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN3 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        key="phase_power_balance_x3",
        register=0x106,
        scale={0: "Disabled", 1: "Enabled"},
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter Function",
        key="meter_function",
        register=0x108,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:meter-electric",
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 1 id",
        key="meter_1_id",
        register=0x109,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:meter-electric",
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 2 id",
        key="meter_2_id",
        register=0x10A,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:meter-electric",
    ),
    SolaXModbusSensorEntityDescription(
        key="export_duration",
        register=0x10B,
        scale={
            4: "Default",
            900: "15 Minutes",
            1800: "30 Minutes",
            3600: "60 Minutes",
            5400: "90 Minutes",
            7200: "120 Minutes",
        },
        allowedtypes=AC | HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="forcetime_period_1_max_capacity",
        register=0x10C,
        allowedtypes=AC | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Auto Restart",
        key="eps_auto_restart",
        register=0x10C,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=HYBRID | GEN3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        key="forcetime_period_2_max_capacity",
        register=0x10D,
        allowedtypes=AC | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="CT Meter Setting",
        key="ct_meter_setting",
        register=0x10E,
        scale={
            0: "Meter",
            1: "CT",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | GEN3,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:meter-electric",
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_charge_upper_soc",
        register=0x10E,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_to_ev_charger",
        register=0x10F,
        scale={
            1: "Enabled",
            0: "Disabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="forcetime_period_1_max_capacity",
        register=0x10F,
        allowedtypes=HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="forcetime_period_2_max_capacity",
        register=0x110,
        allowedtypes=HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="discharge_cut_off_point_different",
        register=0x111,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="battery_minimum_capacity_gridtied",
        register=0x112,
        allowedtypes=HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharge Cut Off Voltage Grid Mode",
        key="discharge_cut_off_voltage_grid_mode",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x113,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Earth Detect X3",
        key="earth_detect_x3",
        register=0x114,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN3 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        key="shadow_fix_function_level_pv2_gmppt",
        register=0x114,
        scale={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="CT Meter Setting",
        key="ct_meter_setting",
        register=0x115,
        scale={
            0: "Meter",
            1: "CT",
        },
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:meter-electric",
    ),
    SolaXModbusSensorEntityDescription(
        key="meter_1_direction",
        register=0x116,
        scale={
            0: "Positive",
            1: "Negative",
        },
        allowedtypes=AC | HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="meter_2_direction",
        register=0x117,
        scale={
            0: "Positive",
            1: "Negative",
        },
        allowedtypes=AC | HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="FVRT Function",
        key="fvrt_function",
        register=0x116,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="FVRT Vac Upper",
        key="fvrt_vac_upper",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x117,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="FVRT Vac Lower",
        key="fvrt_vac_lower",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x118,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Connection Mode",
        key="pv_connection_mode",
        register=0x11B,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Shut Down",
        key="shut_down",
        register=0x11C,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Micro Grid",
        key="micro_grid",
        register=0x11D,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        key="selfuse_mode_backup",
        register=0x11E,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="selfuse_backup_soc",
        native_unit_of_measurement=PERCENTAGE,
        register=0x11F,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="lease_mode",
        register=0x120,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="device_lock",
        register=0x121,
        scale={
            0: "Unlock",
            1: "Lock",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    ####
    #
    # Values need finding on Gen 5
    #
    ###
    SolaXModbusSensorEntityDescription(
        key="manual_mode_control",
        register=0x122,
        scale={
            0: "Off",
            1: "On",
        },
        allowedtypes=AC | HYBRID | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="switch_on_soc",
        register=0x124,
        allowedtypes=AC | HYBRID | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="consume_off_power",
        register=0x125,
        allowedtypes=AC | HYBRID | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="switch_off_soc",
        register=0x126,
        allowedtypes=AC | HYBRID | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="minimum_per_on_signal",
        register=0x127,
        allowedtypes=AC | HYBRID | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="maximum_per_day_on",
        register=0x128,
        allowedtypes=AC | HYBRID | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="schedule",
        register=0x129,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="work_start_time_1",
        register=0x12A,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Work Stop Time 1",
        key="work_stop_time_1",
        register=0x12B,
        scale=value_function_gen4time,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        icon="mdi:home-clock",
    ),
    SolaXModbusSensorEntityDescription(
        key="work_start_time_2",
        register=0x12C,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Work Stop Time 2",
        key="work_stop_time_2",
        register=0x12D,
        scale=value_function_gen4time,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        icon="mdi:home-clock",
    ),
    SolaXModbusSensorEntityDescription(
        key="work_mode",
        register=0x12E,
        scale={0: "Disabled", 1: "Manua;", 2: "Smart Save"},
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="dry_contact_mode",
        register=0x12F,
        scale={
            0: "Load Management",
            1: "Generator Control",
        },
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    #####
    #
    # End of block where Values need finding on Gen 5
    #
    #####
    SolaXModbusSensorEntityDescription(
        key="parallel_setting",
        register=0x130,
        scale={0: "Free", 1: "Master", 2: "Slave"},
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_control",
        register=0x131,
        scale={
            0: "Disabled",
            1: "ATS Control",
            2: "Dry Contact",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_max_charge",
        register=0x132,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_start_method",
        register=0x140,
        scale={
            0: "Reference SOC",
            1: "Immediately",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_switch_on_soc",
        register=0x141,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_switch_off_soc",
        register=0x142,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Generator Max Run Time",
        key="generator_max_run_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        register=0x143,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
    ),
    SolaXModbusSensorEntityDescription(
        name="Generator Min Rest Time",
        key="generator_min_rest_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        register=0x145,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_start_time_1",
        register=0x146,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_stop_time_1",
        register=0x147,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Generator Min Power",
        key="generator_min_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x148,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | DCB,
    ),
    SolaXModbusSensorEntityDescription(
        key="peakshaving_discharge_start_time_1",
        register=0x14F,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="peakshaving_discharge_stop_time_1",
        register=0x150,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="peakshaving_discharge_start_time_2",
        register=0x151,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="peakshaving_discharge_stop_time_2",
        register=0x152,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="peakshaving_discharge_limit_1",
        register=0x153,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="peakshaving_discharge_limit_2",
        register=0x154,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="peakshaving_charge_from_grid",
        register=0x155,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="peakshaving_charge_limit",
        register=0x156,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="peakshaving_max_soc",
        register=0x157,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="peakshaving_reserved_soc",
        register=0x158,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="shadow_fix3_enable",
        register=0x15F,
        scale={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=HYBRID | GEN5 | MPPT3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="ct_cycle_detection",
        register=0x160,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="eps_mode_without_battery",
        register=0x161,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | EPS,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge_start_time_1",
        register=0x162,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge_stop_time_1",
        register=0x163,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_discharge_start_time_1",
        register=0x164,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_discharge_stop_time_1",
        register=0x165,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_time_2",
        register=0x166,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge_start_time_2",
        register=0x167,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge_stop_time_2",
        register=0x168,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_discharge_start_time_2",
        register=0x169,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_discharge_stop_time_2",
        register=0x16A,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge",
        register=0x16B,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge_soc",
        register=0x16C,
        allowedtypes=AC | HYBRID | GEN4 | DCB,
        internal=True,
    ),
    #####
    #
    # Gen5 Block
    #
    # Differs from Gen4 at 0x121 to 0x12F
    #
    #####
    SolaXModbusSensorEntityDescription(
        key="generator_charge_start_time_1",
        register=0x124,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge_stop_time_1",
        register=0x125,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_discharge_start_time_1",
        register=0x126,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_discharge_stop_time_1",
        register=0x127,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_time_2",
        register=0x128,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge_start_time_2",
        register=0x129,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge_stop_time_2",
        register=0x12A,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_discharge_start_time_2",
        register=0x12B,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_discharge_stop_time_2",
        register=0x12C,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge",
        register=0x12D,
        scale={
            0: "Disabled",
            1: "Enabled",
        },
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="generator_charge_soc",
        register=0x12E,
        allowedtypes=AC | HYBRID | GEN5 | DCB,
        internal=True,
    ),
    #####
    #
    # Input
    #
    #####
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage",
        key="inverter_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x0,
        scale=0.1,
        register_type=REG_INPUT,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current",
        key="inverter_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1,
        scale=0.1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power",
        key="inverter_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x3,
        scale=0.1,
        register_type=REG_INPUT,
        rounding=1,
        allowedtypes=HYBRID,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x4,
        scale=0.1,
        register_type=REG_INPUT,
        rounding=1,
        allowedtypes=HYBRID,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x5,
        scale=0.1,
        register_type=REG_INPUT,
        allowedtypes=HYBRID,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x6,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency",
        key="inverter_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x7,
        scale=0.01,
        rounding=2,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x8,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x8,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x9,
        scale={
            0: "Waiting",
            1: "Checking",
            2: "Normal Mode",
            3: "Off Mode",
            4: "Permanent Fault Mode",
            5: "Update Mode",
            6: "EPS Check Mode",
            7: "EPS Mode",
            8: "Self Test",
            9: "Idle Mode",
            10: "Standby",
        },
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN2 | GEN3,
        icon="mdi:run",
    ),
    SolaXModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x9,
        scale={
            0: "Waiting",
            1: "Checking",
            2: "Normal Mode",
            3: "Fault",
            4: "Permanent Fault Mode",
            5: "Update Mode",
            6: "Off-Grid Waiting",
            7: "Off-Grid",
            8: "Self Test",
            9: "Idle Mode",
            10: "Standby",
            20: "Normal (R)",
        },
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:run",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xA,
        register_type=REG_INPUT,
        allowedtypes=HYBRID,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xB,
        register_type=REG_INPUT,
        allowedtypes=HYBRID,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Time Count Down",
        key="time_count_down",
        entity_registry_enabled_default=False,
        register=0x13,
        scale=0.001,
        rounding=0,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        icon="mdi:timer",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Voltage Charge",
        key="battery_voltage_charge",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x14,
        scale=0.01,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Voltage Charge",
        key="battery_voltage_charge",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x14,
        scale=0.1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery 1 Voltage Charge",
        key="battery_1_voltage_charge",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x14,
        scale=0.1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Current Charge",
        key="battery_current_charge",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x15,
        scale=0.01,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | GEN2,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Current Charge",
        key="battery_current_charge",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x15,
        scale=0.1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery 1 Current Charge",
        key="battery_1_current_charge",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x15,
        scale=0.1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN5,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Power Charge",
        key="battery_power_charge",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x16,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4,
        icon="mdi:battery-charging",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery 1 Power Charge",
        key="battery_1_power_charge",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x16,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN5,
        icon="mdi:battery-charging",
    ),
    SolaXModbusSensorEntityDescription(
        name="Temperature Board Charge",
        key="temperature_board_charge",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x17,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | GEN2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="BMS Connect State",
        key="bms_connect_state",
        entity_registry_enabled_default=False,
        register=0x17,
        scale={
            0: "Disconnected",
            1: "Connected",
        },
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        icon="mdi:state-machine",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Temperature",
        key="battery_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x18,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery 1 Temperature",
        key="battery_1_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x18,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Temperature Boost Charge",
        key="temperature_boost_charge",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x19,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | GEN2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Status",
        key="grid_status",
        entity_registry_enabled_default=False,
        register=0x1A,
        scale={
            0: "OnGrid",
            1: "OffGrid",
        },
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:transmission-tower",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Capacity",
        key="battery_capacity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1C,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery 1 Capacity",
        key="battery_1_capacity_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x1C,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Output Energy Total",  # Need revisit these
        key="battery_output_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-arrow-down",
        register=0x1D,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,  # REGISTER_ULSB16MSB16,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Input Energy Total",
        key="battery_input_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-arrow-up",
        register=0x20,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,  # REGISTER_ULSB16MSB16,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Output Energy Today",  # Need revisit this
        key="battery_output_energy_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-arrow-down",
        register=0x20,
        register_type=REG_INPUT,
        unit=REGISTER_U16,
        scale=0.1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Input Energy Total",
        key="battery_input_energy_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-arrow-up",
        register=0x21,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U32,  # REGISTER_ULSB16MSB16,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Package Number",
        key="battery_package_number",
        register=0x22,
        register_type=REG_INPUT,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery State of Health",
        key="battery_state_of_health",
        icon="mdi:battery-heart",
        register=0x23,
        register_type=REG_INPUT,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        allowedtypes=HYBRID | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Input Energy Today",  # Need revisit this
        key="battery_input_energy_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-arrow-up",
        register=0x23,
        register_type=REG_INPUT,
        scale=0.1,
        unit=REGISTER_U16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="BMS Charge Max Current",
        key="bms_charge_max_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
        register=0x24,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="BMS Discharge Max Current",
        key="bms_discharge_max_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
        register=0x25,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="BMS Battery Capacity",
        key="bms_battery_capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        entity_registry_enabled_default=False,
        register=0x26,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power",
        key="measured_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x46,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Export Total",
        key="grid_export_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        register=0x48,
        register_type=REG_INPUT,
        unit=REGISTER_S32,  # Shouldn't this be UINT?
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Import Total",
        key="grid_import_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        register=0x4A,
        unit=REGISTER_U32,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        icon="mdi:home-import-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Voltage",
        key="eps_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x4C,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | X1 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Current",
        key="eps_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x4D,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | X1 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power",
        key="eps_power",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        register=0x4E,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | X1 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Frequency",
        key="eps_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x4F,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Solar Energy",
        key="today_s_solar_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x50,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        scale=0.1,
        rounding=2,
        allowedtypes=HYBRID | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Yield",
        key="today_s_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x50,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=2,  # GEN4 | GEN5 might be 1
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Solar Energy",
        key="total_solar_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        register=0x52,
        scale=0.001,
        rounding=2,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=HYBRID | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Yield",
        key="total_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x52,
        scale=0.1,
        rounding=2,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        key="lock_state",
        register=0x54,
        scale={
            0: "Locked",
            1: "Unlocked",
            2: "Unlocked - Advanced",
        },
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Bus Volt",
        key="bus_volt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_registry_enabled_default=False,
        register=0x66,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="DC Fault Val",
        key="dc_fault_val",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_registry_enabled_default=False,
        register=0x67,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Overload Fault Val",
        key="overload_fault_val",
        register=0x68,
        register_type=REG_INPUT,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        icon="mdi:alert-circle",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Volt Fault Val",
        key="battery_volt_fault_val",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x69,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L1",
        key="inverter_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x6A,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L1",
        key="inverter_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x6B,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power L1",
        key="inverter_power_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x6C,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency L1",
        key="inverter_frequency_l1",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x6D,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L2",
        key="inverter_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x6E,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L2",
        key="inverter_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x6F,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Yield",
        key="today_s_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x70,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=2,
        allowedtypes=HYBRID | GEN2,
        blacklist=("U50EC",),
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power L2",
        key="inverter_power_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x70,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency L2",
        key="inverter_frequency_l2",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x71,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L3",
        key="inverter_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x72,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L3",
        key="inverter_current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x73,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power L3",
        key="inverter_power_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x74,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency L3",
        key="inverter_frequency_l3",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x75,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Voltage L1",
        key="eps_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x76,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Current L1",
        key="eps_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x77,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power Active L1",
        key="eps_power_active_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x78,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power L1",
        key="eps_power_l1",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        register=0x79,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Voltage L2",
        key="eps_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x7A,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Current L2",
        key="eps_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x7B,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power Active L2",
        key="eps_power_active_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x7C,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power L2",
        key="eps_power_l2",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        register=0x7D,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Voltage L3",
        key="eps_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x7E,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Current L3",
        key="eps_current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x7F,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power Active L3",
        key="eps_power_active_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x80,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power L3",
        key="eps_power_l3",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        register=0x81,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power L1",
        key="measured_power_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x82,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power L2",
        key="measured_power_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x84,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power L3",
        key="measured_power_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x86,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=HYBRID | GEN3 | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Mode Runtime",
        key="grid_mode_runtime",
        native_unit_of_measurement=UnitOfTime.HOURS,
        register=0x88,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
        icon="mdi:timer",
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Mode Runtime",
        key="eps_mode_runtime",
        native_unit_of_measurement=UnitOfTime.HOURS,
        register=0x8A,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3 | EPS,
        icon="mdi:timer",
    ),
    SolaXModbusSensorEntityDescription(
        name="Normal Runtime",
        key="normal_runtime",
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_registry_enabled_default=False,
        register=0x8C,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3,
        icon="mdi:timer",
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Yield Total",
        key="eps_yield_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x8E,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID | GEN2 | GEN4 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Yield Total",
        key="eps_yield_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x8E,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID | GEN3 | GEN5 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Yield Today",
        key="eps_yield_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x90,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="E Charge Today",
        key="e_charge_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        register=0x91,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=2,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="E Charge Total",
        key="e_charge_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        register=0x92,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=2,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Solar Energy",
        key="total_solar_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x94,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Solar Energy",
        key="today_s_solar_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x96,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Export Energy",
        key="today_s_export_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        register=0x98,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Import Energy",
        key="today_s_import_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x9A,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        icon="mdi:home-import-outline",
    ),
    SolaXModbusSensorEntityDescription(
        key="grid_export_limit",
        register=0x9C,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 2 Measured Power",
        key="meter_2_measured_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xA8,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 2 Export Total",
        key="meter_2_export_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0xAA,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        entity_registry_enabled_default=False,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 2 Import Total",
        key="meter_2_import_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0xAC,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        entity_registry_enabled_default=False,
        icon="mdi:home-import-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 2 Export Today",
        key="meter_2_export_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0xAE,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        entity_registry_enabled_default=False,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 2 Import Today",
        key="meter_2_import_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0xB0,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        entity_registry_enabled_default=False,
        icon="mdi:home-import-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 2 Measured Power L1",
        key="meter_2_measured_power_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xB2,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
        entity_registry_enabled_default=False,
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 2 Measured Power L2",
        key="meter_2_measured_power_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xB4,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
        entity_registry_enabled_default=False,
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 2 Measured Power L3",
        key="meter_2_measured_power_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xB6,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | X3,
        entity_registry_enabled_default=False,
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 1 Communication State",
        key="meter_1_communication_state",
        register=0xB8,
        register_type=REG_INPUT,
        scale={
            0: "Communication Error",
            1: "Normal",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Meter 2 Communication State",
        key="meter_2_communication_state",
        register=0xB9,
        register_type=REG_INPUT,
        scale={
            0: "Communication Error",
            1: "Normal",
        },
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Temp High",
        key="battery_temp_high",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        register=0xBA,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Temp Low",
        key="battery_temp_low",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        register=0xBB,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Cell Voltage High",
        key="cell_voltage_high",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xBC,
        register_type=REG_INPUT,
        scale=0.001,
        rounding=3,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Cell Voltage Low",
        key="cell_voltage_low",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xBD,
        register_type=REG_INPUT,
        scale=0.001,
        rounding=3,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Voltage Cell Difference",
        key="battery_voltage_cell_difference",
        value_function=value_function_battery_voltage_cell_difference,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        rounding=3,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery State of Health",
        key="battery_soh",
        icon="mdi:battery-heart",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xBF,
        register_type=REG_INPUT,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0xC8,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Voltage",
        key="grid_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xC9,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Voltage L1",
        key="grid_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xCA,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Voltage L2",
        key="grid_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xCB,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Voltage L3",
        key="grid_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xCC,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        entity_registry_enabled_default=False,
        allowedtypes=AC | HYBRID | GEN4 | GEN5 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Modbus Power Control",
        key="modbus_power_control",
        register=0x100,
        register_type=REG_INPUT,
        scale={
            0: "Disabled",
            1: "Enabled Power Control",
            2: "Enabled Quantity Control",
            3: "Enabled SOC Target Control",
            4: "Push Power - P/N Mode",
            5: "Push Power - Zero Mode",
            6: "Self Consume - C/D Mode",
            7: "Self Consume - Charge Only Mode",
        },
        icon="mdi:dip-switch",
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Target Finish Flag",
        key="target_finish_flag",
        register=0x101,
        register_type=REG_INPUT,
        scale={
            0: "Unfinished",
            1: "Finished",
        },
        icon="mdi:bullseye-arrow",
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Active Power Target",
        key="active_power_target",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x102,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Reactive Power Target",
        key="reactive_power_target",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x104,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Active Power Real",
        key="active_power_real",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x106,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Reactive Power Real",
        key="reactive_power_real",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x108,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Active Power Upper",
        key="active_power_upper",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x10A,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Active Power Lower",
        key="active_power_lower",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x10C,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Min Esc Voltage",
        key="eps_min_esc_voltage",
        register=0x10D,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        allowedtypes=HYBRID | GEN3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Min Esc SOC",
        key="eps_min_esc_soc",
        register=0x10E,
        native_unit_of_measurement=PERCENTAGE,
        allowedtypes=HYBRID | GEN3 | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="Reactive Power Upper",
        key="reactive_power_upper",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x10E,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Reactive Power Lower",
        key="reactive_power_lower",
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x110,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charge Discharge Power",
        key="charge_discharge_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        register=0x114,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Chargeable Battery Capacity",
        key="chargeable_battery_capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        entity_registry_enabled_default=False,
        register=0x116,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Remaining Battery Capacity",
        key="remaining_battery_capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        register=0x118,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x122,
        scale=0.1,
        register_type=REG_INPUT,
        rounding=1,
        allowedtypes=HYBRID | GEN5 | MPPT3,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x123,
        scale=0.1,
        register_type=REG_INPUT,
        allowedtypes=HYBRID | GEN5 | MPPT3,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 3",
        key="pv_power_3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x124,
        register_type=REG_INPUT,
        allowedtypes=HYBRID | GEN5 | MPPT3,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery 2 Voltage Charge",
        key="battery_2_voltage_charge",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x127,
        scale=0.1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery 2 Current Charge",
        key="battery_2_current_charge",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x128,
        scale=0.1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | GEN5,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery 2 Power Charge",
        key="battery_2_power_charge",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x129,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=HYBRID | GEN5,
        icon="mdi:battery-charging",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery 2 Capacity",
        key="battery_2_capacity_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x12D,
        register_type=REG_INPUT,
        allowedtypes=HYBRID | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Total Capacity",
        key="battery_total_capacity_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x12E,
        register_type=REG_INPUT,
        allowedtypes=HYBRID | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery 2 Temperature",
        key="battery_2_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x132,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN5,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        key="feedin_on_power",
        register=0x123,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        internal=True,
    ),
    #####
    #
    # Input - Parallel Mode
    #
    #####
    SolaXModbusSensorEntityDescription(
        name="PM Inverter Count",
        key="pm_inverter_count",
        register=0x1DD,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM ActivePower L1",
        key="pm_activepower_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x1E0,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM ActivePower L2",
        key="pm_activepower_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x1E2,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM ActivePower L3",
        key="pm_activepower_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x1E4,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM Reactive or ApparentPower L1",
        key="pm_reactive_or_apparentpower_l1",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x1E6,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM Reactive or ApparentPower L2",
        key="pm_reactive_or_apparentpower_l2",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x1E8,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM Reactive or ApparentPower L3",
        key="pm_reactive_or_apparentpower_l3",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x1EA,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM Inverter Current L1",
        key="pm__current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1EC,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM Inverter Current L2",
        key="pm__current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1EE,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM Inverter Current L3",
        key="pm__current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1F0,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM PV Power 1",
        key="pm_pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1F2,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM PV Power 2",
        key="pm_pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1F4,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM PV Current 1",
        key="pm_pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1F6,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM PV Current 2",
        key="pm_pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1F8,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM Battery Power Charge",
        key="pm_battery_power_charge",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1FA,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:battery-charging",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM Battery Current Charge",
        key="pm_battery_current_charge",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1FC,
        scale=0.01,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:current-dc",
    ),
    # PM I2 Inverter
    SolaXModbusSensorEntityDescription(
        name="PM I2 ActivePower L1",
        key="pm_i2_activepower_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x204,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 ActivePower L2",
        key="pm_i2_activepower_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x205,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 ActivePower L3",
        key="pm_i2_activepower_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x206,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 Reactive or ApparentPower L1",
        key="pm_i2_reactive_or_apparentpower_l1",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x207,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 Reactive or ApparentPower L2",
        key="pm_i2_reactive_or_apparentpower_l2",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x208,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 Reactive or ApparentPower L3",
        key="pm_i2_reactive_or_apparentpower_l3",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x209,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 Inverter Current L1",
        key="pm_i2_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x20A,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 Inverter Current L2",
        key="pm_i2_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x20B,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 Inverter Current L3",
        key="pm_i2_current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x20C,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 PV Power 1",
        key="pm_i2_pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x20D,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 PV Power 2",
        key="pm_i2_pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x20E,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 PV Voltage 1",
        key="pm_i2_pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x20F,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 PV Voltage 2",
        key="pm_i2_pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x210,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 PV Current 1",
        key="pm_i2_pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x211,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 PV Current 2",
        key="pm_i2_pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x212,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 Battery Power Charge",
        key="pm_i2_battery_power_charge",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x213,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:battery-charging",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 Battery Voltage Charge",
        key="pm_i2_battery_voltage_charge",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x214,
        scale=0.1,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 Battery Current Charge",
        key="pm_i2_battery_current_charge",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x215,
        scale=0.1,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I2 Battery Capacity",
        key="pm_i2_battery_capacity_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x219,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    # PM I3 Inverter
    SolaXModbusSensorEntityDescription(
        name="PM I3 ActivePower L1",
        key="pm_i3_activepower_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x21E,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 ActivePower L2",
        key="pm_i3_activepower_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x21F,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 ActivePower L3",
        key="pm_i3_activepower_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x220,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 Reactive or ApparentPower L1",
        key="pm_i3_reactive_or_apparentpower_l1",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x221,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 Reactive or ApparentPower L2",
        key="pm_i3_reactive_or_apparentpower_l2",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x222,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 Reactive or ApparentPower L3",
        key="pm_i3_reactive_or_apparentpower_l3",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        register=0x223,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 Inverter Current L1",
        key="pm_i3_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x224,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 Inverter Current L2",
        key="pm_i3_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x225,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 Inverter Current L3",
        key="pm_i3_current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x226,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 PV Power 1",
        key="pm_i3_pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x227,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 PV Power 2",
        key="pm_i3_pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x228,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 PV Voltage 1",
        key="pm_i3_pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x229,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 PV Voltage 2",
        key="pm_i3_pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x22A,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 PV Current 1",
        key="pm_i3_pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x22B,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 PV Current 2",
        key="pm_i3_pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x22C,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 Battery Power Charge",
        key="pm_i3_battery_power_charge",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x22D,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:battery-charging",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 Battery Voltage Charge",
        key="pm_i3_battery_voltage_charge",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x22E,
        scale=0.1,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 Battery Current Charge",
        key="pm_i3_battery_current_charge",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x22F,
        scale=0.1,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PM I3 Battery Capacity",
        key="pm_i3_battery_capacity_charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x233,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID | GEN3 | GEN4 | GEN5 | PM,
    ),
    #####
    #
    # Computed
    #
    #####
    SolaXModbusSensorEntityDescription(
        name="Grid Export",
        key="grid_export",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_function=value_function_grid_export,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Import",
        key="grid_import",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_function=value_function_grid_import,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        icon="mdi:home-import-outline",
    ),
    SolaXModbusSensorEntityDescription(
        key="hardware_version",
        value_function=value_function_hardware_version_g2,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="hardware_version",
        value_function=value_function_hardware_version_g3,
        allowedtypes=AC | HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="hardware_version",
        value_function=value_function_hardware_version_g4,
        allowedtypes=AC | HYBRID | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="hardware_version",
        value_function=value_function_hardware_version_g5,
        allowedtypes=AC | HYBRID | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="House Load",
        key="house_load",
        value_function=value_function_house_load,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=AC | HYBRID | MIC | GEN | GEN2 | GEN3 | GEN4 | GEN5,
        icon="mdi:home-lightning-bolt",
    ),
    SolaXModbusSensorEntityDescription(
        name="House Load Alt",
        key="house_load_alt",
        value_function=value_function_house_load_alt,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5,
        entity_registry_enabled_default=False,
        icon="mdi:home-lightning-bolt",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power Total",
        key="pv_power_total",
        value_function=value_function_pv_power_total,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=HYBRID,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Remotecontrol Autorepeat Remaining",
        key="remotecontrol_autorepeat_remaining",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_function=value_function_remotecontrol_autorepeat_remaining,
        allowedtypes=AC | HYBRID | GEN4 | GEN5,
        icon="mdi:home-clock",
    ),
    SolaXModbusSensorEntityDescription(
        key="software_version",
        value_function=value_function_software_version_g2,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="software_version",
        value_function=value_function_software_version_g3,
        allowedtypes=AC | HYBRID | GEN3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="software_version",
        value_function=value_function_software_version_g4,
        allowedtypes=AC | HYBRID | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="software_version",
        value_function=value_function_software_version_g5,
        allowedtypes=AC | HYBRID | GEN5,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Battery Power Charge",
        key="battery_power_charge",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_function=value_function_battery_power_charge,
        allowedtypes=AC | HYBRID | GEN5,
        icon="mdi:battery-charging",
    ),
    #####
    #
    # X1 Air,Boost, Mini
    #
    # X3 Mic, Mic Pro
    #
    #####
    #
    # Holding Registers
    #
    #####
    SolaXModbusSensorEntityDescription(
        name="RTC",
        key="rtc",
        register=0x318,
        unit=REGISTER_WORDS,
        wordcount=6,
        scale=value_function_rtc,
        entity_registry_enabled_default=False,
        allowedtypes=MIC,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:clock",
    ),
    SolaXModbusSensorEntityDescription(
        key="firmware_dsp",
        register=0x33D,
        allowedtypes=MIC | GEN,
        blacklist=(
            "MC502T",
            "MU802T",
        ),
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="firmware_arm",
        register=0x33E,
        allowedtypes=MIC | GEN,
        blacklist=(
            "MC502T",
            "MU802T",
        ),
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="q-curve",
        register=0x347,
        scale={
            0: "Off",
            1: "Over Excited",
            2: "Under Excited",
            3: "PF(p)",
            4: "Q(u)",
            5: "FixQPower",
        },
        allowedtypes=MIC | GEN2 | X3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="active_power_limit",
        register=0x351,
        allowedtypes=MIC | GEN2 | X3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="firmware_dsp",
        register=0x352,
        allowedtypes=MIC | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="firmware_arm",
        register=0x353,
        allowedtypes=MIC | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="lock_state",
        register=0x367,
        scale={
            0: "Locked",
            1: "Unlocked",
            2: "Unlocked - Advanced",
        },
        allowedtypes=MIC | GEN2 | X3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Export Power Limit",
        key="export_power_limit",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        register=0x371,
        allowedtypes=MIC | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        key="lock_state",
        register=0x39A,
        scale={
            0: "Locked",
            1: "Unlocked",
            2: "Unlocked - Advanced",
        },
        allowedtypes=MIC | GEN2 | GEN4 | X1,
        internal=True,
    ),
    #####
    #
    # Input Registers
    #
    #####
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x400,
        register_type=REG_INPUT,
        ignore_readerror=True,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x401,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x402,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN | GEN2,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x403,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN | GEN2,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage",
        key="inverter_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x404,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN | GEN2 | X1,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L1",
        key="inverter_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x404,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L2",
        key="inverter_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x405,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L3",
        key="inverter_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x406,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency",
        key="inverter_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x407,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN | GEN2 | X1,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency L1",
        key="inverter_frequency_l1",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x407,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency L2",
        key="inverter_frequency_l2",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x408,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency L3",
        key="inverter_frequency_l3",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x409,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current",
        key="inverter_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x40A,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN | GEN2 | X1,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L1",
        key="inverter_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x40A,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L2",
        key="inverter_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x40B,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L3",
        key="inverter_current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x40C,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x40D,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN | GEN2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power",
        key="inverter_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x40E,
        # newblock = True,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x40F,
        scale={
            0: "Waiting",
            1: "Checking",
            2: "Normal Mode",
            3: "Fault",
            4: "Permanent Fault Mode",
        },
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN | GEN2,
        icon="mdi:run",
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power L1",
        key="inverter_power_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x410,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power L2",
        key="inverter_power_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x411,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power L3",
        key="inverter_power_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x412,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x414,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN | GEN2,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x415,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN | GEN2,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power Total",
        key="pv_power_total",
        value_function=value_function_pv_power_total,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=MIC | GEN | GEN2,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Total Power",
        key="pv_total_power",
        value_function=value_function_pv_power_total,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN | GEN2,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Yield",
        key="total_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x423,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.001,
        rounding=2,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Yield",
        key="today_s_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x425,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.001,
        rounding=2,
        allowedtypes=MIC | GEN,
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Yield",
        key="total_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x423,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Yield",
        key="today_s_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x425,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x429,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | MPPT3,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x42A,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | MPPT3,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 3",
        key="pv_power_3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x42B,
        register_type=REG_INPUT,
        allowedtypes=MIC | MPPT3,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power",
        key="measured_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        ignore_readerror=True,
        newblock=True,  # Do not remove, required for FW <1.38
        register=0x435,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Grid Export",
        key="total_grid_export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x437,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Grid Import",
        key="total_grid_import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x439,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN,
        icon="mdi:home-import-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Grid Export",
        key="today_s_grid_export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x43B,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Grid Import",
        key="today_s_grid_import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x43C,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN,
        icon="mdi:home-import-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power",
        key="measured_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        ignore_readerror=True,
        newblock=True,  # Do not remove, required for FW <1.38
        register=0x43B,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN2,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Grid Export",
        key="total_grid_export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x43D,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN2,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Grid Import",
        key="total_grid_import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x43F,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.01,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN2,
        icon="mdi:home-import-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power 2",
        key="measured_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x704,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MIC | GEN2 | X1,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power L1",
        key="measured_power_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x704,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MIC | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power L2",
        key="measured_power_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x706,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MIC | GEN2 | X3,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power L3",
        key="measured_power_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x708,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=MIC | GEN2 | X3,
    ),
    #####
    #
    # X1 Boost Gen4
    #
    # MIC Gen4?
    #
    #####
    #
    # Holding Registers
    #
    #####
    SolaXModbusSensorEntityDescription(
        key="mppt_scan_mode_pv1",
        register=0x320,
        scale={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=MIC | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="q-curve",
        register=0x35C,
        scale={
            0: "Off",
            1: "Over Excited",
            2: "Under Excited",
            3: "PF(p)",
            4: "Q(u)",
            5: "FixQPower",
        },
        allowedtypes=MIC | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="active_power_limit",
        register=0x381,
        allowedtypes=MIC | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="firmware_arm",
        register=0x390,
        allowedtypes=MIC | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="firmware_dsp",
        register=0x394,
        allowedtypes=MIC | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="mppt_scan_mode_pv2",
        register=0x3A6,
        scale={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=MIC | GEN4,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="mppt_scan_mode_pv3",
        register=0x3A7,
        scale={
            0: "Off",
            1: "Low",
            2: "Middle",
            3: "High",
        },
        allowedtypes=MIC | GEN4 | MPPT3,
        internal=True,
    ),
    #####
    #
    # Input Registers
    #
    #####
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage",
        key="inverter_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x400,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN4 | X1,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current",
        key="inverter_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x403,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN4 | X1,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency",
        key="inverter_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x406,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        sleepmode=SLEEPMODE_LASTAWAKE,
        allowedtypes=MIC | GEN4 | X1,
    ),
    SolaXModbusSensorEntityDescription(
        name="CT Power",
        key="ct_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x408,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power",
        key="measured_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x409,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN4 | GEN5,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x40A,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x40B,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x40C,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN4 | MPPT3,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x40D,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN4,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x40E,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN4,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x40F,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN4 | MPPT3,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x410,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN4,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x411,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN4,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 3",
        key="pv_power_3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x412,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN4,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x413,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN4,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Control Board Temperature",
        key="control_board_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x414,
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN4,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x415,
        scale={
            0: "Waiting",
            1: "Checking",
            2: "Normal Mode",
            3: "Fault",
            4: "Permanent Fault Mode",
            5: "Update Mode",
            6: "EPS Checking",
            7: "EPS Mode",
        },
        register_type=REG_INPUT,
        allowedtypes=MIC | GEN4,
        icon="mdi:run",
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Yield",
        key="total_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x42B,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN4,
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Grid Export",
        key="total_grid_export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x42F,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN4,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Total Grid Import",
        key="total_grid_import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x431,
        register_type=REG_INPUT,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=2,
        entity_registry_enabled_default=False,
        allowedtypes=MIC | GEN4,
        icon="mdi:home-import-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Today's Yield",
        key="today_s_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x437,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=MIC | GEN4,
    ),
    #####
    #
    # X3 MAX MEGA G1
    #
    #
    #####
    #
    # Holding Registers
    #
    #####
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L1",
        key="inverter_voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x1001,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L1",
        key="inverter_current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1002,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power L1",
        key="measured_power_l1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1003,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency L1",
        key="inverter_frequency_l1",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1005,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L2",
        key="inverter_voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x1006,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L2",
        key="inverter_current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1007,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power L2",
        key="measured_power_l2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1008,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency L2",
        key="inverter_frequency_l2",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x100A,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage L3",
        key="inverter_voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x100B,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current L3",
        key="inverter_current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x100C,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Measured Power L3",
        key="measured_power_l3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x100D,
        unit=REGISTER_U32,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency L3",
        key="inverter_frequency_l3",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x100F,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x1010,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1011,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1012,
        allowedtypes=MAX,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x1014,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1015,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1016,
        allowedtypes=MAX,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 3",
        key="pv_voltage_3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x1018,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 3",
        key="pv_current_3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x1019,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 3",
        key="pv_power_3",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x101A,
        allowedtypes=MAX,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Temperature",
        key="inverter_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x101C,
        allowedtypes=MAX,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x101D,
        scale={
            0: "Initial Mode",
            1: "Standby Mode",
            3: "Normal Mode",
            5: "Fault Mode",
            9: "Shutdown mode",
        },
        allowedtypes=MAX,
        icon="mdi:run",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 4",
        key="pv_voltage_4",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x103E,
        scale=0.1,
        rounding=1,
        allowedtypes=MAX,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Current 4",
        key="pv_current_4",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x103F,
        scale=0.01,
        rounding=2,
        allowedtypes=MAX,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 4",
        key="pv_power_4",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x1040,
        allowedtypes=MAX,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Model Number",
        key="model_number",
        register=0x1A00,
        unit=REGISTER_STR,
        wordcount=8,
        allowedtypes=MAX,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="Serial Number",
        key="serial_number",
        register=0x1A10,
        unit=REGISTER_STR,
        wordcount=8,
        allowedtypes=MAX,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="Software Version",
        key="software_version",
        register=0x1A1C,
        unit=REGISTER_STR,
        wordcount=3,
        allowedtypes=MAX,
        icon="mdi:information",
    ),
    SolaXModbusSensorEntityDescription(
        name="MPPT Qty",
        key="mppt_qty",
        register=0x1A3B,
        allowedtypes=MAX,
        icon="mdi:information",
    ),
    #####
    #
    # Computed
    #
    #####
    SolaXModbusSensorEntityDescription(
        name="Grid Export",
        key="grid_export",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_function=value_function_grid_export,
        allowedtypes=MIC,
        icon="mdi:home-export-outline",
    ),
    SolaXModbusSensorEntityDescription(
        name="Grid Import",
        key="grid_import",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_function=value_function_grid_import,
        allowedtypes=MIC,
        icon="mdi:home-import-outline",
    ),
    SolaXModbusSensorEntityDescription(
        key="hardware_version",
        value_function=value_function_hardware_version_g3,
        allowedtypes=MIC | GEN2 | X1,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="hardware_version",
        value_function=value_function_hardware_version_g4,
        allowedtypes=MIC | GEN4 | X1,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="hardware_version",
        value_function=value_function_hardware_version_g1,
        allowedtypes=MIC | GEN | X3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="hardware_version",
        value_function=value_function_hardware_version_g2,
        allowedtypes=MIC | GEN2 | X3,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power Total",
        key="pv_power_total",
        value_function=value_function_pv_power_total,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=MIC | GEN4,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        key="software_version",
        value_function=value_function_software_version_air_g3,
        allowedtypes=MIC | GEN2 | X1,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="software_version",
        value_function=value_function_software_version_air_g4,
        allowedtypes=MIC | GEN4 | X1,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        key="software_version",
        value_function=value_function_software_version_g4,
        allowedtypes=MIC | GEN | GEN2 | X3,
        blacklist=("MU802T",),
        internal=True,
    ),
]

# ============================ plugin declaration =================================================


@dataclass
class solax_plugin(plugin_base):

    def isAwake(self, datadict):
        """determine if inverter is awake based on polled datadict"""
        return datadict.get("run_mode", None) == "Normal Mode"

    def wakeupButton(self):
        """in order to wake up  the inverter , press this button"""
        return "battery_awaken"

    async def async_determineInverterType(self, hub, configdict):
        # global SENSOR_TYPES
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber = await async_read_serialnr(hub, 0x0)
        if not seriesnumber:
            seriesnumber = await async_read_serialnr(hub, 0x300)  # bug in Endian.LITTLE decoding?
        if not seriesnumber:
            seriesnumber = await async_read_serialnr(hub, 0x1A10)
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find any serial number(s)")
            seriesnumber = "unknown"

        # derive invertertupe from seriiesnumber
        if seriesnumber.startswith("L30"):
            invertertype = HYBRID | GEN2 | X1  # Gen2 X1 SK-TL 3kW
            self.inverter_model = f"X1-Hybrid-{seriesnumber[1:2]}.{seriesnumber[2:3]}kW SK-TL"
        elif seriesnumber.startswith("U30"):
            invertertype = HYBRID | GEN2 | X1  # Gen2 X1 SK-SU 3kW
            self.inverter_model = f"X1-Hybrid-{seriesnumber[1:2]}.{seriesnumber[2:3]}kW SK-SU"
        elif seriesnumber.startswith("L37"):
            invertertype = HYBRID | GEN2 | X1  # Gen2 X1 SK-TL 3.7kW Untested
            self.inverter_model = f"X1-Hybrid-{seriesnumber[1:2]}.{seriesnumber[2:3]}kW SK-TL"
        elif seriesnumber.startswith("U37"):
            invertertype = HYBRID | GEN2 | X1  # Gen2 X1 SK-SU 3.7kW Untested
            self.inverter_model = f"X1-Hybrid-{seriesnumber[1:2]}.{seriesnumber[2:3]}kW SK-SU"
        elif seriesnumber.startswith("L50"):
            invertertype = HYBRID | GEN2 | X1  # Gen2 X1 SK-TL 5kW
            self.inverter_model = f"X1-Hybrid-{seriesnumber[1:2]}.{seriesnumber[2:3]}kW SK-TL"
        elif seriesnumber.startswith("U50"):
            invertertype = HYBRID | GEN2 | X1  # Gen2 X1 SK-SU 5kW
            self.inverter_model = f"X1-Hybrid-{seriesnumber[1:2]}.{seriesnumber[2:3]}kW SK-SU"
        elif seriesnumber.startswith("H1E"):
            invertertype = HYBRID | GEN3 | X1  # Gen3 X1 Early
            self.inverter_model = f"X1-Hybrid-{seriesnumber[3:4]}.{seriesnumber[4:5]}kW"
        elif seriesnumber.startswith("H1I"):
            invertertype = HYBRID | GEN3 | X1  # Gen3 X1 Alternative
            self.inverter_model = f"X1-Hybrid-{seriesnumber[3:4]}.{seriesnumber[4:5]}kW"
        elif seriesnumber.startswith("HCC"):
            invertertype = HYBRID | GEN3 | X1  # Gen3 X1 Alternative
            self.inverter_model = f"X1-Hybrid-{seriesnumber[3:4]}.{seriesnumber[4:5]}kW"
        elif seriesnumber.startswith("HUE"):
            invertertype = HYBRID | GEN3 | X1  # Gen3 X1 Late
            self.inverter_model = f"X1-Hybrid-{seriesnumber[3:4]}.{seriesnumber[4:5]}kW"
        elif seriesnumber.startswith("XRE"):
            invertertype = HYBRID | GEN3 | X1  # Gen3 X1 Alternative
            self.inverter_model = f"X1-Hybrid-{seriesnumber[3:4]}.{seriesnumber[4:5]}kW"
        elif seriesnumber.startswith("XAC"):
            invertertype = AC | GEN3 | X1  # X1AC
            self.inverter_model = "X1-AC"
        elif seriesnumber.startswith("PRI"):
            invertertype = AC | GEN3 | X1  # RetroFit
            self.inverter_model = "X1-RetroFit"
        elif seriesnumber.startswith("H3DE"):
            invertertype = HYBRID | GEN3 | X3  # Gen3 X3
            self.inverter_model = f"X3-Hybrid-{seriesnumber[3:5]}kW"
        elif seriesnumber.startswith("H3E"):
            invertertype = HYBRID | GEN3 | X3  # Gen3 X3
            self.inverter_model = f"X3-Hybrid-{seriesnumber[4:6]}kW"
        elif seriesnumber.startswith("H3LE"):
            invertertype = HYBRID | GEN3 | X3  # Gen3 X3
            self.inverter_model = f"X3-Hybrid-{seriesnumber[4:6]}kW"
        elif seriesnumber.startswith("H3PE"):
            invertertype = HYBRID | GEN3 | X3  # Gen3 X3
            self.inverter_model = f"X3-Hybrid-{seriesnumber[4:6]}kW"
        elif seriesnumber.startswith("H3UE"):
            invertertype = HYBRID | GEN3 | X3  # Gen3 X3
            self.inverter_model = f"X3-Hybrid-{seriesnumber[4:6]}kW"
        elif seriesnumber.startswith("F3D"):
            invertertype = AC | GEN3 | X3  # RetroFit
            self.inverter_model = "X3-RetroFit"
        elif seriesnumber.startswith("F3E"):
            invertertype = AC | GEN3 | X3  # RetroFit
            self.inverter_model = "X3-RetroFit"
        elif seriesnumber.startswith("H43"):
            invertertype = HYBRID | GEN4 | X1  # Gen4 X1 3kW / 3.7kW
            self.inverter_model = f"X1-Hybrid-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("H44"):
            invertertype = HYBRID | GEN4 | X1  # Gen4 X1 alt 5kW
            self.inverter_model = f"X1-Hybrid-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("H450"):
            invertertype = HYBRID | GEN4 | X1  # Gen4 X1 5.0kW
            self.inverter_model = f"X1-Hybrid-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("H460"):
            invertertype = HYBRID | GEN4 | X1  # Gen4 X1 6kW?
            self.inverter_model = f"X1-Hybrid-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("H475"):
            invertertype = HYBRID | GEN4 | X1  # Gen4 X1 7.5kW
            self.inverter_model = f"X1-Hybrid-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("F43"):
            invertertype = AC | GEN4 | X1  # RetroFit X1 3kW / 3.7kW?
            self.inverter_model = f"X1-RetroFit-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("F450"):
            invertertype = AC | GEN4 | X1  # RetroFit 5kW
            self.inverter_model = f"X1-RetroFit-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("F460"):
            invertertype = AC | GEN4 | X1  # RetroFit X1 6kW?
            self.inverter_model = f"X1-RetroFit-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("F475"):
            invertertype = AC | GEN4 | X1  # RetroFit X1 7.5kW?
            self.inverter_model = f"X1-RetroFit-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("PRE"):
            invertertype = AC | GEN4 | X1  # RetroFit
            self.inverter_model = "X1-RetroFit"
        elif seriesnumber.startswith("H55"):
            invertertype = HYBRID | GEN5 | X1 | MPPT3  # X1-IES 5kW?
            self.inverter_model = f"X1-IES-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("H56"):
            invertertype = HYBRID | GEN5 | X1 | MPPT3  # X1-IES 6kW?
            self.inverter_model = f"X1-IES-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("H58"):
            invertertype = HYBRID | GEN5 | X1 | MPPT3  # X1-IES 8kW
            self.inverter_model = f"X1-IES-{seriesnumber[2:3]}.{seriesnumber[3:4]}kW"
        elif seriesnumber.startswith("H31"):
            invertertype = HYBRID | GEN4 | X3  # TIGO TSI X3
            self.inverter_model = "X3-TIGO TSI"
        elif seriesnumber.startswith("H34"):
            invertertype = HYBRID | GEN4 | X3  # Gen4 X3
            self.inverter_model = "X3-Hybrid"
        elif seriesnumber.startswith("F34"):
            invertertype = AC | GEN4 | X3  # Gen4 X3 FIT
            self.inverter_model = "X3-RetroFit"
        elif seriesnumber.startswith("H35A0"):
            invertertype = HYBRID | GEN5 | X3  # X3-IES 4-8kW
            self.inverter_model = f"X3-IES-{seriesnumber[5:6]}kW"
        elif seriesnumber.startswith("H35A1"):
            invertertype = HYBRID | GEN5 | X3  # X3-IES 10-15kW
            self.inverter_model = f"X3-IES-{seriesnumber[4:6]}kW"
        elif seriesnumber.startswith("H3BC15"):
            invertertype = HYBRID | GEN5 | X3  # X3 Ultra C
            self.inverter_model = "X3-Ultra-15kW"
        elif seriesnumber.startswith("H3BC19"):
            invertertype = HYBRID | GEN5 | X3  # X3 Ultra C
            self.inverter_model = "X3-Ultra-19.9kW"
        elif seriesnumber.startswith("H3BC20"):
            invertertype = HYBRID | GEN5 | X3  # X3 Ultra C
            self.inverter_model = "X3-Ultra-20kW"
        elif seriesnumber.startswith("H3BC25"):
            invertertype = HYBRID | GEN5 | MPPT3 | X3  # X3 Ultra C
            self.inverter_model = "X3-Ultra-25kW"
        elif seriesnumber.startswith("H3BC30"):
            invertertype = HYBRID | GEN5 | MPPT3 | X3  # X3 Ultra C
            self.inverter_model = "X3-Ultra-30kW"
        elif seriesnumber.startswith("H3BD15"):
            invertertype = HYBRID | GEN5 | X3  # X3 Ultra D
            self.inverter_model = "X3-Ultra-15kW"
        elif seriesnumber.startswith("H3BD19"):
            invertertype = HYBRID | GEN5 | X3  # X3 Ultra D
            self.inverter_model = "X3-Ultra-19.9kW"
        elif seriesnumber.startswith("H3BD20"):
            invertertype = HYBRID | GEN5 | X3  # X3 Ultra D
            self.inverter_model = "X3-Ultra-20kW"
        elif seriesnumber.startswith("H3BD25"):
            invertertype = HYBRID | GEN5 | MPPT3 | X3  # X3 Ultra D
            self.inverter_model = "X3-Ultra-20kW"
        elif seriesnumber.startswith("H3BD30"):
            invertertype = HYBRID | GEN5 | MPPT3 | X3  # X3 Ultra D
            self.inverter_model = "X3-Ultra-30kW"
        elif seriesnumber.startswith("H3BF15"):
            invertertype = HYBRID | GEN5 | X3  # X3 Ultra F
            self.inverter_model = "X3-Ultra-15kW"
        elif seriesnumber.startswith("H3BF19"):
            invertertype = HYBRID | GEN5 | X3  # X3 Ultra F
            self.inverter_model = "X3-Ultra-19.9kW"
        elif seriesnumber.startswith("H3BF20"):
            invertertype = HYBRID | GEN5 | X3  # X3 Ultra F
            self.inverter_model = "X3-Ultra-20kW"
        elif seriesnumber.startswith("H3BF25"):
            invertertype = HYBRID | GEN5 | MPPT3 | X3  # X3 Ultra F
            self.inverter_model = "X3-Ultra-20kW"
        elif seriesnumber.startswith("H3BF30"):
            invertertype = HYBRID | GEN5 | MPPT3 | X3  # X3 Ultra F
            self.inverter_model = "X3-Ultra-30kW"
        elif seriesnumber.startswith("XAU"):
            invertertype = MIC | GEN2 | X1  # X1-Boost
            self.inverter_model = "X1-Boost"
        elif seriesnumber.startswith("XB3"):
            invertertype = MIC | GEN2 | X1  # X1-Boost
            self.inverter_model = "X1-Boost"
        elif seriesnumber.startswith("XM3"):
            invertertype = MIC | GEN2 | X1  # X1-Mini G3
            self.inverter_model = "X1-Mini"
        elif seriesnumber.startswith("XB4"):
            invertertype = MIC | GEN4 | X1  # X1-Boost G4
            self.inverter_model = "X1-Boost"
        elif seriesnumber.startswith("XM4"):
            invertertype = MIC | GEN4 | X1  # X1-Mini G4
            self.inverter_model = "X1-Mini"
        elif seriesnumber.startswith("XMA"):
            invertertype = MIC | GEN2 | X1  # X1-Mini G3
            self.inverter_model = "X1-Mini"
        elif seriesnumber.startswith("ZA4"):
            invertertype = MIC | GEN4 | X1  # X1-Boost G4
            self.inverter_model = "X1-Boost"
        elif seriesnumber.startswith("XST"):
            invertertype = MIC | GEN4 | X1 | MPPT3  # X1-SMART-G2
            self.inverter_model = "X1-SMART-G2"
        elif seriesnumber.startswith("MC103T"):
            invertertype = MIC | GEN | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MP153T"):
            invertertype = MIC | GEN | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC203T"):
            invertertype = MIC | GEN | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC502T"):
            invertertype = MIC | GEN | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MU502T"):
            invertertype = MIC | GEN | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC602T"):
            invertertype = MIC | GEN | X3  # MIC X3 6kW
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MU602T"):
            invertertype = MIC | GEN | X3  # MIC X3 6kW
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC702T"):
            invertertype = MIC | GEN | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MU702T"):
            invertertype = MIC | GEN | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC802T"):
            invertertype = MIC | GEN | X3  # MIC X3 8kW
        elif seriesnumber.startswith("MCU08T"):
            invertertype = MIC | GEN | X3  # MIC X3 8kW
        elif seriesnumber.startswith("MU802T"):
            invertertype = MIC | GEN | X3  # MIC X3
        elif seriesnumber.startswith("MC803T"):
            invertertype = MIC | GEN | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MU803T"):
            invertertype = MIC | GEN | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MU902T"):
            invertertype = MIC | GEN | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC806T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MU806T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC106T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC204T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC205T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC206T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC208T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
            self.software_version = "Unknown"
        elif seriesnumber.startswith("MC210T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC212T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MC215T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MP156T"):
            invertertype = MIC | GEN2 | X3  # MIC X3
            self.inverter_model = "X3-MIC"
        elif seriesnumber.startswith("MPT08"):
            invertertype = MIC | GEN2 | X3  # MIC PRO X3
            self.inverter_model = "X3-MIC PRO-8kW"
        elif seriesnumber.startswith("MPT1"):
            invertertype = MIC | GEN2 | X3  # MIC PRO X3 10-17kW
            self.inverter_model = f"X3-MIC PRO-{seriesnumber[3:5]}kW"
        elif seriesnumber.startswith("MPT20"):
            invertertype = MIC | GEN2 | X3  # MIC PRO X3
            self.inverter_model = "X3-MIC PRO-20kW"
        elif seriesnumber.startswith("MPT25"):
            invertertype = MIC | GEN2 | X3 | MPPT3  # MIC PRO X3
            self.inverter_model = "X3-MIC PRO-25kW"
        elif seriesnumber.startswith("MPT30"):
            invertertype = MIC | GEN2 | X3 | MPPT3  # MIC PRO X3
            self.inverter_model = "X3-MIC PRO-30kW"
        elif seriesnumber.startswith("MAX"):
            invertertype = MAX  # MAX G1
            self.inverter_model = "X3-MAX"
        else:
            invertertype = 0
            _LOGGER.error(f"unrecognized inverter type - serial number : {seriesnumber}")

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
        mpptmatch = ((inverterspec & entitymask & ALL_MPPT_GROUP) != 0) or (entitymask & ALL_MPPT_GROUP == 0)
        pmmatch = ((inverterspec & entitymask & ALL_PM_GROUP) != 0) or (entitymask & ALL_PM_GROUP == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist:
                if serialnumber.startswith(start):
                    blacklisted = True
        return (
            genmatch and xmatch and hybmatch and epsmatch and dcbmatch and mpptmatch and pmmatch
        ) and not blacklisted

    def getSoftwareVersion(self, new_data):
        return new_data.get("software_version", None)

    def getHardwareVersion(self, new_data):
        return new_data.get("hardware_version", None)

    def localDataCallback(self, hub):
        # adapt the read scales for export_control_user_limit if exception is configured
        # only called after initial polling cycle and subsequent modifications to local data
        _LOGGER.info(f"local data update callback")

        config_scale_entity = hub.numberEntities.get("config_export_control_limit_readscale")
        if config_scale_entity and config_scale_entity.enabled:
            new_read_scale = hub.data.get("config_export_control_limit_readscale")
            if new_read_scale != None:
                _LOGGER.info(
                    f"local data update callback for read_scale: {new_read_scale} enabled: {config_scale_entity.enabled}"
                )
                number_entity = hub.numberEntities.get("export_control_user_limit")
                sensor_entity = hub.sensorEntities.get("export_control_user_limit")
                if number_entity:
                    number_entity.entity_description = replace(
                        number_entity.entity_description,
                        read_scale=new_read_scale,
                    )
                if sensor_entity:
                    sensor_entity.entity_description = replace(
                        sensor_entity.entity_description,
                        read_scale=new_read_scale,
                    )

        config_maxexport_entity = hub.numberEntities.get("config_max_export")
        if config_maxexport_entity and config_maxexport_entity.enabled:
            new_max_export = hub.data.get("config_max_export")
            if new_max_export != None:
                for key in [
                    "remotecontrol_active_power",
                    "remotecontrol_import_limit",
                    "export_control_user_limit",
                    "generator_max_charge",
                ]:
                    number_entity = hub.numberEntities.get(key)
                    if number_entity:
                        number_entity._attr_native_max_value = new_max_export
                        # update description also, not sure whether needed or not
                        number_entity.entity_description = replace(
                            number_entity.entity_description,
                            native_max_value=new_max_export,
                        )
                        _LOGGER.info(f"local data update callback for entity: {key} new limit: {new_max_export}")


plugin_instance = solax_plugin(
    plugin_name="SolaX",
    plugin_manufacturer="SolaX Power",
    SENSOR_TYPES=SENSOR_TYPES_MAIN,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=[],
    block_size=100,
    order16=Endian.BIG,
    order32=Endian.LITTLE,
    auto_block_ignore_readerror=True,
)
