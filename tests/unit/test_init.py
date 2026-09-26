"""Test solax_modbus setup process."""

from custom_components.solax_modbus.const import DOMAIN


def test_domain_constant() -> None:
    """Test that the domain constant is correct."""
    assert DOMAIN == "solax_modbus"
