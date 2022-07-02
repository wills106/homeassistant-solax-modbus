from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.components.sensor import SensorEntity
import logging
from typing import Optional, Dict, Any


import homeassistant.util.dt as dt_util

from .const import ATTR_MANUFACTURER, DOMAIN, SENSOR_TYPES # GEN3_X1_SENSOR_TYPES, GEN3_X3_SENSOR_TYPES, GEN4_SENSOR_TYPES, GEN4_X1_SENSOR_TYPES, GEN4_X3_SENSOR_TYPES
#from .const import X1_EPS_SENSOR_TYPES, X3_EPS_SENSOR_TYPES, GEN4_X1_EPS_SENSOR_TYPES, GEN4_X3_EPS_SENSOR_TYPES, SolaXModbusSensorEntityDescription
from .const import matchInverterWithMask, SolaXModbusSensorEntityDescription


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

    for sensor_description in SENSOR_TYPES:
        if matchInverterWithMask(hub._invertertype,sensor_description.allowedtypes, hub.seriesnumber, sensor_description.blacklist):
            sensor = SolaXModbusSensor(
                hub_name,
                hub,
                device_info,
                sensor_description,
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
        description: SolaXModbusSensorEntityDescription,
    ):
        """Initialize the sensor."""
        self._platform_name = platform_name
        self._attr_device_info = device_info
        self._hub = hub
        self.entity_description: SolaXModbusSensorEntityDescription = description
        self._attr_scale = description.scale
        if description.scale_exceptions:
            for (prefix, value,) in description.scale_exceptions: 
                if hub.seriesnumber.startswith(prefix): self._attr_scale = value

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
        if self.entity_description.key in self._hub.data:
            self._state = self._hub.data[self.entity_description.key]

    @property
    def name(self):
        """Return the name."""
        return f"{self._platform_name} {self.entity_description.name}"

    @property
    def unique_id(self) -> Optional[str]:
        return f"{self._platform_name}_{self.entity_description.key}"  
    
    @property
    def native_value(self):
        """Return the state of the sensor."""
        return (
        	self._hub.data[self.entity_description.key]*self._attr_scale
        	if self.entity_description.key in self._hub.data
        	else None
        )