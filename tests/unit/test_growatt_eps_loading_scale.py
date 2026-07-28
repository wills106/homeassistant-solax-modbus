from custom_components.solax_modbus.plugin_growatt import SENSOR_TYPES


def test_gen4_eps_loading_uses_tenths_percent_scale() -> None:
    descriptions = [description for description in SENSOR_TYPES if description.key == "eps_loading" and description.register == 3160]

    assert len(descriptions) == 1
    description = descriptions[0]
    scale = description.scale
    rounding = description.rounding
    assert isinstance(scale, (int, float))
    assert isinstance(rounding, int)
    assert scale == 0.1
    assert rounding == 1
    assert round(60 * scale, rounding) == 6.0
