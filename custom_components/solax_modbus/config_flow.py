import asyncio
import glob
import importlib
import ipaddress
import logging
import re
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_COUNT,
    CONF_BAUDRATE,
    CONF_CORE_HUB,
    CONF_ENERGY_DASHBOARD_DEVICE,
    CONF_INTERFACE,
    CONF_INVERTER_NAME_SUFFIX,
    CONF_INVERTER_POWER_KW,
    CONF_MODBUS_ADDR,
    CONF_MPPT_COUNT,
    CONF_PLUGIN,
    CONF_READ_BATTERY,
    CONF_READ_DCB,
    CONF_READ_EPS,
    CONF_READ_PM,
    CONF_SCAN_INTERVAL_FAST,
    CONF_SCAN_INTERVAL_MEDIUM,
    CONF_SERIAL_PORT,
    CONF_TCP_TYPE,
    CONF_TIME_OUT,
    DEFAULT_BATTERY_COUNT,
    DEFAULT_BAUDRATE,
    DEFAULT_ENERGY_DASHBOARD_DEVICE,
    DEFAULT_INVERTER_NAME_SUFFIX,
    DEFAULT_INVERTER_POWER_KW,
    DEFAULT_INTERFACE,
    DEFAULT_MODBUS_ADDR,
    DEFAULT_MPPT_COUNT,
    DEFAULT_NAME,
    DEFAULT_PLUGIN,
    DEFAULT_PORT,
    DEFAULT_READ_DCB,
    DEFAULT_READ_EPS,
    DEFAULT_READ_PM,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERIAL_PORT,
    DEFAULT_TCP_TYPE,
    DEFAULT_TIME_OUT,
    DOMAIN,
    PLUGIN_PATH,
)

_LOGGER = logging.getLogger(__name__)
FLOW_DETECTION_TIMEOUT_SECONDS = 5

BAUDRATES = [
    selector.SelectOptionDict(value="9600", label="9600"),
    selector.SelectOptionDict(value="14400", label="14400"),
    selector.SelectOptionDict(value="19200", label="19200"),
    selector.SelectOptionDict(value="38400", label="38400"),
    selector.SelectOptionDict(value="56000", label="56000"),
    selector.SelectOptionDict(value="57600", label="57600"),
    selector.SelectOptionDict(value="115200", label="115200"),
]

TCP_TYPES = [
    selector.SelectOptionDict(value="tcp", label="Modbus TCP"),
    selector.SelectOptionDict(value="rtu", label="Modbus RTU over TCP"),
    selector.SelectOptionDict(value="ascii", label="Modbus ASCII over TCP"),
]

PLUGINS = [selector.SelectOptionDict(value=p[len(PLUGIN_PATH) - 4 : -3], label=p[len(PLUGIN_PATH) - 4 : -3]) for p in glob.glob(PLUGIN_PATH)]

INTERFACES = [
    selector.SelectOptionDict(value="tcp", label="TCP / Ethernet"),
    selector.SelectOptionDict(value="serial", label="Serial"),
    selector.SelectOptionDict(value="core", label="Hass core Hub"),
]


def _load_plugin(plugin_name: str) -> ModuleType:
    plugin = importlib.import_module(f".plugin_{plugin_name}", "custom_components.solax_modbus")
    if not plugin:
        _LOGGER.error("Could not import plugin with name: %s", plugin_name)
    return plugin


def _normalize_plugin_name(plugin_name: str) -> str:
    if plugin_name.startswith("custom_components") or plugin_name.startswith("/config") or plugin_name.startswith("plugin_"):
        return plugin_name.split("plugin_", 1)[1][:-3]
    return plugin_name


def _entry_config(entry: ConfigEntry) -> dict[str, Any]:
    return _normalize_numeric_config({**dict(entry.data), **dict(entry.options)})


_INT_CONFIG_KEYS = {
    CONF_PORT,
    CONF_MODBUS_ADDR,
    CONF_MPPT_COUNT,
    CONF_BATTERY_COUNT,
    CONF_INVERTER_POWER_KW,
    CONF_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL_MEDIUM,
    CONF_SCAN_INTERVAL_FAST,
    CONF_TIME_OUT,
}


