"""The SolaX Modbus Integration."""
import asyncio
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional
#import importlib.util, sys
import importlib
from time import time
import json
import aiohttp

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.components.button import ButtonEntity

_LOGGER = logging.getLogger(__name__)
#try: # pymodbus 3.0.x
from pymodbus.client import ModbusTcpClient, ModbusSerialClient
from pymodbus.pdu import ModbusResponse
#    UNIT_OR_SLAVE = 'slave'
#    _LOGGER.warning("using pymodbus library 3.x")
#except: # pymodbus 2.5.3
#    from pymodbus.client.sync import ModbusTcpClient, ModbusSerialClient
#    UNIT_OR_SLAVE = 'unit'
#    _LOGGER.warning("using pymodbus library 2.x")
#import pymodbus
#_LOGGER.debug(f"pymodbus client version: { pymodbus.__version__ }")
#if pymodbus.__version__.startswith('3.3') or pymodbus.__version.startswith('3.0'):
#    Endian_BIG = Endian.big
#    Endian_LITTLE = Endian.little
#else:
#    Endian_BIG = Endian.BIG
#    Endian_LITTLE = Endian.LITTLE
from pymodbus.constants import Endian
from pymodbus.exceptions import ConnectionException
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
from pymodbus.transaction import ModbusRtuFramer, ModbusAsciiFramer

from .const import (
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    DEFAULT_TCP_TYPE,
    CONF_TCP_TYPE,
    CONF_MODBUS_ADDR,
    CONF_INTERFACE,
    CONF_SERIAL_PORT,
    CONF_READ_EPS,
    CONF_READ_DCB,
    CONF_BAUDRATE,
    CONF_PLUGIN,
    CONF_SN,
    DEFAULT_READ_EPS,
    DEFAULT_READ_DCB,
    DEFAULT_INTERFACE,
    DEFAULT_SERIAL_PORT,
    DEFAULT_MODBUS_ADDR,
    DEFAULT_PORT,
    DEFAULT_BAUDRATE,
    DEFAULT_PLUGIN,
    #PLUGIN_PATH,
    SLEEPMODE_LASTAWAKE,
)
from .const import REGISTER_S32, REGISTER_U32, REGISTER_U16, REGISTER_S16, REGISTER_ULSB16MSB16, REGISTER_STR, REGISTER_WORDS, REGISTER_U8H, REGISTER_U8L


PLATFORMS = ["button", "number", "select", "sensor"]

#seriesnumber = 'unknown'


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up a SolaX mobus."""
    _LOGGER.debug(f"setup entries - data: {entry.data}, options: {entry.options}")
    config = entry.options
    name = config[CONF_NAME]
    plugin_name = config[CONF_PLUGIN]

    # convert old style to new style plugin name here - Remove later after a breaking upgrade
    if plugin_name.startswith("custom_components") or plugin_name.startswith("/config") or plugin_name.startswith("plugin_"):
        new = {**config}
        plugin_name = plugin_name.split('plugin_', 1)[1][:-3]
        _LOGGER.warning(f"converting old style plugin name {config[CONF_PLUGIN]} to new style short name {plugin_name}")
        new[CONF_PLUGIN] = plugin_name
        hass.config_entries.async_update_entry(entry, options=new)
    # end of conversion

    # ================== dynamically load desired plugin =======================================================
    _LOGGER.info(f"trying to load plugin - plugin_name: {plugin_name}")
    plugin = importlib.import_module(f".plugin_{plugin_name}", 'custom_components.solax_modbus')
    if not plugin: _LOGGER.error(f"could not import plugin with name: {plugin_name}")
    # ====================== end of dynamic load ==============================================================

    host = config.get(CONF_HOST, None)
    port = config.get(CONF_PORT, DEFAULT_PORT)
    tcp_type = config.get(CONF_TCP_TYPE, DEFAULT_TCP_TYPE)
    modbus_addr = config.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    if modbus_addr == None:
        modbus_addr = DEFAULT_MODBUS_ADDR
        _LOGGER.warning(f"{name} integration may need to be reconfigured for this version; using default Solax modbus_address {modbus_addr}")
    interface = config.get(CONF_INTERFACE, None)
    if not interface: # legacy parameter name was read_serial, this block can be removed later
        if config.get("read_serial", False): interface = "serial"
        else: interface = "tcp"
    serial_port = config.get(CONF_SERIAL_PORT, DEFAULT_SERIAL_PORT)
    baudrate = int(config.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
    scan_interval = config[CONF_SCAN_INTERVAL]
    _LOGGER.debug(f"Setup {DOMAIN}.{name}")
    _LOGGER.debug(f"solax serial port {serial_port} interface {interface}")

    if tcp_type == "http":
        hub = SolaXHttpHub(hass, name, host, scan_interval, plugin, config)
        await hub.init()
    else:
        hub = SolaXModbusHub(hass, name, host, port, tcp_type, modbus_addr, interface, serial_port, baudrate, scan_interval, plugin, config)
    """Register the hub."""
    hass.data[DOMAIN][name] = { "hub": hub,  }

    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )
    entry.async_on_unload(entry.add_update_listener(config_entry_update_listener))
    return True


async def async_unload_entry(hass, entry):
    """Unload SolaX mobus entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if not unload_ok: return False

    hass.data[DOMAIN].pop(entry.data.get("name", None), None ) , # for legacy compatibility, this line can be removed later
    hass.data[DOMAIN].pop(entry.options["name"])
    return True

