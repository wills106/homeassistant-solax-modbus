# Solis Remote Dispatch Example Scripts

These examples demonstrate the [remote dispatch workflow](solis-remote-dispatch.md)
using Grid Import mode. The test prepares dispatch, waits 2 seconds, applies the
requested grid power once, then monitors through the expected failsafe expiry.
It does not renew dispatch.

## Before using the examples

- These scripts send real inverter commands. Check firmware support, SOC limits
  and the underlying storage mode before running them.
- Entity IDs below assume the integration uses the `solis` prefix. Replace the
  number, select, button and sensor entity IDs with those from your installation.
- Enable the diagnostic readback sensors used by the monitor. Staged controls are
  requests, not confirmation of the mode or power accepted by the inverter.
- Keep other dispatch automations and tests from changing staged values or
  renewing dispatch during this test. The monitor only observes; it does not
  prevent other scripts from controlling the inverter.
- A grid target of `0` balances net grid flow; it does not request a fixed battery
  charge rate. Positive values target grid import and negative values target
  export, subject to inverter and battery limits.
- When dispatch expires, the inverter resumes its underlying storage-mode logic.
  To stop early, use the integration's **Disable Remote Dispatch** button.

## Installation

The YAML below uses the keyed format for `scripts.yaml`. If your configuration
already includes that file with `script: !include scripts.yaml`, merge these
entries into it, then reload scripts. For an existing script include or package,
use its corresponding structure instead.

Alternatively, create three scripts in the Home Assistant UI. In each script's
YAML editor, paste the contents beneath its top-level script key, without that
key, and ensure the resulting script entity IDs match the calls below.

## Example scripts

