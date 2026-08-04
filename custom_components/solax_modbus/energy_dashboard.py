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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_ENERGY_DASHBOARD_DEVICE,
    CONF_PLUGIN,
    DEFAULT_ENERGY_DASHBOARD_DEVICE,
    DOMAIN,
    INVERTER_IDENT,
    WRITE_DATA_LOCAL,
    BaseModbusSensorEntityDescription,
    BaseModbusSwitchEntityDescription,
)
from .debug import get_debug_setting

_LOGGER = logging.getLogger(__name__)

# Central Riemann sum configuration (applies to all Riemann sensors)
RIEMANN_METHOD = "trapezoidal"  # Integration method: "trapezoidal", "left", "right"
RIEMANN_ROUND_DIGITS = 3  # Precision for integration result
ENERGY_DASHBOARD_COORDINATOR = "_energy_dashboard_coordinator"

EnergyDashboardRefreshCallback = Callable[[], Awaitable[None]]


@dataclass
class EnergyDashboardHubState:
    """Runtime state for one config entry."""

    entry_id: str
    hub: Any
    role: str | None
    inverter_count: int | None
    refresh_callback: EnergyDashboardRefreshCallback | None = None
    last_total_inverter_count: int | None = None
    dashboard_entity_keys: set[str] = field(default_factory=set)


