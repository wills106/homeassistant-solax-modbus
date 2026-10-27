"""Tests for shared native and Home Assistant Core Modbus transports."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import HomeAssistantError
from pymodbus.exceptions import ConnectionException, ModbusIOException

from custom_components.solax_modbus import SolaXModbusHub, block
from custom_components.solax_modbus.const import (
    REG_HOLDING,
    REG_INPUT,
    REGISTER_STR,
    REGISTER_U8H,
    REGISTER_U8L,
    REGISTER_U16,
    REGISTER_U32,
    BaseModbusSensorEntityDescription,
)
from custom_components.solax_modbus.modbus_transport import (
    CORE_CALL_TYPE_REGISTER_HOLDING,
    CORE_CALL_TYPE_REGISTER_INPUT,
    CORE_CALL_TYPE_WRITE_REGISTER,
    CORE_CALL_TYPE_WRITE_REGISTERS,
    CoreModbusTransport,
    NativeModbusTransport,
)
from custom_components.solax_modbus.pymodbus_compat import ADDR_KW


class FakeNativeClient:
    """Minimal pymodbus client for native transport contract tests."""

    def __init__(self, *, connected: bool = False, read_error: Exception | None = None, write_error: Exception | None = None) -> None:
        self.connected = connected
        self.comm_params = SimpleNamespace(host="192.0.2.1", port=502)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.close_calls = 0
        self.read_error = read_error
        self.write_error = write_error

    async def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.close_calls += 1
        self.connected = False

    async def read_holding_registers(self, **kwargs: Any) -> Any:
        self.calls.append(("read_holding", kwargs))
        if self.read_error is not None:
            raise self.read_error
        return SimpleNamespace(isError=lambda: False)

    async def read_input_registers(self, **kwargs: Any) -> Any:
        self.calls.append(("read_input", kwargs))
        if self.read_error is not None:
            raise self.read_error
        return SimpleNamespace(isError=lambda: False)

    async def write_register(self, **kwargs: Any) -> Any:
        self.calls.append(("write_register", kwargs))
        if self.write_error is not None:
            raise self.write_error
        return SimpleNamespace(isError=lambda: False)

    async def write_registers(self, **kwargs: Any) -> Any:
        self.calls.append(("write_registers", kwargs))
        if self.write_error is not None:
            raise self.write_error
        return SimpleNamespace(isError=lambda: False)


class FakeCoreHub:
    """Minimal Core Modbus hub exposing its supported call interface."""

    def __init__(self, responses: list[Any] | None = None, *, connected: bool = True, config_delay: int = 0) -> None:
        self._client = SimpleNamespace(connected=connected)
        self.config_delay = config_delay
        self._responses = list(responses or [])
        self.calls: list[tuple[int, int, int | list[int], str]] = []

    async def async_pb_call(self, unit: int, address: int, value: int | list[int], call_type: str) -> Any:
        self.calls.append((unit, address, value, call_type))
        if self._responses:
            return self._responses.pop(0)
        return SimpleNamespace(isError=lambda: False)


def make_modbus_io_exception(message: str) -> ModbusIOException:
    """Create a pymodbus I/O exception despite its untyped constructor."""
    return ModbusIOException(message)  # type: ignore[no-untyped-call]


def make_connection_exception(message: str) -> ConnectionException:
    """Create a pymodbus connection exception despite its untyped constructor."""
    return ConnectionException(message)  # type: ignore[no-untyped-call]


def make_core_transport(core_hub: FakeCoreHub) -> CoreModbusTransport:
    """Create a Core transport backed by a test hub."""
    return CoreModbusTransport(
        cast(Any, object()),
        "core",
        "test",
        hub_getter=lambda hass, name: core_hub,
        reconnect_delay=0,
    )


def make_quarantine_hub(core_hub: FakeCoreHub) -> Any:
    """Build the minimal integration hub state needed by quarantine probes."""
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._transport = make_core_transport(core_hub)
    hub._name = "test"
    hub._stopping = False
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub._modbus_addr = 1
    hub._time_out = 15
    hub.bisect_max_depth = 10
    hub.bad_regs = {"holding": set(), "input": set()}
    hub._runtime_block_splits = {}
    hub._runtime_bisect_tasks = {}
    hub._comm_block_failures = {}
    hub.initial_groups = {}
    hub.groups = {}
    hub.blocks_changed = False
    hub._comm_last_quarantined_register = None
    hub._comm_last_recovered_register = None
    hub._ensure_quarantine_recheck_task = Mock()
    hub._update_communication_data = Mock()
    hub._publish_communication_diagnostics = Mock()
    return hub


def make_native_hub(client: FakeNativeClient) -> Any:
    """Build the minimal integration hub state needed by native I/O tests."""
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._transport = NativeModbusTransport(client)
    hub._name = "test"
    hub._stopping = False
    hub._lock = asyncio.Lock()
    hub._inflight_tasks = set()
    hub.plugin = SimpleNamespace(order32="big")
    return hub


@pytest.mark.asyncio
async def test_native_transport_implements_shared_read_write_contract() -> None:
    client = FakeNativeClient()
    transport = NativeModbusTransport(client)

    assert await transport.connect() is True
    assert transport.is_connected() is True
    assert transport.endpoint == "192.0.2.1:502"

    await transport.read("holding", unit=1, address=10, count=2)
    await transport.read("input", unit=2, address=20, count=3)
    await transport.write(unit=3, address=30, values=[7], multiple=False)
    await transport.write(unit=4, address=40, values=[8, 9], multiple=True)

    assert client.calls == [
        ("read_holding", {"address": 10, "count": 2, ADDR_KW: 1}),
        ("read_input", {"address": 20, "count": 3, ADDR_KW: 2}),
        ("write_register", {"address": 30, "value": 7, ADDR_KW: 3}),
        ("write_registers", {"address": 40, "values": [8, 9], ADDR_KW: 4}),
    ]

    await transport.close()
    assert transport.is_connected() is False


@pytest.mark.asyncio
async def test_read_timeout_leaves_connected_native_transport_open() -> None:
    client = FakeNativeClient(connected=True, read_error=make_modbus_io_exception("no response"))
    hub = make_native_hub(client)

    response = await hub.async_read_holding_registers(unit=1, address=9, count=5)

    assert response is None
    assert client.connected is True
    assert client.close_calls == 0


@pytest.mark.asyncio
async def test_read_connection_error_resets_native_transport() -> None:
    client = FakeNativeClient(connected=True, read_error=make_connection_exception("connection lost"))
    hub = make_native_hub(client)

    response = await hub.async_read_holding_registers(unit=1, address=9, count=5)

    assert response is None
    assert client.connected is False
    assert client.close_calls == 1


@pytest.mark.asyncio
async def test_write_timeout_leaves_connected_native_transport_open() -> None:
    client = FakeNativeClient(connected=True, write_error=make_modbus_io_exception("no response"))
    hub = make_native_hub(client)

    with pytest.raises(HomeAssistantError, match="single-register write failed"):
        await hub.async_lowlevel_write_register(unit=1, address=9, payload=1, register_data_type=REGISTER_U16)

    assert client.connected is True
    assert client.close_calls == 0


@pytest.mark.asyncio
async def test_write_connection_error_resets_native_transport() -> None:
    client = FakeNativeClient(connected=True, write_error=make_connection_exception("connection lost"))
    hub = make_native_hub(client)

    with pytest.raises(HomeAssistantError, match="single-register write failed"):
        await hub.async_lowlevel_write_register(unit=1, address=9, payload=1, register_data_type=REGISTER_U16)

    assert client.connected is False
    assert client.close_calls == 1


@pytest.mark.asyncio
async def test_core_transport_delegates_reads_and_writes_to_core_hub() -> None:
    core_hub = FakeCoreHub()
    transport = make_core_transport(core_hub)

    await transport.read("holding", unit=1, address=10, count=2)
    await transport.read("input", unit=2, address=20, count=3)
    await transport.write(unit=3, address=30, values=[7], multiple=False)
    await transport.write(unit=4, address=40, values=[8, 9], multiple=True)

    assert core_hub.calls == [
        (1, 10, 2, CORE_CALL_TYPE_REGISTER_HOLDING),
        (2, 20, 3, CORE_CALL_TYPE_REGISTER_INPUT),
        (3, 30, 7, CORE_CALL_TYPE_WRITE_REGISTER),
        (4, 40, [8, 9], CORE_CALL_TYPE_WRITE_REGISTERS),
    ]


def test_core_transport_uses_real_core_connection_state() -> None:
    core_hub = FakeCoreHub(connected=True)
    transport = make_core_transport(core_hub)

    assert transport.is_connected() is True

    core_hub.config_delay = 5
    assert transport.is_connected() is False

    core_hub.config_delay = 0
    core_hub._client.connected = False
    assert transport.is_connected() is False


@pytest.mark.asyncio
async def test_core_transport_close_does_not_close_shared_client() -> None:
    core_hub = FakeCoreHub()
    transport = make_core_transport(core_hub)

    assert transport.is_connected() is True
    await transport.close()

    assert core_hub._client.connected is True
    assert transport.is_connected() is False


@pytest.mark.asyncio
async def test_runtime_quarantine_operates_through_core_transport() -> None:
    success = SimpleNamespace(isError=lambda: False)
    core_hub = FakeCoreHub([None, None, success])
    hub = make_quarantine_hub(core_hub)
    hub._confirm_bad_register = AsyncMock(return_value=True)
    failing_block = block(start=10, end=12, descriptions={}, regs=[10, 11])

    await hub._runtime_bisect_block(failing_block, "holding", "holding:10-12")

    assert hub.bad_regs["holding"] == {10}
    assert hub._runtime_block_splits == {}
    assert core_hub.calls == [
        (1, 10, 2, CORE_CALL_TYPE_REGISTER_HOLDING),
        (1, 10, 1, CORE_CALL_TYPE_REGISTER_HOLDING),
        (1, 11, 1, CORE_CALL_TYPE_REGISTER_HOLDING),
    ]
    hub._ensure_quarantine_recheck_task.assert_called_once_with()
    hub._update_communication_data.assert_called_once_with()
    hub._publish_communication_diagnostics.assert_called_once_with()


def make_block_split_hub(typ: str, registers: list[int]) -> tuple[Any, FakeCoreHub, dict[int, Any]]:
    core = FakeCoreHub()
    hub = make_quarantine_hub(core)
    hub._hass = object()
    hub.plugin = SimpleNamespace(block_size=100, auto_block_ignore_readerror=None)
    descriptions = {
        address: BaseModbusSensorEntityDescription(
            key=f"value_{address}", register=address, register_type=REG_HOLDING if typ == "holding" else REG_INPUT, internal=True
        )
        for address in registers
    }
    hub.initial_groups = {
        30: SimpleNamespace(
            device_groups={
                "inverter": SimpleNamespace(
                    holdingRegs=descriptions if typ == "holding" else {},
                    inputRegs=descriptions if typ == "input" else {},
                    readPreparation=None,
                    readFollowUp=None,
                )
            }
        )
    }
    hub.rebuild_blocks(hub.initial_groups)
    return hub, core, descriptions


def read_blocks(hub: Any, typ: str, interval: int = 30, device_name: str = "inverter") -> list[block]:
    """Inspect the real rebuild path, including the block's polling-group identity."""
    group = hub.groups[interval].device_groups[device_name]
    return cast(list[block], group.holdingBlocks if typ == "holding" else group.inputBlocks)


