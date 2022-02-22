[![ko-fi](https://www.ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/V7V51QQOL)

[Octopus.Energy 🐙](https://share.octopus.energy/wise-boar-813) referral code. You get £50 credit for joining and I get £50 credit.

# homsassistant-solax-modbus
SolaX Power Modbus custom_component for Home Assistant
Support Modbus over RS485 & TCP
You can have multiple instances of this Integration

Supports:
Gen2 Hybrid
Gen3 Hybrid
Gen4 Hybrid

Gen2, Gen3 & Gen4

- Charge / Discharge rate of battery
- Charger Use Mode

Gen2 & Gen3

- Allow Grid Charge
- Charge periods in Force Time Use Mode
- Min Battery Capacity

Gen3 & Gen4

- Sensors support the "Energy" Dashboard in 2021.08.x and onwards.

Gen3

- ForceTime Period 1 Max Capacity
- ForceTime Period 2 Max Capacity

Gen4

- Backup Discharge Min SOC
- Backup Nightcharge Upper SOC
- Charge / Discharge rate of battery
- Charge and Discharge Period2 Enable
- Export Control User Limit
- Feedin Discharge Min SOC
- Feedin Nightcharge Upper SOC
- Manual Mode Select
- Selfuse Discharge Min SOC
- Selfuse Night Charge Enable
- Selfuse Nightcharge Upper SOC

Untested:
Non Hybrid Models ie Solar PV only
 
# Installation
Copy the folder and contents of solax_modbus into to your home-assistant config/custom_components folder.
After reboot of Home-Assistant, this integration can be configured through the integration setup UI

# Known Issues

1. You can only have one connection to the inverter, so you can't use this and one of my yaml [packages](https://github.com/wills106/homeassistant-config/tree/master/packages) at the same time for writing to registers.
2. Possible Warnings about blocking call in the event loop (in systems with serial modbus connection).
3. You need to manually add select and number entries to your lovelace card if you manually control your front end.

Gen2, Gen3 & Gen4

- number.solax_battery_charge_max_current
- number.solax_battery_discharge_max_current
- select.solax_charger_use_mode

Gen2 & Gen3

- number.solax_battery_minimum_capacity
- select.solax_allow_grid_charge

Gen3
- number.solax_forcetime_period_1_max_capacity
- number.solax_forcetime_period_2_max_capacity

Gen4

- number.solax_backup_discharge_min_soc
- number.solax_backup_nightcharge_upper_soc
- number.solax_charge_discharge_rate_of_battery
- number.solax_export_control_user_limit
- number.solax_feedin_discharge_min_soc
- number.solax_feedin_nightcharge_upper_soc
- number.solax_selfuse_discharge_min_soc
- number.solax_selfuse_nightcharge_upper_soc
- select.solax_charge_and_discharge_period2_enable
- select.solax_manual_mode_select
- select.solax_selfuse_night_charge_enable
