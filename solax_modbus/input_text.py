from .const import ATTR_MANUFACTURER, DOMAIN, TIME_TYPES_G4
from homeassistant.components.input_text import InputText, CONF_MAX, CONF_MIN, CONF_PATTERN, CONF_VALUE
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from typing import Any, Dict, Optional
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass: HomeAssistant, config: ConfigType, add_entities: async_add_entities, discovery_info: DiscoveryInfoType | None = None) -> None:
#async def async_setup_entry(hass, entry, async_add_entities) -> None:
    __LOGGER.warning("text input platform setup ==================================")
    #hub_name = entry.data[CONF_NAME]
    hub_name = config[CONF_NAME]
    hub = hass.data[DOMAIN][hub_name]["hub"]

    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }
    
    entities = []
    
    for number_info in TIME_TYPES:
        number = SolaXModbusTime(
            hub_name,
            hub,
            device_info,
            number_info[0],
            number_info[1],
            number_info[2],
        )
        entities.append(number)
    
    if hub.read_gen2x1 == True:
    	for number_info in TIME_TYPES_G2:
            number = SolaXModbustime(
                hub_name,
                hub,
                device_info,
                number_info[0],
                number_info[1],
                number_info[2],
            )
            entities.append(number)
    elif hub.read_gen4x1 or hub.read_gen4x3:
        for number_info in TIME_TYPES_G4:
            number = SolaXModbusTime(
                hub_name,
                hub,
                device_info,
                number_info[0],
                number_info[1],
                number_info[2],
            )
            entities.append(number)
    else:
    	for number_info in TIME_TYPES_G3:
            number = SolaXModbusTime(
                hub_name,
                hub,
                device_info,
                number_info[0],
                number_info[1],
                number_info[2],
            )
            entities.append(number)
        
    async_add_entities(entities)
    return True

class SolaXModbusTime(InputText):
    """Representation of an SolaX Modbus number."""

    def __init__(self,
                 platform_name,
                 hub,
                 device_info,
                 name,
                 key,
                 register
    ) -> None:
        """Initialize the time object"""
        super().__init__(self, { CONF_MIN: 5, CONF_MAX: 5, CONF_PATTERN: "^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$" } )
        self._platform_name = platform_name
        self._hub = hub
        self._device_info = device_info
        self._name = name
        self._key = key
        self._register = register
        self._state = None

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

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self._key}"

    @property
    def value(self) -> float:
        if self._key in self._hub.data:
            return self._hub.data[self._key]

    async def async_set_value(self, value: str) -> None:
        """Change the time value."""
        payload = None
        if self._hub.read_gen4x1 or self._hub.read_gen4x3: # different encoding for other generations not yet implemented
            hour, minute = value.split(':',1)
            if hour.isnumeric() and minute.isnumeric():
                hour = int(hour)
                minutes = int(minutes)
                if (0 <= hour <=23) and (0 <= minute <= 59):  payload = (minute << 8) + hour
            if payload != None:
                self._hub.write_register(unit=1, address=self._register, payload=payload)
                self._hub.data[self._key] = value
                self.async_write_ha_state()
            else: _LOGGER.warning("Invalid time value: expecting hh:mm format)")