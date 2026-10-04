"""VPP optional corrections use accepted fresh values without blocking control."""

import time
from dataclasses import replace
from typing import Any

import pytest

from custom_components.solax_modbus import InputObservation
from custom_components.solax_modbus.const import BUTTONREPEAT_FIRST, BUTTONREPEAT_LOOP
from custom_components.solax_modbus.plugin_solax import BUTTON_TYPES, SENSOR_TYPES_MAIN, autorepeat_bms_charge

from .test_vpp_poll_cadence import computed, prime, setup_vpp


def describe(hub: Any, key: str, *, enabled: bool = True) -> None:
    description = computed(key) if key in {"bms_max_charge", "bms_2_max_charge"} else next(d for d in SENSOR_TYPES_MAIN if d.key == key)
    hub.sensorDescriptions[key] = replace(description, entity_registry_enabled_default=enabled)


def accept(hub: Any, key: str, value: Any, *, expired: bool = False) -> None:
    describe(hub, key)
    now = time.monotonic()
    hub.data[key] = value
    hub._computed_input_observations[key] = InputObservation(now, value, now - 1 if expired else now + 100)


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["meter_2_measured_power", "bms_2_max_charge"])
async def test_unread_optional_description_does_not_stop_mode8(key: str) -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    accept(hub, "battery_charge_max_current", 20)
    describe(hub, key, enabled=False)
    hub.data[key] = 1234  # Unaccepted old data cannot count as a measurement.
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_LOOP
    assert key not in function.call_args.args[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, False, "100", float("nan"), float("inf"), 500])
async def test_invalid_or_expired_meter_is_omitted_and_invalidates_keepalive(value: Any) -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    accept(hub, "battery_charge_max_current", 20)
    accept(hub, "meter_2_measured_power", 500)
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    hub.compute_autorepeat_payload(BUTTONREPEAT_FIRST, descr)
    assert function.call_args.args[2]["meter_2_measured_power"] == 500
    calls = function.call_count
    hub.compute_autorepeat_payload(BUTTONREPEAT_LOOP, descr, interval=5)
    assert function.call_count == calls
    accept(hub, "meter_2_measured_power", value, expired=value == 500)
    hub.compute_autorepeat_payload(BUTTONREPEAT_LOOP, descr, interval=5)
    assert function.call_count == calls + 1
    assert function.call_args.args[0] == BUTTONREPEAT_LOOP
    assert "meter_2_measured_power" not in function.call_args.args[2]
    accept(hub, "meter_2_measured_power", 0)
    hub.compute_autorepeat_payload(BUTTONREPEAT_LOOP, descr, interval=5)
    assert function.call_args.args[2]["meter_2_measured_power"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["measured_power_l1", "grid_voltage_l1"])
async def test_modes_1_to_7_omit_unread_optional_phase_inputs(key: str) -> None:
    hub, power, settings, _values, _function = setup_vpp()
    await prime(hub, power, settings)
    hub.data["remotecontrol_power_control"] = "Enabled Self Use"
    describe(hub, key)
    hub.data[key] = 999
    descr = next(d for d in BUTTON_TYPES if d.key == "remotecontrol_trigger")
    payload = hub.compute_autorepeat_payload(BUTTONREPEAT_FIRST, descr)
    assert payload["data"][0] == ("remotecontrol_power_control", "Enabled Power Control")


@pytest.mark.asyncio
@pytest.mark.parametrize("battery", [1, 2])
async def test_either_single_battery_limit_reaches_the_existing_helper(battery: int) -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    key = "bms_max_charge" if battery == 1 else "bms_2_max_charge"
    other = "bms_2_max_charge" if battery == 1 else "bms_max_charge"
    accept(hub, key, 6000)
    describe(hub, other, enabled=False)
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    hub.compute_autorepeat_payload(BUTTONREPEAT_FIRST, descr)
    assert function.call_args.args[0] == BUTTONREPEAT_FIRST
    assert function.call_args.args[2][key] == 6000
    assert other not in function.call_args.args[2]
    assert function.call_args.args[2]["battery_charge_max_current"] == 20
    assert autorepeat_bms_charge(function.call_args.args[2], 50, 100, 20000)[2] == 6000


