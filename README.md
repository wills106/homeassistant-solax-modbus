[![ko-fi](https://www.ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/V7V51QQOL)

[Octopus.Energy 🐙](https://share.octopus.energy/wise-boar-813) referal code. You get £50 credit for joining and I get £50 credit.

# homsassistant-solax-modbus
SolaX Power Modbus custom_component for Home Assistant

# Installation
Copy the folder and contents of solax_modbus into to your home-assistant config/custom_components folder.
After reboot of Home-Assistant, this integration can be configured through the integration setup UI

# Known Issues

1. Tick boxes in configflow have no Text. - Fixed!
2. Only supports reading at the moment., writing to registers not net implemented.
3. Gen3 X3 - Supported.
4. Only supports Modbus over TCP. Serial / RS485 not yet implemented.
5. Sensors now support the new "Energy" Dashboard in 2021.08.x and onwards. (Gen3 X1 & X3 only, Gen 2 doesn't support it unfortunately. Look at [solar_bits.yaml](https://github.com/wills106/homeassistant-config/blob/master/packages/solar_bits.yaml) for how to setup the Integration - Integration)
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
