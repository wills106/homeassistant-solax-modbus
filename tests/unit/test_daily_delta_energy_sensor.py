from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

from custom_components.solax_modbus.const import BaseModbusSensorEntityDescription
from custom_components.solax_modbus.sensor import DailyDeltaEnergySensor


def _make_sensor(initial_total: float = 2.37) -> tuple[DailyDeltaEnergySensor, Any]:
    hub = SimpleNamespace(data={"grid_export_energy_total": initial_total})
    description = BaseModbusSensorEntityDescription(
        name="Grid Export Energy Today",
        key="grid_export_energy_today",
        _is_daily_delta_sensor=True,
        _daily_delta_source_key="grid_export_energy_total",
        rounding=3,
    )
    sensor = DailyDeltaEnergySensor("Viessmann", hub, cast(Any, None), description)
    cast(Any, sensor).async_write_ha_state = Mock()
    return sensor, hub


def test_daily_delta_uses_cumulative_total() -> None:
    sensor, hub = _make_sensor()

    sensor.modbus_data_updated()
    assert sensor.native_value == 0.0

    hub.data["grid_export_energy_total"] = 2.44
    sensor.modbus_data_updated()

    assert sensor.native_value == 0.07


def test_daily_delta_resets_on_new_day() -> None:
    sensor, hub = _make_sensor()
    sensor.modbus_data_updated()
    hub.data["grid_export_energy_total"] = 2.44
    sensor.modbus_data_updated()
    assert sensor.native_value == 0.07

    sensor._last_reset_date = date.today() - timedelta(days=1)
    hub.data["grid_export_energy_total"] = 2.45
    sensor.modbus_data_updated()

    assert sensor.native_value == 0.0


def test_daily_delta_handles_cumulative_counter_reset() -> None:
    sensor, hub = _make_sensor()
    sensor.modbus_data_updated()
    hub.data["grid_export_energy_total"] = 0.01
    sensor.modbus_data_updated()

    assert sensor.native_value == 0.0
