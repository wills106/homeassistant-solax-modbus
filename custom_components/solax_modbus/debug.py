"""Debug and Testing Utilities for SolaX Modbus Integration.

**DEVELOPMENT/TESTING/DEBUGGING ONLY**

This module contains debug and testing utilities that are intentionally kept separate
from the core integration code. These features are configured via configuration.yaml
(not exposed in the UI) to keep dev/test/debug specific settings separate from
production user-facing configuration.
"""

import logging

from .const import (
    CONF_DEBUG_SETTINGS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def load_debug_settings(config, hass=None):
    """Load debug settings configuration for inverters.

    **DEVELOPMENT/TESTING/DEBUGGING ONLY**

    This debug settings feature is intended for development, testing, and debugging purposes only.
    It is intentionally configured via configuration.yaml (not exposed in the UI) to keep
    dev/test/debug specific settings separate from production user-facing configuration.

    Debug settings are sourced from configuration.yaml only.

    Args:
        config: Integration configuration dict (unused for debug settings)
        hass: Home Assistant instance (optional, for configuration.yaml access)

    Returns:
        Dict mapping inverter names to their settings (e.g., {"Solax 3": {"treat_as_standalone_energy_dashboard": True}})
        or empty dict if no debug settings configured
    """
    debug_settings = {}

    # Check YAML configuration if hass is available
    # Debug settings from YAML are stored in hass.data[DOMAIN]["_debug_settings"] by async_setup()
    if hass:
        try:
            domain_data = hass.data.get(DOMAIN, {})
            yaml_debug_settings = domain_data.get("_debug_settings", {})
            if yaml_debug_settings and isinstance(yaml_debug_settings, dict):
                debug_settings.update(yaml_debug_settings)
                _LOGGER.debug(
                    "Loaded debug settings from YAML for inverters: %s",
                    list(yaml_debug_settings.keys()),
                )
        except Exception as e:
            _LOGGER.debug(f"Error reading debug settings from YAML configuration: {e}")

    return debug_settings


def get_debug_setting(inverter_name, setting_name, config, hass=None, default=False):
    """Get a boolean debug setting value for an inverter.

    **DEVELOPMENT/TESTING/DEBUGGING ONLY**

    This is a generic function that can check any boolean debug setting
    without requiring code changes when new settings are added. The debug settings feature
    is intended for development, testing, and debugging purposes only. It is configured
    via configuration.yaml (not exposed in the UI) to keep dev/test/debug specific
    settings separate from production user-facing configuration.

    Args:
        inverter_name: Name of the inverter to check
        setting_name: Name of the setting to check (e.g., "treat_as_standalone_energy_dashboard")
        config: Integration configuration dict (from entry.options)
        hass: Home Assistant instance (optional, for configuration.yaml access)
        default: Default value to return if setting is not found (default: False)

    Returns:
        bool: Value of the setting, or default if not found

    Example:
        Configuration in configuration.yaml (dev/test/debug only):

        solax_modbus:
          debug_settings:
            "Solax 3":
              treat_as_standalone_energy_dashboard: true
              custom_behavior: true
              another_setting: false

        Then in code, check the setting:

        from .debug import get_debug_setting

        should_skip = get_debug_setting(
            "Solax 3",
            "treat_as_standalone_energy_dashboard",
            config,
            hass
        )
    """
    debug_settings = load_debug_settings(config, hass)

    # Try exact match first
    inverter_settings = debug_settings.get(inverter_name, {})

    # If not found, try case-insensitive match
    if not inverter_settings:
        for key, settings in debug_settings.items():
            if key.lower() == inverter_name.lower():
                inverter_settings = settings
                _LOGGER.debug(f"get_debug_setting: Matched '{inverter_name}' to '{key}' (case-insensitive)")
                break

    if inverter_settings and setting_name in inverter_settings:
        result = inverter_settings.get(setting_name, default)
        _LOGGER.debug(
            "get_debug_setting(%s, %s): %s",
            inverter_name,
            setting_name,
            result,
        )
        return result

    return default
