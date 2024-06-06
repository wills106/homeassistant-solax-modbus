from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.components.sensor import SensorEntity
import logging
from typing import Optional, Dict, Any, List
from types  import SimpleNamespace
from dataclasses import dataclass, replace
from copy import copy
import homeassistant.util.dt as dt_util

from .const import ATTR_MANUFACTURER, DOMAIN, SLEEPMODE_NONE, SLEEPMODE_ZERO
from .const import REG_INPUT, REG_HOLDING, REGISTER_U32, REGISTER_S32, REGISTER_ULSB16MSB16, REGISTER_STR, REGISTER_WORDS, REGISTER_U8H, REGISTER_U8L
from .const import BaseModbusSensorEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.helpers.device_registry import DeviceInfo


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
                _LOGGER.debug(f"Starting new block at 0x{reg:x} ")
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
            _LOGGER.debug(f"adding register 0x{reg:x} {descr.key} to block with start 0x{start:x}")
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

    entities = []
    groups = {}
    newgrp = lambda: SimpleNamespace(
        holdingRegs  = {},
        inputRegs    = {},
        readPreparation = None,
        readFollowUp = None,
        )
    computedRegs = {}

    plugin = hub.plugin #getPlugin(hub_name)
    entityToList(hub, hub_name, entities, groups, newgrp, computedRegs, hub.device_info,
                 plugin.SENSOR_TYPES, "", "", None, None)

    if plugin.BATTERY_CONFIG is not None:
        battery_config = plugin.BATTERY_CONFIG
        batpack_quantity = await battery_config.get_batpack_quantity(hub)
        bat_quantity = await battery_config.get_bat_quantity(hub)
        _LOGGER.info(f"batpack_quantity: {batpack_quantity}, bat_quantity: {bat_quantity}")

        for batpack_nr in range(0, batpack_quantity, 1):
            device_info_battery = DeviceInfo(
                identifiers = {(DOMAIN, hub_name, f"battery_1_{batpack_nr+1}")},
                name = hub.plugin.plugin_name + f" Battery 1/{batpack_nr+1}",
                manufacturer = hub.plugin.plugin_manufacturer,
                #"model": hub.sensor_description.inverter_model,
                serial_number = hub.seriesnumber,
                via_device = (DOMAIN, hub_name, "Inverter"),
            )

            name_prefix = battery_config.battery_sensor_name_prefix
            key_prefix = battery_config.battery_sensor_key_prefix.replace("{bat-nr}", str(1)).replace("{pack-nr}", str(batpack_nr+1))

            async def readPreparation(old_data, key_prefix=key_prefix, bat_nr=0, batpack_nr=batpack_nr):
                await battery_config.select_battery(hub, bat_nr, batpack_nr)
                return await battery_config.check_battery_on_start(hub, old_data, key_prefix, bat_nr, batpack_nr)

            async def readFollowUp(bat_nr=0, batpack_nr=batpack_nr):
                return await battery_config.check_battery_on_end(hub, bat_nr, batpack_nr)

            entityToList(hub, hub_name, entities, groups, newgrp, computedRegs, device_info_battery,
                         battery_config.battery_sensor_type, name_prefix, key_prefix, readPreparation, readFollowUp)

    async_add_entities(entities)
    _LOGGER.info(f"{hub_name} sensor groups: {len(groups)}")
    #now the groups are available
    for interval, interval_group in groups.items():
        _LOGGER.info(f"{hub_name} group: {interval}")
        for device_name, device_group in interval_group.items():
            # sort the registers for this type of inverter
            holdingRegs = dict(sorted(device_group.holdingRegs.items()))
            inputRegs   = dict(sorted(device_group.inputRegs.items()))
            # check for consistency
            #if (len(inputOrder32)>1) or (len(holdingOrder32)>1): _LOGGER.warning(f"inconsistent Big or Little Endian declaration for 32bit registers")
            #if (len(inputOrder16)>1) or (len(holdingOrder16)>1): _LOGGER.warning(f"inconsistent Big or Little Endian declaration for 16bit registers")
            # split in blocks and store results
            hub_interval_group = hub.groups.setdefault(interval, hub.empty_interval_group())
            hub_device_group = hub_interval_group.device_groups.setdefault(device_name, hub.empty_device_group())
            hub_device_group.readPreparation = device_group.readPreparation
            hub_device_group.readFollowUp = device_group.readFollowUp
            hub_device_group.holdingBlocks = splitInBlocks(holdingRegs, hub.plugin.block_size, hub.plugin.auto_block_ignore_readerror)
            hub_device_group.inputBlocks = splitInBlocks(inputRegs, hub.plugin.block_size, hub.plugin.auto_block_ignore_readerror)
            hub.computedSensors = computedRegs

            for i in hub_device_group.holdingBlocks: _LOGGER.info(f"{hub_name} returning holding block: 0x{i.start:x} 0x{i.end:x} {i.regs}")
            for i in hub_device_group.inputBlocks: _LOGGER.info(f"{hub_name} returning input block: 0x{i.start:x} 0x{i.end:x} {i.regs}")
            _LOGGER.debug(f"holdingBlocks: {hub_device_group.holdingBlocks}")
            _LOGGER.debug(f"inputBlocks: {hub_device_group.inputBlocks}")

    _LOGGER.info(f"computedRegs: {hub.computedSensors}")
    return True

