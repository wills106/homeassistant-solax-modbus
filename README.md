# homeassistant-solax-modbus
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs) [![ko-fi](https://www.ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/V7V51QQOL)

[Octopus.Energy 🐙](https://share.octopus.energy/wise-boar-813) referral code. You get £50 credit for joining and I get £50 credit.

## Summary

Universal Solar Inverter over Modbus RS485 / TCP custom_component for Home Assistant

**Integration 2023.09.4 and newer only supports HA 2023.9.2 and newer. Support for pyModbus below 3.5.2 has been dropped. For HA installations older than 2023.9.0 Integration 2023.09.3 is the last supported version**

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
- J1 Hybrid - **WIP**
- X3 MIC / MIC PRO Gen1 & Gen2 (Limited set of entities available)
- X1 Air/Boost/Mini Gen3 & Gen4 (Limited set of entities available)

</details>
      </li>
    </ul>
</ul>

SRNE - **WIP**
Swatten - **WIP**

## Installation

[Read the Docs - Installation](https://homeassistant-solax-modbus.readthedocs.io/en/latest/installation/)

## Documentation

For further Documentation please refer to the [Read the Docs](http://homeassistant-solax-modbus.readthedocs.io/)

## FAQ

[Read the Docs - General FAQ](https://homeassistant-solax-modbus.readthedocs.io/en/latest/faq/)