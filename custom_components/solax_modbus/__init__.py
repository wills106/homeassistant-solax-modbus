"""The SolaX Modbus Integration."""

import asyncio
from datetime import timedelta

# import importlib.util, sys
import importlib
import json
import logging
from time import time
from types import ModuleType, SimpleNamespace
from typing import Any, Optional
from weakref import ref as WeakRef

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
from pymodbus.pdu import register_message

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STARTED,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

try:
    from homeassistant.components.modbus import ModbusHub as CoreModbusHub, get_hub as get_core_hub
except ImportError:

    def get_hub(name):
        None

    class CoreModbusHub:
        """place holder dummy"""


from .sensor import SolaXModbusSensor

_LOGGER = logging.getLogger(__name__)
# try: # pymodbus 3.0.x

#    UNIT_OR_SLAVE = 'slave'
#    _LOGGER.warning("using pymodbus library 3.x")
# except: # pymodbus 2.5.3
#    from pymodbus.client.sync import ModbusTcpClient, ModbusSerialClient
#    UNIT_OR_SLAVE = 'unit'
#    _LOGGER.warning("using pymodbus library 2.x")
# import pymodbus
# _LOGGER.debug(f"pymodbus client version: { pymodbus.__version__ }")
# if pymodbus.__version__.startswith('3.3') or pymodbus.__version.startswith('3.0'):
#    Endian_BIG = Endian.big
#    Endian_LITTLE = Endian.little
# else:
#    Endian_BIG = Endian.BIG
#    Endian_LITTLE = Endian.LITTLE
from pymodbus.constants import Endian
from pymodbus.exceptions import ConnectionException, ModbusIOException
from .payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
from pymodbus.framer import FramerType


from .const import (
    INVERTER_IDENT,
    CONF_BAUDRATE,
    CONF_INTERFACE,
    CONF_MODBUS_ADDR,
    CONF_PLUGIN,
    CONF_READ_DCB,
    CONF_READ_EPS,
    CONF_SERIAL_PORT,
    CONF_TCP_TYPE,
    CONF_INVERTER_NAME_SUFFIX,
    CONF_CORE_HUB,
    DEFAULT_INVERTER_NAME_SUFFIX,
    DEFAULT_BAUDRATE,
    DEFAULT_INTERFACE,
    DEFAULT_MODBUS_ADDR,
    DEFAULT_NAME,
    DEFAULT_PLUGIN,
    DEFAULT_PORT,
    DEFAULT_READ_DCB,
    DEFAULT_READ_EPS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERIAL_PORT,
    DEFAULT_TCP_TYPE,
    DOMAIN,
    REGISTER_S16,
    REGISTER_S32,
    REGISTER_STR,
    REGISTER_U8H,
    REGISTER_U8L,
    REGISTER_U16,
    REGISTER_U32,
    REGISTER_F32,
    REGISTER_ULSB16MSB16,
    REGISTER_WORDS,
    SCAN_GROUP_DEFAULT,
    # PLUGIN_PATH,
    SLEEPMODE_LASTAWAKE,
    CONF_TIME_OUT,
    DEFAULT_TIME_OUT,
)

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

# seriesnumber = 'unknown'


async def config_entry_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener, called when the config entry options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass, config):
    """Set up the SolaX modbus component."""
    hass.data[DOMAIN] = {}
    _LOGGER.debug("solax data %d", hass.data)
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
    """Set up a SolaX mobus."""
    _LOGGER.debug(f"setup entries - data: {entry.data}, options: {entry.options}")
    config = entry.options
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
    """Register the hub."""
    hass.data[DOMAIN][hub._name] = {
        "hub": hub,
    }

    # Tests on some systems have shown that establishing the Modbus connection
    # can occasionally lead to errors if Home Assistant is not fully loaded.
    if hass.is_running:
        await hub.async_init()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, hub.async_init)

    entry.async_on_unload(entry.add_update_listener(config_entry_update_listener))
    return True


