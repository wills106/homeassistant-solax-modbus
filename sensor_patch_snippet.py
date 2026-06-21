SolaXModbusSensorEntityDescription(
    name="Inverter Temperature Alt",
    key="inverter_temperature_alt",
    register=0x42C,
    register_type=REG_INPUT,
    unit=REGISTER_S16,
    allowedtypes=0x2102,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    device_class=SensorDeviceClass.TEMPERATURE,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
)

