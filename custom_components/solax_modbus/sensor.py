from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers import device_registry as dr
import logging
from typing import Optional, Dict, Any, List
from types  import SimpleNamespace
from dataclasses import dataclass, replace
from copy import copy
import homeassistant.util.dt as dt_util

from .const import ATTR_MANUFACTURER, DOMAIN, SLEEPMODE_NONE, SLEEPMODE_ZERO
from .const import INVERTER_IDENT, REG_INPUT, REG_HOLDING, REGISTER_U32, REGISTER_S32, REGISTER_ULSB16MSB16, REGISTER_STR, REGISTER_WORDS, REGISTER_U8H, REGISTER_U8L, CONF_READ_BATTERY
from .const import BaseModbusSensorEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.helpers.device_registry import DeviceInfo

_LOGGER = logging.getLogger(__name__)



empty_input_interval_group_lambda = lambda: SimpleNamespace(
            interval=0,
            device_groups={}
        )

empty_input_device_group_lambda = lambda: SimpleNamespace(
        holdingRegs  = {},
        inputRegs    = {},
        readPreparation = None,
        readFollowUp = None,
        )

async def async_setup_entry(hass, entry, async_add_entities):
    if entry.data: hub_name = entry.data[CONF_NAME] # old style - remove soon
    else: hub_name = entry.options[CONF_NAME] # new format
    hub = hass.data[DOMAIN][hub_name]["hub"]

    entities = []
    initial_groups = {}

    computedRegs = {}

    plugin = hub.plugin #getPlugin(hub_name)

    async def readFollowUp(old_data, new_data):
        dev_registry = dr.async_get(hass)
        device = dev_registry.async_get_device(identifiers={(DOMAIN, hub_name, INVERTER_IDENT)})
        if device is not None:
            sw_version = plugin.getSoftwareVersion(new_data)
            hw_version = plugin.getHardwareVersion(new_data)

            if sw_version is not None or hw_version is not None:
                dev_registry.async_update_device(
                    device.id,
                    sw_version=sw_version,
                    hw_version=hw_version)
        return True

    inverter_name_suffix = ""
    if hub.inverterNameSuffix is not None and hub.inverterNameSuffix != "":
        inverter_name_suffix = hub.inverterNameSuffix + " "

    entityToList(hub, hub_name, entities, initial_groups, computedRegs, hub.device_info,
                 plugin.SENSOR_TYPES, inverter_name_suffix, "", None, readFollowUp)

    readBattery = entry.options.get(CONF_READ_BATTERY, False)
    if readBattery and plugin.BATTERY_CONFIG is not None:
        battery_config = plugin.BATTERY_CONFIG
        batt_pack_quantity = await battery_config.get_batt_pack_quantity(hub)
        batt_quantity = await battery_config.get_batt_quantity(hub)
        _LOGGER.info(f"batt_pack_quantity: {batt_pack_quantity}, batt_quantity: {batt_quantity}")

        batt_nr = 0
        for batt_pack_nr in range(0, batt_pack_quantity, 1):
            if not await battery_config.select_battery(hub, batt_nr, batt_pack_nr):
                _LOGGER.warning(f"cannot select batt_nr: {batt_nr}, batt_pack_nr: {batt_pack_nr}")
                continue

            batt_pack_id = f"battery_1_{batt_pack_nr+1}"
            dev_registry = dr.async_get(hass)
            device = dev_registry.async_get_device(identifiers={(DOMAIN, hub_name, batt_pack_id)})
            if device is not None:
                _LOGGER.debug(f"batt pack serial: {device.serial_number}")
                await battery_config.init_batt_pack(hub, device.serial_number)

            batt_pack_serial = await battery_config.get_batt_pack_serial(hub, batt_nr, batt_pack_nr)
            if batt_pack_serial is None:
                _LOGGER.warning(f"cannot get serial for batt_nr: {batt_nr}, batt_pack_nr: {batt_pack_nr}")
                await battery_config.init_batt_pack_serials(hub)
                batt_pack_serial = await battery_config.get_batt_pack_serial(hub, batt_nr, batt_pack_nr)
                if batt_pack_serial is None:
                    continue

            device_info_battery = DeviceInfo(
                identifiers = {(DOMAIN, hub_name, batt_pack_id)},
                name = hub.plugin.plugin_name + f" Battery {batt_nr + 1}/{batt_pack_nr + 1}",
                manufacturer = hub.plugin.plugin_manufacturer,
                serial_number = batt_pack_serial,
                via_device = (DOMAIN, hub_name, INVERTER_IDENT),
            )

            name_prefix = battery_config.battery_sensor_name_prefix.replace("{batt-nr}", str(batt_nr+1)).replace("{pack-nr}", str(batt_pack_nr+1))
            key_prefix = battery_config.battery_sensor_key_prefix.replace("{batt-nr}", str(batt_nr+1)).replace("{pack-nr}", str(batt_pack_nr+1))

            async def readPreparation(old_data, key_prefix=key_prefix, batt_nr=0, batt_pack_nr=batt_pack_nr):
                await battery_config.select_battery(hub, batt_nr, batt_pack_nr)
                return await battery_config.check_battery_on_start(hub, old_data, key_prefix, batt_nr, batt_pack_nr)

            async def readFollowUp(old_data, new_data, key_prefix=key_prefix, hub_name=hub_name, batt_pack_id=batt_pack_id, batt_nr=batt_nr, batt_pack_nr=batt_pack_nr):
                dev_registry = dr.async_get(hass)
                device = dev_registry.async_get_device(identifiers={(DOMAIN, hub_name, batt_pack_id)})
                if device is not None:
                    batt_pack_model = await battery_config.get_batt_pack_model(hub)
                    batt_pack_sw_version = await battery_config.get_batt_pack_sw_version(hub, new_data, key_prefix)
                    dev_registry.async_update_device(
                        device.id,
                        sw_version=batt_pack_sw_version,
                        model=batt_pack_model)
                return await battery_config.check_battery_on_end(hub, old_data, new_data, key_prefix, batt_nr, batt_pack_nr)

            entityToList(hub, hub_name, entities, initial_groups, computedRegs, device_info_battery,
                         battery_config.battery_sensor_type, name_prefix, key_prefix, readPreparation, readFollowUp)

    async_add_entities(entities)
    #now the groups are available
    hub.computedSensors = computedRegs
    hub.rebuild_blocks(initial_groups) #, computedRegs) # first time call
    _LOGGER.debug(f"computedRegs: {hub.computedSensors}")
    return True




def entityToList(hub, hub_name, entities, groups, computedRegs, device_info: DeviceInfo,
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
                    entityToListSingle(hub, hub_name, entities, groups, computedRegs, device_info, newdescr, readPreparation, readFollowUp)
            else:
                newdescr = copy(sensor_description)
                try:
                   newdescr.name = name_prefix + newdescr.name
                except:
                   newdescr.name = newdescr.name
                   
                newdescr.key = key_prefix + newdescr.key
                entityToListSingle(hub, hub_name, entities, groups, computedRegs, device_info, newdescr, readPreparation, readFollowUp)

def entityToListSingle(hub, hub_name, entities, groups, computedRegs, device_info: DeviceInfo, newdescr, readPreparation, readFollowUp):  # noqa: D103
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
        interval_group = groups.setdefault(hub.entity_group(sensor), empty_input_interval_group_lambda())
        device_group_key = hub.device_group_key(device_info)
        device_group = interval_group.device_groups.setdefault(device_group_key, empty_input_device_group_lambda())
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
