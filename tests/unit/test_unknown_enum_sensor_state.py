"""Unknown register codes must publish HA's unknown state, not an invalid enum."""

from typing import Any, cast

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.device_registry import DeviceInfo
from pytest_homeassistant_custom_component.common import async_test_home_assistant

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.const import DOMAIN, REGISTER_U16, BaseModbusSensorEntityDescription
from custom_components.solax_modbus.plugin_growatt import GEN3, SENSOR_TYPES, plugin_instance
from custom_components.solax_modbus.sensor import SolaXModbusSensor


def _make_hub() -> Any:
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "test"
    hub.plugin = plugin_instance
    hub.data = {}
    hub.cyclecount = 1
    hub._validate_register_func = None
    hub.tmpdata_expiry = {}
    hub.localsLoaded = True
    return hub


@pytest.mark.asyncio
@pytest.mark.parametrize(("key", "register"), [("priority", 118), ("run_mode", 1000)])
@pytest.mark.parametrize("unknown_code", [10, 65535])
async def test_growatt_unknown_enum_publishes_and_recovers(key: str, register: int, unknown_code: int) -> None:
    """Exercise decoding and real HA publication for both sensors from #2380."""
    description = next(item for item in SENSOR_TYPES if item.key == key and item.register == register and item.allowedtypes & GEN3)
    scale = description.scale
    assert isinstance(scale, dict)
    hub = _make_hub()
    sensor = SolaXModbusSensor("test", hub, DeviceInfo(identifiers={(DOMAIN, "test")}), description)
    sensor.entity_id = f"sensor.test_{key}"
    assert sensor.device_class == SensorDeviceClass.ENUM

    async with async_test_home_assistant() as hass:
        try:
            sensor.hass = hass
            # All declared values remain valid, including after an unknown value.
            for raw_value, expected in scale.items():
                assert hub.treat_address(hub.data, [raw_value], 0, description) == 1
                sensor.modbus_data_updated()
                assert hass.states.is_state(sensor.entity_id, expected)

                assert hub.treat_address(hub.data, [unknown_code], 0, description) == 1
                sensor.modbus_data_updated()
                assert sensor.native_value is None
                assert hass.states.is_state(sensor.entity_id, "unknown")

            hub.treat_address(hub.data, [0], 0, description)
            sensor.modbus_data_updated()
            assert hass.states.is_state(sensor.entity_id, scale[0])
        finally:
            await hass.async_stop(force=True)


@pytest.mark.parametrize(
    ("scale", "raw_value", "expected"),
    [
        ({0: "Off", 1: "On"}, 0, "Off"),
        ({0: "Off", 1: "On"}, 2, None),
        ({0: "Unknown", 1: "On"}, 0, "Unknown"),
        ({0: 230, 1: 240}, 0, 230),
        ({0: 230, 1: 240}, 2, None),
    ],
)
def test_dictionary_scaling_preserves_declared_values(scale: dict[int, Any], raw_value: int, expected: Any) -> None:
    """Only missing codes change; explicitly mapped and numeric values are kept."""
    hub = _make_hub()
    description = BaseModbusSensorEntityDescription(key="status", register=1, register_data_type=REGISTER_U16, scale=scale)
    hub.treat_address(hub.data, [raw_value], 0, description)
    assert hub.data["status"] == expected

    # This explicit label is valid when it is actually declared as an option.
    if expected == "Unknown":
        sensor = SolaXModbusSensor("test", hub, DeviceInfo(identifiers={(DOMAIN, "test")}), description)
        assert sensor.state == "Unknown"
