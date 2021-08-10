from homeassistant.components.sensor import (
    STATE_CLASS_MEASUREMENT,
)
from homeassistant.const import (
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_CURRENT,
    DEVICE_CLASS_ENERGY,
    DEVICE_CLASS_POWER,
    DEVICE_CLASS_POWER_FACTOR,
    DEVICE_CLASS_TEMPERATURE,
    DEVICE_CLASS_VOLTAGE,
)

DOMAIN = "solax_modbus"
DEFAULT_NAME = "SolaX"
DEFAULT_SCAN_INTERVAL = 2
DEFAULT_PORT = 502
CONF_READ_GEN2X1 = "read_gen2_x1"
CONF_READ_GEN3X1 = "read_gen3_x2"
CONF_READ_GEN3X3 = "read_gen3_x3"
CONF_SolaX_HUB = "solax_hub"
ATTR_MANUFACTURER = "SolaX Power"
DEFAULT_READ_GEN2X1 = False
DEFAULT_READ_GEN3X1 = False
DEFAULT_READ_GEN3X3 = False

SENSOR_TYPES = {
    "seriesnumber": ["Series Number", "seriesnumber", None, None, None],
    "factoryname": ["Factory Name", "factoryname", None, None, None],
    "modulename": ["Module Name", "modulename", None, None, None, None],
    "registration_code": ["Registration Code", "registration_code", None, None, None],
    "allow_grid_charge": ["Allow Grid Charge", "allow_grid_charge", None, None, None, None],
    "charger_use_mode": ["Charger Use Mode", "charger_use_mode", None, None, None, None],
    "battery_min_capacity": ["Battery Minimum Capacity", "battery_min_capacity", "%", None, None],
    "battery_power_charge": ["Battery Power Charge", "battery_power_charge", "W", None, DEVICE_CLASS_POWER],
    "battery_type": ["Battery Type", "battery_type", None, None, None],
    "battery_temperature": ["Battery Temperature", "battery_temperature", u"\u2103", None, DEVICE_CLASS_TEMPERATURE],
    "charger_start_time_1_h": ["Start Time 1 hrs", "charger_start_time_1_h", None, None, None],
    "charger_start_time_1_m": ["Start Time 1 mins", "charger_start_time_1_m", None, None, None],
    "charger_end_time_1_h": ["End Time 1 hrs", "charger_end_time_1_h", None, None, None],
    "charger_end_time_1_m": ["End Time 1 mins", "charger_end_time_1_m", None, None, None],
    "charger_start_time_2_h": ["Start Time 2 hrs", "charger_start_time_2_h", None, None, None],
    "charger_start_time_2_m": ["Start Time 2 mins", "charger_start_time_2_m", None, None, None],
    "charger_end_time_2_h": ["End Time 2 hrs", "charger_end_time_2_h", None, None, None],
    "charger_end_time_2_m": ["End Time 2 mins", "charger_end_time_2_m", None, None, None],
    "inverter_voltage": ["Inverter Voltage", "inverter_voltage", "V", None, DEVICE_CLASS_VOLTAGE],
    "inverter_current": ["Inverter Current", "inverter_current", "A", None, DEVICE_CLASS_CURRENT],
    "inverter_load": ["Inverter Power", "inverter_load", "W", None, DEVICE_CLASS_POWER],
    "inverter_temperature": ["Inverter Temperature", "inverter_temperature", u"\u2103", None, DEVICE_CLASS_TEMPERATURE],
    "feedin_power": ["Measured Power", "feedin_power", "W", None, DEVICE_CLASS_POWER],
    "grid_import": ["Grid Import", "grid_import", "W", None, DEVICE_CLASS_POWER],
    "grid_export": ["Grid Export", "grid_export", "W", None, DEVICE_CLASS_POWER],
    "energy_today": ["Today's Yield", "energy_today", "kWh", None, DEVICE_CLASS_POWER, STATE_CLASS_MEASUREMENT, "today"],
    "run_mode": ["Run Mode", "run_mode", None, None, None, None],
    "pv_power_1": ["PV Power 1", "pv_power_1", "W", "mdi:solar-power", DEVICE_CLASS_POWER],
    "pv_power_2": ["PV Power 2", "pv_power_2", "W", "mdi:solar-power", DEVICE_CLASS_POWER],
    "pv_voltage_1": ["PV Voltage 1", "pv_voltage_1", "V", None, DEVICE_CLASS_VOLTAGE],
    "pv_voltage_2": ["PV Voltage 2", "pv_voltage_2", "V", None, DEVICE_CLASS_VOLTAGE],
    "pv_current_1": ["PV Current 1", "pv_current_1", "A", "mdi:current-ac", DEVICE_CLASS_VOLTAGE],
    "pv_current_2": ["PV Current 2", "pv_current_2", "A", "mdi:current-ac", DEVICE_CLASS_VOLTAGE],
    "pv_total_power": ["PV Total Power", "pv_total_power", "W", None, DEVICE_CLASS_POWER],
    "battery_capacity_charge": ["Battery Capacity", "battery_capacity_charge", "%", None, DEVICE_CLASS_BATTERY],
}

GEN2_X1_SENSOR_TYPES = {
	"battery_voltage_charge_g2": ["Battery Voltage Charge", "battery_voltage_charge_g2", "V", None, DEVICE_CLASS_VOLTAGE],
	"battery_current_charge_g2": ["Battery Current Charge", "battery_current_charge_g2", "A", None, DEVICE_CLASS_CURRENT],
	
}

GEN3_X1_SENSOR_TYPES = {
	"battery_voltage_charge_g3": ["Battery Voltage Charge", "battery_voltage_charge_g3", "V", None, DEVICE_CLASS_VOLTAGE],
	"battery_current_charge_g3": ["Battery Current Charge", "battery_current_charge_g3", "A", None, DEVICE_CLASS_CURRENT],
}