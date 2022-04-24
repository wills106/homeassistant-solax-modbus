import ipaddress
import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (CONF_HOST, CONF_NAME, CONF_PORT,
                                 CONF_SCAN_INTERVAL)
from homeassistant.core import HomeAssistant, callback

from .const import (
	DEFAULT_NAME,
	DEFAULT_PORT,
	DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERIAL,
    DEFAULT_SERIAL_PORT,
    DEFAULT_MODBUS_ADDR,
	DOMAIN,
	CONF_READ_EPS,
    CONF_SERIAL,
    CONF_SERIAL_PORT,
    CONF_MODBUS_ADDR,
	DEFAULT_READ_EPS,
)

DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_MODBUS_ADDR, default=DEFAULT_MODBUS_ADDR): int,
        vol.Required(CONF_SERIAL, default=DEFAULT_SERIAL): bool,
        vol.Optional(CONF_SERIAL_PORT, default=DEFAULT_SERIAL_PORT): str,
        vol.Optional(CONF_READ_EPS, default=DEFAULT_READ_EPS): bool,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
    }
)


def host_valid(host):
    """Return True if hostname or IP address is valid."""
    try:
        if ipaddress.ip_address(host).version == (4 or 6):
            return True
    except ValueError:
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        return all(x and not disallowed.search(x) for x in host.split("."))


@callback
def solax_modbus_entries(hass: HomeAssistant):
    """Return the hosts already configured."""
    return set(
        entry.data[CONF_HOST] for entry in hass.config_entries.async_entries(DOMAIN)
    )


class SolaXModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """SolaX Modbus configflow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def _host_in_configuration_exists(self, host) -> bool:
        """Return True if host exists in configuration."""
        if host in solax_modbus_entries(self.hass):
            return True
        return False

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
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
