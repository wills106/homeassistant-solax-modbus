# Verze pluginu: 1.2.5
import logging
from dataclasses import dataclass, replace
from homeassistant.components.number import NumberEntityDescription, NumberDeviceClass
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import (
    UnitOfPower,
    UnitOfEnergy,
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfFrequency,
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

from .payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
from custom_components.solax_modbus.const import *
from time import time
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

# ============================================================================================
# Definuje náš typ střídače
SUNWAY_STT_10KTL = 0x0001
ALLDEFAULT = SUNWAY_STT_10KTL  # Všechny entity se budou vztahovat k našemu střídači
# ============================================================================================

@dataclass
class SunwayModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT

@dataclass
class SunwayModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT

@dataclass
class SunwayModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT

@dataclass
class SunwayModbusSwitchEntityDescription(BaseModbusSwitchEntityDescription):
    allowedtypes: int = ALLDEFAULT

@dataclass
class SunwayModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING

# ====================================== Funkce pro hodnoty ===============================================

def sunway_rtc_function(initval, descr, datadict):
    """Dekóduje RTC čas ze tří registrů pro čtení."""
    try:
        year_month, day_hour, min_sec = initval
        year = (year_month >> 8) + 2000
        month = year_month & 0xFF
        day = day_hour >> 8
        hour = day_hour & 0xFF
        minute = min_sec >> 8
        second = min_sec & 0xFF
        return datetime(year, month, day, hour, minute, second)
    except (ValueError, TypeError):
        return None

def value_function_sync_rtc_sunway(initval, descr, datadict):
    """Vytvoří payload pro zápis RTC času do střídače."""
    now = datetime.now()
    # Formát podle PDF, strana 17, registry 20000-20002
    year_val = now.year % 100
    
    payload_reg1 = (year_val << 8) | now.month
    payload_reg2 = (now.day << 8) | now.hour
    payload_reg3 = (now.minute << 8) | now.second
    
    return [
        (REGISTER_U16, payload_reg1),
        (REGISTER_U16, payload_reg2),
        (REGISTER_U16, payload_reg3),
    ]

# ================================= Tlačítka (Buttons) =======================================================
BUTTON_TYPES = [
    SunwayModbusButtonEntityDescription(
        name="Synchronizovat čas",
        key="sync_rtc",
        register=20000,
        write_method=WRITE_MULTI_MODBUS,
        value_function=value_function_sync_rtc_sunway,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-sync-outline",
    ),
]

# ================================= Čísla (Numbers) ============================================================
NUMBER_TYPES = [
    SunwayModbusNumberEntityDescription(
        name="Grid Injection Power Limit Setting",
        key="grid_injection_power_limit_setting",
        register=25103,
        fmt="f",
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=0.1,
        scale=0.1,
        native_unit_of_measurement=PERCENTAGE,
        device_class=NumberDeviceClass.POWER_FACTOR,
        write_method=WRITE_SINGLE_MODBUS,
        entity_category=EntityCategory.CONFIG,
    ),
    SunwayModbusNumberEntityDescription(
        name="Off-grid Voltage Setting",
        key="off_grid_voltage_setting",
        register=50004,
        fmt="f",
        native_min_value=200.0,
        native_max_value=250.0,
        native_step=0.1,
        scale=0.1,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=NumberDeviceClass.VOLTAGE,
        write_method=WRITE_SINGLE_MODBUS,
        entity_category=EntityCategory.CONFIG,
    ),
    SunwayModbusNumberEntityDescription(
        name="Off-grid Frequency Setting",
        key="off_grid_frequency_setting",
        register=50005,
        fmt="f",
        native_min_value=45.00,
        native_max_value=65.00,
        native_step=0.01,
        scale=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=NumberDeviceClass.FREQUENCY,
        write_method=WRITE_SINGLE_MODBUS,
        entity_category=EntityCategory.CONFIG,
    ),
    SunwayModbusNumberEntityDescription(
        name="Max Grid Power Value Setting",
        key="max_grid_power_value_setting",
        register=50009,
        fmt="f",
        native_min_value=0,
        native_max_value=20, 
        native_step=0.1,
        scale=0.1,
        native_unit_of_measurement="kVA", 
        device_class=NumberDeviceClass.APPARENT_POWER,
        write_method=WRITE_SINGLE_MODBUS,
        entity_category=EntityCategory.CONFIG,
    ),
    SunwayModbusNumberEntityDescription(
        name="PV Power Setting",
        key="pv_power_setting",
        register=50211,
        fmt="i",
        native_min_value=0,
        native_max_value=20000,
        native_step=100,
        scale=1,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        write_method=WRITE_SINGLE_MODBUS,
        entity_category=EntityCategory.CONFIG,
    ),
    SunwayModbusNumberEntityDescription(
        name="On-grid Battery DOD",
        key="on_grid_battery_dod",
        register=52503,
        fmt="f",
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=0.1,
        scale=0.1,
        native_unit_of_measurement=PERCENTAGE,
        write_method=WRITE_SINGLE_MODBUS,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-arrow-down",
    ),
    SunwayModbusNumberEntityDescription(
        name="Off-grid Battery DOD",
        key="off_grid_battery_dod",
        register=52505,
        fmt="f",
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=0.1,
        scale=0.1,
        native_unit_of_measurement=PERCENTAGE,
        write_method=WRITE_SINGLE_MODBUS,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-arrow-down-outline",
    ),
]

# ================================= Výběry (Selects) ==========================================================
SELECT_TYPES = [
    SunwayModbusSelectEntityDescription(
        name="Hybrid Inverter Working Mode",
        key="hybrid_inverter_working_mode",
        register=50000,
        option_dict={
            1: "General Mode",
            2: "Economic Mode",
            3: "UPS Mode",
            258: "EMS General Mode",
            259: "EMS ACCtrlMode",
            513: "EMS BattCtrlMode",
            772: "EMS OffGridMode"
        },
        entity_category=EntityCategory.CONFIG,
    ),
    SunwayModbusSelectEntityDescription(
        name="Inverter AC Power Setting Mode",
        key="inverter_ac_power_setting_mode",
        register=50202,
        option_dict={
            0: "Off",
            1: "Total Power Setting",
            2: "Power on each Phase Setting"
        },
        entity_category=EntityCategory.CONFIG,
    ),
    SunwayModbusSelectEntityDescription(
        name="Priority Power Output Setting",
        key="priority_power_output_setting",
        register=50210,
        option_dict={
            0: "PV Output Priority",
            1: "Battery Output Priority",
        },
        entity_category=EntityCategory.CONFIG,
    ),
]

# ================================= Přepínače (Switches) ========================================================
SWITCH_TYPES = [
    SunwayModbusSwitchEntityDescription(
        name="Grid Injection Power Limit",
        key="grid_injection_power_limit_switch",
        register=25100,
        write_method=WRITE_SINGLE_MODBUS,
        register_bit=0,
        value_function=lambda bit, state, sk, d: 1 if state else 0,
        sensor_key="grid_injection_power_limit_switch_state",
    ),
    SunwayModbusSwitchEntityDescription(
        name="EPS UPS Function",
        key="eps_ups_function_switch",
        register=50001,
        write_method=WRITE_SINGLE_MODBUS,
        register_bit=0,
        value_function=lambda bit, state, sk, d: 1 if state else 0,
        sensor_key="eps_ups_function_switch_state",
    ),
    SunwayModbusSwitchEntityDescription(
        name="Off-grid Asymmetric Output",
        key="off_grid_asymmetric_output_switch",
        register=50006,
        write_method=WRITE_SINGLE_MODBUS,
        register_bit=0,
        value_function=lambda bit, state, sk, d: 1 if state else 0,
        sensor_key="off_grid_asymmetric_output_switch_state",
    ),
    SunwayModbusSwitchEntityDescription(
        name="Peak Load Shifting",
        key="peak_load_shifting_switch",
        register=50007,
        write_method=WRITE_SINGLE_MODBUS,
        register_bit=0,
        value_function=lambda bit, state, sk, d: 1 if state else 0,
        sensor_key="peak_load_shifting_switch_state",
    ),
    SunwayModbusSwitchEntityDescription(
        name="On-grid Battery SOC Protection",
        key="on_grid_battery_soc_protection_switch",
        register=52502,
        write_method=WRITE_SINGLE_MODBUS,
        register_bit=0,
        value_function=lambda bit, state, sk, d: 1 if state else 0,
        sensor_key="on_grid_battery_soc_protection_switch_state",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-lock",
    ),
    SunwayModbusSwitchEntityDescription(
        name="Off-grid Battery SOC Protection",
        key="off_grid_battery_soc_protection_switch",
        register=52504,
        write_method=WRITE_SINGLE_MODBUS,
        register_bit=0,
        value_function=lambda bit, state, sk, d: 1 if state else 0,
        sensor_key="off_grid_battery_soc_protection_switch_state",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-lock-outline",
    ),
]


# ================================= Senzory (Sensors) ============================================================
SENSOR_TYPES = [
    # ---------- Pomocné senzory pro přepínače ----------
    SunwayModbusSensorEntityDescription(
        key="grid_injection_power_limit_switch_state",
        register=25100,
        internal=True,
    ),
    SunwayModbusSensorEntityDescription(
        key="eps_ups_function_switch_state",
        register=50001,
        internal=True,
    ),
    SunwayModbusSensorEntityDescription(
        key="off_grid_asymmetric_output_switch_state",
        register=50006,
        internal=True,
    ),
    SunwayModbusSensorEntityDescription(
        key="peak_load_shifting_switch_state",
        register=50007,
        internal=True,
    ),
    SunwayModbusSensorEntityDescription(
        key="on_grid_battery_soc_protection_switch_state",
        register=52502,
        internal=True,
    ),
    SunwayModbusSensorEntityDescription(
        key="off_grid_battery_soc_protection_switch_state",
        register=52504,
        internal=True,
    ),

    # ---------- Informace o střídači (RO - Read Only) ----------
    SunwayModbusSensorEntityDescription(
        name="Inverter SN",
        key="inverter_sn",
        register=10000,
        unit=REGISTER_STR,
        wordcount=4,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="Firmware Version",
        key="firmware_version",
        register=10011,
        unit=REGISTER_U16,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="RTC",
        key="rtc",
        register=10100,
        unit=REGISTER_WORDS,
        wordcount=3,
        scale=sunway_rtc_function,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:clock",
    ),
    SunwayModbusSensorEntityDescription(
        name="Inverter Running Status",
        key="inverter_running_status",
        register=10105,
        scale={0: "Wait", 1: "Check", 2: "On Grid", 3: "Fault", 4: "Flash (Firmware Update)", 5: "Off Grid"},
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="Equipment Info",
        key="equipment_info",
        register=10008,
        scale=lambda val, desc, data: {(0x30, 0): "WTS-4KW-3P", (0x31, 0): "N/A", (0x30, 1): "WTS-5KW-3P", (0x31, 1): "N/A", (0x30, 2): "WTS-6KW-3P", (0x31, 2): "WTS-4.2KW-1P", (0x30, 3): "WTS-8KW-3P", (0x31, 3): "WTS-4.6KW-1P", (0x30, 4): "WTS-10KW-3P", (0x31, 4): "WTS-5KW-1P", (0x30, 5): "WTS-12KW-3P", (0x31, 5): "WTS-6KW-1P", (0x30, 6): "N/A", (0x31, 6): "WTS-7KW-1P", (0x30, 7): "N/A", (0x31, 7): "WTS-8KW-1P", (0x30, 8): "N/A", (0x31, 8): "WTS-3KW-1P", (0x30, 9): "N/A", (0x31, 9): "WTS-3.6KW-1P",}.get(((val >> 8), (val & 0xFF)), "Unknown"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="Fault FLAG1",
        key="fault_flag_1",
        register=10112,
        unit=REGISTER_U32,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="ARM Fault FLAG1",
        key="arm_fault_flag_1",
        register=18000,
        unit=REGISTER_U32,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    # ---------- Měření ze sítě (Meter) ----------
    SunwayModbusSensorEntityDescription(
        name="Phase A Power on Meter",
        key="phase_a_power_on_meter",
        register=10994,
        unit=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scale=1,
        rounding=0,
    ),
    SunwayModbusSensorEntityDescription(
        name="Phase B Power on Meter",
        key="phase_b_power_on_meter",
        register=10996,
        unit=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scale=1,
        rounding=0,
    ),
    SunwayModbusSensorEntityDescription(
        name="Phase C Power on Meter",
        key="phase_c_power_on_meter",
        register=10998,
        unit=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scale=1,
        rounding=0,
    ),
    SunwayModbusSensorEntityDescription(
        name="Total Power on Meter",
        key="total_power_on_meter",
        register=11000,
        unit=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scale=1,
        rounding=0,
    ),
    SunwayModbusSensorEntityDescription(
        name="Total Grid Injection Energy on Meter",
        key="total_grid_injection_energy",
        register=11002,
        unit=REGISTER_U32,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.01,
        rounding=2,
        icon="mdi:home-export-outline",
    ),
    SunwayModbusSensorEntityDescription(
        name="Total Purchasing Energy from Grid on Meter",
        key="total_purchasing_energy",
        register=11004,
        unit=REGISTER_U32,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.01,
        rounding=2,
        icon="mdi:home-import-outline",
    ),
    
    # ---------- Síťové hodnoty ----------
    SunwayModbusSensorEntityDescription(
        name="Grid Phase A Voltage",
        key="grid_phase_a_voltage",
        register=11009,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Grid Phase A Current",
        key="grid_phase_a_current",
        register=11010,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Grid Phase B Voltage",
        key="grid_phase_b_voltage",
        register=11011,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Grid Phase B Current",
        key="grid_phase_b_current",
        register=11012,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Grid Phase C Voltage",
        key="grid_phase_c_voltage",
        register=11013,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Grid Phase C Current",
        key="grid_phase_c_current",
        register=11014,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency",
        register=11015,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.01,
        rounding=2,
    ),
    SunwayModbusSensorEntityDescription(
        name="AC Power",
        key="ac_power",
        register=11016,
        unit=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scale=1,
        rounding=0,
    ),

    # ---------- PV hodnoty ----------
    SunwayModbusSensorEntityDescription(
        name="Total PV Generation Today",
        key="total_pv_generation_today",
        register=11018,
        unit=REGISTER_U32,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Total PV Generation Since Installation",
        key="total_pv_generation_since_installation",
        register=11020,
        unit=REGISTER_U32,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="PV Input Total Power",
        key="pv_input_total_power",
        register=11028,
        unit=REGISTER_U32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scale=1,
        rounding=0,
    ),
    SunwayModbusSensorEntityDescription(
        name="PV1 Voltage",
        key="pv1_voltage",
        register=11038,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="PV1 Current",
        key="pv1_current",
        register=11039,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="PV1 Input Power",
        key="pv1_input_power",
        register=11062,
        unit=REGISTER_U32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scale=1,
        rounding=0,
    ),
    SunwayModbusSensorEntityDescription(
        name="PV2 Voltage",
        key="pv2_voltage",
        register=11040,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="PV2 Current",
        key="pv2_current",
        register=11041,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="PV2 Input Power",
        key="pv2_input_power",
        register=11064,
        unit=REGISTER_U32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scale=1,
        rounding=0,
    ),
    
    # ---------- Backup / EPS hodnoty ----------
    SunwayModbusSensorEntityDescription(
        name="Backup A Voltage",
        key="backup_a_voltage",
        register=40200,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Backup A Current",
        key="backup_a_current",
        register=40201,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Backup A Power",
        key="backup_a_power",
        register=40204,
        unit=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        scale=1,
        rounding=0,
    ),
    SunwayModbusSensorEntityDescription(
        name="Total Backup Power",
        key="total_backup_power",
        register=40230,
        unit=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        scale=1,
        rounding=0,
    ),

    # ---------- Baterie ----------
    SunwayModbusSensorEntityDescription(
        name="Battery Voltage",
        key="battery_voltage",
        register=40254,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Battery Current",
        key="battery_current",
        register=40255,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.1,
        rounding=1,
    ),
    SunwayModbusSensorEntityDescription(
        name="Battery Mode",
        key="battery_mode",
        register=40256,
        scale={0: "Discharge", 1: "Charge"},
    ),
    SunwayModbusSensorEntityDescription(
        name="Battery Power",
        key="battery_power",
        register=40258,
        unit=REGISTER_S32,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        scale=1,
        rounding=0,
    ),
    SunwayModbusSensorEntityDescription(
        name="Battery SOC",
        key="battery_soc",
        register=43000,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.01,
        rounding=0,
    ),
    SunwayModbusSensorEntityDescription(
        name="Battery SOH",
        key="battery_soh",
        register=43001,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        scale=0.01,
        rounding=0,
        icon="mdi:battery-heart",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="Total Energy Charged to Battery",
        key="total_energy_charged_to_battery",
        register=41108,
        unit=REGISTER_U32,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.1,
        rounding=1,
        icon="mdi:battery-arrow-up",
    ),
    SunwayModbusSensorEntityDescription(
        name="Total Energy Discharged from Battery",
        key="total_energy_discharged_from_battery",
        register=41110,
        unit=REGISTER_U32,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        scale=0.1,
        rounding=1,
        icon="mdi:battery-arrow-down",
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Battery Type",
        key="bms_battery_type",
        register=42000,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Battery Strings",
        key="bms_battery_strings",
        register=42001,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Protocol",
        key="bms_protocol",
        register=42002,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Software Version",
        key="bms_software_version",
        register=42003,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Hardware Version",
        key="bms_hardware_version",
        register=42004,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Max Charge Current",
        key="bms_max_charge_current",
        register=42005,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Max Discharge Current",
        key="bms_max_discharge_current",
        register=42006,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Status",
        key="bms_status",
        register=43002,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Pack Temperature",
        key="bms_pack_temperature",
        register=43003,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Max Cell Temperature",
        key="bms_max_cell_temperature",
        register=43009,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Min Cell Temperature",
        key="bms_min_cell_temperature",
        register=43011,
        scale=0.1,
        rounding=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Max Cell Voltage",
        key="bms_max_cell_voltage",
        register=43013,
        scale=0.001,
        rounding=3,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Min Cell Voltage",
        key="bms_min_cell_voltage",
        register=43015,
        scale=0.001,
        rounding=3,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Error Code",
        key="bms_error_code",
        register=43016,
        unit=REGISTER_U32,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SunwayModbusSensorEntityDescription(
        name="BMS Warn Code",
        key="bms_warn_code",
        register=43018,
        unit=REGISTER_U32,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]

# ============================ plugin declaration =================================================

@dataclass
class sunway_plugin(plugin_base):

    def isAwake(self, datadict):
        """Určuje, zda je střídač v aktivním stavu."""
        run_mode = datadict.get("inverter_running_status")
        return run_mode in ("On Grid", "Off Grid")

    async def async_determineInverterType(self, hub, configdict):
        _LOGGER.info(f"{hub.name}: trying to determine SunWay inverter type")
        
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=10000, count=4)
        
        if inverter_data.isError():
            _LOGGER.error(f"{hub.name}: could not read serial number from address 10000. Please check connection and Modbus address.")
            return 0
            
        decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
        seriesnumber = decoder.decode_string(8).decode("ascii").strip()
        hub.seriesnumber = seriesnumber
        _LOGGER.info(f"{hub.name}: Inverter serial number: {seriesnumber}")

        if seriesnumber:
            self.inverter_model = "STT-10KTL"
            return SUNWAY_STT_10KTL
        else:
            _LOGGER.error(f"{hub.name}: could not determine inverter type, serial number is empty.")
            return 0

    def matchInverterWithMask(self, inverterspec, entitymask, serialnumber="not relevant", blacklist=None):
        return (inverterspec & entitymask) != 0

    def getSoftwareVersion(self, new_data):
        raw_version = new_data.get("firmware_version")
        if raw_version is not None:
             # Formát verze je dle dokumentace na uživateli, zkusíme jednoduché zobrazení
             return str(raw_version)
        return None

    def getHardwareVersion(self, new_data):
        return None

plugin_instance = sunway_plugin(
    plugin_name="SunWay",
    plugin_manufacturer="SunWay",
    SENSOR_TYPES=SENSOR_TYPES,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=SWITCH_TYPES,
    block_size=100,
    order16=Endian.BIG,
    order32=Endian.BIG,
    auto_block_ignore_readerror=True,
)
