# homeassistant-solax-modbus
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs) [![ko-fi](https://www.ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/V7V51QQOL)

[Octopus.Energy 🐙](https://share.octopus.energy/wise-boar-813) referral code. You get £50 credit for joining and I get £50 credit.

## Summary

Universal Solar Inverter over Modbus RS485 / TCP custom_component for Home Assistant

**Integration 2023.09.4 and newer only supports HA 2023.9.2 and newer. Support for pyModbus below 3.5.2 has been dropped. For HA installations older than 2023.9.0 Integration 2023.09.3 is the last supported version**

* Supports Modbus over RS485 & TCP. **Please check the Wiki for [Compatible RS485 Adaptors](https://github.com/wills106/homeassistant-solax-modbus/wiki/Compatible-RS485-Adaptors)**

You can have multiple instances of this Integration, just change the default Prefix from SolaX to something else. Ie. `SolaX Main` or `SolaX Southwest`.

<details>
<summary>

## Known Issues

1. You can only have one connection to the inverter, so you can't use this and one of my yaml [packages](https://github.com/wills106/homeassistant-config/tree/master/packages) at the same time for writing to registers.
2. Possible Warnings about blocking call in the event loop (in systems with serial modbus connection).

You can add the following lines to your configuration file:
```
logger:
  default: warning
  logs:
    homeassistant.util.async_: error
```
3. Please check the Todo List under discussions for other known issues and what's being worked on.
4. If your Inverter is asleep do not start this integration / restart HA as you will get the following error **"Modbus Error: [Connection] Failed to connect[Modbus"** You can't establish a connection if there is nothing to connect to.

## Documentation

For further Documentation please refer to the [Read the Docs](http://homeassistant-solax-modbus.readthedocs.io/)