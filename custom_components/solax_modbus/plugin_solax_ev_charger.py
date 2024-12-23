import logging
from dataclasses import dataclass
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder, Endian
from custom_components.solax_modbus.const import *
from time import time

_LOGGER = logging.getLogger(__name__)

""" ============================================================================================
bitmasks  definitions to characterize inverters, ogranized by group
these bitmasks are used in entitydeclarations to determine to which inverters the entity applies
within a group, the bits in an entitydeclaration will be interpreted as OR
between groups, an AND condition is applied, so all gruoups must match.
An empty group (group without active flags) evaluates to True.
example: GEN3 | GEN4 | X1 | X3 | EPS
means:  any inverter of tyoe (GEN3 or GEN4) and (X1 or X3) and (EPS)
An entity can be declared multiple times (with different bitmasks) if the parameters are different for each inverter type
"""

GEN = 0x0001  # base generation for MIC, PV, AC
GEN2 = 0x0002
GEN3 = 0x0004
GEN4 = 0x0008
ALL_GEN_GROUP = GEN2 | GEN3 | GEN4 | GEN

X1 = 0x0100
X3 = 0x0200
ALL_X_GROUP = X1 | X3

POW7 = 0x0001
POW11 = 0x0002
POW22 = 0x0004
ALL_POW_GROUP = POW7 | POW11 | POW22

ALLDEFAULT = 0  # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub, address):
    res = None
    try:
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=7)
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(14).decode("ascii")
            hub.seriesnumber = res
    except Exception as ex:
        _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x}", exc_info=True)
    if not res:
        _LOGGER.warning(
            f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed"
        )
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number before potential swap: {res}")
    return res


# =================================================================================================


@dataclass
class SolaXEVChargerModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaXEVChargerModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaXEVChargerModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class SolaXEVChargerModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice
    # order16: int = Endian.BIG
    # order32: int = Endian.LITTLE
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING


# ====================================== Computed value functions  =================================================

# ================================= Button Declarations ============================================================

BUTTON_TYPES = [
    SolaXEVChargerModbusButtonEntityDescription(
        name="Sync RTC",
        key="sync_rtc",
        register=0x61E,
        write_method=WRITE_MULTI_MODBUS,
        icon="mdi:home-clock",
        value_function=value_function_sync_rtc,
    ),
]

# ================================= Number Declarations ============================================================

NUMBER_TYPES = [
    ###
    #
    # Data only number types
    #
    ###
    ###
    #
    #  Normal number types
    #
    ###
    SolaXEVChargerModbusNumberEntityDescription(
        name="Datahub Charge Current",
        key="datahub_charge_current",
        register=0x624,
        fmt="f",
        native_min_value=6,
        native_max_value=32,
        native_step=0.1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
    ),
    SolaXEVChargerModbusNumberEntityDescription(
        name="Charge Current",
        key="charge_current",
        register=0x628,
        fmt="f",
        native_min_value=6,
        native_max_value=32,
        native_step=0.1,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
    ),
]

# ================================= Select Declarations ============================================================

