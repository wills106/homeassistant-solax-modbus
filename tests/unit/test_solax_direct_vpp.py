"""Regression tests for complete, one-shot SolaX direct VPP commands."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.const import (
    WRITE_DATA_LOCAL,
    WRITE_MULTI_MODBUS,
    BaseModbusNumberEntityDescription,
    BaseModbusSelectEntityDescription,
)
from custom_components.solax_modbus.number import SolaXModbusNumber
from custom_components.solax_modbus.plugin_solax import (
    DIRECT_VPP_PARAMETER_MODES,
    NUMBER_TYPES,
    SELECT_TYPES,
    async_write_direct_vpp,
    build_direct_vpp_command,
)
from custom_components.solax_modbus.select import SolaXModbusSelect
from tests.unit.test_write_pipeline import make_hub


def encode_command(mode: int, data: dict[str, Any]) -> tuple[int, list[int]]:
    """Exercise the production encoder, including SolaX's low-word-first order."""
    address, payload = build_direct_vpp_command(mode, data)
    hub = make_hub()
    hub.plugin.order32 = "little"
    return address, hub._encode_multi_write_payload(payload)


@pytest.fixture
def parameters() -> dict[str, Any]:
    """Populate even irrelevant fields so zero-padding cannot pass accidentally."""
    return {
        "remote_control_target_set_type_direct": "Update",
        "remotecontrol_active_power_direct": -5000,
        "remotecontrol_reactive_power_direct": -200,
        "remotecontrol_duration_direct": 300,
        "remotecontrol_target_soc_direct": 30,
        "remotecontrol_target_energy_direct": 9000,
        "remotecontrol_charge_discharge_power_direct": -4000,
        "remotecontrol_timeout_direct": 600,
        "remotecontrol_push_mode_power_direct": -1000,
        "power_control_mode_target_set_type_direct": "Set",
        "remotecontrol_pv_power_limit_direct": 15000,
        "remotecontrol_push_mode_power_8_9_direct": -2000,
        "remotecontrol_duration_8_direct": 3600,
        "remotecontrol_target_soc_9_direct": 80,
        "remotecontrol_timeout_8_9_direct": 120,
    }


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (1, [1, 2, 0xEC78, 0xFFFF, 0xFF38, 0xFFFF, 300, 0, 0, 0, 0, 0, 600]),
        (2, [2, 2, 0, 0, 0, 0, 0, 0, 9000, 0, 0xF060, 0xFFFF, 600]),
        (3, [3, 2, 0, 0, 0, 0, 0, 30, 0, 0, 0xF060, 0xFFFF, 600]),
        (4, [4, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 600, 0xFC18, 0xFFFF]),
        (5, [5, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 600, 0, 0]),
        (6, [6, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 600, 0, 0]),
        (7, [7, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 600, 0, 0]),
    ],
)
def test_legacy_modes_write_complete_zero_padded_block(mode: int, expected: list[int], parameters: dict[str, Any]) -> None:
    assert encode_command(mode, parameters) == (0x7C, expected)


@pytest.mark.parametrize(("mode", "duration_or_soc"), [(8, 3600), (9, 80)])
def test_individual_modes_write_separate_complete_block(mode: int, duration_or_soc: int, parameters: dict[str, Any]) -> None:
    assert encode_command(mode, parameters) == (0xA0, [mode, 1, 15000, 0, 0xF830, 0xFFFF, duration_or_soc, 120])


def test_disable_needs_no_target_values() -> None:
    assert encode_command(0, {}) == (0x7C, [0] * 13)


def test_soc_mode_requires_explicit_target() -> None:
    with pytest.raises(HomeAssistantError, match="Target SOC.*before enabling"):
        build_direct_vpp_command(3, {})


def test_zero_soc_target_is_not_treated_as_missing() -> None:
    _, words = encode_command(3, {"remotecontrol_target_soc_direct": 0})
    assert words[7] == 0


def test_defaults_come_from_existing_entity_descriptions() -> None:
    assert encode_command(1, {}) == (0x7C, [1, 1, 0, 0, 0, 0, 60, 0, 0, 0, 0, 0, 0])


