import logging
from dataclasses import dataclass, replace

from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.entity import EntityCategory

from custom_components.solax_modbus.const import (
    _LOGGER,
    CONF_READ_DCB,
    CONF_READ_EPS,
    CONF_READ_PM,
    DEFAULT_READ_DCB,
    DEFAULT_READ_EPS,
    DEFAULT_READ_PM,
    REG_HOLDING,
    REGISTER_F32,
    REGISTER_U16,
    REGISTER_U32,
    WRITE_SINGLE_MODBUS,
    BaseModbusButtonEntityDescription,
    BaseModbusNumberEntityDescription,
    BaseModbusSelectEntityDescription,
    BaseModbusSensorEntityDescription,
    BaseModbusSwitchEntityDescription,
    plugin_base,
)

from .pymodbus_compat import DataType, convert_from_registers

_LOGGER = logging.getLogger(__name__)

""" ============================================================================================
bitmasks  definitions to characterize inverters, ogranized by group
these bitmasks are used in entitydeclarations to determine to which inverters the entity applies
within a group, the bits in an entitydeclaration will be interpreted as OR
between groups, an AND condition is applied, so all gruoups must match.
An empty group (group without active flags) evaluates to True.
example: GEN3 | GEN4 | X1 | X3 | EPS
means:  any inverter of type (GEN3 or GEN4) and (X1 or X3) and (EPS)
An entity can be declared multiple times (with different bitmasks) if the parameters are different for each inverter type
"""

GEN = 0x0001  # base generation for MIC, PV, AC
GEN2 = 0x0002
GEN3 = 0x0004
GEN4 = 0x0008
ALL_GEN_GROUP = GEN | GEN2 | GEN3 | GEN4

X1 = 0x0100
X3 = 0x0200
ALL_X_GROUP = X1 | X3

PV = 0x0400  # Needs further work on PV Only Inverters
AC = 0x0800
HYBRID = 0x1000
MIC = 0x2000
ALL_TYPE_GROUP = PV | AC | HYBRID | MIC

EPS = 0x8000
ALL_EPS_GROUP = EPS

DCB = 0x10000  # dry contact box - gen4
ALL_DCB_GROUP = DCB

PM = 0x20000
ALL_PM_GROUP = PM

ALLDEFAULT = 0  # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================


