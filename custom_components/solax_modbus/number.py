from .const import ATTR_MANUFACTURER, DOMAIN, NUMBER_TYPES, NUMBER_TYPES_G2, NUMBER_TYPES_G3, NUMBER_TYPES_G4, CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR
from homeassistant.components.number import PLATFORM_SCHEMA, NumberEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from typing import Any, Dict, Optional
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    hub_name = entry.data[CONF_NAME]
    hub = hass.data[DOMAIN][hub_name]["hub"]
    modbus_addr = entry.data.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }
    
    entities = []
    
    for number_info in NUMBER_TYPES:
        number = SolaXModbusNumber(
            hub_name,
            hub,
            modbus_addr,
            device_info,
            number_info[0],
            number_info[1],
            number_info[2],
            number_info[3],
            number_info[4],
            number_info[5] if len(number_info) > 5 else None,
        )
        entities.append(number)
    
    if hub.read_gen2x1 == True:
    	for number_info in NUMBER_TYPES_G2:
            number = SolaXModbusNumber(
                hub_name,
                hub,
                modbus_addr,
                device_info,
                number_info[0],
                number_info[1],
                number_info[2],
                number_info[3],
                number_info[4],
                number_info[5] if len(number_info) > 5 else None,
            )
            entities.append(number)
    elif hub.read_gen4x1 or hub.read_gen4x3:
        for number_info in NUMBER_TYPES_G4:
            number = SolaXModbusNumber(
                hub_name,
                hub,
                modbus_addr,
                device_info,
                number_info[0],
                number_info[1],
                number_info[2],
                number_info[3],
                number_info[4],
                number_info[5] if len(number_info) > 5 else None,
            )
            entities.append(number)
    else:
    	for number_info in NUMBER_TYPES_G3:
            number = SolaXModbusNumber(
                hub_name,
                hub,
                modbus_addr,
                device_info,
                number_info[0],
                number_info[1],
                number_info[2],
                number_info[3],
                number_info[4],
                number_info[5] if len(number_info) > 5 else None,
            )
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
                 name,
                 key,
                 register,
                 fmt,
                 attrs,
                 state
    ) -> None:
        """Initialize the number."""
        self._platform_name = platform_name
        self._hub = hub
        self._modbus_addr = modbus_addr
        self._device_info = device_info
        self._name = name
        self._key = key
        self._register = register
        self._fmt = fmt
        self._attr_min_value = attrs["min"]
        self._attr_max_value = attrs["max"]
        self._attr_step = attrs["step"]
        self._attr_unit_of_measurement = attrs["unit"]
        self._state = state

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self._hub.async_add_solax_modbus_sensor(self._modbus_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._hub.async_remove_solax_modbus_sensor(self._modbus_data_updated)
    
    async def async_set_value(self, value: float) -> None:
    	return self._hub.data[self._state]

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
    def value(self) -> float:
        if self._key in self._hub.data:
            return self._hub.data[self._key]

    async def async_set_value(self, value: float) -> None:
        """Change the number value."""
        
        if self._hub.read_gen2x1 == True:
            mult = 100
        else:
            mult = 10
        
        if self._fmt == "i":
            payload = int(value)
        elif self._fmt == "f":
            payload = int(value * mult)

        self._hub.write_register(unit=self._modbus_addr, address=self._register, payload=payload)

        self._hub.data[self._key] = value
        self.async_write_ha_state()