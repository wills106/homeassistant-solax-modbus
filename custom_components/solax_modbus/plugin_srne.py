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

GEN            = 0x0001 # base generation for MIC, PV, AC
GEN2           = 0x0002
GEN3           = 0x0004
GEN4           = 0x0008
ALL_GEN_GROUP  = GEN | GEN2 | GEN3 | GEN4

X1             = 0x0100
X3             = 0x0200
ALL_X_GROUP    = X1 | X3

PV             = 0x0400 # Needs further work on PV Only Inverters
AC             = 0x0800
HYBRID         = 0x1000
MIC            = 0x2000
ALL_TYPE_GROUP = PV | AC | HYBRID | MIC

EPS            = 0x8000
ALL_EPS_GROUP  = EPS

DCB            = 0x10000 # dry contact box - gen4
ALL_DCB_GROUP  = DCB

PM  = 0x20000
ALL_PM_GROUP = PM

ALLDEFAULT = 0 # should be equivalent to HYBRID | AC | GEN2 | GEN3 | GEN4 | X1 | X3

# ======================= end of bitmask handling code =============================================

SENSOR_TYPES = []

# ====================== find inverter type and details ===========================================

async def async_read_serialnr(hub, address):
    res = None
    try:
        inverter_data = await hub.async_read_holding_registers(unit=hub._modbus_addr, address=address, count=4)
        if not inverter_data.isError():
            decoder = BinaryPayloadDecoder.fromRegisters(inverter_data.registers, byteorder=Endian.BIG)
            res = decoder.decode_string(8).decode("ascii")
            hub.seriesnumber = res
    except Exception as ex: _LOGGER.warning(f"{hub.name}: attempt to read serialnumber failed at 0x{address:x}", exc_info=True)
    if not res: _LOGGER.warning(f"{hub.name}: reading serial number from address 0x{address:x} failed; other address may succeed")
    _LOGGER.info(f"Read {hub.name} 0x{address:x} serial number before potential swap: {res}")
    return res

# =================================================================================================

