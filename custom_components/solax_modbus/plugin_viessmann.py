import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.helpers.entity import EntityCategory  # type: ignore[attr-defined]

from custom_components.solax_modbus.const import (
    REG_HOLDING,
    REGISTER_F32,
    REGISTER_S16,
    REGISTER_S32,
    REGISTER_STR,
    REGISTER_U16,
    REGISTER_U32,
    SCAN_GROUP_FAST,
    SCAN_GROUP_MEDIUM,
    BaseModbusSensorEntityDescription,
    plugin_base,
)

from .pymodbus_compat import DataType, convert_from_registers

_LOGGER = logging.getLogger(__name__)

"""
Plugin for Viessmann Hybrid Inverter B1 devices using the GoodWe-compatible
Modbus register map.

Validated against a Viessmann HINV6.0-B1 exposed through Modbus TCP.
The inverter uses holding registers (Modbus function 03) and defaults to
Modbus address 247.
"""

ALLDEFAULT = 0

_WORK_MODE = {
    0: "Wait",
    1: "On-Grid",
    2: "Off-Grid",
    3: "Fault",
    4: "Flash",
    5: "Check",
}

_GRID_MODE = {
    0: "Loss",
    1: "OK",
    2: "Fault",
}

_BATTERY_MODE = {
    0: "No Battery",
    1: "Standby",
    2: "Discharging",
    3: "Charging",
}

_BMS_STATUS = {
    0: "Idle",
    1: "Normal",
    2: "Warning",
    3: "Fault",
}


