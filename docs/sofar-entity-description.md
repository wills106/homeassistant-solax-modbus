# Description of Sofar Entities

WARNING: most of the writeable parameters are written to EEPROM of the inverter after each modification. EEPROM has a limited (typically 100000) number of write cycles, so be careful that your automations do not modify these parameters too frequently.

Very likely this document will always be work in progress ;-)

## Controls

Some of the entities cannot be written alone as Sofar requires several registers to be written together at once. A button that commits the values to the inverter is provided in such cases and needs to be pressed after related values are changed.

| Name | Description | Commit Button, if required |
| ---- | ----------- | -------------------------- |
| Energy Storage Mode | Sets the energy storage mode as described [here](sofar-energy-storage-modes.md). | |
| Passive Desired Grid Power | Set the desired power that is taken from the Grid. The system will try to achieve this level within the boundaries of the current consumption, the current production, and the boundaries set by the battery parameters below. Positive values indicate power flow from grid to the system (grid consumption). Negative values indicate power flow from system to the grid (feed-in). | Passive: Update Battery Charge/Discharge |
| Passive: Maximum Battery Power | Limit the maximum battery power. Must be greater than or equal to "Passive Minimum Battery Power". Positive values indicate charging, negative values indicate discharging. | Passive: Update Battery Charge/Discharge |
| Passive: Minimum Battery Power | Limit the minimum battery power. Must be less than or equal to "Passive Maximum Battery Power". Positive values indicate charging, negative values indicate discharging. | Passive: Update Battery Charge/Discharge |
| Passive: Timeout | The timeout after which the configured timeout action will be executed. | Passive: Update Timeout |
| Passive: Timeout Action | The timeout action that will be executed after which the configured timeout has passed. By default "Force Standby" is selected. "Return to Previous Mode" will set the previously selected "Energy Storage Mode", i.e. if the inverter was switched from "Self Use" into "Passive Mode" the inverter will switch back to "Self Use" after not receiving any communication for the configured "Passive: Timeout". | Passive: Update Timeout |
| Reflux: Control | Control whether and how much your system is allowed to feed-in to the grid. If disabled, no power will flow from your system to the grid. If enabled, no power will be fed in. Using "Enabled Set Value" you can limit the maximum amount of power that is fed-in. See [Reflux Control](sofar-reflux-control.md) for more information. | Reflux: Update |
| Reflux: Maximum Power | The maximum amount of power in Watts that is allowed to be fed-in to your grid from your system. | Reflux: Update |
| Remote Control| Enable/Disable remote control to your inverter. |  |
| Update System Time | Updates the system time of the inverter to the current time of the Home Assistant system. To check whether the write action was successful check the value of "Update System Time Operation Result". Note that while a logger is connected to the USB port and the logger has access to the public internet, the inverter will automatically regularly fetch the time from the Sofar servers. However you might have chosen to disallow the communication to the Sofar servers, or you do not have a logger installed on the system. In this case you can achieve a time synchronisation by regularly pressing this button through an automation. Do not hit this button too often as values will be written to the EEPROM.| |
| Timing: Control | Experimental: To be done |  |
| Timing: Charge | Experimental: To be done |  |
| Timing: Charge Power | Experimental: To be done | |
| Timing: Discharge Power | Experimental: To be done | |
| Timing: Discharge Power | Experimental: To be done | |
| Timing: ID| Experimental: To be done | |
| TOU: Charge Power| Experimental: To be done | |
| TOU: Control | Experimental: To be done | |
| TOU: ID | Experimental: To be done | |
| TOU: Target SOC | Experimental: To be done | |


## Sensors

Sensors should be self-explanatory and should not require additional documentation.

## Configuration
| Name | Description | Commit Button, if required |
| ---- | ----------- | -------------------------- |
| Timing: Charge End Time | Experimental: To be done | |
| Timing: Charge Start Time | Experimental: To be done | |
| Timing: Discharge End Time | Experimental: To be done | |
| Timing: Discharge Start Time | Experimental: To be done | |
| TOU: Charge End Time | Experimental: To be done | |
| TOU: Charge Start Time | Experimental: To be done | |


## Diagnostics

Additional sensors mainly for system health diagnostics like temperatures, health metrics, or fault codes.