import logging
from datetime import datetime
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_MODBUS_ADDR,
    DEBOUNCE_TIME,
    DEFAULT_MODBUS_ADDR,
    DOMAIN,
    WRITE_DATA_LOCAL,
    WRITE_MULTISINGLE_MODBUS,
    BaseModbusSwitchEntityDescription,
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

    for switch_info in plugin.SWITCH_TYPES:
        if (
            plugin.matchInverterWithMask(hub._invertertype, switch_info.allowedtypes, hub.seriesnumber, switch_info.blacklist)
            and matches_modbus_protocol(hub, switch_info)
            and hub.device_group_enabled(switch_info.device_group)
        ):
            device_info = hub.group_device_info(switch_info.device_group) if switch_info.device_group else hub.device_info

            def factory(di: Any = device_info, si: Any = switch_info) -> SolaXModbusSwitch:
                return SolaXModbusSwitch(hub_name, hub, modbus_addr, di, si)

            switch = factory()
            if switch_info.value_function:
                hub.computedSwitches[switch_info.key] = switch_info
            if switch_info.write_method == WRITE_DATA_LOCAL and switch_info.sensor_key is not None:
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
                _LOGGER.debug("%s: %s depends on entities %s", hub.name, switch_info.key, deplist)
                for dep_on in deplist:  # register inter-sensor dependencies (e.g. for value functions)
                    if dep_on != switch_info.key:
                        hub.entity_dependencies.setdefault(dep_on, []).append(switch_info.key)  # can be more than one

            active = matches_active_when(hub, switch_info)
            if switch_info.active_when is not None:
                hub.register_gated_entity(switch_info, factory, async_add_entities, hub.switchEntities, "switch", switch if active else None)
            if active:
                hub.switchEntities[switch_info.key] = switch
                entities.append(switch)
            else:
                hub.switchEntities.pop(switch_info.key, None)

    providers = hass.data.get(DOMAIN, {}).get("_switch_entity_providers", [])
    for provider in providers:
        try:
            device_info, platform_name, switch_descriptions = provider(hub, hass, entry)
        except Exception as ex:
            _LOGGER.error("%s: switch provider failed: %s", hub_name, ex)
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
            if switch_info.write_method == WRITE_DATA_LOCAL and switch_info.sensor_key is not None:
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

    _attr_has_entity_name = True
    entity_description: BaseModbusSwitchEntityDescription

    def __init__(
        self,
        platform_name: str,
        hub: Any,
        modbus_addr: int,
        device_info: DeviceInfo,
        switch_info: BaseModbusSwitchEntityDescription,
    ) -> None:
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
        self._last_command_time: datetime | None = None  # Tracks last user action

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_set_state(False)

    async def _async_set_state(self, is_on: bool) -> None:
        """Write and publish a new state only after the write was accepted."""
        await self._write_switch_to_modbus(is_on)
        self._attr_is_on = is_on
        self._last_command_time = datetime.now()  # Record user action time
        if self.entity_description.write_method != WRITE_DATA_LOCAL:
            # Publish the accepted value locally: the readback register only catches up
            # on a later poll, and entities depending on this key must not see the old value.
            self._hub.data[self._sensor_key or self._key] = 1 if is_on else 0
        self.async_write_ha_state()
        await self._hub.async_refresh_gated_entities()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.entity_description.write_method != WRITE_DATA_LOCAL:
            if self._sensor_key is not None and self._sensor_key in self._hub.data:
                return
            last_state = await self.async_get_last_state()
            if last_state and last_state.state in ("on", "off"):
                self._attr_is_on = last_state.state == "on"
            return
        self.async_on_remove(self.hass.bus.async_listen("solax_modbus_local_data_loaded", self._handle_local_data_loaded))
        if self._sensor_key is not None and self._sensor_key in self._hub.data:
            self.async_write_ha_state()
            return
        last_state = await self.async_get_last_state()
        if not last_state or last_state.state in ("unknown", "unavailable"):
            return
        is_on = last_state.state == "on"
        self._attr_is_on = is_on
        if self._sensor_key is not None:
            self._hub.data[self._sensor_key] = 1 if is_on else 0
        self.async_write_ha_state()

    @callback
    def _handle_local_data_loaded(self, event: Any) -> None:
        if (event.data or {}).get("hub_name") != self._hub._name:
            return
        self.async_write_ha_state()

    async def _write_switch_to_modbus(self, is_on: bool) -> None:
        if self.entity_description.write_method == WRITE_DATA_LOCAL:
            if self._sensor_key is None:
                return
            self._hub.data[self._sensor_key] = 1 if is_on else 0
            self._hub.localsUpdated = True
            try:
                self._hub._hass.bus.async_fire(
                    "solax_modbus_local_switch_changed",
                    {
                        "entry_id": self._hub.entry.entry_id,
                        "hub_name": self._hub._name,
                        "key": self._sensor_key,
                        "state": is_on,
                    },
                )
            except Exception as ex:
                _LOGGER.debug("%s: local switch event failed: %s", self._hub.name, ex)
            return
        if self._value_function is None:
            _LOGGER.debug("No value function for switch %s", self._key)
            return

        payload: int = self._value_function(self._bit, is_on, self._sensor_key, self._hub.data)
        _LOGGER.debug(
            "Writing %s %s to register %s with value %s method %s", self._platform_name, self._key, self._register, payload, self._write_method
        )
        if self._write_method == WRITE_MULTISINGLE_MODBUS:
            await self._hub.async_write_registers_single(
                unit=self._modbus_addr,
                address=self._register,
                payload=payload,
                register_data_type=getattr(self.entity_description, "register_data_type", None),
            )
        else:
            await self._hub.async_write_register(
                unit=self._modbus_addr,
                address=self._register,
                payload=payload,
                register_data_type=getattr(self.entity_description, "register_data_type", None),
            )

    @property
    def is_on(self) -> bool | None:
        """Return the state of the switch."""
        # Prioritize user action within debounce time
        if self._last_command_time and ((datetime.now() - self._last_command_time).total_seconds() < DEBOUNCE_TIME.total_seconds()):
            return self._attr_is_on

        # Otherwise, return the sensor state
        if self._sensor_key and (self._sensor_key in self._hub.data):
            sensvalue = self._hub.data.get(self._sensor_key, None)
            if sensvalue is None:
                # Readback register temporarily unreadable (failed or quarantined read);
                # report unknown instead of a fabricated off state, like selects do.
                _LOGGER.debug("%s: Sensor %s for switch %s has no value yet, state unknown", self._hub.name, self._sensor_key, self._key)
                return None
            try:
                sensor_value = int(sensvalue)
            except (TypeError, ValueError):
                _LOGGER.debug(
                    "%s: Sensor %s for switch %s has non-integer value %r, state unknown",
                    self._hub.name,
                    self._sensor_key,
                    self._key,
                    sensvalue,
                )
                return None
            return bool(sensor_value & (1 << self._bit))

        return self._attr_is_on

    @property
    def name(self) -> str:
        """Return the entity name (description name only — the device name provides context)."""
        return str(self._name or self._key)

    @property
    def unique_id(self) -> str | None:
        return f"{self._platform_name}_{self._key}"
