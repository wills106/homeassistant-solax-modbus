# FAQ

## I have a question that is not answered here

Always also check vendor specific FAQ pages:

- [SolaX Power](solax-faq.md)
- [Sofar Solar](sofar-faq.md)

## Detected blocking call
If you use a UART-RS485 or USB-RS485 adaptor you will get the following errors in the log
```
Detected blocking call to sleep inside the event loop by custom integration 'solax_modbus' 
```
As a work around you can add the following lines to your configuration file:
```
logger:
  filters:
    homeassistant.util.async_:
      - ".*blocking call.*solax_modbus.*"
```

## Donations / Sponsor

Please don't use / expect Donations as a form of paid technical support.

I was asked to add the option to recieve donations as people wanted to buy me a Beer/Cola or multiples as a form of thanks.

## Entity I need is not present

Your desired entity is most likely disabled. Example given is for "Config Max Export"

- Go to the SolaX Integration page.
- Find "+xy entities not shown"
- Click those till you find "Config Max Export"
- Then Cog/Gear icon.
- There is an option to enable it and press "UPDATE"

## How to check a version of a python module e.g. pyModbus

- Virtual Machine - Goto the console:

```
   ha > login
   # docker exec -it homeassistant /bin/bash
   pip show pymodbus
```
   
- Docker (Core) - Goto the console:

```
   pip show pymodbus
```

To list all modules:

```
   Replace:
   pip show pymodbus
   With:
   pip list
```

## unrecognized XYZ inverter type - serial number : unknown

If you get **unrecognized XYZ inverter type - serial number : unknown** you don't have a working Modbus connection.
Don't raise an issue, this isn't a fault of the Integration.
Either use one of the existing discussions or start a new one to understand how to communicate with your Inverter

## Unable to control Inverter when PV = 0 & Battery SOC is at Minimum

This isn't a fault with the Integration.
PV and Hybrid Inverters are designed to produce electricity and not consume.

- PV Inverter's when PV = 0 they shut down.
- Hybrid Inverter's when PV = 0 and Battery reaches Minimum SOC they shut down.

If you want to charge during the night you need to set a charge Window before the Hybrid Inverter shuts down.