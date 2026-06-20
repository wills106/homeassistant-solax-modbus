import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from time import time
from typing import Any

from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.entity import EntityCategory  # type: ignore[attr-defined]  # HA stubs incomplete

from custom_components.solax_modbus.const import (  # type: ignore[attr-defined]  # UnitOfReactivePower conditionally exported
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
    REGISTER_STR,
    REGISTER_U8H,
    REGISTER_U8L,
    REGISTER_U16,
    REGISTER_U32,
    REGISTER_WORDS,
    SCAN_GROUP_AUTO,
    SCAN_GROUP_DEFAULT,
    SCAN_GROUP_FAST,
    SCAN_GROUP_MEDIUM,
    SLEEPMODE_LASTAWAKE,
    TIME_OPTIONS,
    TIME_OPTIONS_GEN4,
    TIME_OPTIONS_SEPARATE_REGISTERS,
    WRITE_DATA_LOCAL,
    WRITE_MULTI_MODBUS,
    WRITE_MULTISINGLE_MODBUS,
    WRITE_SINGLE_MODBUS,
    BaseModbusButtonEntityDescription,
    BaseModbusNumberEntityDescription,
    BaseModbusSelectEntityDescription,
    BaseModbusSensorEntityDescription,
    BaseModbusSwitchEntityDescription,
    BaseModbusTimeEntityDescription,
    UnitOfReactivePower,
    autorepeat_remaining,
    autorepeat_stop,
    plugin_base,
    value_function_disabled_enabled,
    value_function_gain_offset,
    value_function_gen4time,
    value_function_gen23time,
    value_function_grid_export,
    value_function_grid_import,
    value_function_pv_power_total,
    value_function_rtc,
    value_function_sync_rtc,
    value_str_default,
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
FIT = AC | HYBRID  # X1-FIT: AC-coupled hardware but uses Hybrid register layout for some GEN3 registers
ALL_TYPE_GROUP = PV | AC | HYBRID | MIC | MAX

EPS = 0x8000
ALL_EPS_GROUP = EPS

DCB = 0x10000  # dry contact box - gen4
ALL_DCB_GROUP = DCB

PM = 0x20000
ALL_PM_GROUP = PM

# ============================================================================
# Plugin-Level Register Validation
# ============================================================================


def _validation_cache(datadict: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a per-hub cache stored inside the hub data dict."""
    cache = datadict.get("_validation_cache")
    if not isinstance(cache, dict):
        cache = {}
        datadict["_validation_cache"] = cache
    scoped = cache.get(key)
    if not isinstance(scoped, dict):
        scoped = {}
        cache[key] = scoped
    return scoped


def validate_register_data(descr: Any, value: Any, datadict: dict[str, Any]) -> Any:
    """Validate register values for corruption.

    - PM U32 sensors: detect 0xFFFFFF00 overflow pattern and use last known value.
    - battery_capacity: treat zero SoC as invalid and use last known value.
    """
    pm_last_known_values = _validation_cache(datadict, "pm_last_known_values")
    soc_last_known_values = _validation_cache(datadict, "soc_last_known_values")

    if descr.key == "battery_capacity":
        try:
            soc_value = float(value) if value is not None else None
        except (TypeError, ValueError):
            soc_value = None

        if soc_value is not None and soc_value == 0:
            last_value = soc_last_known_values.get(descr.key)
            if last_value is not None and last_value > 5:
                # Only treat zero as invalid when a real SoC was seen before.
                _LOGGER.warning(f"SoC zero reading for {descr.key} -> using last: {last_value}%")
                return last_value
            return value

        if soc_value is not None and soc_value > 0:
            soc_last_known_values[descr.key] = value

    # PM U32 sensors only (filter by key prefix)
    if descr.key.startswith("pm_") and descr.register_data_type == REGISTER_U32:
        # Handle None from core errors
        if value is None:
            last_value = pm_last_known_values.get(descr.key, 0)
            _LOGGER.warning(f"PM sensor {descr.key} received None -> using last: {last_value}W")
            return last_value

        # Handle U32 overflow pattern
        if value >= 0xFFFFFF00:
            last_value = pm_last_known_values.get(descr.key, 0)
            _LOGGER.warning(f"PM U32 overflow {descr.key}: 0x{value:08X} -> using last: {last_value}W")
            return last_value

        # Store valid values for future use
        pm_last_known_values[descr.key] = value

    return value


MPPT3 = 0x40000
MPPT4 = 0x80000
MPPT5 = 0x100000
MPPT6 = 0x200000
MPPT8 = 0x400000
MPPT10 = 0x800000
ALL_MPPT_GROUP = MPPT3 | MPPT4 | MPPT5 | MPPT6 | MPPT8 | MPPT10

ALLDEFAULT = 0  # should be equivalent to AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES: Sequence["SolaXModbusSensorEntityDescription"] = []

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub: Any, address: int) -> str | None:
    res = None
    inverter_data = None
    try:
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=7)
        if inverter_data is not None and not inverter_data.isError():
            # Decode 7 registers (14 bytes) as string using clientless compat helper
            raw = convert_from_registers(inverter_data.registers[0:7], DataType.STRING, "big")  # type: ignore[attr-defined]  # DataType enum dynamic
            res = raw.decode("ascii", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            hub.seriesnumber = res
    except Exception:
        _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x} data: {inverter_data}", exc_info=True)
    if not res:
        _LOGGER.warning(f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed")
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number: {res}")
    return res


def _ensure_hub_data(hub: Any) -> dict[str, Any]:
    """Return hub.data, creating it for lightweight test hubs."""
    data = getattr(hub, "data", None)
    if not isinstance(data, dict):
        data = {}
        hub.data = data
    return data


async def async_read_modbus_protocol_version(hub: Any) -> int:
    """Read the Modbus protocol document version used for register-map gating."""
    data = _ensure_hub_data(hub)
    version = 0
    inverter_data = None
    try:
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=0x82, count=1)
        if inverter_data is not None and not inverter_data.isError():
            version = int(inverter_data.registers[0])
    except Exception:
        _LOGGER.debug(f"{hub.name}: attempt to read Modbus protocol version failed data: {inverter_data}", exc_info=True)

    if 0 < version < 1000:
        hub.modbus_protocol_version = version
        data["modbus_protocol_version"] = version
        _LOGGER.info(f"{hub.name}: Modbus protocol document version detected: {version}")
        return version

    hub.modbus_protocol_version = None
    data.pop("modbus_protocol_version", None)
    _LOGGER.debug(f"{hub.name}: Modbus protocol document version unavailable")
    return 0


async def async_read_inverter_firmware_info(hub: Any) -> int:
    """Read early firmware metadata used for device info and protocol-specific register maps."""
    data = _ensure_hub_data(hub)
    version = 0
    inverter_data = None
    try:
        # 0x7D..0x84 are legacy-safe firmware registers. Do not include 0x7B/0x7C here:
        # older maps may not expose the full-version registers and could reject the whole block.
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=0x7D, count=8)
        if inverter_data is not None and not inverter_data.isError():
            registers = inverter_data.registers
            data["firmware_dsp"] = int(registers[0])
            data["firmware_DSP_hardware_version"] = int(registers[1])
            data["firmware_dsp_major"] = int(registers[2])
            data["firmware_arm_major"] = int(registers[3])
            version = int(registers[5])
            data["firmware_arm"] = int(registers[6])
            data["bootloader_version"] = int(registers[7])
    except Exception:
        _LOGGER.debug(f"{hub.name}: attempt to read inverter firmware info failed data: {inverter_data}", exc_info=True)

    if 0 < version < 1000:
        hub.modbus_protocol_version = version
        data["modbus_protocol_version"] = version
        _LOGGER.info(f"{hub.name}: Modbus protocol document version detected: {version}")
    else:
        hub.modbus_protocol_version = None
        data.pop("modbus_protocol_version", None)
        data.pop("firmware_version_dsp", None)
        data.pop("firmware_version_arm", None)
        _LOGGER.debug(f"{hub.name}: Modbus protocol document version unavailable")
        return 0

    if version >= 100:
        full_version_data = None
        try:
            full_version_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=0x7B, count=2)
            if full_version_data is not None and not full_version_data.isError():
                data["firmware_version_dsp"] = int(full_version_data.registers[0])
                data["firmware_version_arm"] = int(full_version_data.registers[1])
        except Exception:
            _LOGGER.debug(f"{hub.name}: attempt to read full firmware version failed data: {full_version_data}", exc_info=True)
    else:
        data.pop("firmware_version_dsp", None)
        data.pop("firmware_version_arm", None)

    return version


# =================================================================================================


@dataclass(kw_only=True, frozen=True)
class SolaxModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass(kw_only=True, frozen=True)
class SolaxModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass(kw_only=True, frozen=True)
class SolaxModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass(kw_only=True, frozen=True)
class SolaXModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    order32: str | None = None  # optional per-sensor 32-bit word order override
    register_data_type: str = REGISTER_U16
    register_type: int = REG_HOLDING


@dataclass(kw_only=True, frozen=True)
class SolaXModbusSwitchEntityDescription(BaseModbusSwitchEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass(kw_only=True, frozen=True)
class SolaXModbusTimeEntityDescription(BaseModbusTimeEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    register_data_type: str = REGISTER_U16
    register_type: int = REG_HOLDING


# ====================================== Computed value functions  =================================================


def autorepeat_function_remotecontrol_recompute(initval: int, descr: Any, datadict: dict[str, Any]) -> dict[str, Any]:
    """Remote control power calculations for SolaX inverters - Redesigned Implementation.

    This function implements the redesigned remote control calculations based on clear
    variable names and logical formulas. For detailed documentation, see:
    docs/solax-remote-control-redesigned.md

    Args:
        initval: BUTTONREPEAT_FIRST (first run), BUTTONREPEAT_LOOP (subsequent runs),
                or BUTTONREPEAT_POST (cleanup)
        descr: Entity description
        datadict: Current sensor data dictionary

    Returns:
        Dictionary with action and data for Modbus write operations
    """

    # terminate expiring loop by disabling remotecontrol
    if initval == BUTTONREPEAT_POST:
        return {"action": WRITE_MULTI_MODBUS, "data": [("remotecontrol_power_control", "Disabled")]}

    # Get control parameters
    power_control = datadict.get("remotecontrol_power_control", "Disabled")
    set_type = datadict.get("remotecontrol_set_type", "Set")
    target = datadict.get("remotecontrol_active_power", 0)
    reactive_power = datadict.get("remotecontrol_reactive_power", 0)
    rc_duration = datadict.get("remotecontrol_duration", 20)
    reap_up = datadict.get("reactive_power_upper", 0)
    reap_lo = datadict.get("reactive_power_lower", 0)
    import_limit = datadict.get("remotecontrol_import_limit", 20000)
    export_limit = datadict.get("export_control_user_limit", 20000)
    rc_timeout = datadict.get("remotecontrol_timeout", 0)

    # Get power measurements
    measured_power = datadict.get("measured_power", 0)  # Grid power (positive = import, negative = export)
    battery_capacity = datadict.get("battery_capacity", 0)

    # Parallel mode support: Use PM power if in parallel mode and we're the Master
    parallel_setting = datadict.get("parallel_setting", "Free")

    if parallel_setting == "Master":
        # Use PM (Parallel Mode) total calculated sensors
        pv_power = datadict.get("pm_total_pv_power", 0)
        inverter_power = datadict.get("pm_total_inverter_power", 0)
        battery_power_charge = datadict.get("pm_battery_power_charge", 0)
        house_load = datadict.get("pm_total_house_load", 0)  # Use the calculated PM house load

        _LOGGER.debug(
            "[REMOTE_CONTROL] Parallel mode detected (Master): "
            f"PM total inverter={inverter_power}W, PM total PV={pv_power}W, "
            f"PM battery={battery_power_charge}W, PM house_load={house_load}W"
        )
    elif parallel_setting == "Slave":
        # Slaves should not execute remote control
        _LOGGER.debug("[REMOTE_CONTROL] Parallel mode detected (Slave): skipping remote control")
        return {"action": WRITE_MULTI_MODBUS, "data": []}
    else:
        # Single inverter mode - use individual values
        pv_power = datadict.get("pv_power_total", 0)
        inverter_power = datadict.get("inverter_power", 0)
        battery_power_charge = datadict.get("battery_power_charge", 0)
        house_load = inverter_power - measured_power  # Single inverter house load calculation

        _LOGGER.debug(
            "[REMOTE_CONTROL] Single inverter mode: "
            f"inverter_power={inverter_power}W, pv_power={pv_power}W, "
            f"battery_power_charge={battery_power_charge}W, house_load={house_load}W"
        )

    # Debug logging: Input state
    _LOGGER.debug(
        "[REMOTE_CONTROL] Input state: "
        f"power_control={power_control} target={target}W "
        f"import_limit={import_limit}W export_limit={export_limit}W "
        f"measured_power={measured_power}W pv_power={pv_power}W "
        f"house_load={house_load}W battery_capacity={battery_capacity}%"
    )

    # Calculate ap_target based on control mode
    if power_control == "Enabled Power Control":
        # Direct power control - set exact grid power
        ap_target = target

    elif power_control == "Enabled Grid Control":
        # Control grid import/export while accounting for house load
        if target < 0:  # Export target
            ap_target = target - house_load  # Export target minus house load
        else:  # Import target
            ap_target = target - house_load  # Import target minus house load (house load already supplied by inverter)
        power_control = "Enabled Power Control"

    elif power_control == "Enabled Self Use":
        # Minimize grid usage by using PV and battery to supply house load
        ap_target = 0 - house_load
        power_control = "Enabled Power Control"

    elif power_control == "Enabled Battery Control":
        # Control battery charging/discharging to target
        ap_target = target - pv_power  # + house_load ... already accounted for by the inverter
        power_control = "Enabled Power Control"

    elif power_control == "Enabled Feedin Priority":
        # Maximize grid export by using excess PV and battery
        if pv_power > house_load:
            # If more power than house load, try to export all excess
            # power. If this is larger than the inverter/export limit
            # it will be internally limited and any excess PV will go
            # to the battery.
            ap_target = 0 - pv_power
        else:
            # Insufficient power from PV, so just cover house load. The
            # battery will discharge to cover any deficit where possible.
            # If the battery is drained completely, grid will cover deficit.
            ap_target = 0 - house_load
        power_control = "Enabled Power Control"

    elif power_control == "Enabled No Discharge":
        # Hold battery level by preventing discharge
        if battery_capacity < 98:
            # Use PV to supply house load, import from grid only what's needed
            # Any excess PV above house load will go to the battery
            ap_target = 0 - min(house_load, pv_power)
        else:
            # When the battery is fully charged (allowing a tolerance to prevent
            # older inverters shutting down PV), then we emulate self-use mode
            # by simply pushing all PV power through the grid connected port
            ap_target = 0 - pv_power
        power_control = "Enabled Power Control"

    else:
        # Otherwise disabled or unknown mode. Mark as disabled.
        power_control = "Disabled"
        ap_target = target

    # Debug logging: Target calculation
    _LOGGER.debug(f"[REMOTE_CONTROL] Target calculation: mode={power_control} ap_target={ap_target}W")

    # Phase envelope protection: Calculate safe ap_target based on phase limits
    # Get phase-specific data
    measured_power_l1: int | float | None = datadict.get("measured_power_l1", None)
    measured_power_l2: int | float | None = datadict.get("measured_power_l2", None)
    measured_power_l3: int | float | None = datadict.get("measured_power_l3", None)
    grid_voltage_l1: int | float | None = datadict.get("grid_voltage_l1", None)
    grid_voltage_l2: int | float | None = datadict.get("grid_voltage_l2", None)
    grid_voltage_l3: int | float | None = datadict.get("grid_voltage_l3", None)
    main_breaker_current_limit: int | float | None = datadict.get("main_breaker_current_limit", None)

    safe_ap_target_from_phase = None  # Initialize
    safe_ap_target_export_from_phase = None

    if (
        all(p is not None for p in [measured_power_l1, measured_power_l2, measured_power_l3])
        and all(v is not None and v > 0 for v in [grid_voltage_l1, grid_voltage_l2, grid_voltage_l3])
        and main_breaker_current_limit is not None
        and main_breaker_current_limit > 0
    ):
        # Type narrowing for mypy
        assert measured_power_l1 is not None and measured_power_l2 is not None and measured_power_l3 is not None
        assert grid_voltage_l1 is not None and grid_voltage_l2 is not None and grid_voltage_l3 is not None
        assert main_breaker_current_limit is not None

        # Calculate house load per phase using imbalance
        # Imbalance in measured_power = imbalance in house load (inverters balance)
        avg_measured_power = (measured_power_l1 + measured_power_l2 + measured_power_l3) / 3
        house_load_l1_W = (house_load / 3) + (avg_measured_power - measured_power_l1)
        house_load_l2_W = (house_load / 3) + (avg_measured_power - measured_power_l2)
        house_load_l3_W = (house_load / 3) + (avg_measured_power - measured_power_l3)

        # Convert to current
        house_current_l1 = house_load_l1_W / grid_voltage_l1
        house_current_l2 = house_load_l2_W / grid_voltage_l2
        house_current_l3 = house_load_l3_W / grid_voltage_l3

        # Calculate measured phase currents for comparison
        measured_current_l1 = abs(measured_power_l1) / grid_voltage_l1
        measured_current_l2 = abs(measured_power_l2) / grid_voltage_l2
        measured_current_l3 = abs(measured_power_l3) / grid_voltage_l3

        # Find worst phase
        house_currents = [house_current_l1, house_current_l2, house_current_l3]
        worst_phase_house_current = max(house_currents)
        worst_phase_idx = house_currents.index(worst_phase_house_current)
        [grid_voltage_l1, grid_voltage_l2, grid_voltage_l3][worst_phase_idx]

        _LOGGER.debug(
            f"[REMOTE_CONTROL] Phase currents - Measured: L1={measured_current_l1:.2f}A L2={measured_current_l2:.2f}A L3={measured_current_l3:.2f}A | "
            f"House: L1={house_current_l1:.2f}A L2={house_current_l2:.2f}A L3={house_current_l3:.2f}A | "
            f"worst=L{worst_phase_idx + 1}"
        )

        # Calculate safe ap_target for IMPORTS to keep worst phase below 59.85A
        # worst_phase: house_current + (ap_target_current / 3) ≤ 59.85A
        # Solve: ap_target ≤ (59.85A - house_current) × 3 × avg_voltage
        max_phase_current_limit = main_breaker_current_limit * 0.95  # 59.85A
        remaining_current_A = max_phase_current_limit - worst_phase_house_current

        if remaining_current_A > 0:
            avg_voltage = (grid_voltage_l1 + grid_voltage_l2 + grid_voltage_l3) / 3
            safe_ap_target_from_phase = remaining_current_A * 3 * avg_voltage

            _LOGGER.debug(
                f"[REMOTE_CONTROL] Phase protection (import): L{worst_phase_idx + 1} house={worst_phase_house_current:.2f}A "
                f"limit={max_phase_current_limit:.2f}A remaining={remaining_current_A:.2f}A "
                f"safe_ap_target={safe_ap_target_from_phase:.1f}W"
            )
        else:
            safe_ap_target_from_phase = 0
            _LOGGER.warning(
                f"[REMOTE_CONTROL] Phase protection (import): L{worst_phase_idx + 1} house={worst_phase_house_current:.2f}A "
                f"at or above limit {max_phase_current_limit:.2f}A - blocking imports"
            )

        # Calculate safe ap_target for EXPORTS to keep best phase below 59.85A
        # For exports, phase with LOWEST house load exports MOST
        # best_phase (min house): (export_current / 3) - house_current ≤ 59.85A
        # Solve: export_current ≤ (59.85A + house_current) × 3
        # ap_target = -export_current, so: ap_target ≥ -(59.85A + min_house_current) × 3 × avg_voltage
        min_phase_house_current = min(house_currents)
        best_phase_idx = house_currents.index(min_phase_house_current)

        # Maximum export current that keeps best phase below limit
        max_export_current_per_phase = max_phase_current_limit + min_phase_house_current
        safe_export_total_current = max_export_current_per_phase * 3
        safe_ap_target_export_from_phase = -(safe_export_total_current * avg_voltage)

        _LOGGER.debug(
            f"[REMOTE_CONTROL] Phase protection (export): L{best_phase_idx + 1} house={min_phase_house_current:.2f}A "
            f"(lowest) limit={max_phase_current_limit:.2f}A "
            f"safe_ap_target={safe_ap_target_export_from_phase:.1f}W (negative)"
        )

    # Apply bounds checking based on ap_target sign
    old_ap_target = ap_target
    if ap_target > 0:
        # Importing (positive = import)
        # Inverter input cannot be more than the import limit less any used by the house load
        import_bound = import_limit - house_load

        # Apply phase protection limit if available
        if safe_ap_target_from_phase is not None:
            import_bound = min(import_bound, safe_ap_target_from_phase)

        ap_target = min(ap_target, import_bound)
        _LOGGER.debug(
            f"[REMOTE_CONTROL] Import bounds: ap_target={ap_target}W import_bound={import_bound}W "
            f"import_limit={import_limit}W house_load={house_load}W total_import={ap_target + house_load}W"
        )
    elif ap_target < 0:
        # Exporting (negative = export).
        # Inverter output cannot be more than the export limit plus any used by the house load
        export_bound = -(export_limit + house_load)

        # Apply phase protection limit if available
        if safe_ap_target_export_from_phase is not None:
            export_bound = max(export_bound, safe_ap_target_export_from_phase)

        ap_target = max(ap_target, export_bound)
        _LOGGER.debug(
            f"[REMOTE_CONTROL] Export bounds: ap_target={ap_target}W export_bound={export_bound}W "
            f"export_limit={export_limit}W house_load={house_load}W"
        )
    # If ap_target = 0, no bounds checking needed

    # Debug logging: Bounds checking
    if old_ap_target != ap_target:
        _LOGGER.debug(
            "[REMOTE_CONTROL] Bounds checking: "
            f"initial_ap_target={old_ap_target}W final_ap_target={ap_target}W "
            f"adjusted_by={old_ap_target - ap_target}W"
        )

    # Prepare result data
    res = [
        ("remotecontrol_power_control", power_control),
        ("remotecontrol_set_type", set_type),
        ("remotecontrol_active_power", ap_target),
        ("remotecontrol_reactive_power", max(min(reap_up, reactive_power), reap_lo)),
        ("remotecontrol_duration", rc_duration),
        (REGISTER_U16, 0),  # dummy target soc
        (REGISTER_U32, 0),  # dummy target energy Wh
        (REGISTER_S32, 0),  # dummy target charge/discharge power
        ("remotecontrol_timeout", rc_timeout),
    ]

    if power_control == "Disabled":
        autorepeat_stop(datadict, "remotecontrol_trigger")

    _LOGGER.debug(f"Evaluated remotecontrol_trigger: corrected/clamped values: {res}")
    return {"action": WRITE_MULTI_MODBUS, "data": res}


def autorepeat_bms_charge(datadict: dict[str, Any], battery_capacity: float, max_charge_soc: float, available: float) -> tuple[int, int, int, int]:
    # Determines max rate for charging battery

    # User cap (% of BMS max charge power).
    factor_pct = datadict.get("export_first_battery_charge_limit_8_9", 100)
    try:
        f = max(0.0, min(1.0, float(factor_pct) / 100.0))
    except Exception:
        f = 1.0

    # Near full charge rate limit
    chargeable_soc = max(0, max_charge_soc - battery_capacity)
    if chargeable_soc <= 4:
        # For last few % of charge, further reduce the rate limit to account
        # for non-ideal charging curves and reduce battery wear
        f = f * (float(chargeable_soc + 2.0) / 6.0)

    # BMS charge capability approximation
    bms_a = datadict.get("bms_charge_max_current", None)
    batt_v = (
        datadict.get("battery_1_voltage_charge", None)
        or datadict.get("battery_2_voltage_charge", None)
        or datadict.get("battery_voltage_charge", None)
    )
    if isinstance(bms_a, (int, float)) and isinstance(batt_v, (int, float)) and bms_a > 0 and batt_v > 0:
        bms_cap_w = int(bms_a * batt_v)
    else:
        reg_a = datadict.get("battery_charge_max_current", 20)
        bms_cap_w = int(reg_a * (batt_v if isinstance(batt_v, (int, float)) and batt_v > 0 else 360))

    # Cap BMS charge to user defined percentage. f is in range 0-1 so this is always same or lower
    pct_cap_w = int(f * bms_cap_w)

    # If battery can be charged
    if battery_capacity < max_charge_soc:
        # Limit to charge rate to lesser of the available
        # power and the %age capped charge limit.
        max_charge = int(max(0, pct_cap_w))
        desired_charge = int(max(0, min(available, pct_cap_w)))
    else:
        # Can't charge the battery
        max_charge = 0
        desired_charge = 0

    return desired_charge, max_charge, bms_cap_w, pct_cap_w


def autorepeat_setpoint_filter(current_value: int, desired_value: int, steps: int = 5) -> int:
    # Simple rolling average filter for updating control setpoints to avoid oscillation
    return int((current_value * (steps - 1) + desired_value) / steps)


def autorepeat_function_powercontrolmode8_recompute(initval: int, descr: Any, datadict: dict[str, Any]) -> dict[str, Any]:
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
    set_type = datadict.get("remotecontrol_set_type", "Set")  # Set for simplicity; otherwise First time should be Set, subsequent times Update
    setpvlimit = datadict.get("remotecontrol_pv_power_limit", 10000)
    pushmode_power = datadict.get("remotecontrol_push_mode_power_8_9", 0)
    target_soc = datadict.get("remotecontrol_target_soc_8_9", 95)
    # rc_duration = datadict.get("remotecontrol_duration", 20)
    import_limit = datadict.get("remotecontrol_import_limit", 20000)
    battery_capacity = datadict.get("battery_capacity", 0)
    rc_timeout = datadict.get("remotecontrol_timeout", 2)
    timeout_motion = datadict.get("remotecontrol_timeout_next_motion", "VPP Off")
    pv = datadict.get("pv_power_total", 0)
    houseload = value_function_house_load(initval, descr, datadict)
    houseload_alt = value_function_house_load_alt(initval, descr, datadict)

    # Disallow parallel mode for now
    parallel_setting = datadict.get("parallel_setting", "Free")
    if parallel_setting != "Free":
        _LOGGER.warning("Mode 8 autorepeat is not currently supported for inverters where parallel mode != Free. Disabling remote control.")
        power_control = "Disabled"

    if power_control == "Mode 8 - PV and BAT control - Duration":
        pvlimit = setpvlimit  # import capping is done later
    elif power_control == "Negative Injection Price":
        # --- Negative Injection Price (Mode 8 custom) ---
        # Controller goals:
        # 1) If PV < house load (deficit): discharge the battery up to the deficit (respecting min SOC),
        #    aiming to prefer a slight grid import bias over export bias.
        # 2) If PV ≥ house load (surplus): let PV feed the battery first. PV limit is then adjusted using
        #    bounded step changes based on the measured power to prevent export.
        # 3) Use Target SoC as an upper limit for charging the battery. Once that is reached, limit PV
        #    output to prevent further charging and export.

        # Use the alternative house load for house load measurement, clamping to strict positive values.
        hl = max(0, int(houseload_alt))

        # SOC bounds
        min_discharge_soc = datadict.get("selfuse_discharge_min_soc", 10)
        max_charge_soc = min(target_soc, datadict.get("battery_charge_upper_soc", 100))
        charge_soc_hysteresis = datadict.get("negative_injection_battery_hysteresis", 2)
        # bias towards import
        export_target = int(datadict.get("negative_injection_bias_w", -50) or -50)
        export_deadband_w = int(datadict.get("export_feedback_deadband_w", 50) or 50)
        pv_unlimited_step = int(datadict.get("pv_unlimited_delta_w", 1000) or 1000)

        # Local copies
        battery_charge = max(0, int(datadict.get("battery_power_charge", 0) or 0))
        pvlimit = setpvlimit
        pv_threshold = pv + pv_unlimited_step  # point at which PV is considered to be not actively limited
        cur_pvlimit = max(0, setpvlimit if (cur_pvlimit := datadict.get("remotecontrol_current_pv_power_limit", None)) is None else cur_pvlimit)
        cur_push = (-battery_charge) if (cur_push := datadict.get("remotecontrol_current_pushmode_power", None)) is None else cur_push
        pushmode_power = 0  # + = discharge, - = charge
        current_charge = -cur_push

        # Debug inputs
        _LOGGER.debug(
            f"[Mode8 Negative Injection] inputs pv={pv}W hl={houseload}W hl_alt={houseload_alt}W (using hl) imp_lim={import_limit}W "
            f"soc={battery_capacity}% min_soc={min_discharge_soc}% max_soc={max_charge_soc}% cur_pvlimit={cur_pvlimit}W "
            f"last_push={cur_push}W battery_charge={battery_charge}W"
        )

        # Optional probes (if available)
        measured_power = datadict.get("measured_power", None)
        _LOGGER.debug(f"[Mode8 Negative Injection] probes: measured_power={measured_power if measured_power is not None else 'n/a'} ")

        if pv >= hl or cur_pvlimit < min(setpvlimit, pv_threshold):
            # Surplus or limited pv path: battery is requested to charge at up to the rate
            # limit from PV alone then use measured export as the control signal to adjust PV limit.
            # Below target: PV should be reduced to prevent export.
            # At/above target: PV can be increased to reduce import in bounded steps.
            # If PV is being actively limited, continue in this loop to release PV restriction slowly.
            measured_power = int(measured_power or 0)
            surplus = current_charge + measured_power - export_target
            control_state = "surplus" if pv >= hl else "clipping"

            # Battery gets surplus up to BMS limit
            desired_charge, max_charge, bms_cap_w, pct_cap_w = autorepeat_bms_charge(datadict, battery_capacity, max_charge_soc, surplus)

            # Setpoint filter to slow down changes to battery
            selected_charge = autorepeat_setpoint_filter(current_charge, desired_charge)
            pushmode_power = -selected_charge

            # Any surplus not able to feed into the battery needs to be corrected through PV limiting
            error = surplus - selected_charge

            if abs(error) <= export_deadband_w:
                target_pvlimit = cur_pvlimit
                if desired_charge < max_charge and battery_capacity < max_charge_soc - charge_soc_hysteresis:
                    # If the battery can be charged more than it currently is being, then once stable
                    # allow the limit to be increased to see if we can absorb more output from the PV,
                    # but only if the battery has plenty of headroom to absorb an increase.
                    control_reason = "hold-increase-pv"
                    target_pvlimit = min(setpvlimit, cur_pvlimit + (max_charge - desired_charge))
                else:
                    # Otherwise hold
                    control_reason = "hold"
                    target_pvlimit = cur_pvlimit
            elif error > 0:
                if cur_pvlimit > pv_threshold:
                    # If the current PV limit is above any active PV limiting, then we will make
                    # a much larger step to allow for a faster response. Otherwise the steps will
                    # not actually achieve anything for several loops.
                    cur_pvlimit = pv_threshold
                    control_reason = "error-decrease-pv-fast"
                else:
                    control_reason = "error-decrease-pv"
                target_pvlimit = max(0, cur_pvlimit - error)
            else:
                target_pvlimit = min(setpvlimit, cur_pvlimit - error)
                control_reason = "error-increase-pv"

            # Filter the setpoint to avoid oscillation
            pvlimit = autorepeat_setpoint_filter(cur_pvlimit, target_pvlimit)

            _LOGGER.debug(
                f"[Mode8 Negative Injection] {control_state}: surplus={surplus}W measured_power={measured_power}W "
                f"export_target={export_target}W error={error}W pvtarget={target_pvlimit}W reason={control_reason} "
                f"bms_cap≈{bms_cap_w}W pct_cap={pct_cap_w}W desired_charge={desired_charge}W -> charge={selected_charge}W "
                f"pvlimit={pvlimit}W hl={hl}W"
            )

        else:
            # Deficit path: discharge battery up to the current house deficit (if SOC allows).
            # Note this is only reached if pvlimit has been restored to above the house load by
            # the limited pv path and we therefore have insufficient PV to cover the load.
            deficit = hl + export_target - pv
            if battery_capacity > min_discharge_soc:
                desired_charge = -min(deficit, 30000)
                selected_charge = autorepeat_setpoint_filter(current_charge, desired_charge)
                pushmode_power = -selected_charge
            else:
                desired_charge = 0
                pushmode_power = 0
            _LOGGER.debug(
                f"[Mode8 Negative Injection] deficit: deficit={deficit}W export_target={export_target}W "
                f"soc={battery_capacity}% desired_charge={desired_charge}W -> chosen_push={pushmode_power}W"
            )
    elif power_control == "Negative Injection and Consumption Price":
        # Disables PV and charges as fast as possible from the grid
        pvlimit = 0
        # Set maximum charge limit, respecting optional target SoC
        max_charge_soc = min(target_soc, datadict.get("battery_charge_upper_soc", 100))
        # Determine currently requested charge rate to allow filtering
        battery_charge = max(0, int(datadict.get("battery_power_charge", 0) or 0))
        cur_push = (-battery_charge) if (cur_push := datadict.get("remotecontrol_current_pushmode_power", None)) is None else cur_push
        current_charge = -cur_push
        # Debug inputs
        _LOGGER.debug(
            f"[Mode8 Negative Injection and Consumption Price] inputs hl={houseload}W hl_alt={houseload_alt}W (using hl) imp_lim={import_limit}W "
            f"soc={battery_capacity}% max_soc={max_charge_soc}% last_push={current_charge}W battery_charge={battery_charge}W"
        )
        # Use the alternative house load for house load measurement, clamping to strict positive values,
        # to determine maximum available power from the grid
        hl = max(0, int(houseload_alt))
        available = max(import_limit - hl, 0)
        # Request maximum allowed charge rate based on current SoC
        desired_charge, max_charge, bms_cap_w, pct_cap_w = autorepeat_bms_charge(datadict, battery_capacity, max_charge_soc, available)
        # Setpoint filter to slow down changes to battery
        selected_charge = autorepeat_setpoint_filter(current_charge, desired_charge)
        pushmode_power = -selected_charge

        _LOGGER.debug(
            f"[Mode8 Negative Injection and Consumption Price] charge: available={available}W within_bms={max_charge}W "
            f"bms_cap≈{bms_cap_w}W pct_cap={pct_cap_w}W -> charge={desired_charge}W"
        )
    elif power_control == "Enabled Feedin Priority":
        pvlimit = setpvlimit
        pushmode_power = max(houseload - pv, 0.0)
    elif power_control == "Enabled No Discharge":
        # --- Battery No-Discharge (Mode 8 custom)
        # Split PV surplus into (a) battery charging up to charge rate limit (b) grid export if any excess
        # In deficit (house load > PV), prevent battery discharge, making up difference by importing from grid

        # Export limit no readscale:
        export_limit = datadict.get("export_control_user_limit", 30000)

        # SOC bounds
        max_charge_soc = datadict.get("battery_charge_upper_soc", 100)

        # Local copies
        pvlimit = setpvlimit
        pushmode_power = 0  # + = discharge, - = charge

        # Debug inputs
        _LOGGER.debug(f"[Mode8 No-Discharge] inputs pv={pv}W hl={houseload}W soc={battery_capacity}% max_soc={max_charge_soc}% pvlimit={pvlimit}W")

        # Surplus path: charge battery (within BMS and user cap), exporting any excess.
        if pv >= houseload:
            surplus = pv - houseload

            # Battery gets surplus PV up to BMS limit
            desired_charge, max_charge, bms_cap_w, pct_cap_w = autorepeat_bms_charge(datadict, battery_capacity, max_charge_soc, surplus)
            pushmode_power = -desired_charge

            # If there is any left over, it goes to the grid
            surplus_export = max(0, surplus - desired_charge)
            export_within_cap = min(export_limit, surplus_export)
            if surplus_export > export_limit:
                # Unless we've exceeded the export limit, in which case limit the PV too
                pvlimit = pv - (surplus_export - export_limit)
                surplus_export = export_limit

            _LOGGER.debug(
                f"[Mode8 No-Discharge] charge-first: surplus={surplus}W within_bms={max_charge}W "
                f"surplus_export={surplus_export}W within_cap={export_within_cap}W pvlimit={pvlimit}W "
                f"bms_cap≈{bms_cap_w}W pct_cap={pct_cap_w}W -> charge={desired_charge}W"
            )

        else:
            # Deficit path: hold battery SoC
            deficit = houseload - pv

            pushmode_power = 0
            _LOGGER.debug(f"[Mode8 No-Discharge] deficit: deficit={deficit}W hold-soc={battery_capacity}% chosen_push={pushmode_power}W")

        # Final debug and state
        net_flow = min(pvlimit, pv) - houseload + pushmode_power
        _LOGGER.debug(f"[Mode8 No-Discharge] result: push={pushmode_power}W pvlimit={pvlimit}W net_flow={net_flow}W (>0 export, <0 import)")

    elif power_control == "Export-First Battery Limit":
        # --- Export-First Battery Limit (Mode 8 custom) ---
        # Controller goals (no PV limit adjustments in this mode):
        # 1) If PV < house load (deficit): discharge the battery up to the deficit (respecting min SOC).
        # 2) If PV ≥ house load (surplus): let PV feed the grid first and only charge the battery once
        #    measured export is at or above the configured cap. Battery charge is then adjusted using
        #    bounded step changes based on the measured export.
        # 3) Ensure that we don't exceed the inverter power limit in the calculations so that PV above
        #    this limit is allocated to the battery charge rather than being limited.

        # Use the alternative house load basis directly. The current house_load_alt
        # formula already subtracts battery charging, so subtracting it again here
        # would understate the effective load and distort the export target logic.
        battery_charge = max(0, int(datadict.get("battery_power_charge", 0) or 0))
        hl = max(0, int(houseload_alt))

        # Export limit no readscale:
        export_limit = datadict.get("export_control_user_limit", 30000)

        # Test mode: do not trim the export target by inverter power minus house load.
        # This lets Export-First try to use the configured export limit directly before charging the battery.
        export_available = export_limit

        # SOC bounds
        min_discharge_soc = datadict.get("selfuse_discharge_min_soc", 10)
        max_charge_soc = datadict.get("battery_charge_upper_soc", 100)
        # Keep a small gap below the inverter's own export cap so our loop does not
        # constantly fight the inverter's internal export limiter.
        export_margin_w = int(datadict.get("export_first_export_margin_w", 150) or 0)
        export_target = max(0, export_limit - export_margin_w)
        export_deadband_w = int(datadict.get("export_feedback_deadband_w", 50) or 50)
        min_step_w = int(datadict.get("export_first_step_min_w", 100) or 100)
        max_step_w = int(datadict.get("export_feedback_max_w", 500) or 500)

        # Local copies
        pvlimit = max(0, datadict.get("remotecontrol_pv_power_limit", 30000))
        last_push = datadict.get("_mode8_last_push", 0)
        pushmode_power = 0  # + = discharge, - = charge

        # Debug inputs
        _LOGGER.debug(
            f"[Mode8 Export-First] inputs pv={pv}W hl={houseload}W hl_alt={houseload_alt}W (using hl) exp_lim={export_limit}W "
            f"exp_avail={export_available}W exp_target={export_target}W imp_lim={import_limit}W soc={battery_capacity}% "
            f"min_soc={min_discharge_soc}% max_soc={max_charge_soc}% pvlimit={pvlimit}W last_push={last_push}W "
            f"battery_charge={battery_charge}W"
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

        if pv >= hl:
            # Surplus path: use measured export as the control signal.
            # Below target: battery should not charge and may need to back off existing charge.
            # At/above target: battery can absorb the excess in bounded steps.
            surplus = pv - hl
            current_charge = max(0, -int(last_push))
            measured_export = int(grid_export_s or 0)
            error = measured_export - export_target

            # Extract BMS/user charge caps once; control law below only changes the requested charge.
            _, max_charge, bms_cap_w, pct_cap_w = autorepeat_bms_charge(datadict, battery_capacity, max_charge_soc, 10**9)

            if battery_capacity >= max_charge_soc:
                desired_charge = 0
                step_w = 0
                control_reason = "battery-full"
            elif abs(error) <= export_deadband_w:
                desired_charge = current_charge
                step_w = 0
                control_reason = "hold"
            elif error > 0:
                step_w = min(max_step_w, max(min_step_w, error))
                desired_charge = current_charge + step_w
                control_reason = "increase-charge"
            else:
                step_w = min(max_step_w, max(min_step_w, -error))
                desired_charge = max(0, current_charge - step_w)
                control_reason = "decrease-charge"

            desired_charge = int(min(desired_charge, max_charge))
            pushmode_power = -desired_charge

            # Export-First in this mode should not directly clamp PV.
            pv_clamp_target = pvlimit

            _LOGGER.debug(
                f"[Mode8 Export-First] export-first: surplus={surplus}W measured_export={measured_export}W "
                f"target={export_target}W error={error}W step={step_w}W reason={control_reason} "
                f"bms_cap≈{bms_cap_w}W pct_cap={pct_cap_w}W -> charge={desired_charge}W pv_clamp_target={pv_clamp_target}W hl={hl}W"
            )

        else:
            # Deficit path: discharge battery up to the current house deficit (if SOC allows).
            deficit = max(0, hl - pv)
            if battery_capacity > min_discharge_soc:
                pushmode_power = min(deficit, 30000)
            else:
                pushmode_power = 0
            _LOGGER.debug(f"[Mode8 Export-First] deficit: deficit={deficit}W soc={battery_capacity}% chosen_push={pushmode_power}W")

        # If we still see export while discharging, trim discharge a bit.
        if pv < hl and pushmode_power > 0:
            try:
                measured_export = int(datadict.get("grid_export", 0) or 0)
            except Exception:
                measured_export = 0
            if measured_export > export_deadband_w:
                nudge = min(measured_export, max_step_w)
                pushmode_power = max(0, pushmode_power - nudge)
                _LOGGER.debug(
                    f"[Mode8 Export-First] discharge feedback: -{nudge}W (measured_export={measured_export}W) to reduce grid export while discharging"
                )

        # Safety: do not discharge above the instantaneous deficit.
        if pv < hl:
            deficit_now = hl - pv
            if pushmode_power > deficit_now:
                _LOGGER.debug(f"[Mode8 Export-First] clamp discharge to deficit: push={pushmode_power}W -> {deficit_now}W (pv={pv} hl={hl})")
                pushmode_power = deficit_now

        # Final debug and state
        net_flow = pv - hl + pushmode_power
        _LOGGER.debug(f"[Mode8 Export-First] result: push={pushmode_power}W pvlimit={pvlimit}W net_flow={net_flow}W (>0 export, <0 import)")
        datadict["_mode8_last_push"] = pushmode_power
    elif power_control == "Enabled Grid Control":
        pushmode_power = pushmode_power + houseload - pv
        pvlimit = setpvlimit
    else:
        # Otherwise disabled or unknown mode. Mark as disabled.
        power_control = "Disabled"
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
        # (
        #    "remotecontrol_duration",
        #    rc_duration,
        # ),
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
        _LOGGER.warning(f"autorepeat mode 8 changed curmode: {curmode}; battery: {battery_capacity}; mode: {power_control}")
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


def value_function_byteswapserial(initval: str, descr: Any, datadict: dict[str, Any]) -> str:
    if initval and not initval.startswith(("M", "X")):
        preswap = initval
        swapped = ""
        for pos in range(0, len(preswap), 2):
            swapped += preswap[pos + 1] + preswap[pos]
        return swapped
    return initval


def valuefunction_firmware_g3(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return f"3.{initval}"


def valuefunction_firmware_g4(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return f"1.{initval}"


def value_function_remotecontrol_autorepeat_remaining(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    mode_1to7 = autorepeat_remaining(datadict, "remotecontrol_trigger", time())
    mode_8to9 = autorepeat_remaining(datadict, "powercontrolmode8_trigger", time())
    return max(mode_1to7, mode_8to9)


def value_function_remotecontrol_current_pushmode_power(initval: int, descr: Any, datadict: dict[str, Any]) -> Any:
    # do not convert to int(); None is a valid value and is returned if VPP is inactive
    return datadict.get(descr.key, 0)


def value_function_remotecontrol_current_pv_power_limit(initval: int, descr: Any, datadict: dict[str, Any]) -> Any:
    # do not convert to int(); None is a valid value and is returned if VPP is inactive
    return datadict.get(descr.key, 0)


def value_function_battery_power_charge(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    return int(datadict.get("battery_1_power_charge", 0)) + int(datadict.get("battery_2_power_charge", 0))


def value_function_hardware_version_g1(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return "Gen1"


def value_function_hardware_version_g2(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return "Gen2"


def value_function_hardware_version_g3(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return "Gen3"


def value_function_hardware_version_g4(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return "Gen4"


def value_function_hardware_version_g5(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return "Gen5"


def value_function_hardware_version_g6(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return "Gen6"


def value_function_house_load(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    inverter_power = int(datadict.get("inverter_power", 0))
    measured_power = int(datadict.get("measured_power", 0))
    meter_2_power = int(datadict.get("meter_2_measured_power", 0))
    result = inverter_power - measured_power + meter_2_power

    _LOGGER.debug(
        "[HOUSE_LOAD] Calculation: "
        f"inverter_power={inverter_power}W "
        f"measured_power={measured_power}W "
        f"meter_2_power={meter_2_power}W "
        f"result={result}W "
        f"meter_1_direction={datadict.get('meter_1_direction', 'unknown')}"
    )

    return result


def value_function_house_load_alt(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    return int(
        datadict.get("pv_power_total", 0)
        - datadict.get("battery_power_charge", 0)
        - datadict.get("measured_power", 0)
        + datadict.get("meter_2_measured_power", 0)
    )


def value_function_inverter_power_g5(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    return int(datadict.get("inverter_power_l1", 0)) + int(datadict.get("inverter_power_l2", 0)) + int(datadict.get("inverter_power_l3", 0))


def value_function_pm_total_inverter_power(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    """Calculate total inverter power in parallel mode (sum of all phases)."""
    l1_power: int | float | None = datadict.get("pm_activepower_l1", 0)
    l2_power: int | float | None = datadict.get("pm_activepower_l2", 0)
    l3_power: int | float | None = datadict.get("pm_activepower_l3", 0)

    # Handle None values from overflow protection
    if l1_power is None:
        l1_power = 0
    if l2_power is None:
        l2_power = 0
    if l3_power is None:
        l3_power = 0

    return int(l1_power + l2_power + l3_power)


def value_function_pm_total_pv_power(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    """Calculate total PV power in parallel mode (sum of all inverters)."""
    pv_power_1: int | float | None = datadict.get("pm_pv_power_1", 0)
    pv_power_2: int | float | None = datadict.get("pm_pv_power_2", 0)

    # Handle None values from overflow protection
    if pv_power_1 is None:
        pv_power_1 = 0
    if pv_power_2 is None:
        pv_power_2 = 0

    return int(pv_power_1 + pv_power_2)


def value_function_pm_total_house_load(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    """
    Calculate total house load in parallel mode with delta correction.

    Why?
    SolaX inverters underreport the inverter power measurement during remote
    control. For example: This shows up as higher house load during battery
    charging from the grid. We can use the physics method to correct for this.

    How?
    We use two methods and apply correction during remote control. The two
    calculations allow us to normalize the inflaction by taking the midpoint
    of the delta:

    1. Inverter method: pm_power - grid_power
       (can be inflated during RC)
    2. Physics method: pv_power - grid_power - battery_power
       (energy conservation)

    During remote control, if the two methods differ by < 25%, split the difference
    to compensate for inverter measurement inflation.
    """
    # Get raw sensor values
    pm_inverter_power: int | float = (
        int(datadict.get("pm_activepower_l1", 0)) + int(datadict.get("pm_activepower_l2", 0)) + int(datadict.get("pm_activepower_l3", 0))
    )
    grid_power: int | float = datadict.get("measured_power", 0)
    pv_power: int | float = datadict.get("pm_total_pv_power", 0)
    battery_power: int | float = datadict.get("pm_battery_power_charge", 0)
    # Note: pm_battery_power_charge represents grid-to-battery charging only
    # It does NOT include PV contribution to battery charging

    # Method 1: Inverter-based calculation (inverter perspective)
    inverter_method = pm_inverter_power - grid_power

    # Method 2: Physics-based calculation (energy conservation: PV - Grid - Battery_from_grid = House)
    # Since battery_power is grid-to-battery only, this correctly calculates house load
    physics_method = pv_power - grid_power - battery_power

    # Apply delta correction during remote control if delta is reasonable (< 25%)
    rc_active = datadict.get("remotecontrol_active_power", 0)
    if rc_active != 0 and inverter_method != 0:
        delta = physics_method - inverter_method

        # Only apply if delta < 25% (large deltas indicate transition states)
        if abs(delta) <= abs(inverter_method) * 0.25:
            # Split the difference between the two methods
            return inverter_method - (delta / 2)

    # Default: use inverter method
    return inverter_method


def value_function_pm_total_reactive_or_apparentpower(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    """Calculate total reactive power in parallel mode (sum of all phases)."""
    return int(
        datadict.get("pm_reactive_or_apparentpower_l1", 0)
        + datadict.get("pm_reactive_or_apparentpower_l2", 0)
        + datadict.get("pm_reactive_or_apparentpower_l3", 0)
    )


def value_function_pm_total_inverter_current(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    """Calculate total inverter current in parallel mode (sum of all phases)."""
    return int(datadict.get("pm__current_l1", 0)) + int(datadict.get("pm__current_l2", 0)) + int(datadict.get("pm__current_l3", 0))


def value_function_pm_total_pv_current(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    """Calculate total PV current in parallel mode (sum of all PV inputs)."""
    pv_current_1: int | float | None = datadict.get("pm_pv_current_1", 0)
    pv_current_2: int | float | None = datadict.get("pm_pv_current_2", 0)

    # Handle None values from overflow protection
    if pv_current_1 is None:
        pv_current_1 = 0
    if pv_current_2 is None:
        pv_current_2 = 0

    return int(pv_current_1 + pv_current_2)


def value_function_battery_capacity_gen5(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    # Check if total capacity has a sane value, if so return that
    total_charge: int | float = datadict.get("battery_total_capacity_charge", 0)
    if total_charge > 0:
        return int(total_charge)
    # Otherwise try to use the correct battery capacity field
    bat1_charge: int | float = datadict.get("battery_1_capacity_charge", 0)
    bat2_charge: int | float = datadict.get("battery_2_capacity_charge", 0)
    # Use the lesser if both available
    if (bat1_charge > 0) and (bat2_charge > 0):
        return int(min(bat2_charge, bat1_charge))
    # Otherwise use whichever is available
    if bat1_charge > 0:
        return int(bat1_charge)  # batt 1 available, use that
    if bat2_charge > 0:
        return int(bat2_charge)  # batt 2 available, use that
    return 0


def value_function_software_version_g2(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return f"DSP v2.{datadict.get('firmware_dsp')} ARM v2.{datadict.get('firmware_arm')}"


def value_function_firmware_major_default(val: Any, default: int) -> Any:
    return default if val in (None, 0, "0") else val


def value_function_software_version_g3(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return (
        f"DSP v{value_function_firmware_major_default(datadict.get('firmware_dsp_major'), 3)}."
        f"{value_str_default(datadict.get('firmware_dsp'), '??'):>02} "
        f"ARM v{value_function_firmware_major_default(datadict.get('firmware_arm_major'), 3)}."
        f"{value_str_default(datadict.get('firmware_arm'), '??'):>02}"
    )


def value_function_software_version_g4(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return (
        f"DSP {value_str_default(datadict.get('firmware_dsp_major'), '?')}."
        f"{value_str_default(datadict.get('firmware_dsp'), '??'):>02} "
        f"ARM {value_str_default(datadict.get('firmware_arm_major'), '?')}."
        f"{value_str_default(datadict.get('firmware_arm'), '??'):>02}"
    )


def value_function_software_version_g5(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return (
        f"DSP {value_str_default(datadict.get('firmware_dsp_major'), '???'):>03}."
        f"{value_str_default(datadict.get('firmware_dsp'), '??'):>02} "
        f"ARM {value_str_default(datadict.get('firmware_arm_major'), '???'):>03}."
        f"{value_str_default(datadict.get('firmware_arm'), '??'):>02}"
    )


def value_function_modbus_protocol_version(datadict: dict[str, Any]) -> int:
    try:
        return int(datadict.get("modbus_protocol_version") or 0)
    except (TypeError, ValueError):
        return 0


def value_function_software_version_full(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    dsp = datadict.get("firmware_version_dsp")
    arm = datadict.get("firmware_version_arm")
    dsp_str = f"{dsp // 100}.{dsp % 100:02d}" if dsp is not None else "?.??"
    arm_str = f"{arm // 100}.{arm % 100:02d}" if arm is not None else "?.??"
    return f"DSP {dsp_str} ARM {arm_str}"


def value_function_software_version_protocol_aware(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    # FirmwareVersionModbus 100 means V001.00; newer protocol versions can use the combined 0x7B/0x7C registers.
    if (
        value_function_modbus_protocol_version(datadict) >= 100
        and datadict.get("firmware_version_dsp") is not None
        and datadict.get("firmware_version_arm") is not None
    ):
        return value_function_software_version_full(initval, descr, datadict)
    return value_function_software_version_g4(initval, descr, datadict)


def value_function_software_version_air_g3(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return f"DSP v2.{datadict.get('firmware_dsp')} ARM v1.{datadict.get('firmware_arm')}"


def value_function_software_version_air_g4(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
    return f"DSP {datadict.get('firmware_dsp')} ARM {datadict.get('firmware_arm')}"


def value_function_battery_voltage_cell_difference(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
    return float(datadict.get("cell_voltage_high", 0)) - float(datadict.get("cell_voltage_low", 0))


# ================================= Button Declarations ============================================================

BUTTON_TYPES: Sequence["SolaxModbusButtonEntityDescription"] = []

# ================================= Number Declarations ============================================================

MAX_CURRENTS: list[tuple[str, int | float]] = []

# ================================= Switch Declarations ============================================================

SWITCH_TYPES: Sequence["SolaXModbusSwitchEntityDescription"] = []

# ================================= Select Declarations ============================================================

SELECT_TYPES: Sequence["SolaxModbusSelectEntityDescription"] = []

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES_MAIN: list[SolaXModbusSensorEntityDescription] = [
    #####
    #
    # Holding
    #
    #####
    SolaXModbusSensorEntityDescription(
        key="charge_1_start",
        register=0x2580,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charge 1 Stop",
        key="charge_1_stop",
        register=0x2581,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharge 1 Start",
        key="discharge_1_start",
        register=0x2582,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharge 1 Stop",
        key="discharge_1_stop",
        register=0x2583,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charge 2 Start",
        key="charge_2_start",
        register=0x2584,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charge 2 Stop",
        key="charge_2_stop",
        register=0x2585,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharge 2 Start",
        key="discharge_2_start",
        register=0x2586,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharge 2 Stop",
        key="discharge_2_stop",
        register=0x2587,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charge 3 Start",
        key="charge_3_start",
        register=0x2580,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Charge 3 Stop",
        key="charge_3_stop",
        register=0x2581,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharge 3 Start",
        key="discharge_3_start",
        register=0x2582,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
        internal=True,
    ),
    SolaXModbusSensorEntityDescription(
        name="Discharge 3 Stop",
        key="discharge_3_stop",
        register=0x2583,
        scale=value_function_gen4time,
        allowedtypes=AC | HYBRID | GEN2,
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
        register=0x100,
        scale=0.1,
        register_type=REG_INPUT,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN2,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Voltage",
        key="inverter_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x103,
        scale=0.1,
        register_type=REG_INPUT,
        rounding=1,
        allowedtypes=AC | HYBRID | GEN,
    ),
    SolaXModbusSensorEntityDescription(
        name="Inverter Current",
        key="inverter_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x180,
        scale=0.1,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
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
        register_data_type=REGISTER_S32,
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
        register_data_type=REGISTER_S16,
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
        register_data_type=REGISTER_S32,
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
        name="Battery Voltage Charge",
        key="battery_voltage_charge",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x480,
        scale=0.1,
        register_type=REG_INPUT,
        register_data_type=REGISTER_S16,
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
        register_data_type=REGISTER_S16,
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
        register_data_type=REGISTER_S16,
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
        register_data_type=REGISTER_S16,
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
        register_data_type=REGISTER_S16,
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

TIME_TYPES = [
    SolaXModbusTimeEntityDescription(
        name="Charge 1 Start",
        key="charge_1_start",
        register=0x2580,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaXModbusTimeEntityDescription(
        name="Charge 1 Stop",
        key="charge_1_stop",
        register=0x2581,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaXModbusTimeEntityDescription(
        name="Discharge 1 Start",
        key="discharge_1_start",
        register=0x2582,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaXModbusTimeEntityDescription(
        name="Discharge 1 Stop",
        key="discharge_1_stop",
        register=0x2583,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaXModbusTimeEntityDescription(
        name="Charge 2 Start",
        key="charge_2_start",
        register=0x2584,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaXModbusTimeEntityDescription(
        name="Charge 2 Stop",
        key="charge_2_stop",
        register=0x2585,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaXModbusTimeEntityDescription(
        name="Discharge 2 Start",
        key="discharge_2_start",
        register=0x2586,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaXModbusTimeEntityDescription(
        name="Discharge 2 Stop",
        key="discharge_2_stop",
        register=0x2587,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaXModbusTimeEntityDescription(
        name="Charge 3 Start",
        key="charge_3_start",
        register=0x2580,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaXModbusTimeEntityDescription(
        name="Charge 3 Stop",
        key="charge_3_stop",
        register=0x2581,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
    SolaXModbusTimeEntityDescription(
        name="Discharge 3 Start",
        key="discharge_3_start",
        register=0x2582,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-start",
    ),
    SolaXModbusTimeEntityDescription(
        name="Discharge 3 Stop",
        key="discharge_3_stop",
        register=0x2583,
        option_dict=TIME_OPTIONS_GEN4,
        allowedtypes=AC | HYBRID | GEN2,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-end",
    ),
]

# ============================ plugin declaration =================================================


@dataclass(kw_only=True)
class solax_plugin(plugin_base):
    def isAwake(self, datadict: dict[str, Any]) -> bool:
        """determine if inverter is awake based on polled datadict"""
        return datadict.get("run_mode", None) == "Normal Mode"

    def wakeupButton(self) -> str:
        """in order to wake up  the inverter , press this button"""
        return "battery_awaken"

    async def async_determineInverterType(self, hub: Any, configdict: dict[str, Any]) -> int:
        # global SENSOR_TYPES
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        self.inverter_model = None
        seriesnumber = await async_read_serialnr(hub, 0x32)
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find any serial number(s)")
            seriesnumber = "unknown"

        # derive invertertupe from seriiesnumber
        if seriesnumber.startswith("HL1060"):
            invertertype = HYBRID | GEN | X1  # X1-Hybrid-LV 6kW
            self.inverter_model = f"X1-Hybrid-LV {seriesnumber[4:5]}.{seriesnumber[5:6]}kW"
        elif seriesnumber.startswith(10J080"):
            invertertype = HYBRID | GEN2 | X1  # X1-Lite-LV 6kW
            self.inverter_model = f"X1-Lite-LV {seriesnumber[4:5]}.{seriesnumber[5:6]}kW"
        else:
            invertertype = 0
            _LOGGER.error(f"unrecognized inverter type - serial number : {seriesnumber}")

        hub.inverter_model = self.inverter_model if invertertype > 0 else None
        hub._has_local_inverter_model = True

        if invertertype > 0:
            # Firmware metadata is needed before the first poll so the device registry and
            # protocol-specific register filters start with the right values.
            if invertertype & (GEN4 | GEN5 | GEN6):
                await async_read_inverter_firmware_info(hub)
                if invertertype & GEN4:
                    hub.data["hardware_version"] = value_function_hardware_version_g4(0, None, hub.data)
                elif invertertype & GEN5:
                    hub.data["hardware_version"] = value_function_hardware_version_g5(0, None, hub.data)
                elif invertertype & GEN6:
                    hub.data["hardware_version"] = value_function_hardware_version_g6(0, None, hub.data)
                if "firmware_dsp" in hub.data or "firmware_version_dsp" in hub.data:
                    hub.data["software_version"] = value_function_software_version_protocol_aware(0, None, hub.data)

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

    def matchInverterWithMask(
        self, inverterspec: int, entitymask: int, serialnumber: str = "not relevant", blacklist: list[str] | None = None
    ) -> bool:
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
        return (genmatch and xmatch and hybmatch and epsmatch and dcbmatch and mpptmatch and pmmatch) and not blacklisted

    def getSoftwareVersion(self, new_data: dict[str, Any]) -> str | None:
        return new_data.get("software_version", None)

    def getHardwareVersion(self, new_data: dict[str, Any]) -> str | None:
        return new_data.get("hardware_version", None)

    def localDataCallback(self, hub: Any) -> bool:
        # adapt the read scales for export_control_user_limit if exception is configured
        # only called after initial polling cycle and subsequent modifications to local data
        _LOGGER.info("local data update callback")

        config_scale_entity = hub.numberEntities.get("config_export_control_limit_readscale")
        if config_scale_entity and config_scale_entity.enabled:
            new_read_scale = hub.data.get("config_export_control_limit_readscale")
            if new_read_scale is not None:
                _LOGGER.info(f"local data update callback for read_scale: {new_read_scale} enabled: {config_scale_entity.enabled}")
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

        # For parallel mode Master inverters, use inverter_power_kw for remote control limits
        # This allows proper ±limits for multi-inverter systems (e.g., 3× 15kW = ±45kW)
        parallel_setting = hub.data.get("parallel_setting", "Free")
        if parallel_setting == "Master":
            # Use inverter_power_kw (total system capacity) for remote control limits
            system_limit_w = hub.inverterPowerKw * 1000  # Convert kW to W
            for key in ["remotecontrol_active_power", "remotecontrol_import_limit"]:
                number_entity = hub.numberEntities.get(key)
                if number_entity:
                    # remotecontrol_active_power uses ±limits, import_limit uses 0 to +limit
                    if key == "remotecontrol_import_limit":
                        number_entity._attr_native_min_value = 0
                        number_entity._attr_native_max_value = system_limit_w
                        number_entity.entity_description = replace(
                            number_entity.entity_description,
                            native_min_value=0,
                            native_max_value=system_limit_w,
                        )
                        _LOGGER.info(f"Parallel Master: Set {key} limits to 0-{system_limit_w}W (inverter_power_kw={hub.inverterPowerKw}kW)")
                    else:
                        number_entity._attr_native_min_value = -system_limit_w
                        number_entity._attr_native_max_value = system_limit_w
                        number_entity.entity_description = replace(
                            number_entity.entity_description,
                            native_min_value=-system_limit_w,
                            native_max_value=system_limit_w,
                        )
                        _LOGGER.info(f"Parallel Master: Set {key} limits to ±{system_limit_w}W (inverter_power_kw={hub.inverterPowerKw}kW)")

        # For single inverters or if config_max_export is enabled, use config_max_export.
        # Parallel Master remote-control limits are handled above using total system power,
        # but export_control_user_limit still needs the configured max export range.
        parallel_master_remotecontrol_keys = {
            "remotecontrol_active_power",
            "remotecontrol_import_limit",
        }
        config_maxexport_entity = hub.numberEntities.get("config_max_export")
        if config_maxexport_entity and config_maxexport_entity.enabled:
            new_max_export = hub.data.get("config_max_export")
            if new_max_export is not None:
                for key in [
                    "remotecontrol_active_power",
                    "remotecontrol_import_limit",
                    "export_control_user_limit",
                    "generator_max_charge",
                ]:
                    number_entity = hub.numberEntities.get(key)
                    if not number_entity:
                        continue
                    if parallel_setting == "Master" and key in parallel_master_remotecontrol_keys:
                        continue
                    number_entity._attr_native_max_value = new_max_export
                    # update description also, not sure whether needed or not
                    number_entity.entity_description = replace(
                        number_entity.entity_description,
                        native_max_value=new_max_export,
                    )
                    _LOGGER.info(f"local data update callback for entity: {key} new limit: {new_max_export}")

        return False


# Energy Dashboard Virtual Device mapping
# Details: docs/solax/ENERGY_DASHBOARD_MAPPING_GEN1_GEN6.md
from .energy_dashboard import EnergyDashboardMapping, EnergyDashboardSensorMapping  # noqa: E402

ENERGY_DASHBOARD_MAPPING = EnergyDashboardMapping(
    plugin_name="solax",
    mappings=[
        # ===== POWER SENSORS =====
        # Grid Power
        EnergyDashboardSensorMapping(
            source_key="measured_power",
            target_key="grid_power",
            name="Grid Power",
            invert=True,
            icon="mdi:transmission-tower",
            skip_pm_individuals=True,
            allowedtypes=ALL_GEN_GROUP,
        ),
        # Solar Power
        EnergyDashboardSensorMapping(
            source_key="pv_power_total",
            source_key_pm="pm_total_pv_power",
            target_key="solar_power",
            name="Solar Power",
            allowedtypes=ALL_GEN_GROUP,
        ),
        # PV Variant Power (per string)
        EnergyDashboardSensorMapping(
            source_key="pv_power_{n}",
            target_key="pv_power_{n}",
            name="PV Power {n}",
            allowedtypes=ALL_GEN_GROUP,
        ),
        # Battery Power (GEN2-6 only)
        EnergyDashboardSensorMapping(
            source_key="battery_power_charge",
            source_key_pm="pm_battery_power_charge",
            target_key="battery_power",
            name="Battery Power",
            invert=True,
            allowedtypes=GEN2 | GEN3 | GEN4 | GEN5 | GEN6,
        ),
        # Home Consumption Power
        EnergyDashboardSensorMapping(
            source_key="house_load",
            source_key_pm="pm_total_house_load",
            target_key="home_consumption_power",
            name="Home Consumption Power",
            skip_pm_individuals=True,
            allowedtypes=ALL_GEN_GROUP,
        ),
        # Grid to Battery Power (derived from inverter power)
        EnergyDashboardSensorMapping(
            source_key="inverter_power",
            target_key="grid_to_battery_power",
            name="Grid to Battery Power",
            filter_function=lambda v: max(0 - v, 0),
            icon="mdi:transmission-tower-export",
            needs_aggregation=True,
            allowedtypes=GEN3 | GEN4 | GEN5 | GEN6,
        ),
        # ===== ENERGY SENSORS =====
        # PV Variant Energy (per string, Riemann sum)
        EnergyDashboardSensorMapping(
            source_key="pv_power_{n}",
            target_key="pv_energy_{n}",
            name="PV Energy {n}",
            use_riemann_sum=True,
            filter_function=lambda v: max(0, v),
            allowedtypes=ALL_GEN_GROUP,
        ),
        # Grid Import Energy (GEN3-6 today)
        EnergyDashboardSensorMapping(
            source_key="today_s_import_energy",
            target_key="grid_energy_import",
            name="Grid Import Energy",
            skip_pm_individuals=True,
            allowedtypes=GEN3 | GEN4 | GEN5 | GEN6,
        ),
        # Grid Import Energy (GEN2 total)
        EnergyDashboardSensorMapping(
            source_key="grid_import_total",
            target_key="grid_energy_import",
            name="Grid Import Energy",
            skip_pm_individuals=True,
            allowedtypes=GEN2,
        ),
        # Grid Import Energy (GEN1 Riemann sum)
        # GEN1 lacks native energy counters; integrate power to derive energy.
        EnergyDashboardSensorMapping(
            source_key="grid_power_energy_dashboard",
            target_key="grid_energy_import",
            name="Grid Import Energy",
            use_riemann_sum=True,
            filter_function=lambda v: max(0, v),
            allowedtypes=GEN,
        ),
        # Grid Export Energy (GEN3-6 today)
        EnergyDashboardSensorMapping(
            source_key="today_s_export_energy",
            target_key="grid_energy_export",
            name="Grid Export Energy",
            skip_pm_individuals=True,
            allowedtypes=GEN3 | GEN4 | GEN5 | GEN6,
        ),
        # Grid Export Energy (GEN2 total)
        EnergyDashboardSensorMapping(
            source_key="grid_export_total",
            target_key="grid_energy_export",
            name="Grid Export Energy",
            skip_pm_individuals=True,
            allowedtypes=GEN2,
        ),
        # Grid Export Energy (GEN1 Riemann sum)
        # GEN1 export is derived from power; filter to export-only portion.
        EnergyDashboardSensorMapping(
            source_key="grid_power_energy_dashboard",
            target_key="grid_energy_export",
            name="Grid Export Energy",
            use_riemann_sum=True,
            filter_function=lambda v: abs(min(0, v)),
            allowedtypes=GEN,
        ),
        # Home Consumption Energy (Riemann sum)
        EnergyDashboardSensorMapping(
            source_key="house_load",
            source_key_pm="pm_total_house_load",
            target_key="home_consumption_energy",
            name="Home Consumption Energy",
            use_riemann_sum=True,
            filter_function=lambda v: max(0, v),
            skip_pm_individuals=True,
            allowedtypes=ALL_GEN_GROUP,
        ),
        # Battery Charge Energy (GEN3-6 today)
        # Aggregate energy totals across Primary + Secondary in parallel mode.
        EnergyDashboardSensorMapping(
            source_key="battery_input_energy_today",
            target_key="battery_energy_charge",
            name="Battery Charge Energy",
            needs_aggregation=True,
            allowedtypes=GEN3 | GEN4 | GEN5 | GEN6,
        ),
        # Battery Charge Energy (GEN2 total)
        # Aggregate energy totals across Primary + Secondary in parallel mode.
        EnergyDashboardSensorMapping(
            source_key="battery_input_energy_total",
            target_key="battery_energy_charge",
            name="Battery Charge Energy",
            needs_aggregation=True,
            allowedtypes=GEN2,
        ),
        # Battery Discharge Energy (GEN3-6 today)
        # Aggregate energy totals across Primary + Secondary in parallel mode.
        EnergyDashboardSensorMapping(
            source_key="battery_output_energy_today",
            target_key="battery_energy_discharge",
            name="Battery Discharge Energy",
            needs_aggregation=True,
            allowedtypes=GEN3 | GEN4 | GEN5 | GEN6,
        ),
        # Battery Discharge Energy (GEN2 total)
        # Aggregate energy totals across Primary + Secondary in parallel mode.
        EnergyDashboardSensorMapping(
            source_key="battery_output_energy_total",
            target_key="battery_energy_discharge",
            name="Battery Discharge Energy",
            needs_aggregation=True,
            allowedtypes=GEN2,
        ),
        # Grid to Battery Energy (per inverter, aggregate in parallel)
        EnergyDashboardSensorMapping(
            source_key="e_charge_today",
            target_key="grid_to_battery_energy",
            name="Grid to Battery Energy",
            icon="mdi:transmission-tower-export",
            needs_aggregation=True,
            allowedtypes=GEN3 | GEN4 | GEN5 | GEN6,
        ),
        # Solar Production Energy (AC and Hybrid GEN2-6 today)
        # Aggregate energy totals across Primary + Secondary in parallel mode.
        EnergyDashboardSensorMapping(
            source_key="today_s_solar_energy",
            target_key="solar_energy_production",
            name="Solar Production Energy",
            needs_aggregation=True,
            allowedtypes=AC | HYBRID | GEN2 | GEN3 | GEN4 | GEN5 | GEN6,
        ),
        # Solar Production Energy ( MIC today)
        EnergyDashboardSensorMapping(
            source_key="today_s_yield",
            target_key="solar_energy_production",
            name="Solar Production Energy",
            allowedtypes=MIC | GEN | GEN2 | GEN4,
        ),
        # Solar Production Energy (GEN1 Riemann sum)
        # GEN1 lacks native energy counters; integrate power and aggregate in parallel mode.
        EnergyDashboardSensorMapping(
            source_key="solar_power_energy_dashboard",
            target_key="solar_energy_production",
            name="Solar Production Energy",
            use_riemann_sum=True,
            filter_function=lambda v: max(0, v),
            needs_aggregation=True,
            allowedtypes=AC | HYBRID | GEN,
        ),
    ],
)

plugin_instance = solax_plugin(
    plugin_name="SolaX",
    plugin_manufacturer="SolaX Power",
    SENSOR_TYPES=SENSOR_TYPES_MAIN,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=SWITCH_TYPES,
    TIME_TYPES=TIME_TYPES,
    ENERGY_DASHBOARD_MAPPING=ENERGY_DASHBOARD_MAPPING,
    block_size=100,
    # order16=Endian.BIG,
    order32="little",
    auto_block_ignore_readerror=True,
    default_holding_scangroup=SCAN_GROUP_MEDIUM,
    default_input_scangroup=SCAN_GROUP_AUTO,  # SCAN_GROUP_MEDIUM for slow changing units like temperature, kWh, ...
    auto_default_scangroup=SCAN_GROUP_FAST,
    auto_slow_scangroup=SCAN_GROUP_MEDIUM,
)
