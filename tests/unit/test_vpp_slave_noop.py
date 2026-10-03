"""Slave controller no-ops never reach the real multi-register encoder."""

import asyncio
import time
from dataclasses import replace
from types import MethodType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.button import SolaXModbusButton
from custom_components.solax_modbus.const import BUTTONREPEAT_POST
from custom_components.solax_modbus.plugin_solax import BUTTON_TYPES, NUMBER_TYPES, SELECT_TYPES

from .test_vpp_poll_cadence import setup_vpp


async def setup_slave_control() -> tuple[Any, Any, Any, Mock, Mock]:
    hub, power, settings, values, _function = setup_vpp()
    values["parallel_setting"] = "Slave"
    descr = next(d for d in BUTTON_TYPES if d.key == "remotecontrol_trigger")
    function = Mock(wraps=descr.value_function)
    hub.computedEntities = {descr.key: replace(descr, value_function=function)}
    hub.data["remotecontrol_power_control"] = "Enabled Self Use"
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub._stopping = False
    hub._check_connection = AsyncMock(return_value=True)
    hub._transport = SimpleNamespace(write=AsyncMock(return_value=Mock(isError=Mock(return_value=False))))
    hub.plugin.order32 = "little"
    descriptions: tuple[Any, ...] = (*NUMBER_TYPES, *SELECT_TYPES)
    for d in descriptions:
        options = getattr(d, "option_dict", None)
        hub.writeLocals[d.key] = replace(d, reverse_option_dict={label: raw for raw, label in options.items()}) if options else d
    hub.async_write_registers_multi = MethodType(SolaXModbusHub.async_write_registers_multi, hub)
    encoder = Mock(wraps=hub._encode_multi_write_payload)
    hub._encode_multi_write_payload = encoder
    return hub, power, settings, function, encoder


@pytest.mark.asyncio
async def test_slave_first_is_a_noop_before_real_encoding() -> None:
    hub, _power, _settings, function, encoder = await setup_slave_control()
    descr = hub.computedEntities["remotecontrol_trigger"]
    button = SolaXModbusButton("solax", hub, 1, {}, descr)
    await button.async_press()
    assert function.call_count == 1
    assert hub.data["_repeatUntil"][descr.key] > time.time()
    encoder.assert_not_called()
    hub._transport.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_slave_loop_and_cached_noop_do_not_encode_empty_payload() -> None:
    hub, power, _settings, function, encoder = await setup_slave_control()
    hub.data["_repeatUntil"]["remotecontrol_trigger"] = time.time() + 300
    await hub._refresh_interval_group_once(power)
    assert function.call_count == 1
    encoder.assert_not_called()
    for group in power.device_groups.values():
        group.holdingBlocks = []
    await hub._refresh_interval_group_once(power)
    assert function.call_count == 1  # The accepted sample's no-op is also cached.
    assert hub.data["_repeatUntil"]["remotecontrol_trigger"] > time.time()
    encoder.assert_not_called()
    hub._transport.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_slave_expiry_still_encodes_and_writes_disabled_cleanup() -> None:
    hub, _power, settings, function, encoder = await setup_slave_control()
    hub.data["_repeatUntil"]["remotecontrol_trigger"] = time.time() - 1
    await hub._refresh_interval_group_once(settings)
    assert function.call_args.args[0] == BUTTONREPEAT_POST
    encoder.assert_called_once_with([("remotecontrol_power_control", "Disabled")])
    hub._transport.write.assert_awaited_once()
    assert hub.data["_repeatUntil"]["remotecontrol_trigger"] == 0
    assert hub._autorepeat_pending_stops == {}
