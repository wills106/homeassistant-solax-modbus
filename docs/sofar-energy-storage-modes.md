# Sofar Energy Storage Mode

WARNING: most of the writeable parameters are written to EEPROM of the inverter after each modification. EEPROM has a limited (typically 100000) number of write cycles, so be careful that your automations do not modify these parameters too frequently.

The modes are controlled through "Energy Storage Mode", where you can choose one of the following modes by simply selecting one of these values:

- Self Use
- Time of Use
- Timing Mode
- Passive Mode
- Peak Cut Mode
- Off-Grid Mode


## Self Use

This is the default mode and most suitable for typical day by day operation and is designed to optimize your own consumption of your home. In this mode the inverter will automatically charge and discharge the battery according to the following rules:
- If PV generation equals the load consumption (ΔP < 100 W), the inverter won't charge or discharge the battery.
- If the battery is full or at maximum charging power, the excess power will be exported to the grid.
- If the PV generation is less than the load consumption, it will discharge the battery to supply power to the load.
- If PV generation plus Battery discharge power is less than the load, the inverter will import power from the grid.

In this mode priorities are as followed:
- Power supply
  1. PV
  2. Battery
  3. Grid
- Power consumption
  1. Loads
  2. Battery
  3. Grid

So in short: If you have no special needs and just would like the inverter to control the power consumption, this is your standard mode of operation.


## Time of Use

With the Time-of-Use mode, the inverter can be set to charge the battery in defined intervals of time, date or weekday, depending on the State of Charge of the battery. Up to 4 rules (rule 0, 1, 2 and 3) can be set. If more than one rule is valid for any given time, the rule with the lower number is active. Each rule can be enabled or disabled.

Instead of using the "Time of Use" mode, which allows a limited automation within the inverter you might prefer to use Home Assistant to automate this to you liking. Please check "Passive" mode below how to control the inverter's power flows in detail.

_TBD: Describe how to use Time of Use with the Integration_


## Timing Mode

With the Timing Mode you can define fixed times of the day to charge or discharge the battery with a certain power. Up to 4 rules (rule 0, 1, 2 and 3) can be set. If more than one rule is valid for any given time, the rule with the lower number is active. Each rule can be enabled or disabled, also charging and discharging period for a rule can be enabled separately.

Instead of using "Timing Mode", which allows a limited automation within the inverter you might prefer to use Home Assistant to automate this as desired. Please check "Passive" mode below how to control the inverter's power flows in detail.

_TBD: Describe how to use Timing Mode with the Integration_


## Passive Mode

The passive mode is designed for controlling the inverter with external energy management systems and allows fine control over its operations. So as you are using Home Assistant, this might be the most interesting mode for you besides the default "Self Use" mode.

When the inverter is in "Passive Mode" it can be controlled through:

- **Passive: Desired Grid Power**: _Number in Watt_. Set the desired power that is taken from the Grid. The system will try to achieve this level within the boundaries of the current consumption, the current production, and the boundaries set by the battery parameters below. Positive values indicate power flow from grid to the system (grid consumption). Negative values indicate power flow from system to the grid (feed-in). Note that after changing the value in this field you have two minutes to commit the new value to the system using the button below. After two minutes the value will be restored to the value that's stored in the system.

- **Passive: Maximum Battery Power**: _Number in Watt_. Limit the maximum battery power. Must be greater than or equal to "Passive Minimum Battery Power". Positive values indicate charging, negative values indicate discharging. Note that after changing the value in this field you have two minutes to commit the new value to the system using the button below. After two minutes the value will be restored to the value that's stored in the system.

- **Passive: Minimum Battery Power**: _Number in Watt_. Limit the minimum battery power. Must be less than or equal to "Passive Maximum Battery Power". Positive values indicate charging, negative values indicate discharging. Note that after changing the value in this field you have two minutes to commit the new value to the system using the button below. After two minutes the value will be restored to the value that's stored in the system.

- **Passive: Update Battery Charge/Discharge**: _Button_. After changing "Desired Grid Power", "Maximum Battery Power", or "Minimum Battery Power" this button must be pressed to commit these values to the system. Without pressing this button after changing one or multiple of these values nothing will happen.

Let's have a look at some examples that illustrate how you can use these values to control the energy flow of your inverter:

### Examples

#### Same Operation like "Self Use"

You might rather want to just set the "Self Use" mode, but here is what it would look like it "Passive Mode":

Values:

- Desired Grid Power: 0 W
- Maximum Battery Power: 15,000 W
- Minimum Battery Power: -15,000 W

Result:

System tries to pull no energy from the grid. If that is not possible it discharges the battery. In case there is enough PV generation it charges the battery or feeds-in the excess power to the grid. System operates just like in "Self Use".

#### Limit Battery Charging Power

You want to limit the charging power to 2kWh to allow more power for other consumers, e.g. charging your car. Useful for example, if you have a 3 phased charger, which requires at least 4.3 kW to start charging, however the PV production is not enough to cover battery charging and minimum power to start charging the car.

