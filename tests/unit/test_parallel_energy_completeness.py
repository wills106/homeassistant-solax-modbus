"""Issue #2499: an incomplete parallel system is never a valid energy total."""

import time
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from pytest_homeassistant_custom_component.common import async_test_home_assistant

from custom_components.solax_modbus import InputObservation
from custom_components.solax_modbus.const import CONF_PLUGIN, DOMAIN
from custom_components.solax_modbus.energy_dashboard import (
    ED_SWITCH_GRID_TO_BATTERY,
    EnergyDashboardMapping,
    create_energy_dashboard_sensors,
    get_energy_dashboard_coordinator,
)
from custom_components.solax_modbus.plugin_solax import GEN4, HYBRID, PM, X3
from custom_components.solax_modbus.plugin_solax import plugin_instance as solax_plugin
from custom_components.solax_modbus.sensor import SolaXModbusSensor, entityToListSingle

from .test_energy_dashboard_coordinator import FakeHass
from .test_poll_snapshot import make_hub

TARGETS = ("grid_to_battery_energy", "battery_energy_charge", "battery_energy_discharge", "solar_energy_production")
DEVICE = DeviceInfo(identifiers={(DOMAIN, "parallel-energy-test")})


def observe(hub: Any, values: dict[str, Any], *, age: float = 0) -> None:
    """Record accepted raw inputs, not just retained cache values."""
    now = time.monotonic() - age
    for key, value in values.items():
        hub.data[key] = value
        hub._computed_input_observations[key] = InputObservation(now, value, now + 90)


def make_inverter(name: str, role: str, energy: float, *, count: Any = None) -> Any:
    hub = make_hub()
    hub._name = name
    hub.entry = SimpleNamespace(entry_id=name)
    hub.config = {CONF_PLUGIN: "solax", "scan_interval": 30, "scan_interval_fast": 5, "scan_interval_medium": 15}
    hub.plugin = solax_plugin.create_hub_instance()
    hub._invertertype = HYBRID | GEN4 | X3 | PM
    hub.seriesnumber = "H34A10" if role == "Master" else "H34A05"
    hub._computed_input_observations = {}
    hub.sensorDescriptions = {
        description.key: description
        for description in hub.plugin.SENSOR_TYPES
        if hub.plugin.matchInverterWithMask(hub._invertertype, description.allowedtypes)
    }
    observe(
        hub,
        {
            "parallel_setting": role,
            "e_charge_today": energy,
            "battery_input_energy_today": energy,
            "battery_output_energy_today": energy,
            "today_s_solar_energy": energy,
            ED_SWITCH_GRID_TO_BATTERY: 1,
        },
    )
    if count is not None:
        observe(hub, {"pm_inverter_count": count})
    return hub


async def describe(hass: Any, master: Any, target: str) -> Any:
    mappings = [
        mapping
        for mapping in master.plugin.ENERGY_DASHBOARD_MAPPING.mappings
        if mapping.target_key == target and master.plugin.matchInverterWithMask(master._invertertype, mapping.allowedtypes)
    ]
    mapping = EnergyDashboardMapping("solax", mappings, inverter_count_key=master.plugin.ENERGY_DASHBOARD_MAPPING.inverter_count_key)
    with patch("custom_components.solax_modbus.energy_dashboard.create_energy_dashboard_device_info", return_value=DEVICE):
        descriptions = await create_energy_dashboard_sensors(master, mapping, hass, {})
    return next(description for description in descriptions if description.key == f"all_{target}")