async def _read_string(hub: Any, address: int, count: int) -> str | None:
    res = None
    try:
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=count)
        if inverter_data is not None and not inverter_data.isError():
            raw = convert_from_registers(inverter_data.registers[0:count], DataType.STRING, "big")  # type: ignore[attr-defined]
            res = raw.decode("ascii", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            res = res.replace("\x00", "").replace("\xff", "").strip()
    except Exception:
        _LOGGER.warning("%s: failed to read string at 0x%x", hub.name, address, exc_info=True)
    return res


def _hex32(value: int, descr: Any, datadict: dict[str, Any]) -> str:
    return f"0x{value:08x}"


def _keep_previous_value(initval: Any, descr: Any, datadict: dict[str, Any]) -> Any:
    return datadict.get(descr.key)


@dataclass(kw_only=True, frozen=True)
class ViessmannModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT
    register_type: int = REG_HOLDING
    register_data_type: str = REGISTER_U16


SENSOR_TYPES: list[ViessmannModbusSensorEntityDescription] = [
    ViessmannModbusSensorEntityDescription(
        name="Rated Power",
        key="rated_power",
        register=35001,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Serial Number",
        key="serial_number",
        register=35003,
        register_data_type=REGISTER_STR,
        wordcount=8,
        newblock=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:identifier",
    ),
    ViessmannModbusSensorEntityDescription(
        name="Model",
        key="model",
        register=35011,
        register_data_type=REGISTER_STR,
        wordcount=5,
        newblock=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:solar-power-variant",
    ),
    ViessmannModbusSensorEntityDescription(
        name="PV1 Voltage",
        key="pv_voltage_1",
        register=35103,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="PV1 Current",
        key="pv_current_1",
        register=35104,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="PV1 Power",
        key="pv_power_1",
        register=35105,
        register_data_type=REGISTER_U32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="PV2 Voltage",
        key="pv_voltage_2",
        register=35107,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="PV2 Current",
        key="pv_current_2",
        register=35108,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="PV2 Power",
        key="pv_power_2",
        register=35109,
        register_data_type=REGISTER_U32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Grid Voltage",
        key="grid_voltage",
        register=35121,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Grid Current",
        key="grid_current",
        register=35122,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        register=35123,
        scale=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Grid Power",
        key="grid_power",
        register=35124,
        register_data_type=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Grid Mode",
        key="grid_mode",
        register=35136,
        scale=_GRID_MODE,
        icon="mdi:transmission-tower",
        scan_group=SCAN_GROUP_MEDIUM,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Inverter Power",
        key="inverter_power",
        register=35137,
        register_data_type=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="AC Active Power",
        key="ac_active_power",
        register=35139,
        register_data_type=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Backup Load Power",
        key="backup_load_power",
        register=35169,
        register_data_type=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Load Power",
        key="load_power",
        register=35171,
        register_data_type=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Backup Load Percent",
        key="backup_load_percent",
        register=35173,
        scale=0.01,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Air Temperature",
        key="air_temperature",
        register=35174,
        register_data_type=REGISTER_S16,
        scale=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Heatsink Temperature",
        key="heatsink_temperature",
        register=35176,
        register_data_type=REGISTER_S16,
        scale=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Voltage",
        key="battery_voltage",
        register=35180,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Current",
        key="battery_current",
        register=35181,
        register_data_type=REGISTER_S16,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Power",
        key="battery_power",
        register=35182,
        register_data_type=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Mode",
        key="battery_mode",
        register=35184,
        scale=_BATTERY_MODE,
        icon="mdi:battery-sync",
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Work Mode",
        key="work_mode",
        register=35187,
        scale=_WORK_MODE,
        icon="mdi:state-machine",
        scan_group=SCAN_GROUP_MEDIUM,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Error Message",
        key="error_message",
        register=35189,
        register_data_type=REGISTER_U32,
        scale=_hex32,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="PV Energy Total",
        key="pv_energy_total",
        register=35191,
        register_data_type=REGISTER_U32,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="PV Energy Today",
        key="pv_energy_today",
        register=35193,
        register_data_type=REGISTER_U32,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Runtime Total",
        key="runtime_total",
        register=35197,
        register_data_type=REGISTER_U32,
        native_unit_of_measurement="h",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        scan_group=SCAN_GROUP_MEDIUM,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Grid Export Energy Today",
        key="grid_export_energy_today",
        value_function=_keep_previous_value,
        depends_on=["grid_export_energy_total"],
        _is_daily_delta_sensor=True,
        _daily_delta_source_key="grid_export_energy_total",
        rounding=3,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Grid Import Energy Today",
        key="grid_import_energy_today",
        value_function=_keep_previous_value,
        depends_on=["grid_import_energy_total"],
        _is_daily_delta_sensor=True,
        _daily_delta_source_key="grid_import_energy_total",
        rounding=3,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Load Energy Total",
        key="load_energy_total",
        register=35203,
        register_data_type=REGISTER_U32,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Load Energy Today",
        key="load_energy_today",
        register=35205,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Charge Energy Total",
        key="battery_charge_energy_total",
        register=35206,
        register_data_type=REGISTER_U32,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Charge Energy Today",
        key="battery_charge_energy_today",
        register=35208,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Discharge Energy Total",
        key="battery_discharge_energy_total",
        register=35209,
        register_data_type=REGISTER_U32,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Discharge Energy Today",
        key="battery_discharge_energy_today",
        register=35211,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Meter Communication Status",
        key="meter_communication_status",
        register=36004,
        scale={0: "NG", 1: "OK"},
        icon="mdi:meter-electric-outline",
        scan_group=SCAN_GROUP_MEDIUM,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Meter Active Power",
        key="meter_active_power",
        register=36025,
        register_data_type=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Grid Export Energy Total",
        key="grid_export_energy_total",
        register=36015,
        register_data_type=REGISTER_F32,
        scale=0.001,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scan_group=SCAN_GROUP_MEDIUM,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Grid Import Energy Total",
        key="grid_import_energy_total",
        register=36017,
        register_data_type=REGISTER_F32,
        scale=0.001,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scan_group=SCAN_GROUP_MEDIUM,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="BMS Status",
        key="bms_status",
        register=37002,
        scale=_BMS_STATUS,
        icon="mdi:battery-heart",
        scan_group=SCAN_GROUP_MEDIUM,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery SOC",
        key="battery_soc",
        register=37007,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery SOH",
        key="battery_soh",
        register=37008,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Max Cell Temperature",
        key="battery_max_cell_temperature",
        register=37020,
        scale=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Min Cell Temperature",
        key="battery_min_cell_temperature",
        register=37021,
        scale=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Max Cell Voltage",
        key="battery_max_cell_voltage",
        register=37022,
        native_unit_of_measurement="mV",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Battery Min Cell Voltage",
        key="battery_min_cell_voltage",
        register=37023,
        native_unit_of_measurement="mV",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Configured Modbus Address",
        key="configured_modbus_address",
        register=45127,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:identifier",
        scan_group=SCAN_GROUP_MEDIUM,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Real-time BMS Charge Voltage Limit",
        key="realtime_bms_charge_voltage_limit",
        register=47902,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
        newblock=True,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Real-time BMS Charge Current Limit",
        key="realtime_bms_charge_current_limit",
        register=47903,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Real-time BMS Discharge Voltage Limit",
        key="realtime_bms_discharge_voltage_limit",
        register=47904,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Real-time BMS Discharge Current Limit",
        key="realtime_bms_discharge_current_limit",
        register=47905,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Real-time BMS Battery Voltage",
        key="realtime_bms_battery_voltage",
        register=47906,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Real-time BMS Battery Current",
        key="realtime_bms_battery_current",
        register=47907,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Real-time BMS SOC",
        key="realtime_bms_soc",
        register=47908,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_FAST,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Real-time BMS SOH",
        key="realtime_bms_soh",
        register=47909,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
    ViessmannModbusSensorEntityDescription(
        name="Real-time BMS Temperature",
        key="realtime_bms_temperature",
        register=47910,
        scale=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        scan_group=SCAN_GROUP_MEDIUM,
    ),
]


@dataclass(kw_only=True)
class viessmann_plugin(plugin_base):
    async def async_determineInverterType(self, hub: Any, configdict: dict[str, Any]) -> int:
        serial_number = await _read_string(hub, 35003, 8)
        model = await _read_string(hub, 35011, 5)

        if serial_number:
            hub._seriesnumber = serial_number
        if model:
            self.inverter_model = model

        if not serial_number and not model:
            _LOGGER.error("%s: could not identify Viessmann/GoodWe inverter", hub.name)
            return 0

        _LOGGER.info("%s: detected Viessmann/GoodWe inverter model=%s serial=%s", hub.name, model, serial_number)
        return 1

    def matchInverterWithMask(
        self,
        inverterspec: Any,
        entitymask: Any,
        serialnumber: str = "not relevant",
        blacklist: list[str] | None = None,
    ) -> bool:
        return True

    def getModel(self, new_data: dict[str, Any]) -> str | None:
        return new_data.get("model", self.inverter_model)


plugin_instance = viessmann_plugin(
    plugin_name="Viessmann",
    plugin_manufacturer="Viessmann / GoodWe",
    SENSOR_TYPES=SENSOR_TYPES,
    NUMBER_TYPES=[],
    BUTTON_TYPES=[],
    SELECT_TYPES=[],
    SWITCH_TYPES=[],
    TIME_TYPES=[],
    block_size=8,
    order32="big",
    auto_block_ignore_readerror=True,
)
