from .const import ATTR_MANUFACTURER, DOMAIN, BUTTON_TYPES, CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR
from .const import matchInverterWithMask

from homeassistant.components.button import PLATFORM_SCHEMA, ButtonEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from typing import Any, Dict, Optional
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
    
    entities = []
    
    for button_info in BUTTON_TYPES:
        if matchInverterWithMask(hub._invertertype, button_info.allowedtypes, hub.seriesnumber, button_info.blacklist):
            button = SolaXModbusButton( hub_name, hub, modbus_addr, device_info, button_info )
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
                 button_info
    ) -> None:
        """Initialize the button."""
        self._platform_name = platform_name
        self._hub = hub
        self._modbus_addr = modbus_addr
        self._attr_device_info = device_info
        self._name = button_info.name
        self._key = button_info.key
        self._register = button_info.register
        self._command = button_info.command
        self._attr_icon = button_info.icon

    @property
    def name(self) -> str:
        """Return the name."""
        return f"{self._platform_name} {self._name}"

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self._key}"

    async def async_press(self) -> None:
        """Write the button value."""
        _LOGGER.info(f"writing {self._platform_name} button register {self._register} value {self._command}")
        self._hub.write_register(unit=self._modbus_addr, address=self._register, payload=self._command)