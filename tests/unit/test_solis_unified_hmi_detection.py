"""Regression tests for plugin_solis_unified HMI-based register-map auto-detection.

Covers the auto-detection mechanism derived from the RS485_MODBUS(ESINV-33000ID)
Hybrid Inverter protocol (Ver3.5, section 5.1):
- HMI major/sub version registers 33002 + 33069 (low-order bytes)
- 0xFB00..0xFFFF -> plugin_solis_fb00 register map
- 0x0001..0xFAFF -> plugin_solis register map
- unknown version -> presence probe of 34504 (Remote Dispatch Running Status)
- explicit hmi_map override
Plus parity checks: unified detection must match both legacy plugins, and the
selected entity collections must be identical to the corresponding legacy plugin.
"""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.solax_modbus import plugin_solis, plugin_solis_fb00, plugin_solis_unified
from custom_components.solax_modbus.const import CONF_READ_DCB, CONF_READ_EPS
from custom_components.solax_modbus.plugin_solis_unified import (
    MAP_FB00,
    MAP_LEGACY,
    REG_HMI_MAJOR,
    REG_HMI_SUB,
    REG_MODERN_PROBE,
    compute_hmi_version,
    select_hmi_map,
)
from tests.conftest import MockHub, MockModbusResponse

# Serial prefixes that BOTH legacy plugins recognize on main (103303 is only
# recognized by plugin_solis_fb00 until PR #2457 merges, so it is not parity-safe).
KNOWN_PREFIXES = ["103305", "103306", "133306", "303126", "2051"]


def _serial_registers(prefix: str) -> list[int]:
    serial = prefix.ljust(16, "0")
    return [int.from_bytes(serial[i : i + 2].encode("ascii"), "big") for i in range(0, 16, 2)]


def _configure(
    hub: MockHub,
    prefix: str,
    hmi_major: int | None,
    hmi_sub: int | None,
    probe_ok: bool,
) -> None:
    hub.configure_read(1, 33004, 8, MockModbusResponse(registers=_serial_registers(prefix)))
    if hmi_major is None:
        hub.configure_read(1, REG_HMI_MAJOR, 1, MockModbusResponse(error=True))
    else:
        hub.configure_read(1, REG_HMI_MAJOR, 1, MockModbusResponse(registers=[hmi_major]))
    if hmi_sub is None:
        hub.configure_read(1, REG_HMI_SUB, 1, MockModbusResponse(error=True))
    else:
        hub.configure_read(1, REG_HMI_SUB, 1, MockModbusResponse(registers=[hmi_sub]))
    if probe_ok:
        hub.configure_read(1, REG_MODERN_PROBE, 1, MockModbusResponse(registers=[0]))
    else:
        hub.configure_read(1, REG_MODERN_PROBE, 1, MockModbusResponse(error=True))


# ======================================= pure selection logic ==================================


class TestComputeHmiVersion:
    def test_forms_full_version_from_low_bytes(self) -> None:
        # PDF example: 33002 low byte 0x1C + 33069 low byte 0x06 -> 1C06
        assert compute_hmi_version(0x1C, 0x06) == 0x1C06

    def test_ignores_high_bytes(self) -> None:
        assert compute_hmi_version(0x011C, 0x0206) == 0x1C06

    def test_fb00_boundary(self) -> None:
        assert compute_hmi_version(0xFB, 0x00) == 0xFB00

    def test_missing_major_is_unknown(self) -> None:
        assert compute_hmi_version(None, 0x06) is None
        assert compute_hmi_version(0, 0x06) is None

    def test_missing_sub_defaults_to_zero(self) -> None:
        assert compute_hmi_version(0xFB, None) == 0xFB00


class TestSelectHmiMap:
    @pytest.mark.parametrize("version", [0xFB00, 0xFB05, 0xFBFF, 0xFF00])
    def test_fb00_band_selects_fb00_map(self, version: int) -> None:
        assert select_hmi_map(version, None) == MAP_FB00

    @pytest.mark.parametrize("version", [0x1C06, 0x1905, 0x040B, 0x0001, 0xFAFF])
    def test_older_versions_select_legacy_map(self, version: int) -> None:
        assert select_hmi_map(version, None) == MAP_LEGACY

    def test_probe_rescues_unknown_version(self) -> None:
        assert select_hmi_map(None, True) == MAP_FB00
        assert select_hmi_map(None, False) == MAP_LEGACY

    def test_unknown_version_and_unknown_probe_defaults_legacy(self) -> None:
        assert select_hmi_map(None, None) == MAP_LEGACY


