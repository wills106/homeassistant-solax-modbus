"""Issue #2394: omit unsupported inputs without ignoring disabled sensors."""

import time
from copy import copy
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.solax_modbus import InputObservation, plugin_solax
from custom_components.solax_modbus.button import SolaXModbusButton
from custom_components.solax_modbus.const import BUTTONREPEAT_FIRST, BUTTONREPEAT_LOOP, BUTTONREPEAT_POST
from custom_components.solax_modbus.plugin_solax import AC, BUTTON_TYPES, GEN4, SENSOR_TYPES_MAIN, X1

from .test_vpp_optional_inputs import AUTOREPEAT_MODES
from .test_vpp_poll_cadence import setup_vpp


@pytest.mark.asyncio
@pytest.mark.parametrize("serial", ["F4372T", "F4502T"])
@pytest.mark.parametrize(("trigger", "mode"), AUTOREPEAT_MODES)
@pytest.mark.parametrize(("fast", "slow"), [(5, 15), (7, 23)])
async def test_ac_profile_without_pv_allows_first_loop_and_disable(
    serial: str, trigger: str, mode: str, fast: int, slow: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub, power, settings, values, _function = setup_vpp(fast, slow)
    plugin = copy(plugin_solax.plugin_instance)
    monkeypatch.setattr(plugin_solax, "async_read_serialnr", AsyncMock(return_value=serial))
    monkeypatch.setattr(plugin_solax, "async_read_inverter_firmware_info", AsyncMock())
    invertertype = await plugin.async_determineInverterType(hub, {})
    assert invertertype & (AC | GEN4 | X1) == AC | GEN4 | X1
    # Both reported serials select AC profiles. The actual model masks exclude
    # PV Total and its channels; disabling a supported entity does not do this.
    pv_descriptions = [d for d in SENSOR_TYPES_MAIN if d.key in {"pv_power_total", "pv_power_1", "pv_power_2"}]
    assert not any(plugin.matchInverterWithMask(invertertype, d.allowedtypes, serial, d.blacklist) for d in pv_descriptions)
    missing = {d.key for d in pv_descriptions}
    for registry in (hub.sensorDescriptions, hub.sensorEntities, hub.computedSensors, values):
        for key in missing:
            registry.pop(key, None)
    for group in power.device_groups.values():
        for block in group.holdingBlocks:
            block.descriptions = {index: d for index, d in block.descriptions.items() if d.key not in missing}

    base = next(d for d in BUTTON_TYPES if d.key == trigger)
    function = Mock(wraps=base.value_function)
    descr = replace(base, value_function=function)
    hub.computedEntities = {trigger: descr}
    hub.data.update({descr.autorepeat_control: mode, "remotecontrol_active_power": -1000})
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    assert "pv_power_total" not in hub.sensorDescriptions
    hub.data["pv_power_total"] = 9999  # An unsupported cached number must not reach the controller.
    await SolaXModbusButton("solax", hub, 1, {}, descr).async_press()
    assert function.call_args.args[0] == BUTTONREPEAT_FIRST
    assert missing.isdisjoint(function.call_args.args[2])
    assert hub.data["_repeatUntil"][trigger] > time.time()
    assert dict(hub.async_write_registers_multi.call_args.kwargs["payload"])[descr.autorepeat_control] != "Disabled"
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_LOOP
    assert missing.isdisjoint(function.call_args.args[2])
    assert hub.data["_repeatUntil"][trigger] > time.time()
    hub.data[descr.autorepeat_control] = "Disabled"
    await hub._async_run_autorepeats(settings.interval)
    assert hub.data["_repeatUntil"][trigger] == 0
    assert dict(hub.async_write_registers_multi.call_args.kwargs["payload"])[descr.autorepeat_control] == "Disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["remotecontrol_trigger", "powercontrolmode8_trigger"])
@pytest.mark.parametrize("phase", [BUTTONREPEAT_FIRST, BUTTONREPEAT_LOOP])
@pytest.mark.parametrize("state", ["disabled", "unread", "invalid", "expired", "zero"])
async def test_supported_pv_remains_required(trigger: str, phase: int, state: str) -> None:
    hub, power, settings, _values, _function = setup_vpp()
    base = next(d for d in BUTTON_TYPES if d.key == trigger)
    function = Mock(wraps=base.value_function)
    descr = replace(base, value_function=function)
    hub.computedEntities = {trigger: descr}
    hub.data[descr.autorepeat_control] = "Enabled No Discharge"
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    button = SolaXModbusButton("solax", hub, 1, {}, descr)
    if phase == BUTTONREPEAT_LOOP:
        await button.async_press()
        assert function.call_args.args[0] == BUTTONREPEAT_FIRST
    key = "pv_power_total"
    now = time.monotonic()
    if state == "disabled":
        hub.sensorDescriptions[key] = replace(hub.sensorDescriptions[key], entity_registry_enabled_default=False)
        hub.sensorEntities.pop(key)
        hub.computedSensors.pop(key)
    if state in {"disabled", "unread"}:
        hub._computed_input_observations.pop(key)
    else:
        hub._computed_input_observations[key] = InputObservation(now, None if state == "invalid" else 0, now - 1 if state == "expired" else now + 45)
    hub.data[key] = 9999  # A retained value cannot authorize a control write.
    if phase == BUTTONREPEAT_FIRST:
        await button.async_press()
    else:
        await hub._async_run_autorepeats(power.interval)
    assert function.call_args.args[0] == (phase if state == "zero" else BUTTONREPEAT_POST)
    assert (hub.data["_repeatUntil"][trigger] == 0) == (state != "zero")
    if state == "zero":
        assert function.call_args.args[2][key] == 0
    else:
        assert hub.async_write_registers_multi.call_args.kwargs["payload"] == [(descr.autorepeat_control, "Disabled")]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unsupported", "disabled", "expired", "zero"])
async def test_master_profile_filters_only_unsupported_pv(state: str) -> None:
    hub, power, settings, values, _function = setup_vpp()
    values["parallel_setting"] = "Master"
    base = next(d for d in BUTTON_TYPES if d.key == "remotecontrol_trigger")
    function = Mock(wraps=base.value_function)
    descr = replace(base, value_function=function)
    hub.computedEntities = {descr.key: descr}
    hub.data.update(remotecontrol_power_control="Enabled Battery Control", remotecontrol_active_power=-1000)
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    now = time.monotonic()
    for key, value in (("pm_total_inverter_power", 1000), ("pm_battery_power_charge", 0), ("pm_total_house_load", 2000)):
        hub.sensorDescriptions[key] = next(d for d in SENSOR_TYPES_MAIN if d.key == key)
        hub._computed_input_observations[key] = InputObservation(now, value, now + 45)
    key = "pm_total_pv_power"
    if state != "unsupported":
        hub.sensorDescriptions[key] = replace(next(d for d in SENSOR_TYPES_MAIN if d.key == key), entity_registry_enabled_default=False)
    if state in {"expired", "zero"}:
        hub._computed_input_observations[key] = InputObservation(now, 0, now - 1 if state == "expired" else now + 45)
    hub.data[key] = 9999
    await SolaXModbusButton("solax", hub, 1, {}, descr).async_press()
    allowed = state in {"unsupported", "zero"}
    assert function.call_args.args[0] == (BUTTONREPEAT_FIRST if allowed else BUTTONREPEAT_POST)
    if state == "unsupported":
        assert key not in function.call_args.args[2]
    elif state == "zero":
        assert function.call_args.args[2][key] == 0
    assert (hub.data["_repeatUntil"][descr.key] > time.time()) == allowed
