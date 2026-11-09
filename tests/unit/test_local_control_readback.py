"""Polling must not freeze readbacks that share a key with a local control."""

from time import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.solax_modbus.const import PollOutcome
from custom_components.solax_modbus.number import SolaXModbusNumber
from custom_components.solax_modbus.plugin_solis import plugin_instance as solis_plugin
from custom_components.solax_modbus.plugin_solis_fb00 import plugin_instance as solis_fb00_plugin

from .test_poll_snapshot import make_group, make_hub

TIME_READBACKS = [
    (plugin, description.key)
    for plugin in (solis_plugin, solis_fb00_plugin)
    for description in plugin.SENSOR_TYPES
    if description.key.startswith(("timed_charge_start_", "timed_charge_end_", "timed_discharge_start_", "timed_discharge_end_"))
]


def make_readback_hub(plugin: Any, key: str) -> tuple[Any, Any]:
    """Use real Solis descriptions and decoding, with only the wire mocked."""
    hub = make_hub()
    hub.plugin = plugin.create_hub_instance()
    hub._modbus_addr = 1
    hub.cyclecount = 10
    hub._validate_register_func = None
    hub._record_block_result = Mock()
    hub._hass = SimpleNamespace(async_add_executor_job=AsyncMock())
    hub.tmpdata = {}
    hub.blocks_changed = False
    hub.sleepnone = []
    hub.sleepzero = []
    description = next(item for item in plugin.SENSOR_TYPES if item.key == key)
    control = next(item for item in plugin.NUMBER_TYPES if item.key == key)
    hub.sensorDescriptions[key] = description
    # Local descriptions are registered even when their number entities are disabled.
    hub.writeLocals[key] = control
    hub.numberEntities = {}
    group = make_group()
    group.holdingBlocks = [
        SimpleNamespace(
            start=description.register,
            end=description.register + 1,
            regs=[description.register],
            descriptions={description.register: description},
        )
    ]
    group.sensors = [SimpleNamespace(entity_description=description, modbus_data_updated=Mock())]
    hub.async_read_holding_registers = AsyncMock(return_value=SimpleNamespace(registers=[12], isError=Mock(return_value=False)))
    return hub, group


@pytest.mark.asyncio
@pytest.mark.parametrize(("plugin", "key"), TIME_READBACKS)
async def test_solis_time_readbacks_continue_updating_with_controls_disabled(plugin: Any, key: str) -> None:
    hub, group = make_readback_hub(plugin, key)
    interval_group = SimpleNamespace(device_groups={"inverter": group})

    for value in (10, 12, 13):
        hub.async_read_holding_registers.return_value.registers = [value]
        outcome, updated = await hub._refresh_interval_group_once(interval_group)

        assert outcome is PollOutcome.SUCCESS
        assert updated == 1
        assert hub.data[key] == value
        assert hub._computed_input_observations[key].value == value

    assert hub.numberEntities == {}
    assert group.sensors[0].modbus_data_updated.call_count == 3
    assert hub.async_read_holding_registers.await_count == 3


@pytest.mark.asyncio
async def test_pending_local_edit_is_preserved_until_readback_is_released() -> None:
    key = "timed_charge_start_hours"
    hub, group = make_readback_hub(solis_fb00_plugin, key)
    hub.data[key] = 10
    hub.tmpdata_expiry[key] = time() + 120

    await hub.async_read_modbus_registers_all(group)

    assert hub.data[key] == 10
    assert hub._computed_input_observations[key].value is None

    hub.tmpdata_expiry[key] = 0
    await hub.async_read_modbus_registers_all(group)

    assert hub.data[key] == 12
    assert hub._computed_input_observations[key].value == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("edited_value", [10, 14])
async def test_local_edit_after_decode_survives_snapshot_merge(edited_value: int) -> None:
    key = "timed_charge_start_hours"
    hub, group = make_readback_hub(solis_fb00_plugin, key)
    hub.data[key] = 10
    number = SolaXModbusNumber("solis", hub, 1, {}, hub.writeLocals[key])
    cast(Any, number).async_write_ha_state = Mock()
    read_block = hub.async_read_modbus_block

    async def read_then_edit(data: dict[str, Any], block: Any, typ: str) -> Any:
        result = await read_block(data, block, typ)
        assert data[key] == 12
        await number.async_set_native_value(edited_value)
        return result

    hub.async_read_modbus_block = read_then_edit
    await hub.async_read_modbus_registers_all(group)

    assert hub.data[key] == edited_value
    assert hub.tmpdata[key] == edited_value
    assert hub.tmpdata_expiry[key] > time()


@pytest.mark.asyncio
async def test_local_only_controls_keep_changes_made_during_a_poll() -> None:
    key = "timed_charge_start_hours"
    hub, group = make_readback_hub(solis_fb00_plugin, key)
    local_key = "sync_rtc_offset"
    hub.writeLocals[local_key] = next(item for item in solis_fb00_plugin.NUMBER_TYPES if item.key == local_key)
    hub.data[local_key] = 0

    async def read_and_change_local(**kwargs: Any) -> Any:
        hub.data[local_key] = 30
        return SimpleNamespace(registers=[12], isError=Mock(return_value=False))

    hub.async_read_holding_registers.side_effect = read_and_change_local
    await hub.async_read_modbus_registers_all(group)

    assert hub.data[local_key] == 30
    assert hub.data[key] == 12
