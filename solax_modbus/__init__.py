"""The SolaX Modbus Integration."""
import asyncio
import logging
import threading
from datetime import timedelta
from typing import Optional

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.exceptions import ConnectionException
from pymodbus.payload import BinaryPayloadDecoder

from .const import (
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    CONF_READ_GEN2X1,
	CONF_READ_GEN3X1,
	CONF_READ_GEN3X3,
	CONF_READ_OPTIONAL_SENSORS,
	CONF_READ_X1_EPS,
    CONF_READ_X3_EPS,
	DEFAULT_READ_GEN2X1,
	DEFAULT_READ_GEN3X1,
	DEFAULT_READ_GEN3X3,
	DEFAULT_READ_OPTIONAL_SENSORS,
	DEFAULT_READ_X1_EPS,
	DEFAULT_READ_X3_EPS,
)

_LOGGER = logging.getLogger(__name__)

SOLAX_MODBUS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT): cv.string,
        vol.Optional(CONF_READ_GEN2X1, default=DEFAULT_READ_GEN2X1): cv.boolean,
        vol.Optional(CONF_READ_GEN3X1, default=DEFAULT_READ_GEN3X1): cv.boolean,
        vol.Optional(CONF_READ_GEN3X3, default=DEFAULT_READ_GEN3X3): cv.boolean,
        vol.Optional(CONF_READ_OPTIONAL_SENSORS, default=DEFAULT_READ_OPTIONAL_SENSORS): cv.boolean,
        vol.Optional(CONF_READ_X1_EPS, default=DEFAULT_READ_X1_EPS): cv.boolean,
        vol.Optional(CONF_READ_X3_EPS, default=DEFAULT_READ_X3_EPS): cv.boolean,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): cv.positive_int,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({cv.slug: SOLAX_MODBUS_SCHEMA})}, extra=vol.ALLOW_EXTRA
)

PLATFORMS = ["sensor"]


