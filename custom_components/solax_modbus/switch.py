import logging
from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_MODBUS_ADDR,
    DEBOUNCE_TIME,
    DEFAULT_MODBUS_ADDR,
    DOMAIN,
    WRITE_DATA_LOCAL,
    WRITE_MULTISINGLE_MODBUS,
    WRITE_SINGLE_MODBUS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    if entry.data:  # old style - remove soon
        hub_name = entry.data[CONF_NAME]
        modbus_addr = entry.data.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    else:
        hub_name = entry.options[CONF_NAME]  # new style
        modbus_addr = entry.options.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)  # new style
    hub = hass.data[DOMAIN][hub_name]["hub"]

    plugin = hub.plugin  # getPlugin(hub_name)
    inverter_name_suffix = ""
    if hub.inverterNameSuffix is not None and hub.inverterNameSuffix != "":
        inverter_name_suffix = hub.inverterNameSuffix + " "

    entities = []

    for switch_info in plugin.SWITCH_TYPES:
        if plugin.matchInverterWithMask(
            hub._invertertype, switch_info.allowedtypes, hub.seriesnumber, switch_info.blacklist
        ):
            if not (switch_info.name.startswith(inverter_name_suffix)):
                switch_info.name = inverter_name_suffix + switch_info.name
            switch = SolaXModbusSwitch(hub_name, hub, modbus_addr, hub.device_info, switch_info)
            if switch_info.value_function:
                hub.computedSwitches[switch_info.key] = switch_info
            if switch_info.sensor_key is not None:
                hub.writeLocals[switch_info.sensor_key] = switch_info
            dependency_key = getattr(switch_info, "sensor_key", switch_info.key)
            if dependency_key != switch_info.key:
                hub.entity_dependencies.setdefault(dependency_key, []).append(switch_info.key)  # can be more than one

            # register dependency chain
            deplist = switch_info.depends_on
            if isinstance(deplist, str):
                deplist = (deplist,)
            if isinstance(
                deplist,
                (
                    list,
                    tuple,
                ),
            ):
                _LOGGER.debug(f"{hub.name}: {switch_info.key} depends on entities {deplist}")
                for dep_on in deplist:  # register inter-sensor dependencies (e.g. for value functions)
                    if dep_on != switch_info.key:
                        hub.entity_dependencies.setdefault(dep_on, []).append(switch_info.key)  # can be more than one

            hub.switchEntities[switch_info.key] = switch  # Store the switch entity
            entities.append(switch)

    providers = hass.data.get(DOMAIN, {}).get("_switch_entity_providers", [])
    for provider in providers:
        try:
            device_info, platform_name, switch_descriptions = provider(hub, hass, entry)
        except Exception as ex:
            _LOGGER.error(f"{hub_name}: switch provider failed: {ex}")
            continue
        if not switch_descriptions:
            continue
        for switch_info in switch_descriptions:
            switch = SolaXModbusSwitch(
                platform_name,
                hub,
                modbus_addr,
                device_info,
                switch_info,
            )
            if switch_info.value_function:
                hub.computedSwitches[switch_info.key] = switch_info
            if switch_info.sensor_key is not None:
                hub.writeLocals[switch_info.sensor_key] = switch_info
            dependency_key = getattr(switch_info, "sensor_key", switch_info.key)
            if dependency_key != switch_info.key:
                hub.entity_dependencies.setdefault(dependency_key, []).append(switch_info.key)
            hub.switchEntities[switch_info.key] = switch
            entities.append(switch)

    async_add_entities(entities)
    return True


class SolaXModbusSwitch(SwitchEntity, RestoreEntity):
    """Representation of an SolaX Modbus switch."""

    def __init__(self, platform_name, hub, modbus_addr, device_info, switch_info) -> None:
        super().__init__()
        self._platform_name = platform_name
        self._hub = hub
        self._modbus_addr = modbus_addr
        self._attr_device_info = device_info
        # self.entity_id = f"switch.{platform_name}_{switch_info.key}"
        self._name = switch_info.name
        self._key = switch_info.key
        self._register = switch_info.register
        self.entity_description = switch_info
        self._write_method = switch_info.write_method
        self._sensor_key = switch_info.sensor_key
        self._attr_is_on = False
        self._bit = switch_info.register_bit if switch_info.register_bit is not None else 0
        self._value_function = switch_info.value_function
        self._last_command_time = None  # Tracks last user action

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        self._attr_is_on = True
        self._last_command_time = datetime.now()  # Record user action time
        self.async_write_ha_state()
        await self._write_switch_to_modbus()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        self._attr_is_on = False
        self._last_command_time = datetime.now()  # Record user action time
        self.async_write_ha_state()
        await self._write_switch_to_modbus()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self.entity_description.write_method != WRITE_DATA_LOCAL:
            return
        last_state = await self.async_get_last_state()
        if not last_state or last_state.state in ("unknown", "unavailable"):
            return
        is_on = last_state.state == "on"
        self._attr_is_on = is_on
        if self._sensor_key is not None:
            self._hub.data[self._sensor_key] = 1 if is_on else 0
        self.async_write_ha_state()

    async def _write_switch_to_modbus(self):
        if self.entity_description.write_method == WRITE_DATA_LOCAL:
            if self._sensor_key is None:
                return
            self._hub.data[self._sensor_key] = 1 if self._attr_is_on else 0
            self._hub.localsUpdated = True
            try:
                self._hub._hass.bus.async_fire(
                    "solax_modbus_local_switch_changed",
                    {
                        "hub_name": self._hub._name,
                        "key": self._sensor_key,
                        "state": self._attr_is_on,
                    },
                )
            except Exception as ex:
                _LOGGER.debug(f"{self._hub.name}: local switch event failed: {ex}")
            return
        if self._value_function is None:
            _LOGGER.debug(f"No value function for switch {self._key}")
            return

        payload = self._value_function(self._bit, self._attr_is_on, self._sensor_key, self._hub.data)
        _LOGGER.debug(f"Writing {self._platform_name} {self._key} to register {self._register} with value {payload}")
        await self._hub.async_write_registers_single(unit=self._modbus_addr, address=self._register, payload=payload)

    @property
    def is_on(self):
        """Return the state of the switch."""
        # Prioritize user action within debounce time
        if self._last_command_time and ((datetime.now() - self._last_command_time) < DEBOUNCE_TIME):
            return self._attr_is_on

        # Otherwise, return the sensor state
        if self._sensor_key and (self._sensor_key in self._hub.data):
            sensvalue = self._hub.data.get(self._sensor_key, None)
            if sensvalue is not None:
                sensor_value = int(sensvalue)
            else:
                _LOGGER.error(
                    f"{self._hub.name}: Sensor {self._sensor_key} corresponding to switch {self._key} bit {self._bit} has no integer value {sensvalue}"
                )
                sensor_value = 0  # probably completely wrong, but at least we can continue with other entities
            return bool(sensor_value & (1 << self._bit))

        return self._attr_is_on

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self._key}"
