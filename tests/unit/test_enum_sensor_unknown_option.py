"""Regression coverage for unmapped values on enum sensors."""

from types import SimpleNamespace

from homeassistant.helpers.device_registry import DeviceInfo

from custom_components.solax_modbus.const import DOMAIN, BaseModbusSensorEntityDescription
from custom_components.solax_modbus.sensor import SolaXModbusSensor


def test_unmapped_enum_value_is_in_declared_options() -> None:
    """Unknown is a possible published state for every dictionary-scaled enum."""
    description = BaseModbusSensorEntityDescription(
        key="enum_setting",
        name="Enum setting",
        scale={0: "Off", 1: "On"},
    )
    hub = SimpleNamespace(data={"enum_setting": "Unknown"})
    sensor = SolaXModbusSensor(
        "test",
        hub,
        DeviceInfo(identifiers={(DOMAIN, "test")}),
        description,
    )

    assert sensor.native_value == "Unknown"
    assert sensor.options == ["Off", "On", "Unknown"]


def test_unknown_option_is_not_duplicated_when_declared() -> None:
    """A sensor with an explicit Unknown mapping keeps a unique option list."""
    description = BaseModbusSensorEntityDescription(
        key="enum_setting",
        name="Enum setting",
        scale={0: "Off", 1: "Unknown"},
    )
    hub = SimpleNamespace(data={"enum_setting": "Unknown"})
    sensor = SolaXModbusSensor(
        "test",
        hub,
        DeviceInfo(identifiers={(DOMAIN, "test")}),
        description,
    )

    assert sensor.options == ["Off", "Unknown"]