async def async_setup(hass, config):
    """Set up the SolaX modbus component."""
    hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up a SolaX mobus."""
    host = entry.data[CONF_HOST]
    name = entry.data[CONF_NAME]
    port = entry.data[CONF_PORT]
    scan_interval = entry.data[CONF_SCAN_INTERVAL]
    read_gen2x1 = entry.data.get(CONF_READ_GEN2X1, False)
    read_gen3x1 = entry.data.get(CONF_READ_GEN3X1, False)
    read_gen3x3 = entry.data.get(CONF_READ_GEN3X3, False)
    read_optional_sensors = entry.data.get(CONF_READ_OPTIONAL_SENSORS, False)
    read_x1_eps = entry.data.get(CONF_READ_X1_EPS, False)
    read_x3_eps = entry.data.get(CONF_READ_X3_EPS, False)

    _LOGGER.debug("Setup %s.%s", DOMAIN, name)

    hub = SolaXModbusHub(hass, name, host, port, scan_interval, read_gen2x1, read_gen3x1, read_gen3x3, read_optional_sensors, read_x1_eps, read_x3_eps)
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


class SolaXModbusHub:
    """Thread safe wrapper class for pymodbus."""

    def __init__(
        self,
        hass,
        name,
        host,
        port,
        scan_interval,
        read_gen2x1=False,
        read_gen3x1=False,
        read_gen3x3=False,
        read_optional_sensors=False,
        read_x1_eps=False,
        read_x3_eps=False,
    ):
        """Initialize the Modbus hub."""
        self._hass = hass
        self._client = ModbusTcpClient(host=host, port=port, timeout=5)
        self._lock = threading.Lock()
        self._name = name
        self.read_gen2x1 = read_gen2x1
        self.read_gen3x1 = read_gen3x1
        self.read_gen3x3 = read_gen3x3
        self.read_optional_sensors = read_optional_sensors
        self.read_x1_eps = read_x1_eps
        self.read_x3_eps = read_x3_eps
        self._scan_interval = timedelta(seconds=scan_interval)
        self._unsub_interval_method = None
        self._sensors = []
        self.data = {}

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

    def calculate_value(self, value, sf):
        return value * 10 ** sf

    def read_modbus_data(self):
        try:
            return self.read_modbus_holding_registers_0() and self.read_modbus_holding_registers_1() and self.read_modbus_input_registers_0() and self.read_modbus_input_registers_1()
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

        inverter_data = self.read_holding_registers(unit=1, address=0x7d, count=64)

        if inverter_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            inverter_data.registers, byteorder=Endian.Big
        )
        
        firmwareversion_invertermaster = decoder.decode_16bit_uint()
        self.data["firmwareversion_invertermaster"] = firmwareversion_invertermaster
        
        decoder.skip_bytes(6)
        
        firmwareversion_modbustcp_major = decoder.decode_16bit_uint()
        self.data["firmwareversion_modbustcp_major"] = firmwareversion_modbustcp_major
        
        firmwareversion_modbustcp_minor = decoder.decode_16bit_uint()
        self.data["firmwareversion_modbustcp_minor"] = firmwareversion_modbustcp_minor
        
        firmwareversion_manager = decoder.decode_16bit_uint()
        self.data["firmwareversion_manager"] = firmwareversion_manager
        
        myaddress = decoder.decode_16bit_uint()
        self.data["myaddress"] = myaddress
        
        rtc_seconds = decoder.decode_16bit_uint()
        self.data["rtc_seconds"] = rtc_seconds
        
        rtc_minutes = decoder.decode_16bit_uint()
        rtc_hours = decoder.decode_16bit_uint()
        rtc_days = decoder.decode_16bit_uint()
        rtc_months = decoder.decode_16bit_uint()
        rtc_years = decoder.decode_16bit_uint()
        
        self.data["rtc"] = f"{rtc_hours}:{rtc_minutes}:{rtc_seconds} {rtc_days}/{rtc_months}/{rtc_years}"
        
        charger_use_modes = decoder.decode_16bit_uint()       
        if charger_use_modes == 0:
          self.data["charger_use_mode"] = "Self Use Mode"
        elif charger_use_modes == 1:
          self.data["charger_use_mode"] = "Force Time Use"
        elif charger_use_modes == 2:
          self.data["charger_use_mode"] = "Back Up Mode"
        elif charger_use_modes == 3:
          self.data["charger_use_mode"] = "Feedin Priority"
        else:
          self.data["charger_use_mode"] = "Unknown"
        
        battery_min_capacity = decoder.decode_16bit_uint()
        self.data["battery_min_capacity"] = battery_min_capacity
        
        battery_types = decoder.decode_16bit_uint()        
        if battery_types == 0:
          self.data["battery_type"] = "Lead Acid"
        elif battery_types == 1:
          self.data["battery_type"] = "Lithium"
        else:
          self.data["battery_type"] = "Unknown"
        
        battery_charge_float_voltage = decoder.decode_16bit_uint()
        self.data["battery_charge_float_voltage"] = round(battery_charge_float_voltage * 0.1, 1)
        
        battery_discharge_cut_off_voltage = decoder.decode_16bit_uint()
        self.data["battery_discharge_cut_off_voltage"] = round(battery_discharge_cut_off_voltage * 0.1, 1)
        
        battery_charge_max_current = decoder.decode_16bit_uint()
        self.data["battery_charge_max_current"] = round(battery_charge_max_current * 0.1, 1)
        
        battery_discharge_max_current = decoder.decode_16bit_uint()
        self.data["battery_discharge_max_current"] = round(battery_discharge_max_current * 0.1, 1)
        
        charger_start_time_1_h = decoder.decode_16bit_uint()        
        charger_start_time_1_m = decoder.decode_16bit_uint()        
        self.data["charger_start_time_1"] = f"{charger_start_time_1_h}:{charger_start_time_1_m}"
        
        charger_end_time_1_h = decoder.decode_16bit_uint()        
        charger_end_time_1_m = decoder.decode_16bit_uint()
        self.data["charger_end_time_1"] = f"{charger_end_time_1_h}:{charger_end_time_1_m}"
        
        decoder.skip_bytes(8)
        
        charger_start_time_2_h = decoder.decode_16bit_uint()        
        charger_start_time_2_m = decoder.decode_16bit_uint()
        self.data["charger_start_time_2"] = f"{charger_start_time_2_h}:{charger_start_time_2_m}"
        
        charger_end_time_2_h = decoder.decode_16bit_uint()        
        charger_end_time_2_m = decoder.decode_16bit_uint()
        self.data["charger_end_time_2"] = f"{charger_end_time_2_h}:{charger_end_time_2_m}"
        
        decoder.skip_bytes(34)
        
        registration_code = decoder.decode_string(10).decode("ascii")
        self.data["registration_code"] = str(registration_code)
        
        allow_grid_charges = decoder.decode_16bit_uint()
        if allow_grid_charges == 0:
          self.data["allow_grid_charge"] = "Forbidden"
        elif allow_grid_charges == 1:
          self.data["allow_grid_charge"] = "Charger Time 1"
        elif allow_grid_charges == 2:
          self.data["allow_grid_charge"] = "Charger Time 2"
        elif allow_grid_charges == 3:
          self.data["allow_grid_charge"] = "Both Charger Time's"
        else:
          self.data["allow_grid_charge"] = "Unknown"
        
        export_control_factory_limit = decoder.decode_16bit_uint()
        self.data["export_control_factory_limit"] = round(export_control_factory_limit * 0.1, 1)
        
        export_control_user_limit = decoder.decode_16bit_uint()
        self.data["export_control_user_limit"] = round(export_control_user_limit * 0.1, 1)
        
        eps_mutes = decoder.decode_16bit_uint()
        if eps_mutes == 0:
          self.data["eps_mute"] = "Off"
        elif eps_mutes == 1:
          self.data["eps_mute"] = "On"
        else:
          self.data["eps_mute"] = "Unknown"
        
        eps_set_frequencys = decoder.decode_16bit_uint()
        if eps_set_frequencys == 0:
          self.data["eps_set_frequency"] = "50Hz"
        elif eps_set_frequencys == 1:
          self.data["eps_set_frequency"] = "60Hz"
        else:
          self.data["eps_set_frequency"] = "Unknown"
        
        decoder.skip_bytes(2)
        
        inverter_rate_power = decoder.decode_16bit_uint()
        self.data["inverter_rate_power"] = inverter_rate_power
        
        languages = decoder.decode_16bit_uint()
        if languages == 0:
          self.data["language"] = "English"
        elif languages == 1:
          self.data["language"] = "Deutsche"
        else:
          self.data["language"] = languages

        return True

    def read_modbus_input_registers_0(self):

        realtime_data = self.read_input_registers(unit=1, address=0x0, count=86)

        if realtime_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            realtime_data.registers, byteorder=Endian.Big
        )

        inverter_voltage = decoder.decode_16bit_uint()
        self.data["inverter_voltage"] = round(inverter_voltage * 0.1, 1)
        
        inverter_current = decoder.decode_16bit_int()
        self.data["inverter_current"] = round(inverter_current * 0.1, 1)
                
        inverter_load = decoder.decode_16bit_int()
        self.data["inverter_load"] = inverter_load
        
        pv_voltage_1 = decoder.decode_16bit_uint()
        self.data["pv_voltage_1"] = round(pv_voltage_1 * 0.1, 1)
        
        pv_voltage_2 = decoder.decode_16bit_uint()
        self.data["pv_voltage_2"] = round(pv_voltage_2 * 0.1, 1)
        
        pv_current_1 = decoder.decode_16bit_uint()
        self.data["pv_current_1"] = round(pv_current_1 * 0.1, 1)
        
        pv_current_2 = decoder.decode_16bit_uint()
        self.data["pv_current_2"] = round(pv_current_2 * 0.1, 1)
        
        grid_frequency = decoder.decode_16bit_uint()
        self.data["grid_frequency"] = round(grid_frequency * 0.01, 2)
        
        inverter_temperature = decoder.decode_16bit_int()
        self.data["inverter_temperature"] = inverter_temperature
        
        run_modes = decoder.decode_16bit_uint()
        if run_modes == 0:
          self.data["run_mode"] = "Waiting"
        elif run_modes == 1:
          self.data["run_mode"] = "Checking"
        elif run_modes == 2:
          self.data["run_mode"] = "Normal Mode"
        elif run_modes == 3:
          self.data["run_mode"] = "Feedin Priority"
        elif run_modes == 4:
          self.data["run_mode"] = "Pemanent Fault Mode"
        elif run_modes == 5:
          self.data["run_mode"] = "Update Mode"
        elif run_modes == 6:
          self.data["run_mode"] = "EPS Check Mode"
        elif run_modes == 7:
          self.data["run_mode"] = "EPS Mode"
        elif run_modes == 8:
          self.data["run_mode"] = "Self Test"
        elif run_modes == 9:
          self.data["run_mode"] = "Idle Mode"
        else:
          self.data["run_mode"] = "Unknown"
        
        pv_power_1 = decoder.decode_16bit_uint()
        self.data["pv_power_1"] = pv_power_1
        
        pv_power_2 = decoder.decode_16bit_uint()
        self.data["pv_power_2"] = pv_power_2
        
        self.data["pv_total_power"] = pv_power_1 + pv_power_2
        
        decoder.skip_bytes(14)
        
        time_count_down = decoder.decode_16bit_uint()
        self.data["time_count_down"] = round(time_count_down * 0.001, 0)
        
        battery_voltage_charge = decoder.decode_16bit_int()
        self.data["battery_voltage_charge_g2"] = round(battery_voltage_charge * 0.01, 1)
        self.data["battery_voltage_charge_g3"] = round(battery_voltage_charge * 0.1, 1)
        
        battery_current_charge = decoder.decode_16bit_int()
        self.data["battery_current_charge_g2"] = round(battery_current_charge * 0.01, 1)
        self.data["battery_current_charge_g3"] = round(battery_current_charge * 0.1, 1)
        
        battery_power_charge = decoder.decode_16bit_int()
        self.data["battery_power_charge"] = battery_power_charge
        
        bms_connect_states = decoder.decode_16bit_uint()
        if bms_connect_states == 0:
          self.data["bms_connect_state"] = "Disconnected"
        elif bms_connect_states == 1:
          self.data["bms_connect_state"] = "Connected"
        else:
          self.data["bms_connect_state"] = "Unknown"
        
        battery_temperature = decoder.decode_16bit_int()
        self.data["battery_temperature"] = battery_temperature
        
        decoder.skip_bytes(6)
        
        battery_capacity_charge = decoder.decode_16bit_uint()
        self.data["battery_capacity_charge"] = battery_capacity_charge
        
        output_energy_charge_lsb = decoder.decode_16bit_uint()
        self.data["output_energy_charge_lsb"] = round(output_energy_charge_lsb * 0.1, 1)
        
        output_energy_charge_msb = decoder.decode_16bit_uint()
        self.data["output_energy_charge_msb"] = round(output_energy_charge_msb * 0.1, 1)
        
        bms_warning_lsb = decoder.decode_16bit_uint()
        self.data["bms_warning_lsb"] = bms_warning_lsb
        
        output_energy_charge_today = decoder.decode_16bit_uint()
        self.data["output_energy_charge_today"] = round(output_energy_charge_today * 0.1, 1)
        
        input_energy_charge_lsb = decoder.decode_16bit_uint()
        self.data["input_energy_charge_lsb"] = round(input_energy_charge_lsb * 0.1, 1)
        
        input_energy_charge_msb = decoder.decode_16bit_uint()
        self.data["input_energy_charge_msb"] = round(input_energy_charge_msb * 0.1, 1)
        
        input_energy_charge_today = decoder.decode_16bit_uint()
        self.data["input_energy_charge_today"] = round(input_energy_charge_today * 0.1, 1)
        
        bms_charge_max_current = decoder.decode_16bit_uint()
        self.data["BMS Charge Max Current"] = round(bms_charge_max_current * 0.1, 1)
        
        bms_discharge_max_current = decoder.decode_16bit_uint()
        self.data["BMS Discharge Max Current"] = round(bms_discharge_max_current * 0.1, 1)
        
        bms_warning_msb = decoder.decode_16bit_uint()
        self.data["bms_warning_msb"] = bms_warning_msb
        
        decoder.skip_bytes(62)
        
        feedin_power = decoder.decode_16bit_int()
        self.data["feedin_power"] = feedin_power
                
        if feedin_power > 0:
          self.data["grid_export"] = feedin_power
        else:
          self.data["grid_export"] = 0
          
        if feedin_power < 0:
          self.data["grid_import"] = abs(feedin_power)
        else:
          self.data["grid_import"] = 0
          
        if inverter_load > 0:
          self.data["house_load"] = inverter_load - feedin_power
        else:
          self.data["house_load"] = 0
#####################                            
        feedin_energy_total = decoder.decode_16bit_uint()
        self.data["feedin_energy_total"] = round(feedin_energy_total * 0.01, 1)
        
        decoder.skip_bytes(2)
                
        consumed_energy_total = decoder.decode_16bit_uint()
        self.data["consumed_energy_total"] = round(consumed_energy_total * 0.01, 1)
        
        decoder.skip_bytes(2)
        
        eps_volatge = decoder.decode_16bit_uint()
        self.data["eps_volatge"] = round(eps_volatge * 0.1, 1)
        
        eps_current = decoder.decode_16bit_uint()
        self.data["eps_current"] = round(eps_current * 0.1, 1)
        
        eps_power = decoder.decode_16bit_uint()
        self.data["eps_power"] = eps_power
        
        eps_current = decoder.decode_16bit_uint()
        self.data["eps_current"] = round(eps_current * 0.1, 1)
        
        eps_frequency = decoder.decode_16bit_uint()
        self.data["eps_frequency"] = round(eps_frequency * 0.01, 2)
                
        energy_today = decoder.decode_16bit_uint()
        self.data["energy_today"] = round(energy_today * 0.1, 1)
        
        decoder.skip_bytes(2)
        
        total_energy_to_grid = decoder.decode_16bit_uint()
        self.data["total_energy_to_grid"] = round(total_energy_to_grid * 0.001, 1)
        
        decoder.skip_bytes(2)
        
        lock_states = decoder.decode_16bit_uint()
        if lock_states == 0:
          self.data["lock_state"] = "Locked"
        elif lock_states == 1:
          self.data["lock_state"] = "Unlocked"
        else:
          self.data["lock_state"] = "Unknown"
        
        return True
    
    def read_modbus_input_registers_1(self):

        realtime_data = self.read_input_registers(unit=1, address=0x66, count=54)

        if realtime_data.isError():
            return False

        decoder = BinaryPayloadDecoder.fromRegisters(
            realtime_data.registers, byteorder=Endian.Big
        )
        
        bus_volt = decoder.decode_16bit_uint()
        self.data["bus_volt"] = round(bus_volt * 0.1, 1)
        
        dc_fault_val = decoder.decode_16bit_uint()
        self.data["dc_fault_val"] = round(dc_fault_val * 0.1, 1)
        
        overload_fault_val = decoder.decode_16bit_uint()
        self.data["overload_fault_val"] = overload_fault_val
        
        battery_volt_fault_val = decoder.decode_16bit_uint()
        self.data["battery_volt_fault_val"] = round(battery_volt_fault_val * 0.1, 1)
        
        grid_voltage_r = decoder.decode_16bit_uint()
        self.data["grid_voltage_r"] = round(grid_voltage_r * 0.1, 1)
        
        grid_current_r = decoder.decode_16bit_int()
        self.data["grid_current_r"] = round(grid_current_r * 0.1, 1)
        
        grid_power_r = decoder.decode_16bit_int()
        self.data["grid_power_r"] = round(grid_power_r * 0.1, 1)
        
        grid_frequency_r = decoder.decode_16bit_uint()
        self.data["grid_frequency_r"] = round(grid_frequency_r * 0.01, 1)
        
        grid_voltage_s = decoder.decode_16bit_uint()
        self.data["grid_voltage_s"] = round(grid_voltage_s * 0.1, 1)
        
        grid_current_s = decoder.decode_16bit_int()
        self.data["grid_current_s"] = round(grid_current_s * 0.1, 1)
        
        grid_power_s = decoder.decode_16bit_int()
        self.data["grid_power_s"] = round(grid_power_s * 0.1, 1)
        
        grid_frequency_s = decoder.decode_16bit_uint()
        self.data["grid_frequency_s"] = round(grid_frequency_s * 0.01, 1)
        
        grid_voltage_t = decoder.decode_16bit_uint()
        self.data["grid_voltage_t"] = round(grid_voltage_t * 0.1, 1)
        
        grid_current_t = decoder.decode_16bit_int()
        self.data["grid_current_t"] = round(grid_current_t * 0.1, 1)
        
        grid_power_t = decoder.decode_16bit_int()
        self.data["grid_power_t"] = round(grid_power_t * 0.1, 1)
        
        grid_frequency_t = decoder.decode_16bit_uint()
        self.data["grid_frequency_t"] = round(grid_frequency_t * 0.01, 1)
        
        eps_voltage_r = decoder.decode_16bit_uint()
        self.data["eps_voltage_r"] = round(eps_voltage_r * 0.1, 1)
        
        eps_current_r = decoder.decode_16bit_uint()
        self.data["eps_current_r"] = round(eps_current_r * 0.1, 1)
        
        eps_power_active_r = decoder.decode_16bit_uint()
        self.data["eps_power_active_r"] = eps_power_active_r
        
        eps_power_r = decoder.decode_16bit_uint()
        self.data["eps_power_r"] = eps_power_r
        
        eps_voltage_s = decoder.decode_16bit_uint()
        self.data["eps_voltage_s"] = round(eps_voltage_s * 0.1, 1)
        
        eps_current_s = decoder.decode_16bit_uint()
        self.data["eps_current_s"] = round(eps_current_s * 0.1, 1)
        
        eps_power_active_s = decoder.decode_16bit_uint()
        self.data["eps_power_active_s"] = eps_power_active_s
        
        eps_power_s = decoder.decode_16bit_uint()
        self.data["eps_power_s"] = eps_power_s
        
        eps_voltage_t = decoder.decode_16bit_uint()
        self.data["eps_voltage_t"] = round(eps_voltage_t * 0.1, 1)
        
        eps_current_t = decoder.decode_16bit_uint()
        self.data["eps_current_t"] = round(eps_current_t * 0.1, 1)
        
        eps_power_active_t = decoder.decode_16bit_uint()
        self.data["eps_power_active_t"] = eps_power_active_t
        
        eps_power_t = decoder.decode_16bit_uint()
        self.data["eps_power_t"] = eps_power_t
        
        feedin_power_r = decoder.decode_16bit_int()
        self.data["feedin_power_r"] = feedin_power_r
        
        decoder.skip_bytes(2)
        
        feedin_power_s = decoder.decode_16bit_int()
        self.data["feedin_power_s"] = feedin_power_s
        
        decoder.skip_bytes(2)
        
        feedin_power_t = decoder.decode_16bit_int()
        self.data["feedin_power_t"] = feedin_power_t
        
        decoder.skip_bytes(2)
        
        grid_mode_runtime = decoder.decode_16bit_int()
        self.data["grid_mode_runtime"] = round(grid_mode_runtime * 0.1, 1)
        
        decoder.skip_bytes(2)
        
        eps_mode_runtime = decoder.decode_16bit_int()
        self.data["eps_mode_runtime"] = round(eps_mode_runtime * 0.1, 1)
        
        decoder.skip_bytes(2)
        
        normal_runtime = decoder.decode_16bit_int()
        self.data["normal_runtime"] = round(normal_runtime * 0.1, 1)
        
        decoder.skip_bytes(2)
        
        eps_yield_total = decoder.decode_16bit_uint()
        self.data["eps_yield_total"] = round(eps_yield_total * 0.1, 1)
        
        decoder.skip_bytes(2)
        
        eps_yield_today = decoder.decode_16bit_uint()
        self.data["eps_yield_today"] = round(eps_yield_today * 0.1, 1)
        
        e_charge_today = decoder.decode_16bit_uint()
        self.data["e_charge_today"] = e_charge_today
        
        e_charge_total = decoder.decode_16bit_uint()
        self.data["e_charge_total"] = e_charge_total
        
        decoder.skip_bytes(2)
        
        solar_energy_total = decoder.decode_16bit_uint()
        self.data["solar_energy_total"] = round(solar_energy_total * 0.1, 1)
        
        decoder.skip_bytes(2)
        
        solar_energy_today = decoder.decode_16bit_uint()
        self.data["solar_energy_today"] = round(solar_energy_today * 0.1, 1)
        
        decoder.skip_bytes(2)
        
        export_energy_today = decoder.decode_16bit_uint()
        self.data["export_energy_today"] = round(export_energy_today * 0.01, 2)
        
        decoder.skip_bytes(2)
        
        import_energy_today = decoder.decode_16bit_uint()
        self.data["import_energy_today"] = round(import_energy_today * 0.01, 2)
        
        return True