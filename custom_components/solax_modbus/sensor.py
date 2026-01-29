import logging
import time
from copy import copy
from dataclasses import dataclass, replace
from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import RestoreEntity, SensorEntity, SensorEntityDescription
from homeassistant.const import CONF_NAME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    ATTR_MANUFACTURER,
    CONF_READ_BATTERY,
    DOMAIN,
    INVERTER_IDENT,
    REG_HOLDING,
    REG_INPUT,
    REGISTER_S32,
    REGISTER_STR,
    REGISTER_U8H,
    REGISTER_U8L,
    REGISTER_U32,
    REGISTER_ULSB16MSB16,
    REGISTER_WORDS,
    SLEEPMODE_NONE,
    SLEEPMODE_ZERO,
    BaseModbusSensorEntityDescription,
)
from .debug import get_debug_setting

_LOGGER = logging.getLogger(__name__)


def _energy_dashboard_mapping_attrs(description, hub) -> dict:
    mapping = getattr(description, "_energy_dashboard_mapping", None)
    if not mapping:
        return {"ed_mapping_present": False}
    source_hub = getattr(description, "_energy_dashboard_source_hub", None) or hub
    hub_data = getattr(source_hub, "data", None) or getattr(source_hub, "datadict", {})
    try:
        resolved_source_key = mapping.get_source_key(hub_data)
    except Exception:
        resolved_source_key = None
    return {
        "ed_mapping_present": True,
        "ed_target_key": mapping.target_key,
        "ed_source_key": mapping.source_key,
        "ed_source_key_pm": mapping.source_key_pm,
        "ed_resolved_source_key": resolved_source_key,
        "ed_use_riemann_sum": mapping.use_riemann_sum,
        "ed_needs_aggregation": mapping.needs_aggregation,
        "ed_skip_pm_individuals": mapping.skip_pm_individuals,
        "ed_source_hub": getattr(source_hub, "_name", None),
    }


empty_input_interval_group_lambda = lambda: SimpleNamespace(interval=0, device_groups={})

empty_input_device_group_lambda = lambda: SimpleNamespace(
    holdingRegs={},
    inputRegs={},
    readPreparation=None,
    readFollowUp=None,
)