SELECT_TYPES = [
    ###
    #
    #  Data only select types
    #
    ###
    ###
    #
    #  Normal select types
    #
    ###
    SolaXEVChargerModbusSelectEntityDescription(
        name="Meter Setting",
        key="meter_setting",
        register=0x60C,
        option_dict={
            0: "External CT",
            1: "External Meter",
            2: "Inverter",
        },
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:meter-electric",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        register=0x60D,
        option_dict={
            0: "Stop",
            1: "Fast",
            2: "ECO",
            3: "Green",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="ECO Gear",
        key="eco_gear",
        register=0x60E,
        option_dict={
            1: "6A",
            2: "10A",
            3: "16A",
            4: "20A",
            5: "25A",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Green Gear",
        key="green_gear",
        register=0x60F,
        option_dict={
            1: "3A",
            2: "6A",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Start Charge Mode",
        key="start_charge_mode",
        register=0x610,
        option_dict={
            0: "Plug & Charge",
            1: "RFID to Charge",
        },
        icon="mdi:lock",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Boost Mode",
        key="boost_mode",
        register=0x613,
        option_dict={
            0: "Normal",
            1: "Timer Boost",
            2: "Smart Boost",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Device Lock",
        key="device_lock",
        register=0x615,
        option_dict={
            0: "Unlock",
            1: "Lock",
        },
        icon="mdi:lock",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="RFID Program",
        key="rfid_program",
        register=0x616,
        option_dict={
            1: "Program New",
            0: "Program Off",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Charge Phase",
        key="charge_phase",
        register=0x625,
        option_dict={
            0: "Three Phase",
            1: "L1 Phase",
            2: "L2 Phase",
            3: "L3 Phase",
        },
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSelectEntityDescription(
        name="Control Command",
        key="control_command",
        register=0x627,
        option_dict={
            1: "Available",
            2: "Unavailable",
            3: "Stop charging",
            4: "Start Charging",
            5: "Reserve",
            6: "Cancel the Reservation",
        },
        icon="mdi:dip-switch",
    ),
]

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES_MAIN: list[SolaXEVChargerModbusSensorEntityDescription] = [
    ###
    #
    # Holding
    #
    ###
    SolaXEVChargerModbusSensorEntityDescription(
        name="Meter Setting",
        key="meter_setting",
        register=0x60C,
        scale={
            0: "External CT",
            1: "External Meter",
            2: "Inverter",
        },
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:meter-electric",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charger Use Mode",
        key="charger_use_mode",
        register=0x60D,
        scale={
            0: "Stop",
            1: "Fast",
            2: "ECO",
            3: "Green",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="ECO Gear",
        key="eco_gear",
        register=0x60E,
        scale={
            1: "6A",
            2: "10A",
            3: "16A",
            4: "20A",
            5: "25A",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Green Gear",
        key="green_gear",
        register=0x60F,
        scale={
            1: "3A",
            2: "6A",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Start Charge Mode",
        key="start_charge_mode",
        register=0x610,
        scale={
            0: "Plug & Charge",
            1: "RFID to Charge",
        },
        entity_registry_enabled_default=False,
        icon="mdi:lock",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Boost Mode",
        key="boost_mode",
        register=0x613,
        scale={
            0: "Normal",
            1: "Timer Boost",
            2: "Smart Boost",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Device Lock",
        key="device_lock",
        register=0x615,
        scale={
            0: "Unlock",
            1: "Lock",
        },
        entity_registry_enabled_default=False,
        icon="mdi:lock",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="RFID Program",
        key="rfid_program",
        register=0x616,
        scale={
            1: "Program New",
            0: "Program Off",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="RTC",
        key="rtc",
        register=0x61E,
        unit=REGISTER_WORDS,
        wordcount=6,
        scale=value_function_rtc,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:clock",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Datahub Charge Current",
        key="datahub_charge_current",
        register=0x624,
        scale=0.01,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Phase",
        key="charge_phase",
        register=0x625,
        scale={
            0: "Three Phase",
            1: "L1 Phase",
            2: "L2 Phase",
            3: "L3 Phase",
        },
        allowedtypes=X3,
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current",
        key="charge_current",
        register=0x628,
        scale=0.01,
        rounding=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Control Command",
        key="control_command",
        register=0x627,
        scale={
            1: "Available",
            2: "Unavailable",
            3: "Stop charging",
            4: "Start Charging",
            5: "Reserve",
            6: "Cancel the Reservation",
        },
        entity_registry_enabled_default=False,
        icon="mdi:dip-switch",
    ),
    ###
    #
    # Input
    #
    ###
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage",
        key="charge_voltage",
        register=0x0,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        allowedtypes=X1,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage L1",
        key="charge_voltage_l1",
        register=0x0,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage L2",
        key="charge_voltage_l2",
        register=0x1,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Voltage L3",
        key="charge_voltage_l3",
        register=0x2,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge PE Voltage",
        key="charge_pe_voltage",
        register=0x3,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current",
        key="charge_current",
        register=0x4,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X1,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L1",
        key="charge_current_l1",
        register=0x4,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L2",
        key="charge_current_l2",
        register=0x5,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Current L3",
        key="charge_current_l3",
        register=0x6,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge PE Current",
        key="charge_pe_current",
        register=0x7,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        device_class=SensorDeviceClass.CURRENT,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power",
        key="charge_power",
        register=0x8,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X1,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L1",
        key="charge_power_l1",
        register=0x8,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L2",
        key="charge_power_l2",
        register=0x9,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power L3",
        key="charge_power_l3",
        register=0xA,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Power Total",
        key="charge_power_total",
        register=0xB,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency",
        key="charge_frequency",
        register=0xC,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        allowedtypes=X1,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency L1",
        key="charge_frequency_l1",
        register=0xC,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency L2",
        key="charge_frequency_l2",
        register=0xD,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Frequency L3",
        key="charge_frequency_l3",
        register=0xE,
        register_type=REG_INPUT,
        scale=0.01,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Added",
        key="charge_added",
        register=0xF,
        register_type=REG_INPUT,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charge Added Total",
        key="charge_added_total",
        register=0x619,
        register_type=REG_HOLDING,
        unit=REGISTER_U32,
        scale=0.1,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current",
        key="grid_current",
        register=0x12,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X1,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current L1",
        key="grid_current_l1",
        register=0x12,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current L2",
        key="grid_current_l2",
        register=0x13,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Current L3",
        key="grid_current_l3",
        register=0x14,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        scale=0.01,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power",
        key="grid_power",
        register=0x15,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X1,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power L1",
        key="grid_power_l1",
        register=0x15,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power L2",
        key="grid_power_l2",
        register=0x16,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power L3",
        key="grid_power_l3",
        register=0x17,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        allowedtypes=X3,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Grid Power Total",
        key="grid_power_total",
        register=0x18,
        register_type=REG_INPUT,
        unit=REGISTER_S16,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Charger Temperature",
        key="charger_temperature",
        register=0x1C,
        register_type=REG_INPUT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SolaXEVChargerModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        register=0x1D,
        scale={
            0: "Available",
            1: "Preparing",
            2: "Charging",
            3: "Finishing",
            4: "Fault Mode",
            5: "Unavailable",
            6: "Reserved",
            7: "Suspended EV",
            8: "Suspended EVSE",
            9: "Update",
            10: "RFID Activation",
        },
        register_type=REG_INPUT,
        icon="mdi:run",
    ),
]

# ============================ plugin declaration =================================================


@dataclass
class solax_ev_charger_plugin(plugin_base):
    '''
    def isAwake(self, datadict):
        """ determine if inverter is awake based on polled datadict"""
        return (datadict.get('run_mode', None) == 'Normal Mode')

    def wakeupButton(self):
        """ in order to wake up  the inverter , press this button """
        return 'battery_awaken'
    '''

    async def async_determineInverterType(self, hub, configdict):
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber = await async_read_serialnr(hub, 0x600)
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find serial number for EV Charger")
            seriesnumber = "unknown"

        # derive invertertupe from seriiesnumber
        if seriesnumber.startswith("C107"):
            invertertype = X1 | POW7  # 7kW EV Single Phase
        elif seriesnumber.startswith("C311"):
            invertertype = X3 | POW11  # 11kW EV Three Phase
        elif seriesnumber.startswith("C322"):
            invertertype = X3 | POW22  # 22kW EV Three Phase
        # add cases here
        else:
            invertertype = 0
            _LOGGER.error(f"unrecognized inverter type - serial number : {seriesnumber}")
        return invertertype

    def matchInverterWithMask(self, inverterspec, entitymask, serialnumber="not relevant", blacklist=None):
        # returns true if the entity needs to be created for an inverter
        powmatch = ((inverterspec & entitymask & ALL_POW_GROUP) != 0) or (entitymask & ALL_POW_GROUP == 0)
        xmatch = ((inverterspec & entitymask & ALL_X_GROUP) != 0) or (entitymask & ALL_X_GROUP == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist:
                if serialnumber.startswith(start):
                    blacklisted = True
        return (xmatch and powmatch) and not blacklisted


plugin_instance = solax_ev_charger_plugin(
    plugin_name="SolaX EV Charger",
    plugin_manufacturer="SolaX Power",
    SENSOR_TYPES=SENSOR_TYPES_MAIN,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=[],
    block_size=100,
    order16=Endian.BIG,
    order32=Endian.LITTLE,
)
