"""Issue #2356: exercise real polling, Gen5 computations and VPP filters."""

import asyncio
import time
from dataclasses import replace
from types import MethodType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.solax_modbus import BlockReadResult, SolaXModbusHub
from custom_components.solax_modbus.button import SolaXModbusButton
from custom_components.solax_modbus.const import BUTTONREPEAT_FIRST, BUTTONREPEAT_LOOP, BUTTONREPEAT_POST, PollOutcome
from custom_components.solax_modbus.plugin_solax import BUTTON_TYPES, GEN5, NUMBER_TYPES, SELECT_TYPES, SENSOR_TYPES_MAIN

from .test_poll_snapshot import make_group, make_hub, successful_block


def computed(key: str) -> Any:
    return next(d for d in SENSOR_TYPES_MAIN if d.key == key and d.register < 0 and (key != "bms_max_charge" or d.allowedtypes & GEN5))


def setup_vpp(fast: int = 5, slow: int = 15, count: int = 2, reverse: bool = False) -> tuple[Any, Any, Any, dict[str, Any], Mock]:
    hub = make_hub()
    hub.config = {"scan_interval": slow, "scan_interval_fast": fast}
    hub._invertertype = 0
    hub._modbus_addr = 1
    hub.blocks_changed = False
    hub.cyclecount = 0
    hub.sleepnone = []
    hub.sleepzero = []
    values: dict[str, Any] = {
        "measured_power": -1000,
        "inverter_power_l1": 0,
        "inverter_power_l2": 0,
        "inverter_power_l3": 0,
        "pv_power_1": 0,
        "pv_power_2": 0,
        "battery_1_power_charge": 0,
        "battery_2_power_charge": 0,
        "battery_total_capacity_charge": 80,
        "battery_1_capacity_charge": 80,
        "battery_2_capacity_charge": 80,
        "parallel_setting": "Free",
    }
    slow_keys = {"battery_total_capacity_charge", "battery_1_capacity_charge", "battery_2_capacity_charge", "parallel_setting"}
    hub.sensorDescriptions = {
        key: replace(
            next(d for d in SENSOR_TYPES_MAIN if d.key == key and d.register >= 0),
            scan_group="scan_interval" if key in slow_keys else "scan_interval_fast",
        )
        for key in values
    }
    hub.computedSensors = {key: computed(key) for key in ("battery_capacity", "inverter_power", "pv_power_total", "battery_power_charge")}
    hub.sensorDescriptions.update(hub.computedSensors)
    hub.sensorEntities = {key: Mock() for key in hub.computedSensors}
    hub.data.update(
        {
            "remotecontrol_power_control_mode": "Export-First Battery Limit",
            "modbus_power_control": "Individual Setting - Duration Mode",
            "remotecontrol_minimum_soc_8_9": 24,
            "remotecontrol_current_pushmode_power": 0,
            "remotecontrol_current_pv_power_limit": 12000,
            "remotecontrol_pv_power_limit": 12000,
            "remotecontrol_autorepeat_duration": 300,
        }
    )
    base = next(d for d in BUTTON_TYPES if d.key == "powercontrolmode8_trigger")
    function = Mock(wraps=base.value_function)
    hub.computedEntities = {base.key: replace(base, value_function=function)}
    hub.async_write_registers_multi = AsyncMock()

    def poll(keys: set[str], interval: int) -> Any:
        groups = {}
        chunks = [sorted(keys)[i::count] for i in range(count)]
        for i, chunk in enumerate(chunks):
            group = make_group()
            group.holdingBlocks = [SimpleNamespace(start=i, descriptions={j: hub.sensorDescriptions[key] for j, key in enumerate(chunk)})]
            groups[str(i)] = group
        if reverse:
            groups = dict(reversed(list(groups.items())))
        return SimpleNamespace(interval=interval, device_groups=groups)

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        keys = {d.key for d in block.descriptions.values()}
        data.update({key: values[key] for key in keys if key in values})
        return successful_block(*(keys & values.keys()))

    hub.async_read_modbus_block = read
    return hub, poll(set(values) - slow_keys, fast), poll(slow_keys, slow), values, function


