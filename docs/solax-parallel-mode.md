# SolaX Parallel Mode (Master-Slave) Configuration

## Overview

This document provides comprehensive guidance for configuring and using SolaX inverters in parallel mode (also called master-slave mode), where multiple inverters work together as a unified system.

## What is Parallel Mode?

Parallel mode allows multiple SolaX inverters to operate as a coordinated system:
- **Master Inverter**: Controls the entire system and communicates with Home Assistant
- **Slave Inverters**: Follow the master's commands and report their status to the master
- **Total System Power**: Combined power from all inverters working together

## Benefits

1. **Scalability**: Increase total system capacity by adding inverters
2. **Efficiency**: Master coordinates optimal power distribution
3. **Reliability**: System continues working if one inverter fails
4. **Unified Control**: Home Assistant sees one integrated system

## Hardware Requirements

### Supported Models
- SolaX GEN4 inverters with parallel mode capability
- Properly configured master-slave communication cables
- Each inverter must have parallel mode enabled in its settings

### Physical Setup
1. **Communication Cables**: Special RS485 cables connecting master to slaves
2. **Grid Connection**: All inverters connected to the same electrical phase distribution
3. **Battery Banks**: Each inverter typically has its own battery bank
4. **PV Arrays**: Each inverter has its own PV input connections

### Modbus Communication Settings

**Baud Rate Configuration** (for RS485/RTU connections):

All inverters in parallel mode **must use the same baud rate**. Check your inverter model:

| Inverter Model | Baud Rate | Production Tested | Notes |
|:--------------|:----------|:-----------------|:------|
| SolaX X3 Hybrid G4 | **115200** | ✅ Yes | Tested in production with Master/Slave and DataHub |
| SolaX Gen4 & Gen5 | 19200 | - | Standard configuration |
| SolaX Gen3 (no built-in Ethernet) | 115200 | - | X1-AC and similar models |
| SolaX X1 Air, Boost, Mini, Smart, X3 MIC/Pro, X3 Mega | 9600 | - | Older models |
| SolaX J1 | 19200 | - | Same as Gen4/Gen5 |

**Recommended Polling Intervals for Parallel Mode:**
- 🎯 **Master Inverter**: 5-10 seconds (5s minimum, 10s recommended for stability)
- 🎯 **Slave Inverters**: 10 seconds (recommended default)
- ⚠️ **Critical**: Faster polling increases likelihood of communication issues
- 📉 **9600 Baud**: Never poll faster than 5 seconds

**Important Configuration Notes:**
- ⚠️ **All inverters must have matching baud rates** - mismatched rates cause communication failures
- 🔧 **Check via LCD**: Verify baud rate in inverter menu (Settings → Advanced Settings → Modbus → Baud Rate)
- 🔌 **RS485 Adapters**: If using RS485-to-Ethernet adapters, ensure adapter baud rate matches inverter settings
- 📊 **DataHub Systems**: For DataHub 1000 connections, 115200 baud has been tested successfully with X3 Hybrid G4

**For TCP/IP Connections** (Home Assistant ↔ Inverter):
- **Home Assistant to Inverter**: TCP/IP connection (PocketWiFi, DataHub, built-in Ethernet)
  - Baud rate not applicable for this connection
  - Port 502 (Modbus TCP standard)
- **⚠️ Important**: Master/Slave inverters still communicate via RS485 Modbus
  - All inverters must be configured to the same baud rate
  - RS485 communication between inverters is independent of TCP/IP
  - **Recommendation**: Use 115200 baud for the entire system if supported
  - **Why Higher is Better**: Reduces bus congestion and improves parallel mode responsiveness

## Modbus Connection Setup

### Connection Options

You have two main approaches for connecting to parallel mode systems:

#### Option 1: Connect to Master Only (Recommended for Remote Control)
- Master reports combined PM (Parallel Mode) data for the entire system
- Master forwards remote control commands to slave inverters
- Single integration instance manages the entire system
- **Required if you want to use remote control features**

#### Option 2: Connect to Each Inverter Individually
- Each inverter can have its own LAN/WAN interface (e.g., separate PocketWiFi dongles)
- Create separate integration instances for each inverter
- Get detailed individual inverter data
- **Note:** Remote control only works through the master inverter connection
- Useful for detailed monitoring and diagnostics

### Configuration Steps

1. **Identify the Master Inverter**:
   - Check the inverter display settings
   - Look for "Parallel Mode" setting showing "Master"

