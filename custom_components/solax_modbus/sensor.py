from homeassistant.const import CONF_NAME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.components.sensor import SensorEntity, RestoreEntity
from homeassistant.helpers import device_registry as dr
import logging
import time
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
from homeassistant.helpers import entity_registry as er 

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


def is_entity_enabled(hass, hub, descriptor, use_default = False): 
    # simple test, more complex counterpart is should_register_be_loaded
    unique_id     = f"{hub._name}_{descriptor.key}" 
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id('sensor', DOMAIN, unique_id) 
    if entity_id:
        entity_entry = registry.async_get(entity_id) 
        if entity_entry and not entity_entry.disabled: 
            _LOGGER.debug(f"{hub.name}: is_entity_enabled: {entity_id} is enabled, returning True.")
            return True # Found an enabled entity, no need to check further 
    else:
        _LOGGER.info(f"{hub.name}: entity {unique_id} not found in registry")
    if use_default: 
        _LOGGER.debug(f"{hub.name}: is_entity_enabled: {entity_id} not found in registry, returning default {descriptor.entity_registry_enabled_default}.")
        return descriptor.entity_registry_enabled_default
    return False



async def async_setup_entry(hass, entry, async_add_entities):
    if entry.data: hub_name = entry.data[CONF_NAME] # old style - remove soon
    else: hub_name = entry.options[CONF_NAME] # new format
    _LOGGER.info(f"===== {hub_name}: async_setup_entry called =====")
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
    # Test: Comment out to prevent adding inverter suffix to Energy Dashboard sensors
    # if hub.inverterNameSuffix is not None and hub.inverterNameSuffix != "":
    #     inverter_name_suffix = hub.inverterNameSuffix + " "

    entityToList(hub, hub_name, entities, initial_groups, computedRegs, hub.device_info,
                 plugin.SENSOR_TYPES, inverter_name_suffix, "", None, readFollowUp)

    # Energy Dashboard check moved to after rebuild_blocks (see below) so initial_groups are ready for reading

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
    _LOGGER.info(f"{hub.name}: computedRegs: {hub.computedSensors}")
    
    # Give initial bisect task time to start before Energy Dashboard setup
    # The bisect runs in background and may need a moment to begin
    import asyncio
    await asyncio.sleep(1.0)  # 1 second delay to let bisect task start
    
    # Energy Dashboard Virtual Device integration (after rebuild_blocks so initial_groups are ready for reading)
    try:
        from .energy_dashboard import (
            create_energy_dashboard_sensors,
            should_create_energy_dashboard_device,
            validate_mapping,
        )
    except Exception as e:
        _LOGGER.error(f"{hub_name}: Failed to import Energy Dashboard module: {e}", exc_info=True)
        # Continue without Energy Dashboard support
    else:
        try:
            # Check both plugin and plugin_instance (different plugins have different structures)
            plugin_obj = getattr(plugin, 'plugin_instance', plugin)
            
            config = entry.options
            from .const import (
                CONF_ENERGY_DASHBOARD_DEVICE,
                DEFAULT_ENERGY_DASHBOARD_DEVICE,
            )
            
            # Check if Energy Dashboard is disabled - if so, remove existing entities and device
            energy_dashboard_enabled = config.get(CONF_ENERGY_DASHBOARD_DEVICE, DEFAULT_ENERGY_DASHBOARD_DEVICE)
            
            # Handle legacy string values for backward compatibility
            if isinstance(energy_dashboard_enabled, str):
                energy_dashboard_enabled = energy_dashboard_enabled != "disabled"
            
            if not energy_dashboard_enabled:
                _LOGGER.info(f"{hub_name}: Energy Dashboard disabled - removing existing entities and device")
                # Remove Energy Dashboard entities if they exist
                # unique_id format is: {hub._name}_{key}
                entity_registry = er.async_get(hass)
                device_registry = dr.async_get(hass)
                energy_dashboard_entities = []
                hub_unique_prefix = f"{hub._name}_"
                
                # Find Energy Dashboard device identifier
                energy_dashboard_device_identifiers = {(DOMAIN, f"{hub._name}_energy_dashboard", "ENERGY_DASHBOARD")}
                
                for entity_entry in entity_registry.entities.values():
                    if (entity_entry.platform == DOMAIN and 
                        entity_entry.unique_id and 
                        entity_entry.unique_id.startswith(hub_unique_prefix)):
                        # Check if this is an Energy Dashboard sensor by key
                        unique_id_suffix = entity_entry.unique_id[len(hub_unique_prefix):]
                        if (unique_id_suffix in ["grid_power", "battery_power"] or
                            unique_id_suffix.startswith("all_") or unique_id_suffix.startswith("solax_")):
                            energy_dashboard_entities.append(entity_entry.entity_id)
                            _LOGGER.debug(f"{hub_name}: Found Energy Dashboard entity to remove: {entity_entry.entity_id}")
                
                # Remove Energy Dashboard entities first
                if energy_dashboard_entities:
                    _LOGGER.info(f"{hub_name}: Removing {len(energy_dashboard_entities)} Energy Dashboard entities")
                    for entity_id in energy_dashboard_entities:
                        entity_registry.async_remove(entity_id)
                    # Give entities time to be removed before removing device
                    # This ensures proper cleanup order and prevents UI issues
                    import asyncio
                    await asyncio.sleep(0.1)
                
                # Remove Energy Dashboard device from device registry (after entities are removed)
                energy_dashboard_device = device_registry.async_get_device(identifiers=energy_dashboard_device_identifiers)
                if energy_dashboard_device:
                    _LOGGER.info(f"{hub_name}: Removing Energy Dashboard device: {energy_dashboard_device.name}")
                    device_registry.async_remove_device(energy_dashboard_device.id)
                    # Small delay to ensure device removal is processed
                    await asyncio.sleep(0.1)
            elif hasattr(plugin_obj, 'ENERGY_DASHBOARD_MAPPING'):
                mapping = plugin_obj.ENERGY_DASHBOARD_MAPPING
                _LOGGER.info(f"{hub_name}: Energy Dashboard mapping found for plugin: {mapping.plugin_name}")
                
                validation_result = validate_mapping(mapping)
                if not validation_result:
                    _LOGGER.error(f"{hub_name}: Invalid Energy Dashboard mapping, skipping device creation")
                else:
                    result = await should_create_energy_dashboard_device(hub, config, hass, _LOGGER, initial_groups)
                    if result:
                        start_time = time.time()
                        energy_dashboard_sensors = await create_energy_dashboard_sensors(hub, mapping, hass, config)
                        if energy_dashboard_sensors:
                            _LOGGER.info(f"{hub_name}: Creating {len(energy_dashboard_sensors)} Energy Dashboard sensors")
                            # Create a new list to track Energy Dashboard entities
                            energy_dashboard_entities = []
                            # Use Energy Dashboard device name as platform name for entity_id prefix
                            energy_dashboard_platform_name = f"{hub_name} Energy Dashboard"
                            entityToList(hub, energy_dashboard_platform_name, energy_dashboard_entities, initial_groups, computedRegs, hub.device_info,
                                         energy_dashboard_sensors, inverter_name_suffix, "", None, readFollowUp)
                            
                            # Add Energy Dashboard entities to main entities list and register them
                            if energy_dashboard_entities:
                                _LOGGER.info(f"{hub_name}: Registering {len(energy_dashboard_entities)} Energy Dashboard entities")
                                entities.extend(energy_dashboard_entities)
                                async_add_entities(energy_dashboard_entities)
                            
                            elapsed_time = time.time() - start_time
                            _LOGGER.debug(f"{hub_name}: Energy Dashboard device creation completed in {elapsed_time:.3f}s ({len(energy_dashboard_entities)} entities)")
                            
                            # Ensure Energy Dashboard entities are enabled (they might have been disabled previously)
                            entity_registry = er.async_get(hass)
                            hub_unique_prefix = f"{hub._name}_"
                            for sensor_mapping in mapping.mappings:
                                unique_id = f"{hub_unique_prefix}{sensor_mapping.target_key}"
                                entity_id = entity_registry.async_get_entity_id('sensor', DOMAIN, unique_id)
                                if entity_id:
                                    entity_entry = entity_registry.async_get(entity_id)
                                    if entity_entry and entity_entry.disabled_by:
                                        _LOGGER.debug(f"{hub_name}: Enabling previously disabled Energy Dashboard entity: {entity_id}")
                                        entity_registry.async_update_entity(entity_id, disabled_by=None)
            else:
                _LOGGER.debug(f"{hub_name}: ENERGY_DASHBOARD_MAPPING not found (plugin may not support Energy Dashboard)")
        except Exception as e:
            _LOGGER.error(f"{hub_name}: Error during Energy Dashboard setup: {e}", exc_info=True)
            # Continue without Energy Dashboard support - don't break the integration
    
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
    
    # Check if this sensor has custom Energy Dashboard device info
    if hasattr(newdescr, '_energy_dashboard_device_info'):
        device_info = newdescr._energy_dashboard_device_info
    
    # Check if this is a Riemann sum sensor
    if getattr(newdescr, '_is_riemann_sum_sensor', False):
        sensor = RiemannSumEnergySensor(
            hub_name,
            hub,
            device_info,
            newdescr,
        )
    else:
        sensor = SolaXModbusSensor(
            hub_name,
            hub,
            device_info,
            newdescr,
        )

    hub.sensorEntities[newdescr.key] = sensor
    # register dependency chain
    deplist = newdescr.depends_on
    if isinstance(deplist, str): deplist = (deplist, )
    if isinstance(deplist, (list, tuple,)):
        _LOGGER.debug(f"{hub.name}: {newdescr.key} depends on entities {deplist}")
        for dep_on in deplist: # register inter-sensor dependencies (e.g. for value functions)
            if dep_on != newdescr.key: hub.entity_dependencies.setdefault(dep_on, []).append(newdescr.key) # can be more than one
    #internal sensors are only used for polling values for selects, etc
    if not getattr(newdescr,"internal",None):
        entities.append(sensor)
    if newdescr.sleepmode == SLEEPMODE_NONE: hub.sleepnone.append(newdescr.key)
    if newdescr.sleepmode == SLEEPMODE_ZERO: hub.sleepzero.append(newdescr.key)
    if (newdescr.register < 0): # entity without modbus address
        enabled = is_entity_enabled(hub._hass, hub, newdescr, use_default = True) # dont compute disabled entities anymore
        #if not enabled: _LOGGER.info(f"is_entity_enabled called for disabled entity {newdescr.key}")
        if newdescr.value_function and (enabled or newdescr.internal): #*** dont compute disabled entities anymore unless internal
            computedRegs[newdescr.key] = newdescr
        else: 
            if enabled: _LOGGER.warning(f"{hub_name}: entity without modbus register address and without value_function found: {newdescr.key}")
    else:
        #target group
        interval_group = groups.setdefault(hub.scan_group(sensor), empty_input_interval_group_lambda())
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
                else: _LOGGER.warning(f"{hub_name}: holding register already used: 0x{newdescr.register:x} {newdescr.key}")
            else:
                holdingRegs[newdescr.register] = newdescr
        elif newdescr.register_type == REG_INPUT:
            if newdescr.register in inputRegs: # duplicate or 2 bytes in one register ?
                first = inputRegs[newdescr.register]
                inputRegs[newdescr.register] = { first.unit: first, newdescr.unit: newdescr }
                _LOGGER.warning(f"{hub_name}: input register already declared: 0x{newdescr.register:x} {newdescr.key}")
            else:
                inputRegs[newdescr.register] = newdescr
        else: _LOGGER.warning(f"{hub_name}: entity declaration without register_type found: {newdescr.key}")


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
        #self.entity_id = "sensor." + platform_name + "_" + description.key
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
            return self._hub.data[self.entity_description.key]
            #try:    val = self._hub.data[self.entity_description.key] *self.entity_description.read_scale # a bit ugly as we might multiply strings or other types with 1
            #except: val = self._hub.data[self.entity_description.key] # not a number
            #return val
        return None


