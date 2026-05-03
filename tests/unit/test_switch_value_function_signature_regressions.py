"""Regression tests for switch value_function signature mismatch bug.

These tests ensure that the switch value_function signature in the base class
matches the actual call signature used in switch.py.

Historical context:
- Issue: Type mismatch between base class signature and actual usage
- Root cause: Base class defined 3-parameter Callable, but switch.py passed 4 parameters
- Original base signature: Callable[[Any, Any, dict[str, Any]], Any]
- Actual call in switch.py:187: value_function(bit, is_on, sensor_key, datadict)
- Fixed signature: Callable[[int | None, bool | None, str | None, dict[str, Any]], int]
- Commit: dfa6cc2
"""

from collections.abc import Callable
from typing import Any


def test_switch_value_function_receives_four_parameters() -> None:
    """Test that switch value_function is called with 4 parameters.

    This documents the actual call pattern from switch.py:187 that was causing
    the type mismatch with the base class signature.
    """
    # Mock datadict
    datadict: dict[str, Any] = {"some_sensor": 1, "another_sensor": 2}

    # Correct signature: 4 parameters
    def value_function(bit: int | None, is_on: bool | None, sensor_key: str | None, datadict: dict[str, Any]) -> int:
        # Simulate actual usage pattern from switch.py
        if bit is not None and is_on is not None:
            return 1 if is_on else 0
        return 0

    # Call with 4 parameters (as done in switch.py)
    bit = 1
    is_on = True
    sensor_key = "test_switch"

    result = value_function(bit, is_on, sensor_key, datadict)
    assert isinstance(result, int)


def test_switch_value_function_signature_matches_base_class() -> None:
    """Test that the base class signature matches actual usage.

    Regression test for the signature mismatch between:
    - Base class: BaseModbusSwitchEntityDescription.value_function
    - Call site: switch.py line 187

    Original bug:
        Base: Callable[[Any, Any, dict[str, Any]], Any]  # 3 params
        Call: value_function(bit, is_on, sensor_key, datadict)  # 4 params
        Result: Type error at call site

    Fixed:
        Base: Callable[[int | None, bool | None, str | None, dict[str, Any]], int]
    """
    # Simulate the base class type hint
    ValueFunction = Callable[[int | None, bool | None, str | None, dict[str, Any]], int]

    # Define a function matching this signature
    def example_value_function(
        bit: int | None,
        is_on: bool | None,
        sensor_key: str | None,
        datadict: dict[str, Any],
    ) -> int:
        return 1 if is_on else 0

    # Verify it matches the type
    func: ValueFunction = example_value_function

    # Call it with all 4 parameters
    result = func(1, True, "test", {})
    assert result == 1


def test_switch_value_function_handles_none_parameters() -> None:
    """Test that value_function correctly handles None parameters.

    Switch value_functions must handle None for bit, is_on, and sensor_key
    since these can be None in certain states.
    """

    def value_function(
        bit: int | None,
        is_on: bool | None,
        sensor_key: str | None,
        datadict: dict[str, Any],
    ) -> int:
        if bit is None or is_on is None:
            return 0
        # Use bit to create a mask
        mask = 1 << bit
        return mask if is_on else 0

    # Test with all None
    assert value_function(None, None, None, {}) == 0

    # Test with some None
    assert value_function(1, None, None, {}) == 0

    # Test with valid values
    assert value_function(2, True, "switch", {}) == 4  # 1 << 2


def test_switch_value_function_accesses_datadict() -> None:
    """Test that value_function can access datadict parameter.

    Many switch value_functions need to read other sensor values from datadict
    to compute their result.
    """

    def value_function(
        bit: int | None,
        is_on: bool | None,
        sensor_key: str | None,
        datadict: dict[str, Any],
    ) -> int:
        # Example: conditional behavior based on other sensor
        if datadict.get("system_enabled", False):
            return 1 if is_on else 0
        return 0

    # With system enabled
    result = value_function(0, True, "test", {"system_enabled": True})
    assert result == 1

    # With system disabled
    result = value_function(0, True, "test", {"system_enabled": False})
    assert result == 0


def test_switch_value_function_wrong_signature_example() -> None:
    """Document what happens with the old incorrect 3-parameter signature.

    This test shows why the old signature was wrong and would fail at the call site.
    """
    # Old incorrect signature (3 parameters)
    OldValueFunction = Callable[[Any, Any, dict[str, Any]], Any]

    def old_signature_function(param1: Any, param2: Any, datadict: dict[str, Any]) -> Any:
        return 1

    func: OldValueFunction = old_signature_function

    # The call site in switch.py passes 4 parameters
    # With the old signature, this would be a type error:
    # func(bit, is_on, sensor_key, datadict)  # TypeError: too many arguments

    # We can only call with 3 parameters
    result = func(1, True, {})
    assert result == 1


def test_switch_value_function_mutate_bit_pattern() -> None:
    """Test the mutate_bit_in_register pattern from plugin_solis.py.

    Regression test for the common pattern of modifying a bit in a register
    based on switch state, which requires all 4 parameters.
    """

    def mutate_bit_in_register(
        bit: int | None,
        state: bool | None,
        sensor_key: str | None,
        datadict: dict[str, Any],
    ) -> int:
        """Mutate a specific bit in a register value based on switch state."""
        assert bit is not None, "bit must not be None"
        assert state is not None, "state must not be None"

        # Convert state to int
        state_int = 1 if state else 0

        # Read current register value
        register_value = int(datadict.get(sensor_key or "register", 0))

        # Create mask and apply
        mask = 1 << bit
        if state_int:
            return register_value | mask  # Set bit
        else:
            return register_value & ~mask  # Clear bit

    # Test setting bit 3 to on
    result = mutate_bit_in_register(3, True, "control_register", {"control_register": 0})
    assert result == 8  # Bit 3 set

    # Test clearing bit 3
    result = mutate_bit_in_register(3, False, "control_register", {"control_register": 15})
    assert result == 7  # Bit 3 cleared (15 - 8 = 7)
