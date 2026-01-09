# SolaX Phase Envelope Protection

**Author:** fxstein  
**Date:** January 9, 2026  
**GitHub:** https://github.com/fxstein/homeassistant-solax-modbus

**Applies To:** X3 (Three-phase) inverters with remote control

## Overview

Phase envelope protection prevents individual phases from exceeding the fuse limit (e.g., 63A) when phase imbalance exists due to single-phase loads like EV chargers. This feature automatically limits import power to protect against fuse overload while maximizing system capacity.

## The Problem

### Phase Imbalance from Single-Phase Loads

When you have single-phase loads (e.g., a 16A EV charger on L1), the phases become imbalanced:

```
Phase Current Visualization (0A ─────────────────────>| 63A)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                                           59.85A |   | 63A
                                       (95% Safe) |   | (Fuse)
                                                  ↓   ↓

SCENARIO 1: Without Imports (Battery Hold) - House Load Only
─────────────────────────────────────────────────────────────────
L1: [====4A====][======Rivian 16A======]··········|   20A (40A to limit)
L2: [====4A====]··································|   4A  (56A to limit)
L3: [====4A====]··································|   4A  (56A to limit)
    House load: 4A base per phase + Rivian 16A on L1 = 6.4kW total
    └─ Imbalance: 16A (entirely from single-phase EV charger)

SCENARIO 2: Requesting 30kW Import (43.9A per phase) - UNSAFE!
─────────────────────────────────────────────────────────────────
Target: 30kW ap_target + 6.4kW house = 36.4kW total import
Import per phase: 30,000W / (3 × 228V) = 43.9A per phase

L1: [====4A====][======16A======][========43.9A====XXXXX] 64A ✗ EXCEEDS!
L2: [====4A====][==========43.9A==========]········|   48A ✓
L3: [====4A====][==========43.9A==========]········|   48A ✓
    
    Limit Check 1 - Import Limit:
    • Total import: 36.4kW
    • Import limit: 35kW
    • Safe ap_target: 35kW - 6.4kW = 28.6kW ✓ (30kW request reduced by import limit)
    
    Limit Check 2 - Phase Limit (MORE RESTRICTIVE):
    • L1: 20A house + 43.9A import = 63.9A (EXCEEDS 63A fuse, 59.85A safe limit)
    • Safe ap_target: (59.85A - 20A) × 3 × 228V = 27.2kW ✗ (MORE RESTRICTIVE)
    
    └─ REDUCED: Phase limit (27.2kW) would be more restrictive than import limit (28.6kW)

SCENARIO 3: Requesting 30kW with Phase-Protected 27.2kW Import (39.8A per phase) - SAFE ✓
─────────────────────────────────────────────────────────────────
Same as SCENARIO 2 but now with phase protection active:

Limit Check 1 - Import Limit:
  Safe ap_target: 35kW - 6.4kW = 28.6kW ✓ (RESTRICTIVE)

Limit Check 2 - Phase Limit (CONSTRAINING):
  L1 can accept: (59.85A - 20A) = 39.85A more
  Safe ap_target: 39.85A × 3 × 228V = 27.2kW ✗ (MORE RESTRICTIVE)

Result: ap_target = min(30kW, 28.6kW, 27.2kW) = 27.2kW

L1: [====4A====][======16A======][========39.8A=======]|  59.8A ✓ (0.05A to limit!)
L2: [====4A====][========39.8A========]················|  43.8A ✓ (16A to limit)
L3: [====4A====][========39.8A========]················|  43.8A ✓ (16A to limit)
    
    Analysis:
    • L1: 20A house + 39.8A import = 59.8A (just below 59.85A safe limit) ✓
    • L2/L3: 4A house + 39.8A import = 43.8A (16A below limit) ✓
    • Total: 27.2kW + 6.4kW = 33.6kW (within 35kW import limit) ✓
    • Constrained by: PHASE LIMIT (27.2kW), not import limit (28.6kW)
    └─ SUCCESS: Phase protection prevents L1 from exceeding fuse limit

Key Points:
• House load imbalance (16A) is FIXED regardless of import level
• Inverters balance imports: each phase gets exactly ap_target / 3
• Must respect BOTH constraints: 95% fuse limit (59.85A) AND import limit (35kW)
• System uses the MORE RESTRICTIVE of the two limits
• In this scenario: PHASE LIMIT (27.2kW) is more restrictive than import limit (28.6kW)
```

### The Challenge

Without phase protection:
- Requesting 30kW import with 6kW house load (16A on L1)
- Inverters distribute 30kW evenly: 43.9A per phase
- L1 total: 16A + 43.9A = 59.9A (exceeds 59.85A safe limit)
- Risk of fuse blow on L1

## The Solution

### How It Works

1. **Measure Phase Imbalance**
   - Uses `measured_power_l1/l2/l3` to detect imbalance
   - Imbalance in measured power = imbalance in house load (inverters balance imports)

2. **Calculate House Load Per Phase**
   ```
   house_load_l1 = (house_load / 3) + (avg_measured_power - measured_power_l1)
   ```
   - Extracts actual house load distribution from measurements
   - Works regardless of current import level

3. **Calculate Safe Import**
   ```
   safe_ap_target = (59.85A - worst_phase_house_current) × 3 × avg_voltage
   ```
   - Ensures worst phase stays below 59.85A (95% of fuse limit)
   - Allows maximum import while protecting phases

4. **Apply Both Limits**
   ```
   ap_target = min(desired, import_limit - house_load, safe_ap_target)
   ```
   - Respects both total import limit AND phase limit
   - Uses the more restrictive of the two

### Key Insight

