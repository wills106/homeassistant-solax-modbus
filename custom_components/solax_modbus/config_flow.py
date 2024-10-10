import ipaddress
import re
import logging
import glob
import importlib
from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult
from types import ModuleType
from homeassistant.const import (CONF_HOST, CONF_NAME, CONF_PORT,
                                 CONF_SCAN_INTERVAL,)
from homeassistant.const import (MAJOR_VERSION, MINOR_VERSION, )
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaFlowMenuStep,
)

from .const import (
	DEFAULT_NAME,
    DEFAULT_INVERTER_NAME_SUFFIX,
    DEFAULT_PORT,
	DEFAULT_SCAN_INTERVAL,
    DEFAULT_INTERFACE,
    DEFAULT_SERIAL_PORT,
    DEFAULT_MODBUS_ADDR,
    DEFAULT_BAUDRATE,
	DOMAIN,
    DEFAULT_TCP_TYPE,
    CONF_TCP_TYPE,
	CONF_INVERTER_NAME_SUFFIX,
	CONF_READ_EPS,
    CONF_READ_DCB,
    CONF_READ_PM,
    CONF_INTERFACE,
    CONF_SERIAL_PORT,
    CONF_MODBUS_ADDR,
    CONF_BAUDRATE,
    CONF_PLUGIN,
    CONF_READ_BATTERY,
    CONF_CORE_HUB,
	DEFAULT_READ_EPS,
    DEFAULT_READ_DCB,
    DEFAULT_READ_PM,
    DEFAULT_PLUGIN,
    DEFAULT_READ_BATTERY,
    PLUGIN_PATH,
    CONF_SCAN_INTERVAL_MEDIUM,
    CONF_SCAN_INTERVAL_FAST
    # PLUGIN_PATH_OLDSTYLE,
)

_LOGGER = logging.getLogger(__name__)

# ############################# plugin aux functions #################################################

"""
glob_plugin = {}

def setPlugin(instancename, plugin):
    global glob_plugin
    glob_plugin[instancename] = plugin

def getPlugin(instancename):
    return glob_plugin.get(instancename) """

def getPluginName(plugin_path):
    return plugin_path[len(PLUGIN_PATH)-4:-3]


# ####################################################################################################

BAUDRATES = [
    selector.SelectOptionDict(value="9600",   label="9600"),
    selector.SelectOptionDict(value="14400",  label="14400"),
    selector.SelectOptionDict(value="19200",  label="19200"),
    selector.SelectOptionDict(value="38400",  label="38400"),
    selector.SelectOptionDict(value="56000",  label="56000"),
    selector.SelectOptionDict(value="57600",  label="57600"),
    selector.SelectOptionDict(value="115200", label="115200"),
]

TCP_TYPES = [
    selector.SelectOptionDict(value="tcp", label="Modbus TCP"),
    selector.SelectOptionDict(value="rtu", label="Modbus RTU over TCP"),
    selector.SelectOptionDict(value="ascii", label="Modbus ASCII over TCP"),
]

PLUGINS = [ selector.SelectOptionDict(value=getPluginName(i), label=getPluginName(i)) for i in glob.glob(PLUGIN_PATH) ]


INTERFACES = [
    selector.SelectOptionDict(value="tcp",    label="TCP / Ethernet"),
    selector.SelectOptionDict(value="serial", label="Serial"),
    selector.SelectOptionDict(value="core", label="Hass core Hub"),
]

CONFIG_SCHEMA = vol.Schema( {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_INTERFACE, default="tcp"): selector.SelectSelector(selector.SelectSelectorConfig(options=INTERFACES), ),
        vol.Required(CONF_MODBUS_ADDR, default=DEFAULT_MODBUS_ADDR): int,
        vol.Required(CONF_PLUGIN, default=DEFAULT_PLUGIN): selector.SelectSelector(selector.SelectSelectorConfig(options=PLUGINS), ),
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
        vol.Optional(CONF_SCAN_INTERVAL_MEDIUM, default=DEFAULT_SCAN_INTERVAL): int,
        vol.Optional(CONF_SCAN_INTERVAL_FAST, default=DEFAULT_SCAN_INTERVAL): int,
        vol.Optional(CONF_INVERTER_NAME_SUFFIX, description={"suggested_value": DEFAULT_INVERTER_NAME_SUFFIX}): str,
        vol.Optional(CONF_READ_EPS, default=DEFAULT_READ_EPS): bool,
        vol.Optional(CONF_READ_DCB, default=DEFAULT_READ_DCB): bool,
        vol.Optional(CONF_READ_PM, default=DEFAULT_READ_PM): bool,
    } )

