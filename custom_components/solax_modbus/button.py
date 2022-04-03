from .const import ATTR_MANUFACTURER, DOMAIN, BUTTON_TYPES, CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR
from homeassistant.components.button import PLATFORM_SCHEMA, ButtonEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from typing import Any, Dict, Optional
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    hub_name = entry.data[CONF_NAME]
    modbus_addr = entry.data.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    hub = hass.data[DOMAIN][hub_name]["hub"]

    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }
    
    entities = []
    
    for button_info in BUTTON_TYPES:
        button = SolaXModbusButton(
            hub_name,
            hub,
            modbus_addr,
            device_info,
            button_info[0],
            button_info[1],
            button_info[2],
            button_info[3],
        )
        entities.append(button)

    async_add_entities(entities)
    return True

class SolaXModbusButton(ButtonEntity):
    """Representation of an SolaX Modbus button."""

    def __init__(self,
                 platform_name,
                 hub,
                 modbus_addr,
                 device_info,
                 name,
                 key,
                 register,
                 value
    ) -> None:
        """Initialize the button."""
        self._platform_name = platform_name
        self._hub = hub
        self._modbus_addr = modbus_addr,
        self._device_info = device_info
        self._name = name
        self._key = key
        self._register = register
        self._value = value

    @property
    def name(self) -> str:
        """Return the name."""
        return f"{self._platform_name} {self._name}"

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self._key}"

    async def async_press(self) -> None:
        """Write the button value."""

        self._hub.write_register(unit=self._modbus_addr, address=self._register, payload=self._value)