{% raw %}
```yaml
solis_remote_dispatch_grid_test:
  alias: "[Solis] Remote Dispatch - Grid Balance test"
  description: "Request the specified net grid power with the specified failsafe, prepare the common block, apply once, then monitor until one minute after the expected expiry."
  mode: single
  fields:
    grid_power:
      name: Grid power
      description: "Net grid power setpoint in watts. Zero requests grid balance."
      default: 0
      selector:
        number:
          min: -24000
          max: 24000
          step: 100
          unit_of_measurement: W
          mode: box
    failsafe_interval:
      name: Failsafe interval
      description: "Inverter-side dispatch expiry in minutes."
      default: 2
      selector:
        number:
          min: 1
          max: 1440
          step: 1
          unit_of_measurement: min
          mode: box
  sequence:
    - action: system_log.write
      data:
        level: warning
        message: "[Solis] Remote Dispatch - Grid Balance test ({{ grid_power | default(0) }}W, failsafe {{ failsafe_interval | default(2) }}min)"

    - action: script.solis_prepare_remote_dispatch_grid
      data:
        grid_power: "{{ grid_power | default(0) }}"
        failsafe_interval: "{{ failsafe_interval | default(2) }}"

    - delay: "00:00:02"

    - action: button.press
      target:
        entity_id: button.solis_apply_remote_dispatch

    - action: script.turn_on
      target:
        entity_id: script.solis_remote_dispatch_monitor
      data:
        variables:
          monitoring_interval: "{{ (failsafe_interval | default(2)) + 1 }}"


solis_prepare_remote_dispatch_grid:
  alias: "[Solis] Remote Dispatch - Prepare Grid Balance"
  description: "Stage the specified net grid power (zero by default) and prepare dispatch with the specified failsafe interval. Does not send Apply."
  mode: single
  fields:
    grid_power:
      name: Grid power
      description: "Net grid power setpoint in watts. Zero requests grid balance."
      default: 0
      selector:
        number:
          min: -24000
          max: 24000
          step: 100
          unit_of_measurement: W
          mode: box
    failsafe_interval:
      name: Failsafe interval
      description: "Inverter-side dispatch expiry in minutes."
      default: 6
      selector:
        number:
          min: 1
          max: 1440
          step: 1
          unit_of_measurement: min
          mode: box
  sequence:
    - action: system_log.write
      data:
        level: warning
        message: "[Solis] Remote Dispatch - Prepare Grid Balance"

    - action: number.set_value
      target:
        entity_id: number.solis_dispatch_power
      data:
        value: "{{ grid_power | default(0) }}"

    - action: number.set_value
      target:
        entity_id: number.solis_dispatch_soc_minimum
      data:
        value: 0

    - action: number.set_value
      target:
        entity_id: number.solis_dispatch_soc_maximum
      data:
        value: 100

    - action: select.select_option
      target:
        entity_id: select.solis_dispatch_control_mode
      data:
        option: "Grid Import"

    - action: number.set_value
      target:
        entity_id: number.solis_dispatch_failsafe_interval
      data:
        value: "{{ failsafe_interval | default(6) }}"

    - action: button.press
      target:
        entity_id: button.solis_prepare_remote_dispatch


solis_remote_dispatch_monitor:
  alias: "[Solis] Remote Dispatch - Monitor"
  description: "Observe dispatch and battery power every 30 seconds for the monitoring interval, with extra samples at five and ten seconds after start and into the final minute, without renewing or stopping dispatch."
  mode: restart
  fields:
    monitoring_interval:
      name: Monitoring interval
      description: "Total monitoring duration in minutes."
      default: 3
      selector:
        number:
          min: 1
          max: 1441
          step: 1
          unit_of_measurement: min
          mode: box
  sequence:
    - variables:
        monitor_offsets: >-
          {% set monitoring_seconds = (monitoring_interval | default(3)) * 60 %}
          {{ ((range(0, monitoring_seconds + 1, 30) | list)
              + [5, 10, monitoring_seconds - 55, monitoring_seconds - 50]) | unique | sort | list }}

    - action: system_log.write
      data:
        level: warning
        message: "[Solis] Remote Dispatch - Monitor for {{ monitoring_interval | default(3) }}min"

    - repeat:
        for_each: "{{ monitor_offsets }}"
        sequence:
          - delay:
              seconds: "{{ repeat.item - (monitor_offsets[repeat.index - 2] if repeat.index > 1 else 0) }}"

          - action: system_log.write
            data:
              level: warning
              message: >-
                [Solis] Remote Dispatch - Monitor +{{ repeat.item }}s:
                battery={{ states('sensor.solis_battery_power') }}W,
                grid={{ states('sensor.solis_meter_active_power') }}W,
                SOC={{ states('sensor.solis_battery_soc') }}%,
                failsavel={{ states('sensor.solis_dispatch_failsafe_interval') }}min,
                status={{ states('sensor.solis_remote_dispatch_running_status') }},
                mode={{ states('sensor.solis_dispatch_control_mode') }},
                power={{ states('sensor.solis_dispatch_power') }}.
```
{% endraw %}

## Running a test

Run `script.solis_remote_dispatch_grid_test` with `grid_power: 0` and
`failsafe_interval: 2` for a short grid-balance test. These are its defaults.
The test passes the interval explicitly to preparation, overriding the preparation
script's standalone default of 6 minutes. It starts the monitor asynchronously
for 3 minutes, so the test script finishing does not mean dispatch has expired.

Check that readbacks settle to mode `3`, running status `2`, and the requested
power, then compare actual grid and battery power. After renewal stops, look for
dispatch expiry and the return to normal operation; polling can delay the visible
readback change.

`script.solis_prepare_remote_dispatch_grid` can also be called separately with
`grid_power` and `failsafe_interval`. It performs preparation only: its caller
must wait before Apply and handle any subsequent renewals.

`script.solis_remote_dispatch_monitor` is read-only apart from log messages.
Calling it again restarts monitoring. It logs every 30 seconds, with extra samples
at 5 and 10 seconds after starting and 55 and 50 seconds before the end.
