"""Inputless diagnostics retain context without expiring measured inputs."""

import math
from collections.abc import AsyncGenerator
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest
import pytest_asyncio
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from pytest_homeassistant_custom_component.common import async_test_home_assistant

from custom_components.solax_modbus.const import DOMAIN, BaseModbusSensorEntityDescription
from custom_components.solax_modbus.energy_dashboard import (
    EnergyDashboardMapping,
    _create_energy_dashboard_diagnostic_sensors,
    get_energy_dashboard_coordinator,
)
from custom_components.solax_modbus.plugin_solax import SENSOR_TYPES_MAIN, value_function_hardware_version_g4
from custom_components.solax_modbus.sensor import SolaXModbusSensor

from .test_poll_snapshot import make_group, make_hub, successful_block


@pytest_asyncio.fixture
async def publication_hass() -> AsyncGenerator[HomeAssistant]:
    async with async_test_home_assistant() as hass:
        try:
            yield hass
        finally:
            await hass.async_stop(force=True)


def diagnostic_description(hub: Any, hass: HomeAssistant, key: str) -> Any:
    if key == "hardware_version":
        return next(d for d in SENSOR_TYPES_MAIN if d.key == key and d.value_function is value_function_hardware_version_g4)
    diagnostics = _create_energy_dashboard_diagnostic_sensors(
        hub, hass, {}, DeviceInfo(identifiers={(DOMAIN, "dashboard")}), EnergyDashboardMapping(plugin_name="solax", mappings=[])
    )
    return next(d for d in diagnostics if d.key == key)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("hardware_version", "Gen4"),
        ("energy_dashboard_mode", "Standalone"),
        ("energy_dashboard_inverter_count", "1"),
        ("energy_dashboard_last_total_inverter_count", "1"),
        ("energy_dashboard_parallel_setting", "Free"),
        ("energy_dashboard_mapping_summary", "solax: 0 mappings"),
    ],
)
async def test_real_diagnostics_survive_polling_and_silence(publication_hass: HomeAssistant, key: str, expected: str) -> None:
    hub = make_hub()
    hub.config = {CONF_SCAN_INTERVAL: 15}
    hub._invertertype = 0
    hub.data["parallel_setting"] = "Free"
    coordinator = get_energy_dashboard_coordinator(publication_hass)
    coordinator.register_hub("test", hub)
    coordinator.set_last_total_inverter_count(hub, 1)
    descr = diagnostic_description(hub, publication_hass, key)
    entity = SolaXModbusSensor("test", hub, DeviceInfo(identifiers={(DOMAIN, "test")}), descr)
    entity.hass = publication_hass
    entity.entity_id = f"sensor.{key}"
    await entity.async_added_to_hass()
    hub._computed_input_observations = {}
    with patch("custom_components.solax_modbus.sensor.async_call_later") as later:
        for now in (0, 5, 15, 44, 46, 91, 180):
            hub._pending_input_observations = hub._computed_input_observations.copy()
            with patch("custom_components.solax_modbus._mtime.monotonic", return_value=now):
                published = hub.evaluate_computed_sensor(descr, hub.data, {"raw"}, interval=5)
                hub._computed_input_observations = hub._pending_input_observations
                hub._pending_input_observations = None
                if published:
                    entity.modbus_data_updated()
                assert publication_hass.states.is_state(entity.entity_id, expected)
                assert hub._accepted_input_sample(key) is not None
        with patch("custom_components.solax_modbus._mtime.monotonic", return_value=3600):
            assert hub._accepted_input_sample(key) is not None
            assert math.isinf(hub.computed_sensor_remaining_age(descr))
            assert entity.available
            assert publication_hass.states.is_state(entity.entity_id, expected)
        later.assert_not_called()
        entity.set_energy_dashboard_active(False)
        assert publication_hass.states.is_state(entity.entity_id, "unavailable")
        entity.set_energy_dashboard_active(True)
        assert publication_hass.states.is_state(entity.entity_id, expected)
    await entity.async_will_remove_from_hass()


