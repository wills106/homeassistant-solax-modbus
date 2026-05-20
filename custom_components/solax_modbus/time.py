import logging
from dataclasses import replace
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
    inverter_name_suffix = ""
    if hub.inverterNameSuffix is not None and hub.inverterNameSuffix != "":
        inverter_name_suffix = hub.inverterNameSuffix + " "

    entities = []
    for time_info in plugin.TIME_TYPES:
        if plugin.matchInverterWithMask(hub._invertertype, time_info.allowedtypes, hub.seriesnumber, time_info.blacklist) and matches_modbus_protocol(
            hub, time_info
        ):
            if not (time_info.name.startswith(inverter_name_suffix)):
                time_info = replace(time_info, name=inverter_name_suffix + time_info.name)
            time_entity = SolaXModbusTimeEntity(hub_name, hub, modbus_addr, hub.device_info, time_info)
            if time_info.write_method == WRITE_DATA_LOCAL:
                if time_info.initvalue is not None:
                    hub.data[time_info.key] = time_info.initvalue
                hub.writeLocals[time_info.key] = time_info
            hub.timeEntities[time_info.key] = time_entity
            entities.append(time_entity)

    async_add_entities(entities)


class SolaXModbusTimeEntity(TimeEntity):
    """Representation of an SolaX Modbus time entity."""

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
        # wordcount for separate register format (e.g., hours and minutes in adjacent registers)
        self._wordcount = getattr(time_info, "wordcount", None) or 1

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await self._hub.async_add_solax_modbus_sensor(self)

    async def async_will_remove_from_hass(self) -> None:
        await self._hub.async_remove_solax_modbus_sensor(self)

    @callback
    def modbus_data_updated(self) -> None:
        """Update the cached native_value when modbus data is updated."""
        # Clear the cached property by setting _attr_native_value
        self._attr_native_value = self._parse_time_value()
        self.async_write_ha_state()

    def _parse_time_value(self) -> datetime_time | None:
        """Parse the time value from hub.data and return a datetime.time object.

        This method is called by modbus_data_updated to update the cached native_value.
        It returns a datetime.time object as required by Home Assistant's TimeEntity.
        """
        # Use self._key directly for data lookup, consistent with select.py behavior
        # The sensor_key attribute is only used for dependency tracking, not data lookup
        if self._key not in self._hub.data:
            _LOGGER.debug(f"{self._platform_name}: key {self._key} not in data")
            return None

        time_val = self._hub.data[self._key]
        _LOGGER.debug(f"{self._platform_name}: parsing value for {self._key}, value={time_val}, type={type(time_val).__name__}")

        # Handle datetime objects directly - extract the time component
        if isinstance(time_val, datetime):
            return time_val.time()

        # Handle string time values in hh:mm format
        if isinstance(time_val, str):
            # Strip whitespace and handle empty strings
            time_val = time_val.strip()
            if not time_val:
                _LOGGER.debug(f"{self._platform_name}: empty time string for {self._key}")
                return None
            # Common time formats
            for fmt in ["%H:%M", "%H:%M:%S", "%H:%M:%S.%f"]:
                try:
                    parsed = datetime.strptime(time_val, fmt)
                    _LOGGER.debug(f"{self._platform_name}: parsed {self._key} as {fmt}: {parsed.time()}")
                    return parsed.time()
                except ValueError:
                    continue
            # Try parsing as HH:MM:SS with seconds (8 chars like 05:25:30)
            if len(time_val) == 8 and time_val[2] == ":" and time_val[5] == ":":
                try:
                    parsed = datetime.strptime(time_val, "%H:%M:%S")
                    _LOGGER.debug(f"{self._platform_name}: parsed {self._key} as HH:MM:SS: {parsed.time()}")
                    return parsed.time()
                except ValueError:
                    pass
            # Try parsing as HH:MM (5 chars like 05:25)
            if len(time_val) == 5 and time_val[2] == ":":
                try:
                    parsed = datetime.strptime(time_val, "%H:%M")
                    _LOGGER.debug(f"{self._platform_name}: parsed {self._key} as HH:MM: {parsed.time()}")
                    return parsed.time()
                except ValueError:
                    pass
            # If we get here, the string format was not recognized
            _LOGGER.debug(f"{self._platform_name}: unrecognized time format for {self._key}: {time_val}")
            return None

        # Handle numeric values (e.g., from value_function_gen4time or value_function_gen23time)
        if isinstance(time_val, (int, float)):
            # Try to convert to string and parse
            time_str = str(time_val)
            if len(time_str) == 5 and time_str[2] == ":":
                try:
                    parsed = datetime.strptime(time_str, "%H:%M")
                    _LOGGER.debug(f"{self._platform_name}: parsed numeric {self._key} as HH:MM: {parsed.time()}")
                    return parsed.time()
                except ValueError:
                    pass
            if len(time_str) == 8 and time_str[2] == ":" and time_str[5] == ":":
                try:
                    parsed = datetime.strptime(time_str, "%H:%M:%S")
                    _LOGGER.debug(f"{self._platform_name}: parsed numeric {self._key} as HH:MM:SS: {parsed.time()}")
                    return parsed.time()
                except ValueError:
                    pass

        _LOGGER.debug(f"{self._platform_name}: time value for {self._key} is not a string or datetime: {type(time_val)}")
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
    def name(self) -> str:
        """Return the name."""
        return f"{self._platform_name} {self._name}"

    @property
    def should_poll(self) -> bool:
        """Data is delivered by by the hub"""
        return False

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
        for key, time_val in self._option_dict.items():
            if time_val == time_str:
                payload = key
                break

        if payload is None:
            _LOGGER.warning(f"{self._platform_name}: could not find payload for time {time_str}")
            return

        _LOGGER.info(f"writing {self._platform_name} time register {self._register} value {payload} with method {self._write_method}")

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
                    f"{self._platform_name}: writing separate registers - hours={hours} to reg {self._register}, "
                    f"minutes={minutes} to reg {self._register + 1}"
                )
                # Write hours to first register
                await self._hub.async_write_register(unit=self._modbus_addr, address=self._register, payload=hours)
                # Write minutes to second register (adjacent)
                await self._hub.async_write_register(unit=self._modbus_addr, address=self._register + 1, payload=minutes)
            else:
                # Standard single register write
                await self._hub.async_write_register(unit=self._modbus_addr, address=self._register, payload=payload)
        elif self._write_method == WRITE_DATA_LOCAL:
            _LOGGER.info(f"*** local data written {self._key}: {time_str}")
            self._hub.localsUpdated = True  # mark to save permanently
            self._hub.data[self._key] = time_str

        self.async_write_ha_state()

    async def async_set_time(self, time_val: datetime_time) -> None:
        """Set the time value (deprecated, use async_set_value instead)."""
        await self.async_set_value(time_val)
