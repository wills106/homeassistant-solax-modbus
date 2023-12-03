# Ginlong Solis Modes of Operation - WIP

## Energy Storage Control Switch

## Auto Mode - No Grid Charge

Description

## Timed Charge/Discharge - No Grid Charge

This retains the functionality of the timed charge/discharge mode but limits the battery charging to solar only.

## Auto Mode / Self-Use

For most people, this will be the most common mode of operation.
In this mode, the home load will come from following sources in the given priority:
* Solar, for the amount of solar energy available
* Battery, as long as the battery State Of Charge (SOC) is above the "Battery Capacity" level (Default 10%)
* Grid, for the remaining missing power

Excess solar energy will go to Battery first, till the battery reaches the nearly full level.
Once the battery is nearly full (95%), excess energy will go to the grid. Once the battery is completely full, all excess energy will go to the grid.

~The power sent to the grid can be limited with the "Export Control User Limit" parameter.
Battery charge and discharge currents can be limited with the "Battery Charge Max Current" and "Battery Discharge Max Current" parameters.~

## Timed Charge/Discharge

Description

## Off-Grid Mode

Description

## Battery Awaken

Description

## Battery Awaken + Timed Charge/Discharge

Description

## Backup/Reserve

Description

## Timed Charge / Discharge
**(At present HA before 2023.6 doe not support time entities, so the time is split into separate number entities)**

There are three charge / discharge blocks available. (The other blocks end with 2 & 3)

Each block consists off:
* 'timed_charge_start_h'
* 'timed_charge_start_m'
* 'timed_charge_end_h'
* 'timed_charge_end_m'
* 'timed_discharge_start_h'
* 'timed_discharge_start_m'
* 'timed_discharge_end_h'
* 'timed_discharge_end_m'

Within 120s of making your first change the corresponding "Update Charge/Discharge Times" button needs to be pressed, otherwise the number will revert back to the stored value.

These values will only be written to the Inverter after pressing the "Update Charge/Discharge Times" button this is due to all 8 time entities need to be written as a single 'write_registers' block.