import logging
from datetime import datetime
from datetime import time as datetime_time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MODBUS_ADDR,
    DEFAULT_MODBUS_ADDR,
    DOMAIN,
    WRITE_DATA_LOCAL,
    WRITE_MULTISINGLE_MODBUS,
    WRITE_SINGLE_MODBUS,
    BaseModbusTimeEntityDescription,
    matches_active_when,
    matches_modbus_protocol,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    if entry.data:  # old style - remove soon
        hub_name = entry.data[CONF_NAME]
        modbus_addr = entry.data.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)
    else:
        hub_name = entry.options[CONF_NAME]  # new style
        modbus_addr = entry.options.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)  # new style
    hub = hass.data[DOMAIN][hub_name]["hub"]

    plugin = hub.plugin  # getPlugin(hub_name)
    entities = []
    for time_info in plugin.TIME_TYPES:
        if (
            plugin.matchInverterWithMask(hub._invertertype, time_info.allowedtypes, hub.seriesnumber, time_info.blacklist)
            and matches_modbus_protocol(hub, time_info)
            and hub.device_group_enabled(time_info.device_group)
        ):
            device_info = hub.group_device_info(time_info.device_group) if time_info.device_group else hub.device_info

            def factory(di: Any = device_info, ti: Any = time_info) -> SolaXModbusTimeEntity:
                return SolaXModbusTimeEntity(hub_name, hub, modbus_addr, di, ti)

            time_entity = factory()
            if time_info.write_method == WRITE_DATA_LOCAL:
                if time_info.initvalue is not None:
                    hub.data[time_info.key] = time_info.initvalue
                hub.writeLocals[time_info.key] = time_info
            active = matches_active_when(hub, time_info)
            if time_info.active_when is not None:
                hub.register_gated_entity(time_info, factory, async_add_entities, hub.timeEntities, "time", time_entity if active else None)
            if active:
                hub.timeEntities[time_info.key] = time_entity
                entities.append(time_entity)
            else:
                hub.timeEntities.pop(time_info.key, None)

    async_add_entities(entities)


