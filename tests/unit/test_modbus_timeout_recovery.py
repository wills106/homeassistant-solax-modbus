"""Bounded HA-managed read recovery without false health or quarantine events."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from modbus_connection.exceptions import ModbusConnectionError, ModbusExceptionError, ModbusProtocolError, ModbusTimeoutError

from custom_components.solax_modbus import SolaXModbusHub, block
from custom_components.solax_modbus import modbus_transport as transport
from custom_components.solax_modbus.const import REGISTER_U16, BaseModbusSensorEntityDescription, PollOutcome


@pytest.fixture
def recovery(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(transport, "monotonic", lambda: state.now)
    monkeypatch.setattr(transport, "core_connection_params", lambda settings: SimpleNamespace(endpoint=("tcp", "192.0.2.1", 502)))
    state.unit = SimpleNamespace(
        connected=True,
        require_timeout=Mock(),
        require_connect_delay=Mock(),
        set_message_spacing=Mock(),
        read_holding_registers=AsyncMock(return_value=[42]),
        read_input_registers=AsyncMock(return_value=[43]),
        write_register=AsyncMock(),
        write_registers=AsyncMock(),
        disconnect=AsyncMock(),
    )
    state.getter = Mock(return_value=state.unit)
    state.transport = transport.CoreModbusUnitTransport(
        cast(Any, object()),
        cast(Any, object()),
        {"timeout": 5, "delay": 1, "message_wait_milliseconds": 50},
        1,
        unit_getter=state.getter,
    )
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._transport = state.transport
    hub._name = "Growatt"
    hub._modbus_addr = 1
    hub._stopping = False
    hub._lock = asyncio.Lock()
    hub._poll_data_lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub.plugin = SimpleNamespace(order32="big", isAwake=Mock(return_value=True))
    hub.cyclecount = 20
    hub._validate_register_func = None
    hub.tmpdata_expiry = {}
    hub.localsLoaded = True
    hub.slowdown = 1
    hub._comm_block_failures = {}
    hub._comm_last_block_failure_time = None
    hub._comm_recent_outcomes = []
    hub._comm_poll_durations = []
    hub._comm_overrun_count = 0
    hub._comm_recovery_active = False
    hub.bad_regs = {"holding": set(), "input": set()}
    hub.data = {}
    hub.sensorEntities = {}
    hub.sensorDescriptions = {}
    hub.computedSensors = {}
    hub.computedEntities = {}
    hub.writeLocals = {}
    hub._schedule_runtime_bisect = Mock()
    state.hub = hub
    description = BaseModbusSensorEntityDescription(key="power", register=3306, register_data_type=REGISTER_U16)
    state.block = block(start=3306, end=3307, descriptions={3306: description}, regs=[3306])
    return state


@pytest.mark.parametrize("kind", ["holding", "input"])
@pytest.mark.parametrize("error_type", [ModbusTimeoutError, ModbusConnectionError])
async def test_timeout_reconnects_and_repeats_exact_read_once(
    recovery: Any, kind: str, error_type: type[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    method = getattr(recovery.unit, f"read_{kind}_registers")
    method.side_effect = [error_type("response timeout or lost connection"), [123]]
    order = Mock()
    order.attach_mock(method, "read")
    order.attach_mock(recovery.unit.disconnect, "disconnect")

    result = await recovery.transport.read(kind, 1, 3306, 7)

    assert result.registers == [123]
    assert [call[0] for call in order.mock_calls] == ["read", "disconnect", "read"]
    assert method.await_args_list[0] == method.await_args_list[1]
    assert method.await_args.args == (3306, 7)
    assert recovery.transport.backoff_remaining == 0
    assert recovery.transport.recovering is False
    recovery.unit.require_timeout.assert_called_once_with(5)
    recovery.unit.require_connect_delay.assert_called_once_with(1)
    recovery.unit.set_message_spacing.assert_called_once_with(0.05)
    recovery.getter.assert_called_once()
    assert "retrying once" in caplog.text
    assert "succeeded after reconnect" in caplog.text


async def test_recovered_block_is_fresh_and_never_degrades_health_or_triggers_bisect(recovery: Any) -> None:
    recovery.unit.read_holding_registers.side_effect = [ModbusTimeoutError("response timeout"), [42]]
    data: dict[str, Any] = {}

    result = await recovery.hub.async_read_modbus_block(data, recovery.block, "holding")
    recovery.hub._record_poll_cycle(PollOutcome.SUCCESS, 5.1, 15)

    assert result.data_succeeded is True
    assert result.fresh_keys == frozenset({"power"})
    assert data == {"power": 42}
    assert recovery.hub._comm_last_block_failure_time is None
    assert recovery.hub._comm_block_failures == {}
    assert recovery.hub.data["communication_health"] == "Healthy"
    recovery.hub._schedule_runtime_bisect.assert_not_called()


async def test_exhausted_read_records_one_failure_but_no_bad_register_evidence(recovery: Any) -> None:
    recovery.unit.read_holding_registers.side_effect = ModbusTimeoutError("response timeout")
    result = await recovery.hub.async_read_modbus_block({}, recovery.block, "holding")

    assert result.data_succeeded is False
    assert recovery.unit.read_holding_registers.await_count == 2
    recovery.unit.disconnect.assert_awaited_once()
    assert recovery.hub._comm_last_block_failure_time is not None
    assert recovery.hub._comm_block_failures == {}
    assert recovery.hub.bad_regs == {"holding": set(), "input": set()}
    recovery.hub._schedule_runtime_bisect.assert_not_called()


async def test_cooldown_sends_no_requests_and_does_not_record_another_block_failure(recovery: Any) -> None:
    recovery.unit.read_holding_registers.side_effect = ModbusTimeoutError("response timeout")
    await recovery.hub.async_read_modbus_block({}, recovery.block, "holding")
    failed_at = recovery.hub._comm_last_block_failure_time

    with pytest.raises(transport.CoreModbusBackoff):
        await recovery.hub.async_read_modbus_block({}, recovery.block, "holding")

    assert recovery.unit.read_holding_registers.await_count == 2
    assert recovery.hub._comm_last_block_failure_time == failed_at
    assert await recovery.hub.async_read_modbus_data(SimpleNamespace(publish_updates=True)) is PollOutcome.SKIPPED


async def test_backoff_uses_timeout_multiples_caps_at_ten_minutes_and_resets(recovery: Any) -> None:
    recovery.unit.read_holding_registers.side_effect = ModbusTimeoutError("response timeout")
    for delay in (5, 10, 15):
        with pytest.raises(transport.CoreModbusUnitError):
            await recovery.transport.read("holding", 1, 3306, 7)
        assert recovery.transport.backoff_remaining == delay
        recovery.now += delay

    recovery.transport._backoff_delay = 595
    for _ in range(2):
        with pytest.raises(transport.CoreModbusUnitError):
            await recovery.transport.read("holding", 1, 3306, 7)
        assert recovery.transport.backoff_remaining == 600
        recovery.now += 600

    recovery.unit.read_holding_registers.side_effect = None
    await recovery.transport.read("holding", 1, 3306, 1)
    assert recovery.transport.recovering is False
    assert recovery.transport.backoff_remaining == 0
    recovery.unit.read_holding_registers.side_effect = ModbusTimeoutError("response timeout")
    with pytest.raises(transport.CoreModbusUnitError):
        await recovery.transport.read("holding", 1, 3306, 1)
    assert recovery.transport.backoff_remaining == 5


@pytest.mark.parametrize("where", ["disconnect", "retry"])
async def test_reset_and_reconnection_failures_are_bounded_and_logged(recovery: Any, where: str, caplog: pytest.LogCaptureFixture) -> None:
    error = ModbusConnectionError("cannot reconnect")
    recovery.unit.read_holding_registers.side_effect = [ModbusTimeoutError("response timeout"), error]
    if where == "disconnect":
        recovery.unit.disconnect.side_effect = error

    with pytest.raises(transport.CoreModbusUnitError) as caught:
        await recovery.transport.read("holding", 1, 3306, 7)

    assert caught.value.__cause__ is error
    assert recovery.unit.read_holding_registers.await_count == (1 if where == "disconnect" else 2)
    assert recovery.transport.backoff_remaining == 5
    assert ("no retry was sent" if where == "disconnect" else "reconnect or repeated") in caplog.text
    assert "paused for 5.0 seconds" in caplog.text


@pytest.mark.parametrize("error", [ModbusExceptionError(2), ModbusProtocolError("invalid response")])
async def test_device_and_protocol_errors_are_not_retried_or_put_into_backoff(recovery: Any, error: Exception) -> None:
    recovery.unit.read_holding_registers.side_effect = error
    with pytest.raises(transport.CoreModbusUnitError) as caught:
        await recovery.transport.read("holding", 1, 3306, 1)
    assert caught.value.__cause__ is error
    recovery.unit.read_holding_registers.assert_awaited_once()
    recovery.unit.disconnect.assert_not_awaited()
    assert recovery.transport.recovering is False


async def test_real_register_errors_still_reach_existing_bisect_accounting(recovery: Any) -> None:
    recovery.unit.read_holding_registers.side_effect = ModbusExceptionError(2)
    for _ in range(3):
        await recovery.hub.async_read_modbus_block({}, recovery.block, "holding")
    assert len(recovery.hub._comm_block_failures[recovery.hub._block_key(recovery.block, "holding")]) == 3
    recovery.hub._schedule_runtime_bisect.assert_called_once_with(recovery.block, "holding")


async def test_bisect_aborts_without_quarantining_when_transport_times_out(recovery: Any) -> None:
    recovery.unit.read_holding_registers.side_effect = ModbusTimeoutError("response timeout")
    with pytest.raises(transport.CoreModbusBackoff):
        await recovery.hub._probe_block(recovery.block, "holding")
    assert recovery.hub.bad_regs == {"holding": set(), "input": set()}
    assert recovery.unit.read_holding_registers.await_count == 2


async def test_recovery_cooldown_does_not_multiply_sleep_slowdown(recovery: Any) -> None:
    hub = recovery.hub
    hub.blocks_changed = False
    hub.cyclecount = 1  # Normally skipped while slowdown=10.
    hub.slowdown = 10
    hub._async_run_autorepeats = AsyncMock(return_value=set())
    hub._publish_computed_sensors = Mock()
    hub.async_read_modbus_data = AsyncMock(return_value=PollOutcome.FAILED)
    hub.sleepnone = []
    hub.sleepzero = []
    recovery.transport._defer_recovery()
    interval_group = SimpleNamespace(device_groups={"inverter": SimpleNamespace(sensors=[])})

    assert (await hub._refresh_interval_group_once(interval_group))[0] is PollOutcome.SKIPPED
    hub.async_read_modbus_data.assert_not_awaited()
    recovery.now += 5
    assert (await hub._refresh_interval_group_once(interval_group))[0] is PollOutcome.FAILED
    hub.async_read_modbus_data.assert_awaited_once()


@pytest.mark.parametrize("write", [False, True])
async def test_shutdown_cancels_reconnect_without_sending_retry(recovery: Any, write: bool) -> None:
    method = recovery.unit.write_register if write else recovery.unit.read_holding_registers
    method.side_effect = ModbusTimeoutError("response timeout")
    entered = asyncio.Event()

    async def disconnect() -> None:
        entered.set()
        await asyncio.Event().wait()

    recovery.unit.disconnect.side_effect = disconnect
    operation = (
        recovery.hub.async_lowlevel_write_register(1, 4135, 1, REGISTER_U16) if write else recovery.hub.async_read_holding_registers(1, 3306, 7)
    )
    task = asyncio.create_task(operation)
    await entered.wait()
    recovery.hub._stopping = True
    for inflight in list(recovery.hub._inflight_tasks):
        inflight.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    method.assert_awaited_once()
    assert recovery.transport.recovering is False


async def test_recovery_is_isolated_to_its_connection(recovery: Any) -> None:
    other = transport.CoreModbusUnitTransport(cast(Any, object()), cast(Any, object()), recovery.transport._settings, 1, unit_getter=recovery.getter)
    recovery.transport._defer_recovery()
    result = await other.read("holding", 1, 3306, 1)
    assert result is not None and result.registers == [42]
    assert recovery.transport.backoff_remaining == 5


@pytest.mark.parametrize("multiple", [False, True])
async def test_writes_repeat_the_exact_request_once_after_reconnect(recovery: Any, multiple: bool, caplog: pytest.LogCaptureFixture) -> None:
    method = recovery.unit.write_registers if multiple else recovery.unit.write_register
    method.side_effect = [ModbusTimeoutError("missing write acknowledgement"), None]
    values = [1, 2] if multiple else [1]
    order = Mock()
    order.attach_mock(method, "write")
    order.attach_mock(recovery.unit.disconnect, "disconnect")

    response = await recovery.transport.write(1, 4135, values, multiple=multiple)

    assert response.isError() is False
    assert [call[0] for call in order.mock_calls] == ["write", "disconnect", "write"]
    assert method.await_args_list[0] == method.await_args_list[1]
    assert method.await_args.args == (4135, values if multiple else 1)
    assert recovery.transport.backoff_remaining == 0
    assert recovery.transport.recovering is False
    assert "may already have been applied" in caplog.text
    assert "succeeded after reconnect" in caplog.text


@pytest.mark.parametrize("multiple", [False, True])
async def test_exhausted_write_raises_clear_error_without_read_backoff(recovery: Any, multiple: bool) -> None:
    method = recovery.unit.write_registers if multiple else recovery.unit.write_register
    method.side_effect = ModbusTimeoutError("missing write acknowledgement")
    with pytest.raises(HomeAssistantError, match="failed after reconnect and one retry.*write may already have been applied"):
        if multiple:
            await recovery.hub.async_write_registers_single(1, 4135, 1, REGISTER_U16)
        else:
            await recovery.hub.async_lowlevel_write_register(1, 4135, 1, REGISTER_U16)
    assert method.await_count == 2
    recovery.unit.disconnect.assert_awaited_once()
    assert recovery.transport.recovering is False


@pytest.mark.parametrize("outcome", ["success", "recovered", "failed"])
async def test_read_backoff_never_blocks_writes_and_writes_do_not_reset_or_extend_it(recovery: Any, outcome: str) -> None:
    recovery.transport._defer_recovery()
    if outcome == "recovered":
        recovery.unit.write_register.side_effect = [ModbusTimeoutError("missing acknowledgement"), None]
    elif outcome == "failed":
        recovery.unit.write_register.side_effect = ModbusTimeoutError("missing acknowledgement")

    if outcome == "failed":
        with pytest.raises(transport.CoreModbusUnitError):
            await recovery.transport.write(1, 4135, [1], multiple=False)
    else:
        await recovery.transport.write(1, 4135, [1], multiple=False)

    assert recovery.unit.write_register.await_count == (1 if outcome == "success" else 2)
    assert recovery.transport.backoff_remaining == 5
    assert recovery.transport.recovering is True
    recovery.unit.read_holding_registers.assert_not_awaited()


async def test_request_lock_prevents_write_from_interleaving_with_read_reconnect(recovery: Any) -> None:
    recovery.unit.read_holding_registers.side_effect = [ModbusTimeoutError("response timeout"), [42]]
    entered = asyncio.Event()
    release = asyncio.Event()

    async def disconnect() -> None:
        entered.set()
        await release.wait()

    recovery.unit.disconnect.side_effect = disconnect
    read_task = asyncio.create_task(recovery.transport.read("holding", 1, 3306, 1))
    await entered.wait()
    write_task = asyncio.create_task(recovery.transport.write(1, 4135, [1], multiple=False))
    await asyncio.sleep(0)
    recovery.unit.write_register.assert_not_awaited()
    release.set()
    await asyncio.gather(read_task, write_task)
    recovery.unit.write_register.assert_awaited_once()


async def test_write_retry_preserves_payload_even_if_original_list_changes(recovery: Any) -> None:
    values = [1, 2]
    count = 0

    async def write(address: int, payload: list[int]) -> None:
        nonlocal count
        count += 1
        assert address == 4131 and payload == [1, 2]
        if count == 1:
            values[:] = [9, 9]
            raise ModbusTimeoutError("missing acknowledgement")

    recovery.unit.write_registers.side_effect = write
    await recovery.transport.write(1, 4131, values, multiple=True)
    assert count == 2 and values == [9, 9]


async def test_write_device_exception_is_not_repeated(recovery: Any) -> None:
    recovery.unit.write_register.side_effect = ModbusExceptionError(2)
    with pytest.raises(transport.CoreModbusUnitError):
        await recovery.transport.write(1, 4135, [1], multiple=False)
    recovery.unit.write_register.assert_awaited_once()
    recovery.unit.disconnect.assert_not_awaited()


async def test_write_reset_failure_sends_no_second_command(recovery: Any, caplog: pytest.LogCaptureFixture) -> None:
    recovery.unit.write_register.side_effect = ModbusTimeoutError("missing acknowledgement")
    recovery.unit.disconnect.side_effect = ModbusConnectionError("cannot reset link")
    with pytest.raises(transport.CoreModbusUnitError, match="Connection reset.*failed; no retry was sent"):
        await recovery.transport.write(1, 4135, [1], multiple=False)
    recovery.unit.write_register.assert_awaited_once()
    assert recovery.transport.recovering is False
    assert "no retry was sent" in caplog.text


@pytest.mark.parametrize("operation", ["read_holding_registers", "read_input_registers", "write_register", "write_registers"])
async def test_real_unit_api_reconnects_and_keeps_existing_handles(monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    """Use the actual HA library; mock only the underlying socket client."""
    from modbus_connection import ModbusTcpParams
    from modbus_connection import tmodbus as backend

    client_operation = {"write_register": "write_single_register", "write_registers": "write_multiple_registers"}.get(operation, operation)
    failed_unit = SimpleNamespace(**{client_operation: AsyncMock(side_effect=TimeoutError("response timeout"))})
    restored_unit = SimpleNamespace(**{client_operation: AsyncMock(return_value=[42])}, read_coils=AsyncMock(return_value=[True]))
    old_client = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(), for_unit_id=Mock(return_value=failed_unit))
    new_client = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(), for_unit_id=Mock(return_value=restored_unit))
    factory = Mock(side_effect=[old_client, new_client])
    monkeypatch.setattr(backend, "create_async_tcp_client", factory)
    connection = backend.ModbusConnection(ModbusTcpParams(host="192.0.2.1"))
    second_consumer = connection.for_unit(2)
    unit = connection.for_unit(1)
    getter = Mock(return_value=unit)
    adapter = transport.CoreModbusUnitTransport(
        cast(Any, object()),
        cast(Any, object()),
        {"type": "tcp", "host": "192.0.2.1", "port": 502, "timeout": 5, "delay": 0, "message_wait_milliseconds": 0},
        1,
        unit_getter=getter,
    )
    try:
        if operation.startswith("read_"):
            result = await adapter.read("input" if operation == "read_input_registers" else "holding", 1, 10, 1)
            assert result is not None and result.registers == [42]
        else:
            await adapter.write(1, 10, [7], multiple=operation == "write_registers")
        old_client.disconnect.assert_awaited_once()
        old_client.connect.assert_awaited_once()
        new_client.connect.assert_awaited_once()
        assert factory.call_count == 2
        assert all(call.kwargs["timeout"] == 5 for call in factory.call_args_list)
        assert getattr(failed_unit, client_operation).await_count == 1
        assert getattr(restored_unit, client_operation).await_count == 1
        getter.assert_called_once()
        assert await second_consumer.read_coils(0, 1) == [True]
    finally:
        await connection.close()


async def test_recovered_read_does_not_hide_existing_quarantine(recovery: Any) -> None:
    recovery.hub.bad_regs["holding"].add(1)
    recovery.unit.read_holding_registers.side_effect = [ModbusTimeoutError("response timeout"), [42]]
    await recovery.hub.async_read_modbus_block({}, recovery.block, "holding")
    recovery.hub._record_poll_cycle(PollOutcome.SUCCESS, 5.1, 15)
    assert recovery.hub.data["communication_health"] == "Quarantined"


async def test_exhausted_read_stops_remaining_blocks_and_cooldown_polls_are_skipped(recovery: Any) -> None:
    hub = recovery.hub
    hub.localsUpdated = False
    hub.writequeue = {}
    hub.sensorDescriptions = {"power": recovery.block.descriptions[3306]}
    recovery.unit.read_holding_registers.side_effect = ModbusTimeoutError("response timeout")
    group = SimpleNamespace(
        holdingBlocks=[recovery.block, recovery.block], inputBlocks=[recovery.block], readPreparation=None, readFollowUp=None, sensors=[]
    )
    assert await hub.async_read_modbus_data(group) is PollOutcome.FAILED
    assert recovery.unit.read_holding_registers.await_count == 2
    recovery.unit.read_input_registers.assert_not_awaited()
    failed_at = hub._comm_last_block_failure_time
    assert await hub.async_read_modbus_data(group) is PollOutcome.SKIPPED
    assert hub._comm_last_block_failure_time == failed_at
    assert recovery.unit.read_holding_registers.await_count == 2


async def test_explicit_register_error_after_pause_returns_to_normal_bisect_policy(recovery: Any) -> None:
    recovery.transport._defer_recovery()
    recovery.now += 5
    recovery.unit.read_holding_registers.side_effect = ModbusExceptionError(2)
    result = await recovery.hub.async_read_modbus_block({}, recovery.block, "holding")
    assert result.data_succeeded is False
    assert recovery.transport.recovering is False
    assert len(recovery.hub._comm_block_failures[recovery.hub._block_key(recovery.block, "holding")]) == 1
