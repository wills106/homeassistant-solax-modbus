# Developer guide

This section describes some internal mechanisms of this integration. It is mainly meant for plugin developers, but can only be used by the integration core developers.

Following sections will appear some day:
## Attributes for entities

Entities are declared in the plugin_xxx.py files.
Each type of entity may support different attributes.

### Common attributes for all entities

To be completed

### Attributes for sensor entities:

To be completed

### Attributes for number entities:

To be completed

### Attributes for select entities:

To be completed

### Attributes for button entities:

To be completed


## autorepeat mechanism for buttons

A button can have the attribute autorepeat, an attribute that specifies the entity_key of the entity that holds the duration over which the button press will be repeated automatically.
If a button has the autorepeat attribute autorepeat, the button declaration must also have a value_function attribute. The specified value function will be called for each autorepeat loop interation.
The meaning of the parameters of a button value function is:
* initval: either BUTTONREPEAT_FIRST, BUTTONREPEAT_LOOP, BUTTONREPEAT_POST
  * BUTTONREPEAT_FIRST indicates it is the first call, usually a manual button press
  * BUTTONREPEAT_LOOP indicates subsequent autorepeated calls
  * BUTTONREPEAT_POST is called after the loop is finished 
* descr: the entity description object of the button
* datadict: the dictionary with all the known entity values
  
In its current form, the function should return a list that represents the payload of a write_multiple command that starts at the modbus register address of the button entity.
In the future, the return value may be extended to allow other types of writes (to different addresses).
The write_multiple list is a list of tuples [ (entity key name, entity value,), ... ]. Instead of the entity_key_name, a register type can also be specified like REGISTER_U16.
The system will automatically compute the length of the write_multiple payload to be executed.

The autorepeat value_function is called once for every polling loop, so it is up to the value function to reduce the number of interactions if desired. Currently, the value_function cannot pass data to the next polling cycle's value_function's call. This could be enhanced as using global variables is not considered a best practice.
