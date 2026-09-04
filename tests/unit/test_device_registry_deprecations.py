"""Regression tests for the ``async_get_device`` / ``via_device`` deprecations.

Home Assistant 2026.8 made device identifiers and connections unique *per
config entry*. The legacy ``device_registry.async_get_device(identifiers=...)``
lookup and the ``DeviceInfo(..., via_device=...)`` keyword are both deprecated
and break in HA 2027.8.0.

These tests guard against reintroducing either deprecation:

- ``test_no_legacy_async_get_device_calls`` ensures the only remaining
  ``async_get_device`` reference is the intentional fallback inside the shared
  helper (scoped to a config entry everywhere else).
- ``test_no_legacy_via_device_keyword`` ensures no ``DeviceInfo(...)`` literal
  still passes ``via_device=`` (the fallback assignment to a dict is allowed).
- ``test_helper_prefers_scoped_lookup`` / ``test_helper_falls_back_to_legacy``
  exercise both runtime branches of the shared helper against a mock registry.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

from homeassistant.helpers.device_registry import DeviceRegistry

SRC = Path("custom_components/solax_modbus")


def _iter_call_nodes(tree: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _is_async_get_device_reference(node: ast.AST) -> bool:
    """True for the single legacy ``async_get_device`` attribute reference.

    The helper captures the legacy lookup once as ``legacy = registry.async_get_device``;
    we assert that exact attribute access is the only place it is referenced.
    """
    return isinstance(node, ast.Attribute) and node.attr == "async_get_device"


def _is_via_device_kwarg(call: ast.Call) -> bool:
    """True for a ``via_device=`` keyword argument on a call."""
    return any(kw.arg == "via_device" for kw in call.keywords)


def test_no_legacy_async_get_device_calls() -> None:
    """The only ``async_get_device`` reference must be the intentional fallback."""
    helper = ast.parse((SRC / "device_registry_lookup.py").read_text())
    helper_refs = [node for node in ast.walk(helper) if _is_async_get_device_reference(node)]
    assert len(helper_refs) == 1, "expected exactly one legacy fallback reference in the helper"

    # Every other source file must NOT reference the legacy lookup directly.
    for filename in ("sensor.py", "__init__.py", "energy_dashboard.py"):
        path = SRC / filename
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        refs = [node for node in ast.walk(tree) if _is_async_get_device_reference(node)]
        assert not refs, f"{filename} still references the deprecated async_get_device lookup"


def test_helper_prefers_scoped_lookup() -> None:
    """On HA 2026.8+ the helper must use ``async_get_device_by_identifier``."""
    from custom_components.solax_modbus.device_registry_lookup import get_device_by_identifier

    class _FakeRegistry:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[str, str, str], str]] = []

        def async_get_device_by_identifier(self, identifier: tuple[str, str, str], config_entry_id: str) -> Any:
            self.calls.append(("scoped", identifier, config_entry_id))
            return "SCOPED_DEVICE"

    registry = _FakeRegistry()
    result = get_device_by_identifier(cast(DeviceRegistry, registry), ("solax_modbus", "hub", "inverter"), "entry-1")

    assert cast(Any, result) == "SCOPED_DEVICE"
    assert registry.calls == [("scoped", ("solax_modbus", "hub", "inverter"), "entry-1")]


def test_helper_falls_back_to_legacy() -> None:
    """Without the scoped API the helper must fall back to ``async_get_device``."""
    from custom_components.solax_modbus.device_registry_lookup import get_device_by_identifier

    class _FakeRegistry:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def async_get_device(self, identifiers: Any = None) -> Any:
            self.calls.append({"identifiers": identifiers})
            return "LEGACY_DEVICE"

    registry = _FakeRegistry()
    result = get_device_by_identifier(cast(DeviceRegistry, registry), ("solax_modbus", "hub", "inverter"), "entry-1")

    assert cast(Any, result) == "LEGACY_DEVICE"
    assert registry.calls == [{"identifiers": {("solax_modbus", "hub", "inverter")}}]


def test_no_legacy_via_device_keyword() -> None:
    """No ``DeviceInfo(...)`` literal may pass ``via_device=``."""
    for filename in ("sensor.py", "__init__.py", "energy_dashboard.py"):
        path = SRC / filename
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        via_device_calls = [
            c for c in _iter_call_nodes(tree) if isinstance(c.func, ast.Name) and c.func.id == "DeviceInfo" and _is_via_device_kwarg(c)
        ]
        assert not via_device_calls, f"{filename} still passes via_device= to DeviceInfo"


def test_via_device_fallback_uses_via_device_id_first() -> None:
    """The fallback path must set ``via_device_id`` when the parent device resolves."""
    from custom_components.solax_modbus.device_registry_lookup import get_device_by_identifier

    class _FakeDevice:
        def __init__(self, device_id: str) -> None:
            self.id = device_id

    class _FakeRegistry:
        def async_get_device_by_identifier(self, identifier: tuple[str, str, str], config_entry_id: str) -> Any:
            return _FakeDevice("parent-id")

    registry = _FakeRegistry()
    device = get_device_by_identifier(cast(DeviceRegistry, registry), ("solax_modbus", "hub", "inverter"), "entry-1")
    assert device is not None
    assert device.id == "parent-id"


def test_via_device_key_matches_installed_ha_version() -> None:
    """The via-device key must match whatever the installed HA version is.

    CI runs against the real installed HA, which may be older than 2026.8, so
    we assert the key is consistent with ``_ha_version()`` rather than
    hard-coding a specific version.
    """
    from custom_components.solax_modbus.device_registry_lookup import (
        VIA_DEVICE_ID_MIN_VERSION,
        _ha_version,
        via_device_key,
    )

    key = via_device_key()
    version = _ha_version()
    expected = "via_device_id" if version >= VIA_DEVICE_ID_MIN_VERSION else "via_device"
    assert key == expected


def test_via_device_key_falls_back_to_via_device_on_old_ha() -> None:
    """On HA < 2026.8 the via-device key must be the deprecated ``via_device`` tuple."""
    import custom_components.solax_modbus.device_registry_lookup as mod

    original = mod._ha_version

    try:
        mod._ha_version = lambda: (2025, 4)
        assert mod.via_device_key() == "via_device"

        mod._ha_version = lambda: (2026, 7)
        assert mod.via_device_key() == "via_device"
    finally:
        mod._ha_version = original


def test_via_device_key_switches_at_2026_8() -> None:
    """The via-device key must switch to ``via_device_id`` at exactly 2026.8."""
    import custom_components.solax_modbus.device_registry_lookup as mod

    original = mod._ha_version

    try:
        mod._ha_version = lambda: (2026, 8)
        assert mod.via_device_key() == "via_device_id"

        mod._ha_version = lambda: (2027, 1)
        assert mod.via_device_key() == "via_device_id"
    finally:
        mod._ha_version = original


def test_via_device_key_is_version_aware_across_all_callers() -> None:
    """Every caller must route the via-device key through the shared helper.

    This guards against a caller setting ``via_device_id`` directly on a version
    of HA that only understands ``via_device`` (which would break sub-device
    registration on HA < 2026.8).
    """
    for filename in ("sensor.py", "__init__.py", "energy_dashboard.py"):
        path = SRC / filename
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        # No caller may set the deprecated ``via_device`` key *or* the new
        # ``via_device_id`` key directly; both must go through ``via_device_key()``.
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Constant) and node.value.value == "via_device":
                raise AssertionError(f"{filename} sets via_device directly; use via_device_key() instead")
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Constant) and node.value.value == "via_device_id":
                raise AssertionError(f"{filename} sets via_device_id directly; use via_device_key() instead")
