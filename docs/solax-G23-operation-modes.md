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

## Back Up Mode (Labelled Remote Mode on Gen2)
Prevents battery discharging.
- Designed for EPS use if you for example of unstable Grid connection during set periods of the day. 
- Handy for saving battery capacity for expensive Grid Periods.

## Feedin Priority (Gen 3 Only)
In Feedin Priority mode, the home load comes from following sources in the given priority:
- Solar
- Grid
The battery will not discharge.

Excess solar energy will go to the grid. If the grid power has been limited with the "Export Control User Limit" parameter, the remaining surplus power will go to the battery.

## Grid Export (Gen 2 Only)

**Warning, forced discharging may or may not increase the wear on your Inverter / Battery Setup. Use at own risk**

Present from 0.6.0
### Precursors
Note, if you use "Back Up Mode" to prevent Battery discharge, remember to set `number.solax_grid_export_limit` back to zero
- Set `number.solax_grid_export_limit` to desired export level. 0 to -5000

### Start Discharge
- Set `select.solax_charger_use_mode` to "Back Up Mode"

### Stop Discharge
- Set `select.solax_charger_use_mode` to "Self Use Mode" or Mode normally kept in.

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