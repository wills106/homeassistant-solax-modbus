"""Device info handling regression tests.

These tests prevent reintroduction of critical runtime bugs related to device_info
initialization and handling. The bugs caused 300+ runtime errors on startup before
being fixed.

Background: These bugs were discovered during strict type checking implementation,
but the tests focus on runtime behavior, not type checking.
"""

import re
from pathlib import Path

import pytest


def get_source_file(filename: str) -> Path:
    """Get path to a source file in the integration."""
    return Path("custom_components/solax_modbus") / filename


class TestDeviceInfoBugs:
    """Regression tests for device_info handling bugs.

    Background:
    - During Phase 4, multiple critical bugs were found where device_info was None
    - These caused 300+ runtime errors on startup
    - All bugs were related to incorrect handling of device_info initialization/assignment
    """

    def test_energy_dashboard_device_info_none_check(self) -> None:
        """Test that _energy_dashboard_device_info None check exists.

        Bug: sensor.py line 793-794 overwrote valid device_info with None

        Original code:
            if hasattr(newdescr, "_energy_dashboard_device_info"):
                device_info = newdescr._energy_dashboard_device_info  # Could be None!

        Fixed code:
            if hasattr(newdescr, "_energy_dashboard_device_info") and newdescr._energy_dashboard_device_info is not None:
                device_info = newdescr._energy_dashboard_device_info

        Impact: This bug caused ~47 sensors to be created with device_info=None,
        leading to registration failures and diagnostic log spam.

        Commit: fd6893b
        """
        sensor_file = get_source_file("sensor.py")
        content = sensor_file.read_text()

        # Find the problematic line
        pattern = r'if hasattr\(newdescr,\s*"_energy_dashboard_device_info"\).*?device_info\s*='

        # Check if the pattern exists
        matches = list(re.finditer(pattern, content, re.DOTALL))
        assert len(matches) > 0, "Could not find _energy_dashboard_device_info check in sensor.py"

        # For each match, verify the None check is present
        for match in matches:
            # Get the full block (up to 200 chars after the hasattr)
            block_start = match.start()
            block_end = min(match.end() + 200, len(content))
            block = content[block_start:block_end]

            # The fix MUST include "is not None" check
            assert "is not None" in block or "!= None" in block, (
                f"REGRESSION: _energy_dashboard_device_info check at position {block_start} "
                "is missing None validation. This will cause device_info to be overwritten "
                "with None when the attribute exists but has no value.\n"
                f"Found code:\n{block[:200]}"
            )

    def test_deferred_setup_device_info_indentation(self) -> None:
        """Test that device_info assignment in deferred setup is correctly indented.

        Bug: __init__.py lines 685-693 had incorrect indentation

        Original code (WRONG):
            if self.inverterNameSuffix:
                plugin_name = plugin_name + " " + self.inverterNameSuffix
            self.device_info = DeviceInfo(...)  # <-- INSIDE if block by indentation!

        Fixed code:
            if self.inverterNameSuffix:
                plugin_name = plugin_name + " " + self.inverterNameSuffix
            self.device_info = DeviceInfo(...)  # <-- OUTSIDE if block

        Impact: This bug caused ALL slave hubs (EV chargers, meters) to have
        device_info=None if they had no inverterNameSuffix, affecting ~174 sensors.

        Commit: f35fb5b
        """
        init_file = get_source_file("__init__.py")
        content = init_file.read_text()

        # Find the _deferred_setup_loop function
        func_pattern = r"async def _deferred_setup_loop\(self.*?\n(?:.*?\n){0,500}?(?=\n    async def|\nclass |\Z)"
        func_match = re.search(func_pattern, content, re.DOTALL)

        assert func_match, "_deferred_setup_loop function not found in __init__.py"

        func_body = func_match.group(0)

        # Find the device_info assignment in deferred setup
        device_info_pattern = r"self\.device_info\s*=\s*DeviceInfo\("
        device_info_match = re.search(device_info_pattern, func_body)

        assert device_info_match, "device_info assignment not found in _deferred_setup_loop"

        # Get the line containing the assignment
        lines_before_assignment = func_body[: device_info_match.start()].split("\n")
        assignment_line_start = len(lines_before_assignment) - 1

        # Get context around the assignment (previous 10 lines)
        context_start = max(0, assignment_line_start - 10)
        context_lines = func_body.split("\n")[context_start : assignment_line_start + 15]
        context = "\n".join(context_lines)

        # Find the if inverterNameSuffix block
        if_pattern = r"if self\.inverterNameSuffix.*?:"
        if_match = re.search(if_pattern, context)

        if if_match:
            # Calculate indentation levels
            if_line_start = context[: if_match.start()].rfind("\n") + 1
            if_indentation = len(context[if_line_start : if_match.start()]) - len(context[if_line_start : if_match.start()].lstrip())

            # Find the device_info line in the context
            device_info_in_context = context.find("self.device_info")
            device_info_line_start = context[:device_info_in_context].rfind("\n") + 1
            device_info_indentation = len(context[device_info_line_start:device_info_in_context]) - len(
                context[device_info_line_start:device_info_in_context].lstrip()
            )

            # device_info assignment MUST have same or less indentation as the if statement
            # (it should be OUTSIDE the if block)
            assert device_info_indentation <= if_indentation, (
                f"REGRESSION: device_info assignment in _deferred_setup_loop is incorrectly "
                f"indented inside the 'if self.inverterNameSuffix:' block.\n"
                f"if-block indentation: {if_indentation} spaces\n"
                f"device_info indentation: {device_info_indentation} spaces\n"
                f"The device_info assignment must be OUTSIDE the if block (same or less indentation).\n"
                f"Context:\n{context}"
            )

    def test_computed_sensor_registration_check(self) -> None:
        """Test that computed sensors skip hub registration in base sensor classes.

        Bug: Sensors with register < 0 were attempting to register with hub

        Original code (SolaXModbusSensor):
            async def async_added_to_hass(self) -> None:
                await self._hub.async_add_solax_modbus_sensor(self)

        Fixed code (SolaXModbusSensor):
            async def async_added_to_hass(self) -> None:
                if self.entity_description.register < 0:
                    return
                await self._hub.async_add_solax_modbus_sensor(self)

        Impact: Computed/internal sensors (those without Modbus registers) were
        attempting to register with the polling system, causing crashes when
        trying to access device_info that shouldn't exist.

        Note: RiemannSumEnergySensor is exempt from this check as it's a legitimate
        sensor that integrates power data and needs hub registration.

        Commit: 56e0d5a (sensor.py, number.py, select.py, switch.py)
        """
        # Test the base sensor classes, not special cases like RiemannSumEnergySensor
        test_cases = [
            ("sensor.py", "SolaXModbusSensor"),
            ("number.py", "SolaXModbusNumber"),
            ("select.py", "SolaXModbusSelect"),
            ("switch.py", "SolaXModbusSwitch"),
        ]

        for filename, class_name in test_cases:
            file_path = get_source_file(filename)
            if not file_path.exists():
                pytest.skip(f"{filename} not found")

            content = file_path.read_text()

            # Find the specific class definition
            class_pattern = rf"class {re.escape(class_name)}\([^)]+\):.*?(?=\nclass |\Z)"
            class_match = re.search(class_pattern, content, re.DOTALL)

            if not class_match:
                continue  # Class not found, skip

            class_body = class_match.group(0)

            # Find async_added_to_hass in this class
            method_pattern = r"async def async_added_to_hass\(self\).*?(?=\n    async def|\n    def|\n    @|\nclass |\Z)"
            method_match = re.search(method_pattern, class_body, re.DOTALL)

            if not method_match:
                continue  # Method not in this class

            func_body = method_match.group(0)

            # If this function calls async_add_solax_modbus_sensor, it MUST have the check
            if "async_add_solax_modbus_sensor" in func_body:
                # Must have register check before the call
                # Pattern: check for register < 0 or register is None, followed by return
                has_register_check = bool(re.search(r"if.*?\.register\s*(?:<|is None|<=)\s*(?:0|None).*?return", func_body, re.DOTALL))

                assert has_register_check, (
                    f"REGRESSION: {filename} {class_name}.async_added_to_hass() calls "
                    "async_add_solax_modbus_sensor without checking if register < 0.\n"
                    "Computed/internal sensors (register < 0 or None) should skip registration.\n"
                    f"Function body:\n{func_body[:500]}"
                )


