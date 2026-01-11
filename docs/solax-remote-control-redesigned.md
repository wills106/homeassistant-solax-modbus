# SolaX Remote Control - Redesigned Calculations

**Author:** fxstein  
**Date:** October 28, 2025 (Updated: January 9, 2026)  
**GitHub:** https://github.com/fxstein/homeassistant-solax-modbus

**Recent Updates:**
- Added Phase Envelope Protection for X3 inverters (January 9, 2026)
- See [SolaX Phase Protection](solax-phase-protection.md) for details

## Overview

This document redesigns the remote control calculations from scratch, using clear variable names and logical formulas based on our understanding of the system. It is based on a physics based Power Flow Equation.

## System Understanding

### Power Sources
- **PV**: Solar panel production
- **Battery**: Battery charging/discharging
- **Grid**: Grid import/export
- **House**: House consumption

### Power Flow Equation

The fundamental power flow equation is:
```
Power_Sources = Power_Sinks
PV + Grid_import + Battery_discharge = House + Battery_charge + Grid_export
```

### Variable Polarity Problem

Our variables have inconsistent polarity conventions, making the power flow equation confusing:

- **`pv_power`**: Always ≥ 0 (production)
- **`house_load`**: Always ≥ 0 (consumption) 
- **`battery_power`**: Positive = charging, Negative = discharging
- **`grid_power`**: Positive = import, Negative = export

### Power Flow Examples

**Example 1: Battery Charging**
- PV: 5kW production
- Grid: 6kW import
- Battery: 2kW charging (positive)
- House: 9kW consumption
- Equation: `5kW + 6kW + 0kW = 9kW + 2kW + 0kW` ✓

**Example 2: Battery Discharging**
- PV: 3kW production
- Grid: 0kW (no import/export)
- Battery: 2kW discharging (negative)
- House: 5kW consumption
- Equation: `3kW + 0kW + 2kW = 5kW + 0kW + 0kW` ✓

**Example 3: Grid Export**
- PV: 8kW production
- Grid: 3kW export (negative)
- Battery: 1kW charging (positive)
- House: 4kW consumption
- Equation: `8kW + 0kW + 0kW = 4kW + 1kW + 3kW` ✓

### Using Our Variable Conventions

The power flow equation with our variables becomes:
```
pv_power + max(0, grid_power) + max(0, -battery_power) = house_load + max(0, battery_power) + max(0, -grid_power)
```

This accounts for the mixed polarity conventions in our variables.

### Key Variables
- `pv_power`: Current PV production (W, always ≥ 0)
- `battery_power`: Current battery power (W, positive = charging, negative = discharging)
- `grid_power`: Current grid power (W, positive = import, negative = export)
- `house_load`: Current house consumption (W, always ≥ 0)
- `target`: Desired power target (W, positive = import target, negative = export target)
- `ap_target`: Active power target sent to the inverter (W, positive = import, negative = export)

**Note:** `target` and `ap_target` have the same polarity convention. In "Enabled Power Control" mode, `ap_target = target` directly.

### ⚠️ Critical Understanding: AP Target Implicitly Includes House Load

**This is the most important concept for understanding remote control calculations:**

- **An import `ap_target` implicitly includes house load in the total grid import**
- **`ap_target = 0` means ALL house load comes from the grid**
- **`ap_target > 0` means grid import = `ap_target + house_load`**

**Examples:**
- **House load: 4kW, `ap_target = 0`**: 
  - Grid imports 4kW (all for house load)
  - No battery charging
  
- **House load: 4kW, `ap_target = 10kW`**: 
  - Grid imports 14kW total (4kW for house + 10kW for battery/inverter)
  - 10kW available for battery charging
  
- **House load: 4kW, `ap_target = -5kW`**: 
  - Grid exports 5kW from inverter
  - House load (4kW) supplied by inverter, 1kW excess exported

**This is why most control modes subtract house_load from the target** - to account for the fact that the inverter automatically 'adds' house_load to the grid import.

## Redesigned Control Modes

### 1. Enabled Power Control
**Purpose**: Direct power control - set exact grid power
**Formula**: `ap_target = target`
**Explanation**: Simply set the grid power to the target value. The system will adjust battery and PV to maintain this.

### 2. Enabled Grid Control
**Purpose**: Control grid import/export while accounting for house load
**Formula**: 
```python
ap_target = target - house_load
```

### 3. Enabled Self Use
**Purpose**: Minimize grid usage by using PV and battery to supply house load
**Formula**: 
```python
ap_target = 0 - house_load
```
**Explanation**: Set grid power to negative house load, meaning PV + battery should supply the house load.

### 4. Enabled Battery Control
**Purpose**: Control battery charging/discharging to target
**Formula**: 
```python
ap_target = target - pv_power
```
### 5. Enabled Feedin Priority
**Purpose**: Maximize grid export by using excess PV and battery
**Formula**: 
```python
if pv_power > house_load:
    ap_target = 0 - pv_power - battery_power  # Export all excess
else:
    ap_target = 0 - house_load  # Just supply house load
```
**Explanation**: 
- If PV exceeds house load, export all excess (PV + battery)
- Otherwise, just supply house load