OPTION_SCHEMA = vol.Schema( {
        vol.Required(CONF_INTERFACE, default="tcp"): selector.SelectSelector(selector.SelectSelectorConfig(options=INTERFACES), ),
        vol.Required(CONF_MODBUS_ADDR, default=DEFAULT_MODBUS_ADDR): int,
        vol.Required(CONF_PLUGIN, default=DEFAULT_PLUGIN): selector.SelectSelector(selector.SelectSelectorConfig(options=PLUGINS), ),
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
        vol.Optional(CONF_SCAN_INTERVAL_MEDIUM, default=DEFAULT_SCAN_INTERVAL): int,
        vol.Optional(CONF_SCAN_INTERVAL_FAST, default=DEFAULT_SCAN_INTERVAL): int,
        vol.Optional(CONF_INVERTER_NAME_SUFFIX): str,
        vol.Optional(CONF_READ_EPS, default=DEFAULT_READ_EPS): bool,
        vol.Optional(CONF_READ_DCB, default=DEFAULT_READ_DCB): bool,
        vol.Optional(CONF_READ_PM, default=DEFAULT_READ_PM): bool,
    } )

SERIAL_SCHEMA = vol.Schema( {
        vol.Optional(CONF_SERIAL_PORT, default=DEFAULT_SERIAL_PORT): str,
        vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): selector.SelectSelector(selector.SelectSelectorConfig(options=BAUDRATES), ),
    } )

TCP_SCHEMA = vol.Schema( {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_TCP_TYPE, default=DEFAULT_TCP_TYPE): selector.SelectSelector(selector.SelectSelectorConfig(options=TCP_TYPES), ),
    } )

CORE_SCHEMA = vol.Schema( {
        vol.Required(CONF_CORE_HUB): str,
        #vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        #vol.Required(CONF_TCP_TYPE, default=DEFAULT_TCP_TYPE): selector.SelectSelector(selector.SelectSelectorConfig(options=TCP_TYPES), ),
    } )

BATTERY_SCHEMA = vol.Schema( {
        vol.Optional(CONF_READ_BATTERY, default=DEFAULT_READ_BATTERY): bool,
    } )

async def _validate_base(handler: SchemaCommonFlowHandler, user_input: dict[str, Any]) -> dict[str, Any] :
    _LOGGER.info(f"validating base: {user_input}")
    """Validate config."""
    interface   = user_input[CONF_INTERFACE]
    modbus_addr = user_input[CONF_MODBUS_ADDR]
    name        = user_input[CONF_NAME]
    pluginconf_name = user_input[CONF_PLUGIN]

    # convert old style to new style plugin name here - Remove later after a breaking upgrade
    if pluginconf_name.startswith("custom_components") or pluginconf_name.startswith("/config") or pluginconf_name.startswith("plugin_"):
        newpluginname = pluginconf_name.split('plugin_', 1)[1][:-3] #getPluginName(pluginconf_name)
        _LOGGER.warning(f"converting old style plugin name {pluginconf_name} to new style: {newpluginname} ")
        user_input[CONF_PLUGIN] = newpluginname
        pluginconf_name = newpluginname
    # end of conversion

    _LOGGER.info(f"validating base config for {name}: pre: {user_input}")
    #if getPlugin(name) or ((name == DEFAULT_NAME) and (pluginconf_name != DEFAULT_PLUGIN)):
    if ((name == DEFAULT_NAME) and (pluginconf_name != DEFAULT_PLUGIN)):
        _LOGGER.warning(f"instance name {name} already defined or default name for non-default inverter")
        user_input[CONF_NAME] = user_input[CONF_PLUGIN] # getPluginName(user_input[CONF_PLUGIN])
        raise SchemaFlowError("name_already_used")

    return user_input

