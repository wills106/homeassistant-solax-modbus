# Coding Standards

Development standards and best practices for the SolaX Modbus integration.

## Code Style

### Automated Formatting

**All code is automatically formatted** - you don't need to worry about style!

- **Black**: Formats Python code automatically (180-char line length)
- **Flake8**: Checks code style (lenient configuration)
- **codespell**: Fixes spelling errors

**Tools run automatically:**
- GitHub Actions on every push/PR (informational)
- Pre-commit hooks available (optional)
- Manual scripts: `./scripts/lint.sh` and `./scripts/format.sh`

### Line Length

**180 characters** - Preserves readability for complex code

### Python Style

Following Black's formatting with lenient Flake8 rules:
- 4-space indentation
- Star imports allowed (common pattern in this codebase)
- Lambda expressions allowed (used for factory functions)
- Existing patterns respected (bare except, None comparisons)

**Don't worry about style** - Black handles it automatically!

## Code Organization

### Framework vs Plugin Code

**Critical principle:** Keep framework generic, plugin-specific code in plugins

- **Framework** (`__init__.py`): Generic integration logic, no inverter-specific code
- **Plugins** (`plugin_*.py`): Inverter-specific logic, entity definitions, calculations

**Example:**
```python
# ❌ Bad: Inverter-specific logic in __init__.py
if inverter_brand == "SolaX":
    # SolaX-specific code

# ✅ Good: Plugin-level function in plugin_solax.py
def validate_register_data(descr, value, datadict):
    # SolaX-specific validation
```

### Plugin-Level Functions

Use plugin-level functions for inverter-specific logic:

```python
# In plugin_*.py
def validate_register_data(descr, value, datadict):
    """Plugin-level validation called by framework."""
    # Your inverter-specific validation
    return value

# Framework calls this via:
# if hasattr(self.plugin_module, 'validate_register_data'):
#     val = self.plugin_module.validate_register_data(...)
```

## Performance Considerations

### Measure Before Optimizing

Use performance tracking when optimizing hot paths:

```python
import time
t0 = time.perf_counter()
# Code to measure
elapsed_us = (time.perf_counter() - t0) * 1_000_000
```

See: [performance-testing.md](performance-testing.md)

**Remember:** Remove tracking code before committing!

### Optimization Guidelines

- **< 1 µs per sensor:** Excellent
- **Cache function references:** Eliminates hasattr() overhead (30% improvement)
- **Avoid network calls in hot paths:** Modbus I/O is 10-50ms, keep processing < 1ms

## Documentation Standards

### Code Comments

**When to comment:**
- ✅ Complex algorithms (explain the "why")
- ✅ Non-obvious behavior
- ✅ Workarounds for bugs
- ✅ Performance-critical sections

**When NOT to comment:**
- ❌ Obvious code (comment adds no value)
- ❌ Explaining "what" (code should be self-explanatory)

**Example:**
```python
# ✅ Good: Explains why
# Use grid-to-battery only (not total battery power) to correctly calculate house load
battery_power = datadict.get("pm_battery_power_charge", 0)

# ❌ Bad: Explains what (obvious from code)
# Get battery power from datadict
battery_power = datadict.get("pm_battery_power_charge", 0)
```

### Docstrings

**Required for:**
- ✅ Public functions
- ✅ Complex internal functions
- ✅ Plugin interface functions

**Format:**
```python
def validate_register_data(descr, value, datadict):
    """
    Validate register values before processing.
    
    Args:
        descr: Entity descriptor
        value: Raw numeric value
        datadict: Current sensor data
        
    Returns:
        Validated value or safe fallback
    """
```

### Developer Documentation

Place in `docs/developer/`:
- Implementation guides
- Design decisions
- Performance analysis
- Migration guides

## Git Workflow

### Branch Naming

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation only
- `refactor/` - Code refactoring

**Examples:**
- `feature/parallel-mode-support`
- `fix/pm-overflow-detection`
- `docs/performance-testing-guide`

### Commit Messages

**Format:**
```
type: Brief description (50 chars)

Detailed explanation of what and why (wrap at 72 chars).

- Bullet points for specific changes
- Keep each point focused

Completes subtask #X.Y
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `chore`

**Examples:**
```
feat: Add parallel mode overflow protection

Implemented plugin-level validation function:
- Detects 0xFFFFFF00 overflow pattern
- Returns last known good value
- 80% code reduction from previous approach

Completes subtask #157.1
```

### Pull Requests

1. **Create draft PR early** - Get feedback during development
2. **Keep scope focused** - One feature/fix per PR
3. **Test thoroughly** - Include test results in PR description
4. **Update documentation** - Document new features
5. **Respond to feedback** - Address review comments promptly

## Testing Guidelines

### Before Committing

**Run locally (optional):**
```bash
./scripts/lint.sh    # Check formatting/style
./scripts/format.sh  # Auto-fix issues
```

**Automated checks:**
- GitHub Actions run automatically on push
- Informational only - won't block your PR

### Integration Testing

**Critical:** Test with real hardware when possible

**Minimum:**
- ✅ Integration loads without errors
- ✅ Sensors update correctly
- ✅ No errors in Home Assistant logs
- ✅ Existing functionality unaffected

**For new features:**
- ✅ Feature works as described
- ✅ Edge cases considered
- ✅ Error handling tested

## Common Patterns

### Sensor Value Functions

```python
def value_function_custom_calculation(initval, descr, datadict):
    """Calculate custom sensor value."""
    value1 = datadict.get("sensor1", 0)
    value2 = datadict.get("sensor2", 0)
    return value1 + value2
```

### Plugin Validation

```python
def validate_register_data(descr, value, datadict):
    """Validate register values."""
    if descr.key.startswith("special_") and value >= 0xFFFFFF00:
        return last_known_value
    return value
```

### Error Handling

```python
try:
    result = risky_operation()
except SpecificException as ex:
    _LOGGER.error(f"Operation failed: {ex}")
    return safe_fallback
```

## Questions?

- Check existing code for patterns
- See [performance-testing.md](performance-testing.md) for optimization
- See [plugin-validation-function.md](plugin-validation-function.md) for plugin patterns
- Ask in PR discussions

## Summary

**Key Principles:**
1. ✅ Automation-first (zero manual overhead)
2. ✅ Framework stays generic
3. ✅ Plugin-specific code in plugins
4. ✅ Performance matters (< 1 µs per sensor)
5. ✅ Test with real hardware
6. ✅ Document complex decisions
7. ✅ Don't block contributions with strict rules

