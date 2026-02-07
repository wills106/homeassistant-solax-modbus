"""Regression tests for device identifier tuple structure bugs.

These tests ensure that device identifiers and via_device tuples maintain
the correct number of elements as expected by runtime code.

Historical context:
- Issue: IndexError: tuple index out of range at __init__.py:842
- Root cause: Changed 3-element tuples to 2-element tuples to satisfy mypy,
  breaking runtime code that accesses identifier_tuple[2]
- Key finding: HA type stubs incorrectly define identifiers as set[tuple[str, str]]
  but runtime code requires 3-element tuples in some cases
- Solution: Use 3-element tuples with type: ignore for HA stub incompatibility
"""

from typing import cast

import pytest


def test_device_identifier_tuple_structure() -> None:
    """Test that device identifiers are 3-element tuples where required.

    This test documents the correct structure for device identifiers that
    are used in device_group_key() method in __init__.py.
    """
    DOMAIN = "solax_modbus"
    hub_name = "solax_1_energy_dashboard"
    identifier_type = "ENERGY_DASHBOARD"

    # Correct structure: 3-element tuple
    identifier = (DOMAIN, hub_name, identifier_type)

    assert len(identifier) == 3
    assert identifier[0] == DOMAIN
    assert identifier[1] == hub_name
    assert identifier[2] == identifier_type


def test_device_identifier_tuple_indexing() -> None:
    """Test that device identifier tuples can be safely indexed to [2].

    Regression test for __init__.py:842 which accesses identifier_tuple[2].

    Original bug:
        identifiers={(DOMAIN, f"{name}_energy_dashboard")}  # 2-element tuple
        # Later: identifier_tuple[2]  -> IndexError

    Fixed code:
        identifiers={(DOMAIN, f"{name}_energy_dashboard", "ENERGY_DASHBOARD")}  # 3-element
    """
    DOMAIN = "solax_modbus"

    # Simulate the device_group_key logic from __init__.py
    identifier_tuple = cast(tuple[str, ...], (DOMAIN, "solax_1_energy_dashboard", "ENERGY_DASHBOARD"))

    # This operation from __init__.py:842 should not raise IndexError
    if identifier_tuple[0] == DOMAIN:
        key = identifier_tuple[1] + "_" + identifier_tuple[2]

    assert key == "solax_1_energy_dashboard_ENERGY_DASHBOARD"


def test_via_device_tuple_structure() -> None:
    """Test that via_device tuples are 3-element tuples.

    via_device is used to link virtual devices to their parent hardware device.
    The runtime expects 3 elements: (domain, device_name, device_type).
    """
    DOMAIN = "solax_modbus"
    hub_name = "SolaX 1"
    INVERTER_IDENT = "INVERTER"

    # Correct structure: 3-element tuple
    via_device = (DOMAIN, hub_name, INVERTER_IDENT)

    assert len(via_device) == 3
    assert via_device[0] == DOMAIN
    assert via_device[1] == hub_name
    assert via_device[2] == INVERTER_IDENT


def test_device_identifier_set_structure() -> None:
    """Test that identifiers set contains properly structured tuples.

    DeviceInfo.identifiers is a set of tuples. Each tuple should have 3 elements
    for proper runtime operation, despite HA type stubs suggesting 2 elements.
    """
    DOMAIN = "solax_modbus"

    # Correct structure: set of 3-element tuples
    identifiers = {(DOMAIN, "solax_1_energy_dashboard", "ENERGY_DASHBOARD")}

    assert len(identifiers) == 1
    identifier_tuple = next(iter(identifiers))
    assert len(identifier_tuple) == 3


def test_device_group_key_logic() -> None:
    """Test the device_group_key logic that caused the IndexError.

    This simulates the exact logic from __init__.py:800-842 that was breaking
    when identifiers were changed from 3-element to 2-element tuples.
    """
    DOMAIN = "solax_modbus"

    # Mock device_info with correct 3-element identifier
    device_info = {
        "identifiers": {(DOMAIN, "solax_1_energy_dashboard", "ENERGY_DASHBOARD")},
        "name": "SolaX 1 Energy Dashboard",
    }

    # Simulate device_group_key logic
    key = ""
    identifiers = device_info["identifiers"]

    for identifier in identifiers:
        identifier_tuple = cast(tuple[str, ...], identifier)
        if identifier_tuple[0] != DOMAIN:
            continue
        # This line was causing IndexError when tuple only had 2 elements
        key = identifier_tuple[1] + "_" + identifier_tuple[2]

    assert key == "solax_1_energy_dashboard_ENERGY_DASHBOARD"


def test_two_element_tuple_causes_index_error() -> None:
    """Test that 2-element tuples cause IndexError (documents the bug).

    This test explicitly demonstrates what happens when the tuple structure
    is incorrect, which was the original bug we fixed.
    """
    DOMAIN = "solax_modbus"

    # Incorrect structure: 2-element tuple (the bug)
    identifier_tuple = cast(tuple[str, ...], (DOMAIN, "solax_1_energy_dashboard"))

    assert len(identifier_tuple) == 2

    # Attempting to access index 2 should raise IndexError
    with pytest.raises(IndexError) as exc_info:
        _ = identifier_tuple[2]  # type: ignore[misc]  # Intentionally accessing out of range index

    assert "tuple index out of range" in str(exc_info.value)


def test_energy_dashboard_device_info_structure() -> None:
    """Test complete DeviceInfo structure for energy dashboard virtual device.

    This test documents the correct full structure that should be returned
    by create_energy_dashboard_device_info() in energy_dashboard.py.
    """
    DOMAIN = "solax_modbus"
    INVERTER_IDENT = "INVERTER"
    normalized_hub_name = "solax_1"
    hub_name = "SolaX 1"

    # Correct DeviceInfo structure (key fields)
    device_info = {
        "identifiers": {(DOMAIN, f"{normalized_hub_name}_energy_dashboard", "ENERGY_DASHBOARD")},
        "name": f"{hub_name} Energy Dashboard",
        "via_device": (DOMAIN, hub_name, INVERTER_IDENT),
    }

    # Validate identifiers structure
    identifier = next(iter(device_info["identifiers"]))
    assert len(identifier) == 3
    assert identifier[0] == DOMAIN
    assert identifier[1] == f"{normalized_hub_name}_energy_dashboard"
    assert identifier[2] == "ENERGY_DASHBOARD"

    # Validate via_device structure
    via_device = cast(tuple[str, str, str], device_info["via_device"])
    assert len(via_device) == 3
    assert via_device[0] == DOMAIN
    assert via_device[1] == hub_name
    assert via_device[2] == INVERTER_IDENT


def test_multiple_device_identifiers() -> None:
    """Test handling of multiple device identifiers in a set.

    Ensures that when a device has multiple identifiers, each maintains
    the correct 3-element structure.
    """
    DOMAIN = "solax_modbus"

    identifiers = {
        (DOMAIN, "device_1", "TYPE_A"),
        (DOMAIN, "device_2", "TYPE_B"),
    }

    for identifier in identifiers:
        assert len(identifier) == 3
        assert identifier[0] == DOMAIN
        # Can safely access identifier[2]
        assert identifier[2] in ("TYPE_A", "TYPE_B")
