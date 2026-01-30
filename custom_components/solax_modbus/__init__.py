"""The SolaX Modbus Integration."""

import asyncio

# import importlib.util, sys
import importlib
import json
import logging
import time as _mtime
from dataclasses import dataclass, replace
from datetime import timedelta
from time import time
from types import ModuleType, SimpleNamespace
from typing import Any, Optional
from weakref import ref as WeakRef

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_STARTED,
    PERCENTAGE,
    Platform,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException, ModbusIOException
from pymodbus.framer import FramerType
from pymodbus.pdu import register_message

from .pymodbus_compat import ADDR_KW, DataType, convert_from_registers, convert_to_registers, pymodbus_version_info

RETRIES = 1  # was 6 then 0, which worked also, but 1 is probably the safe choice
INVALID_START = 99999
VERBOSE_CYCLES = 20


try:
    from homeassistant.components.modbus import ModbusHub as CoreModbusHub
    from homeassistant.components.modbus import get_hub as get_core_hub
except ImportError:

    def get_core_hub(hass, name):
        return None

    class CoreModbusHub:  # placeholder dummy
        pass


from .sensor import SolaXModbusSensor

_LOGGER = logging.getLogger(__name__)

from .const import (
    BUTTONREPEAT_FIRST,
    BUTTONREPEAT_LOOP,
    BUTTONREPEAT_POST,
    CONF_BAUDRATE,
    CONF_CORE_HUB,
    CONF_DEBUG_SETTINGS,
    CONF_INTERFACE,
    CONF_INVERTER_NAME_SUFFIX,
    CONF_INVERTER_POWER_KW,
    CONF_MODBUS_ADDR,
    CONF_PLUGIN,
    CONF_READ_DCB,
    CONF_READ_EPS,
    CONF_SERIAL_PORT,
    CONF_TCP_TYPE,
    CONF_TIME_OUT,
    DEFAULT_BAUDRATE,
    DEFAULT_INTERFACE,
    DEFAULT_INVERTER_NAME_SUFFIX,
    DEFAULT_INVERTER_POWER_KW,
    DEFAULT_MODBUS_ADDR,
    DEFAULT_NAME,
    DEFAULT_PLUGIN,
    DEFAULT_PORT,
    DEFAULT_READ_DCB,
    DEFAULT_READ_EPS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERIAL_PORT,
    DEFAULT_TCP_TYPE,
    DEFAULT_TIME_OUT,
    DOMAIN,
    INVERTER_IDENT,
    REG_HOLDING,
    REG_INPUT,
    REGISTER_F32,
    REGISTER_S16,
    REGISTER_S32,
    REGISTER_STR,
    REGISTER_U8H,
    REGISTER_U8L,
    REGISTER_U16,
    REGISTER_U32,
    REGISTER_ULSB16MSB16,
    REGISTER_WORDS,
    SCAN_GROUP_AUTO,
    SCAN_GROUP_DEFAULT,
    SCAN_GROUP_MEDIUM,
    # PLUGIN_PATH,
    SLEEPMODE_LASTAWAKE,
    WRITE_MULTI_MODBUS,
    WRITE_MULTISINGLE_MODBUS,
    WRITE_SINGLE_MODBUS,
)

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

# CONFIG_SCHEMA allows YAML configuration ONLY for debug_settings (DEVELOPMENT/TESTING/DEBUGGING ONLY)
# All other configuration must be done via config flow (UI)
CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Schema(
            {
                vol.Optional(CONF_DEBUG_SETTINGS): vol.Schema(
                    {str: vol.Schema({str: cv.boolean})}  # Inverter name -> {setting_name: bool}
                )
            },
            extra=vol.ALLOW_EXTRA,  # Allow extra keys but they won't be processed
        )
    },
    extra=vol.ALLOW_EXTRA,
)

empty_hub_interval_group_lambda = lambda: SimpleNamespace(
    interval=0,
    unsub_interval_method=None,
    device_groups={},
    poll_lock=asyncio.Lock(),
    pending_rerun=False,
)
empty_hub_device_group_lambda = lambda: SimpleNamespace(
    sensors=[],
    inputBlocks={},
    holdingBlocks={},
    readPreparation=None,  # function to call before read group
    readFollowUp=None,  # function to call after read group
)


def should_register_be_loaded(hass, hub, descriptor):
    """
    Check if an entity is enabled in the entity registry, checking across multiple platforms.
    """
    if descriptor.internal:
        _LOGGER.debug(f"{hub.name}: should be loaded: entity with key {descriptor.key} is internal, returning True.")
        return True
    unique_id = f"{hub._name}_{descriptor.key}"
    unique_id_alt = f"{hub._name}.{descriptor.key}"  # dont knnow why
    platforms = (Platform.SENSOR, Platform.SELECT, Platform.NUMBER, Platform.SWITCH, Platform.BUTTON)
    registry = er.async_get(hass)
    entity_found = False
    # First, check if there is an existing enabled entity in the registry for this unique_id.
    for platform in platforms:
        entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
        if entity_id:
            _LOGGER.debug(
                f"{hub.name}: should be loaded: entity_id for {unique_id} on platform {platform} is now {entity_id}"
            )
        else:
            entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id_alt)
            _LOGGER.debug(
                f"{hub.name}: should be loaded: entity_id for alt {unique_id_alt} on platform {platform} is now {entity_id}"
            )
        if entity_id:
            entity_found = True
            entity_entry = registry.async_get(entity_id)
            if entity_entry and not entity_entry.disabled:
                _LOGGER.debug(f"{hub.name}: should be loaded: Entity {entity_id} is enabled, returning True.")
                return True  # Found an enabled entity, no need to check further
    # If we get here, no enabled entity was found across all platforms.
    if entity_found:
        # At least one entity exists for this unique_id, but all are disabled. Respect the user's choice.
        _LOGGER.debug(
            f"{hub.name}: should be loaded: entity with unique_id {unique_id} was found but is disabled across all relevant platforms."
        )
        return False
    else:
        # No entity exists for this unique_id on any platform. Treat it as a new entity.
        _LOGGER.debug(
            f"{hub.name}: should be loaded: entity with unique_id {unique_id} not found in entity registry, checking defaults "
        )
        if descriptor.entity_registry_enabled_default:
            return True
        # check the other platforms descriptors
        d = hub.selectEntities.get(descriptor.key)
        if d and d.entity_registry_enabled_default:
            return True
        d = hub.numberEntities.get(descriptor.key)
        if d and d.entity_registry_enabled_default:
            return True
        d = hub.switchEntities.get(descriptor.key)
        if d and d.entity_registry_enabled_default:
            return True
        _LOGGER.debug(
            f"{hub.name}: should be loaded: entity_default with unique_id {unique_id} was found but is disabled across all relevant platforms."
        )
        return False


async def config_entry_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener, called when the config entry options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass, config):
    """Set up the SolaX modbus component."""
    hass.data[DOMAIN] = {}

    # Extract debug_settings from YAML configuration (DEVELOPMENT/TESTING/DEBUGGING ONLY)
    # Store in hass.data so debug.py can access it
    yaml_config = config.get(DOMAIN, {})
    debug_settings = yaml_config.get(CONF_DEBUG_SETTINGS)
    if debug_settings:
        hass.data[DOMAIN]["_debug_settings"] = debug_settings
    else:
        hass.data[DOMAIN]["_debug_settings"] = {}

    # Register helper services to force-stop hubs
    async def _svc_stop_all(call):
        """Force-stop all SolaX hubs (kills timers/tasks/sockets)."""
        domain_data = hass.data.get(DOMAIN, {})
        for name, rec in list(domain_data.items()):
            hub = rec.get("hub")
            if hub:
                _LOGGER.warning(f"{name}: stop_all service – stopping hub")
                try:
                    await hub.async_stop()
                except Exception as ex:
                    _LOGGER.warning(f"{name}: stop_all service – error during hub stop: {ex}")

    async def _svc_stop_hub(call):
        """Force-stop a single hub by name."""
        name = call.data.get("name")
        if not name:
            _LOGGER.warning("stop_hub service – missing 'name'")
            return
        domain_data = hass.data.get(DOMAIN, {})
        rec = domain_data.get(name)
        hub = rec.get("hub") if rec else None
        if hub:
            _LOGGER.warning(f"{name}: stop_hub service – stopping hub")
            try:
                await hub.async_stop()
            except Exception as ex:
                _LOGGER.warning(f"{name}: stop_hub service – error during hub stop: {ex}")
        # also remove from hass.data to avoid zombie references
        if rec:
            domain_data.pop(name, None)

    hass.services.async_register(DOMAIN, "stop_all", _svc_stop_all)
    hass.services.async_register(DOMAIN, "stop_hub", _svc_stop_hub)
    # _LOGGER.debug("solax data %d", hass.data)
    return True


# Example migration function
async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)
    if config_entry.version == 1:
        new = {**config_entry.options}
        # TODO: modify Config Entry data
        config_entry.version = 2
        hass.config_entries.async_update_entry(config_entry, data=new)
    _LOGGER.info("Migration to version %s successful", config_entry.version)
    return True


