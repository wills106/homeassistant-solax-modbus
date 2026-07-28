from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from custom_components.solax_modbus.plugin_sofar import plugin_instance


@dataclass
class MockEntityDescription:
    native_min_value: int
    native_max_value: int


class MockNumberEntity:
    def __init__(self) -> None:
        self._attr_native_min_value = 0
        self._attr_native_max_value = 20000
        self.entity_description = MockEntityDescription(
            native_min_value=0,
            native_max_value=20000,
        )


def make_hub(parallel_setting: str, inverter_power_kw: int) -> Any:
    return SimpleNamespace(
        data={"parallel_masterslave": parallel_setting},
        inverterPowerKw=inverter_power_kw,
        numberEntities={"feedin_max_power": MockNumberEntity()},
    )


def test_parallel_master_uses_total_system_power_for_feedin_limit() -> None:
    hub = make_hub("Master", 40)

    assert plugin_instance.localDataCallback(hub) is True

    entity = hub.numberEntities["feedin_max_power"]
    assert entity._attr_native_min_value == 0
    assert entity._attr_native_max_value == 40000
    assert entity.entity_description.native_min_value == 0
    assert entity.entity_description.native_max_value == 40000


def test_single_or_slave_inverter_keeps_existing_feedin_limit() -> None:
    hub = make_hub("Slave", 100)

    assert plugin_instance.localDataCallback(hub) is True

    entity = hub.numberEntities["feedin_max_power"]
    assert entity._attr_native_max_value == 20000
    assert entity.entity_description.native_max_value == 20000