def is_entity_enabled(hass, hub, descriptor, use_default=False):
    # simple test, more complex counterpart is should_register_be_loaded
    unique_id = f"{hub._name}_{descriptor.key}"
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    if entity_id:
        entity_entry = registry.async_get(entity_id)
        if entity_entry and not entity_entry.disabled:
            _LOGGER.debug(f"{hub.name}: is_entity_enabled: {entity_id} is enabled, returning True.")
            return True  # Found an enabled entity, no need to check further
    else:
        _LOGGER.info(f"{hub.name}: entity {unique_id} not found in registry")
    if use_default:
        _LOGGER.debug(
            f"{hub.name}: is_entity_enabled: {entity_id} not found in registry, returning default {descriptor.entity_registry_enabled_default}."
        )
        return descriptor.entity_registry_enabled_default
    return False


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.data:
        hub_name = entry.data[CONF_NAME]  # old style - remove soon
    else:
        hub_name = entry.options[CONF_NAME]  # new format
    _LOGGER.info(f"===== {hub_name}: async_setup_entry called =====")
    hub = hass.data[DOMAIN][hub_name]["hub"]

    entities = []
    initial_groups = {}

    computedRegs = {}

    plugin = hub.plugin  # getPlugin(hub_name)

    async def readFollowUp(old_data, new_data):
        dev_registry = dr.async_get(hass)
        device = dev_registry.async_get_device(identifiers={(DOMAIN, hub_name, INVERTER_IDENT)})
        if device is not None:
            sw_version = plugin.getSoftwareVersion(new_data)
            hw_version = plugin.getHardwareVersion(new_data)

            if sw_version is not None or hw_version is not None:
                dev_registry.async_update_device(device.id, sw_version=sw_version, hw_version=hw_version)
        return True

    inverter_name_suffix = ""
    # Test: Comment out to prevent adding inverter suffix to Energy Dashboard sensors
    # if hub.inverterNameSuffix is not None and hub.inverterNameSuffix != "":
    #     inverter_name_suffix = hub.inverterNameSuffix + " "

    entityToList(
        hub,
        hub_name,
        entities,
        initial_groups,
        computedRegs,
        hub.device_info,
        plugin.SENSOR_TYPES,
        inverter_name_suffix,
        "",
        None,
        readFollowUp,
    )

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

            batt_pack_id = f"battery_1_{batt_pack_nr + 1}"
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
                identifiers={(DOMAIN, hub_name, batt_pack_id)},
                name=hub.plugin.plugin_name + f" Battery {batt_nr + 1}/{batt_pack_nr + 1}",
                manufacturer=hub.plugin.plugin_manufacturer,
                serial_number=batt_pack_serial,
                via_device=(DOMAIN, hub_name, INVERTER_IDENT),
            )

            name_prefix = battery_config.battery_sensor_name_prefix.replace("{batt-nr}", str(batt_nr + 1)).replace(
                "{pack-nr}", str(batt_pack_nr + 1)
            )
            key_prefix = battery_config.battery_sensor_key_prefix.replace("{batt-nr}", str(batt_nr + 1)).replace(
                "{pack-nr}", str(batt_pack_nr + 1)
            )

            async def readPreparation(old_data, key_prefix=key_prefix, batt_nr=0, batt_pack_nr=batt_pack_nr):
                await battery_config.select_battery(hub, batt_nr, batt_pack_nr)
                return await battery_config.check_battery_on_start(hub, old_data, key_prefix, batt_nr, batt_pack_nr)

            async def readFollowUp(
                old_data,
                new_data,
                key_prefix=key_prefix,
                hub_name=hub_name,
                batt_pack_id=batt_pack_id,
                batt_nr=batt_nr,
                batt_pack_nr=batt_pack_nr,
            ):
                dev_registry = dr.async_get(hass)
                device = dev_registry.async_get_device(identifiers={(DOMAIN, hub_name, batt_pack_id)})
                if device is not None:
                    batt_pack_model = await battery_config.get_batt_pack_model(hub)
                    batt_pack_sw_version = await battery_config.get_batt_pack_sw_version(hub, new_data, key_prefix)
                    dev_registry.async_update_device(device.id, sw_version=batt_pack_sw_version, model=batt_pack_model)
                return await battery_config.check_battery_on_end(
                    hub, old_data, new_data, key_prefix, batt_nr, batt_pack_nr
                )

            entityToList(
                hub,
                hub_name,
                entities,
                initial_groups,
                computedRegs,
                device_info_battery,
                battery_config.battery_sensor_type,
                name_prefix,
                key_prefix,
                readPreparation,
                readFollowUp,
            )

    async_add_entities(entities)
    # now the groups are available
    hub.computedSensors = computedRegs
    hub.rebuild_blocks(initial_groups)  # , computedRegs) # first time call
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
            plugin_obj = getattr(plugin, "plugin_instance", plugin)

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
                entity_registry = er.async_get(hass)
                device_registry = dr.async_get(hass)
                energy_dashboard_entities = []

                # Find Energy Dashboard device identifier (use normalized hub name)
                energy_dashboard_device = None
                try:
                    from .energy_dashboard import create_energy_dashboard_device_info

                    energy_dashboard_device_info = create_energy_dashboard_device_info(hub, hass)
                    energy_dashboard_device = device_registry.async_get_device(
                        identifiers=energy_dashboard_device_info.identifiers
                    )
                except Exception as e:
                    _LOGGER.debug(f"{hub_name}: Could not build Energy Dashboard device info for removal: {e}")

                if not energy_dashboard_device:
                    # Fallback: match by name or legacy identifiers (scoped to this hub)
                    normalized_hub_name = hub_name.lower().replace(" ", "_")
                    expected_identifier = f"{normalized_hub_name}_energy_dashboard"
                    for device_entry in device_registry.devices.values():
                        if device_entry.name == f"{hub_name} Energy Dashboard":
                            energy_dashboard_device = device_entry
                            break
                        for identifier in device_entry.identifiers:
                            if (
                                identifier[0] == DOMAIN
                                and identifier[2] == "ENERGY_DASHBOARD"
                                and identifier[1] == expected_identifier
                            ):
                                energy_dashboard_device = device_entry
                                break
                        if energy_dashboard_device:
                            break

                # Remove entities tied to the ED device if we found it
                if energy_dashboard_device:
                    for entity_entry in entity_registry.entities.values():
                        if entity_entry.device_id == energy_dashboard_device.id:
                            energy_dashboard_entities.append(entity_entry.entity_id)
                            _LOGGER.debug(
                                f"{hub_name}: Found Energy Dashboard entity to remove: {entity_entry.entity_id}"
                            )

                # Fallback: remove any ED entities by unique_id prefix
                hub_unique_prefix = f"{hub_name} Energy Dashboard_"
                for entity_entry in entity_registry.entities.values():
                    if (
                        entity_entry.platform == DOMAIN
                        and entity_entry.unique_id
                        and entity_entry.unique_id.startswith(hub_unique_prefix)
                        and entity_entry.entity_id not in energy_dashboard_entities
                    ):
                        energy_dashboard_entities.append(entity_entry.entity_id)
                        _LOGGER.debug(f"{hub_name}: Found Energy Dashboard entity to remove: {entity_entry.entity_id}")

                if energy_dashboard_entities:
                    _LOGGER.info(f"{hub_name}: Removing {len(energy_dashboard_entities)} Energy Dashboard entities")
                    for entity_id in energy_dashboard_entities:
                        entity_registry.async_remove(entity_id)
                    import asyncio

                    await asyncio.sleep(0.1)

                if energy_dashboard_device:
                    _LOGGER.info(f"{hub_name}: Removing Energy Dashboard device: {energy_dashboard_device.name}")
                    device_registry.async_remove_device(energy_dashboard_device.id)
                    await asyncio.sleep(0.1)
            elif hasattr(plugin_obj, "ENERGY_DASHBOARD_MAPPING"):
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
                            _LOGGER.info(
                                f"{hub_name}: Creating {len(energy_dashboard_sensors)} Energy Dashboard sensors"
                            )
                            # Create a new list to track Energy Dashboard entities
                            energy_dashboard_entities = []
                            # Use Energy Dashboard device name as platform name for entity_id prefix
                            energy_dashboard_platform_name = f"{hub_name} Energy Dashboard"
                            entityToList(
                                hub,
                                energy_dashboard_platform_name,
                                energy_dashboard_entities,
                                initial_groups,
                                computedRegs,
                                hub.device_info,
                                energy_dashboard_sensors,
                                inverter_name_suffix,
                                "",
                                None,
                                readFollowUp,
                            )

                            # Add Energy Dashboard entities to main entities list and register them
                            if energy_dashboard_entities:
                                _LOGGER.info(
                                    f"{hub_name}: Registering {len(energy_dashboard_entities)} Energy Dashboard entities"
                                )
                                entities.extend(energy_dashboard_entities)
                                async_add_entities(energy_dashboard_entities)

                            elapsed_time = time.time() - start_time
                            _LOGGER.debug(
                                f"{hub_name}: Energy Dashboard device creation completed in {elapsed_time:.3f}s ({len(energy_dashboard_entities)} entities)"
                            )

                            # Ensure Energy Dashboard entities are enabled (they might have been disabled previously)
                            entity_registry = er.async_get(hass)
                            hub_unique_prefix = f"{hub._name}_"
                            for sensor_mapping in mapping.mappings:
                                unique_id = f"{hub_unique_prefix}{sensor_mapping.target_key}"
                                entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)
                                if entity_id:
                                    entity_entry = entity_registry.async_get(entity_id)
                                    if entity_entry and entity_entry.disabled_by:
                                        _LOGGER.debug(
                                            f"{hub_name}: Enabling previously disabled Energy Dashboard entity: {entity_id}"
                                        )
                                        entity_registry.async_update_entity(entity_id, disabled_by=None)

                        async def async_refresh_energy_dashboard_entities() -> None:
                            energy_dashboard_enabled = config.get(
                                CONF_ENERGY_DASHBOARD_DEVICE, DEFAULT_ENERGY_DASHBOARD_DEVICE
                            )
                            if isinstance(energy_dashboard_enabled, str):
                                energy_dashboard_enabled = energy_dashboard_enabled != "disabled"
                            if not energy_dashboard_enabled:
                                return

                            energy_dashboard_sensors = await create_energy_dashboard_sensors(
                                hub, mapping, hass, config
                            )
                            if not energy_dashboard_sensors:
                                return

                            domain_data = hass.data.setdefault(DOMAIN, {})
                            hub_entry = domain_data.setdefault(hub_name, {})
                            pm_inverter_count = hub.data.get("pm_inverter_count")
                            expected_slaves = max(pm_inverter_count - 1, 0) if pm_inverter_count is not None else None
                            last_slave_count = hub_entry.get("energy_dashboard_last_slave_hub_count")
                            if expected_slaves and expected_slaves > 0:
                                hub_entry["energy_dashboard_refresh_pending"] = (
                                    last_slave_count is None or last_slave_count < expected_slaves
                                )
                            else:
                                hub_entry["energy_dashboard_refresh_pending"] = False

                            energy_dashboard_entities = []
                            desired_keys = {descr.key for descr in energy_dashboard_sensors}
                            energy_dashboard_platform_name = f"{hub_name} Energy Dashboard"
                            for newdescr in energy_dashboard_sensors:
                                existing_sensor = hub.sensorEntities.get(newdescr.key)
                                if existing_sensor:
                                    existing_sensor.entity_description = newdescr
                                    if hasattr(existing_sensor, "_riemann_mapping") and getattr(
                                        newdescr, "_riemann_mapping", None
                                    ):
                                        existing_sensor._riemann_mapping = newdescr._riemann_mapping
                                        existing_sensor._filter_function = (
                                            newdescr._riemann_mapping.filter_function
                                            if newdescr._riemann_mapping
                                            else None
                                        ) or (lambda v: v)
                                    if newdescr.register < 0 and newdescr.value_function:
                                        hub.computedSensors[newdescr.key] = newdescr
                                    continue

                                entityToListSingle(
                                    hub,
                                    energy_dashboard_platform_name,
                                    energy_dashboard_entities,
                                    initial_groups,
                                    hub.computedSensors,
                                    hub.device_info,
                                    newdescr,
                                    None,
                                    readFollowUp,
                                )

                            if energy_dashboard_entities:
                                _LOGGER.info(
                                    f"{hub_name}: Registering {len(energy_dashboard_entities)} refreshed Energy Dashboard entities"
                                )
                                entities.extend(energy_dashboard_entities)
                                async_add_entities(energy_dashboard_entities)

                            from .energy_dashboard import (
                                ED_SWITCH_GRID_TO_BATTERY,
                                ED_SWITCH_HOME_CONSUMPTION,
                                ED_SWITCH_PV_VARIANTS,
                                get_energy_dashboard_switch_state,
                            )

                            pv_state = get_energy_dashboard_switch_state(hub, ED_SWITCH_PV_VARIANTS)
                            home_state = get_energy_dashboard_switch_state(hub, ED_SWITCH_HOME_CONSUMPTION)
                            grid_state = get_energy_dashboard_switch_state(hub, ED_SWITCH_GRID_TO_BATTERY)
                            allow_remove_pv = pv_state is False
                            allow_remove_home = home_state is False
                            allow_remove_grid = grid_state is False

                            if allow_remove_pv or allow_remove_home or allow_remove_grid:
                                entity_registry = er.async_get(hass)
                                for key in list(hub.sensorEntities.keys()):
                                    if key in desired_keys:
                                        continue
                                    is_pv_variant = "_pv_power_" in key or "_pv_energy_" in key
                                    is_home = "_home_consumption_" in key
                                    is_grid = "_grid_to_battery_" in key
                                    if (
                                        (is_pv_variant and allow_remove_pv)
                                        or (is_home and allow_remove_home)
                                        or (is_grid and allow_remove_grid)
                                    ):
                                        unique_id = f"{energy_dashboard_platform_name}_{key}"
                                        entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)
                                        if entity_id:
                                            entity_registry.async_remove(entity_id)
                                        hub.sensorEntities.pop(key, None)
                                        hub.computedSensors.pop(key, None)

                            # Recompute ED values immediately to relink unavailable entities.
                            for newdescr in energy_dashboard_sensors:
                                if newdescr.register < 0 and newdescr.value_function:
                                    try:
                                        hub.data[newdescr.key] = newdescr.value_function(0, newdescr, hub.data)
                                    except Exception as e:
                                        _LOGGER.debug(
                                            f"{hub_name}: ED refresh value_function failed for {newdescr.key}: {e}"
                                        )
                                        continue
                                    sens = hub.sensorEntities.get(newdescr.key)
                                    if sens and not getattr(newdescr, "internal", False):
                                        sens.modbus_data_updated()

                        domain_data = hass.data.setdefault(DOMAIN, {})
                        hub_entry = domain_data.setdefault(hub_name, {})
                        hub_entry["energy_dashboard_refresh_callback"] = async_refresh_energy_dashboard_entities
            else:
                _LOGGER.debug(
                    f"{hub_name}: ENERGY_DASHBOARD_MAPPING not found (plugin may not support Energy Dashboard)"
                )
        except Exception as e:
            _LOGGER.error(f"{hub_name}: Error during Energy Dashboard setup: {e}", exc_info=True)
            # Continue without Energy Dashboard support - don't break the integration

    return True


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
        # self.entity_id = "sensor." + platform_name + "_" + description.key
        self.entity_description: BaseModbusSensorEntityDescription = description
        self._attr_extra_state_attributes = _energy_dashboard_mapping_attrs(self.entity_description, self._hub)

    async def async_added_to_hass(self):
        """Register callbacks."""
        await self._hub.async_add_solax_modbus_sensor(self)

    async def async_will_remove_from_hass(self) -> None:
        await self._hub.async_remove_solax_modbus_sensor(self)

    @callback
    def modbus_data_updated(self):
        self._attr_extra_state_attributes = _energy_dashboard_mapping_attrs(self.entity_description, self._hub)
        self.async_write_ha_state()

    @callback
    def _update_state(self):  # never called ?????
        _LOGGER.info(
            f"update_state {self.entity_description.key} : {self._hub.data.get(self.entity_description.key, 'None')}"
        )
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
            # try:    val = self._hub.data[self.entity_description.key] *self.entity_description.read_scale # a bit ugly as we might multiply strings or other types with 1
            # except: val = self._hub.data[self.entity_description.key] # not a number
            # return val
        return None

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes


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
        riemann_mapping = getattr(description, "_riemann_mapping", None)
        if riemann_mapping is None:
            _LOGGER.error(f"{platform_name}: Riemann sum sensor {description.key} missing mapping")

        self._riemann_mapping = riemann_mapping
        self._filter_function = (riemann_mapping.filter_function if riemann_mapping else None) or (lambda v: v)
        self._last_power_value = None
        self._last_update_time = None
        self._total_energy = 0.0  # kWh
        self._last_reset_date = dt_util.now().date()
        self._attr_extra_state_attributes = self._riemann_extra_attrs()

    def _riemann_extra_attrs(self) -> dict:
        attrs = _energy_dashboard_mapping_attrs(self.entity_description, self._hub)
        if self._last_reset_date:
            attrs["last_reset_date"] = self._last_reset_date.isoformat()
        return attrs

    async def async_added_to_hass(self):
        """Register callbacks and restore state."""
        # Restore previous state if available
        if last_state := await self.async_get_last_state():
            if last_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    self._total_energy = float(last_state.state)
                    if last_state.last_updated:
                        self._last_update_time = last_state.last_updated.timestamp()
                    _LOGGER.debug(
                        f"{self._platform_name}: Restored Riemann sum state for {self.entity_description.key}: {self._total_energy} kWh"
                    )
                except (ValueError, AttributeError, TypeError) as e:
                    _LOGGER.debug(
                        f"{self._platform_name}: Could not restore Riemann sum state for {self.entity_description.key}: {e}"
                    )
            reset_date = last_state.attributes.get("last_reset_date") if last_state.attributes else None
            if reset_date:
                try:
                    self._last_reset_date = date.fromisoformat(reset_date)
                except (TypeError, ValueError):
                    self._last_reset_date = dt_util.now().date()

        hub_name = getattr(self._hub, "_name", None)
        if hub_name and get_debug_setting(
            hub_name,
            "reset_riemann_sums_on_restart",
            self._hub.config,
            self._hub._hass,
            default=False,
        ):
            _LOGGER.warning(
                f"{hub_name}: reset_riemann_sums_on_restart enabled for {self.entity_description.key} - resetting daily total"
            )
            self._total_energy = 0.0
            self._last_reset_date = dt_util.now().date()
            self._last_power_value = None
            self._last_update_time = None
            from .energy_dashboard import RIEMANN_ROUND_DIGITS

            self._hub.data[self.entity_description.key] = round(self._total_energy, RIEMANN_ROUND_DIGITS)
            self._attr_extra_state_attributes = self._riemann_extra_attrs()
            self.async_write_ha_state()

        # Register with hub
        await self._hub.async_add_solax_modbus_sensor(self)

    @callback
    def modbus_data_updated(self):
        """Calculate energy when data is updated."""
        if self._riemann_mapping is None:
            return
        from .energy_dashboard import RIEMANN_ROUND_DIGITS

        # Get current power value from source sensor
        data_hub = getattr(self.entity_description, "_riemann_data_hub", None) or self._hub
        hub_data = getattr(data_hub, "data", None) or getattr(data_hub, "datadict", {})
        source_key = self._riemann_mapping.get_source_key(hub_data)

        # PV variant energy should track the matching Energy Dashboard PV power entity
        # to stay aligned in parallel mode. The Master inverter uses its own raw
        # pv_power_{n}, so only use ED power for Slave-derived variants.
        current_power = None
        if "_pv_energy_" in self.entity_description.key:
            if data_hub is not self._hub:
                ed_power_key = self.entity_description.key.replace("_pv_energy_", "_pv_power_")
                ed_hub_data = getattr(self._hub, "data", None) or getattr(self._hub, "datadict", {})
                current_power = ed_hub_data.get(ed_power_key)

        if current_power is None:
            current_power = hub_data.get(source_key)

        if current_power is None:
            # Source sensor not available, keep current total
            return

        # Apply filter function (e.g., only > 0 for import, only < 0 for export)
        filtered_power = self._filter_function(current_power)

        # Get current time
        current_time = time.time()
        current_date = dt_util.now().date()

        # Reset daily totals at midnight (local time)
        if self._last_reset_date is None or current_date != self._last_reset_date:
            self._total_energy = 0.0
            self._last_reset_date = current_date
            self._last_power_value = filtered_power
            self._last_update_time = current_time
            self._hub.data[self.entity_description.key] = round(self._total_energy, RIEMANN_ROUND_DIGITS)
            self._attr_extra_state_attributes = self._riemann_extra_attrs()
            self.async_write_ha_state()
            return

        # Calculate energy increment if we have previous value
        if self._last_power_value is not None and self._last_update_time is not None:
            # Trapezoidal integration: ΔE = (P_prev + P_curr) / 2 * Δt / 3600 / 1000
            # P in W, Δt in seconds, result in kWh
            delta_time = current_time - self._last_update_time
            if delta_time > 0:
                avg_power = (self._last_power_value + filtered_power) / 2.0
                energy_increment = (avg_power * delta_time) / 3600.0 / 1000.0  # Convert to kWh
                self._total_energy += energy_increment

        # Update stored values
        self._last_power_value = filtered_power
        self._last_update_time = current_time

        # Round result and store in hub.data (so native_value property works)
        self._hub.data[self.entity_description.key] = round(self._total_energy, RIEMANN_ROUND_DIGITS)
        self._attr_extra_state_attributes = self._riemann_extra_attrs()

        # Update state
        self.async_write_ha_state()

    @property
    def native_value(self):
        """Return the calculated energy value."""
        # Value is stored in hub.data by modbus_data_updated
        if self.entity_description.key in self._hub.data:
            return self._hub.data[self.entity_description.key]
        return self._total_energy

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes


