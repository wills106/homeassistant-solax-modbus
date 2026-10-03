"""Issue #2356: accepted source observations survive unrelated device groups."""

import asyncio
import time
from collections.abc import AsyncGenerator
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
import pytest_asyncio
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from pytest_homeassistant_custom_component.common import async_test_home_assistant

from custom_components.solax_modbus import BlockReadResult
from custom_components.solax_modbus.const import DOMAIN, BaseModbusSensorEntityDescription, PollOutcome
from custom_components.solax_modbus.energy_dashboard import (
    EnergyDashboardSensorMapping,
    _create_aggregated_value_function,
    _create_sensor_from_mapping,
)
from custom_components.solax_modbus.sensor import SolaXModbusSensor

from .test_computed_review_regressions import description
from .test_poll_snapshot import make_group, make_hub, successful_block
from .test_riemann_readiness import make_integral


@pytest_asyncio.fixture
async def interval_hass() -> AsyncGenerator[HomeAssistant]:
    """Exercise actual HA publication under the unchanged strict asyncio mode."""
    async with async_test_home_assistant() as hass:
        try:
            yield hass
        finally:
            await hass.async_stop(force=True)


def setup_poll(fast: int = 5, slow: int = 15) -> tuple[Any, Any, Any, Any]:
    hub = make_hub()
    hub._invertertype = 0
    hub.config = {"scan_interval": slow, "scan_interval_fast": fast}
    hub.blocks_changed = False
    hub.cyclecount = 0
    hub.sleepnone = []
    hub.sleepzero = []
    hub.sensorDescriptions = {
        key: BaseModbusSensorEntityDescription(key=key, register=i + 1, scan_group=group)
        for i, (key, group) in enumerate(
            [("inverter_power", "scan_interval_fast"), ("measured_power", "scan_interval_fast"), ("parallel_setting", "scan_interval")]
        )
    }
    hub.sensorDescriptions["house_load"] = description("house_load")
    hub.sensorDescriptions["pm_power"] = BaseModbusSensorEntityDescription(key="pm_power", register=4, scan_group="scan_interval_fast")
    hub.data.update(parallel_setting="Free", pm_power=None)
    mapping = EnergyDashboardSensorMapping(source_key="house_load", source_key_pm="pm_power", target_key="home_power", name="Home power")
    ed = _create_sensor_from_mapping(mapping, hub, DeviceInfo(identifiers={(DOMAIN, "ed")}), source_hub=hub)[0]
    hub.computedSensors = {"house_load": hub.sensorDescriptions["house_load"], ed.key: ed}
    hub.sensorDescriptions[ed.key] = ed
    hub.sensorEntities = {key: Mock() for key in hub.computedSensors}

    def group(keys: tuple[str, ...]) -> Any:
        item = make_group()
        item.holdingBlocks = [SimpleNamespace(start=1, descriptions={i: hub.sensorDescriptions[key] for i, key in enumerate(keys)})]
        return item

    fast_group = group(("inverter_power", "measured_power", "pm_power"))
    slow_group = group(("parallel_setting",))
    fast_poll = SimpleNamespace(interval=fast, device_groups={"power": fast_group})
    slow_poll = SimpleNamespace(interval=slow, device_groups={"settings": slow_group})

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        values = {"inverter_power": 250, "measured_power": 59, "pm_power": 400, "parallel_setting": hub.data["parallel_setting"]}
        keys = [descr.key for descr in block.descriptions.values()]
        data.update({key: values[key] for key in keys})
        return successful_block(*keys)

    hub.async_read_modbus_block = read
    return hub, ed, fast_poll, slow_poll


@pytest.mark.asyncio
@pytest.mark.parametrize(("fast", "slow"), [(5, 15), (7, 23), (15, 5)])
async def test_tcworld_sequence_keeps_computed_power_between_groups(
    fast: int, slow: int, monkeypatch: pytest.MonkeyPatch, clock_start: float
) -> None:
    hub, ed, power, settings = setup_poll(fast, slow)
    clock = [clock_start]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    assert hub.data["house_load"] == hub.data[ed.key] == 191
    for poll in (settings, power, settings, power, settings):
        clock[0] += 0.8
        await hub._refresh_interval_group_once(poll)
        assert hub.data["house_load"] == hub.data[ed.key] == 191


