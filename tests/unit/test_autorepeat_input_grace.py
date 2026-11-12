"""A running autorepeat control survives a transient invalid input, but not a lasting one."""

import time
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from homeassistant.const import CONF_NAME

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.const import (
    BUTTONREPEAT_LOOP,
    BUTTONREPEAT_POST,
    CONF_AUTOREPEAT_INPUT_GRACE,
    CONF_INTERFACE,
    DEFAULT_AUTOREPEAT_INPUT_GRACE,
)
from custom_components.solax_modbus.plugin_sofar import plugin_instance as sofar_template

from .test_vpp_poll_cadence import prime, setup_vpp

KEY = "powercontrolmode8_trigger"
GRACE = 30.0


def setup_vpp_with_grace(grace: float = GRACE) -> tuple[Any, Any, Any, dict[str, Any], Mock]:
    """The shared VPP fixture with the opt-in invalid-input grace period configured."""
    setup = setup_vpp()
    setup[0]._autorepeat_input_grace = grace
    return setup


@pytest.mark.asyncio
async def test_transient_invalid_input_holds_running_control() -> None:
    hub, power, settings, values, function = setup_vpp_with_grace()
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    calls = function.call_count
    writes = hub.async_write_registers_multi.await_count
    held = hub.async_write_registers_multi.call_args.kwargs["payload"]
    values["meter_1_measured_power"] = None
    await hub._refresh_interval_group_once(power)
    assert function.call_count == calls  # nothing is recomputed from missing data
    assert hub.data["_repeatUntil"][KEY] > time.time()
    assert hub.data["remotecontrol_current_pushmode_power"] == 210
    # The last command is replayed as a keepalive, and no Disabled write ends the control.
    assert hub.async_write_registers_multi.await_count == writes + 1
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == held
    assert KEY in hub._autorepeat_in_grace


@pytest.mark.asyncio
async def test_control_resumes_when_input_recovers() -> None:
    hub, power, settings, values, function = setup_vpp_with_grace()
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    good = values["meter_1_measured_power"]
    values["meter_1_measured_power"] = None
    await hub._refresh_interval_group_once(power)
    assert KEY in hub._autorepeat_in_grace
    values["meter_1_measured_power"] = good
    await hub._refresh_interval_group_once(power)
    assert KEY not in hub._autorepeat_in_grace
    assert function.call_args.args[0] == BUTTONREPEAT_LOOP
    assert hub.data["_repeatUntil"][KEY] > time.time()


@pytest.mark.asyncio
async def test_lasting_invalid_input_stops_after_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    hub, power, settings, values, function = setup_vpp_with_grace()
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    values["meter_1_measured_power"] = None
    now[0] += GRACE - 1
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] != BUTTONREPEAT_POST
    assert hub.data["_repeatUntil"][KEY] > 0
    now[0] += 2
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["_repeatUntil"][KEY] == 0
    assert hub.data["remotecontrol_current_pushmode_power"] is None
    assert hub.async_write_registers_multi.call_args.kwargs["payload"] == [("remotecontrol_power_control_mode", "Disabled")]
    assert KEY not in hub._autorepeat_inputs_ok_at
    assert KEY not in hub._autorepeat_in_grace


@pytest.mark.asyncio
async def test_default_grace_is_off_and_stops_immediately() -> None:
    assert DEFAULT_AUTOREPEAT_INPUT_GRACE == 0
    hub, power, settings, values, function = setup_vpp()
    await prime(hub, power, settings)
    await hub._refresh_interval_group_once(power)
    values["meter_1_measured_power"] = None
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    assert hub.data["_repeatUntil"][KEY] == 0


@pytest.mark.parametrize(("options", "expected"), [({}, 0.0), ({CONF_AUTOREPEAT_INPUT_GRACE: 30}, 30.0)])
def test_grace_period_is_read_from_the_config_entry(options: dict[str, Any], expected: float) -> None:
    entry = SimpleNamespace(options={CONF_NAME: "test", CONF_INTERFACE: "test", **options})
    plugin_module = cast(ModuleType, SimpleNamespace(plugin_instance=sofar_template))
    hub = SolaXModbusHub(cast(Any, SimpleNamespace()), plugin_module, cast(Any, entry))
    assert hub._autorepeat_input_grace == expected
