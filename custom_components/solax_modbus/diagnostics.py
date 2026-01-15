"""Diagnostics support for SolaX Modbus integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry, async_get as async_get_device_registry

from .const import (
    CONF_ENERGY_DASHBOARD_DEVICE,
    CONF_NAME,
    DEFAULT_ENERGY_DASHBOARD_DEVICE,
    DOMAIN,
)
from .debug import get_debug_setting, load_debug_settings
from .energy_dashboard import create_energy_dashboard_device_info, _find_slave_hubs

_LOGGER = logging.getLogger(__name__)


def _get_hub_name(entry: ConfigEntry) -> str:
    if entry.data and CONF_NAME in entry.data:
        return entry.data[CONF_NAME]
    if entry.options and CONF_NAME in entry.options:
        return entry.options[CONF_NAME]
    return entry.title


def _get_hub(hass: HomeAssistant, hub_name: str):
    return hass.data.get(DOMAIN, {}).get(hub_name, {}).get("hub")


def _get_hub_data(hub) -> dict[str, Any]:
    return getattr(hub, "data", None) or getattr(hub, "datadict", {}) or {}


def _format_mode(parallel_setting: str | None, debug_standalone: bool) -> str:
    if debug_standalone:
        return "Standalone (debug override)"
    if parallel_setting == "Master":
        return "Parallel - Primary"
    if parallel_setting == "Slave":
        return "Parallel - Secondary"
    if parallel_setting == "Free":
        return "Standalone"
    return "Unknown"


def _get_energy_dashboard_mapping_info(hub) -> dict[str, Any]:
    """Return mapping metadata for diagnostics, if available."""
    plugin = getattr(hub, "plugin", None)
    if not plugin:
        return {"available": False}

    plugin_obj = getattr(plugin, "plugin_instance", plugin)
    mapping = getattr(plugin_obj, "ENERGY_DASHBOARD_MAPPING", None)
    if not mapping:
        return {"available": False}

    aggregation_keys = [
        (m.target_key or m.source_key)
        for m in mapping.mappings
        if getattr(m, "needs_aggregation", False)
    ]

    return {
        "available": True,
        "plugin": mapping.plugin_name,
        "enabled": mapping.enabled,
        "parallel_mode_supported": mapping.parallel_mode_supported,
        "sensor_count": len(mapping.mappings),
        "aggregation_mapping_count": len(aggregation_keys),
        "aggregation_mappings": aggregation_keys,
    }


def _get_energy_dashboard_diagnostics(hass: HomeAssistant, entry: ConfigEntry, hub) -> dict[str, Any]:
    hub_name = _get_hub_name(entry)
    hub_data = _get_hub_data(hub)
    parallel_setting = hub_data.get("parallel_setting")

    debug_standalone = get_debug_setting(
        hub_name,
        "treat_as_standalone_energy_dashboard",
        entry.options,
        hass,
    )

    slave_hubs = _find_slave_hubs(hass, hub) if hass else []
    secondary_names = [name for name, _hub in slave_hubs]

    pm_inverter_count = hub_data.get("pm_inverter_count")
    # Only report detected count when we can see Secondary hubs.
    detected_inverter_count = len(secondary_names) + 1 if secondary_names else None

    energy_dashboard_enabled = entry.options.get(
        CONF_ENERGY_DASHBOARD_DEVICE, DEFAULT_ENERGY_DASHBOARD_DEVICE
    )
    if isinstance(energy_dashboard_enabled, str):
        energy_dashboard_enabled = energy_dashboard_enabled != "disabled"

    device_registry = async_get_device_registry(hass)
    ed_device_info = create_energy_dashboard_device_info(hub, hass)
    ed_device = device_registry.async_get_device(
        identifiers=ed_device_info.identifiers
    )

    debug_settings = load_debug_settings(entry.options, hass)
    hub_debug_settings = debug_settings.get(hub_name, {})

    return {
        "enabled": bool(energy_dashboard_enabled),
        "device_present": ed_device is not None,
        "mode": _format_mode(parallel_setting, debug_standalone),
        "parallel_setting": parallel_setting,
        "pm_inverter_count": pm_inverter_count,
        "detected_inverter_count": detected_inverter_count,
        "secondary_inverter_names": secondary_names,
        "debug_override": debug_standalone,
        "debug_settings_for_inverter": hub_debug_settings,
        "mapping": _get_energy_dashboard_mapping_info(hub),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    hub_name = _get_hub_name(entry)
    hub = _get_hub(hass, hub_name)

    if not hub:
        _LOGGER.warning("Diagnostics: hub not found for %s", hub_name)
        return {"error": f"Hub not found for {hub_name}"}

    return {
        "hub_name": hub_name,
        "energy_dashboard": _get_energy_dashboard_diagnostics(hass, entry, hub),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a device."""
    hub_name = _get_hub_name(entry)
    hub = _get_hub(hass, hub_name)
    if not hub:
        _LOGGER.warning("Diagnostics: hub not found for %s", hub_name)
        return {"error": f"Hub not found for {hub_name}"}

    ed_device_info = create_energy_dashboard_device_info(hub, hass)
    if device.identifiers.isdisjoint(ed_device_info.identifiers):
        return {}

    return {
        "hub_name": hub_name,
        "energy_dashboard": _get_energy_dashboard_diagnostics(hass, entry, hub),
    }
