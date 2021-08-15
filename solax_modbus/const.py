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
CONF_READ_X1_EPS = "read_x1_eps"
CONF_READ_X3_EPS = "read_x3_eps"
CONF_SolaX_HUB = "solax_hub"
ATTR_MANUFACTURER = "SolaX Power"
DEFAULT_READ_GEN2X1 = False
DEFAULT_READ_GEN3X1 = False
DEFAULT_READ_GEN3X3 = False
DEFAULT_READ_X1_EPS = False
DEFAULT_READ_X3_EPS = False
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
    "grid_frequency": ["Inverter Frequency", "grid_frequency", "Hz", None, None,],
    "grid_import": ["Grid Import", "grid_import", "W", None, DEVICE_CLASS_POWER],
    "grid_export": ["Grid Export", "grid_export", "W", None, DEVICE_CLASS_POWER],
    "house_load": ["House Load", "house_load", "W", None, DEVICE_CLASS_POWER],
    "import_energy_today": ["Today's Import Energy", "import_energy_today", "kWh", None, DEVICE_CLASS_ENERGY, STATE_CLASS_MEASUREMENT, "today"],
    "inverter_voltage": ["Inverter Voltage", "inverter_voltage", "V", None, DEVICE_CLASS_VOLTAGE],
    "inverter_current": ["Inverter Current", "inverter_current", "A", None, DEVICE_CLASS_CURRENT],
    "inverter_load": ["Inverter Power", "inverter_load", "W", None, DEVICE_CLASS_POWER],
    "inverter_temperature": ["Inverter Temperature", "inverter_temperature", u"\u2103", None, DEVICE_CLASS_TEMPERATURE],    
    "pv_current_1": ["PV Current 1", "pv_current_1", "A", "mdi:current-ac", DEVICE_CLASS_CURRENT],
    "pv_current_2": ["PV Current 2", "pv_current_2", "A", "mdi:current-ac", DEVICE_CLASS_CURRENT],
    "pv_power_1": ["PV Power 1", "pv_power_1", "W", "mdi:solar-power", DEVICE_CLASS_POWER],
    "pv_power_2": ["PV Power 2", "pv_power_2", "W", "mdi:solar-power", DEVICE_CLASS_POWER],
    "pv_voltage_1": ["PV Voltage 1", "pv_voltage_1", "V", None, DEVICE_CLASS_VOLTAGE],
    "pv_voltage_2": ["PV Voltage 2", "pv_voltage_2", "V", None, DEVICE_CLASS_VOLTAGE],    
    "pv_total_power": ["PV Total Power", "pv_total_power", "W", None, DEVICE_CLASS_POWER],    
    "run_mode": ["Run Mode", "run_mode", None, None, None, None],   
    "solar_energy_today": ["Today's Solar Energy", "solar_energy_today", "kWh", None, DEVICE_CLASS_ENERGY, STATE_CLASS_MEASUREMENT, "today"],
    "solar_energy_total": ["Total Solar Energy", "solar_energy_total", "kWh", None, DEVICE_CLASS_ENERGY],
}

GEN2_X1_SENSOR_TYPES = {
	"battery_voltage_charge_g2": ["Battery Voltage Charge", "battery_voltage_charge_g2", "V", None, DEVICE_CLASS_VOLTAGE],
	"battery_current_charge_g2": ["Battery Current Charge", "battery_current_charge_g2", "A", None, DEVICE_CLASS_CURRENT],	
}

