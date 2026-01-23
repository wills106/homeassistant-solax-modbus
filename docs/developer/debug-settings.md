# Debug Settings (Developer)

## Overview

The integration provides a generic debug settings mechanism in `debug.py`. It is intended for development, testing, and troubleshooting and is configured via `configuration.yaml` (not exposed in the UI).

This mechanism is generic and can be reused for additional debug toggles without code changes to the loader.

## How It Works

- Debug settings are read from `configuration.yaml`
- Settings are stored in `hass.data[DOMAIN]["_debug_settings"]`
- `get_debug_setting()` looks up boolean values by inverter name

## Configuration Example

```yaml
solax_modbus:
  debug_settings:
    "Solax 3":
      treat_as_standalone_energy_dashboard: true
```

## Usage in Code

```python
from custom_components.solax_modbus.debug import get_debug_setting

debug_standalone = get_debug_setting(
    "Solax 3",
    "treat_as_standalone_energy_dashboard",
    config,
    hass,
    default=False,
)
```

## Guidelines

- Keep all debug settings **YAML-only**
- Avoid adding UI options for debug flags
- Use clear, boolean setting names
- Ensure debug behavior does not alter production defaults

