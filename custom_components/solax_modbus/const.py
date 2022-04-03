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
    ENERGY_MEGA_WATT_HOUR,
    FREQUENCY_HERTZ,
    PERCENTAGE,
    POWER_VOLT_AMPERE,
    POWER_WATT,
    TEMP_CELSIUS,
    TIME_HOURS,
)

DOMAIN = "solax_modbus"
DEFAULT_NAME = "SolaX"
DEFAULT_SCAN_INTERVAL = 15
DEFAULT_PORT = 502
CONF_READ_GEN2X1 = "read_gen2_x1"
CONF_READ_GEN3X1 = "read_gen3_x1"
CONF_READ_GEN3X3 = "read_gen3_x3"
CONF_READ_GEN4X1 = "read_gen4_x1"
CONF_READ_GEN4X3 = "read_gen4_x3"
CONF_READ_X1_EPS = "read_x1_eps"
CONF_READ_X3_EPS = "read_x3_eps"
CONF_SERIAL      = "read_serial"
CONF_SERIAL_PORT = "read_serial_port"
CONF_SolaX_HUB   = "solax_hub"
ATTR_MANUFACTURER = "SolaX Power"
DEFAULT_SERIAL      = False
DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_READ_GEN2X1 = False
DEFAULT_READ_GEN3X1 = False
DEFAULT_READ_GEN3X3 = False
DEFAULT_READ_GEN4X1 = False
DEFAULT_READ_GEN4X3 = False
DEFAULT_READ_X1_EPS = False
DEFAULT_READ_X3_EPS = False

@dataclass
class SolaXModbusSensorEntityDescription(SensorEntityDescription):
    """A class that describes SolaX Power Modbus sensor entities."""

SENSOR_TYPES: dict[str, list[SolaXModbusSensorEntityDescription]] = {
    "battery_capacity_charge": SolaXModbusSensorEntityDescription(
    	name="Battery Capacity",
    	key="battery_capacity_charge",
    	native_unit_of_measurement=PERCENTAGE,
    	device_class=DEVICE_CLASS_BATTERY,
    ),
    "battery_current_charge": SolaXModbusSensorEntityDescription(
	name="Battery Current Charge",
	key="battery_current_charge",
	native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
    "battery_power_charge": SolaXModbusSensorEntityDescription(
    	name="Battery Power Charge",
    	key="battery_power_charge",
    	native_unit_of_measurement=POWER_WATT,
    	device_class=DEVICE_CLASS_POWER,
    	state_class=STATE_CLASS_MEASUREMENT,
    ),
    "battery_voltage_charge": SolaXModbusSensorEntityDescription(
	name="Battery Voltage Charge",
	key="battery_voltage_charge",
	native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
    "battery_temperature": SolaXModbusSensorEntityDescription(
    	name="Battery Temperature",
    	key="battery_temperature",
    	native_unit_of_measurement=TEMP_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "bms_connect_state": SolaXModbusSensorEntityDescription(
    	name="BMS Connect State", 
    	key="bms_connect_state",
    	entity_registry_enabled_default=False,
    ),
    "grid_frequency": SolaXModbusSensorEntityDescription(
    	name="Inverter Frequency",
    	key="grid_frequency",
    	native_unit_of_measurement=FREQUENCY_HERTZ,
    ),
    "inverter_load": SolaXModbusSensorEntityDescription(
    	name="Inverter Load",
    	key="inverter_load",
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
    "inverter_temperature": SolaXModbusSensorEntityDescription(
    	name="Inverter Temperature",
    	key="inverter_temperature",
    	native_unit_of_measurement=TEMP_CELSIUS,
        device_class=DEVICE_CLASS_TEMPERATURE,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    "rtc": SolaXModbusSensorEntityDescription(
	name="RTC",
	key="rtc",
    ),
    "run_mode": SolaXModbusSensorEntityDescription(
    	name="Run Mode",
    	key="run_mode",
    ),
    "seriesnumber": SolaXModbusSensorEntityDescription(
	name="Series Number",
	key="seriesnumber",
    ),
    "time_count_down": SolaXModbusSensorEntityDescription(
	name="Time Count Down",
	key="time_count_down",
	entity_registry_enabled_default=False,
    ),
}
