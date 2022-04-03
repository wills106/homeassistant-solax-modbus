"""The SolaX Modbus Integration."""
import asyncio
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from pymodbus.client.sync import ModbusTcpClient, ModbusSerialClient
from pymodbus.constants import Endian
from pymodbus.exceptions import ConnectionException
from pymodbus.payload import BinaryPayloadDecoder

from .const import (
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    CONF_SERIAL,
    CONF_SERIAL_PORT,
    CONF_READ_GEN2X1,
    CONF_READ_GEN3X1,
    CONF_READ_GEN3X3,
    CONF_READ_GEN4X1,
    CONF_READ_GEN4X3,
    CONF_READ_X1_EPS,
    CONF_READ_X3_EPS,
    DEFAULT_READ_GEN2X1,
    DEFAULT_READ_GEN3X1,
    DEFAULT_READ_GEN3X3,
    DEFAULT_READ_GEN4X1,
    DEFAULT_READ_GEN4X3,
    DEFAULT_READ_X1_EPS,
    DEFAULT_READ_X3_EPS,
    DEFAULT_SERIAL,
    DEFAULT_SERIAL_PORT,
)

_LOGGER = logging.getLogger(__name__)

SOLAX_MODBUS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT): cv.string,
        vol.Required(CONF_SERIAL,      default=DEFAULT_SERIAL): cv.boolean,
        vol.Optional(CONF_SERIAL_PORT, default=DEFAULT_SERIAL_PORT): cv.string,
        vol.Optional(CONF_READ_GEN2X1, default=DEFAULT_READ_GEN2X1): cv.boolean,
        vol.Optional(CONF_READ_GEN3X1, default=DEFAULT_READ_GEN3X1): cv.boolean,
        vol.Optional(CONF_READ_GEN3X3, default=DEFAULT_READ_GEN3X3): cv.boolean,
        vol.Optional(CONF_READ_GEN4X1, default=DEFAULT_READ_GEN4X1): cv.boolean,
        vol.Optional(CONF_READ_GEN4X3, default=DEFAULT_READ_GEN4X3): cv.boolean,
        vol.Optional(CONF_READ_X1_EPS, default=DEFAULT_READ_X1_EPS): cv.boolean,
        vol.Optional(CONF_READ_X3_EPS, default=DEFAULT_READ_X3_EPS): cv.boolean,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.positive_int,
    }
)


CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({cv.slug: SOLAX_MODBUS_SCHEMA})}, extra=vol.ALLOW_EXTRA
)


PLATFORMS = ["sensor"] 


