"""Mode 8 keeps running when the disabled house_load_alt entity has no value (issue #2458)."""

import time

import pytest

from custom_components.solax_modbus.button import SolaXModbusButton
from custom_components.solax_modbus.const import BUTTONREPEAT_FIRST, BUTTONREPEAT_LOOP
from custom_components.solax_modbus.plugin_solax import SELECT_TYPES

from .test_vpp_poll_cadence import prime, setup_vpp


def active_modes() -> list[str]:
    description = next(d for d in SELECT_TYPES if d.key == "remotecontrol_power_control_mode")
    return [mode for mode in (description.option_dict or {}).values() if mode != "Disabled"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", active_modes())
async def test_mode8_runs_without_disabled_house_load_alt(mode: str) -> None:
    hub, power, settings, values, function = setup_vpp()
    hub.data["remotecontrol_power_control_mode"] = mode
    values["pv_power_1"] = 8000
    await prime(hub, power, settings)
    hub.data["_repeatUntil"].clear()
    # Disabled entities never receive a value, so house_load_alt is absent from the data.
    hub.data.pop("house_load_alt", None)
    descr = hub.computedEntities["powercontrolmode8_trigger"]
    await SolaXModbusButton("solax", hub, 1, {}, descr).async_press()
    assert function.call_args.args[0] == BUTTONREPEAT_FIRST
    await hub._refresh_interval_group_once(power)
    assert function.call_args.args[0] == BUTTONREPEAT_LOOP
    assert hub.data["_repeatUntil"][descr.key] > time.time()
    assert dict(hub.async_write_registers_multi.call_args.kwargs["payload"])[descr.autorepeat_control] != "Disabled"
