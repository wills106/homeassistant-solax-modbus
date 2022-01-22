[![ko-fi](https://www.ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/V7V51QQOL)

[Octopus.Energy 🐙](https://share.octopus.energy/wise-boar-813) referral code. You get £50 credit for joining and I get £50 credit.

# homsassistant-solax-modbus
SolaX Power Modbus custom_component for Home Assistant

 DO NOT USE THIS FORK CODE YET !!!! Work in progress - 
 
 
# Installation
Copy the folder and contents of solax_modbus into to your home-assistant config/custom_components folder.
After reboot of Home-Assistant, this integration can be configured through the integration setup UI

# Known Issues

1. ~~Tick boxes in configflow have no Text.~~ - Fixed!
2. ~~Only supports reading at the moment., writing to registers not net implemented.~~ Write support for Run Mode, Charge from Grid Mode, Min Battery Capacity & Charge / Discharge rate of battery
3. ~~Gen3 X3 Not yet implemented.~~ Gen3 X3 - Supported.
4. Only supports Modbus over TCP. Serial / RS485 not yet implemented.
5. ~~The sensors do not support the new "Energy" Dashboard in 2021.08.x and onwards.~~ Sensors now support the new "Energy" Dashboard in 2021.08.x and onwards. (Gen3 X1 & X3 only, Gen 2 doesn't support it unfortunately. Look at [solar_bits.yaml](https://github.com/wills106/homeassistant-config/blob/master/packages/solar_bits.yaml) for how to setup the Integration - Integration)
6. You can only have one connection to the inverter, so you can't use this and one of my yaml [packages](https://github.com/wills106/homeassistant-config/tree/master/packages) at the same time.

## Version 0.0.2

BMS Connect State

Start and End Times for Force-Time-Mode Formatted

House Load

Import, Export & Solar Daily Energy working in Energy Dashboard

## Version 0.1.0

EPIC Version bump to 0.1.0

Issue 1 no longer exists, working config screen!

![Issue1](https://github.com/wills106/homsassistant-solax-modbus/blob/main/images/issue1b.PNG)


## Version 0.2.0

More Optional Sensors

X3 Support

X1 EPS Sensors

X3 EPS Sensors

## Version 0.2.1

New Optional Sensors - Only seem to update when Import / Exporting?
- Consumed Energy Total
- Feedin Energy Total

Total Energy To Grid - Tweaked to see if it returns sensible figure?

SolaX Today's Export Energy - Rounded to two places and moved to Gen3 only

SolaX Today's Export Energy - Rounded to two places and moved to Gen3 only

Added missing sensors to Gen3 X3
- Battery Current Charge
- Battery Voltage Charge

## Version 0.2.2

Converted all Sensors to use SensorEntityDescription

Removed Optional Sensors - Now form part of the main Sensor Group, but disabled by default

Updated Energy Dashboard compatibility for 2021.9x Version of Home Assistant

Renamed "Input Energy Charge Today" & "Output Energy Charge Today" to "Battery Input Energy Today" & "Battery Output Energy Today" Now compatible with the Energy Dashboard

## Version 0.3.0

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

## Version 0.3.1
Corrected Gen2 Values

## Version 0.3.2
Added missing Language Mappings for Language Register

## Version 0.3.3
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

## Version 0.3.4
Corrected X3 Inverter Power Scaling


Corrected spelling mistakes


Fixed House Load showing Zero when charging from the Grid. Should also fix House Load showing zero when Battery is empty.

## Version xxx
- Add support for X3 Gen4 (X1 Gen4 should work also, but completely untested)
- Add support for serial Modbus RTU connection (needed as the Gen4 modbus is not accessible over TCPIP)
I am using a low-cost 2€ usb-to-RS485 adapter. By default Gen4 device is set to 19200 baud.
