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

#### **(Pocket LAN does not provide a Modbus connection at all and the Pocket WiFi v1 & v2 does not provide a reliable Modbus connection! Trouble shooting for Pocket WiFi v1 or v2 will not be provided)**

#### Pocket WiFi 3.0 with Firmware V3.004.03 and above is only [officially supported](https://kb.solaxpower.com/solution/detail/ff8080818407e2a701840a22dec20032). SolaX only mentions Gen4 Hybrid, other inverters may work?
- **Contact SolaX for latest version.**

(⚠I still don't recomend the PocketWiFi. If you loose all entites after normal operation, try power cycling your Inverter.

Another approach to fixing previously working PocketWiFi installs is to restart your rooter and then reload the integration in Home Assistant. If that doesn't work you can unplug PocketWifi usb for 30 seconds and plug it in again, then reload the integration. 

Updating / downgrading the integration or Home Assitant won't help, you have lost the internal Modbus connection between the Inverter and PocketWiFi and I am unable to assist with this issue.⚠)
</details>

<details>
<summary>

## Installation

</summary>

[Setup](https://github.com/wills106/homeassistant-solax-modbus/wiki/Installation-Notes) your modbus adapter first.

<B>Preferred Option</B>

You can add this custom_component directly through HACS, if you have HACS installed on your Home Assistant instance.

<B>Alternatively</B>

Download the zip / tar.gz source file from the release page.
- Extract the contents of the zip / tar.gz
- In the folder of the extracted content you will find a directory 'custom_components'.
- Copy this directory into your Home-Assistant '<config>' directory so that you end up with this directory structure: '<config>/custom_components/solax_modbus
- Restart Home-Assistant

<B>Post Installation</B>

After reboot of Home-Assistant, this integration can be configured through the integration setup UI

<img src="https://user-images.githubusercontent.com/18155231/200254318-265189d5-34e2-459e-9933-cdb05c05977b.png" width=40% height=40%>

TCP

<img src="https://user-images.githubusercontent.com/18155231/182889165-2b304b6d-f548-4551-a34c-d190ff510992.png" width=40% height=40%>

Serial

<img src="https://user-images.githubusercontent.com/18155231/182894989-e9767f7b-6c5e-482d-bc6e-8c2c7b8f9445.png" width=40% height=40%>

Any manual updates / HACS updates require a restart of Home Assistant to take effect.
- Any major changes might require deleting the Integration from the Integration page and adding again. If you name the Integration exactly the same including the Area if set, you should retain the same entity naming bar any name changes in the release. (Refer to the release notes for any naming change)

</details>

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

## FAQ

<details>
<summary>
1. <em>Help, entity I need is not present!</em>
</summary>
Your desired entity is most likely disabled. Example given is for "Config Max Export"
>Go to the SolaX Integration page.
>
>Find "+xy entities not shown"
>
>Click those till you find "Config Max Export"
>
>Then Cog/Gear icon.
>
>There is an option to enable it and press "UPDATE"
</details>

<details>
<summary>
2. <em>If the Integration fails to load with the following error in your log "unrecognized inverter type - serial number : {your_serial_number_here}" or "unrecognized inverter type - firmware version : {your_firmware_version_here}"</em>
</summary>
Please use one of the following discussions providing the details asked for:

<ul>
    <ul>
      <li><a href="https://github.com/wills106/homeassistant-solax-modbus/discussions/523">Growatt</a></li>
      <li><a href="https://github.com/wills106/homeassistant-solax-modbus/discussions/522">Sofar</a></li>
      <li><a href="https://github.com/wills106/homeassistant-solax-modbus/discussions/520">SolaX</a></li>
      <li><a href="https://github.com/wills106/homeassistant-solax-modbus/discussions/521">Solis</a></li>
    </ul>
</ul>
</details>

<details>
<summary>
3. <em>SolaX Only - unable to change values (read only)</em>
</summary>
If you can read values, but unable to adjust select / number you need to press the "Unlock Inverter" button. Might need performing again following a full Power Cycle*
</details>

<details>
<summary>
4. <em>Check a python module version eg pyModbus:</em>
</summary>

Virtual Machine - Goto the console:
```
   ha > login
   # docker exec -it homeassistant /bin/bash
   pip show pymodbus
```
   Docker (Core) - Goto the console:
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
</details>
