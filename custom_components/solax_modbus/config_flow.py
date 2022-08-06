import ipaddress
import re
import logging
from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (CONF_HOST, CONF_NAME, CONF_PORT,
                                 CONF_SCAN_INTERVAL,)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaFlowMenuStep,
)


from .const import (
	DEFAULT_NAME,
	DEFAULT_PORT,
	DEFAULT_SCAN_INTERVAL,
    DEFAULT_INTERFACE,
    DEFAULT_SERIAL_PORT,
    DEFAULT_MODBUS_ADDR,
    DEFAULT_BAUDRATE,
	DOMAIN,
	CONF_READ_EPS,
    CONF_READ_DCB,
    CONF_INTERFACE,
    CONF_SERIAL_PORT,
    CONF_MODBUS_ADDR,
    CONF_BAUDRATE,
	DEFAULT_READ_EPS,
    DEFAULT_READ_DCB,
)

_LOGGER = logging.getLogger(__name__)

BAUDRATES = [
    selector.SelectOptionDict(value="9600",   label="9600"),
    selector.SelectOptionDict(value="14400",  label="14400"),    
    selector.SelectOptionDict(value="19200",  label="19200"),
    selector.SelectOptionDict(value="38400",  label="38400"),
    selector.SelectOptionDict(value="56000",  label="56000"),
    selector.SelectOptionDict(value="57600",  label="57600"),
    selector.SelectOptionDict(value="115200", label="115200"),
]

INTERFACES = [
    selector.SelectOptionDict(value="tcp",    label="TCP / Ethernet"),
    selector.SelectOptionDict(value="serial", label="Serial"),    
]

CONFIG_SCHEMA = vol.Schema( {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_INTERFACE, default="tcp"): selector.SelectSelector(selector.SelectSelectorConfig(options=INTERFACES), ),
        vol.Required(CONF_MODBUS_ADDR, default=DEFAULT_MODBUS_ADDR): int,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
        vol.Optional(CONF_READ_EPS, default=DEFAULT_READ_EPS): bool,
        vol.Optional(CONF_READ_DCB, default=DEFAULT_READ_DCB): bool,
    } )

SERIAL_SCHEMA = vol.Schema( {
        vol.Optional(CONF_SERIAL_PORT, default=DEFAULT_SERIAL_PORT): str,
        vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): selector.SelectSelector(selector.SelectSelectorConfig(options=BAUDRATES), ),
    } )

TCP_SCHEMA = vol.Schema( {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
    } )


def _validate_base(data: Any) -> Any:
    """Validate config."""
    interface   = data[CONF_INTERFACE]
    modbus_addr = data[CONF_MODBUS_ADDR]
    _LOGGER.info(f"validating base config: returning data: {data}")
    return data

def _validate_host(data: Any) -> Any:
    port        = data[CONF_PORT]
    host        = data[CONF_HOST]
    try:
        if ipaddress.ip_address(host).version == (4 or 6):  pass
    except Exception as e:
        _LOOGGER.warning(e, exc_info = True)
        _LOOGGER.warning("valid IP address? Trying to validate it in another way")
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        res = all(x and not disallowed.search(x) for x in host.split("."))
        if not res: raise SchemaFlowError("invalid_host") from e
    _LOGGER.info(f"validating host: returning data: {data}")
    return data
    """
    # use an id that is more than the IP address, for compatibilityu reasons, only do this with non-default settings
    if ( (port != DEFAULT_PORT) or (modbus_addr != DEFAULT_MODBUS_ADDR) ):  hostid = f"{host}_{port}_{modbus_addr}"
    else: hostid = host
    if self._host_in_configuration_exists(hostid):
        errors[CONF_HOST] = "already_configured"
    elif not host_valid(user_input[CONF_HOST]) and not serial:
        errors[CONF_HOST] = "invalid host IP"
    else:
        await self.async_set_unique_id(hostid) #user_input[CONF_HOST])
    """

def _next_step(data: Any) -> str:
    return data[CONF_INTERFACE] # eitheer "tcp" or "serial"

CONFIG_FLOW: dict[str, SchemaFlowFormStep | SchemaFlowMenuStep] = {
    "user":   SchemaFlowFormStep(CONFIG_SCHEMA, validate_user_input=_validate_base, next_step = _next_step),
    "serial": SchemaFlowFormStep(SERIAL_SCHEMA),
    "tcp":    SchemaFlowFormStep(TCP_SCHEMA, validate_user_input=_validate_host),
}

OPTIONS_FLOW: dict[str, SchemaFlowFormStep | SchemaFlowMenuStep] = {
    "init":   SchemaFlowFormStep(CONFIG_SCHEMA, validate_user_input=_validate_base, next_step = _next_step),
    "serial": SchemaFlowFormStep(SERIAL_SCHEMA),
    "tcp":    SchemaFlowFormStep(TCP_SCHEMA, validate_user_input=_validate_host),
}

class ConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    #Handle a config or options flow for Utility Meter.

    _LOGGER.info(f"starting infradom configflow {DOMAIN} {CONF_NAME}")
    config_flow  = CONFIG_FLOW
    options_flow = OPTIONS_FLOW


    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        _LOGGER.info(f"title configflow {DOMAIN} {CONF_NAME}: {options}")
        # Return config entry title
        return cast(str, options[CONF_NAME]) if CONF_NAME in options else ""

"""

def host_valid(host):
    # Return True if hostname or IP address is valid
    try:
        if ipaddress.ip_address(host).version == (4 or 6):
            return True
    except ValueError:
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        return all(x and not disallowed.search(x) for x in host.split("."))


@callback
def solax_modbus_entries(hass: HomeAssistant):
    #Return the hosts already configured.
    return set(
        entry.data[CONF_HOST] for entry in hass.config_entries.async_entries(DOMAIN)
    )


class SolaXModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    #SolaX Modbus configflow.

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def _host_in_configuration_exists(self, host) -> bool:
        #Return True if host exists in configuration.
        if host in solax_modbus_entries(self.hass):
            return True
        return False

    async def async_step_user(self, user_input=None):
        #Handle the initial step.
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            serial = user_input[CONF_SERIAL]
            modbus_addr = user_input[CONF_MODBUS_ADDR]
            port = user_input[CONF_PORT]
            # use an id that is more than the IP address, for compatibilityu reasons, only do this with non-default settings
            if ( (port != DEFAULT_PORT) or (modbus_addr != DEFAULT_MODBUS_ADDR) ):  hostid = f"{host}_{port}_{modbus_addr}"
            else: hostid = host
            if self._host_in_configuration_exists(hostid):
                errors[CONF_HOST] = "already_configured"
            elif not host_valid(user_input[CONF_HOST]) and not serial:
                errors[CONF_HOST] = "invalid host IP"
            else:
                await self.async_set_unique_id(hostid) #user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )
"""