2. **Configure Integration(s)**:

   **⚠️ Important:** Configuration should be performed via the Home Assistant UI (Settings → Devices & Services → Add Integration → SolaX Modbus). The YAML examples below are for illustration purposes only.

   **Option 1: Master Only (for remote control)**
   
   Via Home Assistant UI:
   - Go to Settings → Devices & Services
   - Click "Add Integration"
   - Search for "SolaX Modbus"
   - Enter master inverter IP address (e.g., 192.168.1.100)
   - Select plugin type (e.g., "solax_x1_g4")
   - Complete setup wizard
   
   YAML example (for reference only):
   ```yaml
   solax_modbus:
     - name: "SolaX System"
       host: 192.168.1.100  # Master inverter IP
       port: 502
       modbus_type: "tcp"
       plugin: "solax_x1_g4"
   ```

   **Option 2: Individual Inverters (detailed monitoring)**
   
   Via Home Assistant UI:
   - Repeat the "Add Integration" process for each inverter
   - First: Master inverter (192.168.1.100)
   - Then: Each slave inverter (192.168.1.101, 192.168.1.102, etc.)
   - Use descriptive names (e.g., "SolaX Master", "SolaX Slave 1")
   
   YAML example (for reference only):
   ```yaml
   solax_modbus:
     - name: "SolaX Master"
       host: 192.168.1.100  # Master inverter IP
       port: 502
       modbus_type: "tcp"
       plugin: "solax_x1_g4"
     
     - name: "SolaX Slave 1"
       host: 192.168.1.101  # Slave 1 inverter IP
       port: 502
       modbus_type: "tcp"
       plugin: "solax_x1_g4"
     
     # Add more slaves as needed
   ```
   
   **Important:** When using Option 2, remote control commands should only be sent to the master inverter entities.

3. **Verify Parallel Mode Detection**:
   - After integration loads, check for `parallel_setting` entity
   - Should show "Master" for the connected inverter

## Parallel Mode Sensors

When parallel mode is detected, the integration exposes additional PM (Parallel Mode) sensors:

### Total System Sensors
- `pm_total_pv_power`: Combined PV production from all inverters
- `pm_total_inverter_power`: Combined inverter power output
- `pm_total_house_load`: Total house consumption (with delta correction)
- `pm_battery_power_charge`: Battery charging power from grid across all units
  - ⚠️ **Important**: This represents **grid contribution to battery charging only**
  - Does **NOT include PV contribution** to battery charging
  - Total battery power = `pm_battery_power_charge` + PV contribution to battery
  - Example: 28kW charging with 12kW PV → sensor shows ~28kW (grid only), actual total ~40kW

### Individual Inverter Sensors
- `pm_pv_power_1`, `pm_pv_power_2`: PV power per PV input across all inverters
- `pm_pv_current_1`, `pm_pv_current_2`: PV current per PV input across all inverters 
- `pm_activepower_l1`, `pm_activepower_l2`, `pm_activepower_l3`: Power per phase across all inverters

### Health Monitoring
- `pm_communication_status`: Master-slave communication health
- Individual inverter status indicators

## Remote Control in Parallel Mode

### How It Works
Remote control commands are sent to the master inverter, which:
1. Calculates total system requirements
2. Distributes commands proportionally to slave inverters
3. Monitors and adjusts based on total system feedback

### Automatic Detection
The remote control functions automatically detect parallel mode:
```python
if parallel_setting == "Master":
    # Use PM total values for calculations
    pv_power = datadict.get("pm_total_pv_power", 0)
    house_load = datadict.get("pm_total_house_load", 0)
    # ... control logic uses total system values
```

### Control Modes
All remote control modes work in parallel mode:
- **Power Control**: Direct power control for the entire system
- **Grid Control**: Control total grid import/export
- **Battery Control**: Control total battery charging/discharging
- **Self Use**: Minimize total grid usage
- **Feedin Priority**: Maximize total grid export
- **No Discharge**: Prevent discharge across all batteries

For detailed control mode documentation, see: [solax-remote-control-redesigned.md](solax-remote-control-redesigned.md)

## PM House Load Delta Correction

### The Problem
SolaX inverters underreport inverter power during remote control operations, particularly during battery charging. This causes calculated house load to appear artificially higher.

### The Solution
The integration uses two independent calculation methods:

1. **Inverter Method**: `pm_inverter_power - grid_power`
   - Direct measurement from inverter perspective
   - Can be underreported during remote control

2. **Physics Method**: `pv_power - grid_power - battery_power`
   - Based on energy conservation
   - More accurate during remote control
   - **Note**: Uses `battery_power` which represents grid-to-battery charging only
   - This correctly calculates house load since PV-to-battery is already accounted for in the `pv_power` term

**Why the Physics Method Works:**
The physics method uses `pm_battery_power_charge` (grid-to-battery only), which is correct because:
```
House = PV - Grid - Battery_from_grid
```
PV contribution to battery is implicitly handled since:
- `pv_power` includes all PV production (to house + to battery + to grid)
- `battery_power` only counts grid-to-battery (not PV-to-battery)
- The difference correctly isolates house consumption

### Delta Correction
```python
delta = physics_method - inverter_method

# Only apply if delta < 25% (avoids transition states)
if abs(delta) <= abs(inverter_method) * 0.25:
    corrected_house_load = inverter_method - (delta / 2)
```

