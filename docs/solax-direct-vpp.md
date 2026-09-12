# SolaX direct VPP controls

The existing `(direct)` entities send one-shot VPP commands. They do not start
the integration's autorepeat controller.

## Operation

1. Unlock the inverter as required by its firmware.
2. Set the direct parameters for the desired mode.
3. Select the direct VPP mode to send the complete command.

While that mode is active, changing a relevant parameter immediately sends the
complete command with the new value. There is no additional Apply button and
no need to reselect the mode for each change. The selected **Set/Update** value
is preserved; the inverter interprets target and duration updates according to
that setting. In particular, **Set** may restart a target or duration.

Before applying a parameter change, the integration reads the active mode from
input register `0x0100`. It does not use the last selected mode as proof that VPP
is still running. If VPP has ended, or the parameter belongs to another mode,
the value is saved for the next explicit activation without sending a command.
The mode 8 duration and mode 9 target SOC are stored separately even though
they share register `0x00A6`.

Parameters are persisted using the integration's existing local-data storage.
Restarting Home Assistant does not start or repeat a VPP command.

## First use after upgrading / externally activated VPP

Earlier versions did not persist the direct parameters. If VPP is already
running but the integration does not know all its parameters, an individual
edit is rejected with an explanatory error. This prevents unknown companion
values from being replaced with defaults. Configure the intended parameters
with VPP disabled, then select the mode once to establish the complete command.
Subsequent edits are applied immediately, including after a normal restart.

An explicit mode selection uses the existing entity defaults for unspecified
parameters. Mode 3 has no default target SOC: set it before enabling that mode.
Disabling VPP does not require target parameters or a successful mode read.
Read or write failures remain errors; rejected values are not saved as accepted.

## Register blocks

[SolaX's VPP documentation](https://kb.solaxpower.com/fr/solution/detail/828080819a0a88fa019a0a941afc01e7)
requires complete FC16 commands for modes 1–7, including zeroes for unused fields:

- Modes 1–3: `0x007C–0x0088` (13 registers).
- Modes 4–7: `0x007C–0x008A` (15 registers).
- Modes 8/9 use `0x00A0–0x00A7` (8 registers).

The integration retains SolaX's low-word-first 32-bit encoding and the signed
power values. Target energy and PV power limit are unsigned 32-bit values.
These changes do not add support for new inverter models or firmware versions.
