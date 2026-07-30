"""Tests for atomic polling snapshots."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.solax_modbus import PendingWrite, SolaXModbusHub
from custom_components.solax_modbus.const import REGISTER_U16, PollOutcome


def make_hub() -> Any:
    """Build the minimal hub state required by polling tests."""
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "test"
    hub.data = {"_repeatUntil": {}, "raw": 1}
    hub.computedSensors = {}
    hub.computedEntities = {}
    hub.sensorEntities = {}
    hub.writeLocals = {}
    hub.writequeue = {}
    hub.localsUpdated = False
    hub.localsLoaded = True
    hub.plugin = SimpleNamespace(
        isAwake=Mock(return_value=True),
        localDataCallback=Mock(return_value=True),
    )
    hub._poll_data_lock = asyncio.Lock()
    hub.slowdown = 1
    return hub


def make_group(*, follow_up: Any = None) -> Any:
    """Build a polling group with two holding-register blocks."""
    return SimpleNamespace(
        holdingBlocks=[
            SimpleNamespace(start=1),
            SimpleNamespace(start=2),
        ],
        inputBlocks=[],
        readPreparation=None,
        readFollowUp=follow_up,
        publish_updates=False,
        sensors=[],
    )


def prepare_communication_diagnostics(hub: Any) -> None:
    """Add the minimal communication diagnostic state to a test hub."""
    hub._comm_recent_outcomes = []
    hub._comm_poll_durations = []
    hub._comm_overrun_count = 0
    hub._comm_recovery_active = False
    hub._comm_last_block_failure_time = None
    hub.bad_regs = {"holding": set(), "input": set()}


@pytest.mark.asyncio
async def test_failed_group_discards_all_partial_values() -> None:
    hub = make_hub()
    group = make_group()
    computed_sensor = Mock()
    hub.computedSensors["computed"] = SimpleNamespace(
        key="computed",
        internal=False,
        value_function=lambda initval, descr, data: data["raw"] * 2,
    )
    hub.sensorEntities["computed"] = computed_sensor

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> bool:
        data["raw"] = block.start * 10
        return bool(block.start == 1)

    hub.async_read_modbus_block = read_block
    original_data_object = hub.data

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.FAILED
    assert hub.data is original_data_object
    assert hub.data["raw"] == 1
    assert "computed" not in hub.data
    assert group.publish_updates is False
    computed_sensor.modbus_data_updated.assert_not_called()


@pytest.mark.asyncio
async def test_tolerated_block_failure_commits_rest_of_snapshot() -> None:
    hub = make_hub()
    hub.data["unavailable"] = 5
    group = make_group()

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> bool:
        if block.start == 1:
            data["raw"] = 10
        else:
            data.pop("unavailable", None)
        return True

    hub.async_read_modbus_block = read_block

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.SUCCESS
    assert hub.data["raw"] == 10
    assert "unavailable" not in hub.data
    assert group.publish_updates is True


@pytest.mark.asyncio
async def test_successful_awake_poll_retries_queued_sleep_write() -> None:
    hub = make_hub()
    group = make_group()
    request = PendingWrite(
        unit=2,
        address=36,
        payload=40000,
        register_data_type=REGISTER_U16,
    )
    hub.writequeue[(request.unit, request.address)] = request
    hub.async_read_modbus_block = AsyncMock(return_value=True)
    hub.async_lowlevel_write_register = AsyncMock(return_value=SimpleNamespace(isError=lambda: False))

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.SUCCESS
    hub.async_lowlevel_write_register.assert_awaited_once_with(
        unit=2,
        address=36,
        payload=40000,
        register_data_type=REGISTER_U16,
    )
    assert hub.writequeue == {}


@pytest.mark.asyncio
async def test_successful_group_commits_raw_and_computed_values_together() -> None:
    hub = make_hub()
    computed_sensor = Mock()
    follow_up_observations: list[tuple[int, int, int]] = []

    async def follow_up(old_data: dict[str, Any], new_data: dict[str, Any]) -> bool:
        follow_up_observations.append((old_data["raw"], new_data["raw"], hub.data["raw"]))
        return True

    group = make_group(follow_up=follow_up)
    hub.computedSensors["computed"] = SimpleNamespace(
        key="computed",
        internal=False,
        value_function=lambda initval, descr, data: data["raw"] * 2,
    )
    hub.sensorEntities["computed"] = computed_sensor

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> bool:
        data["raw"] = block.start
        return True

    hub.async_read_modbus_block = read_block
    original_data_object = hub.data

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.SUCCESS
    assert follow_up_observations == [(1, 2, 1)]
    assert hub.data is original_data_object
    assert hub.data["raw"] == 2
    assert hub.data["computed"] == 4
    assert group.publish_updates is True
    computed_sensor.modbus_data_updated.assert_called_once_with()


@pytest.mark.asyncio
async def test_failed_follow_up_discards_snapshot_without_publishing() -> None:
    hub = make_hub()
    computed_sensor = Mock()
    group = make_group(follow_up=AsyncMock(return_value=False))
    hub.computedSensors["computed"] = SimpleNamespace(
        key="computed",
        internal=False,
        value_function=lambda initval, descr, data: data["raw"] * 2,
    )
    hub.sensorEntities["computed"] = computed_sensor

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> bool:
        data["raw"] = 9
        return True

    hub.async_read_modbus_block = read_block

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.DISCARDED
    assert hub.data["raw"] == 1
    assert "computed" not in hub.data
    assert group.publish_updates is False
    computed_sensor.modbus_data_updated.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_read_preparation_returns_skipped() -> None:
    hub = make_hub()
    group = make_group()
    group.readPreparation = AsyncMock(return_value=False)
    hub.async_read_modbus_block = AsyncMock()

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.SKIPPED
    assert group.publish_updates is False
    hub.async_read_modbus_block.assert_not_awaited()


def test_snapshot_commit_preserves_concurrent_local_change() -> None:
    hub = make_hub()
    previous_data = {"_repeatUntil": {}, "raw": 1, "removed": 5}
    new_data = {"_repeatUntil": {}, "raw": 2, "added": 7}
    hub.data = {"_repeatUntil": {}, "raw": 99, "removed": 5}

    hub._commit_poll_snapshot(previous_data, new_data)

    assert hub.data["raw"] == 99
    assert hub.data["added"] == 7
    assert "removed" not in hub.data


@pytest.mark.asyncio
async def test_group_reads_are_serialized() -> None:
    hub = make_hub()
    active_reads = 0
    maximum_active_reads = 0

    async def read_group(group: Any) -> PollOutcome:
        nonlocal active_reads, maximum_active_reads
        active_reads += 1
        maximum_active_reads = max(maximum_active_reads, active_reads)
        await asyncio.sleep(0)
        active_reads -= 1
        group.publish_updates = True
        return PollOutcome.SUCCESS

    hub.async_read_modbus_registers_all = read_group
    first_group = make_group()
    second_group = make_group()

    first_result, second_result = await asyncio.gather(
        hub.async_read_modbus_data(first_group),
        hub.async_read_modbus_data(second_group),
    )

    assert first_result is PollOutcome.SUCCESS
    assert second_result is PollOutcome.SUCCESS
    assert maximum_active_reads == 1


@pytest.mark.asyncio
async def test_successful_but_discarded_snapshot_does_not_publish_group() -> None:
    hub = make_hub()
    sensor = Mock()
    group = make_group()
    group.sensors = [sensor]
    interval_group = SimpleNamespace(device_groups={"test": group})
    hub.blocks_changed = False
    hub.cyclecount = 1
    hub.sleepnone = []
    hub.sleepzero = []

    async def read_group(current_group: Any) -> PollOutcome:
        current_group.publish_updates = False
        return PollOutcome.DISCARDED

    hub.async_read_modbus_data = read_group

    result, updated_sensors = await hub._refresh_interval_group_once(interval_group)

    assert result is PollOutcome.DISCARDED
    assert updated_sensors == 0
    sensor.modbus_data_updated.assert_not_called()


@pytest.mark.asyncio
async def test_slowdown_skip_does_not_read_or_change_slowdown() -> None:
    hub = make_hub()
    hub.blocks_changed = False
    hub.cyclecount = 1
    hub.slowdown = 10
    hub.sleepnone = []
    hub.sleepzero = []
    hub.async_read_modbus_data = AsyncMock(return_value=PollOutcome.SUCCESS)
    interval_group = SimpleNamespace(device_groups={"test": make_group()})

    outcome, updated_sensors = await hub._refresh_interval_group_once(interval_group)

    assert outcome is PollOutcome.SKIPPED
    assert updated_sensors == 0
    assert hub.slowdown == 10
    hub.async_read_modbus_data.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "group_outcomes",
    [
        [PollOutcome.SUCCESS, PollOutcome.FAILED],
        [PollOutcome.FAILED, PollOutcome.SUCCESS],
    ],
)
async def test_any_failed_device_group_enables_slowdown_regardless_of_order(group_outcomes: list[PollOutcome]) -> None:
    hub = make_hub()
    hub.blocks_changed = False
    hub.cyclecount = 10
    hub.sleepnone = []
    hub.sleepzero = []
    hub.async_read_modbus_data = AsyncMock(side_effect=group_outcomes)
    interval_group = SimpleNamespace(
        device_groups={
            "first": make_group(),
            "second": make_group(),
        }
    )

    outcome, _updated_sensors = await hub._refresh_interval_group_once(interval_group)

    assert outcome is PollOutcome.FAILED
    assert hub.slowdown == 10


@pytest.mark.asyncio
async def test_successful_aggregate_restores_normal_polling_after_all_groups() -> None:
    hub = make_hub()
    hub.blocks_changed = False
    hub.cyclecount = 1
    hub.slowdown = 10
    hub.sleepnone = []
    hub.sleepzero = []
    hub.async_read_modbus_data = AsyncMock(side_effect=[PollOutcome.DISCARDED, PollOutcome.SUCCESS])
    interval_group = SimpleNamespace(
        device_groups={
            "discarded": make_group(),
            "success": make_group(),
        }
    )

    outcome, _updated_sensors = await hub._refresh_interval_group_once(interval_group, bypass_slowdown=True)

    assert outcome is PollOutcome.SUCCESS
    assert hub.slowdown == 1


def test_skipped_cycles_are_not_recorded_as_communication_successes() -> None:
    hub = make_hub()
    prepare_communication_diagnostics(hub)

    for _ in range(5):
        hub._record_poll_cycle(PollOutcome.FAILED, elapsed=0.1, interval=15)
    for _ in range(9):
        hub._record_poll_cycle(PollOutcome.SKIPPED, elapsed=0.0, interval=15)

    assert hub._comm_recent_outcomes == [PollOutcome.FAILED] * 5
    assert len(hub._comm_poll_durations) == 5
    assert hub.data["communication_success_rate"] == 0.0
    assert hub.data["communication_health"] == "Offline"


def test_discarded_snapshot_counts_as_successful_communication() -> None:
    hub = make_hub()
    prepare_communication_diagnostics(hub)

    hub._record_poll_cycle(PollOutcome.DISCARDED, elapsed=0.1, interval=15)

    assert hub._comm_recent_outcomes == [PollOutcome.DISCARDED]
    assert hub.data["communication_success_rate"] == 100.0
    assert hub.data["communication_health"] == "Healthy"
