# homeassistant-solax-modbus
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs) [![ko-fi](https://www.ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/V7V51QQOL)

[Octopus.Energy 🐙](https://share.octopus.energy/wise-boar-813) referral code. You get £50 credit for joining and I get £50 credit.

## Summary

Universal Solar Inverter over Modbus RS485 / TCP custom_component for Home Assistant

**Integration 2024.09.1 and newer only supports HA 2024.9.0 and newer**

* Supports Modbus over RS485 & TCP. **Please check the Docs for [Compatible RS485 Adaptors](https://homeassistant-solax-modbus.readthedocs.io/en/latest/compatible-adaptors/)**

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
   - SPF - **WIP**
   - SPH
   - TL-XH (MIN & MOD)
  
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
  - Azzurro ZSS
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
- Gen3 AC, Hybrid & RetroFit
- Gen4 Hybrid & RetroFit
  - Qcells Q.VOLT HYB-G3-3P
  - TIGO TSI
- Gen5 Hybrid
- J1 Hybrid - **WIP**
- X1 Air/Boost/Mini Gen3 & Gen4 (Limited set of entities available)
- X3 MEGA / FORTH Gen2 (Limited set of entities available)
- X3 MIC / MIC PRO Gen1 & Gen2 (Limited set of entities available)

</details>
Solinteg - WIP

SRNE - WIP

Swatten -WIP
      </li>
    </ul>
</ul>



## Installation

[Read the Docs - Installation](https://homeassistant-solax-modbus.readthedocs.io/en/latest/installation/)

## Documentation

For further Documentation please refer to the [Read the Docs](https://homeassistant-solax-modbus.readthedocs.io/)

## FAQ

[Read the Docs - General FAQ](https://homeassistant-solax-modbus.readthedocs.io/en/latest/faq/)
 - [Read the Docs - Sofar FAQ](https://homeassistant-solax-modbus.readthedocs.io/en/latest/sofar-faq/)
 - [Read the Docs - SolaX FAQ](https://homeassistant-solax-modbus.readthedocs.io/en/latest/solax-faq/)

## Multiple Connections

Modbus is designed to mostly have a single Master.
If you try to connect multiple instances to the Inverter ie this Integration and Node-RED the Inverter will either block the second connection or likely to result in data collisions.

If this happens it's recomended to use a multiplexer such as https://github.com/IngmarStein/tcp-multiplexer this has been tested by reading and writing from two instances of HA at once.

This can be started with Docker or Docker Compose.
Example Compose:

```
services:
  modbus-proxy:
    image: ghcr.io/ingmarstein/tcp-multiplexer
    container_name: modbus_proxy
    ports:
      - "5020:5020"
    command: [ "server", "-t", "192.168.123.123:502", "-l", "5020", "-p", "modbus", "-v" ]
    restart: unless-stopped
```

Server address is the Inverter / data logger.
You then direct this integration to the machine running the proxy and port 5020 in this example.