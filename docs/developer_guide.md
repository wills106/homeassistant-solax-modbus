# Developer guide

This section describes some internal mechanisms of this integration. It is mainly meant for plugin developers, but can only be used by the integration core developers.

Following sections will appear some day:
# attributes for entities

Entities are declared in the plugin_xxx.py files.
Each type of entity may support different attributes.

## common attributes for all entities

## attributes for sensor entities:

## attributes for number entities:

## attributes for select entities:

## attributes for button entities:


# autorepeat mechanism for buttons

A button can have the attribute autorepeat, which specifies a duration over which the button press will be repeated automatically.
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