def _load_plugin(plugin_name: str) -> ModuleType:
    _LOGGER.info("trying to load plugin - plugin_name: %s", plugin_name)
    plugin = importlib.import_module(f".plugin_{plugin_name}", "custom_components.solax_modbus")
    if not plugin:
        _LOGGER.error("Could not import plugin with name: %s", plugin_name)
    return plugin


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up a SolaX modbus."""
    _LOGGER.debug(f"setup config entries - data: {entry.data}, options: {entry.options}")

    # Ensure DOMAIN dict exists (needed for reload support)
    # async_setup() only runs once at HA startup, but async_setup_entry()
    # runs for each config entry AND during reloads, so we must ensure
    # the domain dictionary exists before using it
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    config = entry.options
    # Stop a previously running hub with the same name before creating a new one
    old_name = config.get(CONF_NAME)
    try:
        existing = hass.data.get(DOMAIN, {}).get(old_name)
    except Exception:
        existing = None
    if existing and (old_hub := existing.get("hub")):
        _LOGGER.info(f"{old_name}: stopping previous hub and unloading platforms for reload")
        try:
            await old_hub.async_stop()
        except Exception as ex:
            _LOGGER.warning(f"{old_name}: error while stopping previous hub: {ex}")

        # Unload platforms so they can be reloaded with the new hub
        # This is necessary for reload_config_entry to work properly
        if old_hub._platforms_forwarded:
            try:
                _LOGGER.debug(f"{old_name}: unloading platforms for reload")
                unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
                if unload_ok:
                    _LOGGER.debug(f"{old_name}: platforms unloaded successfully")
                else:
                    _LOGGER.warning(f"{old_name}: platform unload returned False")
            except Exception as ex:
                _LOGGER.warning(f"{old_name}: error unloading platforms during reload: {ex}")

        hass.data.get(DOMAIN, {}).pop(old_name, None)

    plugin_name = config[CONF_PLUGIN]

    # convert old style to new style plugin name here - Remove later after a breaking upgrade
    if (
        plugin_name.startswith("custom_components")
        or plugin_name.startswith("/config")
        or plugin_name.startswith("plugin_")
    ):
        new = {**config}
        plugin_name = plugin_name.split("plugin_", 1)[1][:-3]
        _LOGGER.warning(
            f"converting old style plugin name {config[CONF_PLUGIN]} to new style short name {plugin_name}"
        )
        new[CONF_PLUGIN] = plugin_name
        hass.config_entries.async_update_entry(entry, options=new)
    # end of conversion

    # ================== dynamically load desired plugin =======================================================

    plugin = await hass.async_add_executor_job(_load_plugin, plugin_name)

    # ====================== end of dynamic load ==============================================================

    if config.get(CONF_INTERFACE, None) == "core":
        hub = SolaXCoreModbusHub(
            hass,
            plugin,
            entry,
        )
    else:
        hub = SolaXModbusHub(
            hass,
            plugin,
            entry,
        )
    try:
        from .energy_dashboard import register_energy_dashboard_switch_provider

        register_energy_dashboard_switch_provider(hass)
    except Exception as ex:
        _LOGGER.debug(f"{hub.name}: Energy Dashboard switch provider registration failed: {ex}")
    """Register the hub."""
    hass.data[DOMAIN][hub._name] = {
        "hub": hub,
    }

    # Tests on some systems have shown that establishing the Modbus connection
    # can occasionally lead to errors if Home Assistant is not fully loaded.
    if hass.is_running:
        # Start init in background so it can be cancelled on unload
        hub._init_task = hass.loop.create_task(hub.async_init())
    else:
        # Defer until HA is started, but still capture the task handle for cancellation
        async def _deferred_init(event):
            if getattr(hub, "_stopping", False):
                return
            hub._init_task = hass.loop.create_task(hub.async_init())

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _deferred_init)

    entry.async_on_unload(entry.add_update_listener(config_entry_update_listener))
    return True


async def async_unload_entry(hass, entry):
    """Unload SolaX modbus entry and tear down transports cleanly."""
    name = entry.options.get("name")
    _LOGGER.debug(f"async_unload_entry called for {name} – state={entry.state}")
    hub = hass.data.get(DOMAIN, {}).get(name, {}).get("hub")
    if hub:
        try:
            await hub.async_stop()
        except Exception as ex:
            _LOGGER.warning(f"{name}: error during hub stop: {ex}")

    # Unload platforms - this must succeed for reload to work properly
    # Always try to unload regardless of entry state - during reload, state might not be LOADED
    unload_ok = True
    try:
        _LOGGER.debug(f"{name}: attempting to unload platforms (state={entry.state})")
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if unload_ok:
            _LOGGER.debug(f"{name}: platforms unloaded successfully")
        else:
            _LOGGER.error(f"{name}: platform unload returned False")
    except Exception as ex:
        _LOGGER.error(f"{name}: error during platform unload: {ex}")
        unload_ok = False

    # Ensure removal from hass.data
    try:
        hass.data.get(DOMAIN, {}).pop(name, None)
    except Exception as ex:
        _LOGGER.warning(f"{name}: error removing from hass.data: {ex}")

    return unload_ok


def defaultIsAwake(datadict):
    return True


def Gen4Timestring(numb):
    h = numb % 256
    m = numb >> 8
    return f"{h:02d}:{m:02d}"


@dataclass
class block:
    start: int = None  # start address of the block
    end: int = None  # end address of the block
    # order16: int = None # byte endian for 16bit registers
    # order32: int = None # word endian for 32bit registers
    descriptions: Any = None
    regs: Any = None  # sorted list of registers used in this block


class SolaXModbusHub:
    """Thread safe wrapper class for pymodbus."""

    def __init__(
        self,
        hass,
        plugin,
        entry,
    ):
        config = entry.options
        name = config[CONF_NAME]
        host = config.get(CONF_HOST, None)
        port = config.get(CONF_PORT, DEFAULT_PORT)
        tcp_type = config.get(CONF_TCP_TYPE, DEFAULT_TCP_TYPE)
        modbus_addr = config.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
        if modbus_addr == None:
            modbus_addr = DEFAULT_MODBUS_ADDR
            _LOGGER.warning(
                f"{name} integration may need to be reconfigured for this version; using default Solax modbus_address {modbus_addr}"
            )
        interface = config.get(CONF_INTERFACE, None)
        if not interface:  # core modbus parameter name was read_serial, this block can be removed later
            if config.get("read_serial", False):
                interface = "serial"
            else:
                interface = "tcp"
        serial_port = config.get(CONF_SERIAL_PORT, DEFAULT_SERIAL_PORT)
        baudrate = int(config.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
        time_out = int(config.get(CONF_TIME_OUT, DEFAULT_TIME_OUT))
        _LOGGER.debug(f"Setup {DOMAIN}.{name}")
        _LOGGER.debug(f"solax serial port {serial_port} interface {interface}")

        """Initialize the Modbus hub."""
        _LOGGER.debug(f"solax modbushub creation with interface {interface} baudrate (only for serial): {baudrate}")
        self._hass = hass
        # explicit init for stop flag
        self._stopping = False
        if interface == "serial":
            self._client = AsyncModbusSerialClient(
                port=serial_port,
                baudrate=baudrate,
                parity="N",
                stopbits=1,
                bytesize=8,
                timeout=time_out,
                retries=RETRIES,
            )
        elif interface == "tcp":
            if tcp_type == "rtu":
                self._client = AsyncModbusTcpClient(
                    host=host, port=port, timeout=time_out, framer=FramerType.RTU, retries=RETRIES
                )
            elif tcp_type == "ascii":
                self._client = AsyncModbusTcpClient(
                    host=host, port=port, timeout=time_out, framer=FramerType.ASCII, retries=RETRIES
                )
            else:
                self._client = AsyncModbusTcpClient(host=host, port=port, timeout=time_out, retries=RETRIES)
        elif interface == "core":
            # Core-hub variant uses Home Assistant's Modbus hub; use harmless dummy client
            self._client = SimpleNamespace(connected=False, comm_params=SimpleNamespace(host="", port=""))
        else:
            # Fallback dummy client for unrecognized interface types
            self._client = SimpleNamespace(connected=False, comm_params=SimpleNamespace(host="", port=""))
        self._lock = asyncio.Lock()
        self._name = name
        # following call will modify and extend client in case old modbus API needs to be used
        _LOGGER.debug(f"{name}: using pymodbus version {pymodbus_version_info()}")

        self.inverterNameSuffix = config.get(CONF_INVERTER_NAME_SUFFIX)
        self.inverterPowerKw = config.get(CONF_INVERTER_POWER_KW, DEFAULT_INVERTER_POWER_KW)
        self._modbus_addr = modbus_addr
        self._seriesnumber = "still unknown"
        self.interface = interface
        self.read_serial_port = serial_port
        self._baudrate = int(baudrate)
        self._time_out = int(time_out)
        self.groups = {}  # group info, below
        self.data = {"_repeatUntil": {}}  # _repeatuntil contains button autorepeat expiry times
        self.tmpdata = {}  # for WRITE_DATA_LOCAL entities with corresponding prevent_update number/sensor
        self.tmpdata_expiry = {}  # expiry timestamps for tempdata
        self.cyclecount = 0  # temporary - remove later
        self.slowdown = (
            1  # slow down factor when modbus is not responding: 1 : no slowdown, 10: ignore 9 out of 10 cycles
        )
        self.computedSensors = {}
        self.computedEntities = {}  # buttons and selects with value_function for autorepeat
        self.computedSwitches = {}
        self.sensorEntities = {}  # all sensor entities, indexed by key
        self.numberEntities = {}  # all number entities, indexed by key
        self.selectEntities = {}
        self.switchEntities = {}
        self.entity_dependencies = {}  # Maps a sensor key to a list of data control keys that use the sensor as data source
        # self.preventSensors = {} # sensors with prevent_update = True
        self.writeLocals = {}  # key to description lookup dict for write_method = WRITE_DATA_LOCAL entities
        self.sleepzero = []  # sensors that will be set to zero in sleepmode
        self.sleepnone = []  # sensors that will be cleared in sleepmode
        self.writequeue = {}  # queue requests when inverter is in sleep mode
        _LOGGER.debug(f"{self.name}: ready to call plugin to determine inverter type")
        self.plugin = plugin.plugin_instance  # getPlugin(name).plugin_instance
        self.plugin_module = plugin  # Store plugin module for accessing module-level functions
        self._validate_register_func = getattr(plugin, "validate_register_data", None)  # Cache function reference
        self.wakeupButton = None
        self._invertertype = None
        self.localsUpdated = False
        self.localsLoaded = False
        self.config = config
        self.entry = entry
        self.device_info = None
        self.blocks_changed = False
        self.initial_groups = {}  # as returned by the sensor setup - holdingRegs and inputRegs should not change

        # Track in-flight I/O tasks for fast cancellation on stop
        self._inflight_tasks = set()

        # Bad register handling (startup bisect + deferred recheck)
        # bad_regs: definitively bad entity base-addresses (per register type)
        # bad_recheck: candidates found by bisect that must be revalidated later
        self.bad_regs = {"holding": set(), "input": set()}
        self.bad_recheck = {"holding": set(), "input": set()}
        self._did_initial_bisect = False
        self.bisect_max_depth = 10  # safety cap to avoid pathological recursion

        # Gate normal polling until initial probe completes
        self._probe_ready = asyncio.Event()

        # Deferred setup state
        self._platforms_forwarded = False
        self._deferred_setup_task = None

        # _LOGGER.debug("solax modbushub done %s", self.__dict__)

    async def async_init(self, *args: Any) -> None:  # noqa: D102
        import asyncio
        import time as _t

        self._init_task = asyncio.current_task()
        # Exit early if teardown requested
        if getattr(self, "_stopping", False):
            return

        # Try to detect inverter type, but do not block setup indefinitely.
        # We allow up to ~15s for initial detection; afterwards we proceed with a generic setup
        # so that the integration is usable even with no device connected.
        deadline = _t.monotonic() + 15.0
        attempts = 0
        while self._invertertype in (None, 0) and not getattr(self, "_stopping", False):
            try:
                await self.async_connect()
                await self._check_connection()
                if getattr(self, "_stopping", False):
                    return
                # Attempt type detection via plugin (may return 0/None if unreachable)
                self._invertertype = await self.plugin.async_determineInverterType(self, self.config)
                attempts += 1
                if self._invertertype not in (None, 0):
                    break
            except Exception as ex:
                _LOGGER.debug(f"{self._name}: inverter type detect attempt failed: {ex}")
                attempts += 1

            # Timeout reached → proceed to deferred setup if still not detected
            if _t.monotonic() >= deadline:
                break

            # Small paced wait to avoid tight loop; keep abortable while unloading
            for _ in range(100):
                if getattr(self, "_stopping", False):
                    return
                await asyncio.sleep(0.1)

        # If we reach here with no inverter detected, start deferred detection and return without forwarding platforms
        if self._invertertype in (None, 0):
            _LOGGER.debug(
                f"{self._name}: no inverter detected during initial window – deferring setup until device is online"
            )
            if not getattr(self, "_stopping", False):
                self._deferred_setup_task = self._hass.loop.create_task(self._deferred_setup_loop())
            return

        # Prepare device_info (inverter detected during initial window)
        plugin_name = self.plugin.plugin_name
        if self.inverterNameSuffix is not None and self.inverterNameSuffix != "":
            plugin_name = plugin_name + " " + self.inverterNameSuffix
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, self._name, INVERTER_IDENT)},
            manufacturer=self.plugin.plugin_manufacturer,
            model=getattr(self.plugin, "inverter_model", None),
            name=plugin_name,
            serial_number=self.seriesnumber,
        )

        if getattr(self, "_stopping", False):
            _LOGGER.info(f"{self._name}: init aborted – stopping during init")
            return

        # Forward platforms for this config entry
        # Platforms should be unloaded before reload, so this should always succeed
        if not self._platforms_forwarded:
            try:
                await self._hass.config_entries.async_forward_entry_setups(self.entry, PLATFORMS)
                self._platforms_forwarded = True
                _LOGGER.debug(f"{self._name}: platforms forwarded successfully")
            except ValueError as ex:
                # If platforms are already set up, log warning but continue
                # This shouldn't happen if unload worked properly, but handle gracefully
                _LOGGER.warning(f"{self._name}: platforms already forwarded - reload may not work correctly: {ex}")
                self._platforms_forwarded = True
        else:
            _LOGGER.debug(f"{self._name}: platforms already forwarded on this hub instance, skipping")

        self._init_task = None

    async def _deferred_setup_loop(self, interval: int = 30):
        """Keep trying to detect inverter type and forward platforms once online."""
        import asyncio

        while (not getattr(self, "_stopping", False)) and (not self._platforms_forwarded):
            try:
                await self.async_connect()
                await self._check_connection()
                if getattr(self, "_stopping", False):
                    return
                inv = await self.plugin.async_determineInverterType(self, self.config)
                if inv not in (None, 0):
                    self._invertertype = inv
                    _LOGGER.debug(
                        f"{self._name}: inverter detected during deferred setup (type={inv}) – forwarding platforms"
                    )
                    # Prepare/refresh device_info in case it wasn't set
                    plugin_name = self.plugin.plugin_name
                    if self.inverterNameSuffix:
                        plugin_name = plugin_name + " " + self.inverterNameSuffix
                    self.device_info = DeviceInfo(
                        identifiers={(DOMAIN, self._name, INVERTER_IDENT)},
                        manufacturer=self.plugin.plugin_manufacturer,
                        model=getattr(self.plugin, "inverter_model", None),
                        name=plugin_name,
                        serial_number=self.seriesnumber,
                    )
                    if getattr(self, "_stopping", False):
                        return
                    await self._hass.config_entries.async_forward_entry_setups(self.entry, PLATFORMS)
                    self._platforms_forwarded = True
                    return
            except Exception as ex:
                _LOGGER.debug(f"{self._name}: deferred setup iteration failed: {ex}")
            # Wait and try again
            for _ in range(interval * 10):  # sleep in 0.1s steps to remain abortable
                if getattr(self, "_stopping", False):
                    return
                await asyncio.sleep(0.1)

    # save and load local data entity values to make them persistent
    DATAFORMAT_VERSION = 1

    def saveLocalData(self):
        tosave = {"_version": self.DATAFORMAT_VERSION}
        for desc in self.writeLocals:
            tosave[desc] = self.data.get(desc)

        with open(self._hass.config.path(f"{self.name}_data.json"), "w") as fp:
            json.dump(tosave, fp)
        self.localsUpdated = False
        _LOGGER.debug(f"saved modified persistent date: {tosave}")

    def loadLocalData(self):
        try:
            fp = open(self._hass.config.path(f"{self.name}_data.json"))
        except:
            if self.cyclecount > 5:
                _LOGGER.debug(
                    f"no local data file found after 5 tries - is this a first time run? or didn't you modify any DATA_LOCAL entity?"
                )
                self.localsLoaded = True  # retry a couple of polling cycles - then assume non-existent"
            return
        try:
            loaded = json.load(fp)
        except:
            _LOGGER.debug("Local data file not readable. Resetting to empty")
            fp.close()
            self.saveLocalData()
            return
        else:
            if loaded.get("_version") == self.DATAFORMAT_VERSION:
                for desc in self.writeLocals:
                    val = loaded.get(desc)
                    if val != None:
                        self.data[desc] = val
                    else:
                        self.data[desc] = self.writeLocals[desc].initvalue  # first time initialisation
            else:
                _LOGGER.warning(f"local persistent data lost - please reinitialize {self.writeLocals.keys()}")
            fp.close()
            self.localsLoaded = True
            self.plugin.localDataCallback(self)
            try:
                self._hass.loop.call_soon_threadsafe(
                    self._hass.bus.async_fire,
                    "solax_modbus_local_data_loaded",
                    {"hub_name": self._name},
                )
            except Exception as ex:
                _LOGGER.debug(f"{self._name}: failed to fire local data event: {ex}")

    # end of save and load section

    def scan_group(self, sensor):  # seems to be called for non-sensor entities also - strange
        # scan group
        g = getattr(sensor.entity_description, "scan_group", None)
        if not g:
            regtype = getattr(sensor.entity_description, "register_type", None)
            if regtype == REG_HOLDING:
                g = self.plugin.default_holding_scangroup
            elif regtype == REG_INPUT:
                g = self.plugin.default_input_scangroup
            else:
                _LOGGER.debug(
                    f"{self._name}: default scan_group for {sensor.entity_description.key} returned {g} - {SCAN_GROUP_DEFAULT}"
                )
                g = SCAN_GROUP_DEFAULT  # should not occur

        if g == SCAN_GROUP_AUTO:
            unit = getattr(sensor.entity_description, "native_unit_of_measurement", None)
            if unit in (  # slow changing values
                UnitOfEnergy.WATT_HOUR,
                UnitOfEnergy.KILO_WATT_HOUR,
                UnitOfFrequency.HERTZ,
                UnitOfTemperature.CELSIUS,
                UnitOfTemperature.FAHRENHEIT,
                UnitOfTemperature.KELVIN,
                UnitOfTime.HOURS,
            ):
                g = self.plugin.auto_slow_scangroup
            else:
                g = self.plugin.auto_default_scangroup
        # scan interval
        g = self.config.get(g, None)
        # when declared but not present in config, use default; this MUST exist
        if g is None:
            _LOGGER.warning(
                f"{self._name}: Fast or Medium scan groups do not seem to exist in config: {g} using default {self.config[SCAN_GROUP_DEFAULT]}"
            )
            g = self.config[SCAN_GROUP_DEFAULT]
        else:
            _LOGGER.debug(f"{self._name}: returning scan_group interval {g} for {sensor.entity_description.key}")
        return g

    def device_group_key(self, device_info: DeviceInfo):
        key = ""
        for identifier in device_info["identifiers"]:
            if identifier[0] != DOMAIN:
                continue
            key = identifier[1] + "_" + identifier[2]

        return key

    # following function is the added_to_hass callback for sensors, numbers and selects
    @callback
    async def async_add_solax_modbus_sensor(self, sensor: SolaXModbusSensor):
        """Listen for data updates."""
        # attention, this function is not only called for sensors also for number, select
        # This is the first sensor, set up interval.
        interval = self.scan_group(sensor)
        interval_group = self.groups.setdefault(interval, empty_hub_interval_group_lambda())
        if not interval_group.device_groups:
            interval_group.interval = interval

            async def _refresh(_now: Optional[int] = None) -> None:
                secs = interval_group.interval
                self.cyclecount += 1
                cycle_id = self.cyclecount
                _LOGGER.debug(f"{self._name}: [{secs}s] poll started – cycle #{cycle_id}")
                # If a previous cycle is still running, mark a catch-up and return quickly.
                if interval_group.poll_lock.locked():
                    interval_group.pending_rerun = True
                    _LOGGER.debug(
                        f"{self._name}: [{secs}s] overrun – previous poll still running; scheduling immediate catch-up after it finishes"
                    )
                    return

                # Run cycles back-to-back if a tick was missed while running (catch-up mode)
                while True:
                    start = _mtime.monotonic()
                    async with interval_group.poll_lock:
                        agg_res, updated_sensors = await self.async_refresh_modbus_data(
                            interval_group, _now, cycle_id=cycle_id
                        )
                    elapsed = _mtime.monotonic() - start
                    _LOGGER.debug(
                        f"{self._name}: [{secs}s] poll finished – cycle #{cycle_id}, "
                        f"duration={int(elapsed * 1000)} ms, ok={agg_res}, "
                        f"sensors={updated_sensors}, slowdown={self.slowdown}"
                    )

                    # If the configured interval is shorter than the actual run time, inform once per cycle
                    if elapsed >= (interval_group.interval or 0):
                        _LOGGER.debug(
                            f"{self._name}: [{secs}s] interval too short – cycle took {elapsed:.3f}s ≥ interval {interval_group.interval}s; running at max possible speed"
                        )

                    # Immediate catch-up if a tick arrived during our run.
                    # Only perform catch-up when the last poll succeeded. On failure, drop the pending rerun.
                    if getattr(interval_group, "pending_rerun", False):
                        if agg_res:
                            interval_group.pending_rerun = False
                            # Loop again immediately (no sleep) to catch up once
                            continue
                        else:
                            # Previous poll failed; do not schedule a back-to-back retry.
                            interval_group.pending_rerun = False
                            _LOGGER.debug(
                                f"{self._name}: dropping pending catch-up due to failed poll (slowdown={self.slowdown})"
                            )
                            # Exit the loop; next attempt will occur per slowdown policy
                            break
                    break

            _LOGGER.debug(f"{self._name}: starting timer loop for interval group: {interval}")
            interval_group.unsub_interval_method = async_track_time_interval(
                self._hass, _refresh, timedelta(seconds=interval)
            )
        device_key = self.device_group_key(sensor.device_info)
        grp = interval_group.device_groups.setdefault(device_key, empty_hub_device_group_lambda())
        _LOGGER.debug(
            f"{self._name}: adding sensor {sensor.entity_description.key} available: {sensor._attr_available} "
        )
        grp.sensors.append(sensor)
        self.blocks_changed = True  # will force rebuild_blocks to be called

    @callback
    async def async_remove_solax_modbus_sensor(self, sensor):
        """Remove data update."""
        interval = self.scan_group(sensor)
        interval_group = self.groups.get(interval, None)
        if interval_group is None:
            return

        device_key = self.device_group_key(sensor.device_info)
        grp = interval_group.device_groups.get(device_key, None)
        if grp is None:
            return

        _LOGGER.debug(f"{self._name}:remove sensor {sensor.entity_description.key} remaining:{len(grp.sensors)} ")
        grp.sensors.remove(sensor)

        if not grp.sensors:
            _LOGGER.debug(f"removing device group {device_key}")
            interval_group.device_groups.pop(device_key)

            if not interval_group.device_groups:
                # stop the interval timer upon removal of last device group from interval group
                _LOGGER.debug(f"removing interval group {interval}")
                interval_group.unsub_interval_method()
                interval_group.unsub_interval_method = None
                self.groups.pop(interval)

                if not self.groups:
                    await self.async_close()
        self.blocks_changed = True  # will force rebuild_blocks to be called

    async def async_refresh_modbus_data(self, interval_group, _now: Optional[int] = None, cycle_id=None):
        """Time to update."""
        _LOGGER.debug(
            f"{self._name}: scan_group timer initiated refresh_modbus_data call - interval {interval_group.interval}"
        )
        # self.cyclecount = self.cyclecount + 1  # Now incremented in _refresh
        # Do not start normal polling until initial probe is done
        if not self._probe_ready.is_set():
            _LOGGER.debug(f"{self._name}: skipping poll – initial probe not done yet")
            return False, 0
        if not interval_group.device_groups:
            return True, 0
        if self.blocks_changed:
            self.rebuild_blocks(self.initial_groups)
        agg_res = True  # aggregate result across all device groups in this interval
        updated_sensors = 0  # how many entities were pushed this cycle
        # Use cyclecount from caller, not increment here
        if (self.cyclecount % self.slowdown) == 0:  # only execute once every slowdown count
            for group in list(
                interval_group.device_groups.values()
            ):  # not sure if this does not break things or affects performance
                group_result = await self.async_read_modbus_data(group)
                agg_res = agg_res and group_result
                if group_result:
                    if self.slowdown > 1:
                        _LOGGER.debug(f"{self._name}: communication restored, resuming normal speed after slowdown")
                    self.slowdown = 1  # return to full polling after successful cycle
                    for sensor in group.sensors:
                        sensor.modbus_data_updated()
                    updated_sensors += len(group.sensors)
                else:
                    if self.slowdown <= 1:
                        _LOGGER.debug(
                            f"{self._name}: modbus group read failed - assuming sleep mode - slowing down by factor 10"
                        )
                    self.slowdown = 10
                    for i in self.sleepnone:
                        self.data.pop(i, None)
                    for i in self.sleepzero:
                        self.data[i] = 0
                    # self.data = {} # invalidate data - do we want this ??

                _LOGGER.debug(f"{self._name}: device group read done")
        await self._maybe_refresh_energy_dashboard_on_primary_update()
        # Return aggregate result and updated sensor count to caller for logging
        return agg_res, updated_sensors

    async def _maybe_refresh_energy_dashboard_on_primary_update(self) -> None:
        if not self._hass:
            return
        if self.data.get("parallel_setting") != "Master":
            return

        pm_inverter_count = self.data.get("pm_inverter_count")
        if pm_inverter_count is None:
            return

        domain_data = self._hass.data.setdefault(DOMAIN, {})
        hub_entry = domain_data.setdefault(self._name, {})
        last_count = hub_entry.get("energy_dashboard_last_total_inverter_count")
        if last_count is None:
            hub_entry["energy_dashboard_last_total_inverter_count"] = pm_inverter_count
            return
        refresh_pending = hub_entry.get("energy_dashboard_refresh_pending")
        if pm_inverter_count <= last_count and not refresh_pending:
            return
        if refresh_pending:
            last_refresh_ts = hub_entry.get("energy_dashboard_last_refresh_ts", 0)
            if time() - last_refresh_ts < 5:
                return

        refresh_callback = hub_entry.get("energy_dashboard_refresh_callback")
        if not refresh_callback:
            hub_entry["energy_dashboard_last_total_inverter_count"] = pm_inverter_count
            return
        if hub_entry.get("energy_dashboard_refresh_in_progress"):
            return

        hub_entry["energy_dashboard_refresh_in_progress"] = True
        hub_entry["energy_dashboard_last_total_inverter_count"] = pm_inverter_count
        hub_entry["energy_dashboard_last_refresh_ts"] = time()

        async def _run_refresh():
            try:
                await refresh_callback()
            finally:
                hub_entry["energy_dashboard_refresh_in_progress"] = False

        self._hass.async_create_task(_run_refresh())

    @property
    def invertertype(self):
        return self._invertertype

    @invertertype.setter
    def invertertype(self, newtype):
        self._invertertype = newtype

    @property
    def seriesnumber(self):
        return self._seriesnumber

    @seriesnumber.setter
    def seriesnumber(self, nr):
        self._seriesnumber = nr

    @property
    def name(self):
        """Return the name of this hub."""
        return self._name

    async def async_close(self):
        """Disconnect client."""
        if self._client.connected:
            self._client.close()

    async def async_stop(self):
        """Stop polling/timers and close transport deterministically."""
        self._stopping = True
        # 1) stop interval timers
        for interval_group in list(self.groups.values()):
            unsub = getattr(interval_group, "unsub_interval_method", None)
            if unsub:
                try:
                    unsub()
                except Exception:
                    pass
                interval_group.unsub_interval_method = None
        self.groups.clear()
        # 2) stop any running tasks
        for tname in ("_initial_bisect_task", "_recheck_task"):
            task = getattr(self, tname, None)
            if task and not task.done():
                try:
                    task.cancel()
                except Exception:
                    pass
        # 2b) cancel init task if still running
        init_task = getattr(self, "_init_task", None)
        if init_task and not init_task.done():
            try:
                init_task.cancel()
            except Exception:
                pass
        # 2c) cancel deferred setup loop if scheduled
        dtask = getattr(self, "_deferred_setup_task", None)
        if dtask and not dtask.done():
            try:
                dtask.cancel()
            except Exception:
                pass
        # 2d) cancel in-flight I/O tasks immediately
        for task in list(self._inflight_tasks):
            try:
                task.cancel()
            except Exception:
                pass
        self._inflight_tasks.clear()
        # 3) freeze probe event
        try:
            self._probe_ready.set()
        except Exception:
            pass
        # 4) close transport
        try:
            if self._client and self._client.connected:
                self._client.close()
        except Exception:
            pass

    def _track_task(self, coro):
        """Wrap coroutines in a Task we can cancel during stop."""
        task = asyncio.create_task(coro)
        self._inflight_tasks.add(task)
        task.add_done_callback(lambda t: self._inflight_tasks.discard(t))
        return task

    # async def async_connect(self):
    #    """Connect client."""
    #    _LOGGER.debug("connect modbus")
    #    if not self._client.connected:
    #        async with self._lock:
    #            await self._client.connect()

    async def _check_connection(self):
        if getattr(self, "_stopping", False):
            return False
        if not self._client.connected:
            _LOGGER.debug(f"{self._name}: Inverter is not connected, trying to connect")
            await self._client.connect()
            await asyncio.sleep(1)
        return self._client.connected

    async def is_online(self):
        return self._client.connected and (self.slowdown == 1)

    async def async_connect(self):
        if getattr(self, "_stopping", False):
            return
        _LOGGER.debug(
            f"{self._name}: Trying to connect to Inverter at {self._client.comm_params.host}:{self._client.comm_params.port} connected: {self._client.connected} ",
        )
        await self._client.connect()

    async def async_read_holding_registers(self, unit, address, count):
        """Read holding registers using high-level pymodbus API."""
        async with self._lock:
            if getattr(self, "_stopping", False):
                return None
            await self._check_connection()
            if not self._client.connected:
                return None
            try:
                # Use high-level API; unit key is provided via ADDR_KW for compatibility
                kwargs = {ADDR_KW: unit} if unit is not None else {}
                _LOGGER.debug(f"{self._name}: READ HOLDING {ADDR_KW}={unit} addr=0x{address:x} cnt={count}")
                resp = await self._track_task(
                    self._client.read_holding_registers(address=address, count=count, **kwargs)
                )
            except ModbusException as exception_error:
                error = f"Error: device: {unit} address: 0x{address:x} -> {exception_error!s}"
                _LOGGER.error(error)
                # Flush transport: close + short pause + reconnect to clear any late/queued frames
                _LOGGER.debug(f"{self._name}: ModbusException – flushing transport and reconnecting")
                try:
                    self._client.close()
                finally:
                    await asyncio.sleep(0.2)
                    await self._client.connect()
                return None
        return resp

    async def async_read_input_registers(self, unit, address, count):
        """Read input registers using high-level pymodbus API."""
        async with self._lock:
            if getattr(self, "_stopping", False):
                return None
            await self._check_connection()
            if not self._client.connected:
                return None
            try:
                # Use high-level API; unit key is provided via ADDR_KW for compatibility
                kwargs = {ADDR_KW: unit} if unit is not None else {}
                _LOGGER.debug(f"{self._name}: READ INPUT  {ADDR_KW}={unit} addr=0x{address:x} cnt={count}")
                resp = await self._track_task(
                    self._client.read_input_registers(address=address, count=count, **kwargs)
                )
            except ModbusException as exception_error:
                error = f"Error: device: {unit} address: 0x{address:x} -> {exception_error!s}"
                _LOGGER.error(error)
                # Flush transport: close + short pause + reconnect to clear any late/queued frames
                _LOGGER.debug(f"{self._name}: ModbusException – flushing transport and reconnecting")
                try:
                    self._client.close()
                finally:
                    await asyncio.sleep(0.2)
                    await self._client.connect()
                return None
        return resp

    async def async_lowlevel_write_register(self, unit, address, payload):
        kwargs = {ADDR_KW: unit} if unit is not None else {}
        regs = convert_to_registers(int(payload), DataType.INT16, self.plugin.order32)
        async with self._lock:
            await self._check_connection()
            try:
                resp = await self._track_task(self._client.write_register(address=address, value=regs[0], **kwargs))
                # Plugin-level logging hook
                if hasattr(self.plugin, "log_register_write"):
                    self.plugin.log_register_write(self, address, unit, payload, result=resp)
            except (ConnectionException, ModbusIOException) as e:
                original_message = str(e)
                # Plugin-level logging hook
                if hasattr(self.plugin, "log_register_write"):
                    self.plugin.log_register_write(
                        self, address, unit, payload, error=(type(e).__name__, original_message)
                    )
                raise HomeAssistantError(f"Error writing single Modbus register: {original_message}") from e
        return resp

    async def async_write_register(self, unit, address, payload):
        """Write register."""
        awake = self.plugin.isAwake(self.data)
        if awake:
            return await self.async_lowlevel_write_register(unit, address, payload)
        else:
            # try to write anyway - could be a command that inverter responds to while asleep
            res = await self.async_lowlevel_write_register(unit, address, payload)
            # put request in queue, in order to repeat it when inverter wakes up
            self.writequeue[address] = payload
            # wake up inverter
            if self.wakeupButton:
                _LOGGER.info("waking up inverter: pressing awake button")
                return await self.async_lowlevel_write_register(
                    unit=self._modbus_addr,
                    address=self.wakeupButton.register,
                    payload=self.wakeupButton.command,
                )
            else:
                _LOGGER.warning("cannot wakeup inverter: no awake button found")
            return res

    async def async_write_registers_single(self, unit, address, payload):  # Needs adapting for register queue
        """Write registers multi, but write only one register of type 16bit"""
        regs = convert_to_registers(int(payload), DataType.INT16, self.plugin.order32)
        kwargs = {ADDR_KW: unit} if unit is not None else {}
        async with self._lock:
            await self._check_connection()
            try:
                resp = await self._track_task(self._client.write_registers(address=address, values=regs, **kwargs))
            except (ConnectionException, ModbusIOException) as e:
                original_message = str(e)
                raise HomeAssistantError(f"Error writing single Modbus registers: {original_message}") from e
        return resp

    async def async_write_registers_multi(self, unit, address, payload):  # Needs adapting for register queue
        """Write registers multi.
        unit is the modbus address of the device that will be written to
        address us the start register address
        payload is a list of tuples containing
            - a select or number entity keys names or alternatively REGISTER_xx type declarations
            - the values are the values that will be encoded according to the spec of that entity
        The list of tuples will be converted to a modbus payload with the proper encoding and written
        to modbus device with address=unit
        All register descriptions referenced in the payload must be consecutive (without leaving holes)
        32bit integers will be converted to 2 modbus register values according to the endian strategy of the plugin
        """
        kwargs = {ADDR_KW: unit} if unit is not None else {}
        if isinstance(payload, list):
            regs_out = []
            for (
                key,
                value,
            ) in payload:
                if key.startswith("_"):
                    typ = key
                    value = int(value)
                else:
                    descr = self.writeLocals[key]
                    # --- Begin safer reverse_option_dict mapping logic ---
                    if hasattr(descr, "reverse_option_dict") and descr.reverse_option_dict:
                        # Only map label->int if value is a str; if already numeric, keep as-is
                        if isinstance(value, str):
                            mapped = descr.reverse_option_dict.get(value)
                            if mapped is None:
                                # Accept numeric-like strings, else warn and leave as-is
                                try:
                                    value = int(value)
                                except Exception:
                                    _LOGGER.warning(
                                        f"{self._name}: unknown option '{value}' for {getattr(descr, 'key', '?')}; leaving value unchanged"
                                    )
                            else:
                                value = mapped
                        # if value is already int, leave it
                    elif callable(descr.scale):  # function to call ?
                        value = descr.scale(value, descr, self.data)
                    else:  # apply simple numeric scaling and rounding if not a list of words
                        try:
                            value = value * descr.scale
                        except Exception:
                            _LOGGER.error(f"cannot treat payload scale {value} {descr}")
                    try:
                        value = int(value)
                    except Exception:
                        _LOGGER.warning(
                            f"{self._name}: could not cast '{value}' to int for {getattr(descr, 'key', '?')}; leaving value unchanged"
                        )
                    typ = descr.unit
                try:
                    if typ == REGISTER_U16:
                        regs_out += convert_to_registers(value, DataType.UINT16, self.plugin.order32)
                    elif typ == REGISTER_S16:
                        regs_out += convert_to_registers(value, DataType.INT16, self.plugin.order32)
                    elif typ == REGISTER_U32:
                        regs_out += convert_to_registers(value, DataType.UINT32, self.plugin.order32)
                    elif typ == REGISTER_F32:
                        regs_out += convert_to_registers(value, DataType.FLOAT32, self.plugin.order32)
                    elif typ == REGISTER_S32:
                        regs_out += convert_to_registers(value, DataType.INT32, self.plugin.order32)
                    else:
                        _LOGGER.error(f"unsupported unit type: {typ} for {key}")
                except Exception as ex:
                    _LOGGER.error(
                        f"{self._name}: conversion for typ={typ} value={value} failed payload:{payload} with exception {ex}"
                    )
            online = await self.is_online()
            _LOGGER.debug(f"Ready to write multiple registers at 0x{address:02x}: {regs_out} online: {online} ")
            if online:
                async with self._lock:
                    try:
                        resp = await self._track_task(
                            self._client.write_registers(address=address, values=regs_out, **kwargs)
                        )
                    except (ConnectionException, ModbusIOException) as e:
                        original_message = str(e)
                        raise HomeAssistantError(f"Error writing multiple Modbus registers: {original_message}") from e
                return resp
            else:
                return None
        else:
            _LOGGER.error(f"write_registers_multi expects a list of tuples 0x{address:02x} payload: {payload}")
            return None

    async def async_read_modbus_data(self, group):
        res = True
        try:
            res = await self.async_read_modbus_registers_all(group)
        except ConnectionException as ex:
            _LOGGER.error(f"Reading data failed! Inverter is offline. {ex}")
            res = False
        except ModbusIOException as ex:
            _LOGGER.error(f"ModbusIOError: {ex}")
            res = False
        except Exception as ex:
            _LOGGER.exception(f"Something went wrong reading from modbus: {ex}")
            res = False
        return res

    def treat_address(self, data, regs, idx, descr, initval=0, advance=True):
        return_value = None
        read_scale = descr.read_scale  # read scale might still be wrong the first polling cycle
        order32 = getattr(descr, "order32", None) or self.plugin.order32
        val = None
        if self.cyclecount < VERBOSE_CYCLES:
            _LOGGER.debug(f"{self._name}: treating register 0x{descr.register:02x} : {descr.key}")
        words_used = 0
        try:
            if descr.unit == REGISTER_U16:
                val = convert_from_registers(regs[idx : idx + 1], DataType.UINT16, self.plugin.order32)
                words_used = 1
            elif descr.unit == REGISTER_S16:
                val = convert_from_registers(regs[idx : idx + 1], DataType.INT16, self.plugin.order32)
                words_used = 1
            elif descr.unit == REGISTER_U32:
                val = convert_from_registers(regs[idx : idx + 2], DataType.UINT32, order32)
                words_used = 2
            elif descr.unit == REGISTER_F32:
                val = convert_from_registers(regs[idx : idx + 2], DataType.FLOAT32, order32)
                words_used = 2
            elif descr.unit == REGISTER_S32:
                val = convert_from_registers(regs[idx : idx + 2], DataType.INT32, order32)
                words_used = 2
            elif descr.unit == REGISTER_STR:
                wc = descr.wordcount or 0
                raw = convert_from_registers(regs[idx : idx + wc], DataType.STRING, self.plugin.order32)
                words_used = wc
                val = raw.decode("ascii", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            elif descr.unit == REGISTER_WORDS:
                wc = descr.wordcount or 0
                val = [
                    convert_from_registers(regs[idx + i : idx + i + 1], DataType.UINT16, self.plugin.order32)
                    for i in range(wc)
                ]
                words_used = wc
            elif descr.unit == REGISTER_ULSB16MSB16:
                lo = convert_from_registers(regs[idx : idx + 1], DataType.UINT16, order32)
                hi = convert_from_registers(regs[idx + 1 : idx + 2], DataType.UINT16, order32)
                val = (hi + lo * 65536) if order32 == "big" else (lo + hi * 65536)
                words_used = 2
            elif descr.unit == REGISTER_U8L:
                if advance:
                    base = convert_from_registers(regs[idx : idx + 1], DataType.UINT16, self.plugin.order32)
                    words_used = 1
                    val = base % 256
                else:
                    val = initval % 256
                    words_used = 0
            elif descr.unit == REGISTER_U8H:
                if advance:
                    base = convert_from_registers(regs[idx : idx + 1], DataType.UINT16, self.plugin.order32)
                    words_used = 1
                    val = base >> 8
                else:
                    val = initval >> 8
                    words_used = 0
            else:
                _LOGGER.warning(f"{self._name}: undefinded unit for entity {descr.key} - setting value to zero")
                val = 0
                words_used = 0
        except Exception as ex:
            if self.cyclecount < VERBOSE_CYCLES:
                _LOGGER.warning(
                    f"{self._name}: read failed at 0x{descr.register:02x}: {descr.key}",
                    exc_info=True,
                )
            else:
                _LOGGER.warning(f"{self._name}: read failed at 0x{descr.register:02x}: {descr.key} ")
        """ TO BE REMOVED
        if descr.prevent_update:
            if  (self.tmpdata_expiry.get(descr.key, 0) > time()):
                val = self.tmpdata.get(descr.key, None)
                if val == None:
                    LOGGER.warning(f"cannot find tmpdata for {descr.key} - setting value to zero")
                    val = 0
            else: # expired
                if self.tmpdata_expiry.get(descr.key, 0) > 0: self.localsUpdated = True
                self.tmpdata_expiry[descr.key] = 0 # update locals only once
        """

        # Plugin-level validation hook
        if self._validate_register_func is not None:
            val = self._validate_register_func(descr, val, data)

        if val == None:  # E.g. if errors have occurred during readout
            # _LOGGER.warning(f"****tmp*** treating {descr.key} failed")
            return_value = None
        elif type(descr.scale) is dict:  # translate int to string
            return_value = descr.scale.get(val, "Unknown")
        elif callable(descr.scale):  # function to call ?
            return_value = descr.scale(val, descr, data)
        else:  # apply simple numeric scaling and rounding if not a list of words
            try:
                return_value = round(val * descr.scale * read_scale, descr.rounding)
            except:
                return_value = val  # probably a REGISTER_WORDS instance
            if descr.native_unit_of_measurement == UnitOfFrequency.HERTZ:
                min_val = getattr(descr, "min_value", 20)
                max_val = getattr(descr, "max_value", 80)
            if descr.native_unit_of_measurement == PERCENTAGE:
                min_val = getattr(descr, "min_value", 0)
                max_val = getattr(descr, "max_value", 100)
            elif descr.native_unit_of_measurement == UnitOfTemperature.CELSIUS:
                min_val = getattr(descr, "min_value", -100)
                max_val = getattr(descr, "max_value", 200)
            elif descr.native_unit_of_measurement == UnitOfPower.KILO_WATT:
                min_val = getattr(descr, "min_value", -self.inverterPowerKw * 2)
                max_val = getattr(descr, "max_value", +self.inverterPowerKw * 2)
            elif descr.native_unit_of_measurement == UnitOfElectricCurrent.AMPERE:
                min_val = getattr(descr, "min_value", -self.inverterPowerKw * 2)
                max_val = getattr(descr, "max_value", +self.inverterPowerKw * 2)
            elif descr.native_unit_of_measurement == UnitOfElectricPotential.VOLT:
                min_val = getattr(descr, "min_value", 0)
                max_val = getattr(descr, "max_value", 2000)
            else:
                min_val = getattr(descr, "min_value", None)
                max_val = getattr(descr, "max_value", None)

            if min_val is not None and return_value < min_val:
                raise ModbusIOException(f"Value {return_value} of '{descr.key}' lower than {min_val}")
            if max_val is not None and return_value > max_val:
                raise ModbusIOException(f"Value {return_value} of '{descr.key}' greater than {max_val}")
        # if (descr.sleepmode != SLEEPMODE_LASTAWAKE) or self.awakeplugin(self.data): self.data[descr.key] = return_value
        if (
            (self.tmpdata_expiry.get(descr.key, 0) == 0)
            and ((descr.sleepmode != SLEEPMODE_LASTAWAKE) or self.plugin.isAwake(self.data))
            and (
                self.localsLoaded or not descr.read_scale_exceptions
            )  # ignore as long as read scale is not adapted; may delay real startup a bit
        ):
            data[descr.key] = return_value  # case prevent_update number
        return idx + (words_used if advance else 0)

    async def async_read_modbus_block(self, data, block, typ):
        errmsg = None
        if self.cyclecount < VERBOSE_CYCLES:
            _LOGGER.debug(
                f"{self._name}: modbus {typ} block start: 0x{block.start:x} end: 0x{block.end:x}  len: {block.end - block.start} regs: {block.regs}"
            )
        try:
            if typ == "input":
                realtime_data = await self.async_read_input_registers(
                    unit=self._modbus_addr,
                    address=block.start,
                    count=block.end - block.start,
                )
            else:
                realtime_data = await self.async_read_holding_registers(
                    unit=self._modbus_addr,
                    address=block.start,
                    count=block.end - block.start,
                )
        except Exception as ex:
            errmsg = f"exception {str(ex)} "
            _LOGGER.debug(f"{self._name}: exception reading {typ} {block.start} {errmsg}")
        else:
            if realtime_data is None or realtime_data.isError():
                errmsg = f"read_error "
        if errmsg == None:
            regs = realtime_data.registers
            idx = 0
            for reg in block.regs:
                expected_idx = reg - block.start
                if idx < expected_idx:
                    if self.cyclecount < 5 and expected_idx > idx:
                        _LOGGER.debug(f"skipping bytes {(expected_idx - idx) * 2}")
                    idx = expected_idx

                descr = block.descriptions[reg]

                if isinstance(descr, dict):
                    base16 = convert_from_registers(regs[idx : idx + 1], DataType.UINT16, self.plugin.order32)
                    for k in descr:
                        self.treat_address(data, regs, idx, descr[k], initval=base16, advance=False)
                    idx += 1
                else:
                    idx = self.treat_address(data, regs, idx, descr, initval=0, advance=True)
            return True
        else:  # block read failure
            firstdescr = block.descriptions[block.start]  # check only first item in block
            _LOGGER.debug(
                f"{self._name}: failed {typ} block {errmsg} start 0x{block.start:x} {firstdescr.key} ignore_readerror: {firstdescr.ignore_readerror}"
            )
            if firstdescr.ignore_readerror is False:  # dont ignore block read errors and return static data
                _LOGGER.debug(
                    f"{self._name}: failed block analysis started firstignore: {firstdescr.ignore_readerror}"
                )
                for reg in block.regs:
                    descr = block.descriptions[reg]
                    if type(descr) is dict:
                        l = descr.items()  # special case: multiple U8x entities
                    else:
                        l = {
                            descr.key: descr,
                        }.items()  # normal case, one entity
                    for k, d in l:
                        d_ignore = d.ignore_readerror
                        if (d_ignore is not True) and (d_ignore is not False):
                            _LOGGER.debug(f"{self._name}: returning static {k} = {d_ignore}")
                            data[k] = d_ignore  # return something static
                        else:
                            if d_ignore is False:  # remove potentially faulty data
                                popped = data.pop(k, None)  # added 20250716
                                _LOGGER.debug(f"{self._name}: popping {k} = {popped}")
                            else:
                                _LOGGER.debug(f"{self._name}: not touching {k} ")
                return True
            else:  # ignore readerrors and keep old data
                if self.slowdown == 1:
                    _LOGGER.info(
                        f"{self._name} : {errmsg}: cannot read {typ} registers at device {self._modbus_addr} position 0x{block.start:x}",
                        exc_info=True,
                    )
                return False

    async def async_read_modbus_registers_all(self, group):
        if group.readPreparation is not None:
            if not await group.readPreparation(self.data):
                _LOGGER.info(f"{self._name}: device group read cancel")
                return True
        else:
            _LOGGER.debug(f"{self._name}: device group inverter")

        # data = {"_repeatUntil": self.data["_repeatUntil"]} # remove for issue #1440 but then does not recognize comm errors
        data = self.data  # is an alias, not a copy (issue #1440)
        res = True
        for block in group.holdingBlocks:
            _LOGGER.debug(f"{self._name}: ** trying to read holding block 0x{block.start:x} previous res:{res}")
            res = res and await self.async_read_modbus_block(data, block, "holding")
            _LOGGER.debug(f"{self._name}: holding block 0x{block.start:x} read done; new res: {res}")
        for block in group.inputBlocks:
            _LOGGER.debug(f"{self._name}: ** trying to read input block 0x{block.start:x} previous res: {res}")
            res = res and await self.async_read_modbus_block(data, block, "input")
            _LOGGER.debug(f"{self._name}: input block 0x{block.start:x} read done; new res: {res}")

        if self.localsUpdated:
            await self._hass.async_add_executor_job(self.saveLocalData)
            self.plugin.localDataCallback(self)
        if not self.localsLoaded:
            await self._hass.async_add_executor_job(self.loadLocalData)
        for key, descr in self.computedSensors.items():
            # Do NOT call modbus_data_updated() from here Race Condition:it calls hub.rebuild_blocks() before async_add_entities is called.
            data[key] = descr.value_function(0, descr, data)
            sens = self.sensorEntities[key]
            _LOGGER.debug(f"{self._name}: quickly updating state for computed sensor {sens} {key} {data[descr.key]} ")
            if sens and (not descr.internal):
                try:
                    sens.modbus_data_updated()  # publish state to GUI and automations faster - assuming enabled, otherwise exception
                except Exception:
                    _LOGGER.debug(f"{self._name}: cannot send update for {key} - probably disabled ")

        if group.readFollowUp is not None:
            if not await group.readFollowUp(self.data, data):
                _LOGGER.warning(f"device group check not success")
                return True

        # for key, value in data.items(): # remove for issue #1440, but then does not recognize communication errors anymore
        #    self.data[key] = value # remove for issue #1440, but then comm errors are not detected

        if res and self.writequeue and self.plugin.isAwake(self.data):  # self.awakeplugin(self.data):
            # process outstanding write requests
            _LOGGER.info(f"inverter is now awake, processing outstanding write requests {self.writequeue}")
            for addr in self.writequeue.keys():
                val = self.writequeue.get(addr)
                await self.async_write_register(self._modbus_addr, addr, val)
            self.writequeue = {}  # make sure we do not write multiple times

        # execute autorepeat entities (buttons and selects)
        self.last_ts = time()
        for (
            k,
            v,
        ) in list(self.data["_repeatUntil"].items()):  # use a list copy because dict may change during iteration
            descr = self.computedEntities.get(k)
            if descr and self.last_ts < v:
                payload = descr.value_function(BUTTONREPEAT_LOOP, descr, self.data)  # initval = 1 means autorepeat run
                if payload:
                    reg = payload.get("register", descr.register)
                    action = payload.get("action")
                    if not action:
                        _LOGGER.error(f"autorepeat value function for {k} must return dict containing action")
                    elif action == WRITE_MULTI_MODBUS:
                        _LOGGER.debug(f"**debug** ready to repeat {k} data: {payload}")
                        await self.async_write_registers_multi(
                            unit=self._modbus_addr,
                            address=reg,
                            payload=payload.get("data"),
                        )
                    elif action == WRITE_SINGLE_MODBUS:
                        _LOGGER.debug(f"Repeating {k} register {reg} value {payload.get('payload')}")
                        await self.async_write_register(
                            unit=self._modbus_addr, address=reg, payload=payload.get("payload")
                        )
            elif descr:  # expired autorepeats
                if self.data["_repeatUntil"][k] > 0:  # expired recently
                    self.data["_repeatUntil"][k] = (
                        0  # mark as finally expired, no further buttonrepeat post after this one
                    )
                    _LOGGER.info(f"calling final value function POST for {k} with initval {BUTTONREPEAT_POST}")
                    payload = descr.value_function(
                        BUTTONREPEAT_POST, descr, self.data
                    )  # None means no final call after expiration
                    if payload:
                        reg = payload.get("register", descr.register)
                        action = payload.get("action")
                        if action == WRITE_MULTI_MODBUS:
                            _LOGGER.info(f"terminating loop {k} - ready to send final payload data: {payload}")
                            await self.async_write_registers_multi(
                                unit=self._modbus_addr,
                                address=reg,
                                payload=payload.get("data"),
                            )
        return res

    # --------------------------------------------- Check if sensor is a dependency -----------------------------------------------

    def _is_dependency_for_enabled_control(self, sensor_key: str) -> bool:
        """Check if a sensor is a required data source for any enabled control."""
        control_keys = self.entity_dependencies.get(sensor_key, [])
        for control_key in control_keys:  # usually zero or one key
            # This sensor is a dependency. Now, is the control that needs it enabled?
            # We can reuse the logic from should_register_be_loaded, but we need to find the correct descriptor first.
            control_descr = None
            # currently, a sensor can only have one associated control - is this comment still true???
            if self.selectEntities.get(control_key):
                control_descr = self.selectEntities.get(control_key).entity_description
            if (not control_descr) and self.numberEntities.get(control_key):
                control_descr = self.numberEntities.get(control_key).entity_description
            if (not control_descr) and self.switchEntities.get(control_key):
                control_descr = self.switchEntities.get(control_key).entity_description
            if (not control_descr) and self.sensorEntities.get(control_key):
                control_descr = self.sensorEntities.get(control_key).entity_description
            if control_descr and should_register_be_loaded(self._hass, self, control_descr):
                _LOGGER.debug(
                    f"Sensor '{sensor_key}' is required by enabled control or value_function entity '{control_key}'."
                )
                return True
        return False

    # --------------------------------------------- Sorting and grouping of entities -----------------------------------------------

    def splitInBlocks(self, descriptions):
        start = INVALID_START
        end = 0
        blocks = []
        block_size = self.plugin.block_size
        auto_block_ignore_readerror = self.plugin.auto_block_ignore_readerror
        curblockregs = []
        for reg, descr in descriptions.items():
            d_ignore_readerror = auto_block_ignore_readerror
            if type(descr) is dict:  # 2 byte  REGISTER_U8L, _U8H values on same modbus 16 bit address
                d_newblock = False
                d_enabled = False
                for sub, d in descr.items():
                    # d_newblock = d_newblock or d.newblock # ok, if needed, put a newblock on all subentries
                    if should_register_be_loaded(
                        self._hass, self, d
                    ):  # *** CHANGED LINE: logic delegated to new function
                        d_enabled = True
                        break
                    d_unit = d.unit
                    d_wordcount = 1  # not used here
                    d_key = d.key  # does not matter which key we use here
                    d_regtype = d.register_type
            else:  # normal entity
                # 1. First, check if the entity itself should be loaded based on its own state or defaults.
                d_enabled = should_register_be_loaded(self._hass, self, descr)

                # 2. If it's disabled, check if it's a required dependency for another ENABLED control.
                if not d_enabled:
                    if self._is_dependency_for_enabled_control(descr.key):
                        d_enabled = True
                        _LOGGER.debug(
                            f"{self._name}: Forcing poll for disabled sensor '{descr.key}' as it's a needed dependency."
                        )

                d_newblock = descr.newblock
                d_unit = descr.unit
                d_wordcount = descr.wordcount
                d_key = descr.key
                d_regtype = descr.register_type  # HOLDING or INPUT

            if d_enabled:
                if d_newblock or ((reg - start) > block_size):
                    if (end - start) > 0:
                        _LOGGER.debug(f"{self._name}: Starting new block at 0x{reg:x} ")
                        if (
                            (auto_block_ignore_readerror is True) or (auto_block_ignore_readerror is False)
                        ) and not d_newblock:  # automatically created block
                            if type(descr) is dict:
                                for sub, d in descr.items():
                                    if d.ignore_readerror is False:
                                        d.ignore_readerror = auto_block_ignore_readerror
                                        d_ignore_readerror = d_ignore_readerror or d.ignore_readerror
                            else:
                                if descr.ignore_readerror is False:
                                    descr.ignore_readerror = auto_block_ignore_readerror
                                    d_ignore_readerror = descr.ignore_readerror
                        # newblock = block(start = start, end = end, order16 = descriptions[start].order16, order32 = descriptions[start].order32, descriptions = descriptions, regs = curblockregs)
                        newblock = block(start=start, end=end, descriptions=descriptions, regs=curblockregs)
                        blocks.append(newblock)
                        start = INVALID_START
                        end = 0
                        curblockregs = []
                    else:
                        _LOGGER.debug(f"{self._name}: newblock declaration found for empty block")

                if start == INVALID_START:
                    start = reg

                # Skip definitively bad entity bases and split blocks at bad boundaries
                typ_key = "holding" if d_regtype == REG_HOLDING else "input"
                if reg in self.bad_regs[typ_key]:
                    # Close current block if it already has content
                    if (end - start) > 0:
                        newblock = block(start=start, end=end, descriptions=descriptions, regs=curblockregs)
                        blocks.append(newblock)
                    # Reset for next block after the bad address
                    start = INVALID_START
                    end = 0
                    curblockregs = []
                    _LOGGER.debug(f"{self._name}: skipping bad {typ_key} register 0x{reg:x}")
                    continue

                _LOGGER.debug(
                    f"{self._name}: adding register 0x{reg:x} {d_key} to block with start 0x{start:x} ignore_readerror:{d_ignore_readerror}"
                )
                if d_unit in (
                    REGISTER_STR,
                    REGISTER_WORDS,
                ):
                    if d_wordcount:
                        end = reg + d_wordcount
                    else:
                        _LOGGER.warning(f"{self._name}: invalid or missing missing wordcount for {d_key}")
                elif d_unit in (
                    REGISTER_S32,
                    REGISTER_U32,
                    REGISTER_ULSB16MSB16,
                ):
                    end = reg + 2
                else:
                    end = reg + 1
                _LOGGER.debug(
                    f"{self._name}: adding type {d_regtype} register 0x{reg:x} {d_key} to block with start 0x{start:x}"
                )
                curblockregs.append(reg)
            else:
                _LOGGER.debug(
                    f"{self._name}: ignoring type {d_regtype} register 0x{reg:x} {d_key} to block with start 0x{start:x}"
                )

        if (end - start) > 0:  # close last block
            # newblock = block(start = start, end = end, order16 = descriptions[start].order16, order32 = descriptions[start].order32, descriptions = descriptions, regs = curblockregs)
            newblock = block(start=start, end=end, descriptions=descriptions, regs=curblockregs)
            blocks.append(newblock)
        return blocks

    def rebuild_blocks(self, initial_groups):  # , computedRegs):
        _LOGGER.debug(f"{self._name}: rebuilding groups and blocks - pre: {initial_groups.keys()}")
        self.initial_groups = initial_groups
        for interval, interval_group in initial_groups.items():
            for device_name, device_group in interval_group.device_groups.items():
                _LOGGER.debug(f"{self._name}: rebuild for device {device_name} in interval {interval}")
                holdingRegs = dict(sorted(device_group.holdingRegs.items()))
                inputRegs = dict(sorted(device_group.inputRegs.items()))
                # update the hub groups
                hub_interval_group = self.groups.setdefault(interval, empty_hub_interval_group_lambda())
                hub_device_group = hub_interval_group.device_groups.setdefault(
                    device_name, empty_hub_device_group_lambda()
                )
                hub_device_group.readPreparation = device_group.readPreparation
                hub_device_group.readFollowUp = device_group.readFollowUp
                hub_device_group.holdingBlocks = self.splitInBlocks(holdingRegs)
                hub_device_group.inputBlocks = self.splitInBlocks(inputRegs)
                # self.computedSensors = computedRegs # moved outside the loops
                for i in hub_device_group.holdingBlocks:
                    _LOGGER.debug(
                        f"{self._name} - interval {interval}s: adding holding block: {', '.join('0x{:x}'.format(num) for num in i.regs)}"
                    )
                for i in hub_device_group.inputBlocks:
                    _LOGGER.debug(
                        f"{self._name} - interval {interval}s: adding input block: {', '.join('0x{:x}'.format(num) for num in i.regs)}"
                    )
                # _LOGGER.debug(f"holdingBlocks: {hub_device_group.holdingBlocks}")
                # _LOGGER.debug(f"inputBlocks: {hub_device_group.inputBlocks}")
        self.blocks_changed = False
        _LOGGER.debug(f"{self._name}: done rebuilding groups and blocks - post: {self.initial_groups.keys()}")

        # Trigger a single initial bisect run (non-blocking) after the very first build
        if not self._did_initial_bisect:
            self._did_initial_bisect = True
            # hold off normal polling until probe finishes
            self._probe_ready.clear()
            # run in background to avoid delaying the event loop
            self._initial_bisect_task = self._hass.loop.create_task(self._run_initial_bisect_for_all_groups())

    async def _run_initial_bisect_for_all_groups(self):
        """Run a one-time bisect over all current blocks to discover unreadable entity bases.
        The result updates self.bad_recheck and schedules a delayed revalidation.
        """
        import asyncio
        import time as _t

        bisect_start_time = _t.monotonic()
        bisect_timeout = 30.0  # Maximum 30 seconds for bisect to complete

        try:
            # If not online, postpone once to avoid mislabeling during startup flaps
            if not await self.is_online():
                _LOGGER.debug(f"{self._name}: initial bisect postponed (offline)")
                await asyncio.sleep(5)
                if not await self.is_online():
                    _LOGGER.debug(f"{self._name}: initial bisect skipped (still offline) – allowing polling")
                    self._probe_ready.set()
                    return

            # Walk through all currently built groups/blocks
            for interval_group in self.groups.values():
                # Check timeout periodically
                if (_t.monotonic() - bisect_start_time) > bisect_timeout:
                    _LOGGER.warning(
                        f"{self._name}: initial bisect timeout after {bisect_timeout}s – enabling polling anyway"
                    )
                    self._probe_ready.set()
                    return

            for dev_group in list(interval_group.device_groups.values()):
                # Check timeout before each block
                if (_t.monotonic() - bisect_start_time) > bisect_timeout:
                    _LOGGER.warning(
                        f"{self._name}: initial bisect timeout after {bisect_timeout}s – enabling polling anyway"
                    )
                    self._probe_ready.set()
                    return

                for blk in getattr(dev_group, "holdingBlocks", []):
                    await self._initial_bisect_block(blk, "holding")
                for blk in getattr(dev_group, "inputBlocks", []):
                    await self._initial_bisect_block(blk, "input")

            # If no suspects were identified by the initial bisect, log that explicitly
            if not (self.bad_recheck["holding"] or self.bad_recheck["input"]):
                _LOGGER.debug(f"{self._name}: initial bisect found no suspect registers.")

            # Probing completed – enable polling
            self._probe_ready.set()
        except Exception as e:
            _LOGGER.error(f"{self._name}: Exception in initial bisect: {e}", exc_info=True)
            # Always set probe_ready on exception to avoid permanent blocking
            self._probe_ready.set()

        # Re-validate candidates after a short grace period
        self._recheck_task = self._hass.loop.create_task(self._recheck_bad_after(30))

    async def _initial_bisect_block(self, block_obj, typ):
        """Bisect a block once at startup. Operates on *entity bases* only, so multi-register
        entities (U32/STR/WORDS) are never split apart. No value decoding happens here."""
        try:
            await self._read_block_with_bisect_once(block_obj, typ)
        except Exception as ex:
            _LOGGER.debug(
                f"{self._name}: exception during initial bisect ({typ}) 0x{block_obj.start:x}-0x{block_obj.end:x}: {ex}"
            )

    async def _read_block_with_bisect_once(self, block_obj, typ, depth=0):
        """Attempt a raw bulk read for the block. If it fails and we are online, split the entity-base
        list into halves and probe recursively until single-entity blocks are found.
        Single-entity failures are added to bad_recheck (not yet definitive)."""
        if await self._probe_block(block_obj, typ):
            return True

        # Avoid false positives when transport is down / slowed
        if not await self.is_online():
            _LOGGER.debug(f"{self._name}: assuming offline during bisect")
            return False

        _LOGGER.debug(
            f"{self._name}: probe not fully ok: depth {depth}/{self.bisect_max_depth} len: {len(block_obj.regs) or []}"
        )
        regs = block_obj.regs or []
        if depth >= self.bisect_max_depth or len(regs) <= 1:
            if len(regs) == 1:
                addr = regs[0]
                self.bad_recheck[typ].add(addr)
                _LOGGER.debug(f"{self._name}: candidate bad {typ} entity base 0x{addr:x}")
            return True

        # Split entity-base list (keeps multi-register entities intact)
        mid = len(regs) // 2
        left = self._subblock_entity_span(block_obj, 0, mid)
        right = self._subblock_entity_span(block_obj, mid, len(regs))

        await self._read_block_with_bisect_once(left, typ, depth + 1)
        await self._read_block_with_bisect_once(right, typ, depth + 1)
        return True

    async def _recheck_bad_after(self, seconds):
        """After a grace period, re-validate all candidate bad entity bases. Only reproducible
        failures are promoted to definitive bad_regs; otherwise the candidate is dropped."""
        await asyncio.sleep(seconds)
        confirmed_any = False
        for typ in ("holding", "input"):
            candidates = list(self.bad_recheck[typ])
            for addr in candidates:
                ok = False
                # Entity-Span ermitteln (damit STR/WORDS/U32 nicht zerschnitten werden)
                try:
                    desc_map = None
                    for interval_group in self.groups.values():
                        for dev_group in list(interval_group.device_groups.values()):
                            blocks = (
                                getattr(dev_group, "holdingBlocks", [])
                                if typ == "holding"
                                else getattr(dev_group, "inputBlocks", [])
                            )
                            for blk in blocks:
                                if addr in (blk.regs or []):
                                    desc_map = blk.descriptions
                                    break
                            if desc_map is not None:
                                break
                        if desc_map is not None:
                            break
                    if desc_map is not None:
                        end = self._entity_span_end(desc_map, addr)
                    else:
                        end = addr + 1
                    single = block(start=addr, end=end, descriptions=None, regs=[addr])
                except Exception:
                    single = block(start=addr, end=addr + 1, descriptions=None, regs=[addr])

                # Drei schnelle Re-Checks, um Transienten auszuschließen
                for _ in range(3):
                    if await self.is_online() and await self._probe_block(single, typ):
                        ok = True
                        break
                    await asyncio.sleep(0.05)

                if ok:
                    self.bad_recheck[typ].discard(addr)
                    _LOGGER.info(f"{self._name}: entity base 0x{addr:x} ({typ}) recovered on recheck")
                else:
                    self.bad_regs[typ].add(addr)
                    self.bad_recheck[typ].discard(addr)
                    confirmed_any = True
                    _LOGGER.warning(f"{self._name}: confirmed bad {typ} entity base 0x{addr:x}")

        if confirmed_any:
            # Beim nächsten Poll werden Blöcke neu gebaut, schlechte Basen ausgeschlossen
            self.blocks_changed = True
        else:
            _LOGGER.info(f"{self._name}: no bad registers confirmed on recheck.")

    def _entity_span_end(self, desc_map, base_reg):
        """Compute end address (exclusive) for a single entity starting at base_reg based on its unit.
        This ensures we never split STR/WORDS or 32-bit entities."""
        descr = desc_map.get(base_reg)
        if descr is None:
            return base_reg + 1
        # If the descriptor is a dict of byte-split entities (U8H/U8L), they share the same 16-bit reg
        if isinstance(descr, dict):
            return base_reg + 1
        unit = getattr(descr, "unit", None)
        if unit in (REGISTER_S32, REGISTER_U32, REGISTER_F32, REGISTER_ULSB16MSB16):
            return base_reg + 2
        if unit in (REGISTER_STR, REGISTER_WORDS):
            wc = getattr(descr, "wordcount", 1) or 1
            return base_reg + wc
        return base_reg + 1

    def _subblock_entity_span(self, block_obj, i0, i1):
        """Create a sub-block using entity-base indices [i0, i1), computing a correct exclusive end
        based on the last entity's span. This preserves multi-register entities on reads."""
        regs = block_obj.regs[i0:i1]
        # start is the first entity base
        start = regs[0]
        # end must honor the last entity's full span
        last_base = regs[-1]
        end = self._entity_span_end(block_obj.descriptions, last_base)
        return block(start=start, end=end, descriptions=block_obj.descriptions, regs=regs)

    async def _probe_block(self, block_obj, typ):
        if getattr(self, "_stopping", False):
            return False
        """Transport-level probe: perform a raw modbus read for [start, end) without decoding.
        Returns True if the read returns a non-error response; False on error/timeout."""
        count = max(0, block_obj.end - block_obj.start)
        if count <= 0:
            return True
        try:
            _LOGGER.debug(f"{self._name}: probing {typ} 0x{block_obj.start:x}-0x{block_obj.end:x}")
            if typ == "input":
                resp = await self.async_read_input_registers(
                    unit=self._modbus_addr, address=block_obj.start, count=count
                )
            else:
                resp = await self.async_read_holding_registers(
                    unit=self._modbus_addr, address=block_obj.start, count=count
                )
            if resp is None:
                return False
            is_err = getattr(resp, "isError", lambda: False)()
            return not is_err
        except Exception as ex:
            _LOGGER.info(f"{self._name}: probe {typ} 0x{block_obj.start:x}-0x{block_obj.end:x} failed: {ex}")
            return False


