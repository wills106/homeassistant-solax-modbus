import logging
from dataclasses import dataclass
from typing import Any, cast

from custom_components.solax_modbus.const import (
    plugin_base,
)

from . import plugin_solis as _legacy
from . import plugin_solis_fb00 as _fb00

_LOGGER = logging.getLogger(__name__)

""" ============================================================================================
Unified Solis plugin with HMI-based auto-detection of the register map.

Instead of asking the user to choose between plugin_solis (older HMI firmware) and
plugin_solis_fb00 (newer HMI firmware 0xFB00+, covering the RS485_MODBUS(ESINV-33000ID)
Hybrid Inverter protocol, e.g. the 44100~44126 Remote Dispatch block, Smart Port,
generator telemetry and backup V/I registers), this plugin probes the inverter's HMI
software version at startup and selects the matching entity collections at runtime.

Version registers (RS485_MODBUS(ESINV-33000ID) Hybrid Inverter.pdf, Ver3.5, section 5.1):
- 33002: HMI Software Major Version (U16); low-order byte = major version (hex)
- 33069: HMI Software Sub Version (U16); low-order byte = sub version (hex)
  Together 33002+33069 form the HMI software version, e.g. 0x1C06 (displayed as V1CB06).

HMI versions 0xFB00..0xFFFF identify the newer Gen6/S6 firmware generation and use the
plugin_solis_fb00 register map; lower versions use the legacy plugin_solis map. When the
version registers do not respond, a probe read of register 34504 (Remote Dispatch Running
Status, only defined on the post-FB00 map) decides: a valid response means modern.
"""

# ================== bitmask re-exports (kept identical to plugin_solis) =======================

GEN = _legacy.GEN
GEN2 = _legacy.GEN2
GEN3 = _legacy.GEN3
GEN4 = _legacy.GEN4
ALL_GEN_GROUP = _legacy.ALL_GEN_GROUP

X1 = _legacy.X1
X3 = _legacy.X3
ALL_X_GROUP = _legacy.ALL_X_GROUP

PV = _legacy.PV
AC = _legacy.AC
HYBRID = _legacy.HYBRID
MIC = _legacy.MIC
ALL_TYPE_GROUP = _legacy.ALL_TYPE_GROUP

EPS = _legacy.EPS
ALL_EPS_GROUP = _legacy.ALL_EPS_GROUP

DCB = _legacy.DCB
ALL_DCB_GROUP = _legacy.ALL_DCB_GROUP

MPPT3 = _legacy.MPPT3
MPPT4 = _legacy.MPPT4
MPPT6 = _legacy.MPPT6
MPPT8 = _legacy.MPPT8
MPPT10 = _legacy.MPPT10
ALL_MPPT_GROUP = _legacy.ALL_MPPT_GROUP

ALLDEFAULT = _legacy.ALLDEFAULT

# ===================== HMI version detection constants =========================================

# RS485_MODBUS(ESINV-33000ID) Hybrid Inverter.pdf, Ver3.5, section 5.1
REG_HMI_MAJOR = 33002  # low-order byte = HMI major version (hex)
REG_HMI_SUB = 33069  # low-order byte = HMI sub version (hex)
# Remote Dispatch Running Status: defined only in the post-FB00 (Ver3.4+) protocol,
# used as a presence probe when the version registers do not respond.
REG_MODERN_PROBE = 34504

# HMI firmware from 0xFB00 onwards identifies the Gen6/S6 generation that the
# plugin_solis_fb00 register map was written for.
HMI_FB00_FLOOR = 0xFB00

MAP_LEGACY = "legacy"
MAP_FB00 = "fb00"


def compute_hmi_version(major_low_byte: int | None, sub_low_byte: int | None) -> int | None:
    """Combine the low-order bytes of 33002 and 33069 into the HMI version, e.g. 0x1C06.

    Returns None when the major version register did not respond or reads as zero.
    """
    if major_low_byte is None or (major_low_byte & 0xFF) == 0:
        return None
    return (major_low_byte & 0xFF) << 8 | (sub_low_byte or 0) & 0xFF


def select_hmi_map(hmi_version: int | None, modern_probe_ok: bool | None) -> str:
    """Pick which plugin register map to use.

    - HMI 0xFB00..0xFFFF -> "fb00" (Gen6/S6 map from plugin_solis_fb00)
    - HMI 0x0001..0xFAFF -> "legacy" (map from plugin_solis)
    - unknown version    -> fall back to the 34504 presence probe; when the probe is
      unavailable too, stay on the conservative legacy map.
    """
    if hmi_version is not None:
        if hmi_version >= HMI_FB00_FLOOR:
            return MAP_FB00
        if hmi_version > 0:
            return MAP_LEGACY
    if modern_probe_ok is True:
        return MAP_FB00
    return MAP_LEGACY


# ============================== unified plugin class ===========================================


