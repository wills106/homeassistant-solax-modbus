from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.components.sensor import SensorEntity
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import homeassistant.util.dt as dt_util

from .const import ATTR_MANUFACTURER, DOMAIN, SLEEPMODE_NONE, SLEEPMODE_ZERO
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
    #order16: int = None # byte endian for 16bit registers
    #order32: int = None # word endian for 32bit registers
    descriptions: Any = None
    regs: Any = None # sorted list of registers used in this block


def splitInBlocks( descriptions, block_size, auto_block_ignore_readerror ):
    start = INVALID_START
    end = 0
    blocks = []
    curblockregs = []
    for reg in descriptions:
        descr = descriptions[reg]
        if (not type(descr) is dict) and (descr.newblock or ((reg - start) > block_size)):
            if ((end - start) > 0): 
                _LOGGER.info(f"Starting new block at 0x{reg:x} ")
                if  ( (auto_block_ignore_readerror == True) or (auto_block_ignore_readerror == False) ) and not descr.newblock: # automatically created block
                    descr.ignore_readerror = auto_block_ignore_readerror
                #newblock = block(start = start, end = end, order16 = descriptions[start].order16, order32 = descriptions[start].order32, descriptions = descriptions, regs = curblockregs)
                newblock = block(start = start, end = end, descriptions = descriptions, regs = curblockregs)
                blocks.append(newblock)
                start = INVALID_START
                end = 0
                curblockregs = []
            else: _LOGGER.info(f"newblock declaration found for empty block")

        if start == INVALID_START: start = reg
        if type(descr) is dict: end = reg+1 # couple of byte values
        else:
            _LOGGER.info(f"adding register 0x{reg:x} {descr.key} to block with start 0x{start:x}")
            if descr.unit in (REGISTER_STR, REGISTER_WORDS,): 
                if (descr.wordcount): end = reg+descr.wordcount
                else: _LOGGER.warning(f"invalid or missing missing wordcount for {descr.key}")
            elif descr.unit in (REGISTER_S32, REGISTER_U32, REGISTER_ULSB16MSB16,):  end = reg + 2
            else: end = reg + 1
        curblockregs.append(reg)
    if ((end-start)>0): # close last block
        #newblock = block(start = start, end = end, order16 = descriptions[start].order16, order32 = descriptions[start].order32, descriptions = descriptions, regs = curblockregs)
        newblock = block(start = start, end = end, descriptions = descriptions, regs = curblockregs)
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
    #holdingOrder16 = {} # all entities should have the same order
    #inputOrder16   = {} # all entities should have the same order
    #holdingOrder32 = {} # all entities should have the same order
    #inputOrder32   = {} # all entities should have the same order
     
    plugin = hub.plugin #getPlugin(hub_name)
    for sensor_description in plugin.SENSOR_TYPES:
        if plugin.matchInverterWithMask(hub._invertertype,sensor_description.allowedtypes, hub.seriesnumber, sensor_description.blacklist):
            # apply scale exceptions early 
            readscale = None
            #normal_scale = not ((type(sensor_description.scale) is dict) or callable(sensor_description.scale))
            #if normal_scale and sensor_description.read_scale_exceptions:
            if sensor_description.read_scale_exceptions:
                for (prefix, value,) in sensor_description.read_scale_exceptions: 
                    if hub.seriesnumber.startswith(prefix): readscale = value
            sensor = SolaXModbusSensor(
                hub_name,
                hub,
                device_info,
                sensor_description,
                read_scale = readscale,
            )
            entities.append(sensor)
            if sensor_description.sleepmode == SLEEPMODE_NONE: hub.sleepnone.append(sensor_description.key)
            if sensor_description.sleepmode == SLEEPMODE_ZERO: hub.sleepzero.append(sensor_description.key)
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
                        #holdingOrder16[sensor_description.order16] = True
                        #holdingOrder32[sensor_description.order32] = True
                elif sensor_description.register_type == REG_INPUT:
                    if sensor_description.register in inputRegs: # duplicate or 2 bytes in one register ?
                        first = inputRegs[sensor_description.register]
                        inputRegs[sensor_description.register] = { first.unit: first, sensor_description.unit: sensor_description }
                        _LOGGER.warning(f"input register already declared: 0x{sensor_description.register:x} {sensor_description.key}")
                    else:
                        inputRegs[sensor_description.register] = sensor_description
                        #inputOrder16[sensor_description.order16] = True
                        #inputOrder32[sensor_description.order32] = True
                else: _LOGGER.warning(f"entity declaration without register_type found: {sensor_description.key}")
    async_add_entities(entities)
    # sort the registers for this type of inverter
    holdingRegs = dict(sorted(holdingRegs.items()))
    inputRegs   = dict(sorted(inputRegs.items()))
    # check for consistency
    #if (len(inputOrder32)>1) or (len(holdingOrder32)>1): _LOGGER.warning(f"inconsistent Big or Little Endian declaration for 32bit registers")
    #if (len(inputOrder16)>1) or (len(holdingOrder16)>1): _LOGGER.warning(f"inconsistent Big or Little Endian declaration for 16bit registers")
    # split in blocks and store results
    hub.holdingBlocks = splitInBlocks(holdingRegs, hub.plugin.block_size, hub.plugin.auto_block_ignore_readerror)
    hub.inputBlocks = splitInBlocks(inputRegs, hub.plugin.block_size, hub.plugin.auto_block_ignore_readerror)
    hub.computedSensors = computedRegs

    for i in hub.holdingBlocks: _LOGGER.info(f"{hub_name} returning holding block: 0x{i.start:x} 0x{i.end:x} {i.regs}")
    for i in hub.inputBlocks: _LOGGER.info(f"{hub_name} returning input block: 0x{i.start:x} 0x{i.end:x} {i.regs}")
    _LOGGER.debug(f"holdingBlocks: {hub.holdingBlocks}")
    _LOGGER.debug(f"inputBlocks: {hub.inputBlocks}")
    _LOGGER.info(f"computedRegs: {hub.computedSensors}")
    return True



class SolaXModbusSensor(SensorEntity):
    """Representation of an SolaX Modbus sensor."""

    def __init__(
        self,
        platform_name,
        hub,
        device_info,
        description: BaseModbusSensorEntityDescription,
        read_scale = 1
    ):
        """Initialize the sensor."""
        self._platform_name = platform_name
        self._attr_device_info = device_info
        self._hub = hub
        self.entity_description: BaseModbusSensorEntityDescription = description
        #self._attr_scale = scale
        self._read_scale = read_scale

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
            if self._read_scale: return self._hub.data[self.entity_description.key]*self._read_scale
            else: return self._hub.data[self.entity_description.key]


  

