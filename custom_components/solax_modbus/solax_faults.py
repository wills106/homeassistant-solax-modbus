"""Documented SolaX Hybrid fault bits, scoped by generation, phase and protocol.

G3: Modbus TCP/RTU V3.29, Inverter Error Code (X1/X3) and Manager Err Code.
G4 legacy: Modbus TCP/RTU V3.34, Tables 2-3, 2-4 and 2-5.
G4 ESS: ESS Modbus V001.02, Appendix C (explicitly an X3-Hybrid G4 example).
See docs/solax-entity-description.md for source links and supported models.
Reserved bits are deliberately absent: a set reserved/unknown bit is still a fault.
"""

# Only bits with the same meaning in all four legacy inverter tables are shared.
_COMMON_INVERTER_FAULTS = {
    1: "Grid Lost Fault",
    2: "Grid Volt Fault",
    3: "Grid Freq Fault",
    4: "PV Volt Fault",
    5: "Bus Volt Fault",
    6: "Bat Volt Fault",
    7: "AC10mins Volt Fault",
    8: "DCI OCP Fault",
    10: "SW OCP Fault",
    11: "RC OCP Fault",
    12: "Isolation Fault",
    13: "Temp Over Fault",
    14: "BatConnDir Fault",
}

_GEN3_INVERTER_FAULTS = {
    **_COMMON_INVERTER_FAULTS,
    0: "Hardware Trip",
    9: "DCV OCP Fault",
    15: "Sample Consistence Fault",
    16: "EPS Overload",
    18: "Input Config Fault",
    24: "Inner Comm Fault",
    25: "Fan Fault",
    26: "HCT AC Device Fault",
    27: "EEPROM Fault",
    28: "Residual Current Device Fault",
    29: "EPS Relay Fault",
    30: "Grid Relay Fault",
}

GEN3_X1_INVERTER_FAULTS = {
    **_GEN3_INVERTER_FAULTS,
    17: "Overload",
    19: "EPS Bat Power Low",
    20: "Hybrid IRelay Fault",
    23: "BMS Lost",
    31: "Other Device Fault",
}

GEN3_X3_INVERTER_FAULTS = {
    **_GEN3_INVERTER_FAULTS,
    17: "EPS OCP Fault",
    19: "Firmware Version Fault",
    20: "EPS Bat Power Low",
    21: "Phase Angle Fault",
    22: "PLL Overtime",
    23: "Parallel Fault",
    31: "Bat Relay Fault",
}

_GEN4_INVERTER_FAULTS = {
    **_COMMON_INVERTER_FAULTS,
    0: "TZ Protect Fault",
    20: "Low Temp Fault",
    21: "Parallel Fault",
    24: "Inner Comm Fault",
}

GEN4_X1_INVERTER_FAULTS = {
    **_GEN4_INVERTER_FAULTS,
    15: "Missed CT Fault",
    16: "Off-grid Overload Fault",
    17: "Overload Fault",
    18: "PV ConnDir Fault",
    19: "Bat Power Low",
    22: "Charger Relay Fault",
    23: "BMS Lost",
    25: "Fan Fault",
    26: "Earth Relay Fault",
    27: "INV EEPROM Fault",
    28: "RCD Fault",
    29: "Off-grid Relay Fault",
    30: "Grid Relay Fault",
    31: "Other Device Fault",
}

GEN4_X3_INVERTER_FAULTS = {
    **_GEN4_INVERTER_FAULTS,
    9: "DCV OCP Fault",
    15: "Off-grid Overload",
    16: "Overload",
    17: "Bat Power Low",
    18: "BMS Lost",
    19: "Fan Fault",
    22: "Hard Limit Fault",
    23: "INV Volt Sample Fault",
    25: "INV EEPROM Fault",
    26: "RCD Fault",
    27: "Grid Relay Fault",
    28: "Off-grid Relay Fault",
    29: "PV ConnDir Fault",
    30: "Charger Relay Fault",
    31: "Earth Relay Fault",
}

GEN4_X3_ESS_INVERTER_FAULTS = {
    **GEN4_X3_INVERTER_FAULTS,
    16: "Arc Fault",
}

GEN3_MANAGER_FAULTS = {
    2: "EEPROM Error",
    3: "DSP Version Fault",
    4: "NTC Sample Invalid",
    8: "Internal Comms Error",
    9: "Meter Fault",
}

GEN4_MANAGER_FAULTS = {
    0: "Power Type Fault",
    1: "Port OC Warning",
    2: "Mgr EEPROM Fault",
    4: "NTC Sample Invalid",
    5: "Bat Temp Low",
    6: "Bat Temp High",
    9: "Meter Fault",
    10: "Bypass Relay Fault",
    11: "Fan 2 Fault",
}

GEN4_X3_ESS_MANAGER_FAULTS = {
    **GEN4_MANAGER_FAULTS,
    3: "DataHub Comms Error",
    7: "DSP Run Boot Fault",
    8: "Arc Self-test Fault",
    11: "Arc Hardware Fault",
    12: "ARM Parallel Comms Fault",
    13: "Fan 1 Fault",
    14: "Fan 2 Fault",
    15: "ComTime0ut20305",
}