def test_target_energy_is_unsigned_32_bit(parameters: dict[str, Any]) -> None:
    parameters["remotecontrol_target_energy_direct"] = 0xFEDCBA98
    _, words = encode_command(2, parameters)
    assert words[8:10] == [0xBA98, 0xFEDC]


@pytest.mark.parametrize("mode", [-1, 10, 65535])
def test_unknown_modes_are_rejected(mode: int) -> None:
    with pytest.raises(HomeAssistantError, match="Unsupported direct VPP mode"):
        build_direct_vpp_command(mode, {})


def test_irrelevant_invalid_parameter_does_not_block_other_modes() -> None:
    assert len(encode_command(5, {"remotecontrol_target_soc_direct": "unavailable"})[1]) == 15


def test_relevant_invalid_parameter_is_rejected() -> None:
    with pytest.raises(HomeAssistantError, match="Invalid direct VPP parameter.*Target SOC"):
        build_direct_vpp_command(3, {"remotecontrol_target_soc_direct": "unavailable"})


def test_building_a_command_does_not_mutate_parameters(parameters: dict[str, Any]) -> None:
    original = parameters.copy()
    build_direct_vpp_command(1, parameters)
    assert parameters == original


def make_mode_select(key: str, data: dict[str, Any]) -> tuple[SolaXModbusSelect, Any]:
    description = next(description for description in SELECT_TYPES if description.key == key)
    assert description.option_dict is not None
    description = replace(description, reverse_option_dict={label: raw for raw, label in description.option_dict.items()})
    hub = make_direct_hub(data)
    entity = SolaXModbusSelect("solax", hub, 1, {}, description)
    entity.async_write_ha_state = Mock()  # type: ignore[method-assign]
    return entity, hub


def make_direct_hub(data: dict[str, Any], mode: int = 0) -> Any:
    hub = make_hub()
    hub.plugin.order32 = "little"
    hub.data = data.copy()
    hub._poll_data_lock = asyncio.Lock()
    hub.localsLoaded = True
    hub.localsUpdated = False
    hub.numberEntities = {}
    hub.selectEntities = {}
    hub.async_write_registers_multi = AsyncMock()
    hub.async_write_registers_single = AsyncMock()
    hub.async_write_register = AsyncMock()
    hub.async_read_input_registers = AsyncMock(return_value=SimpleNamespace(isError=lambda: False, registers=[mode]))
    hub.async_refresh_gated_entities = AsyncMock()
    return hub


def make_number(key: str, hub: Any) -> SolaXModbusNumber:
    description = next(description for description in NUMBER_TYPES if description.key == key)
    entity = SolaXModbusNumber("solax", hub, 1, {}, description)
    entity.async_write_ha_state = Mock()  # type: ignore[method-assign]
    return entity


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "mode"),
    [("modbus_power_control_direct", mode) for mode in range(10)] + [("remote_control_power_control_mode_direct", mode) for mode in (0, 8, 9)],
)
async def test_mode_selection_sends_one_full_command(key: str, mode: int, parameters: dict[str, Any]) -> None:
    entity, hub = make_mode_select(key, parameters)
    assert entity.entity_description.option_dict is not None
    option = entity.entity_description.option_dict[mode]
    assert entity.entity_description.write_method == WRITE_MULTI_MODBUS

    await entity.async_select_option(option)

    address, payload = build_direct_vpp_command(mode, parameters)
    hub.async_write_registers_multi.assert_awaited_once_with(unit=1, address=address, payload=payload)
    hub.async_write_registers_single.assert_not_awaited()
    assert hub.data[key] == option
    assert entity.entity_description.value_function is None
    assert entity.entity_description.autorepeat is False
    assert hub.data == parameters | {key: option}


