# Plugin Typing Guide for SolaX Modbus Integration

## Overview

This guide establishes typing patterns for SolaX Modbus plugin modules based on the reference implementation in `plugin_solax.py`. Use these patterns when adding type hints to other plugin files during Phase 3 of the mypy implementation.

**Goal**: Establish consistent type annotations across all 17 plugin modules without fixing architectural issues (deferred to Phase 4).

## Quick Reference

### Common Type Imports

```python
from typing import Any
```

### Function Signature Patterns

```python
# Value functions (compute/transform sensor values)
def value_function_name(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:
def value_function_name(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:
def value_function_name(initval: int, descr: Any, datadict: dict[str, Any]) -> Any:

# Autorepeat functions (button loops with Modbus writes)
def autorepeat_function_name(
    initval: int, descr: Any, datadict: dict[str, Any]
) -> dict[str, Any]:

# Validation functions
def validate_register_data(descr: Any, value: Any, datadict: dict[str, Any]) -> Any:
```

## Type Annotation Patterns

### 1. Value Functions

Value functions transform or compute sensor values from raw Modbus data. They always follow this signature:

```python
def value_function_name(initval: int, descr: Any, datadict: dict[str, Any]) -> ReturnType:
    """Docstring describing the transformation."""
    # Implementation
```

**Return Type Selection:**

- **`int | float`**: Numeric calculations (power, current, voltage, percentages)
  ```python
  def value_function_battery_power_charge(
      initval: int, descr: Any, datadict: dict[str, Any]
  ) -> int | float:
      battery_power = datadict.get("battery_power", 0)
      return abs(battery_power) if battery_power < 0 else 0
  ```

- **`str | None`**: Version strings, formatted text
  ```python
  def value_function_software_version_g4(
      initval: int, descr: Any, datadict: dict[str, Any]
  ) -> str | None:
      if initval is None:
          return None
      return f"{(initval >> 12) & 0xF}.{(initval >> 8) & 0xF}.{initval & 0xFF:02d}"
  ```

- **`Any`**: Complex transformations, mixed types, serial number processing
  ```python
  def value_function_byteswapserial(
      initval: int, descr: Any, datadict: dict[str, Any]
  ) -> Any:
      """Swap bytes in serial number for correct display."""
      return ((initval & 0xFF) << 8) | ((initval >> 8) & 0xFF)
  ```

### 2. Autorepeat Functions

Autorepeat functions implement button loops with repeated Modbus writes. They always return a dictionary with action/data:

```python
def autorepeat_function_name(
    initval: int, descr: Any, datadict: dict[str, Any]
) -> dict[str, Any]:
    """Docstring describing the loop behavior.
    
    Args:
        initval: BUTTONREPEAT_FIRST (first run), BUTTONREPEAT_LOOP (subsequent),
                or BUTTONREPEAT_POST (cleanup)
        descr: Entity description
        datadict: Current sensor data dictionary
    
    Returns:
        Dictionary with action and data for Modbus write operations
    """
    if initval == BUTTONREPEAT_POST:
        # Cleanup action
        return {"action": WRITE_MULTI_MODBUS, "data": []}
    
    # Main logic
    return {"action": WRITE_MULTI_MODBUS, "data": [...]}
```

**Examples:**

```python
def autorepeat_function_remotecontrol_recompute(
    initval: int, descr: Any, datadict: dict[str, Any]
) -> dict[str, Any]:
    """Remote control power calculations for SolaX inverters."""
    # ... implementation
    return {"action": WRITE_MULTI_MODBUS, "data": writes}

def autorepeat_bms_charge(
    datadict: dict[str, Any], battery_capacity: float, max_charge_soc: float, available: float
) -> dict[str, Any]:
    """BMS charge calculations (custom signature for BMS-specific logic)."""
    # ... implementation
    return {"action": WRITE_MULTI_MODBUS, "data": writes}
```

### 3. Validation Functions

Validation functions check register data for corruption patterns:

```python
def validate_register_data(descr: Any, value: Any, datadict: dict[str, Any]) -> Any:
    """Validate register values for corruption.
    
    - PM U32 sensors: detect 0xFFFFFF00 overflow pattern
    - battery_capacity: treat zero SoC as invalid
    """
    # Validation logic
    return value  # or corrected value
```

## Common Patterns and Pitfalls

### ✅ DO: Use `Any` for Complex or Uncertain Types

When dealing with:
- Entity descriptions (`descr: Any`)
- Mixed-type dictionaries (`datadict: dict[str, Any]`)
- Complex transformations where exact type is unclear

**Why**: Phase 3 focuses on establishing patterns, not solving architectural issues. `Any` acknowledges complexity and defers detailed typing to Phase 4.

### ✅ DO: Match Return Types to Function Behavior

```python
# Good: Specific return type for numeric calculation
def value_function_house_load(
    initval: int, descr: Any, datadict: dict[str, Any]
) -> int | float:
    inverter = datadict.get("inverter_power", 0)
    measured = datadict.get("measured_power", 0)
    return inverter - measured

# Good: Any for complex serial processing
def value_function_byteswapserial(
    initval: int, descr: Any, datadict: dict[str, Any]
) -> Any:
    return ((initval & 0xFF) << 8) | ((initval >> 8) & 0xFF)
```

### ❌ DON'T: Try to Fix Architectural Issues

