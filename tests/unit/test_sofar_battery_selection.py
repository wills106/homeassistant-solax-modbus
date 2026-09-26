"""Tests for SOFAR battery-pack selection."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (None, "No response from BMS selection register 0x9044"),
        (SimpleNamespace(isError=lambda: True), "Modbus error reading BMS selection register 0x9044"),
        (TimeoutError("read timed out"), "Cannot read BMS selection register 0x9044"),
        (SimpleNamespace(registers=[], isError=lambda: False), "Cannot read BMS selection register 0x9044"),
    ],
    ids=["no-response", "modbus-error", "exception", "empty-response"],
)
async def test_end_validation_contains_read_failures(response: Any, message: str, caplog: pytest.LogCaptureFixture) -> None:
    """An unreadable selection rejects the snapshot instead of raising a poll exception."""
    config = battery_config(batt_pack_serials={0: {1: "PACK-1"}})
    hub = make_hub()
    hub.async_read_holding_registers.side_effect = [response]

    assert await config.check_battery_on_end(hub, {}, {"pack_serial_number": "PACK-1"}, "", 0, 1) is False

    assert message in caplog.text
    assert "battery 0 pack 1: register 0x9044 expected 0x0100, actual selection unavailable" in caplog.text
    hub.async_write_registers_single.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selection", "new_data", "registered_serials", "message"),
    [
        (0, {"b1_pack_serial_number": "PACK-2"}, {0: {1: "PACK-1"}}, "expected 0x0100, actual selection 0x0000"),
        (0x0100, {}, {0: {1: "PACK-1"}}, "missing serial number (b1_pack_serial_number)"),
        (0x0100, {"b1_pack_serial_number": None}, {0: {1: "PACK-1"}}, "missing serial number"),
    ],
    ids=["wrong-pack", "missing-serial", "null-serial"],
)
async def test_end_validation_reports_rejection_reason(
    selection: int,
    new_data: dict[str, Any],
    registered_serials: dict[int, dict[int, str]],
    message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keep pack identity checks and explain which one failed."""
    config = battery_config(batt_pack_serials=deepcopy(registered_serials))
    hub = make_hub(selection)

    assert await config.check_battery_on_end(hub, {}, new_data, "b1_", 0, 1) is False

    assert "BMS validation after reading failed for battery 0 pack 1" in caplog.text
    assert message in caplog.text
    assert config.batt_pack_serials == registered_serials
    hub.async_write_registers_single.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("registered_serials", [{0: {1: "OLD-PACK"}}, {}], ids=["replaced-pack", "unregistered-pack"])
async def test_valid_selection_refreshes_serial_metadata(registered_serials: dict[int, dict[int, str]]) -> None:
    """Old or absent device metadata must not block a correctly selected pack."""
    config = battery_config(batt_pack_serials=registered_serials)
    hub = make_hub(0x0100, 0x0100)

    assert await config.check_battery_on_start(hub, {}, "b1_", 0, 1) is True
    assert await config.check_battery_on_end(hub, {}, {"b1_pack_serial_number": "NEW-PACK"}, "b1_", 0, 1) is True
    assert await config.get_batt_pack_serial(hub, 0, 1) == "NEW-PACK"
    assert hub.async_read_holding_registers.await_count == 2
    hub.async_write_registers_single.assert_not_awaited()


@pytest.mark.asyncio
async def test_end_validation_accepts_matching_pack_and_serial(caplog: pytest.LogCaptureFixture) -> None:
    """Successful validation is unchanged and does not emit warnings."""
    config = battery_config(batt_pack_serials={0: {1: "PACK-1"}})
    hub = make_hub(0x0100)

    assert await config.check_battery_on_end(hub, {}, {"b1_pack_serial_number": "PACK-1"}, "b1_", 0, 1) is True

    hub.async_read_holding_registers.assert_awaited_once_with(unit=1, address=0x9044, count=1)
    assert not caplog.records


@pytest.mark.asyncio
async def test_start_validation_retries_mismatched_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve the existing selection retry delay."""
    config = battery_config(batt_pack_serials={0: {1: "PACK-1"}})
    hub = make_hub(0, 0x0100)
    sleep = AsyncMock()
    monkeypatch.setattr("custom_components.solax_modbus.plugin_sofar.asyncio.sleep", sleep)

    assert await config.check_battery_on_start(hub, {}, "", 0, 1) is True

    sleep.assert_awaited_once_with(0.3)
    assert hub.async_read_holding_registers.await_count == 2


@pytest.mark.asyncio
async def test_start_validation_contains_read_exception(caplog: pytest.LogCaptureFixture) -> None:
    """Exhausted selection reads skip the pack instead of raising."""
    config = battery_config(batt_pack_serials={0: {1: "PACK-1"}})
    hub = make_hub()
    hub.async_read_holding_registers.side_effect = TimeoutError("read timed out")

    assert await config.check_battery_on_start(hub, {}, "", 0, 1) is False

    assert hub.async_read_holding_registers.await_count == 10
    assert "BMS validation before reading failed for battery 0 pack 1" in caplog.text


@pytest.mark.asyncio
async def test_validation_does_not_swallow_task_cancellation() -> None:
    """Allow integration shutdown to cancel a pending BMS validation."""
    config = battery_config(batt_pack_serials={0: {1: "PACK-1"}})
    hub = make_hub()
    hub.async_read_holding_registers.side_effect = asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await config.check_battery_on_end(hub, {}, {}, "", 0, 1)