def defaultIsAwake( datadict):
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
        name,
        host,
        port,
        tcp_type,
        modbus_addr,
        interface,
        serial_port,
        baudrate,
        scan_interval,
        plugin,
        config
    ):
        """Initialize the Modbus hub."""
        _LOGGER.debug(f"solax modbushub creation with interface {interface} baudrate (only for serial): {baudrate}")
        self._hass = hass
        if (interface == "serial"):
            self._client = ModbusSerialClient(method="rtu", port=serial_port, baudrate=baudrate, parity='N', stopbits=1, bytesize=8, timeout=3)
        else:
            if tcp_type == "rtu":
                self._client = ModbusTcpClient(host=host, port=port, timeout=5, framer=ModbusRtuFramer)
            elif tcp_type == "ascii":
                self._client = ModbusTcpClient(host=host, port=port, timeout=5, framer=ModbusAsciiFramer)
            else:
                self._client = ModbusTcpClient(host=host, port=port, timeout=5)
        self._lock = threading.Lock()
        self._name = name
        self._modbus_addr = modbus_addr
        self._seriesnumber = 'still unknown'
        self.interface = interface
        self.read_serial_port = serial_port
        self._baudrate = int(baudrate)
        self._scan_interval = timedelta(seconds=scan_interval)
        self._unsub_interval_method = None
        self._sensor_callbacks = []
        self.data = { "_repeatUntil": {}} # _repeatuntil contains button autorepeat expiry times
        self.tmpdata = {} # for WRITE_DATA_LOCAL entities with corresponding prevent_update number/sensor
        self.tmpdata_expiry = {} # expiry timestamps for tempdata
        self.cyclecount = 0 # temporary - remove later
        self.slowdown = 1 # slow down factor when modbus is not responding: 1 : no slowdown, 10: ignore 9 out of 10 cycles
        self.inputBlocks = {}
        self.holdingBlocks = {}
        self.computedSensors = {}
        self.computedButtons = {}
        self.sensorEntities = {} # all sensor entities, indexed by key
        self.numberEntities = {} # all number entities, indexed by key
        #self.preventSensors = {} # sensors with prevent_update = True
        self.writeLocals = {} # key to description lookup dict for write_method = WRITE_DATA_LOCAL entities
        self.sleepzero = [] # sensors that will be set to zero in sleepmode
        self.sleepnone = [] # sensors that will be cleared in sleepmode
        self.writequeue = {} # queue requests when inverter is in sleep mode
        _LOGGER.debug(f"{self.name}: ready to call plugin to determine inverter type")
        self.plugin = plugin.plugin_instance #getPlugin(name).plugin_instance
        self.wakeupButton = None
        self._invertertype = self.plugin.determineInverterType(self, config)
        self._lastts = 0  # timestamp of last polling cycle
        self.localsUpdated = False
        self.localsLoaded = False
        _LOGGER.debug("solax modbushub done %s", self.__dict__)


    # save and load local data entity values to make them persistent
    DATAFORMAT_VERSION = 1

    def saveLocalData(self):
        tosave = { '_version': self.DATAFORMAT_VERSION }
        for desc in self.writeLocals:  tosave[desc] = self.data.get(desc)
        with open(self._hass.config.path(f'{self.name}_data.json'), 'w') as fp: json.dump(tosave, fp)
        self.localsUpdated = False
        _LOGGER.info(f"saved modified persistent date: {tosave}")

    def loadLocalData(self):
        try: fp = open(self._hass.config.path(f'{self.name}_data.json'))
        except:
            if self.cyclecount > 5:
                _LOGGER.info(f"no local data file found after 5 tries - is this a first time run? or didnt you modify any DATA_LOCAL entity?")
                self.localsLoaded=True  # retry a couple of polling cycles - then assume non-existent"
        else:
            loaded = json.load(fp)
            if loaded.get('_version') == self.DATAFORMAT_VERSION:
                for desc in self.writeLocals: self.data[desc] = loaded.get(desc)
            else: _LOGGER.warning(f"local persistent data lost - please reinitialize {self.writeLocals.keys()}")
            fp.close()
            self.localsLoaded = True
            self.plugin.localDataCallback(self)

    # end of save and load section

    @callback
    def async_add_solax_modbus_sensor(self, update_callback):
        """Listen for data updates."""
        # This is the first sensor, set up interval.
        if not self._sensor_callbacks:
            self.connect()
            self._unsub_interval_method = async_track_time_interval(
                self._hass, self.async_refresh_modbus_data, self._scan_interval
            )
        self._sensor_callbacks.append(update_callback)


    @callback
    def async_remove_solax_modbus_sensor(self, update_callback):
        """Remove data update."""
        self._sensor_callbacks.remove(update_callback)

        if not self._sensor_callbacks:
            """stop the interval timer upon removal of last sensor"""
            self._unsub_interval_method()
            self._unsub_interval_method = None
            self.close()

    async def async_refresh_modbus_data(self, _now: Optional[int] = None) -> None:
        """Time to update."""
        self.cyclecount = self.cyclecount+1
        if not self._sensor_callbacks:
            return
        if (self.cyclecount % self.slowdown) == 0: # only execute once every slowdown count
            update_result = self.read_modbus_data()
            if update_result:
                self.slowdown = 1 # return to full polling after succesfull cycle
                for update_callback in self._sensor_callbacks:
                    update_callback()
            else:
                _LOGGER.debug(f"assuming sleep mode - slowing down by factor 10")
                self.slowdown = 10
                for i in self.sleepnone: self.data.pop(i, None)
                for i in self.sleepzero: self.data[i] = 0
                # self.data = {} # invalidate data - do we want this ??

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

    def close(self):
        """Disconnect client."""
        with self._lock:
            self._client.close()

    def connect(self):
        """Connect client."""
        with self._lock:
            self._client.connect()


    def read_holding_registers(self, unit, address, count):
        """Read holding registers."""
        with self._lock:
            kwargs = {'slave': unit} if unit else {}
            return self._client.read_holding_registers(address, count, **kwargs)

    def read_input_registers(self, unit, address, count):
        """Read input registers."""
        with self._lock:
            kwargs = {'slave': unit} if unit else {}
            return self._client.read_input_registers(address, count, **kwargs)

    def _lowlevel_write_register(self, unit, address, payload):
        with self._lock:
            kwargs = {'slave': unit} if unit else {}
            #builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
            builder = BinaryPayloadBuilder(byteorder=self.plugin.order16, wordorder=self.plugin.order32)
            builder.reset()
            builder.add_16bit_int(payload)
            payload = builder.to_registers()
            return self._client.write_register(address, payload[0], **kwargs)

    def write_register(self, unit, address, payload):
        """Write register."""
        #awake = self.awakeplugin(self.data)
        awake = self.plugin.isAwake(self.data)
        if awake: return self._lowlevel_write_register(unit, address, payload)
        else:
            # try to write anyway - could be a command that inverter responds to while asleep
            res = self._lowlevel_write_register(unit, address, payload)
            # put request in queue, in order to repeat it when inverter wakes up
            self.writequeue[address] = payload
            # wake up inverter
            if self.wakeupButton:
                _LOGGER.info("waking up inverter: pressing awake button")
                return self._lowlevel_write_register(unit=self._modbus_addr, address=self.wakeupButton.register, payload=self.wakeupButton.command)
            else: _LOGGER.warning("cannot wakeup inverter: no awake button found")
            return res

    def write_registers_single(self, unit, address, payload): # Needs adapting for regiater que
        """Write registers multi, but write only one register of type 16bit"""
        with self._lock:
            kwargs = {'slave': unit} if unit else {}
            builder = BinaryPayloadBuilder(byteorder=self.plugin.order16, wordorder=self.plugin.order32)
            builder.reset()
            builder.add_16bit_int(payload)
            payload = builder.to_registers()
            return self._client.write_registers(address, payload, **kwargs)

    def write_registers_multi(self, unit, address, payload): # Needs adapting for regiater que
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
        with self._lock:
            kwargs = {'slave': unit} if unit else {}
            builder = BinaryPayloadBuilder(byteorder=self.plugin.order16, wordorder=self.plugin.order32)
            builder.reset()
            if isinstance(payload, list):
                for (key, value,) in payload:
                    if key.startswith("_"):
                        typ = key
                        value = int(value)
                    else:
                        descr = self.writeLocals[key]
                        if hasattr(descr, 'reverse_option_dict'): value = descr.reverse_option_dict[value] # string to int
                        elif callable(descr.scale):  # function to call ?
                            value = descr.scale(value, descr, self.data)
                        else: # apply simple numeric scaling and rounding if not a list of words
                            try:    value = value*descr.scale
                            except: _LOGGER.error(f"cannot treat payload scale {value} {descr}")
                        value = int(value)
                        typ = descr.unit
                    if   typ == REGISTER_U16: builder.add_16bit_uint(value)
                    elif typ == REGISTER_S16: builder.add_16bit_int(value)
                    elif typ == REGISTER_U32: builder.add_32bit_uint(value)
                    elif typ == REGISTER_S32: builder.add_32bit_int(value)
                    else: _LOGGER.error(f"unsupported unit type: {typ} for {key}")
                payload = builder.to_registers()
                # for easier debugging, make next line a _LOGGER.info line
                _LOGGER.debug(f"Ready to write multiple registers at 0x{address:02x}: {payload}")
                return self._client.write_registers(address, payload, **kwargs)
            else:
                _LOGGER.error(f"write_registers_multi expects a list of tuples 0x{address:02x} payload: {payload}")
                return None

    def read_modbus_data(self):
        res = True
        try:
            res = self.read_modbus_registers_all()
        except ConnectionException as ex:
            _LOGGER.error("Reading data failed! Inverter is offline.")
            res = False
        except Exception as ex:
            _LOGGER.exception("Something went wrong reading from modbus")
            res = False
        return res


    def treat_address(self, decoder, descr, initval=0):
        return_value = None
        val = None
        if self.cyclecount <5: _LOGGER.debug(f"treating register 0x{descr.register:02x} : {descr.key}")
        try:
            if   descr.unit == REGISTER_U16: val = decoder.decode_16bit_uint()
            elif descr.unit == REGISTER_S16: val = decoder.decode_16bit_int()
            elif descr.unit == REGISTER_U32: val = decoder.decode_32bit_uint()
            elif descr.unit == REGISTER_S32: val = decoder.decode_32bit_int()
            elif descr.unit == REGISTER_STR: val = str( decoder.decode_string(descr.wordcount*2).decode("ascii") )
            elif descr.unit == REGISTER_WORDS: val = [decoder.decode_16bit_uint() for val in range(descr.wordcount) ]
            elif descr.unit == REGISTER_ULSB16MSB16: val = decoder.decode_16bit_uint() + decoder.decode_16bit_uint()*256*256
            elif descr.unit == REGISTER_U8L: val = initval % 256
            elif descr.unit == REGISTER_U8H: val = initval >> 8
            else:
                _LOGGER.warning(f"undefinded unit for entity {descr.key} - setting value to zero")
                val = 0
        except Exception as ex:
            if self.cyclecount < 5: _LOGGER.warning(f"{self.name}: read failed at 0x{descr.register:02x}: {descr.key}", exc_info=True)
            else: _LOGGER.warning(f"{self.name}: read failed at 0x{descr.register:02x}: {descr.key} ")
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
        elif type(descr.scale) is dict: # translate int to string
            return_value = descr.scale.get(val, "Unknown")
        elif callable(descr.scale):  # function to call ?
            return_value = descr.scale(val, descr, self.data)
        else: # apply simple numeric scaling and rounding if not a list of words
            try:    return_value = round(val*descr.scale, descr.rounding)
            except: return_value = val # probably a REGISTER_WORDS instance
        #if (descr.sleepmode != SLEEPMODE_LASTAWAKE) or self.awakeplugin(self.data): self.data[descr.key] = return_value
        if (self.tmpdata_expiry.get(descr.key,0) == 0) and ((descr.sleepmode != SLEEPMODE_LASTAWAKE) or self.plugin.isAwake(self.data)):
            self.data[descr.key] = return_value # case prevent_update number


    def read_modbus_block(self, block, typ):
        errmsg = None
        if self.cyclecount <5:
            _LOGGER.debug(f"{self.name} modbus {typ} block start: 0x{block.start:x} end: 0x{block.end:x}  len: {block.end - block.start} \nregs: {block.regs}")
        try:
            if typ == 'input': realtime_data = self.read_input_registers(unit=self._modbus_addr, address=block.start, count=block.end - block.start)
            else:              realtime_data = self.read_holding_registers(unit=self._modbus_addr, address=block.start, count=block.end - block.start)
        except Exception as ex:
            errmsg = f"exception {str(ex)} "
        else:
            if realtime_data.isError(): errmsg = f"read_error "
        if errmsg == None:
            decoder = BinaryPayloadDecoder.fromRegisters(realtime_data.registers, self.plugin.order16, wordorder=self.plugin.order32)
            prevreg = block.start
            for reg in block.regs:
                if (reg - prevreg) > 0:
                    decoder.skip_bytes((reg-prevreg) * 2)
                    if self.cyclecount < 5: _LOGGER.debug(f"skipping bytes {(reg-prevreg) * 2}")
                descr = block.descriptions[reg]
                if type(descr) is dict: #  set of byte values
                    val = decoder.decode_16bit_uint()
                    for k in descr: self.treat_address(decoder, descr[k], val)
                    prevreg = reg + 1
                else: # single value
                    self.treat_address(decoder, descr)
                    if descr.unit in (REGISTER_S32, REGISTER_U32, REGISTER_ULSB16MSB16,): prevreg = reg + 2
                    elif descr.unit in (REGISTER_STR, REGISTER_WORDS,): prevreg = reg + descr.wordcount
                    else: prevreg = reg+1
            return True
        else: #block read failure
            firstdescr = block.descriptions[block.start] # check only first item in block
            if firstdescr.ignore_readerror != False:  # ignore block read errors and return static data
                for reg in block.regs:
                    descr = block.descriptions[reg]
                    if not (type(descr) is dict):
                        if ((descr.ignore_readerror != True) and (descr.ignore_readerror !=False)) : self.data[descr.key] = descr.ignore_readerror # return something static
                return True
            else:
                if self.slowdown == 1: _LOGGER.info(f"{errmsg}: {self.name} cannot read {typ} registers at device {self._modbus_addr} position 0x{block.start:x}", exc_info=True)
                return False

    def read_modbus_registers_all(self):
        res = True
        for block in self.holdingBlocks:
            res = res and self.read_modbus_block(block, 'holding')
        for block in self.inputBlocks:
            res = res and self.read_modbus_block(block, 'input')
        if self.localsUpdated:
            self.saveLocalData()
            self.plugin.localDataCallback(self)
        if not self.localsLoaded: self.loadLocalData()
        for reg in self.computedSensors:
            descr = self.computedSensors[reg]
            self.data[descr.key] = descr.value_function(0, descr, self.data )

        if res and self.writequeue and self.plugin.isAwake(self.data): #self.awakeplugin(self.data):
            # process outstanding write requests
            _LOGGER.info(f"inverter is now awake, processing outstanding write requests {self.writequeue}")
            for addr in self.writequeue.keys():
                val = self.writequeue.get(addr)
                self.write_register(self._modbus_addr, addr, val)
            self.writequeue = {} # make sure we do not write multiple times
        self.last_ts = time()
        for (k,v,) in self.data['_repeatUntil'].items():
            if self.last_ts < v:
                buttondescr = self.computedButtons[k]
                payload = buttondescr.value_function(0, buttondescr, self.data)
                _LOGGER.debug(f"ready to repeat button {k} data: {payload}")
                self.write_registers_multi(unit=self._modbus_addr, address=buttondescr.register, payload=payload)
        return res

