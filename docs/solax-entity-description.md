# Description of entities

Note available entities differ based on your inverter model.

## active_power



## battery_awaken



## battery_capacity

Current charge percentage of your batteries. Note this might not be accurate when they are cold or no full charge-discharge cycle was performed for a long time.

## battery_charge_upper_soc

Upper limit of battery SoC. Overrides any other battery SoC upper limits.

## battery_charge_max_current & battery_discharge_max_current

Sets maximal battery charge and discharge current. You should not change this.

## battery_heating

Enables battery heating in selected time periods (`battery_heating_end_time_1`, `battery_heating_end_time_2`, `battery_heating_start_time_1` and `battery_heating_start_time_2`).

## battery_input_energy_today

Amount of energy your inverter stored to the battery today (either from PV or charge from grid).

## battery_power_charge & battery_current_charge

Actual current & power the battery is charged with. Negative values mean the battery is discharged.

## battery_state_of_health

Life percentage of your batteries.

## battery_temperature

Shows the internal battery temperature. Could help you to decide if you need to use battery heating.

## battery_voltage_charge

Actual voltage of the battery. Zero, if inverter is in Idle mode.

## charger_use_mode

Sets the use mode of your inverter.

## consume_off_power



## ct_cycle_detection



## eps_mode_without_battery

Enables you to use EPS mode without a battery installed. This will be probably very unstable and you can face issues.

## eps_mute

If enabled, your inverter will not beep while in EPS mode.

## export_control_user_limit

Maximal power your inverter will send to the grid. It is recommended to have this value lower than your limit by the grid manager to avoid fines.

## extend_bms_setting

This is just my opinion, anyone is free to fix this. Used when you want to install another battery to your existing setup, so your batteries will have the same SOC as the new one.

## grid_import & grid_export

Current power your house network imports & exports to the grid.

## hotstandby

Enables the inverter to switch self to StandBy mode, if load is low (about 100 W). In StandBy mode the inverter has lower consumption and does not power the load. If the load rises, the inverter leaves StandBy mode in 5 minutes.

## house_load

Current power your home network consumes.

## inverter_arm_firmware_minor_version

Only for Gen 4 inverters, 1.xx is your ARM firmware version.

## inverter_dsp_firmware_minor_version

Only for Gen 4 inverters, 1.xx is your DSP firmware version.

## inverter_temperature

Shows internal inverter temperature, you can use this information to know if your inverter overheats. Shows no value when the inverter is in idle mode.

## lease_mode


## measured_power

Current power as measured by main grid connection CT or meter. Positive values indicate export and negative values indicate import.

This entity is used in remote control (VPP) modes to monitor grid power such as negative-injection/zero-export modes.

### measured_power_offset/measured_power_gain

If your setup uses a CT (current transformer), the measured power may not be accurate - they are typically 3-10% tolerances which can include a zero-offset. As of writing there SolaX does not provide on all inverters a method to calibrate this measurement value (some older generations had such an option). Inaccuracies in this measurement affect the calculated house load, and can cause problems with remote control modes at low power levels.

To achieve more accurate results from remote control modes, two additional optional configuration entities, `measured_power_offset` and `measured_power_gain` are provided to allow the sensor values to be calibrated. The values shown in home assistant will be scaled by the chosen values.

The raw value from the inverter is corrected by first adding `measured_power_offset` (W), and then multiplying by `measured_power_gain` (%).

The calibration values are disabled by default, and the default values (offset = 0, gain = 100%) mean no correction is applied to the value.

To calculate the correct values, you will need a smart meter which provides real-time power information (e.g. with Octopus Home Mini, IHD, or reported values on the meter screen itself).
1. Find a time when you have a relatively stable import (exact value doesn't matter, but say >> 1kW). Record the power reported by the `measured_power` sensor and the smart meter in Watts, ideally take a few readings over a minute or so and average them.
2. Find a period of relatively stable export (exact value doesn't matter, but say >> 1kW). Again record the power reported by the `measured_power` sensor and the smart meter in Watts, again ideally take an average.
3. Calculate the factors for the equation `smart_meter = gain * (measured_power + offset)` where:<br>
   * `gain` is calculated as `abs(smart_meter {charge} - smart_meter {discharge}) / abs(measured_power {discharge} - measured_power {charge})` <br>
   * `offset` is then `(smart meter {charge} / gain) - measured_power {charge}`
4. Enter the `offset` value as calculated (in Watts). Enter the `gain` value multiplied by 100 (as the entity has units of %).

Typical offsets will be +/-50W, and gains 90-110%. If you get values outside this range, considered repeating the measurements.

## manual_mode_select

Behavior of the manual mode, enable by `manual_mode_control`.

## manual_mode_control

Activates and deactivates manual mode.

## peakshaving*



## pgrid_bias

Changes behavior of your inverter. When `inverter`, your inverter will supply around 40 Watts less to your home network, so if your load decreases, there will be much lower overshoot energy to the grid (useful if you have no permission to sell energy to the grid). When `grid` your inverter will supply 40 Watts more than your load, so when load increases, you will less likely use grid energy. 

## phase_power_balance_x3

If enabled, your inverter will send power to your network based on your load. E.g. your phases are loaded 0 kW, 4 kW and 1 kW, so the inverter power will be 0, 4 and 1 kW on phases. If disabled, your inverter will always have the same power on all phases.

## remotecontrol*



## selfuse_backup_soc

When in self use backup mode, battery usage will be stopped when reaching this capacity.

## selfuse_discharge_min_soc

When in self use mode, battery usage will be stopped when reaching this capacity.

## selfuse_mode_backup

Turns on backup mode in self use mode. Only difference is that `selfuse_backup_soc` is used instead of `selfuse_discharge_min_soc`.

## selfuse_nightcharge_upper_soc

The upper battery SoC to charge the battery from grid in Selfuse mode, if `selfuse_night_charge_enable` is enabled.

## shadow_fix_function_level

Also called GMPPT, find it online.

## today_s_import_energy & today_s_export_energy

Amount of energy your inverter imported exported to grid today. Might need RTC sync for proper values.

## unlock_inverter & unlock_inverter_advanced

Some settings might need to have inverter unlocked, so press this button if your changes do not persist AND YOUR INVERTER IS NOT IN IDLE MODE.