@pytest.mark.asyncio
async def test_failed_command_does_not_publish_selected_mode(parameters: dict[str, Any]) -> None:
    key = "modbus_power_control_direct"
    entity, hub = make_mode_select(key, parameters | {key: "Disabled"})
    hub.async_write_registers_multi.side_effect = HomeAssistantError("write rejected")

    with pytest.raises(HomeAssistantError, match="write rejected"):
        await entity.async_select_option("Enable SOC Target Control Mode")

    assert hub.data[key] == "Disabled"
    hub.async_refresh_gated_entities.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_required_parameter_prevents_any_write() -> None:
    entity, hub = make_mode_select("modbus_power_control_direct", {})

    with pytest.raises(HomeAssistantError, match="Target SOC.*before enabling"):
        await entity.async_select_option("Enable SOC Target Control Mode")

    hub.async_write_registers_multi.assert_not_awaited()
    assert hub.data == {}


@pytest.mark.parametrize("key", list(DIRECT_VPP_PARAMETER_MODES))
def test_all_direct_parameters_use_transactional_writer_and_persistence(key: str) -> None:
    descriptions: list[BaseModbusNumberEntityDescription | BaseModbusSelectEntityDescription] = list(NUMBER_TYPES)
    descriptions.extend(SELECT_TYPES)
    description = next(description for description in descriptions if description.key == key)
    assert description.async_write_function is async_write_direct_vpp
    assert description.write_method == WRITE_DATA_LOCAL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "mode", "new_value"),
    [
        ("remotecontrol_active_power_direct", 1, -2000),
        ("remotecontrol_reactive_power_direct", 1, -300),
        ("remotecontrol_duration_direct", 1, 120),
        ("remotecontrol_target_soc_direct", 3, 0),
        ("remotecontrol_target_energy_direct", 2, 2000),
        ("remotecontrol_charge_discharge_power_direct", 2, 3000),
        ("remotecontrol_charge_discharge_power_direct", 3, -3000),
        ("remotecontrol_timeout_direct", 5, 300),
        ("remotecontrol_push_mode_power_direct", 4, -5000),
        ("remotecontrol_pv_power_limit_direct", 8, 0),
        ("remotecontrol_push_mode_power_8_9_direct", 9, -5000),
        ("remotecontrol_duration_8_direct", 8, 7200),
        ("remotecontrol_target_soc_9_direct", 9, 90),
        ("remotecontrol_timeout_8_9_direct", 8, 240),
    ],
)
async def test_active_parameter_change_immediately_sends_complete_command(key: str, mode: int, new_value: int, parameters: dict[str, Any]) -> None:
    hub = make_direct_hub(parameters, mode)
    entity = make_number(key, hub)

    await entity.async_set_native_value(new_value)

    address, payload = build_direct_vpp_command(mode, parameters | {key: new_value})
    hub.async_read_input_registers.assert_awaited_once_with(unit=1, address=0x100, count=1)
    hub.async_write_registers_multi.assert_awaited_once_with(unit=1, address=address, payload=payload)
    hub.async_write_registers_single.assert_not_awaited()
    hub.async_write_register.assert_not_awaited()
    assert hub.data == parameters | {key: new_value}
    assert hub.localsUpdated is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "mode"),
    [("remote_control_target_set_type_direct", 2), ("power_control_mode_target_set_type_direct", 8)],
)
async def test_target_set_type_changes_immediately_and_is_not_overridden(key: str, mode: int, parameters: dict[str, Any]) -> None:
    entity, hub = make_mode_select(key, parameters)
    hub.async_read_input_registers.return_value.registers = [mode]

    await entity.async_select_option("Update")

    address, payload = build_direct_vpp_command(mode, parameters | {key: "Update"})
    hub.async_write_registers_multi.assert_awaited_once_with(unit=1, address=address, payload=payload)
    assert hub.data[key] == "Update"
    assert hub.localsUpdated is True


