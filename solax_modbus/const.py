from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntityDescription,
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_TOTAL_INCREASING,
)

from homeassistant.const import (
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_CURRENT,
    DEVICE_CLASS_ENERGY,
    DEVICE_CLASS_POWER,
    DEVICE_CLASS_TEMPERATURE,
    DEVICE_CLASS_VOLTAGE,
    ELECTRIC_CURRENT_AMPERE,
    ELECTRIC_CURRENT_MILLIAMPERE,
    ELECTRIC_POTENTIAL_VOLT,
    ENERGY_KILO_WATT_HOUR,
    FREQUENCY_HERTZ,
    PERCENTAGE,
    POWER_VOLT_AMPERE,
    POWER_WATT,
    TEMP_CELSIUS,
    TIME_HOURS,
)

DOMAIN = "solax_modbus"
DEFAULT_NAME = "SolaX"
DEFAULT_SCAN_INTERVAL = 2
DEFAULT_PORT = 502
CONF_READ_GEN2X1 = "read_gen2_x1"
CONF_READ_GEN3X1 = "read_gen3_x1"
CONF_READ_GEN3X3 = "read_gen3_x3"
CONF_READ_X1_EPS = "read_x1_eps"
CONF_READ_X3_EPS = "read_x3_eps"
CONF_SolaX_HUB = "solax_hub"
ATTR_MANUFACTURER = "SolaX Power"
DEFAULT_READ_GEN2X1 = False
DEFAULT_READ_GEN3X1 = False
DEFAULT_READ_GEN3X3 = False
DEFAULT_READ_X1_EPS = False
DEFAULT_READ_X3_EPS = False

@dataclass
class SolaXModbusSensorEntityDescription(SensorEntityDescription):
    """A class that describes SolaX Power Modbus sensor entities."""

