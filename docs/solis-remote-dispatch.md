# Solis Remote Dispatch

Remote dispatch temporarily controls battery or grid power using the inverter's
RAM-only dispatch registers. It provides an inverter-side failsafe: if commands
stop arriving, the inverter returns to its normal storage-mode logic. This workflow
uses the dispatch register block rather than changing persistent export-limit or
storage-mode settings.

These controls are available in the Solis FB00 plugin for hybrid inverters, but
support depends on the inverter and firmware. Entity availability alone does not
confirm that a mode is supported.

## Stage, prepare and apply

The dispatch numbers and selects stage values locally in Home Assistant. Setting
them does not immediately send a command to the inverter.

| Control | Purpose | Sent by |
| --- | --- | --- |
| Dispatch Failsafe Interval | Command lifetime in minutes, 1–1440; default 5 | Prepare Remote Dispatch |
| Dispatch Control Mode | Selects the dispatch mode | Apply Remote Dispatch |
| Dispatch Power | Signed power in watts | Apply Remote Dispatch |
| Dispatch SOC Minimum / Maximum | Battery SOC window for dispatch | Apply Remote Dispatch |
| Dispatch Grid Charging | Allow, Disallow or No instruction; used only in Battery Charge mode | Apply Remote Dispatch |

To start dispatch:

1. Set the failsafe interval, mode, power and SOC limits. For Battery Charge mode,
   also choose the grid-charging instruction.
2. Press **Prepare Remote Dispatch**. This enables the dispatch master and writes
   the selected failsafe interval as one block to registers 44100–44104.
3. Allow the inverter to process preparation before applying the command. A
   **2-second delay** was needed for reliable mode acceptance on the firmware
   described below; this is an observed requirement, not a guaranteed value for
   every inverter. The integration buttons do not insert this delay themselves.
4. Press **Apply Remote Dispatch**. This writes the staged realtime command as one
   block to registers 44105–44112.
5. Check the readback sensors and actual grid/battery power.

Prepare performs a real inverter write and enables the master; it does not send
the staged realtime mode and power. Changing the failsafe number alone does not
change the inverter's interval: press Prepare to send the new value.

## Refresh, expiry and stopping

Press **Apply Remote Dispatch** again before the failsafe interval expires to
refresh the command and restart the countdown. There is no need to set the numbers
again or repeat Prepare for each renewal while dispatch remains correctly
configured. Apply always sends the **currently staged values**, including any
changes made by another automation or manually.

For example, an automation can prepare a 7-minute interval, wait 2 seconds, apply,
and then apply every 5 minutes while its charging condition remains true. Allow
margin for polling, scheduling and communication delays when choosing a refresh
interval.

When the automation stops renewing, dispatch expires and normal inverter operation
resumes. Expiry does not restore an earlier battery SOC or a snapshot of previous
settings. The underlying operating mode, such as Feed-in Priority, determines
behaviour after expiry.

To stop immediately, press **Disable Remote Dispatch**. This clears the dispatch
master and resets the inverter's failsafe interval to 5 minutes. The locally staged
failsafe number can still show your selected value; Prepare sends it again when
starting a new session.

## Modes and power direction

| Value | Selection | Power meaning |
| --- | --- | --- |
| 1 | Battery Hold | Holds battery charging/discharging |
| 2 | Battery Charge | Positive watts charge; negative watts discharge |
| 3 | Grid Import | Positive watts target grid import; negative watts target export |
| 4 | Grid Port Import | Signed power target at the inverter AC/grid port |
| 5 | Self Consumption | Firmware-dependent self-consumption dispatch mode |
| 6 | Feed-in Priority | Firmware-dependent feed-in dispatch mode |

For **Battery Charge**, a value of `200` requests 200 W charging and `-200`
requests 200 W discharging. Home Assistant accepts watts; the integration handles
the register's 10 W scaling.

For **Grid Import**, a target of `0` can be used to balance net grid flow: the
battery absorbs surplus PV and supplies deficits, subject to SOC, battery and
inverter limits. This targets the grid measurement rather than a fixed battery
charging power. It is not a guarantee of zero instantaneous export under all
conditions.

**Dispatch Grid Charging** sets the charging-source instruction in register 44108
only for Battery Charge mode. Other modes send a zero function-switch value.
Disallowing grid charging does not turn a battery-charge command into normal
self-use: if the command prevents battery discharge, the grid can still supply
the household when PV is insufficient.

## Verify what the inverter accepted

The locally staged controls show the requested values. Use the diagnostic
readback sensors to check the inverter's actual registers; most of these sensors
are disabled by default and can be enabled in the device's entity list.

| Readback | Register | Interpretation |
| --- | --- | --- |
| Remote Dispatch Capability | Input 34502 | `43605` / `0xAA55` indicates dispatch capability |
| Remote Dispatch Function Version | Input 34503 | Firmware's dispatch function version |
| Remote Dispatch Running Status | Input 34504 | Observed values: `0` inactive, `2` running |
| Dispatch Master | Holding 44100 | Dispatch master enable |
| Dispatch Failsafe Interval | Holding 44101 | Interval actually stored in the inverter |
| Dispatch Control Mode | Holding 44105 | Mode actually accepted, using the values above |
| Dispatch Power | Holding 44106–44107 | Signed power readback, displayed in watts |
| Dispatch SOC Window Min / Max | Holding 44109 / 44110 | SOC limits read back from the inverter |

The observed running-status values are not a complete status enumeration. A
running status alone does not confirm the requested mode: check the mode readback
and measured power as well. Allow a polling cycle for readbacks to update.

## Firmware observations

The staged Prepare/Apply workflow was tested on a **S5-EH1P5K-L**, with
**HMI 5103 / DSPM 5200** and **Remote Dispatch Function Version 1**:

- Battery Hold, positive/negative Battery Charge power, failsafe expiry and an
  Apply refresh were observed working.
- Grid Import at 0 W worked after allowing 2 seconds between Prepare and Apply.
  Earlier attempts could report running status 2 while the mode remained 1.
- The successful Battery Charge discharge test used **Allow** with negative power.
  A test using Disallow did not discharge. Treat this as a firmware observation,
  rather than a universal requirement for discharge.
- A Self Consumption request left the readback mode at 1. Self Consumption and
  Feed-in Priority dispatch modes have not been validated on this firmware.

Capability and function-version readbacks do not establish that every selectable
mode works. Verify each mode on the inverter and firmware being used.