class EnergyDashboardCoordinator:
    """Coordinate dashboard topology and refreshes across config entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._hubs: dict[str, EnergyDashboardHubState] = {}
        self._pending_refreshes: set[str] = set()
        self._refresh_task: Any = None

    @staticmethod
    def _hub_role(hub: Any) -> str | None:
        hub_data = getattr(hub, "data", None) or getattr(hub, "datadict", {}) or {}
        role = hub_data.get("parallel_setting")
        return role if role in ("Master", "Slave", "Free") else None

    @staticmethod
    def _hub_inverter_count(hub: Any) -> int | None:
        hub_data = getattr(hub, "data", None) or getattr(hub, "datadict", {}) or {}
        count = hub_data.get("pm_inverter_count")
        try:
            return int(count) if count is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _hub_family(hub: Any) -> str | None:
        config = getattr(hub, "config", {}) or {}
        family = config.get(CONF_PLUGIN)
        if family:
            return str(family)
        plugin_module = getattr(hub, "plugin_module", None)
        return getattr(plugin_module, "__name__", None)

    def _entry_id_for_hub(self, hub: Any) -> str | None:
        entry = getattr(hub, "entry", None)
        entry_id = getattr(entry, "entry_id", None)
        if entry_id:
            return str(entry_id)
        for candidate_entry_id, state in self._hubs.items():
            if state.hub is hub:
                return candidate_entry_id
        return None

    def _entry_id_from_event(self, data: dict[str, Any]) -> str | None:
        entry_id = data.get("entry_id")
        if entry_id in self._hubs:
            return str(entry_id)
        hub_name = data.get("hub_name")
        for candidate_entry_id, state in self._hubs.items():
            if getattr(state.hub, "_name", None) == hub_name:
                return candidate_entry_id
        return None

    def _master_entry_ids(self) -> set[str]:
        return {entry_id for entry_id, state in self._hubs.items() if state.role == "Master"}

    def register_hub(self, entry_id: str, hub: Any) -> None:
        """Register or replace a hub using its stable config entry ID."""
        old_masters = self._master_entry_ids()
        previous = self._hubs.get(entry_id)
        if previous is not None and previous.hub is hub:
            self.hub_data_updated(entry_id)
            return
        self._hubs[entry_id] = EnergyDashboardHubState(
            entry_id=entry_id,
            hub=hub,
            role=self._hub_role(hub),
            inverter_count=self._hub_inverter_count(hub),
            dashboard_entity_keys=set(previous.dashboard_entity_keys) if previous else set(),
        )
        affected = old_masters | self._master_entry_ids()
        if previous is not None:
            affected.add(entry_id)
        self.request_refresh_many(affected)

    def unregister_hub(self, entry_id: str) -> None:
        """Remove a hub and refresh masters affected by the topology change."""
        old_masters = self._master_entry_ids()
        removed = self._hubs.pop(entry_id, None)
        self._pending_refreshes.discard(entry_id)
        if removed is None:
            return
        self.request_refresh_many(old_masters | self._master_entry_ids())

    def register_refresh_callback(
        self,
        entry_id: str,
        refresh_callback: EnergyDashboardRefreshCallback,
    ) -> Callable[[], None]:
        """Register a platform refresh callback and return its cleanup callback."""
        state = self._hubs.get(entry_id)
        if state is None:
            raise KeyError(f"Energy Dashboard hub {entry_id} is not registered")
        state.refresh_callback = refresh_callback
        # Platform setup performs one synchronous reconciliation before registering
        # the callback, so it already includes all topology changes seen so far.
        self._pending_refreshes.discard(entry_id)
        self._schedule_refreshes()

        @callback
        def _remove_callback() -> None:
            current = self._hubs.get(entry_id)
            if current is not None and current.refresh_callback is refresh_callback:
                current.refresh_callback = None

        return _remove_callback

    def hub_data_updated(self, entry_id: str) -> None:
        """Reconcile topology after a hub published a complete poll snapshot."""
        state = self._hubs.get(entry_id)
        if state is None:
            return
        old_role = state.role
        old_count = state.inverter_count
        old_masters = self._master_entry_ids()
        state.role = self._hub_role(state.hub)
        state.inverter_count = self._hub_inverter_count(state.hub)
        new_masters = self._master_entry_ids()

        affected: set[str] = set()
        if old_role != state.role:
            affected.update(old_masters | new_masters)
            affected.add(entry_id)
        elif state.role == "Master" and old_count != state.inverter_count:
            affected.add(entry_id)
        self.request_refresh_many(affected)

    def request_refresh_for_event(self, data: dict[str, Any]) -> None:
        """Request a refresh for an integration-local event."""
        if entry_id := self._entry_id_from_event(data):
            self.request_refresh(entry_id)

    def hub_for_event(self, data: dict[str, Any]) -> Any | None:
        """Return the registered hub addressed by an integration-local event."""
        entry_id = self._entry_id_from_event(data)
        state = self._hubs.get(entry_id) if entry_id else None
        return state.hub if state else None

    def request_refresh_many(self, entry_ids: set[str]) -> None:
        for entry_id in entry_ids:
            self.request_refresh(entry_id, schedule=False)
        self._schedule_refreshes()

    def request_refresh(self, entry_id: str, *, schedule: bool = True) -> None:
        if entry_id not in self._hubs:
            return
        self._pending_refreshes.add(entry_id)
        if schedule:
            self._schedule_refreshes()

    def _schedule_refreshes(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        if not any(self._hubs[entry_id].refresh_callback for entry_id in self._pending_refreshes if entry_id in self._hubs):
            return
        self._refresh_task = self.hass.async_create_task(self._async_refresh_pending())

    async def _async_refresh_pending(self) -> None:
        try:
            while True:
                ready = [
                    entry_id for entry_id in self._pending_refreshes if entry_id in self._hubs and self._hubs[entry_id].refresh_callback is not None
                ]
                if not ready:
                    return
                for entry_id in ready:
                    self._pending_refreshes.discard(entry_id)
                    state = self._hubs.get(entry_id)
                    refresh_callback = state.refresh_callback if state else None
                    if refresh_callback is None:
                        continue
                    try:
                        await refresh_callback()
                    except Exception:
                        _LOGGER.exception(
                            "%s: Energy Dashboard refresh failed",
                            getattr(getattr(state, "hub", None), "_name", entry_id),
                        )
        finally:
            self._refresh_task = None
            if any(self._hubs[entry_id].refresh_callback for entry_id in self._pending_refreshes if entry_id in self._hubs):
                self._schedule_refreshes()

    def slave_hubs_for(self, master_hub: Any) -> list[tuple[str, Any]]:
        """Return registered slave hubs compatible with the master plugin."""
        master_entry_id = self._entry_id_for_hub(master_hub)
        master_family = self._hub_family(master_hub)
        slaves = []
        for entry_id, state in self._hubs.items():
            if entry_id == master_entry_id or state.role != "Slave":
                continue
            if self._hub_family(state.hub) != master_family:
                continue
            slaves.append((getattr(state.hub, "_name", entry_id), state.hub))
        return sorted(slaves, key=lambda item: item[0].casefold())

    def set_last_total_inverter_count(self, hub: Any, count: int | None) -> None:
        if entry_id := self._entry_id_for_hub(hub):
            if state := self._hubs.get(entry_id):
                state.last_total_inverter_count = count

    def last_total_inverter_count(self, hub: Any) -> int | None:
        if entry_id := self._entry_id_for_hub(hub):
            if state := self._hubs.get(entry_id):
                return state.last_total_inverter_count
        return None

    def dashboard_entity_keys(self, hub: Any) -> set[str]:
        if entry_id := self._entry_id_for_hub(hub):
            if state := self._hubs.get(entry_id):
                return state.dashboard_entity_keys
        return set()


def get_energy_dashboard_coordinator(hass: HomeAssistant) -> EnergyDashboardCoordinator:
    """Return the integration-wide Energy Dashboard coordinator."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    coordinator = domain_data.get(ENERGY_DASHBOARD_COORDINATOR)
    if not isinstance(coordinator, EnergyDashboardCoordinator):
        coordinator = EnergyDashboardCoordinator(hass)
        domain_data[ENERGY_DASHBOARD_COORDINATOR] = coordinator
    return coordinator