async def prime(hub: Any, power: Any, settings: Any) -> None:
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    hub.data["_repeatUntil"]["powercontrolmode8_trigger"] = time.time() + 300


@pytest.mark.asyncio
@pytest.mark.parametrize(("fast", "slow"), [(5, 15), (6, 15), (7, 23), (15, 15), (15, 5)])
@pytest.mark.parametrize("count", [2, 3])
@pytest.mark.parametrize("reverse", [False, True])
async def test_one_nonzero_filter_step_per_power_poll(fast: int, slow: int, count: int, reverse: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    hub, power, settings, _values, function = setup_vpp(fast, slow, count, reverse)
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    await prime(hub, power, settings)
    now[0] += 1
    await hub._refresh_interval_group_once(power)
    assert hub.data["remotecontrol_current_pushmode_power"] == 210
    assert function.call_count == hub.async_write_registers_multi.await_count == 1
    if slow != fast:
        now[0] += 0.1
        await hub._refresh_interval_group_once(settings)
        assert function.call_count == hub.async_write_registers_multi.await_count == 1
        assert hub.data["remotecontrol_current_pushmode_power"] == 210
    now[0] += 1
    # Identical numbers, but an accepted new measurement must advance the filter.
    await hub._refresh_interval_group_once(power)
    assert hub.data["remotecontrol_current_pushmode_power"] == 378
    assert function.call_count == hub.async_write_registers_multi.await_count == 2
    assert dict(hub.async_write_registers_multi.call_args.kwargs["payload"])["remotecontrol_push_mode_power_8_9"] == 378


@pytest.mark.asyncio
async def test_fresh_authoritative_total_soc_does_not_use_expired_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    hub, power, settings, values, function = setup_vpp()
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    await prime(hub, power, settings)
    assert hub.data["battery_capacity"] == 80
    now[0] += 46
    values.update(battery_total_capacity_charge=20, battery_1_capacity_charge=20)
    values.pop("battery_2_capacity_charge")
    # Refresh settings without running a controller on the expired power first.
    expiry = hub.data["_repeatUntil"].pop("powercontrolmode8_trigger")
    await hub._refresh_interval_group_once(settings)
    hub.data["_repeatUntil"]["powercontrolmode8_trigger"] = expiry
    await hub._refresh_interval_group_once(power)
    assert hub.data["battery_capacity"] == 20
    assert hub.data["remotecontrol_current_pushmode_power"] == 0
    assert function.call_count == 1
    assert dict(hub.async_write_registers_multi.call_args.kwargs["payload"])["remotecontrol_push_mode_power_8_9"] == 0
    assert hub._computed_input_observations["battery_capacity"].deadline == now[0] + 45


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), float("-inf"), True, "80"])
async def test_invalid_required_input_stops_previous_nonzero_command(invalid: Any) -> None:
    hub, power, settings, values, function = setup_vpp()
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    assert hub.data["remotecontrol_current_pushmode_power"] == 210
    values["measured_power"] = invalid
    await hub._refresh_interval_group_once(power)
    assert function.call_count == 2
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["_repeatUntil"]["powercontrolmode8_trigger"] == 0
    assert hub.data["remotecontrol_current_pushmode_power"] is None
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == [("remotecontrol_power_control_mode", "Disabled")]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["absent", "failed", "discarded", "expired"])
async def test_stale_computed_number_cannot_authorize_vpp(outcome: str, monkeypatch: pytest.MonkeyPatch) -> None:
    hub, power, settings, values, function = setup_vpp()
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    assert hub.data["remotecontrol_current_pushmode_power"] == 210
    if outcome == "expired":
        now[0] += 16
        await hub._refresh_interval_group_once(settings)
    else:
        if outcome == "absent":
            values.pop("inverter_power_l2")
        elif outcome == "failed":

            async def fail(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
                return BlockReadResult(data_succeeded=False, communication_succeeded=False)

            hub.async_read_modbus_block = fail
        else:
            for group in power.device_groups.values():
                group.readFollowUp = AsyncMock(return_value=False)
        now[0] += 1
        await hub._refresh_interval_group_once(power)
    assert hub.data["inverter_power"] == 0  # The shared cache deliberately retains its last number.
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["remotecontrol_current_pushmode_power"] is None
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == [("remotecontrol_power_control_mode", "Disabled")]


@pytest.mark.asyncio
async def test_keepalive_replays_without_advancing_filter_and_expiry_cleans_once(monkeypatch: pytest.MonkeyPatch) -> None:
    hub, power, settings, _values, function = setup_vpp()
    now = [1000.0]
    wall = [2000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "time", lambda: wall[0])
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    payload = hub.async_write_registers_multi.call_args.kwargs["payload"]
    for group in power.device_groups.values():
        group.holdingBlocks = []
    now[0] += 1
    await hub._refresh_interval_group_once(power)
    assert function.call_count == 1
    assert hub.async_write_registers_multi.await_count == 2
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == payload
    assert hub.data["remotecontrol_current_pushmode_power"] == 210
    wall[0] += 301
    await hub._refresh_interval_group_once(settings)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["remotecontrol_current_pushmode_power"] is None
    count = hub.async_write_registers_multi.await_count
    await hub._refresh_interval_group_once(power)
    assert hub.async_write_registers_multi.await_count == count


@pytest.mark.asyncio
async def test_startup_button_rejects_cache_then_recovers_after_accepted_poll() -> None:
    hub, power, settings, values, function = setup_vpp()
    hub.data.update(values, battery_capacity=80, inverter_power=0, pv_power_total=0, battery_power_charge=0)
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    button = SolaXModbusButton("solax", hub, 1, {}, descr)
    await button.async_press()
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == [("remotecontrol_power_control_mode", "Disabled")]
    await prime(hub, power, settings)
    await button.async_press()
    assert function.call_args.args[0] == BUTTONREPEAT_FIRST
    assert hub.data["remotecontrol_current_pushmode_power"] == 210
    # FIRST already consumed this measurement. LOOP is only a keepalive.
    await hub._refresh_interval_group_once(SimpleNamespace(interval=power.interval, device_groups={"empty": make_group_empty()}))
    assert function.call_count == 2
    assert hub.data["remotecontrol_current_pushmode_power"] == 210


def make_group_empty() -> Any:
    group = make_group()
    group.holdingBlocks = []
    return group


@pytest.mark.asyncio
async def test_interleaved_slow_and_fast_poll_do_not_duplicate_regulation() -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    started, release = asyncio.Event(), asyncio.Event()
    original = hub.async_read_modbus_block
    first = next(iter(settings.device_groups.values())).holdingBlocks[0]

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block is first:
            started.set()
            await release.wait()
        result: BlockReadResult = await original(data, block, typ)
        return result

    hub.async_read_modbus_block = read
    slow_task = asyncio.create_task(hub._refresh_interval_group_once(settings))
    await started.wait()
    fast_task = asyncio.create_task(hub._refresh_interval_group_once(power))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(slow_task, fast_task)
    assert function.call_count == hub.async_write_registers_multi.await_count == 1
    assert hub.data["remotecontrol_current_pushmode_power"] == 210


@pytest.mark.asyncio
async def test_computed_chain_calculates_once_for_same_accepted_generation() -> None:
    hub, power, settings, _values, _function = setup_vpp(count=3)
    await prime(hub, power, settings)
    hub.data["_repeatUntil"].clear()
    descr = hub.computedSensors["pv_power_total"]
    function = Mock(wraps=descr.value_function)
    hub.computedSensors[descr.key] = replace(descr, value_function=function)
    hub.sensorDescriptions[descr.key] = hub.computedSensors[descr.key]
    # Read both PV inputs together, followed by groups without new PV inputs.
    group = make_group()
    group.holdingBlocks = [
        SimpleNamespace(start=0, descriptions={i: hub.sensorDescriptions[key] for i, key in enumerate(("pv_power_1", "pv_power_2"))})
    ]
    poll = SimpleNamespace(interval=power.interval, device_groups={"pv": group, "eps": make_group_empty(), "other": make_group_empty()})
    hub.sensorEntities[descr.key].modbus_data_updated.reset_mock()
    await hub._refresh_interval_group_once(poll)
    assert function.call_count == 1
    hub.sensorEntities[descr.key].modbus_data_updated.assert_called_once()
    # A full topology poll consumes no new PV measurement.
    await hub._refresh_interval_group_once(settings)
    assert function.call_count == 1


@pytest.mark.asyncio
async def test_slowdown_still_expires_control_without_new_measurements(monkeypatch: pytest.MonkeyPatch) -> None:
    hub, power, settings, _values, function = setup_vpp()
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    now[0] += 16
    hub.slowdown = 10
    hub.cyclecount = 1
    result, _count = await hub._refresh_interval_group_once(power)
    assert result is PollOutcome.SKIPPED
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["remotecontrol_current_pushmode_power"] is None


@pytest.mark.asyncio
async def test_identical_measurements_at_same_clock_time_are_distinct_control_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    hub, power, settings, _values, function = setup_vpp()
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    assert hub.data["remotecontrol_current_pushmode_power"] == 210
    await hub._refresh_interval_group_once(power)
    assert function.call_count == 2
    assert hub.data["remotecontrol_current_pushmode_power"] == 378


@pytest.mark.asyncio
async def test_local_request_changes_on_next_owner_poll_without_new_measurement() -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    hub.data["remotecontrol_minimum_soc_8_9"] = 90
    for group in power.device_groups.values():
        group.holdingBlocks = []
    await hub._refresh_interval_group_once(power)
    assert function.call_count == 2
    assert function.call_args.args[0] == BUTTONREPEAT_LOOP
    assert hub.data["remotecontrol_current_pushmode_power"] == 0


@pytest.mark.asyncio
async def test_real_encoder_writes_one_nonzero_command_to_mock_transport() -> None:
    hub, power, settings, _values, function = setup_vpp(count=3)
    await prime(hub, power, settings)
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub._stopping = False
    hub._check_connection = AsyncMock(return_value=True)
    hub._transport = SimpleNamespace(write=AsyncMock(return_value=Mock(isError=Mock(return_value=False))))
    hub.plugin.order32 = "little"
    descriptions: tuple[Any, ...] = (*NUMBER_TYPES, *SELECT_TYPES)
    for d in descriptions:
        if d.key in {
            "remotecontrol_power_control_mode",
            "remotecontrol_set_type",
            "remotecontrol_pv_power_limit",
            "remotecontrol_push_mode_power_8_9",
            "remotecontrol_timeout",
            "remotecontrol_timeout_next_motion",
        }:
            options = getattr(d, "option_dict", None)
            hub.writeLocals[d.key] = replace(d, reverse_option_dict={label: raw for raw, label in options.items()}) if options else d
    hub.async_write_registers_multi = MethodType(SolaXModbusHub.async_write_registers_multi, hub)
    await hub._refresh_interval_group_once(power)
    assert function.call_count == hub._transport.write.await_count == 1
    call = hub._transport.write.call_args
    assert call.args[:2] == (1, 0xA0)
    assert call.args[2][:6] == [8, 1, 12000, 0, 210, 0]
    assert len(call.args[2]) == 8
    assert call.kwargs == {"multiple": True}


@pytest.mark.asyncio
async def test_rebuild_uses_new_cadence_and_does_not_accept_old_observations() -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    hub.config["scan_interval_fast"] = 7
    hub.rebuild_blocks({})
    power.interval = 7
    # The previous SoC can't authorize a command after the configuration rebuild.
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(settings)
    count = function.call_count
    await hub._refresh_interval_group_once(power)
    assert function.call_count == count + 1
    assert hub.data["remotecontrol_current_pushmode_power"] == 210
    sample = hub._computed_input_observations["measured_power"]
    assert sample.deadline - sample.timestamp == pytest.approx(21)


@pytest.mark.asyncio
async def test_failed_cleanup_is_retried_without_recomputing_filter() -> None:
    hub, power, settings, values, function = setup_vpp()
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    values["measured_power"] = None
    hub.async_write_registers_multi.side_effect = [HomeAssistantError("offline"), None]
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["remotecontrol_current_pushmode_power"] is None
    assert "powercontrolmode8_trigger" in hub._autorepeat_pending_stops
    calls = function.call_count
    await hub._refresh_interval_group_once(settings)
    assert function.call_count == calls
    assert hub._autorepeat_pending_stops == {}
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == [("remotecontrol_power_control_mode", "Disabled")]
