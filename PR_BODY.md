## Summary
- add an SPF-specific Energy Dashboard mapping for Growatt off-grid models
- suppress PV2 entities on known single-MPPT SPF serial families
- add computed SPF solar total sensors used by the Energy Dashboard mapping
- prefer real serial prefixes (including `KAM`) over firmware-branch-only fallback detection
- hide unused Energy Dashboard diagnostic metadata sensors by default

## Why
Growatt SPF off-grid units expose semantics that do not match the existing grid-tied mappings.
On the validated SPF5000ES setup used for testing:
- `ac_input_power` reflects grid/bypass input
- `ac_discharge_power` reflects AC power served to loads
- `battery_power_charge` is signed (`+` discharge, `-` charge)
- PV2 is not physically present on these single-MPPT units

Without an SPF-specific mapping, Home Assistant creates Energy Dashboard helpers that are incomplete or misleading for this inverter family.

## What changed
### Growatt SPF detection and entity filtering
- add `KAM` to the known single-MPPT SPF serial prefixes
- keep `067` / `113` / `500` only as fallback branch detection when a real serial prefix is unavailable
- blacklist PV2 sensors and PV2 energy counters for known single-MPPT SPF families
- make serial parsing more robust by decoding the raw register bytes directly

### SPF computed totals
- add computed `pv_power_total`
- add computed `today_s_solar_energy`
- add computed `total_solar_energy`

### Energy Dashboard mapping
Add a Growatt `ENERGY_DASHBOARD_MAPPING` limited to `allowedtypes=SPF`:
- `grid_power` <- `ac_input_power`
- `solar_power` <- `pv_power_total`
- `battery_power` <- `battery_power_charge`
- `home_consumption_power` <- `ac_discharge_power`
- `grid_to_battery_power` <- `ac_charge_power`
- `grid_energy_import` <- Riemann sum of positive `ac_input_power`
- `solar_energy_production` <- `today_s_solar_energy`
- `home_consumption_energy` <- `today_s_ac_discharge`
- `battery_energy_charge` <- Riemann sum of charge-only portion of `battery_power_charge`
- `battery_energy_discharge` <- `today_s_battery_discharge`
- `grid_to_battery_energy` <- `today_s_ac_charge`

Intentionally not mapped:
- `grid_energy_export`

### Energy Dashboard metadata sensors
Set the diagnostic metadata sensors to `entity_registry_enabled_default=False` so fresh installs do not expose unused `Unknown` metadata entities by default.

## Validation
- `python3 -m py_compile custom_components/solax_modbus/plugin_growatt.py custom_components/solax_modbus/energy_dashboard.py`
- `git diff --check`
- live validation on two parallel Growatt SPF5000ES units in Home Assistant:
  - serial prefixes observed as `KAM...`
  - PV2 absent physically and suppressed as expected
  - `battery_soc`, `pv_power_1`, `grid_voltage`, `grid_frequency`, `output_voltage`, `output_frequency`, `battery_voltage`, and temperature sensors match live readings
  - Energy Dashboard source entities update coherently with local system templates

## Notes
This keeps the PR scoped to SPF/off-grid semantics and avoids inventing unsupported grid export behaviour for systems that do not export to grid.
