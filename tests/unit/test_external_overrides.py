"""External source overrides: selection, unit conversion and freshness behaviour (PR #2421)."""

import asyncio
import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import CONF_SCAN_INTERVAL, STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfPower
from homeassistant.core import State
from homeassistant.helpers.device_registry import DeviceInfo

from custom_components.solax_modbus import InputObservation, SolaXModbusHub
from custom_components.solax_modbus.const import WRITE_DATA_LOCAL, BaseModbusSelectEntityDescription, descriptor_optional_depends
from custom_components.solax_modbus.select import SolaXModbusExternalSourceSelect


def make_hub(states: dict[str, State] | None = None, *, sources: dict[str, Any] | None = None) -> Any:
    """Build the minimal hub state required by external override tests."""
    hub = cast(Any, object.__new__(SolaXModbusHub))
    hub._name = "test"
    hub.data = {"_repeatUntil": {}}
    hub.computedSensors = {}
    hub.computedEntities = {}
    hub.sensorDescriptions = {}
    hub.sensorEntities = {}
    hub.writeLocals = {}
    hub.writequeue = {}
    hub.localsUpdated = False
    hub.localsLoaded = True
    hub.config = {CONF_SCAN_INTERVAL: 15}
    hub._modbus_addr = 1
    hub._external_sources = dict(sources or {"house_load": UnitOfPower.WATT})
    hub._computed_input_observations = {}
    hub._pending_input_observations = None
    hub._hass = Mock()
    hub._hass.states.get = lambda entity_id: (states or {}).get(entity_id)
    hub.plugin = SimpleNamespace(
        isAwake=Mock(return_value=True),
        localDataCallback=Mock(return_value=True),
        default_input_scangroup=CONF_SCAN_INTERVAL,
        EXTERNAL_SOURCE_TYPES=hub._external_sources,
        SELECT_TYPES=(),
    )
    hub._poll_data_lock = asyncio.Lock()
    hub._autorepeat_lock = asyncio.Lock()
    hub.slowdown = 1
    return hub


def power_state(entity_id: str, value: str, unit: str | None = UnitOfPower.WATT, device_class: str | None = "power") -> State:
    attributes = {"device_class": device_class} if device_class else {}
    if unit is not None:
        attributes["unit_of_measurement"] = unit
    return State(entity_id, value, attributes)


def test_no_selection_removes_previous_injection() -> None:
    hub = make_hub()
    hub.data["external_house_load_source"] = ""
    datadict: dict[str, Any] = {"external_house_load": 1234.0}
    injected = hub.apply_external_overrides(datadict)
    assert injected == set()
    assert "external_house_load" not in datadict


def test_unset_source_initialisation_is_tolerated() -> None:
    """Fresh installs hold initvalue=None until the first write."""
    hub = make_hub()
    hub.data["external_house_load_source"] = None
    datadict: dict[str, Any] = {}
    hub.apply_external_overrides(datadict)
    assert "external_house_load" not in datadict


def test_selected_watt_sensor_is_injected_and_observed() -> None:
    hub = make_hub({"sensor.shelly_load": power_state("sensor.shelly_load", "2050.5")})
    hub.data["external_house_load_source"] = "sensor.shelly_load"
    datadict: dict[str, Any] = {}
    injected = hub.apply_external_overrides(datadict, 5)
    assert injected == {"external_house_load"}
    assert datadict["external_house_load"] == 2050.5
    observation = hub._computed_input_observations["external_house_load"]
    assert isinstance(observation, InputObservation)
    assert observation.value == 2050.5
    # Lease covers one missed cycle: 2 * max(interval, configured scan interval)
    assert observation.deadline > time.monotonic() + 9
    assert observation.deadline < time.monotonic() + 11