### 6. Enabled No Discharge
**Purpose**: Hold battery level by preventing discharge
**Formula**: 
```python
if battery_capacity < 98:
    ap_target = 0  # Let inverter balance PV/grid naturally
    power_control = "Enabled Power Control"
else:
    ap_target = 0  # Battery full, no action needed
    power_control = "Disabled"
```
**Explanation**: 
- Below 98%: Use PV to supply house load, prevent battery discharge
- Above 98%: Battery full, no action needed
- If the No Discharge setting would be applied when SoC reaches 100%
  it would disable PV production and import the housload from the
  grid, even on a sunny day. 

## Bounds Checking

### Understanding AP Target Sign Convention
- **Positive `ap_target`**: Inverter is **importing** power from the grid
- **Negative `ap_target`**: Inverter is **exporting** power to the grid

### Phase Envelope Protection (X3 Inverters)

**Purpose**: Prevent individual phases from exceeding fuse limits when phase imbalance exists

Phase protection automatically activates on X3 inverters when:
- Phase-specific sensors are available (`measured_power_l1/l2/l3`, `grid_voltage_l1/l2/l3`)
- Main breaker current limit is configured in inverter settings
- Remote control is active

**How it works:**
1. Calculates house load per phase using measured power imbalance
2. Determines safe `ap_target` to keep worst phase below 95% of fuse limit
3. Applies as additional constraint alongside import/export limits

**Example:**
- Rivian 16A EV charger on L1 creates 14A imbalance
- Without protection: 30kW import → L1 reaches 60A (exceeds 59.85A limit)
- With protection: Limits to 26kW import → L1 stays at 54A (safe)

See [SolaX Phase Protection](solax-phase-protection.md) for detailed documentation.

### Import Limit (for positive ap_target)
**Formula**: 
```python
# Without phase protection:
ap_target = min(ap_target, import_limit - house_load)

# With phase protection (X3 inverters):
safe_ap_target_from_phase = (59.85A - worst_phase_house_current) × 3 × avg_voltage
ap_target = min(ap_target, import_limit - house_load, safe_ap_target_from_phase)
```

**Explanation**: When importing, ensure:
1. Total grid import doesn't exceed `import_limit`
2. Worst phase doesn't exceed 95% of fuse limit (X3 only)

**Example**:
- House load: 6kW (L1=17A, L2=5A, L3=4A)
- Import limit: 32kW
- Fuse limit: 63A
- Import limit check: 32kW - 6kW = 26kW
- Phase limit check: (59.85A - 17A) × 3 × 228V = 29.3kW
- Result: ap_target capped at 26kW (import limit more restrictive)

### Export Limit (for negative ap_target)
**Formula**: `ap_target = max(ap_target, -export_limit)`
**Explanation**: When exporting, ensure total grid export doesn't exceed limit

**Example**:
- House load: 6kW
- Export limit: 20kW
- If ap_target = -30kW: Cap to max(-30kW, -20kW) = -20kW
- Total grid export: 20kW (within limit)

**Note:** Phase protection for exports is planned but not yet implemented.

### Complete Bounds Checking Logic
```python
if ap_target > 0:  # Importing 
    import_bound = import_limit - house_load
    
    # Apply phase protection if available (X3 inverters)
    if safe_ap_target_from_phase is not None:
        import_bound = min(import_bound, safe_ap_target_from_phase)
    
    ap_target = min(ap_target, import_bound)
    
elif ap_target < 0:  # Exporting 
    ap_target = max(ap_target, -export_limit)
    # Phase protection for exports: planned
    
# If ap_target = 0, no bounds checking needed
```

## Key Improvements

1. **Clear Variable Names**: No more misleading `houseload_nett`/`houseload_brut`
2. **Logical Formulas**: Each formula directly implements the control mode's purpose
3. **Power Flow Understanding**: All calculations based on the fundamental power flow equation
4. **Simplified Logic**: No complex nested calculations or mysterious variables
5. **Simplified No Discharge**: Removed unnecessary PV checking logic that was causing excessive imports

## Example Calculations

### Battery Control Example 
- **Target**: 40kW battery charging
- **PV**: 5kW production
- **House**: 6kW consumption
- **Calculation**: `ap_target = 40kW - 5kW = 35kW`
- **Result**: Import 35kW from grid, combined with 5kW PV to achieve 40kW battery charging (house load balanced naturally)

### Grid Control Example - Import
- **Target**: 40kW import
- **House**: 6kW consumption
- **Calculation**: `ap_target = 40kW - 6kW = 34kW`
- **Result**: Import 34kW through inverter + 6kW for house = 40kW total grid import

### Grid Control Example - Export
- **Target**: -20kW export
- **House**: 6kW consumption
- **Calculation**: `ap_target = -20kW - 6kW = -26kW`
- **Result**: Export 26kW through inverter - 6kW for house = 20kW net grid export

