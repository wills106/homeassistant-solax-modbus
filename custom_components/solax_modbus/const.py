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
    "r_grid_frequency": SolaXModbusSensorEntityDescription(
    	name="R Inverter Frequency",
    	key="r_grid_frequency",
    	native_unit_of_measurement=FREQUENCY_HERTZ,
    ),
    "s_grid_frequency": SolaXModbusSensorEntityDescription(
    	name="S Inverter Frequency",
    	key="s_grid_frequency",
    	native_unit_of_measurement=FREQUENCY_HERTZ,
    ),
    "t_grid_frequency": SolaXModbusSensorEntityDescription(
    	name="T Inverter Frequency",
    	key="t_grid_frequency",
    	native_unit_of_measurement=FREQUENCY_HERTZ,
    ),
    "inverter_load": SolaXModbusSensorEntityDescription(
    	name="Inverter Load",
    	key="inverter_load",
    	native_unit_of_measurement=POWER_WATT,
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
    ),    
    "r_inverter_voltage": SolaXModbusSensorEntityDescription(
    	name="R Inverter Voltage",
    	key="r_inverter_voltage",
    	native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
    "s_inverter_voltage": SolaXModbusSensorEntityDescription(
    	name="S Inverter Voltage",
    	key="s_inverter_voltage",
    	native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
    "t_inverter_voltage": SolaXModbusSensorEntityDescription(
    	name="T Inverter Voltage",
    	key="t_inverter_voltage",
    	native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=DEVICE_CLASS_VOLTAGE,
    ),
    "r_inverter_current": SolaXModbusSensorEntityDescription(
    	name="R Inverter Current",
    	key="r_inverter_current",
    	native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
    "s_inverter_current": SolaXModbusSensorEntityDescription(
    	name="S Inverter Current",
    	key="s_inverter_current",
    	native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
    ),
    "t_inverter_current": SolaXModbusSensorEntityDescription(
    	name="T Inverter Current",
    	key="t_inverter_current",
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
    "run_mode": SolaXModbusSensorEntityDescription(
    	name="Run Mode",
    	key="run_mode",
    ),
    "seriesnumber": SolaXModbusSensorEntityDescription(
	name="Series Number",
	key="seriesnumber",
    ),
    "rtc": SolaXModbusSensorEntityDescription(
	name="RTC",
	key="rtc",
    ),
}