@dataclass
class solis_unified_plugin(plugin_base):
    """Solis plugin that auto-selects the legacy or post-FB00 register map per inverter."""

    hmi_map: str | None = None
    hmi_version: int | None = None

    async def async_determineInverterType(self, hub: Any, configdict: dict[str, Any]) -> int:
        _LOGGER.info("%s: trying to determine inverter type (unified Solis plugin)", hub.name)
        # Serial-prefix based model detection is identical in both Solis plugins; reuse
        # plugin_solis's table so both stay the single source of truth for prefixes.
        # The call only uses the `self` reference for logging defaults, so Any-casting is safe.
        invertertype = await _legacy.solis_plugin.async_determineInverterType(cast("Any", self), hub, configdict)
        if invertertype in (0, None):
            return 0

        major = await self._read_low_byte(hub, REG_HMI_MAJOR)
        sub = await self._read_low_byte(hub, REG_HMI_SUB)
        hmi_version = compute_hmi_version(major, sub)

        modern_probe_ok: bool | None = None
        if hmi_version is None:
            modern_probe_ok = await self._register_responds(hub, REG_MODERN_PROBE)

        # An explicit override (e.g. from advanced YAML/options) wins over auto-detection.
        override = str(configdict.get("hmi_map", "") or "").lower()
        map_name = override if override in (MAP_LEGACY, MAP_FB00) else select_hmi_map(hmi_version, modern_probe_ok)

        self.hmi_map = map_name
        self.hmi_version = hmi_version
        self._apply_hmi_map(map_name)

        hmi_str = f"0x{hmi_version:04X}" if hmi_version is not None else "unknown"
        probe_str = "unknown" if modern_probe_ok is None else ("responds" if modern_probe_ok else "no response")
        _LOGGER.info(
            "%s: HMI version %s, probe register %d: %s -> using %s register map (%d sensors)",
            hub.name,
            hmi_str,
            REG_MODERN_PROBE,
            probe_str,
            map_name,
            len(self.SENSOR_TYPES),
        )
        return invertertype

    async def _read_low_byte(self, hub: Any, address: int) -> int | None:
        """Read a single input register and return its low-order byte, or None on failure."""
        try:
            res = await hub.async_read_input_registers(unit=hub._modbus_addr, address=address, count=1)
            if res is not None and not res.isError() and res.registers:
                return int(res.registers[0]) & 0xFF
        except Exception:
            _LOGGER.debug("%s: reading HMI version register 0x%x failed", hub.name, address, exc_info=True)
        return None

    async def _register_responds(self, hub: Any, address: int) -> bool:
        """Presence probe: True when the register answers without a Modbus exception."""
        try:
            res = await hub.async_read_input_registers(unit=hub._modbus_addr, address=address, count=1)
            return res is not None and not res.isError()
        except Exception:
            _LOGGER.debug("%s: probe read of register 0x%x failed", hub.name, address, exc_info=True)
            return False

    def _apply_hmi_map(self, map_name: str) -> None:
        """Swap the runtime entity collections to the selected register map."""
        source = _fb00 if map_name == MAP_FB00 else _legacy
        self.SENSOR_TYPES = list(source.SENSOR_TYPES)
        self.NUMBER_TYPES = list(source.NUMBER_TYPES)
        self.BUTTON_TYPES = list(source.BUTTON_TYPES)
        self.SELECT_TYPES = list(source.SELECT_TYPES)
        self.SWITCH_TYPES = list(source.SWITCH_TYPES)
        # Neither legacy Solis module declares a module-level TIME_TYPES; both pass
        # TIME_TYPES=[] directly to their plugin instance.
        self.TIME_TYPES = list(getattr(source, "TIME_TYPES", []))

    def matchInverterWithMask(
        self,
        inverterspec: Any,
        entitymask: Any,
        serialnumber: str = "not relevant",
        blacklist: list[str] | None = None,
    ) -> bool:
        # Identical mask semantics in both Solis plugins; delegate to plugin_solis.
        return _legacy.solis_plugin.matchInverterWithMask(cast("Any", self), inverterspec, entitymask, serialnumber, blacklist)

    def getSoftwareVersion(self, new_data: dict[str, Any]) -> str | None:
        if self.hmi_version is not None:
            return f"HMI 0x{self.hmi_version:04X}"
        return None


# Energy Dashboard Virtual Device mapping (identical source mapping in both Solis plugins)
from .energy_dashboard import EnergyDashboardMapping, EnergyDashboardSensorMapping  # noqa: E402

ENERGY_DASHBOARD_MAPPING = EnergyDashboardMapping(
    plugin_name="solis_unified",
    mappings=[
        EnergyDashboardSensorMapping(
            source_key="battery_power",  # Note: the Solis plugins use battery_power (not battery_power_charge)
            source_key_pm=None,  # No parallel mode support in these plugins
            target_key="battery_power",
            name="Battery Power",
            invert=True,
        ),
    ],
    parallel_mode_supported=False,  # Plugin doesn't support parallel mode
)

plugin_instance = solis_unified_plugin(
    ENERGY_DASHBOARD_MAPPING=ENERGY_DASHBOARD_MAPPING,
    plugin_name="Solis Unified",
    plugin_manufacturer="Ginlog Solis",
    SENSOR_TYPES=list(_legacy.SENSOR_TYPES),
    NUMBER_TYPES=list(_legacy.NUMBER_TYPES),
    BUTTON_TYPES=list(_legacy.BUTTON_TYPES),
    SELECT_TYPES=list(_legacy.SELECT_TYPES),
    SWITCH_TYPES=list(_legacy.SWITCH_TYPES),
    TIME_TYPES=[],
    block_size=40,
    # order16="big",
    order32="big",
    auto_block_ignore_readerror=True,
)
