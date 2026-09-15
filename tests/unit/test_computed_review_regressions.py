"""End-to-end and semantic regressions from the computed-readiness review."""

import importlib
import time
from collections.abc import AsyncGenerator
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest
import pytest_asyncio
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from pytest_homeassistant_custom_component.common import async_test_home_assistant

from custom_components.solax_modbus.const import DOMAIN, BaseModbusSensorEntityDescription
from custom_components.solax_modbus.energy_dashboard import (
    EnergyDashboardSensorMapping,
    _create_aggregated_value_function,
    _create_sensor_from_mapping,
)
from custom_components.solax_modbus.plugin_solax import SENSOR_TYPES_MAIN
from custom_components.solax_modbus.sensor import COMMUNICATION_SENSOR_TYPES, SolaXModbusSensor

from .test_poll_snapshot import make_group, make_hub, make_pm_poll, read_pm_block, successful_block


@pytest_asyncio.fixture
async def publication_hass() -> AsyncGenerator[HomeAssistant]:
    """Provide real HA state publication with explicit strict-mode ownership."""
    async with async_test_home_assistant() as hass:
        try:
            yield hass
        finally:
            await hass.async_stop(force=True)


def description(key: str) -> Any:
    return next(item for item in SENSOR_TYPES_MAIN if item.key == key and item.register < 0)


def sources(hub: Any, data: dict[str, Any]) -> None:
    hub.data.update(data)
    hub.sensorDescriptions.update({key: BaseModbusSensorEntityDescription(key=key) for key in data})


def source_snapshot(hub: Any, fresh: set[str], *, age: float = 0) -> None:
    hub._computed_source_snapshots = {1: (time.monotonic() - age, hub.data.copy(), fresh)}


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["remotecontrol_current_pushmode_power", "remotecontrol_current_pv_power_limit"])
async def test_remote_control_number_to_none_is_published_to_ha(publication_hass: HomeAssistant, key: str) -> None:
    hass = publication_hass
    hub = make_hub()
    descr = description(key)
    entity = SolaXModbusSensor("test", hub, DeviceInfo(identifiers={(DOMAIN, "test")}), descr)
    entity.hass = hass
    entity.entity_id = f"sensor.{key}"
    await entity.async_added_to_hass()

    async def read(data: dict[str, Any], block: Any, typ: str) -> Any:
        return successful_block("raw")

    hub.async_read_modbus_block = read
    hub.data[key] = 2500
    await hub.async_read_modbus_registers_all(make_group())
    assert hass.states.is_state(entity.entity_id, "2500")
    hub.data[key] = None
    await hub.async_read_modbus_registers_all(make_group())
    assert hass.states.is_state(entity.entity_id, "unknown")
    assert entity.native_value is None
    await entity.async_will_remove_from_hass()


@pytest.mark.asyncio
async def test_computed_lease_expires_without_poll_and_recovers(publication_hass: HomeAssistant) -> None:
    hass = publication_hass
    hub = make_hub()
    sources(hub, {"a": 1000, "b": 2000})
    descr = BaseModbusSensorEntityDescription(key="sum", depends_on=["a", "b"], value_function=lambda _i, _d, data: data["a"] + data["b"])
    entity = SolaXModbusSensor("test", hub, DeviceInfo(identifiers={(DOMAIN, "test")}), descr)
    entity.hass = hass
    entity.entity_id = "sensor.computed_lease"
    await entity.async_added_to_hass()
    with patch("custom_components.solax_modbus.sensor.async_call_later") as later:
        assert hub._compute_poll_sensors(hub.data, {"a", "b"}) == {"sum"}
        entity.modbus_data_updated()
        assert hass.states.is_state(entity.entity_id, "3000")
        assert later.call_args.args[1] == hub.computed_sensor_max_age(descr)
        expiry = later.call_args.args[2]
        for _ in range(5):
            assert hub._compute_poll_sensors(hub.data, {"a"}) == set()
        assert later.call_count == 1  # Failed computations cannot renew the lease.
        assert bool(entity.available)
        expiry(None)
        assert not bool(entity.available)
        assert hass.states.is_state(entity.entity_id, "unavailable")
        assert hub.data["sum"] == 3000
        hub.data["a"] = 0
        hub.data["b"] = 0
        assert hub._compute_poll_sensors(hub.data, {"a", "b"}) == {"sum"}
        entity.modbus_data_updated()
        assert hass.states.is_state(entity.entity_id, "0")
        assert bool(entity.available)
        await entity.async_will_remove_from_hass()
        later.return_value.assert_called()


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), float("-inf")])
def test_invalid_optional_meter_is_omitted_without_mutating_source(bad: Any) -> None:
    hub = make_hub()
    sources(hub, {"inverter_power": 2500, "measured_power": 1000, "meter_2_measured_power": bad})
    assert hub.evaluate_computed_sensor(description("house_load"), hub.data, set(hub.data))
    assert hub.data["house_load"] == 1500
    assert hub.data["meter_2_measured_power"] is bad