This ensures accurate remote control calculations by splitting the difference between the two methods.

## Troubleshooting

### Parallel Mode Not Detected

**Symptoms:**
- No PM sensors appearing
- `parallel_setting` shows "Free" or "Slave"

**Solutions:**
1. Verify master inverter is correctly configured
2. Check RS485 communication cables between inverters
3. Ensure you're connected to the master (not slave) IP address
4. Restart the integration after verifying settings

### Slave Inverter Not Responding

**Symptoms:**
- PM sensors show zero for one or more inverters
- Individual inverter status indicates offline

**Solutions:**
1. Check RS485 cable connections
2. Verify slave inverter parallel mode setting is "Slave"
3. Check master inverter communication status
4. Power cycle the affected slave inverter

### Inaccurate House Load Readings

**Symptoms:**
- House load fluctuates wildly during battery charging
- Total power balance doesn't add up

**Solutions:**
1. Delta correction should automatically handle this
2. Check if `pm_total_house_load` is being used (not individual values)
3. Verify remote control is active when issues occur
4. Review logs for delta correction messages

### Remote Control Not Working

**Symptoms:**
- Commands sent but inverters don't respond
- Only master responds, slaves don't follow

**Solutions:**
1. Verify master is executing remote control commands
2. Check slave communication status
3. Ensure all inverters have remote control enabled
4. Check for error messages in Home Assistant logs

## Export Limits in Parallel Mode

For parallel mode systems, the default export limit may be too low for combined inverter capacity.

**Solution:**
1. Enable the `config_max_export` entity (disabled by default)
2. Set appropriate export limit for your total system capacity
3. May require a Home Assistant restart
4. Verify new limit is reflected in remote control bounds checking

## Best Practices

### Monitoring
1. **Regular Checks**: Monitor PM sensor values for consistency
2. **Communication Health**: Watch PM communication status sensors
3. **Individual Status**: Check each inverter's operational status
4. **Power Balance**: Verify total power adds up correctly

### Remote Control
1. **Start Small**: Test with low power values first
2. **Monitor Response**: Watch all inverters respond to commands
3. **Check Limits**: Ensure bounds checking uses total system capacity
4. **Gradual Changes**: Avoid rapid power target changes

### Maintenance
1. **Firmware Updates**: Keep all inverters on same firmware version
2. **Cable Inspection**: Regularly check RS485 cable connections
3. **Configuration Backup**: Save parallel mode settings
4. **Log Review**: Periodically check for communication errors

## Technical Details

### Communication Protocol
- Master uses Modbus TCP/RTU to communicate with Home Assistant
- Master uses proprietary RS485 protocol to communicate with slaves
- Slaves report status to master at regular intervals
- Master aggregates slave data before reporting to Home Assistant

### Data Aggregation
The master inverter combines data from all inverters:
- **Summation**: Power values (PV, inverter, battery)
- **Status**: Overall system health and individual inverter status
- **Coordination**: Distributes commands proportionally

### Update Frequency
- Master polls slaves at ~1-5 second intervals
- Master reports to Home Assistant at configured scan interval
- Some delay expected between command and all inverters responding

## Advanced Configuration

### Custom PM Sensors
You can create additional template sensors based on PM data:

```yaml
sensor:
  - platform: template
    sensors:
      pm_average_pv_per_inverter:
        value_template: "{{ states('sensor.pm_total_pv_power') | float / 2 }}"
        unit_of_measurement: "W"
      
      pm_system_efficiency:
        value_template: >
          {{ (states('sensor.pm_total_pv_power') | float / 
              (states('sensor.pm_total_inverter_power') | float + 0.01) * 100) | round(1) }}
        unit_of_measurement: "%"
```

### Monitoring Automations
Set up alerts for parallel mode issues:

```yaml
automation:
  - alias: "Alert PM Communication Failure"
    trigger:
      - platform: state
        entity_id: sensor.pm_communication_status
        to: "Error"
        for: "00:05:00"
    action:
      - service: notify.mobile_app
        data:
          message: "Parallel mode communication error detected"
```

## Additional Resources

- **Remote Control Details**: [solax-remote-control-redesigned.md](solax-remote-control-redesigned.md)
- **General FAQ**: [solax-faq.md](solax-faq.md)
- **Developer Guide**: [developer_guide.md](developer_guide.md)

## Community Support

If you encounter issues not covered in this guide:
1. Check Home Assistant logs for error messages
2. Review GitHub issues for similar problems
3. Open a new issue with detailed information:
   - Hardware setup (number of inverters, models)
   - Configuration details
   - Log excerpts showing the issue
   - Screenshots of sensor values

The integration has been tested and validated with parallel mode systems, but configurations can vary. Community feedback helps improve support for all setups.

