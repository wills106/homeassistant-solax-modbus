"""X3-MIC G2 export-control bias settings: total and per-phase variants follow the Pgrid Control Mode."""

from typing import Any

from custom_components.solax_modbus.plugin_solax import MIC, NUMBER_TYPES, SELECT_TYPES, X3, plugin_instance


def _by_key(source: Any, key: str) -> Any:
    return next(d for d in source if d.key == key and d.allowedtypes & MIC and d.allowedtypes & X3)


def test_total_and_per_phase_follow_the_control_mode() -> None:
    for source, key in ((SELECT_TYPES, "pgrid_bias_total"), (NUMBER_TYPES, "pgrid_bias_power_total")):
        assert _by_key(source, key).active_when == {"pgrid_control_mode": ("Total",)}
    for source, key in ((SELECT_TYPES, "pgrid_bias_per_phase"), (NUMBER_TYPES, "pgrid_bias_power_per_phase")):
        assert _by_key(source, key).active_when == {"pgrid_control_mode": ("Per Phase",)}


def test_bias_power_accepts_the_app_range() -> None:
    for key in ("pgrid_bias_power_total", "pgrid_bias_power_per_phase"):
        number = _by_key(NUMBER_TYPES, key)
        assert (number.native_min_value, number.native_max_value) == (1, 1500)


def test_export_control_mode_and_power_limit() -> None:
    select = _by_key(SELECT_TYPES, "export_control_mode")
    number = _by_key(NUMBER_TYPES, "export_power_limit")

    assert select.register == 0x660
    assert select.device_group == number.device_group == "settings"
    assert select.option_dict == {0: "Disable", 1: "Meter"}
    assert number.register == 0x65C
    assert number.active_when == {"export_control_mode": ("Meter",)}
    assert (number.native_min_value, number.native_max_value) == (0, 60000)


def test_export_readbacks_match_the_observed_registers() -> None:
    sensors: list[Any] = list(plugin_instance.SENSOR_TYPES)
    readbacks = {str(d.key): d for d in sensors if d.allowedtypes & MIC and d.allowedtypes & X3}

    assert readbacks["export_control_mode"].register == 0x3D8
    assert readbacks["export_control_mode"].scale == {0: "Disable", 1: "Meter"}
    assert readbacks["export_power_limit"].device_group == "settings"
    assert "meter_enable" not in readbacks
    assert readbacks["export_power_limit"].register == 0x3C0
    assert "export_control_enable" not in readbacks


def test_readbacks_match_the_observed_registers() -> None:
    readbacks: dict[str, Any] = {}
    sensors: list[Any] = list(plugin_instance.SENSOR_TYPES)
    for description in sensors:
        if str(description.key).startswith("pgrid_") and description.allowedtypes & MIC:
            readbacks[str(description.key)] = description

    assert readbacks["pgrid_control_mode"].register == 0x3E3
    assert readbacks["pgrid_bias_total"].register == 0x3E5
    assert readbacks["pgrid_bias_per_phase"].register == 0x3E5
    assert readbacks["pgrid_bias_power_total"].register == 0x3E6
    assert readbacks["pgrid_bias_power_per_phase"].register == 0x3E7
    assert readbacks["pgrid_control_mode"].scale == {0: "Total", 1: "Per Phase"}


def test_export_control_and_safety_are_controls() -> None:
    for source, key in (
        (SELECT_TYPES, "export_control_mode"),
        (NUMBER_TYPES, "export_power_limit"),
        (SELECT_TYPES, "pgrid_control_mode"),
        (SELECT_TYPES, "pgrid_bias_total"),
        (SELECT_TYPES, "pgrid_bias_per_phase"),
        (NUMBER_TYPES, "pgrid_bias_power_total"),
        (NUMBER_TYPES, "pgrid_bias_power_per_phase"),
        (SELECT_TYPES, "safety_code_mic"),
    ):
        assert _by_key(source, key).entity_category is None
