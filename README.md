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

I also asked it, if it would have an inpact on any of the other files...

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