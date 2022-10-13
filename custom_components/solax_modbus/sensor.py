from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.components.sensor import SensorEntity
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import homeassistant.util.dt as dt_util

from .const import ATTR_MANUFACTURER, DOMAIN
from .const import getPlugin
from .const import REG_INPUT, REG_HOLDING, REGISTER_U32, REGISTER_S32, REGISTER_ULSB16MSB16, REGISTER_STR, REGISTER_WORDS, REGISTER_U8H, REGISTER_U8L
from .const import BaseModbusSensorEntityDescription
from homeassistant.components.sensor import SensorEntityDescription


_LOGGER = logging.getLogger(__name__)

INVALID_START = 99999


# =================================== sorting and grouping of entities ================================================

@dataclass
class block():
    start: int = None # start address of the block
    end: int = None # end address of the block
    order16: int = None # byte endian for 16bit registers
    order32: int = None # word endian for 32bit registers
    descriptions: Any = None
    regs: Any = None # sorted list of registers used in this block


def splitInBlocks( descriptions ):
    start = INVALID_START
    end = 0
    blocks = []
    curblockregs = []
    for reg in descriptions:
        descr = descriptions[reg]
        if (not type(descr) is dict) and (descr.newblock or ((reg - start) > 100)): 
            if ((end - start) > 0): 
                newblock = block(start = start, end = end, order16 = descriptions[start].order16, order32 = descriptions[start].order32, descriptions = descriptions, regs = curblockregs)
                blocks.append(newblock)
                start = INVALID_START
                end = 0
                curblockregs = []
            else: _LOGGER.warning(f"newblock declaration found for empty block")

        if start == INVALID_START: start = reg
        if type(descr) is dict: end = reg+1 # couple of byte values
        else:
            if descr.unit in (REGISTER_STR, REGISTER_WORDS,): 
                if (descr.wordcount): end = reg+descr.wordcount
                else: _LOGGER.warning(f"invalid or missing missing wordcount for {descr[reg].key}")
            elif descr.unit in (REGISTER_S32, REGISTER_U32, REGISTER_ULSB16MSB16,):  end = reg + 2
            else: end = reg + 1
        curblockregs.append(reg)
    if ((end-start)>0): # close last block
        newblock = block(start = start, end = end, order16 = descriptions[start].order16, order32 = descriptions[start].order32, descriptions = descriptions, regs = curblockregs)
        blocks.append(newblock)
    return blocks

# ========================================================================================================================

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
    holdingRegs  = {}
    inputRegs    = {}
    computedRegs = {}
    holdingOrder16 = {} # all entities should have the same order
    inputOrder16   = {} # all entities should have the same order
    holdingOrder32 = {} # all entities should have the same order
    inputOrder32   = {} # all entities should have the same order
     
    plugin = getPlugin(hub_name)
    for sensor_description in plugin.SENSOR_TYPES:
        if plugin.matchInverterWithMask(hub._invertertype,sensor_description.allowedtypes, hub.seriesnumber, sensor_description.blacklist):
            # apply scale exceptions early - ? might cause problems for users with multiple different inverter types
            newscale = sensor_description.scale
            normal_scale = not ((type(sensor_description.scale) is dict) or callable(sensor_description.scale))
            if normal_scale and sensor_description.scale_exceptions:
                for (prefix, value,) in sensor_description.scale_exceptions: 
                    if hub.seriesnumber.startswith(prefix): newscale = value
            sensor = SolaXModbusSensor(
                hub_name,
                hub,
                device_info,
                sensor_description,
                newscale,
            )
            entities.append(sensor)
            if (sensor_description.register < 0): # entity without modbus address
                if sensor_description.value_function:
                    computedRegs[sensor_description.key] = sensor_description
                else: _LOGGER.warning(f"entity without modbus register address and without value_function found: {sensor_description.key}")
            else:
                if sensor_description.register_type == REG_HOLDING:
                    if sensor_description.register in holdingRegs: # duplicate or 2 bytes in one register ?
                        if sensor_description.unit in (REGISTER_U8H, REGISTER_U8L,) and holdingRegs[sensor_description.register].unit in (REGISTER_U8H, REGISTER_U8L,) : 
                            first = holdingRegs[sensor_description.register]
                            holdingRegs[sensor_description.register] = { first.unit: first, sensor_description.unit: sensor_description }
                        else: _LOGGER.warning(f"holding register already used: 0x{sensor_description.register:x} {sensor_description.key}")
                    else:
                        holdingRegs[sensor_description.register] = sensor_description
                        holdingOrder16[sensor_description.order16] = True
                        holdingOrder32[sensor_description.order32] = True
                elif sensor_description.register_type == REG_INPUT:
                    if sensor_description.register in inputRegs: # duplicate or 2 bytes in one register ?
                        first = inputRegs[sensor_description.register]
                        inputRegs[sensor_description.register] = { first.unit: first, sensor_description.unit: sensor_description }
                        _LOGGER.warning(f"input register already declared: 0x{sensor_description.register:x} {sensor_description.key}")
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
    # split in blocks and store results
    hub.holdingBlocks = splitInBlocks(holdingRegs)
    hub.inputBlocks = splitInBlocks(inputRegs)
    hub.computedRegs = computedRegs

    _LOGGER.debug(f"holdingBlocks: {hub.holdingBlocks}")
    _LOGGER.debug(f"inputBlocks: {hub.inputBlocks}")
    _LOGGER.info(f"computedRegs: {hub.computedRegs}")
    return True



class SolaXModbusSensor(SensorEntity):
    """Representation of an SolaX Modbus sensor."""

    def __init__(
        self,
        platform_name,
        hub,
        device_info,
        description: BaseModbusSensorEntityDescription,
        newscale
    ):
        """Initialize the sensor."""
        self._platform_name = platform_name
        self._attr_device_info = device_info
        self._hub = hub
        self.entity_description: BaseModbusSensorEntityDescription = description
        self._attr_scale = newscale
        """"normal_scale = not ((type(description.scale) is dict) or callable(description.scale))
        if normal_scale: self._attr_scale = description.scale
        else: self._attr_scale = 1
        if description.scale_exceptions:
            #_LOGGER.info(f"sensor scale exceptions: {hub.seriesnumber}")
            for (prefix, value,) in description.scale_exceptions: 
                if hub.seriesnumber.startswith(prefix): 
                    #_LOGGER.info(f"sensorapplyig scale exceptions: {hub.seriesnumber} {value} normal scale: {normal_scale}")
                    if normal_scale: self._attr_scale = value
        """

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
        if self.entity_description.key in self._hub.data:
            return self._hub.data[self.entity_description.key]
        """
        if self._attr_scale != 1 and not ((type(self._attr_scale) is dict) or callable(self._attr_scale)):
            # is this extra scaling still needed ??
            if self.entity_description.key in self._hub.data:
                return self._hub.data[self.entity_description.key]*self._attr_scale
            
        else: # strings and other data types cannot be scaled
            if self.entity_description.key in self._hub.data:
                return self._hub.data[self.entity_description.key]
        """

  

