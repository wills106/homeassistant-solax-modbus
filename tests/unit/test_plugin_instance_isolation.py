"""Tests for per-hub plugin runtime state."""

from dataclasses import replace
from types import ModuleType, SimpleNamespace
from typing import Any, cast

from homeassistant.const import CONF_NAME

from custom_components.solax_modbus import SolaXModbusHub
from custom_components.solax_modbus.const import CONF_INTERFACE, plugin_base
from custom_components.solax_modbus.plugin_sofar import battery_config as SofarBatteryConfig
from custom_components.solax_modbus.plugin_sofar import plugin_instance as sofar_template
from custom_components.solax_modbus.plugin_solinteg import plugin_instance as solinteg_template


def make_hub(plugin_template: plugin_base, name: str) -> SolaXModbusHub:
    """Create a hub without opening a real transport."""
    plugin_module = cast(ModuleType, SimpleNamespace(plugin_instance=plugin_template))
    entry = SimpleNamespace(options={CONF_NAME: name, CONF_INTERFACE: "test"})
    hass = SimpleNamespace()
    return SolaXModbusHub(cast(Any, hass), plugin_module, cast(Any, entry))


def test_hubs_get_independent_plugin_instances() -> None:
    """Each hub must receive its own plugin runtime object."""
    first = make_hub(sofar_template, "Sofar 1")
    second = make_hub(sofar_template, "Sofar 2")

    assert first.plugin is not second.plugin
    assert first.plugin is not sofar_template
    assert second.plugin is not sofar_template

    first.plugin.inverter_model = "First model"

    assert second.plugin.inverter_model is None
    assert sofar_template.inverter_model is None


def test_sofar_battery_runtime_state_is_isolated_per_hub() -> None:
    """Battery discovery state from one Sofar hub must not leak to another."""
    first = make_hub(sofar_template, "Sofar 1")
    second = make_hub(sofar_template, "Sofar 2")
    first_battery_base = first.plugin.BATTERY_CONFIG
    second_battery_base = second.plugin.BATTERY_CONFIG
    template_battery_base = sofar_template.BATTERY_CONFIG

    assert first_battery_base is not None
    assert second_battery_base is not None
    assert template_battery_base is not None
    first_battery = cast(SofarBatteryConfig, first_battery_base)
    second_battery = cast(SofarBatteryConfig, second_battery_base)
    template_battery = cast(SofarBatteryConfig, template_battery_base)
    assert first_battery is not second_battery
    assert first_battery is not template_battery

    first_battery.number_strings = 2
    first_battery.number_cels_in_parallel = 3
    first_battery.selected_batt_nr = 1
    first_battery.selected_batt_pack_nr = 2
    first_battery.batt_pack_serials[1] = {2: "SOFAR-PACK-1"}

    assert second_battery.number_strings is None
    assert second_battery.number_cels_in_parallel is None
    assert second_battery.selected_batt_nr is None
    assert second_battery.selected_batt_pack_nr is None
    assert second_battery.batt_pack_serials == {}
    assert template_battery.batt_pack_serials == {}


def test_solinteg_runtime_descriptions_are_isolated_per_hub() -> None:
    """MPPT-specific description changes must stay local to one Solinteg hub."""
    first = make_hub(solinteg_template, "Solinteg 1")
    second = make_hub(solinteg_template, "Solinteg 2")
    first_index = next(index for index, description in enumerate(first.plugin.SELECT_TYPES) if description.key == "shadow_scan")
    second_index = next(index for index, description in enumerate(second.plugin.SELECT_TYPES) if description.key == "shadow_scan")
    template_index = next(index for index, description in enumerate(solinteg_template.SELECT_TYPES) if description.key == "shadow_scan")
    second_description = second.plugin.SELECT_TYPES[second_index]
    template_description = solinteg_template.SELECT_TYPES[template_index]

    first.plugin.SELECT_TYPES[first_index] = replace(
        first.plugin.SELECT_TYPES[first_index],
        option_dict={0: "off", 1: "mppt1"},
    )

    assert first.plugin.SELECT_TYPES[first_index].option_dict == {0: "off", 1: "mppt1"}
    assert second.plugin.SELECT_TYPES[second_index] == second_description
    assert solinteg_template.SELECT_TYPES[template_index] == template_description