def test_kw_sensor_is_converted_to_declared_unit() -> None:
    hub = make_hub({"sensor.shelly_load": power_state("sensor.shelly_load", "2.5", UnitOfPower.KILO_WATT)})
    hub.data["external_house_load_source"] = "sensor.shelly_load"
    datadict: dict[str, Any] = {}
    hub.apply_external_overrides(datadict)
    assert datadict["external_house_load"] == 2500.0


@pytest.mark.parametrize("state", [STATE_UNAVAILABLE, STATE_UNKNOWN, "not-a-number"])
def test_bad_or_missing_external_state_fails_open(state: str) -> None:
    hub = make_hub({"sensor.shelly_load": power_state("sensor.shelly_load", state, device_class=None)})
    hub.data["external_house_load_source"] = "sensor.shelly_load"
    datadict: dict[str, Any] = {"external_house_load": 999.0}
    hub.apply_external_overrides(datadict)
    assert "external_house_load" not in datadict


def test_missing_entity_fails_open() -> None:
    hub = make_hub({})
    hub.data["external_house_load_source"] = "sensor.gone_away"
    datadict: dict[str, Any] = {"external_house_load": 999.0}
    hub.apply_external_overrides(datadict)
    assert "external_house_load" not in datadict


def test_injection_repeats_every_cycle_and_replaces_stale_observation() -> None:
    hub = make_hub({"sensor.shelly_load": power_state("sensor.shelly_load", "1000")})
    hub.data["external_house_load_source"] = "sensor.shelly_load"
    datadict: dict[str, Any] = {}
    hub.apply_external_overrides(datadict)
    first = hub._computed_input_observations["external_house_load"]
    hub._hass.states.get = lambda entity_id: power_state("sensor.shelly_load", "1500")
    hub.apply_external_overrides(datadict)
    second = hub._computed_input_observations["external_house_load"]
    assert datadict["external_house_load"] == 1500.0
    assert second.deadline >= first.deadline


@pytest.mark.asyncio
async def test_house_load_prefers_external_measurement() -> None:
    """house_load must use this cycle's injected external value, not the calculated fallback."""
    hub = make_hub({"sensor.shelly_load": power_state("sensor.shelly_load", "2750")})
    hub.data["external_house_load_source"] = "sensor.shelly_load"
    hub._external_sources = {"house_load": UnitOfPower.WATT}
    hub.data.update({"inverter_power": 4000, "measured_power": -1000})
    hub.computedSensors = {}

    from custom_components.solax_modbus.plugin_solax import SENSOR_TYPES_MAIN

    house_load = next(d for d in SENSOR_TYPES_MAIN if d.key == "house_load")
    hub.computedSensors = {"house_load": house_load}
    hub._ordered_computed_sensors = Mock(return_value=[("house_load", house_load)])
    hub._publish_computed_sensors = Mock()

    injected = hub.apply_external_overrides(hub.data, 5)
    assert injected == {"external_house_load"}
    fresh: set[str] = set(injected) | {"inverter_power", "measured_power"}
    assert hub._compute_poll_sensors(hub.data, fresh) == {"house_load"}
    assert hub.data["house_load"] == 2750.0


def test_house_load_falls_back_to_calculation_without_external() -> None:
    from custom_components.solax_modbus.plugin_solax import SENSOR_TYPES_MAIN

    hub = make_hub({})
    hub.data["external_house_load_source"] = ""
    hub.data.update({"inverter_power": 4000, "measured_power": -1000})
    hub.computedSensors = {}
    house_load = next(d for d in SENSOR_TYPES_MAIN if d.key == "house_load")
    hub.computedSensors = {"house_load": house_load}
    hub._ordered_computed_sensors = Mock(return_value=[("house_load", house_load)])

    hub.apply_external_overrides(hub.data)
    assert "external_house_load" not in hub.data
    assert hub._compute_poll_sensors(hub.data, {"inverter_power", "measured_power"}) == {"house_load"}
    assert hub.data["house_load"] == 5000


