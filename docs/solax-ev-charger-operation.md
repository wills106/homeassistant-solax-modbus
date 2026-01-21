# SolaX EV Charger Operation

**Author:** fxstein  
**Date:** January 11, 2026  
**GitHub:** https://github.com/fxstein/solax-modbus

## Overview

This document explains how the SolaX Modbus integration detects and operates with SolaX EV chargers. It covers device type detection, the special case of GEN1/GEN2 hybrid chargers, and integration with the SolaX Datahub 1000.

## Device Type Detection

The integration automatically detects EV charger models from the serial number during the `async_determineInverterType()` process. It supports both legacy prefix-based serials and the newer category/model/power code format.

### Supported Models (Legacy Prefixes)

| Serial Prefix | Model | Power | Generation | Hardware Version |
|---------------|-------|-------|------------|-------------------|
| C107 | X1-EVC-7kW | 7kW | GEN1 | Gen1 |
| C311 | X3-EVC-11kW | 11kW | GEN1/GEN2* | Gen1 or Gen1 (GEN2 FW) |
| C322 | X3-EVC-22kW | 22kW | GEN1/GEN2* | Gen1 or Gen1 (GEN2 FW) |

*C311 and C322 are hybrid models that can run either GEN1 or GEN2 firmware (see Hybrid Detection section below).
*Older code used `50**` prefixes for Gen2 HAC models, but SolaX support confirmed the correct parsing is based on the new category/model/power format below.

### Supported Models (New Serial Format)

Newer EV chargers use a serial format like `5 03 0B 002060C0P`. The Modbus register returns it without spaces; the first 5 characters encode the model and power.

- Product category: `5` = EV Charger (EVC)
- Model codes:
  - `02` = X1-HAC
  - `03` = X3-HAC
  - `04` = A1-HAC
  - `05` = J1-HAC
  - `06` = X1-HAC-S
  - `07` = X3-HAC-S
  - `08` = C1-HAC
  - `09` = C3-HAC

- Power codes:
  - `04` = 4.6kW
  - `07` = 7.2kW
  - `0B` = 11kW
  - `0M` = 22kW

### Detection Process

1. **Serial Number Read**: Integration reads serial number from register 0x600
2. **Legacy Prefix Matching**: Matches C107/C311/C322 first
3. **New Code Parsing**: Parses category/model/power codes for new-format serials
4. **Type Classification**: Sets `invertertype` bitmask (X1/X3, power rating, GEN1/GEN2)
5. **Model Assignment**: Sets `inverter_model` and `hardware_version` fields

### Example Detection

```python
# Serial number (as read from Modbus): 5030B002060C0P
# Support example: 5 03 0B 002060C0P
# Category: 5 (EVC), model code: 03 (X3-HAC), power code: 0B (11kW)
# Result: X3-HAC-11kW, GEN2
```

## Hybrid GEN1/GEN2 Detection

### Problem Statement

C311 and C322 EV charger models are labeled as Gen1 hardware but can run either:
- **Legacy:** Original GEN1 firmware
- **Modern:** GEN2 firmware v7.07+

Simply reclassifying ALL C311/C322 as GEN2 would break backward compatibility for users with legacy firmware.

### Solution: Dynamic Firmware-Based Detection

The integration uses **dynamic firmware detection** to automatically determine the correct generation type:

**Default Classification:** C311/C322 start as GEN1 (backward compatible)

**Runtime Detection:** During `async_determineInverterType()`:
1. Attempt to read firmware version from register 0x25
2. If firmware version >= 7.0:
   - Reclassify `invertertype` as GEN2
   - Set `hardware_version = "Gen1 (GEN2 FW)"`
   - Enable GEN2 registers (Max Charge Current, EVSE Mode, etc.)
3. If firmware read fails or version < 7.0:
   - Keep as GEN1
   - Set `hardware_version = "Gen1"`
   - Use GEN1 registers only

### Implementation

The detection uses the `async_read_firmware(hub, 0x25)` helper function:

```python
elif seriesnumber.startswith("C311"):
    # Default to GEN1 for backward compatibility
    invertertype = X3 | POW11 | GEN1
    self.inverter_model = "X3-EVC-11kW"
    self.hardware_version = "Gen1"
    
    # Try to detect GEN2 firmware for hybrid hardware
    fw_version = await async_read_firmware(hub, 0x25)
    if fw_version is not None and fw_version >= 7.0:
        # Upgrade to GEN2 - has GEN2 firmware
        invertertype = X3 | POW11 | GEN2
        self.hardware_version = "Gen1 (GEN2 FW)"
        _LOGGER.info(f"{hub.name}: C311 detected with GEN2 firmware v{fw_version:.2f}, enabling GEN2 features")
```

Same logic applies to C322 (22kW model).

### Benefits

✅ **Backward Compatible**
- Legacy C311/C322 (old firmware) stay as GEN1
- Existing installations continue working
- No breaking changes

✅ **Forward Compatible**  
- Modern C311/C322 (GEN2 firmware) auto-detect as GEN2
- Get access to GEN2 registers automatically
- Labeled correctly based on actual firmware

