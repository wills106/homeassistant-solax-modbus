from datetime import datetime

from custom_components.solax_modbus.const import (
    BaseModbusSensorEntityDescription,
    value_function_battery_input,
    value_function_battery_output,
    value_function_firmware,
    value_function_gen4time,
    value_function_grid_export,
    value_function_grid_import,
    value_function_pv_power_total,
    value_function_rtc,
)


class MockDescription:
    def __init__(self, key):
        self.key = key


def test_value_function_pv_power_total():
    # Test normal summation
    datadict = {
        "pv_power_1": 100,
        "pv_power_2": 200,
        "pv_power_3": 50,
    }
    assert value_function_pv_power_total(0, None, datadict) == 350

    # Test with missing keys (should stop at first missing)
    datadict_partial = {
        "pv_power_1": 100,
        # pv_power_2 missing
        "pv_power_3": 50,
    }
    assert value_function_pv_power_total(0, None, datadict_partial) == 100

    # Test empty
    assert value_function_pv_power_total(0, None, {}) == 0


def test_value_function_battery_output():
    # Negative value means output (discharging)
    datadict = {"battery_power_charge": -500}
    assert value_function_battery_output(0, None, datadict) == 500

    # Positive value means input (charging) -> output should be 0
    datadict = {"battery_power_charge": 500}
    assert value_function_battery_output(0, None, datadict) == 0


def test_value_function_battery_input():
    # Positive value means input (charging)
    datadict = {"battery_power_charge": 500}
    assert value_function_battery_input(0, None, datadict) == 500

    # Negative value means output (discharging) -> input should be 0
    datadict = {"battery_power_charge": -500}
    assert value_function_battery_input(0, None, datadict) == 0


def test_value_function_grid_import():
    # Negative value means import
    datadict = {"measured_power": -1000}
    assert value_function_grid_import(0, None, datadict) == 1000

    # Positive value means export -> import should be 0
    datadict = {"measured_power": 1000}
    assert value_function_grid_import(0, None, datadict) == 0


def test_value_function_grid_export():
    # Positive value means export
    datadict = {"measured_power": 1000}
    assert value_function_grid_export(0, None, datadict) == 1000

    # Negative value means import -> export should be 0
    datadict = {"measured_power": -1000}
    assert value_function_grid_export(0, None, datadict) == 0


def test_value_function_rtc():
    # Format: (seconds, minutes, hours, days, months, years)
    # Note: The function expects a tuple/list of these values
    # Test case: 2023-10-25 14:30:45
    initval = (45, 30, 14, 25, 10, 23)
    expected = datetime(2023, 10, 25, 14, 30, 45)
    assert value_function_rtc(initval, None, {}) == expected

    # Test invalid date handling (should return None/pass)
    initval_invalid = (99, 99, 99, 99, 99, 99)
    assert value_function_rtc(initval_invalid, None, {}) is None


def test_value_function_gen4time():
    # Format: high byte = minutes, low byte = hours? No, code says:
    # h = initval % 256
    # m = initval >> 8
    # So low byte is hours, high byte is minutes

    # Test 14:30
    # hours = 14 (0x0E), minutes = 30 (0x1E)
    # val = (30 << 8) + 14 = 7680 + 14 = 7694
    val = (30 << 8) + 14
    assert value_function_gen4time(val, None, {}) == "14:30"


def test_value_function_firmware():
    # Code: m = initval % 256, h = initval >> 8
    # return f"{h}.{m:02d}"

    # Test 2.05
    # h = 2, m = 5
    val = (2 << 8) + 5
    assert value_function_firmware(val, None, {}) == "2.05"


def test_entity_description_instantiation():
    # Verify we can instantiate the base class with defaults
    desc = BaseModbusSensorEntityDescription(
        name="Test Sensor",
        key="test_sensor",
    )
    assert desc.name == "Test Sensor"
    assert desc.key == "test_sensor"
    assert desc.register == -1  # Default value
    assert desc.allowedtypes == 0  # Default value