class SolaXHttpHub:
    """Wrapper for http SolaX API """

    def __init__(
        self,
        hass,
        name,
        host,
        scan_interval,
        plugin,
        config
    ):
        """Initialize the Http hub."""
        _LOGGER.debug(f"solax httphub creation.")
        self._hass = hass
        self._name = name
        self._host = host
        self._modbus_addr = 1
        self._seriesnumber = 'still unknown'
        self._scan_interval = timedelta(seconds=scan_interval)
        self._unsub_interval_method = None
        self._sensor_callbacks = []
        self.data = { "_repeatUntil": {}} # _repeatuntil contains button autorepeat expiry times
        self.tmpdata = {} # for WRITE_DATA_LOCAL entities with corresponding prevent_update number/sensor
        self.tmpdata_expiry = {} # expiry timestamps for tempdata
        self.cyclecount = 0 # temporary - remove later
        self.slowdown = 1 # slow down factor when modbus is not responding: 1 : no slowdown, 10: ignore 9 out of 10 cycles
        self.inputBlocks = {}
        self.holdingBlocks = {}
        self.computedSensors = {}
        self.computedButtons = {}
        self.sensorEntities = {} # all sensor entities, indexed by key
        self.numberEntities = {} # all number entities, indexed by key
        #self.preventSensors = {} # sensors with prevent_update = True
        self.writeLocals = {} # key to description lookup dict for write_method = WRITE_DATA_LOCAL entities
        self.sleepzero = [] # sensors that will be set to zero in sleepmode
        self.sleepnone = [] # sensors that will be cleared in sleepmode
        _LOGGER.debug(f"{self.name}: ready to call plugin to determine inverter type")
        self.plugin = plugin.plugin_instance #getPlugin(name).plugin_instance
        self.wakeupButton = None
        self._invertertype = None
        self._lastts = 0  # timestamp of last polling cycle
        self._sn = config[CONF_SN]
        self._typeCode=None
        self._config = config
        self.localsUpdated = False
        self.localsLoaded = False
        _LOGGER.debug("solax modbushub done %s", self.__dict__)

    async def init(self):
        httpData=await self._read_realtime_data()
        self._typeCode=httpData['Information'][2]
        if self._invertertype == None:
            self._invertertype = self.plugin.determineInverterType(self, self._config)

    # save and load local data entity values to make them persistent
    DATAFORMAT_VERSION = 1

    def _saveLocalData(self):
        tosave = { '_version': self.DATAFORMAT_VERSION }
        for desc in self.writeLocals:  tosave[desc] = self.data.get(desc)
        with open(self._hass.config.path(f'{self.name}_data.json'), 'w') as fp: json.dump(tosave, fp)
        self.localsUpdated = False
        _LOGGER.info(f"saved modified persistent date: {tosave}")

    def loadLocalData(self):
        try: fp = open(self._hass.config.path(f'{self.name}_data.json'))
        except:
            if self.cyclecount > 5:
                _LOGGER.info(f"no local data file found after 5 tries - is this a first time run? or didnt you modify any DATA_LOCAL entity?")
                self.localsLoaded=True  # retry a couple of polling cycles - then assume non-existent"
        else:
            loaded = json.load(fp)
            if loaded.get('_version') == self.DATAFORMAT_VERSION:
                for desc in self.writeLocals: self.data[desc] = loaded.get(desc)
            else: _LOGGER.warning(f"local persistent data lost - please reinitialize {self.writeLocals.keys()}")
            fp.close()
            self.localsLoaded = True
            self.plugin.localDataCallback(self)

    # end of save and load section

    @callback
    def async_add_solax_modbus_sensor(self, update_callback):
        """Listen for data updates."""
        # This is the first sensor, set up interval.
        if not self._sensor_callbacks:
            self.connect()
            self._unsub_interval_method = async_track_time_interval(
                self._hass, self._async_refresh_http_data, self._scan_interval
            )
        self._sensor_callbacks.append(update_callback)


    @callback
    def async_remove_solax_modbus_sensor(self, update_callback):
        """Remove data update."""
        self._sensor_callbacks.remove(update_callback)

        if not self._sensor_callbacks:
            """stop the interval timer upon removal of last sensor"""
            self._unsub_interval_method()
            self._unsub_interval_method = None

    async def _async_refresh_http_data(self, _now: Optional[int] = None) -> None:
        """Time to update."""
        self.cyclecount = self.cyclecount+1
        if not self._sensor_callbacks:
            return
        if (self.cyclecount % self.slowdown) == 0: # only execute once every slowdown count
            update_result = await self._read_http_data()
            if update_result:
                self.slowdown = 1 # return to full polling after succesfull cycle
                for update_callback in self._sensor_callbacks:
                    update_callback()
            else:
                _LOGGER.debug(f"assuming sleep mode - slowing down by factor 10")
                self.slowdown = 10
                for i in self.sleepnone: self.data.pop(i, None)
                for i in self.sleepzero: self.data[i] = 0
                # self.data = {} # invalidate data - do we want this ??

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

    def close(self):
        """Disconnect client."""

    def connect(self):
        """Connect client."""

    def read_holding_registers(self, unit, address, count):
        """Read holding registers. In this case we fake it, only for reading serial."""
        res= ModbusResponse()
        if address == 0x600:
            coder=BinaryPayloadBuilder()
            coder.add_string(self._typeCode)
            res.registers=coder.to_registers()
            return res
        res.function_code=0xFF
        return res

    def read_input_registers(self, unit, address, count):
        """Read input registers. In this case we fake it, only for reading serial."""
        res= ModbusResponse()
        if address == 0x600:
            coder=BinaryPayloadBuilder()
            coder.add_string(self._typeCode)
            res.registers=coder.to_registers()
            return res
        res.function_code=0xFF
        return res

    async def _http_post(self, url, payload):
        try:
            connector = aiohttp.TCPConnector(force_close=True,)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(url,data=payload) as resp:
                    if resp.status==200:
                        return await resp.text()
        except asyncio.TimeoutError:
            pass
        except aiohttp.ServerDisconnectedError:
            # Best is to just ignore it. Next refresh will suceed
            pass
        except Exception as ex:
            _LOGGER.exception("Error reading ReadSetData", exc_info=ex)
        return None

    def write_register(self, unit, address, payload):
        """Write register."""


    async def write_registers_single(self, unit, address, payload):
        """Write registers multi, but write only one register of type 16bit"""
        descr=self._map_register(address, payload)
        if descr is None:
            return False
        try:
            resp=None
            resp=await self._http_post(f'http://{self._host}',f'optType=setReg&pwd={self._sn}&data={{"num":1,"Data":{json.dumps(descr)}}}')
            if resp is not None:
                _LOGGER.info(f'Received HTTP API response {resp}')
                return True
        # except aiohttp.ServerDisconnectedError:
        #     # Best is to just ignore it. Next refresh will suceed
        #     pass
        except Exception as ex:
            _LOGGER.exception("Error writing setReg", exc_info=ex)
        return False

    def write_registers_multi(self, unit, address, payload):
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

    async def _read_realtime_data(self):
        httpData=None
        try:
            connector = aiohttp.TCPConnector(force_close=True)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(f'http://{self._host}',data=f"optType=ReadRealTimeData&pwd={self._sn}") as resp:
                    if resp.status==200:
                        httpData=await resp.json(content_type='text/html')
        except asyncio.TimeoutError:
            pass
        except aiohttp.ServerDisconnectedError:
            # Best is to just ignore it. Next refresh will suceed
            pass
        except Exception as ex:
            _LOGGER.exception("Error reading ReadRealTimeData", exc_info=ex)
        return httpData

    async def _read_set_data(self):
        setData=None
        try:
            connector = aiohttp.TCPConnector(force_close=True,)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(f'http://{self._host}',data=f"optType=ReadSetData&pwd={self._sn}") as resp:
                    if resp.status==200:
                        setData=await resp.json(content_type='text/html')
        except asyncio.TimeoutError:
            pass
        except aiohttp.ServerDisconnectedError:
            # Best is to just ignore it. Next refresh will suceed
            pass
        except Exception as ex:
            _LOGGER.exception("Error reading ReadSetData", exc_info=ex)
        return setData

    async def _read_http_data(self):
        res = True
        try:
            res = await self._read_http_registers_all()
        except ConnectionException as ex:
            _LOGGER.error("Reading data failed! Inverter is offline.")
            res = False
        except Exception as ex:
            _LOGGER.exception("Something went wrong reading from modbus")
            res = False
        return res

    def _map_register(self, address, payload):
        match address:
            case 0x60D:
                return [{"reg":2,"val":f"{payload}"}]
            case 0x60C:
                return [{"reg":1,"val":f"{payload}"}]
            case 0x610:
                return [{"reg":5,"val":f"{payload}"}]
            case 0x613:
                return [{"reg":11,"val":f"{payload}"}]
            case 0x625:
                return [{"reg":70,"val":f"{payload}"}]
            case _:
                return None

    def _map_address(self, Data, descr):
        return_value = None
        val = None
        if self.cyclecount <5: _LOGGER.debug(f"treating register 0x{descr.register:02x} : {descr.key}")

        match descr.register:
            case 0x600:
                return_value=Data[502]
            case 0x60C:
                return_value=Data[0]
            case 0x60D:
                return_value=Data[1]
            case 0x610:
                return_value=Data[29]
            case 0x613:
                return_value=Data[11]
            # case 0x615:
            #     return_value=Data[]
            # case 0x616:
            #     return_value=Data[]
            # case 0x61E: # RTC: Y-M-D H:m:S
            #     return_value=[Data[38]H, Data[38]L, Data[37]H, Data[37]L, Data[36]H, Data[36]L]
            # case 0x625:
            #     return_value=Data[65]
            # case 0x628:
            #     return_value=Data[]
            case 0x0:
                return_value=Data[2]
            case 0x1:
                return_value=Data[3]
            case 0x2:
                return_value=Data[4]
            case 0x4:
                return_value=Data[5]
            case 0x5:
                return_value=Data[6]
            case 0x6:
                return_value=Data[7]
            case 0x8:
                return_value=Data[8]
            case 0x9:
                return_value=Data[9]
            case 0xA:
                return_value=Data[10]
            case 0xB:
                return_value=Data[11]
            case 0xF:
                return_value=Data[12]
            case 0x10:
                return_value=Data[15]*65536+Data[14]
            case 0x12:
                return_value=Data[16]
            case 0x13:
                return_value=Data[17]
            case 0x14:
                return_value=Data[18]
            case 0x15:
                return_value=Data[19]
            case 0x16:
                return_value=Data[20]
            case 0x17:
                return_value=Data[21]
            case 0x18:
                return_value=Data[22]
            case 0x1C:
                return_value=Data[24]
            case 0x1D:
                return_value=Data[0]
            case _:
                return_value=None

        if descr.unit == REGISTER_S16 and return_value >= 32768:
            return_value=return_value - 65536
        if type(descr.scale) is dict: # translate int to string
            return_value = descr.scale.get(return_value, "Unknown")
        elif callable(descr.scale):  # function to call ?
            return_value = descr.scale(return_value, descr, self.data)
        else: # apply simple numeric scaling and rounding if not a list of words
            try:    return_value = round(return_value*descr.scale, descr.rounding)
            except: return_value = return_value # probably a REGISTER_WORDS instance

        if (self.tmpdata_expiry.get(descr.key,0) == 0) and ((descr.sleepmode != SLEEPMODE_LASTAWAKE) or self.plugin.isAwake(self.data)):
            self.data[descr.key] = return_value # case prevent_update number


    def _map_block(self, block, data):
        errmsg = None

        if errmsg == None:
            for reg in block.regs:
                descr = block.descriptions[reg]
                if type(descr) is dict: #  set of byte values
                    for k in descr: self._map_address(data, descr[k])
                else: # single value
                    self._map_address(data, descr)
            return True
        else: #block read failure
            firstdescr = block.descriptions[block.start] # check only first item in block
            if firstdescr.ignore_readerror != False:  # ignore block read errors and return static data
                for reg in block.regs:
                    descr = block.descriptions[reg]
                    if not (type(descr) is dict):
                        if ((descr.ignore_readerror != True) and (descr.ignore_readerror !=False)) : self.data[descr.key] = descr.ignore_readerror # return something static
                return True
            else:
                if self.slowdown == 1: _LOGGER.info(f"{errmsg}: {self.name} cannot read registers at device {self._modbus_addr} position 0x{block.start:x}", exc_info=True)
                return False

    async def _read_http_registers_all(self):
        res = True
        realtimeData = await self._read_realtime_data()
        setData = await self._read_set_data()
        if setData is not None:
            data = {i:v for i,v in enumerate(setData)}
            for block in self.holdingBlocks:
                res = res and self._map_block(block, data)
        if realtimeData is not None:
            data = {i:v for i,v in enumerate(realtimeData['Data'])} | {i+500:v for i,v in enumerate(realtimeData['Information'])}
            for block in self.inputBlocks:
                res = res and self._map_block(block, data)
        if self.localsUpdated:
            self._saveLocalData()
            self.plugin.localDataCallback(self)
        if not self.localsLoaded: self.loadLocalData()
        for reg in self.computedSensors:
            descr = self.computedSensors[reg]
            self.data[descr.key] = descr.value_function(0, descr, self.data )

        self.last_ts = time()
        for (k,v,) in self.data['_repeatUntil'].items():
            if self.last_ts < v:
                buttondescr = self.computedButtons[k]
                payload = buttondescr.value_function(0, buttondescr, self.data)
                _LOGGER.debug(f"ready to repeat button {k} data: {payload}")
                self.write_registers_multi(unit=self._modbus_addr, address=buttondescr.register, payload=payload)
        return res