@pytest.mark.parametrize(
    ("stale", "expected"), [(None, 2050), ("pm_total_pv_power", 2000), ("remotecontrol_active_power", 2000), ("pm_battery_power_charge", 2000)]
)
def test_parallel_house_load_never_corrects_using_stale_optional(stale: str | None, expected: int) -> None:
    hub = make_hub()
    sources(
        hub,
        {
            "pm_activepower_l1": 3000,
            "pm_activepower_l2": 0,
            "pm_activepower_l3": 0,
            "parallel_setting": "Master",
            "measured_power": 1000,
            "pm_total_pv_power": 2900,
            "pm_battery_power_charge": 0,
            "remotecontrol_active_power": 500,
        },
    )
    fresh = set(hub.data) - {stale}
    if stale == "pm_total_pv_power":
        hub.data[stale] = 3300  # Would produce 1850 with the stale correction.
    assert hub.evaluate_computed_sensor(description("pm_total_house_load"), hub.data, fresh)
    assert hub.data["pm_total_house_load"] == expected


def test_gen5_soc_does_not_mix_fresh_and_stale_batteries() -> None:
    hub = make_hub()
    sources(
        hub,
        {
            "battery_total_capacity_charge": 0,
            "battery_1_capacity_charge": 60,
            "battery_2_capacity_charge": 20,
            "bms_battery_capacity": 100,
            "bms_2_battery_capacity": 300,
        },
    )
    descr = description("battery_capacity")
    assert not hub.evaluate_computed_sensor(descr, hub.data, set(hub.data) - {"battery_2_capacity_charge"})
    assert hub.evaluate_computed_sensor(descr, hub.data, set(hub.data))
    assert hub.data["battery_capacity"] == 30
    assert hub.evaluate_computed_sensor(descr, hub.data, set(hub.data) - {"bms_2_battery_capacity"})
    assert hub.data["battery_capacity"] == 20  # Documented minimum, not a one-sided weighted average.


def test_bms_charge_fallback_waits_for_active_peer_voltage() -> None:
    hub = make_hub()
    sources(hub, {"battery_1_voltage_charge": 200, "battery_2_voltage_charge": 200, "battery_charge_max_current": 20})
    descr = description("bms_max_charge")
    assert not hub.evaluate_computed_sensor(descr, hub.data, {"battery_1_voltage_charge", "battery_charge_max_current"})
    assert hub.evaluate_computed_sensor(descr, hub.data, set(hub.data))
    assert hub.data[descr.key] == 2000


def test_fresh_alternative_does_not_use_stale_preferred_input() -> None:
    hub = make_hub()
    sources(hub, {"preferred": 100, "fallback": 2})
    descr = BaseModbusSensorEntityDescription(
        key="test",
        depends_on=[],
        depends_on_any=[("preferred", "fallback")],
        value_function=lambda _i, _d, data: data.get("preferred", data["fallback"]),
    )
    assert hub.evaluate_computed_sensor(descr, hub.data, {"fallback"})
    assert hub.data["test"] == 2


def dashboard(hub: Any, source: Any, *, parallel: bool = False) -> Any:
    hub._invertertype = 0
    mapping = EnergyDashboardSensorMapping(
        source_key="energy", target_key="ed_energy", name="Energy", source_key_pm="pm_energy" if parallel else None
    )
    return _create_sensor_from_mapping(mapping, hub, DeviceInfo(identifiers={(DOMAIN, "ed")}), source_hub=source)[0]


def test_dashboard_slave_requires_own_fresh_snapshot_and_propagates_none() -> None:
    master, slave = make_hub(), make_hub()
    sources(master, {"energy": 999})
    sources(slave, {"energy": 25})
    descr = dashboard(master, slave)
    assert master.evaluate_computed_sensor(descr, master.data, {"energy"})
    assert master.data[descr.key] is None
    source_snapshot(slave, {"energy"})
    assert master.evaluate_computed_sensor(descr, master.data, set())
    assert master.data[descr.key] == 25
    source_snapshot(slave, set())
    assert master.evaluate_computed_sensor(descr, master.data, {"energy"})
    assert master.data[descr.key] is None
    source_snapshot(slave, {"energy"}, age=10000)
    assert master.evaluate_computed_sensor(descr, master.data, {"energy"}, force=True)
    assert master.data[descr.key] is None