✅ **Self-Documenting**
- `hardware_version` field shows hybrid status: "Gen1 (GEN2 FW)"
- Debug logs show detection decision
- Clear in device info screen

### Register Availability

**Legacy C311/C322 (GEN1 firmware):**
- Start Charge Mode (0x610) - GEN1 version ✅
- Charge Added Total (0x619) ✅
- Basic GEN1 registers ✅
- Max Charge Current (0x668) ❌
- EVSE Mode (0x669) ❌

**Modern C311/C322 (GEN2 firmware >= 7.0):**
- Start Charge Mode (0x610) - GEN2 version ✅
- Max Charge Current (0x668) ✅
- EVSE Mode (0x669) ✅
- Firmware Version (0x25) ✅
- Charge Added Total (0x619) ✅
- All GEN2 registers ✅

### Firmware Version Register

**Register:** 0x25  
**Type:** Input (read-only)  
**Format:** REGISTER_U16 with decimal hundredths scaling  
**Example:** Raw value 707 → 7.07

**Detection Logic:**
- If register reads successfully AND value >= 700 (7.00): GEN2 firmware
- If register fails OR value < 700: GEN1 firmware

### Error Handling

**If firmware detection fails:**
- Default to GEN1 (safe, backward compatible)
- Log debug message explaining failure
- User still gets working charger (just missing GEN2 features)

**If firmware reads but version unclear:**
- Use conservative threshold (>= 7.0)
- Log actual version for debugging
- Better to stay GEN1 than incorrectly upgrade

## Datahub 1000 Integration

### Overview

When a **Solax Datahub 1000** is connected to Solax EV chargers, it takes control of charging operations via OCPP (Open Charge Point Protocol). The integration defaults to OCPP-style operation when Datahub is present.

### System Architecture

```
┌─────────────────┐
│  Solar Panels   │
└────────┬────────┘
         │
┌────────▼────────┐
│  Solax Inverter │
└────────┬────────┘
         │
┌────────▼────────┐       ┌─────────────┐
│ Datahub 1000    │◄──────┤  Grid       │
│ (Smart Hub)     │       └─────────────┘
└────────┬────────┘
         │ OCPP Protocol
         │
┌────────▼────────┐       ┌─────────────┐
│  EV Charger     │◄──────┤  EV Vehicle │
└─────────────────┘       └─────────────┘
```

### OCPP Mode Behavior

**Automatic Mode Switching:**
- **EVSE Scene** (register 0x61C) automatically set to "OCPP mode"
- Should not be changed to "Standard mode" or "PV mode" while Datahub is connected
- Datahub maintains OCPP mode to retain control

**Load Management:**
The Datahub performs intelligent load balancing across:
1. Solar production (available energy)
2. Grid connection (import/export limits)
3. Battery charging/discharging
4. Home consumption
5. EV charging

**Dynamic Adjustment Example:**
```
Scenario: EV charging + Inverter battery charging enabled

Initial state:
- Max Charge Current: 16A (user setting)
- Grid capacity: Available
- EV charging at: ~16A per phase

When battery charging starts (high system load):
- Datahub reduces EV to: 6A per phase (minimum)
- Prioritizes: Battery charging over EV charging
- Reason: Prevents grid overload

When battery charging stops (capacity available):
- Datahub increases EV back to: ~16A per phase
- Returns to: Max Charge Current limit
```

### Register Behavior in OCPP Mode

**Registers That Work:**

| Register | Entity | Function | Datahub Behavior |
|----------|--------|----------|------------------|
| 0x60D | Charger Use Mode | Stop/Fast | ⚠️ **Only FAST mode available in OCPP** |
| 0x668 | Max Charge Current | Upper limit (6-32A) | ✅ **Enforced as maximum** |
| 0x610 | Start Charge Mode | Plug&Charge/RFID/App | ✅ Required for control |
| 0x26 | Network Connected | Connection status | ✅ **Indicates Datahub ↔ EVC active communication** |

**Critical:** Set `Start Charge Mode` to **"Plug & Charge"** for Datahub control to work.

**OCPP Mode Behavior:**
- In OCPP mode, **only FAST mode is available** - ECO and GREEN modes are not available
- Only **STOP** and **FAST** modes work in OCPP mode
- Datahub enforces FAST mode for active charging in OCPP mode
- **Network Connected** (register 0x26) indicates active communication between Datahub and EV charger

**Registers That Are Ignored:**

| Register | Entity | Status | Reason |
|----------|--------|--------|--------|
| 0x60E | ECO Gear | ❌ Not available | ECO mode not available in OCPP |
| 0x60F | Green Gear | ❌ Not available | GREEN mode not available in OCPP |
| 0x628 | Charge Current | ❌ Ignored | Overridden by OCPP |
| 0x624 | Datahub Charge Current | ⚠️ Status only | Read by Datahub, not control |

**Note:** In OCPP mode, only FAST mode is available. ECO and GREEN modes are not available when Datahub is connected.

### Register Roles

