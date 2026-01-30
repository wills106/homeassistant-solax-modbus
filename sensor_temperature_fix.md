# Fix: Solax Mini – Wrong Temperature Label

## Problem
The existing sensor `"Inverter Temperature"` at register `0x40D` on the Solax Mini reports outside temperature (likely from RJ45 area), not the internal inverter board temperature.

## Solution

- Rename:
  - `"Inverter Temperature"` → `"Outside Temperature"`
  - `key="inverter_temperature"` → `key="outside_temperature"`

- Add:
  - `"Inverter Temperature Alt"` at register `0x42C`
  - Proper diagnostic category

## New Sensor Code

```python
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

