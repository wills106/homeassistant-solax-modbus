# Plugin Phase Naming Convention

## Scope

This note documents the electrical phase naming convention for SolaX plugin entity descriptions.

## SolaX convention

Within SolaX plugins, use `L1`, `L2`, `L3` for electrical phase entity names, keys and state labels.

This applies especially to:

- `plugin_solax.py`
- `plugin_solax_a1j1.py`
- `plugin_solax_ev_charger.py`
- `plugin_solax_lv.py`
- `plugin_solax_mega_forth.py`

For new SolaX phase entities, prefer keys with `*_l1`, `*_l2`, `*_l3`. Do not rename existing Home Assistant entity keys without an explicit migration plan; entity keys are part of the generated Home Assistant unique ID.

If vendor documentation labels the same SolaX registers as A/B/C, keep the integration naming first and put the vendor label in parentheses when useful:

- `L1 (A)`
- `L2 (B)`
- `L3 (C)`

## Known non-SolaX / historical differences

The following plugins intentionally keep their original historical or vendor-specific phase naming (`A/B/C`, `R/S/T`, `R/Y/B`) in names and/or keys. This is a conscious compatibility difference and should not be changed as part of the SolaX naming convention cleanup:

- `plugin_Enertech.py`
- `plugin_sofar_old.py`
- `plugin_solis_old.py`
- `plugin_solinteg.py`
- `plugin_sunway.py`

These plugins are outside the current SolaX phase naming scope. If they are ever normalized, that should be a separate migration-aware change.

## SolaX EV Charger audit

The EV Charger plugin was checked after upstream PR #2012. It now consistently uses:

- Phase select/readback values: `L1 Phase`, `L2 Phase`, `L3 Phase`
- Three-phase sensor keys: `*_l1`, `*_l2`, `*_l3`
- Three-phase sensor names: `... L1`, `... L2`, `... L3`
- Register comments: `L1 (A) / L2 (B) / L3 (C)` where vendor A/B/C terminology is useful

Covered EV Charger sensor groups:

- Charge voltage
- Charge current
- Charge power
- Charge power alt
- Charge frequency
- Grid current
- Grid power
- Active charge phase

## Regression guards

- `tests/unit/test_plugin_phase_naming.py` verifies that SolaX plugin user-facing phase names and new phase keys stay on `L1`/`L2`/`L3`, including the EV Charger plugin.

