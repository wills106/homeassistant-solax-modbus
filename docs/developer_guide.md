# Developer guide

This section describes some internal mechanisms of this integration. It is mainly meant for plugin developers, but can also be used by the integration core developers.

Following sections will appear some day:
## Attributes for entities

Entities are declared in the `plugin_xxx.py` files.
Each type of entity may support different attributes.
The entity types are also briefly documented in the `const.py` file.

### Common attributes for all entities

Most of the attributes are optional or have a meaningfull default value

 * _allowedtypes_: int = 0  # overload with ALLDEFAULT from plugin
 * _register_
 * _blacklist_: # None or list of serial number prefixes like ["XRE",] for which the entity will not appear

To be completed

### Attributes for sensor entities:

To be documented:

* _scale_
* _read_scale_exceptions_
* _read_scale_
* _rounding_
* _register_type_: REGISTER_HOLDING, REGISTER_INPUT or REG_DATA
* _unit_: int = None  #  optional for WRITE_DATA_LOCAL e.g REGISTER_U16, REGISTER_S32 ...
* _internal_
* _newblock_: the system automatically builds blocks of registers that will be polled together, a newblock attribute indicates that a newblock should start at this address. Do not use too many newblock statements as the polling cycle may contain too many operations.
* _value_function_
* _sleepmode_: either SLEEPMODE_LAST (default), SLEEPMODE_ZERO or SLEEPMODE_NONE 
* _ignore_readerror_
* _value_series_
* _min_value_
* _max_value_

### Attributes for number entities:

To be documented:

* _read_scale_exceptions_: list = None
* _read_scale_: float = 1
* _fmt_: str = None
* _scale_: float = 1
* _state_: str = None
* _max_exception_s: list = None  #  None or list with structue [ ('U50EC' , 40,) ]
* _min_exceptions_minus_: list = None  # same structure as max_exceptions, values are applied with a minus
* _write_method_: int = WRITE_SINGLE_MODBUS  # WRITE_SINGLE_MOBUS or WRITE_MULTI_MODBUS or WRITE_DATA_LOCAL
* _initvalue_: int = None  # initial default value for WRITE_DATA_LOCAL entities
* _unit_: int = None  #  optional for WRITE_DATA_LOCAL e.g REGISTER_U16, REGISTER_S32 ...
* _prevent_update_: bool = (
        False  # if set to True, value will not be re-read/updated with each polling cycle; only when read value changes

### Attributes for select entities:

To be documented:
    
* _option_dict_: dict = None
* _reverse_option_dict_: dict = None  # autocomputed - do not specify
* _write_method_: int = WRITE_SINGLE_MODBUS  # WRITE_SINGLE_MOBUS or WRITE_MULTI_MODBUS or WRITE_DATA_LOCAL
* _initvalue_: int = None  # initial default value for WRITE_DATA_LOCAL entities

### Attributes for button entities:

To be documented:

* _command_
* _write_method_
* _autorepeat_ : see separate documentation on autorepeat buttons

### Attributs for switch entities:

To be documented:

* _register_bit_: int = None
* _write_method_: int = `WRITE_SINGLE_MODBUS`  # `WRITE_SINGLE_MOBUS` or `WRITE_MULTI_MODBUS` or `WRITE_DATA_LOCAL`
* _sensor_key_: str = None  # The associated sensor key
* _initvalue_: int = None  # initial default value for WRITE_DATA_LOCAL entities


## Local Data Entities
The integration can create entities that have no corresponding modbus register. These entities can be used as parameter for automations or as parameter of an autorepeat loop. These local data entities have the attribute `write_method=WRITE_LOCAL_DATA`.
Their initial value is determined by attribute `initval`.
Local variables are made persistent across reboots as they are stored in the `config/SolaX_data.json` file periodically after a change of data.
Documentation to be completed ...

## Scan groups for differentiated polling
Some inverter plugins use different scan groups (to differentiate between slowly changing sensor entities and entities that are updated frequently?)
This is determined by the presence of attribute scan_group on sensor entities.
The scan_group attribute can take following values: SCAN_GROUP_DEFAULT, SCAN_GROUP_MEDIUM,  SCAN_GROUP_FAST or SCAN_GROUP_AUTO
If no scan_group is specified, the plugin-specific default will be used. There can be a different default for holding and input registers. See the plugin declaration at the end of your plugin. Example: 
```
plugin_instance = solax_plugin(
    plugin_name="SolaX",
    plugin_manufacturer="SolaX Power",
    SENSOR_TYPES=SENSOR_TYPES_MAIN,
    NUMBER_TYPES=NUMBER_TYPES,
    BUTTON_TYPES=BUTTON_TYPES,
    SELECT_TYPES=SELECT_TYPES,
    SWITCH_TYPES=[],
    block_size=100,
    order16=Endian.BIG,
    order32=Endian.LITTLE,
    auto_block_ignore_readerror=True,
    default_holding_scangroup=SCAN_GROUP_DEFAULT, 
    default_input_scangroup=SCAN_GROUP_AUTO,
    auto_default_scangroup=SCAN_GROUP_FAST,
    auto_slow_scangroup=SCAN_GROUP_MEDIUM,
)
``` 
The actual polling speed for each group is determined during initial or subsequent configuration of the intergration (config_flow).
If the 3 polling group times are set to the same value, the system will act as if there is only one scangroup (they are merged together by interval time)

If SCAN_GROUP_AUTO is chosen for `default_input_scangroup` or `default_holding_scangroup`, entities without a `scan_group` declararation will get the value specified in `plugin.auto_slow_scangroup` if their native unit is slowly changing like temperatures or kWh .., otherwise the value specified in `plugin.auto_default_scangroup`


## Autorepeat mechanism for buttons

A button can have the attribute autorepeat, an attribute that specifies the entity_key of the entity that holds the duration over which the button press will be repeated automatically.
If a button has the attribute **autorepeat**, the button declaration must also have a `value_function` attribute. The specified value function will be called for each autorepeat loop interation.
The meaning of the parameters of a button autorepeat value_function is:

- initval: either `BUTTONREPEAT_FIRST`, `BUTTONREPEAT_LOOP`, `BUTTONREPEAT_POST`
    - `BUTTONREPEAT_FIRST` indicates it is the first call, usually a manual button press
    - `BUTTONREPEAT_LOOP` indicates subsequent autorepeated calls
    - `BUTTONREPEAT_POST` is called after the loop is finished 
- descr: the entity description object of the button
- datadict: the dictionary with all the known entity values
  
In its current form, the function should return a dictionary with following structure: 
`{'action': ... , 'register': ..., 'data': ...}` where


- `action`: the modbus type of write to be executed: currently only MODBUS_WRITE_MULTI is suppored, but the other writes can be easily added later.
- `register` (optional): if not specified, the register address for the autorepeat button will be used
- `data`: a list of tuples `[ (entity_key, value,), ....]` that represents the payload of a write_multiple command that starts at the modbus register addres. Instead of the entity_key_name, a register type can also be specified like `REGISTER_U16`. The payload should not contain the button's entity itself, just the data that needs to be added in the write_multiple scenario. In the future, the `data` structure may be modified to allow other types of writes.
  
The system will automatically convert the data to the modbus low level format, and compute the length of the write_multiple payload to be written to modbus.

The autorepeat value_function is called once for every polling loop, so it is up to the value function to reduce the number of interactions if desired. Currently, the value_function cannot pass data to the next polling cycle's `value_function`'s call. This could be enhanced as using global variables is not considered a best practice (may fail in case of multiple inverters/hubs). Storing this data in the descr._hub object may be better, but it is still not very transparent. Storing data in the `datadict` dictionary may work in future versions, please use a name that cannot conflict with other entities.
____