@dataclass
class EnergyDashboardSensorMapping:
    """Mapping definition for a single Energy Dashboard sensor."""

    source_key: str  # Original sensor key (e.g., "measured_power") or pattern with {n}
    target_key: str  # Energy Dashboard sensor key (e.g., "grid_power") or pattern with {n}
    name: str  # Display name (e.g., "Grid Power") or pattern with {n}
    source_key_pm: str | None = None  # Parallel mode source (e.g., "pm_total_measured_power")
    invert: bool = False  # Whether to invert the value
    icon: str | None = None  # Optional icon override
    unit: str | None = None  # Optional unit override
    invert_function: Callable[[float, dict[str, Any]], float] | None = None  # Custom invert function if needed
    filter_function: Callable[[float], float] | None = None  # Universal filter function (applies to all sensor types)
    use_riemann_sum: bool = False  # Enable Riemann sum calculation for energy sensors
    skip_pm_individuals: bool = False  # Skip creating individual sensors (Master "SolaX 1" and Slave "SolaX 2/3")
    needs_aggregation: bool = False  # Only applies to Master "All" sensors in parallel mode
    allowedtypes: int = 0  # Bitmask for inverter types (same pattern as sensor definitions, 0 = all types)
    max_variants: int = 6  # Maximum variants when using {n} pattern mappings

    def get_source_key(self, datadict: dict[str, float]) -> str:
        """Determine which source key to use based on parallel mode."""
        parallel_setting = datadict.get("parallel_setting", "Free")

        if parallel_setting == "Master" and self.source_key_pm:
            # Prefer PM totals on Primary when available.
            # Validate PM sensor exists before using it
            if self.source_key_pm not in datadict:
                _LOGGER.warning(f"Parallel Master detected but PM sensor {self.source_key_pm} not found, falling back to {self.source_key}")
                return self.source_key
            return self.source_key_pm  # Use PM sensor on Master

        return self.source_key  # Use regular sensor (single mode or Slave)

    def get_value(self, datadict: dict[str, float]) -> float | None:
        """Get value from source sensor, applying filter, invert, and custom functions."""
        source_key = self.get_source_key(datadict)  # Handles parallel mode

        # Grab the value for the source. If it is unavailable, return None value to propagate unavailable state.
        # This avoids resetting total increasing sensors and unintentionally breaking energy statistics.
        value = datadict.get(source_key, None)
        if value is None:
            _LOGGER.debug(f"Source sensor {source_key} not found or has no value, marking unavailable")
            return None

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


def create_energy_dashboard_device_info(hub: Any, hass: Any = None) -> DeviceInfo:
    """Create DeviceInfo for Energy Dashboard virtual device."""
    # Normalize hub name to lowercase with underscores for consistent identifier
    normalized_hub_name = hub._name.lower().replace(" ", "_")

    # Use documentation URL for configuration_url
    config_url = "https://homeassistant-solax-modbus.readthedocs.io/en/latest/"

    return DeviceInfo(
        identifiers={(DOMAIN, f"{normalized_hub_name}_energy_dashboard", "ENERGY_DASHBOARD")},  # type: ignore[arg-type]  # Runtime requires 3-element tuple
        manufacturer="providing curated Grid, Solar, Battery power & energy sensors with parallel mode aggregation support for Home Assistant Energy Dashboard integration",
        model="Energy Dashboard Metrics",
        name=f"{hub._name} Energy Dashboard",
        via_device=(DOMAIN, hub._name, INVERTER_IDENT),  # type: ignore[typeddict-item]  # Runtime requires 3-element tuple
        configuration_url=config_url,
    )


ED_SWITCH_PV_VARIANTS = "energy_dashboard_pv_variants_enabled"
ED_SWITCH_HOME_CONSUMPTION = "energy_dashboard_home_consumption_enabled"
ED_SWITCH_GRID_TO_BATTERY = "energy_dashboard_grid_to_battery_enabled"


def get_energy_dashboard_switch_state(hub: Any, key: str) -> bool | None:
    """Return True/False when available, otherwise None."""
    if hub is None:
        return None
    raw_value = getattr(hub, "data", {}).get(key)
    if raw_value is None:
        return None
    try:
        return bool(int(raw_value))
    except (TypeError, ValueError):
        return None


