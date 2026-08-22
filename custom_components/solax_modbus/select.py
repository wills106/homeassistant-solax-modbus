import logging
from dataclasses import replace
from time import time
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BUTTONREPEAT_FIRST,
    CONF_MODBUS_ADDR,
    DEFAULT_MODBUS_ADDR,
    DOMAIN,
    WRITE_DATA_LOCAL,
    WRITE_MULTISINGLE_MODBUS,
    WRITE_SINGLE_MODBUS,
    BaseModbusSelectEntityDescription,
    autorepeat_set,
    matches_active_when,
    matches_modbus_protocol,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    if entry.data:  # old style - remove soon
        hub_name = entry.data[CONF_NAME]
        modbus_addr = entry.data.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    else:
        hub_name = entry.options[CONF_NAME]  # new style
        modbus_addr = entry.options.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)  # new style
    hub = hass.data[DOMAIN][hub_name]["hub"]

    plugin = hub.plugin  # getPlugin(hub_name)
    entities = []
    for select_info in plugin.SELECT_TYPES:
        if (
            plugin.matchInverterWithMask(hub._invertertype, select_info.allowedtypes, hub.seriesnumber, select_info.blacklist)
            and matches_modbus_protocol(hub, select_info)
            and hub.device_group_enabled(select_info.device_group)
        ):
            select_info = replace(select_info, reverse_option_dict={v: k for k, v in select_info.option_dict.items()})
            device_info = hub.group_device_info(select_info.device_group) if select_info.device_group else hub.device_info

            def factory(di: Any = device_info, si: Any = select_info) -> SolaXModbusSelect:
                return SolaXModbusSelect(hub_name, hub, modbus_addr, di, si)

            select = factory()
            if select_info.write_method == WRITE_DATA_LOCAL:
                if select_info.initvalue is not None:
                    hub.data[select_info.key] = select_info.initvalue
                hub.writeLocals[select_info.key] = select_info
            hub.selectEntities[select_info.key] = select
            # Register autorepeat selects in computedEntities so they can use the unified autorepeat loop
            if select_info.value_function:
                hub.computedEntities[select_info.key] = select_info

            # register dependency chain
            deplist = select_info.depends_on
            if isinstance(deplist, str):
                deplist = (deplist,)
            if isinstance(
                deplist,
                (
                    list,
                    tuple,
                ),
            ):
                _LOGGER.debug("%s: %s depends on entities %s", hub.name, select_info.key, deplist)
                for dep_on in deplist:  # register inter-sensor dependencies (e.g. for value functions)
                    if dep_on != select_info.key:
                        hub.entity_dependencies.setdefault(dep_on, []).append(select_info.key)  # can be more than one
            # Use the explicit sensor_key if provided, otherwise fall back to the select's own key.
            dependency_key = getattr(select_info, "sensor_key", select_info.key)
            if dependency_key != select_info.key:
                hub.entity_dependencies.setdefault(dependency_key, []).append(select_info.key)  # can be more than one
            active = matches_active_when(hub, select_info)
            if select_info.active_when is not None:
                hub.register_gated_entity(select_info, factory, async_add_entities, hub.selectEntities, "select", select if active else None)
            if active:
                hub.selectEntities[select_info.key] = select
                entities.append(select)
            else:
                hub.selectEntities.pop(select_info.key, None)

    async_add_entities(entities)
    return True


class SolaXModbusSelect(SelectEntity):
    """Representation of an SolaX Modbus select."""

    _attr_has_entity_name = True
    entity_description: BaseModbusSelectEntityDescription

    def __init__(
        self,
        platform_name: str,
        hub: Any,
        modbus_addr: int,
        device_info: DeviceInfo,
        select_info: BaseModbusSelectEntityDescription,
    ) -> None:
        """Initialize the selector."""
        self._platform_name = platform_name
        self._hub = hub
        self._modbus_addr = modbus_addr
        self._attr_device_info = device_info
        # self.entity_id = "select." + platform_name + "_" + select_info.key
        self._name = select_info.name
        self._key = select_info.key
        self._register = select_info.register
        self._option_dict = select_info.option_dict
        self.entity_description = select_info
        self._attr_options = list(select_info.option_dict.values()) if select_info.option_dict else []
        self._write_method = select_info.write_method

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        if self._write_method == WRITE_DATA_LOCAL:
            self.async_on_remove(self.hass.bus.async_listen("solax_modbus_local_data_loaded", self._handle_local_data_loaded))
            self.async_write_ha_state()
            return

        # Skip hub registration for computed/internal entities (those without modbus registers)
        if self.entity_description.register is None or self.entity_description.register < 0:
            return
        await self._hub.async_add_solax_modbus_sensor(self)

    async def async_will_remove_from_hass(self) -> None:
        if self._write_method == WRITE_DATA_LOCAL or self.entity_description.register is None or self.entity_description.register < 0:
            return
        await self._hub.async_remove_solax_modbus_sensor(self)

    @callback
    def modbus_data_updated(self) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_local_data_loaded(self, event: Any) -> None:
        if (event.data or {}).get("hub_name") != self._hub._name:
            return
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        option_dict = self._option_dict or {}

        if self._key in self._hub.data:
            value = self._hub.data[self._key]
        else:
            value = self.entity_description.initvalue

        if value is None:
            return None

        # If the value is already one of the select labels, return it as-is.
        if isinstance(value, str) and value in self._attr_options:
            return value

        # Map raw register values back to the corresponding option labels.
        if value in option_dict:
            return option_dict[value]

        # Try again via integer coercion for values that may have been stored as strings/floats.
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            return None

        if int_value in option_dict:
            return option_dict[int_value]

        return None

    @property
    def name(self) -> str:
        """Return the entity name (description name only — the device name provides context)."""
        return str(self._name or self._key)

    @property
    def should_poll(self) -> bool:
        """Data is delivered by the hub"""
        return False

    @property
    def unique_id(self) -> str | None:
        return f"{self._platform_name}_{self._key}"

    async def async_select_option(self, option: str) -> None:
        """Change the select option."""
        reverse_dict = self.entity_description.reverse_option_dict
        payload: Any = reverse_dict.get(option, None) if reverse_dict else None
        if self._write_method == WRITE_MULTISINGLE_MODBUS:
            _LOGGER.info("writing %s select register %s value %s with method %s", self._platform_name, self._register, payload, self._write_method)
            await self._hub.async_write_registers_single(
                unit=self._modbus_addr,
                address=self._register,
                payload=payload,
                register_data_type=getattr(self.entity_description, "register_data_type", None),
            )
        elif self._write_method == WRITE_SINGLE_MODBUS:
            _LOGGER.info("writing %s select register %s value %s with method %s", self._platform_name, self._register, payload, self._write_method)
            await self._hub.async_write_register(
                unit=self._modbus_addr,
                address=self._register,
                payload=payload,
                register_data_type=getattr(self.entity_description, "register_data_type", None),
            )
        elif self._write_method == WRITE_DATA_LOCAL:
            _LOGGER.info("*** local data written %s: %s", self._key, payload)
            self._hub.localsUpdated = True  # mark to save permanently
        self._hub.data[self._key] = option
        await self._hub.async_refresh_gated_entities()

        # Handle autorepeat for selects with value_function (same pattern as buttons)
        if self.entity_description.value_function:
            res: Any = self.entity_description.value_function(BUTTONREPEAT_FIRST, self.entity_description, self._hub.data)
            if res:  # Only set autorepeat if value_function returns something (i.e., this value should be repeated)
                autorepeat_set(self._hub.data, self._key, time() + (10 * 365 * 24 * 60 * 60))

        self.async_write_ha_state()
