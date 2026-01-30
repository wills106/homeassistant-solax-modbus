import logging
from dataclasses import dataclass, replace
from time import time

from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import (
    PERCENTAGE,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.helpers.entity import EntityCategory

from custom_components.solax_modbus.const import (
    BUTTONREPEAT_FIRST,
    BUTTONREPEAT_POST,
    CONF_READ_DCB,
    CONF_READ_EPS,
    CONF_READ_PM,
    DEFAULT_READ_DCB,
    DEFAULT_READ_EPS,
    DEFAULT_READ_PM,
    REG_HOLDING,
    REG_INPUT,
    REGISTER_S16,
    REGISTER_S32,
    REGISTER_U16,
    REGISTER_U32,
    SCAN_GROUP_AUTO,
    SCAN_GROUP_DEFAULT,
    SCAN_GROUP_FAST,
    SCAN_GROUP_MEDIUM,
    WRITE_MULTI_MODBUS,
    BaseModbusButtonEntityDescription,
    BaseModbusNumberEntityDescription,
    BaseModbusSelectEntityDescription,
    BaseModbusSensorEntityDescription,
    BaseModbusSwitchEntityDescription,
    autorepeat_remaining,
    autorepeat_stop,
    plugin_base,
)

from .pymodbus_compat import DataType, convert_from_registers

_LOGGER = logging.getLogger(__name__)

""" ============================================================================================
bitmasks  definitions to characterize inverters, ogranized by group
these bitmasks are used in entitydeclarations to determine to which inverters the entity applies
within a group, the bits in an entitydeclaration will be interpreted as OR
between groups, an AND condition is applied, so all gruoups must match.
An empty group (group without active flags) evaluates to True.
example: GEN3 | GEN4 | GEN5 | X1 | X3 | EPS
means:  any inverter of type (GEN3 or GEN4 | GEN5) and (X1 or X3) and (EPS)
An entity can be declared multiple times (with different bitmasks) if the parameters are different for each inverter type
"""

GEN = 0x0001  # base generation for MIC, PV, AC
GEN2 = 0x0002
GEN3 = 0x0004
GEN4 = 0x0008
GEN5 = 0x0010
GEN6 = 0x0020  # Hybrid X1-VAST & X3-Hybrid-G4 Pro
ALL_GEN_GROUP = GEN | GEN2 | GEN3 | GEN4 | GEN5 | GEN6

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
MPPT5 = 0x100000
MPPT6 = 0x200000
MPPT8 = 0x400000
MPPT10 = 0x800000
ALL_MPPT_GROUP = MPPT3 | MPPT4 | MPPT5 | MPPT6 | MPPT8 | MPPT10

ALLDEFAULT = 0  # should be equivalent to AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub, address):
    res = None
    inverter_data = None
    try:
        inverter_data = await hub.async_read_input_registers(unit=hub._modbus_addr, address=address, count=1)
        if inverter_data is not None and not inverter_data.isError():
            # Decode 7 registers (14 bytes) as string using clientless compat helper
            res = convert_from_registers(inverter_data.registers[0:1], DataType.UINT16, "big")
            hub.seriesnumber = res
    except Exception as ex:
        _LOGGER.warning(
            f"{hub.name}: attempt to read serialnumber failed at 0x{address:x} data: {inverter_data}", exc_info=True
        )
    _LOGGER.info(f"Read {hub.name} 0x{address:x} number: {res}")
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


@dataclass
class SolaXModbusSwitchEntityDescription(BaseModbusSwitchEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


# ====================================== Computed value functions  =================================================


def autorepeat_function_remotecontrol_recompute(initval, descr, datadict):
    # initval = BUTTONREPEAT_FIRST means first run;
    # initval = BUTTONREPEAT_LOOP means subsequent runs for button autorepeat value functions
    # initval = BUTTONREPEAT_POST means final call for cleanup, normally no action needed

    # terminate expiring loop by disabling remotecontrol
    if initval == BUTTONREPEAT_POST:
        return {
            "action": WRITE_MULTI_MODBUS,
            "data": [
                (
                    "remotecontrol_power_control",
                    "Disabled",
                ),
            ],
        }

    power_control = datadict.get("remotecontrol_power_control", "Disabled")
    set_type = datadict.get("remotecontrol_set_type", "Set")  # other options did not work
    target = datadict.get("remotecontrol_active_power", 0)
    reactive_power = datadict.get("remotecontrol_reactive_power", 0)
    rc_duration = datadict.get("remotecontrol_duration", 20)
    reap_up = datadict.get("reactive_power_upper", 0)
    reap_lo = datadict.get("reactive_power_lower", 0)
    import_limit = datadict.get("remotecontrol_import_limit", 20000)
    meas = datadict.get("measured_power", 0)
    pv = datadict.get("pv_power_total", 0)
    rc_timeout = datadict.get("remotecontrol_timeout", 0)
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
    old_ap_target = ap_target
    ap_target = min(ap_target, import_limit - houseload_brut)
    # _LOGGER.warning(f"import shaving: old_ap_target:{old_ap_target} new ap_target:{ap_target} max: {import_limit-houseload} min:{-export_limit-houseload}")
    if old_ap_target != ap_target:
        _LOGGER.debug(
            f"import shaving: old_ap_target:{old_ap_target} new ap_target:{ap_target} max: {import_limit - houseload_brut}"
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
        (  # dummy fill address 0x83
            REGISTER_U16,
            0,  # dummy target soc, should be ignored by system in mode 1
        ),
        (  # dummy fill address 0x84-85
            REGISTER_U32,
            0,  # dummy target energy Wh, should be ignored by system in mode 1
        ),
        (  # dummy fill address 0x86-87
            REGISTER_S32,
            0,  # dummy target charge/discharge power, should be ignored by system in mode 1
        ),
        (
            "remotecontrol_timeout",  # not in documentation as next parameter
            rc_timeout,  # not in documentation as consecutive parameter
        ),
    ]
    if power_control == "Disabled":
        _LOGGER.info("Stopping mode 1 loop")
        autorepeat_stop(datadict, descr.key)
        datadict["remotecontrol_power_control_mode"] = "Disabled"  # disable the mode8 remotecontrol loop
        autorepeat_stop(datadict, "powercontrolmode8_trigger")
    _LOGGER.debug(f"Evaluated remotecontrol_trigger: corrected/clamped values: {res}")
    return {"action": WRITE_MULTI_MODBUS, "data": res}


def autorepeat_function_powercontrolmode8_recompute(initval, descr, datadict):
    # initval = BUTTONREPEAT_FIRST means first run;
    # initval = BUTTONREPEAT_LOOP means subsequent runs for button autorepeat value functions
    # initval = BUTTONREPEAT_POST means final call for cleanup, normally no action needed
    if initval == BUTTONREPEAT_POST:
        datadict["remotecontrol_current_pushmode_power"] = None
        datadict["remotecontrol_current_pv_power_limit"] = None
        return {
            "action": WRITE_MULTI_MODBUS,
            "data": [
                (
                    "remotecontrol_power_control_mode",
                    "Disabled",
                )
            ],
        }
    # See mode 8 and 9 of doc https://kb.solaxpower.com/solution/detail/2c9fa4148ecd09eb018edf67a87b01d2
    power_control = datadict.get("remotecontrol_power_control_mode", "Disabled")
    curmode = datadict.get("modbus_power_control", "unknown")
    set_type = datadict.get(
        "remotecontrol_set_type", "Set"
    )  # Set for simplicity; otherwise First time should be Set, subsequent times Update
    setpvlimit = datadict.get("remotecontrol_pv_power_limit", 10000)
    pushmode_power = datadict.get("remotecontrol_push_mode_power_8_9", 0)
    target_soc = datadict.get("remotecontrol_target_soc_8_9", 95)
    rc_duration = datadict.get("remotecontrol_duration", 20)
    import_limit = datadict.get("remotecontrol_import_limit", 20000)
    battery_capacity = datadict.get("battery_capacity", 0)
    rc_timeout = datadict.get("remotecontrol_timeout", 2)
    timeout_motion = datadict.get("remotecontrol_timeout_next_motion", "VPP Off")
    pv = datadict.get("pv_power_total", 0)
    houseload = value_function_house_load(initval, descr, datadict)

    if power_control == "Mode 8 - PV and BAT control - Duration":
        pvlimit = setpvlimit  # import capping is done later
    elif (
        power_control == "Negative Injection Price"
    ):  # grid export zero; PV restricted to house_load and battery charge
        measured = datadict.get(
            "measured_power", 0
        )  # positive for export, negative for import - for future correction purposes
        houseload = max(0, houseload)
        if battery_capacity >= 92:
            pvlimit = (
                houseload + abs(setpvlimit) * (100.0 - battery_capacity) / 15.0 + 60
            )  # slow down charging - nearly full
        else:
            pvlimit = setpvlimit + houseload + 60  # inverter overhead 40
        pvlimit = max(houseload, pvlimit)
        pushmode_power = (
            houseload - min(pv, pvlimit) - 90 + pv / 14
        )  # some kind of empiric correction for losses - machine learning would be better
        _LOGGER.debug(
            f"***debug*** setpvlimit: {setpvlimit} pvlimit: {pvlimit} pushmode: {pushmode_power} houseload:{houseload} pv: {pv} batcap: {battery_capacity}"
        )

    elif power_control == "Negative Injection and Consumption Price":  # disable PV, charge from grid
        pvlimit = 0
        pushmode_power = houseload - import_limit
    elif power_control == "Export-First Battery Limit":
        # --- Export-First Battery Limit (Mode 8 custom) ---
        # Split PV surplus into (a) grid export up to the configured cap and (b) battery charging.
        # The user percentage limits battery charge power relative to BMS max (0–100%).
        # In deficit (house load > PV), discharge the battery up to the deficit (respecting min SOC).

        DEADBAND_W = 100  # deadband around zero net flow to avoid flicker

        # Export limit no readscale:
        export_limit = datadict.get("export_control_user_limit", 30000)

        # SOC bounds
        min_discharge_soc = datadict.get("selfuse_discharge_min_soc", 10)
        max_charge_soc = datadict.get("battery_charge_upper_soc", 100)

        # Local copies
        pvlimit = max(0, datadict.get("remotecontrol_pv_power_limit", 30000))
        last_push = datadict.get("_mode8_last_push", 0)
        pushmode_power = 0  # + = discharge, - = charge

        # Debug inputs
        _LOGGER.debug(
            f"[Mode8 Export-First] inputs pv={pv}W hl={houseload}W exp_lim={export_limit}W imp_lim={import_limit}W "
            f"soc={battery_capacity}% min_soc={min_discharge_soc}% max_soc={max_charge_soc}% pvlimit={pvlimit}W last_push={last_push}W"
        )

        # Optional probes (if available)
        measured_power = datadict.get("measured_power", None)
        grid_export_s = datadict.get("grid_export", None)
        grid_import_s = datadict.get("grid_import", None)
        _LOGGER.debug(
            "[Mode8 Export-First] probes: "
            f"measured_power={measured_power if measured_power is not None else 'n/a'} "
            f"grid_export={grid_export_s if grid_export_s is not None else 'n/a'} "
            f"grid_import={grid_import_s if grid_import_s is not None else 'n/a'}"
        )

        # Surplus path: export first (up to cap), then charge battery with the remainder (within BMS and user cap).
        if pv >= houseload:
            surplus = pv - houseload

            # User cap (% of BMS max charge power)
            factor_pct = datadict.get("export_first_battery_charge_limit_8_9", 100)
            try:
                f = max(0.0, min(1.0, float(factor_pct) / 100.0))
            except Exception:
                f = 1.0

            export_within_cap = min(export_limit, surplus)

            # BMS charge capability approximation
            bms_a = datadict.get("bms_charge_max_current", None)
            batt_v = datadict.get("battery_1_voltage_charge", None) or datadict.get("battery_voltage_charge", None)
            if isinstance(bms_a, (int, float)) and isinstance(batt_v, (int, float)) and bms_a > 0 and batt_v > 0:
                bms_cap_w = int(bms_a * batt_v)
            else:
                reg_a = datadict.get("battery_charge_max_current", 20)
                bms_cap_w = int(reg_a * (batt_v if isinstance(batt_v, (int, float)) and batt_v > 0 else 360))

            rest_for_batt = max(0, surplus - export_within_cap)
            if rest_for_batt > 0 and battery_capacity < max_charge_soc:
                bms_charge_cap = int(min(bms_cap_w, rest_for_batt))
                pct_cap_w = int(f * bms_cap_w)
                desired_charge = int(min(bms_charge_cap, pct_cap_w))
                pushmode_power = -desired_charge
            else:
                desired_charge = 0
                pushmode_power = 0

            _LOGGER.debug(
                f"[Mode8 Export-First] export-first: surplus={surplus}W within_cap={export_within_cap}W rest={rest_for_batt}W "
                f"bms_cap≈{bms_cap_w}W pct_cap={int(f * bms_cap_w)}W -> charge={desired_charge}W"
            )

        else:
            # Deficit path: discharge battery up to current deficit (if SOC allows).
            deficit = houseload - pv
            if battery_capacity > min_discharge_soc:
                pushmode_power = min(deficit, 30000)
            else:
                pushmode_power = 0
            _LOGGER.debug(
                f"[Mode8 Export-First] deficit: deficit={deficit}W soc={battery_capacity}% chosen_push={pushmode_power}W"
            )

        # Deadband (simple): in surplus and not charging (push>=0), hold last_push near zero flow to avoid flicker.
        net_flow = pv - houseload + pushmode_power  # >0 export, <0 import
        if pv >= houseload and pushmode_power >= 0 and abs(net_flow) < DEADBAND_W:
            _LOGGER.debug(
                f"[Mode8 Export-First] deadband hold: net={net_flow}W within ±{DEADBAND_W}W -> push stays {last_push}W"
            )
            pushmode_power = last_push
        else:
            _LOGGER.debug(
                f"[Mode8 Export-First] deadband not applied: pv>hl={pv >= houseload}, push>=0={pushmode_power >= 0}, |net|={abs(net_flow)}"
            )

        # Export feedback (shortfall): if measured export is below the cap beyond a small margin, reduce charging a bit.
        # Small, bounded nudge; no PID or slew logic.
        try:
            measured_export = int(datadict.get("grid_export", 0) or 0)
        except Exception:
            measured_export = 0
        fb_deadband = int(datadict.get("export_feedback_deadband_w", 100) or 100)  # minimal gap before correcting
        fb_max_nudge = int(datadict.get("export_feedback_max_w", 400) or 400)  # clamp per cycle
        if pv >= houseload and pushmode_power < 0:
            shortfall = export_limit - measured_export
            if shortfall > fb_deadband:
                nudge = min(shortfall, fb_max_nudge)
                pushmode_power += nudge  # make charge less negative → increases export
                if pushmode_power > 0:
                    pushmode_power = 0  # do not flip to discharge in surplus
                _LOGGER.debug(
                    f"[Mode8 Export-First] export feedback: +{nudge}W (measured={measured_export}W, cap={export_limit}W)"
                )

        # Export feedback (overshoot): if measured export exceeds the cap beyond the margin, increase charging a bit.
        if pv >= houseload and pushmode_power <= 0:
            overshoot = measured_export - export_limit
            if overshoot > fb_deadband:
                nudge = min(overshoot, fb_max_nudge)
                pushmode_power -= nudge  # charge a bit more → lowers export
                _LOGGER.debug(
                    f"[Mode8 Export-First] export overshoot feedback: -{nudge}W (measured={measured_export}W, cap={export_limit}W)"
                )

        # Discharge feedback (deficit): if we still see export while discharging, trim discharge a bit.
        # Uses same fb_deadband/fb_max_nudge as surplus feedback to keep behavior bounded.
        if pv < houseload and pushmode_power > 0:
            try:
                measured_export = int(datadict.get("grid_export", 0) or 0)
            except Exception:
                measured_export = 0
            if measured_export > fb_deadband:
                nudge = min(measured_export, fb_max_nudge)
                pushmode_power = max(0, pushmode_power - nudge)
                _LOGGER.debug(
                    f"[Mode8 Export-First] discharge feedback: -{nudge}W (measured_export={measured_export}W) to reduce grid export while discharging"
                )

        # Safety: do not discharge above the instantaneous deficit.
        if pv < houseload:
            deficit_now = houseload - pv
            if pushmode_power > deficit_now:
                _LOGGER.debug(
                    f"[Mode8 Export-First] clamp discharge to deficit: push={pushmode_power}W -> {deficit_now}W (pv={pv} hl={houseload})"
                )
                pushmode_power = deficit_now

        # Final debug and state
        net_flow = pv - houseload + pushmode_power
        _LOGGER.debug(
            f"[Mode8 Export-First] result: push={pushmode_power}W pvlimit={pvlimit}W net_flow={net_flow}W (>0 export, <0 import)"
        )
        datadict["_mode8_last_push"] = pushmode_power
    elif power_control == "Enabled Grid Control":
        pushmode_power = pushmode_power + houseload - pv
        pvlimit = setpvlimit
    elif power_control == "Disabled":
        pvlimit = setpvlimit
    # limit import to max import (capacity tarif in some countries)
    old_pushmode_power = pushmode_power
    excess_import = houseload - pv - pushmode_power - import_limit
    if excess_import > 0:
        pushmode_power = pushmode_power + excess_import  # reduce import

    if old_pushmode_power != pushmode_power:
        _LOGGER.debug(f"import shaving: old_pushmode_power:{old_pushmode_power} new pushmode_power:{pushmode_power}")
    # res sequence only valid for mode 8 and  submodes of mode 8
    res = [
        (
            "remotecontrol_power_control_mode",
            "Mode 8 - PV and BAT control - Duration",
        ),
        (
            "remotecontrol_set_type",
            set_type,
        ),
        (
            "remotecontrol_pv_power_limit",
            pvlimit,
        ),
        (
            "remotecontrol_push_mode_power_8_9",
            pushmode_power,
        ),
        (
            "remotecontrol_duration",
            rc_duration,
        ),
        (
            "remotecontrol_timeout",
            rc_timeout,
        ),
        (
            "remotecontrol_timeout_next_motion",
            timeout_motion,
        ),
    ]
    datadict["remotecontrol_current_pushmode_power"] = pushmode_power
    datadict["remotecontrol_current_pv_power_limit"] = pvlimit
    if initval != BUTTONREPEAT_FIRST and curmode != "Individual Setting - Duration Mode":
        _LOGGER.warning(
            f"autorepeat mode 8 changed curmode: {curmode}; battery: {battery_capacity}; mode: {power_control}"
        )
    if power_control == "Disabled":
        autorepeat_stop(datadict, descr.key)
        _LOGGER.info("Stopping mode 8 loop by disabling mode 8")
        return {
            "action": WRITE_MULTI_MODBUS,
            "register": 0xA0,
            "data": [
                (
                    "remotecontrol_power_control_mode",
                    "Disabled",
                ),
            ],
        }  # was 0x7C
        # datadict["remotecontrol_power_control"] = "Disabled" # disable the remotecontrol Mode 1 loop
        # autorepeat_stop_with_postaction(datadict,"remotecontrol_trigger") # trigger the remotecontrol mode 1 button for a single BUTTONREPEAT_POST action
    _LOGGER.debug(f"Evaluated remotecontrol_mode8_trigger: corrected/clamped values: {res}")
    return {"action": WRITE_MULTI_MODBUS, "data": res}


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
    mode_1to7 = autorepeat_remaining(datadict, "remotecontrol_trigger", time())
    mode_8to9 = autorepeat_remaining(datadict, "powercontrolmode8_trigger", time())
    return max(mode_1to7, mode_8to9)


def value_function_remotecontrol_current_pushmode_power(initval, descr, datadict):
    return datadict.get(descr.key, None)


def value_function_remotecontrol_current_pv_power_limit(initval, descr, datadict):
    return datadict.get(descr.key, None)


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


def value_function_inverter_power_g5(initval, descr, datadict):
    return (
        datadict.get("inverter_power_l1", 0)
        + datadict.get("inverter_power_l2", 0)
        + datadict.get("inverter_power_l3", 0)
    )


def value_function_battery_capacity_gen5(initval, descr, datadict):
    # Check if total capacity has a sane value, if so return that
    total_charge = datadict.get("battery_total_capacity_charge", 0)
    if total_charge > 0:
        return total_charge
    # Otherwise try to use the correct battery capacity field
    bat1_charge = datadict.get("battery_1_capacity_charge", 0)
    bat2_charge = datadict.get("battery_2_capacity_charge", 0)
    # Use the lesser if both available
    if (bat1_charge > 0) and (bat2_charge > 0):
        return min(bat2_charge, bat1_charge)
    # Otherwise use whichever is available
    if bat1_charge > 0:
        return bat1_charge  # batt 1 available, use that
    if bat2_charge > 0:
        return bat2_charge  # batt 2 available, use that
    return 0


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

BUTTON_TYPES = []

# ================================= Number Declarations ============================================================

NUMBER_TYPES = []

# ================================= Switch Declarations ============================================================

SWITCH_TYPES = []

# ================================= Select Declarations ============================================================

SELECT_TYPES = []

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES_MAIN: list[SolaXModbusSensorEntityDescription] = [
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
        register=0x103,
        scale=0.1,
        register_type=REG_INPUT,
        rounding=1,
        allowedtypes=AC | HYBRID,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current",
        key="inverter_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x180,
        scale=0.1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        rounding=1,
        allowedtypes=AC | HYBRID,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Frequency",
        key="inverter_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x106,
        scale=0.01,
        rounding=2,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Power",
        key="inverter_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x2,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID,
    ),
    SolaXModbusSensorEntityDescription(
        name="PowerFactor",
        key="powerfactor",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER_FACTOR,
        register=0x12D,
        scale=0.001,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID,
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x28B,
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
        register=0x292,
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
        register=0x28C,
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
        register=0x293,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=HYBRID,
        icon="mdi:current-dc",
    ),  #
    SolaXModbusSensorEntityDescription(
        name="EPS Voltage",
        key="eps_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x400,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Current",
        key="eps_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x401,
        register_type=REG_INPUT,
        scale=0.1,
        rounding=1,
        allowedtypes=AC | HYBRID | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Power",
        key="eps_power",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        register=0x402,
        register_type=REG_INPUT,
        unit=REGISTER_S32,
        allowedtypes=AC | HYBRID | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="EPS Frequency",
        key="eps_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x404,
        register_type=REG_INPUT,
        scale=0.01,
        rounding=2,
        allowedtypes=AC | HYBRID | EPS,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery",
        key="battery",
        register=0xC00,
        scale={
            0: "Not Connected",
            1: "TLR25/36",
            2: "GSL Lithium",
        },
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:battery-unknown",
    ),
    SolaXModbusSensorEntityDescription(
        name="PV Power 1",
        key="pv_power_1",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x28D,
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
        register=0x294,
        register_type=REG_INPUT,
        allowedtypes=HYBRID,
        icon="mdi:solar-power-variant",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Voltage Charge",
        key="battery_voltage_charge",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x480,
        scale=0.1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Current Charge",
        key="battery_current_charge",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x481,
        scale=0.1,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC,
        icon="mdi:current-dc",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Power Charge",
        key="battery_power_charge",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x482,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID,
        icon="mdi:battery-charging",
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Temperature",
        key="battery_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x484,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Capacity",
        key="battery_capacity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x48D,
        register_type=REG_INPUT,
        allowedtypes=AC | HYBRID,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Temp High",
        key="battery_temp_high",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        register=0xC07,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Temp Low",
        key="battery_temp_low",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        register=0xC08,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.1,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SolaXModbusSensorEntityDescription(
        name="Cell Voltage High",
        key="cell_voltage_high",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xC05,
        scan_group=SCAN_GROUP_DEFAULT,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SolaXModbusSensorEntityDescription(
        name="Cell Voltage Low",
        key="cell_voltage_low",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0xC06,
        scan_group=SCAN_GROUP_DEFAULT,
        register_type=REG_INPUT,
        scale=0.1,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SolaXModbusSensorEntityDescription(
        name="Battery Voltage Cell Difference",
        key="battery_voltage_cell_difference",
        value_function=value_function_battery_voltage_cell_difference,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=AC | HYBRID,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
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
        seriesnumber = await async_read_serialnr(hub, 0xC08)

        # derive invertertupe from seriiesnumber
        invertertype = HYBRID | GEN | X1  # Fake Inverter detection
        self.inverter_model = "X1-Hybrid-LV"
        self.software_version = "Unknown"

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
    SWITCH_TYPES=SWITCH_TYPES,
    block_size=100,
    # order16=Endian.BIG,
    order32="little",
    auto_block_ignore_readerror=True,
    default_holding_scangroup=SCAN_GROUP_MEDIUM,
    default_input_scangroup=SCAN_GROUP_AUTO,  # SCAN_GROUP_MEDIUM for slow changing units like temperature, kWh, ...
    auto_default_scangroup=SCAN_GROUP_FAST,
    auto_slow_scangroup=SCAN_GROUP_MEDIUM,
)