# --- SolaXCoreModbusHub class ---


class SolaXCoreModbusHub(SolaXModbusHub, CoreModbusHub):
    """Thread safe wrapper class for pymodbus."""

    def __init__(
        self,
        hass,
        plugin,
        entry,
    ):
        SolaXModbusHub.__init__(self, hass, plugin, entry)
        config = entry.options
        core_hub_name = config.get(CONF_CORE_HUB, "")
        self._core_hub = core_hub_name
        self._hub = None
        _LOGGER.debug(f"solax via core modbus hub '{core_hub_name}")

        _LOGGER.debug("setup solax core modbus hub done %s", self.__dict__)

    async def async_close(self):
        """Disconnect client."""
        with self._lock:
            if self._hub:
                self._hub = None

    # async def async_connect(self):
    #    """Connect client."""
    #    _LOGGER.debug("connect modbus")
    #    if not self._client.connected:
    #        async with self._lock:
    #            await self._client.connect()

    async def _check_connection(self):
        # get hold of temporary strong reference to CoreModbusHub object
        # and pass it on success to caller if available
        if self._hub is None or (hub := self._hub()) is None:
            return await self.async_connect()
        async with hub._lock:
            try:
                if hub._client.connected:
                    return hub
            except (TypeError, AttributeError):
                pass
        _LOGGER.debug(f"{self._name}: Inverter is not connected, trying to connect")
        return await self.async_connect(hub)

    async def is_online(self):
        """Reflect online state using the Core Modbus hub client."""
        try:
            hub = self._hub() if self._hub is not None else None
        except Exception:
            hub = None
        try:
            return bool(hub and getattr(hub, "_client", None) and hub._client.connected and (self.slowdown == 1))
        except Exception:
            return False

    def _hub_closed_now(self, ref_obj):
        with self._lock:
            if ref_obj is self._hub:
                self._hub = None

    async def async_connect(self, hub=None):
        delay = True
        while True:
            # check if strong reference to
            # get one.
            if hub is not None or (self._hub is not None and (hub := self._hub()) is not None):
                port = hub._pb_params.get("port", 0)
                host = hub._pb_params.get("host", port)
                # TODO just wait some time and recheck again if client connected before
                # giving up
                await hub._lock.acquire()
                try:
                    if hub._client and hub._client.connected:
                        hub._lock.release()
                        _LOGGER.debug(
                            "Inverter connected at %s:%s",
                            host,
                            port,
                        )
                        return hub
                except (TypeError, AttributeError):
                    pass
                hub._lock.release()
                if not delay:
                    reason = " core modbus hub '{self._core_hub}' not ready" if hub._config_delay else ""
                    _LOGGER.warning(f"Unable to connect to Inverter at {host}:{port}.{reason}")
                    return None
            else:
                # get hold of current CoreModbusHub object with
                # provided entity name
                try:
                    hub = get_core_hub(self._hass, self._core_hub)
                except KeyError:
                    _LOGGER.warning(
                        f"CoreModbusHub '{self._core_hub}' not available",
                    )
                    return None
                else:
                    if hub:
                        # update weak reference handle to refer to
                        # the actual CoreModbusHub object
                        self._hub = WeakRef(hub, self._hub_closed_now)
                        continue
                if not delay:
                    _LOGGER.warning(
                        "Unable to join core modbus %s",
                        self._core_hub,
                    )
                    return None
            # wait some time (TODO make configurable) before
            # rechecking if CoreModbusHub object has been created and
            # connected
            delay = False
            await asyncio.sleep(10)

    async def async_read_holding_registers(self, unit, address, count):
        """Read holding registers."""
        kwargs = {ADDR_KW: unit} if unit is not None else {}
        if getattr(self, "_stopping", False):
            return None
        async with self._lock:
            hub = await self._check_connection()
        try:
            if not hub or getattr(hub, "_config_delay", False):
                return None
            async with hub._lock:
                try:
                    resp = await self._track_task(
                        hub._client.read_holding_registers(address=address, count=count, **kwargs)
                    )
                except (ConnectionException, ModbusIOException) as e:
                    original_message = str(e)
                    raise HomeAssistantError(f"Error reading Modbus holding registers: {original_message}") from e
            return resp
        except (TypeError, AttributeError) as e:
            raise HomeAssistantError("Error reading Modbus holding registers: core modbus access failed") from e

    async def async_read_input_registers(self, unit, address, count):
        """Read input registers."""
        kwargs = {ADDR_KW: unit} if unit is not None else {}
        if getattr(self, "_stopping", False):
            return None
        async with self._lock:
            hub = await self._check_connection()
        try:
            if not hub or getattr(hub, "_config_delay", False):
                return None
            async with hub._lock:
                try:
                    resp = await self._track_task(
                        hub._client.read_input_registers(address=address, count=count, **kwargs)
                    )
                except (ConnectionException, ModbusIOException) as e:
                    original_message = str(e)
                    raise HomeAssistantError(f"Error reading Modbus input registers: {original_message}") from e
            return resp
        except (TypeError, AttributeError) as e:
            raise HomeAssistantError("Error reading Modbus input registers: core modbus access failed") from e

    async def async_lowlevel_write_register(self, unit, address, payload):
        """
        Write a single register using the Core hub's client.
        """
        regs = convert_to_registers(int(payload), DataType.INT16, self.plugin.order32)
        kwargs = {ADDR_KW: unit} if unit is not None else {}
        if getattr(self, "_stopping", False):
            return None
        async with self._lock:
            hub = await self._check_connection()
        try:
            if not hub or getattr(hub, "_config_delay", False):
                return None
            async with hub._lock:
                try:
                    resp = await self._track_task(hub._client.write_register(address=address, value=regs[0], **kwargs))
                    # Plugin-level logging hook
                    if hasattr(self.plugin, "log_register_write"):
                        self.plugin.log_register_write(self, address, unit, payload, result=resp)
                except (ConnectionException, ModbusIOException) as e:
                    original_message = str(e)
                    # Plugin-level logging hook
                    if hasattr(self.plugin, "log_register_write"):
                        self.plugin.log_register_write(
                            self, address, unit, payload, error=(type(e).__name__, original_message)
                        )
                    raise HomeAssistantError(f"Error writing single Modbus register: {original_message}") from e
            return resp
        except (TypeError, AttributeError) as e:
            raise HomeAssistantError("Error writing single Modbus register: core modbus access failed") from e

    async def async_write_registers_single(self, unit, address, payload):  # Needs adapting for register queue
        """Write registers multi, but write only one register of type 16bit"""
        regs = convert_to_registers(int(payload), DataType.INT16, self.plugin.order32)
        kwargs = {ADDR_KW: unit} if unit is not None else {}
        async with self._lock:
            hub = await self._check_connection()
        try:
            if hub._config_delay:
                return None
            async with hub._lock:
                try:
                    resp = await self._client.write_registers(address=address, values=regs, **kwargs)
                except (ConnectionException, ModbusIOException) as e:
                    original_message = str(e)
                    raise HomeAssistantError(f"Error writing single Modbus registers: {original_message}") from e

            return resp
        except (TypeError, AttributeError) as e:
            raise HomeAssistantError(f"Error writing single Modbus registers: core modbus access failed") from e

    async def async_write_registers_multi(self, unit, address, payload):  # Needs adapting for register queue
        """Write registers multi.
        unit is the modbus address of the device that will be written to
        address us the start register address
        payload is a list of tuples containing
            - a select or number entity keys names or alternatively REGISTER_xx type declarations
            - the values are the values that will be encoded according to the spec of that entity
        The list of tuples will be converted to a modbus payload with the proper encoding and written
        to modbus device with address=unit
        All register descriptions referenced in the payload must be consecutive (without leaving holes)
        32bit integers will be converted to 2 modbus register values according to the endian strategy of the plugin
        """
        kwargs = {ADDR_KW: unit} if unit is not None else {}
        if isinstance(payload, list):
            regs_out = []
            for (
                key,
                value,
            ) in payload:
                if key.startswith("_"):
                    typ = key
                    value = int(value)
                else:
                    descr = self.writeLocals[key]
                    if hasattr(descr, "reverse_option_dict"):
                        value = descr.reverse_option_dict[value]  # string to int
                    elif callable(descr.scale):  # function to call ?
                        value = descr.scale(value, descr, self.data)
                    else:  # apply simple numeric scaling and rounding if not a list of words
                        try:
                            value = value * descr.scale
                        except:
                            _LOGGER.error(f"cannot treat payload scale {value} {descr}")
                    value = int(value)
                    typ = descr.unit

                if typ == REGISTER_U16:
                    regs_out += convert_to_registers(value, DataType.UINT16, self.plugin.order32)
                elif typ == REGISTER_S16:
                    regs_out += convert_to_registers(value, DataType.INT16, self.plugin.order32)
                elif typ == REGISTER_U32:
                    regs_out += convert_to_registers(value, DataType.UINT32, self.plugin.order32)
                elif typ == REGISTER_F32:
                    regs_out += convert_to_registers(value, DataType.FLOAT32, self.plugin.order32)
                elif typ == REGISTER_S32:
                    regs_out += convert_to_registers(value, DataType.INT32, self.plugin.order32)
                else:
                    _LOGGER.error(f"unsupported unit type: {typ} for {key}")
            # for easier debugging, make next line a _LOGGER.info line
            _LOGGER.debug(f"Ready to write multiple registers at 0x{address:02x}: {regs_out}")
            async with self._lock:
                hub = await self._check_connection()
            try:
                if hub._config_delay:
                    return None
                async with hub._lock:
                    try:
                        resp = await self._client.write_registers(address=address, values=regs_out, **kwargs)
                    except (ConnectionException, ModbusIOException) as e:
                        original_message = str(e)
                        raise HomeAssistantError(f"Error writing multiple Modbus registers: {original_message}") from e
                return resp
            except (TypeError, AttributeError) as e:
                raise HomeAssistantError(f"Error writing single Modbus registers: core modbus access failed") from e
        else:
            _LOGGER.error(f"write_registers_multi expects a list of tuples 0x{address:02x} payload: {payload}")
        return None
