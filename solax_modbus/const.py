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
CONF_READ_GEN3X1 = "read_gen3_x1"
CONF_READ_GEN3X3 = "read_gen3_x3"
CONF_READ_OPTIONAL_SENSORS = "read_optional_sensor_s"
CONF_SolaX_HUB = "solax_hub"
ATTR_MANUFACTURER = "SolaX Power"
DEFAULT_READ_GEN2X1 = False
DEFAULT_READ_GEN3X1 = False
DEFAULT_READ_GEN3X3 = False
DEFAULT_READ_OPTIONAL_SENSORS = False

SENSOR_TYPES = {  
    "allow_grid_charge": ["Allow Grid Charge", "allow_grid_charge", None, None, None, None],    
    "battery_capacity_charge": ["Battery Capacity", "battery_capacity_charge", "%", None, DEVICE_CLASS_BATTERY],    
    "charger_use_mode": ["Charger Use Mode", "charger_use_mode", None, None, None, None],
    "battery_min_capacity": ["Battery Minimum Capacity", "battery_min_capacity", "%", None, None],
    "battery_power_charge": ["Battery Power Charge", "battery_power_charge", "W", None, DEVICE_CLASS_POWER],
    "battery_type": ["Battery Type", "battery_type", None, None, None],
    "battery_temperature": ["Battery Temperature", "battery_temperature", u"\u2103", None, DEVICE_CLASS_TEMPERATURE],
    "bms_connect_state": ["BMS Connect State", "bms_connect_state", None, None, None],
    "charger_start_time_1": ["Start Time 1", "charger_start_time_1", None, None, None],
    "charger_end_time_1": ["End Time 1", "charger_end_time_1", None, None, None],
    "charger_start_time_2": ["Start Time 2", "charger_start_time_2", None, None, None],
    "charger_end_time_2": ["End Time 2", "charger_end_time_2", None, None, None],
    "energy_today": ["Today's Yield", "energy_today", "kWh", None, DEVICE_CLASS_ENERGY, STATE_CLASS_MEASUREMENT, "today"],
    "export_energy_today": ["Today's Export Energy", "export_energy_today", "kWh", None, DEVICE_CLASS_ENERGY, STATE_CLASS_MEASUREMENT, "today"],    
    "feedin_power": ["Measured Power", "feedin_power", "W", None, DEVICE_CLASS_POWER],
    "grid_frequency": ["Grid Frequency", "grid_frequency", "Hz", None, None,],
    "grid_import": ["Grid Import", "grid_import", "W", None, DEVICE_CLASS_POWER],
    "grid_export": ["Grid Export", "grid_export", "W", None, DEVICE_CLASS_POWER],
    "house_load": ["House Load", "house_load", "W", None, DEVICE_CLASS_POWER],
    "import_energy_today": ["Today's Import Energy", "import_energy_today", "kWh", None, DEVICE_CLASS_ENERGY, STATE_CLASS_MEASUREMENT, "today"],
    "inverter_voltage": ["Inverter Voltage", "inverter_voltage", "V", None, DEVICE_CLASS_VOLTAGE],
    "inverter_current": ["Inverter Current", "inverter_current", "A", None, DEVICE_CLASS_CURRENT],
    "inverter_load": ["Inverter Power", "inverter_load", "W", None, DEVICE_CLASS_POWER],
    "inverter_temperature": ["Inverter Temperature", "inverter_temperature", u"\u2103", None, DEVICE_CLASS_TEMPERATURE],    
    "pv_current_1": ["PV Current 1", "pv_current_1", "A", "mdi:current-ac", DEVICE_CLASS_VOLTAGE],
    "pv_current_2": ["PV Current 2", "pv_current_2", "A", "mdi:current-ac", DEVICE_CLASS_VOLTAGE],
    "pv_power_1": ["PV Power 1", "pv_power_1", "W", "mdi:solar-power", DEVICE_CLASS_POWER],
    "pv_power_2": ["PV Power 2", "pv_power_2", "W", "mdi:solar-power", DEVICE_CLASS_POWER],
    "pv_voltage_1": ["PV Voltage 1", "pv_voltage_1", "V", None, DEVICE_CLASS_VOLTAGE],
    "pv_voltage_2": ["PV Voltage 2", "pv_voltage_2", "V", None, DEVICE_CLASS_VOLTAGE],    
    "pv_total_power": ["PV Total Power", "pv_total_power", "W", None, DEVICE_CLASS_POWER],    
    "run_mode": ["Run Mode", "run_mode", None, None, None, None],   
    "solar_energy_today": ["Today's Solar Energy", "solar_energy_today", "kWh", None, DEVICE_CLASS_ENERGY, STATE_CLASS_MEASUREMENT, "today"],
}

GEN2_X1_SENSOR_TYPES = {
	"battery_voltage_charge_g2": ["Battery Voltage Charge", "battery_voltage_charge_g2", "V", None, DEVICE_CLASS_VOLTAGE],
	"battery_current_charge_g2": ["Battery Current Charge", "battery_current_charge_g2", "A", None, DEVICE_CLASS_CURRENT],
	
}

GEN3_X1_SENSOR_TYPES = {
	"battery_voltage_charge_g3": ["Battery Voltage Charge", "battery_voltage_charge_g3", "V", None, DEVICE_CLASS_VOLTAGE],
	"battery_current_charge_g3": ["Battery Current Charge", "battery_current_charge_g3", "A", None, DEVICE_CLASS_CURRENT],
}
OPTIONAL_SENSOR_TYPES = {
	"modulename": ["Module Name", "modulename", None, None, None, None],
	"registration_code": ["Registration Code", "registration_code", None, None, None],
	"seriesnumber": ["Series Number", "seriesnumber", None, None, None],
}