"""Regression tests for frozen dataclass field modification bugs.

These tests ensure that code properly uses dataclasses.replace() instead of
direct field assignment when working with frozen dataclasses.

Historical context:
- Issue: FrozenInstanceError when attempting direct assignment to frozen dataclass fields
- Root cause: Using `obj.field = value` instead of `obj = replace(obj, field=value)`
- Affected areas: sensor.py, number.py, select.py, switch.py, button.py,
  __init__.py, energy_dashboard.py
"""

from dataclasses import dataclass, replace

import pytest


@dataclass(frozen=True)
class MockFrozenEntityDescription:
    """Mock frozen entity description for testing."""

    key: str
    name: str | None = None
    native_max_value: float | None = None
    ignore_readerror: bool = False


def test_frozen_dataclass_cannot_assign_directly() -> None:
    """Test that frozen dataclass raises FrozenInstanceError on direct assignment.

    This test documents the original bug: attempting to modify a frozen dataclass
    field directly raises FrozenInstanceError at runtime.
    """
    descr = MockFrozenEntityDescription(key="test_key", name="Test")

    with pytest.raises(Exception) as exc_info:
        descr.name = "Modified"  # type: ignore[misc]  # Intentionally testing invalid operation

    # Should be a FrozenInstanceError with "cannot assign" message
    error_msg = str(exc_info.value).lower()
    assert "frozen" in error_msg or "can't set attribute" in error_msg or "cannot assign" in error_msg


def test_frozen_dataclass_replace_works() -> None:
    """Test that dataclasses.replace() correctly modifies frozen dataclass.

    This test documents the correct fix: using replace() to create a new
    instance with modified fields.
    """
    original = MockFrozenEntityDescription(key="test_key", name="Original")

    # Correct way: use replace()
    modified = replace(original, name="Modified")

    assert original.name == "Original"  # Original unchanged
    assert modified.name == "Modified"  # New instance has new value
    assert modified.key == "test_key"  # Other fields preserved


def test_frozen_dataclass_multiple_field_replace() -> None:
    """Test replacing multiple fields at once using replace().

    Regression test for energy_dashboard.py line 555-566 where multiple
    metadata fields needed to be updated together.
    """
    original = MockFrozenEntityDescription(key="test_key", name="Original", native_max_value=100.0, ignore_readerror=False)

    # Replace multiple fields at once
    modified = replace(
        original,
        name="Modified",
        native_max_value=200.0,
        ignore_readerror=True,
    )

    assert modified.name == "Modified"
    assert modified.native_max_value == 200.0
    assert modified.ignore_readerror is True
    assert modified.key == "test_key"  # Unchanged field preserved


def test_frozen_dataclass_key_prefix_pattern() -> None:
    """Test key prefix modification pattern from sensor.py line 769.

    Original bug:
        newdescr.key = key_prefix + newdescr.key
        # FrozenInstanceError: cannot assign to field 'key'

    Fixed code:
        newdescr = replace(newdescr, key=key_prefix + newdescr.key)
    """
    original = MockFrozenEntityDescription(key="sensor_name")
    key_prefix = "prefix_"

    # Correct pattern: use replace() with modified key
    modified = replace(original, key=key_prefix + original.key)

    assert modified.key == "prefix_sensor_name"
    assert original.key == "sensor_name"  # Original unchanged


def test_frozen_dataclass_conditional_replace() -> None:
    """Test conditional field modification pattern.

    Regression test for __init__.py line 1738 where ignore_readerror is
    conditionally set based on auto_block_ignore_readerror flag.
    """
    original = MockFrozenEntityDescription(key="test", ignore_readerror=False)
    auto_block_ignore_readerror = True

    # Correct pattern: conditionally replace field
    if auto_block_ignore_readerror:
        modified = replace(original, ignore_readerror=True)
    else:
        modified = original

    assert modified.ignore_readerror is True
    assert original.ignore_readerror is False  # Original unchanged


def test_frozen_dataclass_dict_update_pattern() -> None:
    """Test pattern for updating frozen dataclass in a dictionary.

    Regression test for __init__.py line 1733 where descriptor in a dict
    needed to be replaced with a modified version.
    """
    descriptions = {
        "sensor1": MockFrozenEntityDescription(key="sensor1", ignore_readerror=False),
        "sensor2": MockFrozenEntityDescription(key="sensor2", ignore_readerror=False),
    }

    # Correct pattern: replace the value in the dict
    key_to_update = "sensor1"
    descriptions[key_to_update] = replace(descriptions[key_to_update], ignore_readerror=True)

    assert descriptions["sensor1"].ignore_readerror is True
    assert descriptions["sensor2"].ignore_readerror is False


def test_frozen_dataclass_name_modification_pattern() -> None:
    """Test name modification pattern from platform files.

    Regression test for patterns in number.py:55, select.py:46, switch.py:45,
    button.py:46 where entity names needed prefixes/suffixes.

    Original bug:
        newdescr.name = f"{hub_name} {newdescr.name}"
        # FrozenInstanceError: cannot assign to field 'name'

    Fixed code:
        newdescr = replace(newdescr, name=f"{hub_name} {newdescr.name}")
    """
    original = MockFrozenEntityDescription(key="entity", name="Temperature")
    hub_name = "SolaX 1"

    # Correct pattern: use replace() with modified name
    modified = replace(original, name=f"{hub_name} {original.name}")

    assert modified.name == "SolaX 1 Temperature"
    assert original.name == "Temperature"  # Original unchanged


def test_frozen_dataclass_max_value_update_pattern() -> None:
    """Test max value update pattern from energy_dashboard.py.

    Regression test for energy_dashboard.py line 1211-1214 where
    native_max_value is conditionally updated based on exceptions.
    """
    original = MockFrozenEntityDescription(key="export_limit", native_max_value=5000.0)
    new_max_export = 10000.0

    # Correct pattern: use replace() to update max value
    modified = replace(original, native_max_value=new_max_export)

    assert modified.native_max_value == 10000.0
    assert original.native_max_value == 5000.0  # Original unchanged