def test_dashboard_parallel_switch_requires_actual_selected_source() -> None:
    hub = make_hub()
    sources(hub, {"energy": 10, "pm_energy": 30, "parallel_setting": "Free"})
    descr = dashboard(hub, hub, parallel=True)
    assert hub.evaluate_computed_sensor(descr, hub.data, set(hub.data))
    assert hub.data[descr.key] == 10
    hub.data["parallel_setting"] = "Master"
    assert hub.evaluate_computed_sensor(descr, hub.data, {"energy", "parallel_setting"})
    assert hub.data[descr.key] is None
    assert hub.evaluate_computed_sensor(descr, hub.data, {"pm_energy", "parallel_setting"})
    assert hub.data[descr.key] == 30


def test_dashboard_aggregate_never_partially_sums_unknown_slave() -> None:
    master, slave = make_hub(), make_hub()
    sources(master, {"energy": 10})
    sources(slave, {"energy": 20})
    descr = dashboard(master, master)
    descr = replace(
        descr, _energy_dashboard_source_hubs=(master, slave), value_function=_create_aggregated_value_function(descr._energy_dashboard_mapping)
    )
    source_snapshot(slave, {"energy"})
    assert master.evaluate_computed_sensor(descr, master.data, {"energy"})
    assert master.data[descr.key] == 30
    slave.data["energy"] = None
    source_snapshot(slave, {"energy"})
    assert master.evaluate_computed_sensor(descr, master.data, {"energy"})
    assert master.data[descr.key] is None


@pytest.mark.asyncio
async def test_communication_descriptions_publish_through_normal_poll() -> None:
    hub = make_hub()
    hub.data.update(communication_health="Healthy", communication_success_rate=100, communication_quarantined_registers=0)
    hub.computedSensors = {descr.key: descr for descr in COMMUNICATION_SENSOR_TYPES}
    hub.sensorEntities = {key: Mock() for key in hub.computedSensors}

    async def read(data: dict[str, Any], block: Any, typ: str) -> Any:
        return successful_block("raw")

    hub.async_read_modbus_block = read
    await hub.async_read_modbus_registers_all(make_group())
    for entity in hub.sensorEntities.values():
        entity.modbus_data_updated.assert_called_once()


@pytest.mark.asyncio
async def test_rejected_group_is_absent_from_cross_hub_snapshot() -> None:
    hub, interval = make_pm_poll()
    hub.async_read_modbus_block = read_pm_block
    await hub._refresh_interval_group_once(interval)
    sample = hub._computed_source_snapshots[id(interval)]
    assert "pm_total_pv_power" in sample[2]

    async def reject(_old: Any, _new: Any) -> bool:
        return False

    interval.device_groups["pm"].readFollowUp = reject
    await hub._refresh_interval_group_once(interval)
    sample = hub._computed_source_snapshots[id(interval)]
    assert "pm_total_pv_power" not in sample[2]
    assert "pm_pv_power_1" not in sample[2]


def test_static_scan_group_contracts_can_resolve_other_intervals() -> None:
    """Unlike the review's F6 inventory, real plugin defaults span intervals."""
    from pathlib import Path

    root = Path(__file__).parents[2] / "custom_components" / "solax_modbus"
    checked = 0
    cross_interval = 0
    for path in root.glob("plugin_*.py"):
        module = importlib.import_module(f"custom_components.solax_modbus.{path.stem}")
        plugin = module.plugin_instance
        descriptions = plugin.SENSOR_TYPES
        hub = make_hub()
        hub.plugin = plugin
        hub.config = {"scan_interval": 15, "scan_interval_fast": 5, "scan_interval_medium": 10}
        hub.sensorDescriptions = {descr.key: descr for descr in descriptions}
        for descr in descriptions:
            if descr.register >= 0 or not descr.value_function:
                continue
            checked += 1
            inputs = set(descr.depends_on or [])
            raw = {key: source for key, source in hub.sensorDescriptions.items() if key in inputs and source.register >= 0}
            groups: dict[int, set[str]] = {}
            for key, source in raw.items():
                groups.setdefault(hub.scan_group(SimpleNamespace(entity_description=source)), set()).add(key)
            if len(groups) > 1:
                cross_interval += 1
                values = dict.fromkeys(raw, 1)
                hub._computed_source_snapshots = {interval: (time.monotonic(), values, keys) for interval, keys in groups.items()}
                for interval, keys in groups.items():
                    _data, accepted = hub._computed_inputs(values, keys, set(raw), interval)
                    assert set(raw) <= accepted, (path.stem, descr.key, interval)
    assert checked >= 120
    assert cross_interval > 0


