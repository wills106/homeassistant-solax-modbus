"""Conditional source selection and control validity through accepted polls."""

import time
from collections.abc import AsyncGenerator
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from pytest_homeassistant_custom_component.common import async_test_home_assistant

from custom_components.solax_modbus import BlockReadResult, InputObservation
from custom_components.solax_modbus.const import BUTTONREPEAT_POST, DOMAIN
from custom_components.solax_modbus.plugin_solax import BUTTON_TYPES, SENSOR_TYPES_MAIN, autorepeat_function_powercontrolmode8_recompute
from custom_components.solax_modbus.sensor import SolaXModbusSensor

from .test_poll_snapshot import make_group
from .test_vpp_poll_cadence import computed, prime, setup_vpp


@pytest_asyncio.fixture
async def vpp_hass() -> AsyncGenerator[HomeAssistant]:
    """Use an explicit async fixture under the project's strict asyncio mode."""
    async with async_test_home_assistant() as hass:
        try:
            yield hass
        finally:
            await hass.async_stop(force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("batteries", [1, 2])
@pytest.mark.parametrize("total", [0, None])
async def test_soc_fallback_requires_all_installed_batteries(batteries: int, total: Any) -> None:
    hub, power, settings, values, _function = setup_vpp()
    if batteries == 1:
        hub.sensorDescriptions.pop("battery_2_capacity_charge")
        for group in settings.device_groups.values():
            for block in group.holdingBlocks:
                block.descriptions = {key: d for key, d in block.descriptions.items() if d.key != "battery_2_capacity_charge"}
    values.update(battery_total_capacity_charge=total, battery_1_capacity_charge=80, battery_2_capacity_charge=20)
    await prime(hub, power, settings)
    assert hub.data["battery_capacity"] == (80 if batteries == 1 else 20)
    values.pop("battery_1_capacity_charge")
    await hub._refresh_interval_group_once(settings)
    assert hub._accepted_input_sample("battery_capacity", include_pending=False) is None
    assert hub.data["remotecontrol_current_pushmode_power"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("capacity1", "capacity2", "expected"), [(10000, 10000, 50), (10000, 0, 20), (0, 10000, 20), (None, 10000, 20)])
async def test_soc_weighting_never_uses_one_sided_capacity(capacity1: Any, capacity2: Any, expected: int) -> None:
    hub, _power, settings, values, _function = setup_vpp()
    values.update(battery_total_capacity_charge=0, battery_1_capacity_charge=80, battery_2_capacity_charge=20)
    for key, value in (("bms_battery_capacity", capacity1), ("bms_2_battery_capacity", capacity2)):
        hub.sensorDescriptions[key] = replace(next(d for d in SENSOR_TYPES_MAIN if d.key == key and d.register >= 0), scan_group="scan_interval")
        values[key] = value
        group = make_group()
        group.holdingBlocks = [SimpleNamespace(start=3, descriptions={0: hub.sensorDescriptions[key]})]
        settings.device_groups[key] = group
    await hub._refresh_interval_group_once(settings)
    assert hub.data["battery_capacity"] == expected


@pytest.mark.asyncio
async def test_expired_unused_metadata_cannot_shorten_authoritative_soc_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    hub, power, settings, values, _function = setup_vpp()
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    await prime(hub, power, settings)
    hub.data["_repeatUntil"].clear()
    for key in ("bms_battery_capacity", "bms_2_battery_capacity"):
        hub.sensorDescriptions[key] = next(d for d in SENSOR_TYPES_MAIN if d.key == key and d.register >= 0)
        hub._computed_input_observations[key] = InputObservation(now[0] - 20, 10000, now[0] + 1)
    now[0] += 2
    values["battery_total_capacity_charge"] = 20
    await hub._refresh_interval_group_once(settings)
    assert hub.data["battery_capacity"] == 20
    assert hub._computed_input_observations["battery_capacity"].deadline == now[0] + 45


@pytest.mark.asyncio
@pytest.mark.parametrize("battery", [1, 2])
@pytest.mark.parametrize("bms_current", [None, 0, 20])
async def test_bms_fallback_selects_real_current_and_voltage(battery: int, bms_current: Any) -> None:
    hub, _power, settings, values, _function = setup_vpp()
    values.update(
        battery_1_voltage_charge=400,
        battery_2_voltage_charge=400,
        battery_charge_max_current=30,
        bms_charge_max_current=bms_current,
        bms_2_charge_max_current=bms_current,
    )
    key = "bms_max_charge" if battery == 1 else "bms_2_max_charge"
    hub.computedSensors[key] = computed(key)
    hub.sensorDescriptions[key] = hub.computedSensors[key]
    for source in (
        "battery_1_voltage_charge",
        "battery_2_voltage_charge",
        "battery_charge_max_current",
        "bms_charge_max_current",
        "bms_2_charge_max_current",
    ):
        hub.sensorDescriptions[source] = replace(
            next(d for d in SENSOR_TYPES_MAIN if d.key == source and d.register >= 0), scan_group="scan_interval"
        )
        group = make_group()
        group.holdingBlocks = [SimpleNamespace(start=3, descriptions={0: hub.sensorDescriptions[source]})]
        settings.device_groups[source] = group
    await hub._refresh_interval_group_once(settings)
    assert hub.data[key] == (6000 if bms_current is None else bms_current * 400)
    assert hub._accepted_input_sample(key) is not None
    # A fresh dedicated BMS current doesn't consume the unused total current.
    values["battery_charge_max_current"] = None
    await hub._refresh_interval_group_once(settings)
    assert (hub._accepted_input_sample(key) is not None) == (bms_current is not None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "Mode 8 - PV and BAT control - Duration",
        "Negative Injection Price",
        "Negative Injection and Consumption Price",
        "Enabled Feedin Priority",
        "Enabled No Discharge",
        "Export-First Battery Limit",
    ],
)
@pytest.mark.parametrize(("pv", "grid"), [(0, -1000), (40000, 25000)])
async def test_fixed_inputs_reject_unread_installed_bms_limits_in_every_submode(mode: str, pv: int, grid: int) -> None:
    hub, power, settings, values, function = setup_vpp()
    hub.data["remotecontrol_power_control_mode"] = mode
    values.update(pv_power_1=pv, measured_power=grid)
    for key in ("bms_max_charge", "bms_2_max_charge"):
        hub.sensorDescriptions[key] = computed(key)
        hub.data[key] = 8000
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["remotecontrol_current_pushmode_power"] is None


