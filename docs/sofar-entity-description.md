# Description of Sofar Entities

WARNING: most of the writeable parameters are written to EEPROM of the inverter after each modification. EEPROM has a limited (typically 100000) number of write cycles, so be careful that your automations do not modify these parameters too frequently.

Very likely this document will always be work in progress ;-)

## Controls

Some of the entities cannot be written alone as Sofar requires several registers to be written together at once. A button that commits the values to the inverter is provided in such cases and needs to be pressed after related values are changed.

| Name | Description | Commit Button, if required |
| ---- | ----------- | -------------------------- |
| Energy Storage Mode | Sets the energy storage mode as described. See [Energy Storage Modes](sofar-energy-storage-modes.md) for more information. | |
| Passive Desired Grid Power | Set the desired power that is taken from the Grid. The system will try to achieve this level within the boundaries of the current consumption, the current production, and the boundaries set by the battery parameters below. Positive values indicate power flow from grid to the system (grid consumption). Negative values indicate power flow from system to the grid (feed-in). See [Energy Storage Modes](sofar-energy-storage-modes.md) for more information.| Passive: Update Battery Charge/Discharge |
| Passive: Maximum Battery Power | Limit the maximum battery power. Must be greater than or equal to "Passive Minimum Battery Power". Positive values indicate charging, negative values indicate discharging. See [Energy Storage Modes](sofar-energy-storage-modes.md) for more information.| Passive: Update Battery Charge/Discharge |
| Passive: Minimum Battery Power | Limit the minimum battery power. Must be less than or equal to "Passive Maximum Battery Power". Positive values indicate charging, negative values indicate discharging. See [Energy Storage Modes](sofar-energy-storage-modes.md) for more information.| Passive: Update Battery Charge/Discharge |
| Passive: Timeout | The timeout after which the configured timeout action will be executed. See [Energy Storage Modes](sofar-energy-storage-modes.md) for more information.| Passive: Update Timeout |
| Passive: Timeout Action | The timeout action that will be executed after which the configured timeout has passed. By default "Force Standby" is selected. "Return to Previous Mode" will set the previously selected "Energy Storage Mode", i.e. if the inverter was switched from "Self Use" into "Passive Mode" the inverter will switch back to "Self Use" after not receiving any communication for the configured "Passive: Timeout". See [Energy Storage Modes](sofar-energy-storage-modes.md) for more information.| Passive: Update Timeout |
| FeedIn: Limitation Mode | Control whether and how is allowed to feed-in to the grid. See [Feed-In Limitation](sofar-feedin-limitation.md) for more information. | FeedIn: Update |
| FeedIn: Maximum Power | The maximum amount of power in Watts that is allowed to be fed-in to your grid from your system. See [Feed-In Limitation](sofar-feedin-limitation.md) for more information. | FeedIn: Update |
| Remote Control| Enable/Disable remote control to your inverter. |  |
| Update System Time | Updates the system time of the inverter to the current time of the Home Assistant system. To check whether the write action was successful check the value of "Update System Time Operation Result". Note that while a logger is connected to the USB port and the logger has access to the public internet, the inverter will automatically regularly fetch the time from the Sofar servers. However you might have chosen to disallow the communication to the Sofar servers, or you do not have a logger installed on the system. In this case you can achieve a time synchronisation by regularly pressing this button through an automation. Do not hit this button too often as values will be written to the EEPROM.| |


## Sensors

Sensors should be self-explanatory and should not require additional documentation.


## Diagnostics

Additional sensors mainly for system health diagnostics like temperatures, health metrics, or fault codes.