**All imbalance comes from house load** - inverters distribute imports perfectly:
- Each phase gets exactly `ap_target / 3` of the import current
- The imbalance (difference between phases) is FIXED by house load
- This allows accurate calculation without feedback loops

## Configuration

### Required Sensors

Phase protection requires these sensors (available on X3 inverters):
- `measured_power_l1/l2/l3` - Phase-specific grid power (W)
- `grid_voltage_l1/l2/l3` - Phase-specific voltages (V)
- `main_breaker_current_limit` - Fuse size setting (A, e.g., 63A)

### Automatic Activation

Phase protection activates automatically when:
- All required sensors are available
- Main breaker current limit is configured in inverter
- Remote control is active

No additional configuration needed!

## Behavior

### When Phase-Limited (Phase Constraint is More Restrictive)

```
Example: Rivian 16A on L1, 6.4kW house load (4A base + 16A Rivian on L1)
  
House: L1=20A, L2=4A, L3=4A (high imbalance from single-phase EV)

Import limit check:
  Safe ap_target: 35kW - 6.4kW = 28.6kW ✓
  
Phase limit check (MORE RESTRICTIVE):
  L1 remaining: 59.85A - 20A = 39.85A
  Safe ap_target: 39.85A × 3 × 228V = 27.2kW ✗
  
Result: ap_target = min(30kW, 28.6kW, 27.2kW) = 27.2kW
  Total import: 27.2kW + 6.4kW = 33.6kW ✓
  L1 actual: 20A + 39.8A = 59.8A ✓ (0.05A below safe limit)
  Constraint: PHASE LIMIT (27.2kW) - protecting L1 from fuse blow
```

### When Import-Limited (Import Constraint is More Restrictive)

```
Example: No EV charging, 4kW balanced house load

House: L1=6A, L2=6A, L3=6A (no imbalance)

Import limit check (MORE RESTRICTIVE):
  Safe ap_target: 35kW - 4kW = 31kW ✗
  
Phase limit check:
  L1 remaining: 59.85A - 6A = 53.85A
  Safe ap_target: 53.85A × 3 × 228V = 36.8kW ✓
  
Result: ap_target = min(30kW, 31kW, 36.8kW) = 30kW
  Total import: 30kW + 4kW = 34kW ✓
  L1 actual: 6A + 43.9A = 49.9A ✓ (10A below safe limit)
  Constraint: Desired target (30kW) achieved, neither limit constraining
```

## Logging

### Debug Logging

Enable debug logging to see phase protection calculations:

```yaml
logger:
  default: warn
  logs:
    custom_components.solax_modbus.plugin_solax: debug
```

### Log Output

```
[REMOTE_CONTROL] Phase currents - Measured: L1=54.47A L2=49.50A L3=49.14A | 
                                   House: L1=9.50A L2=5.32A L3=4.39A | worst=L1
[REMOTE_CONTROL] Phase protection: L1 house=9.50A limit=59.85A remaining=50.35A 
                                   safe_ap_target=33908.5W
[REMOTE_CONTROL] Import bounds: ap_target=29999.0W import_bound=30693.0W 
                                import_limit=35000.0W house_load=4307.0W 
                                total_import=34306.0W
```

## Benefits

1. **Automatic Protection**: No manual intervention needed
2. **Maximizes Capacity**: Allows maximum import while staying safe
3. **Prevents Fuse Blow**: Keeps worst phase below 95% of fuse limit
4. **Stable Operation**: No oscillation or feedback loops
5. **Works with EV Charging**: Handles single-phase and three-phase EV chargers
6. **Respects Both Limits**: Honors both import limit and phase limits

## Technical Details

### The Math

**Given:**
- Total `house_load` (W)
- `measured_power_l1/l2/l3` (includes house + imports)
- Fuse limit (e.g., 63A)
- Import limit (e.g., 32kW)

**Calculate:**
```python
# Extract house load per phase using imbalance
avg_measured = (measured_l1 + measured_l2 + measured_l3) / 3
house_l1 = (house_load / 3) + (avg_measured - measured_l1)

# Convert to current
house_current_l1 = house_l1 / voltage_l1

# Calculate safe ap_target
remaining_A = (fuse_limit × 0.95) - house_current_l1
safe_ap_target = remaining_A × 3 × avg_voltage

# Apply both limits
ap_target = min(desired, import_limit - house_load, safe_ap_target)
```

### Why It Works

The imbalance in `measured_power` equals the imbalance in house load because inverters balance imports:

```
measured_l1 - measured_l2 = (house_l1 - import_l1) - (house_l2 - import_l2)
                          = house_l1 - house_l2  (imports cancel)
```

This allows extracting house load distribution without feedback loops.

## Limitations

- **X3 inverters only**: Requires three-phase sensors
- **Requires fuse setting**: Must configure `main_breaker_current_limit` in inverter
- **5% margin**: Targets 95% of fuse limit (brief excursions above acceptable)
- **Balanced import assumption**: Assumes inverters distribute imports evenly (verified accurate)

## Testing

Tested and verified with:
- ✅ Single-phase EV charger (Rivian 16A)
- ✅ Dual EV chargers (Rivian 16A + Tesla 16A 3-phase)
- ✅ Parallel mode (3 inverters)
- ✅ Various house loads (4kW - 18kW)
- ✅ Import limits (32kW - 35kW)
- ✅ Phase limits (55A - 63A)

Results: Stable operation, no oscillation, correct limiting behavior.

## See Also

- [SolaX Remote Control Redesigned](solax-remote-control-redesigned.md) - Main remote control documentation
- [SolaX Parallel Mode](solax-parallel-mode.md) - Parallel mode operation
- [SolaX Mode 1 Power Control](solax-mode1-modbus-power-control.md) - Mode 1 details

