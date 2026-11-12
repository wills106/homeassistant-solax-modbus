"""Direct VPP mode 2/3 charge/discharge power follows the inverter rating, not a fixed ±30 kW."""

from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.solax_modbus.number import SolaXModbusNumber
from custom_components.solax_modbus.plugin_solax import NUMBER_TYPES, plugin_instance

KEY = "remotecontrol_charge_discharge_power_direct"


def make_hub(seriesnumber: str, parallel_setting: str = "Free", inverter_power_kw: float = 0) -> Any:
    """Build real number entities for the direct power and the mode 1 active power."""
    hub = SimpleNamespace(
        data={"parallel_setting": parallel_setting},
        inverterPowerKw=inverter_power_kw,
        seriesnumber=seriesnumber,
        numberEntities={},
        sensorEntities={},
        localsUpdated=False,
    )
    for key in (KEY, "remotecontrol_active_power"):
        description = next(item for item in NUMBER_TYPES if item.key == key)
        hub.numberEntities[key] = SolaXModbusNumber("SolaX", hub, 1, {}, description)
    return hub


@pytest.mark.parametrize(
    ("seriesnumber", "limit"),
    [
        ("8021000000000", 60000),  # X3-Aelio 60 kW
        ("H3E1000000000", 15000),  # Gen3 X3 10 kW
        ("ZZZZZZ0000000", 30000),  # not in MAX_EXPORT: unchanged default
    ],
)
def test_direct_charge_discharge_power_uses_rated_power(seriesnumber: str, limit: int) -> None:
    number = make_hub(seriesnumber).numberEntities[KEY]

    assert number.native_min_value == -limit
    assert number.native_max_value == limit


def test_direct_charge_discharge_power_accepts_more_than_30_kw_on_aelio() -> None:
    number = make_hub("8021000000000").numberEntities[KEY]

    assert number.native_min_value <= -45000
    assert 45000 <= number.native_max_value


@pytest.mark.parametrize("parallel_setting", ["Free", "Slave"])
def test_callback_keeps_rated_power_outside_parallel_master(parallel_setting: str) -> None:
    hub = make_hub("H34A1500000000", parallel_setting, inverter_power_kw=45)

    plugin_instance.localDataCallback(hub)

    number = hub.numberEntities[KEY]
    assert number.native_min_value == -16500
    assert number.native_max_value == 16500


def test_parallel_master_uses_system_power_for_direct_charge_discharge_power() -> None:
    hub = make_hub("H34A1500000000", "Master", inverter_power_kw=45)

    plugin_instance.localDataCallback(hub)

    for key in (KEY, "remotecontrol_active_power"):
        number = hub.numberEntities[key]
        assert number.native_min_value == -45000
        assert number.native_max_value == 45000
