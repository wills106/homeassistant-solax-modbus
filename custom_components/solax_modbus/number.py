from .const import ATTR_MANUFACTURER, DOMAIN, CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR
from .const import WRITE_DATA_LOCAL, WRITE_MULTISINGLE_MODBUS, WRITE_SINGLE_MODBUS, TMPDATA_EXPIRY

# from .const import GEN2, GEN3, GEN4, X1, X3, HYBRID, AC, EPS
from homeassistant.components.number import PLATFORM_SCHEMA, NumberEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional
from time import time
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    if entry.data:  # old style - remove soon
        hub_name = entry.data[CONF_NAME]
        modbus_addr = entry.data.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    else:  # new style
        hub_name = entry.options[CONF_NAME]
        modbus_addr = entry.options.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    hub = hass.data[DOMAIN][hub_name]["hub"]

    plugin = hub.plugin  # getPlugin(hub_name)
    inverter_name_suffix = ""
    if hub.inverterNameSuffix is not None and hub.inverterNameSuffix != "":
        inverter_name_suffix = hub.inverterNameSuffix + " "

    entities = []
    for number_info in plugin.NUMBER_TYPES:
        newdescr = number_info
        if number_info.read_scale_exceptions:
            for (
                prefix,
                value,
            ) in number_info.read_scale_exceptions:
                if hub.seriesnumber.startswith(prefix):
                    newdescr = replace(number_info, read_scale=value)
        if plugin.matchInverterWithMask(
            hub._invertertype, newdescr.allowedtypes, hub.seriesnumber, newdescr.blacklist
        ):
            if not (newdescr.name.startswith(inverter_name_suffix)):
                newdescr.name = inverter_name_suffix + newdescr.name
            number = SolaXModbusNumber(hub_name, hub, modbus_addr, hub.device_info, newdescr)
            if newdescr.write_method == WRITE_DATA_LOCAL:
                hub.writeLocals[newdescr.key] = newdescr
            hub.numberEntities[newdescr.key] = number
            entities.append(number)
    async_add_entities(entities)
    return True


class SolaXModbusNumber(NumberEntity):
    """Representation of an SolaX Modbus number."""

    def __init__(
        self,
        platform_name,
        hub,
        modbus_addr,
        device_info,
        number_info,
        # read_scale
    ) -> None:
        """Initialize the number."""
        self._platform_name = platform_name
        self._hub = hub
        self._modbus_addr = modbus_addr
        self._attr_device_info = device_info
        self.entity_id = "number." + platform_name + "_" + number_info.key
        self._name = number_info.name
        self._key = number_info.key
        self._register = number_info.register
        self._fmt = number_info.fmt
        self._attr_native_min_value = number_info.native_min_value
        self._attr_native_max_value = number_info.native_max_value
        self._attr_scale = number_info.scale
        self.entity_description = number_info
        if number_info.max_exceptions:
            for (
                prefix,
                native_value,
            ) in number_info.max_exceptions:
                if hub.seriesnumber.startswith(prefix):
                    self._attr_native_max_value = native_value
        if number_info.min_exceptions_minus:
            for (
                prefix,
                native_value,
            ) in number_info.min_exceptions_minus:
                if hub.seriesnumber.startswith(prefix):
                    self._attr_native_min_value = -native_value
        self._attr_native_step = number_info.native_step
        self._attr_native_unit_of_measurement = number_info.native_unit_of_measurement
        self._state = number_info.state  # not used AFAIK
        self.entity_description = number_info
        self._write_method = number_info.write_method

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await self._hub.async_add_solax_modbus_sensor(self)

    async def async_will_remove_from_hass(self) -> None:
        await self._hub.async_remove_solax_modbus_sensor(self)

    """ remove duplicate declaration
    async def async_set_value(self, native_value: float) -> None:
    	return self._hub.data[self._state]
    """

    @callback
    def modbus_data_updated(self) -> None:
        self.async_write_ha_state()

    @property
    def name(self) -> str:
        """Return the name."""
        return f"{self._platform_name} {self._name}"

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self._key}"

    @property
    def native_value(self) -> float:
        descr = self.entity_description
        if descr.prevent_update:
            if self._hub.tmpdata_expiry.get(descr.key, 0) > time():
                val = self._hub.tmpdata.get(descr.key, None)
                if val == None:
                    _LOGGER.warning(f"cannot find tmpdata for {descr.key} - setting value to zero")
                    val = 0
                if descr.read_scale and self._hub.tmpdata[self._key]:
                    res = val * descr.read_scale
                else:
                    res = val
                # _LOGGER.debug(f"prevent_update returning native value {descr.key} : {res}")
                return res
            else:  # expired
                if self._hub.tmpdata_expiry.get(descr.key, 0) > 0:
                    self._hub.localsUpdated = True
                self._hub.tmpdata_expiry[descr.key] = 0  # update locals only once
        if self._key in self._hub.data:
            try:
                val = self._hub.data[self._key] * descr.read_scale
            except:
                val = self._hub.data[self._key]
            return val
        else:  # first time initialize
            if descr.initvalue == None:
                return None
            else:
                res = descr.initvalue
                if self._attr_native_max_value != None:
                    res = min(res, self._attr_native_max_value)
                if self._attr_native_min_value != None:
                    res = max(res, self._attr_native_min_value)
                self._hub.data[self._key] = res
                # _LOGGER.warning(f"****** (debug) initializing {self._key}  = {res}")
                return res

    async def async_set_native_value(self, value: float) -> None:
        """Change the number value."""
        payload = value
        if self._fmt == "i":
            payload = int(value / (self._attr_scale * self.entity_description.read_scale))
        elif self._fmt == "f":
            payload = int(value / (self._attr_scale * self.entity_description.read_scale))
        if self._write_method == WRITE_MULTISINGLE_MODBUS:
            _LOGGER.info(
                f"writing {self._platform_name} {self._key} number register {self._register} value {payload} after div by readscale {self.entity_description.read_scale} scale {self._attr_scale}"
            )
            await self._hub.async_write_registers_single(
                unit=self._modbus_addr, address=self._register, payload=payload
            )
        elif self._write_method == WRITE_SINGLE_MODBUS:
            _LOGGER.info(
                f"writing {self._platform_name} {self._key} number register {self._register} value {payload} after div by readscale {self.entity_description.read_scale} scale {self._attr_scale}"
            )
            await self._hub.async_write_register(unit=self._modbus_addr, address=self._register, payload=payload)
        elif self._write_method == WRITE_DATA_LOCAL:
            _LOGGER.info(f"*** local data written {self._key}: {payload}")
            # corresponding_sensor = self._hub.preventSensors.get(self.entity_description.key, None)
            if (
                self.entity_description.prevent_update
            ):  # if corresponding_sensor: # only if corresponding sensor has prevent_update=True
                self._hub.tmpdata[self.entity_description.key] = payload
                self._hub.tmpdata_expiry[self.entity_description.key] = time() + TMPDATA_EXPIRY
                # corresponding_sensor.async_write_ha_state()
            self._hub.localsUpdated = True  # mark to save permanently
        self._hub.data[self._key] = value / self.entity_description.read_scale
        # _LOGGER.info(f"*** data written part 2 {self._key}: {self._hub.data[self._key]}")
        self.async_write_ha_state()  # is this needed ?
