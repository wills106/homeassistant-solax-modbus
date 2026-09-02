"""Tests for SOFAR battery-pack selection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.solax_modbus.plugin_sofar import battery_config


def selection_response(value: int) -> SimpleNamespace:
    """Return a successful one-register Modbus response."""
    return SimpleNamespace(registers=[value], isError=lambda: False)


def make_hub(*selection_values: int) -> SimpleNamespace:
    """Return a hub reporting the supplied battery selections."""
    return SimpleNamespace(
        _modbus_addr=1,
        async_read_holding_registers=AsyncMock(side_effect=[selection_response(value) for value in selection_values]),
        async_write_registers_single=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_select_battery_skips_write_when_pack_is_already_selected() -> None:
    """Do not write 0x9020 when 0x9044 already reports the requested pack."""
    config = battery_config()
    hub = make_hub(0)

    assert await config.select_battery(hub, batt_nr=0, batt_pack_nr=0) is True

    hub.async_write_registers_single.assert_not_awaited()
    assert config.selected_batt_nr == 0
    assert config.selected_batt_pack_nr == 0


@pytest.mark.asyncio
async def test_select_battery_writes_and_verifies_changed_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Write 0x9020 only when needed and verify the result through 0x9044."""
    config = battery_config()
    hub = make_hub(0, 0x0100)
    sleep = AsyncMock()
    monkeypatch.setattr("custom_components.solax_modbus.plugin_sofar.asyncio.sleep", sleep)

    assert await config.select_battery(hub, batt_nr=0, batt_pack_nr=1) is True

    hub.async_write_registers_single.assert_awaited_once_with(unit=1, address=0x9020, payload=0x0100)
    sleep.assert_awaited_once_with(0.3)
    assert config.selected_batt_nr == 0
    assert config.selected_batt_pack_nr == 1


@pytest.mark.asyncio
async def test_select_battery_contains_rejected_write() -> None:
    """A rejected pack-selection write must not abort platform setup."""
    config = battery_config()
    hub = make_hub(0)
    hub.async_write_registers_single.side_effect = RuntimeError("write rejected")

    assert await config.select_battery(hub, batt_nr=0, batt_pack_nr=1) is False

    assert config.selected_batt_nr is None
    assert config.selected_batt_pack_nr is None