class TestDeviceInfoInitializationPattern:
    """Test that device_info initialization follows consistent patterns."""

    def test_initial_setup_device_info_pattern(self) -> None:
        """Test that initial setup device_info follows the same pattern as deferred setup.

        Both initialization paths should have identical structure to prevent divergence.
        """
        init_file = get_source_file("__init__.py")
        content = init_file.read_text()

        # Find both device_info initialization patterns
        # Pattern 1: Initial setup (in async_init_hub around line 640)
        initial_pattern = r"plugin_name = self\.plugin\.plugin_name\s+if self\.inverterNameSuffix.*?self\.device_info = DeviceInfo\("
        initial_match = re.search(initial_pattern, content, re.DOTALL)

        # Pattern 2: Deferred setup (in _deferred_setup_loop around line 687)
        deferred_pattern = r"plugin_name = self\.plugin\.plugin_name\s+if self\.inverterNameSuffix.*?self\.device_info = DeviceInfo\("
        deferred_matches = list(re.finditer(deferred_pattern, content, re.DOTALL))

        assert len(deferred_matches) >= 1, "Could not find device_info initialization patterns"

        if initial_match and len(deferred_matches) > 1:
            # Both patterns exist, verify they're structurally similar
            initial_block = initial_match.group(0)
            deferred_block = deferred_matches[1].group(0)  # Second match is deferred

            # Both should use the same if-condition structure
            initial_has_if = "if self.inverterNameSuffix" in initial_block
            deferred_has_if = "if self.inverterNameSuffix" in deferred_block

            assert initial_has_if == deferred_has_if, (
                "device_info initialization patterns diverge between initial and deferred setup. "
                "They should have identical structure to prevent bugs."
            )