# =================================== detection & map application ===============================


@pytest.mark.parametrize("prefix", KNOWN_PREFIXES)
@pytest.mark.parametrize(
    ("major", "sub", "probe_ok", "expected_map"),
    [
        (0xFB, 0x00, False, MAP_FB00),  # exact FB00 boundary
        (0xFB, 0x05, False, MAP_FB00),  # S6-EH3P(3-12)K-H HMI V1905-style modern unit
        (0x1C, 0x06, True, MAP_LEGACY),  # 1C06 -> legacy map even though probe would respond
        (0x04, 0x0B, False, MAP_LEGACY),  # S6-EH3P(29.9-60)K-H era HMI V040B
        (None, None, True, MAP_FB00),  # version registers silent, modern probe answers
        (None, None, False, MAP_LEGACY),  # nothing known -> conservative legacy
    ],
)
async def test_map_selection_per_hmi_state(prefix, major, sub, probe_ok, expected_map, mock_hub: MockHub) -> None:
    _configure(mock_hub, prefix, major, sub, probe_ok)
    plugin = plugin_solis_unified.plugin_instance.create_hub_instance()

    inverter_type = await plugin.async_determineInverterType(mock_hub, {CONF_READ_EPS: False, CONF_READ_DCB: False})

    assert inverter_type != 0
    assert plugin.hmi_map == expected_map
    expected_sensor_source = plugin_solis_fb00.SENSOR_TYPES if expected_map == MAP_FB00 else plugin_solis.SENSOR_TYPES
    assert [d.key for d in plugin.SENSOR_TYPES] == [d.key for d in expected_sensor_source]
    assert plugin.SENSOR_TYPES is not plugin_solis_unified.plugin_instance.SENSOR_TYPES


async def test_fb00_map_exposes_remote_dispatch_entities(mock_hub: MockHub) -> None:
    """Post-FB00 units must get the 44100-block Remote Dispatch controls from plugin_solis_fb00."""
    _configure(mock_hub, "103305", 0xFB, 0x01, probe_ok=False)
    plugin = plugin_solis_unified.plugin_instance.create_hub_instance()
    await plugin.async_determineInverterType(mock_hub, {})

    keys = {d.key for d in plugin.SENSOR_TYPES} | {d.key for d in plugin.SELECT_TYPES} | {d.key for d in plugin.SWITCH_TYPES}
    assert "remote_dispatch_status" in keys
    assert "dispatch_mode" in keys
    assert "dispatch_master" in keys
    assert {d.key for d in plugin.SENSOR_TYPES} == {d.key for d in plugin_solis_fb00.SENSOR_TYPES}


async def test_legacy_map_exposes_solis_only_entities(mock_hub: MockHub) -> None:
    """Legacy-HMI units must get the plugin_solis entity set, without Remote Dispatch."""
    _configure(mock_hub, "103305", 0x1C, 0x06, probe_ok=True)
    plugin = plugin_solis_unified.plugin_instance.create_hub_instance()
    await plugin.async_determineInverterType(mock_hub, {})

    assert {d.key for d in plugin.SENSOR_TYPES} == {d.key for d in plugin_solis.SENSOR_TYPES}
    assert "remote_dispatch_status" not in {d.key for d in plugin.SENSOR_TYPES}
    assert "special_settings" in {d.key for d in plugin.SENSOR_TYPES}


async def test_hmi_map_override_wins_over_registers(mock_hub: MockHub) -> None:
    """An explicit hmi_map config value must override auto-detection."""
    _configure(mock_hub, "103305", 0xFB, 0x00, probe_ok=True)
    plugin = plugin_solis_unified.plugin_instance.create_hub_instance()
    await plugin.async_determineInverterType(mock_hub, {"hmi_map": MAP_LEGACY})
    assert plugin.hmi_map == MAP_LEGACY
    assert {d.key for d in plugin.SENSOR_TYPES} == {d.key for d in plugin_solis.SENSOR_TYPES}

    _configure(mock_hub, "103305", 0x1C, 0x06, probe_ok=False)
    plugin = plugin_solis_unified.plugin_instance.create_hub_instance()
    await plugin.async_determineInverterType(mock_hub, {"hmi_map": "FB00"})
    assert plugin.hmi_map == MAP_FB00