@pytest.mark.asyncio
async def test_same_interval_following_device_group_keeps_power(monkeypatch: pytest.MonkeyPatch) -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    # A power group followed by topology-only and an empty group in ONE refresh.
    power.device_groups.update(settings.device_groups)
    power.device_groups["unrelated"] = make_group()
    power.device_groups["unrelated"].holdingBlocks = []
    await hub._refresh_interval_group_once(power)
    assert hub.data[ed.key] == 191


@pytest.mark.asyncio
async def test_fast_refresh_interleaves_between_slow_device_groups() -> None:
    """Replay slow / queued fast / further slow groups through the real lock."""
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    first = settings.device_groups["settings"]
    second = make_group()
    second.holdingBlocks = [SimpleNamespace(start=2, descriptions=first.holdingBlocks[0].descriptions)]
    settings.device_groups["second_settings"] = second
    started, release = asyncio.Event(), asyncio.Event()
    original = hub.async_read_modbus_block
    published: list[Any] = []
    hub.sensorEntities[ed.key].modbus_data_updated.side_effect = lambda: published.append(hub.data[ed.key])

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block is first.holdingBlocks[0]:
            started.set()
            await release.wait()
        return cast(BlockReadResult, await original(data, block, typ))

    hub.async_read_modbus_block = read
    slow_task = asyncio.create_task(hub._refresh_interval_group_once(settings))
    await started.wait()
    fast_task = asyncio.create_task(hub._refresh_interval_group_once(power))
    await asyncio.sleep(0)  # Queue fast while the first slow group owns the lock.
    release.set()
    await asyncio.gather(slow_task, fast_task)
    # Publish once per completed interval rather than once per device group.
    assert published == [191, 191]


@pytest.mark.asyncio
async def test_topology_poll_does_not_renew_power_lease(interval_hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, clock_start: float) -> None:
    hub, ed, power, settings = setup_poll()
    entity = SolaXModbusSensor("test", hub, DeviceInfo(identifiers={(DOMAIN, "ed")}), ed)
    entity.hass = interval_hass
    entity.entity_id = "sensor.mixed_interval_power"
    await entity.async_added_to_hass()
    clock = [clock_start]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    later = Mock()
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", later)
    await hub._refresh_interval_group_once(settings)
    clock[0] += 0.1
    await hub._refresh_interval_group_once(power)
    assert interval_hass.states.is_state(entity.entity_id, "191")
    clock[0] += 10
    await hub._refresh_interval_group_once(settings)
    assert interval_hass.states.is_state(entity.entity_id, "191")
    assert later.call_args.args[1] == pytest.approx(5.0, rel=0, abs=1e-9)
    clock[0] += 6
    later.call_args.args[2](None)
    assert interval_hass.states.is_state(entity.entity_id, "unavailable")
    await entity.async_will_remove_from_hass()


@pytest.mark.asyncio
async def test_required_dependencies_expire_individually(monkeypatch: pytest.MonkeyPatch, clock_start: float) -> None:
    hub, ed, power, settings = setup_poll()
    # The computed source actually uses one slow and one fast required input.
    hub.sensorDescriptions["measured_power"] = replace(hub.sensorDescriptions["measured_power"], scan_group="scan_interval")
    power.device_groups["power"].holdingBlocks[0].descriptions = {0: hub.sensorDescriptions["inverter_power"]}
    settings.device_groups["settings"].holdingBlocks[0].descriptions[1] = hub.sensorDescriptions["measured_power"]
    clock = [clock_start]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    assert hub.data[ed.key] == 191
    clock[0] += 16  # Fast input expired; slow input is still within its 45s lease.
    await hub._refresh_interval_group_once(settings)
    assert hub.data[ed.key] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, float("nan"), float("inf")])
async def test_invalid_computed_dependency_propagates_unknown(bad: Any) -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    original = hub.async_read_modbus_block

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        result = await original(data, block, typ)
        data["inverter_power"] = bad
        return cast(BlockReadResult, result)

    hub.async_read_modbus_block = read
    await hub._refresh_interval_group_once(power)
    assert hub.data["house_load"] == 191  # Ordinary computed source retains its last value.
    assert hub.data[ed.key] is None  # ED must not silently hold that invalid source.


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, float("nan")])
async def test_invalid_computed_result_is_not_replaced_with_old_output(bad: Any) -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    descr = replace(hub.sensorDescriptions["house_load"], value_function=lambda _i, _d, _data: bad)
    hub.sensorDescriptions["house_load"] = hub.computedSensors["house_load"] = descr
    await hub._refresh_interval_group_once(power)
    assert hub.data["house_load"] == 191
    assert hub.data[ed.key] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [PollOutcome.FAILED, PollOutcome.DISCARDED, PollOutcome.PARTIAL])
