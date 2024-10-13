# Installation

Before proceeding, [set up your Modbus adaptor](modbus-adaptor-setup.md) first.

## Installing the integration

### Via HACS - recommended

Use this button to install the integration:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?repository=homeassistant-solax-modbus&owner=wills106)

### Manual installation

There should be no need to use this method, but this is how:

- Download the zip / tar.gz source file from the release page.
- Extract the contents of the zip / tar.gz
- In the folder of the extracted content you will find a directory 'custom_components'.
- Copy this directory into your Home-Assistant '<config>' directory so that you end up with this directory structure: '<config>/custom_components/solax_modbus
- Restart Home Assistant Core

## Pair your inverter

Now it's only needed to add your inverter to Home Assistant.
 - a) Click this button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=solax_modbus)

 - b) if your setup does not support My Home Assistant:
    - Navigate to your `Devices & services`.
    - Click `ADD INTEGRATION`
    - Search and select `SolaX Inverter Modbus`
- You can have multiple instances of this Integration, just change the default Prefix from SolaX to something else. Ie. `SolaX Main` or `SolaX Southwest`.
- Select correct Modbus address, look at your inverter if the default one does not work.
![](images/integration-setup.png)
- Only Sofar and Solinteg take advantage of the different poll speeds. "The default polling interval of the modbus registers in seconds" is the one to reduce from 15 if required. Do not try and poll quicker that 5s on Inverters with a baud of 9600.
- If you use RS485 to Ethernet adaptor:
    - Enter IP address of your adaptor.
![](images/integration-setup-tcpip.png)
- If you use RS485 to USB adaptor:
    - Select the right port.
      - If your installation has a tendancy to swap between ttyUSB0 and ttyUSB1 you can define it by the id
      - /dev/serial/by-id/usb-xyz
    - Enter correct baud rate that does match setting on your inverter.
![](images/integration-setup-usb.png)
- If you use Hass core HUB:
    - Enter the hub name.
![](images/integration-setup-corehub.png)
