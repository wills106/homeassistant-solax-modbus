"""Regression coverage for TIGO TSI X1 (Gen4) serial-number detection."""

from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.solax_modbus.plugin_solax import GEN4, HYBRID, X1, plugin_instance


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("serial_number", "expected_model"),
    [
        ("63150012345678", "X1-TIGO-TSI-5.0kW"),
        ("63160012345678", "X1-TIGO-TSI-6.0kW"),
    ],
)
async def test_tigo_tsi_x1_detection(mock_hub: Any, serial_number: str, expected_model: str) -> None:
    """TIGO TSI X1 hybrids (rebranded SolaX X1-HYB-G4) are detected as Gen4 X1 hybrids."""
    plugin = replace(plugin_instance)
    mock_hub.data = {}
    with (
        patch("custom_components.solax_modbus.plugin_solax.async_read_serialnr", new=AsyncMock(return_value=serial_number)),
        patch("custom_components.solax_modbus.plugin_solax.async_read_inverter_firmware_info", new=AsyncMock()),
    ):
        inverter_type = await plugin.async_determineInverterType(mock_hub, {"read_eps": False, "read_pm": False})

    assert inverter_type == HYBRID | GEN4 | X1
    assert mock_hub.inverter_model == expected_model