@pytest.mark.asyncio
@pytest.mark.parametrize("expired_battery", [1, 2])
async def test_partial_bms_sum_uses_only_fresh_channel(expired_battery: int) -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    for battery, key in ((1, "bms_max_charge"), (2, "bms_2_max_charge")):
        accept(hub, key, battery * 6000, expired=battery == expired_battery)
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    hub.compute_autorepeat_payload(BUTTONREPEAT_FIRST, descr)
    source = function.call_args.args[2]
    expired = "bms_max_charge" if expired_battery == 1 else "bms_2_max_charge"
    fresh = "bms_2_max_charge" if expired_battery == 1 else "bms_max_charge"
    assert function.call_args.args[0] == BUTTONREPEAT_FIRST
    assert expired not in source
    assert fresh in source
    # Preserve the helper's partial-sum behavior without using an expired value.
    assert autorepeat_bms_charge(source, 50, 100, 20000)[2] == source[fresh]


@pytest.mark.asyncio
@pytest.mark.parametrize("alternative", [None, "battery_max_charge_power", "bms_max_charge"])
async def test_missing_required_current_cannot_reach_guessed_default(alternative: str | None) -> None:
    hub, power, settings, _values, _function = setup_vpp()
    await prime(hub, power, settings)
    if alternative is not None:
        accept(hub, alternative, 6000)
    hub._computed_input_observations.pop("battery_charge_max_current", None)
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    payload = hub.compute_autorepeat_payload(BUTTONREPEAT_FIRST, descr)
    assert payload["data"] == [("remotecontrol_power_control_mode", "Disabled")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "expired"), [(0, False), (None, False), (True, False), ("20", False), (float("nan"), False), (float("inf"), False), (20, True)]
)
async def test_required_current_accepts_zero_and_rejects_invalid_or_expired_values(value: Any, expired: bool) -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    accept(hub, "battery_charge_max_current", value, expired=expired)
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    payload = hub.compute_autorepeat_payload(BUTTONREPEAT_FIRST, descr)
    if value == 0:
        assert function.call_args.args[0] == BUTTONREPEAT_FIRST
        assert function.call_args.args[2]["battery_charge_max_current"] == 0
    else:
        assert payload["data"] == [("remotecontrol_power_control_mode", "Disabled")]


@pytest.mark.asyncio
async def test_total_limit_expiry_and_recovery_invalidates_keepalive_on_owner_poll() -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    for key in ("bms_max_charge", "bms_2_max_charge"):
        accept(hub, key, 6000)
    accept(hub, "battery_max_charge_power", 15000)
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    hub.compute_autorepeat_payload(BUTTONREPEAT_FIRST, descr)
    assert autorepeat_bms_charge(function.call_args.args[2], 50, 100, 20000)[2] == 15000
    calls = function.call_count
    accept(hub, "battery_max_charge_power", 15000, expired=True)
    hub.compute_autorepeat_payload(BUTTONREPEAT_LOOP, descr, interval=15)
    assert function.call_count == calls
    hub.compute_autorepeat_payload(BUTTONREPEAT_LOOP, descr, interval=5)
    assert function.call_count == calls + 1
    assert "battery_max_charge_power" not in function.call_args.args[2]
    assert function.call_args.args[2]["bms_max_charge"] == function.call_args.args[2]["bms_2_max_charge"] == 6000
    assert autorepeat_bms_charge(function.call_args.args[2], 50, 100, 20000)[2] == 12000
    accept(hub, "battery_max_charge_power", 16000)
    hub.compute_autorepeat_payload(BUTTONREPEAT_LOOP, descr, interval=5)
    assert function.call_count == calls + 2
    assert function.call_args.args[2]["battery_max_charge_power"] == 16000
    assert autorepeat_bms_charge(function.call_args.args[2], 50, 100, 20000)[2] == 16000


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["meter_2_measured_power", "bms_2_max_charge"])
async def test_accepted_optional_value_does_not_depend_on_entity_display_default(key: str) -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    accept(hub, key, 6000)
    describe(hub, key, enabled=False)
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    hub.compute_autorepeat_payload(BUTTONREPEAT_FIRST, descr)
    assert function.call_args.args[0] == BUTTONREPEAT_FIRST
    assert function.call_args.args[2][key] == 6000


@pytest.mark.asyncio
async def test_optional_computed_value_cannot_hide_a_boolean_leaf() -> None:
    hub, power, settings, _values, function = setup_vpp()
    await prime(hub, power, settings)
    accept(hub, "grid_export", 1)
    now = time.monotonic()
    leaf = InputObservation(now, True, now + 100)
    hub._computed_input_observations["boolean_leaf"] = leaf
    hub._computed_input_observations["grid_export"] = InputObservation(now, 1, now + 100, ((hub, "boolean_leaf", leaf),))
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    hub.compute_autorepeat_payload(BUTTONREPEAT_FIRST, descr)
    assert function.call_args.args[0] == BUTTONREPEAT_FIRST
    assert "grid_export" not in function.call_args.args[2]
