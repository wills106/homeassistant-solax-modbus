"""Remote control must size ap_target from the load without the Meter 2 PV.

Issue #2494: with AC-coupled PV on Meter 2, modes 1-7 exported the surplus
instead of charging the battery. The `house_load` sensor includes
`meter_2_measured_power`, so feeding it to the controller made `ap_target` too
small by exactly the Meter 2 contribution.
"""

from typing import Any

import pytest

from custom_components.solax_modbus.const import BUTTONREPEAT_LOOP
from custom_components.solax_modbus.plugin_solax import autorepeat_function_remotecontrol_recompute


def _datadict(**overrides: Any) -> dict[str, Any]:
    """A single-inverter snapshot with AC-coupled PV on Meter 2.

    4 kW through the inverter, 1 kW exported, and 3 kW of AC-coupled PV on
    Meter 2. The house load without Meter 2 is therefore 4 kW - (-1 kW) = 5 kW,
    and the sensor's own value folds the 3 kW in to give 2 kW.
    """
    values: dict[str, Any] = {
        "remotecontrol_power_control": "Enabled Self Use",
        "remotecontrol_set_type": "Set",
        "remotecontrol_active_power": 0,
        "remotecontrol_reactive_power": 0,
        "remotecontrol_duration": 20,
        "remotecontrol_import_limit": 20000,
        "remotecontrol_timeout": 0,
        "reactive_power_upper": 0,
        "reactive_power_lower": 0,
        "export_control_user_limit": 20000,
        "battery_capacity": 50,
        "measured_power": -1000,
        "inverter_power": 4000,
        "pv_power_total": 4000,
        "battery_power_charge": 3000,
        "meter_2_measured_power": -3000,
        "house_load": 2000,
    }
    values.update(overrides)
    return values


def _ap_target(datadict: dict[str, Any]) -> Any:
    result = autorepeat_function_remotecontrol_recompute(BUTTONREPEAT_LOOP, None, datadict)
    return next(value for key, value in result["data"] if key == "remotecontrol_active_power")


def test_self_use_ignores_the_meter_2_contribution() -> None:
    # 0 - (inverter_power - measured_power) = 0 - 5000
    assert _ap_target(_datadict()) == -5000


def test_self_use_matches_the_pre_2026_10_2_formula() -> None:
    """The value 2026.10.1 used: inverter_power - measured_power, no Meter 2."""
    datadict = _datadict()
    expected = 0 - (datadict["inverter_power"] - datadict["measured_power"])
    assert _ap_target(datadict) == expected


@pytest.mark.parametrize("meter_2", [0, -1000, -3000, 2500])
def test_a_different_meter_2_reading_does_not_change_ap_target(meter_2: int) -> None:
    """Setups without Meter 2 are unaffected, and so is every reading of it."""
    assert _ap_target(_datadict(meter_2_measured_power=meter_2)) == -5000


def test_an_external_house_load_override_still_wins() -> None:
    """A configured external sensor replaces the computed load.

    The override injects `external_house_load` into the datadict; ignoring it
    would silently drop a value the user configured.
    """
    assert _ap_target(_datadict(external_house_load=1234)) == -1234


def test_without_an_override_the_meter_2_pv_is_excluded() -> None:
    assert _ap_target(_datadict()) == -5000
