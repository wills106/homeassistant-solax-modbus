# FAQ

## I have a question that is not answered here

Always also check vendor specific FAQ pages:

- [SolaX Power](solax-faq.md)

## Entity I need is not present

Your desired entity is most likely disabled. Example given is for "Config Max Export"

- Go to the SolaX Integration page.
- Find "+xy entities not shown"
- Click those till you find "Config Max Export"
- Then Cog/Gear icon.
- There is an option to enable it and press "UPDATE"

## How to check a version of a python module e.g. pyModbus

- Virtual Machine - Goto the console:

```
   ha > login
   # docker exec -it homeassistant /bin/bash
   pip show pymodbus
```
   
- Docker (Core) - Goto the console:

```
   pip show pymodbus
```

To list all modules:

```
   Replace:
   pip show pymodbus
   With:
   pip list
```