class RiemannSumEnergySensor(SolaXModbusSensor, RestoreEntity):
    """Energy sensor that calculates cumulative energy using Riemann sum integration."""
    
    def __init__(
        self,
        platform_name,
        hub,
        device_info,
        description: BaseModbusSensorEntityDescription,
    ):
        """Initialize the Riemann sum energy sensor."""
        super().__init__(platform_name, hub, device_info, description)
        
        # Get Riemann sum mapping from description
        riemann_mapping = getattr(description, '_riemann_mapping', None)
        if riemann_mapping is None:
            _LOGGER.error(f"{platform_name}: Riemann sum sensor {description.key} missing mapping")
        
        self._riemann_mapping = riemann_mapping
        self._filter_function = (riemann_mapping.filter_function if riemann_mapping else None) or (lambda v: v)
        self._last_power_value = None
        self._last_update_time = None
        self._total_energy = 0.0  # kWh
    
    async def async_added_to_hass(self):
        """Register callbacks and restore state."""
        # Restore previous state if available
        if (last_state := await self.async_get_last_state()):
            if last_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    self._total_energy = float(last_state.state)
                    if last_state.last_updated:
                        self._last_update_time = last_state.last_updated.timestamp()
                    _LOGGER.debug(f"{self._platform_name}: Restored Riemann sum state for {self.entity_description.key}: {self._total_energy} kWh")
                except (ValueError, AttributeError, TypeError) as e:
                    _LOGGER.debug(f"{self._platform_name}: Could not restore Riemann sum state for {self.entity_description.key}: {e}")
        
        # Register with hub
        await self._hub.async_add_solax_modbus_sensor(self)
    
    @callback
    def modbus_data_updated(self):
        """Calculate energy when data is updated."""
        if self._riemann_mapping is None:
            return
        
        # Get current power value from source sensor
        source_key = self._riemann_mapping.source_key
        current_power = self._hub.data.get(source_key)
        
        if current_power is None:
            # Source sensor not available, keep current total
            return
        
        # Apply filter function (e.g., only > 0 for import, only < 0 for export)
        filtered_power = self._filter_function(current_power)
        
        # Get current time
        current_time = time.time()
        
        # Calculate energy increment if we have previous value
        if self._last_power_value is not None and self._last_update_time is not None:
            # Trapezoidal integration: ΔE = (P_prev + P_curr) / 2 * Δt / 3600
            # P in W, Δt in seconds, result in kWh
            delta_time = current_time - self._last_update_time
            if delta_time > 0:
                avg_power = (self._last_power_value + filtered_power) / 2.0
                energy_increment = (avg_power * delta_time) / 3600.0  # Convert to kWh
                self._total_energy += energy_increment
        
        # Update stored values
        self._last_power_value = filtered_power
        self._last_update_time = current_time
        
        # Round result and store in hub.data (so native_value property works)
        from .energy_dashboard import RIEMANN_ROUND_DIGITS
        self._total_energy = round(self._total_energy, RIEMANN_ROUND_DIGITS)
        self._hub.data[self.entity_description.key] = self._total_energy
        
        # Update state
        self.async_write_ha_state()
    
    @property
    def native_value(self):
        """Return the calculated energy value."""
        # Value is stored in hub.data by modbus_data_updated
        if self.entity_description.key in self._hub.data:
            return self._hub.data[self.entity_description.key]
        return self._total_energy




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
    
    # Check if this sensor has custom Energy Dashboard device info
    if hasattr(newdescr, '_energy_dashboard_device_info'):
        device_info = newdescr._energy_dashboard_device_info
    
    # Check if this is a Riemann sum sensor
    if getattr(newdescr, '_is_riemann_sum_sensor', False):
        sensor = RiemannSumEnergySensor(
            hub_name,
            hub,
            device_info,
            newdescr,
        )
    else:
        sensor = SolaXModbusSensor(
            hub_name,
            hub,
            device_info,
            newdescr,
        )

    hub.sensorEntities[newdescr.key] = sensor
    # register dependency chain
    deplist = newdescr.depends_on
    if isinstance(deplist, str): deplist = (deplist, )
    if isinstance(deplist, (list, tuple,)):
        _LOGGER.debug(f"{hub.name}: {newdescr.key} depends on entities {deplist}")
        for dep_on in deplist: # register inter-sensor dependencies (e.g. for value functions)
            if dep_on != newdescr.key: hub.entity_dependencies.setdefault(dep_on, []).append(newdescr.key) # can be more than one
    #internal sensors are only used for polling values for selects, etc
    if not getattr(newdescr,"internal",None):
        entities.append(sensor)
    if newdescr.sleepmode == SLEEPMODE_NONE: hub.sleepnone.append(newdescr.key)
    if newdescr.sleepmode == SLEEPMODE_ZERO: hub.sleepzero.append(newdescr.key)
    if (newdescr.register < 0): # entity without modbus address
        enabled = is_entity_enabled(hub._hass, hub, newdescr, use_default = True) # dont compute disabled entities anymore
        #if not enabled: _LOGGER.info(f"is_entity_enabled called for disabled entity {newdescr.key}")
        if newdescr.value_function and (enabled or newdescr.internal): #*** dont compute disabled entities anymore unless internal
            computedRegs[newdescr.key] = newdescr
        else: 
            if enabled: _LOGGER.warning(f"{hub_name}: entity without modbus register address and without value_function found: {newdescr.key}")
    else:
        #target group
        interval_group = groups.setdefault(hub.scan_group(sensor), empty_input_interval_group_lambda())
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
                else: _LOGGER.warning(f"{hub_name}: holding register already used: 0x{newdescr.register:x} {newdescr.key}")
            else:
                holdingRegs[newdescr.register] = newdescr
        elif newdescr.register_type == REG_INPUT:
            if newdescr.register in inputRegs: # duplicate or 2 bytes in one register ?
                first = inputRegs[newdescr.register]
                inputRegs[newdescr.register] = { first.unit: first, newdescr.unit: newdescr }
                _LOGGER.warning(f"{hub_name}: input register already declared: 0x{newdescr.register:x} {newdescr.key}")
            else:
                inputRegs[newdescr.register] = newdescr
        else: _LOGGER.warning(f"{hub_name}: entity declaration without register_type found: {newdescr.key}")


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
        #self.entity_id = "sensor." + platform_name + "_" + description.key
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
            return self._hub.data[self.entity_description.key]
            #try:    val = self._hub.data[self.entity_description.key] *self.entity_description.read_scale # a bit ugly as we might multiply strings or other types with 1
            #except: val = self._hub.data[self.entity_description.key] # not a number
            #return val
