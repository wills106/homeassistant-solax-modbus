"""TCWORLD review: fixed control inputs and generation-specific BMS voltages."""

import time
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from custom_components.solax_modbus import InputObservation
from custom_components.solax_modbus.button import SolaXModbusButton
from custom_components.solax_modbus.const import (
    BUTTONREPEAT_FIRST,
    BUTTONREPEAT_POST,
    WRITE_DATA_LOCAL,
    BaseModbusNumberEntityDescription,
    BaseModbusSelectEntityDescription,
)
from custom_components.solax_modbus.plugin_solax import BUTTON_TYPES, GEN4, GEN5, NUMBER_TYPES, SELECT_TYPES, SENSOR_TYPES_MAIN

from .test_computed_review_regressions import sources
from .test_poll_snapshot import make_group, make_hub
from .test_vpp_poll_cadence import prime, setup_vpp


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["remotecontrol_trigger", "powercontrolmode8_trigger"])
@pytest.mark.parametrize("disabled", [False, True])
async def test_real_local_descriptions_allow_first_loop_and_disable(trigger: str, disabled: bool) -> None:
    hub, power, settings, _values, _function = setup_vpp()
    # Production registries contain local controls with register=None. Use the
    # actual plugin descriptions, rather than number/select metadata doubles.
    hub.numberEntities = {d.key: SimpleNamespace(entity_description=d) for d in NUMBER_TYPES if d.write_method == WRITE_DATA_LOCAL}
    hub.selectEntities = {d.key: SimpleNamespace(entity_description=d) for d in SELECT_TYPES if d.write_method == WRITE_DATA_LOCAL}
    hub.writeLocals = {key: entity.entity_description for entities in (hub.numberEntities, hub.selectEntities) for key, entity in entities.items()}
    assert any(entity.entity_description.register is None for entity in hub.numberEntities.values())
    assert any(entity.entity_description.register is None for entity in hub.selectEntities.values())
    descr = next(d for d in BUTTON_TYPES if d.key == trigger)
    function = Mock(wraps=descr.value_function)
    descr = replace(descr, value_function=function)
    hub.computedEntities = {trigger: descr}
    hub.data[descr.autorepeat_control] = "Disabled" if disabled else "Enabled Feedin Priority"
    if not disabled:
        await prime(hub, power, settings)
    hub.data["_repeatUntil"].clear()
    button = SolaXModbusButton("solax", hub, 1, {}, descr)
    await button.async_press()
    assert function.call_count == hub.async_write_registers_multi.await_count == 1
    assert function.call_args.args[0] == BUTTONREPEAT_FIRST
    if disabled:
        assert hub.data["_repeatUntil"][trigger] == 0
        assert dict(hub.async_write_registers_multi.call_args.kwargs["payload"])[descr.autorepeat_control] == "Disabled"
        return
    # No new measurements: replay the FIRST payload without another filter step.
    payload = hub.async_write_registers_multi.call_args.kwargs["payload"]
    await hub._async_run_autorepeats(power.interval)
    assert function.call_count == 1
    assert hub.async_write_registers_multi.await_count == 2
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == payload
    hub.data[descr.autorepeat_control] = "Disabled"
    await hub._async_run_autorepeats(settings.interval)
    assert hub.data["_repeatUntil"][trigger] == 0
    assert dict(hub.async_write_registers_multi.call_args.kwargs["payload"])[descr.autorepeat_control] == "Disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("description_type", [BaseModbusNumberEntityDescription, BaseModbusSelectEntityDescription])
@pytest.mark.parametrize("register", [None, -1, 0, 0x24])
@pytest.mark.parametrize("sample_state", ["unread", "invalid", "expired", "zero"])
async def test_declared_readbacks_require_accepted_data(description_type: Any, register: int | None, sample_state: str) -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    hub.data["_repeatUntil"].clear()
    key = "battery_charge_max_current"
    description = description_type(key=key, register=register)
    entities = "numberEntities" if description_type is BaseModbusNumberEntityDescription else "selectEntities"
    setattr(hub, entities, {key: SimpleNamespace(entity_description=description)})
    hub.data[key] = 999  # A retained setting is never an accepted readback.
    if register is not None and register >= 0 and sample_state != "unread":
        now = time.monotonic()
        hub._computed_input_observations[key] = InputObservation(
            now, None if sample_state == "invalid" else 0, now - 1 if sample_state == "expired" else now + 45
        )
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    button = SolaXModbusButton("solax", hub, 1, {}, descr)
    await button.async_press()
    rejected = register is not None and register >= 0 and sample_state != "zero"
    assert function.call_args.args[0] == (BUTTONREPEAT_POST if rejected else BUTTONREPEAT_FIRST)
    assert (hub.data["_repeatUntil"][descr.key] == 0) == rejected
    if not rejected and register is not None and register >= 0:
        assert function.call_args.args[2][key] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("sample_state", ["unread", "invalid", "expired", "zero"])
async def test_mode8_validates_its_computed_grid_export_input(sample_state: str) -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    hub.data["_repeatUntil"].clear()
    key = "grid_export"
    hub.sensorDescriptions[key] = next(d for d in SENSOR_TYPES_MAIN if d.key == key and d.register < 0)
    hub.data[key] = 999
    if sample_state != "unread":
        now = time.monotonic()
        hub._computed_input_observations[key] = InputObservation(
            now, None if sample_state == "invalid" else 0, now - 1 if sample_state == "expired" else now + 45
        )
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    await SolaXModbusButton("solax", hub, 1, {}, descr).async_press()
    assert function.call_args.args[0] == (BUTTONREPEAT_FIRST if sample_state == "zero" else BUTTONREPEAT_POST)
    assert hub.data[key] == 999  # Controller views never overwrite shared measurements.
    if sample_state == "zero":
        assert function.call_args.args[2][key] == 0


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
