# Growatt MID TL3-X: four-MPPT telemetry

## Validated hardware and scope

The additional `mid_*` diagnostic sensors were checked on a **MID 36KTL3-X**, firmware branch **DM1.0**, using a read-only Modbus capture and live Home Assistant readings. They are restricted to the existing `GEN2 | PV | X3 | MPPT4` classification. This is not a new inverter selection or a blanket assertion of support for every MID firmware variant. GEN4 hybrids use a different register map.

The [manufacturer's MID 25–40KTL3-X datasheet](https://vn.growatt.com/upload/file/MID_25-40KTL3-X_B%E1%BA%A3ng_Th%C3%B4ng_S%E1%BB%91_EN_202306.pdf) lists four trackers and two string inputs per tracker for the 36 kW model. Tracker count is distinct from the number of connected strings or physical roof arrays.

## What is exposed

The diagnostics cover operating status, derating, raw fault/warning fields, line-to-line voltages, positive/negative DC bus voltages, output-limit **readback**, eight connector voltage/current pairs, and string mismatch/current-imbalance/disconnection masks. They perform input-register reads only; there are no new controls.

The baseline is [Growatt Modbus RTU Protocol II v1.24](https://b.goeswhere.com/growatt-modbus.pdf), a manufacturer document hosted on a third-party mirror, input table pp. 47–52. Zero-based addresses are used. The existing four PV power descriptions read 5/9/13/17 independently of combined power at 1. Temperature is at 93; address 32 belongs to PV8 current. Removing the competing temperature description preserves the existing entity key.

Unknown status and derating values retain their numeric code. Warning fields and string masks intentionally remain raw rather than borrowing fault descriptions from a different family. A disconnected bit may describe an unused input, not a fault requiring repair. Zero or small connector currents do not establish physical wiring or roof orientation.

## Power and energy

- PV power is DC input; inverter output power is AC.
- Per-phase apparent power is in VA, not W. It is not the site's grid import/export measurement.
- Existing per-MPPT daily energy sensors may need enabling on the Entities page. Newly enabled sensors have no backfilled history.
- A field capture showed internally consistent instantaneous PV power but AC energy counters larger than reported DC counters. The cause has not been established. Do not rescale, reset, or compute conversion efficiency from those counters merely to force agreement. Compare the inverter display and firmware-specific documentation first. For this battery-free inverter, the native AC production counter represents generated AC energy.
- Set integration capacity to the actual installation rating (36 kW for a single MID 36KTL3-X). This affects integration validation, not the inverter's configured output limit.

## Verification and updates

Regression tests exercise the production register decoder, including high-word-first 32-bit quantities, signed connector current, unknown codes, MPPT matching, temperature uniqueness, and unmodified energy scaling. Broader Growatt tests should be run before merging.

Live validation on one unit does not prove undocumented codes or behavior on other firmware. Please include exact model/firmware and a minimal sanitized read-only capture when reporting differences. Avoid publishing serial numbers, network addresses or whole Home Assistant configuration files.

A manually patched HACS installation can be overwritten by updates. Use an integration release containing the change, or deliberately maintain the tested revision of a fork. No automated firmware update or register-write procedure is part of this change.