def entityToList(
    hub,
    hub_name,
    entities,
    groups,
    computedRegs,
    device_info: DeviceInfo,
    sensor_types,
    name_prefix,
    key_prefix,
    readPreparation,
    readFollowUp,
):  # noqa: D103
    for sensor_description in sensor_types:
        if hub.plugin.matchInverterWithMask(
            hub._invertertype, sensor_description.allowedtypes, hub.seriesnumber, sensor_description.blacklist
        ):
            # apply scale exceptions early
            if sensor_description.value_series is not None:
                for serie_value in range(sensor_description.value_series):
                    newdescr = copy(sensor_description)
                    newdescr.name = name_prefix + newdescr.name.replace("{}", str(serie_value + 1))
                    newdescr.key = key_prefix + newdescr.key.replace("{}", str(serie_value + 1))
                    newdescr.register = sensor_description.register + serie_value
                    entityToListSingle(
                        hub,
                        hub_name,
                        entities,
                        groups,
                        computedRegs,
                        device_info,
                        newdescr,
                        readPreparation,
                        readFollowUp,
                    )
            else:
                newdescr = copy(sensor_description)
                try:
                    newdescr.name = name_prefix + newdescr.name
                except:
                    newdescr.name = newdescr.name

                newdescr.key = key_prefix + newdescr.key
                entityToListSingle(
                    hub, hub_name, entities, groups, computedRegs, device_info, newdescr, readPreparation, readFollowUp
                )