@pytest.mark.asyncio
async def test_fixed_inputs_require_installed_individual_limits_even_with_valid_total() -> None:
    hub, power, settings, values, function = setup_vpp()
    key = "battery_max_charge_power"
    hub.sensorDescriptions[key] = replace(next(d for d in SENSOR_TYPES_MAIN if d.key == key), scan_group="scan_interval")
    values[key] = 6000
    group = make_group()
    group.holdingBlocks = [SimpleNamespace(start=3, descriptions={0: hub.sensorDescriptions[key]})]
    settings.device_groups[key] = group
    for bms in ("bms_max_charge", "bms_2_max_charge"):
        hub.sensorDescriptions[bms] = computed(bms)
    values.update(pv_power_1=40000, measured_power=25000)
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    assert hub.data[key] == 6000
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["remotecontrol_current_pushmode_power"] is None


@pytest.mark.asyncio
async def test_rejected_followup_does_not_leak_new_soc_to_control() -> None:
    hub, power, settings, values, function = setup_vpp()
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    values["battery_total_capacity_charge"] = 20
    for group in settings.device_groups.values():
        group.readFollowUp = AsyncMock(return_value=False)
    await hub._refresh_interval_group_once(settings)
    assert hub.data["battery_capacity"] == 80
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["remotecontrol_current_pushmode_power"] is None
    assert hub._pending_input_observations is None


@pytest.mark.asyncio
async def test_stop_request_works_without_any_measured_inputs() -> None:
    hub, power, _settings, _values, function = setup_vpp()
    hub.data["remotecontrol_power_control_mode"] = "Disabled"
    hub.data["_repeatUntil"]["powercontrolmode8_trigger"] = time.time() + 300
    # No first accepted sample: disabling is independent of measurement readiness.
    await hub._refresh_interval_group_once(power)
    assert function.call_count == 1
    assert hub.data["_repeatUntil"]["powercontrolmode8_trigger"] == 0
    assert hub.data["remotecontrol_current_pushmode_power"] is None


