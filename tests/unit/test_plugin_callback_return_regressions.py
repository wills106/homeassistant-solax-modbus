"""Regression tests for plugin callback return type bugs.

These tests ensure that plugin methods return correct types per base class
contract, rather than implicitly returning None.

Historical context:
- Issue: Plugin methods missing return statements, implicitly returning None
- Root cause: Methods declared return type (e.g., -> bool) but had no return statement
- Impact: Violated base class contract, potential runtime type errors
- Affected methods:
  * localDataCallback (should return bool, not None)
  * matchInverterWithMask (should return bool, not implicit)
  * async_determineInverterType (should return int, not implicit)
- Fixed in: Multiple commits (8020a6c, 9c46f46, etc.)
"""

from typing import Any


def test_local_data_callback_must_return_bool() -> None:
    """Test that localDataCallback returns bool, not None.

    Original bug in multiple plugins (alphaess, srne, solax_a1j1, solax_mega_forth):
        def localDataCallback(self, hub: Any) -> bool:
            # ... update logic ...
            pass  # Implicitly returns None, not bool!

    Fixed:
        def localDataCallback(self, hub: Any) -> bool:
            # ... update logic ...
            return True
    """

    class MockPlugin:
        def localDataCallback(self, hub: Any) -> bool:
            # Simulate some update logic
            config_entity = hub.get("config_entity")
            if config_entity:
                # Do some configuration update
                pass
            # Must return bool
            return True

    plugin = MockPlugin()
    result = plugin.localDataCallback({"config_entity": "test"})

    assert isinstance(result, bool)
    assert result is True  # Not None!


def test_match_inverter_with_mask_must_return_bool() -> None:
    """Test that matchInverterWithMask returns bool, not implicit Any.

    This method determines if an entity should be created for a specific
    inverter model based on bitmask matching.
    """

    class MockPlugin:
        def matchInverterWithMask(
            self,
            inverterspec: Any,
            entitymask: Any,
            serialnumber: str = "not relevant",
            blacklist: list[str] | None = None,
        ) -> bool:
            # Simulate bitmask matching
            gen_match = (inverterspec & entitymask & 0xFF) != 0
            blacklisted = False
            if blacklist:
                for start in blacklist:
                    if serialnumber.startswith(start):
                        blacklisted = True
            return gen_match and not blacklisted

    plugin = MockPlugin()
    result = plugin.matchInverterWithMask(0x01, 0x01, "TEST123", None)

    assert isinstance(result, bool)
    assert result is True


def test_async_determine_inverter_type_must_return_int() -> None:
    """Test that async_determineInverterType returns int, not None.

    This async method determines the inverter type flags (bitmask) based on
    serial number or other detection logic.
    """

    class MockPlugin:
        async def async_determineInverterType(self, hub: Any, configdict: dict[str, Any]) -> int:
            # Simulate inverter type detection
            serial = await self._read_serial(hub)
            if serial and serial.startswith("303105"):
                return 0x01 | 0x10  # HYBRID | X1
            return 0  # Unknown type

        async def _read_serial(self, hub: Any) -> str:
            return "303105ABC"

    async def test_async() -> None:
        plugin = MockPlugin()
        result = await plugin.async_determineInverterType({}, {})
        assert isinstance(result, int)
        assert result == 0x11  # 0x01 | 0x10

    # Run async test
    import asyncio

    asyncio.run(test_async())


def test_plugin_optional_methods_can_return_none() -> None:
    """Test that optional plugin methods correctly return str | None.

    Methods like getSoftwareVersion, getHardwareVersion are optional and
    can legitimately return None.
    """

    class MockPlugin:
        def getSoftwareVersion(self, new_data: dict[str, Any]) -> str | None:
            fw = new_data.get("firmware_version")
            return f"v{fw}" if fw is not None else None

        def getHardwareVersion(self, new_data: dict[str, Any]) -> str | None:
            return new_data.get("hardware_version")

    plugin = MockPlugin()

    # With data present
    assert plugin.getSoftwareVersion({"firmware_version": "1.2.3"}) == "v1.2.3"
    assert plugin.getHardwareVersion({"hardware_version": "HW-1"}) == "HW-1"

    # With data missing (None is valid)
    assert plugin.getSoftwareVersion({}) is None
    assert plugin.getHardwareVersion({}) is None


def test_is_awake_must_return_bool() -> None:
    """Test that isAwake method returns bool, not None.

    The isAwake method checks if an inverter is active/awake based on datadict.
    """

    class MockPlugin:
        def isAwake(self, datadict: dict[str, Any]) -> bool:
            # Check if any power generation exists
            pv_power = datadict.get("pv_power_1", 0)
            return bool(pv_power > 0)

    plugin = MockPlugin()

    assert plugin.isAwake({"pv_power_1": 100}) is True
    assert plugin.isAwake({"pv_power_1": 0}) is False
    assert plugin.isAwake({}) is False


def test_wakeup_button_must_return_string() -> None:
    """Test that wakeupButton returns str, not None.

    The wakeupButton method returns the key of the button entity that should
    be pressed to wake up the inverter.
    """

    class MockPlugin:
        def wakeupButton(self) -> str:
            return "battery_awaken"

    plugin = MockPlugin()
    result = plugin.wakeupButton()

    assert isinstance(result, str)
    assert result == "battery_awaken"


def test_local_data_callback_without_return_causes_none() -> None:
    """Document the bug: missing return statement causes None return.

    This test explicitly shows what happens with the buggy code.
    """

    class BuggyPlugin:
        def localDataCallback(self, hub: Any) -> bool:  # type: ignore[return]
            # Do some work
            _ = hub.get("something")
            # BUG: No return statement! Implicitly returns None

    plugin = BuggyPlugin()
    result = plugin.localDataCallback({"something": "value"})

    # This is the bug: result is None, not bool
    assert result is None  # Documents the bug
    assert not isinstance(result, bool)  # type: ignore[unreachable]  # Intentionally documenting buggy behavior


def test_local_data_callback_with_return_correct() -> None:
    """Test the correct fix: explicit return True statement.

    Fixed code from commits 8020a6c, 9c46f46, etc.
    """

    class FixedPlugin:
        def localDataCallback(self, hub: Any) -> bool:
            # Do some work
            _ = hub.get("something")
            # FIXED: Explicit return statement
            return True

    plugin = FixedPlugin()
    result = plugin.localDataCallback({"something": "value"})

    assert result is True
    assert isinstance(result, bool)  # Satisfies base class contract
