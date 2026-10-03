"""Preserve successful PM control after completing all power device groups."""

import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.solax_modbus.const import BUTTONREPEAT_LOOP, BUTTONREPEAT_POST
from custom_components.solax_modbus.plugin_solax import BUTTON_TYPES, SENSOR_TYPES_MAIN, autorepeat_function_remotecontrol_recompute

from .test_poll_snapshot import make_group
from .test_vpp_poll_cadence import computed, setup_vpp


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("invalid_phase", [False, True])
@pytest.mark.parametrize(
    "mode",
    [
        "Enabled Power Control",
        "Enabled Grid Control",
        "Enabled Self Use",
        "Enabled Battery Control",
        "Enabled Feedin Priority",
        "Enabled No Discharge",
    ],
)
async def test_master_control_uses_accepted_pm_values_once(mode: str, reverse: bool, invalid_phase: bool) -> None:
    hub, power, settings, values, _function = setup_vpp()
    values.update(
        parallel_setting="Master",
        pm_activepower_l1=400,
        pm_activepower_l2=500,
        pm_activepower_l3=300,
        pm_pv_power_1=1500,
        pm_pv_power_2=2000,
        pm_battery_power_charge=0,
    )
    if invalid_phase:
        values["inverter_power_l2"] = True
    pm_keys = {key for key in values if key.startswith("pm_")}
    for key in pm_keys:
        hub.sensorDescriptions[key] = replace(next(d for d in SENSOR_TYPES_MAIN if d.key == key), scan_group="scan_interval_fast")
    for key in ("pm_total_inverter_power", "pm_total_pv_power", "pm_total_house_load"):
        hub.computedSensors[key] = computed(key)
        hub.sensorDescriptions[key] = hub.computedSensors[key]
        hub.sensorEntities[key] = Mock()
    group = make_group()
    group.holdingBlocks = [SimpleNamespace(start=3, descriptions={i: hub.sensorDescriptions[key] for i, key in enumerate(sorted(pm_keys))})]
    power.device_groups["pm"] = group
    if reverse:
        power.device_groups = dict(reversed(list(power.device_groups.items())))
    descr = next(d for d in BUTTON_TYPES if d.key == "remotecontrol_trigger")
    function = Mock(wraps=descr.value_function)
    hub.computedEntities = {descr.key: replace(descr, value_function=function)}
    hub.data.update(remotecontrol_power_control=mode, remotecontrol_active_power=1000)
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    hub.data["_repeatUntil"][descr.key] = time.time() + 300
    expected = autorepeat_function_remotecontrol_recompute(BUTTONREPEAT_LOOP, descr, hub.data.copy())
    await hub._refresh_interval_group_once(power)
    assert hub.data["pm_total_inverter_power"] == 1200
    assert hub.data["pm_total_pv_power"] == 3500
    assert hub.data["pm_total_house_load"] == 2200
    assert function.call_count == hub.async_write_registers_multi.await_count == 1
    if invalid_phase:
        assert function.call_args.args[0] == BUTTONREPEAT_POST
        assert hub.async_write_registers_multi.call_args.kwargs["payload"] == [("remotecontrol_power_control", "Disabled")]
        return
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == expected["data"]
    assert dict(item for item in expected["data"] if isinstance(item[0], str)).get("remotecontrol_power_control") != "Disabled"