def _normalize_numeric_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    for key in _INT_CONFIG_KEYS:
        value = normalized.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            normalized[key] = int(value)
    return normalized


def _guess_mppt_count(plugin_module: ModuleType, invertertype: int | None) -> int | None:
    if not invertertype:
        return None

    mppt_flags: list[tuple[int, int]] = []
    for attr_name in dir(plugin_module):
        match = re.fullmatch(r"MPPT(\d+)", attr_name)
        if not match:
            continue
        mask = getattr(plugin_module, attr_name, None)
        if isinstance(mask, int):
            mppt_flags.append((int(match.group(1)), mask))

    for count, mask in sorted(mppt_flags, reverse=True):
        if invertertype & mask:
            return count

    return None


def _guess_power_kw(plugin_module: ModuleType, invertertype: int | None) -> int | None:
    if not invertertype:
        return None

    power_flags: list[tuple[int, int]] = []
    for attr_name in dir(plugin_module):
        match = re.fullmatch(r"POW(\d+)", attr_name)
        if not match:
            continue
        mask = getattr(plugin_module, attr_name, None)
        if isinstance(mask, int):
            power_flags.append((int(match.group(1)), mask))

    for power_kw, mask in sorted(power_flags):
        if invertertype & mask:
            return power_kw

    return None


def _guess_battery_count(plugin_module: ModuleType, invertertype: int | None) -> int | None:
    if not invertertype:
        return None

    hybrid_mask = getattr(plugin_module, "HYBRID", 0)
    ac_mask = getattr(plugin_module, "AC", 0)
    capability_mask = 0
    if isinstance(hybrid_mask, int):
        capability_mask |= hybrid_mask
    if isinstance(ac_mask, int):
        capability_mask |= ac_mask

    if capability_mask == 0:
        return None

    return 1 if invertertype & capability_mask else 0




