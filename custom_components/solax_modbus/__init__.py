"""The SolaX Modbus Integration."""

import asyncio

# import importlib.util, sys
import importlib
import json
import logging
import struct
import time as _mtime
from dataclasses import dataclass, replace
from datetime import timedelta
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_STOP,
    PERCENTAGE,
    Platform,
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
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException, ModbusIOException
from pymodbus.framer import FramerType

from .connection import (
    describe_modbus_connection,
    format_config_entry_names,
    matching_config_entries,
    modbus_connection_identity,
)
from .const import (
    BUTTONREPEAT_FIRST as BUTTONREPEAT_FIRST,
)
from .const import (
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
    CONF_SERIAL_PORT,
    CONF_TCP_TYPE,
    CONF_TIME_OUT,
    DEFAULT_BAUDRATE,
    DEFAULT_INVERTER_POWER_KW,
    DEFAULT_MODBUS_ADDR,
    DEFAULT_PORT,
    DEFAULT_SERIAL_PORT,
    DEFAULT_TCP_TYPE,
    DEFAULT_TIME_OUT,
    DOMAIN,
    INVERTER_IDENT,
    # PLUGIN_PATH,
    REG_HOLDING,
    REG_INPUT,
    REGISTER_F32,
    REGISTER_INT_RANGES,
    REGISTER_S16,
    REGISTER_S32,
    REGISTER_STR,
    REGISTER_TYPE_WORDS,
    REGISTER_U8H,
    REGISTER_U8L,
    REGISTER_U16,
    REGISTER_U32,
    REGISTER_ULSB16MSB16,
    REGISTER_WORDS,
    SCAN_GROUP_AUTO,
    SCAN_GROUP_DEFAULT,
    SLEEPMODE_LASTAWAKE,
    WRITE_MULTI_MODBUS,
    WRITE_SINGLE_MODBUS,
    PollOutcome,
)
from .const import (
    CONF_READ_DCB as CONF_READ_DCB,
)
from .const import (
    CONF_READ_EPS as CONF_READ_EPS,
)
from .const import (
    DEFAULT_INTERFACE as DEFAULT_INTERFACE,
)
from .const import (
    DEFAULT_INVERTER_NAME_SUFFIX as DEFAULT_INVERTER_NAME_SUFFIX,
)
from .const import (
    DEFAULT_NAME as DEFAULT_NAME,
)
from .const import (
    DEFAULT_PLUGIN as DEFAULT_PLUGIN,
)
from .const import (
    DEFAULT_READ_DCB as DEFAULT_READ_DCB,
)
from .const import (
    DEFAULT_READ_EPS as DEFAULT_READ_EPS,
)
from .const import (
    DEFAULT_SCAN_INTERVAL as DEFAULT_SCAN_INTERVAL,
)
from .const import (
    SCAN_GROUP_MEDIUM as SCAN_GROUP_MEDIUM,
)
from .const import (
    WRITE_MULTISINGLE_MODBUS as WRITE_MULTISINGLE_MODBUS,
)
from .modbus_transport import CoreModbusTransport, ModbusTransport, NativeModbusTransport, UnavailableModbusTransport
from .pymodbus_compat import DataType, convert_from_registers, convert_to_registers, pymodbus_version_info
from .sensor import SolaXModbusSensor
from .serial_modbus import AsyncSerialModbusClient, SerialModbusError

RETRIES = 1  # was 6 then 0, which worked also, but 1 is probably the safe choice
INVALID_START = 99999
VERBOSE_CYCLES = 20
COMM_HISTORY_LIMIT = 100
COMM_BLOCK_FAILURE_THRESHOLD = 3
COMM_BLOCK_FAILURE_WINDOW = 600
COMM_RECOVERY_INTERVAL = 300
INFLIGHT_CANCEL_TIMEOUT = 2.0


_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH, Platform.TIME]

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


def empty_hub_interval_group_lambda() -> SimpleNamespace:
    return SimpleNamespace(
        interval=0,
        unsub_interval_method=None,
        device_groups={},
        poll_lock=asyncio.Lock(),
        pending_rerun=False,
    )


def empty_hub_device_group_lambda() -> SimpleNamespace:
    return SimpleNamespace(
        sensors=[],
        inputBlocks={},
        holdingBlocks={},
        readPreparation=None,  # function to call before read group
        readFollowUp=None,  # function to call after read group
        publish_updates=False,
    )


def should_register_be_loaded(hass: HomeAssistant, hub: Any, descriptor: Any) -> bool:
    """
    Check if an entity is enabled in the entity registry, checking across multiple platforms.
    """
    if getattr(descriptor, "internal", False):
        _LOGGER.debug(f"{hub.name}: should be loaded: entity with key {descriptor.key} is internal, returning True.")
        return True
    unique_id = f"{hub._name}_{descriptor.key}"
    unique_id_alt = f"{hub._name}.{descriptor.key}"  # dont knnow why
    platforms = (Platform.SENSOR, Platform.SELECT, Platform.NUMBER, Platform.SWITCH, Platform.BUTTON, Platform.TIME)
    registry = er.async_get(hass)
    entity_found = False
    # First, check if there is an existing enabled entity in the registry for this unique_id.
    for platform in platforms:
        entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
        if entity_id:
            _LOGGER.debug(f"{hub.name}: should be loaded: entity_id for {unique_id} on platform {platform} is now {entity_id}")
        else:
            entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id_alt)
            _LOGGER.debug(f"{hub.name}: should be loaded: entity_id for alt {unique_id_alt} on platform {platform} is now {entity_id}")
        if entity_id:
            entity_found = True
            entity_entry = registry.async_get(entity_id)
            if entity_entry and not entity_entry.disabled:
                _LOGGER.debug(f"{hub.name}: should be loaded: Entity {entity_id} is enabled, returning True.")
                return True  # Found an enabled entity, no need to check further
    # If we get here, no enabled entity was found across all platforms.
    if entity_found:
        # At least one entity exists for this unique_id, but all are disabled. Respect the user's choice.
        _LOGGER.debug(f"{hub.name}: should be loaded: entity with unique_id {unique_id} was found but is disabled across all relevant platforms.")
        return False
    else:
        # No entity exists for this unique_id on any platform. Treat it as a new entity.
        _LOGGER.debug(f"{hub.name}: should be loaded: entity with unique_id {unique_id} not found in entity registry, checking defaults ")
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
        d = hub.timeEntities.get(descriptor.key)
        if d and d.entity_registry_enabled_default:
            return True
        _LOGGER.debug(
            f"{hub.name}: should be loaded: entity_default with unique_id {unique_id} was found but is disabled across all relevant platforms."
        )
        return False