**Manual control registers (when NOT in OCPP mode):**
- `0x628` - Charge Current: Direct current setpoint
- `0x60E` - ECO Gear: Preset current for ECO mode
- `0x60F` - Green Gear: Preset current for Green mode
- `0x60D` - Charger Use Mode: Stop/Fast/ECO/Green (all modes available)

**OCPP mode registers (when Datahub connected):**
- `0x668` - Max Charge Current: Hard upper limit for Datahub
- `0x624` - Datahub Charge Current: Status/feedback (what Datahub is requesting)
- `0x60D` - Charger Use Mode: Only Stop/Fast available (ECO/Green not available in OCPP)
- `0x26` - Network Connected: Indicates active Datahub ↔ EVC communication
- Datahub ignores manual current settings and uses its own algorithm

### How to Control Charging with Datahub

**Recommended Approach:**

Use **Max Charge Current** (0x668) as your control interface:

```
To limit charging to 10A:
→ Set Max Charge Current = 10A
→ Datahub will never exceed 10A
→ But may go lower for load management

To allow full speed:
→ Set Max Charge Current = 32A (or charger maximum)
→ Datahub will use available capacity
→ Dynamically adjusts based on system load
```

**Example Use Cases:**

**Case 1: Limit overnight charging**
```
Set Max Charge Current = 10A
→ Slower charging, less grid impact
→ Datahub may reduce further if needed
```

**Case 2: Fast charging when solar is abundant**
```
Set Max Charge Current = 32A
→ Use maximum available power
→ Datahub manages based on solar production
```

**Case 3: Prevent charging temporarily**
```
Set Charger Use Mode = "Stop"
→ Completely stops charging
→ Can be resumed later
→ Note: Resume with "Fast" mode (only FAST available in OCPP)
```

### Advantages of Datahub OCPP Control

**Benefits:**

1. **Intelligent Load Balancing**
   - Prevents grid overload
   - Optimizes across all loads (home, batteries, EV)
   - Automatic adjustment to changing conditions

2. **Solar Optimization**
   - Increases charging when excess solar is available
   - Reduces when solar production drops
   - Maximizes self-consumption

3. **Grid Protection**
   - Respects import/export limits
   - Prevents breaker trips
   - Manages peak demand

4. **Battery Priority**
   - Can prioritize battery charging over EV
   - Balances long-term storage vs immediate EV needs

**Limitations:**

1. **No Manual Current Control**
   - Cannot set exact charging current
   - ECO/Green Gear settings not available in OCPP mode
   - Only Max Charge Current is respected

2. **Mode Locked to OCPP and FAST**
   - EVSE Scene locked to "OCPP mode"
   - Charger Use Mode: Only FAST mode available (ECO/GREEN not available in OCPP)
   - Should not switch to Standard or PV mode while Datahub connected
   - Datahub maintains control
   - Would require Datahub disconnection to override

3. **Minimum Current Floor**
   - Datahub may reduce to 6A minimum
   - Cannot stop via current setting (use Mode instead)

### Troubleshooting

**EVSE Scene keeps reverting to OCPP mode**
- **Cause:** Datahub is connected and maintaining control  
- **Solution:** This is normal behavior—EVSE Scene must be OCPP mode with Datahub

**ECO/GREEN modes not available**
- **Cause:** In OCPP mode, only FAST mode is available  
- **Behavior:**
  - ECO and GREEN modes are not available when Datahub is connected
  - Only STOP and FAST modes work in OCPP mode
- **Solution:** This is intentional—only STOP and FAST modes work with Datahub. Use Max Charge Current to control speed instead.

**Charging current is lower than expected**
- **Cause:** Datahub load management is reducing current  
- **Check:**
  - Is inverter battery charging active? (high load)
  - Is grid connection heavily loaded?
  - Is solar production low?
- **Solution:** This is intentional load balancing

**Cannot start charging from Home Assistant**
- **Cause:** Start Charge Mode is likely set to "App mode"  
- **Solution:** Change to "Plug & Charge" mode (register 0x610)

**Max Charge Current not being respected**
- **Cause:** Datahub may have its own limits  
- **Check:**
  - Datahub configuration
  - Grid connection limits
  - Physical charger capabilities

## Related Documentation

**Note:** The following documentation files are located in the main homeassistant repository and are not part of this integration's documentation:

- EV Charger Hybrid GEN Detection - Detailed design document (see main repo docs/solax/EV_CHARGER_HYBRID_GEN_DETECTION.md)
- EV Charger Datahub OCPP Mode - Complete OCPP mode reference (see main repo docs/solax/EV_CHARGER_DATAHUB_OCPP_MODE.md)
- EV Charger Control Reference - Register reference guide (see main repo docs/solax/EV_CHARGER_CONTROL_REFERENCE.md)
- Start Charge Mode Behavior - Charge mode documentation (see main repo docs/solax/EV_CHARGER_START_CHARGE_MODE.md)

## Summary

The SolaX Modbus integration provides automatic detection of EV charger models from both legacy prefixes and the newer category/model/power serial format, with special handling for hybrid GEN1/GEN2 chargers (C311/C322). When a Datahub 1000 is present, the integration defaults to OCPP-style operation, providing intelligent load management while maintaining control through Max Charge Current settings.
