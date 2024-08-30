from .const import ATTR_MANUFACTURER, DOMAIN, CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR
from .const import WRITE_DATA_LOCAL, WRITE_MULTISINGLE_MODBUS, WRITE_SINGLE_MODBUS
from homeassistant.components.select import PLATFORM_SCHEMA, SelectEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from typing import Any, Dict, Optional
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities) -> None:
    if entry.data: # old style - remove soon
        hub_name = entry.data[CONF_NAME]
        modbus_addr = entry.data.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    else:
        hub_name = entry.options[CONF_NAME] # new style
        modbus_addr = entry.options.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR) # new style
    hub = hass.data[DOMAIN][hub_name]["hub"]

    plugin = hub.plugin #getPlugin(hub_name)
    inverter_name_suffix = ""
    if hub.inverterNameSuffix is not None and hub.inverterNameSuffix != "":
        inverter_name_suffix = hub.inverterNameSuffix + " "

    entities = []
    for select_info in plugin.SELECT_TYPES:
        if plugin.matchInverterWithMask(hub._invertertype, select_info.allowedtypes, hub.seriesnumber , select_info.blacklist):
            select_info.reverse_option_dict = {v: k for k, v in select_info.option_dict.items()}
            if not (select_info.name.startswith(inverter_name_suffix)): select_info.name = inverter_name_suffix + select_info.name
            select = SolaXModbusSelect(hub_name, hub, modbus_addr, hub.device_info, select_info)
            if select_info.write_method==WRITE_DATA_LOCAL:
                if (select_info.initvalue is not None): hub.data[select_info.key] = select_info.initvalue
                hub.writeLocals[select_info.key] = select_info
            entities.append(select)

    async_add_entities(entities)
    return True


class SolaXModbusSelect(SelectEntity):
    """Representation of an SolaX Modbus select."""

    def __init__(self,
                 platform_name,
                 hub,
                 modbus_addr,
                 device_info,
                 select_info
    ) -> None:
        """Initialize the selector."""
        self._platform_name = platform_name
        self._hub = hub
        self._modbus_addr = modbus_addr
        self._attr_device_info = device_info
        self.entity_id = "select." + platform_name + "_" + select_info.key
        self._name = select_info.name
        self._key = select_info.key
        self._register = select_info.register
        self._option_dict = select_info.option_dict
        self.entity_description = select_info
        self._attr_options = list(select_info.option_dict.values())
        self._write_method = select_info.write_method

    async def async_added_to_hass(self):
        """Register callbacks."""
        await self._hub.async_add_solax_modbus_sensor(self)

    async def async_will_remove_from_hass(self) -> None:
        await self._hub.async_remove_solax_modbus_sensor(self)
    @callback
    def modbus_data_updated(self):
        self.async_write_ha_state()

    @property
    def current_option(self) -> str:
        if self._key in self._hub.data:
            return self._hub.data[self._key]
        else:
            return self.entity_description.initvalue

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
        payload = self.entity_description.reverse_option_dict.get(option, None)
        if self._write_method == WRITE_MULTISINGLE_MODBUS:
            _LOGGER.info(f"writing {self._platform_name} select register {self._register} value {payload}")
            await self._hub.async_write_registers_single(unit=self._modbus_addr, address=self._register, payload=payload)
        elif self._write_method == WRITE_SINGLE_MODBUS:
            _LOGGER.info(f"writing {self._platform_name} select register {self._register} value {payload}")
            await self._hub.async_write_register(unit=self._modbus_addr, address=self._register, payload=payload)
        elif self._write_method == WRITE_DATA_LOCAL:
            _LOGGER.info(f"*** local data written {self._key}: {payload}")
            self._hub.localsUpdated = True # mark to save permanently
        self._hub.data[self._key] = option
        self.async_write_ha_state()