@pytest.mark.parametrize(
    "overrides",
    [
        {"depends_on": None},
        {"register": 0},
        {"depends_on": ["raw"]},
        {"optional_depends_on": ["raw"]},
        {"depends_on_any": [("raw", "alternative")]},
        {"dependency_selector": lambda _data, _keys: (set(), set())},
        {"readiness_validator": lambda _data: True},
        {"_energy_dashboard_mapping": Mock()},
        {"_is_riemann_sum_sensor": True},
        {"_is_daily_delta_sensor": True},
    ],
)
def test_only_explicitly_inputless_computations_have_no_expiry(overrides: dict[str, Any]) -> None:
    hub = make_hub()
    hub.config = {CONF_SCAN_INTERVAL: 15}
    descr = BaseModbusSensorEntityDescription(key="context", depends_on=[], value_function=lambda _i, _d, _data: "context")
    assert math.isinf(hub.computed_sensor_max_age(descr))
    assert hub.computed_sensor_max_age(replace(descr, **overrides)) == 45


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, float("nan"), "exception"])
async def test_invalid_inputless_result_clears_old_value_and_recovers(publication_hass: HomeAssistant, invalid: Any) -> None:
    hub = make_hub()
    hub.config = {CONF_SCAN_INTERVAL: 15}

    def value(_initial: Any, _description: Any, data: dict[str, Any]) -> Any:
        if data["local"] == "exception":
            raise ValueError("invalid context")
        return data["local"]

    descr = BaseModbusSensorEntityDescription(key="context", depends_on=[], value_function=value)
    entity = SolaXModbusSensor("test", hub, DeviceInfo(identifiers={(DOMAIN, "test")}), descr)
    entity.hass = publication_hass
    entity.entity_id = "sensor.context"
    await entity.async_added_to_hass()
    hub._computed_input_observations = {}
    for output, expected in ((0, "0"), (invalid, "unknown"), (12, "12")):
        hub.data["local"] = output
        hub._pending_input_observations = hub._computed_input_observations.copy()
        assert hub.evaluate_computed_sensor(descr, hub.data, force=True)
        hub._computed_input_observations = hub._pending_input_observations
        hub._pending_input_observations = None
        entity.modbus_data_updated()
        assert publication_hass.states.is_state(entity.entity_id, expected)
    await entity.async_will_remove_from_hass()


@pytest.mark.asyncio
async def test_topology_refresh_and_local_recomputation_still_update(publication_hass: HomeAssistant) -> None:
    hub = make_hub()
    hub.config = {CONF_SCAN_INTERVAL: 15}
    hub._invertertype = 0
    hub.data["parallel_setting"] = "Free"
    hub._pending_input_observations = {}
    descr = diagnostic_description(hub, publication_hass, "energy_dashboard_mode")
    assert hub.evaluate_computed_sensor(descr, hub.data, force=True)
    assert hub.data[descr.key] == "Standalone"
    hub.data["parallel_setting"] = "Master"
    refreshed = diagnostic_description(hub, publication_hass, descr.key)
    assert hub.evaluate_computed_sensor(refreshed, hub.data, force=True)
    assert hub.data[descr.key] == "Parallel - Primary"
    local = BaseModbusSensorEntityDescription(
        key="local_context", depends_on=[], recompute_each_poll=True, allow_none=True, value_function=lambda _i, _d, data: data.get("local")
    )
    for output in (0, 12, None):
        hub.data["local"] = output
        assert hub.evaluate_computed_sensor(local, hub.data)
        assert hub.data[local.key] == output


@pytest.mark.asyncio
async def test_invalid_local_result_publishes_unknown_after_full_poll(publication_hass: HomeAssistant) -> None:
    hub = make_hub()
    hub.config = {CONF_SCAN_INTERVAL: 15}
    hub.blocks_changed = False
    hub.cyclecount = 1
    descr = BaseModbusSensorEntityDescription(
        key="context", depends_on=[], recompute_each_poll=True, value_function=lambda _i, _d, data: data["local"]
    )
    entity = SolaXModbusSensor("test", hub, DeviceInfo(identifiers={(DOMAIN, "test")}), descr)
    entity.hass = publication_hass
    entity.entity_id = "sensor.context"
    await entity.async_added_to_hass()

    async def read(data: dict[str, Any], _block: Any, _typ: str) -> Any:
        return successful_block("raw")

    hub.async_read_modbus_block = read
    interval = SimpleNamespace(interval=15, device_groups={"main": make_group()})
    for output, expected in ((12, "12"), (None, "unknown"), (0, "0")):
        hub.data["local"] = output
        await hub._refresh_interval_group_once(interval)
        assert publication_hass.states.is_state(entity.entity_id, expected)
    await entity.async_will_remove_from_hass()


def test_measured_consumer_of_inputless_context_still_expires() -> None:
    hub = make_hub()
    hub.config = {CONF_SCAN_INTERVAL: 15}
    context = BaseModbusSensorEntityDescription(key="context", depends_on=[], value_function=lambda _i, _d, _data: "Gen4")
    measured = BaseModbusSensorEntityDescription(key="raw", register=1)
    consumer = BaseModbusSensorEntityDescription(key="consumer", depends_on=["context", "raw"], value_function=lambda _i, _d, data: data["raw"])
    hub.sensorDescriptions = {d.key: d for d in (context, measured, consumer)}
    hub._pending_input_observations = {}
    with patch("custom_components.solax_modbus._mtime.monotonic", return_value=0):
        assert hub.evaluate_computed_sensor(context, hub.data)
        hub._remember_computed_sample(measured, 0, ())
        hub.data["raw"] = 0
        assert hub.evaluate_computed_sensor(consumer, hub.data, {"raw", "context"})
        assert hub._pending_input_observations[consumer.key].deadline == 45
    with patch("custom_components.solax_modbus._mtime.monotonic", return_value=46):
        assert hub._accepted_input_sample(context.key) is not None
        assert hub._accepted_input_sample(consumer.key) is None
