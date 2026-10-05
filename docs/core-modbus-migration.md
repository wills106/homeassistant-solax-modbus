# Move from a YAML Modbus hub to a Home Assistant managed connection

> **Draft — not yet released.** This branch prepares a future migration. Do not remove your YAML hub based on this draft. The minimum supported Home Assistant release will be confirmed once its Modbus API includes both timeout and startup-delay controls; Home Assistant 2026.9.4 does not provide these controls.

This guide applies if you selected **Hass core Hub** when setting up SolaX Inverter Modbus. Existing **TCP / Ethernet** and **Serial** connections are not affected.

## Why you see the notification

Home Assistant is replacing the old API used to access Modbus hubs configured in YAML. The old API will be removed in **Home Assistant 2027.10**.

Your inverter continues to use its existing connection while the YAML hub is present. The integration saves a copy of the connection settings so it can use the new API after you remove that hub and restart Home Assistant. It does not open a second connection during this transition.

Your integration name, entity IDs and automations are kept. Do not delete and re-add the integration.

## Before removing anything

1. Use a Home Assistant release that provides the Modbus unit API **including timeout and startup-delay controls**. The first unit API appeared in 2026.9, but it does not yet provide both controls in 2026.9.4. The minimum release for this migration will be confirmed before it is published.
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

## If the inverter stops updating after the change

Restore the YAML hub from your backup and restart Home Assistant. The integration will use it again. Keep the migration notification and relevant logs when reporting the problem.

## New installations

Select **Home Assistant Modbus (TCP)** or **Home Assistant Modbus (Serial)** in the integration setup, and enter the connection settings there. No YAML hub or dummy sensor is required.

Home Assistant manages and shares these connections between integrations using the same connection settings. The connection opens on the first request and reconnects as needed.

See Home Assistant's [Modbus API migration announcement](https://developers.home-assistant.io/blog/2026/09/02/modbus-get-hub-deprecation/) for background.
