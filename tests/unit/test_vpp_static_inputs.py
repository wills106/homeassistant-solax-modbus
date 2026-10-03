"""TCWORLD review: fixed control inputs and generation-specific BMS voltages."""

import time
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from custom_components.solax_modbus.const import BUTTONREPEAT_POST
from custom_components.solax_modbus.plugin_solax import BUTTON_TYPES, GEN4, GEN5, SENSOR_TYPES_MAIN

from .test_computed_review_regressions import sources
from .test_poll_snapshot import make_group, make_hub
from .test_vpp_poll_cadence import prime, setup_vpp


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["Mode 8 - PV and BAT control - Duration", "Enabled Feedin Priority", "Export-First Battery Limit"])
@pytest.mark.parametrize("invalid", [None, float("nan"), True])
async def test_unused_installed_limit_is_required_across_submodes(mode: str, invalid: Any) -> None:
    hub, power, settings, values, function = setup_vpp()
    key = "battery_charge_upper_soc"
    hub.sensorDescriptions[key] = replace(next(d for d in SENSOR_TYPES_MAIN if d.key == key), scan_group="scan_interval")
    group = make_group()
    group.holdingBlocks = [SimpleNamespace(start=3, descriptions={0: hub.sensorDescriptions[key]})]
    settings.device_groups[key] = group
    values[key] = 100
    hub.data["remotecontrol_power_control_mode"] = mode
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    assert hub.data["remotecontrol_current_pushmode_power"] is not None
    values[key] = invalid
    # An invalid installed setting stops even on a non-owner poll, with no
    # charging-path calculation to decide whether this sub-mode needs it.
    await hub._refresh_interval_group_once(settings)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["remotecontrol_current_pushmode_power"] is None
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == [("remotecontrol_power_control_mode", "Disabled")]


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["remotecontrol_trigger", "powercontrolmode8_trigger"])
async def test_free_does_not_require_unread_pm_descriptions(trigger: str) -> None:
    hub, power, settings, _values, _function = setup_vpp()
    for key in ("pm_total_pv_power", "pm_total_inverter_power", "pm_battery_power_charge", "pm_total_house_load"):
        hub.sensorDescriptions[key] = next(d for d in SENSOR_TYPES_MAIN if d.key == key)
        hub.data[key] = 9000  # No accepted observation; PM is not polled in Free.
    descr = next(d for d in BUTTON_TYPES if d.key == trigger)
    function = Mock(wraps=descr.value_function)
    hub.computedEntities = {trigger: replace(descr, value_function=function)}
    hub.data["remotecontrol_power_control"] = "Enabled Feedin Priority"
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    hub.data["_repeatUntil"][trigger] = time.time() + 300
    await hub._refresh_interval_group_once(power)
    assert function.call_count == hub.async_write_registers_multi.await_count == 1
    assert function.call_args.args[0] != BUTTONREPEAT_POST
    assert hub.data["_repeatUntil"][trigger] > time.time()


@pytest.mark.parametrize("generation", [GEN4, GEN5])
@pytest.mark.parametrize("peer", [None, 0, 400])
@pytest.mark.parametrize("current", [None, 0, 20])
def test_bms_profile_uses_only_its_voltage_name(generation: int, peer: int | None, current: int | None) -> None:
    hub = make_hub()
    descr = next(d for d in SENSOR_TYPES_MAIN if d.key == "bms_max_charge" and d.allowedtypes & generation)
    voltage = "battery_voltage_charge" if generation == GEN4 else "battery_1_voltage_charge"
    values = {voltage: 400, "bms_charge_max_current": current, "battery_charge_max_current": 30}
    if generation == GEN5 and peer is not None:
        values["battery_2_voltage_charge"] = peer
    sources(hub, values)
    # Mutually exclusive voltage aliases must not influence this model, even
    # if a number survives in the shared cache from an earlier profile.
    hub.data["battery_1_voltage_charge" if generation == GEN4 else "battery_voltage_charge"] = 999
    if generation == GEN4:
        hub.data["battery_2_voltage_charge"] = 999
    assert hub.evaluate_computed_sensor(descr, hub.data, set(values))
    expected_current = current if current is not None else (15 if generation == GEN5 and peer else 30)
    assert hub.data[descr.key] == expected_current * 400


@pytest.mark.parametrize("battery", [1, 2])
def test_gen5_shared_current_waits_for_installed_peer_then_recovers(battery: int) -> None:
    hub = make_hub()
    key = "bms_max_charge" if battery == 1 else "bms_2_max_charge"
    descr = next(d for d in SENSOR_TYPES_MAIN if d.key == key and d.allowedtypes & GEN5)
    own = f"battery_{battery}_voltage_charge"
    peer = f"battery_{3 - battery}_voltage_charge"
    sources(hub, {own: 400, peer: 400, "battery_charge_max_current": 30})
    assert not hub.evaluate_computed_sensor(descr, hub.data, {own, "battery_charge_max_current"})
    assert hub.evaluate_computed_sensor(descr, hub.data, {own, peer, "battery_charge_max_current"})
    assert hub.data[key] == 6000
