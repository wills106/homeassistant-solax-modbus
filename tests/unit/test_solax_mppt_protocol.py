"""The legacy Hybrid MPPT control is not documented by the ESS protocol."""

from types import SimpleNamespace

import pytest

from custom_components.solax_modbus.const import matches_modbus_protocol
from custom_components.solax_modbus.plugin_solax import (
    GEN4,
    GEN5,
    HYBRID,
    MIC,
    MPPT3,
    SELECT_TYPES,
    SENSOR_TYPES_MAIN,
    SWITCH_TYPES,
    X1,
    X3,
    plugin_instance,
)


@pytest.mark.parametrize("generation", [GEN4, GEN5])
@pytest.mark.parametrize("phases", [X1, X3])
@pytest.mark.parametrize(("version", "available"), [(None, True), (0, True), (1, True), (99, True), (100, False), (101, False)])
def test_hybrid_mppt_switch_and_readback_share_protocol_gate(generation: int, phases: int, version: int | None, available: bool) -> None:
    """Keep unknown/legacy profiles and exclude both halves of the ESS control."""
    hub = SimpleNamespace(modbus_protocol_version=version, data={})
    inverter_type = HYBRID | generation | phases
    for descriptions, register in ((SWITCH_TYPES, 0x48), (SENSOR_TYPES_MAIN, 0xBC)):
        matching = [
            description
            for description in descriptions
            if description.key == "mppt" and plugin_instance.matchInverterWithMask(inverter_type, description.allowedtypes)
        ]
        assert len(matching) == 1
        description = matching[0]
        assert description.register == register
        assert description.modbus_max == 99
        assert matches_modbus_protocol(hub, description) is available


@pytest.mark.parametrize("version", [None, 99, 100, 101])
def test_mic_mppt_control_is_unchanged(version: int | None) -> None:
    """MIC MPPT uses a separate register map and must not inherit the limit."""
    hub = SimpleNamespace(modbus_protocol_version=version, data={})
    for descriptions, register in ((SWITCH_TYPES, 0x602), (SENSOR_TYPES_MAIN, 0x382)):
        matching = [
            description
            for description in descriptions
            if description.key == "mppt" and plugin_instance.matchInverterWithMask(MIC | GEN4 | X1, description.allowedtypes)
        ]
        assert len(matching) == 1
        assert matching[0].register == register
        assert matching[0].modbus_max is None
        assert matches_modbus_protocol(hub, matching[0]) is True


def test_shadow_fix_controls_are_unchanged() -> None:
    """Do not confuse the legacy enable switch with the per-PV GMPPT levels."""
    hub = SimpleNamespace(modbus_protocol_version=100, data={})
    keys = {"shadow_fix_function_level_pv1_gmppt", "shadow_fix_function_level_pv2_gmppt", "shadow_fix3_enable"}
    matching = [
        description
        for description in SELECT_TYPES
        if description.key in keys and plugin_instance.matchInverterWithMask(HYBRID | GEN5 | X3 | MPPT3, description.allowedtypes)
    ]
    assert {description.key for description in matching} == keys
    assert all(matches_modbus_protocol(hub, description) for description in matching)
