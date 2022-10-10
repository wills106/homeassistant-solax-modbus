@dataclass
class SofarModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    """A class that describes Sofar Modbus sensor entities."""
    order16: int = Endian.Big
    order32: int = Endian.Big
    unit: int = REGISTER_U16
    register_type: int= REG_HOLDING

SENSOR_TYPES: list[SofarModbusSensorEntityDescription] = [ 

###
#
# On Grid Output
#
###

    SofarModbusSensorEntityDescription(
        name = "Serial Number",
        key = "serial_number",
        native_unit_of_measurement = ELECTRIC_CURRENT_AMPERE,
        device_class = DEVICE_CLASS_CURRENT,
        register = 0x445,
        no_read = 7,
        decode = ASCII,
        allowedtypes = HYBRID | X3,
    ),
    SofarModbusSensorEntityDescription(
        name = "Grid Frequency",
        key = "grid_frequency",
        native_unit_of_measurement = FREQUENCY_HERTZ,
        device_class = DEVICE_CLASS_FREQUENCY,
        register = 0x484,
        scale = 0.01,
        allowedtypes = HYBRID | X3,
    ),
    SofarModbusSensorEntityDescription(
        name = "ActivePower Output Total",
        key = "activepower_output_total",
        native_unit_of_measurement = ENERGY_KILO_WATT_HOUR,
        device_class = DEVICE_CLASS_ENERGY,
        register = 0x485,
        unit = REGISTER_S16,
        scale = 0.01,
        allowedtypes = HYBRID | X3,
    ),
    SofarModbusSensorEntityDescription(
        name = "ReactivePower Output Total",
        key = "reactivepower_output_total",
        native_unit_of_measurement = ENERGY_KILO_WATT_HOUR,
        device_class = DEVICE_CLASS_ENERGY,
        register = 0x486,
        unit = REGISTER_S16,
        scale = 0.01,
        allowedtypes = HYBRID | X3,
    ),
    SofarModbusSensorEntityDescription(
        name = "ApparentPower Output Total",
        key = "apparentpower_output_total",
        native_unit_of_measurement = ENERGY_KILO_WATT_HOUR,
        device_class = DEVICE_CLASS_ENERGY,
        register = 0x487,
        unit = REGISTER_S16,
        scale = 0.01,
        allowedtypes = HYBRID | X3,
    ),
    SofarModbusSensorEntityDescription(
        name = "ActivePower PCC Total",
        key = "activepower_pcc_total",
        native_unit_of_measurement = ENERGY_KILO_WATT_HOUR,
        device_class = DEVICE_CLASS_ENERGY,
        register = 0x488,
        unit = REGISTER_S16,
        scale = 0.01,
        allowedtypes = HYBRID | X3,
    ),
    SofarModbusSensorEntityDescription(
        name = "ReactivePower PCC Total",
        key = "reactivepower_pcc_total",
        native_unit_of_measurement = ENERGY_KILO_WATT_HOUR,
        device_class = DEVICE_CLASS_ENERGY,
        register = 0x489,
        unit = REGISTER_S16,
        scale = 0.01,
        allowedtypes = HYBRID | X3,
    ),
    SofarModbusSensorEntityDescription(
        name = "ApparentPower PCC Total",
        key = "apparentpower_pcc_total",
        native_unit_of_measurement = ENERGY_KILO_WATT_HOUR,
        device_class = DEVICE_CLASS_ENERGY,
        register = 0x48A,
        unit = REGISTER_S16,
        scale = 0.01,
        allowedtypes = HYBRID | X3,
    ),
    SofarModbusSensorEntityDescription(
        name = "Voltage R",
        key = "voltage_r",
        native_unit_of_measurement = ELECTRIC_POTENTIAL_VOLT,
        device_class = DEVICE_CLASS_VOLTAGE,
        register = 0x48D,
        scale = 0.1,
        allowedtypes = HYBRID | X3,
    ),
    SofarModbusSensorEntityDescription(
        name="Current Output R",
        key="current_output_r",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=DEVICE_CLASS_CURRENT,
        register = 0x48E,
        scale = 0.01,
        allowedtypes = HYBRID | X3,
    ),
    SofarModbusSensorEntityDescription(
        name = "ActivePower Output R",
        key = "activepower_output_r",
        native_unit_of_measurement = ENERGY_KILO_WATT_HOUR,
        device_class = DEVICE_CLASS_ENERGY,
        register = 0x48F,
        unit = REGISTER_S16,
        scale = 0.01,
        allowedtypes = HYBRID | X3,
    ),
]
