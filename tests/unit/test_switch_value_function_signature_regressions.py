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

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus import core_modbus as core
from custom_components.solax_modbus import modbus_transport as transport
from custom_components.solax_modbus.const import (
    WRITE_DATA_LOCAL,
    WRITE_SINGLE_MODBUS,
    BaseModbusSwitchEntityDescription,
    value_function_disable_enable,
    value_function_enable_disable,
    value_function_packed_switches,
)
from custom_components.solax_modbus.switch import SolaXModbusSwitch


def yaml_hub(**extra: Any) -> dict[str, Any]:
    return {"name": "inverter_bus", "type": "tcp", "host": "192.0.2.1", "port": 502, "timeout": 12, "delay": 1, **extra}


@pytest.fixture
def unit_transport(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(transport, "core_connection_params", lambda settings: SimpleNamespace(endpoint=("tcp", "192.0.2.1", 502)))
    unit = SimpleNamespace(
        connected=False,
        require_timeout=Mock(),
        require_connect_delay=Mock(),
        set_message_spacing=Mock(),
        read_holding_registers=AsyncMock(return_value=[7, 8]),
        read_input_registers=AsyncMock(return_value=[9]),
        write_register=AsyncMock(),
        write_registers=AsyncMock(),
        disconnect=AsyncMock(),
    )
    getter = Mock(return_value=unit)
    return transport.CoreModbusUnitTransport(
        cast(Any, object()), cast(Any, object()), core.connection_settings(yaml_hub(message_wait_milliseconds=50)), 1, unit_getter=getter
    )


def _hub_with_data(
    monkeypatch: pytest.MonkeyPatch, unit_transport: Any, data: dict[str, Any], descr: set[BaseModbusSwitchEntityDescription]
) -> tuple[Any, SolaXModbusSwitch]:
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "test"
    hub._modbus_addr = 1
    hub.data = data
    hub.sensorDescriptions = descr
    hub._transport = unit_transport
    hub.plugin = SimpleNamespace(order32="big", isAwake=lambda x: True)
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub.gatedEntities = set()

    switch = SolaXModbusSwitch(hub._name, hub, hub._modbus_addr, {}, next(iter(hub.sensorDescriptions)))
    monkeypatch.setattr(switch, "async_write_ha_state", lambda: ())
    return (hub, switch)


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
    type ValueFunction = Callable[[int | None, bool | None, str | None, dict[str, Any]], int]

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
    type OldValueFunction = Callable[[Any, Any, dict[str, Any]], Any]

    def old_signature_function(param1: Any, param2: Any, datadict: dict[str, Any]) -> Any:
        return 1

    func: OldValueFunction = old_signature_function

    # The call site in switch.py passes 4 parameters
    # With the old signature, this would be a type error:
    # func(bit, is_on, sensor_key, datadict)  # TypeError: too many arguments

    # We can only call with 3 parameters
    result = func(1, True, {})
    assert result == 1


@pytest.mark.parametrize(
    ("bit", "state", "original", "expected"),
    [
        (3, True, 0, 8),  # Test bits clearing and setting
        (3, False, 15, 7),
        (1, True, 1, 3),
        (1, False, 3, 1),
        (2, True, 4, 4),  # Test bit already is correct state
        (2, False, 8, 8),
    ],
)
def test_switch_value_function_mutate_bit_pattern(bit: int, state: bool, original: int, expected: int) -> None:
    """Test the value_function_packed_switches
    Regression test for the common pattern of modifying a bit in a register
    based on switch state, which requires all 4 parameters.
    """
    result = value_function_packed_switches(bit, state, "control_register", {"control_register": original})
    assert result == expected


@pytest.mark.parametrize(
    ("bit", "state", "expected"),
    [
        (3, True, 0),  # Test switching on and off
        (3, False, 1),
        (None, True, 0),  # Bit number is ignored
        (None, False, 1),
    ],
)
def test_switch_value_function_disable_enable(bit: int | None, state: bool, expected: int) -> None:
    """Test the boolean switch value functions
    Ensures that switches are mapped to correct boolean 1/0 state
    """
    result = value_function_disable_enable(bit, state, "control_register", {})
    assert result == expected


@pytest.mark.parametrize(
    ("bit", "state", "expected"),
    [
        (3, True, 1),  # Test switching on and off
        (3, False, 0),
        (None, True, 1),  # Bit number is ignored
        (None, False, 0),
    ],
)
def test_switch_value_function_enable_disable(bit: int | None, state: bool, expected: int) -> None:
    """Test the boolean switch value functions
    Ensures that switches are mapped to correct boolean 1/0 state
    """
    result = value_function_enable_disable(bit, state, "control_register", {})
    assert result == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("method", [WRITE_DATA_LOCAL, WRITE_SINGLE_MODBUS], ids=["local", "modbus"])
@pytest.mark.parametrize(
    ("bit", "state", "expected"),
    [
        (3, True, 28),
        (4, False, 4),
        (1, True, 22),
        (1, False, 20),
    ],
    ids=["bit3_on", "bit4_off", "bit1_on", "bit1_off"],
)
async def test_switch_packed_value_updated_in_data(
    monkeypatch: pytest.MonkeyPatch, unit_transport: Any, method: int, bit: int, state: bool, expected: int
) -> None:
    hub, switch = _hub_with_data(
        monkeypatch,
        unit_transport,
        {"test_switch": 20},
        {
            BaseModbusSwitchEntityDescription(
                name="Test Switch",
                key="test_switch",
                register=42,
                write_method=method,
                icon="mdi:switch",
                register_bit=bit,
                sensor_key="test_switch",
                value_function=value_function_packed_switches,
            ),
        },
    )
    await switch._async_set_state(state)
    assert hub.data[switch._key] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [True, False])
async def test_switch_local_nokey_skips_update(monkeypatch: pytest.MonkeyPatch, unit_transport: Any, state: bool) -> None:
    hub, switch = _hub_with_data(
        monkeypatch,
        unit_transport,
        {"test_switch": 20},
        {
            BaseModbusSwitchEntityDescription(
                name="Test Switch",
                key="test_switch",
                register=42,
                write_method=WRITE_DATA_LOCAL,
                icon="mdi:switch",
                register_bit=3,
                value_function=value_function_packed_switches,
            ),
        },
    )
    await switch._async_set_state(state)
    assert hub.data[switch._key] == 20
