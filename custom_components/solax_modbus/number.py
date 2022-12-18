from .const import ATTR_MANUFACTURER, DOMAIN, CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR
from .const import WRITE_DATA_LOCAL, WRITE_MULTISINGLE_MODBUS, WRITE_SINGLE_MODBUS
#from .const import GEN2, GEN3, GEN4, X1, X3, HYBRID, AC, EPS
from homeassistant.components.number import PLATFORM_SCHEMA, NumberEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from typing import Any, Dict, Optional
from .const import getPlugin
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    if entry.data: # old style - remove soon
        hub_name = entry.data[CONF_NAME]
        modbus_addr = entry.data.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    else: # new style
        hub_name = entry.options[CONF_NAME]
        modbus_addr = entry.options.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    hub = hass.data[DOMAIN][hub_name]["hub"]
    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }
    plugin = hub.plugin #getPlugin(hub_name)
    entities = []
    for number_info in plugin.NUMBER_TYPES:
        readscale = 1
        if number_info.read_scale_exceptions:
            for (prefix, value,) in number_info.read_scale_exceptions: 
                if hub.seriesnumber.startswith(prefix): readscale = value
        if plugin.matchInverterWithMask(hub._invertertype,number_info.allowedtypes, hub.seriesnumber ,number_info.blacklist):
            number = SolaXModbusNumber( hub_name, hub, modbus_addr, device_info, number_info, readscale)
            entities.append(number)
        
    async_add_entities(entities)
    return True

class SolaXModbusNumber(NumberEntity):
    """Representation of an SolaX Modbus number."""

    def __init__(self,
                 platform_name,
                 hub,
                 modbus_addr,
                 device_info,
                 number_info,
                 read_scale
    ) -> None:
        """Initialize the number."""
        self._platform_name = platform_name
        self._hub = hub
        self._modbus_addr = modbus_addr
        self._attr_device_info = device_info
        self._name = number_info.name
        self._key = number_info.key
        self._register = number_info.register
        self._fmt = number_info.fmt
        self._attr_native_min_value = number_info.native_min_value
        self._attr_native_max_value = number_info.native_max_value
        self._attr_scale = number_info.scale
        self._read_scale = read_scale
        self.entity_description = number_info
        if number_info.max_exceptions:
            for (prefix, native_value,) in number_info.max_exceptions: 
                if hub.seriesnumber.startswith(prefix): self._attr_native_max_value = native_value
        self._attr_native_step = number_info.native_step
        self._attr_native_unit_of_measurement = number_info.native_unit_of_measurement
        self._state = number_info.state
        self.entity_description = number_info
        self._write_method = number_info.write_method

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self._hub.async_add_solax_modbus_sensor(self._modbus_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._hub.async_remove_solax_modbus_sensor(self._modbus_data_updated)
    
    """ remove duplicate declaration
    async def async_set_value(self, native_value: float) -> None:
    	return self._hub.data[self._state]
    """

    @callback
    def _modbus_data_updated(self) -> None:
        self.async_write_ha_state()

    @property
    def name(self) -> str:
        """Return the name."""
        return f"{self._platform_name} {self._name}"

#    @property
#    def state(self) -> str:
#        """Return the state? """
#        return f"{self._platform_name} {self._state}"

#    @property
#    def should_poll(self) -> bool:
#        """Data is delivered by the hub"""
#        return False

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self._key}"

    @property
    def native_value(self) -> float:
        if self._key in self._hub.data: 
            if self._read_scale: return self._hub.data[self._key]*self._read_scale
            else: return self._hub.data[self._key]
        else: 
            return self.entity_description.initvalue

    async def async_set_native_value(self, value: float) -> None:
        """Change the number value."""
        if self._fmt == "i":
            payload = int(value/(self._attr_scale*self._read_scale))
        elif self._fmt == "f":
            payload = int(value/(self._attr_scale*self._read_scale))

        if self._write_method == WRITE_MULTISINGLE_MODBUS:
            _LOGGER.info(f"writing {self._platform_name} {self._key} number register {self._register} value {payload} after div by readscale {self._read_scale} scale {self._attr_scale}")
            self._hub.write_registers_single(unit=self._modbus_addr, address=self._register, payload=payload)
        elif self._write_method == WRITE_SINGLE_MODBUS:
            _LOGGER.info(f"writing {self._platform_name} {self._key} number register {self._register} value {payload} after div by readscale {self._read_scale} scale {self._attr_scale}")
            self._hub.write_register(unit=self._modbus_addr, address=self._register, payload=payload)
        else: 
            pass # so nothing, just store in hub.data
        self._hub.data[self._key] = value/self._read_scale
        self.async_write_ha_state()