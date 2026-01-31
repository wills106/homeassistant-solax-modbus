import pytest

from custom_components.solax_modbus.plugin_solax import (
    AC,
    EPS,
    GEN3,
    GEN4,
    HYBRID,
    X3,
)
from custom_components.solax_modbus.plugin_solax import (
    plugin_instance as solax_plugin,
)


def test_match_inverter_with_mask_exact():
    # Inverter: Gen4 Hybrid X3
    inverter = GEN4 | HYBRID | X3

    # Entity requires: Gen4 Hybrid X3
    mask = GEN4 | HYBRID | X3
    assert solax_plugin.matchInverterWithMask(inverter, mask) is True


def test_match_inverter_with_mask_partial():
    # Inverter: Gen4 Hybrid X3
    inverter = GEN4 | HYBRID | X3

    # Entity requires: Hybrid (should match any Gen/Phase)
    # Note: If mask only specifies HYBRID, other groups (GEN, X) are 0.
    # Logic: (mask & GROUP == 0) -> True (wildcard for that group)
    mask = HYBRID
    assert solax_plugin.matchInverterWithMask(inverter, mask) is True


def test_match_inverter_with_mask_mismatch_type():
    # Inverter: Gen4 Hybrid X3
    inverter = GEN4 | HYBRID | X3

    # Entity requires: AC
    mask = AC
    assert solax_plugin.matchInverterWithMask(inverter, mask) is False


def test_match_inverter_with_mask_mismatch_gen():
    # Inverter: Gen4 Hybrid X3
    inverter = GEN4 | HYBRID | X3

    # Entity requires: Gen3
    mask = GEN3 | HYBRID | X3
    assert solax_plugin.matchInverterWithMask(inverter, mask) is False


def test_match_inverter_with_mask_or_condition():
    # Inverter: Gen4 Hybrid X3
    inverter = GEN4 | HYBRID | X3

    # Entity requires: Gen3 OR Gen4
    mask = GEN3 | GEN4
    assert solax_plugin.matchInverterWithMask(inverter, mask) is True


def test_match_inverter_with_mask_eps():
    # Inverter: Gen4 Hybrid X3 with EPS
    inverter = GEN4 | HYBRID | X3 | EPS

    # Entity requires: EPS
    mask = EPS
    assert solax_plugin.matchInverterWithMask(inverter, mask) is True

    # Inverter without EPS
    inverter_no_eps = GEN4 | HYBRID | X3
    assert solax_plugin.matchInverterWithMask(inverter_no_eps, mask) is False


@pytest.mark.asyncio
async def test_determine_inverter_type_solax(mock_hub):
    # Test detection logic using MockHub

    # Simulate a Gen4 X3 Hybrid serial number: H34T...
    # H = 0x48, 3 = 0x33, 4 = 0x34, T = 0x54
    # Serial is read as 7 registers (14 chars) usually
    # Let's mock the response for address 0 (or wherever it reads)
    # Solax plugin reads from 0x0 -> count 7

    # "H34T10H..." ->
    # Reg 0: 'H3' = 0x4833
    # Reg 1: '4T' = 0x3454
    # ...

    mock_registers = [0x4833, 0x3454, 0x3130, 0x4831, 0x3233, 0x3435, 0x3637]
    mock_hub.configure_read(1, 0, 7, type("MockResponse", (), {"registers": mock_registers, "isError": lambda: False}))

    # Config dict
    config = {"read_eps": False, "read_dcb": False}

    # Run detection
    inverter_type = await solax_plugin.async_determineInverterType(mock_hub, config)

    # H34T should match: HYBRID | X3 | GEN4
    expected = HYBRID | X3 | GEN4

    # Note: The exact return value depends on the implementation in plugin_solax.py
    # Let's check what H34T maps to in the code...
    # It maps to: HYBRID | X3 | GEN4

    assert inverter_type == expected
