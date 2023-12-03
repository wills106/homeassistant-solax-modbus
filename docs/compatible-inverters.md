# Compatible inverters

## Ginlong Solis

### Single Phase

RHI-nK-48ES-5G (lowercase n indicates Inverter size, ie 6kW)
- Use plugin_solis

Known Serials
- 6031
- 1031

### Three Phase

RHI-3PnK-HVES-5G (lowercase n indicates Inverter size, ie 10kW)
- Use plugin_solis

Known Serials
- 110CA

## Sofar Solar

### Single Phase

#### Hybrid

HYDxxxxES
- Use plugin_sofar_old

Known Serials
- ZE1E
- ZM1E

### Three Phase

#### Hybrid

![Image of SP1ES](images/sofar-sp1s-photo.png)

HYD xxKTL
- Use plugin_sofar

HYD xxKTL-3PH
- Use plugin_sofar

Known Serials
- SP1
- SP2

#### PV Only

4.4 KTLX-G3
- Use plugin_sofar

Known Serials
- SS2E

## SolaX

### AC / Battery Storage

#### Single Phase

##### AC / RetroFit

X1-AC-n.n

![image](images/solax-g2-hybrid-photo.png)

> Must be connected by serial Modbus.

Known Serial Numbers G3
- XAC36 (3.6kW version)

Known Serial Numbers G4
- PRE
- PRI

#### Three Phase

##### RetroFit G3

X3-Fit-nn.nx

> Must be connected by serial Modbus.

Known Serial Numbers
- F3D
- F3E

### Hybrid Gen2

#### Single Phase

![Image of SK-TL](images/solax-g2-hybrid-photo.png)

> Features built in Ethernet

SK-TL (External BMS)

Known Serials
- L30
- L37
- L50

SK-SU (Built in BMS)

Known Serials
- U30
- U37
- U50

#### Three Phase

?

### Hybrid Gen3

#### Single Phase

![Photo of SolaX X3 Hybrid G3](images/solax-x1-hybrid-g3-photo.png)

> Features built in Ethernet

X1-Hybrid-n.n-x-x

Known Serial Numbers
- H1E
- HCC
- HUE
- XRE

#### Three Phase

X3-Hybrid-nn-x-x

X3-Hybrid-n.n-x-x

> Features built in Ethernet (might not be labeled as Ethernet, check this [discussion](https://github.com/wills106/homeassistant-solax-modbus/discussions/303))

Known Serial Numbers
- H3DE
- H3PE
- H3UE

### Hybrid Gen4 (Qcells Q.VOLT HYB-G3)

The Gen4 inverters do not feature built-in Ethernet. An external RS485 adapter is required. See [Modbus adaptor setup](modbus-adaptor-setup.md) wiki page.

#### Single Phase

X1-Hybrid-n.n-x

> Must be connected by serial Modbus.

Known Serial Number
- H43
- H450
- H460
- H475

#### Three Phase
![Photo of SolaX X3 Hybrid G4](images/solax-x3-hybrid-g4-photo.png)

X3-Hybrid-n.n-x

> Must be connected by serial Modbus.

Known Serial Numbers
- H34A
- H34B
- H34T

### PV Only

#### Single Phase

X1-Air, X1-Boost & X1-Mini

Only Firmware Arm 1.37 and above is supported.

**Modbus needs to be enabled in your Admin Menu on the Inverter.**

Firmware version below use a non standard protocol over RS485, they do no speak Modbus.

Known Serial Numbers
- XB3
- XMA
- XM3

#### Three Phase

X3 MIC

On Gen1 Modbus Power Meter support is provided with Firmware Arm 1.38 and above.
Gen2 does not provide reading from a Modbus Power Meter at present.

> Must be connected by serial Modbus.
> Don't poll below 5s, don't perform initial connection while Inverter asleep!

Known Serial Numbers
- MC10
- MC20
- MC21
- MC5
- MC7
- MP15
- MU80

## Untested or in Early Development Phase

### Single Phase

#### Ginlong Solis
Try plugin_solis & plugin_solis_old

Known Serial Numbers
- ???

#### Growatt
Try plugin_growatt

Known Serial Numbers
- ???

#### Sofar Solar
Try plugin_sofar & plugin_sofar_old

Known Serial Numbers
- ???

### Two Phase (Split Phase)

#### SolaX Power - A1
Try plugin_solax_a1j1

Known Serial Numbers
- ???

#### SolaX Power - J1
Try plugin_solax_a1j1

> Must be connected by serial Modbus.

Known Serial Numbers
- ???

### Three Phase

#### Ginlong Solis
Try plugin_solis & plugin_solis_old

Known Serial Numbers
- ???

#### Growatt
Try plugin_growatt

Known Serial Numbers
- ???

#### Sofar Solar
Try plugin_sofar & plugin_sofar_old

Known Serial Numbers
- ???