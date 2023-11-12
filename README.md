# homeassistant-solax-modbus
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs) [![ko-fi](https://www.ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/V7V51QQOL)

[Octopus.Energy 🐙](https://share.octopus.energy/wise-boar-813) referral code. You get £50 credit for joining and I get £50 credit.

## Summary

Universal Solar Inverter over Modbus RS485 / TCP custom_component for Home Assistant

**Integration 2023.09.4 and newer only supports HA 2023.9.2 and newer. Support for pyModbus below 3.5.2 has been dropped. For HA installations older than 2023.9.0 Integration 2023.09.3 is the last supported version**

* Supports Modbus over RS485 & TCP. **Please check the Wiki for [Compatible RS485 Adaptors](https://github.com/wills106/homeassistant-solax-modbus/wiki/Compatible-RS485-Adaptors)**

<ul>
    <ul>
      <li>
       <details>
<summary>
Ginlong Solis
</summary>

- RHI-nK-48ES-5G Single Phase (lowercase n indicates Inverter size, ie 6kW)
- RHI-3PnK-HVES-5G Three Phase (lowercase n indicates Inverter size, ie 10kW)

</details>
      </li>
      <li>
       <details>
<summary>
Growatt:
</summary>

 - AC Battery Storage:
   - SPA
  
 - Hybrid:
   - SPH
   - TL-XH
  
 - PV Only:
   - MAC
   - MAX
   - MID
   - TL-X

</details>
      </li>
      <li>
       <details>
<summary>
Sofar Solar
</summary>

- HYDxxKTL-3P (plugin_sofar)
  - Azzurro 3.3k-12KTL-V3
- HYDxxxxES (plugin_sofar_old)

</details>
      </li>
      <li>
       <details>
<summary>
SolaX Power
</summary>

- A1 Hybrid - **WIP**
- Gen2 Hybrid
- Gen3 AC, Hybrid & Retrofit
- Gen4 Hybrid
  - Qcells Q.VOLT HYB-G3-3P
  - TIGO TSI
- J1 Hybrid - **WIP**
- X3 MIC / MIC PRO (Limited set of entities available)
- X1 Air/Boost/Mini (Limited set of entities available)

</details>
      </li>
    </ul>
</ul>

You can have multiple instances of this Integration, just change the default Prefix from SolaX to something else. Ie. `SolaX Main` or `SolaX Southwest`.

<details>
<summary>
SolaX - PocketLAN & PocketWiFi Readme
</summary>

**(Pocket LAN does not provide a Modbus connection at all and the Pocket WiFi v1 & v2 does not provide a reliable Modbus connection! Trouble shooting for Pocket WiFi v1 or v2 will not be provided)**

#### Pocket WiFi 3.0 with Firmware V3.004.03 and above is only [officially supported](https://kb.solaxpower.com/data/detail/ff8080818407e2a701840a22dec20032.html). SolaX only mentions Gen4 Hybrid, other inverters may work?
- **Contact SolaX for latest version.**

(⚠I still don't recomend the PocketWiFi. If you loose all entites after normal operation, try power cycling your Inverter.

Another approach to fixing previously working PocketWiFi installs is to restart your rooter and then reload the integration in Home Assistant. If that doesn't work you can unplug PocketWifi usb for 30 seconds and plug it in again, then reload the integration. 

Updating / downgrading the integration or Home Assitant won't help, you have lost the internal Modbus connection between the Inverter and PocketWiFi and I am unable to assist with this issue.⚠)
</details>

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