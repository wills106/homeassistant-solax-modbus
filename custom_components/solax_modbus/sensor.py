from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.components.sensor import SensorEntity
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass


import homeassistant.util.dt as dt_util

from .const import ATTR_MANUFACTURER, DOMAIN, SENSOR_TYPES # GEN3_X1_SENSOR_TYPES, GEN3_X3_SENSOR_TYPES, GEN4_SENSOR_TYPES, GEN4_X1_SENSOR_TYPES, GEN4_X3_SENSOR_TYPES
#from .const import X1_EPS_SENSOR_TYPES, X3_EPS_SENSOR_TYPES, GEN4_X1_EPS_SENSOR_TYPES, GEN4_X3_EPS_SENSOR_TYPES, SolaXModbusSensorEntityDescription
from .const import REG_INPUT, REG_HOLDING, REGISTER_U32, REGISTER_S32
from .const import matchInverterWithMask, SolaXModbusSensorEntityDescription


_LOGGER = logging.getLogger(__name__)



@dataclass
class block():
    start: int = None # start address of the block
    end: int = None # end address of the block
    order16 = None # byte endian for 16bit registers
    order32 = None # word endian for 32bit registers
    descriptions: dict = None

def splitInBlocks( descriptions ):
    start = None
    end = None
    blocks = []
    for reg in descriptions:
        if descriptions[reg].newblock or ((reg - start) > 120): 
            if ((end - start) > 0): 
                newblock = block(start = start, end = end, order16 = descriptions[first].order16, order32 = descriptions[first].order32, descriptions = descriptions)
                blocks.append(newblock)
            else: _LOGGER(f"newblock declaration found for empty block")
        else: 
            if start == None: start = reg
            if descriptions[reg].unit in (REGISTER_S32, REGISTER_U32):  end = reg + 2
            else: end = reg + 1
    return blocks


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.data: hub_name = entry.data[CONF_NAME] # old style - remove soon
    else: hub_name = entry.options[CONF_NAME] # new format
    hub = hass.data[DOMAIN][hub_name]["hub"]

    device_info = {
        "identifiers": {(DOMAIN, hub_name)},
        "name": hub_name,
        "manufacturer": ATTR_MANUFACTURER,
    }

    entities = []
    holdingRegs = {}
    inputRegs  = {}
    holdingOrder16 = {} # all entities should have the same order
    inputOrder16   = {} # all entities should have the same order
    holdingOrder32 = {} # all entities should have the same order
    inputOrder32   = {} # all entities should have the same order

    for sensor_description in SENSOR_TYPES:
        if matchInverterWithMask(hub._invertertype,sensor_description.allowedtypes, hub.seriesnumber, sensor_description.blacklist):
            sensor = SolaXModbusSensor(
                hub_name,
                hub,
                device_info,
                sensor_description,
            )
            entities.append(sensor)
            if sensor_description.register < 0: _LOGGER.warning(f"entity without modbus register address found: {sensor_description.key}")
            else:
                if sensor_description.register_type == REG_HOLDING:
                    if sensor_description.register in holdingRegs: _LOGGER.warning(f"holding register already used: {sensor_description.register:x} {sensor_description.key}")
                    else:
                        holdingRegs[sensor_description.register] = sensor_description
                        holdingOrder16[sensor_description.order16] = True
                        holdingOrder32[sensor_description.order32] = True
                elif sensor_description.register_type == REG_INPUT:
                    if sensor_description.register in inputRegs: _LOGGER.warning(f"input register already declared: {sensor_description.register:x} {sensor_description.key}")
                    else:
                        inputRegs[sensor_description.register] = sensor_description
                        inputOrder16[sensor_description.order16] = True
                        inputOrder32[sensor_description.order32] = True
                else: _LOGGER.warning(f"entity declaration without register_type found: {sensor_description.key}")
    async_add_entities(entities)
    # sort the registers for this type of inverter
    holdingRegs = dict(sorted(holdingRegs.items()))
    inputRegs   = dict(sorted(inputRegs.items()))
    # check for consistency
    if (len(inputOrder32)>1) or (len(holdingOrder32)>1): _LOGGER.warning(f"inconsistent Big or Little Endian declaration for 32bit registers")
    if (len(inputOrder16)>1) or (len(holdingOrder16)>1): _LOGGER.warning(f"inconsistent Big or Little Endian declaration for 16bit registers")
    #minHolding = None
    #minInput   = None
    #maxHolding = None
    #maxInput   = None
    holdingBlocks = splitInBlocks(holdingRegs)
    inputBlocks = splitInBlocks(inputRegs)
    """
    for reg in holdingRegs:
        if holdingRegs[reg].newblock : 
        if not minHolding: minHolding = reg
        maxHolding = reg
        _LOGGER.info(f"holdingReg 0x{reg:02x}: {holdingRegs[reg]}")
    for reg in inputRegs:
        if not minInput: minInput = reg
        maxInput = reg
        _LOGGER.info(f"inputReg 0x{reg:02x}: {inputRegs[reg]}")
    """
    # store results
    hass.data[DOMAIN][hub_name]["holdingBlocks"] = holdingBlocks
    hass.data[DOMAIN][hub_name]["inputBlocks"]   = inputBlocks
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
        if self._attr_scale != 1:
            if self.entity_description.key in self._hub.data:
                return self._hub.data[self.entity_description.key]*self._attr_scale
            
        else: # strings and other data types cannot be scaled
            if self.entity_description.key in self._hub.data:
                return self._hub.data[self.entity_description.key]