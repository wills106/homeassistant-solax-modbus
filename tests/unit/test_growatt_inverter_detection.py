import logging
from typing import Any

import pytest

from custom_components.solax_modbus.plugin_growatt import AC, GEN3, GEN4, HYBRID, PV, X1
from custom_components.solax_modbus.plugin_growatt import plugin_instance as growatt_plugin


class GrowattResponse:
    def __init__(self, value: str | None) -> None:
        encoded = (value or "").encode("ascii").ljust(10, b"\x00")
        self.registers = [int.from_bytes(encoded[offset : offset + 2], byteorder="big") for offset in range(0, 10, 2)]

    def isError(self) -> bool:
        return False


class GrowattHub:
    def __init__(self, responses: dict[int, str | None]) -> None:
        self.name = "Growatt"
        self._modbus_addr = 1
        self.seriesnumber: str | None = None
        self.responses = responses
        self.read_addresses: list[int] = []

    async def async_read_holding_registers(self, unit: int, address: int, count: int) -> GrowattResponse:
        assert unit == self._modbus_addr
        assert count == 5
        self.read_addresses.append(address)
        return GrowattResponse(self.responses.get(address))


CONFIG: dict[str, Any] = {"read_eps": False, "read_dcb": False}


@pytest.mark.asyncio
async def test_spa_serial_register_is_checked_after_unknown_identifiers() -> None:
    hub = GrowattHub(
        {
            3001: "NOTAMODEL1",
            209: "ALSOUNKNWN",
            23: "WPDBN4200S",
            9: "RH1.0 ZCAA",
        }
    )

    invertertype = await growatt_plugin.async_determineInverterType(hub, CONFIG)

    assert invertertype == AC | GEN3 | X1
    assert hub.seriesnumber == "WPDBN4200S"
    assert hub.read_addresses == [3001, 209, 23]


@pytest.mark.asyncio
async def test_spa_firmware_is_used_when_serial_is_unavailable() -> None:
    hub = GrowattHub(
        {
            3001: "NOTAMODEL1",
            209: None,
            23: None,
            9: "RH1.0 ZCAA",
        }
    )

    invertertype = await growatt_plugin.async_determineInverterType(hub, CONFIG)

    assert invertertype == AC | GEN3 | X1
    assert hub.seriesnumber == "RH1.0 ZCAA"
    assert hub.read_addresses == [3001, 209, 23, 9]


@pytest.mark.asyncio
async def test_known_serial_still_stops_detection_at_first_register() -> None:
    hub = GrowattHub(
        {
            3001: "XTD1234567",
            209: "NOTREAD001",
            23: "NOTREAD002",
            9: "NOTREAD003",
        }
    )

    invertertype = await growatt_plugin.async_determineInverterType(hub, CONFIG)

    assert invertertype == PV | GEN4 | X1
    assert hub.seriesnumber == "XTD1234567"
    assert hub.read_addresses == [3001]


@pytest.mark.asyncio
async def test_known_secondary_serial_is_not_blocked_by_unknown_primary_value() -> None:
    hub = GrowattHub(
        {
            3001: "NOTAMODEL1",
            209: "HJU1234567",
        }
    )

    invertertype = await growatt_plugin.async_determineInverterType(hub, CONFIG)

    assert invertertype == HYBRID | GEN4 | X1
    assert hub.seriesnumber == "HJU1234567"
    assert hub.read_addresses == [3001, 209]


@pytest.mark.asyncio
async def test_existing_firmware_fallback_is_preserved_without_probe_warnings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.solax_modbus.plugin_growatt")
    hub = GrowattHub(
        {
            9: "GH1.0 ZAAa",
        }
    )

    invertertype = await growatt_plugin.async_determineInverterType(hub, CONFIG)

    assert invertertype == PV | GEN4 | X1
    assert hub.seriesnumber == "GH1.0 ZAAa"
    assert hub.read_addresses == [3001, 209, 23, 9]
    assert "no inverter identifier at 0x17; other address may succeed" in caplog.text
    assert not [
        record for record in caplog.records if record.name == "custom_components.solax_modbus.plugin_growatt" and record.levelno >= logging.WARNING
    ]
