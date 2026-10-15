# Move from a YAML Modbus hub to a Home Assistant managed connection

> **Requires Home Assistant 2026.10 or later for the new connection API.** Install an integration release containing this migration before changing your YAML. Older Home Assistant releases continue using the existing YAML hub.

The YAML instructions in this guide apply if you selected **Hass core Hub** when setting up SolaX Inverter Modbus. Direct **TCP / Ethernet** connections move automatically to the new API on Home Assistant 2026.10 or later; see [Automatic TCP migration](#automatic-tcp-migration).

## Why you see the notification

Home Assistant is replacing the old API used to access Modbus hubs configured in YAML. The old API will be removed in **Home Assistant 2027.10**.

Your inverter continues to use its existing connection while the YAML hub is present. On Home Assistant 2026.10 or later, the integration saves a copy of the connection settings so it can use the new API after you remove that hub and restart Home Assistant. Older versions continue using YAML unchanged; they do not copy settings or show the migration notification yet. It does not open a second connection during this transition.

The old API and its Home Assistant deprecation warning remain in use while the YAML hub is configured or still running. This is intentional: switching immediately could open a second connection and interfere with other users of that hub. The warning disappears only after the old hub is removed and Home Assistant is restarted.

Your integration name, entity IDs and automations are kept. Do not delete and re-add the integration.

## Connection behavior

| Situation | Behavior |
| --- | --- |
| The selected YAML hub is still configured | Copy its connection settings and continue using the existing hub. Show a migration notification; do not open a second connection. |
| YAML was removed, but the old hub is still running | Keep using the old hub until Home Assistant is restarted. |
| YAML was removed and Home Assistant was restarted | Use the saved settings through the new Home Assistant Modbus API. Dismiss the migration notification. |
| Other entities or integrations still need the YAML hub | Keep the YAML hub and continue sharing its existing connection until those users are migrated too. |
| A new Home Assistant Modbus connection is configured | Use the new API without a YAML hub or dummy sensor. If a YAML hub already occupies the endpoint, do not open a competing connection. |
| Home Assistant is older than 2026.10 | Keep existing YAML hub connections working; do not offer the new connection options. |

The new connection opens on the first Modbus request, including inverter identification during setup. Home Assistant manages connection sharing and reconnection. Unloading this integration releases its use of the connection; other consumers are not disconnected.

## Before removing anything

1. Use **Home Assistant 2026.10 or later**. The first unit API appeared in 2026.9, but that release does not provide the timeout and startup-delay controls needed to preserve your connection settings.
2. Install the integration update containing this migration and restart Home Assistant **with your existing YAML hub still configured**. This lets the integration copy the settings first.
3. Check the notification. It must say that the connection settings have been saved. If it says they could not be saved, keep the YAML hub and follow the instructions in that message.
4. Back up your Home Assistant configuration.

## If the hub is used only by this integration

The notification names the hub to remove. Find that name under `modbus:` in `configuration.yaml`, or in a file included from it.

For example, if the notification names `inverter_bus`:

```yaml
modbus:
  - name: inverter_bus
    type: tcp
    host: 192.168.1.50
    port: 502
```

1. Remove the complete `inverter_bus` item, including its connection settings. Keep any other Modbus hub items.
2. If this was the only item under `modbus:`, remove the now-empty `modbus:` section too.
3. Check your Home Assistant configuration, then restart Home Assistant. Reloading only the SolaX integration is not enough to stop the old YAML connection.
4. Check that the inverter entities update normally. The integration now uses the saved settings through Home Assistant's new Modbus API, and the migration notification disappears.

No IP address, port or serial settings need to be entered again.

## If the hub has other users

Check whether the hub contains real `sensors:`, `switches:`, `binary_sensors:` or other Modbus entities, or whether another custom integration refers to its name.

Removing the complete hub would also remove or disconnect those users. Keep the YAML hub until they have been migrated as well. The SolaX integration will continue using that existing connection in the meantime.

Some older setups contain a dummy sensor created only to allow the hub to start. If you are certain that it is just a dummy and is not used in a dashboard or automation, it can be removed with the hub.

The new connection does not automatically migrate Home Assistant's YAML Modbus entities or other integrations. Two independently opened connections to the same adapter can interfere with each other, especially on a serial bus or an adapter that only supports one client.

Conflict checks compare the configured address and port, ignoring hostname case, a trailing hostname dot and IPv6 formatting differences. TCP, RTU/ASCII-over-TCP and equivalent `socket://host:port` serial URLs are treated as the same TCP endpoint. DNS aliases (including a hostname versus its IP address) and different filesystem paths to the same serial adapter are not resolved. Use the same address or stable serial path in all configurations; an alias must not be used to bypass the check.

## If the inverter stops updating after the change

Restore the YAML hub from your backup and restart Home Assistant. The integration will use it again. Keep the migration notification and relevant logs when reporting the problem.

## New installations

Select **TCP / Ethernet** to use a Home Assistant-managed TCP connection on HA 2026.10 or later. On older HA versions, the same choice uses the integration's direct TCP client. Modbus TCP, RTU over TCP and ASCII over TCP remain available. No YAML hub or dummy sensor is required for a managed connection.

Home Assistant manages and shares these connections between integrations using the same connection settings. The connection opens on the first request and reconnects as needed.

## Automatic TCP migration

On Home Assistant 2026.10 or later, existing direct TCP connections switch to Home Assistant's shared Modbus API at the next startup or integration reload. No manual changes, deletion or reconfiguration are needed for normal TCP setups.

- The same config entry, integration name, devices, entity IDs and automations are kept.
- Host/IP, port, Modbus address, TCP framing, timeout and polling settings are retained. All three framing options are supported.
- Reloading closes the old native connection before preparing the managed one. Settings are validated and YAML endpoint conflicts checked before the migration is saved.
- Older HA versions retain the native TCP client without migration. An entry already migrated to the new API requires HA 2026.10 or later.
- Existing **Home Assistant Modbus (TCP)** entries already use this API and now appear as **TCP / Ethernet** in the interface selector.

**Compatibility note:** TCP communication now uses HA's tmodbus backend rather than the integration's Pymodbus client. Timeout, retry, reconnect and protocol-error handling are not identical. Some inverters or TCP bridges may therefore behave differently or encounter communication problems after migration, even though their settings are retained. If this happens, share a debug log and your inverter/bridge details; do not delete and recreate the integration. Shared connections also use the highest timeout required by their consumers.

Serial connections and the staged YAML hub migration are outside the scope of this TCP change.

## Scope and dependencies

The integration declares Home Assistant's `modbus` integration as a dependency so HA installs its version-matched Modbus libraries and loads the public API before setup or config flows use it. This applies to all installations, but loading `modbus` without YAML hubs does not open a Modbus connection. Only a configured YAML hub or a request through the shared unit API opens a link.

See Home Assistant's [Modbus API migration announcement](https://developers.home-assistant.io/blog/2026/09/02/modbus-get-hub-deprecation/) for background.
