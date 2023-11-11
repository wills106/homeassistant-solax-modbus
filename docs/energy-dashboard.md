# Home Assistant "Energy Dashboard"

Energy Dashboard isn't actually live. It lags behind by an hour.

![Energy dashboard config](images/dashboard-energy-config.png)

## Entities

### Electricity Grid

- SolaX Gen2
  - Grid consumption - You need to enable "Grid Import Total"
  - Return to grid - You need to enable "Grid Export Total"
- SolaX Gen 3 & Gen4
  - Grid consumption - sensor.solax_today_s_import_energy
  - Return to grid - sensor.solax_today_s_export_energy

### Solar Panels

- SolaX Gen2 - 4
  - Solar production - sensor.solax_today_s_solar_energy

### Home Battery Storage

- SolaX Gen2
  - Energy going to the battery (kWh) - You need to enable "Battery Input Energy Total"
  - Energy coming out of the battery (kWh) - You need to enable "Battery Output Energy Total"
- SolaX Gen3 & Gen4
  - Energy going to the battery (kWh) - sensor.solax_battery_input_energy_today
  - Energy coming out of the battery (kWh) - sensor.solax_battery_output_energy_today

## [Power Distribution Card](https://github.com/JonahKr/power-distribution-card)

Real Time Visualization of Energy flows

![Power Distribution Card](images/cards-power-distribution-card.png)

```
type: custom:power-distribution-card
title: Power Flow
entities:
  - decimals: '2'
    display_abs: true
    name: Grid
    unit_of_display: W
    icon: mdi:transmission-tower
    entity: sensor.solax_measured_power
    preset: grid
    icon_color:
      bigger: ''
      equal: ''
      smaller: ''
    invert_value: true
    threshold: ''
    secondary_info_entity: ''
  - decimals: 2
    display_abs: true
    name: House
    unit_of_display: W
    invert_value: true
    consumer: true
    icon: mdi:home-assistant
    entity: sensor.solax_house_load
    preset: home
    threshold: ''
    icon_color:
      bigger: ''
      equal: ''
      smaller: ''
  - decimals: 2
    display_abs: true
    name: Solar
    unit_of_display: W
    icon: mdi:solar-power
    producer: true
    entity: sensor.solax_pv_power_total
    preset: solar
    threshold: ''
    icon_color:
      bigger: ''
      equal: ''
      smaller: ''
  - decimals: 2
    display_abs: true
    name: battery
    unit_of_display: W
    consumer: true
    icon: mdi:battery
    producer: true
    entity: sensor.solax_battery_power_charge
    preset: battery
    threshold: ''
    icon_color:
      bigger: ''
      equal: ''
      smaller: ''
    secondary_info_entity: sensor.solax_battery_capacity
    invert_value: true
    secondary_info_attribute: ''
    battery_percentage_entity: sensor.solax_battery_capacity
center:
  type: card
  content:
    type: glance
    entities:
      - entity: sensor.octopus_agile_current_rate
        name: Electric Cost
    show_icon: false
animation: flash
```

## [Power Flow Card Plus](https://github.com/flixlix/power-flow-card-plus)

Another approach, uses the same visual style as Homeassistant energy dashboard

![Power Flow Card Plus](images/cards-power-flow-card-plus.png)

```
type: custom:power-flow-card-plus
entities:
  battery:
    entity: sensor.solax_battery_power_charge
    state_of_charge: sensor.solax_battery_capacity
    invert_state: true
  grid:
    entity:
      consumption: sensor.solax_grid_import
      production: sensor.solax_grid_export
    name: EGD
  solar:
    entity: sensor.solax_pv_power_total
    display_zero_state: true
  home:
    entity: sensor.solax_house_load
clickable_entities: true
display_zero_lines:
  mode: show
  transparency: 50
  grey_color:
    - 189
    - 189
    - 189
use_new_flow_rate_model: true
w_decimals: 0
kw_decimals: 1
min_flow_rate: 0.75
max_flow_rate: 6
max_expected_power: 2000
min_expected_power: 0.01
watt_threshold: 100
transparency_zero_lines: 0
```