def test_register_external_sources_warns_on_declaration_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    hub = make_hub()
    hub.plugin.SELECT_TYPES = ()
    hub.register_external_sources()
    assert "no select entity 'external_house_load_source' is declared" in caplog.text

    hub.plugin.SELECT_TYPES = (SimpleNamespace(key="external_mystery_source"),)
    caplog.clear()
    hub.register_external_sources()
    assert "external_mystery_source" in caplog.text
    assert "no matching EXTERNAL_SOURCE_TYPES" in caplog.text


def test_register_external_sources_accepts_matching_declaration(caplog: pytest.LogCaptureFixture) -> None:
    hub = make_hub()
    hub.plugin.SELECT_TYPES = (SimpleNamespace(key="external_house_load_source"),)
    hub.register_external_sources()
    assert "EXTERNAL_SOURCE_TYPES" not in caplog.text


def make_select(hub: Any, *, device_class: SensorDeviceClass | None = SensorDeviceClass.POWER) -> Any:
    descr = BaseModbusSelectEntityDescription(
        key="external_house_load_source",
        name="External House Load Source",
        write_method=WRITE_DATA_LOCAL,
        initvalue=None,
        dynamic_options=True,
        dynamic_device_class=device_class,
        option_dict=None,
    )
    return SolaXModbusExternalSourceSelect("test", hub, 1, DeviceInfo(identifiers={("solax_modbus", "test")}), descr)


def test_current_option_never_reports_none() -> None:
    hub = make_hub()
    select = make_select(hub)
    # Fresh install: initvalue None stored in hub.data must not produce a "None" state
    hub.data["external_house_load_source"] = None
    assert select.current_option == SolaXModbusExternalSourceSelect._NO_SOURCE_LABEL
    # Explicit "no source" selection
    hub.data["external_house_load_source"] = ""
    assert select.current_option == SolaXModbusExternalSourceSelect._NO_SOURCE_LABEL
    hub.data["external_house_load_source"] = "sensor.shelly_load"
    assert select.current_option == "sensor.shelly_load"


def test_current_option_label_is_member_of_options(monkeypatch: pytest.MonkeyPatch) -> None:
    import homeassistant.helpers.entity_registry as er

    hub = make_hub()
    select = make_select(hub)
    registry = Mock()
    registry.entities.values.return_value = []
    monkeypatch.setattr(er, "async_get", lambda hass: registry)
    select.hass = Mock()
    hub.data["external_house_load_source"] = None
    assert select.current_option in select.options


# --------------------------------------------------------------------------------------
# Latency behaviour: identical measurements must not re-trigger the control loop, and an
# external-only change must be able to recompute house_load on its own (PR #2421 review).
# --------------------------------------------------------------------------------------


def test_external_house_load_declared_as_optional_dependency() -> None:
    """house_load must recompute when only the external measurement changes."""
    from custom_components.solax_modbus.plugin_solax import SENSOR_TYPES_MAIN

    for key in ("house_load", "house_load_alt"):
        descr = next(d for d in SENSOR_TYPES_MAIN if d.key == key)
        descr_deps = descriptor_optional_depends(descr) or []
        assert "external_house_load" in descr_deps, key


def _house_load_hub(states: dict[str, State]) -> Any:
    """Hub with the real SolaX house_load description and accepted polled inputs."""
    from custom_components.solax_modbus.plugin_solax import SENSOR_TYPES_MAIN

    hub = make_hub(states)
    hub.data["external_house_load_source"] = "sensor.shelly_load"
    hub.data.update({"inverter_power": 4000, "measured_power": -1000})
    house_load = next(d for d in SENSOR_TYPES_MAIN if d.key == "house_load")
    hub.computedSensors = {"house_load": house_load}
    hub._ordered_computed_sensors = Mock(return_value=[("house_load", house_load)])
    hub._publish_computed_sensors = Mock()
    now = time.monotonic()
    hub._computed_input_observations = {key: InputObservation(now, hub.data[key], now + 120) for key in ("inverter_power", "measured_power")}
    return hub
