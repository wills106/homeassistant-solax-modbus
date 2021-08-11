# homsassistant-solax-modbus
SolaX Power Modbus custom_component for Home Assistant

# Installation
Copy the folder and contents of solax_modbus into to your home-assistant config/custom_components folder.
After reboot of Home-Assistant, this integration can be configured through the integration setup UI

# Known Issues

1. Tick boxes in configflow have no Text.
![Issue1](https://github.com/wills106/homsassistant-solax-modbus/blob/main/images/issue1a.PNG)

They are:
- Gen2 X1
- Gen3 X1
- Gen3 X3
- Optional Sensors
2. Only supports reading at the moment., writing to registers not net implemented.
3. Gen3 X3 Not yet implemented.
4. Only supports Modbus over TCP. Serial / RS485 not yet implemented.
5. Sensors now support the new "Energy" Dashboard in 2021.08.x and onwards.
6. You can only have one connection to the inverter, so you can't use this and one of my yaml [packages](https://github.com/wills106/homeassistant-config/tree/master/packages) at the same time.

Version 0.0.2
BMS Connect State
Start and End Times for Force-Time-Mode Formatted
House Load
Import, Export & Solar Daily Energy working in Energy Dashboard
