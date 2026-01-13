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

    source_key: str  # Original sensor key (e.g., "measured_power")
    target_key: str  # Energy Dashboard sensor key (e.g., "grid_power_energy_dashboard")
    name: str  # Display name (e.g., "Grid Power (Energy Dashboard)")
    source_key_pm: Optional[str] = None  # Parallel mode source (e.g., "pm_total_measured_power")
    invert: bool = False  # Whether to invert the value
    icon: Optional[str] = None  # Optional icon override
    unit: Optional[str] = None  # Optional unit override
    invert_function: Optional[Callable] = None  # Custom invert function if needed
    filter_function: Optional[Callable] = None  # Universal filter function (applies to all sensor types)
    use_riemann_sum: bool = False  # Enable Riemann sum calculation for energy sensors
    allowedtypes: int = 0  # Bitmask for inverter types (same pattern as sensor definitions, 0 = all types)

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


def create_energy_dashboard_sensors(hub, mapping: EnergyDashboardMapping) -> list:
    """Generate Energy Dashboard sensor entities from mapping."""
    if not mapping.enabled:
        return []

    sensors = []
    energy_dashboard_device_info = create_energy_dashboard_device_info(hub)

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
        # Create value function that uses mapping's get_value method
        # This handles parallel mode detection automatically
        def make_value_function(sensor_mapping: EnergyDashboardSensorMapping):
            def value_function(initval, descr, datadict):
                return sensor_mapping.get_value(datadict)

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

        # Create sensor entity description
        sensor_desc = BaseModbusSensorEntityDescription(
            name=sensor_mapping.name,
            key=sensor_mapping.target_key,
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
        if logger:
            logger.debug(f"{hub_name}: parallel_setting from hub.data: {parallel_setting}")
    
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
                if logger:
                    logger.debug(f"{hub_name}: Waiting for initial probe to complete before polling parallel_setting")
                
                # Wait for the initial bisect task to complete (if it exists)
                if initial_bisect_task and not initial_bisect_task.done():
                    if logger:
                        logger.debug(f"{hub_name}: Initial bisect task still running, waiting for completion")
                    try:
                        # Wait up to 15 seconds for bisect task to complete
                        await asyncio.wait_for(initial_bisect_task, timeout=15.0)
                        if logger:
                            logger.debug(f"{hub_name}: Initial bisect task completed")
                    except asyncio.TimeoutError:
                        if logger:
                            logger.warning(f"{hub_name}: Initial bisect task timeout after 15s, may be stuck")
                    except Exception as e:
                        if logger:
                            logger.debug(f"{hub_name}: Error waiting for bisect task: {e}")
                
                # Also wait for probe_ready event (in case task completed but event not set yet)
                if probe_ready and not probe_ready.is_set():
                    try:
                        # Wait up to 5 seconds for probe event (shorter since task should be done)
                        await asyncio.wait_for(probe_ready.wait(), timeout=5.0)
                        if logger:
                            logger.debug(f"{hub_name}: Initial probe completed, proceeding with parallel_setting read")
                    except asyncio.TimeoutError:
                        if logger:
                            logger.warning(f"{hub_name}: Initial probe event timeout after 5s, proceeding anyway (probe may be stuck)")
                    except Exception as e:
                        if logger:
                            logger.debug(f"{hub_name}: Error waiting for probe event: {e}, proceeding anyway")
            
            # Small delay to let probe settle if it just completed
            await asyncio.sleep(0.5)
            
            if logger:
                logger.debug(f"{hub_name}: parallel_setting not in hub.data, polling inverter registers")
            max_retries = 3
            retry_delay = 0.5
            for retry in range(max_retries):
                try:
                    # Find the first interval group that has device groups and read all device groups in it
                    for interval_group in hub_groups.values():
                        if hasattr(interval_group, 'device_groups') and interval_group.device_groups:
                            if logger and retry > 0:
                                logger.debug(f"{hub_name}: Retrying parallel_setting read (attempt {retry + 1}/{max_retries})")
                            # Read each device group in this interval group
                            for device_group in interval_group.device_groups.values():
                                read_result = await hub.async_read_modbus_data(device_group)
                                if read_result:
                                    # Data is written to hub.data during the read (data is alias to self.data), check immediately after
                                    if hub_data:
                                        parallel_setting = hub_data.get("parallel_setting")
                                        if parallel_setting and parallel_setting != "unknown":
                                            if logger:
                                                logger.debug(f"{hub_name}: parallel_setting read from inverter: {parallel_setting}")
                                            break
                                elif not read_result and logger and retry < max_retries - 1:
                                    logger.debug(f"{hub_name}: Modbus read failed, retrying in {retry_delay}s")
                            if parallel_setting and parallel_setting != "unknown":
                                break
                    if parallel_setting and parallel_setting != "unknown":
                        break
                    # Wait before retry (except on last attempt)
                    if retry < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                except Exception as e:
                    if logger:
                        logger.debug(f"{hub_name}: Error during parallel_setting read (attempt {retry + 1}): {e}")
                    if retry < max_retries - 1:
                        await asyncio.sleep(retry_delay)
    
    # Try datadict as fallback (safely check if attribute exists)
    if parallel_setting is None:
        datadict = getattr(hub, 'datadict', None)
        if datadict:
            parallel_setting = datadict.get("parallel_setting")
            if logger:
                logger.debug(f"{hub_name}: parallel_setting from datadict: {parallel_setting}")
    
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
                if logger:
                    logger.debug(f"{hub_name}: parallel_setting from entity {entity_id}: {parallel_setting}")
        except Exception as e:
            if logger:
                logger.debug(f"{hub_name}: Error looking up entity {entity_id}: {e}")
    
    # Skip only if definitively a Slave
    if parallel_setting == "Slave":
        if logger:
            logger.warning(f"{hub_name}: Energy Dashboard enabled but device will not be created (Slave inverter - only Master has system totals)")
        return False
    
    # Master, single, or unknown: Create device
    if logger:
        logger.info(f"{hub_name}: Creating Energy Dashboard device (parallel_mode: {parallel_setting or 'unknown'})")
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