async def config_entry_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener, called when the config entry options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
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

    async def _stop_hubs_on_homeassistant_stop(event: Any) -> None:
        """Stop active hubs before HA reaches final task cancellation."""
        domain_data = hass.data.get(DOMAIN, {})
        for name, rec in list(domain_data.items()):
            if not isinstance(rec, dict):
                continue
            hub = rec.get("hub")
            if hub:
                _LOGGER.debug(f"{name}: Home Assistant stop event - stopping hub")
                try:
                    await hub.async_stop()
                except Exception as ex:
                    _LOGGER.warning(f"{name}: error during Home Assistant stop: {ex}")

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop_hubs_on_homeassistant_stop)

    # Register helper services to force-stop hubs
    async def _svc_stop_all(call: Any) -> None:
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

    async def _svc_stop_hub(call: Any) -> None:
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
async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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
    if plugin_name.startswith("custom_components") or plugin_name.startswith("/config") or plugin_name.startswith("plugin_"):
        new = {**config}
        plugin_name = plugin_name.split("plugin_", 1)[1][:-3]
        _LOGGER.warning(f"converting old style plugin name {config[CONF_PLUGIN]} to new style short name {plugin_name}")
        new[CONF_PLUGIN] = plugin_name
        hass.config_entries.async_update_entry(entry, options=new)
    # end of conversion

    # ================== dynamically load desired plugin =======================================================

    plugin = await hass.async_add_executor_job(_load_plugin, plugin_name)

    # ====================== end of dynamic load ==============================================================

    hub: SolaXModbusHub
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
        from .energy_dashboard import (
            get_energy_dashboard_coordinator,
            register_energy_dashboard_switch_provider,
        )

        register_energy_dashboard_switch_provider(hass)
        get_energy_dashboard_coordinator(hass).register_hub(entry.entry_id, hub)
    except Exception as ex:
        _LOGGER.debug(f"{hub.name}: Energy Dashboard coordinator registration failed: {ex}")
    """Register the hub."""
    hass.data[DOMAIN][hub._name] = {
        "hub": hub,
    }

    await hub.async_init()

    entry.async_on_unload(entry.add_update_listener(config_entry_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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

    try:
        from .energy_dashboard import get_energy_dashboard_coordinator

        get_energy_dashboard_coordinator(hass).unregister_hub(entry.entry_id)
    except Exception as ex:
        _LOGGER.debug(f"{name}: Energy Dashboard coordinator cleanup failed: {ex}")

    return unload_ok


def defaultIsAwake(datadict: dict[str, Any]) -> bool:
    return True


def Gen4Timestring(numb: int) -> str:
    h = numb % 256
    m = numb >> 8
    return f"{h:02d}:{m:02d}"


@dataclass
class block:
    start: int | None = None  # start address of the block
    end: int | None = None  # end address of the block
    # order16: int = None # byte endian for 16bit registers
    # order32: int = None # word endian for 32bit registers
    descriptions: Any = None
    regs: Any = None  # sorted list of registers used in this block


@dataclass(frozen=True)
class PendingWrite:
    """A single-register write that must be retried when the inverter wakes."""

    unit: int
    address: int
    payload: int
    register_data_type: str | None = None


@dataclass(frozen=True)
class BlockReadResult:
    """Result of reading and decoding one Modbus block."""

    data_succeeded: bool
    communication_succeeded: bool
    tolerated: bool = False
    fresh_keys: frozenset[str] = frozenset()


class RegisterEncodingError(HomeAssistantError):
    """Raised when a value cannot be represented by its Modbus register type."""


class SolaXModbusHub:
    """Thread safe wrapper class for pymodbus."""

    def __init__(
        self,
        hass: HomeAssistant,
        plugin: ModuleType,
        entry: ConfigEntry,
    ) -> None:
        config = entry.options
        name = config[CONF_NAME]
        host = config.get(CONF_HOST, None)
        port = config.get(CONF_PORT, DEFAULT_PORT)
        tcp_type = config.get(CONF_TCP_TYPE, DEFAULT_TCP_TYPE)
        modbus_addr = config.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
        if modbus_addr is None:
            modbus_addr = DEFAULT_MODBUS_ADDR
            _LOGGER.warning(f"{name} integration may need to be reconfigured for this version; using default Solax modbus_address {modbus_addr}")
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
        self._transport: ModbusTransport
        if interface == "serial":
            self._transport = NativeModbusTransport(
                AsyncSerialModbusClient(
                    port=serial_port,
                    baudrate=baudrate,
                    parity="N",
                    stopbits=1,
                    bytesize=8,
                    timeout=time_out,
                    retries=RETRIES,
                )
            )
        elif interface == "tcp":
            if tcp_type == "rtu":
                client = AsyncModbusTcpClient(host=host, port=port, timeout=time_out, framer=FramerType.RTU, retries=RETRIES)
            elif tcp_type == "ascii":
                client = AsyncModbusTcpClient(host=host, port=port, timeout=time_out, framer=FramerType.ASCII, retries=RETRIES)
            else:
                client = AsyncModbusTcpClient(host=host, port=port, timeout=time_out, retries=RETRIES)
            self._transport = NativeModbusTransport(client)
        elif interface == "core":
            self._transport = CoreModbusTransport(
                hass,
                config.get(CONF_CORE_HUB, ""),
                name,
            )
        else:
            self._transport = UnavailableModbusTransport(interface)
        self._lock = asyncio.Lock()
        self._poll_data_lock = asyncio.Lock()
        self._name: str = name
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
        self.groups: dict[Any, Any] = {}  # group info, below
        self.data: dict[str, Any] = {"_repeatUntil": {}}  # _repeatuntil contains button autorepeat expiry times
        self.tmpdata: dict[Any, Any] = {}  # for WRITE_DATA_LOCAL entities with corresponding prevent_update number/sensor
        self.tmpdata_expiry: dict[Any, Any] = {}  # expiry timestamps for tempdata
        self.cyclecount: int = 0  # temporary - remove later
        self.slowdown: int = 1  # slow down factor when modbus is not responding: 1 : no slowdown, 10: ignore 9 out of 10 cycles
        self.computedSensors: dict[Any, Any] = {}
        self.computedEntities: dict[Any, Any] = {}  # buttons and selects with value_function for autorepeat
        self.computedSwitches: dict[Any, Any] = {}
        self.sensorDescriptions: dict[Any, Any] = {}  # all sensor descriptions, indexed by key
        self.sensorEntities: dict[Any, Any] = {}  # all sensor entities, indexed by key
        self.numberEntities: dict[Any, Any] = {}  # all number entities, indexed by key
        self.selectEntities: dict[Any, Any] = {}
        self.switchEntities: dict[Any, Any] = {}
        self.timeEntities: dict[Any, Any] = {}
        self.entity_dependencies: dict[str, list[str]] = {}  # Maps a sensor key to a list of data control keys that use the sensor as data source
        # self.preventSensors = {} # sensors with prevent_update = True
        self.writeLocals: dict[Any, Any] = {}  # key to description lookup dict for write_method = WRITE_DATA_LOCAL entities
        self.sleepzero: list[str] = []  # sensors that will be set to zero in sleepmode
        self.sleepnone: list[str] = []  # sensors that will be cleared in sleepmode
        self.writequeue: dict[tuple[int, int], PendingWrite] = {}  # requests to retry when the inverter wakes
        _LOGGER.debug(f"{self.name}: ready to call plugin to determine inverter type")
        self.plugin = plugin.plugin_instance.create_hub_instance()
        self.plugin_module = plugin  # Store plugin module for accessing module-level functions
        self._validate_register_func = getattr(plugin, "validate_register_data", None)  # Cache function reference
        self.wakeupButton: Any = None
        self._invertertype: int | None = None
        self.modbus_protocol_version: int | None = None
        self.localsUpdated: bool = False
        self.localsLoaded: bool = False
        self.config: Any = config  # MappingProxyType from entry.options
        self.entry: ConfigEntry = entry
        self.device_info: DeviceInfo | None = None
        self.inverter_model: str | None = None
        self._has_local_inverter_model: bool = False
        self.blocks_changed: bool = False
        self.initial_groups: dict[Any, Any] = {}  # as returned by the sensor setup - holdingRegs and inputRegs should not change

        # Track in-flight I/O tasks for fast cancellation on stop
        self._inflight_tasks: set[Any] = set()

        # Runtime bad register handling. bad_regs are temporarily quarantined
        # entity base-addresses that are excluded from normal polling.
        self.bad_regs: dict[str, set[int]] = {"holding": set(), "input": set()}
        self.bisect_max_depth = 10  # safety cap to avoid pathological recursion
        self._runtime_bisect_tasks: dict[str, asyncio.Task[Any]] = {}
        self._quarantine_recheck_task: asyncio.Task[Any] | None = None
        self._comm_block_failures: dict[str, list[float]] = {}
        self._comm_last_block_success_time: float | None = None
        self._comm_last_block_failure_time: float | None = None
        self._comm_recent_outcomes: list[PollOutcome] = []
        self._comm_poll_durations: list[int] = []
        self._comm_last_error: str | None = None
        self._comm_last_error_time: str | None = None
        self._comm_last_quarantined_register: str | None = None
        self._comm_last_recovered_register: str | None = None
        self._comm_overrun_count = 0
        self._comm_recovery_active = False

        # Polling is no longer blocked by a startup bisect. Bad registers are
        # found at runtime and rechecked periodically.
        self._probe_ready = asyncio.Event()
        self._probe_ready.set()
        self._initial_refresh_task: Any = None
        self._initial_refresh_active: bool = False
        self._initial_refresh_done: bool = False

        # Deferred setup state
        self._platforms_forwarded = False
        self._deferred_setup_task: Any = None

        # _LOGGER.debug("solax modbushub done %s", self.__dict__)

    def _start_initial_refresh_if_needed(self) -> None:
        """Start the one-shot initial refresh after platforms are available."""
        if self._initial_refresh_done or self._initial_refresh_task is not None:
            return
        if getattr(self, "_stopping", False):
            return
        if not self._platforms_forwarded:
            return
        self._initial_refresh_task = self._hass.loop.create_task(self._run_initial_refresh_when_ready())

    async def async_init(self, *args: Any) -> None:  # noqa: D102
        import asyncio
        import time as _t

        self._init_task: Any = asyncio.current_task()
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
            _LOGGER.debug(f"{self._name}: no inverter detected during initial window – deferring setup until device is online")
            if not getattr(self, "_stopping", False):
                self._deferred_setup_task = self._hass.loop.create_task(self._deferred_setup_loop())
            return

        # Prepare device_info (inverter detected during initial window)
        # Device name = hub name + optional suffix (e.g. "EV" + "Charger" -> "EV Charger").
        # Unique per config entry; entity names never repeat it, HA composes the friendly name.
        device_name = self._name
        if self.inverterNameSuffix is not None and self.inverterNameSuffix != "":
            device_name = device_name + " " + self.inverterNameSuffix
        self.device_info = DeviceInfo(
            identifiers=cast(set[tuple[str, str]], {(DOMAIN, self._name, INVERTER_IDENT)}),
            manufacturer=self.plugin.plugin_manufacturer,
            model=self._get_inverter_model(),
            name=device_name,
            serial_number=self.seriesnumber,
            sw_version=self.plugin.getSoftwareVersion(self.data),
            hw_version=self.plugin.getHardwareVersion(self.data),
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
                self._start_initial_refresh_if_needed()
            except ValueError as ex:
                # If platforms are already set up, log warning but continue
                # This shouldn't happen if unload worked properly, but handle gracefully
                _LOGGER.warning(f"{self._name}: platforms already forwarded - reload may not work correctly: {ex}")
                self._platforms_forwarded = True
                self._start_initial_refresh_if_needed()
        else:
            _LOGGER.debug(f"{self._name}: platforms already forwarded on this hub instance, skipping")
            self._start_initial_refresh_if_needed()

        self._init_task = None

    def _get_inverter_model(self) -> str | None:
        if self._has_local_inverter_model:
            return self.inverter_model
        return getattr(self.plugin, "inverter_model", None)

    async def _deferred_setup_loop(self, interval: int = 30) -> None:
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
                    _LOGGER.debug(f"{self._name}: inverter detected during deferred setup (type={inv}) – forwarding platforms")
                    # Prepare/refresh device_info in case it wasn't set
                    device_name = self._name
                    if self.inverterNameSuffix:
                        device_name = device_name + " " + self.inverterNameSuffix
                    self.device_info = DeviceInfo(
                        identifiers=cast(set[tuple[str, str]], {(DOMAIN, self._name, INVERTER_IDENT)}),
                        manufacturer=self.plugin.plugin_manufacturer,
                        model=self._get_inverter_model(),
                        name=device_name,
                        serial_number=self.seriesnumber,
                        sw_version=self.plugin.getSoftwareVersion(self.data),
                        hw_version=self.plugin.getHardwareVersion(self.data),
                    )
                    if getattr(self, "_stopping", False):
                        return
                    await self._hass.config_entries.async_forward_entry_setups(self.entry, PLATFORMS)
                    self._platforms_forwarded = True
                    self._start_initial_refresh_if_needed()
                    return
                else:
                    _LOGGER.debug(f"{self._name}: deferred setup – inverter still not responding, will retry in {interval}s")
            except Exception as ex:
                _LOGGER.debug(f"{self._name}: deferred setup iteration failed: {ex}")
            # Wait and try again
            for _ in range(interval * 10):  # sleep in 0.1s steps to remain abortable
                if getattr(self, "_stopping", False):
                    return
                await asyncio.sleep(0.1)

    # save and load local data entity values to make them persistent
    DATAFORMAT_VERSION = 1

    def saveLocalData(self) -> None:
        tosave: dict[str, Any] = {"_version": self.DATAFORMAT_VERSION}
        for desc in self.writeLocals:
            tosave[desc] = self.data.get(desc)

        with open(self._hass.config.path(f"{self.name}_data.json"), "w") as fp:
            json.dump(tosave, fp)
        self.localsUpdated = False
        _LOGGER.debug(f"saved modified persistent date: {tosave}")

    def loadLocalData(self) -> None:
        try:
            fp = open(self._hass.config.path(f"{self.name}_data.json"))
        except Exception:
            if self.cyclecount > 5:
                _LOGGER.debug("no local data file found after 5 tries - is this a first time run? or didn't you modify any DATA_LOCAL entity?")
                self.localsLoaded = True  # retry a couple of polling cycles - then assume non-existent"
            return
        try:
            loaded = json.load(fp)
        except Exception:
            _LOGGER.debug("Local data file not readable. Resetting to empty")
            fp.close()
            self.saveLocalData()
            return
        else:
            if loaded.get("_version") == self.DATAFORMAT_VERSION:
                for desc in self.writeLocals:
                    val = loaded.get(desc)
                    if val is not None:
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
                    {"entry_id": self.entry.entry_id, "hub_name": self._name},
                )
            except Exception as ex:
                _LOGGER.debug(f"{self._name}: failed to fire local data event: {ex}")

    # end of save and load section

    def scan_group(self, sensor: Any) -> int:  # seems to be called for non-sensor entities also - strange
        # scan group
        g = getattr(sensor.entity_description, "scan_group", None)
        if not g:
            regtype = getattr(sensor.entity_description, "register_type", None)
            if regtype == REG_HOLDING:
                g = self.plugin.default_holding_scangroup
            elif regtype == REG_INPUT:
                g = self.plugin.default_input_scangroup
            else:
                _LOGGER.debug(f"{self._name}: default scan_group for {sensor.entity_description.key} returned {g} - {SCAN_GROUP_DEFAULT}")
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
        return int(g)

    def _warn_duplicate_inverter_configuration(self, interval: int) -> None:
        """Warn from one active duplicate configuration on every slow poll."""
        slow_interval = int(self.config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        if interval != slow_interval:
            return

        entries = matching_config_entries(self._hass, self.config, active_only=True)
        if len(entries) < 2:
            return

        warning_owner = min(entries, key=lambda entry: str(entry.entry_id))
        if warning_owner.entry_id != self.entry.entry_id:
            return

        identity = modbus_connection_identity(self.config)
        if identity is None:
            return
        _LOGGER.warning(
            "Duplicate inverter configuration detected: %s are enabled and poll the same Modbus device (%s).",
            format_config_entry_names(entries),
            describe_modbus_connection(identity),
        )

    def device_group_key(self, device_info: DeviceInfo) -> str:
        """Extract device group key from device_info identifiers.

        CRITICAL: This is called during sensor setup for every entity.
        The device_info parameter should NEVER be None.
        """
        key = ""

        # DEFENSIVE: Check if device_info is None (should never happen)
        if device_info is None:
            _LOGGER.error(f"{self._name}: device_group_key called with None device_info! This is a BUG - device_info should never be None here.")  # type: ignore[unreachable]
            return ""

        # DEFENSIVE: Check if it's a dict-like object
        if not isinstance(device_info, dict):
            _LOGGER.error(f"{self._name}: device_group_key called with non-dict device_info! type={type(device_info)}, value={device_info}")  # type: ignore[unreachable]
            return ""

        # DEFENSIVE: Check if "identifiers" key exists
        if "identifiers" not in device_info:
            _LOGGER.error(
                f"{self._name}: device_group_key called with device_info missing 'identifiers' key! "
                f"keys={list(device_info.keys())}, device_info={device_info}"
            )
            return ""

        identifiers = device_info["identifiers"]

        # DEFENSIVE: Check if identifiers is None
        if identifiers is None:
            _LOGGER.error(f"{self._name}: device_group_key got None for device_info['identifiers']! device_info={device_info}")  # type: ignore[unreachable]
            return ""

        # DEFENSIVE: Check if identifiers is iterable
        try:
            iter(identifiers)
        except TypeError:
            _LOGGER.error(f"{self._name}: device_group_key got non-iterable identifiers! type={type(identifiers)}, value={identifiers}")
            return ""

        for identifier in identifiers:
            identifier_tuple = cast(tuple[str, ...], identifier)
            if identifier_tuple[0] != DOMAIN:
                continue
            key = identifier_tuple[1] + "_" + identifier_tuple[2]

        return key

    # following function is the added_to_hass callback for sensors, numbers and selects
    @callback
    async def async_add_solax_modbus_sensor(self, sensor: SolaXModbusSensor) -> None:
        """Listen for data updates."""
        # attention, this function is not only called for sensors also for number, select
        # This is the first sensor, set up interval.
        interval = self.scan_group(sensor)
        interval_group = self.groups.setdefault(interval, empty_hub_interval_group_lambda())
        if not interval_group.device_groups:
            interval_group.interval = interval

            async def _refresh(_now: Any = None) -> None:
                secs = interval_group.interval
                self._warn_duplicate_inverter_configuration(secs)
                self.cyclecount += 1
                cycle_id = self.cyclecount
                _LOGGER.debug(f"{self._name}: [{secs}s] poll started – cycle #{cycle_id}")
                # If a previous cycle is still running, mark a catch-up and return quickly.
                if interval_group.poll_lock.locked():
                    interval_group.pending_rerun = True
                    _LOGGER.debug(f"{self._name}: [{secs}s] overrun – previous poll still running; scheduling immediate catch-up after it finishes")
                    return

                # Run cycles back-to-back if a tick was missed while running (catch-up mode)
                while True:
                    start = _mtime.monotonic()
                    async with interval_group.poll_lock:
                        outcome, updated_sensors = await self.async_refresh_modbus_data(interval_group, _now, cycle_id=cycle_id)
                    elapsed = _mtime.monotonic() - start
                    _LOGGER.debug(
                        f"{self._name}: [{secs}s] poll finished – cycle #{cycle_id}, "
                        f"duration={int(elapsed * 1000)} ms, outcome={outcome.value}, "
                        f"sensors={updated_sensors}, slowdown={self.slowdown}"
                    )
                    self._record_poll_cycle(outcome, elapsed, interval_group.interval or secs)

                    # If the configured interval is shorter than the actual run time, inform once per cycle
                    if elapsed >= (interval_group.interval or 0):
                        _LOGGER.debug(
                            f"{self._name}: [{secs}s] interval too short – cycle took {elapsed:.3f}s ≥ interval {interval_group.interval}s; running at max possible speed"
                        )

                    # Immediate catch-up if a tick arrived during our run.
                    # Only perform catch-up when the previous poll succeeded and did not consume
                    # the complete interval; otherwise this creates an endless backlog.
                    if getattr(interval_group, "pending_rerun", False):
                        interval_group.pending_rerun = False
                        if outcome.communication_succeeded and elapsed < (interval_group.interval or 0):
                            # Loop again immediately (no sleep) to catch up once
                            continue
                        if outcome.communication_succeeded:
                            _LOGGER.debug(f"{self._name}: dropping pending catch-up because the previous poll already consumed the interval")
                        elif outcome is PollOutcome.SKIPPED:
                            _LOGGER.debug(f"{self._name}: dropping pending catch-up because polling was skipped")
                        else:
                            _LOGGER.debug(f"{self._name}: dropping pending catch-up due to failed poll (slowdown={self.slowdown})")
                        # Exit the loop; next attempt will occur per normal schedule/slowdown policy
                        break
                    break

            _LOGGER.debug(f"{self._name}: starting timer loop for interval group: {interval}")
            interval_group.unsub_interval_method = async_track_time_interval(self._hass, _refresh, timedelta(seconds=interval))

        # Defensive check: Skip sensors with no device_info (shouldn't happen normally)
        if sensor.device_info is None:
            _LOGGER.error(
                f"{self._name}: Sensor {sensor.entity_description.key} has no device_info - skipping registration. "
                f"This may indicate a bug in sensor creation. "
                f"_attr_device_info={getattr(sensor, '_attr_device_info', 'NO_ATTR')}"
            )
            return

        device_key = self.device_group_key(sensor.device_info)
        grp = interval_group.device_groups.setdefault(device_key, empty_hub_device_group_lambda())
        _LOGGER.debug(f"{self._name}: adding sensor {sensor.entity_description.key} available: {sensor._attr_available} ")
        grp.sensors.append(sensor)
        self.blocks_changed = True  # will force rebuild_blocks to be called

    @callback
    async def async_remove_solax_modbus_sensor(self, sensor: Any) -> None:
        """Remove data update."""
        interval = self.scan_group(sensor)
        interval_group = self.groups.get(interval, None)
        if interval_group is None:
            return

        # Defensive check: Skip sensors with no device_info
        if sensor.device_info is None:
            _LOGGER.warning(f"{self._name}: Cannot remove sensor {sensor.entity_description.key} - no device_info")
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

    async def async_refresh_modbus_data(self, interval_group: Any, _now: int | None = None, cycle_id: int | None = None) -> tuple[PollOutcome, int]:
        """Time to update."""
        _LOGGER.debug(f"{self._name}: scan_group timer initiated refresh_modbus_data call - interval {interval_group.interval}")
        # self.cyclecount = self.cyclecount + 1  # Now incremented in _refresh
        # Do not start normal polling until initial probe is done
        if not self._probe_ready.is_set():
            _LOGGER.debug(f"{self._name}: skipping poll – initial probe not done yet")
            return PollOutcome.SKIPPED, 0
        if self._initial_refresh_active:
            _LOGGER.debug(f"{self._name}: skipping scheduled poll – initial refresh still running")
            return PollOutcome.SKIPPED, 0
        outcome, updated_sensors = await self._refresh_interval_group_once(interval_group)
        await self._maybe_refresh_energy_dashboard_on_primary_update()
        # Return aggregate result and updated sensor count to caller for logging
        return outcome, updated_sensors

    async def _refresh_interval_group_once(self, interval_group: Any, bypass_slowdown: bool = False) -> tuple[PollOutcome, int]:
        """Refresh one interval group once."""
        if not interval_group.device_groups:
            return PollOutcome.SKIPPED, 0
        if self.blocks_changed:
            self.rebuild_blocks(self.initial_groups)
        if not bypass_slowdown and (self.cyclecount % self.slowdown) != 0:
            return PollOutcome.SKIPPED, 0

        outcomes: list[PollOutcome] = []
        updated_sensors = 0
        for group in list(interval_group.device_groups.values()):
            group_outcome = await self.async_read_modbus_data(group)
            outcomes.append(group_outcome)
            if group_outcome.communication_succeeded and getattr(group, "publish_updates", True):
                for sensor in group.sensors:
                    sensor.modbus_data_updated()
                updated_sensors += len(group.sensors)
            _LOGGER.debug(f"{self._name}: device group read done with outcome={group_outcome.value}")

        if PollOutcome.FAILED in outcomes:
            outcome = PollOutcome.FAILED
        elif PollOutcome.PARTIAL in outcomes:
            outcome = PollOutcome.PARTIAL
        elif PollOutcome.SUCCESS in outcomes:
            outcome = PollOutcome.SUCCESS
        elif PollOutcome.DISCARDED in outcomes:
            outcome = PollOutcome.DISCARDED
        else:
            outcome = PollOutcome.SKIPPED

        if outcome is PollOutcome.FAILED:
            if self.slowdown <= 1:
                _LOGGER.debug(f"{self._name}: modbus group read failed - assuming sleep mode - slowing down by factor 10")
            self.slowdown = 10
            for key in self.sleepnone:
                self.data.pop(key, None)
            for key in self.sleepzero:
                self.data[key] = 0
        elif outcome.communication_succeeded:
            if self.slowdown > 1:
                _LOGGER.debug(f"{self._name}: communication restored, resuming normal speed after slowdown")
            self.slowdown = 1

        return outcome, updated_sensors

    async def _run_initial_refresh_when_ready(self) -> None:
        """Do a one-time initial refresh of all scan groups after startup probe has completed."""
        await self._probe_ready.wait()
        if getattr(self, "_stopping", False) or self._initial_refresh_done or not self.groups:
            return
        # Let entity setup settle, then populate values once from slow to fast groups.
        await asyncio.sleep(0.2)
        self._initial_refresh_active = True
        try:
            for interval in sorted(self.groups.keys(), reverse=True):
                interval_group = self.groups.get(interval)
                if interval_group is None or not interval_group.device_groups:
                    continue
                _LOGGER.debug(f"{self._name}: initial refresh for interval {interval}s")
                async with interval_group.poll_lock:
                    outcome, updated_sensors = await self._refresh_interval_group_once(interval_group, bypass_slowdown=True)
                await self._maybe_refresh_energy_dashboard_on_primary_update()
                _LOGGER.debug(f"{self._name}: initial refresh for interval {interval}s finished (outcome={outcome.value}, sensors={updated_sensors})")
        finally:
            self._initial_refresh_active = False
            self._initial_refresh_done = True

    async def _maybe_refresh_energy_dashboard_on_primary_update(self) -> None:
        if not self._hass:
            return
        try:
            from .energy_dashboard import get_energy_dashboard_coordinator

            get_energy_dashboard_coordinator(self._hass).hub_data_updated(self.entry.entry_id)
        except Exception as ex:
            _LOGGER.debug(f"{self._name}: Energy Dashboard topology update failed: {ex}")

    @property
    def invertertype(self) -> int | None:
        return self._invertertype

    @invertertype.setter
    def invertertype(self, newtype: int) -> None:
        self._invertertype = newtype

    @property
    def seriesnumber(self) -> str:
        return self._seriesnumber

    @seriesnumber.setter
    def seriesnumber(self, nr: str) -> None:
        self._seriesnumber = nr

    @property
    def name(self) -> str:
        """Return the name of this hub."""
        return self._name

    async def async_close(self) -> None:
        """Disconnect client."""
        await self._transport.close()

    async def async_stop(self) -> None:
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
        for tname in ("_initial_refresh_task", "_quarantine_recheck_task"):
            task = getattr(self, tname, None)
            if task and not task.done():
                try:
                    task.cancel()
                except Exception:
                    pass
        for task in list(getattr(self, "_runtime_bisect_tasks", {}).values()):
            if task and not task.done():
                try:
                    task.cancel()
                except Exception:
                    pass
        self._runtime_bisect_tasks.clear()
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
        # 2d) cancel in-flight I/O tasks immediately and collect their
        # cancellation results so pymodbus shutdown exceptions do not leak.
        inflight_tasks = list(self._inflight_tasks)
        for task in inflight_tasks:
            try:
                task.cancel()
            except Exception:
                pass
        if inflight_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*inflight_tasks, return_exceptions=True), timeout=INFLIGHT_CANCEL_TIMEOUT)
            except TimeoutError:
                _LOGGER.debug(f"{self._name}: timed out waiting for in-flight Modbus tasks to cancel during shutdown")
        self._inflight_tasks.clear()
        # 3) freeze probe event
        try:
            self._probe_ready.set()
        except Exception:
            pass
        # 4) close transport
        try:
            await self.async_close()
        except Exception:
            pass

    def _track_task(self, coro: Any) -> asyncio.Task[Any]:
        """Wrap coroutines in a Task we can cancel during stop."""
        task = asyncio.create_task(coro)
        self._inflight_tasks.add(task)
        task.add_done_callback(self._handle_tracked_task_done)
        return task

    def _handle_tracked_task_done(self, task: asyncio.Task[Any]) -> None:
        """Collect finished in-flight task results during shutdown."""
        self._inflight_tasks.discard(task)
        if not getattr(self, "_stopping", False):
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        except Exception as ex:
            _LOGGER.debug(f"{self._name}: failed to collect in-flight Modbus task result during shutdown: {ex}")
            return
        if exc is None:
            return
        if self._is_expected_shutdown_modbus_error(exc):
            _LOGGER.debug(f"{self._name}: collected expected Modbus task cancellation during shutdown: {exc}")
            return
        _LOGGER.debug(f"{self._name}: in-flight Modbus task ended during shutdown: {exc}")

    def _is_expected_shutdown_modbus_error(self, ex: BaseException) -> bool:
        """Return True for pymodbus cancellation errors caused by HA shutdown."""
        if not getattr(self, "_stopping", False):
            return False
        return isinstance(ex, ModbusIOException) and "Request cancelled outside pymodbus" in str(ex)

    async def _check_connection(self) -> bool:
        if getattr(self, "_stopping", False):
            return False
        if not self._transport.is_connected():
            _LOGGER.debug(f"{self._name}: Inverter is not connected, trying to connect")
            await self.async_connect()
        return self._transport.is_connected()

    async def is_online(self) -> bool:
        return self._transport.is_connected() and (self.slowdown == 1)

    async def async_connect(self) -> bool:
        if getattr(self, "_stopping", False):
            return False
        if self._transport.is_connected():
            _LOGGER.debug(f"{self._name}: async_connect skipped - already connected")
            return True
        _LOGGER.debug(f"{self._name}: trying to connect to inverter through {self._transport.endpoint}")
        return await self._transport.connect()

    async def _handle_transport_exception(self, exception_error: BaseException, operation: str) -> None:
        """Reset only connections that are known to be unusable."""
        if getattr(self, "_stopping", False):
            return

        connection_lost = isinstance(exception_error, ConnectionException) or not self._transport.is_connected()
        if connection_lost:
            _LOGGER.debug(f"{self._name}: {operation} lost the connection; resetting transport before the next request")
            await self._transport.close()
            return

        _LOGGER.debug(
            f"{self._name}: {operation} failed while the transport remains connected; leaving retry and reconnect handling to the transport"
        )

    async def async_read_holding_registers(self, unit: int, address: int, count: int) -> Any:
        """Read holding registers."""
        return await self._async_read_registers("holding", unit, address, count)

    async def async_read_input_registers(self, unit: int, address: int, count: int) -> Any:
        """Read input registers."""
        return await self._async_read_registers("input", unit, address, count)

    async def _async_read_registers(self, register_type: str, unit: int, address: int, count: int) -> Any:
        """Read registers through the configured transport."""
        async with self._lock:
            if getattr(self, "_stopping", False):
                return None
            if not await self._check_connection():
                return None
            try:
                _LOGGER.debug(f"{self._name}: READ {register_type.upper()} device={unit} addr=0x{address:x} cnt={count}")
                response = await self._track_task(self._transport.read(register_type, unit, address, count))
            except (ModbusException, SerialModbusError, AttributeError, TypeError) as exception_error:
                error = f"Error: device: {unit} address: 0x{address:x} -> {exception_error!s}"
                if self._is_expected_shutdown_modbus_error(exception_error):
                    _LOGGER.debug(f"{self._name}: ignoring Modbus read cancellation during shutdown: {error}")
                    return None
                _LOGGER.error(error)
                if getattr(self, "_stopping", False):
                    _LOGGER.debug(f"{self._name}: ModbusException during shutdown - skipping reconnect")
                    return None
                await self._handle_transport_exception(exception_error, f"{register_type} read")
                return None
        return response

    def _validate_write_response(self, response: Any, *, unit: int, address: int, operation: str) -> Any:
        """Raise when pymodbus did not confirm a write operation."""
        if response is None:
            raise HomeAssistantError(f"{self._name}: {operation} returned no response for device {unit} at register 0x{address:x}")
        try:
            is_error = bool(response.isError())
        except (AttributeError, TypeError) as ex:
            raise HomeAssistantError(
                f"{self._name}: {operation} returned an invalid response for device {unit} at register 0x{address:x}: {response}"
            ) from ex
        if is_error:
            raise HomeAssistantError(f"{self._name}: {operation} was rejected by device {unit} at register 0x{address:x}: {response}")
        return response

    def _encode_write_value(
        self,
        payload: int | float,
        register_data_type: str | None,
        *,
        single_register: bool,
    ) -> list[int]:
        """Validate and encode one value before it reaches the transport."""
        effective_type = register_data_type or (REGISTER_S16 if single_register else None)
        if effective_type is None:
            raise RegisterEncodingError(f"{self._name}: unsupported register data type {register_data_type}")
        data_type_enum = cast(Any, DataType)
        data_types: dict[str, Any] = {
            REGISTER_U16: data_type_enum.UINT16,
            REGISTER_S16: data_type_enum.INT16,
            REGISTER_U32: data_type_enum.UINT32,
            REGISTER_F32: data_type_enum.FLOAT32,
            REGISTER_S32: data_type_enum.INT32,
        }
        data_type = data_types.get(effective_type)
        word_count = REGISTER_TYPE_WORDS.get(effective_type)
        if data_type is None or word_count is None:
            raise RegisterEncodingError(f"{self._name}: unsupported register data type {register_data_type}")
        if single_register and word_count != 1:
            raise RegisterEncodingError(
                f"{self._name}: register data type {effective_type} requires {word_count} registers and cannot be written as a single register"
            )

        try:
            if effective_type == REGISTER_F32:
                value: int | float = float(payload)
            else:
                value = int(payload)
                minimum, maximum = REGISTER_INT_RANGES[effective_type]
                if value < minimum or value > maximum:
                    raise RegisterEncodingError(f"{self._name}: value {value} is outside the {effective_type} register range {minimum}..{maximum}")
            registers = cast(list[int], convert_to_registers(value, data_type, self.plugin.order32))
        except RegisterEncodingError:
            raise
        except (OverflowError, TypeError, ValueError, struct.error) as ex:
            raise RegisterEncodingError(f"{self._name}: cannot encode value {payload!r} as {effective_type}: {ex}") from ex

        if len(registers) != word_count:
            raise RegisterEncodingError(f"{self._name}: encoding {effective_type} produced {len(registers)} registers instead of {word_count}")
        return registers

    def _encode_multi_write_payload(self, payload: list[tuple[Any, Any]]) -> list[int]:
        """Encode a complete multi-register payload before any data is sent."""
        if not isinstance(payload, list) or not payload:
            raise HomeAssistantError(f"{self._name}: multi-register write requires a non-empty payload")

        registers: list[int] = []
        for item in payload:
            try:
                key, value = item
                if key.startswith("_"):
                    register_data_type = key
                else:
                    descr = self.writeLocals[key]
                    reverse_options = getattr(descr, "reverse_option_dict", None)
                    if reverse_options:
                        if isinstance(value, str):
                            if value in reverse_options:
                                value = reverse_options[value]
                            else:
                                value = int(value)
                    elif callable(descr.scale):
                        value = descr.scale(value, descr, self.data)
                    else:
                        value = value * descr.scale
                    register_data_type = descr.register_data_type

                registers.extend(self._encode_write_value(value, register_data_type, single_register=False))
            except Exception as ex:
                raise HomeAssistantError(f"{self._name}: cannot encode multi-register write item {item!r}: {ex}") from ex

        return registers

    async def _async_transport_write(
        self,
        unit: int,
        address: int,
        values: list[int],
        *,
        multiple: bool,
        operation: str,
    ) -> Any:
        """Write encoded registers through the configured transport."""
        if getattr(self, "_stopping", False):
            raise HomeAssistantError(f"{self._name}: integration is stopping")
        async with self._lock:
            if not await self._check_connection():
                raise HomeAssistantError(f"{self._name}: inverter is not connected")
            try:
                response = await self._track_task(self._transport.write(unit, address, values, multiple=multiple))
            except (ModbusException, SerialModbusError, AttributeError, TypeError) as ex:
                await self._handle_transport_exception(ex, operation)
                raise HomeAssistantError(f"{self._name}: {operation} failed: {ex}") from ex
        return self._validate_write_response(
            response,
            unit=unit,
            address=address,
            operation=operation,
        )

    async def async_lowlevel_write_register(self, unit: int, address: int, payload: int, register_data_type: str | None = None) -> Any:
        try:
            regs = self._encode_write_value(payload, register_data_type, single_register=True)
            response = await self._async_transport_write(
                unit=unit,
                address=address,
                values=regs,
                multiple=False,
                operation="single-register write",
            )
        except HomeAssistantError as ex:
            if hasattr(self.plugin, "log_register_write"):
                self.plugin.log_register_write(self, address, unit, payload, error=(type(ex).__name__, str(ex)))
            raise

        if hasattr(self.plugin, "log_register_write"):
            self.plugin.log_register_write(self, address, unit, payload, result=response)
        return response

    async def async_write_register(self, unit: int, address: int, payload: int, register_data_type: str | None = None) -> Any:
        """Write register."""
        awake = self.plugin.isAwake(self.data)
        if awake:
            return await self.async_lowlevel_write_register(unit, address, payload, register_data_type=register_data_type)

        request = PendingWrite(
            unit=unit,
            address=address,
            payload=int(payload),
            register_data_type=register_data_type,
        )
        try:
            # Some commands are accepted even while the inverter reports sleep mode.
            response = await self.async_lowlevel_write_register(
                unit,
                address,
                payload,
                register_data_type=register_data_type,
            )
        except RegisterEncodingError:
            raise
        except HomeAssistantError as ex:
            self.writequeue[(unit, address)] = request
            if self.wakeupButton:
                _LOGGER.info("waking up inverter: pressing awake button")
                try:
                    await self.async_lowlevel_write_register(
                        unit=self._modbus_addr,
                        address=self.wakeupButton.register,
                        payload=self.wakeupButton.command,
                    )
                except HomeAssistantError as wake_ex:
                    _LOGGER.warning(f"{self._name}: inverter wake-up command failed: {wake_ex}")
            else:
                _LOGGER.warning("cannot wakeup inverter: no awake button found")
            raise HomeAssistantError(f"{self._name}: write to register 0x{address:x} was not confirmed and was queued for retry") from ex

        # Preserve the existing behavior of repeating an acknowledged command after wake-up.
        self.writequeue[(unit, address)] = request
        if self.wakeupButton:
            _LOGGER.info("waking up inverter: pressing awake button")
            try:
                await self.async_lowlevel_write_register(
                    unit=self._modbus_addr,
                    address=self.wakeupButton.register,
                    payload=self.wakeupButton.command,
                )
            except HomeAssistantError as ex:
                _LOGGER.warning(f"{self._name}: inverter wake-up command failed after confirmed write: {ex}")
        else:
            _LOGGER.warning("cannot wakeup inverter: no awake button found")
        return response

    async def async_write_registers_single(
        self, unit: int, address: int, payload: int, register_data_type: str | None = None
    ) -> Any:  # Needs adapting for register queue
        """Write registers multi, but write only one register of type 16bit"""
        regs = self._encode_write_value(payload, register_data_type, single_register=True)
        return await self._async_transport_write(
            unit=unit,
            address=address,
            values=regs,
            multiple=True,
            operation="multi-function single-register write",
        )

    async def async_write_registers_multi(self, unit: int, address: int, payload: list[tuple[Any, Any]]) -> Any:  # Needs adapting for register queue
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
        regs_out = self._encode_multi_write_payload(payload)
        _LOGGER.debug(f"Ready to write multiple registers at 0x{address:02x}: {regs_out}")
        return await self._async_transport_write(
            unit=unit,
            address=address,
            values=regs_out,
            multiple=True,
            operation="multi-register write",
        )

    async def async_read_modbus_data(self, group: Any) -> PollOutcome:
        group.publish_updates = False
        try:
            async with self._poll_data_lock:
                return await self.async_read_modbus_registers_all(group)
        except ConnectionException as ex:
            _LOGGER.error(f"Reading data failed! Inverter is offline. {ex}")
        except ModbusIOException as ex:
            _LOGGER.error(f"ModbusIOError: {ex}")
        except Exception as ex:
            _LOGGER.exception(f"Something went wrong reading from modbus: {ex}")
        return PollOutcome.FAILED

    def treat_address(
        self,
        data: dict[str, Any],
        regs: list[int],
        idx: int,
        descr: Any,
        initval: int = 0,
        advance: bool = True,
        fresh_keys: set[str] | None = None,
    ) -> int:
        return_value: int | None = None
        read_scale = descr.read_scale  # read scale might still be wrong the first polling cycle
        order32 = getattr(descr, "order32", None) or self.plugin.order32
        val = None
        if self.cyclecount < VERBOSE_CYCLES:
            _LOGGER.debug(f"{self._name}: treating register 0x{descr.register:02x} : {descr.key}")
        words_used = 0
        try:
            if descr.register_data_type == REGISTER_U16:
                val = convert_from_registers(regs[idx : idx + 1], DataType.UINT16, self.plugin.order32)  # type: ignore[attr-defined]
                words_used = 1
            elif descr.register_data_type == REGISTER_S16:
                val = convert_from_registers(regs[idx : idx + 1], DataType.INT16, self.plugin.order32)  # type: ignore[attr-defined]
                words_used = 1
            elif descr.register_data_type == REGISTER_U32:
                val = convert_from_registers(regs[idx : idx + 2], DataType.UINT32, order32)  # type: ignore[attr-defined]
                words_used = 2
            elif descr.register_data_type == REGISTER_F32:
                val = convert_from_registers(regs[idx : idx + 2], DataType.FLOAT32, order32)  # type: ignore[attr-defined]
                words_used = 2
            elif descr.register_data_type == REGISTER_S32:
                val = convert_from_registers(regs[idx : idx + 2], DataType.INT32, order32)  # type: ignore[attr-defined]
                words_used = 2
            elif descr.register_data_type == REGISTER_STR:
                wc = descr.wordcount or 0
                raw = convert_from_registers(regs[idx : idx + wc], DataType.STRING, order32)  # type: ignore[attr-defined]
                words_used = wc
                val = raw.decode("ascii", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            elif descr.register_data_type == REGISTER_WORDS:
                wc = descr.wordcount or 0
                val = [convert_from_registers(regs[idx + i : idx + i + 1], DataType.UINT16, self.plugin.order32) for i in range(wc)]  # type: ignore[attr-defined]
                words_used = wc
            elif descr.register_data_type == REGISTER_ULSB16MSB16:
                lo = convert_from_registers(regs[idx : idx + 1], DataType.UINT16, order32)  # type: ignore[attr-defined]
                hi = convert_from_registers(regs[idx + 1 : idx + 2], DataType.UINT16, order32)  # type: ignore[attr-defined]
                val = (hi + lo * 65536) if order32 == "big" else (lo + hi * 65536)
                words_used = 2
            elif descr.register_data_type == REGISTER_U8L:
                if advance:
                    base = convert_from_registers(regs[idx : idx + 1], DataType.UINT16, self.plugin.order32)  # type: ignore[attr-defined]
                    words_used = 1
                    val = base % 256
                else:
                    val = initval % 256
                    words_used = 0
            elif descr.register_data_type == REGISTER_U8H:
                if advance:
                    base = convert_from_registers(regs[idx : idx + 1], DataType.UINT16, self.plugin.order32)  # type: ignore[attr-defined]
                    words_used = 1
                    val = base >> 8
                else:
                    val = initval >> 8
                    words_used = 0
            else:
                _LOGGER.warning(f"{self._name}: undefinded unit for entity {descr.key} - setting value to zero")
                val = 0
                words_used = 0
        except Exception:
            if self.cyclecount < VERBOSE_CYCLES:
                _LOGGER.warning(
                    f"{self._name}: read failed at 0x{descr.register:02x}: {descr.key}",
                    exc_info=True,
                )
            else:
                _LOGGER.warning(f"{self._name}: read failed at 0x{descr.register:02x}: {descr.key} ")
        """ TO BE REMOVED
        if descr.prevent_update:
            if  (self.tmpdata_expiry.get(descr.key, 0) > _mtime.time()):
                val = self.tmpdata.get(descr.key, None)
                if val is None:
                    LOGGER.warning(f"cannot find tmpdata for {descr.key} - setting value to zero")
                    val = 0
            else: # expired
                if self.tmpdata_expiry.get(descr.key, 0) > 0: self.localsUpdated = True
                self.tmpdata_expiry[descr.key] = 0 # update locals only once
        """

        # Plugin-level validation hook
        if self._validate_register_func is not None:
            val = self._validate_register_func(descr, val, data)

        if isinstance(val, list) and descr.register_data_type != REGISTER_WORDS:
            if self.cyclecount < VERBOSE_CYCLES:
                _LOGGER.warning(f"{self._name}: invalid list value for numeric entity {descr.key}: {val} - setting value to None")
            val = None

        if val is None:  # E.g. if errors have occurred during readout
            # _LOGGER.warning(f"****tmp*** treating {descr.key} failed")
            return_value = None
        elif type(descr.scale) is dict:  # translate int to string
            return_value = descr.scale.get(val, "Unknown")
        elif callable(descr.scale):  # function to call ?
            return_value = descr.scale(val, descr, data)
        else:  # apply simple numeric scaling and rounding if not a list of words
            try:
                return_value = round(val * descr.scale * read_scale, descr.rounding)
            except Exception:
                return_value = val  # probably a REGISTER_WORDS instance
            native_unit = getattr(descr, "native_unit_of_measurement", None)
            if native_unit == UnitOfFrequency.HERTZ:
                min_val = getattr(descr, "min_value", 20)
                max_val = getattr(descr, "max_value", 80)
            if native_unit == PERCENTAGE:
                min_val = getattr(descr, "min_value", 0)
                max_val = getattr(descr, "max_value", 100)
            elif native_unit == UnitOfTemperature.CELSIUS:
                min_val = getattr(descr, "min_value", -100)
                max_val = getattr(descr, "max_value", 200)
            elif native_unit == UnitOfPower.KILO_WATT:
                min_val = getattr(descr, "min_value", -self.inverterPowerKw * 2)
                max_val = getattr(descr, "max_value", +self.inverterPowerKw * 2)
            elif native_unit == UnitOfElectricCurrent.AMPERE:
                min_val = getattr(descr, "min_value", -self.inverterPowerKw * 2)
                max_val = getattr(descr, "max_value", +self.inverterPowerKw * 2)
            elif native_unit == UnitOfElectricPotential.VOLT:
                min_val = getattr(descr, "min_value", 0)
                max_val = getattr(descr, "max_value", 2000)
            else:
                min_val = getattr(descr, "min_value", None)
                max_val = getattr(descr, "max_value", None)

            if min_val is not None and return_value < min_val:
                raise ModbusIOException(f"Value {return_value} of '{descr.key}' lower than {min_val}")  # type: ignore[no-untyped-call]
            if max_val is not None and return_value > max_val:
                raise ModbusIOException(f"Value {return_value} of '{descr.key}' greater than {max_val}")  # type: ignore[no-untyped-call]
        # if (descr.sleepmode != SLEEPMODE_LASTAWAKE) or self.awakeplugin(self.data): self.data[descr.key] = return_value
        if (
            (self.tmpdata_expiry.get(descr.key, 0) == 0)
            and ((descr.sleepmode != SLEEPMODE_LASTAWAKE) or self.plugin.isAwake(data))
            and (self.localsLoaded or not descr.read_scale_exceptions)  # ignore as long as read scale is not adapted; may delay real startup a bit
        ):
            data[descr.key] = return_value  # case prevent_update number
            if fresh_keys is not None:
                fresh_keys.add(descr.key)
        return idx + (words_used if advance else 0)

    async def async_read_modbus_block(self, data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        errmsg = None
        communication_succeeded = False
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
            if realtime_data is None:
                errmsg = "read_error "
            else:
                communication_succeeded = True
                if realtime_data.isError():
                    errmsg = "read_error "
        if errmsg is None:
            regs = realtime_data.registers
            idx = 0
            fresh_keys: set[str] = set()
            for reg in block.regs:
                expected_idx = reg - block.start
                if idx < expected_idx:
                    if self.cyclecount < 5 and expected_idx > idx:
                        _LOGGER.debug(f"skipping bytes {(expected_idx - idx) * 2}")
                    idx = expected_idx

                descr = block.descriptions[reg]

                if isinstance(descr, dict):
                    base16 = convert_from_registers(regs[idx : idx + 1], DataType.UINT16, self.plugin.order32)  # type: ignore[attr-defined]
                    for k in descr:
                        self.treat_address(data, regs, idx, descr[k], initval=base16, advance=False, fresh_keys=fresh_keys)
                    idx += 1
                else:
                    idx = self.treat_address(data, regs, idx, descr, initval=0, advance=True, fresh_keys=fresh_keys)
            self._record_block_result(block, typ, True)
            return BlockReadResult(
                data_succeeded=True,
                communication_succeeded=True,
                fresh_keys=frozenset(fresh_keys),
            )
        else:  # block read failure
            self._record_block_result(block, typ, False, errmsg)
            # Check only the first item in the block for ignore_readerror behavior.
            firstdescr_raw = block.descriptions.get(block.start) or block.descriptions[block.regs[0]]
            firstdescr = next(iter(firstdescr_raw.values())) if isinstance(firstdescr_raw, dict) else firstdescr_raw
            _LOGGER.debug(
                f"{self._name}: failed {typ} block {errmsg} start 0x{block.start:x} {firstdescr.key} ignore_readerror: {firstdescr.ignore_readerror}"
            )
            tolerated = firstdescr.ignore_readerror is not False
            _LOGGER.debug(f"{self._name}: failed block analysis started firstignore: {firstdescr.ignore_readerror}")
            for reg in block.regs:
                descr = block.descriptions[reg]
                if type(descr) is dict:
                    items = descr.items()  # special case: multiple U8x entities
                else:
                    items = {
                        descr.key: descr,
                    }.items()  # normal case, one entity
                for k, d in items:
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
            if tolerated and self.slowdown == 1:
                _LOGGER.info(
                    f"{self._name} : {errmsg}: cannot read {typ} registers at device {self._modbus_addr} position 0x{block.start:x}",
                    exc_info=True,
                )
            return BlockReadResult(
                data_succeeded=False,
                communication_succeeded=communication_succeeded,
                tolerated=tolerated,
            )

    def _commit_poll_snapshot(self, previous_data: dict[str, Any], new_data: dict[str, Any]) -> None:
        """Commit polling changes without replacing the shared data dictionary."""
        missing = object()

        for key in previous_data.keys() - new_data.keys():
            if self.data.get(key, missing) == previous_data[key]:
                self.data.pop(key, None)

        for key, value in new_data.items():
            previous_value = previous_data.get(key, missing)
            if previous_value is not missing and value == previous_value:
                continue

            current_value = self.data.get(key, missing)
            if current_value is missing or current_value == previous_value:
                self.data[key] = value

    def _active_computed_dependencies(self, descr: Any) -> set[str] | None:
        """Return declared dependencies that are available for this inverter."""
        dependencies = getattr(descr, "depends_on", None)
        if dependencies is None:
            return None
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        return {dependency for dependency in dependencies if dependency in self.sensorDescriptions}

    def _compute_poll_sensors(self, data: dict[str, Any], fresh_keys: set[str]) -> set[str]:
        """Compute sensors whose active, explicitly declared dependencies are fresh."""
        computed_fresh_keys: set[str] = set()
        pending = list(self.computedSensors.items())

        while pending:
            remaining: list[tuple[str, Any]] = []
            made_progress = False

            for key, descr in pending:
                dependencies = self._active_computed_dependencies(descr)
                if dependencies is not None and not dependencies.issubset(fresh_keys):
                    remaining.append((key, descr))
                    continue

                try:
                    data[key] = descr.value_function(0, descr, data)
                except Exception as ex:
                    _LOGGER.debug(f"{self._name}: cannot compute value for {key}: {ex}")
                    continue

                fresh_keys.add(key)
                computed_fresh_keys.add(key)
                made_progress = True

            if not made_progress:
                for key, descr in remaining:
                    dependencies = self._active_computed_dependencies(descr)
                    missing = set(dependencies or []) - fresh_keys
                    _LOGGER.debug(f"{self._name}: keeping previous value for {key}; dependencies not fresh: {sorted(missing)}")
                break
            pending = remaining

        return computed_fresh_keys

    async def async_read_modbus_registers_all(self, group: Any) -> PollOutcome:
        group.publish_updates = False
        if group.readPreparation is not None:
            if not await group.readPreparation(self.data):
                _LOGGER.info(f"{self._name}: device group read cancel")
                return PollOutcome.SKIPPED
        else:
            _LOGGER.debug(f"{self._name}: device group inverter")

        previous_data = self.data.copy()
        data = previous_data.copy()
        block_results: list[BlockReadResult] = []
        fresh_keys: set[str] = set()
        for block in group.holdingBlocks:
            _LOGGER.debug(f"{self._name}: ** trying to read holding block 0x{block.start:x}")
            block_result = await self.async_read_modbus_block(data, block, "holding")
            block_results.append(block_result)
            fresh_keys.update(block_result.fresh_keys)
            _LOGGER.debug(
                f"{self._name}: holding block 0x{block.start:x} read done; "
                f"data_succeeded={block_result.data_succeeded}, communication_succeeded={block_result.communication_succeeded}"
            )
        for block in group.inputBlocks:
            _LOGGER.debug(f"{self._name}: ** trying to read input block 0x{block.start:x}")
            block_result = await self.async_read_modbus_block(data, block, "input")
            block_results.append(block_result)
            fresh_keys.update(block_result.fresh_keys)
            _LOGGER.debug(
                f"{self._name}: input block 0x{block.start:x} read done; "
                f"data_succeeded={block_result.data_succeeded}, communication_succeeded={block_result.communication_succeeded}"
            )

        all_data_succeeded = all(result.data_succeeded for result in block_results)
        communication_succeeded = not block_results or any(result.communication_succeeded for result in block_results)
        required_block_failed = any(not result.data_succeeded and not result.tolerated for result in block_results)
        if all_data_succeeded:
            poll_outcome = PollOutcome.SUCCESS
        elif communication_succeeded:
            poll_outcome = PollOutcome.PARTIAL
        else:
            poll_outcome = PollOutcome.FAILED

        local_callback_needed = self.localsUpdated
        if self.localsUpdated:
            await self._hass.async_add_executor_job(self.saveLocalData)
            self.plugin.localDataCallback(self)
        if not self.localsLoaded:
            await self._hass.async_add_executor_job(self.loadLocalData)
            local_callback_needed = local_callback_needed or self.localsLoaded

        # Local controls can change independently while a Modbus group is being read.
        for key in self.writeLocals:
            if key in self.data:
                data[key] = self.data[key]

        computed_fresh_keys: set[str] = set()
        if poll_outcome.communication_succeeded:
            computed_fresh_keys = self._compute_poll_sensors(data, fresh_keys)

            if group.readFollowUp is not None:
                if not await group.readFollowUp(previous_data, data):
                    _LOGGER.warning(f"{self._name}: device group validation failed; discarding polling snapshot")
                    return PollOutcome.DISCARDED

            self._commit_poll_snapshot(previous_data, data)
            if local_callback_needed:
                self.plugin.localDataCallback(self)

            for key, descr in list(self.computedSensors.items()):
                if key not in computed_fresh_keys:
                    continue
                sens = self.sensorEntities.get(key)
                _LOGGER.debug(f"{self._name}: quickly updating state for computed sensor {sens} {key} {self.data.get(descr.key)} ")
                if sens and (not descr.internal):
                    try:
                        sens.modbus_data_updated()
                    except Exception:
                        _LOGGER.debug(f"{self._name}: cannot send update for {key} - probably disabled ")
            group.publish_updates = True

        if poll_outcome.communication_succeeded and not required_block_failed and self.writequeue and self.plugin.isAwake(self.data):
            # process outstanding write requests
            _LOGGER.info(f"inverter is now awake, processing outstanding write requests {self.writequeue}")
            for queue_key, request in list(self.writequeue.items()):
                try:
                    await self.async_lowlevel_write_register(
                        unit=request.unit,
                        address=request.address,
                        payload=request.payload,
                        register_data_type=request.register_data_type,
                    )
                except HomeAssistantError as ex:
                    _LOGGER.warning(f"{self._name}: queued write to register 0x{request.address:x} is still not confirmed: {ex}")
                else:
                    self.writequeue.pop(queue_key, None)

        # execute autorepeat entities (buttons and selects)
        self.last_ts = _mtime.time()
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
                        await self.async_write_register(unit=self._modbus_addr, address=reg, payload=payload.get("payload"))
            elif descr:  # expired autorepeats
                if self.data["_repeatUntil"][k] > 0:  # expired recently
                    self.data["_repeatUntil"][k] = 0  # mark as finally expired, no further buttonrepeat post after this one
                    _LOGGER.info(f"calling final value function POST for {k} with initval {BUTTONREPEAT_POST}")
                    payload = descr.value_function(BUTTONREPEAT_POST, descr, self.data)  # None means no final call after expiration
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
        return poll_outcome

    # --------------------------------------------- Check if sensor is a dependency -----------------------------------------------

    def _is_dependency_for_enabled_control(self, sensor_key: str) -> bool:
        """Check if a sensor is a required data source for any enabled control."""
        control_keys = self.entity_dependencies.get(sensor_key, [])
        for control_key in control_keys:  # usually zero or one key
            # This sensor is a dependency. Now, is the control that needs it enabled?
            # We can reuse the logic from should_register_be_loaded, but we need to find the correct descriptor first.
            control_descr = None
            # currently, a sensor can only have one associated control - is this comment still true???
            control_entity = self.selectEntities.get(control_key)
            if control_entity:
                control_descr = control_entity.entity_description
            if not control_descr:
                control_entity = self.numberEntities.get(control_key)
                if control_entity:
                    control_descr = control_entity.entity_description
            if not control_descr:
                control_entity = self.switchEntities.get(control_key)
                if control_entity:
                    control_descr = control_entity.entity_description
            if not control_descr:
                control_entity = self.sensorEntities.get(control_key)
                if control_entity:
                    control_descr = control_entity.entity_description
            if not control_descr:
                control_descr = self.sensorDescriptions.get(control_key)
            if control_descr and should_register_be_loaded(self._hass, self, control_descr):
                _LOGGER.debug(f"Sensor '{sensor_key}' is required by enabled control or value_function entity '{control_key}'.")
                return True
        return False

    # --------------------------------------------- Sorting and grouping of entities -----------------------------------------------

    def splitInBlocks(self, descriptions: dict[Any, Any]) -> list[Any]:
        start = INVALID_START
        end = 0
        blocks: list[Any] = []
        block_size = self.plugin.block_size
        auto_block_ignore_readerror = self.plugin.auto_block_ignore_readerror
        curblockregs: list[Any] = []
        for reg, descr in descriptions.items():
            d_ignore_readerror = auto_block_ignore_readerror
            if type(descr) is dict:  # 2 byte  REGISTER_U8L, _U8H values on same modbus 16 bit address
                d_newblock = False
                d_enabled = False
                first_descr = next(iter(descr.values()))
                d_unit = first_descr.register_data_type
                d_wordcount = 1  # U8L/U8H values share one 16-bit Modbus register.
                d_key = first_descr.key
                d_regtype = first_descr.register_type
                for _sub, d in descr.items():
                    # d_newblock = d_newblock or d.newblock # ok, if needed, put a newblock on all subentries
                    if should_register_be_loaded(self._hass, self, d):  # *** CHANGED LINE: logic delegated to new function
                        d_enabled = True
                        break
            else:  # normal entity
                # 1. First, check if the entity itself should be loaded based on its own state or defaults.
                d_enabled = should_register_be_loaded(self._hass, self, descr)

                # 2. If it's disabled, check if it's a required dependency for another ENABLED control.
                if not d_enabled:
                    if self._is_dependency_for_enabled_control(descr.key):
                        d_enabled = True
                        _LOGGER.debug(f"{self._name}: Forcing poll for disabled sensor '{descr.key}' as it's a needed dependency.")

                d_newblock = descr.newblock
                d_unit = descr.register_data_type
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
                                for _sub, d in descr.items():
                                    if d.ignore_readerror is False:
                                        descr[_sub] = replace(d, ignore_readerror=auto_block_ignore_readerror)
                                        d_ignore_readerror = d_ignore_readerror or auto_block_ignore_readerror
                            else:
                                if descr.ignore_readerror is False:
                                    descr = replace(descr, ignore_readerror=auto_block_ignore_readerror)
                                    descriptions[reg] = descr
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
                    REGISTER_F32,
                    REGISTER_ULSB16MSB16,
                ):
                    end = reg + 2
                else:
                    end = reg + 1
                _LOGGER.debug(f"{self._name}: adding type {d_regtype} register 0x{reg:x} {d_key} to block with start 0x{start:x}")
                curblockregs.append(reg)
            else:
                _LOGGER.debug(f"{self._name}: ignoring type {d_regtype} register 0x{reg:x} {d_key} to block with start 0x{start:x}")

        if (end - start) > 0:  # close last block
            # newblock = block(start = start, end = end, order16 = descriptions[start].order16, order32 = descriptions[start].order32, descriptions = descriptions, regs = curblockregs)
            newblock = block(start=start, end=end, descriptions=descriptions, regs=curblockregs)
            blocks.append(newblock)
        return blocks

    def rebuild_blocks(self, initial_groups: dict[Any, Any]) -> None:  # , computedRegs):
        _LOGGER.debug(f"{self._name}: rebuilding groups and blocks - pre: {initial_groups.keys()}")
        self.initial_groups = initial_groups
        for interval, interval_group in initial_groups.items():
            for device_name, device_group in interval_group.device_groups.items():
                _LOGGER.debug(f"{self._name}: rebuild for device {device_name} in interval {interval}")
                holdingRegs = dict(sorted(device_group.holdingRegs.items()))
                inputRegs = dict(sorted(device_group.inputRegs.items()))
                # update the hub groups
                hub_interval_group = self.groups.setdefault(interval, empty_hub_interval_group_lambda())
                hub_device_group = hub_interval_group.device_groups.setdefault(device_name, empty_hub_device_group_lambda())
                hub_device_group.readPreparation = device_group.readPreparation
                hub_device_group.readFollowUp = device_group.readFollowUp
                hub_device_group.holdingBlocks = self.splitInBlocks(holdingRegs)
                hub_device_group.inputBlocks = self.splitInBlocks(inputRegs)
                # self.computedSensors = computedRegs # moved outside the loops
                for i in hub_device_group.holdingBlocks:
                    _LOGGER.debug(f"{self._name} - interval {interval}s: adding holding block: {', '.join(f'0x{num:x}' for num in i.regs)}")
                for i in hub_device_group.inputBlocks:
                    _LOGGER.debug(f"{self._name} - interval {interval}s: adding input block: {', '.join(f'0x{num:x}' for num in i.regs)}")
                # _LOGGER.debug(f"holdingBlocks: {hub_device_group.holdingBlocks}")
                # _LOGGER.debug(f"inputBlocks: {hub_device_group.inputBlocks}")
        self.blocks_changed = False
        _LOGGER.debug(f"{self._name}: done rebuilding groups and blocks - post: {self.initial_groups.keys()}")

    def _block_key(self, block_obj: Any, typ: str) -> str:
        return f"{typ}:0x{block_obj.start:x}-0x{block_obj.end:x}"

    def _format_register(self, typ: str, addr: int) -> str:
        descr = self._find_descriptor_for_reg(typ, addr)
        key: str | None = None
        if isinstance(descr, dict):
            key = "/".join(str(getattr(item, "key", "")) for item in descr.values() if getattr(item, "key", None))
        elif descr is not None:
            key = getattr(descr, "key", None)
        label = f"{typ} 0x{addr:x}"
        return f"{label} ({key})" if key else label

    def _find_descriptor_for_reg(self, typ: str, addr: int) -> Any | None:
        for interval_group in self.initial_groups.values():
            for device_group in getattr(interval_group, "device_groups", {}).values():
                regs = getattr(device_group, "holdingRegs", {}) if typ == "holding" else getattr(device_group, "inputRegs", {})
                if addr in regs:
                    return regs[addr]
        for interval_group in self.groups.values():
            for device_group in getattr(interval_group, "device_groups", {}).values():
                blocks = getattr(device_group, "holdingBlocks", []) if typ == "holding" else getattr(device_group, "inputBlocks", [])
                for block_obj in blocks:
                    if addr in (block_obj.regs or []):
                        return block_obj.descriptions.get(addr) if block_obj.descriptions else None
        return None

    def _record_block_result(self, block_obj: Any, typ: str, success: bool, errmsg: str | None = None) -> None:
        key = self._block_key(block_obj, typ)
        if success:
            self._comm_last_block_success_time = _mtime.time()
            self._comm_block_failures.pop(key, None)
            return

        now = _mtime.time()
        self._comm_last_block_failure_time = now
        self._comm_last_error = f"{key}: {errmsg or 'read_error'}"
        self._comm_last_error_time = _mtime.strftime("%Y-%m-%d %H:%M:%S")
        failures = [ts for ts in self._comm_block_failures.get(key, []) if now - ts <= COMM_BLOCK_FAILURE_WINDOW]
        failures.append(now)
        self._comm_block_failures[key] = failures
        if len(failures) >= COMM_BLOCK_FAILURE_THRESHOLD:
            self._schedule_runtime_bisect(block_obj, typ)

    def _schedule_runtime_bisect(self, block_obj: Any, typ: str) -> None:
        if getattr(self, "_stopping", False):
            return
        key = self._block_key(block_obj, typ)
        task = self._runtime_bisect_tasks.get(key)
        if task and not task.done():
            return
        last_success = self._comm_last_block_success_time
        if last_success is None or (_mtime.time() - last_success) > COMM_BLOCK_FAILURE_WINDOW:
            _LOGGER.debug(f"{self._name}: skipping runtime bisect for {key}; no recent successful block reads")
            return
        recent = self._comm_recent_outcomes[-20:]
        if recent and not any(outcome.communication_succeeded for outcome in recent):
            _LOGGER.debug(f"{self._name}: skipping runtime bisect for {key}; all recent polls failed")
            return
        probe_block = block(
            start=block_obj.start,
            end=block_obj.end,
            descriptions=block_obj.descriptions,
            regs=list(block_obj.regs or []),
        )
        task = self._hass.loop.create_task(self._runtime_bisect_block(probe_block, typ, key))
        self._runtime_bisect_tasks[key] = task

        def _remove_runtime_bisect_task(_task: asyncio.Task[Any], block_key: str = key) -> None:
            self._runtime_bisect_tasks.pop(block_key, None)

        task.add_done_callback(_remove_runtime_bisect_task)

    async def _runtime_bisect_block(self, block_obj: Any, typ: str, key: str) -> None:
        if not self._transport.is_connected():
            return
        candidates: set[int] = set()
        _LOGGER.warning(f"{self._name}: repeated failures for {key}; probing block to isolate bad registers")
        try:
            await self._find_bad_regs_in_block(block_obj, typ, candidates)
            confirmed: list[int] = []
            for addr in sorted(candidates):
                if addr in self.bad_regs[typ]:
                    continue
                if await self._confirm_bad_register(typ, addr):
                    self.bad_regs[typ].add(addr)
                    self._comm_last_quarantined_register = self._format_register(typ, addr)
                    confirmed.append(addr)
            if confirmed:
                self.blocks_changed = True
                self._ensure_quarantine_recheck_task()
                labels = ", ".join(self._format_register(typ, addr) for addr in confirmed)
                _LOGGER.warning(f"{self._name}: quarantined unreadable Modbus register(s): {labels}")
                self._update_communication_data()
                self._publish_communication_diagnostics()
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            _LOGGER.debug(f"{self._name}: runtime bisect for {key} failed: {ex}")

    async def _find_bad_regs_in_block(self, block_obj: Any, typ: str, candidates: set[int], depth: int = 0) -> None:
        if getattr(self, "_stopping", False):
            return
        if await self._probe_block(block_obj, typ):
            return
        if not self._transport.is_connected():
            return

        regs = list(block_obj.regs or [])
        if depth >= self.bisect_max_depth or len(regs) <= 1:
            if len(regs) == 1:
                candidates.add(regs[0])
                _LOGGER.debug(f"{self._name}: candidate bad {typ} entity base 0x{regs[0]:x}")
            return

        mid = len(regs) // 2
        await self._find_bad_regs_in_block(self._subblock_entity_span(block_obj, 0, mid), typ, candidates, depth + 1)
        await self._find_bad_regs_in_block(self._subblock_entity_span(block_obj, mid, len(regs)), typ, candidates, depth + 1)

    async def _confirm_bad_register(self, typ: str, addr: int) -> bool:
        single = self._single_register_block(typ, addr)
        failures = 0
        for _ in range(2):
            if not self._transport.is_connected():
                return False
            if await self._probe_block(single, typ):
                return False
            failures += 1
            await asyncio.sleep(1)
        return failures >= 2

    def _single_register_block(self, typ: str, addr: int) -> Any:
        descr = self._find_descriptor_for_reg(typ, addr)
        desc_map = {addr: descr} if descr is not None else {}
        try:
            end = self._entity_span_end(desc_map, addr) if desc_map else addr + 1
        except Exception:
            end = addr + 1
        return block(start=addr, end=end, descriptions=desc_map, regs=[addr])

    def _ensure_quarantine_recheck_task(self) -> None:
        task = self._quarantine_recheck_task
        if task and not task.done():
            return
        self._quarantine_recheck_task = self._hass.loop.create_task(self._quarantine_recheck_loop())

    async def _quarantine_recheck_loop(self) -> None:
        try:
            while not getattr(self, "_stopping", False):
                await asyncio.sleep(COMM_RECOVERY_INTERVAL)
                if not (self.bad_regs["holding"] or self.bad_regs["input"]):
                    return
                self._comm_recovery_active = True
                try:
                    for typ in ("holding", "input"):
                        for addr in sorted(list(self.bad_regs[typ])):
                            await self._recheck_quarantined_register(typ, addr)
                finally:
                    self._comm_recovery_active = False
                    self._update_communication_data()
                    self._publish_communication_diagnostics()
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            _LOGGER.debug(f"{self._name}: quarantine recheck loop failed: {ex}")

    async def _recheck_quarantined_register(self, typ: str, addr: int) -> None:
        if not self._transport.is_connected():
            return
        single = self._single_register_block(typ, addr)
        if not await self._probe_block(single, typ, timeout=self._quarantine_recheck_timeout()):
            return
        self.bad_regs[typ].discard(addr)
        self._comm_last_recovered_register = self._format_register(typ, addr)
        self.blocks_changed = True
        _LOGGER.info(f"{self._name}: restored previously quarantined Modbus register {self._comm_last_recovered_register}")

    def _quarantine_recheck_timeout(self) -> float:
        return max(2.0, float(self._time_out) / 3.0)

    def _record_poll_cycle(self, outcome: PollOutcome, elapsed: float, interval: int | float | None) -> None:
        if outcome is PollOutcome.SKIPPED:
            return
        self._comm_recent_outcomes.append(outcome)
        self._comm_recent_outcomes = self._comm_recent_outcomes[-COMM_HISTORY_LIMIT:]
        elapsed_ms = int(elapsed * 1000)
        self._comm_poll_durations.append(elapsed_ms)
        self._comm_poll_durations = self._comm_poll_durations[-COMM_HISTORY_LIMIT:]
        if interval and elapsed >= interval:
            self._comm_overrun_count += 1
        self._update_communication_data()
        self._publish_communication_diagnostics()

    def _update_communication_data(self) -> None:
        recent = self._comm_recent_outcomes
        success_rate = round((sum(1 for outcome in recent if outcome.communication_succeeded) / len(recent)) * 100, 1) if recent else None
        quarantined_count = sum(len(regs) for regs in self.bad_regs.values())
        last_five = recent[-5:]

        if recent and last_five and not any(outcome.communication_succeeded for outcome in last_five):
            health = "Offline"
        elif self._comm_recovery_active:
            health = "Recovering"
        elif quarantined_count:
            health = "Quarantined"
        elif self._comm_last_block_failure_time and (_mtime.time() - self._comm_last_block_failure_time) <= COMM_BLOCK_FAILURE_WINDOW:
            health = "Degraded"
        elif success_rate is not None and success_rate < 98:
            health = "Degraded"
        else:
            health = "Healthy"

        self.data["communication_health"] = health
        self.data["communication_success_rate"] = success_rate
        self.data["communication_quarantined_registers"] = quarantined_count

    def _publish_communication_diagnostics(self) -> None:
        for key in ("communication_health", "communication_success_rate", "communication_quarantined_registers"):
            sens = self.sensorEntities.get(key)
            if sens:
                try:
                    sens.modbus_data_updated()
                except Exception:
                    _LOGGER.debug(f"{self._name}: cannot send communication diagnostic update for {key}")

    def communication_health_attributes(self) -> dict[str, Any]:
        durations = self._comm_poll_durations
        avg_duration = round(sum(durations) / len(durations), 1) if durations else None
        max_duration = max(durations) if durations else None
        return {
            "success_rate": self.data.get("communication_success_rate"),
            "last_error": self._comm_last_error,
            "last_error_time": self._comm_last_error_time,
            "last_block_failure_age_seconds": round(_mtime.time() - self._comm_last_block_failure_time, 1)
            if self._comm_last_block_failure_time
            else None,
            "average_poll_duration_ms": avg_duration,
            "max_poll_duration_ms": max_duration,
            "overrun_count": self._comm_overrun_count,
            "quarantined_registers": self.data.get("communication_quarantined_registers", 0),
            "recovering": self._comm_recovery_active,
            "last_quarantined_register": self._comm_last_quarantined_register,
            "last_recovered_register": self._comm_last_recovered_register,
        }

    def communication_quarantine_attributes(self) -> dict[str, Any]:
        registers = [self._format_register(typ, addr) for typ in ("holding", "input") for addr in sorted(self.bad_regs[typ])]
        return {
            "registers": registers,
            "next_recheck_interval_seconds": COMM_RECOVERY_INTERVAL,
            "recheck_timeout_seconds": round(self._quarantine_recheck_timeout(), 1),
            "recheck_strategy": "all_quarantined_registers_per_interval",
            "last_quarantined_register": self._comm_last_quarantined_register,
            "last_recovered_register": self._comm_last_recovered_register,
        }

    def _entity_span_end(self, desc_map: dict[int, Any], base_reg: int) -> int:
        """Compute end address (exclusive) for a single entity starting at base_reg based on its unit.
        This ensures we never split STR/WORDS or 32-bit entities."""
        descr = desc_map.get(base_reg)
        if descr is None:
            return base_reg + 1
        # If the descriptor is a dict of byte-split entities (U8H/U8L), they share the same 16-bit reg
        if isinstance(descr, dict):
            return base_reg + 1
        unit = getattr(descr, "register_data_type", getattr(descr, "unit", None))
        if unit in (REGISTER_S32, REGISTER_U32, REGISTER_F32, REGISTER_ULSB16MSB16):
            return base_reg + 2
        if unit in (REGISTER_STR, REGISTER_WORDS):
            wc = getattr(descr, "wordcount", 1) or 1
            return base_reg + wc
        return base_reg + 1

    def _subblock_entity_span(self, block_obj: Any, i0: int, i1: int) -> Any:
        """Create a sub-block using entity-base indices [i0, i1), computing a correct exclusive end
        based on the last entity's span. This preserves multi-register entities on reads."""
        regs = block_obj.regs[i0:i1]
        # start is the first entity base
        start = regs[0]
        # end must honor the last entity's full span
        last_base = regs[-1]
        end = self._entity_span_end(block_obj.descriptions, last_base)
        return block(start=start, end=end, descriptions=block_obj.descriptions, regs=regs)

    async def _probe_block(self, block_obj: Any, typ: str, timeout: float | None = None) -> bool:
        if getattr(self, "_stopping", False):
            return False
        """Transport-level probe: perform a raw modbus read for [start, end) without decoding.
        Returns True if the read returns a non-error response; False on error/timeout."""
        count = max(0, block_obj.end - block_obj.start)
        if count <= 0:
            return True
        try:
            timeout_msg = f" timeout={timeout:.1f}s" if timeout is not None else ""
            _LOGGER.debug(f"{self._name}: probing {typ} 0x{block_obj.start:x}-0x{block_obj.end:x}{timeout_msg}")
            if typ == "input":
                read_coro = self.async_read_input_registers(unit=self._modbus_addr, address=block_obj.start, count=count)
            else:
                read_coro = self.async_read_holding_registers(unit=self._modbus_addr, address=block_obj.start, count=count)
            resp = await asyncio.wait_for(read_coro, timeout=timeout) if timeout is not None else await read_coro
            if resp is None:
                return False
            is_err = getattr(resp, "isError", lambda: False)()
            return not is_err
        except TimeoutError:
            timeout_msg = f"{timeout:.1f}s" if timeout is not None else "configured timeout"
            _LOGGER.debug(f"{self._name}: probe {typ} 0x{block_obj.start:x}-0x{block_obj.end:x} timed out after {timeout_msg}")
            return False
        except Exception as ex:
            _LOGGER.info(f"{self._name}: probe {typ} 0x{block_obj.start:x}-0x{block_obj.end:x} failed: {ex}")
            return False


class SolaXCoreModbusHub(SolaXModbusHub):
    """Compatibility type using the Core transport configured by the base hub."""
