"""Tests for SolaX X3-MIC Gen1 write-only lock controls."""

from custom_components.solax_modbus.plugin_solax import BUTTON_TYPES, GEN, GEN2, MIC, X3, plugin_instance


def test_mic_gen1_lock_controls_use_write_only_register() -> None:
    """Expose explicit lock actions with the Gen1 register values."""
    descriptions = {description.key: description for description in BUTTON_TYPES}

    lock = descriptions["lock_settings"]
    unlock = descriptions["unlock_advanced_settings"]

    assert lock.register == 0x600
    assert lock.command == 0
    assert unlock.register == 0x600
    assert unlock.command == 6868


def test_mic_gen1_lock_controls_are_model_specific() -> None:
    """Do not replace readable lock-state controls on newer generations."""
    descriptions = {description.key: description for description in BUTTON_TYPES}
    gen1_type = MIC | GEN | X3
    gen2_type = MIC | GEN2 | X3

    for key in ("lock_settings", "unlock_advanced_settings"):
        description = descriptions[key]
        assert plugin_instance.matchInverterWithMask(gen1_type, description.allowedtypes, "MU502T") is True
        assert plugin_instance.matchInverterWithMask(gen2_type, description.allowedtypes, "MC806T") is False