def _topology_reduced(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    old_mppt = previous.get(CONF_MPPT_COUNT)
    new_mppt = current.get(CONF_MPPT_COUNT)
    if isinstance(old_mppt, int) and isinstance(new_mppt, int) and new_mppt < old_mppt:
        return True

    old_battery = previous.get(CONF_BATTERY_COUNT)
    new_battery = current.get(CONF_BATTERY_COUNT)
    if isinstance(old_battery, int) and isinstance(new_battery, int) and new_battery < old_battery:
        return True

    return False


async def _remove_all_entry_entities(hass: Any, entry_id: str) -> None:
    registry = er.async_get(hass)
    entity_ids = [entity_entry.entity_id for entity_entry in registry.entities.values() if entity_entry.config_entry_id == entry_id]
    for entity_id in entity_ids:
        registry.async_remove(entity_id)

async def _detect_existing_plugin_state(hass: Any, config: dict[str, Any]) -> dict[str, Any]:
    plugin_module = await hass.async_add_executor_job(_load_plugin, _normalize_plugin_name(config[CONF_PLUGIN]))

    from .__init__ import SolaXCoreModbusHub, SolaXModbusHub

    temp_entry = SimpleNamespace(options=config, data={}, entry_id="flow-detect")
    hub = SolaXCoreModbusHub(hass, plugin_module, temp_entry) if config.get(CONF_INTERFACE) == "core" else SolaXModbusHub(hass, plugin_module, temp_entry)

    try:
        await hub.async_connect()
        await hub._check_connection()
        invertertype = await plugin_module.plugin_instance.async_determineInverterType(hub, config)
        if invertertype in (None, 0):
            return {"success": False}

        model = getattr(plugin_module.plugin_instance, "inverter_model", None)
        return {
            "success": True,
            "invertertype": invertertype,
            "model": model,
            "serialnumber": getattr(hub, "seriesnumber", None),
            "mppt_count": _guess_mppt_count(plugin_module, invertertype),
            "battery_count": _guess_battery_count(plugin_module, invertertype),
            "inverter_power_kw": _guess_power_kw(plugin_module, invertertype),
        }
    except Exception as ex:
        _LOGGER.warning("%s: inverter detection failed in config flow: %s", config.get(CONF_NAME, "unknown"), ex)
        return {"success": False}
    finally:
        try:
            await hub.async_stop()
        except Exception:
            try:
                await hub.async_close()
            except Exception:
                pass


async def _detect_existing_plugin_state_with_timeout(hass: Any, config: dict[str, Any]) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(_detect_existing_plugin_state(hass, config), timeout=FLOW_DETECTION_TIMEOUT_SECONDS)
    except TimeoutError:
        _LOGGER.warning(
            "%s: inverter detection timed out in config flow after %ss",
            config.get(CONF_NAME, "unknown"),
            FLOW_DETECTION_TIMEOUT_SECONDS,
        )
        return {"success": False}


class _FlowMixin:
    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._detected: dict[str, Any] = {}
        self._recreate_entities_required = False
        self._recreate_entities_selected = False

    def _base_schema(self, current: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Optional(CONF_NAME, default=current.get(CONF_NAME, DEFAULT_NAME)): str,
                vol.Required(CONF_PLUGIN, default=current.get(CONF_PLUGIN, DEFAULT_PLUGIN)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=PLUGINS),
                ),
                vol.Required(CONF_INTERFACE, default=current.get(CONF_INTERFACE, DEFAULT_INTERFACE)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=INTERFACES),
                ),
            }
        )

    def _connection_schema(self, current: dict[str, Any], allow_continue: bool) -> vol.Schema:
        interface = current.get(CONF_INTERFACE, DEFAULT_INTERFACE)
        schema: dict[Any, Any] = {}
        if interface == "tcp":
            schema.update(
                {
                    vol.Required(CONF_HOST, default=current.get(CONF_HOST, "")): str,
                    vol.Required(CONF_PORT, default=current.get(CONF_PORT, DEFAULT_PORT)): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=65535,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(CONF_MODBUS_ADDR, default=current.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=255,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(CONF_TCP_TYPE, default=current.get(CONF_TCP_TYPE, DEFAULT_TCP_TYPE)): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=TCP_TYPES),
                    ),
                }
            )
        elif interface == "serial":
            schema.update(
                {
                    vol.Required(CONF_SERIAL_PORT, default=current.get(CONF_SERIAL_PORT, DEFAULT_SERIAL_PORT)): str,
                    vol.Required(CONF_BAUDRATE, default=current.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=BAUDRATES),
                    ),
                    vol.Required(CONF_MODBUS_ADDR, default=current.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=255,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            )
        elif interface == "core":
            schema.update(
                {
                    vol.Required(CONF_CORE_HUB, default=current.get(CONF_CORE_HUB, "")): str,
                    vol.Required(CONF_MODBUS_ADDR, default=current.get(CONF_MODBUS_ADDR, DEFAULT_MODBUS_ADDR)): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=255,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            )
        if allow_continue:
            schema[vol.Optional("continue_without_detection", default=False)] = bool
        return vol.Schema(schema)

    def _topology_schema(self, current: dict[str, Any], include_recreate_entities: bool = False) -> vol.Schema:
        schema: dict[Any, Any] = {}
        if CONF_MPPT_COUNT in current:
            schema[vol.Required(CONF_MPPT_COUNT, default=current[CONF_MPPT_COUNT])] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=10, step=1, mode=selector.NumberSelectorMode.BOX)
            )
        else:
            schema[vol.Required(CONF_MPPT_COUNT)] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=10, step=1, mode=selector.NumberSelectorMode.BOX)
            )

        if CONF_BATTERY_COUNT in current:
            schema[vol.Required(CONF_BATTERY_COUNT, default=current[CONF_BATTERY_COUNT])] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=8, step=1, mode=selector.NumberSelectorMode.BOX)
            )
        else:
            schema[vol.Required(CONF_BATTERY_COUNT)] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=8, step=1, mode=selector.NumberSelectorMode.BOX)
            )

        if CONF_INVERTER_POWER_KW in current:
            schema[vol.Required(CONF_INVERTER_POWER_KW, default=current[CONF_INVERTER_POWER_KW])] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=500, step=1, mode=selector.NumberSelectorMode.BOX)
            )
        else:
            schema[vol.Required(CONF_INVERTER_POWER_KW, default=10)] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=500, step=1, mode=selector.NumberSelectorMode.BOX)
            )

        if include_recreate_entities:
            schema[vol.Optional("recreate_entities", default=self._recreate_entities_selected)] = bool

        return vol.Schema(schema)

    def _settings_schema(self, current: dict[str, Any]) -> vol.Schema:
        schema: dict[Any, Any] = {
            vol.Required(CONF_SCAN_INTERVAL, default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=3600, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_SCAN_INTERVAL_MEDIUM, default=current.get(CONF_SCAN_INTERVAL_MEDIUM, current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=3600, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_SCAN_INTERVAL_FAST, default=current.get(CONF_SCAN_INTERVAL_FAST, current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=3600, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_TIME_OUT, default=current.get(CONF_TIME_OUT, DEFAULT_TIME_OUT)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=300, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_INVERTER_NAME_SUFFIX, default=current.get(CONF_INVERTER_NAME_SUFFIX, DEFAULT_INVERTER_NAME_SUFFIX)): str,
            vol.Optional(CONF_ENERGY_DASHBOARD_DEVICE, default=current.get(CONF_ENERGY_DASHBOARD_DEVICE, DEFAULT_ENERGY_DASHBOARD_DEVICE)): bool,
            vol.Optional(CONF_READ_EPS, default=current.get(CONF_READ_EPS, DEFAULT_READ_EPS)): bool,
            vol.Optional(CONF_READ_DCB, default=current.get(CONF_READ_DCB, DEFAULT_READ_DCB)): bool,
            vol.Optional(CONF_READ_PM, default=current.get(CONF_READ_PM, DEFAULT_READ_PM)): bool,
        }
        return vol.Schema(schema)

    @staticmethod
    def _placeholder_value(value: Any, suffix: str = "") -> str:
        if value is None:
            return "—"
        return f"{value}{suffix}"

    def _topology_placeholders(self) -> dict[str, str]:
        config_mppt = self._config.get(CONF_MPPT_COUNT)
        config_battery = self._config.get(CONF_BATTERY_COUNT)
        config_power = self._config.get(CONF_INVERTER_POWER_KW)

        if not self._detected.get("success"):
            return {
                "detected_model": "—",
                "detected_serial": "—",
                "mppt_value": "—",
                "battery_value": "—",
                "power_value": "—",
            }
        return {
            "detected_model": str(self._detected.get("model") or "—"),
            "detected_serial": str(self._detected.get("serialnumber") or "—"),
            "mppt_value": self._placeholder_value(config_mppt if config_mppt is not None else self._detected.get("mppt_count")),
            "battery_value": self._placeholder_value(config_battery if config_battery is not None else self._detected.get("battery_count")),
            "power_value": self._placeholder_value(config_power if config_power is not None else self._detected.get("inverter_power_kw"), " kW"),
        }

    async def _validate_base(self, user_input: dict[str, Any], current_name: str | None = None) -> dict[str, Any]:
        user_input[CONF_PLUGIN] = _normalize_plugin_name(user_input[CONF_PLUGIN])
        name = user_input[CONF_NAME]
        plugin_name = user_input[CONF_PLUGIN]
        if (name == DEFAULT_NAME) and (plugin_name != DEFAULT_PLUGIN):
            user_input[CONF_NAME] = plugin_name
        for existing in self.hass.config_entries.async_entries(DOMAIN):
            existing_config = existing.options or existing.data
            existing_name = existing_config.get(CONF_NAME)
            if existing_name != user_input[CONF_NAME]:
                continue
            if current_name is not None and existing_name == current_name:
                continue
            raise ValueError("name_already_used")
        return user_input

    async def _validate_connection(self, current: dict[str, Any]) -> None:
        interface = current.get(CONF_INTERFACE, DEFAULT_INTERFACE)
        if interface == "tcp":
            host = current[CONF_HOST]
            try:
                if ipaddress.ip_address(host).version not in (4, 6):
                    raise ValueError
            except Exception:
                disallowed = re.compile(r"[^a-zA-Z\d\-]")
                res = all(part and not disallowed.search(part) for part in host.split("."))
                if not res:
                    raise ValueError("invalid_host")
        elif interface == "core":
            hub_name = current[CONF_CORE_HUB]
            if not re.search(r"\w", hub_name):
                raise ValueError("invalid_core_hub")


class ConfigFlowHandler(_FlowMixin, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        ConfigFlow.__init__(self)
        _FlowMixin.__init__(self)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._config.update(await self._validate_base(dict(user_input)))
                return await self.async_step_connection()
            except ValueError as ex:
                errors["base"] = str(ex)
        current = {**self._config}
        return self.async_show_form(step_id="user", data_schema=self._base_schema(current), errors=errors)

    async def async_step_connection(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        interface = (user_input or self._config).get(CONF_INTERFACE, self._config.get(CONF_INTERFACE, DEFAULT_INTERFACE))
        allow_continue = True
        if user_input is not None:
            continue_without_detection = bool(user_input.pop("continue_without_detection", False))
            try:
                merged = {**self._config, **user_input}
                await self._validate_connection(merged)
                self._config.update(user_input)
                self._detected = await _detect_existing_plugin_state_with_timeout(self.hass, self._config)
                if not self._detected.get("success") and not continue_without_detection:
                    errors["base"] = "cannot_detect"
                else:
                    return await self.async_step_topology()
            except ValueError as ex:
                errors["base"] = str(ex)
        current = {**self._config, CONF_INTERFACE: interface}
        return self.async_show_form(
            step_id="connection",
            data_schema=self._connection_schema(current, allow_continue=allow_continue),
            errors=errors,
        )

    async def async_step_topology(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._config.update(_normalize_numeric_config(user_input))
            self._config[CONF_READ_BATTERY] = bool(self._config.get(CONF_BATTERY_COUNT, 0) > 0)
            return await self.async_step_settings()

        current = {**self._config}
        if self._detected.get("success"):
            if self._detected.get("mppt_count") is not None:
                current.setdefault(CONF_MPPT_COUNT, self._detected["mppt_count"])
            if self._detected.get("battery_count") is not None:
                current.setdefault(CONF_BATTERY_COUNT, self._detected["battery_count"])
            if self._detected.get("inverter_power_kw") is not None:
                current.setdefault(CONF_INVERTER_POWER_KW, self._detected["inverter_power_kw"])

        return self.async_show_form(
            step_id="topology",
            data_schema=self._topology_schema(current),
            description_placeholders=self._topology_placeholders(),
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._config.update(_normalize_numeric_config(user_input))
            return self.async_create_entry(title=cast(str, self._config[CONF_NAME]), data=self._config)
        current = {**self._config}
        current.setdefault(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        current.setdefault(CONF_SCAN_INTERVAL_MEDIUM, current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        current.setdefault(CONF_SCAN_INTERVAL_FAST, current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        current.setdefault(CONF_INVERTER_NAME_SUFFIX, DEFAULT_INVERTER_NAME_SUFFIX)
        current.setdefault(CONF_ENERGY_DASHBOARD_DEVICE, DEFAULT_ENERGY_DASHBOARD_DEVICE)
        current.setdefault(CONF_READ_EPS, DEFAULT_READ_EPS)
        current.setdefault(CONF_READ_DCB, DEFAULT_READ_DCB)
        current.setdefault(CONF_READ_PM, DEFAULT_READ_PM)
        current.setdefault(CONF_TIME_OUT, DEFAULT_TIME_OUT)
        return self.async_show_form(step_id="settings", data_schema=self._settings_schema(current))


class OptionsFlowHandler(_FlowMixin, OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        OptionsFlow.__init__(self)
        _FlowMixin.__init__(self)
        self._config_entry = config_entry
        self._config = _entry_config(config_entry)
        self._topology_baseline = {
            CONF_MPPT_COUNT: self._config.get(CONF_MPPT_COUNT),
            CONF_BATTERY_COUNT: self._config.get(CONF_BATTERY_COUNT),
        }

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                current_name = self._config.get(CONF_NAME)
                self._config.update(await self._validate_base(dict(user_input), current_name=current_name))
                return await self.async_step_connection()
            except ValueError as ex:
                errors["base"] = str(ex)
        return self.async_show_form(step_id="init", data_schema=self._base_schema(self._config), errors=errors)

    async def async_step_connection(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        interface = (user_input or self._config).get(CONF_INTERFACE, self._config.get(CONF_INTERFACE, DEFAULT_INTERFACE))
        allow_continue = True
        if user_input is not None:
            continue_without_detection = bool(user_input.pop("continue_without_detection", False))
            try:
                merged = {**self._config, **user_input}
                await self._validate_connection(merged)
                self._config.update(user_input)
                self._detected = await _detect_existing_plugin_state_with_timeout(self.hass, self._config)
                if not self._detected.get("success") and not continue_without_detection:
                    errors["base"] = "cannot_detect"
                else:
                    return await self.async_step_topology()
            except ValueError as ex:
                errors["base"] = str(ex)
        current = {**self._config, CONF_INTERFACE: interface}
        return self.async_show_form(
            step_id="connection",
            data_schema=self._connection_schema(current, allow_continue=allow_continue),
            errors=errors,
        )

    async def async_step_topology(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            raw_input = dict(user_input)
            recreate_entities = bool(raw_input.pop("recreate_entities", False))
            normalized_input = _normalize_numeric_config(raw_input)
            proposed = {**self._config, **normalized_input}
            self._recreate_entities_required = _topology_reduced(self._topology_baseline, proposed)
            self._recreate_entities_selected = recreate_entities
            self._config.update(normalized_input)
            self._config[CONF_READ_BATTERY] = bool(self._config.get(CONF_BATTERY_COUNT, 0) > 0)
            return await self.async_step_settings()

        current = {**self._config}
        if self._detected.get("success"):
            if self._detected.get("mppt_count") is not None:
                current.setdefault(CONF_MPPT_COUNT, self._detected["mppt_count"])
            if self._detected.get("battery_count") is not None:
                current.setdefault(CONF_BATTERY_COUNT, self._detected["battery_count"])
            if self._detected.get("inverter_power_kw") is not None:
                current.setdefault(CONF_INVERTER_POWER_KW, self._detected["inverter_power_kw"])

        return self.async_show_form(
            step_id="topology",
            data_schema=self._topology_schema(current, include_recreate_entities=True),
            description_placeholders=self._topology_placeholders(),
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._config.update(_normalize_numeric_config(user_input))
            if self._recreate_entities_selected and _topology_reduced(self._topology_baseline, self._config):
                await _remove_all_entry_entities(self.hass, self._config_entry.entry_id)
            return self.async_create_entry(title="", data=self._config)
        current = {**self._config}
        current.setdefault(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        current.setdefault(CONF_SCAN_INTERVAL_MEDIUM, current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        current.setdefault(CONF_SCAN_INTERVAL_FAST, current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        current.setdefault(CONF_INVERTER_NAME_SUFFIX, DEFAULT_INVERTER_NAME_SUFFIX)
        current.setdefault(CONF_ENERGY_DASHBOARD_DEVICE, DEFAULT_ENERGY_DASHBOARD_DEVICE)
        current.setdefault(CONF_READ_EPS, DEFAULT_READ_EPS)
        current.setdefault(CONF_READ_DCB, DEFAULT_READ_DCB)
        current.setdefault(CONF_READ_PM, DEFAULT_READ_PM)
        current.setdefault(CONF_TIME_OUT, DEFAULT_TIME_OUT)
        return self.async_show_form(step_id="settings", data_schema=self._settings_schema(current))