async def test_actual_source_failure_is_not_filled_from_cached_computation(outcome: PollOutcome) -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    if outcome is PollOutcome.DISCARDED:

        async def reject(_old: Any, _new: Any) -> bool:
            return False

        power.device_groups["power"].readFollowUp = reject
    else:

        async def fail(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
            return BlockReadResult(data_succeeded=False, communication_succeeded=outcome is PollOutcome.PARTIAL)

        hub.async_read_modbus_block = fail
    await hub._refresh_interval_group_once(power)
    if outcome is not PollOutcome.DISCARDED:
        assert hub.data[ed.key] is None or outcome is PollOutcome.FAILED

    # Restore settings reader; a topology poll must not revive failed power.
    async def read_settings(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        return successful_block("parallel_setting")

    hub.async_read_modbus_block = read_settings
    await hub._refresh_interval_group_once(settings)
    assert hub.data[ed.key] is None


@pytest.mark.asyncio
async def test_topology_changes_select_only_current_mapping() -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    assert hub.data[ed.key] == 191
    for mode, expected in (("Master", 400), ("Slave", 191), ("Free", 191)):
        hub.data["parallel_setting"] = mode
        await hub._refresh_interval_group_once(settings)
        assert hub.data[ed.key] == expected


@pytest.mark.asyncio
async def test_identical_power_is_a_new_observation_but_topology_is_not(monkeypatch: pytest.MonkeyPatch, clock_start: float) -> None:
    hub, ed, power, settings = setup_poll()
    clock = [clock_start]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    first = hub._accepted_input_sample("house_load")
    clock[0] += 2
    await hub._refresh_interval_group_once(settings)
    assert hub._accepted_input_sample("house_load") == first
    assert hub._input_observations()[ed.key].timestamp == first.timestamp
    clock[0] += 2
    await hub._refresh_interval_group_once(power)
    assert hub._accepted_input_sample("house_load").timestamp == clock[0]
    assert hub._accepted_input_sample("house_load").deadline == clock[0] + 15
    assert hub.data[ed.key] == 191


@pytest.mark.asyncio
async def test_invalid_input_publishes_unknown_then_expires(
    interval_hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, clock_start: float
) -> None:
    hub, ed, power, settings = setup_poll()
    entity = SolaXModbusSensor("test", hub, DeviceInfo(identifiers={(DOMAIN, "ed")}), ed)
    entity.hass = interval_hass
    entity.entity_id = "sensor.invalid_input_power"
    await entity.async_added_to_hass()
    clock = [clock_start]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    later = Mock()
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", later)
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    clock[0] += 5
    original = hub.async_read_modbus_block

    async def invalid(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        result = await original(data, block, typ)
        data["inverter_power"] = None
        return cast(BlockReadResult, result)

    hub.async_read_modbus_block = invalid
    await hub._refresh_interval_group_once(power)
    assert interval_hass.states.is_state(entity.entity_id, "unknown")
    assert entity.available
    assert later.call_args.args[1] == pytest.approx(10.0, rel=0, abs=1e-9)
    clock[0] += 11
    later.call_args.args[2](None)
    assert interval_hass.states.is_state(entity.entity_id, "unavailable")
    hub.async_read_modbus_block = original
    await hub._refresh_interval_group_once(power)
    assert interval_hass.states.is_state(entity.entity_id, "191")
    await entity.async_will_remove_from_hass()


@pytest.mark.asyncio
async def test_dashboard_also_expires_a_faster_topology_input(monkeypatch: pytest.MonkeyPatch, clock_start: float) -> None:
    hub, ed, power, settings = setup_poll(15, 5)
    clock = [clock_start]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    assert hub.computed_sensor_remaining_age(ed) == pytest.approx(15.0, rel=0, abs=1e-9)
    clock[0] += 16
    await hub._refresh_interval_group_once(power)
    assert hub.data[ed.key] is None


@pytest.mark.asyncio
async def test_rejected_inflight_group_is_not_visible_to_another_hub() -> None:
    hub, _ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    old = hub._accepted_input_sample("house_load")
    assert old is not None
    # The follow-up can await while another hub is polling. It must see only
    # the committed source sample, even though the staged value is now zero.
    original = hub.async_read_modbus_block

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        result = await original(data, block, typ)
        data.update(inverter_power=59, measured_power=59)
        return cast(BlockReadResult, result)

    async def reject(_old: Any, _new: Any) -> bool:
        mapping = EnergyDashboardSensorMapping(source_key="house_load", target_key="home_power", name="Home")
        sample = hub._dashboard_source_sample(mapping, {}, set())
        assert sample is not None and sample[0] == old.timestamp and sample[1]["house_load"] == 191
        return False

    power.device_groups["power"].readFollowUp = reject
    hub.async_read_modbus_block = read
    outcome, _ = await hub._refresh_interval_group_once(power)
    assert outcome is PollOutcome.DISCARDED
    assert hub.data["house_load"] == 191
    assert hub._accepted_input_sample("house_load") is None


@pytest.mark.asyncio
async def test_validation_exception_clears_staged_observations() -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)

    async def reject(_old: Any, _new: Any) -> bool:
        raise RuntimeError("invalid device data")

    power.device_groups["power"].readFollowUp = reject
    with pytest.raises(RuntimeError, match="invalid device data"):
        await hub.async_read_modbus_registers_all(power.device_groups["power"])
    assert hub._pending_input_observations is None
    await hub._refresh_interval_group_once(settings)
    assert hub.data[ed.key] is None


@pytest.mark.asyncio
async def test_parallel_sum_requires_every_source_hub() -> None:
    master, ed, power, settings = setup_poll()
    slave, _slave_ed, slave_power, slave_settings = setup_poll()
    await slave._refresh_interval_group_once(slave_settings)
    await slave._refresh_interval_group_once(slave_power)
    ed = replace(ed, _energy_dashboard_source_hubs=(master, slave), value_function=_create_aggregated_value_function(ed._energy_dashboard_mapping))
    master.computedSensors[ed.key] = ed
    await master._refresh_interval_group_once(settings)
    await master._refresh_interval_group_once(power)
    assert master.data[ed.key] == 382

    async def fail(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        return BlockReadResult(data_succeeded=False, communication_succeeded=False)

    slave.async_read_modbus_block = fail
    await slave._refresh_interval_group_once(slave_power)
    await master._refresh_interval_group_once(power)
    assert master.data[ed.key] is None


@pytest.mark.asyncio
async def test_computed_zero_is_not_missing_data() -> None:
    hub, ed, power, settings = setup_poll()
    original = hub.async_read_modbus_block

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        result = await original(data, block, typ)
        data.update(inverter_power=59, measured_power=59)
        return cast(BlockReadResult, result)

    await hub._refresh_interval_group_once(settings)
    hub.async_read_modbus_block = read
    await hub._refresh_interval_group_once(power)
    await hub._refresh_interval_group_once(settings)
    assert hub.data["house_load"] == hub.data[ed.key] == 0


@pytest.mark.asyncio
async def test_integral_uses_shortest_required_input_lease_and_breaks_silent_gap(monkeypatch: pytest.MonkeyPatch, clock_start: float) -> None:
    hub, _ed, power, settings = setup_poll()
    config, source_description = hub.config, hub.sensorDescriptions["house_load"]
    integral, _source = make_integral(source_hub=hub, source_key="house_load")
    hub.config, hub.sensorDescriptions["house_load"] = config, source_description
    # One input is slow. The old maximum would keep the integral alive for 45s.
    hub.sensorDescriptions["measured_power"] = replace(hub.sensorDescriptions["measured_power"], scan_group="scan_interval")
    power.device_groups["power"].holdingBlocks[0].descriptions = {0: hub.sensorDescriptions["inverter_power"]}
    settings.device_groups["settings"].holdingBlocks[0].descriptions[1] = hub.sensorDescriptions["measured_power"]
    clock = [clock_start]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    later = Mock()
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", later)
    await hub._refresh_interval_group_once(settings)
    clock[0] += 0.1
    await hub._refresh_interval_group_once(power)
    assert hub._accepted_input_sample("house_load") is not None
    assert hub._dashboard_source_sample(integral._riemann_mapping, {}, set(), require_source_sample=True) is not None
    integral.modbus_data_updated()
    assert later.call_args.args[1] == pytest.approx(15.0, rel=0, abs=1e-9)
    clock[0] += 5
    await hub._refresh_interval_group_once(power)
    integral.modbus_data_updated()
    total = integral._total_energy
    assert total > 0
    clock[0] += 16  # Do not invoke the expiry callback: simulate delayed delivery.
    await hub._refresh_interval_group_once(settings)
    clock[0] += 0.1
    await hub._refresh_interval_group_once(power)
    integral.modbus_data_updated()
    assert integral._total_energy == total
