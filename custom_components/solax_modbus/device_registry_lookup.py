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

from homeassistant.const import __version__
from homeassistant.helpers.device_registry import DeviceEntry, DeviceRegistry

# A device identifier is a 3-element tuple: (domain, device_name, device_type).
DeviceIdentifier = tuple[str, str, str]

# The via-device link in ``DeviceInfo`` changed name in HA 2026.8: the deprecated
# ``via_device`` tuple key was replaced by the config-entry-scoped ``via_device_id``.
VIA_DEVICE_ID_MIN_VERSION = (2026, 8)


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


def _ha_version() -> tuple[int, int]:
    """Return the installed Home Assistant version as a (major, minor) tuple."""
    # ``__version__`` looks like "2026.8.0" (or "2026.8.0.dev0" on core-dev).
    head = __version__.split(".")[0:2]
    try:
        return (int(head[0]), int(head[1]))
    except (IndexError, ValueError):
        return (0, 0)


def via_device_key() -> str:
    """Return the ``DeviceInfo`` key that links a sub-device to its parent.

    On HA 2026.8+ the key is ``via_device_id`` (a device id, config-entry scoped);
    on older versions it is ``via_device`` (a ``(domain, name, type)`` identifier
    tuple). Keeping this in one place means callers never set a key that the
    installed Home Assistant does not understand.
    """
    return "via_device_id" if _ha_version() >= VIA_DEVICE_ID_MIN_VERSION else "via_device"
