import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.helpers.device_registry import DeviceInfo

from custom_components.solax_modbus.const import (
    CONF_ENERGY_DASHBOARD_DEVICE,
    CONF_PLUGIN,
    DOMAIN,
    BaseModbusSensorEntityDescription,
)
from custom_components.solax_modbus.energy_dashboard import (
    EnergyDashboardCoordinator,
    should_create_energy_dashboard_device,
)
from custom_components.solax_modbus.sensor import SolaXModbusSensor


@dataclass
class FakeHass:
    data: dict[str, Any] = field(default_factory=dict)
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)

    def async_create_task(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task


def make_hub(
    entry_id: str,
    name: str,
    role: str | None,
    *,
    plugin: str = "solax",
    inverter_count: int | None = None,
) -> Any:
    data: dict[str, Any] = {}
    if role is not None:
        data["parallel_setting"] = role
    if inverter_count is not None:
        data["pm_inverter_count"] = inverter_count
    return SimpleNamespace(
        _name=name,
        config={CONF_PLUGIN: plugin},
        data=data,
        datadict=data,
        entry=SimpleNamespace(entry_id=entry_id),
    )


def test_slave_topology_uses_entry_ids_and_plugin_family() -> None:
    hass = FakeHass()
    coordinator = EnergyDashboardCoordinator(hass)  # type: ignore[arg-type]
    master = make_hub("master-entry", "Shared name", "Master")
    slave = make_hub("slave-entry", "Shared name", "Slave")
    other_plugin_slave = make_hub("other-entry", "Other", "Slave", plugin="growatt")

    coordinator.register_hub("master-entry", master)
    coordinator.register_hub("slave-entry", slave)
    coordinator.register_hub("other-entry", other_plugin_slave)

    assert coordinator.slave_hubs_for(master) == [("Shared name", slave)]


@pytest.mark.asyncio
async def test_topology_changes_refresh_master_without_startup_delay() -> None:
    hass = FakeHass()
    coordinator = EnergyDashboardCoordinator(hass)  # type: ignore[arg-type]
    master = make_hub("master-entry", "Primary", "Master", inverter_count=1)
    slave = make_hub("slave-entry", "Secondary", "Free")
    coordinator.register_hub("master-entry", master)
    coordinator.register_hub("slave-entry", slave)

    refresh_count = 0

    async def refresh() -> None:
        nonlocal refresh_count
        refresh_count += 1

    coordinator.register_refresh_callback("master-entry", refresh)
    slave.data["parallel_setting"] = "Slave"
    coordinator.hub_data_updated("slave-entry")
    await hass.tasks[-1]

    assert refresh_count == 1
    assert coordinator.slave_hubs_for(master) == [("Secondary", slave)]

    coordinator.unregister_hub("slave-entry")
    await hass.tasks[-1]

    assert refresh_count == 2
    assert coordinator.slave_hubs_for(master) == []


@pytest.mark.asyncio
async def test_refresh_requests_are_coalesced() -> None:
    hass = FakeHass()
    coordinator = EnergyDashboardCoordinator(hass)  # type: ignore[arg-type]
    hub = make_hub("entry", "Primary", "Master")
    coordinator.register_hub("entry", hub)
    refresh_count = 0

    async def refresh() -> None:
        nonlocal refresh_count
        refresh_count += 1

    coordinator.register_refresh_callback("entry", refresh)
    coordinator.request_refresh("entry")
    coordinator.request_refresh("entry")
    coordinator.request_refresh("entry")
    await hass.tasks[-1]

    assert refresh_count == 1


@pytest.mark.asyncio
async def test_dashboard_creation_uses_published_role_without_polling() -> None:
    hub = make_hub("entry", "Secondary", "Slave")
    hub.groups = {"must_not_be_read": object()}

    assert (
        await should_create_energy_dashboard_device(
            hub,
            {CONF_ENERGY_DASHBOARD_DEVICE: True},
        )
        is False
    )

    hub.data.clear()
    assert (
        await should_create_energy_dashboard_device(
            hub,
            {CONF_ENERGY_DASHBOARD_DEVICE: True},
        )
        is True
    )


def test_dashboard_entity_can_be_deactivated_without_changing_identity() -> None:
    description = BaseModbusSensorEntityDescription(
        key="energy_dashboard_test",
        name="Test",
        register=-1,
        value_function=lambda _init, _description, data: data.get("source"),
    )
    hub = SimpleNamespace(data={}, sensorEntities={}, sensorDescriptions={}, computedSensors={})
    sensor = SolaXModbusSensor(
        "Energy Dashboard",
        hub,
        DeviceInfo(identifiers={(DOMAIN, "energy-dashboard-test")}),
        description,
    )
    unique_id = sensor.unique_id

    sensor.set_energy_dashboard_active(False)
    assert sensor.available is False
    assert sensor.unique_id == unique_id

    sensor.set_energy_dashboard_active(True)
    assert sensor.available is True


@pytest.mark.asyncio
async def test_inactive_dashboard_entity_stays_out_of_computed_pipeline() -> None:
    description = BaseModbusSensorEntityDescription(
        key="energy_dashboard_test",
        name="Test",
        register=-1,
        value_function=lambda _init, _description, data: data.get("source"),
    )
    hub = SimpleNamespace(data={}, sensorEntities={}, sensorDescriptions={}, computedSensors={})
    sensor = SolaXModbusSensor(
        "Energy Dashboard",
        hub,
        DeviceInfo(identifiers={(DOMAIN, "energy-dashboard-test")}),
        description,
    )

    sensor.set_energy_dashboard_active(False)
    await sensor.async_added_to_hass()

    assert description.key in hub.sensorEntities
    assert description.key not in hub.computedSensors
