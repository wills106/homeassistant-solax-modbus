"""Protocol definitions for SolaX Modbus plugins.

This module defines the Protocol that all plugin modules must implement,
providing type safety and consistency across all 17 plugins.

Note: This file is named protocols.py (not plugin_*.py) to avoid
being detected as an actual plugin by test patterns that match plugin_*.py
"""

from types import ModuleType
from typing import Any, Protocol, TypedDict

from .const import (
    BaseModbusButtonEntityDescription,
    BaseModbusNumberEntityDescription,
    BaseModbusSelectEntityDescription,
    BaseModbusSensorEntityDescription,
    BaseModbusSwitchEntityDescription,
)


class PluginRegistersDict(TypedDict, total=False):
    """Type definition for plugin registers dictionary.

    Used by plugins to define which registers to read from the inverter.
    """

    holdingRegs: dict[int, Any]
    inputRegs: dict[int, Any]
    readPreparation: Any  # Callable for pre-read setup
    readFollowUp: Any  # Callable for post-read processing


class PluginProtocol(Protocol):
    """Protocol that all plugin modules must implement.

    Each plugin is a Python module that exports specific module-level
    attributes defining the entities it provides and metadata about
    the supported inverter models.

    Example:
        ```python
        # In plugin_solax.py
        SENSOR_TYPES: list[BaseModbusSensorEntityDescription] = [...]
        BUTTON_TYPES: list[BaseModbusButtonEntityDescription] = [...]
        # ... etc
        ```
    """

    # Required entity type lists
    SENSOR_TYPES: list[BaseModbusSensorEntityDescription]
    BUTTON_TYPES: list[BaseModbusButtonEntityDescription]
    NUMBER_TYPES: list[BaseModbusNumberEntityDescription]
    SELECT_TYPES: list[BaseModbusSelectEntityDescription]
    SWITCH_TYPES: list[BaseModbusSwitchEntityDescription]

    def matchInverterWithMask(
        self,
        invertertype: int,
        bitmask: int,
        serialnumber: str,
        blacklist: dict[str, int] | None,
    ) -> bool:
        """Match inverter type against bitmask and blacklist.

        Args:
            invertertype: The inverter type identifier
            bitmask: Bitmask defining which inverter types are supported
            serialnumber: Inverter serial number
            blacklist: Optional dict of serial prefixes to exclude

        Returns:
            True if inverter matches and is not blacklisted
        """
        ...

    def wakeupButton(self) -> BaseModbusButtonEntityDescription | None:
        """Return the button entity description for waking up the inverter.

        Returns:
            Button description for wakeup functionality, or None if not supported
        """
        ...


def is_plugin_module(module: ModuleType) -> bool:
    """Check if a module implements the PluginProtocol.

    Args:
        module: Python module to check

    Returns:
        True if module has all required plugin attributes
    """
    required_attrs = [
        "SENSOR_TYPES",
        "BUTTON_TYPES",
        "NUMBER_TYPES",
        "SELECT_TYPES",
        "SWITCH_TYPES",
        "matchInverterWithMask",
        "wakeupButton",
    ]
    return all(hasattr(module, attr) for attr in required_attrs)