This redesign eliminates the confusing variable names and complex calculations, making the control logic clear and maintainable.

## Parallel Mode Considerations

### Parallel Mode Architecture

In parallel mode systems, multiple inverters work together:
- **Master Inverter**: Controls the entire system and communicates with Home Assistant
- **Slave Inverters**: Follow the master's commands and report their status
- **Total System Power**: Sum of all inverters' power

### Parallel Mode Variables

- `parallel_setting`: "Master", "Slave", or "Free"
- `pm_total_inverter_power`: Total power from all inverters (Master + Slaves)
- `pm_total_pv_power`: Total PV power from all inverters
- `pm_battery_power_charge`: Battery charging power from grid only (does NOT include PV contribution)
  - ⚠️ **Critical**: This sensor shows **grid-to-battery charging only**
  - Total battery charging = `pm_battery_power_charge` + PV contribution
- `single_inverter_power`: Power from individual inverter (for comparison)

### Parallel Mode Power Flow

The power flow equation becomes:
```
PM_PV + PM_Grid + PM_Battery = PM_House
```

Where:
- **PM_PV**: Total PV production from all inverters
- **PM_Grid**: Total grid power (import/export)
- **PM_Battery**: Total battery power (charging/discharging)
- **PM_House**: Total house consumption

### Parallel Mode Control Logic

**Master Inverter Control**:
- Only the master inverter should execute remote control commands
- Master calculates total system requirements
- Master distributes commands to slave inverters
- Master reports total system status to Home Assistant

**Slave Inverter Behavior**:
- Slaves should not execute remote control commands
- Slaves report their individual status to the master
- Slaves follow master's power distribution commands

### Parallel Mode Calculations 

**Battery Control Example**:
- **Target**: 40kW total battery charging
- **PM PV**: 15kW total production
- **PM House**: 18kW total consumption
- **Calculation**: `ap_target = 40kW - 15kW = 25kW`
- **Result**: Master imports 25kW, combined with 15kW PV to achieve 40kW total battery charging (house load balanced naturally)

**Grid Control Example - Import**:
- **Target**: 40kW total import
- **PM House**: 18kW total consumption
- **Calculation**: `ap_target = 40kW - 18kW = 22kW`
- **Result**: Master imports 22kW through inverter + 18kW for house = 40kW total grid import

**Grid Control Example - Export**:
- **Target**: -20kW total export
- **PM House**: 18kW total consumption
- **Calculation**: `ap_target = -20kW - 18kW = -38kW`
- **Result**: Master exports 38kW through inverter - 18kW for house = 20kW net grid export

### Parallel Mode Implementation

```python
if parallel_setting == "Master":
    # Use PM total values for calculations
    pv_power = datadict.get("pm_total_pv_power", 0)
    inverter_power = datadict.get("pm_total_inverter_power", 0)
    battery_power_charge = datadict.get("pm_battery_power_charge", 0)
    house_load = datadict.get("pm_total_house_load", 0)  # Use the calculated PM house load
elif parallel_setting == "Slave":
    # Slaves should not execute remote control
    return { 'action': WRITE_MULTI_MODBUS, 'data': [] }
else:
    # Single inverter mode - use individual values
    pv_power = datadict.get("pv_power_total", 0)
    inverter_power = datadict.get("inverter_power", 0)
    battery_power_charge = datadict.get("battery_power_charge", 0)
    house_load = inverter_power - measured_power
```

### PM House Load Delta Correction

**Problem:** SolaX inverters underreport the inverter power measurement during remote control operations, particularly during battery charging. This causes the calculated house load to appear artificially higher than actual consumption.

**Solution:** The `value_function_pm_total_house_load()` function implements a delta correction using two independent calculation methods:

1. **Inverter Method**: `pm_inverter_power - grid_power`
   - Direct measurement from inverter perspective
   - Can be underreported during remote control

2. **Physics Method**: `pv_power - grid_power - battery_power`
   - Based on energy conservation (Power Flow Equation)
   - More accurate during remote control operations

**Delta Correction Logic:**
```python
delta = physics_method - inverter_method

# Only apply correction if delta < 25% of house load
# (Large deltas indicate transition states)
if abs(delta) <= abs(inverter_method) * 0.25:
    corrected_house_load = inverter_method - (delta / 2)
```

**Key Points:**
- **Active during remote control only**: Correction only applies when `remotecontrol_active_power != 0`
- **25% threshold**: Prevents correction during transition states (e.g., starting/stopping battery charging)
- **Half-strength correction**: Splits the difference between the two methods to avoid overcorrection
- **Preserves accuracy**: Provides more reliable house load readings for remote control calculations

**Example:**
- Inverter method: 4,233W
- Physics method: 4,831W
- Delta: 598W (14.1% of house load)
- Correction applied: -299W (half the delta)
- Corrected house load: 3,934W

This correction ensures that remote control modes (especially Battery Control and Grid Control) can accurately account for true house load when calculating `ap_target` values.

This parallel mode design ensures the remote control system works correctly with multi-inverter setups.
