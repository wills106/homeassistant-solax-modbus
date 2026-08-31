"""Tests for SOFAR HYD-EP pack-specific sensors."""

from custom_components.solax_modbus.plugin_sofar import BATTERY_SENSOR_TYPES, GEN, HYBRID, HYD_EP, X1, plugin_instance


def test_hyd_ep_pack_sensors_use_pack_specific_registers() -> None:
    """HYD-EP exposes its individual pack voltage and SOC registers."""
    descriptions = {description.key: description for description in BATTERY_SENSOR_TYPES}

    assert descriptions["pack_total_voltage"].register == 0x9079
    assert descriptions["pack_total_voltage"].scale == 0.1
    assert descriptions["pack_soc"].register == 0x907A
    assert descriptions["pack_soc"].scale == 0.1


def test_hyd_ep_pack_sensors_are_model_specific() -> None:
    """Do not expose HYD-EP pack registers on other SOFAR families."""
    pack_soc = next(description for description in BATTERY_SENSOR_TYPES if description.key == "pack_soc")
    hyd_ep_type = HYBRID | X1 | GEN | HYD_EP
    other_sofar_type = HYBRID | X1 | GEN

    assert plugin_instance.matchInverterWithMask(hyd_ep_type, pack_soc.allowedtypes, "SM2ES4") is True
    assert plugin_instance.matchInverterWithMask(other_sofar_type, pack_soc.allowedtypes, "SP1") is False


def test_hyd_ep_current_sensors_apply_model_specific_scale() -> None:
    """HYD-EP current values use 0.01 A without changing other models."""
    descriptions = {description.key: description for description in BATTERY_SENSOR_TYPES}

    for key in ("total_current", "pack_current"):
        description = descriptions[key]
        assert description.scale == 0.1
        assert description.read_scale_exceptions == [("SM2ES4", 0.1)]
