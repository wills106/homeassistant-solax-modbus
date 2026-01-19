# Energy Dashboard (Developer)

## Overview

This document describes the virtual Energy Dashboard device implementation for developers and maintainers.

The Energy Dashboard framework:
- Creates a virtual device per hub
- Builds curated power/energy sensors from mappings
- Handles parallel mode aggregation
- Exposes diagnostics for troubleshooting

## Core Files

- `custom_components/solax_modbus/energy_dashboard.py`
- `custom_components/solax_modbus/diagnostics.py`
- `custom_components/solax_modbus/sensor.py`

## Mapping Structure

Mappings are defined per plugin via:
- `EnergyDashboardMapping`
- `EnergyDashboardSensorMapping`

Mapping fields:
- `source_key`, `target_key`, `name`
- `source_key_pm` for Primary totals
- `invert` / `invert_function`
- `use_riemann_sum` for GEN1 energy
- `needs_aggregation` for energy totals in parallel mode

## Mapping Examples (from `plugin_solax`)

These examples are taken from the SolaX plugin mappings and show common patterns.

Basic power sensor with inversion and parallel mode skip:

```python
EnergyDashboardSensorMapping(
    source_key="measured_power",
    target_key="grid_power",
    name="Grid Power",
    invert=True,
    icon="mdi:transmission-tower",
    skip_pm_individuals=True,
    allowedtypes=ALL_GEN_GROUP,
)
```

Parallel mode override using a PM total source:

```python
EnergyDashboardSensorMapping(
    source_key="pv_power_total",
    source_key_pm="pm_total_pv_power",
    target_key="solar_power",
    name="Solar Power",
    allowedtypes=ALL_GEN_GROUP,
)
```

GEN1 energy sensor using Riemann sum + filtering:

```python
EnergyDashboardSensorMapping(
    source_key="grid_power_energy_dashboard",
    target_key="grid_energy_import",
    name="Grid Import Energy",
    use_riemann_sum=True,
    filter_function=lambda v: max(0, v),
    allowedtypes=GEN,
)
```

Parallel mode energy totals with aggregation:

```python
EnergyDashboardSensorMapping(
    source_key="battery_input_energy_today",
    target_key="battery_energy_charge",
    name="Battery Charge Energy",
    needs_aggregation=True,
    allowedtypes=GEN3 | GEN4 | GEN5 | GEN6,
)
```

## Sensor Creation Flow

1. Validate mapping
2. Determine hub mode (Standalone / Parallel Primary / Parallel Secondary)
3. Create sensors:
   - Standalone: per‑inverter sensors only
   - Primary: “All” sensors + per‑inverter sensors
   - Secondary: skipped unless debug override
4. Attach diagnostics once per virtual Energy Dashboard device

## Parallel Mode Aggregation

- Power totals: use PM totals on Primary where available
- Energy totals: aggregate Primary + Secondary values when `needs_aggregation=True`
- Secondary inverters are read via hub access, not HA entity lookups

## Diagnostics

Diagnostics are computed sensors (no registers) on the virtual Energy Dashboard device:
- Mode
- Inverter count
- Debug override (only when enabled)
- Parallel setting (only when debug override is off)
- Secondary inverters and PM inverter count (only when parallel context exists)
- Mapping summary