@pytest.mark.parametrize("age", [0, 31])
@pytest.mark.parametrize("valid_snapshot", [True, False])
def test_other_interval_requires_latest_accepted_bounded_snapshot(age: int, valid_snapshot: bool) -> None:
    hub = make_hub()
    hub.plugin = SimpleNamespace()
    hub.config = {"scan_interval": 15, "scan_interval_fast": 5, "scan_interval_medium": 10}
    hub.sensorDescriptions = {
        "fast": BaseModbusSensorEntityDescription(key="fast", register=1, scan_group="scan_interval_fast"),
        "slow": BaseModbusSensorEntityDescription(key="slow", register=2, scan_group="scan_interval_medium"),
    }
    hub.data.update(fast=2, slow=999)
    hub._computed_source_snapshots = {10: (time.monotonic() - age, {"slow": 3}, {"slow"} if valid_snapshot else set())}
    descr = BaseModbusSensorEntityDescription(key="sum", depends_on=["fast", "slow"], value_function=lambda _i, _d, data: data["fast"] + data["slow"])
    fresh = {"fast"}
    assert hub.evaluate_computed_sensor(descr, hub.data, fresh, interval=5) is (valid_snapshot and age == 0)
    if valid_snapshot and age == 0:
        assert hub.data["sum"] == 5
    assert fresh == {"fast"}
    assert hub.data["slow"] == 999  # Snapshot overlay never rewrites raw hub state.
    assert not hub.evaluate_computed_sensor(descr, hub.data, {"slow"}, interval=5)  # Same-group failure is never filled.


def test_dashboard_separate_setting_interval_does_not_freeze_or_reuse_old_mapping() -> None:
    hub = make_hub()
    hub.config = {"scan_interval": 15, "scan_interval_fast": 5, "scan_interval_medium": 10}
    sources(hub, {"energy": 10, "pm_energy": 30, "parallel_setting": "Free"})
    hub.sensorDescriptions["parallel_setting"] = BaseModbusSensorEntityDescription(
        key="parallel_setting", register=1, scan_group="scan_interval_medium"
    )
    hub._computed_source_snapshots = {10: (time.monotonic(), {"parallel_setting": "Master"}, {"parallel_setting"})}
    descr = dashboard(hub, hub, parallel=True)
    assert hub.evaluate_computed_sensor(descr, hub.data, {"energy", "pm_energy"}, interval=5)
    assert hub.data[descr.key] == 30
    hub._computed_source_snapshots[10] = (time.monotonic(), {"parallel_setting": "Master"}, set())
    assert hub.evaluate_computed_sensor(descr, hub.data, {"energy", "pm_energy"}, interval=5)
    assert hub.data[descr.key] is None


@pytest.mark.asyncio
async def test_real_poll_uses_other_interval_then_blocks_after_its_failure() -> None:
    hub, original = make_pm_poll()
    hub.plugin = importlib.import_module("custom_components.solax_modbus.plugin_solax").plugin_instance
    hub.config = {"scan_interval": 15, "scan_interval_fast": 5, "scan_interval_medium": 10}
    slow = SimpleNamespace(interval=10, device_groups={"inverter": original.device_groups["inverter"]})
    fast = SimpleNamespace(interval=5, device_groups={"pm": original.device_groups["pm"]})
    hub.async_read_modbus_block = read_pm_block
    await hub._refresh_interval_group_once(fast)
    assert hub.data["pm_total_inverter_power"] == 0  # Uninitialized source baseline, no calculation yet.
    await hub._refresh_interval_group_once(slow)
    await hub._refresh_interval_group_once(fast)
    assert hub.data["pm_total_inverter_power"] == 1200
    before = hub.sensorEntities["pm_total_inverter_power"].modbus_data_updated.call_count

    async def reject(_old: Any, _new: Any) -> bool:
        return False

    slow.device_groups["inverter"].readFollowUp = reject
    await hub._refresh_interval_group_once(slow)
    await hub._refresh_interval_group_once(fast)
    assert hub.sensorEntities["pm_total_inverter_power"].modbus_data_updated.call_count == before
    hub.rebuild_blocks({})
    assert hub._computed_source_snapshots == {}
    await hub._refresh_interval_group_once(fast)
    assert hub.sensorEntities["pm_total_inverter_power"].modbus_data_updated.call_count == before