@pytest.mark.asyncio
async def test_stale_mode_select_cannot_reactivate_expired_vpp(parameters: dict[str, Any]) -> None:
    parameters["modbus_power_control_direct"] = "Enable Power Control Mode"
    hub = make_direct_hub(parameters, mode=0)
    entity = make_number("remotecontrol_active_power_direct", hub)

    await entity.async_set_native_value(2000)

    hub.async_write_registers_multi.assert_not_awaited()
    assert hub.data[entity.entity_description.key] == 2000
    assert hub.localsUpdated is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "mode"),
    [("remotecontrol_duration_8_direct", 9), ("remotecontrol_target_soc_9_direct", 8), ("remotecontrol_active_power_direct", 4)],
)
async def test_irrelevant_parameter_does_not_resend_or_switch_active_mode(key: str, mode: int, parameters: dict[str, Any]) -> None:
    hub = make_direct_hub(parameters, mode)
    entity = make_number(key, hub)

    await entity.async_set_native_value(50)

    hub.async_write_registers_multi.assert_not_awaited()
    assert hub.data == parameters | {key: 50}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        None,
        SimpleNamespace(isError=lambda: True, registers=[1]),
        SimpleNamespace(isError=lambda: False, registers=[]),
        SimpleNamespace(isError=lambda: False, registers=[1, 2]),
        SimpleNamespace(isError=lambda: False, registers=[10]),
        SimpleNamespace(isError=lambda: False, registers=[65535]),
        object(),
    ],
)
async def test_unknown_active_mode_fails_without_write_or_cache_change(response: Any, parameters: dict[str, Any]) -> None:
    hub = make_direct_hub(parameters)
    hub.async_read_input_registers.return_value = response
    entity = make_number("remotecontrol_active_power_direct", hub)

    with pytest.raises(HomeAssistantError, match="Cannot read the active.*0x100"):
        await entity.async_set_native_value(1000)

    hub.async_write_registers_multi.assert_not_awaited()
    assert hub.data == parameters
    assert hub.localsUpdated is False


@pytest.mark.asyncio
async def test_unknown_active_command_is_not_overwritten_with_defaults() -> None:
    hub = make_direct_hub({}, mode=1)
    entity = make_number("remotecontrol_active_power_direct", hub)

    with pytest.raises(HomeAssistantError, match="parameter.*unknown"):
        await entity.async_set_native_value(1000)

    hub.async_write_registers_multi.assert_not_awaited()
    assert hub.data == {}


@pytest.mark.asyncio
async def test_failed_parameter_write_preserves_all_previous_values(parameters: dict[str, Any]) -> None:
    hub = make_direct_hub(parameters, mode=3)
    hub.async_write_registers_multi.side_effect = HomeAssistantError("write rejected")
    entity = make_number("remotecontrol_target_soc_direct", hub)

    with pytest.raises(HomeAssistantError, match="write rejected"):
        await entity.async_set_native_value(75)

    assert hub.data == parameters
    assert hub.localsUpdated is False


@pytest.mark.asyncio
async def test_successful_activation_remembers_defaults_for_immediate_updates() -> None:
    select, hub = make_mode_select("modbus_power_control_direct", {})
    await select.async_select_option("Enable Power Control Mode")
    assert hub.data["remotecontrol_duration_direct"] == 60
    assert hub.data["remotecontrol_reactive_power_direct"] == 0
    hub.async_read_input_registers.return_value.registers = [1]
    hub.async_write_registers_multi.reset_mock()
    number = make_number("remotecontrol_active_power_direct", hub)

    await number.async_set_native_value(-1000)

    hub.async_write_registers_multi.assert_awaited_once()
    assert hub.data["remotecontrol_active_power_direct"] == -1000


@pytest.mark.asyncio
async def test_concurrent_changes_keep_both_new_values(parameters: dict[str, Any]) -> None:
    hub = make_direct_hub(parameters, mode=1)
    first_write_started = asyncio.Event()
    finish_first_write = asyncio.Event()
    writes: list[list[tuple[str, int]]] = []

    async def write(*, unit: int, address: int, payload: list[tuple[str, int]]) -> None:
        writes.append(payload)
        if len(writes) == 1:
            first_write_started.set()
            await finish_first_write.wait()

    hub.async_write_registers_multi.side_effect = write
    active = make_number("remotecontrol_active_power_direct", hub)
    reactive = make_number("remotecontrol_reactive_power_direct", hub)
    first = asyncio.create_task(active.async_set_native_value(1000))
    await first_write_started.wait()
    second = asyncio.create_task(reactive.async_set_native_value(500))
    finish_first_write.set()
    await asyncio.gather(first, second)

    expected_data = parameters | {"remotecontrol_active_power_direct": 1000, "remotecontrol_reactive_power_direct": 500}
    assert writes[-1] == build_direct_vpp_command(1, expected_data)[1]
    assert hub.data == expected_data


