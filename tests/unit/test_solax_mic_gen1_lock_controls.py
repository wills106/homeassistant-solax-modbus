"""Tests for SolaX X3-MIC Gen1 write-only lock controls."""

from custom_components.solax_modbus.plugin_solax import BUTTON_TYPES, GEN, GEN2, MIC, X3, plugin_instance


def test_mic_gen1_lock_controls_use_write_only_register() -> None:
    """Expose explicit lock actions with the Gen1 register values."""
    lock = next(filter(lambda description: description.key == "lock_settings", BUTTON_TYPES))
    unlock = next(filter(lambda description: description.key == "unlock_advanced_settings", BUTTON_TYPES))

    assert lock.register == 0x600
    assert lock.command == 0
    assert unlock.register == 0x600
    assert unlock.command == 6868


def test_mic_gen1_lock_controls_are_model_specific() -> None:
    """Do not replace readable lock-state controls on newer generations."""
    gen1_type = MIC | GEN | X3
    gen2_type = MIC | GEN2 | X3

    for key in ("lock_settings", "unlock_advanced_settings"):
        description = next(filter(lambda description: description.key == key, BUTTON_TYPES))
        assert plugin_instance.matchInverterWithMask(gen1_type, description.allowedtypes, "MU502T") is True
        assert plugin_instance.matchInverterWithMask(gen2_type, description.allowedtypes, "MC806T") is False
