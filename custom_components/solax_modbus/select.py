from .const import ATTR_MANUFACTURER, DOMAIN, SELECT_TYPES, SELECT_TYPES_G4
from homeassistant.components.select import PLATFORM_SCHEMA, SelectEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from typing import Any, Dict, Optional
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    hub_name = entry.data[CONF_NAME]
    hub = hass.data[DOMAIN][hub_name]["hub"]

    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }
    
    entities = []
    if hub.read_gen4x1 or hub.read_gen4x3:
        for select_info in SELECT_TYPES_G4:
            select = SolaXModbusSelect(
                hub_name,
                hub,
                device_info,
                select_info[0],
                select_info[1],
                select_info[2],
                select_info[3],
            )
            entities.append(select)
    else:
        for select_info in SELECT_TYPES:
            select = SolaXModbusSelect(
                hub_name,
                hub,
                device_info,
                select_info[0],
                select_info[1],
                select_info[2],
                select_info[3],
            )
            entities.append(select)
        
    async_add_entities(entities)
    return True

def get_payload(my_dict, search):
    for k, v in my_dict.items():
        if v == search:
            return k
    return None

class SolaXModbusSelect(SelectEntity):
    """Representation of an SolaX Modbus select."""

    def __init__(self,
                 platform_name,
                 hub,
                 device_info,
                 name,
                 key,
                 register,
                 options
    ) -> None:
        """Initialize the selector."""
        self._platform_name = platform_name
        self._hub = hub
        self._device_info = device_info
        self._name = name
        self._key = key
        self._register = register
        self._option_dict = options

        self._attr_options = list(options.values())

    async def async_added_to_hass(self):
        """Register callbacks."""
        self._hub.async_add_solax_modbus_sensor(self._modbus_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._hub.async_remove_solax_modbus_sensor(self._modbus_data_updated)

    @callback
    def _modbus_data_updated(self):
        self.async_write_ha_state()

    @property
    def current_option(self) -> str:
        if self._key in self._hub.data:
            return self._hub.data[self._key]

    @property
    def name(self):
        """Return the name."""
        return f"{self._platform_name} {self._name}"

    @property
    def should_poll(self) -> bool:
        """Data is delivered by the hub"""
        return False

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self._key}"

    async def async_select_option(self, option: str) -> None:
        """Change the select option."""
        self._hub.write_register(unit=1, address=self._register, payload=get_payload(self._option_dict, option))

        self._hub.data[self._key] = option
        self.async_write_ha_state()