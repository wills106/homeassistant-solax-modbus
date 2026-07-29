"""Tests for entity-description loading decisions."""

from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.solax_modbus import should_register_be_loaded
from custom_components.solax_modbus.const import BaseModbusSwitchEntityDescription


def test_descriptor_without_internal_is_loaded_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control descriptions without an internal field must not stop polling."""
    descriptor = BaseModbusSwitchEntityDescription(key="test_switch")
    hub = SimpleNamespace(name="Test hub", _name="Test hub")
    registry = SimpleNamespace(async_get_entity_id=lambda *_args: None)
    fake_hass: Any = object()
    monkeypatch.setattr(
        "custom_components.solax_modbus.er.async_get",
        lambda _hass: registry,
    )

    assert not hasattr(descriptor, "internal")
    assert should_register_be_loaded(fake_hass, hub, descriptor)