async def async_setup(hass, config):
    """Set up the SolaX modbus component."""
    hass.data[DOMAIN] = {}
    _LOGGER.info("solax data %d", hass.data)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up a SolaX mobus."""
    _LOGGER.info("solax setup")
    host = entry.data[CONF_HOST]
    name = entry.data[CONF_NAME]
    port = entry.data[CONF_PORT]
    serial = entry.data[CONF_SERIAL]
    serial_port = entry.data[CONF_SERIAL_PORT]
    scan_interval = entry.data[CONF_SCAN_INTERVAL]
    read_gen2x1 = entry.data.get(CONF_READ_GEN2X1, False)
    read_gen3x1 = entry.data.get(CONF_READ_GEN3X1, False)
    read_gen3x3 = entry.data.get(CONF_READ_GEN3X3, False)
    read_gen4x1 = entry.data.get(CONF_READ_GEN4X1, False)
    read_gen4x3 = entry.data.get(CONF_READ_GEN4X3, False)
    read_x1_eps = entry.data.get(CONF_READ_X1_EPS, False)
    read_x3_eps = entry.data.get(CONF_READ_X3_EPS, False)

    _LOGGER.debug("Setup %s.%s", DOMAIN, name)
    _LOGGER.info("solax serial port %s %s", serial_port, serial)

    hub = SolaXModbusHub(hass, name, host, port, serial, serial_port, scan_interval, read_gen2x1, read_gen3x1, read_gen3x3, read_gen4x1, read_gen4x3, read_x1_eps, read_x3_eps)
    """Register the hub."""
    hass.data[DOMAIN][name] = {"hub": hub}

    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )
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
    if not unload_ok:
        return False

    hass.data[DOMAIN].pop(entry.data["name"])
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
        serial,
        serial_port,
        scan_interval,
        read_gen2x1=False,
        read_gen3x1=False,
        read_gen3x3=False,
        read_gen4x1=False,
        read_gen4x3=False,
        read_x1_eps=False,
        read_x3_eps=False,
    ):
        """Initialize the Modbus hub."""
        _LOGGER.info("solax modbushub creation")
        self._hass = hass
        if serial: # serial
            self._client = ModbusSerialClient(method="rtu", port=serial_port, baudrate=19200, parity='N', stopbits=1, bytesize=8, timeout=3)
        else:
            self._client = ModbusTcpClient(host=host, port=port, timeout=5)
        self._lock = threading.Lock()
        self._name = name
        self.read_gen2x1 = read_gen2x1
        self.read_gen3x1 = read_gen3x1
        self.read_gen3x3 = read_gen3x3
        self.read_gen4x1 = read_gen4x1
        self.read_gen4x3 = read_gen4x3
        self.read_x1_eps = read_x1_eps
        self.read_x3_eps = read_x3_eps
        self.read_serial = serial
        self.read_serial_port = serial_port
        self._scan_interval = timedelta(seconds=scan_interval)
        self._unsub_interval_method = None
        self._sensors = []
        self.data = {}
        _LOGGER.info("solax modbushub done %s", self.__dict__)

    @callback
    def async_add_solax_modbus_sensor(self, update_callback):
        """Listen for data updates."""
        # This is the first sensor, set up interval.
        if not self._sensors:
            self.connect()
            self._unsub_interval_method = async_track_time_interval(
                self._hass, self.async_refresh_modbus_data, self._scan_interval
            )

        self._sensors.append(update_callback)

    @callback
    def async_remove_solax_modbus_sensor(self, update_callback):
        """Remove data update."""
        self._sensors.remove(update_callback)

        if not self._sensors:
            """stop the interval timer upon removal of last sensor"""
            self._unsub_interval_method()
            self._unsub_interval_method = None
            self.close()

    async def async_refresh_modbus_data(self, _now: Optional[int] = None) -> None:
        """Time to update."""
        if not self._sensors:
            return

        update_result = self.read_modbus_data()

        if update_result:
            for update_callback in self._sensors:
                update_callback()

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
            kwargs = {"unit": unit} if unit else {}
            return self._client.read_holding_registers(address, count, **kwargs)
    
    def read_input_registers(self, unit, address, count):
        """Read input registers."""
        with self._lock:
            kwargs = {"unit": unit} if unit else {}
            return self._client.read_input_registers(address, count, **kwargs)

    def write_register(self, unit, address, payload):
        """Write registers."""
        with self._lock:
            kwargs = {"unit": unit} if unit else {}
            return self._client.write_register(address, payload, **kwargs)

    def read_modbus_data(self):
 	
        try:
            return self.read_modbus_holding_registers_0() and self.read_modbus_holding_registers_1() and self.read_modbus_input_registers_0()
        except ConnectionException as ex:
            _LOGGER.error("Reading data failed! Inverter is offline.")   

            return True

    def read_modbus_holding_registers_0(self):

        inverter_data = self.read_holding_registers(unit=1, address=0x0, count=21)

        if inverter_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            inverter_data.registers, byteorder=Endian.Big
        )

        seriesnumber = decoder.decode_string(14).decode("ascii")
        self.data["seriesnumber"] = str(seriesnumber)

        factoryname = decoder.decode_string(14).decode("ascii")
        self.data["factoryname"] = str(factoryname)

        modulename = decoder.decode_string(14).decode("ascii")
        self.data["modulename"] = str(modulename)

        return True

    def read_modbus_holding_registers_1(self):

        inverter_data = self.read_holding_registers(unit=1, address=0x85, count=6)

        if inverter_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            inverter_data.registers, byteorder=Endian.Big
        )
        

        rtc_seconds = str(decoder.decode_16bit_uint())
        rtc_minutes = str(decoder.decode_16bit_uint())
        rtc_hours = str(decoder.decode_16bit_uint())
        rtc_days = str(decoder.decode_16bit_uint())
        rtc_months = str(decoder.decode_16bit_uint())
        rtc_years = str(decoder.decode_16bit_uint())
        
        date_string = f"{rtc_days.zfill(2)}/{rtc_months.zfill(2)}/{rtc_years.zfill(2)} {rtc_hours.zfill(2)}:{rtc_minutes.zfill(2)}:{rtc_seconds.zfill(2)}"
        
        self.data["rtc"] = datetime.strptime(date_string, '%d/%m/%y %H:%M:%S')

        return True

    def read_modbus_input_registers_0(self):
    	
        realtime_data = self.read_input_registers(unit=1, address=0x0, count=29)

        if realtime_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            realtime_data.registers, Endian.Big, wordorder=Endian.Little
        )

        inverter_voltage = decoder.decode_16bit_uint()
        self.data["inverter_voltage"] = round(inverter_voltage * 0.1, 1)
        
        inverter_current = decoder.decode_16bit_int()
        self.data["inverter_current"] = round(inverter_current * 0.1, 1)
                
        inverter_load = decoder.decode_16bit_int()
        self.data["inverter_load"] = inverter_load
        
        decoder.skip_bytes(8)
        
        grid_frequency = decoder.decode_16bit_uint()
        self.data["grid_frequency"] = round(grid_frequency * 0.01, 2)
        
        inverter_temperature = decoder.decode_16bit_int()
        self.data["inverter_temperature"] = inverter_temperature
        
        run_modes = decoder.decode_16bit_uint()
        if   run_modes == 0: self.data["run_mode"] = "Waiting"
        elif run_modes == 1: self.data["run_mode"] = "Checking"
        elif run_modes == 2: self.data["run_mode"] = "Normal Mode"
        elif run_modes == 3: self.data["run_mode"] = "Off Mode"
        elif run_modes == 4: self.data["run_mode"] = "Permanent Fault Mode"
        elif run_modes == 5: self.data["run_mode"] = "Update Mode"
        elif run_modes == 6: self.data["run_mode"] = "EPS Check Mode"
        elif run_modes == 7: self.data["run_mode"] = "EPS Mode"
        elif run_modes == 8: self.data["run_mode"] = "Self Test"
        elif run_modes == 9: self.data["run_mode"] = "Idle Mode"
        else: self.data["run_mode"] = "Unknown"
        
        decoder.skip_bytes(18)
        
        time_count_down = decoder.decode_16bit_uint()
        self.data["time_count_down"] = round(time_count_down * 0.001, 0)
        
        battery_voltage_charge = decoder.decode_16bit_int()
        self.data["battery_voltage_charge"] = round(battery_voltage_charge * 0.1, 1)
        
        battery_current_charge = decoder.decode_16bit_int()
        self.data["battery_current_charge"] = round(battery_current_charge * 0.1, 1)
        
        battery_power_charge = decoder.decode_16bit_int()
        self.data["battery_power_charge"] = battery_power_charge
        
        bms_connect_states = decoder.decode_16bit_uint()
        if   bms_connect_states == 0: self.data["bms_connect_state"] = "Disconnected"
        elif bms_connect_states == 1: self.data["bms_connect_state"] = "Connected"
        else: self.data["bms_connect_state"] = "Unknown"
        
        battery_temperature = decoder.decode_16bit_int()
        self.data["battery_temperature"] = battery_temperature
        
        decoder.skip_bytes(6)
        
        #0x01C
        battery_capacity_charge = decoder.decode_16bit_uint()
        self.data["battery_capacity_charge"] = battery_capacity_charge
        
        return True
