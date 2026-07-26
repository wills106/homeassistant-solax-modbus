"""Regression tests for scaled number writes."""

import pytest

from custom_components.solax_modbus.number import _scale_native_value_to_register


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5.1, 51),
        (5.8, 58),
        (6.6, 66),
        (8.2, 82),
        (9.7, 97),
    ],
)
def test_tenth_scale_does_not_truncate_float_rounding_error(value: float, expected: int) -> None:
    """Values on a 0.1 step are written to the matching register value."""
    assert _scale_native_value_to_register(value, 0.1, 1) == expected


def test_hundredth_scale_does_not_truncate_float_rounding_error() -> None:
    """The conversion also works for registers with a 0.01 scale."""
    assert _scale_native_value_to_register(1.23, 0.01, 1) == 123


def test_negative_scaled_value_rounds_to_nearest_register_step() -> None:
    """Negative values are rounded instead of truncated toward zero."""
    assert _scale_native_value_to_register(-5.1, 0.1, 1) == -51


def test_read_scale_is_included_in_conversion() -> None:
    """Per-inverter read scaling remains part of the register conversion."""
    assert _scale_native_value_to_register(5.2, 0.1, 2) == 26
