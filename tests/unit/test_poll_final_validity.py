"""Publish only values that survive every group of the completed interval."""

import asyncio
from typing import Any

import pytest

from custom_components.solax_modbus import BlockReadResult
from custom_components.solax_modbus.const import PollOutcome

from .test_dashboard_poll_intervals import setup_poll


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_source", ["topology", "power"])
@pytest.mark.parametrize("outcome", [PollOutcome.FAILED, PollOutcome.DISCARDED, PollOutcome.PARTIAL])
async def test_trailing_invalid_group_reconciles_final_publication(invalid_source: str, outcome: PollOutcome) -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    for entity in hub.sensorEntities.values():
        entity.modbus_data_updated.reset_mock()
    published: list[Any] = []
    hub.sensorEntities[ed.key].modbus_data_updated.side_effect = lambda: published.append(hub.data[ed.key])
    trailing = settings.device_groups["settings"] if invalid_source == "topology" else setup_poll()[2].device_groups["power"]
    power.device_groups["trailing"] = trailing
    original = hub.async_read_modbus_block

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block is trailing.holdingBlocks[0] and outcome is not PollOutcome.DISCARDED:
            return BlockReadResult(data_succeeded=False, communication_succeeded=outcome is PollOutcome.PARTIAL)
        result: BlockReadResult = await original(data, block, typ)
        return result

    async def reject(_old: Any, _new: Any) -> bool:
        return False

    if outcome is PollOutcome.DISCARDED:
        trailing.readFollowUp = reject
    hub.async_read_modbus_block = read
    actual, _ = await hub._refresh_interval_group_once(power)
    assert actual is (PollOutcome.SUCCESS if outcome is PollOutcome.DISCARDED else outcome)
    assert published == [None]
    assert hub.data["house_load"] == 191
    assert hub.sensorEntities["house_load"].modbus_data_updated.call_count == (1 if invalid_source == "topology" else 0)


@pytest.mark.asyncio
async def test_trailing_topology_change_publishes_only_selected_pm_value() -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    published: list[Any] = []
    hub.sensorEntities[ed.key].modbus_data_updated.side_effect = lambda: published.append(hub.data[ed.key])
    power.device_groups.update(settings.device_groups)
    trailing = settings.device_groups["settings"].holdingBlocks[0]
    original = hub.async_read_modbus_block

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        result: BlockReadResult = await original(data, block, typ)
        if block is trailing:
            data["parallel_setting"] = "Master"
        return result

    hub.async_read_modbus_block = read
    await hub._refresh_interval_group_once(power)
    assert published == [400]


@pytest.mark.asyncio
async def test_final_reconciliation_waits_for_other_interval_validation() -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    published: list[Any] = []
    hub.sensorEntities[ed.key].modbus_data_updated.side_effect = lambda: published.append(hub.data[ed.key])
    started, release = asyncio.Event(), asyncio.Event()
    slow_tasks: list[asyncio.Task[Any]] = []
    original = hub.async_read_modbus_data

    async def reject(_old: Any, _new: Any) -> bool:
        pending = hub._pending_input_observations
        started.set()
        await release.wait()
        assert hub._pending_input_observations is pending
        return False

    settings.device_groups["settings"].readFollowUp = reject

    async def read(group: Any, fresh_keys: set[str]) -> PollOutcome:
        outcome: PollOutcome = await original(group, fresh_keys)
        if group is power.device_groups["power"]:
            slow_tasks.append(asyncio.create_task(hub._refresh_interval_group_once(settings)))
            await started.wait()
        return outcome

    hub.async_read_modbus_data = read
    fast_task = asyncio.create_task(hub._refresh_interval_group_once(power))
    await started.wait()
    await asyncio.sleep(0)
    assert not fast_task.done()
    assert published == []
    release.set()
    await asyncio.gather(fast_task, *slow_tasks)
    assert published == [None, None]
    assert hub._pending_input_observations is None
