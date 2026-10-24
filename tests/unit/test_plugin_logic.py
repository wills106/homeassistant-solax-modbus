from typing import Any

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


def test_match_inverter_with_mask_exact() -> None:
    # Inverter: Gen4 Hybrid X3
    inverter = GEN4 | HYBRID | X3

    # Entity requires: Gen4 Hybrid X3
    mask = GEN4 | HYBRID | X3
    assert solax_plugin.matchInverterWithMask(inverter, mask) is True


def test_match_inverter_with_mask_partial() -> None:
    # Inverter: Gen4 Hybrid X3
    inverter = GEN4 | HYBRID | X3

    # Entity requires: Hybrid (should match any Gen/Phase)
    # Note: If mask only specifies HYBRID, other groups (GEN, X) are 0.
    # Logic: (mask & GROUP == 0) -> True (wildcard for that group)
    mask = HYBRID
    assert solax_plugin.matchInverterWithMask(inverter, mask) is True


def test_match_inverter_with_mask_mismatch_type() -> None:
    # Inverter: Gen4 Hybrid X3
    inverter = GEN4 | HYBRID | X3

    # Entity requires: AC
    mask = AC
    assert solax_plugin.matchInverterWithMask(inverter, mask) is False


def test_match_inverter_with_mask_mismatch_gen() -> None:
    # Inverter: Gen4 Hybrid X3
    inverter = GEN4 | HYBRID | X3

    # Entity requires: Gen3
    mask = GEN3 | HYBRID | X3
    assert solax_plugin.matchInverterWithMask(inverter, mask) is False


def test_match_inverter_with_mask_or_condition() -> None:
    # Inverter: Gen4 Hybrid X3
    inverter = GEN4 | HYBRID | X3

    # Entity requires: Gen3 OR Gen4
    mask = GEN3 | GEN4
    assert solax_plugin.matchInverterWithMask(inverter, mask) is True


def test_match_inverter_with_mask_eps() -> None:
    # Inverter: Gen4 Hybrid X3 with EPS
    inverter = GEN4 | HYBRID | X3 | EPS

    # Entity requires: EPS
    mask = EPS
    assert solax_plugin.matchInverterWithMask(inverter, mask) is True

    # Inverter without EPS
    inverter_no_eps = GEN4 | HYBRID | X3
    assert solax_plugin.matchInverterWithMask(inverter_no_eps, mask) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("serial_number", ["H34T10H1234567", "N34A10K1234567"])
async def test_determine_inverter_type_solax(mock_hub: Any, serial_number: str) -> None:
    # Exercise the Gen4 X3 detection path for both SolaX and Nord OEM prefixes.
    # Modbus exposes the 14-character serial as seven big-endian 16-bit registers.
    serial_bytes = serial_number.encode("ascii")
    mock_registers = [int.from_bytes(serial_bytes[index : index + 2], "big") for index in range(0, 14, 2)]
    mock_hub.configure_read(1, 0, 7, type("MockResponse", (), {"registers": mock_registers, "isError": lambda: False}))

    # Config dict
    config = {"read_eps": False, "read_dcb": False}

    # Run detection
    inverter_type = await solax_plugin.async_determineInverterType(mock_hub, config)

    expected = HYBRID | X3 | GEN4

    assert inverter_type == expected
    assert mock_hub.inverter_model == "X3-Hybrid-10kW"


def test_parallel_master_scales_active_power(mock_hub: Any) -> None:
    """
    Verify parallel Master inverters retain their active-power limits.
    """
    from dataclasses import dataclass

    from custom_components.solax_modbus.plugin_solax import plugin_instance

    # Setup: Mock parallel Master with 45kW capacity
    mock_hub.inverterPowerKw = 45
    mock_hub.data = {"parallel_setting": "Master"}

    # Create mock entity description
    @dataclass
    class MockEntityDescription:
        native_min_value: int
        native_max_value: int

    # Create mock entity
    class MockEntity:
        def __init__(self) -> None:
            self._attr_native_min_value = 0
            self._attr_native_max_value = 30000  # Bug: stuck at default
            self.entity_description = MockEntityDescription(native_min_value=0, native_max_value=30000)

    mock_hub.numberEntities = {"remotecontrol_active_power": MockEntity()}
    mock_hub.sensorEntities = {}

    # Execute: Trigger the callback
    plugin_instance.localDataCallback(mock_hub)

    # Assert: Active power should scale to ±45kW, independently of import limit.
    entity = mock_hub.numberEntities["remotecontrol_active_power"]
    assert entity._attr_native_min_value == -45000
    assert entity._attr_native_max_value == 45000, (
        f"Parallel Master with 45kW capacity should scale active power to 45000W, got {entity._attr_native_max_value}W"
    )