@pytest.mark.asyncio
@pytest.mark.parametrize("typ", ["holding", "input"])
@pytest.mark.parametrize("reason", ["gap", "read_limit"])
async def test_bisect_keeps_readable_partitions_without_extra_probes(typ: str, reason: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed parent must not be rebuilt when all entity ranges are readable."""
    registers = [0x347, 0x34F, 0x351, 0x352, 0x353, 0x354, 0x367, 0x371] if reason == "gap" else list(range(8))
    hub, core, descriptions = make_block_split_hub(typ, registers)
    original = read_blocks(hub, typ)[0]
    key = hub._block_key(original, typ)
    hub._comm_block_failures[key] = [1, 2, 3]
    hub._confirm_bad_register = AsyncMock()
    success = SimpleNamespace(isError=lambda: False)

    async def read(unit: int, address: int, count: int, call_type: str) -> Any:
        core.calls.append((unit, address, count, call_type))
        fails = address <= 0x355 < address + count if reason == "gap" else count > 4
        return None if fails else success

    monkeypatch.setattr(core, "async_pb_call", read)
    await hub._runtime_bisect_block(original, typ, key)
    expected = [(0x347, 0x353), (0x353, 0x355), (0x367, 0x372)] if reason == "gap" else [(0, 4), (4, 8)]
    assert hub.blocks_changed is True
    assert hub.bad_regs == {"holding": set(), "input": set()}
    assert hub._runtime_block_splits == {(30, "inverter", typ): {start for start, _end in expected[1:]}}
    assert key not in hub._comm_block_failures
    hub._confirm_bad_register.assert_not_awaited()
    hub._ensure_quarantine_recheck_task.assert_not_called()
    # Only the existing binary search is needed: one probe per tree node.
    assert len(core.calls) == 2 * len(expected) - 1
    core.calls.clear()

    for _ in range(2):
        hub.rebuild_blocks(hub.initial_groups)
        blocks = read_blocks(hub, typ)
        assert [(item.start, item.end) for item in blocks] == expected
        for item in blocks:
            assert item.group_key == (30, "inverter")
            assert await hub._probe_block(item, typ) is True
    assert len(core.calls) == 2 * len(expected)
    for _unit, address, count, _call_type in core.calls:
        assert isinstance(count, int)
        assert (address, address + count) in expected

    # Learned limits must survive when the first entity after a split disappears.
    if reason == "gap":
        descriptions.pop(0x353)
        hub.rebuild_blocks(hub.initial_groups)
        assert [(item.start, item.end) for item in read_blocks(hub, typ)] == [(0x347, 0x353), (0x354, 0x355), (0x367, 0x372)]


@pytest.mark.asyncio
@pytest.mark.parametrize("typ", ["holding", "input"])
async def test_bisect_is_scoped_to_the_polling_group(typ: str) -> None:
    """Identical addresses in another device or interval must not share failures or splits."""
    hub, core, descriptions = make_block_split_hub(typ, [10, 30])
    for interval, device_name in ((30, "battery_2"), (60, "inverter")):
        group = SimpleNamespace(
            holdingRegs=dict(descriptions) if typ == "holding" else {},
            inputRegs=dict(descriptions) if typ == "input" else {},
            readPreparation=None,
            readFollowUp=None,
        )
        hub.initial_groups.setdefault(interval, SimpleNamespace(device_groups={})).device_groups[device_name] = group
    hub.rebuild_blocks(hub.initial_groups)
    original = read_blocks(hub, typ)[0]
    other = read_blocks(hub, typ, device_name="battery_2")[0]
    slower = read_blocks(hub, typ, interval=60)[0]
    assert len({hub._block_key(item, typ) for item in (original, other, slower)}) == 3

    hub._hass = SimpleNamespace(loop=asyncio.get_running_loop())
    hub._comm_recent_outcomes = []
    core._responses = [None, SimpleNamespace(isError=lambda: False), SimpleNamespace(isError=lambda: False)]
    # Successful reads of the other group must not erase this group's failures.
    for _ in range(3):
        hub._record_block_result(original, typ, False)
        hub._record_block_result(other, typ, True)
    assert len(hub._runtime_bisect_tasks) == 1
    await hub._runtime_bisect_tasks[hub._block_key(original, typ)]

    assert hub._runtime_block_splits == {(30, "inverter", typ): {30}}
    assert len(core.calls) == 3  # Existing probes only: parent and two readable children.
    for _ in range(2):
        hub.rebuild_blocks(hub.initial_groups)
        assert [(item.start, item.end) for item in read_blocks(hub, typ)] == [(10, 11), (30, 31)]
        assert [(item.start, item.end) for item in read_blocks(hub, typ, device_name="battery_2")] == [(10, 31)]
        assert [(item.start, item.end) for item in read_blocks(hub, typ, interval=60)] == [(10, 31)]
    assert len(core.calls) == 3  # Rebuilding groups never adds revalidation requests.


@pytest.mark.parametrize("auto_ignore", [None, False, True])
@pytest.mark.parametrize("byte_split", [False, True])
def test_learned_boundary_keeps_ignore_readerror(auto_ignore: bool | None, byte_split: bool) -> None:
    """A learned boundary must not rewrite normal or byte-split entity failure policies."""
    hub, _core, descriptions = make_block_split_hub("holding", [10, 30])
    hub.plugin.auto_block_ignore_readerror = auto_ignore
    if byte_split:
        descriptions[30] = {unit: replace(descriptions[30], key=f"value_30_{unit}", register_data_type=unit) for unit in (REGISTER_U8H, REGISTER_U8L)}
    hub._runtime_block_splits[(30, "inverter", "holding")] = {30}
    hub.rebuild_blocks(hub.initial_groups)
    blocks = read_blocks(hub, "holding")
    assert [(item.start, item.end) for item in blocks] == [(10, 11), (30, 31)]
    description = blocks[1].descriptions[30]
    entries = description.values() if byte_split else [description]
    assert all(entry.ignore_readerror is False for entry in entries)


@pytest.mark.parametrize("auto_ignore", [None, False, True])
def test_size_overflow_keeps_automatic_ignore_readerror(auto_ignore: bool | None) -> None:
    """The existing policy for size-overflow blocks is unchanged."""
    hub, _core, _descriptions = make_block_split_hub("holding", [10, 30])
    hub.plugin.auto_block_ignore_readerror = auto_ignore
    hub.plugin.block_size = 10
    hub.rebuild_blocks(hub.initial_groups)
    blocks = read_blocks(hub, "holding")
    assert [(item.start, item.end) for item in blocks] == [(10, 11), (30, 31)]
    assert blocks[1].descriptions[30].ignore_readerror is (auto_ignore is True)


@pytest.mark.asyncio
async def test_learned_partitions_keep_multi_register_entities_whole() -> None:
    hub, core, descriptions = make_block_split_hub("holding", [10, 30])
    descriptions[10] = BaseModbusSensorEntityDescription(
        key="power", register=10, register_type=REG_HOLDING, internal=True, register_data_type=REGISTER_U32
    )
    descriptions[30] = BaseModbusSensorEntityDescription(
        key="serial", register=30, register_type=REG_HOLDING, internal=True, register_data_type=REGISTER_STR, wordcount=4
    )
    hub.rebuild_blocks(hub.initial_groups)
    original = read_blocks(hub, "holding")[0]
    core._responses = [None, SimpleNamespace(isError=lambda: False), SimpleNamespace(isError=lambda: False)]
    await hub._runtime_bisect_block(original, "holding", hub._block_key(original, "holding"))
    hub.rebuild_blocks(hub.initial_groups)
    assert [(item.start, item.end) for item in read_blocks(hub, "holding")] == [(10, 12), (30, 34)]
    assert [(address, count) for _unit, address, count, _call_type in core.calls] == [(10, 24), (10, 2), (30, 4)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("outcome", "probes"), [("disconnect", 2), ("stop", 2), ("unreadable", 3), ("recovered", 1), ("depth_limit", 1)])
async def test_bisect_does_not_keep_unproven_partitions(outcome: str, probes: int, monkeypatch: pytest.MonkeyPatch) -> None:
    hub, core, descriptions = make_block_split_hub("holding", [10, 30])
    original = read_blocks(hub, "holding")[0]
    hub._confirm_bad_register = AsyncMock(return_value=False)
    if outcome == "depth_limit":
        hub.bisect_max_depth = 0

    async def read(unit: int, address: int, count: int, call_type: str) -> Any:
        core.calls.append((unit, address, count, call_type))
        if len(core.calls) == 2 and outcome == "disconnect":
            core._client.connected = False
        if len(core.calls) == 2 and outcome == "stop":
            hub._stopping = True
        return SimpleNamespace(isError=lambda: False) if outcome == "recovered" else None

    monkeypatch.setattr(core, "async_pb_call", read)
    await hub._runtime_bisect_block(original, "holding", hub._block_key(original, "holding"))
    assert hub._runtime_block_splits == {}
    assert hub.bad_regs["holding"] == set()
    assert hub.blocks_changed is False
    assert len(core.calls) == probes


@pytest.mark.asyncio
async def test_quarantined_register_is_rechecked_through_core_transport() -> None:
    core_hub = FakeCoreHub()
    hub = make_quarantine_hub(core_hub)
    hub.bad_regs["holding"].add(10)

    await hub._recheck_quarantined_register("holding", 10)

    assert hub.bad_regs["holding"] == set()
    assert hub.blocks_changed is True
    assert hub._comm_last_recovered_register == "holding 0xa"
    assert core_hub.calls == [(1, 10, 1, CORE_CALL_TYPE_REGISTER_HOLDING)]
