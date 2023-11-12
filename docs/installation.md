# Installation

Before proceeding, [set up your Modbus adaptor](modbus-adaptor-setup.md) first.

## Installing the integration

### Via HACS - recommended

You can search this integration in HACS, install it and restart your Home Assistant core.

### Manual installation

There should be no need to use this method, but this is how:

- Download the zip / tar.gz source file from the release page.
- Extract the contents of the zip / tar.gz
- In the folder of the extracted content you will find a directory 'custom_components'.
- Copy this directory into your Home-Assistant '<config>' directory so that you end up with this directory structure: '<config>/custom_components/solax_modbus
- Restart Home Assistant

## Pair your inverter

Now it's only needed to add your inverter to Home Assistant.

- Navigate to your `Devices & services`.
- Click `ADD INTEGRATION`
- Search and select `SolaX Inverter Modbus`
    - Select correct Modbus address, look at your inverter if the default one does not work.
![](images/integration-setup.png)
- If you use RS485 to Ethernet adaptor:
    - Enter IP address of your adaptor.
![](images/integration-setup-tcpip.png)
- If you use RS485 to USB adaptor:
    - Select the right port.
    - Enter correct baud rate that does match setting on your inverter.
![](images/integration-setup-usb.png)