async def test_unrecognized_serial_skips_hmi_probing(mock_hub: MockHub) -> None:
    """Unknown serial prefixes stay unsupported and no map is applied."""
    _configure(mock_hub, "133307", 0xFB, 0x00, probe_ok=True)
    plugin = plugin_solis_unified.plugin_instance.create_hub_instance()
    inverter_type = await plugin.async_determineInverterType(mock_hub, {})
    assert inverter_type == 0
    assert plugin.hmi_map is None
    # Untouched template collections
    assert [d.key for d in plugin.SENSOR_TYPES] == [d.key for d in plugin_solis.SENSOR_TYPES]


@pytest.mark.parametrize("prefix", KNOWN_PREFIXES)
@pytest.mark.parametrize("read_optional", [False, True])
async def test_detection_parity_with_legacy_plugins(prefix, read_optional, mock_hub: MockHub) -> None:
    """Unified plugin must return exactly the same inverter mask as both legacy plugins."""
    config = {CONF_READ_EPS: read_optional, CONF_READ_DCB: read_optional}

    expected = None
    for legacy in (plugin_solis, plugin_solis_fb00):
        hub = MockHub()
        hub.configure_read(1, 33004, 8, MockModbusResponse(registers=_serial_registers(prefix)))
        plugin = legacy.plugin_instance.create_hub_instance()
        result = await plugin.async_determineInverterType(hub, config)
        if expected is None:
            expected = result
        assert result == expected  # legacy plugins agree with each other

    hub = MockHub()
    _configure(hub, prefix, 0xFB, 0x00, probe_ok=False)
    unified = plugin_solis_unified.plugin_instance.create_hub_instance()
    assert await unified.async_determineInverterType(hub, config) == expected


async def test_serial_read_uses_input_registers_once_per_detection(mock_hub: MockHub) -> None:
    """Detection must read the serial from 33004 (count 8) exactly once, like the legacy plugins."""
    _configure(mock_hub, "103305", 0xFB, 0x00, probe_ok=True)
    plugin = plugin_solis_unified.plugin_instance.create_hub_instance()
    read = AsyncMock(wraps=mock_hub.async_read_input_registers)
    with patch.object(mock_hub, "async_read_input_registers", read):
        await plugin.async_determineInverterType(mock_hub, {})
    serial_reads = [c for c in read.await_args_list if c.kwargs.get("address") == 33004 or c.args[1:2] == (33004,)]
    assert len(serial_reads) == 1
    assert mock_hub.seriesnumber == "103305".ljust(16, "0")


async def test_getsoftwareversion_reports_detected_hmi(mock_hub: MockHub) -> None:
    _configure(mock_hub, "103305", 0x1C, 0x06, probe_ok=False)
    plugin = plugin_solis_unified.plugin_instance.create_hub_instance()
    await plugin.async_determineInverterType(mock_hub, {})
    assert plugin.getSoftwareVersion({}) == "HMI 0x1C06"


async def test_runtime_instances_are_isolated() -> None:
    """Two hubs with different inverters must not share the swapped collections."""
    hub_a = MockHub(name="A")
    _configure(hub_a, "103305", 0xFB, 0x00, probe_ok=False)
    hub_b = MockHub(name="B")
    _configure(hub_b, "103305", 0x1C, 0x06, probe_ok=False)

    plugin_a = plugin_solis_unified.plugin_instance.create_hub_instance()
    plugin_b = plugin_solis_unified.plugin_instance.create_hub_instance()
    await plugin_a.async_determineInverterType(hub_a, {})
    await plugin_b.async_determineInverterType(hub_b, {})

    assert plugin_a.hmi_map == MAP_FB00
    assert plugin_b.hmi_map == MAP_LEGACY
    assert plugin_a.SENSOR_TYPES is not plugin_b.SENSOR_TYPES
    assert "remote_dispatch_status" in {d.key for d in plugin_a.SENSOR_TYPES}
    assert "remote_dispatch_status" not in {d.key for d in plugin_b.SENSOR_TYPES}
    # Template itself must remain the legacy defaults
    assert [d.key for d in plugin_solis_unified.plugin_instance.SENSOR_TYPES] == [d.key for d in plugin_solis.SENSOR_TYPES]