async def _validate_host(handler: SchemaCommonFlowHandler, user_input: Any) -> Any:
    port        = user_input[CONF_PORT]
    host        = user_input[CONF_HOST]
    try:
        if ipaddress.ip_address(host).version == (4 or 6):  pass
    except Exception as e:
        _LOGGER.warning(e, exc_info = True)
        _LOGGER.warning("valid IP address? Trying to validate it in another way")
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        res = all(x and not disallowed.search(x) for x in host.split("."))
        if not res: raise SchemaFlowError("invalid_host") from e
    _LOGGER.info(f"validating host: returning data: {user_input}")

    pluginconf_name = handler.options[CONF_PLUGIN]
    plugin = await handler.parent_handler.hass.async_add_executor_job(_load_plugin, pluginconf_name)
    user_input["support-battery"] = plugin.plugin_instance.BATTERY_CONFIG is not None

    return user_input

async def _validate_core_modbus_hub(handler: SchemaCommonFlowHandler, user_input: Any) -> Any:
    hub_name = user_input[CONF_CORE_HUB]
    non_empty = re.compile(r"\w")
    try:
        res = non_empty.search(hub_name)
    except Exception as e:
        raise SchemaFlowError(f"invalid core modbus hub name: '{hub_name}'") from e
    if not res:
        raise SchemaFlowError(f"core modbus hub name empty")
    return user_input

        
    

async def _next_step_modbus(user_input: Any) -> str:
    return user_input[CONF_INTERFACE] # eitheer "tcp" or "serial"

async def _next_step_battery(user_input: Any) -> str:
    _LOGGER.debug(f"_next_step_battery: returning data: {user_input}")
    if user_input.get("support-battery", False):
        return "battery"
    return None

def _load_plugin(plugin_name:str) -> ModuleType:
    _LOGGER.info("trying to load plugin - plugin_name: %s",plugin_name)
    plugin = importlib.import_module(
        f".plugin_{plugin_name}", "custom_components.solax_modbus"
    )
    if not plugin:
        _LOGGER.error("Could not import plugin with name: %s",plugin_name)
    return plugin


if (MAJOR_VERSION >=2023) or ((MAJOR_VERSION==2022) and (MINOR_VERSION==12)):
    _LOGGER.info(f"detected HA core version {MAJOR_VERSION} {MINOR_VERSION}")
    CONFIG_FLOW: dict[str, SchemaFlowFormStep | SchemaFlowMenuStep] = {
        "user":    SchemaFlowFormStep(CONFIG_SCHEMA, validate_user_input=_validate_base, next_step = _next_step_modbus),
        "serial":  SchemaFlowFormStep(SERIAL_SCHEMA, next_step = _next_step_battery),
        "tcp":     SchemaFlowFormStep(TCP_SCHEMA, validate_user_input=_validate_host, next_step = _next_step_battery),
        "core":  SchemaFlowFormStep(CORE_SCHEMA, validate_user_input=_validate_core_modbus_hub, next_step = _next_step_battery),
        "battery": SchemaFlowFormStep(BATTERY_SCHEMA),
    }
    OPTIONS_FLOW: dict[str, SchemaFlowFormStep | SchemaFlowMenuStep] = {
        "init":    SchemaFlowFormStep(OPTION_SCHEMA, next_step = _next_step_modbus),
        "serial":  SchemaFlowFormStep(SERIAL_SCHEMA, next_step = _next_step_battery),
        "tcp":     SchemaFlowFormStep(TCP_SCHEMA, validate_user_input=_validate_host, next_step = _next_step_battery),
        "core":  SchemaFlowFormStep(CORE_SCHEMA, validate_user_input=_validate_core_modbus_hub, next_step = _next_step_battery),
        "battery": SchemaFlowFormStep(BATTERY_SCHEMA),
    }

else: # for older versions - REMOVE SOON
    _LOGGER.error(f"detected old HA core version {MAJOR_VERSION} {MINOR_VERSION}")


class ConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    #Handle a config or options flow for Utility Meter.

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors = {}

    _LOGGER.info(f"starting configflow - domain = {DOMAIN}")
    config_flow  = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        _LOGGER.info(f"title configflow {DOMAIN} {CONF_NAME}: {options}")
        # Return config entry title
        return cast(str, options[CONF_NAME]) if CONF_NAME in options else ""
