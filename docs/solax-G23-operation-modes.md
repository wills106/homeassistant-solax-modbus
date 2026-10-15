# SolaX Gen2 & Gen3 Modes of Operation

Work in progress, some of this information may be inaccurate

## Export Control User Limit
By default "Export Control User Limit" is based off the datasheet for your specific model. This is to make the slider on the number entity more manageable.

If you are running multiple Inverters at a property you will limit the total Grid Export to the maximum value "Export Control User Limit" is set to.

To allow maximum export you can override "Export Control User Limit" with "Config Max Export" (Disabled by default) you can then define a new upper limit which will apply to "Export Control User Limit"

## Self Use
For most people, this will be the most common mode of operation.
In this mode, the home load will come from following sources in the given priority:
- Solar, for the amount of solar energy available
- Battery, as long as the battery State Of Charge (SOC) is above the "Battery Capacity" level (Default 10%)
- Grid, for the remaining missing power

Excess solar energy will go to Battery first, till the battery reaches the nearly full level.
Once the battery is nearly full (95%), excess energy will go to the grid. Once the battery is completely full, all excess energy will go to the grid.

The power sent to the grid can be limited with the "Export Control User Limit" parameter.
Battery charge and discharge currents can be limited with the "Battery Charge Max Current" and "Battery Discharge Max Current" parameters.

## Force Time
Allows Battery Charging from the Grid:
Allow Grid Charge has 4 sub-modes:
- Both Forbidden: Does not charge from the grid. Inverter won't consume from batteries during time slots if set.
- Period 1 Allowed: Charges from Grid during time set. Inverter won't consume from batteries during this time slot if set & Period 2 Allowed.
- Period 2 Allowed: Charges from Grid during time set. Inverter won't consume from batteries during this time slot if set & Period 1 Allowed.
- Both Allowed: Charges from Grid during both time slots. Handy if you have more dynamic Grid Pricing.

### Gen2 compatibility note
On a tested Gen2 SK-SU3000E (U30E), the Force Time mode, charge window, Allow Grid Charge setting and charge-current limit could all be written and read back correctly, but the configured charge window did not start grid charging. This may be model- or firmware-specific; confirmation from other Gen2 models is welcome.

### Modbus address note (Gen2)
The tested SK-SU3000E (U30E) shows an unusual but repeatable difference between Modbus address / unit ID `1` and `0`.

With integration address `1`, registers could be read and changes could be written and read back. However, changes to the Gen2 remote battery power register `0x51` were not physically acted upon by the inverter. After changing the integration Modbus address to `0`, the same `0x51` setpoints were executed immediately and reproducibly for both charging and discharging.

This is consistent with earlier testing in [issue #73](https://github.com/wills106/homeassistant-solax-modbus/issues/73), where register reads worked with integration address `1`, while control only started working after changing the integration address to `0`.

At the same time, holding register `0x84` (`MyAddress`) still reports `1`. Since Modbus address `0` is normally the broadcast address, this should not be interpreted as evidence that the inverter itself is configured as address `0`.

The exact reason for this discrepancy is not understood and may be specific to the inverter, gateway, firmware or Modbus transport implementation. Address `0` should therefore not be presented as a general Gen2 requirement. However, if Gen2 remote power setpoints can be written and read back but have no physical effect, trying integration Modbus address `0` is a useful compatibility test.

## Back Up Mode / Remote Control Mode (Gen2)
The Gen2 Modbus protocol names mode value `2` **Remote control mode**. The integration currently labels this option **Back Up Mode**.

On Gen2, Remote control mode activates the signed battery power setpoint in register `0x51` (`wExt_SetChargerPower` in the Gen2 protocol):

- Positive values: force battery charging
- `0 W`: neutral / hold battery power around zero
- Negative values: force battery discharging

The setpoint is not applied while the inverter is in Self Use mode. This means the order in which the mode and power setpoint are changed is not important: the stored setpoint becomes active when Remote control mode is selected, and Self Use continues normal self-consumption operation regardless of the stored setpoint.

No System On/Off toggle is required for normal remote power control. The Gen2 remote switch register `0x1C` is the inverter software start/stop control; writing `0` stops the inverter.

The behavior above has been verified on an SK-SU3000E (U30E). A requested power above the inverter/battery capability was accepted and limited by the inverter to the available hardware power.

## Feedin Priority (Gen 3 Only)
In Feedin Priority mode, the home load comes from following sources in the given priority:
- Solar
- Grid
The battery will not discharge.

Excess solar energy will go to the grid. If the grid power has been limited with the "Export Control User Limit" parameter, the remaining surplus power will go to the battery.

## Remote Battery Power (Gen 2 Only)

**Warning, forced charging or discharging may or may not increase the wear on your Inverter / Battery Setup. Use at own risk**

The existing `number.solax_grid_export_limit` entity maps to Gen2 register `0x51`. Despite the historical entity name, the Gen2 protocol defines this register as `wExt_SetChargerPower`, a signed battery power setpoint.

### Set battery power
- Set `number.solax_grid_export_limit` to the desired battery power setpoint, from `-5000 W` to `+5000 W`.
- Set `select.solax_charger_use_mode` to "Back Up Mode" (Remote control mode in the Gen2 protocol).

Examples:
- `+1000 W`: force charging at approximately 1000 W
- `0 W`: neutral / hold
- `-1000 W`: force discharging at approximately 1000 W

The inverter may clamp the requested value to its own battery/inverter power limit.

### Return to normal operation
- Set `select.solax_charger_use_mode` to "Self Use Mode" or the mode normally used.
- Setting `number.solax_grid_export_limit` back to `0 W` is optional for Self Use operation, but can be useful to leave a neutral stored setpoint for the next time Remote control mode is selected.

### Automation Example
[Gen2 & Gen3 Export Example](https://github.com/wills106/homeassistant-solax-modbus/discussions/110)

## Grid Export (Gen 3 Only)

**Warning, forced discharging may or may not increase the wear on your Inverter / Battery Setup. Use at own risk**

Present from 0.6.0
### Precursors
- Set `select.solax_export_duration` to the time period of dynamic export pricing. For example if your rate changes every 30 Minutes, set it to that.
- Set `number.solax_battery_minimum_capacity_grid_tied` to the Minimum SOC you wish to discharge to.

### Operation
- Trigger `button.solax_grid_export`
- Set `number.solax_grid_export_limit` to desired export level. 0 to -6000
- After time set in `select.solax_export_duration` the Inverter will return to normal mode of Operation, unless you trigger `button.solax_grid_export` again.

### Cancel Grid Export
- Set `select.solax_export_duration` to default. Reverts back to normal operation after 4 seconds.

### Automation Example
[Gen2 & Gen3 Export Example](https://github.com/wills106/homeassistant-solax-modbus/discussions/110)