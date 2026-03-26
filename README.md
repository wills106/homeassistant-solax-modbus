TimeV3.3

Merged updated Main branch back into TimeV3
CI-CD failed, so asked Roo to fix, got the following outcome:

Task Completed

I've fixed all the pre-commit errors in the homeassistant-solax-modbus project:

Summary of Changes
1. README.md - Fixed codespell errors
2. init.py - Fixed mypy and ruff errors
Removed unused import from time import time (line 12)
Removed unused # type: ignore[attr-defined] comments
Removed unused # type: ignore[unreachable] comments
Fixed async_add_solax_modbus_sensor and async_remove_solax_modbus_sensor parameter types
Added # type: ignore[misc] to get_core_hub fallback function
3. const.py - Fixed mypy errors
Added # type: ignore[misc] to all base entity description classes:
BaseModbusSensorEntityDescription
BaseModbusButtonEntityDescription
BaseModbusSelectEntityDescription
BaseModbusSwitchEntityDescription
BaseModbusTimeEntityDescription
BaseModbusNumberEntityDescription
4. time.py - Fixed mypy errors
Added from typing import Any import
Added type annotations to async_setup_entry and __init__ methods
Added # type: ignore[misc] to @callback decorator
Fixed async_set_value to return None explicitly
5. switch.py, select.py, number.py, button.py, sensor.py - Fixed mypy errors
Added # type: ignore[misc] to entity classes
Added # type: ignore[misc] to @callback decorators
Removed unused # type: ignore[assignment] comments
Added # type: ignore[call-arg] to replace() calls in sensor.py
6. config_flow.py - Fixed mypy errors
Removed unused # type: ignore[comparison-overlap] comment
Added # type: ignore[misc, call-arg] to ConfigFlowHandler class
7. energy_dashboard.py - Fixed mypy errors
Re-added necessary # type: ignore[arg-type] and # type: ignore[typeddict-item] comments for DeviceInfo
Added # type: ignore[misc] to @callback decorators
8. pymodbus_compat.py - Fixed mypy errors
Removed unused # type: ignore[misc] comment
9. Plugin files - Fixed mypy errors (all plugin_*.py files)
Removed unused # type: ignore[attr-defined] comments from imports
Added TIME_TYPES=[] parameter to plugin instance calls where missing
All pre-commit errors have been resolved. The codebase now passes mypy, ruff, and codespell checks.

------

TimeV3.2

Removed unneeded value_function:, autorepeat:, depends_on:, sensor_key: from "class BaseModbusTimeEntityDescription(TimeEntityDescription):" in const.py

Also updated time.py code relating to these unused functions

------

TimeV3.1

Backup charge now working for GEN3 SolaX Hybrid.
Writing the hours on one register and the mins are on the following register now working.

Added GEN2:

- Time "Discharge Start 1"
- Time "Discharge End 1"
- Time "Discharge Start 2"
- Time "Discharge End 2"

Added GEN2/3:

- Time "Charge Start 1"
- Time "Charge End 1"
- Time "Charge Start 2"
- Time "Charge End 2"

Removed GEN2:

- Select Select "Discharger Start Time 1"
- Select Select "Discharger End Time 1"
- Select Select "Discharger Start Time 2"
- Select Select "Discharger End Time 2"

Removed GEN2/3:

- Number "Backup Charge Start Hours"
- Number "Backup Charge Start Minutes"
- Number "Backup Charge End Hours"
- Number "Backup Charge End Minutes"

- Select "Charger Start Time 1"
- Select "Charger End Time 1"
- Select "Charger Start Time 2"
- Select "Charger End Time 2"

- Sensor "Backup Charge Start"
- Sensor "Backup Charge End"

There will be a number of entities with the following error:
"This entity is no longer being provided by the solax_modbus integration. If the entity is no longer in use, delete it in settings."

So either delete them, or remove the Integration and add it back in, if you name the Integration exactly the same then the history will load back in.

GEN3 Should return 102 entities without EPS enabled.

For GEN4-6 it would make sense to shorten the time names to match GEN2/3.

------

TimeV3.0

Moved to Qwen3.5:27b with 104K Context, to reduce VRAM

For TimeV3 I now have working time values displayed for time.solax_charger_end_time1 etc
I have removed the selects for GEN2 / GEN3 SolaX Inverters
I have left in the GEN4-6 Selects as I don't have the means to test them

TIME_OPTIONS & TIME_OPTIONS_GEN4 need reworking to allow you to set time for every minute, currently it's still set in 5min blocks

I also haven't looked into key="backup_charge_end_h", for the GEN3 yet, where you read / write the hours on one register and the mins are on separate hours. This register set doesn't use high8 & low8

------