def configure_local_storage(hub: Any, tmp_path: Path) -> None:
    hub.writeLocals = {
        description.key: description for description in (*NUMBER_TYPES, *SELECT_TYPES) if description.key in DIRECT_VPP_PARAMETER_MODES
    }
    hub._hass = SimpleNamespace(config=SimpleNamespace(path=lambda name: str(tmp_path / name)))
    hub.plugin.localDataCallback = Mock()
    hub.cyclecount = 10


def test_parameters_are_restored_but_no_mode_is_restored_or_reactivated(parameters: dict[str, Any], tmp_path: Path) -> None:
    hub = make_direct_hub(parameters | {"modbus_power_control_direct": "Enable Power Control Mode"})
    configure_local_storage(hub, tmp_path)
    hub.saveLocalData()
    restored = make_direct_hub({})
    configure_local_storage(restored, tmp_path)

    restored.loadLocalData()

    assert restored.data == parameters
    assert restored.localsLoaded is True
    restored.async_write_registers_multi.assert_not_awaited()


def test_existing_local_file_does_not_invent_unknown_direct_parameters(tmp_path: Path) -> None:
    hub = make_direct_hub({})
    configure_local_storage(hub, tmp_path)
    (tmp_path / "test_data.json").write_text(json.dumps({"_version": hub.DATAFORMAT_VERSION}))

    hub.loadLocalData()

    assert hub.data["remotecontrol_active_power_direct"] is None
    assert hub.data["remotecontrol_duration_direct"] is None


@pytest.mark.asyncio
async def test_disable_does_not_need_local_storage_or_mode_read() -> None:
    entity, hub = make_mode_select("modbus_power_control_direct", {})
    hub.localsLoaded = False
    hub._hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=AssertionError("must not load parameters")))

    await entity.async_select_option("Disabled")

    hub.async_read_input_registers.assert_not_awaited()
    hub.async_write_registers_multi.assert_awaited_once_with(unit=1, address=0x7C, payload=build_direct_vpp_command(0, {})[1])
    assert hub.localsUpdated is False


@pytest.mark.asyncio
async def test_invalid_parameter_is_not_even_staged_while_disabled() -> None:
    hub = make_direct_hub({})
    entity = make_number("remotecontrol_pv_power_limit_direct", hub)

    with pytest.raises(HomeAssistantError, match="outside"):
        await entity.async_set_native_value(-1)

    assert hub.data == {}
    hub.async_write_registers_multi.assert_not_awaited()


@pytest.mark.asyncio
async def test_activation_updates_companion_entity_states() -> None:
    entity, hub = make_mode_select("modbus_power_control_direct", {})
    duration = Mock()
    hub.numberEntities["remotecontrol_duration_direct"] = duration

    await entity.async_select_option("Enable Power Control Mode")

    duration.modbus_data_updated.assert_called_once()
    assert hub.data["remotecontrol_duration_direct"] == 60


@pytest.mark.asyncio
async def test_parameter_update_reaches_transport_as_one_complete_fc16_write(parameters: dict[str, Any]) -> None:
    hub = make_direct_hub(parameters, mode=3)
    hub.async_write_registers_multi = SolaXModbusHub.async_write_registers_multi.__get__(hub)
    hub._transport.write = AsyncMock(return_value=SimpleNamespace(isError=lambda: False))
    entity = make_number("remotecontrol_charge_discharge_power_direct", hub)

    await entity.async_set_native_value(-4000)

    hub._transport.write.assert_awaited_once_with(1, 0x7C, [3, 2, 0, 0, 0, 0, 0, 30, 0, 0, 0xF060, 0xFFFF, 600], multiple=True)
