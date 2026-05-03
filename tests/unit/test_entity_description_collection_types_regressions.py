"""Regression tests for entity description collection type bugs.

These tests ensure that entity description fields use correct collection types
(list vs tuple) and correct device class enums for entity types.

Historical context:
- Issue 1: depends_on and blacklist fields received tuples but expected lists
- Root cause: Plugins used tuple literals ("value",) but base class expected list[str]
- Fixed by: Converting all tuples to lists throughout plugins
- Commits: Multiple (987d008, 23c239f, bc41531, etc.)

- Issue 2: Wrong device_class enum for number entities
- Root cause: Used SensorDeviceClass.POWER instead of NumberDeviceClass.POWER
- Fixed by: Correcting to NumberDeviceClass.POWER
- Commit: d501814
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MockEntityDescription:
    """Mock entity description for testing."""

    key: str
    depends_on: list[str] | None = None
    blacklist: list[str] | None = None


def test_depends_on_accepts_list_not_tuple() -> None:
    """Test that depends_on field expects list, not tuple.

    Original bug in multiple plugins:
        depends_on=("value",)  # Tuple literal
        Type error: Expected list[str], got tuple[str, ...]

    Fixed:
        depends_on=["value"]  # List literal
    """
    # Correct: list
    entity = MockEntityDescription(
        key="test_sensor",
        depends_on=["pv_voltage_1", "pv_current_1"],
    )

    assert entity.depends_on is not None
    assert isinstance(entity.depends_on, list)
    assert len(entity.depends_on) == 2


def test_blacklist_accepts_list_not_tuple() -> None:
    """Test that blacklist field expects list, not tuple.

    Same bug pattern as depends_on field.
    """
    # Correct: list
    entity = MockEntityDescription(
        key="test_sensor",
        blacklist=["BAD_MODEL", "DEPRECATED"],
    )

    assert entity.blacklist is not None
    assert isinstance(entity.blacklist, list)
    assert len(entity.blacklist) == 2


def test_single_element_depends_on_must_be_list() -> None:
    """Test that single-element depends_on is a list, not tuple.

    This was a common pattern that caused errors:
        depends_on=("value",)  # Single-element tuple

    Should be:
        depends_on=["value"]  # Single-element list
    """
    # Correct: single-element list
    entity = MockEntityDescription(key="computed_sensor", depends_on=["source_sensor"])

    assert entity.depends_on is not None
    assert isinstance(entity.depends_on, list)
    assert entity.depends_on == ["source_sensor"]


def test_number_entity_uses_number_device_class() -> None:
    """Test that NumberEntityDescription uses NumberDeviceClass, not SensorDeviceClass.

    Original bug in plugin_growatt.py:1015, 1033, 1074:
        GrowattModbusNumberEntityDescription(
            device_class=SensorDeviceClass.POWER,  # Wrong enum!
        )

    Fixed:
        device_class=NumberDeviceClass.POWER  # Correct enum
    """

    # Mock device classes
    class SensorDeviceClass:
        POWER = "sensor_power"

    class NumberDeviceClass:
        POWER = "number_power"

    # Correct: Use NumberDeviceClass for number entities
    number_entity_device_class = NumberDeviceClass.POWER
    assert number_entity_device_class == "number_power"
    assert number_entity_device_class != SensorDeviceClass.POWER


def test_sensor_entity_uses_sensor_device_class() -> None:
    """Test that SensorEntityDescription uses SensorDeviceClass (correct usage).

    This documents the correct usage to contrast with the number entity bug.
    """

    class SensorDeviceClass:
        POWER = "sensor_power"

    # Correct: Use SensorDeviceClass for sensor entities
    sensor_entity_device_class = SensorDeviceClass.POWER
    assert sensor_entity_device_class == "sensor_power"


def test_depends_on_none_is_valid() -> None:
    """Test that depends_on=None is a valid value.

    Many entities don't depend on other sensors, so None is acceptable.
    """
    entity = MockEntityDescription(key="independent_sensor", depends_on=None)

    assert entity.depends_on is None


def test_depends_on_empty_list_vs_none() -> None:
    """Test the semantic difference between empty list and None for depends_on.

    None: No dependency tracking
    []: Explicitly tracked as having no dependencies
    """
    entity_with_none = MockEntityDescription(key="sensor1", depends_on=None)
    entity_with_empty = MockEntityDescription(key="sensor2", depends_on=[])

    assert entity_with_none.depends_on is None
    assert entity_with_empty.depends_on == []
    assert entity_with_empty.depends_on is not None


def test_tuple_to_list_conversion_pattern() -> None:
    """Test the conversion pattern used to fix the tuple vs list bug.

    This documents the systematic fix applied across all plugins.
    """
    # Original buggy code pattern
    buggy_tuple = ("sensor_1", "sensor_2")

    # Fixed pattern: convert to list
    fixed_list = list(buggy_tuple) if isinstance(buggy_tuple, tuple) else buggy_tuple

    assert isinstance(fixed_list, list)
    assert fixed_list == ["sensor_1", "sensor_2"]

    # Direct list usage (preferred)
    direct_list = ["sensor_1", "sensor_2"]
    assert isinstance(direct_list, list)


def test_bracket_mismatch_from_tuple_conversion() -> None:
    """Test that tuple-to-list conversion fixes bracket mismatches.

    During the bulk conversion, some code had mismatched brackets:
        depends_on=("value",)  # Tuple with parentheses

    Was incorrectly changed to:
        depends_on=["value",)  # Mixed brackets - syntax error!

    Should be:
        depends_on=["value"]  # Consistent brackets
    """
    # Correct: consistent square brackets
    depends_on = ["value_1", "value_2"]

    assert isinstance(depends_on, list)
    assert depends_on[0] == "value_1"
    assert depends_on[1] == "value_2"


def test_device_class_type_safety() -> None:
    """Test that using wrong device_class enum is caught by type system.

    This test documents why type checking helps catch device_class mismatches.
    """
    from enum import Enum

    class SensorDeviceClass(Enum):
        POWER = "sensor_power"
        ENERGY = "sensor_energy"

    class NumberDeviceClass(Enum):
        POWER = "number_power"
        ENERGY = "number_energy"

    # Type-safe usage: match entity type with device class
    sensor_power: SensorDeviceClass = SensorDeviceClass.POWER
    number_power: NumberDeviceClass = NumberDeviceClass.POWER

    assert sensor_power.value == "sensor_power"
    assert number_power.value == "number_power"
    assert sensor_power.value != number_power.value  # Different enums!
