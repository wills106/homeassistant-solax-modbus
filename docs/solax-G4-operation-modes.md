# SolaX Gen4 Modes of Operation

WARNING: Work in progress, some of this information may be inaccurate. Use at your own risk

WARNING: most of the writeable parameters are written to EEPROM of the inverter after each modification. EEPROM has a limited (typically 100000) number of write cycles, so be careful that your automations do not modify these parameters too frequently.

## Export Control User Limit
By default "Export Control User Limit" is based off the datasheet for your specific model. This is to make the slider on the number entity more manageable.

If you are running multiple Inverters at a property you will limit the total Grid Export to the maximum value "Export Control User Limit" is set to.

To allow maximum export you can override "Export Control User Limit" with "Config Max Export" (Disabled by default) you can then define a new upper limit which will apply to "Export Control User Limit"

This override also applies to "External Generation Max Charge" "Remotecontrol Active Power" & "Remotecontrol Import Limit" 

## Self Use
For most people, this will be the most common mode of operation.
In this mode, the home load will come from following sources in the given priority:

- Solar, for the amount of solar energy available
- Battery, as long as the battery State Of Charge (SOC) is above the "Selfuse Discharge Min SOC" level
- Grid, for the remaining missing power

Excess solar energy will go to Battery first, till the battery reaches the nearly full level.
Once the battery is nearly full (95%), excess energy will go to the grid. Once the battery is completely full, all excess energy will go to the grid.

The power sent to the grid can be limited with the "Export Control User Limit" parameter.
Battery charge and discharge currents can be limited with the "Battery Charge Max Current" and "Battery Discharge Max Current" parameters.

Attention: The description above assumes that the charger time window is inactive, and that the discharge time window is active. If you would set the charger window to active for a certain time period, the battery may charge from grid.

## Feedin Priority
In Feedin Priority mode, the home load comes from following sources in the given priority:

- Solar
- Grid

Excess solar energy will go to the grid. If the grid power has been limited with the "Export Control User Limit" parameter, the remaining surplus power will go to the battery.

The battery will not discharge (unless the discharge time window is active). 
In this mode, **during the charging time window**, the battery may still be charged with excess solar energy (if the grid export is limited), up to the "Feedin ??? SOC" limit. During the active discharge time window, no battery charging occurs.

attention:

- if the charging time window is active, the grid will load battery and power the home load. 
> - if the discharge time window is active, battery will discharge to power the home load up to the set discharge limit

## Manual Mode
Manual mode has 3 sub-modes ("Manual Mode Select"):

- Stop Charge and Discharge: The charger/discharger part of the SolaX device is inactive. AFAIK, this does not mean that the PV subsystem stops delivering energy to the home load, battery and grid. AFAIK, only the charging from grid and discharging to grid is stopped.
- Force Charge: the batteries will be charged from the grid (and solar?), but limited by the "Battery Charge Max Current" and ..
- Force Discharge: the batteries will be discharged towards the grid, but limited by the "Export Control User Limit", the "Battery Discharge Max Current" and the inverter's limits. During force discharge, the grid may receive the sum of the PV power and the battery discharge power (minus house load). If the inverter's limits are reached, it seems like the battery discharge current will be limited (solar energy is not limited).

## Back Up Mode
Prevents battery discharging so that a guaranteed amount of energy is available to cover power outages

- Designed for EPS use if you for example of unstable Grid connection during set periods of the day. 
- Handy for saving battery capacity for expensive Grid Periods.
- minimum battery level can be set with the "Backup Discharge Min SOC" parameter (range 30 - 100%)
- it is possible to configure a night charge up to "Backup Nightcharge Upper SOC"
