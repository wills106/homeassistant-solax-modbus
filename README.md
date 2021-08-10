# homsassistant-solax-modbus
SolaX Power Modbus custom_component for Home Assistant

# Installation
Copy the folder and contents of solax_modbus into to your home-assistant config/custom_components folder.
After reboot of Home-Assistant, this integration can be configured through the integration setup UI

# Known Issues

1. Tick boxes in configflow have no Text.
![Issue1](https://github.com/wills106/homeassistant-solax-modbus/blob/master/images1/issue1.png)
They are:
Gen2 X1
Gen3 X1
Gen3 X3
2. Only supports reading at the moment., writing to registers not net implemented.
3. Gen3 X3 Not yet implemented.
4. Only supports Modbus over TCP. Serial / RS485 not yet implemented.