async def async_read_serialnr(hub, address):
    res = None
    try:
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=4)
        if not inverter_data.isError():
            raw = convert_from_registers(inverter_data.registers[0:4], DataType.STRING, "big")
            res = raw.decode("ascii", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
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
class EnertechModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class EnertechModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class EnertechModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT  # maybe 0x0000 (nothing) is a better default choice


@dataclass
class EnertechModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT  # Default allowed types
    unit: int = REGISTER_U16  # Default unit (16-bit)
    register_type: int = REG_HOLDING  # Holding register type
    order32: str = "big"  # Default 32-bit endianness

    def __init__(self, *args, order32="big", **kwargs):
        super().__init__(*args, **kwargs)
        self.order32 = order32  # Assign order32


@dataclass
class EnertechModbusSwitchEntityDescription(BaseModbusSwitchEntityDescription):
    """Base class for Enertech Modbus switch entities."""

    register_bit: int = None  # Bit position in the register
    write_method: int = WRITE_SINGLE_MODBUS  # Default write method


# ====================================== Computed value functions  =================================================
"""
def value_function_remotecontrol_recompute(initval, descr, datadict):
    power_control  = datadict.get('remotecontrol_power_control', "Disabled")
    set_type       = datadict.get('remotecontrol_set_type', "Set") # other options did not work
    target         = datadict.get('remotecontrol_active_power', 0)
    reactive_power = datadict.get('remotecontrol_reactive_power', 0)
    rc_duration    = datadict.get('remotecontrol_duration', 20)
    ap_up          = datadict.get('active_power_upper', 0)
    ap_lo          = datadict.get('active_power_lower', 0)
    reap_up        = datadict.get('reactive_power_upper', 0)
    reap_lo        = datadict.get('reactive_power_lower', 0)
    import_limit   = datadict.get('remotecontrol_import_limit', 20000)
    meas           = datadict.get('measured_power', 0)
    pv             = datadict.get('pv_power_total', 0)
    houseload_nett = datadict.get('inverter_load', 0) - meas
    houseload_brut = pv - datadict.get('battery_power_charge', 0) - meas
    if   power_control == "Enabled Power Control":
        ap_target = target
    elif power_control == "Enabled Grid Control": # alternative computation for Power Control
        if target <0 : ap_target = target - houseload_nett # subtract house load
        else:          ap_target = target - houseload_brut
        power_control = "Enabled Power Control"
    elif power_control == "Enabled Self Use": # alternative computation for Power Control
        ap_target = 0 - houseload_nett # subtract house load
        power_control = "Enabled Power Control"
    elif power_control == "Enabled Battery Control": # alternative computation for Power Control
        ap_target = target - pv # subtract house load and pv
        power_control = "Enabled Power Control"
    elif power_control == "Enabled Feedin Priority": # alternative computation for Power Control
        if pv > houseload_nett:  ap_target = 0 - pv + (houseload_brut - houseload_nett)*1.20  # 0 - pv + (houseload_brut - houseload_nett)
        else:                    ap_target = 0 - houseload_nett
        power_control = "Enabled Power Control"
    elif power_control == "Enabled No Discharge": # alternative computation for Power Control
        if pv <= houseload_nett: ap_target = 0 - pv + (houseload_brut - houseload_nett) # 0 - pv + (houseload_brut - houseload_nett)
        else:                    ap_target = 0 - houseload_nett
        power_control = "Enabled Power Control"
    elif power_control == "Disabled":
        ap_target = target
        autorepeat_duration = 10 # or zero - stop autorepeat since it makes no sense when disabled
    old_ap_target = ap_target
    ap_target = min(ap_target,  import_limit - houseload_brut)
    #_LOGGER.warning(f"peak shaving: old_ap_target:{old_ap_target} new ap_target:{ap_target} max: {import_limit-houseload} min:{-export_limit-houseload}")
    if  old_ap_target != ap_target:
        _LOGGER.debug(f"peak shaving: old_ap_target:{old_ap_target} new ap_target:{ap_target} max: {import_limit-houseload_brut}")
    res =  [ ('remotecontrol_power_control',  power_control, ),
             ('remotecontrol_set_type',       set_type, ),
             ('remotecontrol_active_power',   max(min(ap_up, ap_target),   ap_lo), ),
             ('remotecontrol_reactive_power', max(min(reap_up, reactive_power), reap_lo), ),
             ('remotecontrol_duration',       rc_duration, ),
           ]
    if (power_control == "Disabled"): autorepeat_stop(datadict, descr.key)
    _LOGGER.debug(f"Evaluated remotecontrol_trigger: corrected/clamped values: {res}")
    return res

def value_function_remotecontrol_autorepeat_remaining(initval, descr, datadict):
    return autorepeat_remaining(datadict, 'remotecontrol_trigger', time())

# for testing prevent_update only
#def value_function_test_prevent(initval, descr, datadict):
#    _LOGGER.warning(f"succeeded test prevent_update - datadict: {datadict['dummy_timed_charge_start_h']}")
#    return  None
"""

# ================================= Button Declarations ============================================================

BUTTON_TYPES = []

# ================================= Number Declarations ============================================================

NUMBER_TYPES = [
    EnertechModbusNumberEntityDescription(
        name="DIESEL GENERATOR Start Voltage (V)",
        key="DIESEL_GENERATOR_Start_Voltage",
        register=0x199,
        unit=REGISTER_U16,
        # register_type = REG_HOLDING,
        native_min_value=10,
        native_max_value=100,
        native_step=1,
        fmt="i",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        write_method=WRITE_SINGLE_MODBUS,
        icon="mdi:battery-10",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    EnertechModbusNumberEntityDescription(
        name="Grid/DIESEL GENERATOR Current Limit",
        key="Grid_DIESEL_GENERATOR_Current_Limit",
        register=0x197,
        unit=REGISTER_U16,
        # register_type = REG_HOLDING,
        native_min_value=10,
        native_max_value=100,
        native_step=1,
        fmt="i",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        write_method=WRITE_SINGLE_MODBUS,
        icon="mdi:battery-10",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    EnertechModbusNumberEntityDescription(
        name="DIESEL GENERATOR Run time (Min)",
        key="DIESEL_GENERATOR_Run_time",
        register=0x198,
        unit=REGISTER_U16,
        # register_type = REG_HOLDING,
        native_min_value=10,
        native_max_value=300,
        native_step=1,
        fmt="i",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.VOLTAGE,
        write_method=WRITE_SINGLE_MODBUS,
        icon="mdi:battery-10",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
]


async def async_update(self):
    """Fetch the current value from the Modbus register."""
    value = await self._hub.read_register(self._description["register"])
    if value is not None:
        self._attr_native_value = value
    self.async_write_ha_state()


# ================================= Select Declarations ============================================================

SELECT_TYPES = [
    ###
    #
    #  Data only select types
    #
    ###
    EnertechModbusSelectEntityDescription(
        name="Inverter Mode",
        key="Inverter Mode",
        unit=REGISTER_U16,
        # register_type = REG_HOLDING,
        write_method=WRITE_SINGLE_MODBUS,
        register=0x1A5,  # Modbus register address
        option_dict={
            1: "Saving Mode",
            2: "Backup Mode",  # battery charge level in absence of PV
            3: "Export Mode",  # grid import level in absence of PV
            4: "Battery Less",  # battery import without PV
            5: "Remote Control",  # self-consumption mode
        },
        initvalue="Export Mode",
        icon="mdi:transmission-tower",
    ),
]

SWITCH_TYPES = [
    EnertechModbusSwitchEntityDescription(
        name="Force DIESEL GENERATOR Start/Stop",
        key="force_diesel_generator_start_stop",
        register=0x196,  # Register address
        register_bit=0,  # Bit position (0 for bit 0)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    # DIESEL GENERATOR start auto/manual (bit 1)
    EnertechModbusSwitchEntityDescription(
        name="DIESEL GENERATOR Start Auto/Manual",
        key="diesel_generator_start_auto_manual",
        register=0x196,  # Register address
        register_bit=1,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Inverter Reset/NO Action",
        key="inverter_reset",
        register=0x196,  # Register address
        register_bit=2,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Inverter start/stop",
        key="inverter_start_stop",
        register=0x196,  # Register address
        register_bit=3,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Buzzer Disable",
        key="buzzer_disable",
        register=0x196,  # Register address
        register_bit=4,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Emergency Off",
        key="emergency_off",
        register=0x196,  # Register address
        register_bit=5,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="MPPT1 ON/OFF",
        key="MPPT1_on_off",
        register=0x196,  # Register address
        register_bit=6,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="MPPT2 ON/OFF",
        key="MPPT2_on_off",
        register=0x196,  # Register address
        register_bit=7,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="MPPT3 ON/OFF",
        key="MPPT3_on_off",
        register=0x196,  # Register address
        register_bit=8,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Grid charging On/Off",
        key="grid_charging_on_off",
        register=0x196,  # Register address
        register_bit=9,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Export On/Off",
        key="export_on_off",
        register=0x196,  # Register address
        register_bit=10,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Battery Test",
        key="battery_test",
        register=0x196,  # Register address
        register_bit=11,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Manual Equalize",
        key="manual_equalize",
        register=0x196,  # Register address
        register_bit=12,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Force Bypass Transfer",
        key="force_bypass_transfer",
        register=0x196,  # Register address
        register_bit=13,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Auto restart Enable/Disable",
        key="auto_restart_enable_disable",
        register=0x196,  # Register address
        register_bit=14,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    EnertechModbusSwitchEntityDescription(
        name="Spare 3",
        key="spare_3",
        register=0x196,  # Register address
        register_bit=15,  # Bit position (1 for bit 1)
        write_method=WRITE_SINGLE_MODBUS,
        allowedtypes=ALLDEFAULT,
        icon="mdi:engine",
    ),
    # Add more switches for other bits as needed
]
# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES_MAIN: list[EnertechModbusSensorEntityDescription] = [
    ###
    #
    # Holding
    #
    ###
    EnertechModbusSensorEntityDescription(
        name="Battery Capacity",
        key="battery_capacity_charge",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x133,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Load %",
        key="Load",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        register=0x12F,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Output PF",
        key="Output_PF",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER_FACTOR,
        register=0x12D,
        allowedtypes=ALLDEFAULT,
        scale=0.01,
    ),
    EnertechModbusSensorEntityDescription(
        name="Input PF",
        key="Input_PF",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER_FACTOR,
        register=0x119,
        allowedtypes=ALLDEFAULT,
        scale=0.01,
    ),
    EnertechModbusSensorEntityDescription(
        name="Battery Voltage",
        key="battery_voltage",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x130,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Battery Current",
        key="battery_current",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x135,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
        icon="mdi:current-dc",
    ),
    EnertechModbusSensorEntityDescription(
        name="Battery Current In",
        key="battery_current_in",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x134,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
        icon="mdi:current-dc",
    ),
    EnertechModbusSensorEntityDescription(
        name="PV Voltage 1",
        key="pv_voltage_1",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x13B,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="PV Current 1",
        key="pv_current_1",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x13C,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
        icon="mdi:current-dc",
    ),
    EnertechModbusSensorEntityDescription(
        name="Solar Power 1",
        key="Solar_power_1",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x146,
        unit=REGISTER_U32,
        register_type=REG_HOLDING,
        wordcount=2,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
        order32="big",
        icon="mdi:solar-power-variant",
    ),
    # ================================= declare not found ============================================================
    # EnertechModbusSensorEntityDescription(
    # name = "Charger State",
    #  key = "charger_state",
    #  register = 0x10B,
    # scale = { 0: "Charger Off",
    #    1: "Quick Charge",
    #    2: "Constant Voltage Charge",
    #   4: "Float Charge",
    # 5: "Reserved 1",
    # 6: "Lithium Battery Active",
    # 7: "Reserved 2", },
    # allowedtypes = ALLDEFAULT,
    # icon = "mdi:dip-switch",
    #  ),
    # ================================= declare not found ============================================================
    # EnertechModbusSensorEntityDescription(
    #  name = "Battery Power",
    # key = "battery_power",
    # native_unit_of_measurement = UnitOfPower.WATT,
    #  device_class = SensorDeviceClass.POWER,
    # state_class = SensorStateClass.MEASUREMENT,
    # register = 0x10E,
    # unit = REGISTER_S16,
    # allowedtypes = ALLDEFAULT,
    # ),
    # ================================= declare not found ============================================================
    EnertechModbusSensorEntityDescription(
        name="PV Voltage 2",
        key="pv_voltage_2",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x13D,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="PV Current 2",
        key="pv_current_2",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x13E,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
        icon="mdi:current-dc",
    ),
    EnertechModbusSensorEntityDescription(
        name="PV Power 2",
        key="pv_power_2",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x142,
        allowedtypes=ALLDEFAULT,
        icon="mdi:solar-power-variant",
    ),
    EnertechModbusSensorEntityDescription(
        name="Run Mode",
        key="run_mode",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        register=0x10F,
        scale={
            1: "Saving Mode",
            2: "Back Mode",
            3: "Export Mode",
            4: "Battery Less",
            5: "Remote Control",
        },
        allowedtypes=ALLDEFAULT,
        icon="mdi:run",
    ),
    EnertechModbusSensorEntityDescription(
        name="Grid Voltage R",
        key="grid_voltage_meter_l1",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x111,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Grid Voltage Y",
        key="grid_voltage_meter_l2",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x112,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Grid Voltage B",
        key="grid_voltage_meter_l3",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x113,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Grid Current R",
        key="grid_current_l1",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x114,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Grid Current Y",
        key="grid_current_l2",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x115,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Grid Current B",
        key="grid_current_l3",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x116,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Grid Frequency",
        key="grid_frequency_l1",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x11A,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Output Frequency",
        key="Output_frequency",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x12E,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Inverter Voltage R",
        key="inverter_voltage_meter_l1",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x11B,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Inverter Voltage Y",
        key="inverter_voltage_meter_l2",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x11C,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Inverter Voltage B",
        key="inverter_voltage_meter_l3",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x11D,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Inverter Current R",
        key="inverter_current_11",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x11E,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Inverter Current Y",
        key="inverter_current_Y",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x11F,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Inverter Current B",
        key="inverter_current_B",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x120,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Inverter Frequency",
        key="inverter_frequency_l1",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x124,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Load Current R",
        key="load_current_R",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x128,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Load Current Y",
        key="load_current_Y",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x129,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Load Current B",
        key="load_current_B",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        register=0x12A,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="DC-DC Temperature",
        key="dc_dc_temperature",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x136,
        scale=1,
        allowedtypes=ALLDEFAULT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EnertechModbusSensorEntityDescription(
        name="DC-AC Temperature",
        key="dc_ac_temperature",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x169,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EnertechModbusSensorEntityDescription(
        name="Translator Temperature",
        key="translator_temperature",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x222,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EnertechModbusSensorEntityDescription(
        name="Battery Charge PV",
        key="battery_charge_pv",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        register=0x224,
        scale=0.1,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Output Voltage R",
        key="Output_voltage_meter_l1",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x125,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Output Voltage Y",
        key="Output_voltage_meter_l2",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x126,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Output Voltage B",
        key="Output_voltage_meter_l3",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        register=0x127,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Total Inverter run time",
        key="Total_Inverter_run_time",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        register=0x15F,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Total Bypass run time",
        key="Total_Bypass_run_time",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        register=0x160,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Total Grid fail hour",
        key="Total_Grid_fail_hour",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        register=0x161,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Total Grid fail Minutes",
        key="Total_Grid_fail_MINUTES",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        register=0x162,
        allowedtypes=ALLDEFAULT,
    ),
    EnertechModbusSensorEntityDescription(
        name="Total Grid IMP kWh - 1",
        key="Grid_IMP_kwh_1",
        unit=REGISTER_F32,  # Change from REGISTER_U16 to REGISTER_F32
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x152,
        wordcount=2,  # Add this line for 32-bit float
        scale=1,  # Adjust scaling factor if needed
        allowedtypes=ALLDEFAULT,
        icon="mdi:solar-power-variant",
    ),
    EnertechModbusSensorEntityDescription(
        name="Total Grid Export Kwh - 1",
        key="Grid_Export_kwh_1",
        unit=REGISTER_F32,
        register_type=REG_HOLDING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        register=0x154,
        wordcount=2,
        scale=1,
        allowedtypes=ALLDEFAULT,
        icon="mdi:solar-power-variant",
    ),
    # ============================ Enertech Extras Stats Here =================================================
    EnertechModbusSensorEntityDescription(
        name="MPPT Mode",
        key="info_MPPT_Mode",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        register=0x10E,
        scale={
            1: "Auto Mode",
            2: "Short Mode",
            3: "Manual Mode",
        },
        allowedtypes=ALLDEFAULT,
        icon="mdi:solar-power",
    ),
    EnertechModbusSensorEntityDescription(
        name="Product Type",
        key="info_Product_Type",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        register=0x108,
        scale={
            1: "UPS",
            2: "Reserved",
            3: "Solar Power Unit",
            4: "UPC",
            9: "Other",
        },
        allowedtypes=ALLDEFAULT,
        icon="mdi:factory",
    ),
    EnertechModbusSensorEntityDescription(
        name="Configuration",
        key="info_Configuration",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        register=0x109,
        scale={
            1: "1Phase in 1Phase out Standalone",
            2: "1 Phase in 3 Phase Out Standalone",
            3: "3Phase in 3Phase out Standalone",
            4: "3Phase in 1Phase out Standalone",
            5: "1Phase in 1Phase out Parallel",
            6: "1Phase in 3 Phase out Parallel",
            7: "3Phase in 3Phase out Parallel",
            8: "3Phase in 1Phase out Parallel",
            9: "AC 1 Phase out",
            10: "AC 3 Phase out",
            11: "DC out",
            12: "3Phase Variable Frequency out",
        },
        allowedtypes=ALLDEFAULT,
        icon="mdi:transmission-tower",
    ),
    # ============================ Enertech Diagnostics Stats Here =================================================
    EnertechModbusSensorEntityDescription(
        name="Fault Monitor",
        key="info_Fault Monitor",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        register=0x159,
        scale={
            500: "NO Error",
            501: "CAN Bus Err",
            502: "Battery BMS Com Err",
            503: "Battery Relay Open",
            504: "Smoke Detected",
            505: "Output MCB Trip",
            506: "Earth Leakage",
            507: "DG ON",
            508: "Remote shutdown",
            509: "Energy meter com Err",
        },
        allowedtypes=ALLDEFAULT,
        wordcount=1,  # Add this line for 32-bit float
        icon="mdi:alert-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EnertechModbusSensorEntityDescription(
        name="Fault Grid",
        key="info_Fault_Grid",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        register=0x15A,
        scale={
            100: "NO Error",
            101: "Input Low Voltage",
            102: "Input High Voltage",
            103: "Input Low Frequency",
            104: "Input High Frequency",
            105: "Input Sequence Error",
            106: "Input Overload",
            107: "Input Current Unbalance",
            108: "Input Voltage unbalance",
        },
        allowedtypes=ALLDEFAULT,
        icon="mdi:alert-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EnertechModbusSensorEntityDescription(
        name="Fault PFC Rectifier",
        key="info_Fault_PFC",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        register=0x15B,
        scale={
            600: "NO Error",
            601: "PFC IGBT Error",
            602: "Input DC Low",
            603: "Input DC High",
            604: "Output DC High",
            605: "Output DC Low",
            606: "PFC Total Current Limit",
            607: "PFC battery Current Limit",
            608: "Positive Bus under",
            609: "Negative Bus under",
            610: "Positive Bus over",
            611: "Negative Bus over",
            612: "DC Bus unbalance",
            613: "PFC module overtemperature",
            614: "Dc Bus Soft Start Fail",
            615: "Charer soft-start failure",
        },
        allowedtypes=ALLDEFAULT,
        icon="mdi:alert-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EnertechModbusSensorEntityDescription(
        name="Fault Solar 1",
        key="info_Fault_Solar1",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        register=0x15C,
        scale={
            600: "NO Error",
            601: "SOLAR1 External off",
            602: "SOLAR1 IGBT ERROR",
            603: "Output DC High",
            604: "SOLAR1 Input Voltage Low",
            605: "SOLAR1 Input Voltage High",
            606: "SOLAR1 power limit",
            607: "Output DC low",
        },
        allowedtypes=ALLDEFAULT,
        icon="mdi:alert-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EnertechModbusSensorEntityDescription(
        name="Fault Inverter",
        key="info_Fault_Inverter",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        register=0x15D,
        scale={
            400: "NO Error",
            401: "Inverter IGBT Fault",
            402: "User stop",
            403: "External/EPO Stop",
            404: "Output Low Voltage",
            405: "Output High Voltage",
            406: "Output Frequency Low",
            407: "Output Frequency High",
            408: "Output Overload Alarm",
            409: "Output Overload Trip",
            410: "Inverter module High temperature",
            411: "Load Transfer to Bypass",
            412: "Load Retransfer from Bypass",
            413: "Output Voltage Unbalance",
            414: "Output Current Unbalance",
            415: "Regenerative Transfer",
            416: "Terminal Volt Error",
            417: "SPD Fail",
            418: "Grid Not in Sync",
        },
        allowedtypes=ALLDEFAULT,
        icon="mdi:alert-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EnertechModbusSensorEntityDescription(
        name="Fault Battery",
        key="info_Fault_Battery",
        unit=REGISTER_U16,
        register_type=REG_HOLDING,
        register=0x15E,
        scale={
            300: "NO Error",
            301: "Battery IGBT Fault",
            302: "Battery Low Voltage",
            303: "Battery High voltage",
            304: "Battery Low Warning",
            305: "Battery Earth Fault",
            306: "Battery Temp Compensation",
            307: "Battery Equalize Charging",
            308: "Battery test progress",
            309: "Battery test fail",
            310: "Battery Over current Charge",
            311: "Battery Over current Discharge",
            312: "Battery module overtemperature",
            313: "Battery High Temperature",
            314: "Battery low temperature",
            315: "Battery Com Err",
        },
        allowedtypes=ALLDEFAULT,
        icon="mdi:alert-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]

# ============================ plugin declaration =================================================


@dataclass
class Enertech_plugin(plugin_base):
    def isAwake(self, datadict):
        """determine if inverter is awake based on polled datadict"""
        return datadict.get("run_mode", None) == "Normal Mode"

    def wakeupButton(self):
        """in order to wake up  the inverter , press this button"""
        return "battery_awaken"

    async def async_determineInverterType(self, hub, configdict):
        # global SENSOR_TYPES
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber = await async_read_serialnr(hub, 0x14)
        if not seriesnumber:
            seriesnumber = await async_read_serialnr(hub, 0x300)  # bug in Endian.LITTLE decoding?
            if seriesnumber and not seriesnumber.startswith(("M", "X")):
                ba = bytearray(seriesnumber, "ascii")  # convert to bytearray for swapping
                ba[0::2], ba[1::2] = ba[1::2], ba[0::2]  # swap bytes ourselves - due to bug in Endian.LITTLE ?
                res = str(ba, "ascii")  # convert back to string
                seriesnumber = res
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find serial number, even not for MIC")
            seriesnumber = "unknown"

        # derive invertertupe from seriiesnumber
        if seriesnumber.startswith("GEN"):
            invertertype = HYBRID | GEN  # GEN Hybrid - Unknown Serial
        elif seriesnumber.startswith("32"):
            invertertype = HYBRID | A1  # A1 Hybrid - Unknown Serial
        # add cases here
        else:
            invertertype = GEN
            _LOGGER.error(f"unrecognized inverter type - serial number : {seriesnumber}")

        if invertertype > 0:
            read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
            read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
            read_pm = configdict.get(CONF_READ_PM, DEFAULT_READ_PM)
            if read_eps:
                invertertype = invertertype | EPS
            if read_dcb:
                invertertype = invertertype | DCB
            if read_pm:
                invertertype = invertertype | PM

            if invertertype & MIC:
                self.SENSOR_TYPES = SENSOR_TYPES_MIC
            # else: self.SENSOR_TYPES = SENSOR_TYPES_MAIN

        return invertertype

    def matchInverterWithMask(self, inverterspec, entitymask, serialnumber="not relevant", blacklist=None):
        # returns true if the entity needs to be created for an inverter
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP) != 0) or (entitymask & ALL_GEN_GROUP == 0)
        xmatch = ((inverterspec & entitymask & ALL_X_GROUP) != 0) or (entitymask & ALL_X_GROUP == 0)
        hybmatch = ((inverterspec & entitymask & ALL_TYPE_GROUP) != 0) or (entitymask & ALL_TYPE_GROUP == 0)
        epsmatch = ((inverterspec & entitymask & ALL_EPS_GROUP) != 0) or (entitymask & ALL_EPS_GROUP == 0)
        dcbmatch = ((inverterspec & entitymask & ALL_DCB_GROUP) != 0) or (entitymask & ALL_DCB_GROUP == 0)
        pmmatch = ((inverterspec & entitymask & ALL_PM_GROUP) != 0) or (entitymask & ALL_PM_GROUP == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist:
                if serialnumber.startswith(start):
                    blacklisted = True
        return (genmatch and xmatch and hybmatch and epsmatch and dcbmatch and pmmatch) and not blacklisted

    def localDataCallback(self, hub):
        # adapt the read scales for export_control_user_limit if exception is configured
        # only called after initial polling cycle and subsequent modifications to local data
        _LOGGER.info(f"local data update callback")

        config_scale_entity = hub.numberEntities.get("config_export_control_limit_readscale")
        if config_scale_entity and config_scale_entity.enabled:
            new_read_scale = hub.data.get("config_export_control_limit_readscale")
            if new_read_scale != None:
                _LOGGER.info(
                    f"local data update callback for read_scale: {new_read_scale} enabled: {config_scale_entity.enabled}"
                )
                number_entity = hub.numberEntities.get("export_control_user_limit")
                sensor_entity = hub.sensorEntities.get("export_control_user_limit")
                if number_entity:
                    number_entity.entity_description = replace(
                        number_entity.entity_description,
                        read_scale=new_read_scale,
                    )
                if sensor_entity:
                    sensor_entity.entity_description = replace(
                        sensor_entity.entity_description,
                        read_scale=new_read_scale,
                    )

        config_maxexport_entity = hub.numberEntities.get("config_max_export")
        if config_maxexport_entity and config_maxexport_entity.enabled:
            new_max_export = hub.data.get("config_max_export")
            if new_max_export != None:
                for key in [
                    "remotecontrol_active_power",
                    "remotecontrol_import_limit",
                    "export_control_user_limit",
                    "external_generation_max_charge",
                ]:
                    number_entity = hub.numberEntities.get(key)
                    if number_entity:
                        number_entity._attr_native_max_value = new_max_export
                        # update description also, not sure whether needed or not
                        number_entity.entity_description = replace(
                            number_entity.entity_description,
                            native_max_value=new_max_export,
                        )
                        _LOGGER.info(f"local data update callback for entity: {key} new limit: {new_max_export}")


plugin_instance = Enertech_plugin(
    plugin_name="Enertech",
    plugin_manufacturer="Enertech Solar",
    SENSOR_TYPES=SENSOR_TYPES_MAIN,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=SWITCH_TYPES,
    block_size=100,
    # order16 = "big",
    order32="big",
    auto_block_ignore_readerror=True,
)
