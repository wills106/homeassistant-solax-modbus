## Solax Mode 8 Modbus Power Control (autorepeat)

This page describes features that will appear in the near future.
Not to be confused with the remotecontrol_xxx_direct approach.

## Why use Modbus power control?

Normal power controls are rather static and are written to EEPROM, so they are not well suited for use in automations as the automation might change the values too often. 
The Modbus power control commands (remotecontrol_xxx) are not stored in EEPROM and can be called as often as desired. The lifetime of some of these commands is however limited, so they need to be repeated frequently as the house load and PV power may vary quickly. 
An external task or process could interact with the integration every few seconds, but this might cause an unnecessary overhead.
Fortunately, this integration has an autorepeat option that makes these commands as easy to use as the normal power control parameters.

Solax has documented the remotecontrol commands for Gen4 (and higher) in this KB document:  [KB document: SolaX_VPP function Definition of ESS]( https://kb.solaxpower.com/solution/detail/2c9fa4148ecd09eb018edf67a87b01d2)
In this page, we focus on the mode 8 type of remotecontrol. This mode 8 is capable of limiting the PV power, a feature that is interesting in times of negative injection or consumption prices. 


A similar autorepeat mechanism is available for mode 1; see the dedicated wiki page


### Notes:
* For people using external tasks to control the power, the _remotecontrol_xxx_direct_ versions of the entities could be used. This is outside the scope if this wiki page.
* Although the addition of Mode 8 in new firmwares is a big enhancement, we still feel there is a missing mode that focusses on the grid interface and can limit the PV in case of negative prices. Our Mode 8 autorepeat loop tries to emulate this, but can only adjust every polling cycle, a firmware based solution could react faster.
* This mechanism will only work on the most recent firmware versions; previous versions do not support mode 8 or 9. I am running Firmware: DSP v1.52 ARM v1.50 at the time of my testing
* If you use modbus power control autorepeat loops, make sure the polling interval for the fastest scangroup is sufficiently low e.g. 3-5 seconds, otherwise the values are updated too slowly. A too short interval can overload your system or modbus communication bus. Some people can go as low as 1 second, but it is safer to have more margin.


### KNOWN ISSUES: (Work in progress):
* When the battery gets fully charged (or when the specified duration expires), the systems sometimes seems to automatically change to mode 6 (Self consume - Charge an Discharge), this mode does not limit PV anymore and may export power when prices are still negative. Further observation is necassary to understand this.
* The remotecontrol_duration parameter (not to be confused with autorepeat duration) seems to be ignored by the Solax firmware and mode 8 remains active for a longer time. This can be overcome by using an automation that sets the mode 8 to disabled. We are working on an automatic deactivation when the autorepeat_duration expires.
* In case the mode does not terminate, the new modes can be disabled with the Mode 1 Disabled selection followed by a click on the Mode 1 trigger button (this issue should be solved now).
* The inverter may take some time to reduce the PV power, it can take a minute or more before the target is reached.

***
## Solax Gen4 approach for Mode 8
***

The Solax Gen4 inverters and higher use a modbus write_multiple_registers command.
On the Gen4, these actions are not stored in EEPROM, so they can be executed frequently.
The integration hides this complexity and implements one button to trigger a single or repeated update(s). The action behind this button is configurable through following parameter entities:

* **powercontrolmode8_trigger**: trigger button for activating mode 8 loop
* **remotecontrol_power_control_mode**: Select the submode:
    * **Disabled**: changing to Disabled also deactivates the loop mechanism
    * **Mode 8 - PV and Bat control - Duration**: this is the manual fixed mode that uses fixed remeotecontrol_pv_power_limit and fixed remotecontrol_push_mode_8_9 settings. The same behavior can probably be achieved with the _direct version of the entities (without autorepeat loop)
    * **Negative Injection Price**: in this submode, PV will charge the battery and feed the house load, but once the battery is fully charged, PV will be reduced to house load so that no export takes place. The autorepeat mechanism is essential to adapt to the varying PV power or house load. If there is still some remaining export (probably because there is a limit on the possible charging power), reduce the remotecontrol_pv_power_limit parameter. In this submode, remotecontrol_pv_power_limit will be interpreted as maximum battery charge power.
    * **Negative Injection and Consumption Price**: In this submode, PV will be limited to zero and battery will be charged from the grid (house load also from grid)
* **remotecontrol_pv_power_limit**: maximum PV power; is automatically recomputed in the Negative Price submodes. an initial max value is needed however
* **remotecontrol_push_mode_power_8_9**: positive numbers are discharge, negative numbers charge; is automatically computed in the Negative Price submodes
* **remotecontrol_import_limit**: can be used to limit the maximum import from grid. This limmitation is active in all submodes, so make sure to set this parameter to a proper value. Please note that the import limitation will only work as long as the battery is not empty. In regions where the maximum import has a financial impact (e.g. part of Belgium), the autorepeat approach may have an advantage over the _direct alternative.
* **remotecontrol_target_soc_8_9* (not yet used)
* **remotecontrol_duration**: we recommend to keep the default value of 20s
* **remotecontrol_autorepeat_duration**: typically a couple of hours - e..g duration of the negative price
* **remotecontrol_timeout**: can be left 0 or set to a few seconds more than the polling interval; unclear how to use this


With these parameters a power control dashboard card can be created:

<img width="503" height="670" alt="image" src="https://github.com/user-attachments/assets/08555a38-5b42-4155-97c4-7d63b4d3bb9c" />



Modifying these parameters has no direct effect, the autorepeat loop is only activated when the trigger button is pressed.
For deactivating these modes, select "Disabled"; clicking the trigger button again is normally not needed for deactivation of the loop.

The current state of the modbus power control mechanism can be examined with entity `solax_modbus_power_control`. If Mode 8 is active, it will show `Individual Setting - Duration Mode`

## Example automation: Negative injection prices
This sample automation will activate the 'Negative Injection Price' mode when the battery is nearly full. We deliberately do not activate it whenever injection prices are negative, to reduce the inaccuracies of the relatively slow autorepeat loop.
These examples assume you have an integration that provides the current injection and consumption price (in my case dynamic_grid_prices).

### Automation to start negative prices mode:

```
alias: Negative Price - Mode 8
description: ""
triggers:
  - entity_id:
      - sensor.dynamic_grid_prices_injection_price
    below: -0.0021
    trigger: numeric_state
  - trigger: numeric_state
    entity_id:
      - sensor.solax_battery_capacity
    above: 91
  - trigger: time_pattern
    minutes: /15
    seconds: "14"
conditions:
  - condition: numeric_state
    entity_id: sensor.dynamic_grid_prices_injection_price
    below: -0.0021
  - condition: numeric_state
    entity_id: sensor.dynamic_grid_prices_consumption_price
    above: 0
  - condition: numeric_state
    entity_id: sensor.solax_battery_capacity
    above: 91
actions:
  - action: select.select_option
    metadata: {}
    data:
      option: Negative Injection Price
    target:
      entity_id: select.solax_remotecontrol_power_control_mode
  - action: number.set_value
    metadata: {}
    data:
      value: "3594"
    target:
      entity_id: number.solax_remotecontrol_autorepeat_duration
  - action: number.set_value
    metadata: {}
    data:
      value: "20"
    target:
      entity_id:
        - number.solax_remotecontrol_duration
  - action: button.press
    metadata: {}
    data: {}
    target:
      entity_id: button.solax_powercontrolmode8_trigger
mode: single


```

### Automation to stop negative prices mode:

```
alias: Positive Price - Mode 8
description: ""
triggers:
  - entity_id:
      - sensor.dynamic_grid_prices_injection_price
    above: -0.0021
    trigger: numeric_state
  - seconds: "20"
    minutes: /15
    trigger: time_pattern
  - trigger: state
    entity_id:
      - sensor.solax_modbus_power_control
    from: null
    to: Self Consume - C/D Mode
conditions:
  - condition: numeric_state
    entity_id: sensor.dynamic_grid_prices_injection_price
    above: 0
  - condition: or
    conditions:
      - condition: state
        entity_id: sensor.solax_modbus_power_control
        state: Self Consume - C/D Mode
      - condition: state
        entity_id: sensor.solax_modbus_power_control
        state: Individual Setting - Duration Mode
actions:
  - action: select.select_option
    metadata: {}
    data:
      option: Disabled
    target:
      entity_id: select.solax_remotecontrol_power_control_mode
  - action: button.press
    metadata: {}
    data: {}
    target:
      entity_id: button.solax_powercontrolmode8_trigger
mode: single

```

I am using similar automations to discharge the battery to grid when injection price are high (used in summer), and to charge batteries when consumption prices are low (used in winter)
