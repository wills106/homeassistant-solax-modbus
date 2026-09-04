"""Shared helpers for config-entry-scoped device registry lookups.

Home Assistant 2026.8 made device identifiers and connections unique *per
config entry*. The legacy ``device_registry.async_get_device(identifiers=...)``
lookup is therefore deprecated (breaking in HA 2027.8.0) because the same
identifier can belong to devices owned by different config entries.

This module centralises a single, typed helper that prefers the scoped
``async_get_device_by_identifier`` API while retaining compatibility with
older HA versions that only expose the legacy ``async_get_device`` lookup.
"""

from collections.abc import Callable
from typing import cast

from homeassistant.helpers.device_registry import DeviceEntry, DeviceRegistry

# A device identifier is a 3-element tuple: (domain, device_name, device_type).
DeviceIdentifier = tuple[str, str, str]


def _scoped_lookup(registry: DeviceRegistry) -> Callable[[DeviceIdentifier, str], DeviceEntry | None]:
    """Return ``async_get_device_by_identifier`` when available, else the legacy lookup.

    The returned callable is typed for the scoped API. When falling back to the
    legacy ``async_get_device`` we wrap it so the signature matches the scoped
    API: it ignores the config-entry scope and matches on the identifier alone.
    """
    scoped = getattr(registry, "async_get_device_by_identifier", None)
    if scoped is not None:
        return cast(
            Callable[[DeviceIdentifier, str], DeviceEntry | None],
            scoped,
        )

    legacy = registry.async_get_device

    def _fallback(identifier: DeviceIdentifier, _config_entry_id: str) -> DeviceEntry | None:
        # The legacy API expects a set of identifier tuples.
        identifiers = {cast(tuple[str, str], identifier)}
        return legacy(identifiers=identifiers)

    return _fallback


def get_device_by_identifier(
    registry: DeviceRegistry,
    identifier: DeviceIdentifier,
    config_entry_id: str,
) -> DeviceEntry | None:
    """Look up a device scoped to ``config_entry_id``.

    Uses ``async_get_device_by_identifier`` on HA 2026.8+ and transparently
    falls back to the legacy ``async_get_device`` lookup on older versions.
    """
    scoped_lookup = _scoped_lookup(registry)
    return scoped_lookup(identifier, config_entry_id)
