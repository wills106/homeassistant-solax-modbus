# Performance Testing Guide

Quick guide for measuring performance overhead of integration code changes.

## Measuring Function Call Overhead

### 1. Add Performance Tracking

**Location:** Where you want to measure (e.g., in `treat_address()`)

```python
import time

# Before code to measure
t0 = time.perf_counter()

# Code being measured
if self._validate_register_func is not None:
    val = self._validate_register_func(descr, val, data)

# After code
elapsed_us = (time.perf_counter() - t0) * 1_000_000  # Convert to µs

# Aggregate stats
if not hasattr(self, '_perf_stats'):
    self._perf_stats = {"calls": 0, "total_us": 0}

self._perf_stats["calls"] += 1
self._perf_stats["total_us"] += elapsed_us

# Log every 100 calls
if self._perf_stats["calls"] % 100 == 0:
    avg = self._perf_stats["total_us"] / self._perf_stats["calls"]
    _LOGGER.warning(f"[PERF] {self._perf_stats['calls']} calls, avg {avg:.3f} µs/call")
```

### 2. Use Appropriate Log Level

**Important:** Use whatever logging level is already active in `configuration.yaml` to minimize config changes:
- If module is at `warning`: Use `_LOGGER.warning()`
- If module is at `info`: Use `_LOGGER.info()`
- If module is at `debug`: Use `_LOGGER.debug()`

**Why:** The performance tracking code MUST be removed before committing (the measurement overhead itself is significant - adds ~1-2 µs per call). Minimizing configuration.yaml changes during testing makes cleanup easier.

Example for warning level (no config change needed):
```python
_LOGGER.warning(f"[PERF] {calls} calls, avg {avg:.3f} µs/call")
```

### 3. Restart and Monitor

```bash
ha core restart
sleep 30
ha core logs | grep "\[PERF\]"
```

### 4. Analyze Results

Look for:
- Average µs per call
- Consistency across measurements
- Breakdown by sensor type if tracking multiple categories

### 5. Remove Tracking Code

After collecting data, remove all performance tracking code - keep only the optimizations.

## Example Results

```
[PERF] 100 calls, avg 0.540 µs/call
[PERF] 200 calls, avg 0.616 µs/call
[PERF] 1000 calls, avg 0.921 µs/call
```

**Interpretation:**
- Each call takes ~0.9-1.0 µs
- Overhead stabilizes around 1000 calls
- Compare before/after optimization to measure improvement

## Common Optimizations

### Function Caching (30% improvement)

**Before:**
```python
if hasattr(self.plugin_module, 'validate_register_data'):
    val = self.plugin_module.validate_register_data(descr, val, data)
```

**After:**
```python
# In __init__:
self._validate_func = getattr(plugin, 'validate_register_data', None)

# In hot path:
if self._validate_func is not None:
    val = self._validate_func(descr, val, data)
```

**Savings:** Eliminates per-call `hasattr()` and attribute lookup (~0.3 µs per call)

## Performance Context

**Integration overhead should be << Modbus I/O:**
- Modbus read: 10-50 milliseconds (network)
- Validation: < 1 µs (CPU)
- Ratio: 0.001-0.01% overhead

Anything under 1 µs per sensor is excellent.