class SolaXModbusTimeEntity(TimeEntity):
    """Representation of an SolaX Modbus time entity."""

    _attr_has_entity_name = True
    entity_description: BaseModbusTimeEntityDescription

    def __init__(
        self,
        platform_name: str,
        hub: Any,
        modbus_addr: int,
        device_info: DeviceInfo,
        time_info: Any,
    ) -> None:
        """Initialize the time entity."""
        self._platform_name = platform_name
        self._hub = hub
        self._modbus_addr = modbus_addr
        self._attr_device_info = device_info
        # self.entity_id = "time." + platform_name + "_" + time_info.key
        self._name = time_info.name
        self._key = time_info.key
        self._register = time_info.register
        self._option_dict = time_info.option_dict
        self.entity_description = time_info
        self._write_method = time_info.write_method
        self._attr_native_value = None
        # wordcount for separate register format (e.g., hours and minutes in adjacent registers)
        self._wordcount = getattr(time_info, "wordcount", None) or 1

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        if self._write_method == WRITE_DATA_LOCAL:
            self.async_on_remove(self.hass.bus.async_listen("solax_modbus_local_data_loaded", self._handle_local_data_loaded))
            self.modbus_data_updated()
            return

        if self.entity_description.register is None or self.entity_description.register < 0:
            return
        await self._hub.async_add_solax_modbus_sensor(self)

    async def async_will_remove_from_hass(self) -> None:
        if self._write_method == WRITE_DATA_LOCAL or self.entity_description.register is None or self.entity_description.register < 0:
            return
        await self._hub.async_remove_solax_modbus_sensor(self)

    @callback
    def modbus_data_updated(self) -> None:
        """Update the cached native_value when modbus data is updated."""
        # Clear the cached property by setting _attr_native_value
        self._attr_native_value = self._parse_time_value()
        self.async_write_ha_state()

    @callback
    def _handle_local_data_loaded(self, event: Any) -> None:
        if (event.data or {}).get("hub_name") != self._hub._name:
            return
        self.modbus_data_updated()

    def _parse_time_string(self, time_val: str) -> datetime_time | None:
        """Parse common time string formats into a datetime.time object."""
        time_val = time_val.strip()
        if not time_val:
            _LOGGER.debug("%s: empty time string for %s", self._platform_name, self._key)
            return None

        for fmt in ["%H:%M", "%H:%M:%S", "%H:%M:%S.%f"]:
            try:
                parsed = datetime.strptime(time_val, fmt).time()
                _LOGGER.debug("%s: parsed %s as %s: %s", self._platform_name, self._key, fmt, parsed)
                return parsed
            except ValueError:
                continue

        _LOGGER.debug("%s: unrecognized time format for %s: %s", self._platform_name, self._key, time_val)
        return None

    def _parse_time_value(self) -> datetime_time | None:
        """Parse the time value from hub.data and return a datetime.time object.

        This method is called by modbus_data_updated to update the cached native_value.
        It returns a datetime.time object as required by Home Assistant's TimeEntity.
        """
        # Use self._key directly for data lookup, consistent with select.py behavior
        # The sensor_key attribute is only used for dependency tracking, not data lookup
        if self._key not in self._hub.data:
            _LOGGER.debug("%s: key %s not in data", self._platform_name, self._key)
            return None

        time_val = self._hub.data[self._key]
        _LOGGER.debug("%s: parsing value for %s, value=%s, type=%s", self._platform_name, self._key, time_val, type(time_val).__name__)

        # Handle datetime objects directly - extract the time component
        if isinstance(time_val, datetime):
            return time_val.time()

        # Handle string time values in hh:mm format
        if isinstance(time_val, str):
            return self._parse_time_string(time_val)

        # Handle raw Modbus payloads by translating through the descriptor's option table.
        if isinstance(time_val, (int, float)):
            payload = int(time_val)
            if self._option_dict is not None:
                mapped_value = self._option_dict.get(payload)
                if mapped_value is not None:
                    return self._parse_time_string(mapped_value)
            _LOGGER.debug("%s: no time option mapping for %s payload %s", self._platform_name, self._key, payload)
            return None

        _LOGGER.debug("%s: time value for %s is not a string or datetime: %s", self._platform_name, self._key, type(time_val))
        return None

    @property
    def native_value(self) -> datetime_time | None:
        """Return the time value as a datetime.time object.

        This property is called by Home Assistant to get the current time value
        of the time entity. It must return a datetime.time object or None.
        Note: This is cached by Home Assistant, so we update _attr_native_value in modbus_data_updated().
        """
        return self._attr_native_value

    @property
    def should_poll(self) -> bool:
        """Data is delivered by by the hub"""
        return False

    @property
    def name(self) -> str:
        """Return the entity name (description name only — the device name provides context)."""
        return str(self._name or self._key)

    @property
    def unique_id(self) -> str | None:
        return f"{self._platform_name}_{self._key}"

    async def async_set_value(self, value: datetime_time | None) -> None:
        """Set the time value (required by Home Assistant time component)."""
        if value is None:
            return

        # Convert time to string
        time_str = value.strftime("%H:%M")

        # Find the corresponding payload from option_dict
        payload = None
        for key, time_val in (self._option_dict or {}).items():
            if time_val == time_str:
                payload = key
                break

        if payload is None:
            _LOGGER.warning("%s: could not find payload for time %s", self._platform_name, time_str)
            return

        _LOGGER.info("writing %s time register %s value %s with method %s", self._platform_name, self._register, payload, self._write_method)

        if self._write_method == WRITE_MULTISINGLE_MODBUS:
            await self._hub.async_write_registers_single(unit=self._modbus_addr, address=self._register, payload=payload)
        elif self._write_method == WRITE_SINGLE_MODBUS:
            # Handle separate register format (wordcount > 1)
            if self._wordcount and self._wordcount >= 2:
                # For TIME_OPTIONS_SEPARATE_REGISTERS format: payload = hours * 100 + minutes
                # Extract hours and minutes from the combined payload
                hours = payload // 100
                minutes = payload % 100
                _LOGGER.info(
                    "%s: writing separate registers - hours=%s to reg %s, minutes=%s to reg %s",
                    self._platform_name,
                    hours,
                    self._register,
                    minutes,
                    self._register + 1,
                )
                # Write hours to first register
                await self._hub.async_write_register(unit=self._modbus_addr, address=self._register, payload=hours)
                # Write minutes to second register (adjacent)
                await self._hub.async_write_register(unit=self._modbus_addr, address=self._register + 1, payload=minutes)
            else:
                # Standard single register write
                await self._hub.async_write_register(unit=self._modbus_addr, address=self._register, payload=payload)
        elif self._write_method == WRITE_DATA_LOCAL:
            _LOGGER.info("*** local data written %s: %s", self._key, time_str)
            self._hub.localsUpdated = True  # mark to save permanently

        self._hub.data[self._key] = time_str
        self._attr_native_value = value
        self.async_write_ha_state()

    async def async_set_time(self, time_val: datetime_time) -> None:
        """Set the time value (deprecated, use async_set_value instead)."""
        await self.async_set_value(time_val)