@pytest.mark.asyncio
@pytest.mark.parametrize("target", TARGETS)
async def test_startup_unload_and_recovery_never_publish_master_only(target: str) -> None:
    hass = FakeHass()
    coordinator = get_energy_dashboard_coordinator(hass)  # type: ignore[arg-type]
    master = make_inverter("Master", "Master", 4.7, count=2)
    slave = make_inverter("Slave", "Slave", 5.8)
    coordinator.register_hub("Master", master)

    description = await describe(hass, master, target)
    assert "pm_inverter_count" in description.depends_on
    assert master.evaluate_computed_sensor(description, master.data, set(master.data))
    assert master.data[description.key] is None
    assert not SolaXModbusSensor("test", master, DEVICE, description).available

    coordinator.register_hub("Slave", slave)
    description = await describe(hass, master, target)
    assert master.evaluate_computed_sensor(description, master.data, set(master.data))
    assert master.data[description.key] == 10.5

    coordinator.unregister_hub("Slave")
    description = await describe(hass, master, target)
    assert master.evaluate_computed_sensor(description, master.data, set(master.data))
    assert master.data[description.key] is None

    coordinator.register_hub("Slave", slave)
    description = await describe(hass, master, target)
    assert master.evaluate_computed_sensor(description, master.data, set(master.data))
    assert master.data[description.key] == 10.5


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [None, 0, -1, True, False, 2.5, "2", 1, 3])
async def test_unknown_invalid_or_mismatched_count_is_not_a_complete_system(count: Any) -> None:
    hass = FakeHass()
    coordinator = get_energy_dashboard_coordinator(hass)  # type: ignore[arg-type]
    master = make_inverter("Master", "Master", 4.7, count=count)
    slave = make_inverter("Slave", "Slave", 5.8)
    coordinator.register_hub("Master", master)
    coordinator.register_hub("Slave", slave)
    description = await describe(hass, master, "grid_to_battery_energy")

    assert master.evaluate_computed_sensor(description, master.data, set(master.data))
    assert master.data[description.key] is None

    observe(master, {"pm_inverter_count": 2})
    assert master.evaluate_computed_sensor(description, master.data, {"pm_inverter_count"})
    assert master.data[description.key] == 10.5


@pytest.mark.asyncio
async def test_count_only_updates_and_stale_inputs_invalidate_the_total() -> None:
    hass = FakeHass()
    coordinator = get_energy_dashboard_coordinator(hass)  # type: ignore[arg-type]
    master = make_inverter("Master", "Master", 4.7, count=2)
    slave = make_inverter("Slave", "Slave", 5.8)
    coordinator.register_hub("Master", master)
    coordinator.register_hub("Slave", slave)
    description = await describe(hass, master, "grid_to_battery_energy")
    master._pending_input_observations = master._computed_input_observations

    assert master.evaluate_computed_sensor(description, master.data, set(master.data))
    assert master.data[description.key] == 10.5
    assert master._computed_input_observations[description.key].deadline <= master._computed_input_observations["pm_inverter_count"].deadline

    # The energy readings have not changed: a topology-only update must still count.
    observe(master, {"pm_inverter_count": 3})
    assert master.evaluate_computed_sensor(description, master.data, {"pm_inverter_count"})
    assert master.data[description.key] is None
    observe(master, {"pm_inverter_count": 2})
    assert master.evaluate_computed_sensor(description, master.data, {"pm_inverter_count"})
    assert master.data[description.key] == 10.5

    observe(master, {"pm_inverter_count": 2}, age=1000)
    assert master.evaluate_computed_sensor(description, master.data, set())
    assert master.data[description.key] is None
    observe(master, {"pm_inverter_count": 2})
    observe(slave, {"e_charge_today": 5.8}, age=1000)
    assert master.evaluate_computed_sensor(description, master.data, set())
    assert master.data[description.key] is None
    observe(slave, {"e_charge_today": 5.8})
    assert master.evaluate_computed_sensor(description, master.data, set())
    assert master.data[description.key] == 10.5


