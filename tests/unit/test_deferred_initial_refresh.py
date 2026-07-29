"""Tests for the initial refresh after deferred inverter detection."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from custom_components.solax_modbus import PLATFORMS, SolaXModbusHub


@pytest.mark.asyncio
async def test_deferred_setup_starts_initial_refresh_after_forwarding_platforms() -> None:
    hub = cast(Any, object.__new__(SolaXModbusHub))
    entry = object()
    forward_setups = AsyncMock()
    run_initial_refresh = AsyncMock()
    hub._hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_forward_entry_setups=forward_setups),
        loop=asyncio.get_running_loop(),
    )
    hub.entry = entry
    hub._name = "test"
    hub._stopping = False
    hub._platforms_forwarded = False
    hub._initial_refresh_done = False
    hub._initial_refresh_task = None
    hub._run_initial_refresh_when_ready = run_initial_refresh
    hub._has_local_inverter_model = False
    hub.inverter_model = None
    hub.inverterNameSuffix = None
    hub._seriesnumber = "test-serial"
    hub.data = {}
    hub.config = {}
    hub.async_connect = AsyncMock()
    hub._check_connection = AsyncMock(return_value=True)
    hub.plugin = SimpleNamespace(
        async_determineInverterType=AsyncMock(return_value=1),
        plugin_manufacturer="Test",
        inverter_model="Test inverter",
        getSoftwareVersion=lambda data: "1.0",
        getHardwareVersion=lambda data: "1.0",
    )

    await hub._deferred_setup_loop(interval=0)

    forward_setups.assert_awaited_once_with(entry, PLATFORMS)
    assert hub._platforms_forwarded is True
    assert hub._initial_refresh_task is not None
    await hub._initial_refresh_task
    run_initial_refresh.assert_awaited_once_with()
