# Phase D Runtime Bug Fixes & Regression Tests

## Overview

During Phase 4 mypy strict mode implementation, three critical runtime bugs were discovered and fixed that affected 300+ sensors on system startup. This document details the bugs, fixes, and regression tests added to prevent reintroduction.

## Critical Bugs Fixed

### Bug 1: Energy Dashboard device_info Overwrite

**Location**: `sensor.py` lines 793-794  
**Commit**: fd6893b  
**Impact**: 47 sensors created with `device_info=None`

#### Problem
```python
# WRONG: hasattr() returns True even when value is None
if hasattr(newdescr, "_energy_dashboard_device_info"):
    device_info = newdescr._energy_dashboard_device_info  # Could be None!
```

The code checked if the attribute *exists*, not if it has a valid *value*. When `_energy_dashboard_device_info` was `None` (the default for most sensors), it overwrote the valid `device_info` parameter passed to the function.

#### Fix
```python
# CORRECT: Check both existence AND non-None value
if hasattr(newdescr, "_energy_dashboard_device_info") and newdescr._energy_dashboard_device_info is not None:
    device_info = newdescr._energy_dashboard_device_info
```

#### Regression Test
`test_energy_dashboard_device_info_none_check()` verifies the None check is present in the code pattern.

---

### Bug 2: Deferred Setup Indentation

**Location**: `__init__.py` lines 685-693  
**Commit**: f35fb5b  
**Impact**: 174 sensors on slave hubs had `device_info=None`

#### Problem
```python
# WRONG: device_info assignment was INSIDE the if block due to incorrect indentation
if self.inverterNameSuffix:
    plugin_name = plugin_name + " " + self.inverterNameSuffix
self.device_info = DeviceInfo(...)  # <-- Indented to be INSIDE if block!
```

If a hub had no `inverterNameSuffix` and went through deferred setup (common for slave hubs like EV chargers, meters), the `device_info` assignment was skipped entirely, leaving it as `None`.

#### Fix
```python
# CORRECT: device_info assignment is OUTSIDE the if block
if self.inverterNameSuffix:
    plugin_name = plugin_name + " " + self.inverterNameSuffix
self.device_info = DeviceInfo(...)  # <-- Properly outdented
```

#### Regression Tests
- `test_deferred_setup_device_info_indentation()` - Verifies correct indentation pattern
- `test_initial_setup_device_info_pattern()` - Ensures both setup paths remain consistent

---

### Bug 3: Computed Sensor Registration

**Location**: `sensor.py`, `number.py`, `select.py`, `switch.py`  
**Commit**: 56e0d5a  
**Impact**: Prevented crashes for 100+ computed/internal sensors

#### Problem
```python
# WRONG: All sensors attempted to register with hub, even computed ones
async def async_added_to_hass(self) -> None:
    await self._hub.async_add_solax_modbus_sensor(self)
```

Computed/internal sensors (those with `register < 0`) don't have actual Modbus registers and were never meant to participate in the hub's polling cycle. When they attempted to register, they triggered crashes trying to access `device_info` that didn't exist for their use case.

#### Fix
```python
# CORRECT: Computed sensors skip registration
async def async_added_to_hass(self) -> None:
    # Skip hub registration for computed/internal sensors
    if self.entity_description.register < 0:
        return
    await self._hub.async_add_solax_modbus_sensor(self)
```

Applied to: `SolaXModbusSensor`, `SolaXModbusNumber`, `SolaXModbusSelect`, `SolaXModbusSwitch`

**Note**: `RiemannSumEnergySensor` is intentionally exempt - it's a legitimate sensor that integrates power data and needs hub registration.

#### Regression Test
`test_computed_sensor_registration_check()` verifies all base platform classes have the register check before calling `async_add_solax_modbus_sensor()`.

---

## Regression Test Suite

**File**: `tests/unit/test_phase_d_regressions.py`  
**Tests**: 7 new tests  
**Total Suite**: 262 tests (255 original + 7 new)  
**Status**: All passing ✅

### Test Classes

1. **TestDeviceInfoBugs** - Core bug validation
   - `test_energy_dashboard_device_info_none_check()`
   - `test_deferred_setup_device_info_indentation()`
   - `test_computed_sensor_registration_check()`

2. **TestDeviceInfoInitializationPattern** - Pattern consistency
   - `test_initial_setup_device_info_pattern()`

3. **TestSensorEntityListSingleFunction** - Parameter flow validation
   - `test_device_info_parameter_not_lost()`

4. **TestDeviceInfoRuntimeBehavior** - Runtime behavior
   - `test_sensor_with_none_energy_dashboard_device_info()`
   - `test_deferred_setup_without_suffix_creates_device_info()`

### Running the Tests

```bash
# Run Phase D regression tests only
uv run pytest tests/unit/test_phase_d_regressions.py -v

# Run full test suite
uv run pytest tests/ -v
```

---

## Impact Summary

### Before Fixes
- **300+ runtime errors** on system startup
- TypeError: 'NoneType' object is not subscriptable
- AttributeError: 'NoneType' object has no attribute 'register'
- ValueError: Sensor X has no device_info
- All slave hubs non-functional
- Energy Dashboard sensors broken

### After Fixes
- **Zero runtime errors** ✅
- All 8 hubs operational (3 inverters + 4 EV chargers + 1 meter)
- All 1000+ entities created successfully
- Normal data collection and polling working
- Integration loads cleanly on restart

---

## Key Lessons Learned

1. **Integration Reload vs. Code Reload**
   - `ha-api --reload-integration` does NOT reload Python code
   - Only `ha core restart` recompiles Python modules
   - Always use full restart when testing code changes

2. **Defensive Coding Patterns**
   - Check both attribute existence AND non-None values
   - Be cautious with hasattr() - it returns True even when value is None
   - Validate indentation carefully in Python, especially in conditionals

3. **Architecture Understanding**
   - Computed sensors (register < 0) are architectural constructs
   - They don't participate in Modbus polling
   - They shouldn't attempt hub registration

4. **Test Coverage Importance**
   - Regression tests prevent reintroduction of fixed bugs
   - Pattern-based tests catch structural issues
   - Runtime tests validate actual behavior

---

## References

- Phase 4 Issue: #262.14.29
- Commits: fd6893b, f35fb5b, 56e0d5a, 9f96ee5
- Test File: `tests/unit/test_phase_d_regressions.py`
- Related: Phase C regression tests (`test_phase_c_regressions.py`)