def register_energy_dashboard_switch_provider(hass: Any) -> None:
    """Register ED switch provider in hass data."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    get_energy_dashboard_coordinator(hass)
    providers = domain_data.setdefault("_switch_entity_providers", [])
    for provider in providers:
        if getattr(provider, "__name__", "") == "_energy_dashboard_switch_provider":
            return
    providers.append(_energy_dashboard_switch_provider)
    _register_energy_dashboard_switch_listener(hass)
    _register_energy_dashboard_local_data_listener(hass)


def _register_energy_dashboard_switch_listener(hass: Any) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_ed_switch_listener_registered"):
        return

    @callback
    def _handle_local_switch_event(event: Any) -> Any:
        data = event.data or {}
        key = data.get("key")
        if key not in (
            ED_SWITCH_PV_VARIANTS,
            ED_SWITCH_HOME_CONSUMPTION,
            ED_SWITCH_GRID_TO_BATTERY,
        ):
            return
        get_energy_dashboard_coordinator(hass).request_refresh_for_event(data)

    hass.bus.async_listen("solax_modbus_local_switch_changed", _handle_local_switch_event)
    domain_data["_ed_switch_listener_registered"] = True


def _register_energy_dashboard_local_data_listener(hass: Any) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_ed_local_data_listener_registered"):
        return

    @callback
    def _handle_local_data_loaded(event: Any) -> Any:
        data = event.data or {}
        coordinator = get_energy_dashboard_coordinator(hass)
        hub = coordinator.hub_for_event(data)
        if hub is None:
            return
        if (
            get_energy_dashboard_switch_state(hub, ED_SWITCH_PV_VARIANTS) is not True
            and get_energy_dashboard_switch_state(hub, ED_SWITCH_HOME_CONSUMPTION) is not True
            and get_energy_dashboard_switch_state(hub, ED_SWITCH_GRID_TO_BATTERY) is not True
        ):
            return
        coordinator.request_refresh_for_event(data)

    hass.bus.async_listen("solax_modbus_local_data_loaded", _handle_local_data_loaded)
    domain_data["_ed_local_data_listener_registered"] = True


def _energy_dashboard_switch_provider(hub: Any, hass: Any, entry: Any) -> tuple[Any, Any, list[Any]]:
    """Return device info, platform name, and switch descriptions for ED switches."""
    config = entry.options if entry else {}
    energy_dashboard_enabled = config.get(CONF_ENERGY_DASHBOARD_DEVICE, DEFAULT_ENERGY_DASHBOARD_DEVICE)
    if isinstance(energy_dashboard_enabled, str):
        energy_dashboard_enabled = energy_dashboard_enabled != "disabled"
    if not energy_dashboard_enabled:
        return None, None, []

    energy_dashboard_device_info = create_energy_dashboard_device_info(hub, hass)
    energy_dashboard_platform_name = f"{hub._name} Energy Dashboard"

    def _local_switch_value_function(_bit: Any, is_on: Any, _sensor_key: Any, _datadict: Any) -> Any:
        return 1 if is_on else 0

    config_category = getattr(EntityCategory, "CONFIGURATION", None)
    if config_category is None:
        config_category = getattr(EntityCategory, "CONFIG", None)

    return (
        energy_dashboard_device_info,
        energy_dashboard_platform_name,
        [
            BaseModbusSwitchEntityDescription(
                key=ED_SWITCH_PV_VARIANTS,
                name="Enable PV Variant Detail Sensors",
                register=0,
                write_method=WRITE_DATA_LOCAL,
                initvalue=0,
                sensor_key=ED_SWITCH_PV_VARIANTS,
                value_function=_local_switch_value_function,
                icon="mdi:solar-power-variant",
                entity_category=config_category,
            ),
            BaseModbusSwitchEntityDescription(
                key=ED_SWITCH_HOME_CONSUMPTION,
                name="Enable Home Consumption Sensor",
                register=0,
                write_method=WRITE_DATA_LOCAL,
                initvalue=0,
                sensor_key=ED_SWITCH_HOME_CONSUMPTION,
                value_function=_local_switch_value_function,
                icon="mdi:home-lightning-bolt",
                entity_category=config_category,
            ),
            BaseModbusSwitchEntityDescription(
                key=ED_SWITCH_GRID_TO_BATTERY,
                name="Enable Grid to Battery Sensors",
                register=0,
                write_method=WRITE_DATA_LOCAL,
                initvalue=0,
                sensor_key=ED_SWITCH_GRID_TO_BATTERY,
                value_function=_local_switch_value_function,
                icon="mdi:transmission-tower-export",
                entity_category=config_category,
            ),
        ],
    )


def _create_energy_dashboard_diagnostic_sensors(
    hub: Any,
    hass: HomeAssistant,
    config: dict[str, Any],
    energy_dashboard_device_info: DeviceInfo,
    mapping: EnergyDashboardMapping | None = None,
) -> list[Any]:
    """Create diagnostic sensors for the Energy Dashboard device."""
    hub_name = getattr(hub, "_name", "Unknown")
    config = config or {}
    hub_data = getattr(hub, "data", None) or getattr(hub, "datadict", {}) or {}
    parallel_setting = hub_data.get("parallel_setting")
    debug_standalone = get_debug_setting(
        hub_name,
        "treat_as_standalone_energy_dashboard",
        config,
        hass,
        default=False,
    )
    pm_inverter_count = hub_data.get("pm_inverter_count")
    secondary_names = []
    if hass and not debug_standalone:
        secondary_names = [name for name, _hub in _find_slave_hubs(hass, hub)]
    has_parallel_context = not debug_standalone and (parallel_setting == "Master" or pm_inverter_count is not None or bool(secondary_names))

    def _mode_value(_initval: Any, _descr: Any, _datadict: Any) -> Any:
        if debug_standalone:
            return "Standalone (debug override)"
        if parallel_setting == "Master":
            return "Parallel - Primary"
        if parallel_setting == "Slave":
            return "Parallel - Secondary"
        if parallel_setting == "Free":
            return "Standalone"
        return "Unknown"

    def _inverter_count_value(_initval: Any, _descr: Any, _datadict: Any) -> Any:
        if debug_standalone:
            return 1

        if pm_inverter_count is not None:
            return pm_inverter_count

        if secondary_names:
            return len(secondary_names) + 1

        if parallel_setting in ("Master", "Slave", "Free"):
            return 1
        return None

    def _secondary_names_value(_initval: Any, _descr: Any, _datadict: Any) -> Any:
        if not secondary_names:
            return None
        return ", ".join(secondary_names) if secondary_names else None

    def _debug_override_value(_initval: Any, _descr: Any, _datadict: Any) -> Any:
        return "enabled" if debug_standalone else "disabled"

    def _parallel_setting_value(_initval: Any, _descr: Any, _datadict: Any) -> Any:
        return parallel_setting or "Unknown"

    def _pm_inverter_count_value(_initval: Any, _descr: Any, _datadict: Any) -> Any:
        return pm_inverter_count if pm_inverter_count is not None else None

    def _mapping_summary_value(_initval: Any, _descr: Any, _datadict: Any) -> Any:
        if not mapping:
            return None
        summary = f"{mapping.plugin_name}: {len(mapping.mappings)} mappings"
        if not mapping.enabled:
            summary += " (disabled)"
        return summary

    def _last_total_inverter_count_value(_initval: Any, _descr: Any, _datadict: Any) -> Any:
        if not hass:
            return None
        return get_energy_dashboard_coordinator(hass).last_total_inverter_count(hub)

    diagnostics = [
        BaseModbusSensorEntityDescription(
            key="energy_dashboard_mode",
            name="Mode",
            register=-1,
            value_function=_mode_value,
            allowedtypes=hub._invertertype,
            icon="mdi:swap-horizontal",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
        ),
        BaseModbusSensorEntityDescription(
            key="energy_dashboard_inverter_count",
            name="Inverter Count",
            register=-1,
            value_function=_inverter_count_value,
            allowedtypes=hub._invertertype,
            icon="mdi:counter",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
        ),
    ]

    diagnostics.append(
        BaseModbusSensorEntityDescription(
            key="energy_dashboard_last_total_inverter_count",
            name="Last Total Inverter Count",
            register=-1,
            value_function=_last_total_inverter_count_value,
            allowedtypes=hub._invertertype,
            icon="mdi:counter",
            entity_category=EntityCategory.DIAGNOSTIC,
        )
    )

    if debug_standalone:
        diagnostics.append(
            BaseModbusSensorEntityDescription(
                key="energy_dashboard_debug_override",
                name="Debug Override",
                register=-1,
                value_function=_debug_override_value,
                allowedtypes=hub._invertertype,
                icon="mdi:bug-check",
                entity_category=EntityCategory.DIAGNOSTIC,
            )
        )
    else:
        diagnostics.append(
            BaseModbusSensorEntityDescription(
                key="energy_dashboard_parallel_setting",
                name="Parallel Setting",
                register=-1,
                value_function=_parallel_setting_value,
                allowedtypes=hub._invertertype,
                icon="mdi:shuffle-variant",
                entity_category=EntityCategory.DIAGNOSTIC,
                entity_registry_enabled_default=False,
            )
        )

    if has_parallel_context:
        diagnostics.append(
            BaseModbusSensorEntityDescription(
                key="energy_dashboard_secondary_inverters",
                name="Secondary Inverters",
                register=-1,
                value_function=_secondary_names_value,
                allowedtypes=hub._invertertype,
                icon="mdi:solar-power-variant",
                entity_category=EntityCategory.DIAGNOSTIC,
            )
        )

        if pm_inverter_count is not None:
            diagnostics.append(
                BaseModbusSensorEntityDescription(
                    key="energy_dashboard_pm_inverter_count",
                    name="PM Inverter Count",
                    register=-1,
                    value_function=_pm_inverter_count_value,
                    allowedtypes=hub._invertertype,
                    icon="mdi:counter",
                    entity_category=EntityCategory.DIAGNOSTIC,
                )
            )

    if mapping:
        diagnostics.append(
            BaseModbusSensorEntityDescription(
                key="energy_dashboard_mapping_summary",
                name="Mapping Summary",
                register=-1,
                value_function=_mapping_summary_value,
                allowedtypes=hub._invertertype,
                icon="mdi:clipboard-text",
                entity_category=EntityCategory.DIAGNOSTIC,
            )
        )

    diagnostics = [replace(description, _energy_dashboard_device_info=energy_dashboard_device_info) for description in diagnostics]

    return diagnostics


def _create_sensor_from_mapping(
    sensor_mapping: EnergyDashboardSensorMapping,
    hub: Any,
    energy_dashboard_device_info: DeviceInfo,
    source_hub: Any = None,
    name_prefix: str = "",
) -> list[Any]:
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
    def make_value_function(sensor_mapping: EnergyDashboardSensorMapping) -> Any:
        captured_hub = data_hub  # Capture in closure

        def value_function(initval: Any, descr: Any, datadict: dict[str, Any]) -> Any:
            # Use captured_hub's data dictionary instead of the passed datadict
            # This allows reading from Slave hubs
            hub_data = getattr(captured_hub, "data", None) or getattr(captured_hub, "datadict", datadict)
            try:
                return sensor_mapping.get_value(hub_data)
            except Exception as e:
                hub_name = getattr(captured_hub, "_name", "Unknown")
                _LOGGER.error(f"Error getting value for {sensor_mapping.target_key} from hub {hub_name}: {e}")
                return None

        return value_function

    # Try to inherit attributes from source sensor if not specified in mapping
    source_sensor_desc = None
    source_key = sensor_mapping.get_source_key(getattr(data_hub, "data", None) or getattr(data_hub, "datadict", {}))

    # Prefer source descriptors; entity objects are only available for enabled entities.
    sensor_descriptions = getattr(data_hub, "sensorDescriptions", {}) or {}
    if source_key in sensor_descriptions:
        source_sensor_desc = sensor_descriptions[source_key]
    elif hasattr(data_hub, "sensorEntities") and source_key in data_hub.sensorEntities:
        source_sensor = data_hub.sensorEntities[source_key]
        if hasattr(source_sensor, "entity_description"):
            source_sensor_desc = source_sensor.entity_description

    # Detect sensor type: power vs energy
    # Energy sensors: use Riemann sum OR target_key contains "energy" but not "power"
    # Power sensors: target_key contains "power" (even if it also contains "energy")
    target_key_lower = sensor_mapping.target_key.lower()
    is_energy_sensor = sensor_mapping.use_riemann_sum or ("energy" in target_key_lower and "power" not in target_key_lower)
    is_soc_sensor = (source_sensor_desc.device_class == SensorDeviceClass.BATTERY) if source_sensor_desc else ("soc" in target_key_lower)

    # Set attributes - inherit from source if available, otherwise use defaults
    if is_energy_sensor:
        # Energy sensor attributes - use hardcoded classes but inherit icon
        device_class = SensorDeviceClass.ENERGY
        state_class = SensorStateClass.TOTAL_INCREASING
        unit = sensor_mapping.unit or UnitOfEnergy.KILO_WATT_HOUR
        default_icon = source_sensor_desc.icon if source_sensor_desc and source_sensor_desc.icon else "mdi:lightning-bolt"
    elif is_soc_sensor:
        # State of Charge attributes - use hardcoded classes, skipping icon so that HA loads dynamic battery symbol
        device_class = SensorDeviceClass.BATTERY
        state_class = SensorStateClass.MEASUREMENT
        unit = PERCENTAGE
        default_icon = None
    else:
        # Power sensor attributes - inherit from source sensor
        device_class = source_sensor_desc.device_class if source_sensor_desc else SensorDeviceClass.POWER
        state_class = source_sensor_desc.state_class if source_sensor_desc else SensorStateClass.MEASUREMENT
        unit = sensor_mapping.unit or (source_sensor_desc.native_unit_of_measurement if source_sensor_desc else UnitOfPower.WATT)
        default_icon = source_sensor_desc.icon if source_sensor_desc and source_sensor_desc.icon else "mdi:flash"

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
        icon=(sensor_mapping.icon or default_icon) if default_icon else None,
        register=-1,  # No modbus register (computed sensor)
        # Custom device_info will be set during sensor creation
    )

    # Store mapping info for sensor creation
    sensor_desc = replace(
        sensor_desc,
        _energy_dashboard_device_info=energy_dashboard_device_info,
        _energy_dashboard_mapping=sensor_mapping,
        _energy_dashboard_source_hub=data_hub,
    )

    # Mark Riemann sum sensors for special handling
    if sensor_mapping.use_riemann_sum:
        sensor_desc = replace(
            sensor_desc,
            _is_riemann_sum_sensor=True,
            _riemann_mapping=sensor_mapping,
            _riemann_data_hub=data_hub,
        )
    else:
        sensor_desc = replace(sensor_desc, _is_riemann_sum_sensor=False)

    sensors.append(sensor_desc)

    return sensors


def _find_slave_hubs(hass: Any, master_hub: Any) -> Any:
    """Return registered Slave hubs from the stable entry topology."""
    if not hass:
        return []
    return get_energy_dashboard_coordinator(hass).slave_hubs_for(master_hub)


def _needs_aggregation(target_key: str) -> Any:
    """Check if a sensor needs aggregation (sum of Master + Slaves).

    Energy sensors that need aggregation:
    - battery_energy_charge_energy_dashboard
    - battery_energy_discharge_energy_dashboard
    - solar_energy_production_energy_dashboard

    Grid energy doesn't need aggregation (Master already aggregates all).
    """
    target_key_lower = target_key.lower()
    return (
        "battery_energy_charge" in target_key_lower or "battery_energy_discharge" in target_key_lower or "solar_energy_production" in target_key_lower
    )


def _create_aggregated_value_function(sensor_mapping: EnergyDashboardSensorMapping, master_hub: Any, slave_hubs: list[Any]) -> Any:
    """Create a value function that sums Master + all Slaves for aggregation.

    Handles edge cases:
    - No Slaves: Returns Master value only
    - Slave hub offline: Treats missing values as 0, logs debug message
    - Missing keys: Treats as 0, continues with other Slaves
    """
    master_name = getattr(master_hub, "_name", "Unknown")

    def value_function(initval: Any, descr: Any, datadict: dict[str, Any]) -> Any:
        # Get Master value (individual inverter value)
        master_data = getattr(master_hub, "data", None) or getattr(master_hub, "datadict", datadict)
        try:
            master_value = sensor_mapping.get_value(master_data)
            total = master_value if master_value is not None else 0
        except Exception as e:
            _LOGGER.debug(f"{master_name}: Error getting Master value for aggregation: {e}")
            total = 0

        # Sum all Slave values
        for slave_name, slave_hub in slave_hubs:
            try:
                slave_data = getattr(slave_hub, "data", None) or getattr(slave_hub, "datadict", {})
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


async def create_energy_dashboard_sensors(hub: Any, mapping: EnergyDashboardMapping, hass: Any = None, config: Any = None) -> list[Any]:
    """Generate Energy Dashboard sensor entities from mapping.

    Args:
        hub: SolaXModbusHub instance
        mapping: EnergyDashboardMapping configuration
        hass: Home Assistant instance (optional, needed for Slave hub access)
        config: Integration configuration dict (optional, for whitelist check)
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
    # return []

    if not mapping.enabled:
        _LOGGER.debug("Energy Dashboard mapping is disabled")
        return []

    sensors = []
    energy_dashboard_device_info = create_energy_dashboard_device_info(hub, hass)

    # Determine if this is a Master hub
    hub_name = getattr(hub, "_name", "Unknown")
    hub_data = getattr(hub, "data", None) or getattr(hub, "datadict", {})
    parallel_setting = hub_data.get("parallel_setting", "Free")
    is_master = parallel_setting == "Master"
    debug_standalone = get_debug_setting(
        hub_name,
        "treat_as_standalone_energy_dashboard",
        config,
        hass,
        default=False,
    )
    ed_is_master = is_master and not debug_standalone
    _LOGGER.info(f"{hub_name}: Energy Dashboard sensor creation - parallel_setting={parallel_setting}, is_master={is_master}")

    # Find Slave hubs if this is a Master
    slave_hubs = []
    if ed_is_master and hass:
        slave_hubs = _find_slave_hubs(hass, hub)
        if slave_hubs:
            _LOGGER.info(f"Found {len(slave_hubs)} registered Slave hub(s) for Energy Dashboard")
        else:
            _LOGGER.debug("No Slave hubs found for Energy Dashboard (Master mode but no Slaves)")
    elif ed_is_master and not hass:
        _LOGGER.warning("Master hub detected but hass not provided - cannot find Slave hubs for aggregation")

    total_inverter_count = None
    pm_inverter_count = hub_data.get("pm_inverter_count")
    if pm_inverter_count is not None:
        total_inverter_count = pm_inverter_count
    elif slave_hubs:
        total_inverter_count = len(slave_hubs) + 1
    elif parallel_setting in ("Master", "Slave", "Free"):
        total_inverter_count = 1

    if hass:
        get_energy_dashboard_coordinator(hass).set_last_total_inverter_count(hub, total_inverter_count)

    # Get inverter name for prefix (e.g., "Solax 1")
    inverter_name = hub_name

    pv_variants_enabled = get_energy_dashboard_switch_state(hub, ED_SWITCH_PV_VARIANTS) is True
    home_consumption_enabled = get_energy_dashboard_switch_state(hub, ED_SWITCH_HOME_CONSUMPTION) is True
    grid_to_battery_enabled = get_energy_dashboard_switch_state(hub, ED_SWITCH_GRID_TO_BATTERY) is True

    for sensor_mapping in mapping.mappings:
        if "pv_power_" in sensor_mapping.target_key or "pv_energy_" in sensor_mapping.target_key:
            if not pv_variants_enabled:
                continue
        if "home_consumption_" in sensor_mapping.target_key:
            if not home_consumption_enabled:
                continue
        if "grid_to_battery_" in sensor_mapping.target_key:
            if not grid_to_battery_enabled:
                continue
        # Filter by allowedtypes (same pattern as regular sensors)
        # If allowedtypes is 0, apply to all types (backward compatibility)
        if sensor_mapping.allowedtypes != 0:
            if not hub.plugin.matchInverterWithMask(
                hub._invertertype,
                sensor_mapping.allowedtypes,
                hub.seriesnumber,
                None,  # blacklist
            ):
                continue  # Skip this mapping for this inverter type

        # Check if this is a pattern-based mapping (contains {n} placeholder)
        has_pattern = "{n}" in sensor_mapping.source_key or "{n}" in sensor_mapping.target_key or "{n}" in sensor_mapping.name

        if has_pattern:
            base_source_key = sensor_mapping.source_key.replace("{n}", "")

            def _detect_variants(hub_obj: Any, mapping: Any, base_key: str) -> list[int]:
                sensor_keys = getattr(hub_obj, "sensorEntities", {}) or {}
                sensor_descriptions = getattr(hub_obj, "sensorDescriptions", {}) or {}
                hub_data = getattr(hub_obj, "data", None) or getattr(hub_obj, "datadict", {})
                variants = []
                for n in range(1, mapping.max_variants + 1):
                    variant_key = f"{base_key}{n}"
                    if variant_key in sensor_keys or variant_key in sensor_descriptions or variant_key in hub_data:
                        variants.append(n)
                return variants

            master_variants = _detect_variants(hub, sensor_mapping, base_source_key)

            for variant_num in master_variants:
                variant_mapping = EnergyDashboardSensorMapping(
                    source_key=sensor_mapping.source_key.replace("{n}", str(variant_num)),
                    target_key=sensor_mapping.target_key.replace("{n}", str(variant_num)),
                    name=sensor_mapping.name.replace("{n}", str(variant_num)),
                    source_key_pm=sensor_mapping.source_key_pm,
                    invert=sensor_mapping.invert,
                    icon=sensor_mapping.icon,
                    unit=sensor_mapping.unit,
                    invert_function=sensor_mapping.invert_function,
                    filter_function=sensor_mapping.filter_function,
                    use_riemann_sum=sensor_mapping.use_riemann_sum,
                    skip_pm_individuals=sensor_mapping.skip_pm_individuals,
                    needs_aggregation=sensor_mapping.needs_aggregation,
                    allowedtypes=sensor_mapping.allowedtypes,
                    max_variants=sensor_mapping.max_variants,
                )
                sensors.extend(
                    _create_sensor_from_mapping(
                        variant_mapping,
                        hub,
                        energy_dashboard_device_info,
                        source_hub=hub,
                        name_prefix=f"{inverter_name} ",
                    )
                )

            if ed_is_master and not sensor_mapping.skip_pm_individuals:
                for slave_name, slave_hub in slave_hubs:
                    slave_variants = _detect_variants(slave_hub, sensor_mapping, base_source_key)

                    for variant_num in slave_variants:
                        variant_mapping = EnergyDashboardSensorMapping(
                            source_key=sensor_mapping.source_key.replace("{n}", str(variant_num)),
                            target_key=sensor_mapping.target_key.replace("{n}", str(variant_num)),
                            name=sensor_mapping.name.replace("{n}", str(variant_num)),
                            source_key_pm=sensor_mapping.source_key_pm,
                            invert=sensor_mapping.invert,
                            icon=sensor_mapping.icon,
                            unit=sensor_mapping.unit,
                            invert_function=sensor_mapping.invert_function,
                            filter_function=sensor_mapping.filter_function,
                            use_riemann_sum=sensor_mapping.use_riemann_sum,
                            skip_pm_individuals=sensor_mapping.skip_pm_individuals,
                            needs_aggregation=sensor_mapping.needs_aggregation,
                            allowedtypes=sensor_mapping.allowedtypes,
                            max_variants=sensor_mapping.max_variants,
                        )
                        sensors.extend(
                            _create_sensor_from_mapping(
                                variant_mapping,
                                hub,
                                energy_dashboard_device_info,
                                source_hub=slave_hub,
                                name_prefix=f"{slave_name} ",
                            )
                        )
            continue

        # Create sensors based on Master/Standalone
        if ed_is_master:
            # For Master: Create "All" sensor and individual inverter sensors
            # Check if this sensor needs aggregation for "All" version
            needs_agg = sensor_mapping.needs_aggregation or _needs_aggregation(sensor_mapping.target_key)

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
                )
                sensors.extend(_create_sensor_from_mapping(all_mapping, hub, energy_dashboard_device_info, source_hub=hub, name_prefix="All "))
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
                    )
                    sensors.extend(_create_sensor_from_mapping(all_mapping, hub, energy_dashboard_device_info, source_hub=hub, name_prefix="All "))
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
                    )
                    # Create sensor with aggregated value function
                    aggregated_sensor = _create_sensor_from_mapping(
                        all_mapping, hub, energy_dashboard_device_info, source_hub=hub, name_prefix="All "
                    )
                    if aggregated_sensor:
                        # Replace value function with aggregated version
                        aggregated_sensor[0] = replace(
                            aggregated_sensor[0],
                            value_function=_create_aggregated_value_function(all_mapping, hub, slave_hubs),
                        )
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
                )
                sensors.extend(_create_sensor_from_mapping(all_mapping, hub, energy_dashboard_device_info, source_hub=hub, name_prefix="All "))

            # Create "Solax 1" sensor (Master individual)
            # Check if individual sensors should be skipped
            _LOGGER.debug(
                f"Master individual check: target_key={sensor_mapping.target_key}, skip_pm_individuals={sensor_mapping.skip_pm_individuals}"
            )
            if not sensor_mapping.skip_pm_individuals:
                # For Master individual, force use of non-PM sensor by setting source_key_pm=None
                master_individual_mapping = EnergyDashboardSensorMapping(
                    source_key=sensor_mapping.source_key,
                    target_key=sensor_mapping.target_key,
                    name=sensor_mapping.name,
                    source_key_pm=None,  # Force non-PM sensor for Master individual
                    invert=sensor_mapping.invert,
                    icon=sensor_mapping.icon,
                    unit=sensor_mapping.unit,
                    invert_function=sensor_mapping.invert_function,
                    filter_function=sensor_mapping.filter_function,
                    use_riemann_sum=sensor_mapping.use_riemann_sum,
                    allowedtypes=sensor_mapping.allowedtypes,
                )
                sensors.extend(
                    _create_sensor_from_mapping(
                        master_individual_mapping,
                        hub,
                        energy_dashboard_device_info,
                        source_hub=hub,
                        name_prefix=f"{inverter_name} ",
                    )
                )

            # Create "Solax 2/3" sensors from Slave hubs
            # Check if individual sensors should be skipped
            _LOGGER.debug(f"Slave individual check: target_key={sensor_mapping.target_key}, skip_pm_individuals={sensor_mapping.skip_pm_individuals}")
            if not sensor_mapping.skip_pm_individuals:
                for slave_name, slave_hub in slave_hubs:
                    sensors.extend(
                        _create_sensor_from_mapping(
                            sensor_mapping,
                            hub,
                            energy_dashboard_device_info,
                            source_hub=slave_hub,
                            name_prefix=f"{slave_name} ",
                        )
                    )
        else:
            # For Standalone: Create only individual inverter sensor (no "All" prefix)
            # Note: skip_pm_individuals flag only applies to parallel mode (ignored here)
            sensors.extend(
                _create_sensor_from_mapping(sensor_mapping, hub, energy_dashboard_device_info, source_hub=hub, name_prefix=f"{inverter_name} ")
            )

    # Append diagnostics once per virtual device to avoid duplicates.
    sensors.extend(
        _create_energy_dashboard_diagnostic_sensors(
            hub,
            hass,
            config,
            energy_dashboard_device_info,
            mapping=mapping,
        )
    )

    return sensors


