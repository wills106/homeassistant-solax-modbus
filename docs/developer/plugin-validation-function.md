# Plugin Validation Function - Implementation Guide

**Author:** fxstein  
**Date:** October 29, 2025  
**Context:** PR #1690 - U32 Register Overflow Detection  
**GitHub Discussion:** https://github.com/wills106/homeassistant-solax-modbus/pull/1690

## Overview

Simple plugin-level validation function to handle U32 overflow in PM sensors. **28 lines total** (26 plugin + 2 framework).

## The Solution

Add one optional function to the plugin that validates ALL register values. Framework calls it if present.

**Code:** 28 lines total  
**Reduction:** 80% (from 138 lines current implementation)

## Implementation

### 1. Framework Hook (__init__.py)

**Location:** In `treat_address()`, after `convert_from_registers()`, before scaling

```python
# Plugin-level validation hook
if hasattr(self.plugin, 'validate_register_data'):
    val = self.plugin.validate_register_data(descr, val, datadict)
```

**Lines:** 2

### 2. Plugin Validation Function (plugin_solax.py)

**Location:** Near top of file, after imports

```python
# ============================================================================
# Plugin-Level Register Validation
# ============================================================================

# Global storage for last known good values
_pm_last_known_values = {}

def validate_register_data(descr, value, datadict):
    """
    Validate PM U32 sensors for overflow corruption.
    
    Detects 0xFFFFFF00 pattern from uninitialized slave registers and
    returns the last known good value.
    """
    global _pm_last_known_values
    
    # PM U32 sensors only (filter by key prefix)
    if descr.key.startswith("pm_") and descr.unit == REGISTER_U32:
        # Handle None from core errors
        if value is None:
            last_value = _pm_last_known_values.get(descr.key, 0)
            _LOGGER.warning(f"PM sensor {descr.key} received None -> using last: {last_value}W")
            return last_value
        
        # Handle U32 overflow pattern
        if value >= 0xFFFFFF00:
            last_value = _pm_last_known_values.get(descr.key, 0)
            _LOGGER.warning(f"PM U32 overflow {descr.key}: 0x{value:08X} -> using last: {last_value}W")
            return last_value
        
        # Store valid values for future use
        _pm_last_known_values[descr.key] = value
    
    return value
```

**Lines:** 26

## How It Works

### Data Flow

```
1. Raw Registers (0xFFFF 0xFF00)
2. Convert to U32 (0xFFFFFF00)
3. validate_register_data() ← Validation here
   - If overflow: Return last known value
   - If valid: Store and return value
4. Apply scaling
5. Update entity
```

### PM Filtering

The function only validates sensors where:
- ✅ Key starts with `pm_` (PM sensors)
- ✅ Unit is `REGISTER_U32` (32-bit unsigned)
- ✅ Value is overflow pattern (≥ 0xFFFFFF00)

All other sensors pass through unchanged.

### Last Known Value Logic

- **Valid value received**: Store in `_pm_last_known_values[key]`
- **Overflow detected**: Return `_pm_last_known_values.get(key, 0)`
- **No previous value**: Return `0` as safe fallback

## Complete Code Example

**plugin_solax.py:**
```python
_pm_last_known_values = {}

def validate_register_data(descr, value, datadict):
    """Validate PM U32 sensors for overflow."""
    global _pm_last_known_values
    
    if descr.key.startswith("pm_") and descr.unit == REGISTER_U32:
        if value is None:
            last = _pm_last_known_values.get(descr.key, 0)
            _LOGGER.warning(f"PM {descr.key} None -> {last}W")
            return last
        
        if value >= 0xFFFFFF00:
            last = _pm_last_known_values.get(descr.key, 0)
            _LOGGER.warning(f"PM {descr.key} overflow 0x{value:08X} -> {last}W")
            return last
        
        _pm_last_known_values[descr.key] = value
    
    return value
```

**__init__.py (in treat_address()):**
```python
if hasattr(self.plugin, 'validate_register_data'):
    val = self.plugin.validate_register_data(descr, val, datadict)
```

**Total: 21 lines** (minimal version with logging)

## Implementation Checklist

- [ ] Add framework hook in `treat_address()` (__init__.py, 2 lines)
- [ ] Add `_pm_last_known_values = {}` to plugin_solax.py
- [ ] Add `validate_register_data()` function to plugin_solax.py (26 lines)
- [ ] Test with PM sensors during overflow conditions
- [ ] Remove current raw/computed sensor implementation
- [ ] Remove `value_function_pm_overflow_protection` function
- [ ] Update PR description

## Testing

**Test 1: Normal value**
- Input: `pm_pv_power_1 = 1500W`
- Output: `1500W`
- Stored: `_pm_last_known_values["pm_pv_power_1"] = 1500`

**Test 2: Overflow with previous value**
- Input: `pm_pv_power_1 = 0xFFFFFF00`
- Output: `1500W` (last known)
- Logged: Warning about overflow

**Test 3: Overflow without previous value**
- Input: `pm_pv_power_2 = 0xFFFFFF00` (first read)
- Output: `0W` (safe fallback)
- Logged: Warning about overflow

**Test 4: Non-PM U32 sensor**
- Input: `total_energy = 0xFFFFFF00`
- Output: `0xFFFFFF00` (passes through, not PM)
- No validation applied

## Why This Approach

### vs Current Implementation (138 lines)
- ✅ 80% code reduction
- ✅ No raw/computed sensor duplication
- ✅ Single function handles all PM sensors

### vs Per-Entity validate_data (57-87 lines)
- ✅ 50-67% fewer lines
- ✅ No per-entity overhead
- ✅ Same functionality

### vs Original __init__.py (5 lines)
- ✅ Framework stays generic
- ✅ Addresses @infradom's architectural concerns
- ✅ Only 23 more lines for proper architecture

**Best balance:** Simple implementation + architectural purity

## References

- **PR #1690**: https://github.com/wills106/homeassistant-solax-modbus/pull/1690
- **@infradom's feedback**: Keep Solax-specific code out of __init__.py
- **Alternative**: Per-entity validate_data attribute (more code, more flexibility)