- From Branch time, Line numbers probably don't corolate to what they are in this branch.

I have been working on time.py again, to replace these drop down selects.
I was getting the below error, so for the first time I have been trying to use Roo Code and Qwen3.5:35b
So I asked it the following: 

------

When Home Assistant starts I am getting the following error, can you suggest a way to fix the error:

Traceback (most recent call last):
  File "/config/custom_components/solax_modbus/__init__.py", line 1292, in async_read_modbus_data
    res = await self.async_read_modbus_registers_all(group)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/config/custom_components/solax_modbus/__init__.py", line 1566, in async_read_modbus_registers_all
    self.last_ts = time()
                   ~~~~^^
TypeError: 'module' object is not callable

------

Recommendation
Replace all occurrences of time() with _mtime.time() in the __init__.py file. This is already done correctly in other parts of the code (e.g., line 833 uses _mtime.monotonic()).

Locations to fix:

Line 965: if time() - last_refresh_ts < 5:
Line 977: hub_entry["energy_dashboard_last_refresh_ts"] = time()
Line 1372: if (self.tmpdata_expiry.get(descr.key, 0) > time()):
Line 1566: self.last_ts = time()
This fix ensures that the time module is always accessed via its alias _mtime, preventing shadowing issues from dictionary keys named "time".

------

I also asked it, if it would have an impact on any of the other files...

------

Based on my analysis of the files, no changes are required in the plugin_*.py files, button.py, select.py, sensor.py, switch.py, time.py, or number.py. Here's why:

Analysis of Each File
button.py (line 2): from time import time - Uses time() at line 108. This file is a separate module with its own namespace, so the time function imported here is not affected by dictionary keys in __init__.py.

select.py (line 2): from time import time - Uses time() at line 145. Same as above - separate module namespace.

sensor.py (line 2): import time - Uses time.time() at lines 322, 350, 641. This uses the module reference time.time(), not the bare time() function, so it's safe.

switch.py - Does not use time() at all. Uses datetime.now() instead.

time.py (line 3): from time import time - Uses time() at line 170. Same as above - separate module namespace.

number.py (line 3): from time import time - Uses time() at lines 161 and 229. Same as above - separate module namespace.

plugin_*.py files - These files import from time import time and use time() in their value functions. Each plugin file has its own module namespace, so they are not affected by dictionary keys in __init__.py.

Why No Changes Are Needed
The shadowing issue only occurs in __init__.py because:

The from time import time import at the module level makes time available as a global name
The self.data dictionary in the hub can contain a key named "time" (from time entities)
When code in __init__.py tries to call time(), it's actually trying to call a dictionary entry
Each of the other files (button.py, select.py, sensor.py, switch.py, time.py, number.py, and plugin_*.py) has its own module namespace. The time function imported in those files is not affected by dictionary keys in __init__.py's hub data.

The fix I applied to __init__.py is sufficient to resolve the error.


Task Completed
No changes are required in the plugin_*.py files, button.py, select.py, sensor.py, switch.py, time.py, or number.py.

Reason
Each of these files has its own module namespace. The time function imported in those files (e.g., from time import time) is not affected by dictionary keys in __init__.py's hub data because:

button.py, select.py, time.py, number.py: These use from time import time and call time() directly. They have their own module namespace, so the imported time function is not shadowed by dictionary keys.

sensor.py: Uses import time and calls time.time(). This uses the module reference, not the bare function, so it's safe.

switch.py: Does not use time() at all; uses datetime.now() instead.

plugin_*.py files: Each plugin file has its own module namespace with its own from time import time import. The time function in these files is not affected by dictionary keys in __init__.py.

The fix applied to __init__.py (replacing time() with _mtime.time()) is sufficient to resolve the error because the shadowing issue only occurs in __init__.py where the hub's self.data dictionary can contain a key named "time" that shadows the imported time function.

------

As I don't have a GEN4 or later SolaX Inverter I can't test out any of the auto repeat stuff.

So far time.solax_charger_end_time_1 for GEN3 Inverter will successfully write the time to the Inverter. But if I put 5:20, it will write 05:00 and then 05:20 after. Might need to put a write delay in so you can update both half's of the time? Unless it's best to use a service call / automation to set it as 5:20 in one go.

I can't get time.solax_charger_end_time_1 to display the value from the Internal sensor with the key solax_charger_end_time_1

Initially Roo Code / Qwen was trying to change the time register to match the sensor register, but I managed to explain that read and write are on different registers.
It went off to try and put extra parsing in const.py for value_function_gen23time and value_function_gen4time
But I think the issue is the linking is missing. As I keep running out of context size (I think) I have left it at this stage, as I can't fit anymore GPU's in the server...
The quality of my prompting probably isn't helping.