def entityToList(hub, hub_name, entities, groups, newgrp, computedRegs, device_info: DeviceInfo,
                 sensor_types, name_prefix, key_prefix, readPreparation, readFollowUp):  # noqa: D103
    for sensor_description in sensor_types:
        if hub.plugin.matchInverterWithMask(hub._invertertype,sensor_description.allowedtypes, hub.seriesnumber, sensor_description.blacklist):
            # apply scale exceptions early
            if sensor_description.value_series is not None:
                for serie_value in range(sensor_description.value_series):
                    newdescr = copy(sensor_description)
                    newdescr.name = name_prefix + newdescr.name.replace("{}", str(serie_value+1))
                    newdescr.key = key_prefix + newdescr.key.replace("{}", str(serie_value+1))
                    newdescr.register = sensor_description.register + serie_value
                    entityToListSingle(hub, hub_name, entities, groups, newgrp, computedRegs, device_info, newdescr, readPreparation, readFollowUp)
            else:
                newdescr = copy(sensor_description)
                newdescr.name = name_prefix + newdescr.name
                newdescr.key = key_prefix + newdescr.key
                entityToListSingle(hub, hub_name, entities, groups, newgrp, computedRegs, device_info, newdescr, readPreparation, readFollowUp)

def entityToListSingle(hub, hub_name, entities, groups, newgrp, computedRegs, device_info: DeviceInfo, newdescr, readPreparation, readFollowUp):  # noqa: D103
    if newdescr.read_scale_exceptions:
        for (prefix, value,) in newdescr.read_scale_exceptions:
            if hub.seriesnumber.startswith(prefix):  newdescr = replace(newdescr, read_scale = value)
    sensor = SolaXModbusSensor(
        hub_name,
        hub,
        device_info,
        newdescr,
    )

    hub.sensorEntities[newdescr.key] = sensor
    #internal sensors are only used for polling values for selects, etc
    if not getattr(newdescr,"internal",None):
        entities.append(sensor)
    if newdescr.sleepmode == SLEEPMODE_NONE: hub.sleepnone.append(newdescr.key)
    if newdescr.sleepmode == SLEEPMODE_ZERO: hub.sleepzero.append(newdescr.key)
    if (newdescr.register < 0): # entity without modbus address
        if newdescr.value_function:
            computedRegs[newdescr.key] = newdescr
        else: _LOGGER.warning(f"entity without modbus register address and without value_function found: {newdescr.key}")
    else:
        #target group
        interval_group = groups.setdefault(hub.entity_group(sensor), {})
        device_group_key = hub.device_group_key(device_info)
        device_group = interval_group.setdefault(device_group_key, newgrp())
        holdingRegs  = device_group.holdingRegs
        inputRegs    = device_group.inputRegs
        device_group.readPreparation = readPreparation
        device_group.readFollowUp = readFollowUp

        if newdescr.register_type == REG_HOLDING:
            if newdescr.register in holdingRegs: # duplicate or 2 bytes in one register ?
                if newdescr.unit in (REGISTER_U8H, REGISTER_U8L,) and holdingRegs[newdescr.register].unit in (REGISTER_U8H, REGISTER_U8L,) :
                    first = holdingRegs[newdescr.register]
                    holdingRegs[newdescr.register] = { first.unit: first, newdescr.unit: newdescr }
                else: _LOGGER.warning(f"holding register already used: 0x{newdescr.register:x} {newdescr.key}")
            else:
                holdingRegs[newdescr.register] = newdescr
        elif newdescr.register_type == REG_INPUT:
            if newdescr.register in inputRegs: # duplicate or 2 bytes in one register ?
                first = inputRegs[newdescr.register]
                inputRegs[newdescr.register] = { first.unit: first, newdescr.unit: newdescr }
                _LOGGER.warning(f"input register already declared: 0x{newdescr.register:x} {newdescr.key}")
            else:
                inputRegs[newdescr.register] = newdescr
        else: _LOGGER.warning(f"entity declaration without register_type found: {newdescr.key}")

class SolaXModbusSensor(SensorEntity):
    """Representation of an SolaX Modbus sensor."""

    def __init__(
        self,
        platform_name,
        hub,
        device_info,
        description: BaseModbusSensorEntityDescription,
    ):
        """Initialize the sensor."""
        self._platform_name = platform_name
        self._attr_device_info = device_info
        self._hub = hub
        self.entity_id = "sensor." + platform_name + "_" + description.key
        self.entity_description: BaseModbusSensorEntityDescription = description

    async def async_added_to_hass(self):
        """Register callbacks."""
        await self._hub.async_add_solax_modbus_sensor(self)

    async def async_will_remove_from_hass(self) -> None:
        await self._hub.async_remove_solax_modbus_sensor(self)

    @callback
    def modbus_data_updated(self):
        self.async_write_ha_state()

    @callback
    def _update_state(self): # never called ?????
        _LOGGER.info(f"update_state {self.entity_description.key} : {self._hub.data.get(self.entity_description.key,'None')}")
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
            try:    val = self._hub.data[self.entity_description.key]*self.entity_description.read_scale # a bit ugly as we might multiply strings or other types with 1
            except: val = self._hub.data[self.entity_description.key] # not a number
            return val