GEN3_X1_SENSOR_TYPES = {
	"battery_voltage_charge_g3": ["Battery Voltage Charge", "battery_voltage_charge_g3", "V", None, DEVICE_CLASS_VOLTAGE],
	"battery_current_charge_g3": ["Battery Current Charge", "battery_current_charge_g3", "A", None, DEVICE_CLASS_CURRENT],
}
X1_EPS_SENSOR_TYPES = {
	"eps_current": ["EPS Current", "eps_current", "A", None, DEVICE_CLASS_CURRENT],
	"eps_frequency": ["EPS Frequency", "eps_frequency", "Hz", None, None,],
	"eps_power": ["EPS Power", "eps_power", "VA", None, None],
	"eps_voltage": ["EPS Voltage", "eps_voltage", "V", None, DEVICE_CLASS_VOLTAGE],
}
X3_EPS_SENSOR_TYPES = {
	"eps_current_r": ["EPS Current R", "eps_current_r", "A", None, DEVICE_CLASS_CURRENT],
	"eps_current_s": ["EPS Current S", "eps_current_s", "A", None, DEVICE_CLASS_CURRENT],
	"eps_current_t": ["EPS Current T", "eps_current_t", "A", None, DEVICE_CLASS_CURRENT],
	"eps_mode_runtime": ["EPS Mode Runtime", "eps_mode_runtime", "H", None, None],
	"eps_power_r": ["EPS Power R", "eps_power_r", "VA", None, None],
	"eps_power_s": ["EPS Power S", "eps_power_s", "VA", None, None],
	"eps_power_t": ["EPS Power T", "eps_power_t", "VA", None, None],
	"eps_power_active_r": ["EPS Power Active R", "eps_power_active_r", "W", None, DEVICE_CLASS_POWER],
	"eps_power_active_s": ["EPS Power Active S", "eps_power_active_s", "W", None, DEVICE_CLASS_POWER],
	"eps_power_active_t": ["EPS Power Active T", "eps_power_active_t", "W", None, DEVICE_CLASS_POWER],
	"eps_voltage_r": ["EPS Voltage R", "eps_voltage_r", "V", None, DEVICE_CLASS_VOLTAGE],
	"eps_voltage_s": ["EPS Voltage S", "eps_voltage_s", "V", None, DEVICE_CLASS_VOLTAGE],
	"eps_voltage_t": ["EPS Voltage T", "eps_voltage_t", "V", None, DEVICE_CLASS_VOLTAGE],	
}
GEN3_X3_SENSOR_TYPES = {
	"battery_current_charge_g3": ["Battery Current Charge", "battery_current_charge_g3", "A", None, DEVICE_CLASS_CURRENT],
	"feedin_power_r": ["Measured Power R", "feedin_power_r", "W", None, DEVICE_CLASS_POWER],
	"feedin_power_s": ["Measured Power S", "feedin_power_s", "W", None, DEVICE_CLASS_POWER],
	"feedin_power_t": ["Measured Power T", "feedin_power_t", "W", None, DEVICE_CLASS_POWER],
	"grid_current_r": ["Inverter Current R", "grid_current_r", "A", None, DEVICE_CLASS_CURRENT],
	"grid_current_s": ["Inverter Current S", "grid_current_s", "A", None, DEVICE_CLASS_CURRENT],
	"grid_current_t": ["Inverter Current T", "grid_current_t", "A", None, DEVICE_CLASS_CURRENT],
	"grid_mode_runtime": ["Grid Mode Runtime", "grid_mode_runtime", "H", None, None],
	"grid_power_r": ["Inverter Power R", "grid_power_r", "W", None, DEVICE_CLASS_POWER],
	"grid_power_s": ["Inverter Power S", "grid_power_s", "W", None, DEVICE_CLASS_POWER],
	"grid_power_t": ["Inverter Power T", "grid_power_t", "W", None, DEVICE_CLASS_POWER],
	"grid_voltage_r": ["Inverter Voltage R", "grid_voltage_r", "V", None, DEVICE_CLASS_VOLTAGE],
	"grid_voltage_s": ["Inverter Voltage S", "grid_voltage_s", "V", None, DEVICE_CLASS_VOLTAGE],
	"grid_voltage_t": ["Inverter Voltage T", "grid_voltage_t", "V", None, DEVICE_CLASS_VOLTAGE],	
}
OPTIONAL_SENSOR_TYPES = {
	"eps_mute": ["EPS Mute", "eps_mute", None, None, None, None],
	"battery_dicharge_cut_off_voltage": ["Battery Discharge Cut Off Voltage", "battery_discharge_cut_off_voltage", "V", None, None],
	"battery_charge_max_current": ["Battery Charge Max Current", "battery_charge_max_current", "A", None, None],
	"battery_discharge_max_current": ["Battery Disharge Max Current", "battery_discharge_max_current", "A", None, None],
	"battery_volt_fault_val": ["Battery Volt Fault Val", "battery_volt_fault_val", None, None, None],
	"bms_charge_max_current": ["BMS Charge Max Current", "bms_charge_max_current", "A", None, None],
	"bms_discharge_max_current": ["BMS Discharge Max Current", "bms_discharge_max_current", "A", None, None],
	"bus_volt": ["Bus Volt", "bus_volt", "V", None, None, None],
	"dc_fault_val": ["DC Fault Val", "dc_fault_val", None, None, None, None],
	"eps_mute": ["EPS Mute", "eps_mute", None, None, None, None],
	"eps_set_frequency": ["EPS Set Frequency", "eps_set_frequency", None, None, None, None],
	"export_control_factory_limit": ["Export Control Factory Limit", "export_control_factory_limit", "W", None, None],
	"export_control_user_limit": ["Export Control User Limit", "export_control_user_limit", "W", None, None],
	"firmwareversion_invertermaster": ["Firmware Version Inverter Master", "firmwareversion_invertermaster", None, None, None],
	"firmwareversion_manager": ["Firmware Version Manager", "firmwareversion_manager", None, None, None],
	"firmwareversion_modbustcp_major": ["Firmware Version Modbus TCP Major", "firmwareversion_modbustcp_major", None, None, None],
	"firmwareversion_modbustcp_minor": ["Firmware Version Modbus TCP Minor", "firmwareversion_modbustcp_minor", None, None, None],
	"input_energy_charge_today": ["Input Energy Charge Today", "input_energy_charge_today", "kWh", None, DEVICE_CLASS_ENERGY, STATE_CLASS_MEASUREMENT, "today"],
	"language": ["Language", "language", None, None, None, None],
	"lock_state": ["Lock State", "lock_state", None, None, None, None],
	"myaddress": ["My address", "myaddress", None, None, None],
	"modulename": ["Module Name", "modulename", None, None, None, None],
	"normal_runtime": ["Normal Runtime", "normal_runtime", "H", None, None],
	"overload_fault_val": ["Overload Fault Val", "overload_fault_val", None, None, None, None],
	"output_energy_charge_today": ["Output Energy Charge Today", "output_energy_charge_today", "kWh", None, DEVICE_CLASS_ENERGY, STATE_CLASS_MEASUREMENT, "today"],
	"registration_code": ["Registration Code", "registration_code", None, None, None],
	"rtc": ["RTC", "rtc", None, None, None],
	"seriesnumber": ["Series Number", "seriesnumber", None, None, None],
	"time_count_down": ["Time Count Down", "time_count_down", None, None, None],
	"total_energy_to_grid": ["Total Energy To Grid", "total_energy_to_grid", "kWh", None, DEVICE_CLASS_ENERGY],
}