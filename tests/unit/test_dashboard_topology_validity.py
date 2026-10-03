"""Dashboard source selection requires a known topology and its actual source."""

from typing import Any

import pytest

from custom_components.solax_modbus import BlockReadResult

from .test_dashboard_poll_intervals import setup_poll
from .test_poll_snapshot import successful_block


def omit_parallel_power(hub: Any, power: Any) -> None:
    """Model Free mode, where the PM group has never been read."""
    hub.data.pop("pm_power", None)
    for group in power.device_groups.values():
        for block in group.holdingBlocks:
            block.descriptions = {key: descr for key, descr in block.descriptions.items() if descr.key != "pm_power"}


@pytest.mark.asyncio
async def test_master_requires_first_parallel_power_read() -> None:
    hub, ed, power, settings = setup_poll()
    omit_parallel_power(hub, power)
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    assert hub.data[ed.key] == 191

    hub.data["parallel_setting"] = "Master"
    await hub._refresh_interval_group_once(settings)

    assert "pm_power" not in hub.data
    assert hub.data[ed.key] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("topology", ["Unknown", "", None, False, 0])
async def test_unknown_topology_cannot_select_single_inverter_power(topology: Any) -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)

    hub.data["parallel_setting"] = topology
    await hub._refresh_interval_group_once(settings)

    assert hub.data[ed.key] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("topology", "expected"), [("Free", 191), ("Slave", 191), ("Master", 400)])
async def test_known_topology_selects_accepted_source(topology: str, expected: int) -> None:
    hub, ed, power, settings = setup_poll()
    hub.data["parallel_setting"] = topology
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)

    assert hub.data[ed.key] == expected


@pytest.mark.asyncio
async def test_model_without_topology_input_defaults_to_free() -> None:
    hub, ed, power, _settings = setup_poll()
    hub.sensorDescriptions.pop("parallel_setting")
    hub.data.pop("parallel_setting")

    async def read(data: dict[str, Any], block: Any, typ: str) -> BlockReadResult:
        values = {"inverter_power": 250, "measured_power": 59, "pm_power": 400}
        data.update(values)
        return successful_block(*values)

    hub.async_read_modbus_block = read
    await hub._refresh_interval_group_once(power)

    assert hub.data[ed.key] == 191
    sample = hub._dashboard_source_sample(ed._energy_dashboard_mapping, {}, set(), require_source_sample=True)
    assert sample is not None and sample[1]["house_load"] == 191


@pytest.mark.asyncio
async def test_integral_cannot_use_main_power_before_first_parallel_read() -> None:
    hub, ed, power, settings = setup_poll()
    omit_parallel_power(hub, power)
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    mapping = ed._energy_dashboard_mapping
    assert hub._dashboard_source_sample(mapping, {}, set(), require_source_sample=True) is not None

    hub.data["parallel_setting"] = "Master"
    await hub._refresh_interval_group_once(settings)

    assert hub._dashboard_source_sample(mapping, {}, set(), require_source_sample=True) is None


@pytest.mark.asyncio
async def test_integral_cannot_use_power_with_unknown_topology() -> None:
    hub, ed, power, settings = setup_poll()
    await hub._refresh_interval_group_once(settings)
    await hub._refresh_interval_group_once(power)
    hub.data["parallel_setting"] = "Unknown"
    await hub._refresh_interval_group_once(settings)

    assert hub._dashboard_source_sample(ed._energy_dashboard_mapping, {}, set(), require_source_sample=True) is None
