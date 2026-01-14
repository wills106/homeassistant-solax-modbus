"""Energy Dashboard Virtual Device Framework.

This module provides a plugin-independent framework for creating Energy Dashboard
sensors with automatic virtual device creation and per-sensor invert configuration.

The framework allows plugins to define simple mapping structures that automatically
handle:
- Virtual device creation
- Sensor generation with correct value inversion
- Parallel mode support (dynamic source selection)
- Config flow option handling
- Riemann sum integration for energy sensors (GEN1 support)
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass, RestoreEntity
from homeassistant.const import UnitOfPower, UnitOfEnergy, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    INVERTER_IDENT,
    BaseModbusSensorEntityDescription,
)

_LOGGER = logging.getLogger(__name__)

# Central Riemann sum configuration (applies to all Riemann sensors)
RIEMANN_METHOD = "trapezoidal"  # Integration method: "trapezoidal", "left", "right"
RIEMANN_ROUND_DIGITS = 3  # Precision for integration result


@dataclass
class EnergyDashboardSensorMapping:
    """Mapping definition for a single Energy Dashboard sensor."""

    source_key: str  # Original sensor key (e.g., "measured_power") or pattern with {n} placeholder
    target_key: str  # Energy Dashboard sensor key (e.g., "grid_power_energy_dashboard") or pattern with {n}
    name: str  # Display name (e.g., "Grid Power (Energy Dashboard)") or pattern with {n}
    source_key_pm: Optional[str] = None  # Parallel mode source (e.g., "pm_total_measured_power")
    invert: bool = False  # Whether to invert the value
    icon: Optional[str] = None  # Optional icon override
    unit: Optional[str] = None  # Optional unit override
    invert_function: Optional[Callable] = None  # Custom invert function if needed
    filter_function: Optional[Callable] = None  # Universal filter function (applies to all sensor types)
    use_riemann_sum: bool = False  # Enable Riemann sum calculation for energy sensors
    allowedtypes: int = 0  # Bitmask for inverter types (same pattern as sensor definitions, 0 = all types)
    max_variants: int = 4  # Maximum number of variants for pattern-based mapping (when {n} placeholder is used)

    def get_source_key(self, datadict: dict) -> str:
        """Determine which source key to use based on parallel mode."""
        parallel_setting = datadict.get("parallel_setting", "Free")

        if parallel_setting == "Master" and self.source_key_pm:
            # Validate PM sensor exists before using it
            if self.source_key_pm not in datadict:
                _LOGGER.warning(
                    f"Parallel Master detected but PM sensor {self.source_key_pm} not found, "
                    f"falling back to {self.source_key}"
                )
                return self.source_key
            return self.source_key_pm  # Use PM sensor on Master

        return self.source_key  # Use regular sensor (single mode or Slave)

    def get_value(self, datadict: dict) -> float:
        """Get value from source sensor, applying filter, invert, and custom functions."""
        source_key = self.get_source_key(datadict)  # Handles parallel mode
        value = datadict.get(source_key, 0)

        if value is None:
            _LOGGER.warning(f"Source sensor {source_key} not found, using 0")
            return 0

        # Apply filter function first (universal - applies to all sensor types)
        if self.filter_function:
            value = self.filter_function(value)

        # Apply custom invert function if specified
        if self.invert_function:
            return self.invert_function(value, datadict)

        # Apply simple invert if needed
        return -value if self.invert else value


@dataclass
class EnergyDashboardMapping:
    """Complete mapping structure for a plugin."""

    plugin_name: str  # Plugin identifier
    mappings: list[EnergyDashboardSensorMapping]  # List of sensor mappings
    enabled: bool = True  # Whether Energy Dashboard sensors are enabled
    parallel_mode_supported: bool = True  # Whether plugin supports parallel mode


# RiemannSumEnergySensor class is defined in sensor.py
# Import it here for reference (but actual class is in sensor.py to avoid circular imports)


def create_energy_dashboard_device_info(hub) -> DeviceInfo:
    """Create DeviceInfo for Energy Dashboard virtual device."""
    plugin_name = hub.plugin.plugin_name
    if hub.inverterNameSuffix:
        plugin_name = f"{plugin_name} {hub.inverterNameSuffix}"

    return DeviceInfo(
        identifiers={(DOMAIN, f"{hub._name}_energy_dashboard", "ENERGY_DASHBOARD")},
        manufacturer=hub.plugin.plugin_manufacturer,
        model=f"{hub.plugin.inverter_model} - Energy Dashboard",
        name=f"{plugin_name} - Energy Dashboard",
        via_device=(DOMAIN, hub._name, INVERTER_IDENT),
    )


def _create_sensor_from_mapping(sensor_mapping: EnergyDashboardSensorMapping, hub, energy_dashboard_device_info, 
                                 source_hub=None, name_prefix="") -> list:
    """Create a single sensor entity from a mapping (helper function).
    
    Args:
        sensor_mapping: The sensor mapping definition
        hub: The hub instance (for device info and types)
        energy_dashboard_device_info: Device info for the virtual device
        source_hub: Optional hub to read data from (if different from hub, e.g., for Slave sensors)
        name_prefix: Optional prefix to add to sensor name (e.g., "All ", "Solax 1 ")
    """
    _LOGGER.debug(f"_create_sensor_from_mapping: name_prefix='{name_prefix}', target_key={sensor_mapping.target_key}")
    sensors = []
    
    # Use source_hub if provided, otherwise use hub
    data_hub = source_hub if source_hub is not None else hub
    
    # Create value function that uses mapping's get_value method
    # This handles parallel mode detection automatically
    # Capture data_hub in closure to avoid late binding issues
    def make_value_function(sensor_mapping: EnergyDashboardSensorMapping):
        captured_hub = data_hub  # Capture in closure
        def value_function(initval, descr, datadict):
            # Use captured_hub's data dictionary instead of the passed datadict
            # This allows reading from Slave hubs
            hub_data = getattr(captured_hub, 'data', None) or getattr(captured_hub, 'datadict', datadict)
            return sensor_mapping.get_value(hub_data)

        return value_function

    # Detect sensor type: power vs energy
    # Energy sensors: use Riemann sum OR target_key contains "energy" but not "power"
    # Power sensors: target_key contains "power" (even if it also contains "energy")
    target_key_lower = sensor_mapping.target_key.lower()
    is_energy_sensor = (
        sensor_mapping.use_riemann_sum or
        ("energy" in target_key_lower and "power" not in target_key_lower)
    )

    # Set attributes based on sensor type
    if is_energy_sensor:
        # Energy sensor attributes
        device_class = SensorDeviceClass.ENERGY
        state_class = SensorStateClass.TOTAL_INCREASING
        unit = UnitOfEnergy.KILO_WATT_HOUR
        default_icon = "mdi:lightning-bolt"
    else:
        # Power sensor attributes
        device_class = SensorDeviceClass.POWER
        state_class = SensorStateClass.MEASUREMENT
        unit = UnitOfPower.WATT
        default_icon = "mdi:flash"

    # Add name prefix if provided
    sensor_name = f"{name_prefix}{sensor_mapping.name}" if name_prefix else sensor_mapping.name
    
    # Create unique key by adding prefix to target_key to avoid collisions
    # Convert name_prefix ("All ", "SolaX 1 ", etc.) to key_prefix ("all_", "solax_1_", etc.)
    if name_prefix:
        key_prefix = name_prefix.lower().replace(" ", "_")
        sensor_key = f"{key_prefix}{sensor_mapping.target_key}"
    else:
        sensor_key = sensor_mapping.target_key
    
    # Create sensor entity description
    sensor_desc = BaseModbusSensorEntityDescription(
        name=sensor_name,
        key=sensor_key,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=state_class,
        value_function=make_value_function(sensor_mapping),
        allowedtypes=hub._invertertype,  # Use same types as source sensor
        icon=sensor_mapping.icon or default_icon,
        register=-1,  # No modbus register (computed sensor)
        # Custom device_info will be set during sensor creation
    )

    # Store mapping info for sensor creation
    sensor_desc._energy_dashboard_device_info = energy_dashboard_device_info
    
    # Mark Riemann sum sensors for special handling
    if sensor_mapping.use_riemann_sum:
        sensor_desc._is_riemann_sum_sensor = True
        sensor_desc._riemann_mapping = sensor_mapping
    else:
        sensor_desc._is_riemann_sum_sensor = False
    
    sensors.append(sensor_desc)
    return sensors


def _find_slave_hubs(hass, master_hub):
    """Find all Slave hubs in parallel mode.
    
    Args:
        hass: Home Assistant instance
        master_hub: The Master hub instance
    
    Returns:
        List of Slave hub instances
    """
    slave_hubs = []
    if not hass:
        return slave_hubs
    
    domain_data = hass.data.get(DOMAIN, {})
    master_name = getattr(master_hub, '_name', None)
    
    for hub_name, hub_data in domain_data.items():
        # Skip self (Master)
        if hub_name == master_name:
            continue
        
        hub_instance = hub_data.get("hub")
        if not hub_instance:
            continue
        
        # Check if Slave
        hub_data_dict = getattr(hub_instance, 'data', None) or getattr(hub_instance, 'datadict', {})
        parallel_setting = hub_data_dict.get("parallel_setting")
        if parallel_setting == "Slave":
            slave_hubs.append((hub_name, hub_instance))
    
    return slave_hubs


def _needs_aggregation(target_key):
    """Check if a sensor needs aggregation (sum of Master + Slaves).
    
    Energy sensors that need aggregation:
    - battery_energy_charge_energy_dashboard
    - battery_energy_discharge_energy_dashboard
    - solar_energy_production_energy_dashboard
    
    Grid energy doesn't need aggregation (Master already aggregates all).
    """
    target_key_lower = target_key.lower()
    return (
        "battery_energy_charge" in target_key_lower or
        "battery_energy_discharge" in target_key_lower or
        "solar_energy_production" in target_key_lower
    )


def _create_aggregated_value_function(sensor_mapping: EnergyDashboardSensorMapping, master_hub, slave_hubs):
    """Create a value function that sums Master + all Slaves for aggregation.
    
    Handles edge cases:
    - No Slaves: Returns Master value only
    - Slave hub offline: Treats missing values as 0, logs debug message
    - Missing keys: Treats as 0, continues with other Slaves
    """
    master_name = getattr(master_hub, '_name', 'Unknown')
    
    def value_function(initval, descr, datadict):
        # Get Master value (individual inverter value)
        master_data = getattr(master_hub, 'data', None) or getattr(master_hub, 'datadict', datadict)
        try:
            master_value = sensor_mapping.get_value(master_data)
            total = master_value if master_value is not None else 0
        except Exception as e:
            _LOGGER.debug(f"{master_name}: Error getting Master value for aggregation: {e}")
            total = 0
        
        # Sum all Slave values
        for slave_name, slave_hub in slave_hubs:
            try:
                slave_data = getattr(slave_hub, 'data', None) or getattr(slave_hub, 'datadict', {})
                if not slave_data:
                    _LOGGER.debug(f"{master_name}: Slave hub '{slave_name}' has no data, using 0 for aggregation")
                    continue
                
                slave_value = sensor_mapping.get_value(slave_data)
                if slave_value is not None:
                    total += slave_value
                # If slave_value is None, treat as 0 (already handled by not adding)
            except Exception as e:
                _LOGGER.debug(f"{master_name}: Error getting Slave '{slave_name}' value for aggregation: {e}, using 0")
                # Continue with other Slaves (treat this Slave as 0)
        
        return total
    
    return value_function


def create_energy_dashboard_sensors(hub, mapping: EnergyDashboardMapping, hass=None) -> list:
    """Generate Energy Dashboard sensor entities from mapping.
    
    Args:
        hub: SolaXModbusHub instance
        mapping: EnergyDashboardMapping configuration
        hass: Home Assistant instance (optional, needed for Slave hub access)
    """
    # NOTE: If logging from this module stops working, clear Python cache to force recompile:
    # rm -f /homeassistant/custom_components/solax_modbus/__pycache__/energy_dashboard*.pyc
    # Then restart Home Assistant.
    
    # try:
    #     import sys
    #     sys.stderr.write("STDERR: create_energy_dashboard_sensors called\n")
    #     sys.stderr.flush()
    #     _LOGGER.error("TEST ERROR LOG - create_energy_dashboard_sensors called")
    # except Exception as e:
    #     sys.stderr.write(f"STDERR: Exception during logging: {e}\n")
    #     sys.stderr.flush()
    #return []
    
    if not mapping.enabled:
        _LOGGER.debug("Energy Dashboard mapping is disabled")
        return []

    sensors = []
    energy_dashboard_device_info = create_energy_dashboard_device_info(hub)
    
    # Determine if this is a Master hub
    hub_data = getattr(hub, 'data', None) or getattr(hub, 'datadict', {})
    parallel_setting = hub_data.get("parallel_setting", "Free")
    is_master = parallel_setting == "Master"
    
    # Find Slave hubs if this is a Master
    slave_hubs = []
    if is_master and hass:
        slave_hubs = _find_slave_hubs(hass, hub)
        if slave_hubs:
            _LOGGER.info(f"Found {len(slave_hubs)} Slave hub(s) for Energy Dashboard")
        else:
            _LOGGER.debug("No Slave hubs found for Energy Dashboard (Master mode but no Slaves)")
    elif is_master and not hass:
        _LOGGER.warning("Master hub detected but hass not provided - cannot find Slave hubs for aggregation")
    
    # Get inverter name for prefix (e.g., "Solax 1")
    hub_name = getattr(hub, '_name', 'Unknown')
    inverter_name = hub_name

    for sensor_mapping in mapping.mappings:
        # Filter by allowedtypes (same pattern as regular sensors)
        # If allowedtypes is 0, apply to all types (backward compatibility)
        if sensor_mapping.allowedtypes != 0:
            if not hub.plugin.matchInverterWithMask(
                hub._invertertype,
                sensor_mapping.allowedtypes,
                hub.seriesnumber,
                None  # blacklist
            ):
                continue  # Skip this mapping for this inverter type
        
        # Check if this is a pattern-based mapping (contains {n} placeholder)
        has_pattern = "{n}" in sensor_mapping.source_key or "{n}" in sensor_mapping.target_key or "{n}" in sensor_mapping.name
        
        if has_pattern:
            # Pattern-based mapping: create sensors for each detected variant
            # For Master: Create for Master + all Slaves
            # For Standalone: Create only for this inverter
            
            # Detect variants from Master hub first
            master_hub_data = getattr(hub, 'data', None) or getattr(hub, 'datadict', {})
            base_source_key = sensor_mapping.source_key.replace("{n}", "")
            master_variants = []
            for n in range(1, sensor_mapping.max_variants + 1):
                variant_key = f"{base_source_key}{n}"
                if variant_key in master_hub_data:
                    master_variants.append(n)
            
            # For Master: Create "Solax 1" variants
            for variant_num in master_variants:
                variant_source_key = sensor_mapping.source_key.replace("{n}", str(variant_num))
                variant_target_key = sensor_mapping.target_key.replace("{n}", str(variant_num))
                variant_name = sensor_mapping.name.replace("{n}", str(variant_num))
                
                variant_mapping = EnergyDashboardSensorMapping(
                    source_key=variant_source_key,
                    target_key=variant_target_key,
                    name=variant_name,
                    source_key_pm=sensor_mapping.source_key_pm,
                    invert=sensor_mapping.invert,
                    icon=sensor_mapping.icon,
                    unit=sensor_mapping.unit,
                    invert_function=sensor_mapping.invert_function,
                    filter_function=sensor_mapping.filter_function,
                    use_riemann_sum=sensor_mapping.use_riemann_sum,
                    allowedtypes=sensor_mapping.allowedtypes,
                    max_variants=sensor_mapping.max_variants,
                )
                
                # Create "Solax 1" variant sensor
                sensors.extend(_create_sensor_from_mapping(variant_mapping, hub, energy_dashboard_device_info, 
                                                          source_hub=hub, name_prefix=f"{inverter_name} "))
            
            # For Master: Create variants for each Slave
            if is_master:
                for slave_name, slave_hub in slave_hubs:
                    # Detect variants from Slave hub
                    slave_hub_data = getattr(slave_hub, 'data', None) or getattr(slave_hub, 'datadict', {})
                    slave_variants = []
                    for n in range(1, sensor_mapping.max_variants + 1):
                        variant_key = f"{base_source_key}{n}"
                        if variant_key in slave_hub_data:
                            slave_variants.append(n)
                    
                    # Create sensors for each Slave variant
                    for variant_num in slave_variants:
                        variant_source_key = sensor_mapping.source_key.replace("{n}", str(variant_num))
                        variant_target_key = sensor_mapping.target_key.replace("{n}", str(variant_num))
                        variant_name = sensor_mapping.name.replace("{n}", str(variant_num))
                        
                        variant_mapping = EnergyDashboardSensorMapping(
                            source_key=variant_source_key,
                            target_key=variant_target_key,
                            name=variant_name,
                            source_key_pm=sensor_mapping.source_key_pm,
                            invert=sensor_mapping.invert,
                            icon=sensor_mapping.icon,
                            unit=sensor_mapping.unit,
                            invert_function=sensor_mapping.invert_function,
                            filter_function=sensor_mapping.filter_function,
                            use_riemann_sum=sensor_mapping.use_riemann_sum,
                            allowedtypes=sensor_mapping.allowedtypes,
                            max_variants=sensor_mapping.max_variants,
                        )
                        
                        # Create "Solax 2/3" variant sensor from Slave hub
                        sensors.extend(_create_sensor_from_mapping(variant_mapping, hub, energy_dashboard_device_info,
                                                                  source_hub=slave_hub, name_prefix=f"{slave_name} "))
        else:
            # Regular mapping: create sensors based on Master/Standalone
            if is_master:
                # For Master: Create "All" sensor and individual inverter sensors
                # Check if this sensor needs aggregation for "All" version
                needs_agg = _needs_aggregation(sensor_mapping.target_key)
                
                # Create "All" sensor
                if sensor_mapping.source_key_pm:
                    # Use PM total for "All" (already aggregated)
                    all_mapping = EnergyDashboardSensorMapping(
                        source_key=sensor_mapping.source_key_pm,  # Use PM version
                        target_key=sensor_mapping.target_key,
                        name=sensor_mapping.name,
                        source_key_pm=None,  # No PM version for PM sensor itself
                        invert=sensor_mapping.invert,
                        icon=sensor_mapping.icon,
                        unit=sensor_mapping.unit,
                        invert_function=sensor_mapping.invert_function,
                        filter_function=sensor_mapping.filter_function,
                        use_riemann_sum=sensor_mapping.use_riemann_sum,
                        allowedtypes=sensor_mapping.allowedtypes,
                        max_variants=sensor_mapping.max_variants,
                    )
                    sensors.extend(_create_sensor_from_mapping(all_mapping, hub, energy_dashboard_device_info,
                                                              source_hub=hub, name_prefix="All "))
                elif needs_agg:
                    # Skip aggregation for Riemann sum sensors (they integrate from power, already aggregated)
                    if sensor_mapping.use_riemann_sum:
                        # Use Master value only for Riemann sum "All" sensor
                        all_mapping = EnergyDashboardSensorMapping(
                            source_key=sensor_mapping.source_key,
                            target_key=sensor_mapping.target_key,
                            name=sensor_mapping.name,
                            source_key_pm=sensor_mapping.source_key_pm,
                            invert=sensor_mapping.invert,
                            icon=sensor_mapping.icon,
                            unit=sensor_mapping.unit,
                            invert_function=sensor_mapping.invert_function,
                            filter_function=sensor_mapping.filter_function,
                            use_riemann_sum=sensor_mapping.use_riemann_sum,
                            allowedtypes=sensor_mapping.allowedtypes,
                            max_variants=sensor_mapping.max_variants,
                        )
                        sensors.extend(_create_sensor_from_mapping(all_mapping, hub, energy_dashboard_device_info,
                                                                  source_hub=hub, name_prefix="All "))
                    else:
                        # Create aggregated "All" sensor (sum Master + Slaves)
                        all_mapping = EnergyDashboardSensorMapping(
                            source_key=sensor_mapping.source_key,
                            target_key=sensor_mapping.target_key,
                            name=sensor_mapping.name,
                            source_key_pm=sensor_mapping.source_key_pm,
                            invert=sensor_mapping.invert,
                            icon=sensor_mapping.icon,
                            unit=sensor_mapping.unit,
                            invert_function=sensor_mapping.invert_function,
                            filter_function=sensor_mapping.filter_function,
                            use_riemann_sum=sensor_mapping.use_riemann_sum,
                            allowedtypes=sensor_mapping.allowedtypes,
                            max_variants=sensor_mapping.max_variants,
                        )
                        # Create sensor with aggregated value function
                        aggregated_sensor = _create_sensor_from_mapping(all_mapping, hub, energy_dashboard_device_info,
                                                                       source_hub=hub, name_prefix="All ")
                        if aggregated_sensor:
                            # Replace value function with aggregated version
                            aggregated_sensor[0].value_function = _create_aggregated_value_function(all_mapping, hub, slave_hubs)
                            sensors.extend(aggregated_sensor)
                else:
                    # Grid energy: Master already aggregates all, use Master value for "All"
                    all_mapping = EnergyDashboardSensorMapping(
                        source_key=sensor_mapping.source_key,
                        target_key=sensor_mapping.target_key,
                        name=sensor_mapping.name,
                        source_key_pm=sensor_mapping.source_key_pm,
                        invert=sensor_mapping.invert,
                        icon=sensor_mapping.icon,
                        unit=sensor_mapping.unit,
                        invert_function=sensor_mapping.invert_function,
                        filter_function=sensor_mapping.filter_function,
                        use_riemann_sum=sensor_mapping.use_riemann_sum,
                        allowedtypes=sensor_mapping.allowedtypes,
                        max_variants=sensor_mapping.max_variants,
                    )
                    sensors.extend(_create_sensor_from_mapping(all_mapping, hub, energy_dashboard_device_info,
                                                              source_hub=hub, name_prefix="All "))
                
                # Create "Solax 1" sensor (Master individual)
                sensors.extend(_create_sensor_from_mapping(sensor_mapping, hub, energy_dashboard_device_info,
                                                          source_hub=hub, name_prefix=f"{inverter_name} "))
                
                # Create "Solax 2/3" sensors from Slave hubs
                for slave_name, slave_hub in slave_hubs:
                    sensors.extend(_create_sensor_from_mapping(sensor_mapping, hub, energy_dashboard_device_info,
                                                              source_hub=slave_hub, name_prefix=f"{slave_name} "))
            else:
                # For Standalone: Create only individual inverter sensor (no "All" prefix)
                sensors.extend(_create_sensor_from_mapping(sensor_mapping, hub, energy_dashboard_device_info,
                                                          source_hub=hub, name_prefix=f"{inverter_name} "))

    return sensors


async def should_create_energy_dashboard_device(hub, config, hass=None, logger=None, initial_groups=None) -> bool:
    """Determine if Energy Dashboard virtual device should be created.

    Args:
        hub: SolaXModbusHub instance
        config: Integration configuration dict
        hass: Home Assistant instance (optional, for entity state lookup)

    Returns:
        bool: True if virtual device should be created
    """
    from .const import (
        CONF_ENERGY_DASHBOARD_DEVICE,
        DEFAULT_ENERGY_DASHBOARD_DEVICE,
    )

    # Simple boolean check - if enabled, always create device (like old "manual" mode)
    # User's explicit choice should be respected regardless of parallel mode
    energy_dashboard_enabled = config.get(
        CONF_ENERGY_DASHBOARD_DEVICE, DEFAULT_ENERGY_DASHBOARD_DEVICE
    )
    
    # Handle legacy string values for backward compatibility
    if isinstance(energy_dashboard_enabled, str):
        if energy_dashboard_enabled == "disabled":
            return False
        elif energy_dashboard_enabled == "manual":
            return True
        elif energy_dashboard_enabled == "enabled":
            # Legacy "enabled" mode: Auto-detect (skip Slaves)
            parallel_setting = None
            datadict = getattr(hub, 'datadict', None)
            if datadict:
                parallel_setting = datadict.get("parallel_setting")
            if parallel_setting == "Slave":
                return False
            return True
        else:  # Any other value, default to enabled
            energy_dashboard_enabled = True
    
    # Boolean value: If disabled, don't create
    if not energy_dashboard_enabled:
        return False
    
    hub_name = getattr(hub, 'name', getattr(hub, '_name', 'unknown'))
    
    # Enabled: Check parallel mode - skip Slaves (Master has system totals)
    parallel_setting = None
    
    # Try hub.data first (most direct access to register values)
    hub_data = getattr(hub, 'data', None)
    if hub_data:
        parallel_setting = hub_data.get("parallel_setting")
        _LOGGER.debug("parallel_setting found in hub.data")
    
    # If not in hub.data, try to trigger a read from hub.groups (after rebuild_blocks)
    # Wait for initial probe to complete before polling to avoid interference
    if parallel_setting is None:
        hub_groups = getattr(hub, 'groups', None)
        if hub_groups:
            import asyncio
            
            # Wait for initial probe to complete (with timeout to avoid blocking forever)
            probe_ready = getattr(hub, '_probe_ready', None)
            initial_bisect_task = getattr(hub, '_initial_bisect_task', None)
            
            # Check if probe is still running
            if probe_ready and not probe_ready.is_set():
                _LOGGER.debug("Waiting for initial probe to complete before polling parallel_setting")
                
                # Wait for the initial bisect task to complete (if it exists)
                if initial_bisect_task and not initial_bisect_task.done():
                    _LOGGER.debug("Initial bisect task still running, waiting for completion")
                    try:
                        # Wait up to 15 seconds for bisect task to complete
                        await asyncio.wait_for(initial_bisect_task, timeout=15.0)
                        _LOGGER.debug("Initial bisect task completed")
                    except asyncio.TimeoutError:
                        _LOGGER.warning("Initial bisect task timeout after 15s, may be stuck")
                    except Exception as e:
                        _LOGGER.debug("Error waiting for bisect task")
                
                # Also wait for probe_ready event (in case task completed but event not set yet)
                if probe_ready and not probe_ready.is_set():
                    try:
                        # Wait up to 5 seconds for probe event (shorter since task should be done)
                        await asyncio.wait_for(probe_ready.wait(), timeout=5.0)
                        _LOGGER.debug("Initial probe completed, proceeding with parallel_setting read")
                    except asyncio.TimeoutError:
                        _LOGGER.warning("Initial probe event timeout after 5s, proceeding anyway")
                    except Exception as e:
                        _LOGGER.debug("Error waiting for probe event, proceeding anyway")
            
            # Small delay to let probe settle if it just completed
            await asyncio.sleep(0.5)
            
            _LOGGER.debug("parallel_setting not in hub.data, polling inverter registers")
            max_retries = 3
            retry_delay = 0.5
            for retry in range(max_retries):
                try:
                    # Find the first interval group that has device groups and read all device groups in it
                    for interval_group in hub_groups.values():
                        if hasattr(interval_group, 'device_groups') and interval_group.device_groups:
                            if retry > 0:
                                _LOGGER.debug("Retrying parallel_setting read")
                            # Read each device group in this interval group
                            for device_group in interval_group.device_groups.values():
                                read_result = await hub.async_read_modbus_data(device_group)
                                if read_result:
                                    # Data is written to hub.data during the read (data is alias to self.data), check immediately after
                                    if hub_data:
                                        parallel_setting = hub_data.get("parallel_setting")
                                        if parallel_setting and parallel_setting != "unknown":
                                            _LOGGER.debug("parallel_setting read from inverter")
                                            break
                                elif not read_result and retry < max_retries - 1:
                                    _LOGGER.debug("Modbus read failed, retrying")
                            if parallel_setting and parallel_setting != "unknown":
                                break
                    if parallel_setting and parallel_setting != "unknown":
                        break
                    # Wait before retry (except on last attempt)
                    if retry < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                except Exception as e:
                    _LOGGER.debug("Error during parallel_setting read")
                    if retry < max_retries - 1:
                        await asyncio.sleep(retry_delay)
    
    # Try datadict as fallback (safely check if attribute exists)
    if parallel_setting is None:
        datadict = getattr(hub, 'datadict', None)
        if datadict:
            parallel_setting = datadict.get("parallel_setting")
            _LOGGER.debug("parallel_setting found in datadict")
    
    # If still not found and hass available, try entity lookup
    if parallel_setting is None and hass is not None:
        hub_name_for_entity = getattr(hub, '_name', hub_name)
        # Convert "SolaX 1" to "solax_1" format for entity ID
        entity_name = hub_name_for_entity.lower().replace(" ", "_")
        entity_id = f"select.{entity_name}_parallel_setting"
        try:
            state = hass.states.get(entity_id)
            if state and state.state:
                parallel_setting = state.state
                _LOGGER.debug("parallel_setting found from entity state")
        except Exception as e:
            _LOGGER.debug("Error looking up entity state")
    
    # Skip only if definitively a Slave
    if parallel_setting == "Slave":
        _LOGGER.warning("Energy Dashboard device will not be created (Slave inverter)")
        return False
    
    # Master, single, or unknown: Create device
    _LOGGER.info("Creating Energy Dashboard device")
    return True


def validate_mapping(mapping: EnergyDashboardMapping) -> bool:
    """Validate mapping structure.

    Args:
        mapping: EnergyDashboardMapping to validate

    Returns:
        bool: True if mapping is valid, False otherwise
    """
    if not mapping.mappings:
        _LOGGER.error(f"Plugin {mapping.plugin_name}: No mappings defined")
        return False

    for sensor_mapping in mapping.mappings:
        if not sensor_mapping.source_key or not sensor_mapping.target_key:
            _LOGGER.error(
                f"Invalid mapping: missing source_key or target_key for {mapping.plugin_name}"
            )
            return False

    return True
