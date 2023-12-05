# Desciption of entities

Note available entities differ based on your inverter model.

## active_power



## battery_awaken



## battery_capacity

Current charge percentage of your batteries. Note this might not be accurate when they are cold or no full charge-discharge cycle was performed for a long time.

## battery_charge_upper_soc



## battery_charge_max_current & battery_discharge_max_current

Sets maximal battery charge and discharge current. You should not change this.

## battery_heating

Enables battery heating in selected time periods (`battery_heating_end_time_1`, `battery_heating_end_time_2`, `battery_heating_start_time_1` and `battery_heating_start_time_2`).

## battery_input_energy_today

Amount of energy your inverter stored to the battery today (either from PV or charge from grid).

## battery_power_charge & battery_current_charge

Current current & power your battery is charged with. Negative values mean the battery is drained.

## battery_state_of_health

Life percentage of your batteries.

## battery_temperature

Shows the internal battery temperature. Could help you to decide if you need to use battery heating.

## battery_voltage_charge

Current voltage of your batteries. Works only if batteries are used at the moment.

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

Current power your house network imports & exports to the grid. Requires either a Modbus smart meter or CT clamps installed.

## hotstandby



## house_load

Current power your home network consumes.

## inverter_arm_firmware_minor_version

Only for Gen 4 inverters, 1.xx is your ARM firmware version.

## inverter_dsp_firmware_minor_version

Only for Gen 4 inverters, 1.xx is your DSP firmware version.

## inverter_temperature

Shows internal inverter temperature, you can use this information to know if your inverter overheats. Shows no value when the inventer is in idle mode.

## lease_mode



## manual_mode_select

Behavior of the manual mode, enable by `manual_mode_control`.

## manual_mode_control

Activates and deactivates manual mode.

## peakshaving*



## pgrid_bias

Changes behavior of your inverter. When `inverter`, your inverter will supply aroud 40 Watts less to your home network, so if your load decreases, there will be much lower overshoot energy to the grid (useful if you have no permission to sell energy to the grid). When `grid` your inverter will supply 40 Watts more than your load, so when load increases, you will less likely use grid energy. 

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

Target battery charge for night charging. Note my inverter overshoots this value, so your experience may vary.

## shadow_fix_function_level

Also called GMPPT, find it online.

## today_s_import_energy & today_s_export_energy

Amount of energy your inverter imported exported to grid today. Might need RTC sync for proper values.

## unlock_inverter & unlock_inverter_advanced

Some settings might need to have inverter unlocked, so press this button if your changes do not persist AND YOUR INVERTER IS NOT IN IDLE MODE.
