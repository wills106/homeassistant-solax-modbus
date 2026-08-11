"""Rated-current derivation for the SolaX EV charger plugin.

The rated current feeds max_key="rated_current" on the current controls, so a
wrong value silently caps Charge Current / Max Charge Current in Home Assistant.
Documented nameplate ratings must win over the watts/(phases*230) derivation,
which truncates the 7.2 kW X1 unit to 31 A instead of its actual 32 A.
"""

import pytest

from custom_components.solax_modbus.plugin_solax_ev_charger import value_function_rated_current


@pytest.mark.parametrize(
    ("power_rating", "phase_type", "expected"),
    [
        ("7 kW", "Single Phase", 32.0),
        ("4.6 kW", "Single Phase", 20.0),
        ("7.6 kW", "Single Phase", 32.0),
        ("9.6 kW", "Single Phase", 40.0),
        ("11.5 kW", "Single Phase", 48.0),
        ("11 kW", "Three Phase", 16.0),
        ("22 kW", "Three Phase", 32.0),
    ],
)
def test_documented_nameplate_ratings(power_rating: str, phase_type: str, expected: float) -> None:
    data = {"power_rating": power_rating, "phase_type": phase_type}
    assert value_function_rated_current(None, None, data) == expected


@pytest.mark.parametrize(
    ("power_rating", "phase_type", "expected"),
    [
        ("6 kW", "Single Phase", 26.0),
        ("6 kW", "Three Phase", 9.0),
        ("7 kW", "Three Phase", 10.0),
    ],
)
def test_underived_combinations_fall_back_to_calculation(power_rating: str, phase_type: str, expected: float) -> None:
    data = {"power_rating": power_rating, "phase_type": phase_type}
    assert value_function_rated_current(None, None, data) == expected


def test_unknown_power_rating_returns_none() -> None:
    assert value_function_rated_current(None, None, {"power_rating": None, "phase_type": "Single Phase"}) is None
    assert value_function_rated_current(None, None, {}) is None
