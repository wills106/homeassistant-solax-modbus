"""Regression coverage for Solinteg model detection (#2416)."""

import pytest

from custom_components.solax_modbus.plugin_solinteg import HYBRID, MPPT2, MPPT4, MPPT6, SENSOR_TYPES, X1, X3, _model_str, plugin_instance
from tests.conftest import MockHub, MockModbusResponse


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_code", "expected_type", "model_name", "mppt_count"),
    [
        (0x1E04, HYBRID | X3 | MPPT2, "MHT-10K-25", 2),
        (0x1F08, HYBRID | X1, "MHS-3K-30S", 1),
        (0x1F04, HYBRID | X1 | MPPT2, "MHS-5K-30D", 2),
        (0x2004, HYBRID | X3 | MPPT4, "MHT-50K-100", 4),
        (0x2800, HYBRID | X1, "M2HT-3K-30", 1),
        (0x2804, HYBRID | X1 | MPPT2, "M2HT-5K-30", 2),
        (0x2904, HYBRID | X3 | MPPT4, "M2HT-50K-150", 4),
        (0x2A03, HYBRID | X3 | MPPT2, "M2HT-10K-30", 2),
        (0x2A00, HYBRID | X3 | MPPT2, "unknown", 2),
        (0x2B00, HYBRID | X3 | MPPT6, "M2HT-75K-300", 6),
    ],
)
async def test_solinteg_model_detection(model_code: int, expected_type: int, model_name: str, mppt_count: int) -> None:
    """Read the model register and select existing battery, phase and MPPT entities."""
    hub = MockHub(modbus_addr=255)
    serial = b"A112601234567890"
    hub.configure_read(255, 10000, 8, MockModbusResponse([int.from_bytes(serial[i : i + 2], "big") for i in range(0, len(serial), 2)]))
    hub.configure_read(255, 10008, 1, MockModbusResponse([model_code]))
    plugin = plugin_instance.create_hub_instance()

    inverter_type = await plugin.async_determineInverterType(hub, {"read_eps": False, "read_dcb": False})

    assert inverter_type == expected_type
    assert plugin.inverter_model == model_name
    descriptions = {
        description.key: description for description in SENSOR_TYPES if plugin.matchInverterWithMask(inverter_type, description.allowedtypes)
    }
    assert descriptions["battery_soc"].register == 33000
    assert descriptions["battery_temperature"].register == 33003
    for phase in range(1, 4):
        assert (f"grid_current_l{phase}" in descriptions) is (phase == 1 or bool(expected_type & X3))
    for mppt in range(1, 7):
        for measurement in ("voltage", "current", "power"):
            assert (f"pv_{measurement}_{mppt}" in descriptions) is (mppt <= mppt_count)


@pytest.mark.parametrize("model_code", [0x2A00, 0x2A01, 0x2A02, 0x2A04, 0x2AFF])
def test_unconfirmed_series_42_model_names_remain_unknown(model_code: int) -> None:
    """Do not guess the unconfirmed model names surrounding index 3."""
    assert _model_str(model_code) == "unknown"
