"""Tests for atomic polling snapshots."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.solax_modbus import BlockReadResult, PendingWrite, SolaXModbusHub
from custom_components.solax_modbus.const import REGISTER_U16, PollOutcome
from custom_components.solax_modbus.plugin_sofar import battery_config
from custom_components.solax_modbus.plugin_solax import SENSOR_TYPES_MAIN


def make_hub() -> Any:
    """Build the minimal hub state required by polling tests."""
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "test"
    hub.data = {"_repeatUntil": {}, "raw": 1}
    hub.computedSensors = {}
    hub.computedEntities = {}
    hub.sensorDescriptions = {}
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


def successful_block(*fresh_keys: str) -> BlockReadResult:
    """Return a successful block result for polling tests."""
    return BlockReadResult(
        data_succeeded=True,
        communication_succeeded=True,
        fresh_keys=frozenset(fresh_keys),
    )


def make_pm_poll(*, reverse: bool = False) -> tuple[Any, Any]:
    """Use the real SolaX totals with separate inverter and Parallel groups."""
    hub = make_hub()
    hub.blocks_changed = False
    hub.cyclecount = 1
    hub.sleepnone = []
    hub.sleepzero = []
    hub.sensorDescriptions = {description.key: description for description in SENSOR_TYPES_MAIN}
    hub.computedSensors = {key: description for key, description in hub.sensorDescriptions.items() if key.startswith("pm_total_")}
    hub.sensorEntities = {key: Mock() for key in hub.computedSensors}
    hub.data.update(dict.fromkeys(hub.computedSensors, 0))
    groups = {}
    for name in ("inverter", "pm"):
        group = make_group()
        group.holdingBlocks = [SimpleNamespace(start=name)]
        groups[name] = group
    if reverse:
        groups = dict(reversed(list(groups.items())))
    return hub, SimpleNamespace(device_groups=groups)


PM_POLL_VALUES: dict[str, dict[str, Any]] = {
    "inverter": {"parallel_setting": "Master", "measured_power": 200},
    "pm": {
        "pm_activepower_l1": 400,
        "pm_activepower_l2": 500,
        "pm_activepower_l3": 300,
        "pm_pv_power_1": 1500,
        "pm_pv_power_2": 2000,
        "pm_reactive_or_apparentpower_l1": 10,
        "pm_reactive_or_apparentpower_l2": 20,
        "pm_reactive_or_apparentpower_l3": 30,
        "pm__current_l1": 1,
        "pm__current_l2": 2,
        "pm__current_l3": 3,
        "pm_pv_current_1": 4,
        "pm_pv_current_2": 5,
    },
}


async def read_pm_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
    values = PM_POLL_VALUES[block.start]
    data.update(values)
    return successful_block(*values)


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_pm_totals_compute_across_device_groups(reverse: bool) -> None:
    hub, interval_group = make_pm_poll(reverse=reverse)
    hub.async_read_modbus_block = read_pm_block

    outcome, _ = await hub._refresh_interval_group_once(interval_group)

    assert outcome is PollOutcome.SUCCESS
    expected = {
        "pm_total_inverter_power": 1200,
        "pm_total_pv_power": 3500,
        "pm_total_house_load": 1000,
        "pm_total_reactive_or_apparentpower": 60,
        "pm_total_inverter_current": 6,
        "pm_total_pv_current": 9,
    }
    for key, value in expected.items():
        assert hub.data[key] == value
        hub.sensorEntities[key].modbus_data_updated.assert_called_once_with()


@pytest.mark.asyncio
async def test_cross_group_computed_dependency_chain() -> None:
    hub, interval_group = make_pm_poll(reverse=True)
    hub.async_read_modbus_block = read_pm_block
    downstream = SimpleNamespace(
        key="downstream",
        depends_on=["pm_total_pv_power"],
        value_function=lambda initval, descr, data: data["pm_total_pv_power"] / 1000,
        internal=True,
    )
    # Put the dependent first to exercise topological retries across groups.
    hub.computedSensors = {"downstream": downstream, **hub.computedSensors}
    hub.sensorDescriptions["downstream"] = downstream

    await hub._refresh_interval_group_once(interval_group)

    assert hub.data["downstream"] == 3.5


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("bad_group", ["inverter", "pm"])
@pytest.mark.parametrize("failure", ["failed", "partial", "discarded", "skipped"])
async def test_cross_group_totals_require_accepted_fresh_sources(reverse: bool, bad_group: str, failure: str) -> None:
    hub, interval_group = make_pm_poll(reverse=reverse)
    # Cached inputs must not release a calculation when this cycle's read fails.
    for values in PM_POLL_VALUES.values():
        hub.data.update(values)
    group = interval_group.device_groups[bad_group]
    if failure == "discarded":
        group.readFollowUp = AsyncMock(return_value=False)
    elif failure == "skipped":
        group.readPreparation = AsyncMock(return_value=False)

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block.start == bad_group and failure in ("failed", "partial"):
            return BlockReadResult(data_succeeded=False, communication_succeeded=failure == "partial")
        return await read_pm_block(data, block, typ)

    hub.async_read_modbus_block = read_block
    await hub._refresh_interval_group_once(interval_group)

    assert hub.data["pm_total_pv_power"] == 0
    hub.sensorEntities["pm_total_pv_power"].modbus_data_updated.assert_not_called()


@pytest.mark.asyncio
async def test_cross_group_freshness_resets_each_cycle() -> None:
    hub, interval_group = make_pm_poll()
    hub.async_read_modbus_block = read_pm_block
    await hub._refresh_interval_group_once(interval_group)
    assert hub.data["pm_total_pv_power"] == 3500
    hub.sensorEntities["pm_total_pv_power"].reset_mock()

    async def read_without_setting(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block.start == "inverter":
            return BlockReadResult(data_succeeded=False, communication_succeeded=False)
        result = await read_pm_block(data, block, typ)
        data["pm_pv_power_1"] = 2500
        return result

    hub.async_read_modbus_block = read_without_setting
    outcome, _ = await hub._refresh_interval_group_once(interval_group)

    assert outcome is PollOutcome.FAILED
    assert hub.slowdown == 10
    assert hub.data["pm_pv_power_1"] == 2500
    assert hub.data["pm_total_pv_power"] == 3500
    hub.sensorEntities["pm_total_pv_power"].modbus_data_updated.assert_not_called()


@pytest.mark.asyncio
async def test_cross_group_freshness_does_not_leak_between_scan_intervals() -> None:
    hub, interval_group = make_pm_poll()
    hub.async_read_modbus_block = read_pm_block
    for name, group in interval_group.device_groups.items():
        await hub._refresh_interval_group_once(SimpleNamespace(device_groups={name: group}))

    assert hub.data["pm_total_pv_power"] == 0


@pytest.mark.asyncio
async def test_partial_group_contributes_successful_sources_across_groups() -> None:
    hub, interval_group = make_pm_poll()
    interval_group.device_groups["inverter"].holdingBlocks.append(SimpleNamespace(start="unrelated"))

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block.start == "unrelated":
            return BlockReadResult(data_succeeded=False, communication_succeeded=False)
        return await read_pm_block(data, block, typ)

    hub.async_read_modbus_block = read_block
    outcome, _ = await hub._refresh_interval_group_once(interval_group)

    assert outcome is PollOutcome.PARTIAL
    assert hub.slowdown == 1
    assert hub.data["pm_total_pv_power"] == 3500


@pytest.mark.asyncio
async def test_rejected_snapshot_does_not_leak_computed_freshness() -> None:
    hub, interval_group = make_pm_poll()
    hub.async_read_modbus_block = read_pm_block
    cycle_fresh_keys: set[str] = set()
    await hub.async_read_modbus_data(interval_group.device_groups["inverter"], cycle_fresh_keys)
    before_rejection = cycle_fresh_keys.copy()
    group = interval_group.device_groups["pm"]
    group.readFollowUp = AsyncMock(return_value=False)

    outcome = await hub.async_read_modbus_data(group, cycle_fresh_keys)

    assert outcome is PollOutcome.DISCARDED
    assert cycle_fresh_keys == before_rejection
    assert hub.data["pm_total_pv_power"] == 0


@pytest.mark.asyncio
async def test_partial_group_commits_successful_values_and_legacy_computed_sensor() -> None:
    hub = make_hub()
    group = make_group()
    computed_sensor = Mock()
    hub.computedSensors["computed"] = SimpleNamespace(
        key="computed",
        internal=False,
        value_function=lambda initval, descr, data: data["raw"] * 2,
    )
    hub.sensorEntities["computed"] = computed_sensor

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block.start == 1:
            data["raw"] = 10
            return successful_block("raw")
        return BlockReadResult(data_succeeded=False, communication_succeeded=False)

    hub.async_read_modbus_block = read_block
    original_data_object = hub.data

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.PARTIAL
    assert hub.data is original_data_object
    assert hub.data["raw"] == 10
    assert hub.data["computed"] == 20
    assert group.publish_updates is True
    computed_sensor.modbus_data_updated.assert_called_once_with()


@pytest.mark.asyncio
async def test_partial_group_keeps_computed_value_when_dependency_is_not_fresh() -> None:
    hub = make_hub()
    hub.data.update({"source_a": 1, "source_b": 2, "computed": 3})
    hub.sensorDescriptions.update({"source_a": SimpleNamespace(), "source_b": SimpleNamespace()})
    group = make_group()
    computed_sensor = Mock()
    hub.computedSensors["computed"] = SimpleNamespace(
        key="computed",
        internal=False,
        depends_on=["source_a", "source_b"],
        value_function=lambda initval, descr, data: data["source_a"] + data["source_b"],
    )
    hub.sensorEntities["computed"] = computed_sensor

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block.start == 1:
            data["source_a"] = 10
            return BlockReadResult(
                data_succeeded=True,
                communication_succeeded=True,
                fresh_keys=frozenset({"source_a"}),
            )
        return BlockReadResult(data_succeeded=False, communication_succeeded=False)

    hub.async_read_modbus_block = read_block

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.PARTIAL
    assert hub.data["source_a"] == 10
    assert hub.data["source_b"] == 2
    assert hub.data["computed"] == 3
    assert group.publish_updates is True
    computed_sensor.modbus_data_updated.assert_not_called()


@pytest.mark.asyncio
async def test_computed_dependency_chain_uses_fresh_values() -> None:
    hub = make_hub()
    group = make_group()
    second = SimpleNamespace(
        key="second",
        internal=True,
        depends_on=["first"],
        value_function=lambda initval, descr, data: data["first"] + 1,
    )
    first = SimpleNamespace(
        key="first",
        internal=True,
        depends_on=["raw"],
        value_function=lambda initval, descr, data: data["raw"] * 2,
    )
    hub.computedSensors.update({"second": second, "first": first})
    hub.sensorDescriptions.update({"raw": SimpleNamespace(), "first": first, "second": second})

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block.start == 1:
            data["raw"] = 5
            return BlockReadResult(
                data_succeeded=True,
                communication_succeeded=True,
                fresh_keys=frozenset({"raw"}),
            )
        return BlockReadResult(data_succeeded=False, communication_succeeded=False)

    hub.async_read_modbus_block = read_block

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.PARTIAL
    assert hub.data["first"] == 10
    assert hub.data["second"] == 11


@pytest.mark.asyncio
async def test_partial_group_ignores_dependencies_not_available_for_inverter() -> None:
    hub = make_hub()
    hub.data.update({"pv_power_1": 100, "pv_power_2": 200, "pv_power_total": 300})
    hub.sensorDescriptions.update({"pv_power_1": SimpleNamespace(), "pv_power_2": SimpleNamespace()})
    group = make_group()
    computed_sensor = Mock()
    hub.computedSensors["pv_power_total"] = SimpleNamespace(
        key="pv_power_total",
        internal=False,
        depends_on=[f"pv_power_{index}" for index in range(1, 7)],
        value_function=lambda initval, descr, data: data["pv_power_1"] + data["pv_power_2"],
    )
    hub.sensorEntities["pv_power_total"] = computed_sensor

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block.start == 1:
            data.update({"pv_power_1": 150, "pv_power_2": 250})
            return successful_block("pv_power_1", "pv_power_2")
        return BlockReadResult(data_succeeded=False, communication_succeeded=False)

    hub.async_read_modbus_block = read_block

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.PARTIAL
    assert hub.data["pv_power_total"] == 400
    computed_sensor.modbus_data_updated.assert_called_once_with()


@pytest.mark.asyncio
async def test_total_communication_failure_still_discards_snapshot() -> None:
    hub = make_hub()
    group = make_group()

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        data["raw"] = 99
        return BlockReadResult(data_succeeded=False, communication_succeeded=False)

    hub.async_read_modbus_block = read_block

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.FAILED
    assert hub.data["raw"] == 1
    assert group.publish_updates is False


@pytest.mark.asyncio
async def test_tolerated_block_failure_commits_rest_of_snapshot() -> None:
    hub = make_hub()
    hub.data["unavailable"] = 5
    group = make_group()

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block.start == 1:
            data["raw"] = 10
        else:
            data.pop("unavailable", None)
        return successful_block("raw" if block.start == 1 else "unavailable")

    hub.async_read_modbus_block = read_block

    result = await hub.async_read_modbus_registers_all(group)

    assert result is PollOutcome.SUCCESS
    assert hub.data["raw"] == 10
    assert "unavailable" not in hub.data
    assert group.publish_updates is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ignore_readerror", "tolerated", "value_is_kept"),
    [
        (True, True, True),
        (False, False, False),
    ],
)
async def test_block_error_preserves_ignore_readerror_semantics(
    ignore_readerror: bool,
    tolerated: bool,
    value_is_kept: bool,
) -> None:
    hub = make_hub()
    hub.cyclecount = 20
    hub._modbus_addr = 1
    hub._record_block_result = Mock()
    hub.async_read_holding_registers = AsyncMock(return_value=SimpleNamespace(isError=lambda: True))
    description = SimpleNamespace(key="vpp_status", ignore_readerror=ignore_readerror)
    block = SimpleNamespace(
        start=0x7594,
        end=0x7595,
        regs=[0x7594],
        descriptions={0x7594: description},
    )
    data = {"vpp_status": 5}

    result = await hub.async_read_modbus_block(data, block, "holding")

    assert result == BlockReadResult(
        data_succeeded=False,
        communication_succeeded=True,
        tolerated=tolerated,
    )
    assert ("vpp_status" in data) is value_is_kept


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
    hub.async_read_modbus_block = AsyncMock(return_value=successful_block())
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

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        data["raw"] = block.start
        return successful_block("raw")

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

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        data["raw"] = 9
        return successful_block("raw")

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


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, TimeoutError("BMS read timed out")], ids=["no-response", "exception"])
async def test_sofar_validation_failure_only_discards_pack_group(response: Any) -> None:
    """A failed BMS check must not trigger global sleep/slowdown or suppress inverter updates."""
    hub = make_hub()
    hub._modbus_addr = 1
    hub.async_read_holding_registers = AsyncMock(side_effect=[response])
    config = battery_config(batt_pack_serials={0: {0: "PACK-0"}})

    async def validate_pack(old_data: dict[str, Any], new_data: dict[str, Any]) -> bool:
        return await config.check_battery_on_end(hub, old_data, new_data, "", 0, 0)

    pack_group = make_group(follow_up=validate_pack)
    inverter_group = make_group()
    pack_sensor, inverter_sensor = Mock(), Mock()
    pack_group.sensors = [pack_sensor]
    inverter_group.sensors = [inverter_sensor]
    pack_group.holdingBlocks = [SimpleNamespace(start=1)]
    inverter_group.holdingBlocks = [SimpleNamespace(start=2)]
    hub.data.update({"pack_power": 10, "inverter_power": 20, "sleep_none": 30, "sleep_zero": 40})
    hub.sleepnone = ["sleep_none"]
    hub.sleepzero = ["sleep_zero"]
    hub.blocks_changed = False
    hub.cyclecount = 1

    async def read_block(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        key = "pack_power" if block.start == 1 else "inverter_power"
        data[key] = 100
        return successful_block(key)

    hub.async_read_modbus_block = read_block
    interval_group = SimpleNamespace(device_groups={"pack": pack_group, "inverter": inverter_group})

    outcome, updated_sensors = await hub._refresh_interval_group_once(interval_group)

    assert outcome is PollOutcome.SUCCESS
    assert updated_sensors == 1
    assert hub.data["pack_power"] == 10
    assert hub.data["inverter_power"] == 100
    assert hub.data["sleep_none"] == 30
    assert hub.data["sleep_zero"] == 40
    assert hub.slowdown == 1
    pack_sensor.modbus_data_updated.assert_not_called()
    inverter_sensor.modbus_data_updated.assert_called_once_with()


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

    async def read_group(group: Any, cycle_fresh_keys: set[str] | None = None) -> PollOutcome:
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

    async def read_group(current_group: Any, cycle_fresh_keys: set[str] | None = None) -> PollOutcome:
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
async def test_partial_poll_publishes_updates_without_enabling_slowdown() -> None:
    hub = make_hub()
    sensor = Mock()
    group = make_group()
    group.sensors = [sensor]
    group.publish_updates = True
    hub.blocks_changed = False
    hub.cyclecount = 1
    hub.sleepnone = []
    hub.sleepzero = []
    hub.async_read_modbus_data = AsyncMock(return_value=PollOutcome.PARTIAL)
    interval_group = SimpleNamespace(device_groups={"test": group})

    outcome, updated_sensors = await hub._refresh_interval_group_once(interval_group)

    assert outcome is PollOutcome.PARTIAL
    assert updated_sensors == 1
    assert hub.slowdown == 1
    sensor.modbus_data_updated.assert_called_once_with()


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
