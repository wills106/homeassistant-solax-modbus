# Sofar Reflux Control

Controls, whether power can be feed-in to the grid. Optionally can limit the maximum amount of power the flows from your system to the grid.

Set "Reflux: Control" to one of the following values:

- **Disabled**: Reflux control is disabled. Excess power will always be fed-in to the grid.
- **Enabled**: Reflux control is enabled. No excess power will be fed-in to the grid. The MPPTs will be steered to reduce power generation to avoid any power from being fed-in to the grid
- **Enabled - Set Value**: Reflux control is enabled. Using the value of "Reflux: Maximum Power" you can specify the maximum amount of power that will be fed-in to the grid. If the power to be fed-in exceeds this limit, MPPTs will be steered to reduce further power generation.

After changing either "Reflux Control" and/or "Reflux: Maximum Power" press "Reflux: Update" to commit the values to the inverter.