@pytest.mark.asyncio
async def test_modes_1_to_7_validate_parallel_sources() -> None:
    hub, power, settings, values, _function = setup_vpp()
    await prime(hub, power, settings)
    hub.data["_repeatUntil"].clear()
    descr = next(d for d in BUTTON_TYPES if d.key == "remotecontrol_trigger")
    function = Mock(wraps=descr.value_function)
    hub.computedEntities[descr.key] = replace(descr, value_function=function)
    hub.data["remotecontrol_power_control"] = "Enabled Feedin Priority"
    values["parallel_setting"] = "Master"
    await hub._refresh_interval_group_once(settings)
    hub.data["_repeatUntil"][descr.key] = time.time() + 300
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == [("remotecontrol_power_control", "Disabled")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "Mode 8 - PV and BAT control - Duration",
        "Negative Injection Price",
        "Negative Injection and Consumption Price",
        "Enabled Feedin Priority",
        "Enabled No Discharge",
        "Export-First Battery Limit",
    ],
)
@pytest.mark.parametrize(("pv", "grid"), [(0, -1000), (40000, 25000)])
async def test_healthy_loop_matches_existing_controller_for_one_step(mode: str, pv: int, grid: int) -> None:
    hub, power, settings, values, _function = setup_vpp()
    hub.data["remotecontrol_power_control_mode"] = mode
    values.update(pv_power_1=pv, measured_power=grid, battery_max_charge_power=6000)
    key = "battery_max_charge_power"
    hub.sensorDescriptions[key] = replace(next(d for d in SENSOR_TYPES_MAIN if d.key == key), scan_group="scan_interval")
    group = make_group()
    group.holdingBlocks = [SimpleNamespace(start=3, descriptions={0: hub.sensorDescriptions[key]})]
    settings.device_groups[key] = group
    await prime(hub, power, settings)
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    expected_data = hub.data.copy()
    expected = autorepeat_function_powercontrolmode8_recompute(1, descr, expected_data)
    await hub._refresh_interval_group_once(power)
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == expected["data"]
    assert hub.data["remotecontrol_current_pushmode_power"] == expected_data["remotecontrol_current_pushmode_power"]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["inverter_power_l2", "pv_power_1", "battery_1_power_charge"])
async def test_boolean_raw_power_cannot_hide_behind_numeric_computation(key: str) -> None:
    hub, power, settings, values, function = setup_vpp()
    await prime(hub, power, settings)
    values[key] = False
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["remotecontrol_current_pushmode_power"] is None


@pytest.mark.asyncio
async def test_local_filter_outputs_remain_authoritative_when_published_as_sensors() -> None:
    hub, power, settings, _values, _function = setup_vpp()
    await prime(hub, power, settings)
    for key in ("remotecontrol_current_pushmode_power", "remotecontrol_current_pv_power_limit"):
        hub.sensorDescriptions[key] = computed(key)
        hub._computed_input_observations[key] = InputObservation(time.monotonic(), 0, time.monotonic() + 100)
    await hub._refresh_interval_group_once(power)
    assert hub.data["remotecontrol_current_pushmode_power"] == 210
    await hub._refresh_interval_group_once(power)
    assert hub.data["remotecontrol_current_pushmode_power"] == 378


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [True, False])
async def test_cleanup_publishes_inactive_none_on_failed_or_skipped_poll(vpp_hass: HomeAssistant, failed: bool) -> None:
    hub, power, settings, _values, _function = setup_vpp()
    descr = computed("remotecontrol_current_pushmode_power")
    entity = SolaXModbusSensor("solax", hub, DeviceInfo(identifiers={(DOMAIN, "test")}), descr)
    entity.hass = vpp_hass
    entity.entity_id = "sensor.vpp_current_push"
    await entity.async_added_to_hass()
    try:
        await prime(hub, power, settings)
        await hub._refresh_interval_group_once(power)
        assert vpp_hass.states.is_state(entity.entity_id, "210")
        if failed:

            async def fail(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
                return BlockReadResult(data_succeeded=False, communication_succeeded=False)

            hub.async_read_modbus_block = fail
        else:
            now = time.monotonic()
            hub._computed_input_observations["measured_power"] = InputObservation(now, -1000, now - 1)
            hub.slowdown = 10
            hub.cyclecount = 1
        await hub._refresh_interval_group_once(power)
        assert hub.data[descr.key] is None
        assert vpp_hass.states.is_state(entity.entity_id, "unknown")
        assert entity.available
    finally:
        await entity.async_will_remove_from_hass()