@dataclass
class SRNEModbusButtonEntityDescription(BaseModbusButtonEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SRNEModbusNumberEntityDescription(BaseModbusNumberEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SRNEModbusSelectEntityDescription(BaseModbusSelectEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice

@dataclass
class SRNEModbusSensorEntityDescription(BaseModbusSensorEntityDescription):
    allowedtypes: int = ALLDEFAULT # maybe 0x0000 (nothing) is a better default choice
    #order16: int = Endian.BIG
    #order32: int = Endian.LITTLE
    unit: int = REGISTER_U16
    register_type: int = REG_HOLDING

# ====================================== Computed value functions  =================================================

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


# ================================= Button Declarations ============================================================

BUTTON_TYPES = [

]

# ================================= Number Declarations ============================================================

NUMBER_TYPES = [

]

# ================================= Select Declarations ============================================================

SELECT_TYPES = [

]

# ================================= Sennsor Declarations ============================================================

SENSOR_TYPES_MAIN: list[SRNEModbusSensorEntityDescription] = [
    ###
    #
    # Holding
    #
    ###
    SRNEModbusSensorEntityDescription(
        name = "Battery Capacity",
        key = "battery_capacity_charge",
        native_unit_of_measurement = PERCENTAGE,
        device_class = SensorDeviceClass.BATTERY,
        register = 0x100,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Battery Voltage",
        key = "battery_voltage",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x101,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Battery Current",
        key = "battery_current",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x102,
        scale = 0.1,
        unit = REGISTER_S16,
        allowedtypes = ALLDEFAULT,
        icon = "mdi:current-dc",
    ),
    SRNEModbusSensorEntityDescription(
        name = "PV Voltage 1",
        key = "pv_voltage_1",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x107,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "PV Current 1",
        key = "pv_current_1",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x108,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
        icon = "mdi:current-dc",
    ),
    SRNEModbusSensorEntityDescription(
        name = "PV Power 1",
        key = "pv_power_1",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x109,
        allowedtypes = ALLDEFAULT,
        icon = "mdi:solar-power-variant",
    ),
    SRNEModbusSensorEntityDescription(
        name = "Charger State",
        key = "charger_state",
        register = 0x10B,
        scale = { 0: "Charger Off",
            1: "Quick Charge",
            2: "Constant Voltage Charge",
            4: "Float Charge",
            5: "Reserved 1",
            6: "Lithium Battery Active",
            7: "Reserved 2", },
        allowedtypes = ALLDEFAULT,
        icon = "mdi:dip-switch",
    ),
    SRNEModbusSensorEntityDescription(
        name = "Battery Power",
        key = "battery_power",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x10E,
        unit = REGISTER_S16,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "PV Voltage 2",
        key = "pv_voltage_2",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x10F,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "PV Current 2",
        key = "pv_current_2",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x110,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
        icon = "mdi:current-dc",
    ),
    SRNEModbusSensorEntityDescription(
        name = "PV Power 2",
        key = "pv_power_2",
        native_unit_of_measurement = UnitOfPower.WATT,
        device_class = SensorDeviceClass.POWER,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x111,
        allowedtypes = ALLDEFAULT,
        icon = "mdi:solar-power-variant",
    ),
    SRNEModbusSensorEntityDescription(
        name = "Run Mode",
        key = "run_mode",
        register = 0x210,
        scale = { 0: "Power-up Delay",
                  1: "Waiting State",
                  2: "Initialisation",
                  3: "Soft Start",
                  4: "Mains Powered Operation",
                  5: "Inverter Powered Operation",
                  6: "Inverter to Mains",
                  7: "Mains to Inverter",
                  8: "Battery Active",
                  9: "Shutdown by User",
                 10: "Fault", },
        allowedtypes = ALLDEFAULT,
        icon = "mdi:run",
    ),
    SRNEModbusSensorEntityDescription(
        name = "Grid Voltage L1",
        key = "grid_voltage_meter_l1",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x213,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Grid Current L1",
        key = "grid_current_l1",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x214,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Grid Frequency L1",
        key = "grid_frequency_l1",
        native_unit_of_measurement = UnitOfFrequency.HERTZ,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x215,
        scale = 0.01,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Inverter Voltage L1",
        key = "inverter_voltage_meter_l1",
        native_unit_of_measurement = UnitOfElectricPotential.VOLT,
        device_class = SensorDeviceClass.VOLTAGE,
        register = 0x216,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Inverter Current L1",
        key = "inverter_current_l1",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x217,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Inverter Frequency L1",
        key = "inverter_frequency_l1",
        native_unit_of_measurement = UnitOfFrequency.HERTZ,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x218,
        scale = 0.01,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Load Current L1",
        key = "load_current_l1",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        register = 0x219,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Battery Charge Mains",
        key = "battery_charge_mains",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x21E,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
    ),
    SRNEModbusSensorEntityDescription(
        name = "DC-DC Temperature",
        key = "dc_dc_temperature",
        native_unit_of_measurement = UnitOfTemperature.CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x220,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SRNEModbusSensorEntityDescription(
        name = "DC-AC Temperature",
        key = "dc_ac_temperature",
        native_unit_of_measurement = UnitOfTemperature.CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x221,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Translator Temperature",
        key = "translator_temperature",
        native_unit_of_measurement = UnitOfTemperature.CELSIUS,
        device_class = SensorDeviceClass.TEMPERATURE,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x222,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
        entity_category = EntityCategory.DIAGNOSTIC,
    ),
    SRNEModbusSensorEntityDescription(
        name = "Battery Charge PV",
        key = "battery_charge_pv",
        native_unit_of_measurement = UnitOfElectricCurrent.AMPERE,
        device_class = SensorDeviceClass.CURRENT,
        state_class = SensorStateClass.MEASUREMENT,
        register = 0x224,
        scale = 0.1,
        allowedtypes = ALLDEFAULT,
    ),
]

# ============================ plugin declaration =================================================

@dataclass
class srne_plugin(plugin_base):

    def isAwake(self, datadict):
        """ determine if inverter is awake based on polled datadict"""
        return (datadict.get('run_mode', None) == 'Normal Mode')

    def wakeupButton(self):
        """ in order to wake up  the inverter , press this button """
        return 'battery_awaken'

    async def async_determineInverterType(self, hub, configdict):
        #global SENSOR_TYPES
        _LOGGER.info(f"{hub.name}: trying to determine inverter type")
        seriesnumber                       = await async_read_serialnr(hub, 0x14)
        if not seriesnumber:
            seriesnumber = await async_read_serialnr(hub, 0x300) # bug in Endian.LITTLE decoding?
            if seriesnumber and not seriesnumber.startswith(("M", "X")):
                ba = bytearray(seriesnumber,"ascii") # convert to bytearray for swapping
                ba[0::2], ba[1::2] = ba[1::2], ba[0::2] # swap bytes ourselves - due to bug in Endian.LITTLE ?
                res = str(ba, "ascii") # convert back to string
                seriesnumber = res
        if not seriesnumber:
            _LOGGER.error(f"{hub.name}: cannot find serial number, even not for MIC")
            seriesnumber = "unknown"

        # derive invertertupe from seriiesnumber
        if   seriesnumber.startswith('GEN'):  invertertype = HYBRID | GEN # GEN Hybrid - Unknown Serial
        elif seriesnumber.startswith('A1'):  invertertype = HYBRID | A1 # A1 Hybrid - Unknown Serial
        # add cases here
        else:
            invertertype = GEN
            _LOGGER.error(f"unrecognized inverter type - serial number : {seriesnumber}")

        if invertertype > 0:
            read_eps = configdict.get(CONF_READ_EPS, DEFAULT_READ_EPS)
            read_dcb = configdict.get(CONF_READ_DCB, DEFAULT_READ_DCB)
            read_pm = configdict.get(CONF_READ_PM, DEFAULT_READ_PM)
            if read_eps: invertertype = invertertype | EPS
            if read_dcb: invertertype = invertertype | DCB
            if read_pm: invertertype = invertertype | PM

            if invertertype & MIC: self.SENSOR_TYPES = SENSOR_TYPES_MIC
            #else: self.SENSOR_TYPES = SENSOR_TYPES_MAIN

        return invertertype

    def matchInverterWithMask (self, inverterspec, entitymask, serialnumber = 'not relevant', blacklist = None):
        # returns true if the entity needs to be created for an inverter
        genmatch = ((inverterspec & entitymask & ALL_GEN_GROUP)  != 0) or (entitymask & ALL_GEN_GROUP  == 0)
        xmatch   = ((inverterspec & entitymask & ALL_X_GROUP)    != 0) or (entitymask & ALL_X_GROUP    == 0)
        hybmatch = ((inverterspec & entitymask & ALL_TYPE_GROUP) != 0) or (entitymask & ALL_TYPE_GROUP == 0)
        epsmatch = ((inverterspec & entitymask & ALL_EPS_GROUP)  != 0) or (entitymask & ALL_EPS_GROUP  == 0)
        dcbmatch = ((inverterspec & entitymask & ALL_DCB_GROUP)  != 0) or (entitymask & ALL_DCB_GROUP  == 0)
        pmmatch = ((inverterspec & entitymask & ALL_PM_GROUP)  != 0) or (entitymask & ALL_PM_GROUP  == 0)
        blacklisted = False
        if blacklist:
            for start in blacklist:
                if serialnumber.startswith(start) : blacklisted = True
        return (genmatch and xmatch and hybmatch and epsmatch and dcbmatch and pmmatch) and not blacklisted

    def localDataCallback(self, hub):
        # adapt the read scales for export_control_user_limit if exception is configured
        # only called after initial polling cycle and subsequent modifications to local data
        _LOGGER.info(f"local data update callback")

        config_scale_entity = hub.numberEntities.get("config_export_control_limit_readscale")
        if config_scale_entity and config_scale_entity.enabled:
            new_read_scale = hub.data.get("config_export_control_limit_readscale")
            if new_read_scale != None:
                _LOGGER.info(f"local data update callback for read_scale: {new_read_scale} enabled: {config_scale_entity.enabled}")
                number_entity = hub.numberEntities.get("export_control_user_limit")
                sensor_entity = hub.sensorEntities.get("export_control_user_limit")
                if number_entity: number_entity.entity_description = replace(number_entity.entity_description, read_scale = new_read_scale, )
                if sensor_entity: sensor_entity.entity_description = replace(sensor_entity.entity_description, read_scale = new_read_scale, )

        config_maxexport_entity = hub.numberEntities.get("config_max_export")
        if config_maxexport_entity and config_maxexport_entity.enabled:
            new_max_export = hub.data.get("config_max_export")
            if new_max_export != None:
                for key in ["remotecontrol_active_power", "remotecontrol_import_limit", "export_control_user_limit", "external_generation_max_charge"]:
                    number_entity = hub.numberEntities.get(key)
                    if number_entity:
                        number_entity._attr_native_max_value = new_max_export
                        # update description also, not sure whether needed or not
                        number_entity.entity_description = replace(number_entity.entity_description, native_max_value = new_max_export, )
                        _LOGGER.info(f"local data update callback for entity: {key} new limit: {new_max_export}")

plugin_instance = srne_plugin(
    plugin_name = 'SRNE',
    plugin_manufacturer = 'SRNE Solar',
    SENSOR_TYPES = SENSOR_TYPES_MAIN,
    NUMBER_TYPES = NUMBER_TYPES,
    BUTTON_TYPES = BUTTON_TYPES,
    SELECT_TYPES = SELECT_TYPES,
    block_size = 100,
    order16 = Endian.BIG,
    order32 = Endian.LITTLE,
    auto_block_ignore_readerror = True
    )