SENSOR_TYPES: dict[str, list[SolaXModbusSensorEntityDescription]] = {  
    "allow_grid_charge": SolaXModbusSensorEntityDescription(
        name="Allow Grid Charge",
        key="allow_grid_charge",
    ),
    "battery_capacity_charge": SolaXModbusSensorEntityDescription(
    	name="Battery Capacity",
    	key="battery_capacity_charge",
    	native_unit_of_measurement=PERCENTAGE,
    	device_class=DEVICE_CLASS_BATTERY,
    ),
    "battery_charge_max_current": SolaXModbusSensorEntityDescription(
		name="Battery Charge Max Current",
		key="battery_charge_max_current",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
	),
    "battery_dicharge_cut_off_voltage": SolaXModbusSensorEntityDescription(
		name="Battery Discharge Cut Off Voltage",
		key="battery_discharge_cut_off_voltage",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
		entity_registry_enabled_default=False,
    ),
	"battery_discharge_max_current": SolaXModbusSensorEntityDescription(
		name="Battery Disharge Max Current",
		key="battery_discharge_max_current",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
	),
    "battery_input_energy_today": SolaXModbusSensorEntityDescription(
		name="Battery Input Energy Today",
		key="input_energy_charge_today",
		native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    "battery_min_capacity": SolaXModbusSensorEntityDescription(
    	name="Battery Minimum Capacity",
    	key="battery_min_capacity",
    	native_unit_of_measurement=PERCENTAGE,
    ),
    "battery_output_energy_today": SolaXModbusSensorEntityDescription(
		name="Battery Output Energy Today",
		key="output_energy_charge_today",
		native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    "battery_power_charge": SolaXModbusSensorEntityDescription(
    	name="Battery Power Charge",
    	key="battery_power_charge",
    	native_unit_of_measurement=POWER_WATT,
    	device_class=DEVICE_CLASS_POWER,
    	state_class=STATE_CLASS_MEASUREMENT,
    ),
    "battery_type": SolaXModbusSensorEntityDescription(
    	name="Battery Type",
    	key="battery_type",
    	entity_registry_enabled_default=False,
    ),
    "battery_temperature": SolaXModbusSensorEntityDescription(
    	name="Battery Temperature",
    	key="battery_temperature",
    	native_unit_of_measurement=TEMP_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "battery_volt_fault_val": SolaXModbusSensorEntityDescription(
		name="Battery Volt Fault Val",
		key="battery_volt_fault_val",
		entity_registry_enabled_default=False,
	),
	"bms_charge_max_current": SolaXModbusSensorEntityDescription(
		name="BMS Charge Max Current",
		key="bms_charge_max_current",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
		entity_registry_enabled_default=False,
	),
    "bms_connect_state": SolaXModbusSensorEntityDescription(
    	name="BMS Connect State", 
    	key="bms_connect_state",
    ),
    "bms_discharge_max_current": SolaXModbusSensorEntityDescription(
		name="BMS Discharge Max Current",
		key="bms_discharge_max_current",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
		entity_registry_enabled_default=False,
	),
	"bus_volt": SolaXModbusSensorEntityDescription(
		name="Bus Volt",
		key="bus_volt",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
        entity_registry_enabled_default=False,
    ),
    "charger_start_time_1": SolaXModbusSensorEntityDescription(
    	name="Start Time 1",
    	key="charger_start_time_1",
    ),
    "charger_end_time_1": SolaXModbusSensorEntityDescription(
    	name="End Time 1",
    	key="charger_end_time_1",
    ),
    "charger_start_time_2": SolaXModbusSensorEntityDescription(
    	name="Start Time 2",
    	key="charger_start_time_2",
    ),
    "charger_end_time_2": SolaXModbusSensorEntityDescription(
    	name="End Time 2",
    	key="charger_end_time_2",
    ),
    "charger_use_mode": SolaXModbusSensorEntityDescription(
    	name="Charger Use Mode",
    	key="charger_use_mode",
    ),
    "consumed_energy_total": SolaXModbusSensorEntityDescription(
		name="Consumed Energy Total",
		key="consumed_energy_total",
		native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "dc_fault_val": SolaXModbusSensorEntityDescription(
		name="DC Fault Val",
		key="dc_fault_val",
		entity_registry_enabled_default=False,
	),
    "energy_today": SolaXModbusSensorEntityDescription(
    	name="Today's Yield",
    	key="energy_today",
    	native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    "export_control_factory_limit": SolaXModbusSensorEntityDescription(
		name="Export Control Factory Limit",
		key="export_control_factory_limit",
		native_unit_of_measurement=POWER_WATT,
		entity_registry_enabled_default=False,
    ),
	"export_control_user_limit": SolaXModbusSensorEntityDescription(
		name="Export Control User Limit",
		key="export_control_user_limit",
		native_unit_of_measurement=POWER_WATT,
		entity_registry_enabled_default=False,
    ),
    "feedin_power": SolaXModbusSensorEntityDescription(
    	name="Measured Power",
    	key="feedin_power",
    	native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "firmwareversion_invertermaster": SolaXModbusSensorEntityDescription(
		name="Firmware Version Inverter Master",
		key="firmwareversion_invertermaster",
		entity_registry_enabled_default=False,
	),
	"firmwareversion_manager": SolaXModbusSensorEntityDescription(
		name="Firmware Version Manager",
		key="firmwareversion_manager",
		entity_registry_enabled_default=False,
	),
	"firmwareversion_modbustcp_major": SolaXModbusSensorEntityDescription(
		name="Firmware Version Modbus TCP Major",
		key="firmwareversion_modbustcp_major",
		entity_registry_enabled_default=False,
	),
	"firmwareversion_modbustcp_minor": SolaXModbusSensorEntityDescription(
		name="Firmware Version Modbus TCP Minor",
		key="firmwareversion_modbustcp_minor",
		entity_registry_enabled_default=False,
	),
    "grid_frequency": SolaXModbusSensorEntityDescription(
    	name="Inverter Frequency",
    	key="grid_frequency",
    	native_unit_of_measurement=FREQUENCY_HERTZ,
    ),
    "grid_import": SolaXModbusSensorEntityDescription(
    	name="Grid Import",
    	key="grid_import",
    	native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "grid_export": SolaXModbusSensorEntityDescription(
    	name="Grid Export",
    	key="grid_export",
    	native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "house_load": SolaXModbusSensorEntityDescription(
    	name="House Load",
    	key="house_load",
    	native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),    
    "inverter_voltage": SolaXModbusSensorEntityDescription(
    	name="Inverter Voltage",
    	key="inverter_voltage",
    	native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
    "inverter_current": SolaXModbusSensorEntityDescription(
    	name="Inverter Current",
    	key="inverter_current",
    	native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
    "inverter_load": SolaXModbusSensorEntityDescription(
    	name="Inverter Power",
    	key="inverter_load",
    	native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "inverter_temperature": SolaXModbusSensorEntityDescription(
    	name="Inverter Temperature",
    	key="inverter_temperature",
    	native_unit_of_measurement=TEMP_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "language": SolaXModbusSensorEntityDescription(
		name="Language",
		key="language",
		entity_registry_enabled_default=False,
	),
	"lock_state": SolaXModbusSensorEntityDescription(
		name="Lock State",
		key="lock_state",
		entity_registry_enabled_default=False,
	),
	"myaddress": SolaXModbusSensorEntityDescription(
		name="My address",
		key="myaddress",
		entity_registry_enabled_default=False,
	),
	"modulename": SolaXModbusSensorEntityDescription(
		name="Module Name",
		key="modulename",
		entity_registry_enabled_default=False,
	),
	"normal_runtime": SolaXModbusSensorEntityDescription(
		name="Normal Runtime",
		key="normal_runtime",
		native_unit_of_measurement=TIME_HOURS,
		entity_registry_enabled_default=False,
	),
	"overload_fault_val": SolaXModbusSensorEntityDescription(
		name="Overload Fault Val",
		key="overload_fault_val",
		entity_registry_enabled_default=False,
	),
    "pv_current_1": SolaXModbusSensorEntityDescription(
    	name="PV Current 1",
    	key="pv_current_1",
    	native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
    "pv_current_2": SolaXModbusSensorEntityDescription(
    	name="PV Current 2",
    	key="pv_current_2",
    	native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
    "pv_power_1": SolaXModbusSensorEntityDescription(
    	name="PV Power 1",
    	key="pv_power_1",
    	native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "pv_power_2": SolaXModbusSensorEntityDescription(
    	name="PV Power 2",
    	key="pv_power_2",
    	native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "pv_voltage_1": SolaXModbusSensorEntityDescription(
    	name="PV Voltage 1",
    	key="pv_voltage_1",
    	native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
    "pv_voltage_2": SolaXModbusSensorEntityDescription(
    	name="PV Voltage 2",
    	key="pv_voltage_2",
    	native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
    "pv_total_power": SolaXModbusSensorEntityDescription(
    	name="PV Total Power",
    	key="pv_total_power",
    	native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "registration_code": SolaXModbusSensorEntityDescription(
		name="Registration Code",
		key="registration_code",
		entity_registry_enabled_default=False,
	),
	"rtc": SolaXModbusSensorEntityDescription(
		name="RTC",
		key="rtc",
		entity_registry_enabled_default=False,
	),
    "run_mode": SolaXModbusSensorEntityDescription(
    	name="Run Mode",
    	key="run_mode",
    ),
    "seriesnumber": SolaXModbusSensorEntityDescription(
		name="Series Number",
		key="seriesnumber",
		entity_registry_enabled_default=False,
	),
    "solar_energy_today": SolaXModbusSensorEntityDescription(
    	name="Today's Solar Energy",
    	key="solar_energy_today",
    	native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    "solar_energy_total": SolaXModbusSensorEntityDescription(
    	name="Total Solar Energy",
    	key="solar_energy_total",
    	native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    "time_count_down": SolaXModbusSensorEntityDescription(
		name="Time Count Down",
		key="time_count_down",
		entity_registry_enabled_default=False,
	),
	"total_energy_to_grid": SolaXModbusSensorEntityDescription(
		name="Total Energy To Grid",
		key="total_energy_to_grid",
		native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
}

GEN2_X1_SENSOR_TYPES: dict[str, list[SolaXModbusSensorEntityDescription]] = {
	"battery_current_charge_g2": SolaXModbusSensorEntityDescription(
		name="Battery Current Charge",
		key="battery_current_charge_g2",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
	"battery_voltage_charge_g2": SolaXModbusSensorEntityDescription(
		name="Battery Voltage Charge",
		key="battery_voltage_charge_g2",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
}

GEN3_X1_SENSOR_TYPES: dict[str, list[SolaXModbusSensorEntityDescription]] = {
	"battery_current_charge_g3": SolaXModbusSensorEntityDescription(
		name="Battery Current Charge",
		key="battery_current_charge_g3",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
	"battery_voltage_charge_g3": SolaXModbusSensorEntityDescription(
		name="Battery Voltage Charge",
		key="battery_voltage_charge_g3",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
	"export_energy_today": SolaXModbusSensorEntityDescription(
		name="Today's Export Energy",
		key="export_energy_today",
		native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
	"import_energy_today": SolaXModbusSensorEntityDescription(
		name="Today's Import Energy",
		key="import_energy_today",
		native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
}
X1_EPS_SENSOR_TYPES: dict[str, list[SolaXModbusSensorEntityDescription]] = {
	"eps_current": SolaXModbusSensorEntityDescription(
		name="EPS Current",
		key="eps_current",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
	"eps_frequency": SolaXModbusSensorEntityDescription(
		name="EPS Frequency",
		key="eps_frequency",
		native_unit_of_measurement=FREQUENCY_HERTZ,
	),
	"eps_mute": SolaXModbusSensorEntityDescription(
		name="EPS Mute",
		key="eps_mute",
	),
	"eps_power": SolaXModbusSensorEntityDescription(
		name="EPS Power",
		key="eps_power",
		native_unit_of_measurement=POWER_VOLT_AMPERE
	),
	"eps_set_frequency": SolaXModbusSensorEntityDescription(
		name="EPS Set Frequency",
		key="eps_set_frequency",
		native_unit_of_measurement=FREQUENCY_HERTZ,
    ),
	"eps_voltage": SolaXModbusSensorEntityDescription(
		name="EPS Voltage",
		key="eps_voltage",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
}
X3_EPS_SENSOR_TYPES: dict[str, list[SolaXModbusSensorEntityDescription]] = {
	"eps_current_r": SolaXModbusSensorEntityDescription(
		name="EPS Current R",
		key="eps_current_r",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
	"eps_current_s": SolaXModbusSensorEntityDescription(
		name="EPS Current S",
		key="eps_current_s",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
	"eps_current_t": SolaXModbusSensorEntityDescription(
		name="EPS Current T",
		key="eps_current_t",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
	"eps_mode_runtime": SolaXModbusSensorEntityDescription(
		name="EPS Mode Runtime",
		key="eps_mode_runtime",
	),
	"eps_mute": SolaXModbusSensorEntityDescription(
		name="EPS Mute",
		key="eps_mute",
	),	
	"eps_power_r": SolaXModbusSensorEntityDescription(
		name="EPS Power R",
		key="eps_power_r",
		native_unit_of_measurement=POWER_VOLT_AMPERE,
    ),
	"eps_power_s": SolaXModbusSensorEntityDescription(
		name="EPS Power S",
		key="eps_power_s",
		native_unit_of_measurement=POWER_VOLT_AMPERE,
    ),
	"eps_power_t": SolaXModbusSensorEntityDescription(
		name="EPS Power T",
		key="eps_power_t",
		native_unit_of_measurement=POWER_VOLT_AMPERE,
    ),
	"eps_power_active_r": SolaXModbusSensorEntityDescription(
		name="EPS Power Active R",
		key="eps_power_active_r",
		native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
	"eps_power_active_s": SolaXModbusSensorEntityDescription(
		name="EPS Power Active S",
		key="eps_power_active_s",
		native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
	"eps_power_active_t": SolaXModbusSensorEntityDescription(
		name="EPS Power Active T",
		key="eps_power_active_t",
		native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "eps_set_frequency": SolaXModbusSensorEntityDescription(
		name="EPS Set Frequency",
		key="eps_set_frequency",
		native_unit_of_measurement=FREQUENCY_HERTZ,
    ),
	"eps_voltage_r": SolaXModbusSensorEntityDescription(
		name="EPS Voltage R",
		key="eps_voltage_r",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
	"eps_voltage_s": SolaXModbusSensorEntityDescription(
		name="EPS Voltage S",
		key="eps_voltage_s",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
	"eps_voltage_t": SolaXModbusSensorEntityDescription(
		name="EPS Voltage T",
		key="eps_voltage_t",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
}
GEN3_X3_SENSOR_TYPES: dict[str, list[SolaXModbusSensorEntityDescription]] = {
	"battery_current_charge_g3": SolaXModbusSensorEntityDescription(
		name="Battery Current Charge",
		key="battery_current_charge_g3",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
	"export_energy_today": SolaXModbusSensorEntityDescription(
		name="Today's Export Energy",
		key="export_energy_today",
		native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    "feedin_energy_total": SolaXModbusSensorEntityDescription(
		name="Feedin Energy Total",
		key="feedin_energy_total",
		native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
	"feedin_power_r": SolaXModbusSensorEntityDescription(
		name="Measured Power R",
		key="feedin_power_r",
		native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
	"feedin_power_s": SolaXModbusSensorEntityDescription(
		name="Measured Power S",
		key="feedin_power_s",
		native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
	"feedin_power_t": SolaXModbusSensorEntityDescription(
		name="Measured Power T",
		key="feedin_power_t",
		native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
	"grid_current_r": SolaXModbusSensorEntityDescription(
		name="Inverter Current R",
		key="grid_current_r",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
	"grid_current_s": SolaXModbusSensorEntityDescription(
		name="Inverter Current S",
		key="grid_current_s",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
	"grid_current_t": SolaXModbusSensorEntityDescription(
		name="Inverter Current T",
		key="grid_current_t",
		native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
	"grid_mode_runtime": SolaXModbusSensorEntityDescription(
		name="Grid Mode Runtime",
		key="grid_mode_runtime",
		native_unit_of_measurement=TIME_HOURS,
	),
	"grid_power_r": SolaXModbusSensorEntityDescription(
		name="Inverter Power R",
		key="grid_power_r",
		native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
	"grid_power_s": SolaXModbusSensorEntityDescription(
		name="Inverter Power S",
		key="grid_power_s",
		native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
	"grid_power_t": SolaXModbusSensorEntityDescription(
		name="Inverter Power T",
		key="grid_power_t",
		native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
	"grid_voltage_r": SolaXModbusSensorEntityDescription(
		name="Inverter Voltage R",
		key="grid_voltage_r",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
	"grid_voltage_s": SolaXModbusSensorEntityDescription(
		name="Inverter Voltage S",
		key="grid_voltage_s",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
	"grid_voltage_t": SolaXModbusSensorEntityDescription(
		name="Inverter Voltage T",
		key="grid_voltage_t",
		native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
	"import_energy_today": SolaXModbusSensorEntityDescription(
		name="Today's Import Energy",
		key="import_energy_today",
		native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
}