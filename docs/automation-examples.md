# Automation - Hints and Examples

This page will host some example automations and hints related to creating automations.
The authors are not responsible for the correctness of the sample code and the applicability on a particular system
## Hint 1: Be carefull with frequent modifications
Automations may modify certain parameters frequently. According to the Solax documentation, most of the parameters that are modified are written to EEPROM. As you may know, EEPROM life is limited by a number of write cycles which is often no more than 100000 write operations.
So if you want your inverter to survive 10 years, you should not make more than 27 modifications a day. To be on the safe side, I would recommend to use 10 modified parameters a day as a safe value.
It is unclear if modifying a parameter from e.g. 10 to the same value 10 would issue a real EEPROM write. Future versions of our integration could ignore such changes, but currently the code does not compare with previous value.

## Example 1: TBD