```python
# DON'T try to type entity descriptions in detail (Phase 4 issue)
def value_function_example(
    initval: int,
    descr: BaseModbusSensorEntityDescription,  # ❌ Too specific for Phase 3
    datadict: dict[str, Any]
) -> int:
    ...

# DO use Any for now
def value_function_example(
    initval: int,
    descr: Any,  # ✅ Acknowledge complexity, defer to Phase 4
    datadict: dict[str, Any]
) -> int:
    ...
```

### ❌ DON'T: Add Type Hints to Entity Descriptions Yet

Entity descriptions (e.g., `SENSOR_TYPES`, `BUTTON_TYPES`) will reveal many architectural issues when typed. These are tracked for Phase 4:

```python
# Phase 3: Leave untyped for now
SENSOR_TYPES = [
    SolaxModbusSensorEntityDescription(
        key="battery_voltage",
        # ... many fields, some with type mismatches
    ),
]

# Phase 4: Will address:
# - unit vs register_type confusion (192 errors in plugin_solax)
# - Non-frozen dataclass inheritance
# - Missing/incorrect type annotations
```

## Known Issues (Tracked for Phase 4)

### 1. Unit/Register Type Confusion (192 errors in plugin_solax)

**Issue**: Entity descriptions use `unit=REGISTER_S32` instead of proper unit enums.

```python
# Current (wrong but common pattern)
BaseModbusNumberEntityDescription(
    key="charge_max_current",
    unit=REGISTER_S32,  # ❌ String register type
    # ...
)

# Should be (Phase 4 fix)
BaseModbusNumberEntityDescription(
    key="charge_max_current",
    unit=UnitOfElectricCurrent.AMPERE,  # ✅ Proper unit enum
    register_type=REGISTER_S32,  # Separate field
    # ...
)
```

**Impact**: 72% of mypy errors in typed plugins (192/267 in plugin_solax.py)  
**Resolution**: Phase 4 will add `register_type` field and fix all entity descriptions

### 2. Non-Frozen Dataclass Inheritance (5 errors)

**Issue**: `BaseModbus*EntityDescription` classes inherit from frozen Home Assistant base classes but are not frozen themselves.

**Resolution**: Phase 4 architectural decision (add `frozen=True` or restructure)

### 3. Global Variable Typing (4 errors)

**Issue**: Module-level state variables lack type annotations.

```python
# Current
_pm_last_known_values = {}
_soc_last_known_values = {}

# Phase 4
_pm_last_known_values: dict[str, int | float] = {}
_soc_last_known_values: dict[str, float] = {}
```

## Typing Workflow for Plugin Batches

When typing additional plugins (tasks #262.13.4 through #262.13.7):

### 1. Add Type Import

```python
from typing import Any
```

### 2. Type Value Functions (Batch Operation)

Use `sed` for efficient batch typing:

```bash
# Numeric value functions
for func in value_function_house_load value_function_battery_power; do
    sed -i "s/^def ${func}(initval, descr, datadict):/def ${func}(initval: int, descr: Any, datadict: dict[str, Any]) -> int | float:/" plugin_*.py
done

# Version/string functions
for func in value_function_firmware_version value_function_serial; do
    sed -i "s/^def ${func}(initval, descr, datadict):/def ${func}(initval: int, descr: Any, datadict: dict[str, Any]) -> str | None:/" plugin_*.py
done
```

### 3. Type Autorepeat Functions Manually

Autorepeat functions often have unique logic and should be reviewed individually:

```python
def autorepeat_function_name(
    initval: int, descr: Any, datadict: dict[str, Any]
) -> dict[str, Any]:
    # Review implementation to confirm return type
```

### 4. Run Tests After Each Batch

```bash
# Full test suite
uv run pytest tests/ -v

# Check mypy baseline (expect stable or slight increase)
uv run mypy custom_components/solax_modbus | grep "Found"

# Verify specific plugin
uv run mypy custom_components/solax_modbus/plugin_xxx.py | grep "Found"
```

### 5. Commit Progress

```bash
git add custom_components/solax_modbus/plugin_*.py
git commit -m "backend: Add type hints to plugin batch N (task#262.13.X)"
```

## Plugin Batch Strategy (Phase 3 Tasks)

### Batch 1: Small Plugins (#262.13.4)
- `plugin_sofar_old.py`
- `plugin_swatten.py`
- `plugin_qcells.py`
- `plugin_sofar.py`

**Strategy**: Few functions, straightforward typing

### Batch 2: Medium Plugins (#262.13.5)
- `plugin_alphaess.py`
- `plugin_solinteg.py`

**Strategy**: More entity descriptions, validate pattern consistency

### Batch 3: Large Plugins (#262.13.6)
- `plugin_growatt.py`
- `plugin_solis.py`

**Strategy**: Many value functions, use batch `sed` operations

### Batch 4: Special Cases (#262.13.7)
- `plugin_ev_charger.py`
- `plugin_lv.py`

**Strategy**: Unique architectures, manual review required

## Success Criteria

For each plugin typing task:

1. ✅ All value functions have type hints
2. ✅ All autorepeat functions have type hints
3. ✅ Test suite passes (255 tests)
4. ✅ mypy error count stable or slight increase (architectural issues revealed)
5. ✅ No new runtime errors introduced

## References

- **Reference Plugin**: `custom_components/solax_modbus/plugin_solax.py`
- **Protocol Definition**: `custom_components/solax_modbus/protocols.py`
- **Phase 3 Design**: `docs/solax/mypy-type-checking-design.md` (Section 3)
- **Entity Base Classes**: `custom_components/solax_modbus/const.py`

---

**Last Updated**: 2026-02-06  
**Phase**: 3 (Plugin Typing)  
**Status**: Active reference for tasks #262.13.4 through #262.13.7