Values:

- Desired Grid Power: 0 W
- Maximum Battery Power: 2,000 W
- Minimum Battery Power: -15,000 W

Result:

System operates like in "Self Use", however the battery is charged with a maximum of 2 kWh that can be consumed by other power consumers. 

#### Prevent Battery Discharging

You want to charge the battery with the PV generation, but would like to prevent it from discharging. E.g. in the winter you want to enforce a full charge cycle over the course of multiple days with little power generation while avoiding pulling extra power from the grid for charging the battery.

Values:

- Desired Grid Power: 0 W
- Maximum Battery Power: 10,000 W
- Minimum Battery Power: 0 W

Result:

- If enough PV generation, no power will be pulled from the grid.
- If PV generation is larger than consumption, battery will be charged with up to 10 kW. If your battery cannot be charged with 10 kW it will automatically be charged with the maximum amount of power the battery can handle (BTS-5K: 2.5 kWh per module). Excess power will be fed-in to the grid.
- If PV generation is less than consumption, power will be pulled from the grid. Battery will not be discharged.

#### Force Battery Charging

You want to load the battery with a at least 3.5 kWh, but a maximum of 5 kWh.

Values:

- Desired Grid Power: 0 W
- Maximum Battery Power: 5,000 W
- Minimum Battery Power: 3,500 W

Result:

"Desired Grid Power" is irrelevant in this scenario. As "Minimum Battery Power" is set to 3.5 kW, the battery will be charged as long as possible with this amount of power. IF PV generation does not deliver enough power, required power will be consumed from the grid. If PV generation produced more excess energy than 3.5 kW the battery will be charged with up to 5kW. Any excess power that exceeds the sum of home consumption and 5 kW will be fed in to the grid.

Note: Battery management will override the minimum battery power of course. So when the battery is nearly full, charging power will still be reduced even below the value of "Minimum Battery Power" and when the battery is full, charging will be stopped.

#### Provide Feed-in Power If Possible

As long as possible you want to prioritize feeding-in at least 1 kW to the grid. Maybe you have the luxury that you get a higher price for feeding in energy than consuming it.

Values:

- Desired Grid Power: -1,000 W
- Maximum Battery Power: 15,000 W
- Minimum Battery Power: 0 W

Result:

- If PV generation is less than the sum of 1 kW and the consumption of all power consumers, the difference will be fed-in to the grid. Battery will not be discharged.
- If PV generation is more than the sum of 1kW and the consumption of all power consumers, 1 kW will be fed-in to the grid. Additional power will be used to charge the battery up to its maximum charging power. If PV generation exceeds the maximum charging power additional excess power will be fed-in to the grid.

**IMPORTANT:** Check your local regulations. Many grid operators do not permit feeding in power from the battery to the grid. If you set minimum battery power to negative values, while setting "Desired Grid Power" and/or "Maximum Battery Power" to negative values, you are potentially feeding in power from the battery. While this is technically possible in "Passive Mode" and actually works it might be prohibited by law.

### Timeout and Timeout Action

When in passive mode the inverter can perform a configurable action after it did not receive any communication for longer than a configurable time. This may not be important for automation, however if set to non-default values, it could lead to unexpected side effects.

- **Passive: Timeout**: _Default: Disabled_. The timeout after which the configured timeout action will be executed. Note that the displayed value in this field does not necessarily reflect the current value that is set in the inverter. See the entity "RO: Passive: Timeout" for checking the current value, which will be displayed in number of seconds, where 0 means 'Disabled'.

- **Passive: Timeout Action**: _Default: Force Standby". The timeout action that will be executed after which the configured timeout has passed. By default "Force Standby" is selected. "Return to Previous Mode" will set the previously selected "Energy Storage Mode", i.e. if the inverter was switched from "Self Use" into "Passive Mode" the inverter will switch back to "Self Use" after not receiving any communication for the configured "Passive: Timeout". Note that the displayed value in this field does not necessarily reflect the current value that is set in the inverter. See the entity "RO: Passive: Timeout Action" for checking the current value.

- **Passive: Update Timeout**: _Button_. After changing "Passive: Timeout" or "Passive: Timeout Action" this button must be pressed to commit the values to the system. Please allow the system several minutes to reflect the changes in the corresponding read-only values.


## Off-Grid (EPS)

With the EPS Mode the inverter can provide energy to the loads without public grid connection or during grid outages. The EPS mode is only available when a battery is connected to the inverter.

- If PV generation equals the load consumption (ΔP < 100 W), the inverter won't charge or discharge the battery.
- If PV generation is larger than the load consumption, the surplus power is stored in the battery. If the battery is full or at maximum charging power, the PV power is reduced by adjusting the MPPT.
- If the PV generation is less than the load consumption, it will discharge the battery to supply power to the load.