@pytest.mark.asyncio
async def test_disabled_inverter_count_is_polled_as_an_aggregate_dependency() -> None:
    hass = FakeHass()
    coordinator = get_energy_dashboard_coordinator(hass)  # type: ignore[arg-type]
    master = make_inverter("Master", "Master", 4.7)
    coordinator.register_hub("Master", master)
    description = await describe(hass, master, "grid_to_battery_energy")
    master.entity_dependencies = {}
    master.selectEntities = {}
    master.numberEntities = {}
    master.switchEntities = {}
    master.sleepnone = []
    master.sleepzero = []
    master.bad_regs = {"holding": set(), "input": set()}
    master._hass = hass
    entityToListSingle(master, "Energy Dashboard", [], {}, {}, DEVICE, description, None, None)
    count = master.sensorDescriptions["pm_inverter_count"]
    assert not count.entity_registry_enabled_default

    with patch("custom_components.solax_modbus.should_register_be_loaded", side_effect=lambda _hass, _hub, item: item.key == description.key):
        blocks = master.splitInBlocks({count.register: count})

    assert len(blocks) == 1
    assert blocks[0].regs == [count.register]


@pytest_asyncio.fixture
async def publication_hass() -> AsyncGenerator[HomeAssistant]:
    async with async_test_home_assistant() as hass:
        try:
            yield hass
        finally:
            await hass.async_stop(force=True)


@pytest.mark.asyncio
async def test_ha_sees_unavailable_not_a_false_counter_reset(publication_hass: HomeAssistant) -> None:
    hass = FakeHass()
    coordinator = get_energy_dashboard_coordinator(hass)  # type: ignore[arg-type]
    master = make_inverter("Master", "Master", 4.7, count=2)
    slave = make_inverter("Slave", "Slave", 5.8)
    coordinator.register_hub("Master", master)
    description = await describe(hass, master, "grid_to_battery_energy")
    entity = SolaXModbusSensor("test", master, DEVICE, description)
    entity.hass = publication_hass
    entity.entity_id = "sensor.parallel_energy_completeness"
    await entity.async_added_to_hass()
    published = []

    with patch("custom_components.solax_modbus.sensor.async_call_later"):
        for ready in (False, True, False, True):
            if ready:
                coordinator.register_hub("Slave", slave)
            else:
                coordinator.unregister_hub("Slave")
            entity.entity_description = await describe(hass, master, "grid_to_battery_energy")
            assert master.evaluate_computed_sensor(entity.entity_description, master.data, set(master.data))
            entity.modbus_data_updated()
            state = publication_hass.states.get(entity.entity_id)
            assert state is not None
            published.append(state.state)

    assert published == ["unavailable", "10.5", "unavailable", "10.5"]
    await entity.async_will_remove_from_hass()


@pytest.mark.asyncio
async def test_standalone_and_valid_zero_are_unchanged() -> None:
    hass = FakeHass()
    coordinator = get_energy_dashboard_coordinator(hass)  # type: ignore[arg-type]
    master = make_inverter("Master", "Free", 4.7)
    coordinator.register_hub("Master", master)
    source_mapping = next(item for item in master.plugin.ENERGY_DASHBOARD_MAPPING.mappings if item.target_key == "grid_to_battery_energy")
    mapping = EnergyDashboardMapping("solax", [source_mapping], inverter_count_key="pm_inverter_count")
    with patch("custom_components.solax_modbus.energy_dashboard.create_energy_dashboard_device_info", return_value=DEVICE):
        descriptions = await create_energy_dashboard_sensors(master, mapping, hass, {})
    individual = next(item for item in descriptions if item.key == "master_grid_to_battery_energy")
    assert "pm_inverter_count" not in individual.depends_on
    assert master.evaluate_computed_sensor(individual, master.data, set(master.data))
    assert master.data[individual.key] == 4.7

    observe(master, {"parallel_setting": "Master", "pm_inverter_count": 2, "e_charge_today": 0.0})
    slave = make_inverter("Slave", "Slave", 0.0)
    coordinator.hub_data_updated("Master")
    coordinator.register_hub("Slave", slave)
    description = await describe(hass, master, "grid_to_battery_energy")
    assert master.evaluate_computed_sensor(description, master.data, set(master.data))
    assert master.data[description.key] == 0.0
    assert SolaXModbusSensor("test", master, DEVICE, description).available