def entityToListSingle(
    hub, hub_name, entities, groups, computedRegs, device_info: DeviceInfo, newdescr, readPreparation, readFollowUp
):  # noqa: D103
    if newdescr.read_scale_exceptions:
        for (
            prefix,
            value,
        ) in newdescr.read_scale_exceptions:
            if hub.seriesnumber.startswith(prefix):
                newdescr = replace(newdescr, read_scale=value)

    # Check if this sensor has custom Energy Dashboard device info
    if hasattr(newdescr, "_energy_dashboard_device_info"):
        device_info = newdescr._energy_dashboard_device_info

    # Check if this is a Riemann sum sensor
    if getattr(newdescr, "_is_riemann_sum_sensor", False):
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
    if isinstance(deplist, str):
        deplist = (deplist,)
    if isinstance(
        deplist,
        (
            list,
            tuple,
        ),
    ):
        _LOGGER.debug(f"{hub.name}: {newdescr.key} depends on entities {deplist}")
        for dep_on in deplist:  # register inter-sensor dependencies (e.g. for value functions)
            if dep_on != newdescr.key:
                hub.entity_dependencies.setdefault(dep_on, []).append(newdescr.key)  # can be more than one
    # internal sensors are only used for polling values for selects, etc
    if not getattr(newdescr, "internal", None):
        entities.append(sensor)
    if newdescr.sleepmode == SLEEPMODE_NONE:
        hub.sleepnone.append(newdescr.key)
    if newdescr.sleepmode == SLEEPMODE_ZERO:
        hub.sleepzero.append(newdescr.key)
    if newdescr.register < 0:  # entity without modbus address
        enabled = is_entity_enabled(
            hub._hass, hub, newdescr, use_default=True
        )  # dont compute disabled entities anymore
        # if not enabled: _LOGGER.info(f"is_entity_enabled called for disabled entity {newdescr.key}")
        if newdescr.value_function and (
            enabled or newdescr.internal
        ):  # *** dont compute disabled entities anymore unless internal
            computedRegs[newdescr.key] = newdescr
        else:
            if enabled:
                _LOGGER.warning(
                    f"{hub_name}: entity without modbus register address and without value_function found: {newdescr.key}"
                )
    else:
        # target group
        interval_group = groups.setdefault(hub.scan_group(sensor), empty_input_interval_group_lambda())
        device_group_key = hub.device_group_key(device_info)
        device_group = interval_group.device_groups.setdefault(device_group_key, empty_input_device_group_lambda())
        holdingRegs = device_group.holdingRegs
        inputRegs = device_group.inputRegs
        device_group.readPreparation = readPreparation
        device_group.readFollowUp = readFollowUp

        if newdescr.register_type == REG_HOLDING:
            if newdescr.register in holdingRegs:  # duplicate or 2 bytes in one register ?
                if newdescr.unit in (
                    REGISTER_U8H,
                    REGISTER_U8L,
                ) and holdingRegs[newdescr.register].unit in (
                    REGISTER_U8H,
                    REGISTER_U8L,
                ):
                    first = holdingRegs[newdescr.register]
                    holdingRegs[newdescr.register] = {first.unit: first, newdescr.unit: newdescr}
                else:
                    _LOGGER.warning(
                        f"{hub_name}: holding register already used: 0x{newdescr.register:x} {newdescr.key}"
                    )
            else:
                holdingRegs[newdescr.register] = newdescr
        elif newdescr.register_type == REG_INPUT:
            if newdescr.register in inputRegs:  # duplicate or 2 bytes in one register ?
                first = inputRegs[newdescr.register]
                inputRegs[newdescr.register] = {first.unit: first, newdescr.unit: newdescr}
                _LOGGER.warning(f"{hub_name}: input register already declared: 0x{newdescr.register:x} {newdescr.key}")
            else:
                inputRegs[newdescr.register] = newdescr
        else:
            _LOGGER.warning(f"{hub_name}: entity declaration without register_type found: {newdescr.key}")