async def async_unload_entry(hass, entry):
    """Unload SolaX mobus entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    hass.data[DOMAIN].pop(entry.options["name"])
    return unload_ok


def defaultIsAwake(datadict):
    return True


def Gen4Timestring(numb):
    h = numb % 256
    m = numb >> 8
    return f"{h:02d}:{m:02d}"


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
        if interface == "serial":
            self._client = AsyncModbusSerialClient(
                port=serial_port,
                baudrate=baudrate,
                parity="N",
                stopbits=1,
                bytesize=8,
                timeout=time_out,
                retries=6,
            )
        elif interface == "tcp":
            if tcp_type == "rtu":
                self._client = AsyncModbusTcpClient(
                    host=host, port=port, timeout=time_out, framer=FramerType.RTU, retries=6
                )
            elif tcp_type == "ascii":
                self._client = AsyncModbusTcpClient(
                    host=host, port=port, timeout=time_out, framer=FramerType.ASCII, retries=6
                )
            else:
                self._client = AsyncModbusTcpClient(host=host, port=port, timeout=time_out, retries=6)
        self._lock = asyncio.Lock()
        self._name = name
        self.inverterNameSuffix = config.get(CONF_INVERTER_NAME_SUFFIX)
        self._modbus_addr = modbus_addr
        self._seriesnumber = "still unknown"
        self.interface = interface
        self.read_serial_port = serial_port
        self._baudrate = int(baudrate)
        self._time_out = int(time_out)
        self.groups = {}  # group info, below
        self.empty_interval_group = lambda: SimpleNamespace(interval=0, unsub_interval_method=None, device_groups={})
        self.empty_device_group = lambda: SimpleNamespace(
            sensors=[],
            inputBlocks={},
            holdingBlocks={},
            readPreparation=None,  # function to call before read group
            readFollowUp=None,  # function to call after read group
        )
        self.data = {"_repeatUntil": {}}  # _repeatuntil contains button autorepeat expiry times
        self.tmpdata = {}  # for WRITE_DATA_LOCAL entities with corresponding prevent_update number/sensor
        self.tmpdata_expiry = {}  # expiry timestamps for tempdata
        self.cyclecount = 0  # temporary - remove later
        self.slowdown = (
            1  # slow down factor when modbus is not responding: 1 : no slowdown, 10: ignore 9 out of 10 cycles
        )
        self.computedSensors = {}
        self.computedButtons = {}
        self.computedSwitches = {}
        self.sensorEntities = {}  # all sensor entities, indexed by key
        self.numberEntities = {}  # all number entities, indexed by key
        self.switchEntities = {}
        # self.preventSensors = {} # sensors with prevent_update = True
        self.writeLocals = {}  # key to description lookup dict for write_method = WRITE_DATA_LOCAL entities
        self.sleepzero = []  # sensors that will be set to zero in sleepmode
        self.sleepnone = []  # sensors that will be cleared in sleepmode
        self.writequeue = {}  # queue requests when inverter is in sleep mode
        _LOGGER.debug(f"{self.name}: ready to call plugin to determine inverter type")
        self.plugin = plugin.plugin_instance  # getPlugin(name).plugin_instance
        self.wakeupButton = None
        self._invertertype = None
        self.localsUpdated = False
        self.localsLoaded = False
        self.config = config
        self.entry = entry
        self.device_info = None

        _LOGGER.debug("solax modbushub done %s", self.__dict__)

    async def async_init(self, *args: Any) -> None:  # noqa: D102
        while self._invertertype in (None, 0):
            await self._check_connection()
            self._invertertype = await self.plugin.async_determineInverterType(self, self.config)

            if self._invertertype == 0:
                _LOGGER.info("next inverter check in 10sec")
                await asyncio.sleep(10)

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

        await self._hass.config_entries.async_forward_entry_setups(self.entry, PLATFORMS)

    # save and load local data entity values to make them persistent
    DATAFORMAT_VERSION = 1

    def saveLocalData(self):
        tosave = {"_version": self.DATAFORMAT_VERSION}
        for desc in self.writeLocals:
            tosave[desc] = self.data.get(desc)

        with open(self._hass.config.path(f"{self.name}_data.json"), "w") as fp:
            json.dump(tosave, fp)
        self.localsUpdated = False
        _LOGGER.info(f"saved modified persistent date: {tosave}")

    def loadLocalData(self):
        try:
            fp = open(self._hass.config.path(f"{self.name}_data.json"))
        except:
            if self.cyclecount > 5:
                _LOGGER.info(
                    f"no local data file found after 5 tries - is this a first time run? or didnt you modify any DATA_LOCAL entity?"
                )
                self.localsLoaded = True  # retry a couple of polling cycles - then assume non-existent"
            return
        try:
            loaded = json.load(fp)
        except:
            _LOGGER.info("Local data file not readable. Reseting to empty")
            fp.close()
            self.saveLocalData()
            return
        else:
            if loaded.get("_version") == self.DATAFORMAT_VERSION:
                for desc in self.writeLocals:
                    self.data[desc] = loaded.get(desc)
            else:
                _LOGGER.warning(f"local persistent data lost - please reinitialize {self.writeLocals.keys()}")
            fp.close()
            self.localsLoaded = True
            self.plugin.localDataCallback(self)

    # end of save and load section

    def entity_group(self, sensor):
        # scan group
        g = getattr(sensor.entity_description, "scan_group", None)
        if not g:
            g = SCAN_GROUP_DEFAULT
        # scan interval
        g = self.config.get(g, None)
        # when declared but not present in config, use default; this MUST exist
        if not g:
            g = self.config[SCAN_GROUP_DEFAULT]

        return g

    def device_group_key(self, device_info: DeviceInfo):
        key = ""
        for identifier in device_info["identifiers"]:
            if identifier[0] != DOMAIN:
                continue
            key = identifier[1] + "_" + identifier[2]

        return key

    @callback
    async def async_add_solax_modbus_sensor(self, sensor: SolaXModbusSensor):
        """Listen for data updates."""
        # This is the first sensor, set up interval.
        interval = self.entity_group(sensor)
        interval_group = self.groups.setdefault(interval, self.empty_interval_group())
        if not interval_group.device_groups:
            interval_group.interval = interval

            async def _refresh(_now: Optional[int] = None) -> None:
                await self._check_connection()
                await self.async_refresh_modbus_data(interval_group, _now)

            interval_group.unsub_interval_method = async_track_time_interval(
                self._hass, _refresh, timedelta(seconds=interval)
            )

        device_key = self.device_group_key(sensor.device_info)
        grp = interval_group.device_groups.setdefault(device_key, self.empty_device_group())
        grp.sensors.append(sensor)

    @callback
    async def async_remove_solax_modbus_sensor(self, sensor):
        """Remove data update."""
        interval = self.entity_group(sensor)
        interval_group = self.groups.get(interval, None)
        if interval_group is None:
            return

        device_key = self.device_group_key(sensor.device_info)
        grp = interval_group.device_groups.get(device_key, None)
        if grp is None:
            return

        _LOGGER.debug(f"remove sensor {sensor.entity_description.key}")
        grp.sensors.remove(sensor)

        if not grp.sensors:
            interval_group.device_groups.pop(device_key)

            if not interval_group.device_groups:
                # stop the interval timer upon removal of last device group from interval group
                interval_group.unsub_interval_method()
                interval_group.unsub_interval_method = None
                self.groups.pop(interval)

                if not self.groups:
                    await self.async_close()

    async def async_refresh_modbus_data(self, interval_group, _now: Optional[int] = None) -> None:
        """Time to update."""
        self.cyclecount = self.cyclecount + 1
        if not interval_group.device_groups:
            return

        if (self.cyclecount % self.slowdown) == 0:  # only execute once every slowdown count
            for group in interval_group.device_groups.values():
                update_result = await self.async_read_modbus_data(group)
                if update_result:
                    self.slowdown = 1  # return to full polling after succesfull cycle
                    for sensor in group.sensors:
                        sensor.modbus_data_updated()
                else:
                    _LOGGER.debug(f"assuming sleep mode - slowing down by factor 10")
                    self.slowdown = 10
                    for i in self.sleepnone:
                        self.data.pop(i, None)
                    for i in self.sleepzero:
                        self.data[i] = 0
                    # self.data = {} # invalidate data - do we want this ??

                _LOGGER.debug(f"device group read done")

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

    # async def async_connect(self):
    #    """Connect client."""
    #    _LOGGER.debug("connect modbus")
    #    if not self._client.connected:
    #        async with self._lock:
    #            await self._client.connect()

    async def _check_connection(self):
        if not self._client.connected:
            _LOGGER.info("Inverter is not connected, trying to connect")
            return await self.async_connect()

        return self._client.connected

    async def async_connect(self):
        result = False

        _LOGGER.debug(
            "Trying to connect to Inverter at %s:%s",
            self._client.comm_params.host,
            self._client.comm_params.port,
        )

        result = await self._client.connect()
        if result:
            _LOGGER.info(
                "Inverter connected at %s:%s",
                self._client.comm_params.host,
                self._client.comm_params.port,
            )
        else:
            _LOGGER.warning(
                "Unable to connect to Inverter at %s:%s",
                self._client.comm_params.host,
                self._client.comm_params.port,
            )
        return result

    async def async_read_holding_registers(self, unit, address, count):
        """Read holding registers."""
        #kwargs = {"slave": unit} if unit else {}
        async with self._lock:
            await self._check_connection()
            try:
                pdu_request = register_message.ReadHoldingRegistersRequest(address=address, count=count, dev_id=unit)
                resp = await self._client.execute(False, pdu_request)
                if resp.transaction_id!=0 and resp.dev_id != pdu_request.dev_id:
                    _LOGGER.warning("Modbus: ERROR: expected id %s but got %s, IGNORING.", pdu_request.dev_id, resp.dev_id)
                    return None
                if resp.transaction_id!=0 and pdu_request.transaction_id != resp.transaction_id:
                    _LOGGER.warning("Modbus: ERROR: expected transaction %s but got %s, IGNORING.", pdu_request.transaction_id, resp.transaction_id)
                    return None
            except ModbusException as exception_error:
                error = f"Error: device: {unit} address: {address} -> {exception_error!s}"
                _LOGGER.error(error)
                return None

        return resp

    async def async_read_input_registers(self, unit, address, count):
        """Read input registers."""
        #kwargs = {"slave": unit} if unit else {}
        async with self._lock:
            await self._check_connection()
            try:
                pdu_request = register_message.ReadInputRegistersRequest(address=address, count=count, dev_id=unit)
                resp = await self._client.execute(False, pdu_request)
                if resp.transaction_id!=0 and resp.dev_id != pdu_request.dev_id:
                    _LOGGER.warning("Modbus: ERROR: expected id %s but got %s, IGNORING.", pdu_request.dev_id, resp.dev_id)
                    return None
                if resp.transaction_id!=0 and pdu_request.transaction_id != resp.transaction_id:
                    _LOGGER.warning("Modbus: ERROR: expected transaction %s but got %s, IGNORING.", pdu_request.transaction_id, resp.transaction_id)
                    return None
            except ModbusException as exception_error:
                error = f"Error: device: {unit} address: {address} -> {exception_error!s}"
                _LOGGER.error(error)
                return None
        return resp

    async def async_lowlevel_write_register(self, unit, address, payload):
        kwargs = {"slave": unit} if unit else {}
        # builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
        builder = BinaryPayloadBuilder(byteorder=self.plugin.order16, wordorder=self.plugin.order32)
        builder.reset()
        builder.add_16bit_int(payload)
        payload = builder.to_registers()
        async with self._lock:
            await self._check_connection()
            resp = await self._client.write_register(address, payload[0], **kwargs)
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

    async def async_write_registers_single(self, unit, address, payload):  # Needs adapting for regiater que
        """Write registers multi, but write only one register of type 16bit"""
        kwargs = {"slave": unit} if unit else {}
        builder = BinaryPayloadBuilder(byteorder=self.plugin.order16, wordorder=self.plugin.order32)
        builder.reset()
        builder.add_16bit_int(payload)
        payload = builder.to_registers()
        async with self._lock:
            await self._check_connection()
            try:
                resp = await self._client.write_registers(address=address, values=payload, **kwargs)
            except (ConnectionException, ModbusIOException) as e:
                original_message = str(e)
                raise HomeAssistantError(f"Error writing single Modbus registers: {original_message}") from e
        return resp

    async def async_write_registers_multi(self, unit, address, payload):  # Needs adapting for regiater que
        """Write registers multi.
        unit is the modbus address of the device that will be writen to
        address us the start register address
        payload is a list of tuples containing
            - a select or number entity keys names or alternatively REGISTER_xx type declarations
            - the values are the values that will be encoded according to the spec of that entity
        The list of tuples will be converted to a modbus payload with the proper encoding and written
        to modbus device with address=unit
        All register descriptions referenced in the payload must be consecutive (without leaving holes)
        32bit integers will be converted to 2 modbus register values according to the endian strategy of the plugin
        """
        kwargs = {"slave": unit} if unit else {}
        builder = BinaryPayloadBuilder(byteorder=self.plugin.order16, wordorder=self.plugin.order32)
        builder.reset()
        if isinstance(payload, list):
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
                    builder.add_16bit_uint(value)
                elif typ == REGISTER_S16:
                    builder.add_16bit_int(value)
                elif typ == REGISTER_U32:
                    builder.add_32bit_uint(value)
                elif typ == REGISTER_S32:
                    builder.add_32bit_int(value)
                elif typ == REGISTER_F32:
                    builder.add_32bit_float(value)
                else:
                    _LOGGER.error(f"unsupported unit type: {typ} for {key}")
            payload = builder.to_registers()
            # for easier debugging, make next line a _LOGGER.info line
            _LOGGER.debug(f"Ready to write multiple registers at 0x{address:02x}: {payload}")
            async with self._lock:
                await self._check_connection()
                try:
                    resp = await self._client.write_registers(address=address, values=payload, **kwargs)
                except (ConnectionException, ModbusIOException) as e:
                    original_message = str(e)
                    raise HomeAssistantError(f"Error writing multiple Modbus registers: {original_message}") from e
            return resp
        else:
            _LOGGER.error(f"write_registers_multi expects a list of tuples 0x{address:02x} payload: {payload}")
            return None

    async def async_read_modbus_data(self, group):
        res = True
        try:
            res = await self.async_read_modbus_registers_all(group)
        except ConnectionException as ex:
            _LOGGER.error("Reading data failed! Inverter is offline.")
            res = False
        except ModbusIOException as ex:
            _LOGGER.error(f"ModbusIOError: {ex}")
            res = False
        except Exception as ex:
            _LOGGER.exception("Something went wrong reading from modbus")
            res = False
        return res

    def treat_address(self, data, decoder, descr, initval=0):
        return_value = None
        val = None
        if self.cyclecount < 5:
            _LOGGER.debug(f"treating register 0x{descr.register:02x} : {descr.key}")
        try:
            if descr.unit == REGISTER_U16:
                val = decoder.decode_16bit_uint()
            elif descr.unit == REGISTER_S16:
                val = decoder.decode_16bit_int()
            elif descr.unit == REGISTER_U32:
                val = decoder.decode_32bit_uint()
            elif descr.unit == REGISTER_F32:
                val = decoder.decode_32bit_float()
            elif descr.unit == REGISTER_S32:
                val = decoder.decode_32bit_int()
            elif descr.unit == REGISTER_STR:
                val = str(decoder.decode_string(descr.wordcount * 2).decode("ascii"))
            elif descr.unit == REGISTER_WORDS:
                val = [decoder.decode_16bit_uint() for val in range(descr.wordcount)]
            elif descr.unit == REGISTER_ULSB16MSB16:
                val = decoder.decode_16bit_uint() + decoder.decode_16bit_uint() * 256 * 256
            elif descr.unit == REGISTER_U8L:
                val = initval % 256
            elif descr.unit == REGISTER_U8H:
                val = initval >> 8
            else:
                _LOGGER.warning(f"undefinded unit for entity {descr.key} - setting value to zero")
                val = 0
        except Exception as ex:
            if self.cyclecount < 5:
                _LOGGER.warning(
                    f"{self.name}: read failed at 0x{descr.register:02x}: {descr.key}",
                    exc_info=True,
                )
            else:
                _LOGGER.warning(f"{self.name}: read failed at 0x{descr.register:02x}: {descr.key} ")
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

        if val == None:  # E.g. if errors have occurred during readout
            return_value = None
        elif type(descr.scale) is dict:  # translate int to string
            return_value = descr.scale.get(val, "Unknown")
        elif callable(descr.scale):  # function to call ?
            return_value = descr.scale(val, descr, data)
        else:  # apply simple numeric scaling and rounding if not a list of words
            try:
                return_value = round(val * descr.scale, descr.rounding)
            except:
                return_value = val  # probably a REGISTER_WORDS instance
        # if (descr.sleepmode != SLEEPMODE_LASTAWAKE) or self.awakeplugin(self.data): self.data[descr.key] = return_value
        if (self.tmpdata_expiry.get(descr.key, 0) == 0) and (
            (descr.sleepmode != SLEEPMODE_LASTAWAKE) or self.plugin.isAwake(self.data)
        ):
            data[descr.key] = return_value  # case prevent_update number

    async def async_read_modbus_block(self, data, block, typ):
        errmsg = None
        if self.cyclecount < 5:
            _LOGGER.debug(
                f"{self.name} modbus {typ} block start: 0x{block.start:x} end: 0x{block.end:x}  len: {block.end - block.start} \nregs: {block.regs}"
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
        else:
            if realtime_data is None or realtime_data.isError():
                errmsg = f"read_error "
        if errmsg == None:
            decoder = BinaryPayloadDecoder.fromRegisters(
                realtime_data.registers,
                self.plugin.order16,
                wordorder=self.plugin.order32,
            )
            # decoder = self._client.convert_from_registers(
            #    registers=realtime_data.registers,
            #    data_type=client.DATATYPE.INT16,
            #    word_order=self.plugin.order32
            # )
            prevreg = block.start
            for reg in block.regs:
                if (reg - prevreg) > 0:
                    decoder.skip_bytes((reg - prevreg) * 2)
                    if self.cyclecount < 5:
                        _LOGGER.debug(f"skipping bytes {(reg-prevreg) * 2}")
                descr = block.descriptions[reg]
                if type(descr) is dict:  #  set of byte values
                    val = decoder.decode_16bit_uint()
                    for k in descr:
                        self.treat_address(data, decoder, descr[k], val)
                    prevreg = reg + 1
                else:  # single value
                    self.treat_address(data, decoder, descr)
                    if descr.unit in (
                        REGISTER_S32,
                        REGISTER_U32,
                        REGISTER_F32,
                        REGISTER_ULSB16MSB16,
                    ):
                        prevreg = reg + 2
                    elif descr.unit in (
                        REGISTER_STR,
                        REGISTER_WORDS,
                    ):
                        prevreg = reg + descr.wordcount
                    else:
                        prevreg = reg + 1
            return True
        else:  # block read failure
            firstdescr = block.descriptions[block.start]  # check only first item in block
            if firstdescr.ignore_readerror != False:  # ignore block read errors and return static data
                for reg in block.regs:
                    descr = block.descriptions[reg]
                    if not (type(descr) is dict):
                        if (descr.ignore_readerror != True) and (descr.ignore_readerror != False):
                            data[descr.key] = descr.ignore_readerror  # return something static
                return True
            else:
                if self.slowdown == 1:
                    _LOGGER.info(
                        f"{errmsg}: {self.name} cannot read {typ} registers at device {self._modbus_addr} position 0x{block.start:x}",
                        exc_info=True,
                    )
                return False

    async def async_read_modbus_registers_all(self, group):
        if group.readPreparation is not None:
            if not await group.readPreparation(self.data):
                _LOGGER.info(f"device group read cancel")
                return True
        else:
            _LOGGER.debug(f"device group inverter")

        data = {"_repeatUntil": self.data["_repeatUntil"]}
        res = True
        for block in group.holdingBlocks:
            res = res and await self.async_read_modbus_block(data, block, "holding")
        for block in group.inputBlocks:
            res = res and await self.async_read_modbus_block(data, block, "input")

        if self.localsUpdated:
            await self._hass.async_add_executor_job(self.saveLocalData)
            self.plugin.localDataCallback(self)
        if not self.localsLoaded:
            await self._hass.async_add_executor_job(self.loadLocalData)
        for reg in self.computedSensors:
            descr = self.computedSensors[reg]
            data[descr.key] = descr.value_function(0, descr, data)

        if group.readFollowUp is not None:
            if not await group.readFollowUp(self.data, data):
                _LOGGER.warning(f"device group check not success")
                return True

        for key, value in data.items():
            self.data[key] = value

        if res and self.writequeue and self.plugin.isAwake(self.data):  # self.awakeplugin(self.data):
            # process outstanding write requests
            _LOGGER.info(f"inverter is now awake, processing outstanding write requests {self.writequeue}")
            for addr in self.writequeue.keys():
                val = self.writequeue.get(addr)
                await self.async_write_register(self._modbus_addr, addr, val)
            self.writequeue = {}  # make sure we do not write multiple times
        self.last_ts = time()
        for (
            k,
            v,
        ) in self.data["_repeatUntil"].items():
            if self.last_ts < v:
                buttondescr = self.computedButtons[k]
                payload = buttondescr.value_function(0, buttondescr, self.data)
                _LOGGER.debug(f"ready to repeat button {k} data: {payload}")
                await self.async_write_registers_multi(
                    unit=self._modbus_addr,
                    address=buttondescr.register,
                    payload=payload,
                )
        return res


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
        _LOGGER.info("Inverter is not connected, trying to connect")
        return await self.async_connect(hub)

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
                        _LOGGER.info(
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
                        # upbdate weak reference handle to refere to
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
        kwargs = {"slave": unit} if unit else {}
        async with self._lock:
            hub = await self._check_connection()
        try:
            if hub._config_delay:
                return None
            async with hub._lock:
                try:
                    resp = await hub._client.read_holding_registers(address=address, count=count, **kwargs)
                except (ConnectionException, ModbusIOException) as e:
                    original_message = str(e)
                    raise HomeAssistantError(f"Error reading Modbus holding registers: {original_message}") from e
            return resp
        except (TypeError, AttributeError) as e:
            raise HomeAssistantError(f"Error reading Modbus holding registers: core modbus access failed") from e

    async def async_read_input_registers(self, unit, address, count):
        """Read input registers."""
        kwargs = {"slave": unit} if unit else {}
        async with self._lock:
            hub = await self._check_connection()
        try:
            if hub._config_delay:
                return None
            async with hub._lock:
                try:
                    resp = await hub._client.read_input_registers(address=address, count=count, **kwargs)
                except (ConnectionException, ModbusIOException) as e:
                    original_message = str(e)
                    raise HomeAssistantError(f"Error reading Modbus input registers: {original_message}") from e
        except (TypeError, AttributeError) as e:
            raise HomeAssistantError(f"Error reading Modbus input registers: core modbus access failed") from e
        return resp

    async def async_lowlevel_write_register(self, unit, address, payload):
        # builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
        builder = BinaryPayloadBuilder(byteorder=self.plugin.order16, wordorder=self.plugin.order32)
        builder.reset()
        builder.add_16bit_int(payload)
        payload = builder.to_registers()
        kwargs = {"slave": unit} if unit else {}
        async with self._lock:
            hub = await self._check_connection()
        try:
            if hub._config_delay:
                return None
            async with hub._lock:
                try:
                    resp = await self._client.write_register(address=address, values=payload[0], **kwargs)
                except (ConnectionException, ModbusIOException) as e:
                    original_message = str(e)
                    raise HomeAssistantError(f"Error writing single Modbus register: {original_message}") from e
            return resp
        except (TypeError, AttributeError) as e:
            raise HomeAssistantError(f"Error writing single Modbus input register: core modbus access failed") from e

    async def async_write_registers_single(self, unit, address, payload):  # Needs adapting for regiater que
        """Write registers multi, but write only one register of type 16bit"""
        builder = BinaryPayloadBuilder(byteorder=self.plugin.order16, wordorder=self.plugin.order32)
        builder.reset()
        builder.add_16bit_int(payload)
        payload = builder.to_registers()
        kwargs = {"slave": unit} if unit else {}
        async with self._lock:
            hub = await self._check_connection()
        try:
            if hub._config_delay:
                return None
            async with hub._lock:
                try:
                    resp = await self._client.write_registers(address=address, values=payload, **kwargs)
                except (ConnectionException, ModbusIOException) as e:
                    original_message = str(e)
                    raise HomeAssistantError(f"Error writing single Modbus registers: {original_message}") from e

            return resp
        except (TypeError, AttributeError) as e:
            raise HomeAssistantError(f"Error writing single Modbus Modbus registers: core modbus access failed") from e

    async def async_write_registers_multi(self, unit, address, payload):  # Needs adapting for regiater que
        """Write registers multi.
        unit is the modbus address of the device that will be writen to
        address us the start register address
        payload is a list of tuples containing
            - a select or number entity keys names or alternatively REGISTER_xx type declarations
            - the values are the values that will be encoded according to the spec of that entity
        The list of tuples will be converted to a modbus payload with the proper encoding and written
        to modbus device with address=unit
        All register descriptions referenced in the payload must be consecutive (without leaving holes)
        32bit integers will be converted to 2 modbus register values according to the endian strategy of the plugin
        """
        kwargs = {"slave": unit} if unit else {}
        builder = BinaryPayloadBuilder(byteorder=self.plugin.order16, wordorder=self.plugin.order32)
        builder.reset()
        if isinstance(payload, list):
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
                    builder.add_16bit_uint(value)
                elif typ == REGISTER_S16:
                    builder.add_16bit_int(value)
                elif typ == REGISTER_U32:
                    builder.add_32bit_uint(value)
                elif typ == REGISTER_F32:
                    builder.add_32bit_float(value)
                elif typ == REGISTER_S32:
                    builder.add_32bit_int(value)
                else:
                    _LOGGER.error(f"unsupported unit type: {typ} for {key}")
            payload = builder.to_registers()
            # for easier debugging, make next line a _LOGGER.info line
            _LOGGER.debug(f"Ready to write multiple registers at 0x{address:02x}: {payload}")
            async with self._lock:
                hub = await self._check_connection()
            try:
                if hub._config_delay:
                    return None
                async with hub._lock:
                    try:
                        resp = await self._client.write_registers(address=address, values=payload, **kwargs)
                    except (ConnectionException, ModbusIOException) as e:
                        original_message = str(e)
                        raise HomeAssistantError(f"Error writing multiple Modbus registers: {original_message}") from e
                return resp
            except (TypeError, AttributeError) as e:
                raise HomeAssistantError(
                    f"Error writing single Modbus Modbus registers: core modbus access failed"
                ) from e
        else:
            _LOGGER.error(f"write_registers_multi expects a list of tuples 0x{address:02x} payload: {payload}")
        return None