async def should_create_energy_dashboard_device(hub: Any, config: Any, hass: Any = None, logger: Any = None, initial_groups: Any = None) -> bool:
    """Return whether this entry should currently expose a dashboard device."""
    energy_dashboard_enabled = config.get(CONF_ENERGY_DASHBOARD_DEVICE, DEFAULT_ENERGY_DASHBOARD_DEVICE)

    if isinstance(energy_dashboard_enabled, str):
        if energy_dashboard_enabled == "disabled":
            return False
        if energy_dashboard_enabled == "manual":
            return True
        energy_dashboard_enabled = True

    if not energy_dashboard_enabled:
        return False

    hub_name = getattr(hub, "name", getattr(hub, "_name", "unknown"))
    debug_standalone = get_debug_setting(
        hub_name,
        "treat_as_standalone_energy_dashboard",
        config,
        hass,
        default=False,
    )
    if debug_standalone:
        return True

    hub_data = getattr(hub, "data", None) or getattr(hub, "datadict", {}) or {}
    parallel_setting = hub_data.get("parallel_setting")
    if parallel_setting == "Slave":
        _LOGGER.warning("Energy Dashboard device will not be created (Slave inverter)")
        return False

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
            _LOGGER.error(f"Invalid mapping: missing source_key or target_key for {mapping.plugin_name}")
            return False

    return True
