"""Tests for number entity limits derived from Modbus data types."""

import pytest
from homeassistant.components.number import DEFAULT_MAX_VALUE, DEFAULT_MIN_VALUE

from custom_components.solax_modbus.const import (
    REGISTER_F32,
    REGISTER_INT_RANGES,
    REGISTER_S16,
    REGISTER_S32,
    REGISTER_U16,
    REGISTER_U32,
    BaseModbusNumberEntityDescription,
)
from custom_components.solax_modbus.number import _native_value_bounds
from custom_components.solax_modbus.plugin_sofar import NUMBER_TYPES as SOFAR_NUMBER_TYPES


@pytest.mark.parametrize("register_data_type", [REGISTER_U16, REGISTER_S16, REGISTER_U32, REGISTER_S32])
def test_integer_register_bounds_are_derived(register_data_type: str) -> None:
    """An entity without explicit limits should accept its full wire range."""
    description = BaseModbusNumberEntityDescription(key="test", register_data_type=register_data_type)

    assert _native_value_bounds(description) == REGISTER_INT_RANGES[register_data_type]


def test_derived_bounds_include_native_scaling() -> None:
    """Raw register bounds should be exposed in the entity's native units."""
    description = BaseModbusNumberEntityDescription(
        key="test",
        register_data_type=REGISTER_S16,
        scale=0.1,
        read_scale=2,
    )

    assert _native_value_bounds(description) == (-6553.6, 6553.4)


def test_explicit_bounds_override_derived_bounds_independently() -> None:
    """Plugins may constrain either side of the data type's native range."""
    description = BaseModbusNumberEntityDescription(
        key="test",
        register_data_type=REGISTER_U16,
        native_min_value=10,
        native_max_value=20000,
    )

    assert _native_value_bounds(description) == (10, 20000)


def test_non_integer_type_uses_home_assistant_defaults() -> None:
    """A type without integer bounds should retain HA's defaults."""
    description = BaseModbusNumberEntityDescription(key="test", register_data_type=REGISTER_F32)

    assert _native_value_bounds(description) == (DEFAULT_MIN_VALUE, DEFAULT_MAX_VALUE)


def test_sofar_passive_grid_power_uses_signed_32_bit_bounds() -> None:
    """Parallel Sofar systems should accept totals above one inverter's rating."""
    description = next(item for item in SOFAR_NUMBER_TYPES if item.key == "passive_mode_grid_power")

    assert description.native_min_value is None
    assert description.native_max_value is None
    assert _native_value_bounds(description) == (-(1 << 31), (1 << 31) - 1)
