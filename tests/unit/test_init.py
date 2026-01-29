"""Test solax_modbus setup process."""

from custom_components.solax_modbus.const import DOMAIN


async def test_domain_constant(hass):
    """Test that the domain constant is correct."""
    assert DOMAIN == "solax_modbus"
