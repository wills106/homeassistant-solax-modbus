from homeassistant.components.sensor import SensorEntity
import logging
from typing import Optional, Dict, Any

from homeassistant.const import CONF_NAME
from homeassistant.core import callback
import homeassistant.util.dt as dt_util

from .const import ATTR_MANUFACTURER, DOMAIN, SENSOR_TYPES, GEN2_X1_SENSOR_TYPES, GEN3_X1_SENSOR_TYPES, GEN3_X3_SENSOR_TYPES, X1_EPS_SENSOR_TYPES, X3_EPS_SENSOR_TYPES, OPTIONAL_SENSOR_TYPES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    hub_name = entry.data[CONF_NAME]
    hub = hass.data[DOMAIN][hub_name]["hub"]

    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }

    entities = []
    for sensor_info in SENSOR_TYPES.values():
        sensor = SolaXModbusSensor(
            hub_name,
            hub,
            device_info,
            sensor_info[0],
            sensor_info[1],
            sensor_info[2],
            sensor_info[3],
            sensor_info[4],
            sensor_info[5] if len(sensor_info) > 5 else None,
            sensor_info[6] if len(sensor_info) > 6 else None,
        )
        entities.append(sensor)
    
    if hub.read_gen2x1 == True:
        for gen2_x1_info in GEN2_X1_SENSOR_TYPES.values():
            sensor = SolaXModbusSensor(
                hub_name,
                hub,
                device_info,
                gen2_x1_info[0],
                gen2_x1_info[1],
                gen2_x1_info[2],
                gen2_x1_info[3],
                gen2_x1_info[4],
                gen2_x1_info[5] if len(gen2_x1_info) > 5 else None,
                gen2_x1_info[6] if len(gen2_x1_info) > 6 else None,
            )
            entities.append(sensor)

    if hub.read_gen3x1 == True:
        for gen3_x1_info in GEN3_X1_SENSOR_TYPES.values():
            sensor = SolaXModbusSensor(
                hub_name,
                hub,
                device_info,
                gen3_x1_info[0],
                gen3_x1_info[1],
                gen3_x1_info[2],
                gen3_x1_info[3],
                gen3_x1_info[4],
                gen3_x1_info[5] if len(gen3_x1_info) > 5 else None,
                gen3_x1_info[6] if len(gen3_x1_info) > 6 else None,
            )
            entities.append(sensor)
            
    if hub.read_gen3x3 == True:
        for gen3_x3_info in GEN3_X3_SENSOR_TYPES.values():
            sensor = SolaXModbusSensor(
                hub_name,
                hub,
                device_info,
                gen3_x3_info[0],
                gen3_x3_info[1],
                gen3_x3_info[2],
                gen3_x3_info[3],
                gen3_x3_info[4],
                gen3_x3_info[5] if len(gen3_x3_info) > 5 else None,
                gen3_x3_info[6] if len(gen3_x3_info) > 6 else None,
            )
            entities.append(sensor)
            
    if hub.read_x1_eps == True:
        for x1_eps_info in X1_EPS_SENSOR_TYPES.values():
            sensor = SolaXModbusSensor(
                hub_name,
                hub,
                device_info,
                x1_eps_info[0],
                x1_eps_info[1],
                x1_eps_info[2],
                x1_eps_info[3],
                x1_eps_info[4],
                x1_eps_info[5] if len(x1_eps_info) > 5 else None,
                x1_eps_info[6] if len(x1_eps_info) > 6 else None,
            )
            entities.append(sensor)
            
    if hub.read_x3_eps == True:
        for x3_eps_info in X3_EPS_SENSOR_TYPES.values():
            sensor = SolaXModbusSensor(
                hub_name,
                hub,
                device_info,
                x3_eps_info[0],
                x3_eps_info[1],
                x3_eps_info[2],
                x3_eps_info[3],
                x3_eps_info[4],
                x3_eps_info[5] if len(x3_eps_info) > 5 else None,
                x3_eps_info[6] if len(x3_eps_info) > 6 else None,
            )
            entities.append(sensor)
            
    if hub.read_optional_sensors == True:
        for optional_sensors_info in OPTIONAL_SENSOR_TYPES.values():
            sensor = SolaXModbusSensor(
                hub_name,
                hub,
                device_info,
                optional_sensors_info[0],
                optional_sensors_info[1],
                optional_sensors_info[2],
                optional_sensors_info[3],
                optional_sensors_info[4],
                optional_sensors_info[5] if len(optional_sensors_info) > 5 else None,
                optional_sensors_info[6] if len(optional_sensors_info) > 6 else None,
            )
            entities.append(sensor)

    async_add_entities(entities)
    return True


class SolaXModbusSensor(SensorEntity):
    """Representation of an SolaX Modbus sensor."""

    def __init__(
        self,
        platform_name,
        hub,
        device_info,
        name,
        key,
        unit,
        icon,
        device_class,
        state_class,
        last_reset,
    ):
        """Initialize the sensor."""
        self._platform_name = platform_name
        self._hub = hub
        self._key = key
        self._name = name
        self._attr_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_device_info = device_info
        self._attr_state_class = state_class

        if last_reset == "today":
            self._attr_last_reset = (
                dt_util.now().today().replace(hour=0, minute=0, second=0, microsecond=0)
            )
        elif last_reset:
            self._attr_last_reset = dt_util.utc_from_timestamp(0)

        self._attr_should_poll = False

    async def async_added_to_hass(self):
        """Register callbacks."""
        self._hub.async_add_solax_modbus_sensor(self._modbus_data_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._hub.async_remove_solax_modbus_sensor(self._modbus_data_updated)

    @callback
    def _modbus_data_updated(self):
        self.async_write_ha_state()

    @callback
    def _update_state(self):
        if self._key in self._hub.data:
            self._state = self._hub.data[self._key]

    @property
    def name(self):
        """Return the name."""
        return f"{self._platform_name} {self._name}"

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self._key}"

    @property
    def state(self):
        """Return the state of the sensor."""
        if self._key in self._hub.data:
            return self._hub.data[self._key]
