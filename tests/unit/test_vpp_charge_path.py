"""Match control-input validation to the charging branch the regulator uses."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.solax_modbus.const import BUTTONREPEAT_POST
from custom_components.solax_modbus.plugin_solax import SENSOR_TYPES_MAIN, autorepeat_function_powercontrolmode8_recompute

from .test_poll_snapshot import make_group
from .test_vpp_poll_cadence import computed, prime, setup_vpp


@pytest.mark.asyncio
async def test_zero_clipping_step_cannot_bypass_invalid_charge_limits() -> None:
    hub, power, settings, values, function = setup_vpp()
    for key in ("bms_max_charge", "bms_2_max_charge"):
        hub.sensorDescriptions[key] = computed(key)
        hub.data[key] = 8000  # A cached number has no accepted measurement.
    await prime(hub, power, settings)
    hub.data.update(
        remotecontrol_power_control_mode="Negative Injection Price",
        remotecontrol_current_pushmode_power=-1000,
        remotecontrol_current_pv_power_limit=500,
        pv_unlimited_delta_w=0,
    )
    values["measured_power"] = -100
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["remotecontrol_current_pushmode_power"] is None
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == [("remotecontrol_power_control_mode", "Disabled")]


@pytest.mark.asyncio
@pytest.mark.parametrize("step", [0, None])
async def test_clipping_step_defaults_preserve_healthy_regulator_payload(step: Any) -> None:
    hub, power, settings, values, _function = setup_vpp()
    key = "battery_max_charge_power"
    hub.sensorDescriptions[key] = replace(next(d for d in SENSOR_TYPES_MAIN if d.key == key), scan_group="scan_interval")
    values[key] = 6000
    group = make_group()
    group.holdingBlocks = [SimpleNamespace(start=3, descriptions={0: hub.sensorDescriptions[key]})]
    settings.device_groups[key] = group
    await prime(hub, power, settings)
    hub.data.update(
        remotecontrol_power_control_mode="Negative Injection Price",
        remotecontrol_current_pushmode_power=-1000,
        remotecontrol_current_pv_power_limit=500,
        pv_unlimited_delta_w=step,
    )
    values["measured_power"] = -100
    # Align the reference snapshot with the values returned by the next read.
    expected_data = hub.data.copy()
    expected_data["measured_power"] = values["measured_power"]
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    expected = autorepeat_function_powercontrolmode8_recompute(1, descr, expected_data)
    await hub._refresh_interval_group_once(power)
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == expected["data"]
    assert hub.data["remotecontrol_current_pushmode_power"] == expected_data["remotecontrol_current_pushmode_power"]
