"""Energy Dashboard Virtual Device Framework.

This module provides a plugin-independent framework for creating Energy Dashboard
sensors with automatic virtual device creation and per-sensor invert configuration.

The framework allows plugins to define simple mapping structures that automatically
handle:
- Virtual device creation
- Sensor generation with correct value inversion
- Parallel mode support (dynamic source selection)
- Config flow option handling
"""

import logging
from dataclasses import dataclass
from typing import Optional, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfPower
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    INVERTER_IDENT,
    BaseModbusSensorEntityDescription,
)

_LOGGER = logging.getLogger(__name__)


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
        """Get value from source sensor, applying invert if needed."""
        source_key = self.get_source_key(datadict)  # Handles parallel mode
        value = datadict.get(source_key, 0)

        if value is None:
            _LOGGER.warning(f"Source sensor {source_key} not found, using 0")
            return 0

        if self.invert_function:
            return self.invert_function(value, datadict)

        return -value if self.invert else value


@dataclass
class EnergyDashboardMapping:
    """Complete mapping structure for a plugin."""

    plugin_name: str  # Plugin identifier
    mappings: list[EnergyDashboardSensorMapping]  # List of sensor mappings
    enabled: bool = True  # Whether Energy Dashboard sensors are enabled
    parallel_mode_supported: bool = True  # Whether plugin supports parallel mode


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
        # Create value function that uses mapping's get_value method
        # This handles parallel mode detection automatically
        def make_value_function(sensor_mapping: EnergyDashboardSensorMapping):
            def value_function(initval, descr, datadict):
                return sensor_mapping.get_value(datadict)

            return value_function

        # Create sensor entity description
        sensor_desc = BaseModbusSensorEntityDescription(
            name=sensor_mapping.name,
            key=sensor_mapping.target_key,
            native_unit_of_measurement=UnitOfPower.WATT,
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            value_function=make_value_function(sensor_mapping),
            allowedtypes=hub._invertertype,  # Use same types as source sensor
            icon=sensor_mapping.icon or "mdi:flash",
            register=-1,  # No modbus register (computed sensor)
            # Custom device_info will be set during sensor creation
        )

        # Store mapping info for sensor creation
        sensor_desc._energy_dashboard_device_info = energy_dashboard_device_info
        sensors.append(sensor_desc)

    return sensors


def should_create_energy_dashboard_device(hub, config) -> bool:
    """Determine if Energy Dashboard virtual device should be created.

    Args:
        hub: SolaXModbusHub instance
        config: Integration configuration dict

    Returns:
        bool: True if virtual device should be created
    """
    from .const import (
        CONF_ENERGY_DASHBOARD_DEVICE,
        DEFAULT_ENERGY_DASHBOARD_DEVICE,
    )

    # Simple boolean check - if enabled, create device
    # For parallel mode: Master creates device, Slave skips (user can enable manually if needed)
    energy_dashboard_enabled = config.get(
        CONF_ENERGY_DASHBOARD_DEVICE, DEFAULT_ENERGY_DASHBOARD_DEVICE
    )
    
    # Handle legacy string values for backward compatibility
    if isinstance(energy_dashboard_enabled, str):
        if energy_dashboard_enabled == "disabled":
            return False
        elif energy_dashboard_enabled == "manual":
            return True
        else:  # "enabled" or any other value
            energy_dashboard_enabled = True
    
    if not energy_dashboard_enabled:
        return False
    
    # If enabled, check parallel mode to skip Slaves automatically
    # Note: datadict might not be populated during initial setup
    parallel_setting = None
    if hub.datadict:
        parallel_setting = hub.datadict.get("parallel_setting")
    
    # Skip Slaves automatically (Master has system totals)
    # User can manually enable if they want device on Slave too
    if parallel_setting == "Slave":
        return False
    
    # Master, single inverter, or datadict not populated: Create device
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
