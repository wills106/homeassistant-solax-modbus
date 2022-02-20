[![ko-fi](https://www.ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/V7V51QQOL)

[Octopus.Energy 🐙](https://share.octopus.energy/wise-boar-813) referral code. You get £50 credit for joining and I get £50 credit.
 
# homsassistant-solax-modbus
SolaX Power Modbus custom_component for Home Assistant
 
# Installation
Copy the folder and contents of solax_modbus into to your home-assistant config/custom_components folder.
After reboot of Home-Assistant, this integration can be configured through the integration setup UI

# Known Issues

1. ~~Tick boxes in configflow have no Text.~~ - Fixed!
2. ~~Only supports reading at the moment., writing to registers not net implemented.~~ Write support for Run Mode, Charge from Grid Mode, Min Battery Capacity & Charge / Discharge rate of battery
3. ~~Gen3 X3 Not yet implemented.~~ Gen3 X3 - Supported.
4. ~~Only supports Modbus over TCP. Serial / RS485 not yet implemented.~~ Serial / RS485 now supported.
5. ~~The sensors do not support the new "Energy" Dashboard in 2021.08.x and onwards.~~ Sensors now support the new "Energy" Dashboard in 2021.08.x and onwards. (Gen3 X1 & X3 only, Gen 2 doesn't support it unfortunately. Look at [solar_bits.yaml](https://github.com/wills106/homeassistant-config/blob/master/packages/solar_bits.yaml) for how to setup the Integration - Integration)
6. You can only have one connection to the inverter, so you can't use this and one of my yaml [packages](https://github.com/wills106/homeassistant-config/tree/master/packages) at the same time.
7. Possible Warnings about blocking call in the event loop (in systems with serial modbus connection).

## Version 0.0.2
<details>
  <summary>Click to expand!</summary>

BMS Connect State

Start and End Times for Force-Time-Mode Formatted

House Load

Import, Export & Solar Daily Energy working in Energy Dashboard
</details>

## Version 0.1.0
<details>
  <summary>Click to expand!</summary>

EPIC Version bump to 0.1.0

Issue 1 no longer exists, working config screen!

![Issue1](https://github.com/wills106/homsassistant-solax-modbus/blob/main/images/issue1b.PNG)
</details>

## Version 0.2.0
<details>
  <summary>Click to expand!</summary>

More Optional Sensors

X3 Support

X1 EPS Sensors

X3 EPS Sensors
</details>

## Version 0.2.1
<details>
  <summary>Click to expand!</summary>

New Optional Sensors - Only seem to update when Import / Exporting?
- Consumed Energy Total
- Feedin Energy Total

Total Energy To Grid - Tweaked to see if it returns sensible figure?

SolaX Today's Export Energy - Rounded to two places and moved to Gen3 only

SolaX Today's Export Energy - Rounded to two places and moved to Gen3 only

Added missing sensors to Gen3 X3
- Battery Current Charge
- Battery Voltage Charge
</details>

## Version 0.2.2
<details>
  <summary>Click to expand!</summary>

Converted all Sensors to use SensorEntityDescription

Removed Optional Sensors - Now form part of the main Sensor Group, but disabled by default

Updated Energy Dashboard compatibility for 2021.9x Version of Home Assistant

Renamed "Input Energy Charge Today" & "Output Energy Charge Today" to "Battery Input Energy Today" & "Battery Output Energy Today" Now compatible with the Energy Dashboard
</details>
 
## Version 0.3.0
<details>
  <summary>Click to expand!</summary>

Write Support!
- Run Mode
- Charge periods in Force Time Use Mode
- Min Battery Capacity
- Charge / Discharge rate of battery

@mickemartinsson Has done a Swedish Translation

Default names of new select / number
- select.solax_run_mode_select
- select.solax_grid_charge_select
- number.solax_battery_minimum_capacity
- number.solax_battery_charge
- number.solax_battery_discharge

Battery Charge/Discharge Limits
Gen 2 - 50Amp (I don't know if this applies to all Batteries on the Gen 2 or just the Pylon Tech. Be very careful!)
Every other setup 20Amp

![Battery1](https://github.com/wills106/homsassistant-solax-modbus/blob/main/images/battery1.png)
</details>

## Version 0.3.1
<details>
  <summary>Click to expand!</summary>

Corrected Gen2 Values
</details>

## Version 0.3.2
<details>
  <summary>Click to expand!</summary>

Added missing Language Mappings for Language Register
</details>

## Version 0.3.3
<details>
  <summary>Click to expand!</summary>

Added:

EPS Sensors:
- EPS Auto Restart
- EPS Min Esc SOC
- EPS Min Esc Voltage

Gen 3 Sensors:
- Backup Charge End
- Backup Charge Start
- Backup Gridcharge
- Cloud Control (Disabled by default)
- CT Meter Setting (Disabled by default)
- Discharge Cut Off Capacity Grid Mode (Disabled by default)
- Discharge Cut Off Point Different (Disabled by default)
- Discharge Cut Off Voltage Grid Mode (Disabled by default)
- Forcetime Period 1 Maximum Capacity
- Forcetime Period 2 Maximum Capacity
- Global MPPT Function (Disabled by default)
- Machine Style (Disabled by default)
- Meter 1 id (Disabled by default)
- Meter 2 id (Disabled by default)
- Meter Function (Disabled by default)
- Power Control Timeout (Disabled by default)
- wAS4777 Power Manager (Disabled by default)

Gen 3 X3 Sensors:
- Earth Detect X3
- Grid Service X3
- Phase Power Balance X3

Number:
- ForceTime Period 1 Max Capacity
- ForceTime Period 2 Max Capacity

Also corrected "Select Naming" & Adjusted Gen2 rounding
</details>

## Version 0.3.4
<details>
  <summary>Click to expand!</summary>

Corrected X3 Inverter Power Scaling


Corrected spelling mistakes


Fixed House Load showing Zero when charging from the Grid. Should also fix House Load showing zero when Battery is empty.
</details>

## Version 0.4.0

# ATTENTION: Gen4 is Work in progress - only tested for X3, Gen4 X1 not tested - Use at your own risk !!!!
Great thanks to @infradom for help adding in Serial Modbus and the Gen 4
- Add support for X3 Gen4 (X1 Gen4 should work also, but completely untested)
- Add support for serial Modbus RTU connection (needed as the Gen4 modbus is not accessible over TCPIP)
I am using a low-cost 2€ usb-to-RS485 adapter. By default Gen4 device is set to 19200 baud.
![setup-screen-gen4](https://user-images.githubusercontent.com/11804014/154648472-c7c53269-0618-4580-bbc3-b17c7a16105c.png)
If you are trying this on a non Hybrid (X1 Air, X1 Mini, X1 Boost) start off without setting any of the tick boxes and see what values you have.

## Version 0.4.1
Fixed the following:
- number.solax_battery_minimum_capacity now survives restart of HA

## Version 0.4.2
Fixed the following:
Gen2 X1
- sensor.solax_battery_charge_float_voltage
- sensor.solax_battery_discharge_cut_off_voltage
- sensor.solax_export_control_user_limit

Gen2 & Gen3
- select.solax_run_mode_select now select.solax_charger_use_mode
- select.solax_grid_charge_select now select.solax_allow_grid_charge
Changed response from sensor.solax_allow_grid_charge
- "Forbidden"
- "Charger Time 1"
- "Charger Time 2"
- "Both Charger Time's"

to
- "Both Forbidden",
- "Period 1 Allowed",
- "Period 2 Allowed",
- "Both Allowed
Now matches the state of select.solax_allow_grid_charge
- select.solax_charger_use_mode & select.solax_allow_grid_charge survies a restart of HA and also responds to changes made through the SolaX Cloud portal

Set the following to be hidden as default due to them being duplicates of select / number entries
- sensor.solax_allow_grid_charge
- sensor.solax_battery_charge_max_current
- sensor.solax_battery_discharge_max_current
- sensor.solax_battery_minimum_capacity
- sensor.solax_charger_use_mode
