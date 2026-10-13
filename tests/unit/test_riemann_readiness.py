"""Energy integrals must not turn communication gaps into measured energy."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.const import CONF_SCAN_INTERVAL

from custom_components.solax_modbus import BlockReadResult, InputObservation
from custom_components.solax_modbus.const import BaseModbusSensorEntityDescription, PollOutcome
from custom_components.solax_modbus.energy_dashboard import EnergyDashboardSensorMapping
from custom_components.solax_modbus.sensor import RiemannSumEnergySensor

from .test_poll_snapshot import make_group, make_hub, successful_block


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch, clock_start: float) -> list[float]:
    """Control sample/expiry time without sleeping or accessing a device."""
    now = [clock_start]
    monkeypatch.setattr("custom_components.solax_modbus.sensor.time.monotonic", lambda: now[0])
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", Mock())
    return now


def make_integral(*, source_hub: Any = None, source_key: str = "power", key: str = "energy", mapping: Any = None) -> tuple[Any, Any]:
    hub = make_hub()
    data_hub = source_hub or hub
    data_hub.config = {CONF_SCAN_INTERVAL: 15}
    data_hub.sensorDescriptions[source_key] = BaseModbusSensorEntityDescription(key=source_key, register=1)
    mapping = mapping or EnergyDashboardSensorMapping(source_key=source_key, target_key=key, name="Energy", use_riemann_sum=True)
    description = BaseModbusSensorEntityDescription(
        key=key, depends_on=[source_key], _is_riemann_sum_sensor=True, _riemann_mapping=mapping, _riemann_data_hub=data_hub
    )
    entity = RiemannSumEnergySensor("test", hub, cast(Any, None), description)
    cast(Any, entity).hass = Mock()
    cast(Any, entity).async_write_ha_state = Mock()
    cast(Any, entity).async_get_last_extra_data = AsyncMock(return_value=None)
    hub.sensorEntities[key] = entity
    return entity, data_hub


def observe(hub: Any, clock: list[float], value: Any, *, fresh: bool = True) -> None:
    hub.data["power"] = value
    hub._computed_source_snapshots = {15: (clock[0], hub.data.copy(), {"power"} if fresh else set())}


def test_startup_requires_an_accepted_power_observation(clock: list[float]) -> None:
    entity, hub = make_integral()
    hub.data["power"] = 3600
    assert entity.native_value is None
    entity.modbus_data_updated()
    assert not entity.available
    assert entity.native_value is None
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.available
    assert entity.native_value == 0
    clock[0] += 15
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.native_value == 0.015


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), float("-inf"), "unknown", "3600", True])
def test_invalid_input_preserves_total_and_breaks_interval(clock: list[float], bad: Any) -> None:
    entity, hub = make_integral()
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    clock[0] += 15
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    clock[0] += 15
    observe(hub, clock, bad)
    entity.modbus_data_updated()
    assert not entity.available
    assert entity.native_value == 0.015
    clock[0] += 15
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.available
    assert entity.native_value == 0.015  # No trapezoid across the invalid sample.
    clock[0] += 15
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.native_value == 0.030


def test_duplicate_callbacks_do_not_integrate_or_renew_lease(clock: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    later = Mock()
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", later)
    entity, hub = make_integral()
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    for _ in range(3):
        clock[0] += 10
        entity.modbus_data_updated()
    assert entity.native_value == 0
    assert later.call_count == 1
    clock[0] += 16
    entity.modbus_data_updated()
    assert not entity.available
    assert entity._last_update_time is None


def test_expiry_without_callbacks_breaks_gap_and_keeps_total(clock: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    later = Mock()
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", later)
    entity, hub = make_integral()
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert later.call_args.args[1] == pytest.approx(45.0, rel=0, abs=1e-9)
    clock[0] += 46
    later.call_args.args[2](None)
    assert not entity.available
    clock[0] += 600
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.available
    assert entity.native_value == 0


def test_long_gap_is_not_bridged_even_before_delayed_expiry_callback(clock: list[float]) -> None:
    entity, hub = make_integral()
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    clock[0] += 600
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.native_value == 0


def test_valid_zero_and_filter_are_not_missing_data(clock: list[float]) -> None:
    entity, hub = make_integral()
    entity._filter_function = lambda value: max(0, -value)
    observe(hub, clock, -7200)
    entity.modbus_data_updated()
    clock[0] += 15
    observe(hub, clock, 0)
    entity.modbus_data_updated()
    assert entity.available
    assert entity.native_value == 0.015
    clock[0] += 15
    observe(hub, clock, 1000)
    entity.modbus_data_updated()
    assert entity.native_value == 0.015


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), True])
def test_invalid_filtered_power_is_rejected(clock: list[float], bad: Any) -> None:
    entity, hub = make_integral()
    entity._filter_function = lambda _value: bad
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert not entity.available
    assert entity.native_value is None


def test_slave_integral_uses_slave_snapshot_not_master_cached_mirror(clock: list[float]) -> None:
    slave = make_hub()
    entity, _ = make_integral(source_hub=slave, key="slave_pv_energy_1")
    entity._hub.data.update(power=999999, slave_pv_power_1=999999)
    observe(slave, clock, 3600)
    entity.modbus_data_updated()
    clock[0] += 15
    observe(slave, clock, 3600)
    entity.modbus_data_updated()
    assert entity.native_value == 0.015
    clock[0] += 15
    observe(slave, clock, 3600, fresh=False)
    entity.modbus_data_updated()
    assert not entity.available
    assert entity.native_value == 0.015


def test_unrelated_interval_cannot_redate_overlaid_power(clock: list[float]) -> None:
    entity, hub = make_integral()
    first_sample = clock[0]
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    clock[0] += 10
    hub._computed_source_snapshots[5] = (clock[0], hub.data.copy(), {"other"})
    entity.modbus_data_updated()
    assert entity.native_value == 0
    assert entity._last_update_time == first_sample


@pytest.mark.parametrize("fresh", [set(), {"power"}])
def test_new_failed_source_interval_cannot_fall_back_to_older_computation(clock: list[float], fresh: set[str]) -> None:
    entity, hub = make_integral()
    hub.sensorDescriptions["power"] = BaseModbusSensorEntityDescription(key="power", depends_on=["a", "b"])
    hub.sensorDescriptions["a"] = BaseModbusSensorEntityDescription(key="a", register=1)
    hub.sensorDescriptions["b"] = BaseModbusSensorEntityDescription(key="b", register=2)
    hub.scan_group = lambda sensor: 30 if sensor.entity_description.key == "b" else 15
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    clock[0] += 15
    hub._computed_source_snapshots[30] = (clock[0], {"power": 3600}, {"power"})
    entity.modbus_data_updated()
    assert entity.native_value == 0.015
    clock[0] += 15
    hub._computed_source_snapshots[15] = (clock[0], {"power": None if fresh else 3600}, fresh)
    entity.modbus_data_updated()
    assert not entity.available
    clock[0] += 15
    hub._computed_source_snapshots[15] = (clock[0], {"power": 3600}, {"power"})
    entity.modbus_data_updated()
    assert entity.native_value == 0.015


def test_parallel_source_change_breaks_integration_interval(clock: list[float]) -> None:
    mapping = EnergyDashboardSensorMapping(source_key="power", source_key_pm="pm_power", target_key="energy", name="Energy", use_riemann_sum=True)
    entity, hub = make_integral(mapping=mapping)
    hub.sensorDescriptions["pm_power"] = BaseModbusSensorEntityDescription(key="pm_power", register=2)
    hub.sensorDescriptions["parallel_setting"] = BaseModbusSensorEntityDescription(key="parallel_setting", register=3)
    hub.data.update(power=3600, pm_power=7200, parallel_setting="Free")
    hub._computed_source_snapshots = {15: (clock[0], hub.data.copy(), set(hub.data))}
    entity.modbus_data_updated()
    clock[0] += 15
    hub.data["parallel_setting"] = "Master"
    hub._computed_source_snapshots = {15: (clock[0], hub.data.copy(), set(hub.data))}
    entity.modbus_data_updated()
    assert entity.native_value == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [PollOutcome.FAILED, PollOutcome.PARTIAL, PollOutcome.DISCARDED])
async def test_poll_snapshot_published_before_integral_and_failure_breaks_gap(clock: list[float], outcome: PollOutcome) -> None:
    entity, hub = make_integral()
    hub.blocks_changed = False
    hub.cyclecount = 0
    hub.sleepnone = []
    hub.sleepzero = []
    group = make_group()
    group.sensors = [entity]
    interval = SimpleNamespace(interval=15, device_groups={"test": group})
    hub.async_read_modbus_block = AsyncMock(return_value=successful_block("power"))
    hub.data["power"] = 3600
    await hub._refresh_interval_group_once(interval)
    clock[0] += 15
    await hub._refresh_interval_group_once(interval)
    assert entity.native_value == 0.015
    clock[0] += 15
    if outcome is PollOutcome.DISCARDED:
        group.readFollowUp = AsyncMock(return_value=False)
    else:
        hub.async_read_modbus_block = AsyncMock(
            return_value=BlockReadResult(data_succeeded=False, communication_succeeded=outcome is PollOutcome.PARTIAL)
        )
    result, _ = await hub._refresh_interval_group_once(interval)
    assert result is outcome
    assert not entity.available
    assert entity.native_value == 0.015
    clock[0] += 150
    group.readFollowUp = None
    hub.async_read_modbus_block = AsyncMock(return_value=successful_block("power"))
    await hub._refresh_interval_group_once(interval)
    assert entity.available
    assert entity.native_value == 0.015
    assert hub.slowdown == 1


@pytest.mark.asyncio
async def test_restored_total_survives_restart_without_integrating_downtime(clock: list[float]) -> None:
    entity, hub = make_integral()
    entity.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="12.5", attributes={}))
    hub.async_add_solax_modbus_sensor = AsyncMock()
    hub._name = None  # No optional debug override in this test.
    await entity.async_added_to_hass()
    assert entity.native_value == 12.5
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.native_value == 12.5
    clock[0] += 15
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.native_value == 12.515


@pytest.mark.asyncio
async def test_partial_poll_with_accepted_power_still_integrates(clock: list[float]) -> None:
    entity, hub = make_integral()
    hub.blocks_changed = False
    hub.cyclecount = 0
    hub.sleepnone = []
    hub.sleepzero = []
    group = make_group()
    group.sensors = [entity]
    interval = SimpleNamespace(interval=15, device_groups={"test": group})

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        if block.start == 1:
            data["power"] = 3600
            return successful_block("power")
        return BlockReadResult(data_succeeded=False, communication_succeeded=False)

    hub.async_read_modbus_block = read
    result, _ = await hub._refresh_interval_group_once(interval)
    assert result is PollOutcome.PARTIAL
    clock[0] += 15
    await hub._refresh_interval_group_once(interval)
    assert entity.available
    assert entity.native_value == 0.015


def test_filter_exception_preserves_total(clock: list[float]) -> None:
    entity, hub = make_integral()
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    entity._filter_function = lambda _value: 1 / 0
    clock[0] += 15
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert not entity.available
    assert entity.native_value == 0


def test_midnight_reset_and_reactivation_do_not_bridge_gaps(clock: list[float]) -> None:
    entity, hub = make_integral()
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    clock[0] += 15
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    entity._last_reset_date -= timedelta(days=1)
    clock[0] += 15
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.native_value == 0
    entity.set_energy_dashboard_active(False)
    clock[0] += 600
    entity.set_energy_dashboard_active(True)
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.native_value == 0


def test_source_interval_controls_expiry(clock: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    later = Mock()
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", later)
    entity, hub = make_integral()
    hub.scan_group = Mock(return_value=30)
    hub.sensorDescriptions["power"] = replace(hub.sensorDescriptions["power"], register=1)
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert later.call_args.args[1] == pytest.approx(90.0, rel=0, abs=1e-9)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unknown", "unavailable"])
@pytest.mark.parametrize("clock_start", [1000.0, 1.1, 1.4, 113.2])
async def test_restart_during_outage_restores_saved_total(clock: list[float], state: str) -> None:
    # Fractional clock origins expose subtraction rounding on either platform.
    entity, hub = make_integral()
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    clock[0] += 15
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    entity._expire_computed(None)
    saved_extra = entity.extra_restore_state_data
    saved_energy = saved_extra.as_dict()["energy"]
    assert saved_energy == pytest.approx(0.015, rel=0, abs=1e-12)
    restored, restored_hub = make_integral()
    restored.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state=state, attributes={}))
    restored.async_get_last_extra_data = AsyncMock(return_value=saved_extra)
    restored_hub.async_add_solax_modbus_sensor = AsyncMock()
    restored_hub._name = None
    await restored.async_added_to_hass()
    assert restored.extra_restore_state_data.as_dict()["energy"] == saved_energy
    assert restored.native_value == 0.015
    clock[0] += 600
    observe(restored_hub, clock, 3600)
    restored.modbus_data_updated()
    assert restored.extra_restore_state_data.as_dict()["energy"] == saved_energy
    assert restored.native_value == 0.015


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "bad", True, None])
async def test_invalid_restored_total_starts_unknown(clock: list[float], bad: Any) -> None:
    entity, hub = make_integral()
    entity.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="unavailable", attributes={}))
    entity.async_get_last_extra_data = AsyncMock(return_value=SimpleNamespace(as_dict=lambda: {"energy": bad}))
    hub.async_add_solax_modbus_sensor = AsyncMock()
    hub._name = None
    await entity.async_added_to_hass()
    assert entity.native_value is None
    observe(hub, clock, 0)
    entity.modbus_data_updated()
    assert entity.native_value == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("saved_energy", "published_energy"), [(0.015000000000000003, 0.015), (12.3456789, 12.346), (0.0, 0.0)])
async def test_restored_total_is_rounded_for_publication_only(clock: list[float], saved_energy: float, published_energy: float) -> None:
    entity, hub = make_integral()
    entity.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state="unavailable", attributes={}))
    entity.async_get_last_extra_data = AsyncMock(return_value=SimpleNamespace(as_dict=lambda: {"energy": saved_energy}))
    hub.async_add_solax_modbus_sensor = AsyncMock()
    hub._name = None
    await entity.async_added_to_hass()
    assert "energy" not in hub.data  # Exercise the restored-value fallback.
    assert entity.native_value == published_energy
    assert entity._total_energy == saved_energy
    assert entity.extra_restore_state_data.as_dict()["energy"] == saved_energy
    clock[0] += 600
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    assert entity.native_value == published_energy
    assert entity._total_energy == saved_energy
    assert entity.extra_restore_state_data.as_dict()["energy"] == saved_energy


def test_switching_source_hubs_does_not_bridge_same_named_inputs(clock: list[float]) -> None:
    entity, hub = make_integral()
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    _, other = make_integral()
    clock[0] += 15
    observe(other, clock, 7200)
    entity.entity_description = replace(entity.entity_description, _riemann_data_hub=other)
    entity.modbus_data_updated()
    assert entity.native_value == 0


@pytest.mark.asyncio
async def test_removal_cancels_expiry(clock: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    later = Mock()
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", later)
    entity, hub = make_integral()
    hub.async_remove_solax_modbus_sensor = AsyncMock()
    observe(hub, clock, 3600)
    entity.modbus_data_updated()
    await entity.async_will_remove_from_hass()
    later.return_value.assert_called_once_with()
    assert entity._cancel_computed_expiry is None
    assert "energy" not in hub.sensorEntities


def make_parallel_integral(clock: list[float], *, topology_interval: int = 15) -> tuple[Any, Any]:
    """Use the real accepted-observation path for mixed power/topology polls."""
    mapping = EnergyDashboardSensorMapping(source_key="power", source_key_pm="pm_power", target_key="energy", name="Energy", use_riemann_sum=True)
    entity, hub = make_integral(mapping=mapping)
    hub.sensorDescriptions["pm_power"] = BaseModbusSensorEntityDescription(key="pm_power", register=2)
    hub.sensorDescriptions["parallel_setting"] = BaseModbusSensorEntityDescription(key="parallel_setting", register=3)
    hub.scan_group = lambda sensor: topology_interval if sensor.entity_description.key == "parallel_setting" else 15
    hub.data.update(power=3600, pm_power=7200, parallel_setting="Free")
    hub._computed_input_observations = {
        key: InputObservation(clock[0], hub.data[key], clock[0] + 3 * (topology_interval if key == "parallel_setting" else 15))
        for key in ("power", "pm_power", "parallel_setting")
    }
    hub._computed_source_snapshots = {15: (clock[0], hub.data.copy(), {"power", "pm_power", "parallel_setting"})}
    return entity, hub


def observe_parallel_input(hub: Any, clock: list[float], key: str, value: Any, *, interval: int) -> None:
    hub.data[key] = value
    hub._computed_input_observations[key] = InputObservation(clock[0], value, clock[0] + 3 * interval)
    hub._computed_source_snapshots[interval] = (clock[0], hub.data.copy(), {key})


def test_parallel_selector_deadline_limits_energy_lease(clock: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    later = Mock()
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", later)
    entity, _hub = make_parallel_integral(clock, topology_interval=5)
    entity.modbus_data_updated()
    assert later.call_args.args[1] == pytest.approx(15.0, rel=0, abs=1e-9)


@pytest.mark.parametrize("run_expiry_callback", [False, True])
def test_parallel_selector_expiry_recovery_does_not_bridge_gap(
    clock: list[float], monkeypatch: pytest.MonkeyPatch, run_expiry_callback: bool
) -> None:
    later = Mock()
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", later)
    entity, hub = make_parallel_integral(clock, topology_interval=5)
    entity.modbus_data_updated()
    clock[0] += 16
    if run_expiry_callback:
        later.call_args.args[2](None)
    clock[0] += 4
    observe_parallel_input(hub, clock, "parallel_setting", "Free", interval=5)
    entity.modbus_data_updated()
    clock[0] += 10
    observe_parallel_input(hub, clock, "power", 3600, interval=15)
    entity.modbus_data_updated()
    assert entity.available
    assert entity.native_value == 0


def test_parallel_switch_waits_for_power_observed_after_switch(clock: list[float]) -> None:
    entity, hub = make_parallel_integral(clock, topology_interval=5)
    entity.modbus_data_updated()
    clock[0] += 10
    observe_parallel_input(hub, clock, "parallel_setting", "Master", interval=5)
    entity.modbus_data_updated()
    assert entity.native_value == 0
    clock[0] += 10
    observe_parallel_input(hub, clock, "pm_power", 7200, interval=15)
    entity.modbus_data_updated()
    assert entity.available
    assert entity.native_value == 0
    clock[0] += 2
    observe_parallel_input(hub, clock, "parallel_setting", "Master", interval=5)
    entity.modbus_data_updated()
    clock[0] += 13
    observe_parallel_input(hub, clock, "pm_power", 7200, interval=15)
    entity.modbus_data_updated()
    assert entity.native_value == 0.03


def test_unchanged_topology_can_refresh_its_lease_without_redating_power(clock: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    later = Mock()
    monkeypatch.setattr("custom_components.solax_modbus.sensor.async_call_later", later)
    entity, hub = make_parallel_integral(clock, topology_interval=5)
    first_power_time = clock[0]
    entity.modbus_data_updated()
    clock[0] += 10
    observe_parallel_input(hub, clock, "parallel_setting", "Free", interval=5)
    entity.modbus_data_updated()
    assert entity._last_update_time == first_power_time
    assert entity.native_value == 0
    assert later.call_args.args[1] == pytest.approx(15.0, rel=0, abs=1e-9)
    clock[0] += 10
    observe_parallel_input(hub, clock, "power", 3600, interval=15)
    entity.modbus_data_updated()
    assert entity.native_value == 0.02


def test_switching_to_hub_with_cached_power_waits_for_its_next_observation(clock: list[float]) -> None:
    entity, hub = make_integral()
    _, other = make_integral()
    observe(hub, clock, 3600)
    observe(other, clock, 7200)
    entity.modbus_data_updated()
    clock[0] += 10
    entity.entity_description = replace(entity.entity_description, _riemann_data_hub=other)
    entity.modbus_data_updated()
    clock[0] += 10
    observe(other, clock, 7200)
    entity.modbus_data_updated()
    assert entity.native_value == 0
    clock[0] += 15
    observe(other, clock, 7200)
    entity.modbus_data_updated()
    assert entity.native_value == 0.03