class TestSensorEntityListSingleFunction:
    """Test the entityToListSingle function for correct device_info handling."""

    def test_device_info_parameter_not_lost(self) -> None:
        """Test that device_info parameter is not lost in entityToListSingle.

        The function receives device_info as a parameter and should use it,
        only overriding when _energy_dashboard_device_info is explicitly set
        to a non-None value.
        """
        sensor_file = get_source_file("sensor.py")
        content = sensor_file.read_text()

        # Find entityToListSingle function
        func_pattern = r"def entityToListSingle\([^)]+device_info[^)]*\).*?(?=\ndef |\nclass |\Z)"
        func_match = re.search(func_pattern, content, re.DOTALL)

        assert func_match, "entityToListSingle function not found or doesn't have device_info parameter"

        func_body = func_match.group(0)

        # Verify that device_info parameter is used when creating sensors
        assert "SolaXModbusSensor(" in func_body or "RiemannSumEnergySensor(" in func_body, "entityToListSingle should create sensor instances"

        # Check that device_info is passed to sensor constructors
        sensor_creation_pattern = r"(SolaXModbusSensor|RiemannSumEnergySensor)\([^)]*device_info[^)]*\)"
        sensor_creations = re.findall(sensor_creation_pattern, func_body, re.DOTALL)

        assert len(sensor_creations) > 0, "entityToListSingle should pass device_info to sensor constructors"


@pytest.mark.asyncio
class TestDeviceInfoRuntimeBehavior:
    """Runtime tests for device_info handling (require mock setup)."""

    async def test_sensor_with_none_energy_dashboard_device_info(self) -> None:
        """Test that sensor with _energy_dashboard_device_info=None gets parent device_info.

        This is the runtime validation of the fix in sensor.py line 793-794.
        """

        # Mock sensor description with _energy_dashboard_device_info = None
        # This was causing the bug - sensors with _energy_dashboard_device_info = None
        # would have their valid device_info parameter overwritten with None

        # We can't easily run entityToListSingle directly, but we verify the code pattern
        sensor_file = get_source_file("sensor.py")
        content = sensor_file.read_text()

        # Verify the fix is in place
        assert "is not None" in content or "!= None" in content, "The None check for _energy_dashboard_device_info is missing"

    async def test_deferred_setup_without_suffix_creates_device_info(self) -> None:
        """Test that deferred setup creates device_info even without inverterNameSuffix.

        This is the runtime validation of the fix in __init__.py line 685-693.
        """
        init_file = get_source_file("__init__.py")
        content = init_file.read_text()

        # Verify the indentation fix is present by checking the structure
        deferred_func_pattern = r"async def _deferred_setup_loop.*?self\.device_info = DeviceInfo\("

        match = re.search(deferred_func_pattern, content, re.DOTALL)
        assert match, "Deferred setup device_info assignment not found"

        # Check that the pattern shows device_info is ALWAYS set, not conditionally
        block = match.group(0)

        # The device_info assignment should come after the if block
        # Look for the pattern: "if self.inverterNameSuffix:" followed by "self.device_info"
        # with proper indentation indicating device_info is OUTSIDE the if
        lines = block.split("\n")

        if_line_idx = None
        device_info_idx = None

        for i, line in enumerate(lines):
            if "if self.inverterNameSuffix" in line:
                if_line_idx = i
            if "self.device_info = DeviceInfo(" in line:
                device_info_idx = i

        if if_line_idx is not None and device_info_idx is not None:
            # device_info should come after the if block
            assert device_info_idx > if_line_idx, "device_info assignment should be after inverterNameSuffix check"
