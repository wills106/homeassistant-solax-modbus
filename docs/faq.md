# FAQ

## I have a question that is not answered here

Always also check vendor specific FAQ pages:

- [SolaX Power](solax-faq.md)
- [Sofar Solar](sofar-faq.md)

## Detailed Error Log
[![Open your Home Assistant instance and display logs.](https://my.home-assistant.io/badges/logs.svg)](https://my.home-assistant.io/redirect/logs/)

Settings → System → Logs > at bottom of page press “LOAD FULL LOGS”
Now the full logs are loaded. If you scroll down, you will see them. Once the full logs are shown, you can either use the search function in your browser to search for “solax” related entries or use the search entry field on top of the page.
Search for solax and report us the logs. Make sure to replace sensitive information by xxxx (if any)

If the log doesn't return anything useful add the following to your `configuration.yaml`
```
logger:
  default: info
```

## Detected blocking call

This issue is resolved in the 2024.02.6 version of the integration. Please update.

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

## Unable to control Inverter when PV = 0 & Battery SOC is at Minimum

This isn't a fault with the Integration.
PV and Hybrid Inverters are designed to produce electricity and not consume.

- PV Inverter's when PV = 0 they shut down.
- Hybrid Inverter's when PV = 0 and Battery reaches Minimum SOC they shut down.

If you want to charge during the night you need to set a charge Window before the Hybrid Inverter shuts down.

## Unrecognized XYZ inverter type - serial number : unknown

If you get **unrecognized XYZ inverter type - serial number : unknown** you don't have a working Modbus connection.
Don't raise an issue, this isn't a fault of the Integration.
Either use one of the [existing discussions](https://github.com/wills106/homeassistant-solax-modbus/discussions?discussions_q=%22Unrecognized+Inverter%22) or start a new one to understand how to communicate with your Inverter.