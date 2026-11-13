"""X3-Aelio battery charge/discharge max current follows the datasheet: 160 A (80 A x 2 battery ports)."""

from types import SimpleNamespace

import pytest

from custom_components.solax_modbus.number import SolaXModbusNumber
from custom_components.solax_modbus.plugin_solax import NUMBER_TYPES

KEYS = ("battery_charge_max_current", "battery_discharge_max_current")


def make_numbers(seriesnumber: str) -> list[SolaXModbusNumber]:
    hub = SimpleNamespace(seriesnumber=seriesnumber, data={}, numberEntities={}, sensorEntities={}, localsUpdated=False)
    return [SolaXModbusNumber("SolaX", hub, 1, {}, description) for description in NUMBER_TYPES if description.key in KEYS]


@pytest.mark.parametrize(
    ("seriesnumber", "limit"),
    [
        ("8021000000000", 160),  # X3-Aelio: 80 A per battery port x 2, register 0x24/0x25 sets the total
        ("H3BC000000000", 60),  # Gen5 X3 Ultra: unchanged
    ],
)
def test_battery_max_current_limit(seriesnumber: str, limit: int) -> None:
    numbers = make_numbers(seriesnumber)

    assert numbers
    assert all(number.native_max_value == limit for number in numbers)
