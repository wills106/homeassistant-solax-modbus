"""The X3-MIC G2 parallel settings live in the Parallel sub-device, switched by the Parallel Mode option."""

from typing import Any

from custom_components.solax_modbus.plugin_solax import (
    GEN2,
    MIC,
    PM,
    SELECT_TYPES,
    SWITCH_TYPES,
    X3,
    plugin_instance,
)

KEYS = {"parallel_enable_mic", "parallel_number", "master_or_slave", "parallel_disconnect_off", "parallel_reconnect_on"}


def _descriptions() -> list[Any]:
    found: list[Any] = [*SELECT_TYPES, *SWITCH_TYPES, *plugin_instance.SENSOR_TYPES]
    return [d for d in found if d.key in KEYS and d.allowedtypes & MIC]


def test_parallel_entities_are_in_the_parallel_group() -> None:
    descriptions = _descriptions()

    assert {d.key for d in descriptions} == KEYS
    assert all(d.device_group == "pm" for d in descriptions)


def test_parallel_entities_follow_the_parallel_mode_option() -> None:
    for description in _descriptions():
        assert plugin_instance.matchInverterWithMask(MIC | GEN2 | X3 | PM, description.allowedtypes, "MC208T") is True
        assert plugin_instance.matchInverterWithMask(MIC | GEN2 | X3, description.allowedtypes, "MC208T") is False


def test_parallel_number_offers_zero() -> None:
    select = next(d for d in SELECT_TYPES if d.key == "parallel_number" and d.allowedtypes & MIC)

    assert select.option_dict == {i: str(i) for i in range(7)}
